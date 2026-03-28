# map_functions/ui/buttons.py
from ui_elements import Button
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT

def render_buttons(self):
    if not self.selection_mode:
        # ALL BUTTONS NOW IN TOP BAR (y=10)
        self.elements = [
            Button(120, 10, "small", "green", "Terrain", self.set_terrain),
            Button(230, 10, "small", "blue", "Political", self.set_political),
            Button(340, 10, "small", "grey", "Reset", self.reset_view),
            Button(450, 10, "small", "grey", "Refresh", self.refresh_political_map),
            Button(480, 10, "small", "grey", "Units", lambda: self.set_view_mode("UNITS")),
            Button(590, 10, "small", "grey", "Economy", lambda: self.set_view_mode("ECONOMY")),
            Button(700, 10, "small", "grey", "Blank", lambda: self.set_view_mode("BLANK")),
        ]

        # Right-side top buttons
        if self.is_editor:
            self.elements.extend([
                Button(SCREEN_WIDTH - 120, 10, "small", "blue", "Save", self.save_map_data),
                Button(SCREEN_WIDTH - 230, 10, "small", "blue", "Load", self.editor_load_map),
                Button(SCREEN_WIDTH - 340, 10, "small", "grey", "Nation", self.select_brush_nation),
                Button(SCREEN_WIDTH - 450, 10, "small", "grey", "Building", self.select_building_brush)
            ])
        else:
            self.elements.extend([
                Button(SCREEN_WIDTH - 120, 10, "small", "green", "Next Turn", self.advance_time),
                Button(SCREEN_WIDTH - 230, 10, "small", "blue", "Research", self.open_research),
                Button(SCREEN_WIDTH - 340, 10, "small", "grey", "Save Game", self.save_map_data)
            ])
    
    self.btn_go_build = Button(1390, 550, "medium", "grey", "Construction", self.open_construction)
    self.elements.append(self.btn_go_build)

    # Add this to your contextual buttons
    self.btn_go_navy = Button(1390, 490, "medium", "blue", "Navy Menu", self.open_navy)
    self.btn_go_navy.visible = False
    self.elements.append(self.btn_go_navy)

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
        self.btn_go_navy,
        self.btn_declare_war, 
        self.btn_form_alliance
    ])