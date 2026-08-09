import os
import pygame
from gameState import GameState
from ui_elements import Button, make_back_button
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
            make_back_button(self.exit_screen),
            Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings)
        ]

        scenario_dir = c.SCENARIOS_CUSTOM_DIR
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
        scenarios = os.listdir(scenario_dir)

        self.scroll_content_rect = pygame.Rect(0, 100, c.SCREEN_WIDTH, (c.SCREEN_HEIGHT - 50) - 100)
        for i, btn_y in self.layout_list_rows(len(scenarios), self.ROW_HEIGHT, self.ROW_TOP, pad=20):
            btn = Button("centered", btn_y, "large", "blue", scenarios[i],
                        lambda n=scenarios[i], d=scenario_dir: self.start_host_setup(n, d))
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

    def scenario_settings(self):
        # Point Scenario_Settings back here, the same way New_Game claims it,
        # so its Back button returns to the host list instead of the new-game menu.
        from screens.menu_screens.scenario_settings import Scenario_Settings
        Scenario_Settings.back_state = "MULTIPLAYER_NEW"
        self.go_to("SCENARIO_SETTINGS")

    def start_host_setup(self, scenario_name, directory=c.SCENARIOS_CUSTOM_DIR):
        import secrets
        from data.io import multiplayer_io
        from screens.menu_screens.map import Map
        from ui import confirm_dialog
        import re

        def ask_tour_name():
            def on_name(tour_name):
                if not tour_name or not tour_name.strip():
                    return

                safe_tour_name = re.sub(r'[\\/*?:"<>|]', '', tour_name).strip()
                if not safe_tour_name:
                    safe_tour_name = "Tournament"

                tournament_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, safe_tour_name)
                if os.path.exists(tournament_dir):
                    confirm_dialog.show_error("Error", f"Tournament with this name already exists in {c.TOURNAMENT_SAVES_DIR}")
                    ask_tour_name()
                    return

                ask_master_key(safe_tour_name, tournament_dir)

            confirm_dialog.ask_string("Tournament Name", "Enter a name for this tournament:", on_name)

        def ask_master_key(safe_tour_name, tournament_dir):
            def on_key(master_key):
                if not master_key:
                    return

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

                confirm_dialog.show_success("Success", f"Tournament '{safe_tour_name}' created!\n\nFolder created:\n{tournament_dir}\n\nFiles saved in folder:\n- Turn_{turn}_Host.gd5tour\n- Host_Keys.txt\n- ALL_Host_Keys.txt\n\nSend the .gd5tour file and keys to your players.")

                self.go_to("MULTIPLAYER_HOST")

            confirm_dialog.ask_string("Host Key", "Enter a Master Key for this tournament:", on_key)

        ask_tour_name()

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def additional_draw(self, surface):
        self.draw_list_scrollbar(surface, 40, 160, c.SCREEN_HEIGHT - 200)
