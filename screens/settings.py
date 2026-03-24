import pygame
from gameState import GameState
from ui_elements import Button, Slider
from map_functions.data import keybind_io

class Settings(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        
        # 1. DEFINE VARIABLES FIRST
        self.volume = 0.5
        self.fullscreen = False
        self.listening_for = None
        
        # 2. THEN BUILD THE UI
        self.refresh_ui()

    def refresh_ui(self):
        """Rebuilds buttons to show current key names"""
        # Ensure controller exists before trying to access keybinds
        back_key_name = pygame.key.name(self.controller.keybinds["BACK"]).upper()
        
        back_btn_text = f"Back Key: {back_key_name}"
        if self.listening_for == "BACK":
            back_btn_text = "Press any key..."
    
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.go_back),
            Button("centered", "centered", "medium", "blue", "Toggle Fullscreen", self.toggle_full),
            Slider(300, 300, 200, "Volume", self.volume, self.set_volume),
            Button("centered", "centered - 100", "large", "grey", back_btn_text, self.start_listening_back),
            Button("centered", "centered - 200", "medium", "blue", "Reset Keybinds", self.reset_defaults)
        ]

    def start_listening_back(self):
        self.listening_for = "BACK"
        self.refresh_ui()

    def reset_defaults(self):
        default_keys = {"BACK": pygame.K_ESCAPE}
        self.controller.keybinds = default_keys
        keybind_io.save_keybinds(default_keys)
        self.refresh_ui()
        
    def additional_events(self, event):
        if self.listening_for and event.type == pygame.KEYDOWN:
            # Update active binds
            self.controller.keybinds[self.listening_for] = event.key
            
            # PERMANENCE: Save to file immediately
            keybind_io.save_keybinds(self.controller.keybinds)
            
            # Reset UI
            self.listening_for = None
            self.refresh_ui()

    def handle_back_key(self):
        # Don't go back if we are currently trying to record a new key
        if not self.listening_for:
            self.go_back()
    
    def go_back(self):
        self.next_state = "MENU"
        self.done = True

    def toggle_full(self):
        self.fullscreen = not self.fullscreen
        pygame.display.toggle_fullscreen()

    def set_volume(self, val):
        self.volume = val