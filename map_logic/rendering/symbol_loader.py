import pygame
import os
import re
import json
import numpy as np
import data.constants as c

SYMBOLS = {}
COLORED_SYMBOLS = {}

#: Alternate unit-art sets, keyed by style name (e.g. "hanskolmer") -> {unit
#: name key -> Surface}. Populated from <style folder>/unit_art.json, which
#: maps the same kind of name keys assets/images files are named after (an
#: exact tier like "Medium Tank III", an era range like "Infantry 1900-1935",
#: or a bare family like "Artillery") to an image filename in that folder.
#: "classic" is never a key here -- it just means "use SYMBOLS".
STYLE_SYMBOLS = {}

#: What each (style, requested name) resolved to: (source_style, base_name) in
#: whichever of SYMBOLS/STYLE_SYMBOLS[source_style] actually holds the image,
#: or None for "no such icon anywhere". The resolution in _resolve_against
#: tries five fallbacks in turn and two of them walk every loaded symbol
#: building a regex per key. The map asks for one symbol per unit box per
#: frame, so at 178 loaded symbols that was 200,000 re.escape calls a second
#: and 40% of a zoomed-out frame -- the whole of the lag when a player zoomed
#: out with units showing.
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

    for style in c.UNIT_ART_STYLES:
        if style != "classic":
            load_style_symbols(style)

    # A mod can add or replace art, and both caches below are keyed on names
    # that were resolved against the old set.
    clear_caches()


def load_style_symbols(style):
    """(Re)loads one alternate unit-art style from <style>/unit_art.json.

    The manifest maps a name key -- the same convention assets/images files
    are named after (an exact tier, an era range, or a bare family) -- to an
    image filename in the same folder. Missing folder/manifest/image entries
    are skipped rather than raised: an incomplete style is meant to fall back
    to classic per-unit, not refuse to load at all.
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

        for name_key, filename in manifest.items():
            if name_key.startswith("_"):
                continue  # reserved for comments/metadata, not a unit name
            img_path = os.path.join(style_dir, filename)
            if not os.path.exists(img_path):
                print(f"Warning: {style} unit art '{name_key}' -> '{filename}' not found in {style_dir}")
                continue
            symbols[name_key] = pygame.image.load(img_path).convert_alpha()

    STYLE_SYMBOLS[style] = symbols
    clear_caches()

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

def _resolve_against(name, table):
    """Which key of `table` (a SYMBOLS-shaped dict) `name` should draw, or
    None if nothing in it matches. Pure name arithmetic against whatever set
    of loaded symbols it's handed -- classic's SYMBOLS or one style's entry
    in STYLE_SYMBOLS."""
    # 1. Resolve base name
    base_name = name

    # Convoys/Trucks wrap the carried unit's name in parens (e.g.
    # "Convoy (Infantry Type 1940)"); the wrapper itself is what should be
    # drawn on the map/orders panel, so strip the carried unit off first.
    carrier_match = re.match(r'^(Convoy|Truck) \(.+\)$', name)
    if carrier_match:
        base_name = carrier_match.group(1)

    # --- NEW: RANGE-BASED IMAGE LOOKUP (Lvl X-Y) ---
    if base_name not in table:
        lvl_match = re.search(r'^(.*?)\s+Lvl\s+(\d+)$', name, re.IGNORECASE)
        if lvl_match:
            base_type = lvl_match.group(1)
            target_lvl = int(lvl_match.group(2))

            # Check for range keys (e.g., "Factory Lvl 1-3")
            for sym_key in table.keys():
                range_match = re.match(rf'^{re.escape(base_type)}\s+Lvl\s+(\d+)-(\d+)$', sym_key, re.IGNORECASE)
                if range_match:
                    start_lvl, end_lvl = int(range_match.group(1)), int(range_match.group(2))
                    if start_lvl <= target_lvl <= end_lvl:
                        base_name = sym_key
                        break

    if base_name not in table:
        # Check if there is a 4-digit year in the name (e.g., "Infantry Type 1860")
        year_match = re.search(r'\b(\d{4})\b', name)
        if year_match:
            year = int(year_match.group(1))

            # Dynamically strip "Type" and the year to extract the generic class ("Infantry")
            base_type = re.sub(r'\s*(?:Type)?\s*\d{4}.*', '', name, flags=re.IGNORECASE).strip()

            range_found = False
            # Look for an image formatted as "BaseType YYYY-YYYY" (e.g. "Infantry 1850-1900")
            for sym_key in table.keys():
                pattern = rf'^{re.escape(base_type)}\s+(\d{{4}})-(\d{{4}})$'
                range_match = re.match(pattern, sym_key, re.IGNORECASE)

                if range_match:
                    start_year, end_year = int(range_match.group(1)), int(range_match.group(2))
                    # Check if our requested year falls within the bounds of this image file
                    if start_year <= year <= end_year:
                        base_name = sym_key
                        range_found = True
                        break

            # If no specific era image matched, fallback to generic base type (e.g., "Infantry")
            if not range_found and base_type in table:
                base_name = base_type

    # Original fallback for Roman Numerals (Tanks & Navy)
    if base_name not in table:
        base_name = re.sub(r'\s+[IVXLCDM]+$', '', name, flags=re.IGNORECASE).strip()

    # Fallback for Lvl # (Research, Buildings, etc.)
    if base_name not in table:
        base_name = re.sub(r'\s+Lvl\s+\d+$', '', name, flags=re.IGNORECASE).strip()

    if base_name not in table:
        return None

    return base_name


def resolve(name, style=None):
    """Public form of _resolve_name, for callers outside this module that need
    to know what a name resolves to (and where from) without drawing it --
    the Unit Art settings screen groups units by shared art this way."""
    return _resolve_name(name, style)


def _resolve_name(name, style=None):
    """Which (source_style, key) pair `name` should draw, or None if nothing
    matches in `style` or in classic. `style` defaults to the globally active
    c.UNIT_ART_STYLE.

    The same answer every time for a given set of loaded symbols, which is
    the only reason it is safe to memoise -- see RESOLVED_NAMES for why it is
    worth memoising.
    """
    if style is None:
        style = c.UNIT_ART_STYLE
    key = (style, name)
    if key in RESOLVED_NAMES:
        return RESOLVED_NAMES[key]
    resolved = _resolve_name_uncached(name, style)
    RESOLVED_NAMES[key] = resolved
    return resolved


def _resolve_name_uncached(name, style=None):
    if style is None:
        style = c.UNIT_ART_STYLE

    if style != "classic":
        style_table = STYLE_SYMBOLS.get(style)
        if style_table:
            resolved = _resolve_against(name, style_table)
            if resolved is not None:
                return (style, resolved)

    # No style requested, or the style has nothing for this name -- classic
    # is both the default and the universal fallback.
    resolved = _resolve_against(name, SYMBOLS)
    if resolved is None:
        return None
    return ("classic", resolved)


def get_symbol(name, zoom, color=None, alpha=255, style=None):
    """Returns the scaled icon, or None if no loaded symbol matches the name.

    `style` defaults to the globally active c.UNIT_ART_STYLE; anything that
    style's manifest doesn't cover for this name falls back to classic.

    The surface is shared with every other caller asking for the same picture at
    the same size, so treat what comes back as read-only. That is what `alpha` is
    for: setting it afterwards would leave the next caller of that name and size
    holding a see-through icon.
    """
    resolved = _resolve_name(name, style)
    if resolved is None:
        return None
    source_style, base_name = resolved

    table = SYMBOLS if source_style == "classic" else STYLE_SYMBOLS[source_style]
    base_img = table[base_name]
    # Custom per-symbol scale overrides, on top of the global 0.5.
    size = _scaled_size(base_img, zoom, c.SYMBOL_BASE_SCALES.get(base_name, 1.0))

    key = (source_style, base_name, color, alpha, size)
    scaled = SCALED_SYMBOLS.get(key)
    if scaled is not None:
        return scaled

    # Colorize and cache if a color is requested. Kept separate from the scaled
    # cache: colorizing is the expensive half and is worth keeping across zooms.
    if color:
        colour_key = (source_style, base_name, color)
        if colour_key not in COLORED_SYMBOLS:
            COLORED_SYMBOLS[colour_key] = colorize_red_image(base_img, color)
        target_img = COLORED_SYMBOLS[colour_key]
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