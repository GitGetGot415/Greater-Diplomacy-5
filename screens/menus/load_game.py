import os
import json
import pygame
from ui import dialogs
from data import queries
from ui.dialogs import pickers
from ui.dialogs import file_exchange
from data.map import history_io
from ui.navigation.game_state import FolderListState
from ui.widgets.ui_elements import Button, make_back_button, play_ui_sound
import data.constants as c

from data.map.load_map import newer_version_message


class Load_Game(FolderListState):
    back_state = "MENU"

    ROW_HEIGHT = 40
    ROW_TOP = 120
    # (x, size preset, color, label, handler name) for the buttons on every save row.
    # A None label falls back to the folder name.
    ROW_BUTTONS = [
        (20, "save_file", "blue", None, "load_specific_save"),
        (785, "small_save_button", "purple", "History", "open_history_menu"),
        (895, "small_save_button", "grey", "Rename", "start_rename"),
        (1005, "small_save_button", "green", "Export", "export_save_zip"),
        (1115, "small_save_button", "red", "Del", "start_delete"),
    ]

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
            Button(160, 20, "medium", "green", "Import .zip",
                   lambda: file_exchange.import_zip_to_dir(self, self.managed_dir, self.refresh_ui))
        ]

        folders = self.list_folders()
        self.scroll_content_rect = pygame.Rect(0, 100, c.SCREEN_WIDTH, (c.SCREEN_HEIGHT - 50) - 100)
        for i, btn_y in self.layout_list_rows(len(folders), self.ROW_HEIGHT, self.ROW_TOP):
            folder = folders[i]
            for x, size, color, label, handler in self.ROW_BUTTONS:
                # These two play their own sound, which depends on what they find.
                btn = Button(x, btn_y, size, color, label or folder,
                            lambda f=folder, h=handler: getattr(self, h)(f),
                            sound_kind=None if handler in ("load_specific_save", "open_history_menu") else "click")
                self.add_list_row(btn)

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def additional_draw(self, surface):
        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 40, self.ROW_TOP, c.SCREEN_HEIGHT - 200)

    def export_save_zip(self, folder_name):
        file_exchange.export_dir_as_zip(os.path.join(self.managed_dir, folder_name), f"{folder_name}.zip")

    def open_history_menu(self, folder_name):
        save_dir = os.path.join(self.managed_dir, folder_name)
        # Refused here, because a click on a turn in the list already plays a sound.
        message = newer_version_message(save_dir)
        if message:
            dialogs.show_info("Update Required", message)
            return
        turn_dates = history_io.read_turn_dates(save_dir)

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

    def load_specific_save(self, folder_name, history_turn=None):
        message = newer_version_message(os.path.join(self.managed_dir, folder_name))
        if message:
            dialogs.show_info("Update Required", message)
            return
        # A turn chosen from the history list has already played its row's click.
        if history_turn is None:
            play_ui_sound("click")
        self.selected_save_path = os.path.join(self.managed_dir, folder_name)
        self.selected_history_turn = history_turn
        self.go_to("MAP")
