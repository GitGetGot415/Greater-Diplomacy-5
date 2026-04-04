import pygame
import json
import os
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button
from map_functions.rendering.font_manager import fonts
from map_functions.rendering import symbol_loader

class Research_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = None
        self.current_category = "INFANTRY" 
        self.categories = ["INFANTRY", "TANKS", "NAVY", "INDUSTRY", "COMPLETED"]

        self.tech_tree = self.load_json("data/json/research_template.json")
        self.unit_library = self.load_json("data/json/unit_data.json")
        self.building_library = self.load_json("data/json/building_data.json")
        
        self.active_modal = None

        # --- Timeline Variables ---
        self.scroll_x = 0
        self.target_scroll_x = 0
        self.pixels_per_year = 35 # Adjust this to change how squeezed together the years are

        self.setup_nodes()

    def load_json(self, path):
        if os.path.exists(path):
            with open(path, "r") as f: return json.load(f)
        print(f"Error: {path} not found!")
        return {}

    def setup_nodes(self):
        """Dynamically positions nodes based on their associated year."""
        self.tech_years = {
            ("ww1_armored_car", 1): 1910, ("ww1_tank", 1): 1915, ("civilian_car", 1): 1905,
            ("light_tank", 1): 1918, ("light_tank", 2): 1924, ("light_tank", 3): 1930, ("light_tank", 4): 1936, ("light_tank", 5): 1942,
            ("medium_tank", 1): 1925, ("medium_tank", 2): 1932, ("medium_tank", 3): 1939,
            ("heavy_tank", 1): 1930, ("heavy_tank", 2): 1935, ("heavy_tank", 3): 1940,
            ("main_battle_tank", 1): 1945,
            ("armored_car", 1): 1916, ("armored_car", 2): 1922, ("armored_car", 3): 1928, ("armored_car", 4): 1934, ("armored_car", 5): 1940,
            
            ("carrack", 1): 1500, ("ironclad", 1): 1860, ("pre-dreadnaught", 1): 1880, ("dreadnaught", 1): 1900,
            ("destroyer", 1): 1910, ("destroyer", 2): 1916, ("destroyer", 3): 1922, ("destroyer", 4): 1928, ("destroyer", 5): 1934, ("destroyer", 6): 1940, ("destroyer", 7): 1946, ("destroyer", 8): 1952,
            ("aircraft_carrier", 1): 1920, ("aircraft_carrier", 2): 1930, ("aircraft_carrier", 3): 1940, ("aircraft_carrier", 4): 1950,
            
            ("workshop", 1): 1800, ("workshop", 2): 1820, ("workshop", 3): 1840, ("workshop", 4): 1860, ("workshop", 5): 1880,
            ("basic_factory", 1): 1900,
            ("factory", 1): 1910, ("factory", 2): 1920, ("factory", 3): 1930, ("factory", 4): 1940, ("factory", 5): 1950,
            ("bergius_process", 1): 1910, ("synthetic_fuel_experiments", 1): 1920,
            ("fuel_refining", 1): 1930, ("fuel_refining", 2): 1940, ("fuel_refining", 3): 1950
        }

        # Stagger the Y positions to prevent branches overlapping
        self.tech_rows = {
            "ww1_armored_car": 250, "armored_car": 250, "civilian_car": 250,
            "ww1_tank": 350, "light_tank": 350,
            "medium_tank": 450, "main_battle_tank": 450,
            "heavy_tank": 550,
            "destroyer": 250,
            "carrack": 350, "ironclad": 350, "pre-dreadnaught": 350, "dreadnaught": 350,
            "aircraft_carrier": 450,
            "workshop": 250, "basic_factory": 250, "factory": 250,
            "bergius_process": 400, "synthetic_fuel_experiments": 400, "fuel_refining": 400
        }

        self.nodes = {"TANKS": [], "NAVY": [], "INDUSTRY": []}

        for tech_key, data in self.tech_tree.items():
            cat = data["category"]
            if cat in self.nodes:
                max_lvl = data["max_lvl"]
                for lvl in range(1, max_lvl + 1):
                    year = self.tech_years.get((tech_key, lvl), 1900)
                    row_y = self.tech_rows.get(tech_key, 350)
                    self.nodes[cat].append({
                        "key": tech_key,
                        "lvl": lvl,
                        "year": year,
                        "base_y": row_y
                    })

    def update(self):
        super().update()
        # Smooth horizontal scrolling mechanic
        if hasattr(self, 'target_scroll_x'):
            if abs(self.scroll_x - self.target_scroll_x) > 0.5:
                self.scroll_x += (self.target_scroll_x - self.scroll_x) * 0.15
                
                # Instantly move dynamically generated buttons to stick to the scrolling
                for el in self.elements:
                    if getattr(el, 'is_tech_node', False):
                        el.rect.x = el.base_x + self.scroll_x

    def additional_events(self, event):
        # Enable map-style drag panning and scroll-wheel interactions for the timeline
        if self.current_category in ["TANKS", "NAVY", "INDUSTRY"] and not self.active_modal:
            if event.type == pygame.MOUSEWHEEL:
                self.target_scroll_x += event.y * 70
            elif event.type == pygame.MOUSEMOTION and event.buttons[2]: # Right click drag
                self.target_scroll_x += event.rel[0]
                self.scroll_x += event.rel[0] # Instant lock for smooth dragging
                
                for el in self.elements:
                    if getattr(el, 'is_tech_node', False):
                        el.rect.x = el.base_x + self.scroll_x

    def get_display_name(self, tech_key, lvl):
        if tech_key == "infantry": return "Infantry"
        
        romans = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}
        
        if tech_key == "civilian_car": return "Civilian Car"
        if tech_key == "ww1_armored_car": return "WW1 Armored Car"
        if tech_key == "ww1_tank": return "WW1 Tank"
        if tech_key == "main_battle_tank": return "Main Battle Tank"
        if tech_key == "carrack": return "Carrack"
        if tech_key == "ironclad": return "Ironclad"
        if tech_key == "pre-dreadnaught": return "Pre-Dreadnought"
        if tech_key == "dreadnaught": return "Dreadnought"
        if tech_key == "bergius_process": return "Bergius Process"
        if tech_key == "synthetic_fuel_experiments": return "Synthetic Fuel Experiments"
        if tech_key == "basic_factory": return "Basic Factory"
        
        base_name = tech_key.replace('_', ' ').title()
        
        if tech_key in ["workshop", "factory", "fuel_refining"]:
            if tech_key == "fuel_refining": base_name = "Synthetic Refinery" 
            return f"{base_name} Lvl {lvl}"
            
        return f"{base_name} {romans.get(lvl, str(lvl))}"

    def start_research(self, map_ref):
        self.map_screen = map_ref
        self.current_category = "INFANTRY"
        self.active_modal = None
        self.scroll_x = 0
        self.target_scroll_x = 0
        self.refresh_ui()

    def set_category(self, cat):
        self.current_category = cat
        self.active_modal = None
        self.scroll_x = 0
        self.target_scroll_x = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        if not self.map_screen or self.map_screen.player_country == "None": return
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.setdefault("research", {})
        queue = player_data.setdefault("research_queue", [])
        progress_cache = player_data.setdefault("research_progress", {})

        if self.active_modal:
            st = self.active_modal["status"]
            panel_x, panel_y = 400, 200
            
            self.elements.append(Button(panel_x + 650, panel_y + 430, "small", "red", "Cancel", self.close_modal))
            
            if st == "AVAILABLE":
                if len(queue) >= 2:
                    self.elements.append(Button(panel_x + 50, panel_y + 430, "medium", "grey", "Slots Full", lambda: None))
                else:
                    self.elements.append(Button(panel_x + 50, panel_y + 430, "medium", "blue", "Start Research", self.modal_start_research))
            elif st == "RESEARCHING":
                self.elements.append(Button(panel_x + 50, panel_y + 430, "medium", "orange", "Pause", self.modal_pause_research))
            elif st == "LOCKED":
                self.elements.append(Button(panel_x + 50, panel_y + 430, "medium", "red", "Missing Reqs", lambda: None))
            elif st == "COMPLETED":
                self.elements.append(Button(panel_x + 50, panel_y + 430, "medium", "green", "Researched", lambda: None))
            return
        
        self.elements.append(Button(20, 10, "small", "red", "Exit", self.exit_to_map))

        start_x = 180 
        for i, cat in enumerate(self.categories):
            color = "green" if self.current_category == cat else "blue"
            btn = Button(start_x + (i * 205), 10, "medium", color, cat, lambda c=cat: self.set_category(c))
            self.elements.append(btn)

        if self.current_category == "COMPLETED":
            pass 
        elif self.current_category == "INFANTRY":
            self.draw_infantry_content(res_levels, queue, progress_cache)
        else:
            self.draw_tech_nodes(res_levels, queue)

    def draw_infantry_content(self, res_levels, queue, progress_cache):
        tech = "infantry"
        level = res_levels.get(tech, 0)
        tech_data = self.tech_tree[tech]
        total_cost = tech_data.get("cost", 300)
        queued_item = next((item for item in queue if item["tech_name"] == tech), None)
        
        display_name = tech.replace('_',' ').title()
        level_str = f" Type {level + (0 if queued_item else 1)}"
        
        if queued_item:
            pts = queued_item.get('points_remaining', total_cost)
            status_text = f"{display_name}: {pts} pts left (PAUSE)"
            color, callback = "orange", lambda t=tech: self.pause_research(t)
        elif len(queue) < 2:
            has_progress = tech in progress_cache
            pts_needed = progress_cache.get(tech, total_cost)
            prefix = "Resume" if has_progress else "Start"
            status_text = f"{prefix} {display_name}{level_str} ({pts_needed} pts)"
            color, callback = "blue", lambda t=tech: self.start_or_resume_research(t)
        else:
            status_text = f"{display_name} (Slots Full)"
            color, callback = "grey", lambda: self.map_screen.show_feedback("Research slots full!")

        btn = Button("centered", 200, "large", color, status_text, callback)
        self.elements.append(btn)

    def draw_tech_nodes(self, res_levels, queue):
        current_year = self.map_screen.time_manager.year

        for node in self.nodes.get(self.current_category, []):
            tech_key = node["key"]
            lvl = node["lvl"]
            year = node["year"]
            base_y = node["base_y"]
            
            # 80px size button offset by 40 so the center of the button lands exactly on the timeline tick
            base_x = (year - current_year) * self.pixels_per_year + (SCREEN_WIDTH // 2) - 40
            
            cur_lvl = res_levels.get(tech_key, 0)
            is_researching = any(q["tech_name"] == tech_key for q in queue)
            
            status = "LOCKED"
            if cur_lvl >= lvl:
                status = "COMPLETED"
            elif is_researching and cur_lvl + 1 == lvl:
                status = "RESEARCHING"
            elif cur_lvl == lvl - 1:
                if lvl == 1:
                    reqs = self.tech_tree[tech_key].get("req", {})
                    if self.check_requirements(res_levels, reqs):
                        status = "AVAILABLE"
                else:
                    status = "AVAILABLE"
                    
            color_map = {"COMPLETED": "green", "RESEARCHING": "orange", "AVAILABLE": "blue", "LOCKED": "grey"}
            btn_color = color_map[status]
            
            display_name = self.get_display_name(tech_key, lvl)
            icon = symbol_loader.get_symbol(display_name, 2.0)
            
            node_info = {
                "tech_key": tech_key,
                "level": lvl,
                "display_name": display_name,
                "cost": self.tech_tree[tech_key].get("cost", 300),
                "status": status,
                "icon": icon
            }
            
            btn = Button(base_x + self.scroll_x, base_y, "tech_square", btn_color, display_name, 
                         lambda n=node_info: self.open_modal(n), image=icon, show_text=False)
            
            # Apply dynamic tracking flags
            btn.base_x = base_x
            btn.is_tech_node = True
            
            self.elements.append(btn)

    def check_requirements(self, res_levels, reqs):
        if not reqs: return True
        if "OR" in reqs:
            return any(res_levels.get(k, 0) >= v for sub in reqs["OR"] for k, v in sub.items())
        return all(res_levels.get(k, 0) >= v for k, v in reqs.items())

    # --- MODAL ACTIONS ---
    def open_modal(self, node_info):
        self.active_modal = node_info
        self.refresh_ui()
        
    def close_modal(self):
        self.active_modal = None
        self.refresh_ui()

    def modal_start_research(self):
        self.start_or_resume_research(self.active_modal["tech_key"])
        self.close_modal()

    def modal_pause_research(self):
        self.pause_research(self.active_modal["tech_key"])
        self.close_modal()

    def start_or_resume_research(self, tech_name):
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        progress_cache = player_data.setdefault("research_progress", {})
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

    # --- RENDERING ---
    def draw_timeline_axis(self, surface):
        """Draws the dynamic horizontal year axis across the screen"""
        if self.current_category in ["INFANTRY", "COMPLETED"] or self.active_modal:
            return

        current_year = self.map_screen.time_manager.year
        axis_y = 180

        pygame.draw.line(surface, (150, 150, 150), (0, axis_y), (SCREEN_WIDTH, axis_y), 3)
        year_font = fonts.get("heading2")

        # Map current window limits to game years
        start_year = int((-self.scroll_x - (SCREEN_WIDTH // 2)) / self.pixels_per_year) + current_year - 5
        end_year = int((SCREEN_WIDTH - self.scroll_x - (SCREEN_WIDTH // 2)) / self.pixels_per_year) + current_year + 5

        for year in range(start_year, end_year):
            x = (year - current_year) * self.pixels_per_year + (SCREEN_WIDTH // 2) + self.scroll_x
            if year % 5 == 0:
                pygame.draw.line(surface, (200, 200, 200), (x, axis_y - 10), (x, axis_y + 10), 2)
                txt = year_font.render(str(year), True, (200, 200, 200))
                surface.blit(txt, (x - txt.get_width()//2, axis_y - 40))
            elif year % 1 == 0:
                pygame.draw.line(surface, (100, 100, 100), (x, axis_y - 5), (x, axis_y + 5), 1)

    def draw_connections(self, surface, res_levels):
        nodes = self.nodes.get(self.current_category, [])
        lookup = {(n["key"], n["lvl"]): n for n in nodes}
        
        current_year = self.map_screen.time_manager.year
        
        for node in nodes:
            k = node["key"]
            l = node["lvl"]
            
            x1 = (node["year"] - current_year) * self.pixels_per_year + (SCREEN_WIDTH // 2) + self.scroll_x
            y1 = node["base_y"] + 40
            p1 = (x1, y1)
            
            def draw_line_to_prev(req_k, req_lvl):
                prev_node = lookup.get((req_k, req_lvl))
                if prev_node:
                    x2 = (prev_node["year"] - current_year) * self.pixels_per_year + (SCREEN_WIDTH // 2) + self.scroll_x
                    y2 = prev_node["base_y"] + 40
                    p2 = (x2, y2)
                    color = (0, 255, 0) if res_levels.get(req_k, 0) >= req_lvl else (100, 100, 100)
                    pygame.draw.line(surface, color, p2, p1, 3)

            if l > 1:
                draw_line_to_prev(k, l - 1)
            elif l == 1:
                reqs = self.tech_tree[k].get("req", {})
                if "OR" in reqs:
                    for sub_req in reqs["OR"]:
                        for req_k, req_lvl in sub_req.items():
                            draw_line_to_prev(req_k, req_lvl)
                else:
                    for req_k, req_lvl in reqs.items():
                        draw_line_to_prev(req_k, req_lvl)

    def draw_hud_slots(self, surface):
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
                pts_left = p.get('points_remaining', 0)
                total_cost = self.tech_tree.get(p['tech_name'], {}).get("cost", 300)
                progress_pct = int((1 - (pts_left / total_cost)) * 100)
                
                txt = f"Slot {i+1}: {tech_name} ({pts_left} pts left | {progress_pct}%)"
                surface.blit(hud_font.render(txt, True, (100, 255, 100)), (40, y_off))
            else:
                surface.blit(hud_font.render(f"Slot {i+1}: [EMPTY]", True, (150, 150, 150)), (40, y_off))

    def draw_subscreen_modal(self, surface):
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        panel_rect = pygame.Rect(400, 200, 800, 500)
        pygame.draw.rect(surface, (30, 30, 40), panel_rect)
        pygame.draw.rect(surface, (200, 200, 200), panel_rect, 2)

        font_title = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        title = font_title.render(self.active_modal["display_name"].upper(), True, (255, 255, 255))
        surface.blit(title, (panel_rect.x + 30, panel_rect.y + 30))

        if self.active_modal["icon"]:
            big_icon = pygame.transform.scale(self.active_modal["icon"], (120, 120))
            surface.blit(big_icon, (panel_rect.x + 30, panel_rect.y + 100))

        cost = self.active_modal["cost"]
        time = cost // 10
        cost_txt = font_med.render(f"Base Research Cost: {cost} pts ({time} days)", True, (255, 215, 0))
        surface.blit(cost_txt, (panel_rect.x + 200, panel_rect.y + 100))

        stats = self.get_stats_for_modal(self.active_modal["display_name"])
        y_off = panel_rect.y + 160
        for line in stats:
            surf_line = font_small.render(line, True, (200, 200, 200))
            surface.blit(surf_line, (panel_rect.x + 200, y_off))
            y_off += 30

    def get_stats_for_modal(self, display_name):
        if display_name in self.unit_library:
            s = self.unit_library[display_name]
            return [
                f"Combat Stats:   ❤️ HP: {s.get('health',0)}   |   ⚔️ Attack: {s.get('attack',0)}   |   🛡️ Defense: {s.get('defense',0)}   |   ⚡ Speed: {s.get('speed',0)}",
                f"Production Cost:   ⚙️ {s.get('cost_materials',0)}   |   👤 {s.get('cost_manpower',0)}   |   ⛽ {s.get('cost_fuel',0)}"
            ]
        elif display_name in self.building_library:
            s = self.building_library[display_name]
            return [
                f"Construction Time: {s.get('time',0)} days",
                f"Daily Yield:   ⚙️ +{s.get('prod_materials',0)}   |   👤 +{s.get('prod_manpower',0)}   |   ⛽ +{s.get('prod_fuel',0)}",
                f"Construction Cost:   ⚙️ {s.get('cost_materials',0)}   |   👤 {s.get('cost_manpower',0)}"
            ]
        return ["Advanced statistical data unavailable."]

    def render_completed_text_list(self, surface):
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.get("research", {})
        
        text_font = fonts.get("button")
        label_font = fonts.get("heading2")
        
        organized = {cat: [] for cat in self.categories if cat != "COMPLETED"}
        for tech_id, data in self.tech_tree.items():
            cat = data["category"]
            lvl = res_levels.get(tech_id, 0)
            organized[cat].append((tech_id, lvl, data["max_lvl"]))

        start_y = 150
        column_width = 320
        
        for i, (cat_name, techs) in enumerate(organized.items()):
            curr_x = 50 + (i * column_width)
            curr_y = start_y
            
            head = label_font.render(cat_name, True, (255, 215, 0))
            surface.blit(head, (curr_x, curr_y))
            curr_y += 40
            
            techs.sort(key=lambda x: x[2] != 9999)
            
            has_inf_spacer = False
            for tech_id, lvl, max_lvl in techs:
                if has_inf_spacer and max_lvl != 9999:
                    curr_y += 15
                    has_inf_spacer = False
                if max_lvl == 9999: has_inf_spacer = True

                display_name = tech_id.replace('_', ' ').title()
                
                if max_lvl == 9999:
                    val_text = f": Type {lvl}"
                elif max_lvl == 1:
                    val_text = ": Level 1" if lvl >= 1 else ": Level 0"
                else:
                    val_text = f": Level {lvl}"

                color = (200, 200, 200) if lvl > 0 else (100, 100, 100)
                if tech_id in ["infantry"] and lvl <= 1800:
                    color = (140, 140, 140)

                txt_surf = text_font.render(f"{display_name}{val_text}", True, color)
                surface.blit(txt_surf, (curr_x + 10, curr_y))
                curr_y += 28

    def additional_draw(self, surface):
        if not self.map_screen: return
        
        # --- Axis Rendering ---
        self.draw_timeline_axis(surface)
        
        # --- Standard Header ---
        pygame.draw.rect(surface, (40, 40, 50), (0, 0, SCREEN_WIDTH, 70))
        pygame.draw.line(surface, (200, 200, 200), (0, 70), (SCREEN_WIDTH, 70), 2)

        font = fonts.get("heading1")
        ts = font.render(f"VIEWING: {self.current_category}", True, (255, 255, 255))
        surface.blit(ts, (SCREEN_WIDTH//2 - ts.get_width()//2, 75))

        output_text = font.render("RESEARCH OUTPUT: 10 pts/day", True, (0, 255, 255))
        surface.blit(output_text, (SCREEN_WIDTH - output_text.get_width() - 30, 85))

        if self.current_category == "COMPLETED":
            self.render_completed_text_list(surface)
        elif self.current_category != "INFANTRY":
            player_data = self.map_screen.nation_data[self.map_screen.player_country]
            res_levels = player_data.get("research", {})
            self.draw_connections(surface, res_levels)

        if not self.active_modal and self.current_category != "COMPLETED":
            self.draw_hud_slots(surface)

        if self.active_modal:
            self.draw_subscreen_modal(surface)

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        if self.active_modal:
            self.close_modal()
        else:
            self.exit_to_map()