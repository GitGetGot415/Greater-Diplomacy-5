# Standard Library & Third Party
import pygame
import os
import sys

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Data & Constants
import data.constants as c
from data import queries
from data.map import load_map, save_map

# Core Game State & Global UI Elements
from gameState import GameState
from map_logic.system32 import turn_manager
from ui import event_handler, buttons

# Game Logic & Rendering Submodules
from ui import diplomatic_popups
from map_logic.camera.camera_handler import MapCamera
from map_logic.camera import camera_handler
from map_logic.diplomacy import diplomacy_logic
from map_logic.random_map import random_map_generator
from map_logic.rendering import map_renderer, refresh_map
from map_logic.rendering.font_manager import fonts
from map_logic.rendering.country_names import update_country_centers as calc_country_centers

class Map(GameState):
    def __init__(self, load_path=None, is_scenario=False, is_random=False, force_editor=False, random_settings=None, map_settings=None, num_players=1, history_turn=None):
        super().__init__()

        self.history_turn = history_turn
        self.num_players = num_players
        self.active_players = [] # Usually empty on boot unless loaded from save
        self.current_player_index = 0
        self.show_player_ready_screen = False

       # --- UI DISPLAY OVERRIDES ---
        self.hide_raised_rect = False
        self.hide_top_info = False
        self.hide_tooltip = False
        self.hide_resource_hud = False
        self.hide_minimap = False
        self.centers_need_update = False
        self.error_copied = False
        self.random_settings = None

        # --- BACKGROUND PROCESSING FLAGS ---
        self.ai_is_thinking = False
        self.ai_processing_complete = False
        self.is_refreshing = False
        self.thread_error = None
        self.force_skip_llm = False

        # --- TACTICAL MODE STATE ---
        self.tactical_mode = False
        self.player_unit = None
        self.unit_economy = {"manpower": 0, "materials": 0, "fuel": 0, "fuel_inc": 0}
        
        # --- MULTI-TURN FLAGS ---
        self.multi_turn_processing_complete = False
        self.multi_turns_total = 0
        self.multi_turns_completed = 0
        
        # --- NEW PROGRESS BAR TRACKERS ---
        self.loading_status_text = "Waiting..."
        self.proactive_tasks_total = 0
        self.proactive_tasks_completed = 0
        self.proactive_llm_tasks_total = 0
        self.proactive_llm_tasks_completed = 0
        self.proactive_llm_tasks = []
        self.responsive_tasks_total = 0
        self.responsive_tasks_completed = 0
        self.diplomatic_popups = []

        # Initialize variables previously hidden by getattr
        self.fog_map = None
        self.visible_provinces = None
        self.mail_draft_text = ""
        self.mail_input_active = False

        # --- NEW REFRESH TRACKERS ---
        self.refresh_tasks_total = 0
        self.refresh_tasks_completed = 0
        self.loading_spinner_angle = 0

        self.brush_building = "None" 
        self.brush_unit = "None"    
        self.editor_mode = "NATION" 
        
        self.show_country_names = True 

        # --- 1. Basic State Variables ---
        self.camera_tilt_slider_val = 0.0 # Starts fully top-down
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
            self.random_settings = random_settings
            load_map.load_map_assets(self, random_settings["map_path"])
            self.time_manager.year = random_settings["year"]
        else:
            load_map.load_map_assets(self, load_path)

        # Sync constants mapping directly from loaded configuration store values if they exist
        if hasattr(self, 'controller') and hasattr(self.controller, 'drag_mouse_button_toggle'):
            c.DRAG_MOUSE_BUTTON_TOGGLE = self.controller.drag_mouse_button_toggle

        # Capture settings passed from New_Game
        if map_settings:
            self.scenario_settings = map_settings
        elif not hasattr(self, 'scenario_settings'):
            self.scenario_settings = {
                "fog_of_war": c.DEFAULT_FOG_OF_WAR,
                "casus_belli_required": c.DEFAULT_CASUS_BELLI
            }

        # --- 3. Visuals & UI Setup ---
        self.bg_color = (20, 20, 20)
        self.font = fonts.get("normal") 
        self.small_font = fonts.get("tiny") 
        
        self.top_ui_height = c.TOP_UI_HEIGHT
        self.bot_ui_height = c.BOT_UI_HEIGHT
        self.total_ui_h = c.TOTAL_UI_HEIGHT
        
        self.top_bar_rect = pygame.Rect(0, 0, c.SCREEN_WIDTH, self.top_ui_height)
        self.bot_bar_rect = pygame.Rect(0, c.SCREEN_HEIGHT - self.bot_ui_height, c.SCREEN_WIDTH, self.bot_ui_height)
        self.raised_rect = pygame.Rect(0, 0, c.UI_LEFT_OFFSET, c.SCREEN_HEIGHT)
        self.ui_background_rect = pygame.Rect(0, c.SCREEN_HEIGHT - self.total_ui_h, 270, self.total_ui_h)
        
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
        self.faction_territories_map = self.id_map.copy()

        # --- 3. RUN THE RANDOMIZER ---
        if is_random and random_settings:
            random_map_generator.randomize_all_provinces(self, random_settings)

        # --- 4. REFRESH MAPS ---
        self.refresh_political_map()
        self.refresh_relations_map()
        self.refresh_factions_map()
        self.refresh_cores_map()
        self.refresh_faction_territories_map()
        self.refresh_fog_map()
        
        buttons.render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})

        self.update_country_centers()

        # --- 5. INITIALIZE INCOME ---
        # Provide 1 turn of simulated income so nations don't spawn with 0 resources
        if self.time_manager.total_turns == 0:
            from map_logic.system32 import economy_processor
            economy_processor.process_economy(self)

    def draw_clean_map_background(self, surface):
        """Temporarily hides UI elements and province selection to draw a clean map background."""
        temp_prov = self.selected_province
        self.selected_province = None
        
        # Save previous states to be completely safe
        prev_raised = self.hide_raised_rect
        prev_tooltip = self.hide_tooltip
        prev_hud = self.hide_resource_hud
        prev_mini = self.hide_minimap
        
        self.hide_raised_rect = True
        self.hide_tooltip = True
        self.hide_resource_hud = True
        self.hide_minimap = True
        
        self.additional_draw(surface)
        
        # Restore original states
        self.hide_raised_rect = prev_raised
        self.hide_tooltip = prev_tooltip
        self.hide_resource_hud = prev_hud
        self.hide_minimap = prev_mini
        self.selected_province = temp_prov

    # --- Properties ---
    @property
    def player_manpower(self): 
        if self.tactical_mode: return self.unit_economy.get("manpower", 0)
        return self.nation_data.get(self.player_country, {}).get("manpower", 0)
    @player_manpower.setter
    def player_manpower(self, value): 
        if self.tactical_mode: self.unit_economy["manpower"] = value
        elif self.player_country in self.nation_data: self.nation_data[self.player_country]["manpower"] = value

    @property
    def player_materials(self): 
        if self.tactical_mode: return self.unit_economy.get("materials", 0)
        return self.nation_data.get(self.player_country, {}).get("materials", 0)
    
    @property
    def player_fuel(self): 
        if getattr(self, 'tactical_mode', False) and getattr(self, 'player_unit', None):
            base_fuel = self.unit_economy.get("fuel", 0)
            u = self.player_unit
            order = u.get("order")
            path = order.get("path", []) if isinstance(order, dict) else []
            if path:
                u_type = u.get("original_type", u.get("type"))
                from data import queries
                uses_oil = queries.get_unit_library().get(u_type, {}).get("cost_fuel", 0) > 0
                calc_speed = u.get("speed", 1) + (1 if uses_oil else 0)
                immediate_steps = min(len(path), calc_speed)
                fuel_inc = self.unit_economy.get("fuel_inc", 0)
                cost_per_tile = fuel_inc / calc_speed if calc_speed > 0 else 0
                return max(0, base_fuel - (cost_per_tile * immediate_steps))
            return base_fuel
        return self.nation_data.get(self.player_country, {}).get("fuel", 0)

    def set_camera_tilt(self, val):
        """Callback for the manual camera tilt slider."""
        self.camera_tilt_slider_val = val
        
        # Grab the old tilt before we update it to calculate the difference
        old_tilt = self.camera.manual_tilt_factor
        new_tilt = 1.0 - (val * (1.0 - c.MAX_Y_TILT_FACTOR))
        
        # Failsafe to prevent division by zero
        if old_tilt == 0: old_tilt = 0.001
        if new_tilt == 0: new_tilt = 0.001
        
        # --- NEW: Anchor the compression to the center of the camera ---
        # Find the pixel center of the playable view area (excluding UI bars)
        view_h = c.SCREEN_HEIGHT - self.total_ui_h
        screen_center_y = view_h / 2.0
        
        # Shift the camera Y position to perfectly compensate for the scale change,
        # keeping the exact same world coordinate centered on your screen.
        self.camera.pos.y += (screen_center_y / self.camera.zoom) * ((1.0 / old_tilt) - (1.0 / new_tilt))
        
        # Sync the target position so the smooth-pan lerp doesn't aggressively snap it back
        self.camera.target_pos.y = self.camera.pos.y
        
        # Apply the new tilt
        self.camera.manual_tilt_factor = new_tilt
        
        # Flag the label centers for an update because tilting the world compresses 
        # the visual space, shifting where country names need to physically render.
        self.centers_need_update = True

    # --- Toggles & View Modes ---
    def toggle_country_names(self):
        self.show_country_names = not self.show_country_names
        self.show_feedback(f"Country Names: {'ON' if self.show_country_names else 'OFF'}")

    def toggle_skip_ai(self):
        self.skip_ai_view = not self.skip_ai_view
        self.show_feedback(f"Skip AI View: {'ON' if self.skip_ai_view else 'OFF'}")
        buttons.update_button_states(self)
        
    def set_view_mode(self, mode):
        self.secondary_mode = mode
        self.show_feedback(f"View: {mode}")

    def cycle_secondary_mode(self):
        self.sec_idx = (self.sec_idx + 1) % len(self.secondary_modes)
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        self.show_feedback(f"View Mode: {self.secondary_mode}")

    def trigger_multi_turn(self):
        import tkinter as tk
        from tkinter import simpledialog
        from data import queries
        import threading
        
        root = queries.get_transient_tk_root()
        turns = simpledialog.askinteger("Process Multiple Turns", "How many turns to process at once?", minvalue=1, maxvalue=5000)
        queries.destroy_tk_root(root)
        
        if turns:
            self.multi_turns_total = turns
            self.multi_turns_completed = 0
            self.ai_is_thinking = True
            self.loading_status_text = f"Skipping {turns} Turns..."
            threading.Thread(target=self._run_multi_turn_thread, args=(turns,), daemon=True).start()

    def _run_multi_turn_thread(self, turns):
        from map_logic.system32 import turn_processor
        from map_logic.ai import ai_handler
        import traceback
        
        try:
            ai_handler.FORCE_SKIP = True
            self.force_skip_llm = True
            self.viewing_ai_moves = True # Prevents PyGame surface edits from background thread
            
            for i in range(turns):
                self.multi_turns_completed = i + 1
                self.loading_status_text = f"Processing Turn {i+1}/{turns}..."
                
                # Mock the UI prep variables to prevent crashes
                self.proactive_tasks_total = 1
                self.proactive_tasks_completed = 1
                self.proactive_llm_tasks_total = 0
                self.proactive_llm_tasks_completed = 0
                self.proactive_llm_tasks = []
                self.responsive_tasks_total = 0
                self.responsive_tasks_completed = 0
                
                turn_processor.prepare_turn(self)
                turn_processor.resolve_turn_logic(self)
                
        except Exception as e:
            self.thread_error = traceback.format_exc()
            print(f"MULTI-TURN CRASH CAUGHT:\n{self.thread_error}")
        finally:
            ai_handler.FORCE_SKIP = False
            self.force_skip_llm = False
            self.multi_turn_processing_complete = True

    def update_country_centers(self):
        """Calculates new label centers and text blobs for the map."""
        calc_country_centers(self)

    def set_map_layer(self, layer_name):
        """Unified map layer setter."""
        self.base_layer = layer_name
        self.map_mode = layer_name
        layer_map = {
            "TERRAIN": self.terrain_map,
            "POLITICAL": self.political_map,
            "RELATIONS": self.relations_map,
            "FACTIONS": self.factions_map,
            "CORES": self.cores_map,
            "FACTION_TERRITORIES": self.faction_territories_map
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
        if self.selected_province:
            owner = self.selected_province.get("owner")
            # Allow the spectator to bypass ownership checks
            if owner == self.player_country or self.player_country == "Spectator":
                if requires_land and self.selected_province.get("terrain") in c.WATER_TERRAINS:
                    return
                self.change_state(next_state)

    def deselect_province(self):
        if self.selected_province:
            owner = self.selected_province.get("owner")
            is_foreign = queries.is_foreign_playable(owner, self.player_country, self.nation_data)
            if is_foreign:
                draft = self.mail_draft_text.strip()
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
    def refresh_faction_territories_map(self): refresh_map.refresh_faction_territories_map(self)
    def refresh_fog_map(self): refresh_map.refresh_fog_map(self)

    def refresh_all_maps(self):
        """Unified method to refresh all visual map layers and text at once."""
        # do note that for larger maps this might take over 1000 ms to complete, this is NOT instant by any means
        # TODO: maybe add the ability to ignore certain refresh actions (example: refresh all except for faction territories)
        self.update_country_centers()
        self.refresh_political_map()
        self.refresh_relations_map()
        self.refresh_factions_map()
        self.refresh_cores_map()
        self.refresh_faction_territories_map()
        self.refresh_fog_map()
        self.show_feedback("Maps refreshed!")

    def auto_assign_cores(self):
        import tkinter as tk
        from tkinter import messagebox
        from data import queries
        
        # Ask for confirmation first before doing anything destructive
        root = queries.get_transient_tk_root()
        confirm = messagebox.askyesno(
            "Confirm Auto-Core", 
            "Are you sure you want to auto-assign all cores?\nThis will overwrite existing core data for every province on the map based on current ownership.",
            parent=root
        )
        queries.destroy_tk_root(root)
        
        if confirm:
            for province in self.map_data.values():
                owner = province.get("owner", "Unclaimed")
                province["cores"] = [owner] if owner not in ["Unclaimed", "None", "Ocean", "Lakes"] else []
            self.show_feedback("Auto-assigned all cores!")
            if self.map_mode == "CORES":
                self.refresh_cores_map()
        else:
            self.show_feedback("Auto-core cancelled.")

    def exit_to_menu(self): 
        self.show_exit_confirmation = True
        for el in self.elements: el.visible = False

    def cancel_exit(self):
        self.show_exit_confirmation = False
        self.show_feedback("Exit cancelled")

    def confirm_exit(self):
        diplomatic_popups.clear_popups(self)
        self.change_state("MENU")

    def show_feedback(self, text): 
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()
        print(f"[UI EVENT] {text}")

    def additional_events(self, event): 
        # Intercept inputs if the game has crashed
        if self.thread_error:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                btn_rect = pygame.Rect(c.SCREEN_WIDTH - 240, c.SCREEN_HEIGHT - 80, 220, 60)
                if btn_rect.collidepoint(event.pos):
                    try:
                        import tkinter as tk
                        root = tk.Tk()
                        root.withdraw()
                        root.clipboard_clear()
                        root.clipboard_append(self.thread_error)
                        root.update()
                        root.destroy()
                        self.error_copied = True
                    except Exception as e:
                        print(f"Failed to copy to clipboard: {e}")
            return # Block all other map events!

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
            for queue_key in ["building_queue", "unit_queue"]:
                if queue_key in province:
                    valid_queue = []
                    for q in province[queue_key]:
                        is_valid = True
                        if q.get("order_type") == "BUILDING" and q.get("item_name") not in building_library:
                            is_valid = False
                        elif "unit_type" in q and q.get("unit_type") not in unit_library:
                            is_valid = False
                            
                        if is_valid:
                            valid_queue.append(q)
                        else:
                            removed_count += 1
                    province[queue_key] = valid_queue
                    
            # Wipe legacy data if it exists
            if "deployment_queue" in province:
                del province["deployment_queue"]
                
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
        
        diplomatic_popups.draw(self, surface)
        
        if self.thread_error:
            surface.fill((150, 0, 0))
            title = fonts.get("heading1").render("FATAL THREAD ERROR", True, (255, 255, 255))
            surface.blit(title, (20, 20))
            y_offset = 80
            for line in self.thread_error.split('\n'):
                surface.blit(fonts.get("small").render(line, True, (255, 200, 200)), (20, y_offset))
                y_offset += 25
                
            # Draw Copy Button
            btn_rect = pygame.Rect(c.SCREEN_WIDTH - 240, c.SCREEN_HEIGHT - 80, 220, 60)
            mx, my = pygame.mouse.get_pos()
            
            # Hover effect
            color = (200, 50, 50) if btn_rect.collidepoint(mx, my) else (150, 30, 30)
            
            pygame.draw.rect(surface, color, btn_rect, border_radius=5)
            pygame.draw.rect(surface, (255, 255, 255), btn_rect, 2, border_radius=5)
            
            btn_txt = fonts.get("button").render("Copy to Clipboard", True, (255, 255, 255))
            surface.blit(btn_txt, btn_txt.get_rect(center=btn_rect.center))
            
            # Show "Copied!" feedback text above the button
            if self.error_copied:
                copied_txt = fonts.get("small").render("Copied!", True, (100, 255, 100))
                surface.blit(copied_txt, (btn_rect.centerx - copied_txt.get_width()//2, btn_rect.y - 25))
                
            return

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

                if "research" in data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, start_val in data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = start_val
                            updated_count += 1

        # --- NEW: AUTO-RESET ASSETS TO DISK DEFAULTS ---
            # By setting to DEFAULT, we force the rendering engine to search the disk again.
            queries.clear_image_cache()
            for c_name, n_data in self.nation_data.items():
                n_data["flag_data"] = "DEFAULT"
                n_data["portrait_data"] = "DEFAULT"

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
                
        self.nation_colors = {name: tuple(stats.get("color", [150, 150, 150])) for name, stats in self.nation_data.items()}
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

        # Defer editor map label updates until the user finishes their brush stroke
        if self.centers_need_update and not pygame.mouse.get_pressed()[0]:
            self.update_country_centers()
            self.centers_need_update = False

        # Only spawn popups when the player is fully in control of the current turn
        is_playing = not self.viewing_ai_moves and \
                     not self.ai_is_thinking and \
                     not self.show_player_ready_screen and \
                     not self.selection_mode

        if is_playing:
            from ui import diplomatic_popups
            diplomatic_popups.spawn_popups_for_player(self)

        if self.show_player_ready_screen:
            for el in self.elements: el.visible = False
            return

        if self.multi_turn_processing_complete:
            self.multi_turn_processing_complete = False
            self.multi_turns_total = 0
            self.ai_is_thinking = False
            
            if self.thread_error: return
            
            self.refresh_political_map()
            self.refresh_relations_map()
            self.refresh_factions_map()
            self.refresh_cores_map()
            self.refresh_faction_territories_map()
            self.refresh_fog_map()
            self.update_country_centers()
            
            self.viewing_ai_moves = False # Safely unlock PyGame UI rendering
            
            buttons.update_button_states(self)
            self.show_feedback(f"Multi-Turn Processing Complete!")
            return

        if self.ai_processing_complete:
            self.ai_processing_complete = False
            self.ai_is_thinking = False
            
            if self.thread_error: return
            
            if self.skip_ai_view:
                self.viewing_ai_moves = True
                turn_manager.advance_time(self)
            else:
                self.viewing_ai_moves = True
                self.refresh_political_map()
                self.refresh_relations_map()
                self.refresh_fog_map()
                buttons.render_buttons(self)
                elapsed_seconds = (pygame.time.get_ticks() - self.turn_start_time) / 1000.0
                self.show_feedback(f"AI Strategy generated in {elapsed_seconds:.2f}s")
                print(f"[PERFORMANCE] Phase 1 completed in {elapsed_seconds:.2f} seconds.")

        self.bg_color = camera_handler.get_dynamic_ocean_color(self.camera, self.min_zoom)
        buttons.update_button_states(self)