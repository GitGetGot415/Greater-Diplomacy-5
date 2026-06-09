import os
import json
import shutil
import pygame
from gameState import GameState
from ui_elements import Button
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts

class New_Game(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_scenario_path = None
        self.settings_data = {"fog_of_war": c.DEFAULT_FOG_OF_WAR}
        self.sub_state = "CATEGORY" # "CATEGORY", "HISTORICAL", "ALTERNATE"
        
        # --- SCROLLING AND DELETION STATE ---
        self.scroll_y = 0
        self.max_scroll = 0
        self.is_dragging_scrollbar = False
        self.scroll_track_rect = None
        self.scroll_handle_rect = None
        
        self.deleting_scenario = None
        self.deleting_directory = None
        
        self.refresh_scenarios()

    def refresh_scenarios(self):
        self.elements = []
        
        if self.sub_state == "CATEGORY":
            self.elements = [
                Button(20, 20, "small", "red", "Back", self.exit_to_menu),
                Button("centered", 200, "large", "blue", "Historical Scenarios", lambda: self.set_sub_state("HISTORICAL")),
                Button("centered", 300, "large", "purple", "Alternate Scenarios", lambda: self.set_sub_state("ALTERNATE")),
                Button("centered", 400, "large", "purple", "Custom Scenarios", lambda: self.set_sub_state("CUSTOM")),
                Button("centered", 500, "large", "orange", "Random Scenario", self.start_random_scenario),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 160, "medium", "purple", "Data Refresh", self.trigger_global_data_refresh),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings),
            ]
        else:
            self.elements = [
                Button(20, 20, "small", "red", "Back", lambda: self.set_sub_state("CATEGORY")),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings),
            ]
            
            if self.sub_state == "HISTORICAL":
                scenario_dir = c.SCENARIOS_HISTORICAL_DIR  
            elif self.sub_state ==  "ALTERNATE":
                scenario_dir = c.SCENARIOS_ALTERNATE_DIR
            else:
                scenario_dir = c.SCENARIOS_CUSTOM_DIR
            if not os.path.exists(scenario_dir):
                os.makedirs(scenario_dir)
                
            scenarios = os.listdir(scenario_dir)
            
            # Calculate scroll boundaries
            total_content_height = len(scenarios) * 60
            self.max_scroll = min(0, (c.SCREEN_HEIGHT - 200) - total_content_height - 20)

            for i, name in enumerate(scenarios):
                if getattr(self, 'deleting_scenario', None) == name:
                    continue # Hide buttons for the row being deleted
                    
                btn_y = 200 + (i * 60) + self.scroll_y
                
                # Simple Y-based culling so we don't draw off-screen buttons
                if not (100 < btn_y < c.SCREEN_HEIGHT - 50):
                    continue

                # Create a button for each scenario
                self.elements.append(
                    Button("centered", btn_y, "new_game", "blue", name, 
                           lambda n=name, d=scenario_dir: self.start_scenario(n, d))
                )
                
                # Add a delete button for custom scenarios
                if self.sub_state == "CUSTOM":
                    self.elements.append(
                        Button(c.SCREEN_WIDTH // 2 + 160, btn_y + 5, "small_square", "red", "X",
                               lambda n=name, d=scenario_dir: self.trigger_delete_conf(n, d))
                    )

    # --- DELETION LOGIC ---
    def trigger_delete_conf(self, scenario_name, directory):
        self.deleting_scenario = scenario_name
        self.deleting_directory = directory
        self.refresh_scenarios()

    def confirm_delete(self):
        if self.deleting_scenario and self.deleting_directory:
            path = os.path.join(self.deleting_directory, self.deleting_scenario)
            if os.path.exists(path):
                shutil.rmtree(path)
        self.deleting_scenario = None
        self.deleting_directory = None
        self.refresh_scenarios()

    def cancel_delete(self):
        self.deleting_scenario = None
        self.deleting_directory = None
        self.refresh_scenarios()

    # --- SCROLL LOGIC ---
    def _snap_scroll(self, my):
        view_h = c.SCREEN_HEIGHT - 200
        handle_h = max(30, int(view_h * (view_h / max(1, view_h - self.max_scroll))))
        rel_y = my - 200 - (handle_h / 2)
        max_y = view_h - handle_h
        ratio = max(0.0, min(1.0, rel_y / max(1, max_y)))
        self.scroll_y = ratio * self.max_scroll
        self.refresh_scenarios()

    def additional_events(self, event):
        # 1. Deletion Input Logic
        if getattr(self, 'deleting_scenario', None):
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN: self.confirm_delete()
                elif event.key == pygame.K_ESCAPE: self.cancel_delete()
            return # Block background inputs when a popup is rendering

        # 2. Scrolling Logic
        if self.sub_state != "CATEGORY":
            if event.type == pygame.MOUSEWHEEL:
                self.scroll_y += event.y * 40
                self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
                self.refresh_scenarios()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if self.scroll_handle_rect and self.scroll_handle_rect.collidepoint(mx, my):
                    self.is_dragging_scrollbar = True
                elif self.scroll_track_rect and self.scroll_track_rect.collidepoint(mx, my):
                    self.is_dragging_scrollbar = True
                    self._snap_scroll(my)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.is_dragging_scrollbar = False

            elif event.type == pygame.MOUSEMOTION and getattr(self, 'is_dragging_scrollbar', False):
                self._snap_scroll(event.pos[1])

    def additional_draw(self, surface):
        if self.sub_state == "CATEGORY":
            title_text = "NEW GAME"
        elif self.sub_state == "HISTORICAL":
            title_text = "HISTORICAL SCENARIOS"
        elif self.sub_state == "ALTERNATE":
            title_text = "ALTERNATE SCENARIOS"
        else:
            title_text = "CUSTOM SCENARIOS"
            
        title = fonts.get("heading1").render(title_text, True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))

        if self.sub_state != "CATEGORY":
            # --- Draw Scrollbar ---
            if self.max_scroll < 0:
                view_h = c.SCREEN_HEIGHT - 200
                track_rect = pygame.Rect(c.SCREEN_WIDTH - 40, 200, 15, view_h)
                pygame.draw.rect(surface, (50, 50, 60), track_rect)
                
                ratio = self.scroll_y / self.max_scroll
                handle_h = max(30, int(view_h * (view_h / (view_h - self.max_scroll))))
                handle_y = 200 + ratio * (view_h - handle_h)
                
                handle_rect = pygame.Rect(c.SCREEN_WIDTH - 40, handle_y, 15, handle_h)
                pygame.draw.rect(surface, (150, 150, 150), handle_rect, border_radius=5)
                
                self.scroll_track_rect = track_rect
                self.scroll_handle_rect = handle_rect
            else:
                self.scroll_track_rect = None
                self.scroll_handle_rect = None

        # --- Draw Delete Confirmation Popup ---
        if getattr(self, 'deleting_scenario', None):
            overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))
            
            pop_rect = pygame.Rect(0, 0, 500, 200)
            pop_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
            pygame.draw.rect(surface, (60, 20, 20), pop_rect)
            pygame.draw.rect(surface, (255, 50, 50), pop_rect, 3)
            
            font = fonts.get("heading2")
            msg = font.render(f"Delete '{self.deleting_scenario}'?", True, (255, 255, 255))
            msg_rect = msg.get_rect(center=(pop_rect.centerx, pop_rect.y + 60))
            surface.blit(msg, msg_rect)
            
            sub_msg = fonts.get("normal").render("Press Enter to Confirm or Esc to Cancel", True, (200, 200, 200))
            sub_rect = sub_msg.get_rect(center=(pop_rect.centerx, pop_rect.y + 110))
            surface.blit(sub_msg, sub_rect)

    def set_sub_state(self, state):
        self.sub_state = state
        self.scroll_y = 0
        self.deleting_scenario = None
        self.refresh_scenarios()

    def scenario_settings(self):
        from screens.scenario_settings import Scenario_Settings
        Scenario_Settings.return_screen = "NEW_GAME"
        self.next_state = "SCENARIO_SETTINGS"
        self.done = True

    def start_scenario(self, scenario_name, directory):
        self.selected_save_path = os.path.join(directory, scenario_name)
        # Pass the settings to the Map class
        self.map_settings = queries.get_scenario_settings() 
        self.set_sub_state("CATEGORY")
        self.next_state = "MAP"
        self.done = True

    def trigger_global_data_refresh(self):
        """Headlessly instantiates each map scenario, runs internal data sync cleaners, and forces an in-place write to disk."""
        from screens.map import Map
        
        scenarios_processed = 0
        dirs_to_check = [c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR, c.SCENARIOS_CUSTOM_DIR]

        for scenario_dir in dirs_to_check:
            if not os.path.exists(scenario_dir):
                continue

            scenarios = os.listdir(scenario_dir)

            for name in scenarios:
                scenario_path = os.path.join(scenario_dir, name)
                map_json_path = os.path.join(scenario_path, "map_data.json")
                
                # Boundary guard to ensure it's a valid directory file structure containing a playable scenario template
                if not os.path.isdir(scenario_path) or not os.path.exists(map_json_path):
                    continue
                    
                try:
                    # 1. Instantiate Map with standard singleplayer configurations to pull existing meta/map data into memory
                    temp_map_context = Map(load_path=scenario_path, is_scenario=True)
                    
                    # 2. Execute the official resync pipeline (handles unit synchronization, country updates, and tech scrubbing)
                    temp_map_context.refresh_nation_data()
                    print(f"refreshed {name}")
                    
                    # Set all playable country resources to 0 before compounding income calculations
                    for nation_name, stats in temp_map_context.nation_data.items():
                        if nation_name != "GLOBAL_EVENTS" and nation_name not in c.UNPLAYABLE_NATIONS:
                            stats["manpower"] = 0
                            stats["materials"] = 0
                            stats["fuel"] = 0
                    
                    # 3. Clean country flags/portraits inside memory before serializing
                    queries.scrub_default_images(temp_map_context.nation_data)
                    
                    # 4. Reconstruct the exact structural configuration payload generated by save_map_data()
                    save_dict = {
                        "date": {
                            "day": temp_map_context.time_manager.day,
                            "month": temp_map_context.time_manager.month_index,
                            "year": temp_map_context.time_manager.year,
                            "total_turns": getattr(temp_map_context.time_manager, 'total_turns', 0)
                        },
                        "loop_map": temp_map_context.loop_map,
                        "player_country": temp_map_context.player_country,
                        "active_players": getattr(temp_map_context, "active_players", [temp_map_context.player_country]),
                        "current_player_index": getattr(temp_map_context, "current_player_index", 0),
                        "default_research": getattr(temp_map_context, "default_research", None),
                        "nation_data": temp_map_context.nation_data,
                        "provinces": {}
                    }
                    
                    for data in temp_map_context.map_data.values():
                        save_dict["provinces"][data["json_key"]] = {
                            "owner": data["owner"],
                            "cores": data.get("cores", []),
                            "is_coastal": data.get("is_coastal", False),
                            "units": data.get("units", []),
                            "deployment_queue": data.get("deployment_queue", []),
                            "orders": data.get("orders", []),
                            "resources": data.get("resources", []),
                            "buildings": data.get("buildings", [])
                        }

                    # 5. Perform the manual write operations in-place inside the scenario path directory
                    indent_val = c.SAVE_INDENT
                    
                    # Overwrite master operational dataset file
                    with open(os.path.join(scenario_path, "meta.json"), "w") as f:
                        json.dump(save_dict, f, indent=indent_val)
                        
                    # Overwrite master geometric vector layout file 
                    with open(map_json_path, "w") as f:
                        json.dump(temp_map_context.raw_json_data, f, indent=indent_val)
                        
                    # Overwrite turning history logs if applicable
                    if hasattr(temp_map_context, 'history'):
                        with open(os.path.join(scenario_path, "history.json"), "w") as f:
                            json.dump(temp_map_context.history, f, indent=c.HISTORY_INDENT)
                            
                    # Overwrite visual map files in place
                    pygame.image.save(temp_map_context.political_map, os.path.join(scenario_path, "political.png"))
                    pygame.image.save(temp_map_context.terrain_map, os.path.join(scenario_path, "terrain.png"))
                    pygame.image.save(temp_map_context.id_map, os.path.join(scenario_path, "id_map.png"))
                    pygame.image.save(temp_map_context.cores_map, os.path.join(scenario_path, "cores.png"))
                    
                    scenarios_processed += 1
                except Exception as e:
                    print(f"[REFRESH ERROR] Failed to automatically sync structural data profiles for scenario '{name}': {e}")

        # Post an alert back onto the UI layout template frame
        print(f"Synced {scenarios_processed} scenarios!")

    def map_selected(self):
        self.next_state = "MAP"
        self.done = True

    def exit_to_menu(self):
        self.set_sub_state("CATEGORY")
        self.next_state = "MENU"
        self.done = True
    
    def handle_back_key(self):
        if self.sub_state != "CATEGORY":
            self.set_sub_state("CATEGORY")
        else:
            self.exit_to_menu()

    def start_random_scenario(self):
        self.set_sub_state("CATEGORY")
        self.next_state = "RANDOM_SETUP"
        self.done = True