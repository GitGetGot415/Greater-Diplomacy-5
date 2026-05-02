import pygame
import pygame.scrap
import data.constants as c
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import symbol_loader

# Global sound & icon variables to be loaded in main.py
click_sound = None
slider_sound = None
UI_ICONS = {}

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
        self.width, self.height = c.SIZES.get(size_preset, (200, 50))
        final_x = parse_pos(x, c.SCREEN_WIDTH, self.width)
        final_y = parse_pos(y, c.SCREEN_HEIGHT, self.height)
        self.rect = pygame.Rect(final_x, final_y, self.width, self.height)
        
        self.color, self.hover_color = c.UI_COLORS.get(color_preset, c.UI_COLORS["grey"])
        self.pressed_color = (max(0, self.color[0]-40), max(0, self.color[1]-40), max(0, self.color[2]-40))
        
        self.text = text
        self.callback = callback
        self.image = image 
        self.show_text = show_text # Store the boolean

        self.font = fonts.get("button")

        self.visible = True
        self.is_pressed = False
        
        self.is_selected = False
        self.disabled = False

    def draw(self, surface):
        if not self.visible: return

        mouse_pos = pygame.mouse.get_pos()
        is_hovered = self.rect.collidepoint(mouse_pos)
        
        current_color = self.color
        if getattr(self, 'disabled', False): current_color = c.UI_COLORS["grey"][0]
        elif self.is_pressed and is_hovered: current_color = self.pressed_color
        elif is_hovered: current_color = self.hover_color
        
        # 1. Background Gradient & Outline
        # Check if the button has shading disabled; default to True if the attribute doesn't exist
        if getattr(self, 'shading', True):
            self.draw_gradient_rect(surface, current_color, self.rect)
        else:
            pygame.draw.rect(surface, current_color, self.rect)
        
        # Apply the highlight color and thickness if the button is selected
        if getattr(self, 'is_selected', False):
            border_color = c.COLOR_GOLD_HIGHLIGHT # Gold Highlight
            border_thickness = 3
        else:
            if getattr(self, 'disabled', False):
                border_color = c.COLOR_DIM_BORDER # Dimmer border
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
        if not self.visible or getattr(self, 'disabled', False): return

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
        if not self.visible: return
        
        pygame.draw.rect(surface, c.COLOR_SLIDER_TRACK, self.rect) # Track
        pygame.draw.rect(surface, c.COLOR_SLIDER_HANDLE, self.handle_rect) # Handle
        
        slider_font = fonts.get("normal")

        # Strip the percentage display if we're rendering a discrete count like "Players"
        if self.text.startswith("Players"):
            txt = slider_font.render(self.text, True, (255, 255, 255))
        else:
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

def process_text_input(event, current_text, max_length=None, validation_func=None):
    """
    Handles standard Pygame text input.
    Returns the updated string and a status flag ('TYPING', 'SUBMIT', or 'CANCEL').
    """
    if event.type != pygame.KEYDOWN:
        return current_text, "TYPING"

    if event.key == pygame.K_BACKSPACE:
        return current_text[:-1], "TYPING"
    elif event.key == pygame.K_RETURN:
        return current_text, "SUBMIT"
    elif event.key == pygame.K_ESCAPE:
        return current_text, "CANCEL"
    elif event.key == pygame.K_v and (pygame.key.get_mods() & pygame.KMOD_CTRL or pygame.key.get_mods() & pygame.KMOD_GUI):
        # Handle Ctrl+V (or CMD+V) Paste
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            clip_bytes = pygame.scrap.get(pygame.SCRAP_TEXT)
            if clip_bytes:
                clip_str = clip_bytes.decode('utf-8', errors='ignore').replace('\x00', '')
                for char in clip_str:
                    # Check length constraint before adding the char
                    if max_length is not None and len(current_text) >= max_length:
                        break
                        
                    # Check character validity
                    if validation_func:
                        if validation_func(char):
                            current_text += char
                    elif char.isprintable(): # Default safe check
                        current_text += char
        except Exception as e:
            print(f"Paste Error: {e}")
        return current_text, "TYPING"
    else:
        # Check length constraint
        if max_length is not None and len(current_text) >= max_length:
            return current_text, "TYPING"

        char = event.unicode
        
        # Check character validity
        if validation_func:
            if not validation_func(char):
                return current_text, "TYPING"
        elif not char.isprintable(): # Default safe check
            return current_text, "TYPING"

        return current_text + char, "TYPING"

def draw_resource_string(surface, font, base_text, mat, man, fuel, x, y, color, is_yield=False):
    """Helper function to blit image icons directly into the string, hiding zero values."""
    base_surf = font.render(base_text, True, color)
    surface.blit(base_surf, (x, y))
    curr_x = x + base_surf.get_width()
    
    icons = [("Iron", mat), ("Infantry", man), ("Oil", fuel)]
    drawn_any = False
    
    for icon_name, val in icons:
        # Skip drawing if the cost/yield is zero
        try:
            if float(val) == 0:
                continue
        except (ValueError, TypeError):
            continue
            
        drawn_any = True
        display_val = str(val)
        
        # Format positive yields with a '+'
        if is_yield and float(val) > 0 and not display_val.startswith("+"):
            display_val = f"+{display_val}"

        icon_surf = symbol_loader.SYMBOLS.get(icon_name)
        if icon_surf:
            icon_surf = pygame.transform.smoothscale(icon_surf, (16, 16))
            surface.blit(icon_surf, (curr_x, y + 2))
            curr_x += 20
        
        val_surf = font.render(f"{display_val}   ", True, color)
        surface.blit(val_surf, (curr_x, y))
        curr_x += val_surf.get_width()
        
    # Handle the edge case where everything costs 0 or yields 0
    if not drawn_any:
        fallback_text = "None" if is_yield else "Free"
        val_surf = font.render(fallback_text, True, color)
        surface.blit(val_surf, (curr_x, y))

def draw_combat_stats(surface, font, base_text, atk, df, hp, spd, x, y, color):
    """Helper function to blit combat stat icons directly into the string."""
    base_surf = font.render(base_text, True, color)
    surface.blit(base_surf, (x, y))
    curr_x = x + base_surf.get_width()

    icons = [
        (c.ICON_ATTACK, atk, "ATK:"), 
        (c.ICON_DEFENSE, df, "DEF:"), 
        (c.ICON_HEALTH, hp, "HP:"), 
        (c.ICON_SPEED, spd, "SPD:")
    ]

    for icon_name, val, prefix in icons:
        icon_surf = symbol_loader.SYMBOLS.get(icon_name)
        if icon_surf:
            # Scale the icon to roughly match the height of the font
            icon_h = max(16, font.get_height())
            icon_surf = pygame.transform.smoothscale(icon_surf, (icon_h, icon_h))
            surface.blit(icon_surf, (curr_x, y + 2))
            curr_x += icon_h + 4
        
        val_surf = font.render(f"{prefix} {val}   ", True, color)
        surface.blit(val_surf, (curr_x, y))
        curr_x += val_surf.get_width()