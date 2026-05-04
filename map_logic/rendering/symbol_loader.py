import pygame
import os
import re
import numpy as np
import data.constants as c

SYMBOLS = {}
COLORED_SYMBOLS = {}

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

def get_symbol(name, zoom, color=None):
    """Returns scaled icon. Generates and caches colored variants if a color is provided."""
    # 1. Resolve base name
    base_name = name
    
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
        base_name = re.sub(r'\s+(X{0,1}V{0,1}I{0,3}|X{0,2}|I[VX]|VI{0,3})$', '', name).strip()
        
    if base_name not in SYMBOLS:
        return None

    base_img = SYMBOLS[base_name]

    # 2. Colorize and Cache if a color is requested
    if color:
        cache_key = (base_name, color)
        if cache_key not in COLORED_SYMBOLS:
            # Generate the colored version once and cache it
            COLORED_SYMBOLS[cache_key] = colorize_red_image(base_img, color)
        
        target_img = COLORED_SYMBOLS[cache_key]
    else:
        target_img = base_img

    # 3. Scale the final image dynamically based on camera zoom and custom base scales
    # Check constants for a specific scale override, default to 1.0
    custom_scale = getattr(c, 'SYMBOL_BASE_SCALES', {}).get(base_name, 1.0)
    return _scale_img(target_img, zoom, custom_scale)

def _scale_img(img, zoom, custom_scale=1.0):
    # Get original proportions
    orig_w, orig_h = img.get_size()
    
    # Multiply the global 0.5 scale by our custom scale multiplier
    scale_factor = zoom * 0.5 * custom_scale
    
    target_w = max(4, int(orig_w * scale_factor))
    target_h = max(4, int(orig_h * scale_factor))
    
    return pygame.transform.scale(img, (target_w, target_h))