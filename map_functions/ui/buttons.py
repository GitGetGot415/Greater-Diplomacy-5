# map_functions/ui/buttons.py
from ui_elements import Button
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT

def render_buttons(self):
    # --- Persistent Map Buttons ---
    if not self.selection_mode:
        self.elements = [
            Button(20, SCREEN_HEIGHT - 50, "small", "green", "Terrain", self.set_terrain),
            Button(130, SCREEN_HEIGHT - 50, "small", "blue", "Political", self.set_political),
            Button(240, SCREEN_HEIGHT - 50, "small", "grey", "Reset", self.reset_view),
            Button(360, SCREEN_HEIGHT - 50, "small", "grey", "Full Refresh", self.refresh_political_map),
            Button(480, SCREEN_HEIGHT - 50, "small", "grey", "Save Map", self.save_map_data),

            # NEW: Persistent Research Button (placed next to Save Map)
            Button(590, SCREEN_HEIGHT - 50, "small", "blue", "Research", self.open_research),

            Button(SCREEN_WIDTH - 120, SCREEN_HEIGHT - 50, "small", "green", "Next Turn", self.advance_time),
            Button(SCREEN_WIDTH - 230, SCREEN_HEIGHT - 50, "small", "grey", "View Mode", self.cycle_secondary_mode),
        ]
    
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