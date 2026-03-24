import pygame
import random
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.ui import buttons, event_handler
from map_functions.data import load_map, save_map
from map_functions.logic import edit_province_ownership, political_refresher, turn_processor
from map_functions.camera.camera_handler import MapCamera
from map_functions.rendering import map_renderer
from map_functions.data import country_io
from map_functions.logic import map_utils
from map_functions.logic import diplomacy_logic

class Map(GameState):
    def __init__(self, load_path=None, is_scenario=False):
        super().__init__()

        # --- 1. Basic State Variables ---
        self.selection_mode = is_scenario
        self.pending_selection = None 
        self.player_country = "None"

        self.secondary_modes = ["UNITS", "ECONOMY", "MILITARY", "BLANK"]
        self.sec_idx = 0
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        
        self.base_layer = "POLITICAL" 
        self.load_path = load_path

        # --- 2. Data Loading ---
        # This call now handles images, province JSON, AND nation_data logic
        load_map.load_map_assets(self, load_path)

        # --- 3. Visuals & UI Setup ---
        self.bg_color = (20, 20, 20)
        self.font = pygame.font.SysFont("Arial", 18)
        self.small_font = pygame.font.SysFont("Arial", 14)
        
        self.top_ui_height = self.bot_ui_height = 60
        self.total_ui_h = 120
        self.top_bar_rect = pygame.Rect(0, 0, SCREEN_WIDTH, 60)
        self.bot_bar_rect = pygame.Rect(0, SCREEN_HEIGHT - 60, SCREEN_WIDTH, 60)
        
        self.map_w, self.map_h = self.id_map.get_size()
        self.min_zoom = (SCREEN_HEIGHT - self.total_ui_h) / self.map_h 
        self.camera = MapCamera(self.min_zoom)
        
        # Sync active map to the default base layer
        self.active_map = self.political_map if self.base_layer == "POLITICAL" else self.terrain_map
        self.map_mode = self.base_layer

        self.selected_province = self.hovered_province = self.last_hovered_id = None
        self.hover_glow_surf = self.hover_glow_rect = None
        self.feedback_text = ""
        self.feedback_timer = 0

        # Build UI Buttons
        buttons.render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})

    # --- Properties (Links UI variables directly to the loaded dictionary) ---
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

    # --- Logic Methods ---
    def cycle_secondary_mode(self):
        self.sec_idx = (self.sec_idx + 1) % len(self.secondary_modes)
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        self.show_feedback(f"View Mode: {self.secondary_mode}")
        
    def select_player_country(self, province):
        owner = province.get("owner", "empty")
        # Check if it's a real playable country
        if owner in self.nation_data and self.nation_data[owner].get("is_playable"):
            self.pending_selection = owner
            self.selected_province = province # This ensures the renderer draws the highlight!
            self.show_feedback(f"Selected {owner.title()}...")
        else:
            self.show_feedback("Cannot select unowned or non-playable territory")

    def confirm_player_country(self):
        if self.pending_selection:
            self.player_country = self.pending_selection
            self.selection_mode = False
            self.pending_selection = None
            
            # --- THE FIX ---
            self.selected_province = None  # Clear the "clicked" state
            self.hovered_province = None
            self.hover_glow_surf = None
            # ----------------
            
            self.show_feedback(f"Now playing as {self.player_country}")
            buttons.render_buttons(self)
            
    def cancel_selection(self):
        self.pending_selection = None
        self.selected_province = None # Remove highlight

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
        self.show_feedback("Mode: Political")

    def save_map_data(self): 
        save_map.save_map_data(self)

    def refresh_political_map(self): 
        political_refresher.refresh_political_map(self)

    def conquer_province(self): 
        """
        Maintains the original behavior: picks a random nation 
        and assigns it to the currently selected province.
        """
        if self.selected_province:
            
            # 1. Get the list of possible countries (just like the old script did)
            # nations_dict = country_io.get_nation_colors()
            # nations_list = list(nations_dict.keys())
            
            # To match your previous specific logic exactly:
            nations_list = ["rome", "gaul", "carthage"] 
            
            # 2. Pick one at random
            new_owner = random.choice(nations_list)
            
            # 3. Call the refactored function with the necessary arguments
            edit_province_ownership.conquer_province(self, self.selected_province, new_owner)

    def exit_to_menu(self): 
        self.next_state, self.done = "MENU", True

    def reset_view(self): 
        self.camera.target_zoom, self.camera.target_pos = self.min_zoom, pygame.Vector2(0, 0)

    def advance_time(self):
        turn_processor.process_next_turn(self)

    def show_feedback(self, text): 
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()

    def additional_events(self, event): 
        event_handler.handle_map_events(self, event)

    def open_recruit(self):
        if self.selected_province:
            self.next_state = "RECRUIT"
            self.done = True

    def open_orders(self):
        if self.selected_province:
            self.next_state = "ORDERS"
            self.done = True

    def open_navy(self):
        if self.selected_province and self.selected_province.get("is_coastal"):
            self.next_state = "NAVY"
            self.done = True

    def update(self):
        self.camera.update(self, SCREEN_HEIGHT)
        for el in self.elements: el.visible = False

        is_sel = bool(self.selected_province)
        if self.selection_mode:
            self.btn_exit_to_menu.visible = True
            return

        for i in range(min(7, len(self.elements))): self.elements[i].visible = True
        self.btn_exit_to_menu.visible = not is_sel
        self.btn_close_info.visible = is_sel

        if is_sel:
            self.btn_conquer.visible = True
            owner = self.selected_province.get("owner", "empty")
            player_data = self.nation_data.get(self.player_country, {})
            pending = player_data.get("pending_diplomacy", {})
            
            # --- 1. PRESENCE LOGIC (Orders/Recruitment) ---
            has_player_units = any(u['owner'] == self.player_country for u in self.selected_province.get("units", []))
            
            if owner == self.player_country or has_player_units:
                self.btn_go_orders.visible = True
                
                if owner == self.player_country:
                    terrain = self.selected_province.get("terrain", "")
                    is_land = terrain not in ["ocean", "coastal_sea", "inland_sea", "lakes"]
                    self.btn_go_recruit.visible = is_land
                    self.btn_go_navy.visible = is_land and self.selected_province.get("is_coastal", False)

            # --- 2. DIPLOMACY LOGIC (Foreign Land) ---
            # Now an 'if', not an 'elif', so it can show alongside Orders
            if owner != self.player_country and owner in self.nation_data and self.nation_data[owner].get("is_playable"):
                # Move these buttons down so they don't overlap with Recruit/Orders
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