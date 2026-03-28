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
        
        # Stat Tooltip tracking
        self.hovered_unit_stats = None
        
        self.unit_library = self.load_unit_data()
        # Pre-calculate the groups in JSON order
        self.ordered_groups = self.get_ordered_groups()

    def load_unit_data(self):
        path = 'map_functions/data/unit_data.json'
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
        return {}

    def get_group_name(self, name):
        """Groups 'Destroyer I' and 'Destroyer II' into 'Destroyer'"""
        return re.sub(r'\s+[IVXLCDM]+$', '', name).strip()

    def get_ordered_groups(self):
        """Returns unique group names in the order they first appear in the JSON."""
        groups = []
        for name, stats in self.unit_library.items():
            if stats.get("naval_unit", False) == self.is_naval:
                base = self.get_group_name(name)
                if base not in groups:
                    groups.append(base)
        return groups

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(20, 20, "small", "red", "Back", self.exit_to_map)]
        
        # 1. Map units to their groups while preserving JSON order
        grouped_units = {group: [] for group in self.ordered_groups}
        for name, stats in self.unit_library.items():
            if stats.get("naval_unit", False) == self.is_naval:
                base = self.get_group_name(name)
                grouped_units[base].append((name, stats))

        # 2. Render rows based on the order of self.ordered_groups
        y_offset = 120
        row_height = 60
        btn_width = 110 
        
        for group_name in self.ordered_groups:
            units = grouped_units[group_name]
            # No sorting here; we want JSON order within the row too
            
            x_offset = 250 
            for name, stats in units:
                display_label = name.replace(group_name, "").strip() or group_name
                
                btn = Button(x_offset, y_offset, "small", "blue" if self.is_naval else "green", 
                             display_label, lambda n=name: self.buy_unit(n))
                
                # Attach the full name to the button object for tooltip detection
                btn.internal_unit_name = name 
                self.elements.append(btn)
                x_offset += btn_width + 10
            
            y_offset += row_height

    def buy_unit(self, unit_name):
        stats = self.unit_library.get(unit_name)
        if not stats or not self.map_screen: return

        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        
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
            self.map_screen.show_feedback(f"Production started: {unit_name}")
        else:
            self.map_screen.show_feedback("Insufficient resources!")

    def draw_tooltip(self, surface):
        if not self.hovered_unit_stats: return
        
        mx, my = pygame.mouse.get_pos()
        stats = self.hovered_unit_stats
        
        # Prepare text lines
        lines = [
            f"--- {stats['name']} ---",
            f"HP: {stats.get('health', 0)} | ATK: {stats.get('attack', 0)}",
            f"DEF: {stats.get('defense', 0)} | SPD: {stats.get('speed', 0)}",
            f"Time: {stats.get('production_time', 0)} days",
            f"Cost: {stats.get('cost_money', 0)} Money",
            f"      {stats.get('cost_materials', 0)} Mat | {stats.get('cost_manpower', 0)} Man"
        ]
        
        font = pygame.font.SysFont("Arial", 16)
        # Calculate tooltip size
        max_w = max(font.size(l)[0] for l in lines) + 20
        height = len(lines) * 20 + 10
        
        tip_rect = pygame.Rect(mx + 15, my + 15, max_w, height)
        # Boundary check
        if tip_rect.right > SCREEN_WIDTH: tip_rect.x -= (max_w + 30)
        
        pygame.draw.rect(surface, (40, 40, 40), tip_rect)
        pygame.draw.rect(surface, (200, 200, 200), tip_rect, 1)
        
        for i, line in enumerate(lines):
            color = (255, 255, 255) if i != 0 else (255, 215, 0)
            surface.blit(font.render(line, True, color), (tip_rect.x + 10, tip_rect.y + 5 + i * 20))

    def additional_draw(self, surface):
        if not self.target_province: return
        
        # 1. Title
        title_font = pygame.font.SysFont("Arial", 28, bold=True)
        title_str = "NAVAL SHIPYARD" if self.is_naval else "ARMY RECRUITMENT"
        surface.blit(title_font.render(title_str, True, (255, 255, 255)), (150, 25))

        # 2. Draw Group Labels using the ordered list
        label_font = pygame.font.SysFont("Arial", 20)
        for i, group_name in enumerate(self.ordered_groups):
            txt = label_font.render(f"{group_name}:", True, (200, 200, 200))
            surface.blit(txt, (50, 130 + (i * 60)))

        # 3. Detect Hover for Tooltips
        mouse_pos = pygame.mouse.get_pos()
        self.hovered_unit_stats = None
        for el in self.elements:
            if hasattr(el, 'rect') and el.rect.collidepoint(mouse_pos):
                if hasattr(el, 'internal_unit_name'):
                    name = el.internal_unit_name
                    self.hovered_unit_stats = self.unit_library[name].copy()
                    self.hovered_unit_stats['name'] = name

        # 4. RESOURCE HUD
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
            surface.blit(res_font.render(text, True, color), (50 + (i * 300), hud_rect.y + 15))

        # 5. Sidebar & Tooltip
        self.cancel_hitboxes = recruit_ui.draw_recruitment_overlay(surface, self.target_province)
        self.draw_tooltip(surface)

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