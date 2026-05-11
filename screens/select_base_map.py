import os
from gameState import GameState
from ui_elements import Button
import data.constants as c

class Select_Base_Map(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (40, 20, 60) # A distinct purple-ish background for the editor setup
        self.selected_save_path = None
        self.refresh_maps()

    def refresh_maps(self):
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_menu),
        ]
        
        base_dir = c.BASE_MAPS_DIR
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
            
        maps = os.listdir(base_dir)
        for i, name in enumerate(maps):
            btn_y = 150 + (i * 60)
            self.elements.append(
                Button("centered", btn_y, "new_game", "blue", name, 
                       lambda n=name: self.start_editor_with_map(n))
            )

    def start_editor_with_map(self, map_name):
        # Pass the specific base map folder
        self.selected_save_path = os.path.join(c.BASE_MAPS_DIR, map_name)
        self.next_state = "MAP"
        self.done = True

    def exit_to_menu(self):
        self.next_state = "MENU"
        self.done = True

    def handle_back_key(self):
        self.exit_to_menu()