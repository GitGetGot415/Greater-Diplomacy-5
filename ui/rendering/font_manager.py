# --- Start of file: .\map_logic\rendering\font_manager.py ---
import pygame
import data.constants as c

class FallbackFont:
    """A pygame font that draws any word it has no glyphs for with the fallback font.

    A missing glyph does not raise an error. The font draws its "not defined"
    box instead, so the missing check compares a character's picture with that
    box. Results are cached per character. Other font methods pass through to
    the primary font.
    """

    def __init__(self, primary, fallback_path, size, bold=False):
        self._primary = primary
        self._fallback_path = fallback_path
        self._size = size
        self._bold = bold
        self._fallback_font = None
        self._fallback_failed = False
        self._notdef = None
        self._lacks_cache = {}

    def __getattr__(self, name):
        return getattr(self._primary, name)

    @property
    def _fallback(self):
        if self._fallback_font is None and not self._fallback_failed:
            try:
                self._fallback_font = pygame.font.Font(self._fallback_path, self._size)
                if self._bold:
                    self._fallback_font.set_bold(True)
            except (FileNotFoundError, pygame.error) as e:
                print(f"Failed to load fallback font ({e}). Missing characters stay as boxes.")
                self._fallback_failed = True
        return self._fallback_font

    def _picture(self, ch):
        surf = self._primary.render(ch, False, (255, 255, 255))
        return surf.get_size(), pygame.image.tobytes(surf, "RGBA")

    def _lacks(self, ch):
        if ch.isascii() or ch.isspace():
            return False
        if ch not in self._lacks_cache:
            if self._notdef is None:
                self._notdef = self._picture("￿")  # Never assigned, so always the box.
            self._lacks_cache[ch] = self._picture(ch) == self._notdef
        return self._lacks_cache[ch]

    def _segments(self, text):
        """Splits text into (text, font) runs. A word with a missing glyph uses the fallback whole."""
        fallback = self._fallback
        segments = []
        for index, word in enumerate(text.split(" ")):
            font = fallback if fallback is not None and any(self._lacks(ch) for ch in word) else self._primary
            pieces = [(word, font)] if index == 0 else [(" ", self._primary), (word, font)]
            for piece_text, piece_font in pieces:
                if segments and segments[-1][1] is piece_font:
                    segments[-1] = (segments[-1][0] + piece_text, piece_font)
                else:
                    segments.append((piece_text, piece_font))
        return segments

    def size(self, text):
        if text.isascii():
            return self._primary.size(text)
        sizes = [font.size(piece) for piece, font in self._segments(text)]
        return sum(w for w, _h in sizes), max(h for _w, h in sizes)

    def render(self, text, antialias, color, bgcolor=None, wraplength=0):
        if text.isascii() or wraplength:
            return self._primary.render(text, antialias, color, bgcolor, wraplength)
        segments = self._segments(text)
        if all(font is self._primary for _piece, font in segments):
            return self._primary.render(text, antialias, color, bgcolor)
        # Line the runs up on one baseline, since the two fonts differ in height.
        ascent = max(font.get_ascent() for _piece, font in segments)
        parts = [(font.render(piece, antialias, color, bgcolor), ascent - font.get_ascent())
                 for piece, font in segments if piece]
        result = pygame.Surface((sum(part.get_width() for part, _y in parts),
                                 max(y + part.get_height() for part, y in parts)), pygame.SRCALPHA)
        if bgcolor is not None:
            result.fill(bgcolor)
        x = 0
        for part, y in parts:
            result.blit(part, (x, y))
            x += part.get_width()
        return result


class FontManager:
    def __init__(self):
        self.font_path = None
        self.cache = {}
        
        # Define your standard text presets here.
        # This matches the general sizes used across your project.
        self.presets = {
            "tiny": {"size": 14, "bold": False},
            "small": {"size": 16, "bold": False},
            "normal": {"size": 18, "bold": False},
            "button": {"size": 24, "bold": False},
            "button_small": {"size": 18, "bold": False},
            "research_year": {"size": 28, "bold": False},
            "heading2": {"size": 28, "bold": False},
            "heading1": {"size": 32, "bold": False},
            "title": {"size": 40, "bold": False},
            # Map names get a specific font path override here
            "country_name_display": {"size": 100, "bold": False, "path": c.FONT_PATH_MAP},
            
            # --- NEW: Dedicated UI Fonts ---
            "date_bar": {"size": 24, "bold": False, "path": c.FONT_PATH_DATE},
            "top_bar_country": {"size": 32, "bold": False, "path": c.FONT_PATH_TOP_COUNTRY},
            "resource_hud": {"size": 18, "bold": False, "path": c.FONT_PATH_RESOURCES},
            # fonts.get("title")
            # --- NEW: Production HUD mapping ---
            "production_hud": {"size": 28, "bold": False, "path": c.FONT_PATH_RESOURCES},
        }

    def init_fonts(self, font_path=None):
        """
        Call this once in main.py after pygame.init().
        Pass a path like "assets/fonts/myfont.ttf" to use a custom font.
        """
        self.font_path = font_path
        self.cache.clear()

    def _open(self, path, size, bold):
        """Loads a font file with the fallback font behind it, or the system font without a path."""
        if path:
            try:
                font = pygame.font.Font(path, size)
                if bold:
                    font.set_bold(True)
                return FallbackFont(font, c.FONT_PATH_FALLBACK, size, bold)
            except Exception as e:
                print(f"Failed to load custom font ({e}). Falling back to SysFont.")
        return pygame.font.SysFont("Arial", size, bold=bold)

    def get(self, preset_name):
        """Retrieves a cached font based on the preset name."""
        if preset_name not in self.presets:
            print(f"Warning: Font preset '{preset_name}' not found. Defaulting to 'normal'.")
            preset_name = "normal"
            
        if preset_name not in self.cache:
            settings = self.presets[preset_name]
            size = settings["size"]
            bold = settings.get("bold", False)
            
            # Check if the preset specifies a custom path, otherwise use the global font_path
            preset_path = settings.get("path", self.font_path)
            self.cache[preset_name] = self._open(preset_path, size, bold)
                
        return self.cache[preset_name]

    def get_size(self, size, bold=False):
        """Retrieves a cached font at an explicit point size."""
        size = int(size)
        cache_key = ("explicit", size, bool(bold))
        if cache_key not in self.cache:
            self.cache[cache_key] = self._open(self.font_path, size, bold)
        return self.cache[cache_key]

    def draw_text_with_shadow(self, surface, text, x, y, preset_name="normal", text_color=(255, 255, 255), shadow_color=(0, 0, 0), offset=1):
        """Helper to draw text with a drop shadow."""
        font = self.get(preset_name)
        shadow_surf = font.render(text, True, shadow_color)
        text_surf = font.render(text, True, text_color)
        surface.blit(shadow_surf, (x + offset, y + offset))
        surface.blit(text_surf, (x, y))
        return text_surf.get_width(), text_surf.get_height()

# Create a global instance that other files can import
fonts = FontManager()
