# map_functions/ui/buttons.py
from ui_elements import Button
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.rendering import symbol_loader

def render_buttons(self):
    if not self.selection_mode:
        unit_icon = symbol_loader.get_symbol("Infantry", 0.8)
        economy_icon = symbol_loader.get_symbol("Factory", 0.8)
        blank_icon = symbol_loader.get_symbol("Star", 0.8)
        terrain_icon = symbol_loader.get_symbol("Mountains", 0.8)
        political_icon = symbol_loader.get_symbol("Flag", 0.8)
        relations_icon = symbol_loader.get_symbol("Heart", 0.8)
        research_icon = symbol_loader.get_symbol("Research", 0.8)
        save_icon = symbol_loader.get_symbol("Save", 0.8)

        self.elements = [
            # Refresh remains in the top bar
            Button(120, 10, "small", "grey", "Pol Refresh", self.refresh_political_map),
            Button(220, 10, "small", "grey", "Rel Refresh", self.refresh_relations_map),
            Button(320, 10, "small", "grey", "Data Refresh", self.refresh_nation_data), # <-- ADDED THIS
        ]

        # Primary View Buttons (Inside the bottom bar)
        self.elements.extend([
            Button(20, SCREEN_HEIGHT - 50, "small_square", "green", "Terrain", self.set_terrain, image=terrain_icon, show_text=False),
            Button(70, SCREEN_HEIGHT - 50, "small_square", "blue", "Political", self.set_political, image=political_icon, show_text=False),
            Button(120, SCREEN_HEIGHT - 50, "small_square", "purple", "Relations", self.set_relations, image=relations_icon, show_text=False),
        ])

        # Secondary View Buttons (Floating directly above the primary buttons)
        self.elements.extend([
            Button(20, SCREEN_HEIGHT - 100, "small_square", "red", "Units", lambda: self.set_view_mode("UNITS"), image=unit_icon, show_text=False),
            Button(70, SCREEN_HEIGHT - 100, "small_square", "orange", "Economy", lambda: self.set_view_mode("ECONOMY"), image=economy_icon, show_text=False),
            Button(120, SCREEN_HEIGHT - 100, "small_square", "yellow", "Blank", lambda: self.set_view_mode("BLANK"), image=blank_icon, show_text=False),
        ])

        # Right-side top buttons
        if self.is_editor:
            self.elements.extend([
                Button(SCREEN_WIDTH - 120, 10, "small", "blue", "Save", self.save_map_data),
                Button(SCREEN_WIDTH - 230, 10, "small", "blue", "Load", self.editor_load_map),
                Button(SCREEN_WIDTH - 340, 10, "small", "grey", "Nation", self.select_brush_nation),
                Button(SCREEN_WIDTH - 450, 10, "small", "grey", "Building", self.select_building_brush),
                Button(SCREEN_WIDTH - 560, 10, "small", "grey", "Unit", self.select_unit_brush),      # <-- ADDED THIS
                Button(SCREEN_WIDTH - 670, 10, "small", "purple", "Map Tech", self.open_map_research_editor) # <-- ADDED THIS
            ])
        else:
            self.elements.extend([
                # Next Turn
                Button(SCREEN_WIDTH - 120, 10, "small", "purple", "Next Turn", self.advance_time),
                # Research
                Button(SCREEN_WIDTH - 230, 10, "small", "blue", "R&D", self.open_research, image=research_icon),
                # Save
                Button(SCREEN_WIDTH - 340, 10, "small", "green", "Save", self.save_map_data, image=save_icon)
            ])
    
    self.btn_go_build = Button(1390, 550, "medium", "grey", "Construction", self.open_construction)
    self.elements.append(self.btn_go_build)

    # --- Contextual Buttons (Visible when province selected) ---
    self.btn_conquer = Button(20, 440, "small", "red", "Conquer", self.conquer_province)
    self.btn_conquer.visible = False 
    self.elements.append(self.btn_conquer)

    # Close/Deselect button
    self.btn_close_info = Button(15, 15, "small", "red", "X", self.deselect_province)
    self.btn_close_info.visible = False
    self.elements.append(self.btn_close_info)

    # Exit to menu button
    self.btn_exit_to_menu = Button(15, 15, "small", "red", "Exit", self.exit_to_menu)
    self.btn_exit_to_menu.visible = False
    self.elements.append(self.btn_exit_to_menu)

    # NEW: Navigation buttons for sub-screens
    # These replace the old single 'Recruit' button
    self.btn_go_recruit = Button(1390, 370, "medium", "green", "Recruit Menu", self.open_recruit)
    self.btn_go_orders = Button(1390, 430, "medium", "blue", "Give Orders", self.open_orders)

    self.btn_declare_war = Button(1390, 370, "medium", "red", "Declare War", self.handle_declare_war)
    self.btn_form_alliance = Button(1390, 430, "medium", "green", "Form Alliance", self.handle_form_alliance)

    # Initial Visibility
    self.btn_conquer.visible = False 
    self.btn_close_info.visible = False
    self.btn_go_recruit.visible = False
    self.btn_go_orders.visible = False

    # Add them to the elements list
    self.elements.extend([
        self.btn_conquer, 
        self.btn_close_info, 
        self.btn_exit_to_menu,
        self.btn_go_recruit,
        self.btn_go_orders,
        self.btn_declare_war, 
        self.btn_form_alliance
    ])