from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from screens.map_related_screens import recruit_ui  # Import the new UI helper
import pygame

class Recruit_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.target_province = None
        self.cancel_hitboxes = [] # Store rects from the UI helper

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                # Check if an "X" was clicked
                mouse_pos = pygame.mouse.get_pos()
                for rect, index in self.cancel_hitboxes:
                    if rect.collidepoint(mouse_pos):
                        self.cancel_order(index)
                        return # Exit early to avoid multiple clicks

            # Standard button handling
            for element in self.elements:
                element.handle_event(event)

    def cancel_order(self, index):
        if self.target_province:
            queue = self.target_province.get("deployment_queue", [])
            if 0 <= index < len(queue):
                removed_item = queue.pop(index)
                # Logic for refunding (if you have a gold variable)
                # self.map_screen.player_gold += removed_item.get('cost', 0)
                self.map_screen.show_feedback(f"Cancelled {removed_item['unit_type']}")

    def additional_draw(self, surface):
        if self.target_province:
            # Draw the UI and catch the list of button rectangles
            self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        
        # Define buttons specifically for this screen
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_map),
            Button(300, 300, "large", "green", "Recruit Hilux (100g)", self.buy_toyota),
            Button(300, 400, "large", "blue", "Recruit T-55 (300g)", self.buy_tank)
        ]

    def buy_toyota(self):
        if self.target_province:
            order = {"unit_type": "Chadian Toyota Hilux", "days_remaining": 5}
            self.target_province["deployment_queue"].append(order)
            self.map_screen.show_feedback("Hilux Ordered!")

    def buy_tank(self):
        if self.target_province:
            order = {"unit_type": "Libyan T-55", "days_remaining": 10}
            self.target_province["deployment_queue"].append(order)
            self.map_screen.show_feedback("T-55 Ordered!")

    """def additional_draw(self, surface):
        if self.target_province:
            # Draw the Screen Title
            font = pygame.font.SysFont("Arial", 42)
            title_surf = font.render(f"Province {self.target_province['id']} Arsenal", True, (255, 255, 255))
            surface.blit(title_surf, (SCREEN_WIDTH//2 - title_surf.get_width()//2, 40))

            # Call the drawing code from the same folder
            recruit_ui.draw_recruitment_overlay(surface, self.target_province)"""

    def exit_to_map(self):
        self.next_state = "MAP"
        self.done = True

    def handle_back_key(self):
        self.exit_to_map()