import os
import pygame
from gameState import GameState
from ui_elements import Button
import data.constants as c
from ui.bars import ui_bars

class Multiplayer_New(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_save_path = None
        
        self.scroll_y = 0
        self.max_scroll = 0
        self.is_dragging_scrollbar = False
        self.scroll_track_rect = None
        self.scroll_handle_rect = None
        
        self.refresh_scenarios()

    def refresh_scenarios(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_to_host_menu),
            Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings)
        ]
        
        scenario_dir = c.SCENARIOS_CUSTOM_DIR
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
            
        scenarios = os.listdir(scenario_dir)
        
        # Calculate scroll boundaries
        total_content_height = len(scenarios) * 60
        self.max_scroll = min(0, (c.SCREEN_HEIGHT - 200) - total_content_height - 20)

        for i, name in enumerate(scenarios):
            btn_y = 150 + (i * 60) + self.scroll_y
            
            # Simple Y-based culling
            if not (100 < btn_y < c.SCREEN_HEIGHT - 50):
                continue

            self.elements.append(
                Button("centered", btn_y, "large", "blue", name, 
                       lambda n=name, d=scenario_dir: self.start_host_setup(n, d))
            )

    def scenario_settings(self):
        from screens.menu_screens.scenario_settings import Scenario_Settings
        Scenario_Settings.return_screen = "MULTIPLAYER_NEW"
        self.next_state = "SCENARIO_SETTINGS"
        self.done = True

    def start_host_setup(self, scenario_name, directory=c.SCENARIOS_CUSTOM_DIR):
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        import secrets
        import os
        from data.io import multiplayer_io
        from screens.menu_screens.map import Map
        
        root = tk.Tk()
        root.withdraw()
        
        master_key = simpledialog.askstring("Host Key", "Enter a Master Key for this tournament:", parent=root)
        if not master_key: return
        
        from data import queries
        map_settings = queries.get_scenario_settings()
        
        temp_map = Map(load_path=os.path.join(directory, scenario_name), is_scenario=True, map_settings=map_settings)
        temp_map.multiplayer_host_mode = True
        temp_map.multiplayer_master_key = master_key
        
        keys_dict = {}
        for cid, data in temp_map.nation_data.items():
            if data.get("is_playable"):
                keys_dict[cid] = secrets.token_hex(4)
                
        turn = temp_map.time_manager.total_turns if hasattr(temp_map, 'time_manager') else 0
        export_path = os.path.join(c.TOURNAMENT_SAVES_DIR, f"Turn_{turn}_Host.gd5tour")
        keys_path, all_keys_path = multiplayer_io.export_tournament(temp_map, export_path, master_key, keys_dict)
        
        messagebox.showinfo("Success", f"Tournament created!\nKeys saved to:\n{keys_path}\nand\n{all_keys_path}\n\nFile saved to:\n{export_path}\n\nSend the .gd5tour file and the keys to your players. When they send you their .gd5move files, use 'Load Existing Tournament' to play.")
        
        self.next_state = "MULTIPLAYER_HOST"
        self.done = True

    def scenario_settings(self):
        self.next_state = "SCENARIO_SETTINGS"
        self.done = True
        
    def exit_to_host_menu(self):
        self.next_state = "MULTIPLAYER_HOST"
        self.done = True

    def additional_events(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.exit_to_host_menu()
            
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_y = max(self.max_scroll, min(0, self.scroll_y + event.y * c.SCROLL_SPEED))
            self.refresh_scenarios()
            
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                if self.scroll_handle_rect and self.scroll_handle_rect.collidepoint(event.pos):
                    self.is_dragging_scrollbar = True
                elif self.scroll_track_rect and self.scroll_track_rect.collidepoint(event.pos):
                    self._snap_scroll(event.pos[1])

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.is_dragging_scrollbar = False

        elif event.type == pygame.MOUSEMOTION and self.is_dragging_scrollbar:
            self._snap_scroll(event.pos[1])

    def _snap_scroll(self, mouse_y):
        track_y = self.scroll_track_rect.top
        track_h = self.scroll_track_rect.height
        rel_y = max(0, min(track_h, mouse_y - track_y))
        
        scroll_fraction = rel_y / track_h
        self.scroll_y = int(self.max_scroll * scroll_fraction)
        self.refresh_scenarios()

    def draw(self, surface):
        surface.fill(self.bg_color)
        ui_bars.draw_centered_title(surface, "HOST CUSTOM MAP", 40)

        # Draw Scrollbar
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, self.scroll_y, self.max_scroll, 40, 160, c.SCREEN_HEIGHT - 200
        )
        
        super().draw(surface)
