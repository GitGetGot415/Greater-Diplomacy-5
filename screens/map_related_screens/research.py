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
        
        self.active_modal = None # Holds data for the tech subscreen

        # --- ADD THIS: Load custom backgrounds ---
        try:
            # Make sure to use .convert() for large background images to optimize performance
            self.navy_bg = pygame.image.load("assets/ocean_bg.png").convert()
            # Optional: Scale it to fit the area below your top bar
            self.navy_bg = pygame.transform.scale(self.navy_bg, (SCREEN_WIDTH, SCREEN_HEIGHT - 70))
        except:
            self.navy_bg = None
            
        self.setup_nodes()

    def load_json(self, path):
        if os.path.exists(path):
            with open(path, "r") as f: return json.load(f)
        print(f"Error: {path} not found!")
        return {}

    def setup_nodes(self):
        """Hardcoded specific coordinates for the visual tech tree layout."""
        self.nodes = {
            "TANKS": [
                {"key": "ww1_armored_car", "lvl": 1, "pos": (150, 250)},
                {"key": "armored_car", "lvl": 1, "pos": (300, 250)},
                {"key": "armored_car", "lvl": 2, "pos": (450, 250)},
                {"key": "armored_car", "lvl": 3, "pos": (600, 250)},
                {"key": "armored_car", "lvl": 4, "pos": (750, 250)},
                {"key": "armored_car", "lvl": 5, "pos": (900, 250)},
                
                {"key": "ww1_tank", "lvl": 1, "pos": (150, 450)},
                {"key": "light_tank", "lvl": 1, "pos": (300, 350)},
                {"key": "light_tank", "lvl": 2, "pos": (450, 350)},
                {"key": "light_tank", "lvl": 3, "pos": (600, 350)},
                {"key": "light_tank", "lvl": 4, "pos": (750, 350)},
                {"key": "light_tank", "lvl": 5, "pos": (900, 350)},
                
                {"key": "medium_tank", "lvl": 1, "pos": (300, 450)},
                {"key": "medium_tank", "lvl": 2, "pos": (450, 450)},
                {"key": "medium_tank", "lvl": 3, "pos": (600, 450)},
                
                {"key": "heavy_tank", "lvl": 1, "pos": (300, 550)},
                {"key": "heavy_tank", "lvl": 2, "pos": (450, 550)},
                {"key": "heavy_tank", "lvl": 3, "pos": (600, 550)},
                
                {"key": "main_battle_tank", "lvl": 1, "pos": (750, 500)}
            ],
            "NAVY": [
                {"key": "carrack", "lvl": 1, "pos": (100, 350)},
                {"key": "ironclad", "lvl": 1, "pos": (220, 350)},
                {"key": "pre-dreadnaught", "lvl": 1, "pos": (340, 350)},
                {"key": "dreadnaught", "lvl": 1, "pos": (460, 350)},
                
                {"key": "destroyer", "lvl": 1, "pos": (580, 300)},
                {"key": "destroyer", "lvl": 2, "pos": (700, 300)},
                {"key": "destroyer", "lvl": 3, "pos": (820, 300)},
                {"key": "destroyer", "lvl": 4, "pos": (940, 300)},
                {"key": "destroyer", "lvl": 5, "pos": (1060, 300)},
                {"key": "destroyer", "lvl": 6, "pos": (1180, 300)},
                {"key": "destroyer", "lvl": 7, "pos": (1300, 300)},
                {"key": "destroyer", "lvl": 8, "pos": (1420, 300)},
                
                {"key": "aircraft_carrier", "lvl": 1, "pos": (580, 400)},
                {"key": "aircraft_carrier", "lvl": 2, "pos": (700, 400)},
                {"key": "aircraft_carrier", "lvl": 3, "pos": (820, 400)},
                {"key": "aircraft_carrier", "lvl": 4, "pos": (940, 400)}
            ],
            "INDUSTRY": [
                {"key": "workshop", "lvl": 1, "pos": (150, 250)},
                {"key": "workshop", "lvl": 2, "pos": (270, 250)},
                {"key": "workshop", "lvl": 3, "pos": (390, 250)},
                {"key": "workshop", "lvl": 4, "pos": (510, 250)},
                {"key": "workshop", "lvl": 5, "pos": (630, 250)},
                {"key": "basic_factory", "lvl": 1, "pos": (750, 250)},
                
                {"key": "factory", "lvl": 1, "pos": (870, 250)},
                {"key": "factory", "lvl": 2, "pos": (990, 250)},
                {"key": "factory", "lvl": 3, "pos": (1110, 250)},
                {"key": "factory", "lvl": 4, "pos": (1230, 250)},
                {"key": "factory", "lvl": 5, "pos": (1350, 250)},
                
                {"key": "bergius_process", "lvl": 1, "pos": (150, 450)},
                {"key": "synthetic_fuel_experiments", "lvl": 1, "pos": (300, 450)},
                {"key": "fuel_refining", "lvl": 1, "pos": (450, 450)},
                {"key": "fuel_refining", "lvl": 2, "pos": (600, 450)},
                {"key": "fuel_refining", "lvl": 3, "pos": (750, 450)}
            ]
        }

    def get_display_name(self, tech_key, lvl):
        if tech_key == "infantry": return "Infantry"
        
        romans = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}
        
        # Exceptions
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
        
        # Buildings
        if tech_key in ["workshop", "factory", "fuel_refining"]:
            if tech_key == "fuel_refining": base_name = "Synthetic Refinery" 
            return f"{base_name} Lvl {lvl}"
            
        # Units
        return f"{base_name} {romans.get(lvl, str(lvl))}"

    def start_research(self, map_ref):
        self.map_screen = map_ref
        self.current_category = "INFANTRY"
        self.active_modal = None
        self.refresh_ui()

    def set_category(self, cat):
        self.current_category = cat
        self.active_modal = None
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        if not self.map_screen or self.map_screen.player_country == "None": return
        player_data = self.map_screen.nation_data[self.map_screen.player_country]
        res_levels = player_data.setdefault("research", {})
        queue = player_data.setdefault("research_queue", [])
        progress_cache = player_data.setdefault("research_progress", {})

        # --- MODAL SUBSCREEN MODE ---
        if self.active_modal:
            # We are inside the modal, so we only generate buttons for the subscreen
            st = self.active_modal["status"]
            panel_x, panel_y = 400, 200
            
            # Cancel/Close Button
            self.elements.append(Button(panel_x + 650, panel_y + 430, "small", "red", "Cancel", self.close_modal))
            
            # Action Button
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
        
        # --- STANDARD SCREEN MODE ---
        self.elements.append(Button(20, 10, "small", "red", "Exit", self.exit_to_map))

        start_x = 180 
        for i, cat in enumerate(self.categories):
            color = "green" if self.current_category == cat else "blue"
            btn = Button(start_x + (i * 205), 10, "medium", color, cat, lambda c=cat: self.set_category(c))
            self.elements.append(btn)

        if self.current_category == "COMPLETED":
            pass # Drawn in additional_draw
        elif self.current_category == "INFANTRY":
            self.draw_infantry_content(res_levels, queue, progress_cache)
        else:
            self.draw_tech_nodes(res_levels, queue)

    def draw_infantry_content(self, res_levels, queue, progress_cache):
        # Keep Infantry as a vertical standard list since it has 9999 levels
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
        for node in self.nodes.get(self.current_category, []):
            tech_key = node["key"]
            lvl = node["lvl"]
            
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
            
            btn = Button(node["pos"][0], node["pos"][1], "tech_square", btn_color, display_name, 
                         lambda n=node_info: self.open_modal(n), image=icon, show_text=False)
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
    def additional_draw(self, surface):
        if not self.map_screen: return
        
        # --- ADD THIS: CUSTOM BACKGROUNDS / HARDCODED TEXT ---
        if self.current_category == "NAVY" and self.navy_bg:
            # Draw ocean background starting just below the top UI bar (y=70)
            surface.blit(self.navy_bg, (0, 70))
            
        elif self.current_category == "TANKS":
            # Example: Draw some hardcoded watermark text in the background
            bg_font = fonts.get("country_name_display") # Using your massive font preset
            # Dark, faint color so it blends into the background
            bg_text = bg_font.render("ARMOR DEVELOPMENT", True, (40, 40, 50)) 
            surface.blit(bg_text, (SCREEN_WIDTH//2 - bg_text.get_width()//2, 300))
        # -----------------------------------------------------

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

        # Draw HUD Slots (Skip if modal is active to prevent visual clutter)
        if not self.active_modal and self.current_category != "COMPLETED":
            self.draw_hud_slots(surface)

        # Draw Modal Subscreen if active
        if self.active_modal:
            self.draw_subscreen_modal(surface)

    def draw_connections(self, surface, res_levels):
        nodes = self.nodes.get(self.current_category, [])
        lookup = {(n["key"], n["lvl"]): n["pos"] for n in nodes}
        
        for node in nodes:
            k = node["key"]
            l = node["lvl"]
            
            # Center of the 80x80 tech square
            p1 = (node["pos"][0] + 40, node["pos"][1] + 40)
            
            if l > 1:
                prev_pos = lookup.get((k, l - 1))
                if prev_pos:
                    p2 = (prev_pos[0] + 40, prev_pos[1] + 40)
                    color = (0, 255, 0) if res_levels.get(k, 0) >= l - 1 else (100, 100, 100)
                    pygame.draw.line(surface, color, p2, p1, 3)
            elif l == 1:
                reqs = self.tech_tree[k].get("req", {})
                if "OR" in reqs:
                    for sub_req in reqs["OR"]:
                        for req_k, req_lvl in sub_req.items():
                            prev_pos = lookup.get((req_k, req_lvl))
                            if prev_pos:
                                p2 = (prev_pos[0] + 40, prev_pos[1] + 40)
                                color = (0, 255, 0) if res_levels.get(req_k, 0) >= req_lvl else (100, 100, 100)
                                pygame.draw.line(surface, color, p2, p1, 3)
                else:
                    for req_k, req_lvl in reqs.items():
                        prev_pos = lookup.get((req_k, req_lvl))
                        if prev_pos:
                            p2 = (prev_pos[0] + 40, prev_pos[1] + 40)
                            color = (0, 255, 0) if res_levels.get(req_k, 0) >= req_lvl else (100, 100, 100)
                            pygame.draw.line(surface, color, p2, p1, 3)

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
        # Dark overlay
        overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        # Panel
        panel_rect = pygame.Rect(400, 200, 800, 500)
        pygame.draw.rect(surface, (30, 30, 40), panel_rect)
        pygame.draw.rect(surface, (200, 200, 200), panel_rect, 2)

        font_title = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        # Title & Icon
        title = font_title.render(self.active_modal["display_name"].upper(), True, (255, 255, 255))
        surface.blit(title, (panel_rect.x + 30, panel_rect.y + 30))

        if self.active_modal["icon"]:
            # Scale up the icon for the modal display
            big_icon = pygame.transform.scale(self.active_modal["icon"], (120, 120))
            surface.blit(big_icon, (panel_rect.x + 30, panel_rect.y + 100))

        # Time & Cost
        cost = self.active_modal["cost"]
        time = cost // 10
        cost_txt = font_med.render(f"Base Research Cost: {cost} pts ({time} days)", True, (255, 215, 0))
        surface.blit(cost_txt, (panel_rect.x + 200, panel_rect.y + 100))

        # Stats
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
                f"Production Cost:   💰 {s.get('cost_money',0)}   |   ⚙️ {s.get('cost_materials',0)}   |   👤 {s.get('cost_manpower',0)}   |   ⛽ {s.get('cost_fuel',0)}"
            ]
        elif display_name in self.building_library:
            s = self.building_library[display_name]
            return [
                f"Construction Time: {s.get('time',0)} days",
                f"Daily Yield:   💰 +{s.get('prod_money',0)}   |   ⚙️ +{s.get('prod_materials',0)}   |   👤 +{s.get('prod_manpower',0)}   |   ⛽ +{s.get('prod_fuel',0)}",
                f"Construction Cost:   💰 {s.get('cost_money',0)}   |   ⚙️ {s.get('cost_materials',0)}   |   👤 {s.get('cost_manpower',0)}"
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

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        if self.active_modal:
            self.close_modal()
        else:
            self.exit_to_map()