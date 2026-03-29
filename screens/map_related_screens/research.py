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
        y_pos = 120
        cat_techs = [t for t, data in self.tech_tree.items() if data[0] == self.current_category]
        cat_techs.sort(key=lambda t: self.tech_tree[t][1] != 9999)

        has_drawn_infinite = False

        for tech in cat_techs:
            level = res_levels.get(tech, 0)
            max_lvl = self.tech_tree[tech][1]
            reqs = self.tech_tree[tech][2]
            req_met = self.check_requirements(res_levels, reqs)
            queued_item = next((item for item in queue if item["tech_name"] == tech), None)

            if has_drawn_infinite and max_lvl != 9999:
                y_pos += 25 
                has_drawn_infinite = False
            
            if max_lvl == 9999: has_drawn_infinite = True

            display_name = tech.replace('_',' ').title()
            
            # --- Type vs Lvl vs One-off ---
            if max_lvl == 9999:
                level_str = f" Type {level + 1}" if not queued_item else f" Type {level}"
            elif max_lvl == 1:
                level_str = ""
            else:
                level_str = f" Lvl {level + 1}" if not queued_item else f" Lvl {level}"

            if level >= max_lvl and max_lvl != 9999:
                status_text = f"{display_name}: MAXED"
                color, callback = "grey", lambda: None
            elif queued_item:
                status_text = f"{display_name}: {queued_item['days_remaining']}d"
                color, callback = "green", lambda t=tech: self.pause_research(t)
            elif not req_met:
                status_text = f"{display_name} (Locked)"
                color, callback = "red", lambda: self.map_screen.show_feedback("Requirements not met!")
            elif len(queue) < 2:
                # Setup days calculation
                effective_lvl = max(0, level - 1800) if tech in ["infantry", "industry"] else level
                base_days = 30 + (effective_lvl * 15)
                days = progress_cache.get(tech, base_days)
                prefix = "Resume" if tech in progress_cache else "Start"
                status_text = f"{prefix} {display_name}{level_str} ({days}d)"
                color, callback = "blue", lambda t=tech: self.start_or_resume_research(t)
            else:
                status_text = f"{display_name} (Slots Full)"
                color, callback = "grey", lambda: self.map_screen.show_feedback("Research slots full!")

            btn = Button("centered", y_pos, "large", color, status_text, callback)
            self.elements.append(btn)

            # --- DRAW PROGRESS BAR ---
            if queued_item:
                effective_lvl = max(0, level - 1800) if tech in ["infantry", "industry"] else level
                total_days = 30 + (effective_lvl * 15)
                progress = 1 - (queued_item['days_remaining'] / total_days)
                self.draw_inline_progress(btn, progress)

            y_pos += 75

    def draw_inline_progress(self, btn, progress):
        """Draws a small progress bar at the bottom of the button."""
        # This is a bit of a 'hack' because we draw it after the button element is created
        # but before the frame finishes. 
        # Since additional_draw happens after self.elements are drawn in GameState, 
        # we can just draw right over the button.
        surf = pygame.display.get_surface()
        bar_rect = pygame.Rect(btn.rect.x + 5, btn.rect.bottom - 8, btn.rect.width - 10, 4)
        pygame.draw.rect(surf, (20, 20, 20), bar_rect) # Background
        pygame.draw.rect(surf, (0, 255, 0), (bar_rect.x, bar_rect.y, bar_rect.width * progress, 4))

    def draw_completed_tab(self, res_levels):
        """
        Clears interactive elements for this tab. 
        The actual text is drawn in additional_draw to avoid 'Button' styling.
        """
        # We clear elements so we don't have invisible buttons catching clicks
        # The Back and Category buttons are already added in refresh_ui()
        pass

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
        
        # --- Standard Header ---
        pygame.draw.rect(surface, (40, 40, 50), (0, 0, SCREEN_WIDTH, 70))
        pygame.draw.line(surface, (200, 200, 200), (0, 70), (SCREEN_WIDTH, 70), 2)

        font = pygame.font.SysFont("Arial", 32)
        title_str = f"VIEWING: {self.current_category}"
        ts = font.render(title_str, True, (255, 255, 255))
        surface.blit(ts, (SCREEN_WIDTH//2 - ts.get_width()//2, 75))

        # --- COMPLETED TAB TEXT RENDERING ---
        if self.current_category == "COMPLETED":
            self.render_completed_text_list(surface)
        else:
            # --- Standard HUD (Slots) for active research tabs ---
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
    
    def render_completed_text_list(self, surface):
        """Draws the full list of techs as clean text with logical spacing."""
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.get("research", {})
        
        text_font = pygame.font.SysFont("Arial", 22)
        label_font = pygame.font.SysFont("Arial", 24, bold=True)
        
        organized = {cat: [] for cat in self.categories if cat != "COMPLETED"}
        for tech_id, data in self.tech_tree.items():
            cat = data[0]
            lvl = res_levels.get(tech_id, 0)
            max_lvl = data[1]
            organized[cat].append((tech_id, lvl, max_lvl))

        start_y = 150
        column_width = 320
        
        for i, (cat_name, techs) in enumerate(organized.items()):
            curr_x = 50 + (i * column_width)
            curr_y = start_y
            
            # Header
            head = label_font.render(cat_name, True, (255, 215, 0))
            surface.blit(head, (curr_x, curr_y))
            curr_y += 40
            
            # Sort techs within column: Infinites first
            techs.sort(key=lambda x: x[2] != 9999)
            
            has_infinite_spacer = False
            for tech_id, lvl, max_lvl in techs:
                if has_infinite_spacer and max_lvl != 9999:
                    curr_y += 15 # Smaller spacer for text list
                    has_infinite_spacer = False
                if max_lvl == 9999: has_infinite_spacer = True

                display_name = tech_id.replace('_', ' ').title()
                
                # Logic: Hide level if max is 1 and level is 0 or 1
                if max_lvl == 9999:
                    val_text = f": Type {lvl}"
                elif max_lvl == 1:
                    val_text = ": Level 1" if lvl >= 1 else ": Level 0"
                else:
                    val_text = f": Level {lvl}"

                color = (200, 200, 200) if lvl > 0 else (100, 100, 100)
                if tech_id in ["infantry", "industry"] and lvl <= 1800:
                    color = (140, 140, 140)

                txt_surf = text_font.render(f"{display_name}{val_text}", True, color)
                surface.blit(txt_surf, (curr_x + 10, curr_y))
                curr_y += 28

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()