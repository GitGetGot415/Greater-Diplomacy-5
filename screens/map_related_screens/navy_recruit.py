from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from screens.map_related_screens import recruit_ui
import pygame

class Navy_Recruit_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 30, 60) # Deep Navy Blue tint
        self.target_province = None
        self.map_screen = None
        self.cancel_hitboxes = []

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_map),
            Button(300, 300, "large", "blue", "Patrol Boat (200g)", self.buy_boat),
            Button(300, 400, "large", "blue", "Frigate (800g)", self.buy_frigate)
        ]

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                mouse_pos = pygame.mouse.get_pos()
                for rect, index in self.cancel_hitboxes:
                    if rect.collidepoint(mouse_pos):
                        self.cancel_order(index)
                        return
            
            for element in self.elements:
                element.handle_event(event)

    def cancel_order(self, index):
        if self.target_province:
            queue = self.target_province.get("deployment_queue", [])
            if 0 <= index < len(queue):
                removed = queue.pop(index)
                self.map_screen.show_feedback(f"Cancelled {removed['unit_type']}")

    def buy_boat(self):
        order = {"unit_type": "Chadian Patrol Boat", "days_remaining": 10}
        self.target_province["deployment_queue"].append(order)
        self.map_screen.show_feedback("Boat Ordered!")

    def buy_frigate(self):
        order = {"unit_type": "Libyan Frigate", "days_remaining": 25}
        self.target_province["deployment_queue"].append(order)
        self.map_screen.show_feedback("Frigate Ordered!")

    def additional_draw(self, surface):
        if self.target_province:
            font = pygame.font.SysFont("Arial", 32)
            title = f"Naval Shipyard: Province {self.target_province['id']}"
            txt_surf = font.render(title, True, (255, 255, 255))
            surface.blit(txt_surf, (SCREEN_WIDTH//2 - txt_surf.get_width()//2, 50))

            # Use the shared UI component for the queue
            self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)

    def exit_to_map(self):
        self.next_state = "MAP"
        self.done = True

    def handle_back_key(self):
        self.exit_to_map()