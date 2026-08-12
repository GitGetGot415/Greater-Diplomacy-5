import pygame
import os
import re
import numpy as np
import data.constants as c

SYMBOLS = {}
COLORED_SYMBOLS = {}

#: What each requested name resolved to in SYMBOLS, or None for "no such icon".
#: The resolution in _resolve_name tries five fallbacks in turn and two of them
#: walk every loaded symbol building a regex per key. The map asks for one symbol
#: per unit box per frame, so at 178 loaded symbols that was 200,000 re.escape
#: calls a second and 40% of a zoomed-out frame -- the whole of the lag when a
#: player zoomed out with units showing.
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
    """Load small icons for units, factories, etc."""
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

    # A mod can add or replace art, and both caches below are keyed on names
    # that were resolved against the old set.
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

def _resolve_name(name):
    """Which SYMBOLS key `name` should draw, or None if nothing matches.

    Pure name arithmetic and the same answer every time for a given set of
    loaded symbols, which is the only reason it is safe to memoise -- see
    RESOLVED_NAMES for why it is worth memoising.
    """
    if name in RESOLVED_NAMES:
        return RESOLVED_NAMES[name]
    resolved = _resolve_name_uncached(name)
    RESOLVED_NAMES[name] = resolved
    return resolved


def _resolve_name_uncached(name):
    # 1. Resolve base name
    base_name = name

    # Convoys/Trucks wrap the carried unit's name in parens (e.g.
    # "Convoy (Infantry Type 1940)"); the wrapper itself is what should be
    # drawn on the map/orders panel, so strip the carried unit off first.
    carrier_match = re.match(r'^(Convoy|Truck) \(.+\)$', name)
    if carrier_match:
        base_name = carrier_match.group(1)

    # --- NEW: RANGE-BASED IMAGE LOOKUP (Lvl X-Y) ---
    if base_name not in SYMBOLS:
        lvl_match = re.search(r'^(.*?)\s+Lvl\s+(\d+)$', name, re.IGNORECASE)
        if lvl_match:
            base_type = lvl_match.group(1)
            target_lvl = int(lvl_match.group(2))
            
            # Check for range keys (e.g., "Factory Lvl 1-3")
            for sym_key in SYMBOLS.keys():
                range_match = re.match(rf'^{re.escape(base_type)}\s+Lvl\s+(\d+)-(\d+)$', sym_key, re.IGNORECASE)
                if range_match:
                    start_lvl, end_lvl = int(range_match.group(1)), int(range_match.group(2))
                    if start_lvl <= target_lvl <= end_lvl:
                        base_name = sym_key
                        break

    if base_name not in SYMBOLS:
        # Check if there is a 4-digit year in the name (e.g., "Infantry Type 1860")
        year_match = re.search(r'\b(\d{4})\b', name)
        if year_match:
            year = int(year_match.group(1))
            
            # Dynamically strip "Type" and the year to extract the generic class ("Infantry")
            base_type = re.sub(r'\s*(?:Type)?\s*\d{4}.*', '', name, flags=re.IGNORECASE).strip()
            
            range_found = False
            # Look for an image formatted as "BaseType YYYY-YYYY" (e.g. "Infantry 1850-1900")
            for sym_key in SYMBOLS.keys():
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
            if not range_found and base_type in SYMBOLS:
                base_name = base_type

    # Original fallback for Roman Numerals (Tanks & Navy)
    if base_name not in SYMBOLS:
        base_name = re.sub(r'\s+[IVXLCDM]+$', '', name, flags=re.IGNORECASE).strip()

    # Fallback for Lvl # (Research, Buildings, etc.)
    if base_name not in SYMBOLS:
        base_name = re.sub(r'\s+Lvl\s+\d+$', '', name, flags=re.IGNORECASE).strip()

    if base_name not in SYMBOLS:
        return None

    return base_name


def get_symbol(name, zoom, color=None, alpha=255):
    """Returns the scaled icon, or None if no loaded symbol matches the name.

    The surface is shared with every other caller asking for the same picture at
    the same size, so treat what comes back as read-only. That is what `alpha` is
    for: setting it afterwards would leave the next caller of that name and size
    holding a see-through icon.
    """
    base_name = _resolve_name(name)
    if base_name is None:
        return None

    base_img = SYMBOLS[base_name]
    # Custom per-symbol scale overrides, on top of the global 0.5.
    size = _scaled_size(base_img, zoom, c.SYMBOL_BASE_SCALES.get(base_name, 1.0))

    key = (base_name, color, alpha, size)
    scaled = SCALED_SYMBOLS.get(key)
    if scaled is not None:
        return scaled

    # Colorize and cache if a color is requested. Kept separate from the scaled
    # cache: colorizing is the expensive half and is worth keeping across zooms.
    if color:
        colour_key = (base_name, color)
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