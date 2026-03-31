import pygame
import json
import os
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from map_functions.rendering.font_manager import fonts

class Research_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = None
        self.current_category = "INFANTRY" 
        self.categories = ["INFANTRY", "TANKS", "NAVY", "INDUSTRY", "COMPLETED"]

        # Load tech tree from the template file
        self.tech_tree = self.load_tech_tree()

    def load_tech_tree(self):
        path = "map_functions/data/json/research_template.json"
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        else:
            print(f"Error: {path} not found!")
            return {}

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
        # Filter techs based on the 'category' key in the new JSON structure
        cat_techs = [t for t, data in self.tech_tree.items() if data["category"] == self.current_category]
        
        # Sort so that 9999 (infinite) techs come first
        cat_techs.sort(key=lambda t: self.tech_tree[t]["max_lvl"] != 9999)

        has_drawn_infinite = False

        for tech in cat_techs:
            level = res_levels.get(tech, 0)
            tech_data = self.tech_tree[tech]
            max_lvl = tech_data["max_lvl"]
            reqs = tech_data["req"]
            req_met = self.check_requirements(res_levels, reqs)
            queued_item = next((item for item in queue if item["tech_name"] == tech), None)

            if has_drawn_infinite and max_lvl != 9999:
                y_pos += 25 
                has_drawn_infinite = False
            if max_lvl == 9999: has_drawn_infinite = True

            display_name = tech.replace('_',' ').title()
            
            # --- Type vs Lvl Logic ---
            level_str = ""
            if max_lvl == 9999:
                level_str = f" Type {level + (0 if queued_item else 1)}"
            elif max_lvl > 1:
                level_str = f" Lvl {level + (0 if queued_item else 1)}"

            # --- Cost & Progress Logic ---
            total_cost = tech_data.get("cost", 300)
            
            if level >= max_lvl and max_lvl != 9999:
                status_text = f"{display_name}: MAXED"
                color, callback = "grey", lambda: None
            elif queued_item:
                pts = queued_item.get('points_remaining', total_cost)
                status_text = f"{display_name}: {pts} pts left (PAUSE)"
                color, callback = "green", lambda t=tech: self.pause_research(t)
            elif not req_met:
                status_text = f"{display_name} (Locked)"
                color, callback = "red", lambda: self.map_screen.show_feedback("Requirements not met!")
            elif len(queue) < 2:
                has_progress = tech in progress_cache
                pts_needed = progress_cache.get(tech, total_cost)
                prefix = "Resume" if has_progress else "Start"
                status_text = f"{prefix} {display_name}{level_str} ({pts_needed} pts)"
                color, callback = "blue", lambda t=tech: self.start_or_resume_research(t)
            else:
                status_text = f"{display_name} (Slots Full)"
                color, callback = "grey", lambda: self.map_screen.show_feedback("Research slots full!")

            btn = Button("centered", y_pos, "large", color, status_text, callback)
            self.elements.append(btn)

            if queued_item:
                progress = 1 - (queued_item.get('points_remaining', total_cost) / total_cost)
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
        
        # Get point cost from tech tree
        total_cost = self.tech_tree[tech_name].get("cost", 300)
        points_remaining = progress_cache.pop(tech_name, total_cost)
            
        player_data["research_queue"].append({
            "tech_name": tech_name, 
            "points_remaining": points_remaining
        })
        self.refresh_ui()

    def pause_research(self, tech_name):
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        queue = player_data["research_queue"]
        for i, project in enumerate(queue):
            if project["tech_name"] == tech_name:
                player_data["research_progress"][tech_name] = project["points_remaining"]
                queue.pop(i)
                break
        self.refresh_ui()

    def additional_draw(self, surface):
        if not self.map_screen: return
        
        # --- Standard Header ---
        pygame.draw.rect(surface, (40, 40, 50), (0, 0, SCREEN_WIDTH, 70))
        pygame.draw.line(surface, (200, 200, 200), (0, 70), (SCREEN_WIDTH, 70), 2)

        font = fonts.get("heading1")
        title_str = f"VIEWING: {self.current_category}"
        ts = font.render(title_str, True, (255, 255, 255))
        surface.blit(ts, (SCREEN_WIDTH//2 - ts.get_width()//2, 75))

        # --- Research Output Indicator ---
        output_font = fonts.get("heading1")
        # For now, this is hardcoded to 10/day as per your requirement
        output_text = output_font.render("RESEARCH OUTPUT: 10 pts/day", True, (0, 255, 255))
        surface.blit(output_text, (SCREEN_WIDTH - output_text.get_width() - 30, 85))

        # --- COMPLETED TAB TEXT RENDERING ---
        if self.current_category == "COMPLETED":
            self.render_completed_text_list(surface)
        else:
            # --- Updated HUD (Slots) ---
            hud_rect = pygame.Rect(20, SCREEN_HEIGHT - 120, 400, 100)
            pygame.draw.rect(surface, (40, 40, 60), hud_rect)
            pygame.draw.rect(surface, (200, 200, 200), hud_rect, 2)
            hud_font = fonts.get("button")
            surface.blit(hud_font.render("ACTIVE RESEARCH SLOTS:", True, (255, 255, 0)), (30, SCREEN_HEIGHT - 110))
            
            queue = self.map_screen.nation_data[self.map_screen.player_country].get("research_queue", [])
            for i in range(2):
                y_off = SCREEN_HEIGHT - 80 + (i * 25)
                if i < len(queue):
                    p = queue[i]
                    tech_name = p['tech_name'].replace('_',' ').title()
                    
                    # Fix for the KeyError: Use points_remaining
                    pts_left = p.get('points_remaining', 0)
                    total_cost = self.tech_tree.get(p['tech_name'], {}).get("cost", 300)
                    
                    # Optional: Add a percentage for clarity
                    progress_pct = int((1 - (pts_left / total_cost)) * 100)
                    
                    txt = f"Slot {i+1}: {tech_name} ({pts_left} pts left | {progress_pct}%)"
                    surface.blit(hud_font.render(txt, True, (100, 255, 100)), (40, y_off))
                else:
                    surface.blit(hud_font.render(f"Slot {i+1}: [EMPTY]", True, (150, 150, 150)), (40, y_off))
    
    def render_completed_text_list(self, surface):
        """Draws the summary with spacing and 'Type' vs 'Level' labeling."""
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.get("research", {})
        
        text_font = fonts.get("button")
        label_font = fonts.get("heading2")
        
        organized = {cat: [] for cat in self.categories if cat != "COMPLETED"}
        for tech_id, data in self.tech_tree.items():
            cat = data["category"]
            lvl = res_levels.get(tech_id, 0)
            max_lvl = data["max_lvl"]
            organized[cat].append((tech_id, lvl, max_lvl))

        start_y = 150
        column_width = 320
        
        for i, (cat_name, techs) in enumerate(organized.items()):
            curr_x = 50 + (i * column_width)
            curr_y = start_y
            
            head = label_font.render(cat_name, True, (255, 215, 0))
            surface.blit(head, (curr_x, curr_y))
            curr_y += 40
            
            techs.sort(key=lambda x: x[2] != 9999)
            
            has_infinite_spacer = False
            for tech_id, lvl, max_lvl in techs:
                if has_infinite_spacer and max_lvl != 9999:
                    curr_y += 15
                    has_infinite_spacer = False
                if max_lvl == 9999: has_infinite_spacer = True

                display_name = tech_id.replace('_', ' ').title()
                
                # --- Label Refactor ---
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