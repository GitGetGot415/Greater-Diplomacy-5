import pygame
import ui_elements
from gameState import GameState
from ui_elements import Button, Slider
from data.io import keybind_io

class Settings(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        
        # Grab the volume that was loaded in main.py
        self.volume = self.controller.volume 
        self.num_players = getattr(self.controller, 'num_players', 1)
        self.fullscreen = False
        self.listening_for = None
        
        self.refresh_ui()

    def refresh_ui(self):
        back_key_name = pygame.key.name(self.controller.keybinds["BACK"]).upper()
        
        back_btn_text = f"Back Key: {back_key_name}"
        if self.listening_for == "BACK":
            back_btn_text = "Press any key..."
    
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.go_back),
            Button("centered", "centered", "medium", "blue", "Toggle Fullscreen", self.toggle_full),
            Slider(300, 300, 200, "Volume", self.volume, self.set_volume),
            Slider(300, 400, 200, f"Players: {self.num_players}", (self.num_players - 1) / 7.0, self.set_players),
            Button("centered", "centered - 100", "large", "grey", back_btn_text, self.start_listening_back),
            Button("centered", "centered - 200", "medium", "blue", "Reset Keybinds", self.reset_defaults)
        ]

    def start_listening_back(self):
        self.listening_for = "BACK"
        self.refresh_ui()

    def reset_defaults(self):
        default_keys = {"BACK": pygame.K_ESCAPE}
        self.controller.keybinds = default_keys
        keybind_io.save_settings(default_keys, self.volume)
        self.refresh_ui()
        
    def additional_events(self, event):
        if self.listening_for and event.type == pygame.KEYDOWN:
            self.controller.keybinds[self.listening_for] = event.key
            keybind_io.save_settings(self.controller.keybinds, self.volume)
            self.listening_for = None
            self.refresh_ui()

    def set_players(self, val):
        self.num_players = 1 + int(val * 7)
        self.controller.num_players = self.num_players
        self.elements[3].text = f"Players: {self.num_players}" # Updates slider text

    def save_and_go_back(self):
        # Save all configs
        keybind_io.save_settings(self.controller.keybinds, self.volume, self.num_players)
        self.next_state = "MENU"
        self.done = True

    def handle_back_key(self):
        if not self.listening_for:
            self.save_and_go_back()
    
    def go_back(self):
        self.save_and_go_back()

    def toggle_full(self):
        self.fullscreen = not self.fullscreen
        pygame.display.toggle_fullscreen()

    def set_volume(self, val):
        self.volume = val
        self.controller.volume = val
        
        # Apply volume live as the slider moves
        if ui_elements.click_sound:
            ui_elements.click_sound.set_volume(val)
        if ui_elements.slider_sound:  # Fixed your missing slider sound sync!
            ui_elements.slider_sound.set_volume(val)