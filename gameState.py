import pygame

# Default Keybinds
DEFAULT_KEYS = {
    "BACK": pygame.K_ESCAPE,
    "NEXT_TURN": pygame.K_SPACE,
    "ORDERS": pygame.K_q
}

class GameState:
    def __init__(self):
        self.done = False
        self.next_state = None
        self.elements = []
        self.bg_image_path = None # Added support for generic background images

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        pass

    def draw(self, surface):
        # 1. Fill background or draw background image
        if getattr(self, 'bg_image_path', None):
            import data.constants as c
            from ui.bars import ui_bars
            bg_img = ui_bars.get_ui_image(self.bg_image_path, directory=c.BACKGROUNDS_DIR)
            if bg_img.get_size() != surface.get_size():
                bg_img = pygame.transform.scale(bg_img, surface.get_size())
            surface.blit(bg_img, (0, 0))
        else:
            surface.fill(getattr(self, 'bg_color', (30, 30, 30)))
        
        # 2. Draw the specific screen content (Map, UI Bars)
        # Moving this BEFORE elements fixes the layering
        self.additional_draw(surface)
        
        # 3. Draw UI buttons on the very top
        for el in self.elements:
            el.draw(surface)

    def additional_draw(self, surface):
        pass

    def update(self):
        pass