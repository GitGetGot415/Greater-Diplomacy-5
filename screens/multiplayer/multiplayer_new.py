import secrets
import re

import os
from ui.navigation.screen import MenuListScreen
from ui.widgets.ui_elements import Button, make_back_button
import data.constants as c
from data import queries

from data.multiplayer.tournament import files as tournament_files
from screens.setup.scenario_settings import Scenario_Settings
from screens.game.map import Map
from ui import dialogs
from ui.dialogs import file_exchange
from ui.navigation import screen_runner
from data.platform import LoadingSteps
class Multiplayer_New(MenuListScreen):
    back_state = "MULTIPLAYER_HOST"

    title = "HOST CUSTOM MAP"

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

        self.add_menu_list([(name, name) for name in scenarios],
                           lambda name, d=scenario_dir: self.start_host_setup(name, d))

    def scenario_settings(self):
        # Point Scenario_Settings back here, the same way New_Game claims it,
        # so its Back button returns to the host list instead of the new-game menu.
        Scenario_Settings.back_state = "MULTIPLAYER_NEW"
        self.go_to("SCENARIO_SETTINGS")

    def start_host_setup(self, scenario_name, directory=c.SCENARIOS_CUSTOM_DIR):

        def ask_tour_name():
            def on_name(tour_name):
                if not tour_name or not tour_name.strip():
                    return

                safe_tour_name = re.sub(r'[\\/*?:"<>|]', '', tour_name).strip()
                if not safe_tour_name:
                    safe_tour_name = "Tournament"

                tournament_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, safe_tour_name)
                file_exchange.choose_save_destination(
                    tournament_dir, lambda path, _overwrite: ask_master_key(safe_tour_name, path),
                    game_state=self, title="Save Tournament", directory=True)

            dialogs.ask_string("Tournament Name", "Enter a name for this tournament:", on_name)

        def ask_master_key(safe_tour_name, tournament_dir):
            def on_key(master_key):
                if not master_key:
                    return

                if tournament_files.is_reserved_tournament_key(master_key):
                    dialogs.show_error(
                        "Reserved Key",
                        "'Spectator' is reserved for tournament spectator access. Choose a different Master Key.")
                    ask_master_key(safe_tour_name, tournament_dir)
                    return

                os.makedirs(tournament_dir, exist_ok=True)

                map_settings = queries.get_scenario_settings()

                def create_tournament():
                    temp_map = yield from Map.loading_steps(
                        load_path=os.path.join(directory, scenario_name),
                        is_scenario=True, map_settings=map_settings)
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
                    yield "Saving Tournament..."
                    keys_path, all_keys_path = tournament_files.export_tournament(temp_map, export_path, master_key, keys_dict)
                    return turn

                def created(turn):
                    dialogs.show_success("Success", f"Tournament '{safe_tour_name}' created!\n\nFolder created:\n{tournament_dir}\n\nFiles saved in folder:\n- Turn_{turn}_Host.gd5tour\n- Host_Keys.txt\n- ALL_Host_Keys.txt\n\nSend the .gd5tour file and keys to your players.")
                    self.go_to("MULTIPLAYER_HOST")

                total = Map.loading_step_count(load_path=os.path.join(directory, scenario_name)) + 1
                screen_runner.run_loading(
                    LoadingSteps(create_tournament(), total), "Creating Tournament...", on_done=created)

            dialogs.ask_string("Host Key", "Enter a Master Key for this tournament:", on_key)

        ask_tour_name()
