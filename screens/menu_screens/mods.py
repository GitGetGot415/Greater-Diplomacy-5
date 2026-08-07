import os
import pygame
from data import queries
from gameState import FolderListState
from ui_elements import Button
from map_logic.rendering.font_manager import fonts
import data.constants as c
import mod_loader

class Mods(FolderListState):
    """Import/list/toggle/delete screen for .GD5MOD source patches.

    mod_loader.py applies enabled mods at process start by substituting their
    source in for the target module's real file -- nothing on disk is ever
    overwritten, so toggling a mod off or deleting it here just reverts to the
    real file next launch. Nothing here can affect the game that's already
    running: Python only imports a module once per process, so every change
    made on this screen needs a restart to take effect.
    """
    back_state = "MENU"
    title = "MODS"

    ROW_HEIGHT = 60
    ROW_TOP = 130

    def __init__(self):
        super().__init__()
        self.bg_color = (30, 40, 30)
        self.refresh_ui()

    @property
    def managed_dir(self):
        return c.MODS_DIR

    def list_folders(self, directory=None):
        directory = self.managed_dir if directory is None else directory
        if not os.path.exists(directory):
            os.makedirs(directory)
        return sorted(f for f in os.listdir(directory) if f.lower().endswith(".gd5mod"))

    def toggle_mod(self, filename):
        info = mod_loader.describe_mod(filename)
        new_enabled = not info["enabled"]

        # Enabling a mod that targets the same file as another already-enabled
        # mod would make which one applies depend on scan order -- keep it
        # deterministic by turning the other one off instead of just letting
        # mod_loader.install() silently skip it at next launch.
        if new_enabled and info["valid"]:
            for other in self.list_folders():
                if other == filename:
                    continue
                other_info = mod_loader.describe_mod(other)
                if other_info["enabled"] and other_info["valid"] and other_info["module"] == info["module"]:
                    mod_loader.set_mod_enabled(other, False)

        mod_loader.set_mod_enabled(filename, new_enabled)
        queries.sync_persisted_dir(self.managed_dir)
        self.refresh_ui()

    def confirm_delete(self):
        if self.deleting_item:
            path = os.path.join(self.managed_dir, self.deleting_item)
            if os.path.exists(path):
                os.remove(path)
                mod_loader.set_mod_enabled(self.deleting_item, None)
                queries.sync_persisted_dir(self.managed_dir)
        self.cancel_delete()

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
            Button(160, 20, "medium", "green", "Import .GD5MOD",
                   lambda: queries.import_gd5mod_file(self, self.refresh_ui)),
        ]

        self._row_subtext = []
        mods = self.list_folders()
        self.scroll_content_rect = pygame.Rect(0, 110, c.SCREEN_WIDTH, (c.SCREEN_HEIGHT - 50) - 110)
        for i, btn_y in self.layout_list_rows(len(mods), self.ROW_HEIGHT, self.ROW_TOP):
            filename = mods[i]
            if self.is_row_hidden(filename):
                continue
            self._add_row(filename, btn_y)

    def _add_row(self, filename, btn_y):
        info = mod_loader.describe_mod(filename)
        enabled = info["enabled"] and info["valid"]

        name_color = "green" if enabled else ("grey" if not info["valid"] else "blue")
        name_btn = Button(20, btn_y, "save_file", name_color, filename, None)
        name_btn.disabled = True
        name_btn.is_scrollable = True
        name_btn.click_guard = self.scroll_click_guard
        self.elements.append(name_btn)

        toggle_btn = Button(895, btn_y, "small_save_button",
                            "green" if enabled else "grey",
                            "On" if enabled else "Off",
                            lambda f=filename: self.toggle_mod(f))
        toggle_btn.disabled = not info["valid"]
        toggle_btn.is_scrollable = True
        toggle_btn.click_guard = self.scroll_click_guard
        self.elements.append(toggle_btn)

        del_btn = Button(1005, btn_y, "small_save_button", "red", "Del",
                         lambda f=filename: self.start_delete(f))
        del_btn.is_scrollable = True
        del_btn.click_guard = self.scroll_click_guard
        self.elements.append(del_btn)

        subtext = f"-> {info['target']}" if info["target"] else ""
        if info["error"]:
            subtext = f"{subtext}  ({info['error']})" if subtext else info["error"]
        self._row_subtext.append((subtext, 25, btn_y + 32))

    def additional_events(self, event):
        if not self.handle_name_prompt_event(event):
            self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def additional_draw(self, surface):
        clip = surface.get_clip()
        surface.set_clip(self.scroll_content_rect)
        for text, x, y in getattr(self, "_row_subtext", []):
            if text:
                fonts.draw_text_with_shadow(surface, text, x, y, "small", (180, 180, 180))
        surface.set_clip(clip)

        if not self.list_folders():
            fonts.draw_text_with_shadow(surface, "No mods installed yet.", 25, self.ROW_TOP,
                                        "normal", (180, 180, 180))

        fonts.draw_text_with_shadow(surface, "Restart the game for changes to take effect.",
                                    20, c.SCREEN_HEIGHT - 35, "small", (180, 180, 180))

        if self.deleting_item:
            self.draw_delete_confirm(surface)

        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 40, self.ROW_TOP, c.SCREEN_HEIGHT - 200)
