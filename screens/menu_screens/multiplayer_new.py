import os
import pygame
from gameState import GameState
from ui_elements import Button
import data.constants as c
from data import queries

class Multiplayer_New(GameState):
    back_state = "MULTIPLAYER_HOST"

    title = "HOST CUSTOM MAP"
    ROW_HEIGHT = 60
    ROW_TOP = 150

    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_save_path = None
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
            Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings)
        ]

        scenario_dir = c.SCENARIOS_CUSTOM_DIR
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
        scenarios = os.listdir(scenario_dir)

        for i, btn_y in self.layout_list_rows(len(scenarios), self.ROW_HEIGHT, self.ROW_TOP, pad=20):
            self.elements.append(
                Button("centered", btn_y, "large", "blue", scenarios[i],
                       lambda n=scenarios[i], d=scenario_dir: self.start_host_setup(n, d))
            )

    def scenario_settings(self):
        # Point Scenario_Settings back here, the same way New_Game claims it,
        # so its Back button returns to the host list instead of the new-game menu.
        from screens.menu_screens.scenario_settings import Scenario_Settings
        Scenario_Settings.back_state = "MULTIPLAYER_NEW"
        self.go_to("SCENARIO_SETTINGS")

    def start_host_setup(self, scenario_name, directory=c.SCENARIOS_CUSTOM_DIR):
        from tkinter import simpledialog, messagebox
        import secrets
        from data.io import multiplayer_io
        from screens.menu_screens.map import Map

        root = queries.get_transient_tk_root()

        import re
        while True:
            tour_name = simpledialog.askstring("Tournament Name", "Enter a name for this tournament:", parent=root)
            if not tour_name or not tour_name.strip(): return
            
            safe_tour_name = re.sub(r'[\\/*?:"<>|]', '', tour_name).strip()
            if not safe_tour_name:
                safe_tour_name = "Tournament"
                
            tournament_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, safe_tour_name)
            if os.path.exists(tournament_dir):
                messagebox.showerror("Error", f"Tournament with this name already exists in {c.TOURNAMENT_SAVES_DIR}")
                continue
            break
            
        master_key = simpledialog.askstring("Host Key", "Enter a Master Key for this tournament:", parent=root)
        if not master_key: return
        
        os.makedirs(tournament_dir, exist_ok=True)

        map_settings = queries.get_scenario_settings()
        
        temp_map = Map(load_path=os.path.join(directory, scenario_name), is_scenario=True, map_settings=map_settings)
        temp_map.multiplayer_host_mode = True
        temp_map.multiplayer_master_key = master_key
        temp_map.multiplayer_tournament_name = safe_tour_name
        temp_map.multiplayer_tournament_dir = tournament_dir
        
        keys_dict = {}
        for cid, data in temp_map.nation_data.items():
            if data.get("is_playable"):
                keys_dict[cid] = secrets.token_hex(4)
                
        turn = temp_map.time_manager.total_turns if hasattr(temp_map, 'time_manager') else 0
        export_path = os.path.join(tournament_dir, f"Turn_{turn}_Host.gd5tour")
        keys_path, all_keys_path = multiplayer_io.export_tournament(temp_map, export_path, master_key, keys_dict)
        
        messagebox.showinfo("Success", f"Tournament '{safe_tour_name}' created!\n\nFolder created:\n{tournament_dir}\n\nFiles saved in folder:\n- Turn_{turn}_Host.gd5tour\n- Host_Keys.txt\n- ALL_Host_Keys.txt\n\nSend the .gd5tour file and keys to your players.")

        self.go_to("MULTIPLAYER_HOST")

    def additional_events(self, event):
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.exit_screen()

        self.handle_list_scroll(event)

    def additional_draw(self, surface):
        self.draw_list_scrollbar(surface, 40, 160, c.SCREEN_HEIGHT - 200)
