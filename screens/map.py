import pygame
import random
import math
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.ui import buttons, event_handler, editor_menus
from data import save_map
from map_functions.logic import edit_province_ownership, refresh_map, turn_processor
from map_functions.camera.camera_handler import MapCamera
from map_functions.rendering import map_renderer
from data import country_io, load_map
from map_functions.logic import map_utils
from map_functions.logic import diplomacy_logic
from data.economy_data import BASE_YIELDS, UPKEEP_MODIFIER
from map_functions.ui.minimap import UI_LEFT_OFFSET
from map_functions.rendering.font_manager import fonts # <-- Import here

class Map(GameState):
    def __init__(self, load_path=None, is_scenario=False, is_random=False): 
        super().__init__()

        self.brush_building = "None" 
        self.brush_unit = "None"    
        self.editor_mode = "NATION" 

        # --- 1. Basic State Variables ---
        self.selection_mode = is_scenario
        self.pending_selection = None 
        self.player_country = "None"

        self.secondary_modes = ["UNITS", "ECONOMY", "BLANK"]
        self.sec_idx = 0
        self.secondary_mode = self.secondary_modes[2]
        
        self.base_layer = "POLITICAL" 
        self.load_path = load_path

        self.is_editor = (self.load_path is None and not is_scenario) 
        if self.is_editor:
            self.player_country = "Editor"
            self.selection_mode = False 
            
        self.painting_active = False 
        self.brush_nation = "Unclaimed" 
        
        # --- 2. Data Loading ---
        load_map.load_map_assets(self, load_path)

        # --- 3. Visuals & UI Setup ---
        self.bg_color = (20, 20, 20)
        self.font = fonts.get("normal") # <-- NEW
        self.small_font = fonts.get("tiny") # <-- NEW
        
        self.top_ui_height = self.bot_ui_height = 60
        self.total_ui_h = 120
        self.top_bar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, 60)
        self.bot_bar_rect = pygame.Rect(0, SCREEN_HEIGHT - 60, SCREEN_WIDTH, 60)
        # red thingy to the left
        self.raised_rect = pygame.Rect(0, 0, UI_LEFT_OFFSET, SCREEN_HEIGHT)
        # ui background
        self.ui_background_rect = pygame.Rect(0, SCREEN_HEIGHT - 120, 220, SCREEN_HEIGHT)
        
        self.map_w, self.map_h = self.id_map.get_size()
        self.min_zoom = (SCREEN_HEIGHT - self.total_ui_h) / self.map_h 
        self.camera = MapCamera(self.min_zoom)
        
        self.active_map = self.political_map if self.base_layer == "POLITICAL" else self.terrain_map
        self.map_mode = self.base_layer

        self.selected_province = self.hovered_province = self.last_hovered_id = None
        self.hover_glow_surf = self.hover_glow_rect = None
        self.feedback_text = ""
        self.feedback_timer = 0

        self.show_exit_confirmation = False 
        self.confirm_box_rect = pygame.Rect(0, 0, 400, 200) 
        
        load_map.load_map_assets(self, load_path)

        self.relations_map = self.id_map.copy()
        # self.cores_map = self.id_map.copy()

        if is_random:
            self.randomize_all_provinces()
            self.refresh_political_map()
            self.refresh_relations_map()

        buttons.render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})

        self.update_country_centers()

    # --- Properties ---
    @property
    def player_money(self):
        if self.player_country in self.nation_data:
            return self.nation_data[self.player_country].get("money", 0)
        return 0

    @player_money.setter
    def player_money(self, value):
        if self.player_country in self.nation_data:
            self.nation_data[self.player_country]["money"] = value

    @property
    def player_manpower(self):
        if self.player_country in self.nation_data:
            return self.nation_data[self.player_country].get("manpower", 0)
        return 0

    @player_manpower.setter
    def player_manpower(self, value):
        if self.player_country in self.nation_data:
            self.nation_data[self.player_country]["manpower"] = value

    @property
    def player_materials(self):
        if self.player_country in self.nation_data:
            return self.nation_data[self.player_country].get("materials", 0)
        return 0

    @property
    def player_fuel(self):
        if self.player_country in self.nation_data:
            return self.nation_data[self.player_country].get("fuel", 0)
        return 0

    # --- Logic Methods ---
    def set_view_mode(self, mode):
        self.secondary_mode = mode
        self.show_feedback(f"View: {mode}")

    def cycle_secondary_mode(self):
        self.sec_idx = (self.sec_idx + 1) % len(self.secondary_modes)
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        self.show_feedback(f"View Mode: {self.secondary_mode}")
        
    def select_player_country(self, province):
        owner = province.get("owner", "Unclaimed")
        if owner in self.nation_data and self.nation_data[owner].get("is_playable"):
            self.pending_selection = owner
            self.selected_province = province 
            self.show_feedback(f"Selected {owner.title()}...")
        else:
            self.show_feedback("Cannot select unowned or non-playable territory")

    def confirm_player_country(self):
        if self.pending_selection:
            self.player_country = self.pending_selection
            self.selection_mode = False
            self.pending_selection = None
            
            self.selected_province = None 
            self.hovered_province = None
            self.hover_glow_surf = None
            
            self.show_feedback(f"Now playing as {self.player_country}")
            buttons.render_buttons(self)
            
    def cancel_selection(self):
        self.pending_selection = None
        self.selected_province = None

    def deselect_province(self):
        self.selected_province = None
        self.hovered_province = None
        self.hover_glow_surf = None
        self.last_hovered_id = None
        self.show_feedback("Map Unlocked")

    def set_terrain(self): 
        self.base_layer = "TERRAIN"
        self.active_map = self.terrain_map
        self.show_feedback("Mode: Terrain")

    def set_political(self): 
        self.base_layer = "POLITICAL"
        self.active_map = self.political_map
        # self.refresh_political_map()
        self.show_feedback("Mode: Political")
        
    def set_relations(self): 
        self.base_layer = "RELATIONS"
        self.active_map = self.relations_map
        # self.refresh_relations_map()
        self.show_feedback("Mode: Relations")

    def set_cores(self): 
        self.base_layer = "CORES"
        self.active_map = self.cores_map
        # self.refresh_cores_map()
        self.show_feedback("Mode: Cores")

    def save_map_data(self): 
        save_map.save_map_data(self)

    def refresh_political_map(self): 
        refresh_map.refresh_political_map(self)
        
    def refresh_relations_map(self): 
        refresh_map.refresh_relations_map(self)
    
    def select_core_brush(self): 
        editor_menus.select_core_brush(self)

    def refresh_cores_map(self): 
        refresh_map.refresh_cores_map(self)

    def select_resource_brush(self):
        editor_menus.select_resource_brush(self)

    def auto_assign_cores(self):
        """Automatically assigns a core to whoever owns the province."""
        for province in self.map_data.values():
            owner = province.get("owner", "Unclaimed")
            if owner not in ["Unclaimed", "None", "Ocean", "Lakes"]:
                province["cores"] = [owner]
            else:
                province["cores"] = []
                
        self.show_feedback("Auto-assigned all cores!")
        
        # Rebuild the visual map immediately if we are looking at it
        if self.map_mode == "CORES":
            self.refresh_cores_map()

    def conquer_province(self): 
        if self.selected_province:
            nations_list = ["Rome", "Gaul", "Carthage"] 
            new_owner = random.choice(nations_list)
            edit_province_ownership.conquer_province(self, self.selected_province, new_owner)

    def exit_to_menu(self): 
        self.show_exit_confirmation = True
        for el in self.elements:
            el.visible = False

    def cancel_exit(self):
        self.show_exit_confirmation = False
        self.show_feedback("Exit cancelled")

    def confirm_exit(self):
        self.next_state, self.done = "MENU", True

    def reset_view(self): 
        self.camera.target_zoom, self.camera.target_pos = self.min_zoom, pygame.Vector2(0, 0)

    def advance_time(self):
        turn_processor.process_next_turn(self)

    def show_feedback(self, text): 
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()

    def additional_events(self, event): 
        event_handler.handle_map_events(self, event)

    def handle_declare_war(self):
        target = self.selected_province.get("owner")
        player_data = self.nation_data[self.player_country]
        at_war = target in player_data.get("at_war_with", [])
        
        action = "CEASEFIRE" if at_war else "WAR_DECLARATION"
        msg = diplomacy_logic.toggle_diplomacy_action(self.nation_data, self.player_country, target, action)
        self.show_feedback(msg)

    def handle_form_alliance(self):
        target = self.selected_province.get("owner")
        player_data = self.nation_data[self.player_country]
        allied = target in player_data.get("allied_with", [])
        
        action = "BREAK_ALLIANCE" if allied else "ALLIANCE_REQUEST"
        msg = diplomacy_logic.toggle_diplomacy_action(self.nation_data, self.player_country, target, action)
        self.show_feedback(msg)

    def handle_back_key(self):
        if self.selected_province:
            self.deselect_province()

    def additional_draw(self, surface): 
        map_renderer.draw_map_screen(self, surface)
        
    def randomize_all_provinces(self):
        playable_nations = [
            name for name, stats in self.nation_data.items() 
            if stats.get("is_playable") and name not in ["Ocean", "Lakes", "Unclaimed"]
        ]
        
        if not playable_nations:
            return

        for province in self.map_data.values():
            terrain = province.get("terrain", "")
            is_water = terrain in ["ocean", "coastal_sea", "inland_sea", "lakes"]
            if not is_water:
                new_owner = random.choice(playable_nations)
                province["owner"] = new_owner
        
        self.show_feedback("Map Randomized!")

    def get_player_economy_projections(self):
        YIELD_MONEY = BASE_YIELDS["money"]
        YIELD_MANPOWER = BASE_YIELDS["manpower"]
        YIELD_MATERIALS = BASE_YIELDS["materials"]
        YIELD_FUEL = BASE_YIELDS["fuel"]

        inc_money = 0
        inc_manpower = 0
        bonus = {"money":0, "manpower":0, "materials":0, "fuel":0}
        upkeep = {"money":0, "manpower":0, "materials":0, "fuel":0}

        if not hasattr(self, 'cached_unit_library'):
            import json, os
            self.cached_unit_library = json.load(open('data/json/unit_data.json')) if os.path.exists('data/json/unit_data.json') else {}
            self.cached_building_library = json.load(open('data/json/building_data.json')) if os.path.exists('data/json/building_data.json') else {}

        for province in self.map_data.values():
            owner = province.get("owner")
            if owner == self.player_country and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
                is_core = owner in province.get("cores", [])
                core_mult = 1.0 if is_core else 0.5
                manpower_mult = 1.0 if is_core else 0.0

                inc_money += core_mult
                inc_manpower += manpower_mult
                
                # --- RESOURCE PROJECTIONS ---
                res = province.get("resources", {})
                if isinstance(res, dict):
                    iron = int(res.get("Iron", 0))
                    coal = int(res.get("Coal", 0))
                    oil = int(res.get("Oil", 0))
                    
                    bonus["materials"] += iron * core_mult
                    bonus["fuel"] += (coal + oil) * core_mult

                for b_name in province.get("buildings", []):
                    stats = self.cached_building_library.get(b_name, {})
                    bonus["money"] += stats.get("prod_money", 0) * core_mult
                    bonus["manpower"] += stats.get("prod_manpower", 0) * manpower_mult
                    bonus["materials"] += stats.get("prod_materials", 0) * core_mult
                    bonus["fuel"] += stats.get("prod_fuel", 0) * core_mult
            
            for unit in province.get("units", []):
                if unit.get("owner") == self.player_country:
                    stats = self.cached_unit_library.get(unit["type"], {})
                    upkeep["money"] += stats.get("cost_money", 0) * UPKEEP_MODIFIER
                    upkeep["manpower"] += stats.get("cost_manpower", 0) * UPKEEP_MODIFIER
                    upkeep["materials"] += stats.get("cost_materials", 0) * UPKEEP_MODIFIER
                    upkeep["fuel"] += stats.get("cost_fuel", 0) * UPKEEP_MODIFIER

        total_inc = {
            "money": (inc_money * YIELD_MONEY) + bonus["money"],
            "manpower": (inc_manpower * YIELD_MANPOWER) + bonus["manpower"],
            "materials": (inc_money * YIELD_MATERIALS) + bonus["materials"],
            "fuel": (inc_money * YIELD_FUEL) + bonus["fuel"]
        }
        return total_inc, upkeep
    
    def refresh_nation_data(self):
        from data import country_io
        new_data = country_io.load_all_country_data()
        added_count = 0
        updated_count = 0
        
        for country, data in new_data.items():
            if country not in self.nation_data:
                self.nation_data[country] = data
                added_count += 1
            else:
                if "color" in data and self.nation_data[country].get("color") != data["color"]:
                    self.nation_data[country]["color"] = data["color"]
                    updated_count += 1
                if "name" in data:
                    self.nation_data[country]["name"] = data["name"]
                
        self.nation_colors = {name: tuple(stats["color"]) for name, stats in self.nation_data.items()}
        self.refresh_political_map()
        self.refresh_relations_map()
        self.show_feedback(f"Data Resynced! Added {added_count}, Updated {updated_count}.")
        
    def toggle_editor_brush_type(self):
        if self.editor_mode == "NATION":
            self.editor_mode = "BUILDING"
            self.show_feedback("Editor: Building Placement")
        else:
            self.editor_mode = "NATION"
            self.show_feedback("Editor: Nation Painting")

    # --- Screen Transitions ---
    def open_recruit(self):
        if self.selected_province:
            self.next_state, self.done = "RECRUIT", True

    def open_orders(self):
        if self.selected_province:
            self.next_state, self.done = "ORDERS", True

    def open_construction(self):
        if self.selected_province and self.selected_province.get("owner") == self.player_country:
            self.next_state, self.done = "CONSTRUCTION", True

    def open_research(self):
        self.next_state, self.done = "RESEARCH", True

    def open_economy_screen(self):
        self.next_state, self.done = "ECONOMY", True

    # --- Tkinter Wrappers (Imported from editor_menus.py) ---
    def editor_load_map(self):
        editor_menus.editor_load_map(self)

    def select_brush_nation(self):
        editor_menus.select_brush_nation(self)

    def select_building_brush(self):
        editor_menus.select_building_brush(self)

    def open_editor_economy(self):
        editor_menus.open_editor_economy(self)

    def open_map_research_editor(self):
        editor_menus.open_map_research_editor(self)

    def select_unit_brush(self):
        editor_menus.select_unit_brush(self)
    
    def open_editor_date(self):
        editor_menus.open_editor_date(self)
    
    def open_edit_country(self):
        if self.player_country and self.player_country != "None":
            self.next_state, self.done = "EDIT_COUNTRY", True

    def update_country_centers(self):
        """Calculates the visual center, rotation, and physical spread for every country landmass."""
        self.country_text_blobs = []
        visited = set()

        # Iterate through every province by ID
        for prov_id, prov in self.id_to_province.items():
            owner = prov.get("owner")
            if not owner or owner in ["None", "Unclaimed", "Ocean", "Lakes"]:
                continue
            
            # If we haven't checked this province yet, it's a new landmass
            if prov_id not in visited:
                comp = []
                queue = [prov]
                visited.add(prov_id)
                
                # Flood-fill to find all connected provinces with the SAME owner
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for n_id in curr.get("neighbors", []):
                        if n_id not in visited:
                            n_prov = self.id_to_province.get(n_id)
                            if n_prov and n_prov.get("owner") == owner:
                                visited.add(n_id)
                                queue.append(n_prov)
                
                count = len(comp)
                if count == 0: continue
                
                # 1. Average center (Mean)
                avg_x = sum(c["center"][0] for c in comp) / count
                avg_y = sum(c["center"][1] for c in comp) / count
                
                # 2. Covariance Matrix calculations (for rotation and scale)
                c_xx = sum((c["center"][0] - avg_x)**2 for c in comp) / count
                c_yy = sum((c["center"][1] - avg_y)**2 for c in comp) / count
                c_xy = sum((c["center"][0] - avg_x) * (c["center"][1] - avg_y) for c in comp) / count
                
                # Calculate angle (math.atan2 handles division by zero safely)
                # atan2 returns radians, we need degrees. Pygame rotates counter-clockwise.
                angle_rad = 0.5 * math.atan2(2 * c_xy, c_xx - c_yy)
                display_angle = -math.degrees(angle_rad) 
                
                # 3. Calculate Principal Axes (Length and Thickness) via Eigenvalues
                W = (c_xx + c_yy) / 2.0
                D = math.sqrt(((c_xx - c_yy) / 2.0)**2 + c_xy**2)
                
                major_variance = W + D
                minor_variance = max(W - D, 1.0) # Prevent zero/negative variance
                
                # Convert variance to spatial distance. 
                # 3.0 is a tuning constant (adjust if all text is globally too big/small)
                country_length = math.sqrt(major_variance) * 3.0
                country_thickness = math.sqrt(minor_variance) * 3.0
                
                # Snap to the closest actual province in this component
                closest_prov = min(comp, key=lambda c: (c["center"][0] - avg_x)**2 + (c["center"][1] - avg_y)**2)
                
                self.country_text_blobs.append({
                    "owner": owner,
                    "cx": closest_prov["center"][0],
                    "cy": closest_prov["center"][1],
                    "length": country_length,       # NEW
                    "thickness": country_thickness, # NEW
                    "spread": math.sqrt(c_xx + c_yy), # Kept for your sorting logic
                    "count": count, 
                    "angle": display_angle
                })

    # --- Pygame Core Loop Updates ---
    def update(self):
        self.camera.update(self, SCREEN_HEIGHT)
        for el in self.elements:
            el.visible = False

            if hasattr(el, 'text'):
                if el.text == "Terrain":
                    el.is_selected = (self.base_layer == "TERRAIN")
                elif el.text == "Political":
                    el.is_selected = (self.base_layer == "POLITICAL")
                elif el.text == "Relations":
                    el.is_selected = (self.base_layer == "RELATIONS")
                elif el.text == "Cores":
                    el.is_selected = (self.base_layer == "CORES")
                elif el.text == "Units":
                    el.is_selected = (self.secondary_mode == "UNITS")
                elif el.text == "Blank":
                    el.is_selected = (self.secondary_mode == "BLANK")
                elif el.text == "Economy":
                    if not getattr(el, 'show_text', True):
                        el.is_selected = (self.secondary_mode == "ECONOMY")
                    else:
                        el.is_selected = False
                elif el.text == "Resources":
                    el.is_selected = (self.secondary_mode == "RESOURCES")
                else:
                    el.is_selected = False

        if self.is_editor:
            for el in self.elements:
                if el.text in ["Terrain", "Political", "Relations", "Pol Refresh", "Rel Refresh", "Core Refresh", "Data Refresh", "Set Date", "Core Brush", "Cores", "Auto-Core", "Unit", "Map Tech", "Reset", "Save", "Load", "Nation", "Building", "Refresh", "Exit", "View Mode", "Units", "Economy", "Blank", "Resource", "Resources"]:
                    el.visible = True
                
                # Add highlighting for the editor Resource button
                if el.text == "Resource":
                    el.visible = True
                    if getattr(self, "editor_mode", "") == "RESOURCE":
                        el.color, el.hover_color = (150, 0, 150), (200, 50, 200)
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150)

                if el.text == "Nation":
                    el.visible = True
                    if self.editor_mode == "NATION":
                        el.color, el.hover_color = (0, 150, 0), (0, 200, 0)
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150)

                if el.text == "Building":
                    el.visible = True
                    if self.editor_mode == "BUILDING":
                        el.color, el.hover_color = (0, 100, 200), (50, 150, 255)
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150)
                
                # --- ADD THIS FOR CORE BRUSH ---
                if el.text == "Core Brush":
                    el.visible = True
                    if self.editor_mode == "CORE":
                        el.color, el.hover_color = (200, 100, 100), (255, 150, 150) # Pink
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150) # Grey

                # --- ADD THIS FOR UNIT BRUSH ---
                if el.text == "Unit":
                    el.visible = True
                    if self.editor_mode == "UNIT":
                        el.color, el.hover_color = (200, 0, 0), (255, 50, 50) # Red
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150) # Grey
            return

        is_sel = bool(self.selected_province)
        if self.selection_mode:
            self.btn_exit_to_menu.visible = True
            return
        
        contextual_buttons = {
            getattr(self, 'btn_go_build', None),
            getattr(self, 'btn_close_info', None), getattr(self, 'btn_exit_to_menu', None),
            getattr(self, 'btn_go_recruit', None), getattr(self, 'btn_go_orders', None),
            getattr(self, 'btn_declare_war', None), getattr(self, 'btn_form_alliance', None)
        }
        
        for el in self.elements:
            if el not in contextual_buttons:
                el.visible = True
                
        self.btn_exit_to_menu.visible = not is_sel
        
        # funny, a hardcoded number
        # gotta manually reset this whenever the number of buttons is changed
        for i in range(min(10, len(self.elements))): self.elements[i].visible = True
        self.btn_exit_to_menu.visible = not is_sel
        self.btn_close_info.visible = is_sel

        if is_sel:
            owner = self.selected_province.get("owner", "Unclaimed")
            player_data = self.nation_data.get(self.player_country, {})
            pending = player_data.get("pending_diplomacy", {})
            
            has_player_units = any(u['owner'] == self.player_country for u in self.selected_province.get("units", []))
            
            if owner == self.player_country or has_player_units:
                self.btn_go_orders.visible = True
                if owner == self.player_country:
                    terrain = self.selected_province.get("terrain", "")
                    is_land = terrain not in ["ocean", "coastal_sea", "inland_sea", "lakes"]
                    self.btn_go_build.visible = True
                    self.btn_go_recruit.visible = is_land

            if owner != self.player_country and owner in self.nation_data and self.nation_data[owner].get("is_playable"):
                self.btn_declare_war.rect.y = 550 
                self.btn_form_alliance.rect.y = 610
                
                at_war = owner in player_data.get("at_war_with", [])
                allied = owner in player_data.get("allied_with", [])

                if at_war:
                    self.btn_declare_war.visible = True
                    self.btn_declare_war.text = "UNDO CEASEFIRE" if pending.get(owner) == "CEASEFIRE" else "CEASEFIRE"
                elif allied:
                    self.btn_form_alliance.visible = True
                    self.btn_form_alliance.text = "UNDO BREAK" if pending.get(owner) == "BREAK_ALLIANCE" else "BREAK ALLIANCE"
                else:
                    self.btn_declare_war.visible = True
                    self.btn_declare_war.text = "DECLARING..." if pending.get(owner) == "WAR_DECLARATION" else "DECLARE WAR"
                    self.btn_form_alliance.visible = True
                    self.btn_form_alliance.text = "REQUESTING..." if pending.get(owner) == "ALLIANCE_REQUEST" else "FORM ALLIANCE"