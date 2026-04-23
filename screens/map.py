import pygame
import random
import math
from data.map import load_map
from gameState import GameState
from map_functions.ui import buttons, event_handler, editor_menus
from data.map import save_map
from map_functions.logic import (
    edit_province_ownership,
    random_map_generator,
    diplomacy_logic,
    refresh_map,
    turn_processor,
    player_diplomacy_actions
)
from map_functions.camera.camera_handler import MapCamera
from map_functions.rendering import map_renderer
from map_functions.ui import spectator_menus
from data.constants import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    BASE_YIELDS,
    UPKEEP_MODIFIER,
    UI_LEFT_OFFSET,
    NON_CORE_MULTIPLIERS,
    WATER_TERRAINS,
    UNPLAYABLE_NATIONS,
    PROVINCE_UI
)
from map_functions.rendering.font_manager import fonts
from map_functions.logic import state_queries
from ui_elements import Button, process_text_input

class Map(GameState):
    def __init__(self, load_path=None, is_scenario=False, is_random=False, force_editor=False, random_settings=None, num_players=1):
        super().__init__()

        self.num_players = num_players
        self.active_players = getattr(self, 'active_players', []) # Usually empty on boot unless loaded from save
        self.current_player_index = getattr(self, 'current_player_index', 0)
        self.show_player_ready_screen = False

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

        self.is_editor = force_editor or (self.load_path is None and not is_scenario)
        if self.is_editor:
            self.player_country = "Editor"
            self.selection_mode = False 
            
        self.painting_active = False 
        self.brush_nation = "Unclaimed" 
        self.viewing_ai_moves = False
        
        # --- 2. Data Loading (FIXED ORDER) ---
        # Load the selected map BEFORE we do any camera math!
        if is_random and random_settings:
            load_map.load_map_assets(self, random_settings["map_path"])
            self.time_manager.year = random_settings["year"]
        else:
            load_map.load_map_assets(self, load_path)

        # --- 3. Visuals & UI Setup ---
        self.bg_color = (20, 20, 20)
        self.font = fonts.get("normal") 
        self.small_font = fonts.get("tiny") 
        
        self.top_ui_height = self.bot_ui_height = 60
        self.total_ui_h = 120
        self.top_bar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, 60)
        self.bot_bar_rect = pygame.Rect(0, SCREEN_HEIGHT - 60, SCREEN_WIDTH, 60)
        self.raised_rect = pygame.Rect(0, 0, UI_LEFT_OFFSET, SCREEN_HEIGHT)
        self.ui_background_rect = pygame.Rect(0, SCREEN_HEIGHT - 120, 220, SCREEN_HEIGHT)
        
        # Now these grab the dimensions of the CORRECT map
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

        self.relations_map = self.id_map.copy()

        # --- 3. RUN THE RANDOMIZER ---
        # Now that the map data and nation data actually exist, we can randomize them
        if is_random and random_settings:
            random_map_generator.randomize_all_provinces(self, random_settings)

        # --- 4. REFRESH MAPS ---
        self.refresh_political_map()
        self.refresh_relations_map()
        self.refresh_cores_map()
        
        buttons.render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})

        self.update_country_centers()

    # --- Properties ---
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

    # 2. UPDATE confirm logic to loop until all players are picked
    def confirm_player_country(self):
        if self.pending_selection:
            self.active_players.append(self.pending_selection)
            
            self.selected_province = None 
            self.hovered_province = None
            self.hover_glow_surf = None
            
            if len(self.active_players) < self.num_players:
                self.show_feedback(f"Player {len(self.active_players) + 1}, pick a country!")
                self.pending_selection = None
            else:
                # Everyone picked, start with Player 1
                self.current_player_index = 0
                self.player_country = self.active_players[0]
                self.selection_mode = False
                self.pending_selection = None
                
                self.show_feedback(f"Now playing as {self.player_country}")
                buttons.render_buttons(self)
                self.refresh_relations_map()

    # --- NEW SPECTATOR LOGIC ---
    def start_spectator(self):
        self.player_country = "Spectator"
        if "Spectator" not in self.nation_data:
            self.nation_data["Spectator"] = {
                "name": "Spectator",
                "color": [200, 200, 200],
                "is_playable": False,
                "at_war_with": [],
                "allied_with": [],
                "pending_diplomacy": {}
            }
        self.active_players.append("Spectator")
        
        if len(self.active_players) < self.num_players:
            self.show_feedback(f"Player {len(self.active_players) + 1}, pick a country!")
            self.pending_selection = None
        else:
            self.current_player_index = 0
            self.player_country = self.active_players[0]
            self.selection_mode = False
            self.pending_selection = None
            self.show_feedback(f"Now playing as {self.player_country}")
            
            buttons.render_buttons(self)
            self.refresh_relations_map()

    def force_war_menu(self): spectator_menus.force_war_menu(self)
    def force_peace_menu(self): spectator_menus.force_peace_menu(self)
    def force_alliance_menu(self): spectator_menus.force_alliance_menu(self)
    def force_break_alliance_menu(self): spectator_menus.force_break_alliance_menu(self)
            
    def cancel_selection(self):
        self.pending_selection = None
        self.selected_province = None

    def deselect_province(self):
        # --- Auto-save or clear direct message draft on exit ---
        if self.selected_province:
            owner = self.selected_province.get("owner")
            is_foreign = state_queries.is_foreign_playable(owner, self.player_country, self.nation_data)
            if is_foreign:
                draft = getattr(self, "mail_draft_text", "").strip()
                if draft:
                    diplomacy_logic.queue_text_message(self.nation_data, self.player_country, owner, draft)
                else:
                    diplomacy_logic.cancel_text_message(self.nation_data, self.player_country, owner)
                self.mail_input_active = False

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

    def open_messages(self):
        self.next_state, self.done = "MESSAGES", True

    def auto_assign_cores(self):
        # Automatically assigns a core to whoever owns the province.
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

    # 3. INTERCEPT NEXT TURN
    def advance_time(self):
        # PHASE 2: Resolve the turn if we are currently viewing AI moves
        if getattr(self, 'viewing_ai_moves', False):
            self.draw_turn_loading_screen("Resolving Orders...")
            turn_processor.resolve_turn(self)
            self.refresh_political_map()
            self.refresh_relations_map()
            self.viewing_ai_moves = False

            # If playing multiplayer, show the ready screen for Player 1 again
            if hasattr(self, 'active_players') and len(self.active_players) > 1:
                self.show_player_ready_screen = True

            buttons.render_buttons(self) 
            return

        # PHASE 1: Prepare the turn and generate AI moves
        if hasattr(self, 'active_players') and len(self.active_players) > 1:
            self.current_player_index += 1
            
            if self.current_player_index < len(self.active_players):
                # Next player's turn to issue orders
                self.player_country = self.active_players[self.current_player_index]
                self.show_player_ready_screen = True
            else:
                # All players have gone, loop back to player 1 and PREPARE the turn!
                self.current_player_index = 0
                self.player_country = self.active_players[0]
                
                # --- Show loading screen and explicitly refresh maps ---
                self.draw_turn_loading_screen("AI is thinking...")
                turn_processor.prepare_turn(self)
                self.refresh_political_map() 
                self.refresh_relations_map() 
                
                self.viewing_ai_moves = True
                buttons.render_buttons(self) 
        else:
            self.draw_turn_loading_screen("AI is thinking...")
            turn_processor.prepare_turn(self)
            self.refresh_political_map()    
            self.refresh_relations_map()    
            self.viewing_ai_moves = True
            buttons.render_buttons(self) 

    def draw_turn_loading_screen(self, text="Processing Turn & Updating Map..."):
        # Draws an overlay informing the player the turn is processing.
        surf = pygame.display.get_surface()
        if surf:
            overlay = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 200))
            surf.blit(overlay, (0, 0))

            font = fonts.get("title")
            txt = font.render(text, True, (255, 255, 255))
            surf.blit(txt, txt.get_rect(center=(surf.get_width()//2, surf.get_height()//2 - 40)))

            pygame.display.flip()

    def show_feedback(self, text): 
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()

    def additional_events(self, event): 
        event_handler.handle_map_events(self, event)

    def sync_units_to_data(self):
        # Forces all units currently on the map to adopt the stats from unit_data.json.
        import json, os
        unit_path = 'data/json/unit_data.json'
        
        if not os.path.exists(unit_path):
            self.show_feedback("Error: unit_data.json not found!")
            return
            
        with open(unit_path, 'r') as f:
            unit_library = json.load(f)
            
        updated_count = 0
        for province in self.map_data.values():
            for unit in province.get("units", []):
                u_type = unit.get("type")
                if u_type in unit_library:
                    stats = unit_library[u_type]
                    
                    unit["max_health"] = stats.get("health", 100)
                    unit["health"] = stats.get("health", 100)
                    unit["attack"] = stats.get("attack", 5)
                    unit["defense"] = stats.get("defense", 0)
                    unit["speed"] = stats.get("speed", 1)
                    
                    updated_count += 1
                    
        self.show_feedback(f"Synced {updated_count} units on map!")

    def handle_declare_war(self):
        player_diplomacy_actions.handle_declare_war(self)

    def handle_form_alliance(self):
        player_diplomacy_actions.handle_form_alliance(self)

    def handle_back_key(self):
        if self.selected_province:
            self.deselect_province()

    # Changed handle_orders_key to correctly utilize state queries instead of duplicate list comprehensions
    def handle_orders_key(self):
        if self.selected_province and not self.selection_mode:
            owner = self.selected_province.get("owner", "Unclaimed")
            has_player_units = state_queries.has_units_in_province(self.player_country, self.selected_province)
            
            # Replicate the button visibility condition
            if owner == self.player_country or has_player_units:
                self.open_orders()

    def additional_draw(self, surface): 
        map_renderer.draw_map_screen(self, surface)
    
    def refresh_nation_data(self):
        from data.io import country_io
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

                # --- SYNC RESEARCH ---
                # This ensures the active map inherits any new tech you added 
                # to the JSON without deleting existing research progress.
                if "research" in data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, start_val in data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = start_val
                            updated_count += 1
                
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
        # Calculates the visual center, rotation, and physical spread for every country landmass.
        self.country_text_blobs = []
        visited = set()

        # Iterate through every province by ID
        for prov_id, prov in self.id_to_province.items():
            owner = prov.get("owner")
            if not owner or owner in UNPLAYABLE_NATIONS:
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
                minor_variance = max(W - D, 1.0)
                
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
                    "length": country_length,
                    "thickness": country_thickness,
                    "spread": math.sqrt(c_xx + c_yy),
                    "count": count, 
                    "angle": display_angle
                })

    # --- Pygame Core Loop Updates ---
    def update(self):
        self.camera.update(self, SCREEN_HEIGHT)

        # NEW: Prevent UI drawing if ready screen is active
        if getattr(self, 'show_player_ready_screen', False):
            for el in self.elements:
                el.visible = False
            return

        # --- DYNAMIC OCEAN COLOR ---
        # Calculate zoom progress (0.0 when fully zoomed out, 1.0 when fully zoomed in)
        
        # Dynamically scale the brightest blue threshold.
        # It guarantees the zoom range is always relative to the map size,
        # but preserves the original pacing (6.0) for your larger maps.
        target_brightest_zoom = max(6.0, self.min_zoom * 2.0) 
        zoom_range = target_brightest_zoom - self.min_zoom
        
        if zoom_range > 0:
            t = (self.camera.zoom - self.min_zoom) / zoom_range
            t = max(0.0, min(1.0, t))
        else:
            t = 0.0

        # Lerp from Dark Blue to Light Blue
        dark_blue = (10, 20, 40)
        light_blue = (40, 100, 180)

        r = int(dark_blue[0] + t * (light_blue[0] - dark_blue[0]))
        g = int(dark_blue[1] + t * (light_blue[1] - dark_blue[1]))
        b = int(dark_blue[2] + t * (light_blue[2] - dark_blue[2]))
        
        self.bg_color = (r, g, b)
        # --------------------------------
        
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
                # wooaaahhhhhhhhhhhh this seems... unessecarially long
                if el.text in ["Terrain", "Political", "Relations", "Pol Refresh", "Rel Refresh", "Core Refresh", "Data Refresh", "Set Date", "Core Brush", "Cores", "Auto-Core", "Unit", "Map Tech", "Reset", "Save", "Load", "Nation", "Building", "Refresh", "Exit", "View Mode", "Units", "Economy", "Blank", "Resource", "Resources", "Sync Units"]:
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
                
                if el.text == "Core Brush":
                    el.visible = True
                    if self.editor_mode == "CORE":
                        el.color, el.hover_color = (200, 100, 100), (255, 150, 150)
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150)

                if el.text == "Unit":
                    el.visible = True
                    if self.editor_mode == "UNIT":
                        el.color, el.hover_color = (200, 0, 0), (255, 50, 50)
                    else:
                        el.color, el.hover_color = (100, 100, 100), (150, 150, 150)
            return

        is_sel = bool(self.selected_province)
        if self.selection_mode:
            self.btn_exit_to_menu.visible = True
            if hasattr(self, 'btn_spectator'):
                self.btn_spectator.visible = True
            return
        
        contextual_buttons = {
            getattr(self, 'btn_go_build', None),
            getattr(self, 'btn_close_info', None), getattr(self, 'btn_exit_to_menu', None),
            getattr(self, 'btn_go_recruit', None), getattr(self, 'btn_go_orders', None),
            getattr(self, 'btn_declare_war', None), getattr(self, 'btn_form_alliance', None),
            getattr(self, 'btn_force_war', None), getattr(self, 'btn_force_peace', None),
            getattr(self, 'btn_force_alliance', None), getattr(self, 'btn_break_alliance', None),
            getattr(self, 'btn_spectator', None)
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

        # --- NEW: Hide Next Turn if in province view ---
        for el in self.elements:
            if el.text == "Next Turn":
                el.visible = not is_sel
                break

        if is_sel:
            owner = self.selected_province.get("owner", "Unclaimed")
            player_data = self.nation_data.get(self.player_country, {})
            
            if self.player_country == "Spectator":
                if state_queries.is_playable(owner, self.nation_data):
                    self.btn_force_war.visible = True
                    self.btn_force_peace.visible = True
                    self.btn_force_alliance.visible = True
                    self.btn_break_alliance.visible = True
            else:
                has_player_units = state_queries.has_units_in_province(self.player_country, self.selected_province)
                
                if owner == self.player_country or has_player_units:
                    self.btn_go_orders.visible = True
                    if owner == self.player_country:
                        terrain = self.selected_province.get("terrain", "")
                        is_land = terrain not in WATER_TERRAINS
                        self.btn_go_build.visible = True
                        self.btn_go_recruit.visible = is_land

                if owner != self.player_country and state_queries.is_playable(owner, self.nation_data):
                    
                    incoming_action, incoming_turns = state_queries.get_diplomatic_status(owner, self.player_country, self.nation_data)

                    if incoming_action == "ALLIANCE_REQUEST" and incoming_turns > 0:
                        self.btn_declare_war.visible = True
                        self.btn_declare_war.text = "REJECT ALLIANCE"
                        self.btn_form_alliance.visible = True
                        self.btn_form_alliance.text = "ACCEPT ALLIANCE"

                    elif incoming_action == "CEASEFIRE" and incoming_turns > 0:
                        self.btn_declare_war.visible = True
                        self.btn_declare_war.text = "REJECT CEASEFIRE"
                        self.btn_form_alliance.visible = True
                        self.btn_form_alliance.text = "ACCEPT CEASEFIRE"

                    else:
                        at_war = state_queries.are_at_war(self.player_country, owner, self.nation_data)
                        allied = state_queries.are_allied(self.player_country, owner, self.nation_data)

                        pending_action, pending_turns = state_queries.get_diplomatic_status(self.player_country, owner, self.nation_data)
                        is_sending = (pending_turns == 0)

                        def get_status_text():
                            return "SENDING (UNDO)" if is_sending else "WAITING..."

                        if at_war:
                            self.btn_form_alliance.visible = False
                            self.btn_declare_war.visible = True
                            if pending_action == "CEASEFIRE":
                                self.btn_declare_war.text = get_status_text()
                            else:
                                self.btn_declare_war.text = "CEASEFIRE"
                                
                        elif allied:
                            self.btn_declare_war.visible = False
                            self.btn_form_alliance.visible = True
                            if pending_action == "BREAK_ALLIANCE":
                                self.btn_form_alliance.text = get_status_text()
                            else:
                                self.btn_form_alliance.text = "BREAK ALLIANCE"
                                
                        else:
                            if pending_action == "WAR_DECLARATION":
                                self.btn_declare_war.visible = True
                                self.btn_declare_war.text = get_status_text()
                                self.btn_form_alliance.visible = False
                                
                            elif pending_action == "ALLIANCE_REQUEST":
                                self.btn_form_alliance.visible = True
                                self.btn_form_alliance.text = get_status_text()
                                self.btn_declare_war.visible = False
                                
                            else:
                                self.btn_declare_war.visible = True
                                self.btn_declare_war.text = "DECLARE WAR"
                                self.btn_form_alliance.visible = True
                                self.btn_form_alliance.text = "FORM ALLIANCE"

        # --- NEW: Sync Message Box Draft ---
        if self.selected_province:
            curr_sel = self.selected_province["id"]
            if getattr(self, "last_selected_id", None) != curr_sel:
                self.last_selected_id = curr_sel
                owner = self.selected_province.get("owner")
                self.mail_input_active = False
                if owner and owner != self.player_country:
                    self.mail_draft_text = state_queries.get_message_draft(self.player_country, owner, self.nation_data)
        else:
            self.last_selected_id = None