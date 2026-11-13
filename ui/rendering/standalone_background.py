"""The shared background of standalone menus and settings."""
import pygame

from data import queries


def _load_image(text):
    """Return the background image, or None when there is no readable image."""
    if not text:
        return None
    try:
        image = queries.load_png_b64(text)
    except (ValueError, pygame.error) as error:
        print(f"Failed to load the standalone background image: {error}")
        return None
    # smoothscale needs 24- or 32-bit pixels. Palette PNGs load with 8.
    full_color = pygame.Surface(image.get_size(), pygame.SRCALPHA, 32)
    full_color.blit(image, (0, 0))
    return full_color


class StandaloneBackground:
    """Fill the export settings' background color, then draw their image over it, centered."""

    def __init__(self, settings):
        settings = queries.normalized_standalone_export_settings(settings)
        self.color = settings["background_color"]
        self.image = _load_image(settings["background_image"])
        self.fit = settings["image_fit"]
        self.smoothing = settings["image_smoothing"]
        self._scaled = None

    def _scaled_size(self, size):
        width, height = self.image.get_size()
        if self.fit == "stretch":
            return size
        if self.fit == "actual":
            return width, height
        # Fill covers the whole screen without stretching. The centered image's edges are cropped.
        scale = max(size[0] / width, size[1] / height)
        return max(1, round(width * scale)), max(1, round(height * scale))

    def draw(self, surface):
        surface.fill(self.color)
        if self.image is None:
            return
        size = surface.get_size()
        if self._scaled is None or self._scaled[0] != size:
            # Transparent parts of the image show the background color.
            target = self._scaled_size(size)
            if target == self.image.get_size():
                scaled = self.image
            elif self.smoothing:
                scaled = pygame.transform.smoothscale(self.image, target)
            else:
                scaled = pygame.transform.scale(self.image, target)
            self._scaled = (size, scaled, scaled.get_rect(center=(size[0] // 2, size[1] // 2)))
        _size, scaled, rect = self._scaled
        surface.blit(scaled, rect)
