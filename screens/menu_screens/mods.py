import os
import pygame
from data import queries
from gameState import FolderListState
from ui_elements import Button
import data.constants as c

class Mods(FolderListState):
    """Import/export/delete screen for the mods/ folder.

    Purely a file-management screen for now: nothing in the game reads from
    mods/ yet, so imported mods don't affect gameplay until a loader exists
    to apply them.
    """
    back_state = "MENU"
    title = "MODS"

    ROW_HEIGHT = 40
    ROW_TOP = 120
    # (x, size preset, colour, label, handler name) for the buttons on every mod row.
    # A None label falls back to the folder name.
    ROW_BUTTONS = [
        (20, "save_file", "blue", None, None),
        (895, "small_save_button", "grey", "Rename", "start_rename"),
        (1005, "small_save_button", "green", "Export", "export_mod_zip"),
        (1115, "small_save_button", "red", "Del", "start_delete"),
    ]

    def __init__(self):
        super().__init__()
        self.bg_color = (30, 40, 30)
        self.refresh_ui()

    @property
    def managed_dir(self):
        return c.MODS_DIR

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
            Button(160, 20, "medium", "green", "Import .zip",
                   lambda: queries.import_zip_to_dir(self, self.managed_dir, self.refresh_ui))
        ]

        folders = self.list_folders()
        self.scroll_content_rect = pygame.Rect(0, 100, c.SCREEN_WIDTH, (c.SCREEN_HEIGHT - 50) - 100)
        for i, btn_y in self.layout_list_rows(len(folders), self.ROW_HEIGHT, self.ROW_TOP):
            folder = folders[i]
            # The row being renamed or deleted is replaced by its prompt
            if self.is_row_hidden(folder):
                continue

            for x, size, color, label, handler in self.ROW_BUTTONS:
                btn = Button(x, btn_y, size, color, label or folder,
                            lambda f=folder, h=handler: getattr(self, h)(f) if h else None)
                if handler is None:
                    btn.disabled = True
                btn.is_scrollable = True
                btn.click_guard = self.scroll_click_guard
                self.elements.append(btn)

    def additional_events(self, event):
        if not self.handle_name_prompt_event(event):
            self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def additional_draw(self, surface):
        if self.renaming_item:
            folders = self.list_folders()
            idx = folders.index(self.renaming_item) if self.renaming_item in folders else 0
            self.draw_rename_box(surface, 200, self.ROW_TOP + (idx * self.ROW_HEIGHT) + self.scroll_y)

        if self.deleting_item:
            self.draw_delete_confirm(surface)

        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 40, self.ROW_TOP, c.SCREEN_HEIGHT - 200)

    def export_mod_zip(self, folder_name):
        queries.export_dir_as_zip(os.path.join(self.managed_dir, folder_name), f"{folder_name}.zip")
