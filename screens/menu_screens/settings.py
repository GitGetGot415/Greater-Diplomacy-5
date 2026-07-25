import pygame
import ui_elements
from gameState import GameState
from data.io import keybind_io
import data.constants as c
from ui import buttons
from data import queries
from map_logic.rendering.font_manager import fonts
import tkinter as tk
from tkinter import filedialog
from tkinter import colorchooser

class Settings(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self.bg_image_path = c.SETTINGS_BG_FILE 
        self.return_state = "MENU"
        
        self.sfx_volume = self.controller.sfx_volume
        self.num_players = self.controller.num_players
        self.ai_mode = self.controller.ai_mode
        self.ai_immersion_level = self.controller.ai_immersion_level
        self.ai_modes = ["OFF", "GEMINI", "OLLAMA", "CHATGPT", "CLAUDE"]
        
        self.last_ai_mode = self.ai_mode if self.ai_mode != "OFF" else c.DEFAULT_AI_MODE
        
        self.fullscreen = False
        self.listening_for = None

        # Dynamically load all 8 string fields from the controller
        self.gemini_api_key_text = self.controller.gemini_api_key
        self.gemini_model_text = self.controller.gemini_model

        # Load dynamic mouse button config from controller, fallback to constants configuration setting
        self.drag_mouse_button_toggle = self.controller.drag_mouse_button_toggle

        self.ollama_api_key_text = self.controller.ollama_api_key
        self.ollama_model_text = self.controller.ollama_model

        self.chatgpt_api_key_text = self.controller.chatgpt_api_key
        self.chatgpt_model_text = self.controller.chatgpt_model

        self.claude_api_key_text = self.controller.claude_api_key
        self.claude_model_text = self.controller.claude_model

        self.active_input = None # Dynamically track which box is selected: "{MODE}_KEY" or "{MODE}_MOD"

        self.ai_threads = self.controller.ai_threads
        self.show_fps = self.controller.show_fps
        
        self.saves_dir = self.controller.saves_dir
        self.custom_scenarios_dir = self.controller.custom_scenarios_dir
        
        self.ocean_light_color = self.controller.ocean_light_color
        self.ocean_dark_color = self.controller.ocean_dark_color
        
        self.tournament_saves_dir = self.controller.tournament_saves_dir
        
        self.refresh_ui()

    def toggle_fps(self):
        self.show_fps = not self.show_fps
        self.controller.show_fps = self.show_fps
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def toggle_drag_button(self):
        """Cycles the dynamic mouse button configuration toggle value string."""
        options = ["RIGHT", "LEFT", "BOTH"]
        current_idx = options.index(self.drag_mouse_button_toggle)
        next_idx = (current_idx + 1) % len(options)
        
        self.drag_mouse_button_toggle = options[next_idx]
        
        # Inject the modification to the global fallback configuration value AND controller
        c.DRAG_MOUSE_BUTTON_TOGGLE = self.drag_mouse_button_toggle
        self.controller.drag_mouse_button_toggle = self.drag_mouse_button_toggle
        
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def set_ai_threads(self, val):
        # Scale 0.0-1.0 to 1-8
        threads = 1 + int(val * 7)
        self.ai_threads = threads
        self.controller.ai_threads = threads
        if hasattr(self, 'ai_thread_slider'):
            self.ai_thread_slider.text = f"Maximum AI Threads: {threads}"
        # Silently save whenever the slider moves
        queries.save_global_settings(self.controller)

    def update(self):
        super().update()
        if hasattr(self, 'player_slider'):
            self.player_slider.visible = (self.return_state != "MAP")

    def set_ai_mode(self, mode):
        self.ai_mode = mode
        self.controller.ai_mode = mode
        self.active_input = None # Deselect input box when switching modes
        self.refresh_ui()

    def set_ai_immersion_level(self, level):
        self.ai_immersion_level = level
        self.controller.ai_immersion_level = level
        self.refresh_ui()

    def clear_input(self, box_type):
        """Generic method to clear the currently visible input box."""
        if box_type == "KEY":
            # Map the active AI mode directly to its controller attribute
            # This takes more lines but is safer in case it gets changed
            if self.ai_mode == "GEMINI": self.gemini_api_key_text = self.controller.gemini_api_key = ""
            elif self.ai_mode == "OLLAMA": self.ollama_api_key_text = self.controller.ollama_api_key = ""
            elif self.ai_mode == "CHATGPT": self.chatgpt_api_key_text = self.controller.chatgpt_api_key = ""
            elif self.ai_mode == "CLAUDE": self.claude_api_key_text = self.controller.claude_api_key = ""
        elif box_type == "MOD":
            if self.ai_mode == "GEMINI": self.gemini_model_text = self.controller.gemini_model = ""
            elif self.ai_mode == "OLLAMA": self.ollama_model_text = self.controller.ollama_model = ""
            elif self.ai_mode == "CHATGPT": self.chatgpt_model_text = self.controller.chatgpt_model = ""
            elif self.ai_mode == "CLAUDE": self.claude_model_text = self.controller.claude_model = ""
            
        self.active_input = None
        self.refresh_ui()

    def refresh_ui(self):
        buttons.render_settings_buttons(self)

    def toggle_ai_enabled(self):
        if self.ai_mode == "OFF":
            self.set_ai_mode(self.last_ai_mode)
        else:
            self.last_ai_mode = self.ai_mode
            self.set_ai_mode("OFF")

    def start_listening(self, action):
        self.listening_for = action
        self.refresh_ui()

    def reset_defaults(self):
        default_keys = {"BACK": pygame.K_ESCAPE, "ORDERS": pygame.K_q, "FULLSCREEN": pygame.K_F11}
        self.controller.keybinds = default_keys
        self.controller.target_fps = c.TARGET_FPS
        
        self.controller.ai_threads = c.DEFAULT_AI_THREADS
        self.ai_threads = self.controller.ai_threads
        
        self.controller.num_players = 1
        self.num_players = self.controller.num_players

        self.drag_mouse_button_toggle = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        c.DRAG_MOUSE_BUTTON_TOGGLE = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        self.controller.drag_mouse_button_toggle = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        
        self.reset_ocean_light_color(refresh=False)
        self.reset_ocean_dark_color(refresh=False)
        
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def edit_saves_dir(self):
        root = tk.Tk()
        root.withdraw()
        folder_selected = filedialog.askdirectory(initialdir=self.saves_dir, title="Select Saves Directory")
        if folder_selected:
            self.saves_dir = folder_selected
            self.controller.saves_dir = folder_selected
            c.SAVES_DIR = folder_selected
            queries.save_global_settings(self.controller)
            self.refresh_ui()

    def edit_tournament_saves_dir(self):
        root = tk.Tk()
        root.withdraw()
        folder_selected = filedialog.askdirectory(initialdir=self.tournament_saves_dir, title="Select Tournament Saves Directory")
        if folder_selected:
            self.tournament_saves_dir = folder_selected
            self.controller.tournament_saves_dir = folder_selected
            c.TOURNAMENT_SAVES_DIR = folder_selected
            queries.save_global_settings(self.controller)
            self.refresh_ui()

    def edit_custom_scenarios_dir(self):
        root = tk.Tk()
        root.withdraw()
        folder_selected = filedialog.askdirectory(initialdir=self.custom_scenarios_dir, title="Select Custom Scenarios Directory")
        if folder_selected:
            self.custom_scenarios_dir = folder_selected
            self.controller.custom_scenarios_dir = folder_selected
            c.SCENARIOS_CUSTOM_DIR = folder_selected
            queries.save_global_settings(self.controller)
            self.refresh_ui()

    def reset_saves_dir(self):
        self.saves_dir = "saves"
        self.controller.saves_dir = "saves"
        c.SAVES_DIR = "saves"
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def reset_tournament_saves_dir(self):
        self.tournament_saves_dir = "tournament_saves"
        self.controller.tournament_saves_dir = "tournament_saves"
        c.TOURNAMENT_SAVES_DIR = "tournament_saves"
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def reset_custom_scenarios_dir(self):
        self.custom_scenarios_dir = "scenarios/map_editor"
        self.controller.custom_scenarios_dir = "scenarios/map_editor"
        c.SCENARIOS_CUSTOM_DIR = "scenarios/map_editor"
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def edit_ocean_light_color(self):
        root = tk.Tk()
        root.withdraw()
        color = colorchooser.askcolor(title="Select Zoom-In Water Color", color=self.ocean_light_color)
        if color[0]:
            self.ocean_light_color = tuple(map(int, color[0]))
            self.controller.ocean_light_color = self.ocean_light_color
            c.OCEAN_LIGHT_BLUE = self.ocean_light_color
            queries.save_global_settings(self.controller)
            self.refresh_ui()

    def edit_ocean_dark_color(self):
        root = tk.Tk()
        root.withdraw()
        color = colorchooser.askcolor(title="Select Zoom-Out Water Color", color=self.ocean_dark_color)
        if color[0]:
            self.ocean_dark_color = tuple(map(int, color[0]))
            self.controller.ocean_dark_color = self.ocean_dark_color
            c.OCEAN_DARK_BLUE = self.ocean_dark_color
            queries.save_global_settings(self.controller)
            self.refresh_ui()

    def reset_ocean_light_color(self, refresh=True):
        self.ocean_light_color = c.DEFAULT_OCEAN_LIGHT_BLUE
        self.controller.ocean_light_color = self.ocean_light_color
        c.OCEAN_LIGHT_BLUE = self.ocean_light_color
        queries.save_global_settings(self.controller)
        if refresh:
            self.refresh_ui()

    def reset_ocean_dark_color(self, refresh=True):
        self.ocean_dark_color = c.DEFAULT_OCEAN_DARK_BLUE
        self.controller.ocean_dark_color = self.ocean_dark_color
        c.OCEAN_DARK_BLUE = self.ocean_dark_color
        queries.save_global_settings(self.controller)
        if refresh:
            self.refresh_ui()

    def set_fps(self, val):
        fps = int(20 + (val * 40)) # Scale 0.0-1.0 to 20-60
        self.controller.target_fps = fps
        if hasattr(self, 'fps_slider'):
            self.fps_slider.text = f"Max FPS: {fps}"

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                
                # Check for Input Box Selection Dynamically
                if self.ai_mode != "OFF":
                    key_rect = pygame.Rect(c.SETTINGS_BOX_X, c.SETTINGS_KEY_BOX_Y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
                    mod_rect = pygame.Rect(c.SETTINGS_BOX_X, c.SETTINGS_MOD_BOX_Y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
                    
                    if key_rect.collidepoint(mx, my):
                        self.active_input = f"{self.ai_mode}_KEY"
                    elif mod_rect.collidepoint(mx, my):
                        self.active_input = f"{self.ai_mode}_MOD"
                    else:
                        self.active_input = None

            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        if self.listening_for and event.type == pygame.KEYDOWN:
            self.controller.keybinds[self.listening_for] = event.key
            self.save_and_go_back(execute_exit=False) # Silently save
            self.listening_for = None
            self.refresh_ui()

        # Handle explicit text entry mapping (No getattr/setattr!)
        elif self.active_input and self.ai_mode != "OFF":
            
            if self.active_input.endswith("_KEY"):
                # Fetch the current text based on mode
                current_text = ""
                if self.ai_mode == "GEMINI": current_text = self.gemini_api_key_text
                elif self.ai_mode == "OLLAMA": current_text = self.ollama_api_key_text
                elif self.ai_mode == "CHATGPT": current_text = self.chatgpt_api_key_text
                elif self.ai_mode == "CLAUDE": current_text = self.claude_api_key_text

                new_text, status = ui_elements.process_text_input(event, current_text, max_length=c.MAX_API_KEY_LENGTH)
                clean_text = new_text.strip()

                # Save the new text back to the screen state and controller
                if self.ai_mode == "GEMINI": 
                    self.gemini_api_key_text = new_text
                    self.controller.gemini_api_key = clean_text
                elif self.ai_mode == "OLLAMA": 
                    self.ollama_api_key_text = new_text
                    self.controller.ollama_api_key = clean_text
                elif self.ai_mode == "CHATGPT": 
                    self.chatgpt_api_key_text = new_text
                    self.controller.chatgpt_api_key = clean_text
                elif self.ai_mode == "CLAUDE": 
                    self.claude_api_key_text = new_text
                    self.controller.claude_api_key = clean_text

            elif self.active_input.endswith("_MOD"):
                # Fetch the current text based on mode
                current_text = ""
                if self.ai_mode == "GEMINI": current_text = self.gemini_model_text
                elif self.ai_mode == "OLLAMA": current_text = self.ollama_model_text
                elif self.ai_mode == "CHATGPT": current_text = self.chatgpt_model_text
                elif self.ai_mode == "CLAUDE": current_text = self.claude_model_text

                new_text, status = ui_elements.process_text_input(event, current_text, max_length=c.MAX_MODEL_NAME_LENGTH)
                clean_text = new_text.strip()

                # Save the new text back to the screen state and controller
                if self.ai_mode == "GEMINI": 
                    self.gemini_model_text = new_text
                    self.controller.gemini_model = clean_text
                elif self.ai_mode == "OLLAMA": 
                    self.ollama_model_text = new_text
                    self.controller.ollama_model = clean_text
                elif self.ai_mode == "CHATGPT": 
                    self.chatgpt_model_text = new_text
                    self.controller.chatgpt_model = clean_text
                elif self.ai_mode == "CLAUDE": 
                    self.claude_model_text = new_text
                    self.controller.claude_model = clean_text

    def additional_draw(self, surface):
        font = fonts.get("normal")

        # --- DRAW DIRECTORY TEXTBOXES (Middle Top) ---
        dir_box_w = 400
        dir_box_h = 35
        dir_box_x = c.SCREEN_WIDTH // 2 - dir_box_w // 2 + 50
        
        # Saves Dir Box
        saves_y = 60
        surface.blit(font.render("Saves Path:", True, (100, 100, 100)), (dir_box_x, saves_y - 20))
        saves_rect = pygame.Rect(dir_box_x, saves_y, dir_box_w, dir_box_h)
        pygame.draw.rect(surface, (20, 20, 30), saves_rect)
        pygame.draw.rect(surface, (150, 150, 150), saves_rect, 1)
        surface.set_clip(saves_rect.inflate(-10, -10))
        surface.blit(font.render(self.saves_dir, True, (255, 255, 255)), (saves_rect.x + 5, saves_rect.y + 10))
        surface.set_clip(None)

        # Scenarios Dir Box
        scen_y = 120
        surface.blit(font.render("Custom Maps Path:", True, (100, 100, 100)), (dir_box_x, scen_y - 20))
        scen_rect = pygame.Rect(dir_box_x, scen_y, dir_box_w, dir_box_h)
        pygame.draw.rect(surface, (20, 20, 30), scen_rect)
        pygame.draw.rect(surface, (150, 150, 150), scen_rect, 1)
        surface.set_clip(scen_rect.inflate(-10, -10))
        surface.blit(font.render(self.custom_scenarios_dir, True, (255, 255, 255)), (scen_rect.x + 5, scen_rect.y + 10))
        surface.set_clip(None)

        # Draw current water colors
        color_box_w = 40
        color_box_h = 35
        
        # Light Water Color
        light_color_y = 175
        surface.blit(font.render("Zoom-In Water Color:", True, (100, 100, 100)), (dir_box_x, light_color_y + 10))
        light_rect = pygame.Rect(dir_box_x + dir_box_w - color_box_w, light_color_y, color_box_w, color_box_h)
        pygame.draw.rect(surface, self.ocean_light_color, light_rect)
        pygame.draw.rect(surface, (150, 150, 150), light_rect, 1)

        # Dark Water Color
        dark_color_y = 230
        surface.blit(font.render("Zoom-Out Water Color:", True, (100, 100, 100)), (dir_box_x, dark_color_y + 10))
        dark_rect = pygame.Rect(dir_box_x + dir_box_w - color_box_w, dark_color_y, color_box_w, color_box_h)
        pygame.draw.rect(surface, self.ocean_dark_color, dark_rect)
        pygame.draw.rect(surface, (150, 150, 150), dark_rect, 1)

        # Tournament Saves Box
        mp_saves_y = 285
        surface.blit(font.render("Tournament Saves Path:", True, (100, 100, 100)), (dir_box_x, mp_saves_y - 20))
        mp_saves_rect = pygame.Rect(dir_box_x, mp_saves_y, dir_box_w, dir_box_h)
        pygame.draw.rect(surface, (20, 20, 30), mp_saves_rect)
        pygame.draw.rect(surface, (150, 150, 150), mp_saves_rect, 1)
        surface.set_clip(mp_saves_rect.inflate(-10, -10))
        surface.blit(font.render(self.tournament_saves_dir, True, (255, 255, 255)), (mp_saves_rect.x + 5, mp_saves_rect.y + 10))
        surface.set_clip(None)
        
        if self.ai_mode in ["GEMINI", "CHATGPT", "CLAUDE", "OLLAMA"]:
            if self.ai_mode == "GEMINI":
                key_text_var = self.gemini_api_key_text
                mod_text_var = self.gemini_model_text
            elif self.ai_mode == "OLLAMA":
                key_text_var = self.ollama_api_key_text
                mod_text_var = self.ollama_model_text
            elif self.ai_mode == "CHATGPT":
                key_text_var = self.chatgpt_api_key_text
                mod_text_var = self.chatgpt_model_text
            elif self.ai_mode == "CLAUDE":
                key_text_var = self.claude_api_key_text
                mod_text_var = self.claude_model_text

            # --- TOP BOX: API KEY / URL ---
            label_top = "Ollama Base URL (blank = localhost):" if self.ai_mode == "OLLAMA" else f"Paste {self.ai_mode.capitalize()} API Key:"
            surface.blit(font.render(label_top, True, (200, 200, 200)), (c.SETTINGS_BOX_X, c.SETTINGS_KEY_BOX_Y - 25))

            key_rect = pygame.Rect(c.SETTINGS_BOX_X, c.SETTINGS_KEY_BOX_Y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
            is_key_active = (self.active_input == f"{self.ai_mode}_KEY")
            pygame.draw.rect(surface, (60, 60, 80) if is_key_active else (20, 20, 30), key_rect)
            pygame.draw.rect(surface, (150, 150, 150), key_rect, 1)

            display_key = key_text_var + ("|" if is_key_active else "")
            surface.set_clip(key_rect.inflate(-10, -10))
            surface.blit(font.render(display_key, True, (255, 255, 255)), (key_rect.x + 5, key_rect.y + 10))
            surface.set_clip(None)

            # --- BOTTOM BOX: MODEL ---
            label_bot = f"{self.ai_mode.capitalize()} Model Name:"
            surface.blit(font.render(label_bot, True, (200, 200, 200)), (c.SETTINGS_BOX_X, c.SETTINGS_MOD_BOX_Y - 25))

            mod_rect = pygame.Rect(c.SETTINGS_BOX_X, c.SETTINGS_MOD_BOX_Y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
            is_mod_active = (self.active_input == f"{self.ai_mode}_MOD")
            pygame.draw.rect(surface, (60, 60, 80) if is_mod_active else (20, 20, 30), mod_rect)
            pygame.draw.rect(surface, (150, 150, 150), mod_rect, 1)

            display_mod = mod_text_var + ("|" if is_mod_active else "")
            surface.set_clip(mod_rect.inflate(-10, -10))
            surface.blit(font.render(display_mod, True, (255, 255, 255)), (mod_rect.x + 5, mod_rect.y + 10))
            surface.set_clip(None)

    def set_players(self, val):
        self.num_players = 1 + int(val * 7)
        self.controller.num_players = self.num_players
        if hasattr(self, 'player_slider'):
            self.player_slider.text = f"Players: {self.num_players}"

    def save_and_go_back(self, execute_exit=True):
        queries.save_global_settings(self.controller)
        
        if execute_exit:
            self.next_state = getattr(self, 'return_state', 'MENU')
            self.done = True

    def handle_back_key(self):
        if not self.listening_for:
            self.save_and_go_back()
    
    def go_back(self):
        self.save_and_go_back()

    def toggle_full(self):
        self.controller.toggle_fullscreen()
        self.fullscreen = getattr(self.controller, 'is_fullscreen', False)

    def set_volume(self, val):
        self.sfx_volume = val
        self.controller.sfx_volume = val
        ui_elements.global_sfx_volume = val
        
        if not c.USE_SOLOUD:
            if getattr(ui_elements, 'pygame_click_sound', None):
                ui_elements.pygame_click_sound.set_volume(val)
            if getattr(ui_elements, 'pygame_slider_sound', None):
                ui_elements.pygame_slider_sound.set_volume(val)