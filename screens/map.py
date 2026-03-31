import pygame
import random
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.ui import buttons, event_handler, editor_menus
from map_functions.data import load_map, save_map
from map_functions.logic import edit_province_ownership, political_refresher, turn_processor
from map_functions.camera.camera_handler import MapCamera
from map_functions.rendering import map_renderer
from map_functions.data import country_io
from map_functions.logic import map_utils
from map_functions.logic import diplomacy_logic
from map_functions.data.economy_data import BASE_YIELDS, UPKEEP_MODIFIER
from map_functions.ui.minimap import UI_LEFT_OFFSET

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
        self.font = pygame.font.SysFont("Arial", 18)
        self.small_font = pygame.font.SysFont("Arial", 14)
        
        self.top_ui_height = self.bot_ui_height = 60
        self.total_ui_h = 120
        self.top_bar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, 60)
        self.bot_bar_rect = pygame.Rect(0, SCREEN_HEIGHT - 60, SCREEN_WIDTH, 60)
        # red thingy to the left
        self.raised_rect = pygame.Rect(0, 0, UI_LEFT_OFFSET, SCREEN_HEIGHT)
        
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

        if is_random:
            self.randomize_all_provinces()
            self.refresh_political_map()
            self.refresh_relations_map()

        buttons.render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})

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
        self.refresh_political_map()
        self.show_feedback("Mode: Political")
        
    def set_relations(self): 
        self.base_layer = "RELATIONS"
        self.active_map = self.relations_map
        self.refresh_relations_map()
        self.show_feedback("Mode: Relations")

    def save_map_data(self): 
        save_map.save_map_data(self)

    def refresh_political_map(self): 
        political_refresher.refresh_political_map(self)
        
    def refresh_relations_map(self): 
        political_refresher.refresh_relations_map(self)

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

        inc = 0
        bonus = {"money":0, "manpower":0, "materials":0, "fuel":0}
        upkeep = {"money":0, "manpower":0, "materials":0, "fuel":0}

        if not hasattr(self, 'cached_unit_library'):
            import json, os
            self.cached_unit_library = json.load(open('map_functions/data/json/unit_data.json')) if os.path.exists('map_functions/data/json/unit_data.json') else {}
            self.cached_building_library = json.load(open('map_functions/data/json/building_data.json')) if os.path.exists('map_functions/data/json/building_data.json') else {}

        for province in self.map_data.values():
            owner = province.get("owner")
            if owner == self.player_country and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
                inc += 1
                for b_name in province.get("buildings", []):
                    stats = self.cached_building_library.get(b_name, {})
                    bonus["money"] += stats.get("prod_money", 0)
                    bonus["manpower"] += stats.get("prod_manpower", 0)
                    bonus["materials"] += stats.get("prod_materials", 0)
                    bonus["fuel"] += stats.get("prod_fuel", 0)
            
            for unit in province.get("units", []):
                if unit.get("owner") == self.player_country:
                    stats = self.cached_unit_library.get(unit["type"], {})
                    upkeep["money"] += stats.get("cost_money", 0) * UPKEEP_MODIFIER
                    upkeep["manpower"] += stats.get("cost_manpower", 0) * UPKEEP_MODIFIER
                    upkeep["materials"] += stats.get("cost_materials", 0) * UPKEEP_MODIFIER
                    upkeep["fuel"] += stats.get("cost_fuel", 0) * UPKEEP_MODIFIER

        total_inc = {
            "money": (inc * YIELD_MONEY) + bonus["money"],
            "manpower": (inc * YIELD_MANPOWER) + bonus["manpower"],
            "materials": (inc * YIELD_MATERIALS) + bonus["materials"],
            "fuel": (inc * YIELD_FUEL) + bonus["fuel"]
        }
        return total_inc, upkeep
    
    def refresh_nation_data(self):
        from map_functions.data import country_io
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
                elif el.text == "Units":
                    el.is_selected = (self.secondary_mode == "UNITS")
                elif el.text == "Blank":
                    el.is_selected = (self.secondary_mode == "BLANK")
                elif el.text == "Economy":
                    if not getattr(el, 'show_text', True):
                        el.is_selected = (self.secondary_mode == "ECONOMY")
                    else:
                        el.is_selected = False
                else:
                    el.is_selected = False

        if self.is_editor:
            for el in self.elements:
                if el.text in ["Terrain", "Political", "Relations", "Pol Refresh", "Rel Refresh", "Data Refresh", "Unit", "Map Tech", "Reset", "Save", "Load", "Nation", "Building", "Refresh", "Exit", "View Mode", "Units", "Economy", "Blank"]:
                    el.visible = True
                
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
            return

        is_sel = bool(self.selected_province)
        if self.selection_mode:
            self.btn_exit_to_menu.visible = True
            return
        
        contextual_buttons = {
            getattr(self, 'btn_go_build', None), getattr(self, 'btn_conquer', None),
            getattr(self, 'btn_close_info', None), getattr(self, 'btn_exit_to_menu', None),
            getattr(self, 'btn_go_recruit', None), getattr(self, 'btn_go_orders', None),
            getattr(self, 'btn_declare_war', None), getattr(self, 'btn_form_alliance', None)
        }
        
        for el in self.elements:
            if el not in contextual_buttons:
                el.visible = True
                
        self.btn_exit_to_menu.visible = not is_sel
                
        for i in range(min(12, len(self.elements))): self.elements[i].visible = True
        self.btn_exit_to_menu.visible = not is_sel
        self.btn_close_info.visible = is_sel

        if is_sel:
            self.btn_conquer.visible = True
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