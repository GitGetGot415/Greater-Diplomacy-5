import os
from ui import dialogs
from ui.dialogs import pickers
from ui.dialogs import file_exchange
from data.map import history_io
from ui.widgets.content_browser import ContentBrowserScreen
from screens.game import map_launch
from ui.widgets.ui_elements import Button, make_back_button
from ui.sound_effects import play_ui_sound
from ui.navigation import screen_runner
from data.platform import IS_WEB, LoadingSteps
from data.io import standalone_game
import data.constants as c

from data.map.load_map import newer_version_message


class Load_Game(ContentBrowserScreen):
    back_state = "MENU"
    title = "LOAD GAME"
    content_label = "saves"

    def __init__(self):
        super().__init__()
        self.bg_color = (50, 0, 50)
        self.refresh_ui()

    def on_enter(self, app, previous):
        # Refresh on entry. Frame updates use cached entries.
        self.selected_entry = None
        self.reload_entries()

    def prepare_map(self, app):
        map_launch.open_saved_map(app, self.selected_save_path,
                                  history_turn=self.selected_history_turn)
        return True

    def prepare_map_steps(self, app):
        return map_launch.open_saved_map_steps(
            app, self.selected_save_path, history_turn=self.selected_history_turn)

    @property
    def managed_dir(self):
        return c.SAVES_DIR

    def refresh_ui(self):
        self.build_browser(self.managed_dir, "No saves yet. Save a game or import a .zip archive.")
        browse_button = Button(c.SCREEN_WIDTH - 496, 24, (160, 40), "blue", "Browse...", self.browse_save,
                               font_preset="button_small")
        import_button = Button(c.SCREEN_WIDTH - 324, 24, (160, 40), "green", "Import .zip",
                               lambda: file_exchange.import_zip_to_dir(self, self.managed_dir, self.reload_entries),
                               font_preset="button_small")
        # A standalone game plays only its own scenario, so it cannot open saves from other folders or archives.
        browse_button.apply_state(enabled=not IS_WEB and not standalone_game.IS_STANDALONE)
        import_button.apply_state(enabled=not standalone_game.IS_STANDALONE)
        self.elements.extend([
            make_back_button(self.exit_screen),
            browse_button,
            import_button,
            Button(c.SCREEN_WIDTH - 152, 24, (128, 40), "grey", "Refresh", self.reload_entries,
                   font_preset="button_small"),
        ])
        if self.selected_entry:
            self.add_browser_action("History", lambda: self.call_selected(self.open_history_menu), 0, "purple",
                                    enabled=self.selection_can_open, sound_kind=None)
            self.add_browser_action("Rename", lambda: self.call_selected(self.start_rename), 1, "blue")
            self.add_browser_action("Export", lambda: self.call_selected(self.export_save_zip), 2, "green")
            self.add_browser_action("Delete…", lambda: self.call_selected(self.start_delete), 3, "red")
        self.open_button = self.add_primary_action("Load Game") if self.selection_can_open else None

    def activate_selected(self):
        if self.selection_can_open:
            self.call_selected(self.load_specific_save)

    def export_save_zip(self, folder_name):
        file_exchange.export_dir_as_zip(os.path.join(self.managed_dir, folder_name), f"{folder_name}.zip",
                                        game_state=self)

    def browse_save(self):
        file_exchange.open_saved_content_folder(
            self, "Select Saved Game Folder", self.managed_dir,
            lambda path: self.load_specific_save(path, play_sound=False))

    def open_history_menu(self, folder_name):
        save_dir = os.path.join(self.managed_dir, folder_name)
        # Refused here, because a click on a turn in the list already plays a sound.
        message = newer_version_message(save_dir)
        if message:
            dialogs.show_info("Update Required", message)
            return
        def read_dates():
            yield "Loading History..."
            return history_io.read_turn_dates(save_dir)

        def show_turns(turn_dates):
            if not turn_dates:
                has_file = any(os.path.exists(os.path.join(save_dir, name))
                               for name in (history_io.GZ_NAME, history_io.PLAIN_NAME))
                dialogs.show_info("No History", "History file is empty." if has_file
                                         else "No history available for this save.")
                return

            play_ui_sound("time_select")
            turns = sorted([int(k) for k in turn_dates])
            turn_by_label = {}
            items = []
            for t in turns:
                date_str = turn_dates[str(t)]
                label = f"Turn {t}: {date_str}"
                items.append(label)
                turn_by_label[label] = t

            def on_select(label):
                self.load_specific_save(folder_name, history_turn=turn_by_label[label])

            pickers.open_listbox_selector(self, f"History: {folder_name}", "Select a past turn to load:",
                                          items, on_select)

        screen_runner.run_loading(LoadingSteps(read_dates(), 1), "Loading History...", on_done=show_turns)

    def load_specific_save(self, folder_name, history_turn=None, *, play_sound=True):
        message = newer_version_message(os.path.join(self.managed_dir, folder_name))
        if message:
            dialogs.show_info("Update Required", message)
            return
        # A history row already played its selection sound.
        if history_turn is None and play_sound:
            play_ui_sound("click")
        self.selected_save_path = os.path.join(self.managed_dir, folder_name)
        self.selected_history_turn = history_turn
        self.go_to("MAP")
