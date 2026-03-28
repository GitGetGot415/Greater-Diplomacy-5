import pygame
import os
import re

SYMBOLS = {}

def load_symbols():
    """Load small icons for units, factories, etc."""
    path = "assets"
    if not os.path.exists(path):
        os.makedirs(path)
        return

    for file in os.listdir(path):
        if file.endswith(".png"):
            name = os.path.splitext(file)[0]
            # Load and keep transparency
            img = pygame.image.load(os.path.join(path, file)).convert_alpha()
            # Scale it to a base size (e.g., 32x32)
            # SYMBOLS[name] = pygame.transform.scale(img, (32, 32))
            SYMBOLS[name] = img

def get_symbol(name, zoom):
    """Returns scaled icon. Falls back to base name if Roman Numeral version is missing."""
    # 1. Try exact match
    if name in SYMBOLS:
        return _scale_img(SYMBOLS[name], zoom)

    # 2. Try falling back (stripping I, II, III... XX)
    # Regex looks for space followed by Roman Numerals at the end of the string
    base_name = re.sub(r'\s+(X{0,1}V{0,1}I{0,3}|X{0,2}|I[VX]|VI{0,3})$', '', name).strip()
    
    if base_name in SYMBOLS:
        return _scale_img(SYMBOLS[base_name], zoom)
    
    return None

def _scale_img(img, zoom):
    # Base target size is 32. We scale the width by zoom.
    target_w = max(8, int(32 * zoom))
    
    # Get original proportions
    orig_w, orig_h = img.get_size()
    aspect_ratio = orig_h / orig_w
    
    # Calculate height based on aspect ratio
    target_h = int(target_w * aspect_ratio)
    
    return pygame.transform.scale(img, (target_w, target_h))