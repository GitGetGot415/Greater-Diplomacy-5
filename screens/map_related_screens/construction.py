import pygame
import json
import os
from gameState import GameState
from data.constants import SCREEN_WIDTH, SCREEN_HEIGHT, DAYS_PER_TURN, BUILDING_DATA_PATH
from ui_elements import Button
from screens.map_related_screens import recruit_ui
from map_functions.rendering.font_manager import fonts
from map_functions.rendering import symbol_loader
from map_functions.logic import state_queries

class Construction_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (30, 25, 20)
        self.target_province = None
        self.map_screen = None
        self.cancel_hitboxes = []
        self.building_library = self.load_building_data()
        self.active_bars = []
        
        self.other_start_y = self.other_end_y = 0
        self.fuel_start_y = self.fuel_end_y = 0

    def load_building_data(self):
        path = BUILDING_DATA_PATH
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return {}

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.building_library = self.load_building_data()
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]
        current_buildings = self.target_province.get("buildings", [])
        queue = self.target_province.get("deployment_queue", [])
        player_research = self.map_screen.nation_data[self.map_screen.player_country].get("research", {})

        self.active_bars = []
        y_offset = 120
        x_pos = 50

        # Define category groups manually
        groups = {
            "Other": ["industry"],
            "Fuel": ["refinery"]
        }

        def process_categories(cat_groups, is_fuel):
            nonlocal y_offset
            for group_id in cat_groups:
                b_list = [b for b, d in self.building_library.items() if d.get("group") == group_id]
                target = None
                owned_in_group = [b for b in current_buildings if self.building_library.get(b, {}).get("group") == group_id]

                if not owned_in_group:
                    target = b_list[0] if b_list else None
                else:
                    for i, b_name in enumerate(b_list):
                        if b_name in owned_in_group:
                            if i + 1 < len(b_list):
                                target = b_list[i+1]

                if target:
                    data = self.building_library[target]
                    is_building = any(q.get("group") == data["group"] for q in queue)
                    req_tech, req_lvl = state_queries.get_building_required_tech(target)

                    # --- CHANGED LOGIC HERE ---
                    # If we don't have the tech, skip this group entirely
                    if req_tech and player_research.get(req_tech, 0) < req_lvl:
                        continue 

                    # We no longer need the 'elif', just use a standard 'if'
                    if is_building:
                        btn_txt = "Building..."
                        cb = lambda: None
                        btn_color = "grey"
                    else:
                        btn_txt = target
                        cb = lambda t=target: self.start_construction(t)
                        btn_color = "purple" if is_fuel else "orange"
                    # --------------------------

                    btn = Button(x_pos, y_offset, "medium", btn_color, btn_txt, cb)
                    self.elements.append(btn)

                    # Store stats to draw the bar later
                    bar_rect = pygame.Rect(x_pos + 210, y_offset, 550, 50)
                    self.active_bars.append((bar_rect, data))

                    y_offset += 60

        # --- 1. Process Other (Orange) ---
        self.other_start_y = y_offset
        process_categories(groups["Other"], is_fuel=False)
        self.other_end_y = y_offset

        # --- 2. Process Fuel (Purple) ---
        y_offset += 30
        self.fuel_start_y = y_offset
        process_categories(groups["Fuel"], is_fuel=True)
        self.fuel_end_y = y_offset

    def start_construction(self, b_name):
        data = self.building_library[b_name]
        p_data = self.map_screen.nation_data[self.map_screen.player_country]

        costs = {
            "manpower": data.get("cost_manpower", 0),
            "materials": data.get("cost_materials", 0),
            "fuel": data.get("cost_fuel", 0)
        }

        if all(p_data.get(res, 0) >= amount for res, amount in costs.items()):
            for res, amount in costs.items(): p_data[res] -= amount
            order = {
                "order_type": "BUILDING",
                "item_name": b_name,
                "turns_remaining": max(1, data.get("time", DAYS_PER_TURN) // DAYS_PER_TURN),
                "group": data["group"],
                "refund": costs
            }
            self.target_province.setdefault("deployment_queue", []).append(order)
            self.map_screen.show_feedback(f"Started {b_name}")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def draw_resource_string(self, surface, font, base_text, mat, man, fuel, x, y, color, is_yield=False):
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

    def additional_draw(self, surface):
        if not self.target_province: return
        
        title_font = fonts.get("heading1")
        surface.blit(title_font.render("CONSTRUCTION & CIVIL WORKS", True, (255, 255, 255)), (150, 25))

        # --- Draw Orange Background for General ---
        if self.other_end_y > self.other_start_y:
            land_rect = pygame.Rect(30, self.other_start_y - 15, 840, self.other_end_y - self.other_start_y + 15)
            pygame.draw.rect(surface, (60, 40, 20), land_rect)
            pygame.draw.rect(surface, (200, 100, 30), land_rect, 2)
            lbl = fonts.get("heading2").render("GENERAL BUILDINGS", True, (255, 150, 50))
            surface.blit(lbl, (40, self.other_start_y - 45))

        # --- Draw Purple Background for Fuel ---
        if self.fuel_end_y > self.fuel_start_y:
            navy_rect = pygame.Rect(30, self.fuel_start_y - 15, 840, self.fuel_end_y - self.fuel_start_y + 15)
            pygame.draw.rect(surface, (50, 30, 60), navy_rect)
            pygame.draw.rect(surface, (150, 50, 200), navy_rect, 2)
            lbl = fonts.get("heading2").render("FUEL REFINERIES", True, (200, 100, 255))
            surface.blit(lbl, (40, self.fuel_start_y - 45))

        # --- Draw Custom UI Bars Next to Buttons ---
        bar_font = fonts.get("small")
        for bar_rect, stats in self.active_bars:
            pygame.draw.rect(surface, (40, 40, 40), bar_rect)
            pygame.draw.rect(surface, (100, 100, 100), bar_rect, 1)
            
            t = max(1, stats.get('time', DAYS_PER_TURN) // DAYS_PER_TURN)
            
            self.draw_resource_string(
                surface, bar_font, f"Build Time: {t} turns   |   Cost: ",
                stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0),
                bar_rect.x + 15, bar_rect.y + 6, (255, 215, 0)
            )
            self.draw_resource_string(
                surface, bar_font, f"Yield (Per Turn):   ",
                stats.get('prod_materials', 0), stats.get('prod_manpower', 0), stats.get('prod_fuel', 0),
                bar_rect.x + 15, bar_rect.y + 26, (150, 255, 150), is_yield=True
            )

        # --- Draw HUD ---
        hud_rect = pygame.Rect(0, SCREEN_HEIGHT - 60, SCREEN_WIDTH, 60)
        pygame.draw.rect(surface, (30, 30, 30), hud_rect)
        pygame.draw.line(surface, (100, 100, 100), (0, hud_rect.y), (SCREEN_WIDTH, hud_rect.y), 2)

        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_font = fonts.get("heading2")
        resources = [
            (f"Manpower: {p_data.get('manpower', 0)}", (100, 200, 255)),
            (f"Materials: {p_data.get('materials', 0)}", (180, 180, 180)),
            (f"Fuel: {p_data.get('fuel', 0)}", (200, 100, 255))
        ]
        for i, (text, color) in enumerate(resources):
            surface.blit(res_font.render(text, True, color), (50 + (i * 300), hud_rect.y + 15))

        # --- Draw Queue ---
        self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                for rect, index in self.cancel_hitboxes:
                    if rect.collidepoint(event.pos):
                        self.cancel_order(index)
                        return
            for element in self.elements:
                element.handle_event(event)

    def cancel_order(self, index):
        queue = self.target_province.get("deployment_queue", [])
        if 0 <= index < len(queue):
            item = queue.pop(index)
            p_data = self.map_screen.nation_data[self.map_screen.player_country]
            
            # --- REFUND LOGIC ---
            if "refund" in item:
                # Use the stored costs
                for res, amount in item["refund"].items():
                    p_data[res] = p_data.get(res, 0) + amount
            else:
                # Fallback for old save files
                stats = {}
                if item.get("order_type") == "BUILDING":
                    stats = self.building_library.get(item.get("item_name"), {})
                elif "unit_type" in item:
                    import json, os
                    if os.path.exists('data/json/unit_data.json'):
                        with open('data/json/unit_data.json', 'r') as f:
                            stats = json.load(f).get(item["unit_type"], {})
                            
                p_data["materials"] = p_data.get("materials", 0) + stats.get("cost_materials", 0)
                p_data["manpower"] = p_data.get("manpower", 0) + stats.get("cost_manpower", 0)
                p_data["fuel"] = p_data.get("fuel", 0) + stats.get("cost_fuel", 0)

            self.map_screen.show_feedback("Cancelled & Refunded")
            self.refresh_ui()

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()