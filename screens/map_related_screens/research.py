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
        self.current_category = "MAIN"  # MAIN, INFANTRY, TANKS, NAVY, INDUSTRY

        # Define the Tech Tree Structure
        # name: [category, max_level, requirement_dict]
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
        self.current_category = "MAIN"
        self.refresh_ui()

    def set_category(self, cat):
        self.current_category = cat
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        
        # Back Button logic
        if self.current_category == "MAIN":
            self.elements.append(Button(50, 50, "small", "red", "Exit", self.exit_to_map))
        else:
            self.elements.append(Button(50, 50, "small", "red", "Back", lambda: self.set_category("MAIN")))

        if not self.map_screen or self.map_screen.player_country == "None": return
        
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.setdefault("research", {})
        queue = player_data.setdefault("research_queue", [])
        progress_cache = player_data.setdefault("research_progress", {})

        if self.current_category == "MAIN":
            self.draw_main_menu()
        else:
            self.draw_category_menu(res_levels, queue, progress_cache)

    def draw_main_menu(self):
        categories = ["INFANTRY", "TANKS", "NAVY", "INDUSTRY"]
        for i, cat in enumerate(categories):
            btn = Button("centered", 200 + (i * 100), "large", "blue", cat, lambda c=cat: self.set_category(c))
            self.elements.append(btn)

    def draw_category_menu(self, res_levels, queue, progress_cache):
        y_pos = 150
        # Filter techs by current category
        cat_techs = [t for t, data in self.tech_tree.items() if data[0] == self.current_category]
        
        for tech in cat_techs:
            level = res_levels.get(tech, 0)
            max_lvl = self.tech_tree[tech][1]
            reqs = self.tech_tree[tech][2]
            
            # Check Requirements
            req_met = self.check_requirements(res_levels, reqs)
            queued_item = next((item for item in queue if item["tech_name"] == tech), None)

            if level >= max_lvl and max_lvl != 9999:
                status_text = f"{tech.replace('_',' ').title()}: MAX LEVEL"
                color, callback = "grey", lambda: None
            elif queued_item:
                status_text = f"{tech.replace('_',' ').title()}: {queued_item['days_remaining']}d (PAUSE)"
                color, callback = "green", lambda t=tech: self.pause_research(t)
            elif not req_met:
                status_text = f"{tech.replace('_',' ').title()} (Locked)"
                color, callback = "red", lambda: self.map_screen.show_feedback("Requirements not met!")
            elif len(queue) < 2:
                has_progress = tech in progress_cache
                days = progress_cache[tech] if has_progress else (30 + (level * 15))
                prefix = "Resume" if has_progress else "Start"
                status_text = f"{prefix} {tech.replace('_',' ').title()} ({days}d)"
                color, callback = "blue", lambda t=tech: self.start_or_resume_research(t)
            else:
                status_text = f"{tech.replace('_',' ').title()} (Slots Full)"
                color, callback = "grey", lambda: self.map_screen.show_feedback("Research slots full!")

            self.elements.append(Button("centered", y_pos, "large", color, status_text, callback))
            y_pos += 85

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
            duration = 30 + (level * 15)
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
        # Title
        font = pygame.font.SysFont("Arial", 32)
        title_str = f"RESEARCH: {self.current_category}"
        ts = font.render(title_str, True, (255, 255, 255))
        surface.blit(ts, (SCREEN_WIDTH//2 - ts.get_width()//2, 40))

        # --- THE HUD (Bottom Left) ---
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
        if self.current_category != "MAIN": self.set_category("MAIN")
        else: self.exit_to_map()