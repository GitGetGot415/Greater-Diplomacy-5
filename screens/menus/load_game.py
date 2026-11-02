import os
import json
import pygame
from ui import dialogs
from data import queries
from ui.dialogs import pickers
from ui.dialogs import file_exchange
from data.map import history_io
from ui.navigation.game_state import FolderListState
from ui.widgets.ui_elements import make_back_button
import data.constants as c

from data.map.load_map import newer_version_message


class Load_Game(FolderListState):
    back_state = "MENU"

    ROW_HEIGHT = 40
    ROW_TOP = 120
    ROW_BUTTONS = (
        (20, 0, "save_file", "blue", None, "load_specific_save"),
        (785, 0, "small_save_button", "purple", "History", "open_history_menu"),
        (895, 0, "small_save_button", "grey", "Rename", "start_rename"),
        (1005, 0, "small_save_button", "green", "Export", "export_save_zip"),
        (1115, 0, "small_save_button", "red", "X", "start_delete"),
    )
    ROW_BUTTON_SOUNDS = {"open_history_menu": "time_select"}

    def __init__(self):
        super().__init__()
        self.bg_color = (50, 0, 50)
        self.refresh_ui()

    @property
    def managed_dir(self):
        return c.SAVES_DIR

    def refresh_ui(self):
        self.elements = [
            make_back_button(self.exit_screen),
            self.make_import_zip_button(),
        ]

        folders = self.list_folders()
        self.scroll_content_rect = pygame.Rect(0, 100, c.SCREEN_WIDTH, (c.SCREEN_HEIGHT - 50) - 100)
        for i, btn_y in self.layout_list_rows(len(folders), self.ROW_HEIGHT, self.ROW_TOP):
            self.add_folder_row(folders[i], btn_y)

    def export_save_zip(self, folder_name):
        file_exchange.export_dir_as_zip(os.path.join(self.managed_dir, folder_name), f"{folder_name}.zip")

    def open_history_menu(self, folder_name):
        save_dir = os.path.join(self.managed_dir, folder_name)
        turn_dates = history_io.read_turn_dates(save_dir)

        if not turn_dates:
            has_file = any(os.path.exists(os.path.join(save_dir, name))
                           for name in (history_io.GZ_NAME, history_io.PLAIN_NAME))
            dialogs.show_info("No History", "History file is empty." if has_file
                                     else "No history available for this save.")
            return

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

    def load_specific_save(self, folder_name, history_turn=None):
        message = newer_version_message(os.path.join(self.managed_dir, folder_name))
        if message:
            dialogs.show_info("Update Required", message)
            return
        self.selected_save_path = os.path.join(self.managed_dir, folder_name)
        self.selected_history_turn = history_turn
        self.go_to("MAP")
