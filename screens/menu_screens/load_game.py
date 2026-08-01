import os
import json
from ui import confirm_dialog
from data import queries
from gameState import FolderListState
from ui_elements import Button
import data.constants as c

class Load_Game(FolderListState):
    back_state = "MENU"

    ROW_HEIGHT = 40
    ROW_TOP = 120
    # (x, size preset, colour, label, handler name) for the buttons on every save row.
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
            Button(20, 20, "small", "red", "Back", self.exit_screen),
            Button(160, 20, "medium", "green", "Import .zip",
                   lambda: queries.import_zip_to_dir(self, self.managed_dir, self.refresh_ui))
        ]

        folders = self.list_folders()
        for i, btn_y in self.layout_list_rows(len(folders), self.ROW_HEIGHT, self.ROW_TOP):
            folder = folders[i]
            # The row being renamed or deleted is replaced by its prompt
            if self.is_row_hidden(folder):
                continue

            for x, size, color, label, handler in self.ROW_BUTTONS:
                self.elements.append(Button(x, btn_y, size, color, label or folder,
                                            lambda f=folder, h=handler: getattr(self, h)(f)))

    def additional_events(self, event):
        if not self.handle_name_prompt_event(event):
            self.handle_list_scroll(event)

    def additional_draw(self, surface):
        if self.renaming_item:
            folders = self.list_folders()
            idx = folders.index(self.renaming_item) if self.renaming_item in folders else 0
            self.draw_rename_box(surface, 200, self.ROW_TOP + (idx * self.ROW_HEIGHT) + self.scroll_y)

        if self.deleting_item:
            self.draw_delete_confirm(surface)

        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 40, self.ROW_TOP, c.SCREEN_HEIGHT - 200)

    def export_save_zip(self, folder_name):
        queries.export_dir_as_zip(os.path.join(self.managed_dir, folder_name), f"{folder_name}.zip")

    def open_history_menu(self, folder_name):
        history_path = os.path.join(self.managed_dir, folder_name, "history.json")
        history_data = {}
        if os.path.exists(history_path):
            with open(history_path, "r") as f:
                history_data = json.load(f)

        if not history_data:
            confirm_dialog.show_info("No History", "History file is empty." if os.path.exists(history_path)
                                     else "No history available for this save.")
            return

        turns = sorted([int(k) for k in history_data.keys()])
        turn_by_label = {}
        items = []
        for t in turns:
            date_str = history_data[str(t)].get("date_str", f"Turn {t}")
            label = f"Turn {t}: {date_str}"
            items.append(label)
            turn_by_label[label] = t

        def on_select(label):
            self.selected_history_turn = turn_by_label[label]
            self.load_specific_save(folder_name)

        queries.open_listbox_selector(self, f"History: {folder_name}", "Select a past turn to load:",
                                      items, on_select)

    def load_specific_save(self, folder_name):
        self.selected_save_path = os.path.join(self.managed_dir, folder_name)
        self.go_to("MAP")
