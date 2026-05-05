# Standard Library & Third Party
import pygame
import random
import math

# Data & Constants
import data.constants as c
from data import queries
from data.map import load_map, save_map

# Core Game State & Global UI Elements
from gameState import GameState
from map_logic.system32 import loading_screen, turn_manager
from ui_elements import Button, process_text_input
from ui import event_handler, spectator_menus, buttons, editor_menus

# Game Logic & Rendering Submodules
from map_logic import player_setup
from map_logic.camera.camera_handler import MapCamera
from map_logic.diplomacy import diplomacy_logic, player_diplomacy_actions
from map_logic.random_map import random_map_generator
from map_logic.rendering import edit_province_ownership, map_renderer, refresh_map
from map_logic.rendering.font_manager import fonts
from map_logic.rendering.country_names import update_country_centers as calc_country_centers

class Map(GameState):
    def __init__(self, load_path=None, is_scenario=False, is_random=False, force_editor=False, random_settings=None, num_players=1):
        super().__init__()

        self.num_players = num_players
        self.active_players = getattr(self, 'active_players', []) # Usually empty on boot unless loaded from save
        self.current_player_index = getattr(self, 'current_player_index', 0)
        self.show_player_ready_screen = False

       # --- BACKGROUND PROCESSING FLAGS ---
        self.ai_is_thinking = False
        self.ai_processing_complete = False
        self.thread_error = None
        
        # --- NEW PROGRESS BAR TRACKERS ---
        self.loading_status_text = "Waiting..."
        self.proactive_tasks_total = 0
        self.proactive_tasks_completed = 0
        self.responsive_tasks_total = 0
        self.responsive_tasks_completed = 0
        self.loading_spinner_angle = 0

        self.brush_building = "None" 
        self.brush_unit = "None"    
        self.editor_mode = "NATION" 
        
        self.show_country_names = True 

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
        self.skip_ai_view = False
        
        # --- 2. Data Loading ---
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
        
        self.top_bar_rect = pygame.Rect(0, 0, c.SCREEN_WIDTH, 60)
        self.bot_bar_rect = pygame.Rect(0, c.SCREEN_HEIGHT - 60, c.SCREEN_WIDTH, 60)
        self.raised_rect = pygame.Rect(0, 0, c.UI_LEFT_OFFSET, c.SCREEN_HEIGHT)
        self.ui_background_rect = pygame.Rect(0, c.SCREEN_HEIGHT - 120, 270, 120)
        
        self.map_w, self.map_h = self.id_map.get_size()
        self.min_zoom = (c.SCREEN_HEIGHT - self.total_ui_h) / self.map_h
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
        self.factions_map = self.id_map.copy()

        # --- 3. RUN THE RANDOMIZER ---
        if is_random and random_settings:
            random_map_generator.randomize_all_provinces(self, random_settings)

        # --- 4. REFRESH MAPS ---
        self.refresh_political_map()
        self.refresh_relations_map()
        self.refresh_factions_map()
        self.refresh_cores_map()
        
        buttons.render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})

        self.update_country_centers()

    # --- Properties ---
    @property
    def player_manpower(self): return self.nation_data.get(self.player_country, {}).get("manpower", 0)
    @player_manpower.setter
    def player_manpower(self, value): 
        if self.player_country in self.nation_data: self.nation_data[self.player_country]["manpower"] = value

    @property
    def player_materials(self): return self.nation_data.get(self.player_country, {}).get("materials", 0)
    
    @property
    def player_fuel(self): return self.nation_data.get(self.player_country, {}).get("fuel", 0)

    # --- Toggles & View Modes ---
    def toggle_country_names(self):
        self.show_country_names = not getattr(self, 'show_country_names', True)
        self.show_feedback(f"Country Names: {'ON' if self.show_country_names else 'OFF'}")

    def toggle_skip_ai(self):
        self.skip_ai_view = not getattr(self, 'skip_ai_view', False)
        self.show_feedback(f"Skip AI View: {'ON' if self.skip_ai_view else 'OFF'}")
        buttons.update_button_states(self)
        
    def set_view_mode(self, mode):
        self.secondary_mode = mode
        self.show_feedback(f"View: {mode}")

    def cycle_secondary_mode(self):
        self.sec_idx = (self.sec_idx + 1) % len(self.secondary_modes)
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        self.show_feedback(f"View Mode: {self.secondary_mode}")

    def update_country_centers(self):
        """Calculates new label centers and text blobs for the map."""
        calc_country_centers(self)

    def set_map_layer(self, layer_name):
        """Unified map layer setter."""
        self.base_layer = layer_name
        layer_map = {
            "TERRAIN": self.terrain_map,
            "POLITICAL": self.political_map,
            "RELATIONS": self.relations_map,
            "FACTIONS": self.factions_map,
            "CORES": self.cores_map
        }
        self.active_map = layer_map.get(layer_name, self.political_map)
        
        # --- ADDED: Auto-refresh the text blobs when changing map views ---
        self.update_country_centers()
        
        self.show_feedback(f"Mode: {layer_name.title()}")
        
    # --- Screen Transitions ---
    def change_state(self, next_state):
        self.next_state, self.done = next_state, True
        
    def change_state_if_owned(self, next_state, requires_land=False):
        """Only transitions if the player owns the selected province (and optionally if it's land)."""
        if self.selected_province and self.selected_province.get("owner") == self.player_country:
            if requires_land and self.selected_province.get("terrain") in c.WATER_TERRAINS:
                return
            self.change_state(next_state)

    def deselect_province(self):
        if self.selected_province:
            owner = self.selected_province.get("owner")
            is_foreign = queries.is_foreign_playable(owner, self.player_country, self.nation_data)
            if is_foreign:
                draft = getattr(self, "mail_draft_text", "").strip()
                if draft:
                    diplomacy_logic.queue_text_message(self.nation_data, self.player_country, owner, draft)
                else:
                    diplomacy_logic.cancel_text_message(self.nation_data, self.player_country, owner)
                self.mail_input_active = False

        self.selected_province = self.hovered_province = self.hover_glow_surf = self.last_hovered_id = None
        self.show_feedback("Map Unlocked")

    def save_map_data(self): 
        save_map.save_map_data(self)

    def refresh_political_map(self): refresh_map.refresh_political_map(self)
    def refresh_relations_map(self): refresh_map.refresh_relations_map(self)
    def refresh_factions_map(self): refresh_map.refresh_factions_map(self)
    def refresh_cores_map(self): refresh_map.refresh_cores_map(self)

    def auto_assign_cores(self):
        for province in self.map_data.values():
            owner = province.get("owner", "Unclaimed")
            province["cores"] = [owner] if owner not in ["Unclaimed", "None", "Ocean", "Lakes"] else []
        self.show_feedback("Auto-assigned all cores!")
        if self.map_mode == "CORES":
            self.refresh_cores_map()

    def exit_to_menu(self): 
        self.show_exit_confirmation = True
        for el in self.elements: el.visible = False

    def cancel_exit(self):
        self.show_exit_confirmation = False
        self.show_feedback("Exit cancelled")

    def confirm_exit(self):
        self.change_state("MENU")

    def show_feedback(self, text): 
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()
        print(f"[UI EVENT] {text}")

    def additional_events(self, event): 
        event_handler.handle_map_events(self, event)

    def sync_units_to_data(self):
        unit_library = queries.get_unit_library()
        building_library = queries.get_building_library()
        if not unit_library:
            self.show_feedback("Error: unit library not found!")
            return
            
        updated_count = 0
        removed_count = 0
        
        for province in self.map_data.values():
            # 1. Clean Units
            units_to_keep = []
            for unit in province.get("units", []):
                u_type = unit.get("type", "")
                base_type = unit.get("original_type", u_type)
                
                # Handle dynamic transport names
                if base_type.startswith("Convoy (") or base_type.startswith("Truck ("):
                    import re
                    match = re.search(r'\((.*?)\)', base_type)
                    if match:
                        base_type = match.group(1).strip()
                        
                # Check if the unit is still valid
                if base_type in unit_library or base_type in ["Convoy", "Truck"]:
                    if u_type in unit_library:
                        stats = unit_library[u_type]
                        unit.update({
                            "max_health": stats.get("health", c.DEFAULT_UNIT_HP),
                            "attack": stats.get("attack", c.DEFAULT_UNIT_ATK),
                            "defense": stats.get("defense", c.DEFAULT_UNIT_DEF),
                            "speed": stats.get("speed", c.DEFAULT_UNIT_SPD)
                        })
                        # Cap health to new max
                        unit["health"] = min(unit.get("health", stats.get("health", c.DEFAULT_UNIT_HP)), unit["max_health"])
                        updated_count += 1
                    units_to_keep.append(unit)
                else:
                    removed_count += 1 # It's obsolete, drop it!
                    
            province["units"] = units_to_keep
            
            # 2. Clean Buildings
            if "buildings" in province:
                original_b_count = len(province["buildings"])
                province["buildings"] = [b for b in province["buildings"] if b in building_library]
                removed_count += (original_b_count - len(province["buildings"]))
                
            # 3. Clean Queues
            if "deployment_queue" in province:
                valid_queue = []
                for q in province["deployment_queue"]:
                    is_valid = True
                    if q.get("order_type") == "BUILDING" and q.get("item_name") not in building_library:
                        is_valid = False
                    elif "unit_type" in q and q.get("unit_type") not in unit_library:
                        is_valid = False
                        
                    if is_valid:
                        valid_queue.append(q)
                    else:
                        removed_count += 1
                province["deployment_queue"] = valid_queue
                
        print(f"[MAP SCRUBBER] {updated_count} entities updated, {removed_count} obsolete entities vaporized.")

    def handle_back_key(self):
        if self.selected_province:
            self.deselect_province()

    def handle_orders_key(self):
        if self.selected_province and not self.selection_mode:
            owner = self.selected_province.get("owner", "Unclaimed")
            has_player_units = queries.has_units_in_province(self.player_country, self.selected_province)
            if owner == self.player_country or has_player_units:
                self.change_state("ORDERS")

    def additional_draw(self, surface): 
        map_renderer.draw_map_screen(self, surface)

    def draw(self, surface):
        super().draw(surface)
        map_renderer.draw_badges(self, surface)
        
        if getattr(self, 'thread_error', None):
            surface.fill((150, 0, 0))
            title = fonts.get("heading1").render("FATAL THREAD ERROR", True, (255, 255, 255))
            surface.blit(title, (20, 20))
            y_offset = 80
            for line in self.thread_error.split('\n'):
                surface.blit(fonts.get("small").render(line, True, (255, 200, 200)), (20, y_offset))
                y_offset += 25
            return 
        
        if getattr(self, 'ai_is_thinking', False):
            loading_screen.draw_turn_loading_screen(self, surface)

    def refresh_nation_data(self):
        from data.io import country_io
        new_data = country_io.load_all_country_data()
        added_count, updated_count = 0, 0
        
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

                if "research" in data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, start_val in data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = start_val
                            updated_count += 1

        # Clean up obsolete research for EVERY nation currently on the map
        tech_tree = queries.get_tech_tree()
        for country, data in self.nation_data.items():
            if "research" in data:
                obsolete_keys = [k for k in data["research"].keys() if k not in tech_tree]
                for k in obsolete_keys:
                    del data["research"][k]
                    updated_count += 1
                    
        # --- NEW: Scrub the map's default template too! ---
        if getattr(self, "default_research", None) is not None:
            obsolete_defaults = [k for k in self.default_research.keys() if k not in tech_tree]
            for k in obsolete_defaults:
                del self.default_research[k]
                updated_count += 1
                
        self.nation_colors = {name: tuple(stats["color"]) for name, stats in self.nation_data.items()}
        self.refresh_political_map()
        self.refresh_relations_map()
        
        # Merge the unit sync into this function
        self.sync_units_to_data()
        
        self.show_feedback(f"Data Resynced! Added {added_count}, Updated {updated_count}. Objects Synced.")
        
    def toggle_editor_brush_type(self):
        if self.editor_mode == "NATION":
            self.editor_mode = "BUILDING"
            self.show_feedback("Editor: Building Placement")
        else:
            self.editor_mode = "NATION"
            self.show_feedback("Editor: Nation Painting")

    def update(self):
        super().update()
        self.camera.update(self, c.SCREEN_HEIGHT)

        if getattr(self, 'show_player_ready_screen', False):
            for el in self.elements: el.visible = False
            return

        if getattr(self, 'ai_processing_complete', False):
            self.ai_processing_complete = False
            self.ai_is_thinking = False
            
            if getattr(self, 'thread_error', None): return
            
            if getattr(self, 'skip_ai_view', False):
                self.viewing_ai_moves = True
                turn_manager.advance_time(self)
            else:
                self.refresh_political_map()
                self.refresh_relations_map()
                self.viewing_ai_moves = True
                buttons.render_buttons(self)
                elapsed_seconds = (pygame.time.get_ticks() - self.turn_start_time) / 1000.0
                self.show_feedback(f"AI Strategy generated in {elapsed_seconds:.2f}s")
                print(f"[PERFORMANCE] Phase 1 completed in {elapsed_seconds:.2f} seconds.")

        from map_logic.camera import camera_handler
        self.bg_color = camera_handler.get_dynamic_ocean_color(self.camera, self.min_zoom)
        buttons.update_button_states(self)