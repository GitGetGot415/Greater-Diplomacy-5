# map_functions/ui/buttons.py
from ui_elements import Button
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.rendering import symbol_loader
from map_functions.ui.minimap import UI_LEFT_OFFSET

def render_buttons(self):
    if not self.selection_mode:
        unit_icon = symbol_loader.get_symbol("Infantry", 2)
        economy_icon = symbol_loader.get_symbol("Factory", 2)
        blank_icon = symbol_loader.get_symbol("Star", 2)
        terrain_icon = symbol_loader.get_symbol("Mountains", 1.5)
        political_icon = symbol_loader.get_symbol("Flag", 1.5)
        relations_icon = symbol_loader.get_symbol("Heart", 2)
        research_icon = symbol_loader.get_symbol("Research", 2)
        save_icon = symbol_loader.get_symbol("Save", 2)
        core_icon = symbol_loader.get_symbol("Star", 1.5) # Using star as a symbol for cores

        self.elements = [
            # Refresh remains in the top bar
            # Button(1120, 210, "small", "grey", "Pol Refresh", self.refresh_political_map),
            # Button(1220, 210, "small", "grey", "Rel Refresh", self.refresh_relations_map),
        ]

        # Primary View Buttons (Inside the bottom bar)
        econ_callback = self.open_editor_economy if getattr(self, 'is_editor', False) else self.open_economy_screen
        
        self.elements.extend([
            Button(10, SCREEN_HEIGHT - 50, "small_square", "green", "Terrain", self.set_terrain, image=terrain_icon, show_text=False),
            Button(60, SCREEN_HEIGHT - 50, "small_square", "light_blue", "Political", self.set_political, image=political_icon, show_text=False),
            Button(110, SCREEN_HEIGHT - 50, "small_square", "purple", "Relations", self.set_relations, image=relations_icon, show_text=False),
            Button(160, SCREEN_HEIGHT - 50, "small_square", "pink", "Cores", self.set_cores, image=core_icon, show_text=False), # <--- NEW
            Button(20, 420, "left_ui_bar", "orange", "Economy", econ_callback)
        ])

        # Secondary View Buttons (Floating directly above the primary buttons)
        self.elements.extend([
            Button(10, SCREEN_HEIGHT - 100, "small_square", "red", "Units", lambda: self.set_view_mode("UNITS"), image=unit_icon, show_text=False),
            Button(60, SCREEN_HEIGHT - 100, "small_square", "orange", "Economy", lambda: self.set_view_mode("ECONOMY"), image=economy_icon, show_text=False),
            Button(110, SCREEN_HEIGHT - 100, "small_square", "yellow", "Blank", lambda: self.set_view_mode("BLANK"), image=blank_icon, show_text=False),
        ])

        # Right-side top buttons
        if self.is_editor:
            self.elements.extend([
                Button(SCREEN_WIDTH - 120, SCREEN_HEIGHT - 50, "small", "blue", "Save", self.save_map_data),
                Button(SCREEN_WIDTH - 230, SCREEN_HEIGHT - 50, "small", "blue", "Load", self.editor_load_map),
                Button(SCREEN_WIDTH - 340, SCREEN_HEIGHT - 50, "small", "grey", "Nation", self.select_brush_nation),
                Button(SCREEN_WIDTH - 340, SCREEN_HEIGHT - 100, "small", "pink", "Core Brush", self.select_core_brush),
                Button(SCREEN_WIDTH - 450, SCREEN_HEIGHT - 50, "small", "grey", "Building", self.select_building_brush),
                Button(SCREEN_WIDTH - 560, SCREEN_HEIGHT - 50, "small", "grey", "Unit", self.select_unit_brush),
                Button(SCREEN_WIDTH - 670, SCREEN_HEIGHT - 50, "small", "purple", "Map Tech", self.open_map_research_editor),
                Button(SCREEN_WIDTH - 780, SCREEN_HEIGHT - 50, "small", "grey", "Data Refresh", self.refresh_nation_data),
                
                # --- NEW BUTTON ---
                Button(SCREEN_WIDTH - 890, SCREEN_HEIGHT - 50, "small", "orange", "Set Date", self.open_editor_date)
            ])
        else:
            self.elements.extend([
                # Change the Y coordinate from 10 to SCREEN_HEIGHT - 50
                Button(SCREEN_WIDTH - 120, SCREEN_HEIGHT - 50, "small", "purple", "Next Turn", self.advance_time),
                # Research
                Button(20, 220, "left_ui_bar", "blue", "R&D", self.open_research, image=research_icon),
                # Save
                Button(20, 320, "left_ui_bar", "green", "Save", self.save_map_data, image=save_icon),
                # --- NEW BUTTON ---
                Button(20, 120, "left_ui_bar", "orange", "Edit Nation", self.open_edit_country)
            ])
    
    self.btn_go_build = Button(1390, 550, "medium", "grey", "Construction", self.open_construction)
    self.elements.append(self.btn_go_build)

    # Close/Deselect button
    self.btn_close_info = Button(SCREEN_WIDTH - 120, 10, "small", "red", "X", self.deselect_province)
    self.btn_close_info.visible = False
    self.elements.append(self.btn_close_info)

    # Exit to menu button
    self.btn_exit_to_menu = Button(SCREEN_WIDTH - 120, 10, "small", "red", "Exit", self.exit_to_menu)
    self.btn_exit_to_menu.visible = False
    self.elements.append(self.btn_exit_to_menu)

    # NEW: Navigation buttons for sub-screens
    # These replace the old single 'Recruit' button
    self.btn_go_recruit = Button(1390, 370, "medium", "green", "Recruit Menu", self.open_recruit)
    self.btn_go_orders = Button(1390, 430, "medium", "blue", "Give Orders", self.open_orders)

    self.btn_declare_war = Button(1390, 370, "medium", "red", "Declare War", self.handle_declare_war)
    self.btn_form_alliance = Button(1390, 430, "medium", "green", "Form Alliance", self.handle_form_alliance)

    # Initial Visibility
    self.btn_close_info.visible = False
    self.btn_go_recruit.visible = False
    self.btn_go_orders.visible = False

    # Add them to the elements list
    self.elements.extend([
        self.btn_close_info, 
        self.btn_exit_to_menu,
        self.btn_go_recruit,
        self.btn_go_orders,
        self.btn_declare_war, 
        self.btn_form_alliance
    ])