"""Native pygame replacement for tkinter's filedialog.askopenfilename / askdirectory.

Every call site browses a single known, pre-scoped directory (saves, tournament
saves, maps) rather than the whole filesystem, so this is an in-game scoped
browser -- not a raw OS dialog -- matching ui/list_select_screen.py's shape.
"""
import os
import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui_elements import Button
from map_logic.rendering.font_manager import fonts


def _truncate(text, max_chars):
    return text if len(text) <= max_chars else text[:max_chars - 3] + "..."


class FileBrowserScreen(GameState):
    """In-engine stand-in for a tkinter file/folder picker.

    `mode` is one of:
      "open_file"     -- pick a single file, on_confirm(full_path)
      "open_files"     -- pick one or more files, on_confirm([full_path, ...])
      "select_folder"  -- navigate to a folder, on_confirm(folder_path)
    Browsing never leaves `root_dir`; on_confirm is never called on cancel.
    """
    PANEL_SIZE = (760, 620)
    ROW_HEIGHT = 38
    ROW_TOP = 130
    ROW_LABEL_MAX_CHARS = 60
    UP_LABEL = ".. (Up)"

    def __init__(self, game_state, title, root_dir, on_confirm,
                 mode="open_file", extensions=None, confirm_label="Select"):
        super().__init__()
        # Only used to resolve custom keybinds (BACK/ORDERS); may not carry feedback_text.
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title
        self.root_dir = os.path.abspath(root_dir)
        self.on_confirm = on_confirm
        self.mode = mode
        self.extensions = tuple(e.lower() for e in extensions) if extensions else None
        self.confirm_label = confirm_label

        self.current_dir = self.root_dir
        self.selected_file = None
        self.selected = set()
        self._rows = []

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        panel_w, panel_h = self.PANEL_SIZE
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

        self._load_entries()
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              NAVIGATION                            #
    # ------------------------------------------------------------------ #

    def _load_entries(self):
        os.makedirs(self.current_dir, exist_ok=True)
        try:
            names = sorted(os.listdir(self.current_dir), key=str.lower)
        except OSError:
            names = []

        folders, files = [], []
        for name in names:
            full = os.path.join(self.current_dir, name)
            if os.path.isdir(full):
                folders.append((name, "dir"))
            elif self.mode != "select_folder" and (self.extensions is None or name.lower().endswith(self.extensions)):
                files.append((name, "file"))
        # Selection state deliberately survives navigation so multi-select can span folders.
        self.entries = folders + files

    def _enter(self, name):
        self.current_dir = os.path.join(self.current_dir, name)
        self._load_entries()
        self.scroll_y = 0
        self.refresh_ui()

    def _go_up(self):
        self.current_dir = os.path.dirname(self.current_dir)
        self._load_entries()
        self.scroll_y = 0
        self.refresh_ui()

    def _row_click(self, name, kind):
        if kind == "up":
            self._go_up()
            return
        if kind == "dir":
            self._enter(name)
            return

        full = os.path.join(self.current_dir, name)
        if self.mode == "open_files":
            self.selected.symmetric_difference_update({full})
        else:
            self.selected_file = None if self.selected_file == full else full
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              CONFIRM                                #
    # ------------------------------------------------------------------ #

    def _has_valid_selection(self):
        if self.mode == "select_folder":
            return True
        if self.mode == "open_files":
            return bool(self.selected)
        return self.selected_file is not None

    def _confirm_label(self):
        if self.mode == "open_files" and self.selected:
            return f"{self.confirm_label} ({len(self.selected)})"
        return self.confirm_label

    def _confirm(self):
        if not self._has_valid_selection():
            return
        if self.mode == "select_folder":
            result = self.current_dir
        elif self.mode == "open_files":
            result = sorted(self.selected)
        else:
            result = self.selected_file
        self.on_confirm(result)
        self.exit_screen()

    # ------------------------------------------------------------------ #
    #                              RENDERING                              #
    # ------------------------------------------------------------------ #

    def _row_label(self, name, kind):
        if kind == "up":
            return name
        if kind == "dir":
            return _truncate(f"[DIR] {name}", self.ROW_LABEL_MAX_CHARS)
        full = os.path.join(self.current_dir, name)
        if self.mode == "open_files":
            mark = "[x]" if full in self.selected else "[ ]"
            return _truncate(f"{mark} {name}", self.ROW_LABEL_MAX_CHARS)
        return _truncate(name, self.ROW_LABEL_MAX_CHARS)

    def refresh_ui(self):
        self.elements = [Button(self.panel_rect.x + 20, self.panel_rect.y + 20, "small", "red",
                                "Cancel", self.exit_screen)]

        confirm_btn = Button(self.panel_rect.right - 190, self.panel_rect.bottom - 55, "medium",
                             "green", self._confirm_label(), self._confirm)
        confirm_btn.apply_state(enabled=self._has_valid_selection())
        self.elements.append(confirm_btn)

        rows = list(self.entries)
        if self.current_dir != self.root_dir:
            rows = [(self.UP_LABEL, "up")] + rows
        self._rows = rows

        row_top = self.panel_rect.y + self.ROW_TOP
        view_h = self.panel_rect.height - self.ROW_TOP - 80
        row_x = self.panel_rect.centerx - (c.SIZES["list_row"][0] // 2)

        for i, y in self.layout_list_rows(len(rows), self.ROW_HEIGHT, row_top, view_h=view_h,
                                          cull_top=self.panel_rect.y + 95, cull_bottom=self.panel_rect.bottom - 70):
            name, kind = rows[i]
            color = {"up": "yellow", "dir": "orange", "file": "blue"}[kind]
            btn = Button(row_x, y, "list_row", color, self._row_label(name, kind),
                        lambda n=name, k=kind: self._row_click(n, k))
            if kind == "file":
                full = os.path.join(self.current_dir, name)
                btn.is_selected = full in self.selected if self.mode == "open_files" else full == self.selected_file
            self.elements.append(btn)

    def additional_events(self, event):
        self.handle_list_scroll(event)

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        ui_bars.draw_fullscreen_overlay(surface, 190)

        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(35, 35, 45),
                               border_color=(100, 150, 255), border_width=3)
        ui_bars.draw_centered_title(surface, self.title, self.panel_rect.y + 20, "heading2")

        rel = os.path.relpath(self.current_dir, self.root_dir)
        path_text = "/" if rel == "." else rel.replace(os.sep, "/")
        path_surf = fonts.get("normal").render(path_text, True, (180, 180, 220))
        surface.blit(path_surf, path_surf.get_rect(center=(self.panel_rect.centerx, self.panel_rect.y + 75)))

        if not self._rows:
            msg_surf = fonts.get("normal").render("Nothing here.", True, (200, 200, 200))
            surface.blit(msg_surf, msg_surf.get_rect(center=(self.panel_rect.centerx, self.panel_rect.centery)))

        for el in self.elements:
            el.draw(surface)

        self.draw_list_scrollbar(surface, self.panel_rect.right - 30, self.panel_rect.y + self.ROW_TOP,
                                 self.panel_rect.height - self.ROW_TOP - 80)
