import pygame
import json
import os
import re
import math
from gameState import GameState
from data.constants import SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from screens.map_related_screens import recruit_ui
from map_functions.rendering.font_manager import fonts
from map_functions.rendering import symbol_loader

class Recruit_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 25, 20)
        self.target_province = None
        self.map_screen = None
        self.cancel_hitboxes = []
        
        # Load both libraries generically
        self.unit_library = self.load_json('data/json/unit_data.json')
        self.tech_tree = self.load_json('data/json/research_template.json') # <-- NEW
        
        self.infantry_groups, self.tank_groups, self.navy_groups = self.get_ordered_groups()
        self.active_bars = []
        
        self.infantry_start_y = self.infantry_end_y = 0
        self.tank_start_y = self.tank_end_y = 0
        self.navy_start_y = self.navy_end_y = 0

    def load_json(self, path):
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return {}

    def load_unit_data(self):
        path = 'data/json/unit_data.json'
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return {}

    def get_group_name(self, name):
        # We strip the year off the infantry so they all group properly!
        base = re.sub(r'\s+\d{4}$', '', name)
        return re.sub(r'\s+[IVXLCDM]+$', '', base).strip()

    def get_ordered_groups(self):
        infantry_groups, tank_groups, navy_groups = [], [], []
        for name, stats in self.unit_library.items():
            base = self.get_group_name(name)
            if stats.get("naval_unit", False):
                if base not in navy_groups: navy_groups.append(base)
            elif "Tank" in base or "Armored Car" in base:
                if base not in tank_groups: tank_groups.append(base)
            else:
                if base not in infantry_groups: infantry_groups.append(base)
        return infantry_groups, tank_groups, navy_groups

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]
        player_research = self.map_screen.nation_data[self.map_screen.player_country].get("research", {})

        self.active_bars = []
        y_offset = 120
        x_pos = 50

        def process_groups(groups, btn_color):
            nonlocal y_offset
            for group_name in groups:
                # --- OBSOLESCENCE CHECKS ---
                if group_name == "WW1 Armored Car" and player_research.get("armored_car", 0) >= 1:
                    continue
                if group_name == "WW1 Tank" and (player_research.get("medium_tank", 0) >= 1 or player_research.get("heavy_tank", 0) >= 1):
                    continue
                # ---------------------------

                highest_unlocked = None
                tech_key = group_name.lower().replace(" ", "_")
                researched_lvl = player_research.get(tech_key, 0)

                # --- NEW: Infantry & Cavalry Processing ---
                if tech_key == "infantry_type":
                    # Pull the array directly from the JSON template
                    inf_years = self.tech_tree.get("infantry_type", {}).get("years", [1850])
                    if researched_lvl > 0:
                        year = inf_years[min(researched_lvl - 1, len(inf_years)-1)]
                        highest_unlocked = f"Infantry Type {year}"
                elif tech_key == "cavalry":
                    if researched_lvl > 0:
                        highest_unlocked = "Cavalry"
                else:
                    group_units = [(n, s) for n, s in self.unit_library.items() if self.get_group_name(n) == group_name]
                    highest_lvl = -1
                    for name, stats in group_units:
                        lvl_str = name.replace(group_name, "").strip()
                        lvl = self.roman_to_int(lvl_str)
                        required_research = max(1, lvl) 
                        if researched_lvl >= required_research:
                            if lvl > highest_lvl:
                                highest_lvl = lvl
                                highest_unlocked = name

                if highest_unlocked:
                    lookup_name = highest_unlocked
                    
                    btn = Button(x_pos, y_offset, "medium", btn_color, 
                                 highest_unlocked, lambda n=lookup_name: self.buy_unit(n))
                    self.elements.append(btn)
                    
                    # Fetch stats from your newly hardcoded unit dictionary
                    stats = self.unit_library[lookup_name]
                    bar_rect = pygame.Rect(x_pos + 210, y_offset, 550, 50)
                    self.active_bars.append((bar_rect, stats))
                    
                    y_offset += 60

        # --- 1. Process Infantry Elements ---
        self.infantry_start_y = y_offset
        process_groups(self.infantry_groups, "green")
        self.infantry_end_y = y_offset

        # --- 2. Process Tank Elements ---
        y_offset += 30 
        self.tank_start_y = y_offset
        process_groups(self.tank_groups, "green")
        self.tank_end_y = y_offset

        # --- 3. Process Naval Elements (Only if coastal) ---
        y_offset += 30 
        if self.target_province.get("is_coastal", False):
            self.navy_start_y = y_offset
            process_groups(self.navy_groups, "blue")
            self.navy_end_y = y_offset
        else:
            self.navy_start_y = self.navy_end_y = y_offset

    def roman_to_int(self, s):
        if not s: return 0
        rom_val = {'I': 1, 'V': 5, 'X': 10}
        res, i = 0, 0
        while i < len(s):
            s1 = rom_val.get(s[i], 0)
            if i + 1 < len(s):
                s2 = rom_val.get(s[i+1], 0)
                if s1 >= s2: res += s1; i += 1
                else: res += s2 - s1; i += 2
            else: res += s1; i += 1
        return res

    def buy_unit(self, unit_name):
        stats = self.unit_library.get(unit_name)
        if not stats or not self.map_screen: return

        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        costs = {
            "manpower": stats.get("cost_manpower", 0),
            "materials": stats.get("cost_materials", 0),
            "fuel": stats.get("cost_fuel", 0)
        }

        if all(p_data.get(res, 0) >= amount for res, amount in costs.items()):
            for res, amount in costs.items(): p_data[res] -= amount
            order = {
                "unit_type": unit_name,
                "days_remaining": stats.get("production_time", 5),
                "refund": costs
            }
            self.target_province.setdefault("deployment_queue", []).append(order)
            self.map_screen.show_feedback(f"Production started: {unit_name}")
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def draw_resource_string(self, surface, font, base_text, mat, man, fuel, x, y, color):
        """Helper function to blit image icons directly into the string, hiding zero values."""
        base_surf = font.render(base_text, True, color)
        surface.blit(base_surf, (x, y))
        curr_x = x + base_surf.get_width()
        
        icons = [("Iron", mat), ("Infantry", man), ("Oil", fuel)]
        drawn_any = False

        for icon_name, val in icons:
            # Skip drawing if the cost is zero
            try:
                if float(val) == 0:
                    continue
            except (ValueError, TypeError):
                continue
                
            drawn_any = True
            icon_surf = symbol_loader.SYMBOLS.get(icon_name)
            if icon_surf:
                icon_surf = pygame.transform.smoothscale(icon_surf, (16, 16))
                surface.blit(icon_surf, (curr_x, y + 2))
                curr_x += 20
            
            val_surf = font.render(f"{val}   ", True, color)
            surface.blit(val_surf, (curr_x, y))
            curr_x += val_surf.get_width()

        # Handle edge case where a unit literally costs nothing
        if not drawn_any:
            val_surf = font.render("Free", True, color)
            surface.blit(val_surf, (curr_x, y))

    def additional_draw(self, surface):
        if not self.target_province: return
        
        title_font = fonts.get("heading1")
        surface.blit(title_font.render("RECRUITMENT & DOCKYARDS", True, (255, 255, 255)), (150, 25))

        # --- Draw Green Background for Infantry Forces ---
        if self.infantry_end_y > self.infantry_start_y:
            inf_rect = pygame.Rect(30, self.infantry_start_y - 15, 840, self.infantry_end_y - self.infantry_start_y + 15)
            pygame.draw.rect(surface, (30, 60, 30), inf_rect)
            pygame.draw.rect(surface, (50, 150, 50), inf_rect, 2)
            lbl = fonts.get("heading2").render("INFANTRY", True, (100, 255, 100))
            surface.blit(lbl, (40, self.infantry_start_y - 45))

        # --- Draw Darker Green Background for Tanks ---
        if self.tank_end_y > self.tank_start_y:
            tank_rect = pygame.Rect(30, self.tank_start_y - 15, 840, self.tank_end_y - self.tank_start_y + 15)
            pygame.draw.rect(surface, (20, 45, 20), tank_rect) 
            pygame.draw.rect(surface, (40, 120, 40), tank_rect, 2) 
            lbl = fonts.get("heading2").render("TANKS", True, (80, 200, 80))
            surface.blit(lbl, (40, self.tank_start_y - 45))

        # --- Draw Blue Background for Naval Forces ---
        if self.navy_end_y > self.navy_start_y:
            navy_rect = pygame.Rect(30, self.navy_start_y - 15, 840, self.navy_end_y - self.navy_start_y + 15)
            pygame.draw.rect(surface, (30, 30, 60), navy_rect)
            pygame.draw.rect(surface, (50, 50, 150), navy_rect, 2)
            lbl = fonts.get("heading2").render("NAVAL FORCES", True, (100, 150, 255))
            surface.blit(lbl, (40, self.navy_start_y - 45))

        # --- Draw Custom UI Bars Next to Buttons ---
        bar_font = fonts.get("small")
        for bar_rect, stats in self.active_bars:
            pygame.draw.rect(surface, (40, 40, 40), bar_rect)
            pygame.draw.rect(surface, (100, 100, 100), bar_rect, 1)
            
            t = stats.get('production_time', 0)
            
            self.draw_resource_string(
                surface, bar_font, f"Deploy: {t}d   |   Cost: ",
                stats.get('cost_materials', 0), stats.get('cost_manpower', 0), stats.get('cost_fuel', 0),
                bar_rect.x + 15, bar_rect.y + 6, (255, 215, 0)
            )
            
            txt2 = f"Combat Stats:   ⚔️ATK: {stats.get('attack', 0)}   🛡️DEF: {stats.get('defense', 0)}   ❤️HP: {stats.get('health', 0)}   ⚡SPD: {stats.get('speed', 0)}"
            surface.blit(bar_font.render(txt2, True, (200, 200, 200)), (bar_rect.x + 15, bar_rect.y + 26))

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
            for el in self.elements:
                el.handle_event(event)

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
                if "unit_type" in item:
                    stats = self.unit_library.get(item["unit_type"], {})
                elif item.get("order_type") == "BUILDING":
                    import json, os
                    if os.path.exists('data/building_data.json'):
                        with open('data/building_data.json', 'r') as f:
                            stats = json.load(f).get(item.get("item_name"), {})
                            
                p_data["materials"] = p_data.get("materials", 0) + stats.get("cost_materials", 0)
                p_data["manpower"] = p_data.get("manpower", 0) + stats.get("cost_manpower", 0)
                p_data["fuel"] = p_data.get("fuel", 0) + stats.get("cost_fuel", 0)

            self.map_screen.show_feedback("Cancelled & Refunded")
            self.refresh_ui()

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()