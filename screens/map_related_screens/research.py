import pygame
import json
import os
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button

class Research_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = None
        self.current_category = "INFANTRY" 

        # 1. Added COMPLETED category
        self.categories = ["INFANTRY", "TANKS", "NAVY", "INDUSTRY", "COMPLETED"]

        self.tech_tree = {
            "cavalry": ["INFANTRY", 20, {}],
            "infantry": ["INFANTRY", 9999, {}],
            "WW1_armored_car": ["TANKS", 1, {}],
            "WW1_tank": ["TANKS", 1, {}],
            "armored_car": ["TANKS", 5, {"WW1_armored_car": 1}],
            "light_tank": ["TANKS", 5, {"WW1_tank": 1}],
            "medium_tank": ["TANKS", 3, {"WW1_tank": 1}],
            "heavy_tank": ["TANKS", 3, {"WW1_tank": 1}],
            "main_battle_tank": ["TANKS", 1, {"OR": [{"medium_tank": 3}, {"heavy_tank": 3}]}],
            "carrack": ["NAVY", 1, {}],
            "ironclad": ["NAVY", 1, {"carrack": 1}],
            "pre-dreadnaught": ["NAVY", 1, {"ironclad": 1}],
            "dreadnaught": ["NAVY", 1, {"pre-dreadnaught": 1}],
            "destroyer": ["NAVY", 8, {"dreadnaught": 1}],
            "aircraft_carrier": ["NAVY", 4, {"destroyer": 1}],
            "industry": ["INDUSTRY", 9999, {}],
            "workshop": ["INDUSTRY", 5, {}],
            "basic_factory": ["INDUSTRY", 1, {"workshop": 5}],
            "factory": ["INDUSTRY", 5, {"basic_factory": 1}],
            "bergius_process": ["INDUSTRY", 1, {}],
            "synthetic_fuel_experiments": ["INDUSTRY", 1, {"bergius_process": 1}],
            "fuel_refining": ["INDUSTRY", 3, {"synthetic_fuel_experiments": 1}]
        }

    def start_research(self, map_ref):
        self.map_screen = map_ref
        self.current_category = "INFANTRY"
        self.refresh_ui()

    def set_category(self, cat):
        self.current_category = cat
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        self.elements.append(Button(20, 10, "small", "red", "Exit", self.exit_to_map))

        # Persistent Navigation Bar
        start_x = 180 # Shifted slightly left to fit 5 buttons
        for i, cat in enumerate(self.categories):
            color = "green" if self.current_category == cat else "blue"
            # Adjusted spacing to 205 to fit all 5 comfortably
            btn = Button(start_x + (i * 205), 10, "medium", color, cat, lambda c=cat: self.set_category(c))
            self.elements.append(btn)

        if not self.map_screen or self.map_screen.player_country == "None": return
        
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.setdefault("research", {})
        queue = player_data.setdefault("research_queue", [])
        progress_cache = player_data.setdefault("research_progress", {})

        # 2. Logic to switch between Tech Tree and History
        if self.current_category == "COMPLETED":
            self.draw_completed_tab(res_levels)
        else:
            self.draw_category_content(res_levels, queue, progress_cache)

    def draw_category_content(self, res_levels, queue, progress_cache):
        y_pos = 120 # Moved up slightly to fit more
        cat_techs = [t for t, data in self.tech_tree.items() if data[0] == self.current_category]
        
        for tech in cat_techs:
            level = res_levels.get(tech, 0)
            max_lvl = self.tech_tree[tech][1]
            reqs = self.tech_tree[tech][2]
            req_met = self.check_requirements(res_levels, reqs)
            queued_item = next((item for item in queue if item["tech_name"] == tech), None)

            if level >= max_lvl and max_lvl != 9999:
                status_text = f"{tech.replace('_',' ').title()}: MAX ({level})"
                color, callback = "grey", lambda: None
            elif queued_item:
                status_text = f"{tech.replace('_',' ').title()}: {queued_item['days_remaining']}d (PAUSE)"
                color, callback = "green", lambda t=tech: self.pause_research(t)
            elif not req_met:
                status_text = f"{tech.replace('_',' ').title()} (Locked)"
                color, callback = "red", lambda: self.map_screen.show_feedback("Requirements not met!")
            elif len(queue) < 2:
                has_progress = tech in progress_cache
                effective_lvl = max(0, level - 1800) if tech in ["infantry", "industry"] else level
                days = 30 + (effective_lvl * 15) if not has_progress else progress_cache[tech]
                prefix = "Resume" if has_progress else "Start"
                status_text = f"{prefix} {tech.replace('_',' ').title()} Lvl {level+1} ({days}d)"
                color, callback = "blue", lambda t=tech: self.start_or_resume_research(t)
            else:
                status_text = f"{tech.replace('_',' ').title()} (Slots Full)"
                color, callback = "grey", lambda: self.map_screen.show_feedback("Research slots full!")

            self.elements.append(Button("centered", y_pos, "large", color, status_text, callback))
            y_pos += 75

    def draw_completed_tab(self, res_levels):
        """3. New method to display finished tech and their levels."""
        y_pos = 120
        # Sort them alphabetically for better readability
        sorted_techs = sorted(res_levels.items())
        
        found_any = False
        for tech, level in sorted_techs:
            # Logic: Hide if level 0. For infantry/industry, hide if they haven't progressed past start
            is_baseline = tech in ["infantry", "industry"] and level <= 1800
            if level > 0 and not is_baseline:
                found_any = True
                display_name = tech.replace('_', ' ').title()
                # These are non-interactive buttons just for display
                self.elements.append(Button("centered", y_pos, "large", "grey", f"{display_name}: Level {level}", lambda: None))
                y_pos += 60

        if not found_any:
            self.elements.append(Button("centered", 300, "large", "red", "No advanced research completed", lambda: None))

    def check_requirements(self, res_levels, reqs):
        if not reqs: return True
        if "OR" in reqs:
            return any(res_levels.get(k, 0) >= v for sub in reqs["OR"] for k, v in sub.items())
        return all(res_levels.get(k, 0) >= v for k, v in reqs.items())

    def start_or_resume_research(self, tech_name):
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        progress_cache = player_data.setdefault("research_progress", {})
        
        if tech_name in progress_cache:
            duration = progress_cache.pop(tech_name)
        else:
            level = player_data["research"].get(tech_name, 0)
            effective_lvl = max(0, level - 1800) if tech_name in ["infantry", "industry"] else level
            duration = 30 + (effective_lvl * 15)
            
        player_data["research_queue"].append({"tech_name": tech_name, "days_remaining": duration})
        self.refresh_ui()

    def pause_research(self, tech_name):
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        queue = player_data["research_queue"]
        for i, project in enumerate(queue):
            if project["tech_name"] == tech_name:
                player_data["research_progress"][tech_name] = project["days_remaining"]
                queue.pop(i)
                break
        self.refresh_ui()

    def additional_draw(self, surface):
        if not self.map_screen: return
        pygame.draw.rect(surface, (40, 40, 50), (0, 0, SCREEN_WIDTH, 70))
        pygame.draw.line(surface, (200, 200, 200), (0, 70), (SCREEN_WIDTH, 70), 2)

        # Title
        font = pygame.font.SysFont("Arial", 32)
        title_str = f"VIEWING: {self.current_category}"
        ts = font.render(title_str, True, (255, 255, 255))
        surface.blit(ts, (SCREEN_WIDTH//2 - ts.get_width()//2, 75))

        # HUD (Slots)
        hud_rect = pygame.Rect(20, SCREEN_HEIGHT - 120, 350, 100)
        pygame.draw.rect(surface, (40, 40, 60), hud_rect)
        pygame.draw.rect(surface, (200, 200, 200), hud_rect, 2)
        hud_font = pygame.font.SysFont("Arial", 20)
        surface.blit(hud_font.render("ACTIVE RESEARCH SLOTS:", True, (255, 255, 0)), (30, SCREEN_HEIGHT - 110))
        
        queue = self.map_screen.nation_data[self.map_screen.player_country].get("research_queue", [])
        for i in range(2):
            y_off = SCREEN_HEIGHT - 80 + (i * 25)
            if i < len(queue):
                p = queue[i]
                txt = f"Slot {i+1}: {p['tech_name'].replace('_',' ').title()} ({p['days_remaining']}d)"
                surface.blit(hud_font.render(txt, True, (100, 255, 100)), (40, y_off))
            else:
                surface.blit(hud_font.render(f"Slot {i+1}: [EMPTY]", True, (150, 150, 150)), (40, y_off))

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()