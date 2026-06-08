import pygame
import ui_elements
from gameState import GameState
from data.io import keybind_io
import data.constants as c
from ui import buttons
from data import queries
from map_logic.rendering.font_manager import fonts

class Settings(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self.bg_image_path = c.SETTINGS_BG_FILE 
        self.return_state = "MENU"
        
        self.sfx_volume = self.controller.sfx_volume
        self.num_players = getattr(self.controller, 'num_players', 1)
        self.ai_mode = getattr(self.controller, 'ai_mode', 'GEMINI')
        self.ai_immersion_level = getattr(self.controller, 'ai_immersion_level', 'LITE')
        self.ai_modes = ["OFF", "GEMINI", "OLLAMA", "CHATGPT", "CLAUDE"]
        
        self.last_ai_mode = self.ai_mode if self.ai_mode != "OFF" else c.DEFAULT_AI_MODE
        
        self.fullscreen = False
        self.listening_for = None

        # Dynamically load all 8 string fields from the controller
        self.gemini_api_key_text = getattr(self.controller, 'gemini_api_key', '')
        self.gemini_model_text = getattr(self.controller, 'gemini_model', 'gemini-2.5-flash')

        # Load dynamic mouse button config from controller, fallback to constants configuration setting
        self.drag_mouse_button_toggle = getattr(self.controller, 'drag_mouse_button_toggle', c.DRAG_MOUSE_BUTTON_TOGGLE)

        self.ollama_api_key_text = getattr(self.controller, 'ollama_api_key', '')
        self.ollama_model_text = getattr(self.controller, 'ollama_model', 'llama3')

        self.chatgpt_api_key_text = getattr(self.controller, 'chatgpt_api_key', '')
        self.chatgpt_model_text = getattr(self.controller, 'chatgpt_model', 'gpt-4o-mini')

        self.claude_api_key_text = getattr(self.controller, 'claude_api_key', '')
        self.claude_model_text = getattr(self.controller, 'claude_model', 'claude-3-haiku-20240307')

        self.active_input = None # Dynamically track which box is selected: "{MODE}_KEY" or "{MODE}_MOD"

        self.ai_threads = getattr(self.controller, 'ai_threads', c.DEFAULT_AI_THREADS)
        self.show_fps = getattr(self.controller, 'show_fps', c.SHOW_FPS)
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
        mode = self.ai_mode.lower()
        if box_type == "KEY":
            setattr(self, f"{mode}_api_key_text", "")
            setattr(self.controller, f"{mode}_api_key", "")
        elif box_type == "MOD":
            setattr(self, f"{mode}_model_text", "")
            setattr(self.controller, f"{mode}_model", "")
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
        default_keys = {"BACK": pygame.K_ESCAPE, "ORDERS": pygame.K_q}
        self.controller.keybinds = default_keys
        self.controller.target_fps = getattr(c, 'TARGET_FPS', 60)
        
        self.controller.ai_threads = getattr(c, 'DEFAULT_AI_THREADS', 1)
        self.ai_threads = self.controller.ai_threads
        
        self.controller.num_players = 1
        self.num_players = self.controller.num_players

        self.drag_mouse_button_toggle = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        c.DRAG_MOUSE_BUTTON_TOGGLE = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        self.controller.drag_mouse_button_toggle = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        
        queries.save_global_settings(self.controller)
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

        # Handle dynamic text entry mapping
        elif self.active_input and self.ai_mode != "OFF":
            mode = self.ai_mode.lower()
            if self.active_input.endswith("_KEY"):
                current_text = getattr(self, f"{mode}_api_key_text")
                new_text, status = ui_elements.process_text_input(event, current_text, max_length=200)
                setattr(self, f"{mode}_api_key_text", new_text)
                setattr(self.controller, f"{mode}_api_key", new_text.strip())
            elif self.active_input.endswith("_MOD"):
                current_text = getattr(self, f"{mode}_model_text")
                new_text, status = ui_elements.process_text_input(event, current_text, max_length=150)
                setattr(self, f"{mode}_model_text", new_text)
                setattr(self.controller, f"{mode}_model", new_text.strip())

    def additional_draw(self, surface):
        font = fonts.get("normal")
        
        if self.ai_mode in ["GEMINI", "CHATGPT", "CLAUDE", "OLLAMA"]:
            mode_prefix = self.ai_mode.lower()
            key_text_var = getattr(self, f"{mode_prefix}_api_key_text")
            mod_text_var = getattr(self, f"{mode_prefix}_model_text")

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
        self.fullscreen = not self.fullscreen
        pygame.display.toggle_fullscreen()

    def set_volume(self, val):
        self.sfx_volume = val
        self.controller.sfx_volume = val
        ui_elements.global_sfx_volume = val
        
        if not c.USE_SOLOUD:
            if getattr(ui_elements, 'pygame_click_sound', None):
                ui_elements.pygame_click_sound.set_volume(val)
            if getattr(ui_elements, 'pygame_slider_sound', None):
                ui_elements.pygame_slider_sound.set_volume(val)