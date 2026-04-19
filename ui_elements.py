import pygame
from data.constants import SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.rendering.font_manager import fonts # <-- Import here

# --- Presets ---
COLORS = {
    "red": ((200, 0, 0), (255, 50, 50)),
    "orange": ((200, 100, 0), (255, 150, 50)),
    "yellow": ((200, 200, 0), (255, 255, 50)),
    "purple": ((200, 0, 200), (255, 50, 255)),
    "pink": ((200, 100, 100), (255, 150, 150)),
    "green": ((0, 150, 0), (0, 200, 0)),
    "light_blue": ((100, 100, 200), (150, 150, 255)),
    "blue": ((0, 0, 200), (50, 50, 255)),
    "grey": ((100, 100, 100), (150, 150, 150))
}

SIZES = {
    "small_square": (40, 40),
    "tech_square": (80, 80),
    "small": (100, 40),
    "left_ui_bar": (120, 50),
    "medium": (200, 50),
    "large": (300, 80)
}

# Global sound variables to be loaded in main.py
click_sound = None
slider_sound = None

def parse_pos(val, limit, size):
    """
    Handles 'centered', 'centered + 100', or raw numbers.
    limit: The screen width or height.
    size: The width or height of the button.
    """
    if isinstance(val, str):
        if "centered" in val:
            base = (limit / 2) - (size / 2)
            if "+" in val:
                return base + int(val.split("+")[-1])
            if "-" in val:
                return base - int(val.split("-")[-1])
            return base
    return val

class Button:
    def __init__(self, x, y, size_preset, color_preset, text, callback, image=None, show_text=True):
        self.width, self.height = SIZES.get(size_preset, (200, 50))
        final_x = parse_pos(x, SCREEN_WIDTH, self.width)
        final_y = parse_pos(y, SCREEN_HEIGHT, self.height)
        self.rect = pygame.Rect(final_x, final_y, self.width, self.height)
        
        self.color, self.hover_color = COLORS.get(color_preset, COLORS["grey"])
        self.pressed_color = (max(0, self.color[0]-40), max(0, self.color[1]-40), max(0, self.color[2]-40))
        
        self.text = text
        self.callback = callback
        self.image = image 
        self.show_text = show_text # Store the boolean

        self.font = fonts.get("button") # <-- NEW

        self.visible = True
        self.is_pressed = False
        
        # Add the selected state property
        self.is_selected = False

    def draw(self, surface):
        if not self.visible: return

        mouse_pos = pygame.mouse.get_pos()
        is_hovered = self.rect.collidepoint(mouse_pos)
        
        current_color = self.color
        if self.is_pressed and is_hovered: current_color = self.pressed_color
        elif is_hovered: current_color = self.hover_color
        
        # 1. Background Gradient & Outline
        # Check if the button has shading disabled; default to True if the attribute doesn't exist
        if getattr(self, 'shading', True):
            self.draw_gradient_rect(surface, current_color, self.rect)
        else:
            pygame.draw.rect(surface, current_color, self.rect)
        
        # Apply the highlight color and thickness if the button is selected
        if getattr(self, 'is_selected', False):
            border_color = (255, 215, 0) # Gold Highlight
            border_thickness = 3
        else:
            border_color = (255, 255, 255) if is_hovered else (20, 20, 20)
            border_thickness = 2
            
        pygame.draw.rect(surface, border_color, self.rect, border_thickness)

        # 2. Content Layout Logic
        # CASE A: Image exists and we WANT to show text alongside it
        if self.image and self.text and self.show_text:
            img_rect = self.image.get_rect(midleft=(self.rect.x + 10, self.rect.centery))
            surface.blit(self.image, img_rect)
            
            text_surf = self.font.render(self.text, True, (255, 255, 255))
            text_rect = text_surf.get_rect(midleft=(img_rect.right + 10, self.rect.centery))
            # Shadow
            shadow = self.font.render(self.text, True, (0, 0, 0))
            surface.blit(shadow, (text_rect.x + 1, text_rect.y + 1))
            surface.blit(text_surf, text_rect)
            
        # CASE B: Image exists and we either have no text OR show_text is False
        elif self.image:
            # Center just the icon
            img_rect = self.image.get_rect(center=self.rect.center)
            surface.blit(self.image, img_rect)
            
        # CASE C: No image, just show text (centered)
        elif self.text:
            text_surf = self.font.render(self.text, True, (255, 255, 255))
            text_rect = text_surf.get_rect(center=self.rect.center)
            shadow = self.font.render(self.text, True, (0, 0, 0))
            surface.blit(shadow, (text_rect.x + 1, text_rect.y + 1))
            surface.blit(text_surf, text_rect)

    def draw_gradient_rect(self, surface, color, rect):
        """Draws a simple vertical gradient from light to dark."""
        hi = 30
        low = 50
        # Top color (brighter)
        c1 = (min(255, color[0] + hi), min(255, color[1] + hi), min(255, color[2] + hi))
        # Bottom color (darker)
        c2 = (max(0, color[0] - low), max(0, color[1] - low), max(0, color[2] - low))
        
        for i in range(rect.height):
            # Linearly interpolate between c1 and c2
            lerp = i / rect.height
            r = int(c1[0] + (c2[0] - c1[0]) * lerp)
            g = int(c1[1] + (c2[1] - c1[1]) * lerp)
            b = int(c1[2] + (c2[2] - c1[2]) * lerp)
            pygame.draw.line(surface, (r, g, b), (rect.x, rect.y + i), (rect.right - 1, rect.y + i))

    def handle_event(self, event):
        if not self.visible: return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.is_pressed = True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_pressed:
                self.is_pressed = False
                if self.rect.collidepoint(event.pos):
                    # --- PLAY CLICK SOUND ---
                    if click_sound:
                        # Get volume from the active state (which inherits from GameState)
                        # This assumes 'self' is in a state with access to volume
                        click_sound.play()
                    self.callback()

class Slider:
    def __init__(self, x, y, width, text, initial_val, callback):
        self.rect = pygame.Rect(x, y, width, 20)
        self.handle_rect = pygame.Rect(x + (width * initial_val) - 10, y - 5, 20, 30)
        self.text = text
        self.callback = callback
        self.value = initial_val
        self.dragging = False
        self.visible = True

    def draw(self, surface):
        pygame.draw.rect(surface, (100, 100, 100), self.rect) # Track
        pygame.draw.rect(surface, (200, 200, 200), self.handle_rect) # Handle
        
        slider_font = fonts.get("normal") # <-- NEW (Renamed to avoid shadowing)

        txt = slider_font.render(f"{self.text}: {int(self.value * 100)}%", True, (255, 255, 255))
        surface.blit(txt, (self.rect.x, self.rect.y - 25))

    def handle_event(self, event):

        if not self.visible: return # Don't click if hidden
        
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.callback()
        """

        if event.type == pygame.MOUSEBUTTONDOWN and self.handle_rect.collidepoint(event.pos):
            self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            # Constrain movement to the bar
            self.handle_rect.centerx = max(self.rect.left, min(event.pos[0], self.rect.right))
            self.value = (self.handle_rect.centerx - self.rect.left) / self.rect.width
            self.callback(self.value)
            if slider_sound:
                slider_sound.play()