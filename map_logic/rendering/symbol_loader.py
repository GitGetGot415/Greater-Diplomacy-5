import pygame
import os
import re
import json
import numpy as np
import data.constants as c

SYMBOLS = {}
COLORED_SYMBOLS = {}

#: Alternate unit-art sets, keyed by style name (e.g. "hanskolmer") -> {unit
#: name key -> [variant, ...]}. Populated from <style folder>/unit_art.json,
#: which maps the same kind of name keys assets/images files are named after
#: (an exact tier like "Medium Tank III", an era range like "Infantry
#: 1900-1935", or a bare family like "Artillery") to one or more variants of
#: that art. Each variant is {"countries": frozenset|None, "surface": Surface,
#: "filename": str} -- `countries` is None for art that applies to whoever
#: asks (the manifest's plain "key": "file.png" form), or the set of country
#: ids (the same strings keying data/json/countries_data.json, e.g.
#: "Germany") it's restricted to (the "key": {"file":..., "countries":[...]}
#: form). `filename` is that entry's raw "file" value, kept around so
#: get_research_scale can key a *separate* per-style sizing file off it
#: without re-deriving it from the Surface. "classic" is never a key here --
#: it just means "use SYMBOLS", which stays a flat name -> Surface map since
#: it has no country variants or per-style sizing.
STYLE_SYMBOLS = {}

#: Per-style research-screen sizing, keyed by style name -> {"icon_scales":
#: {filename: float}, "button_scale": float, "button_scale_overrides":
#: {name_key: {"width": float, "height": float}}}. Populated from <style
#: folder>/research_scale.json -- kept in its own file rather than folded
#: into unit_art.json so a style's art mapping and its research-screen sizing
#: can be edited/shared independently. See get_research_scale,
#: get_research_button_scale and get_research_button_scale_overrides.
STYLE_RESEARCH_DISPLAY = {}

#: Per-style culture groups, keyed by style name -> {culture name: [country
#: id, ...]}, straight from that style's unit_art.json "_cultures" section.
#: A restricted art entry always names a whole culture (never an individual
#: country), so every member of a group shares identical art -- this lets the
#: Unit Art settings screen offer one tab per culture (e.g. "Germanic")
#: instead of one per country (Germany, German Reich, German Empire, ...).
#: See style_cultures and culture_representative.
STYLE_CULTURES = {}

#: What each (style, country, requested name) resolved to: (source_style,
#: base_name) in whichever of SYMBOLS/STYLE_SYMBOLS[source_style] actually
#: holds the image, or None for "no such icon anywhere". `country` is part of
#: the key because it can change the *outcome*, not just which picture a fixed
#: outcome points to: a name key with only a Germany-scoped variant is simply
#: not present in the style for France, and resolution has to fall through to
#: classic exactly as if the key were missing.
#:
#: The resolution in _resolve_against tries five fallbacks in turn and two of
#: them walk every loaded symbol building a regex per key. The map asks for
#: one symbol per unit box per frame, so at 178 loaded symbols that was
#: 200,000 re.escape calls a second and 40% of a zoomed-out frame -- the whole
#: of the lag when a player zoomed out with units showing.
RESOLVED_NAMES = {}

#: (base_name, color, alpha, size) -> the scaled surface. Shared with every
#: caller asking for the same picture, so what comes back is read-only: pass
#: `alpha` to get_symbol rather than calling set_alpha on the result, or the next
#: caller inherits it. Everything else here already copies before it mutates.
SCALED_SYMBOLS = {}

#: Zoom is continuous, so every notch of it mints a new size. Emptied wholesale
#: rather than evicted one at a time -- these are small surfaces and the cache
#: refills from whatever is on screen inside a frame.
SCALED_CACHE_LIMIT = 4000


def clear_caches():
    """Drops everything derived from SYMBOLS. Called when SYMBOLS changes."""
    RESOLVED_NAMES.clear()
    SCALED_SYMBOLS.clear()
    COLORED_SYMBOLS.clear()


def load_symbols():
    """Load small icons for units, factories, etc., plus every non-classic unit art style."""
    path = c.ASSETS_DIR
    if not os.path.exists(path):
        os.makedirs(path)
        return

    for file in os.listdir(path):
        if file.endswith(".png"):
            name = os.path.splitext(file)[0]
            # Load and keep transparency
            img = pygame.image.load(os.path.join(path, file)).convert_alpha()
            SYMBOLS[name] = img

    # Factory/recruitment center building art lives in its own folder (see
    # c.BUILDINGS_DIR) but still resolves through the same flat name->Surface
    # map as everything above, since _resolve_against only ever looks names
    # up in SYMBOLS -- it has no idea which folder a symbol came from.
    if os.path.exists(c.BUILDINGS_DIR):
        for file in os.listdir(c.BUILDINGS_DIR):
            if file.endswith(".png"):
                name = os.path.splitext(file)[0]
                img = pygame.image.load(os.path.join(c.BUILDINGS_DIR, file)).convert_alpha()
                SYMBOLS[name] = img

    for style in c.UNIT_ART_STYLES:
        if style != "classic":
            load_style_symbols(style)

    # A mod can add or replace art, and both caches below are keyed on names
    # that were resolved against the old set.
    clear_caches()


def _load_variant(style, style_dir, name_key, entry, cultures=None):
    """One art variant for `name_key`. `entry` is either a plain filename
    string (applies to every country) or {"file": ..., "countries": [...]}
    (restricted to those country ids -- the same strings that key
    data/json/countries_data.json, e.g. "Germany", "German Reich"). The
    "countries" value can also be a string referencing a culture group from
    the manifest's _cultures section. Returns None on anything unusable so
    the caller can skip it rather than fail the whole style."""
    if isinstance(entry, str):
        filename, countries = entry, None
    elif isinstance(entry, dict):
        filename, countries = entry.get("file"), entry.get("countries")
    else:
        print(f"Warning: {style} unit art '{name_key}' has an entry that is "
              f"neither a filename nor an object: {entry!r}")
        return None

    if not filename:
        print(f"Warning: {style} unit art '{name_key}' has an entry with no 'file'")
        return None

    # Resolve culture group references to actual country lists
    if isinstance(countries, str):
        if cultures and countries in cultures:
            countries = cultures[countries]
        else:
            print(f"Warning: {style} unit art '{name_key}' references unknown "
                  f"culture group '{countries}'")
            return None

    img_path = os.path.join(style_dir, filename)
    if not os.path.exists(img_path):
        print(f"Warning: {style} unit art '{name_key}' -> '{filename}' not found in {style_dir}")
        return None

    try:
        surface = pygame.image.load(img_path).convert_alpha()
    except pygame.error as e:
        # Same posture as the missing-file branch above: one art file the
        # running platform can't decode shouldn't take the entire game down.
        # Which formats load is platform-dependent, so this is not a
        # theoretical guard -- desktop SDL_image reads WebP while the
        # pygbag/WASM build does not, so a file that opens fine on the dev's
        # machine can still be fatal in the browser build (that exact case,
        # WebP saved as .png under assets/hanskolmer/, crashed the web build
        # on startup). Mods can also ship arbitrary art.
        print(f"Warning: {style} unit art '{name_key}' -> '{filename}' "
              f"could not be loaded ({e}); skipping")
        return None

    return {"countries": frozenset(countries) if countries else None,
            "surface": surface,
            "filename": filename}


def load_style_symbols(style):
    """(Re)loads one alternate unit-art style from <style>/unit_art.json.

    The manifest maps a name key -- the same convention assets/images files
    are named after (an exact tier, an era range, or a bare family) -- to one
    or more art variants (see _load_variant). A key with several variants
    picks between them by country at draw time; missing folder/manifest/image
    entries are skipped rather than raised, since an incomplete style is meant
    to fall back to classic per-unit, not refuse to load at all.
    """
    style_dir = os.path.join(c.UNIT_ART_STYLES_DIR, style)
    manifest_path = os.path.join(style_dir, "unit_art.json")

    symbols = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not read {manifest_path}: {e}")
            manifest = {}

        cultures = manifest.get("_cultures", {})
        STYLE_CULTURES[style] = cultures

        for name_key, value in manifest.items():
            if name_key.startswith("_"):
                continue  # reserved for comments/metadata, not a unit name
            entries = value if isinstance(value, list) else [value]
            variants = [v for v in (_load_variant(style, style_dir, name_key, e, cultures) for e in entries)
                       if v is not None]
            if variants:
                symbols[name_key] = variants

    STYLE_SYMBOLS[style] = symbols
    _load_research_display(style, style_dir)
    clear_caches()


def _load_research_display(style, style_dir):
    """Loads <style>/research_scale.json -- a separate, optional file so a
    style's art mapping (unit_art.json) and its research-screen sizing hints
    can be edited/shared independently of each other. Missing file or bad
    JSON just leaves this style at the neutral 1.0 defaults everywhere."""
    path = os.path.join(style_dir, "research_scale.json")
    icon_scales, button_scale, button_scale_overrides = {}, 1.0, {}

    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: could not read {path}: {e}")
            config = {}
        icon_scales = config.get("icon_scales", {})
        button_scale = config.get("button_scale", 1.0)
        button_scale_overrides = config.get("button_scale_overrides", {})

    STYLE_RESEARCH_DISPLAY[style] = {
        "icon_scales": icon_scales,
        "button_scale": button_scale,
        "button_scale_overrides": button_scale_overrides,
    }


def style_countries(style):
    """Every country id with at least one dedicated art variant in `style`,
    sorted. Drives the per-country tabs on the Unit Art settings screen."""
    countries = set()
    for variants in STYLE_SYMBOLS.get(style, {}).values():
        for variant in variants:
            if variant["countries"]:
                countries.update(variant["countries"])
    return sorted(countries)


def style_cultures(style):
    """Culture group names (from unit_art.json's "_cultures") that have at
    least one member country with dedicated art in this style, sorted.
    Drives the culture tabs on the Unit Art settings screen -- countries in
    the same culture always share art (a restricted entry names the whole
    culture, never an individual country), so browsing by culture collapses
    e.g. Germany/German Reich/German Empire into one "Germanic" tab instead
    of one per country."""
    countries_with_art = set(style_countries(style))
    return sorted(name for name, members in STYLE_CULTURES.get(style, {}).items()
                  if countries_with_art.intersection(members))


def culture_representative(style, name):
    """The country id to resolve/draw art against for culture `name` in
    `style` -- the group's first listed member, since every country in a
    culture is defined to share identical art. None if `name` isn't a known
    culture for this style."""
    members = STYLE_CULTURES.get(style, {}).get(name)
    return members[0] if members else None


def _pick_variant_entry(variants, country):
    """The variant dict `country` should see among a name key's variants: an
    exact country match wins, otherwise the first unrestricted (generic)
    variant.

    Callers that reach this already know (via _table_has) that one of those
    two cases applies, so the final `variants[0]` is only a safety net."""
    generic = None
    for variant in variants:
        countries = variant["countries"]
        if countries is None:
            if generic is None:
                generic = variant
        elif country and country in countries:
            return variant
    return generic or variants[0]


def _pick_variant(variants, country):
    """The Surface `country` should see among a name key's variants -- see
    _pick_variant_entry."""
    return _pick_variant_entry(variants, country)["surface"]


def get_research_scale(name, style=None, country=None):
    """Per-icon multiplier authored in a style's <style>/research_scale.json
    (its "icon_scales" map, keyed by the same filename unit_art.json points
    at) for how large this unit's art should render on the research screen,
    layered on top of whatever zoom the caller already asked for.

    Exists because a style's source art can be a completely different native
    resolution than classic's hand-sized icons (hanskolmer's raw unit
    photos/paintings vs. classic's small pre-scaled sprites), so the same
    zoom that looks right for one blows the other well past the button that
    contains it. 1.0 (no change) for classic, or any file research_scale.json
    doesn't mention.
    """
    resolved = _resolve_name(name, style, country)
    if resolved is None:
        return 1.0
    source_style, base_name = resolved
    if source_style == "classic":
        return 1.0
    variant = _pick_variant_entry(STYLE_SYMBOLS[source_style][base_name], country)
    icon_scales = STYLE_RESEARCH_DISPLAY.get(source_style, {}).get("icon_scales", {})
    return icon_scales.get(variant["filename"], 1.0)


def get_research_button_scale(style=None):
    """Per-style multiplier (<style>/research_scale.json's "button_scale"
    field) for how big the research screen's tech node buttons should be
    while this style is active. 1.0 (no change) for classic or a style with
    no research_scale.json.

    `style` defaults to the globally active c.UNIT_ART_STYLE, matching every
    other lookup in this module.
    """
    if style is None:
        style = c.UNIT_ART_STYLE
    return STYLE_RESEARCH_DISPLAY.get(style, {}).get("button_scale", 1.0)


def get_research_button_scale_overrides(name, style=None, country=None):
    """(width_scale, height_scale) for this specific tech's research-screen
    button, from <style>/research_scale.json's "button_scale_overrides" map
    -- layered on top of the style's overall get_research_button_scale, for
    a unit whose button needs to be wider/taller than the rest (e.g.
    hanskolmer's long artillery pieces).

    Matched first against the exact resolved name key (e.g. "Artillery I"),
    then -- same Roman-numeral stripping _resolve_against falls back to --
    against the bare family name ("Artillery"), so one override can widen
    every tier without listing each one. (1.0, 1.0) if nothing resolves, the
    style is classic, or no override matches either name.
    """
    resolved = _resolve_name(name, style, country)
    if resolved is None:
        return 1.0, 1.0
    source_style, base_name = resolved
    if source_style == "classic":
        return 1.0, 1.0

    overrides = STYLE_RESEARCH_DISPLAY.get(source_style, {}).get("button_scale_overrides", {})
    entry = overrides.get(base_name)
    if entry is None:
        family_name = re.sub(r'\s+[IVXLCDM]+$', '', base_name, flags=re.IGNORECASE).strip()
        entry = overrides.get(family_name)
    if entry is None:
        return 1.0, 1.0
    return entry.get("width", 1.0), entry.get("height", 1.0)


def _table_has(table, key, country):
    """Whether `table[key]` has a picture `country` would actually be shown.

    Classic's SYMBOLS is a flat name -> Surface map with no country variants,
    so presence there always counts. A style's entry is a variant list, and a
    key that exists only for other countries must read as absent -- exactly
    like a key that was never in the manifest -- so resolution falls through
    to the next fallback (and eventually to classic) instead of showing the
    wrong nation's art.
    """
    if key not in table:
        return False
    entry = table[key]
    if isinstance(entry, list):
        return any(v["countries"] is None or (country and country in v["countries"]) for v in entry)
    return True

# --- NEW: NumPy Colorizer ---
def colorize_red_image(img, new_color):
    """Treats the Red channel as brightness, but ONLY for red-tinted pixels.
       Leaves white, grey, and black pixels completely untouched."""
    
    # 1. Extract RGB and Alpha channels. Convert to float32 for precise math.
    rgb = pygame.surfarray.pixels3d(img).astype(np.float32)
    alpha = pygame.surfarray.pixels_alpha(img)

    # 2. Isolate the "Redness" (How much Red dominates Green and Blue)
    max_gb = np.maximum(rgb[:, :, 1], rgb[:, :, 2])
    
    # Calculate saturation of the red channel. 
    # 1e-5 prevents division by zero on pure black pixels.
    redness = np.clip((rgb[:, :, 0] - max_gb) / (rgb[:, :, 0] + 1e-5), 0, 1)
    
    # Expand 'redness' to 3 dimensions so we can multiply it with our RGB arrays
    redness_3d = redness[:, :, np.newaxis]

    # 3. Calculate the Colorized Version for the red parts
    brightness = rgb[:, :, 0:1] / 255.0  # Keep it 3D for broadcasting
    target_rgb = np.array(new_color, dtype=np.float32)
    colorized_pixels = brightness * target_rgb

    # 4. Blend original and colorized based on the redness mask
    # Grayscale pixels (redness = 0) keep their original color.
    # Red pixels (redness = 1) get fully replaced by the target color.
    final_rgb = (rgb * (1.0 - redness_3d)) + (colorized_pixels * redness_3d)

    # 5. Build the new surface
    new_img = pygame.Surface(img.get_size(), pygame.SRCALPHA)
    pygame.surfarray.blit_array(new_img, final_rgb.astype(np.uint8))

    # 6. Copy the original alpha channel back over
    alpha_dest = pygame.surfarray.pixels_alpha(new_img)
    np.copyto(alpha_dest, alpha)

    return new_img

def _resolve_against(name, table, country):
    """Which key of `table` (a SYMBOLS-shaped dict, or one style's entry in
    STYLE_SYMBOLS) `name` should draw for `country`, or None if nothing in it
    applies. Pure name arithmetic, except every candidate key is also checked
    with _table_has so a key that exists only for a different country is
    treated exactly like a key that isn't there at all."""
    # 1. Resolve base name
    base_name = name

    # Convoys/Trucks wrap the carried unit's name in parens (e.g.
    # "Convoy (Infantry Type 1940)"); the wrapper itself is what should be
    # drawn on the map/orders panel, so strip the carried unit off first.
    carrier_match = re.match(r'^(Convoy|Truck) \(.+\)$', name)
    if carrier_match:
        base_name = carrier_match.group(1)

    # --- NEW: RANGE-BASED IMAGE LOOKUP (Lvl X-Y) ---
    if not _table_has(table, base_name, country):
        lvl_match = re.search(r'^(.*?)\s+Lvl\s+(\d+)$', name, re.IGNORECASE)
        if lvl_match:
            base_type = lvl_match.group(1)
            target_lvl = int(lvl_match.group(2))

            # Check for range keys (e.g., "Factory Lvl 1-3"). Keep scanning
            # rather than stopping at the first hit so a later-listed
            # matching key overrides an earlier, overlapping one.
            for sym_key in table.keys():
                range_match = re.match(rf'^{re.escape(base_type)}\s+Lvl\s+(\d+)-(\d+)$', sym_key, re.IGNORECASE)
                if range_match:
                    start_lvl, end_lvl = int(range_match.group(1)), int(range_match.group(2))
                    if start_lvl <= target_lvl <= end_lvl and _table_has(table, sym_key, country):
                        base_name = sym_key

    if not _table_has(table, base_name, country):
        # Check if there is a 4-digit year in the name (e.g., "Infantry Type 1860")
        year_match = re.search(r'\b(\d{4})\b', name)
        if year_match:
            year = int(year_match.group(1))

            # Dynamically strip "Type" and the year to extract the generic class ("Infantry")
            base_type = re.sub(r'\s*(?:Type)?\s*\d{4}.*', '', name, flags=re.IGNORECASE).strip()

            range_found = False
            # Look for an image formatted as "BaseType YYYY-YYYY" (e.g. "Infantry 1850-1900").
            # Ranges can overlap (e.g. a country-specific range nested inside a
            # broader generic one); keep scanning rather than stopping at the
            # first hit so a later-listed matching key overrides an earlier one,
            # same as everywhere else in this manifest.
            for sym_key in table.keys():
                pattern = rf'^{re.escape(base_type)}\s+(\d{{4}})-(\d{{4}})$'
                range_match = re.match(pattern, sym_key, re.IGNORECASE)

                if range_match:
                    start_year, end_year = int(range_match.group(1)), int(range_match.group(2))
                    # Check if our requested year falls within the bounds of this image file
                    if start_year <= year <= end_year and _table_has(table, sym_key, country):
                        base_name = sym_key
                        range_found = True

            # If no specific era image matched, fallback to generic base type (e.g., "Infantry")
            if not range_found and _table_has(table, base_type, country):
                base_name = base_type

    # Original fallback for Roman Numerals (Tanks & Navy)
    if not _table_has(table, base_name, country):
        base_name = re.sub(r'\s+[IVXLCDM]+$', '', name, flags=re.IGNORECASE).strip()

    # Fallback for Lvl # (Research, Buildings, etc.)
    if not _table_has(table, base_name, country):
        base_name = re.sub(r'\s+Lvl\s+\d+$', '', name, flags=re.IGNORECASE).strip()

    if not _table_has(table, base_name, country):
        return None

    return base_name


def resolve(name, style=None, country=None):
    """Public form of _resolve_name, for callers outside this module that need
    to know what a name resolves to (and where from) without drawing it --
    the Unit Art settings screen groups units by shared art this way."""
    return _resolve_name(name, style, country)


def _resolve_name(name, style=None, country=None):
    """Which (source_style, key) pair `name` should draw for `country`, or
    None if nothing matches in `style` or in classic. `style` defaults to the
    globally active c.UNIT_ART_STYLE; `country` (a country id, the same
    strings that key data/json/countries_data.json) defaults to "nobody in
    particular", which only ever sees unrestricted art.

    The same answer every time for a given set of loaded symbols, which is
    the only reason it is safe to memoise -- see RESOLVED_NAMES for why it is
    worth memoising.
    """
    if style is None:
        style = c.UNIT_ART_STYLE
    key = (style, country, name)
    if key in RESOLVED_NAMES:
        return RESOLVED_NAMES[key]
    resolved = _resolve_name_uncached(name, style, country)
    RESOLVED_NAMES[key] = resolved
    return resolved


def _resolve_name_uncached(name, style=None, country=None):
    if style is None:
        style = c.UNIT_ART_STYLE

    if style != "classic":
        style_table = STYLE_SYMBOLS.get(style)
        if style_table:
            resolved = _resolve_against(name, style_table, country)
            if resolved is not None:
                return (style, resolved)

    # No style requested, the style has nothing for this name, or nothing in
    # it applies to this country -- classic is both the default and the
    # universal fallback (and has no country variants of its own).
    resolved = _resolve_against(name, SYMBOLS, country)
    if resolved is None:
        return None
    return ("classic", resolved)


def _resolved_base_img(name, style, country):
    """The unscaled Surface `get_symbol`/`get_native_size` would draw for this
    request, plus (source_style, base_name), or (None, None, None) if nothing
    resolves."""
    resolved = _resolve_name(name, style, country)
    if resolved is None:
        return None, None, None
    source_style, base_name = resolved

    if source_style == "classic":
        base_img = SYMBOLS[base_name]
    else:
        base_img = _pick_variant(STYLE_SYMBOLS[source_style][base_name], country)
    return base_img, source_style, base_name


def get_native_size(name, style=None, country=None):
    """The unscaled pixel size of whatever `get_symbol` would draw for this
    name/style/country, or None if nothing resolves. Lets a caller work out a
    zoom that fits a fixed on-screen box without scaling the image first just
    to measure it."""
    base_img, _, _ = _resolved_base_img(name, style, country)
    return base_img.get_size() if base_img else None


def get_symbol(name, zoom, color=None, alpha=255, style=None, country=None):
    """Returns the scaled icon, or None if no loaded symbol matches the name.

    `style` defaults to the globally active c.UNIT_ART_STYLE; anything that
    style's manifest doesn't cover for this name (or doesn't cover for
    `country`, a country id) falls back to classic.

    The surface is shared with every other caller asking for the same picture at
    the same size, so treat what comes back as read-only. That is what `alpha` is
    for: setting it afterwards would leave the next caller of that name and size
    holding a see-through icon.
    """
    base_img, source_style, base_name = _resolved_base_img(name, style, country)
    if base_img is None:
        return None

    # Custom per-symbol scale overrides, on top of the global 0.5.
    size = _scaled_size(base_img, zoom, c.SYMBOL_BASE_SCALES.get(base_name, 1.0))

    # Keyed on the picture itself (identity-hashed, since Surfaces never
    # define __eq__) rather than (style, base_name, country): most countries
    # share the same generic variant of a given key, and keying on the
    # resolved image lets them share one cache entry instead of minting a
    # duplicate per country that happens to see identical art.
    img_key = id(base_img)

    key = (img_key, color, alpha, size)
    scaled = SCALED_SYMBOLS.get(key)
    if scaled is not None:
        return scaled

    # Colorize and cache if a color is requested. Kept separate from the scaled
    # cache: colorizing is the expensive half and is worth keeping across zooms.
    if color:
        color_key = (img_key, color)
        if color_key not in COLORED_SYMBOLS:
            COLORED_SYMBOLS[color_key] = colorize_red_image(base_img, color)
        target_img = COLORED_SYMBOLS[color_key]
    else:
        target_img = base_img

    scaled = pygame.transform.scale(target_img, size)
    if alpha < 255:
        scaled.set_alpha(alpha)

    if len(SCALED_SYMBOLS) >= SCALED_CACHE_LIMIT:
        SCALED_SYMBOLS.clear()
    SCALED_SYMBOLS[key] = scaled
    return scaled


def _scaled_size(img, zoom, custom_scale=1.0):
    """The pixel size this symbol is drawn at, keeping its proportions."""
    orig_w, orig_h = img.get_size()

    # Multiply the global 0.5 scale by our custom scale multiplier
    scale_factor = zoom * 0.5 * custom_scale

    return (max(4, int(orig_w * scale_factor)),
            max(4, int(orig_h * scale_factor)))
