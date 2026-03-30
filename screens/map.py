import pygame
import random
import tkinter as tk
from tkinter import Listbox
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
    def __init__(self, load_path=None, is_scenario=False, is_random=False): # Added is_random
        super().__init__()

        # Add these to Map.__init__ in screens/map.py
        self.brush_building = "None" 
        self.brush_unit = "None"    # <-- ADDED THIS
        self.editor_mode = "NATION" # Toggle between painting nations and buildings

        # --- 1. Basic State Variables ---
        self.selection_mode = is_scenario
        self.pending_selection = None 
        self.player_country = "None"

        self.secondary_modes = ["UNITS", "ECONOMY", "BLANK"]
        self.sec_idx = 0
        # this first one chooses units
        # self.secondary_mode = self.secondary_modes[self.sec_idx]
        # this second one chooses BLANK because it's the second one in the list!
        self.secondary_mode = self.secondary_modes[2]
        
        self.base_layer = "POLITICAL" 
        self.load_path = load_path

        self.is_editor = (self.load_path is None and not is_scenario) 
        if self.is_editor:
            self.player_country = "Editor"
            self.selection_mode = False # No need to pick a country in editor
            
        self.painting_active = False # New state for drag-to-paint
        self.brush_nation = "Unclaimed" # The nation we are currently 'painting'
        
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
        # CHANGED: Increased height from 50 to 110 so it covers the bottom bar
        self.raised_rect = pygame.Rect(0, SCREEN_HEIGHT - 110, 175, 110)
        
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

        self.show_exit_confirmation = False # New state variable
        self.confirm_box_rect = pygame.Rect(0, 0, 400, 200) # For the modal
        
        # Load standard assets
        load_map.load_map_assets(self, load_path)

        # Add the new Relations Map layer
        self.relations_map = self.id_map.copy()
        # self.refresh_political_map()
        # self.refresh_relations_map() # <-- ADD THIS LINE

        # New: Scramble the map if requested
        if is_random:
            self.randomize_all_provinces()
            # Force a visual refresh after changing logic data
            self.refresh_political_map()
            self.refresh_relations_map() # <-- ADD THIS LINE HERE TOO

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

    def set_view_mode(self, mode):
        self.secondary_mode = mode
        self.show_feedback(f"View: {mode}")

    def editor_load_map(self):
        """Opens a file dialog to load a map folder directly into the editor."""
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askdirectory(initialdir="saves", title="Select Map Folder to Edit")
        root.destroy()
    
        if path:
            # Re-run asset loader on this instance
            from map_functions.data import load_map
            load_map.load_map_assets(self, path)
            self.refresh_political_map()
            self.show_feedback("Map Loaded into Editor")

    # --- Logic Methods ---
    def cycle_secondary_mode(self):
        self.sec_idx = (self.sec_idx + 1) % len(self.secondary_modes)
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        self.show_feedback(f"View Mode: {self.secondary_mode}")
        
    def select_player_country(self, province):
        owner = province.get("owner", "Unclaimed")
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
        self.refresh_political_map()
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
            nations_list = ["Rome", "Gaul", "Carthage"] 
            
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

    def select_brush_nation(self):
        """Opens a Tkinter selection window and sets mode to NATION."""
        import tkinter as tk
        
        root = tk.Tk()
        root.title("Select Nation")
        root.geometry("300x450")
        root.attributes("-topmost", True)
        self.menu_active = True

        def on_select(event=None):
            selection = lb.curselection()
            if selection:
                self.brush_nation = lb.get(selection[0])
                # Ensure the editor knows we are now painting countries
                self.editor_mode = "NATION" 
                self.show_feedback(f"Brush: {self.brush_nation}")
            close_menu()

        def close_menu():
            self.menu_active = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_menu)
        tk.Label(root, text="Select Paint Nation:", font=("Arial", 12)).pack(pady=10)
        
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        
        # Sort and filter out utility 'countries'
        nations = sorted(list(self.nation_data.keys()))
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
        for n in nations:
            if n not in ["Ocean", "Lakes"]:
                lb.insert(tk.END, n)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        
        tk.Button(root, text="Confirm Selection", command=on_select, 
                  bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

        lb.bind('<Double-1>', on_select)

        while self.menu_active:
            try:
                root.update()
                pygame.event.pump()
            except (tk.TclError, Exception):
                break

    def select_building_brush(self):
        """Opens a selection window for building types and sets mode to BUILDING."""
        import tkinter as tk
        
        root = tk.Tk()
        root.title("Select Building")
        root.geometry("300x400")
        root.attributes("-topmost", True)
        self.menu_active = True

        buildings = [
            "None",
            "Workshop Lvl 1", "Workshop Lvl 2", "Workshop Lvl 3", "Workshop Lvl 4", "Workshop Lvl 5",
            "Basic Factory",
            "Factory Lvl 1", "Factory Lvl 2", "Factory Lvl 3", "Factory Lvl 4", "Factory Lvl 5",
            "Synthetic Refinery Lvl 1", "Synthetic Refinery Lvl 2", "Synthetic Refinery Lvl 3"
        ]

        def on_select(event=None):
            selection = lb.curselection()
            if selection:
                self.brush_building = lb.get(selection[0])
                # Ensure the editor knows we are now placing buildings
                self.editor_mode = "BUILDING"
                self.show_feedback(f"Brush: {self.brush_building}")
            close_menu()

        def close_menu():
            self.menu_active = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_menu)
        tk.Label(root, text="Select Building to Place:", font=("Arial", 12)).pack(pady=10)
        
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
        for b in buildings:
            lb.insert(tk.END, b)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        
        tk.Button(root, text="Confirm Selection", command=on_select, 
                  bg="#2196F3", fg="white", font=("Arial", 10, "bold"), pady=10).pack(fill="x", padx=10, pady=10)

        lb.bind('<Double-1>', on_select)

        while self.menu_active:
            try:
                root.update()
                pygame.event.pump()
            except (tk.TclError, Exception):
                break
    
    def open_construction(self):
        if self.selected_province and self.selected_province.get("owner") == self.player_country:
            self.next_state = "CONSTRUCTION"
            self.done = True

    # Update the toggle method to switch modes
    def toggle_editor_brush_type(self):
        if self.editor_mode == "NATION":
            self.editor_mode = "BUILDING"
            self.show_feedback("Editor: Building Placement")
        else:
            self.editor_mode = "NATION"
            self.show_feedback("Editor: Nation Painting")
            
    def update(self):
        self.camera.update(self, SCREEN_HEIGHT)
        for el in self.elements:
            el.visible = False

            # --- HIGHLIGHT SELECTED BUTTONS ---
            # Tie button highlight states to your view variables
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
                    # Because there is a separate primary Economy button with text, we verify 
                    # we are grabbing the "Secondary mode" icon button by checking `show_text`
                    if not getattr(el, 'show_text', True):
                        el.is_selected = (self.secondary_mode == "ECONOMY")
                    else:
                        el.is_selected = False
                else:
                    el.is_selected = False

        if self.is_editor:
            # Only show basic map buttons in Editor mode
            for el in self.elements:
                # Standard Editor Buttons (Added "Relations")
                if el.text in ["Terrain", "Political", "Relations", "Pol Refresh", "Rel Refresh", "Data Refresh", "Unit", "Map Tech", "Reset", "Save", "Load", "Nation", "Building", "Refresh", "Exit", "View Mode", "Units", "Economy", "Blank"]:
                    el.visible = True
                
                # Dynamic Color for "Nation" button
                if el.text == "Nation":
                    el.visible = True
                    if self.editor_mode == "NATION":
                        el.color = (0, 150, 0)        # Active Green
                        el.hover_color = (0, 200, 0)
                    else:
                        el.color = (100, 100, 100)    # Inactive Grey
                        el.hover_color = (150, 150, 150)

                # Dynamic Color for "Building" button
                if el.text == "Building":
                    el.visible = True
                    if self.editor_mode == "BUILDING":
                        el.color = (0, 100, 200)      # Active Blue
                        el.hover_color = (50, 150, 255)
                    else:
                        el.color = (100, 100, 100)    # Inactive Grey
                        el.hover_color = (150, 150, 150)
            return

        is_sel = bool(self.selected_province)
        if self.selection_mode:
            self.btn_exit_to_menu.visible = True
            return
        
        # Fix for the hardcoded number comment! Safely identify contextual buttons:
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
                
        # funny, a hardcoded number
        # this will be a problem later if more than 12 buttons are ever added
        for i in range(min(12, len(self.elements))): self.elements[i].visible = True
        self.btn_exit_to_menu.visible = not is_sel
        self.btn_close_info.visible = is_sel
        # self.btn_go_build.visible = is_sel and owner == self.player_country

        if is_sel:
            self.btn_conquer.visible = True
            owner = self.selected_province.get("owner", "Unclaimed")
            player_data = self.nation_data.get(self.player_country, {})
            pending = player_data.get("pending_diplomacy", {})
            
            # --- 1. PRESENCE LOGIC (Orders/Recruitment) ---
            has_player_units = any(u['owner'] == self.player_country for u in self.selected_province.get("units", []))
            
            if owner == self.player_country or has_player_units:
                self.btn_go_orders.visible = True
                
                if owner == self.player_country:
                    terrain = self.selected_province.get("terrain", "")
                    is_land = terrain not in ["ocean", "coastal_sea", "inland_sea", "lakes"]
                    self.btn_go_build.visible = True
                    self.btn_go_recruit.visible = is_land

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
    
    def open_research(self):
        """Transition to research screen without needing a province."""
        self.next_state = "RESEARCH"
        self.done = True
    
    def randomize_all_provinces(self):
        """Assigns every land province to a random playable nation."""
        import random
        
        # 1. Get list of playable nations (excluding utility nations like Ocean/Unclaimed)
        playable_nations = [
            name for name, stats in self.nation_data.items() 
            if stats.get("is_playable") and name not in ["Ocean", "Lakes", "Unclaimed"]
        ]
        
        if not playable_nations:
            return

        # 2. Iterate through map data
        for province in self.map_data.values():
            terrain = province.get("terrain", "")
            # Only paint land provinces
            is_water = terrain in ["ocean", "coastal_sea", "inland_sea", "lakes"]
            
            if not is_water:
                new_owner = random.choice(playable_nations)
                province["owner"] = new_owner
        
        self.show_feedback("Map Randomized!")
    
    def exit_to_menu(self): 
        """This now just triggers the UI instead of exiting"""
        self.show_exit_confirmation = True
        # Hide standard UI elements while confirming to avoid clicks
        for el in self.elements:
            el.visible = False

    def cancel_exit(self):
        """Returns to the game"""
        self.show_exit_confirmation = False
        # Re-trigger button visibility logic in next update()
        self.show_feedback("Exit cancelled")

    def confirm_exit(self):
        """Actually leaves the game"""
        self.next_state, self.done = "MENU", True
    
    def set_relations(self): 
        self.base_layer = "RELATIONS"
        self.active_map = self.relations_map
        self.refresh_relations_map()
        self.show_feedback("Mode: Relations")

    #def refresh_relations(self):
        #self.refresh_relations_map()

    def refresh_relations_map(self): 
        political_refresher.refresh_relations_map(self)

    def get_player_economy_projections(self):
        """Calculates expected daily resource changes for the UI"""
        # other increase in turn processor might be different if this is modified
        YIELD_MONEY = 500
        YIELD_MANPOWER = 50
        YIELD_MATERIALS = 100
        YIELD_FUEL = 1
        UPKEEP_MODIFIER = 0.05

        inc = 0
        bonus = {"money":0, "manpower":0, "materials":0, "fuel":0}
        upkeep = {"money":0, "manpower":0, "materials":0, "fuel":0}

        # Cache library loads to prevent lag
        if not hasattr(self, 'cached_unit_library'):
            import json, os
            self.cached_unit_library = json.load(open('map_functions/data/unit_data.json')) if os.path.exists('map_functions/data/unit_data.json') else {}
            self.cached_building_library = json.load(open('map_functions/data/building_data.json')) if os.path.exists('map_functions/data/building_data.json') else {}

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
                # Add entirely new countries
                self.nation_data[country] = data
                added_count += 1
            else:
                # Update existing countries without overwriting their live game stats (like money/troops)
                if "color" in data and self.nation_data[country].get("color") != data["color"]:
                    self.nation_data[country]["color"] = data["color"]
                    updated_count += 1
                
                # Good idea to update the display name too just in case you changed it
                if "name" in data:
                    self.nation_data[country]["name"] = data["name"]
                
        # Resync the visual colors for the renderer
        self.nation_colors = {name: tuple(stats["color"]) for name, stats in self.nation_data.items()}
        
        # CRITICAL: Force the visual map layers to immediately redraw using the new colors
        self.refresh_political_map()
        self.refresh_relations_map()
        
        self.show_feedback(f"Data Resynced! Added {added_count}, Updated {updated_count}.")
    
    def open_economy_screen(self):
        self.next_state = "ECONOMY"
        self.done = True

    def open_editor_economy(self):
        """Opens a Tkinter window listing the income of every active country."""
        import tkinter as tk
        from tkinter import ttk
        import json, os

        active_countries = set()
        for prov in self.map_data.values():
            owner = prov.get("owner")
            if owner and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
                active_countries.add(owner)

        if not active_countries:
            self.show_feedback("No active countries on map!")
            return

        root = tk.Tk()
        root.title("Global Economy Overview")
        root.geometry("600x400")
        root.attributes("-topmost", True)
        self.menu_active = True

        def close_menu():
            self.menu_active = False
            root.destroy()
            
        root.protocol("WM_DELETE_WINDOW", close_menu)

        # Economy logic
        YIELD_MONEY = 500
        UPKEEP_MODIFIER = 0.05
        
        unit_library = {}
        building_library = {}
        if os.path.exists('map_functions/data/unit_data.json'):
            with open('map_functions/data/unit_data.json', 'r') as f: unit_library = json.load(f)
        if os.path.exists('map_functions/data/building_data.json'):
            with open('map_functions/data/building_data.json', 'r') as f: building_library = json.load(f)

        econ_data = {c: {"inc": 0, "bonus": 0, "upkeep": 0} for c in active_countries}

        for prov in self.map_data.values():
            owner = prov.get("owner")
            if owner in econ_data:
                econ_data[owner]["inc"] += 1
                for b_name in prov.get("buildings", []):
                    stats = building_library.get(b_name, {})
                    econ_data[owner]["bonus"] += stats.get("prod_money", 0)
            
            for unit in prov.get("units", []):
                u_owner = unit.get("owner")
                if u_owner in econ_data:
                    stats = unit_library.get(unit["type"], {})
                    econ_data[u_owner]["upkeep"] += stats.get("cost_money", 0) * UPKEEP_MODIFIER

        columns = ("Country", "Gross Income", "Upkeep", "Net Income", "Treasury")
        tree = ttk.Treeview(root, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=110, anchor="center")
        
        for c in sorted(active_countries):
            d = econ_data[c]
            gross = (d["inc"] * YIELD_MONEY) + d["bonus"]
            upk = int(d["upkeep"])
            net = gross - upk
            treasury = self.nation_data.get(c, {}).get("money", 0)
            tree.insert("", tk.END, values=(c, f"+{gross}", f"-{upk}", f"{'+' if net>=0 else ''}{net}", treasury))

        scrollbar = ttk.Scrollbar(root, orient="vertical", command=tree.yview)
        tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(fill="both", expand=True)

        while self.menu_active:
            try:
                root.update()
                pygame.event.pump()
            except:
                break

    def open_map_research_editor(self):
        """Opens a UI to edit research for countries currently existing on the map."""
        import tkinter as tk
        import json, os
        
        # 1. Find only countries that actually own territory
        active_countries = set()
        for prov in self.map_data.values():
            owner = prov.get("owner")
            if owner and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
                active_countries.add(owner)

        if not active_countries:
            self.show_feedback("No active countries on map!")
            return

        # 2. Get default tech dict dynamically
        def get_default_research():
            template_path = "map_functions/data/research_template.json"
            res_dict = {}
            if os.path.exists(template_path):
                with open(template_path, "r") as f:
                    struct = json.load(f)
                res_dict = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
                if "carrack" in res_dict: res_dict["carrack"] = 1
                if "cavalry" in res_dict: res_dict["cavalry"] = 0
            return res_dict

        default_res = get_default_research()

        root = tk.Tk()
        root.title("Map Tech Editor")
        root.geometry("350x500")
        root.attributes("-topmost", True)
        self.menu_active = True

        def close_menu():
            self.menu_active = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_menu)
        tk.Label(root, text="Select Country to Edit:", font=("Arial", 12)).pack(pady=5)
        
        lb = tk.Listbox(root, font=("Arial", 11))
        
        def populate_listbox():
            lb.delete(0, tk.END)
            for c in sorted(active_countries):
                c_res = self.nation_data.get(c, {}).get("research", {})
                is_diff = False
                # Check if it deviates from the default template
                for k, v in default_res.items():
                    if c_res.get(k, v) != v:
                        is_diff = True
                        break
                prefix = "[MODIFIED] " if is_diff else ""
                lb.insert(tk.END, f"{prefix}{c}")

        populate_listbox()
        lb.pack(fill="both", expand=True, padx=10, pady=5)

        def open_edit_window(target_country, is_bulk=False):
            # If bulk, load default as base. If specific, load their current
            if is_bulk:
                base_data = default_res.copy()
            else:
                actual_name = target_country.replace("[MODIFIED] ", "") # Strip prefix
                base_data = self.nation_data.get(actual_name, {}).get("research", default_res.copy())
            
            # Ensure all keys from default exist in base_data visually
            for k, v in default_res.items():
                if k not in base_data:
                    base_data[k] = v

            edit_win = tk.Toplevel(root)
            title_text = "ALL COUNTRIES" if is_bulk else actual_name
            edit_win.title(f"{title_text} Research")
            edit_win.geometry("300x500")
            edit_win.attributes("-topmost", True)
            
            canvas = tk.Canvas(edit_win)
            scrollbar = tk.Scrollbar(edit_win, orient="vertical", command=canvas.yview)
            scroll_frame = tk.Frame(canvas)
            scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True, pady=5)
            scrollbar.pack(side="right", fill="y")
            
            entries = {}
            for i, tech in enumerate(sorted(base_data.keys())):
                tk.Label(scroll_frame, text=tech.replace("_", " ").title()).grid(row=i, column=0, sticky="e", padx=5)
                ent = tk.Entry(scroll_frame, width=8)
                ent.insert(0, str(base_data[tech]))
                ent.grid(row=i, column=1, pady=2)
                entries[tech] = ent
                
            def save_res():
                new_data = {}
                for tech, ent in entries.items():
                    try:
                        new_data[tech] = int(ent.get())
                    except ValueError: 
                        new_data[tech] = base_data.get(tech, 0)
                
                if is_bulk:
                    for c in active_countries:
                        if "research" not in self.nation_data[c]:
                            self.nation_data[c]["research"] = {}
                        self.nation_data[c]["research"].update(new_data)
                    self.show_feedback("Saved research for ALL countries")
                else:
                    if "research" not in self.nation_data[actual_name]:
                        self.nation_data[actual_name]["research"] = {}
                    self.nation_data[actual_name]["research"].update(new_data)
                    self.show_feedback(f"Saved research for {actual_name}")
                
                populate_listbox()
                edit_win.destroy()
                
            tk.Button(edit_win, text="Save Tech Levels", command=save_res, bg="#4CAF50", fg="white").pack(side="bottom", fill="x", pady=5)

        def edit_selected():
            sel = lb.curselection()
            if not sel: return
            open_edit_window(lb.get(sel[0]), is_bulk=False)

        def edit_all():
            open_edit_window(None, is_bulk=True)

        tk.Button(root, text="Edit Selected Nation", command=edit_selected, bg="#2196F3", fg="white", pady=5).pack(fill="x", padx=10, pady=2)
        tk.Button(root, text="Edit ALL Nations (Bulk)", command=edit_all, bg="#f44336", fg="white", pady=5).pack(fill="x", padx=10, pady=5)

        while self.menu_active:
            try:
                root.update()
                pygame.event.pump()
            except:
                break
    
    def select_unit_brush(self):
        """Opens a selection window for unit types and sets mode to UNIT."""
        import tkinter as tk
        import json, os
        
        root = tk.Tk()
        root.title("Select Unit")
        root.geometry("300x400")
        root.attributes("-topmost", True)
        self.menu_active = True

        unit_path = 'map_functions/data/unit_data.json'
        units = list(json.load(open(unit_path, 'r')).keys()) if os.path.exists(unit_path) else []

        def on_select(event=None):
            selection = lb.curselection()
            if selection:
                self.brush_unit = lb.get(selection[0])
                self.editor_mode = "UNIT"
                self.show_feedback(f"Brush: {self.brush_unit}")
            close_menu()

        def close_menu():
            self.menu_active = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_menu)
        tk.Label(root, text="Select Unit to Place:", font=("Arial", 12)).pack(pady=10)
        
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True, padx=10)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        
        lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
        for u in ["None"] + units:
            lb.insert(tk.END, u)
        lb.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=lb.yview)
        
        tk.Button(root, text="Confirm Selection", command=on_select, bg="#f44336", fg="white", pady=10).pack(fill="x", padx=10, pady=10)
        lb.bind('<Double-1>', on_select)

        while self.menu_active:
            try:
                root.update()
                pygame.event.pump()
            except:
                break