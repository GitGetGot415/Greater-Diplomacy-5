import pygame
import ui_elements
from gameState import GameState
from ui_elements import Button, Slider
from data.io import keybind_io
import tkinter as tk
from tkinter import simpledialog

class Settings(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        
        self.volume = self.controller.volume 
        self.num_players = getattr(self.controller, 'num_players', 1)
        self.ai_mode = getattr(self.controller, 'ai_mode', 'GEMINI')
        self.ai_modes = ["OFF", "GEMINI", "OLLAMA"]
        
        self.fullscreen = False
        self.listening_for = None

        self.refresh_ui()


    def set_ai_mode(self, mode):
        self.ai_mode = mode
        self.controller.ai_mode = mode
        
        # Open a text prompt if Gemini is selected
        if mode == "GEMINI":
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            new_key = simpledialog.askstring("API Key", "Paste your custom Gemini API Key\n(Leave blank to keep current):")
            if new_key:
                self.controller.api_key = new_key
            root.destroy()
            pygame.event.pump() # Clear ghost clicks

        self.refresh_ui()

    def refresh_ui(self):
        back_key_name = pygame.key.name(self.controller.keybinds.get("BACK", pygame.K_ESCAPE)).upper()
        back_btn_text = f"Back Key: {back_key_name}"
        if self.listening_for == "BACK":
            back_btn_text = "Press any key..."

        orders_key_name = pygame.key.name(self.controller.keybinds.get("ORDERS", pygame.K_q)).upper()
        orders_btn_text = f"Orders Key: {orders_key_name}"
        if self.listening_for == "ORDERS":
            orders_btn_text = "Press any key..."
    
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.go_back),
            Button("centered", 100, "medium", "blue", "Toggle Fullscreen", self.toggle_full),
        ]
        
        # --- NEW VERTICAL AI BUTTONS ---
        c_off = "green" if self.ai_mode == "OFF" else "grey"
        self.elements.append(Button("centered", 180, "medium", c_off, "AI: OFF", lambda: self.set_ai_mode("OFF")))
        
        c_gem = "green" if self.ai_mode == "GEMINI" else "grey"
        self.elements.append(Button("centered", 240, "medium", c_gem, "AI: GEMINI", lambda: self.set_ai_mode("GEMINI")))
        
        c_oll = "green" if self.ai_mode == "OLLAMA" else "grey"
        self.elements.append(Button("centered", 300, "medium", c_oll, "AI: OLLAMA", lambda: self.set_ai_mode("OLLAMA")))

        # Adjust the Y positions of the remaining elements slightly lower
        self.elements.extend([
            Slider(300, 420, 200, "Volume", self.volume, self.set_volume),
            Slider(300, 500, 200, f"Players: {self.num_players}", (self.num_players - 1) / 7.0, self.set_players),
            Button("centered", 580, "large", "grey", back_btn_text, lambda: self.start_listening("BACK")),
            Button("centered", 670, "large", "grey", orders_btn_text, lambda: self.start_listening("ORDERS")),
            Button("centered", 760, "medium", "blue", "Reset Keybinds", self.reset_defaults)
        ])

    def toggle_ai(self):
        idx = self.ai_modes.index(self.ai_mode)
        self.ai_mode = self.ai_modes[(idx + 1) % len(self.ai_modes)]
        self.controller.ai_mode = self.ai_mode
        self.refresh_ui()

    def start_listening(self, action):
        self.listening_for = action
        self.refresh_ui()

    def reset_defaults(self):
        default_keys = {"BACK": pygame.K_ESCAPE, "ORDERS": pygame.K_q}
        self.controller.keybinds = default_keys
        # Safely fetch api_key to ensure we don't accidentally wipe it during a reset
        api_key = getattr(self.controller, 'api_key', '')
        keybind_io.save_settings(default_keys, self.volume, self.num_players, self.ai_mode, api_key)
        self.refresh_ui()
        
    def additional_events(self, event):
        if self.listening_for and event.type == pygame.KEYDOWN:
            self.controller.keybinds[self.listening_for] = event.key
            keybind_io.save_settings(self.controller.keybinds, self.volume, self.num_players, self.ai_mode)
            self.listening_for = None
            self.refresh_ui()

    def set_players(self, val):
        self.num_players = 1 + int(val * 7)
        self.controller.num_players = self.num_players
        self.elements[4].text = f"Players: {self.num_players}"

    def save_and_go_back(self):
        # Ensure we pass the api_key when saving
        api_key_to_save = getattr(self.controller, 'api_key', '')
        keybind_io.save_settings(self.controller.keybinds, self.volume, self.num_players, self.ai_mode, api_key_to_save)
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
        if ui_elements.slider_sound:
            ui_elements.slider_sound.set_volume(val)