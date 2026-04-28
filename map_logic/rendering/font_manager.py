import pygame
import data.constants as c

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
            "research_year": {"size": 28, "bold": False},
            "heading2": {"size": 28, "bold": False},
            "heading1": {"size": 32, "bold": False},
            "title": {"size": 40, "bold": False},
            # Map names get a specific font path override here
            "country_name_display": {"size": 100, "bold": False, "path": c.FONT_PATH_MAP},
            # fonts.get("title")
        }

    def init_fonts(self, font_path=None):
        """
        Call this once in main.py after pygame.init().
        Pass a path like "assets/fonts/myfont.ttf" to use a custom font.
        """
        self.font_path = font_path
        self.cache.clear()

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
            
            if preset_path:
                try:
                    # Load from a custom .ttf file
                    font = pygame.font.Font(preset_path, size)
                    if bold: font.set_bold(True)
                    self.cache[preset_name] = font
                except Exception as e:
                    print(f"Failed to load custom font ({e}). Falling back to SysFont.")
                    self.cache[preset_name] = pygame.font.SysFont("Arial", size, bold=bold)
            else:
                # Default fallback
                self.cache[preset_name] = pygame.font.SysFont("Arial", size, bold=bold)
                
        return self.cache[preset_name]

# Create a global instance that other files can import
fonts = FontManager()