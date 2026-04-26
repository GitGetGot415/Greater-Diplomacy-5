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
        self.master_volume = 0.5

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        pass

    def draw(self, surface):
        # 1. Fill background
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