"""Native pygame replacement for tkinter's filedialog.askopenfilename / askdirectory.

Unlike the scoped pickers elsewhere in ui/, this one browses the whole machine:
the Places sidebar reaches every mounted drive, the path bar accepts any typed
path, and navigation is bounded only by what the OS lets the process read. A
call site's `start_dir` is just where the browser opens, never a fence.

run_file_browser() is the blocking entry point. It works with no pygame display
already up (the standalone map_tools scripts) by opening its own window, the
same trick ui/confirm_dialog.py uses.
"""
import os
import string
import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui_elements import Button, TextField
from map_logic.rendering.font_manager import fonts

IS_WINDOWS = os.name == "nt"

# current_dir sentinel for the "This PC" view, which lists mount points rather
# than the contents of any one directory. Not a legal Windows path, so it can
# never collide with a real one.
DRIVE_VIEW = "::drives::"

_DRIVE_TYPES = {2: "Removable", 3: "Local Disk", 4: "Network", 5: "CD/DVD", 6: "RAM Disk"}

# FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_WIN_HIDDEN_MASK = 0x2 | 0x4

# The repo root, two levels up from this file, so "Game Folder" survives the
# game being launched from somewhere other than its own directory.
GAME_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


# ---------------------------------------------------------------------- #
#                            FILESYSTEM HELPERS                          #
# ---------------------------------------------------------------------- #

def list_drives():
    """Every mount point the OS admits to: drive letters on Windows, / elsewhere."""
    if not IS_WINDOWS:
        return ["/"]
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = [f"{letter}:\\" for i, letter in enumerate(string.ascii_uppercase) if bitmask >> i & 1]
        if drives:
            return drives
    except Exception:
        pass
    # Probing every letter touches the drive, so it is only the fallback.
    return [f"{letter}:\\" for letter in string.ascii_uppercase if os.path.exists(f"{letter}:\\")]


def _drive_label(root):
    """Labels a drive by type. Deliberately avoids GetVolumeInformationW, which
    spins up (and can hang on) empty removable drives; GetDriveTypeW does no I/O."""
    if not IS_WINDOWS:
        return root
    try:
        import ctypes
        kind = _DRIVE_TYPES.get(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)))
        if kind:
            return f"{root}  ({kind})"
    except Exception:
        pass
    return root


def _is_root(path):
    return os.path.dirname(path) == path


def _is_hidden(full_path, name):
    if name.startswith("."):
        return True
    if not IS_WINDOWS:
        return False
    try:
        return bool(os.stat(full_path).st_file_attributes & _WIN_HIDDEN_MASK)
    except (OSError, AttributeError, ValueError):
        return False


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def build_places(start_dir=None):
    """The sidebar shortcuts: mount points, the usual user folders, the game, and
    wherever the caller opened the browser."""
    home = os.path.expanduser("~")
    places = [("This PC" if IS_WINDOWS else "Filesystem", DRIVE_VIEW if IS_WINDOWS else "/")]

    for label, path in [("Home", home)] + [(n, os.path.join(home, n)) for n in
                                           ("Desktop", "Documents", "Downloads", "Pictures")]:
        if os.path.isdir(path):
            places.append((label, path))

    for label, path in (("Game Folder", GAME_DIR), (None, start_dir)):
        if not path:
            continue
        path = os.path.abspath(path)
        if os.path.isdir(path) and not any(p != DRIVE_VIEW and _same_path(p, path) for _l, p in places):
            places.append((label or os.path.basename(path) or path, path))

    return places


# ---------------------------------------------------------------------- #
#                              TEXT FITTING                              #
# ---------------------------------------------------------------------- #

def _fit_text(text, font, max_width):
    """Trims from the right, which keeps the start of a file name readable."""
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "...")[0] > max_width:
        text = text[:-1]
    return text + "..."


def _fit_path(text, font, max_width):
    """Trims from the left, which keeps the deepest part of a path readable."""
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size("..." + text)[0] > max_width:
        text = text[1:]
    return "..." + text


class FileBrowserScreen(GameState):
    """In-engine stand-in for a native file/folder picker.

    `mode` is one of:
      "open_file"     -- pick a single file, on_confirm(full_path)
      "open_files"    -- pick one or more files, on_confirm([full_path, ...])
      "select_folder" -- navigate to a folder, on_confirm(folder_path)
    on_confirm is never called on cancel.
    """
    PANEL_SIZE = (1180, 640)
    ROW_HEIGHT = 30
    LIST_TOP_OFF = 108
    LIST_VIEW_H = 450
    SIDEBAR_OFF = 16
    LIST_X_OFF = 250
    TOOLBAR_OFF = 56
    DOUBLE_CLICK_MS = 400

    def __init__(self, game_state, title, start_dir, on_confirm,
                 mode="open_file", extensions=None, confirm_label=None):
        super().__init__()
        # Only used to resolve custom keybinds (BACK/ORDERS); may not carry feedback_text.
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title
        self.on_confirm = on_confirm
        self.mode = mode
        self.extensions = tuple(e.lower() for e in extensions) if extensions else None
        self.confirm_label = confirm_label or ("Select Folder" if mode == "select_folder" else "Open")

        self.selected_file = None
        self.selected = set()
        self.show_hidden = False
        self.show_all_types = False
        self.status = ""
        self.entries = []
        self._rows = []
        self._last_click = (None, 0)

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        panel_w, panel_h = self.PANEL_SIZE
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

        self.places = build_places(start_dir)
        self.current_dir = self._resolve_start(start_dir)

        self.path_field = TextField(0, 0, 10, 32, "", on_submit=self._submit_path)
        self._layout_toolbar()

        self._load_entries()
        self._sync_path_field()
        self.refresh_ui()

    def _resolve_start(self, start_dir):
        """Opens where the caller asked. A start dir that does not exist yet (a
        game folder nothing has written to, a stale path from settings) falls back
        to its nearest existing ancestor rather than being created -- opening a
        browser should never leave folders behind."""
        home = os.path.abspath(os.path.expanduser("~"))
        if not start_dir:
            return home
        path = os.path.abspath(os.path.expanduser(start_dir))
        while not os.path.isdir(path) and not _is_root(path):
            path = os.path.dirname(path)
        return path if os.path.isdir(path) else home

    # ------------------------------------------------------------------ #
    #                              GEOMETRY                              #
    # ------------------------------------------------------------------ #

    def _layout_toolbar(self):
        panel = self.panel_rect
        nav_w, nav_h = c.SIZES["browser_nav"]
        self.toolbar_y = panel.y + self.TOOLBAR_OFF
        field_x = panel.x + self.SIDEBAR_OFF + nav_w + 10
        field_right = panel.right - self.SIDEBAR_OFF - nav_w - 10
        self.path_field.rect = pygame.Rect(field_x, self.toolbar_y, field_right - field_x, nav_h)

        self.list_x = panel.x + self.LIST_X_OFF
        self.list_top = panel.y + self.LIST_TOP_OFF

    # ------------------------------------------------------------------ #
    #                             NAVIGATION                             #
    # ------------------------------------------------------------------ #

    @property
    def listening_for(self):
        """Suppresses the global BACK/ORDERS keybinds while the path bar has focus,
        so typing a path never closes the browser out from under the user."""
        return self.path_field.active

    def _full_path(self, name):
        return name if self.current_dir == DRIVE_VIEW else os.path.join(self.current_dir, name)

    def _matches_filter(self, name):
        if self.extensions is None or self.show_all_types:
            return True
        return name.lower().endswith(self.extensions)

    def _load_entries(self):
        self.status = ""
        if self.current_dir == DRIVE_VIEW:
            self.entries = [(d, "dir") for d in list_drives()]
            return

        try:
            names = sorted(os.listdir(self.current_dir), key=str.lower)
        except OSError as e:
            self.entries = []
            self.status = f"Cannot open this folder: {e.strerror or 'access denied'}."
            return

        folders, files = [], []
        for name in names:
            full = os.path.join(self.current_dir, name)
            if not self.show_hidden and _is_hidden(full, name):
                continue
            try:
                is_dir = os.path.isdir(full)
            except OSError:
                continue
            if is_dir:
                folders.append((name, "dir"))
            elif self.mode != "select_folder" and self._matches_filter(name):
                files.append((name, "file"))
        # Selection state deliberately survives navigation so multi-select can span folders.
        self.entries = folders + files

    def _navigate(self, path):
        self.current_dir = path
        self.scroll_y = 0
        self._load_entries()
        self._sync_path_field()
        self.refresh_ui()

    def _is_current(self, path):
        if path == DRIVE_VIEW or self.current_dir == DRIVE_VIEW:
            return path == self.current_dir
        return _same_path(path, self.current_dir)

    def _can_go_up(self):
        if self.current_dir == DRIVE_VIEW:
            return False
        return IS_WINDOWS or not _is_root(self.current_dir)

    def _go_up(self):
        if not self._can_go_up():
            return
        parent = DRIVE_VIEW if _is_root(self.current_dir) else os.path.dirname(self.current_dir)
        self._navigate(parent)

    def _sync_path_field(self):
        self.path_field.text = "" if self.current_dir == DRIVE_VIEW else self.current_dir
        self.path_field.active = False

    def _submit_path(self):
        """Jumps anywhere on the machine from a typed path -- the escape hatch for
        directories no shortcut reaches."""
        raw = self.path_field.text.strip().strip('"')
        if not raw:
            self._sync_path_field()
            return

        path = os.path.abspath(os.path.expanduser(os.path.expandvars(raw)))
        if os.path.isdir(path):
            self._navigate(path)
            return

        if os.path.isfile(path):
            if self.mode == "select_folder":
                self._navigate(os.path.dirname(path))  # A file names the folder holding it.
                return
            if not self._matches_filter(os.path.basename(path)):
                self.show_all_types = True  # A typed file always wins over the filter.
            if self.mode == "open_files":
                self.selected.add(path)
            else:
                self.selected_file = path
            self._navigate(os.path.dirname(path))
            return

        self._sync_path_field()
        self.status = "No such file or folder." if not os.path.exists(path) else "Not a folder this browser can open."
        self.refresh_ui()

    def _row_click(self, name, kind):
        if kind == "up":
            self._go_up()
            return
        if kind == "dir":
            self._navigate(self._full_path(name))
            return

        full = self._full_path(name)
        if self.mode == "open_files":
            # No double-click shortcut here: rapid clicking is how a multi-select
            # gets built, and confirming mid-way would drop the rest of the picks.
            self.selected.symmetric_difference_update({full})
            self.refresh_ui()
            return

        now = pygame.time.get_ticks()
        if self._last_click[0] == full and now - self._last_click[1] <= self.DOUBLE_CLICK_MS:
            self.selected_file = full
            self._confirm()
            return

        self._last_click = (full, now)
        self.selected_file = None if self.selected_file == full else full
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              TOGGLES                               #
    # ------------------------------------------------------------------ #

    def _toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.scroll_y = 0
        self._load_entries()
        self.refresh_ui()

    def _toggle_filter(self):
        self.show_all_types = not self.show_all_types
        self.scroll_y = 0
        self._load_entries()
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              CONFIRM                               #
    # ------------------------------------------------------------------ #

    def _has_valid_selection(self):
        if self.mode == "select_folder":
            return self.current_dir != DRIVE_VIEW
        if self.mode == "open_files":
            return bool(self.selected)
        return self.selected_file is not None

    def _confirm_text(self):
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
    #                              RENDERING                             #
    # ------------------------------------------------------------------ #

    def _row_label(self, name, kind, max_width):
        font = fonts.get("button")
        if kind == "up":
            return name
        if kind == "dir":
            display = _drive_label(name) if self.current_dir == DRIVE_VIEW else name
            return _fit_text(f"[DIR]  {display}", font, max_width)
        if self.mode == "open_files":
            mark = "[x]" if self._full_path(name) in self.selected else "[  ]"
            return _fit_text(f"{mark} {name}", font, max_width)
        return _fit_text(name, font, max_width)

    def refresh_ui(self):
        panel = self.panel_rect
        nav_w, _nav_h = c.SIZES["browser_nav"]
        self.elements = [self.path_field]

        up_btn = Button(panel.x + self.SIDEBAR_OFF, self.toolbar_y, "browser_nav", "yellow", "Up", self._go_up)
        up_btn.apply_state(enabled=self._can_go_up(), color="yellow")
        self.elements.append(up_btn)
        self.elements.append(Button(panel.right - self.SIDEBAR_OFF - nav_w, self.toolbar_y,
                                    "browser_nav", "light_blue", "Go", self._submit_path))

        # -- Places sidebar
        place_w, place_h = c.SIZES["browser_place"]
        place_font = fonts.get("button")
        for i, (label, path) in enumerate(self.places):
            btn = Button(panel.x + self.SIDEBAR_OFF, self.list_top + i * (place_h + 4), "browser_place",
                         "light_blue", _fit_text(label, place_font, place_w - 16),
                         lambda p=path: self._navigate(p))
            btn.is_selected = self._is_current(path)
            self.elements.append(btn)

        # -- Entry list
        rows = [("Up one level", "up")] if self._can_go_up() else []
        rows += list(self.entries)
        self._rows = rows

        row_w, _row_h = c.SIZES["browser_row"]
        for i, y in self.layout_list_rows(len(rows), self.ROW_HEIGHT, self.list_top,
                                          view_h=self.LIST_VIEW_H,
                                          cull_top=self.list_top - 1,
                                          cull_bottom=self.list_top + self.LIST_VIEW_H - 20):
            name, kind = rows[i]
            color = {"up": "yellow", "dir": "orange", "file": "blue"}[kind]
            btn = Button(self.list_x, y, "browser_row", color, self._row_label(name, kind, row_w - 20),
                         lambda n=name, k=kind: self._row_click(n, k))
            if kind == "file":
                full = self._full_path(name)
                btn.is_selected = full in self.selected if self.mode == "open_files" else full == self.selected_file
            self.elements.append(btn)

        # -- Bottom bar
        btn_y = panel.bottom - 56
        self.elements.append(Button(panel.x + self.SIDEBAR_OFF, btn_y, "small", "red", "Cancel", self.exit_screen))

        # The toggles carry longer labels than a button font fits, so they drop a size.
        tool_w, _tool_h = c.SIZES["browser_tool"]
        tool_font = fonts.get("normal")
        tool_x = panel.x + self.SIDEBAR_OFF + 120
        hidden_btn = Button(tool_x, btn_y, "browser_tool", "light_blue",
                            "Hidden files: On" if self.show_hidden else "Hidden files: Off",
                            self._toggle_hidden, font_preset="normal")
        hidden_btn.is_selected = self.show_hidden
        self.elements.append(hidden_btn)

        if self.extensions and self.mode != "select_folder":
            exts = " ".join("*" + e for e in self.extensions)
            filter_label = ("Showing: all files" if self.show_all_types else
                            f"Only {exts}" if len(self.extensions) <= 2 else
                            f"Only {len(self.extensions)} file types")
            filter_btn = Button(tool_x + tool_w + 10, btn_y, "browser_tool", "light_blue",
                                _fit_text(filter_label, tool_font, tool_w - 16),
                                self._toggle_filter, font_preset="normal")
            filter_btn.is_selected = not self.show_all_types
            self.elements.append(filter_btn)

        confirm_w, _confirm_h = c.SIZES["medium"]
        confirm_btn = Button(panel.right - self.SIDEBAR_OFF - confirm_w, btn_y - 5, "medium", "green",
                             self._confirm_text(), self._confirm)
        confirm_btn.apply_state(enabled=self._has_valid_selection(), color="green")
        self.elements.append(confirm_btn)

    def additional_events(self, event):
        self.handle_list_scroll(event)

    def _selection_summary(self):
        if self.mode == "select_folder":
            return "" if self.current_dir == DRIVE_VIEW else f"Selected folder: {self.current_dir}"
        if self.mode == "open_files":
            return f"{len(self.selected)} file(s) selected" if self.selected else "Click files to select them"
        return f"Selected: {os.path.basename(self.selected_file)}" if self.selected_file else "Click a file to select it"

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        else:
            surface.fill((20, 20, 28))
        ui_bars.draw_fullscreen_overlay(surface, 190)

        panel = self.panel_rect
        ui_bars.draw_modal_box(surface, panel, bg_color=(35, 35, 45),
                               border_color=(100, 150, 255), border_width=3)
        ui_bars.draw_centered_title(surface, self.title, panel.y + 14, "heading2")

        small = fonts.get("small")
        label_y = panel.y + self.LIST_TOP_OFF - 18
        surface.blit(small.render("Places", True, (170, 170, 210)), (panel.x + self.SIDEBAR_OFF, label_y))

        info_w = panel.right - 40 - self.list_x
        if self.status:
            info, color = _fit_text(self.status, small, info_w), (240, 140, 140)
        else:
            info, color = _fit_path(self._selection_summary(), small, info_w), (170, 200, 170)
        surface.blit(small.render(info, True, color), (self.list_x, label_y))

        if not self._rows and not self.status:
            msg = fonts.get("normal").render("Nothing here.", True, (200, 200, 200))
            surface.blit(msg, msg.get_rect(center=(self.list_x + c.SIZES["browser_row"][0] // 2,
                                                   self.list_top + self.LIST_VIEW_H // 2)))

        for el in self.elements:
            el.draw(surface)

        # Drawn over the (empty) path field rather than into it, so the hint never
        # has to be cleared back out of the user's typed text.
        if not self.path_field.text and not self.path_field.active:
            hint = fonts.get("normal").render("Type any path here and press Enter", True, (130, 130, 155))
            surface.blit(hint, hint.get_rect(midleft=(self.path_field.rect.x + 8,
                                                      self.path_field.rect.centery)))

        self.draw_list_scrollbar(surface, panel.right - 26, self.list_top, self.LIST_VIEW_H)


# ---------------------------------------------------------------------- #
#                            BLOCKING ENTRY POINT                        #
# ---------------------------------------------------------------------- #

def run_file_browser(title, start_dir=None, mode="open_file", extensions=None,
                     confirm_label=None, game_state=None, tk_parent=None, on_result=None):
    """Answers on_result(path) -- or (list of paths), or None if cancelled.

    Usable from the game (a display is already up, so this hands off to the
    modal stack and returns immediately) and from the standalone map_tools
    scripts and Tk editor windows (a window is created for the duration and
    on_result fires synchronously before this returns -- see run_screen).
    """
    from ui.screen_runner import run_screen

    result = {}
    run_screen(lambda: FileBrowserScreen(game_state, title, start_dir,
                                         lambda picked: result.setdefault("picked", picked),
                                         mode=mode, extensions=extensions,
                                         confirm_label=confirm_label),
               on_done=lambda screen: on_result(result.get("picked")) if on_result else None,
               tk_parent=tk_parent, caption=title)
