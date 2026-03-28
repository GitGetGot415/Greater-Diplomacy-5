import pygame
import json
import os
import re
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from screens.map_related_screens import recruit_ui

class Recruit_Screen(GameState):
    def __init__(self, is_naval=False):
        super().__init__()
        self.bg_color = (20, 30, 20) if not is_naval else (10, 20, 40)
        self.target_province = None
        self.map_screen = None
        self.cancel_hitboxes = []
        self.is_naval = is_naval
        self.unit_library = self.load_unit_data()

    def load_unit_data(self):
        path = 'map_functions/data/unit_data.json'
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {}

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.refresh_ui()

    def get_group_name(self, name):
        """Groups 'Destroyer I' and 'Destroyer II' into 'Destroyer'"""
        return re.sub(r'\s+[IVXLCDM]+$', '', name).strip()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]
        
        # 1. Group units by their base name
        groups = {}
        for name, stats in self.unit_library.items():
            if stats.get("naval_unit", False) == self.is_naval:
                base_name = self.get_group_name(name)
                if base_name not in groups:
                    groups[base_name] = []
                groups[base_name].append((name, stats))

        # 2. Render groups into horizontal rows
        y_offset = 120
        row_height = 60
        btn_width = 110 # Approximate width of 'small' button preset
        
        for base_name, units in groups.items():
            # Draw label for the row
            # (Labels are drawn in additional_draw to avoid button collision logic)
            
            # Sort units within group (so I comes before II)
            units.sort(key=lambda x: x[0])

            x_offset = 250 # Start buttons after the label
            for name, stats in units:
                # Shorten the name for the button display (e.g. 'Destroyer III' -> 'III')
                display_label = name.replace(base_name, "").strip() or base_name
                
                btn = Button(x_offset, y_offset, "small", "blue" if self.is_naval else "green", 
                             display_label, lambda n=name: self.buy_unit(n))
                self.elements.append(btn)
                x_offset += btn_width + 10
            
            y_offset += row_height

    def buy_unit(self, unit_name):
        stats = self.unit_library.get(unit_name)
        if not stats or not self.map_screen: return

        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        
        # Comprehensive Affordability Check
        costs = {
            "money": stats.get("cost_money", 0),
            "manpower": stats.get("cost_manpower", 0),
            "materials": stats.get("cost_materials", 0),
            "fuel": stats.get("cost_fuel", 0)
        }

        if all(p_data.get(res, 0) >= amount for res, amount in costs.items()):
            for res, amount in costs.items():
                p_data[res] -= amount

            order = {
                "unit_type": unit_name,
                "days_remaining": stats.get("production_time", 5),
            }
            self.target_province.setdefault("deployment_queue", []).append(order)
            self.map_screen.show_feedback(f"Started production: {unit_name}")
        else:
            self.map_screen.show_feedback("Insufficient resources for this unit!")

    def additional_draw(self, surface):
        if not self.target_province: return
        
        # 1. Draw Title
        title_font = pygame.font.SysFont("Arial", 28, bold=True)
        title_str = "NAVAL SHIPYARD" if self.is_naval else "ARMY RECRUITMENT"
        surface.blit(title_font.render(title_str, True, (255, 255, 255)), (150, 25))

        # 2. Draw Group Labels
        label_font = pygame.font.SysFont("Arial", 20)
        groups = sorted(list(set(self.get_group_name(n) for n, s in self.unit_library.items() 
                                if s.get("naval_unit") == self.is_naval)))
        
        for i, group_name in enumerate(groups):
            txt = label_font.render(f"{group_name}:", True, (200, 200, 200))
            surface.blit(txt, (50, 130 + (i * 60)))

        # 3. RESOURCE HUD (Bottom Bar)
        hud_rect = pygame.Rect(0, SCREEN_HEIGHT - 60, SCREEN_WIDTH, 60)
        pygame.draw.rect(surface, (30, 30, 30), hud_rect)
        pygame.draw.line(surface, (100, 100, 100), (0, hud_rect.y), (SCREEN_WIDTH, hud_rect.y), 2)

        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_font = pygame.font.SysFont("Arial", 22)
        
        resources = [
            (f"Money: {p_data.get('money', 0)}", (255, 215, 0)),
            (f"Manpower: {p_data.get('manpower', 0)}", (100, 200, 255)),
            (f"Materials: {p_data.get('materials', 0)}", (180, 180, 180)),
            (f"Fuel: {p_data.get('fuel', 0)}", (200, 100, 255))
        ]

        for i, (text, color) in enumerate(resources):
            surf = res_font.render(text, True, color)
            surface.blit(surf, (50 + (i * 300), hud_rect.y + 15))

        # 4. Draw Queued Orders Sidebar
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
            queue.pop(index)
            self.refresh_ui()

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()