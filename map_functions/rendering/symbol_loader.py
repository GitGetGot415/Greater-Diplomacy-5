import pygame
import os

SYMBOLS = {}

def load_symbols():
    """Load small icons for units, factories, etc."""
    path = "assets/symbols/"
    if not os.path.exists(path):
        os.makedirs(path)
        return

    for file in os.listdir(path):
        if file.endswith(".png"):
            name = os.path.splitext(file)[0]
            # Load and keep transparency
            img = pygame.image.load(os.path.join(path, file)).convert_alpha()
            # Scale it to a base size (e.g., 32x32)
            SYMBOLS[name] = pygame.transform.scale(img, (32, 32))

def get_symbol(name, zoom):
    """Returns a scaled version of the requested icon."""
    if name in SYMBOLS:
        base_img = SYMBOLS[name]
        size = int(32 * zoom)
        if size < 8: size = 8 # Don't let it disappear
        return pygame.transform.scale(base_img, (size, size))
    return None