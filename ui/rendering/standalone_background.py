"""The background of a standalone game's main menu and country selector."""
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
    """Fill the export settings' background color, then draw their image over it."""

    def __init__(self, settings):
        settings = queries.normalized_standalone_export_settings(settings)
        self.color = settings["background_color"]
        self.image = _load_image(settings["background_image"])
        self._scaled = None

    def draw(self, surface):
        surface.fill(self.color)
        if self.image is None:
            return
        size = surface.get_size()
        if self._scaled is None or self._scaled[0] != size:
            # Cover the whole screen without stretching. The image is centered, so its edges are cropped.
            # Transparent parts of the image show the background color.
            scale = max(size[0] / self.image.get_width(), size[1] / self.image.get_height())
            scaled = pygame.transform.smoothscale(
                self.image, (max(1, round(self.image.get_width() * scale)), max(1, round(self.image.get_height() * scale))))
            self._scaled = (size, scaled, scaled.get_rect(center=(size[0] // 2, size[1] // 2)))
        _size, scaled, rect = self._scaled
        surface.blit(scaled, rect)
