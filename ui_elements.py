import pygame
import gameState as g

# --- Presets ---
COLORS = {
    "red": ((200, 0, 0), (255, 50, 50)),
    "green": ((0, 150, 0), (0, 200, 0)),
    "blue": ((0, 0, 150), (50, 50, 255)),
    "grey": ((100, 100, 100), (150, 150, 150))
}

SIZES = {
    "small": (100, 40),
    "medium": (200, 50),
    "large": (300, 80)
}

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
    def __init__(self, x, y, size_preset, color_preset, text, callback):
        self.width, self.height = SIZES.get(size_preset, (200, 50))
        final_x = parse_pos(x, g.SCREEN_WIDTH, self.width)
        final_y = parse_pos(y, g.SCREEN_HEIGHT, self.height)
        self.rect = pygame.Rect(final_x, final_y, self.width, self.height)
        
        self.color, self.hover_color = COLORS.get(color_preset, COLORS["grey"])
        # Add a "pressed" color variant (slightly darker)
        self.pressed_color = (max(0, self.color[0]-40), max(0, self.color[1]-40), max(0, self.color[2]-40))
        
        self.text = text
        self.callback = callback
        self.font = pygame.font.SysFont("Arial", 24)
        self.visible = True
        self.is_pressed = False # Tracks if we are currently holding the button down

    def draw(self, surface):
        if not self.visible: return

        mouse_pos = pygame.mouse.get_pos()
        is_hovered = self.rect.collidepoint(mouse_pos)
        
        # Determine color based on state
        if self.is_pressed and is_hovered:
            current_color = self.pressed_color
        elif is_hovered:
            current_color = self.hover_color
        else:
            current_color = self.color
        
        pygame.draw.rect(surface, current_color, self.rect)
        
        # Draw a small border if pressed for visual feedback
        if self.is_pressed and is_hovered:
            pygame.draw.rect(surface, (255, 255, 255), self.rect, 2)

        text_surf = self.font.render(self.text, True, (255, 255, 255))
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)

    def handle_event(self, event):
        if not self.visible: return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.is_pressed = True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_pressed:
                self.is_pressed = False
                # Final check: only trigger if mouse is released while still over the button
                if self.rect.collidepoint(event.pos):
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
        
        font = pygame.font.SysFont("Arial", 18)
        txt = font.render(f"{self.text}: {int(self.value * 100)}%", True, (255, 255, 255))
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