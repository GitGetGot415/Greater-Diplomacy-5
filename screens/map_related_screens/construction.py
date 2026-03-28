import pygame
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from map_functions.data.building_data import BUILDING_LIBRARY
from screens.map_related_screens import recruit_ui

class Construction_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 40, 30)
        self.target_province = None
        self.map_screen = None
        self.cancel_hitboxes = []

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, 50, "small", "red", "Back", self.exit_to_map)]
        current_buildings = self.target_province.get("buildings", [])
        y_offset = 150

        categories = {
            "Industry": ["Workshop Lvl 1", "Workshop Lvl 2", "Workshop Lvl 3", "Workshop Lvl 4", "Workshop Lvl 5", "Basic Factory", "Factory Lvl 1", "Factory Lvl 2", "Factory Lvl 3", "Factory Lvl 4", "Factory Lvl 5"],
            "Refinery": ["Synthetic Refinery Lvl 1", "Synthetic Refinery Lvl 2", "Synthetic Refinery Lvl 3"]
        }

        for cat_name, b_list in categories.items():
            target = None
            
            # Check if ANY building of this group already exists
            # We determine the 'group' by checking the first item in the list's group in BUILDING_LIBRARY
            sample_b = b_list[0]
            group_id = BUILDING_LIBRARY[sample_b]["group"]
            
            owned_in_group = [b for b in current_buildings if BUILDING_LIBRARY.get(b, {}).get("group") == group_id]
            
            if not owned_in_group:
                # If nothing owned in group, Level 1 is the target
                target = b_list[0]
            else:
                # Find the building immediately following the highest one we own
                # (Assuming b_list is ordered by tier)
                for i, b_name in enumerate(b_list):
                    if b_name in owned_in_group:
                        if i + 1 < len(b_list):
                            target = b_list[i+1]
                        # else: MAX LEVEL (target remains None)

            if target:
                data = BUILDING_LIBRARY[target]
                txt = f"{target} ({data['cost']}g, {data['time']}d)"
                self.elements.append(Button(100, y_offset, "large", "blue", txt, lambda t=target: self.start_construction(t)))
                y_offset += 100

    def start_construction(self, b_name):
        data = BUILDING_LIBRARY[b_name]
        
        # Check if already building something in this group
        queue = self.target_province.get("deployment_queue", [])
        if any(q.get("group") == data["group"] for q in queue):
            self.map_screen.show_feedback("Group already under construction!")
            return

        if self.map_screen.player_money >= data["cost"]:
            self.map_screen.player_money -= data["cost"]
            order = {
                "order_type": "BUILDING",
                "item_name": b_name,
                "days_remaining": data["time"],
                "group": data["group"]
            }
            self.target_province.setdefault("deployment_queue", []).append(order)
            self.map_screen.show_feedback(f"Started {b_name}")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Not enough money!")

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
        queue = self.target_province.get("deployment_queue", [])
        if 0 <= index < len(queue):
            # Building refund logic can be added here
            queue.pop(index)
            self.refresh_ui()

    def additional_draw(self, surface):
        if self.target_province:
            # Use unit UI helper to show building queue too
            self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)
            
            font = pygame.font.SysFont("Arial", 32)
            title = f"Construction: Province {self.target_province['id']}"
            txt_surf = font.render(title, True, (255, 255, 255))
            surface.blit(txt_surf, (SCREEN_WIDTH//2 - txt_surf.get_width()//2, 50))

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()