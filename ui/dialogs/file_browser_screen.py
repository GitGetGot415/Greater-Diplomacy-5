"""Native pygame replacement for tkinter's filedialog.askopenfilename / askdirectory.

Unlike the scoped pickers elsewhere in ui/, this one browses the whole machine:
the Places sidebar reaches every mounted drive, the path bar accepts any typed
path, and navigation is bounded only by what the OS lets the process read. A
call site's `start_dir` is just where the browser opens, never a fence.

The layout follows the Windows 2000 Open dialog: a Places bar, a details list
with sortable columns, and file name and file type rows above Open and Cancel.
The clickable path bar comes from later Windows versions. The colors and
bevels are the game's own.

run_file_browser() is the blocking entry point. It works with no pygame display
already up (the standalone scripts/maps tools) by opening its own window, the
same trick ui/dialogs/ uses.
"""

# Keep ctypes imports inside the Windows-only drive helpers.

import os
import string
import time
from typing import NamedTuple, Optional

import pygame
import data.constants as c
from data.queries.content import IMAGE_EXTENSIONS
from ui.navigation.modal_screen import ModalScreen
from ui.background_styles import DIALOG_STYLES
from ui.widgets import text_utils, ui_elements
from ui.widgets.ui_elements import Button, TextField
from ui.rendering.font_manager import fonts

from ui.navigation import screen_runner


IS_WINDOWS = os.name == "nt"

# current_dir sentinel for the "This PC" view, which lists mount points rather
# than the contents of any one directory. Not a legal Windows path, so it can
# never collide with a real one.
DRIVE_VIEW = "::drives::"
DRIVE_VIEW_LABEL = "This PC"

_DRIVE_TYPES = {2: "Removable", 3: "Local Disk", 4: "Network", 5: "CD/DVD", 6: "RAM Disk"}

# FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
_WIN_HIDDEN_MASK = 0x2 | 0x4

# The repo root, two levels up from this file, so "Game Folder" survives the
# game being launched from somewhere other than its own directory.
GAME_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))

# Item          # Icon

# Folder	    # Star
# Drive	        # Save
# Generic file	# Paper
# Images	    # Colors
# Audio	        # Music
# .zip	        # Heart
# .json	        # Text
# .py	        # Gear

# Filler art from the shared symbols. Change these names to replace an icon.
FOLDER_ICON = "Star"
DRIVE_ICON = "Save"
FILE_ICON = "Paper"
EXTENSION_ICONS = {
    **dict.fromkeys(IMAGE_EXTENSIONS, "Colors"),
    **dict.fromkeys(c.MUSIC_AUDIO_EXTENSIONS, "Music"),
    ".zip": "Heart",
    ".json": "Text",
    ".py": "Gear",
}

ROW_SELECTED_STYLE = {"color": c.UI_COLORS["blue"][0], "gradient_strength": 1.0}
ROW_HOVER_STYLE = {"color": (60, 60, 85), "gradient_strength": 1.0}
PANE_BG = (24, 24, 32)
CHROME_COLOR = (70, 70, 95)
CHROME_HOVER_COLOR = (105, 105, 140)
STATUS_ERROR_COLOR = (240, 140, 140)
STATUS_INFO_COLOR = (170, 200, 170)
HINT_COLOR = (130, 130, 155)

PATH_HINT = "Type any path here and press Enter"
SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")
MODIFIED_FORMAT = "%Y-%m-%d %H:%M"
TYPE_AHEAD_RESET_MS = 800


class Entry(NamedTuple):
    """One line of the details list. Size and date are None when unknown or not shown."""
    name: str
    kind: str  # "dir" or "file"
    size: Optional[int]
    modified: Optional[float]
    type_label: str


SORT_KEYS = {
    "name": lambda e: e.name.casefold(),
    "size": lambda e: (e.size or 0, e.name.casefold()),
    "type": lambda e: (e.type_label.casefold(), e.name.casefold()),
    "modified": lambda e: (e.modified or 0, e.name.casefold()),
}


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


def _drive_type(root):
    """Names a drive's type. Deliberately avoids GetVolumeInformationW, which
    spins up (and can hang on) empty removable drives; GetDriveTypeW does no I/O."""
    if not IS_WINDOWS:
        return "Drive"
    try:
        import ctypes
        return _DRIVE_TYPES.get(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)), "Drive")
    except Exception:
        return "Drive"


def _is_root(path):
    return os.path.dirname(path) == path


def _is_hidden(dir_entry):
    if dir_entry.name.startswith("."):
        return True
    if not IS_WINDOWS:
        return False
    try:
        return bool(dir_entry.stat(follow_symlinks=False).st_file_attributes & _WIN_HIDDEN_MASK)
    except (OSError, AttributeError, ValueError):
        return False


def _same_path(a, b):
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _file_type_label(name):
    extension = os.path.splitext(name)[1]
    return f"{extension[1:].upper()} file" if extension else "File"


def _read_entry(dir_entry):
    """Builds an Entry from one os.scandir result, or None when it cannot be read."""
    try:
        is_dir = dir_entry.is_dir()
    except OSError:
        return None
    try:
        info = dir_entry.stat()
        size, modified = (None if is_dir else info.st_size), info.st_mtime
    except OSError:
        size, modified = None, None
    if is_dir:
        return Entry(dir_entry.name, "dir", size, modified, "Folder")
    return Entry(dir_entry.name, "file", size, modified, _file_type_label(dir_entry.name))


def sort_entries(entries, key, descending=False):
    """Folders stay above files, as in Explorer. The direction applies inside each group."""
    folders = [e for e in entries if e.kind == "dir"]
    files = [e for e in entries if e.kind != "dir"]
    return (sorted(folders, key=SORT_KEYS[key], reverse=descending)
            + sorted(files, key=SORT_KEYS[key], reverse=descending))


def format_size(size):
    if size is None:
        return ""
    value = float(size)
    for unit in SIZE_UNITS:
        if value < 1024 or unit == SIZE_UNITS[-1]:
            return f"{int(value)} {unit}" if unit == SIZE_UNITS[0] else f"{value:.1f} {unit}"
        value /= 1024


def format_modified(timestamp):
    if timestamp is None:
        return ""
    try:
        return time.strftime(MODIFIED_FORMAT, time.localtime(timestamp))
    except (OSError, OverflowError, ValueError):
        return ""


def build_places(start_dir=None):
    """The sidebar shortcuts: mount points, the usual user folders, the game, and
    wherever the caller opened the browser."""
    home = os.path.expanduser("~")
    places = [(DRIVE_VIEW_LABEL if IS_WINDOWS else "Filesystem", DRIVE_VIEW if IS_WINDOWS else "/")]

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


def breadcrumbs(path):
    """The clickable path segments for `path`, as (label, path) from the root down."""
    if path == DRIVE_VIEW:
        return [(DRIVE_VIEW_LABEL, DRIVE_VIEW)]
    segments = []
    while not _is_root(path):
        segments.append((os.path.basename(path), path))
        path = os.path.dirname(path)
    segments.append((path.rstrip("\\") or path, path))
    if IS_WINDOWS:
        segments.append((DRIVE_VIEW_LABEL, DRIVE_VIEW))
    segments.reverse()
    return segments


# ---------------------------------------------------------------------- #
#                              TEXT FITTING                              #
# ---------------------------------------------------------------------- #

def _fit_text(text, font, max_width):
    """Trims from the right, which keeps the start of a file name readable."""
    return text_utils.fit_text(text, font, max_width)


def _fit_path(text, font, max_width):
    """Trims from the left, which keeps the deepest part of a path readable."""
    return text_utils.fit_path(text, font, max_width)


# ---------------------------------------------------------------------- #
#                                WIDGETS                                 #
# ---------------------------------------------------------------------- #

class FileRow:
    """One line of the details list, with the same duck-typed interface as Button.

    Rows are rebuilt on refresh_ui, not per frame, so the cell text renders once.
    """

    def __init__(self, rect, icon, cells, is_selected, on_click):
        self.rect = rect
        self.icon = icon
        self.is_selected = is_selected
        self.on_click = on_click
        self.visible = True
        self.is_pressed = False
        self.click_guard = None

        font = fonts.get("normal")
        self.cells = []
        for text, x, width, align in cells:
            if not text:
                continue
            surf = font.render(_fit_text(text, font, width), True, c.UI_TEXT_BRIGHT)
            anchor = {"midright": (x + width, rect.centery)} if align == "right" else {"midleft": (x, rect.centery)}
            self.cells.append((surf, surf.get_rect(**anchor)))

    def _accepts(self, pos):
        return self.rect.collidepoint(pos) and (self.click_guard is None or self.click_guard())

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.is_pressed = self._accepts(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.is_pressed:
            self.is_pressed = False
            if self._accepts(event.pos):
                ui_elements.play_ui_sound("click")
                self.on_click()

    def draw(self, surface):
        if self.is_selected:
            ui_elements.draw_pixel_background(surface, self.rect, ROW_SELECTED_STYLE)
        elif self._accepts(pygame.mouse.get_pos()):
            ui_elements.draw_pixel_background(surface, self.rect, ROW_HOVER_STYLE)
        if self.icon:
            surface.blit(self.icon, self.icon.get_rect(midleft=(self.rect.x + FileBrowserScreen.CELL_PAD,
                                                                self.rect.centery)))
        for surf, rect in self.cells:
            surface.blit(surf, rect)


class PathField(TextField):
    """The path bar's text box. It stays empty until clicked, because the
    breadcrumb buttons show the path on top of it the rest of the time."""

    def draw(self, surface):
        ui_elements.draw_text_box(surface, self.rect, self.text if self.active else "", active=self.active,
                                  pad_x=self.pad_x, placeholder=PATH_HINT if self.active else None)


class FileBrowserScreen(ModalScreen):
    """In-engine stand-in for a native file/folder picker.

    `mode` is one of:
      "open_file"     -- pick a single file, on_confirm(full_path)
      "open_files"    -- pick one or more files, on_confirm([full_path, ...])
      "select_folder" -- pick the highlighted or current folder, on_confirm(folder_path)
    on_confirm is never called on cancel.
    """
    PANEL_SIZE = (1180, 640)
    PANEL_STYLE = DIALOG_STYLES["file_browser"]
    DOUBLE_CLICK_MS = 400

    # Toolbar
    TOOLBAR_OFF = 52
    TOOLBAR_H = 32
    NAV_W = 36
    NAV_GAP = 4
    CRUMB_H = 24
    CRUMB_PAD = 16
    CRUMB_MAX_W = 180
    CRUMB_SEP_W = 18
    # Panes
    PANE_TOP_OFF = 92
    PANE_GAP = 8
    PANE_BORDER = 2
    SIDEBAR_W = 226
    PLACE_GAP = 4
    SCROLLBAR_W = 15
    HEADER_H = 26
    ROW_HEIGHT = 28
    ICON_SIZE = 20
    CELL_PAD = 6
    # The Name column takes whatever width the fixed columns leave.
    COLUMNS = (("name", "Name", None, "left"),
               ("size", "Size", 100, "right"),
               ("type", "Type", 130, "left"),
               ("modified", "Modified", 160, "left"))
    # Form rows under the panes
    FORM_H = 136
    FORM_ROW_H = 32
    FORM_ROW_STEP = 38
    FORM_LABEL_W = 124
    FORM_BTN_W = 150
    HIDDEN_TOGGLE_W = 240
    MENU_ROW_H = 30

    def __init__(self, game_state, title, start_dir, on_confirm,
                 mode="open_file", extensions=None, confirm_label=None):
        super().__init__(game_state, title)
        self.on_confirm = on_confirm
        self.mode = mode
        self.extensions = tuple(e.lower() for e in extensions) if extensions else None
        self.confirm_label = confirm_label or ("Select Folder" if mode == "select_folder" else "Open")

        # Picked files. They survive navigation in "open_files", so a multi-select can span folders.
        self.selected = set()
        self.selected_folder = None
        # The row the arrow keys move from and the row a Shift range starts at.
        self.cursor = None
        self.anchor = None
        self.show_hidden = False
        self.show_all_types = False
        self.type_menu_open = False
        self.sort_key = "name"
        self.sort_descending = False
        self.status = ""
        self.entries = []
        self.back_stack = []
        self.forward_stack = []
        self._last_click = (None, 0)
        self._type_ahead = ("", 0)
        self._icons = {}
        self._crumbs = []
        self._crumb_seps = []
        self._menu_buttons = []
        self._status_line = None
        self.confirm_btn = None

        self.places = build_places(start_dir)
        self.current_dir = self._resolve_start(start_dir)

        self.path_field = PathField(0, 0, 10, self.TOOLBAR_H, "", on_submit=self._submit_path)
        self.path_field.click_guard = self._path_click_allowed
        self.name_field = TextField(0, 0, 10, self.FORM_ROW_H, "", on_submit=self._open_action,
                                    on_change=lambda _text: self._update_confirm())
        self._layout()

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

    def _layout(self):
        panel = self.panel_rect
        self.toolbar_y = panel.y + self.TOOLBAR_OFF
        self.nav_x = panel.x + self.PAD
        bar_x = self.nav_x + 3 * (self.NAV_W + self.NAV_GAP) + self.NAV_GAP
        self.path_field.rect = pygame.Rect(bar_x, self.toolbar_y, panel.right - self.PAD - bar_x, self.TOOLBAR_H)

        top = panel.y + self.PANE_TOP_OFF
        pane_h = panel.bottom - self.FORM_H - top
        self.sidebar_rect = pygame.Rect(panel.x + self.PAD, top, self.SIDEBAR_W, pane_h)
        list_x = self.sidebar_rect.right + self.PANE_GAP
        self.list_rect = pygame.Rect(list_x, top, panel.right - self.PAD - list_x, pane_h)

        inner = self.list_rect.inflate(-2 * self.PANE_BORDER, -2 * self.PANE_BORDER)
        self.header_y = inner.y
        self.rows_rect = pygame.Rect(inner.x, inner.y + self.HEADER_H,
                                     inner.width - self.SCROLLBAR_W, inner.height - self.HEADER_H)

        name_w = self.rows_rect.width - sum(width for _k, _l, width, _a in self.COLUMNS if width)
        self.column_rects = {}
        x = self.rows_rect.x
        for key, _label, width, _align in self.COLUMNS:
            self.column_rects[key] = (x, width or name_w)
            x += width or name_w

        self.form_y = panel.bottom - self.FORM_H + self.PANE_GAP
        self.form_label_x = panel.x + self.PAD
        self.form_field_x = self.form_label_x + self.FORM_LABEL_W
        self.form_btn_x = panel.right - self.PAD - self.FORM_BTN_W
        self.form_field_w = self.form_btn_x - self.PANE_GAP - self.form_field_x
        self.name_field.rect = pygame.Rect(self.form_field_x, self.form_y, self.form_field_w, self.FORM_ROW_H)

    # ------------------------------------------------------------------ #
    #                             NAVIGATION                             #
    # ------------------------------------------------------------------ #

    def _full_path(self, name):
        return name if self.current_dir == DRIVE_VIEW else os.path.join(self.current_dir, name)

    def _matches_filter(self, name):
        if self.extensions is None or self.show_all_types:
            return True
        return name.lower().endswith(self.extensions)

    def _load_entries(self):
        self.status = ""
        if self.current_dir == DRIVE_VIEW:
            self.entries = [Entry(d, "dir", None, None, _drive_type(d)) for d in list_drives()]
            self._apply_sort()
            return

        entries = []
        try:
            with os.scandir(self.current_dir) as scan:
                for dir_entry in scan:
                    if not self.show_hidden and _is_hidden(dir_entry):
                        continue
                    entry = _read_entry(dir_entry)
                    if entry is None:
                        continue
                    if entry.kind == "dir" or (self.mode != "select_folder" and self._matches_filter(entry.name)):
                        entries.append(entry)
        except OSError as e:
            self.entries = []
            self.status = f"Cannot open this folder: {e.strerror or 'access denied'}."
            return
        self.entries = entries
        self._apply_sort()

    def _apply_sort(self):
        self.entries = sort_entries(self.entries, self.sort_key, self.sort_descending)

    def _set_sort(self, key):
        self.sort_descending = key == self.sort_key and not self.sort_descending
        self.sort_key = key
        self._apply_sort()
        self.scroll_y = 0
        self.refresh_ui()

    def _show(self, path):
        """Opens `path` without touching the Back and Forward history."""
        self.current_dir = path
        self.scroll_y = 0
        self.selected_folder = None
        self.cursor = self.anchor = None
        if self.mode != "open_files":
            self.selected.clear()
        self._load_entries()
        self._sync_path_field()
        self._sync_name_field()
        self.refresh_ui()

    def _navigate(self, path):
        if not self._is_current(path):
            self.back_stack.append(self.current_dir)
            self.forward_stack.clear()
        self._show(path)

    def _history_back(self):
        if self.back_stack:
            self.forward_stack.append(self.current_dir)
            self._show(self.back_stack.pop())

    def _history_forward(self):
        if self.forward_stack:
            self.back_stack.append(self.current_dir)
            self._show(self.forward_stack.pop())

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

    def _path_click_allowed(self):
        """A click on a breadcrumb navigates. Only the bar's empty space starts typing."""
        return not any(crumb.rect.collidepoint(pygame.mouse.get_pos()) for crumb in self._crumbs)

    def _resolve_typed(self, raw):
        path = os.path.expanduser(os.path.expandvars(raw.strip().strip('"')))
        if self.current_dir != DRIVE_VIEW:
            path = os.path.join(self.current_dir, path)
        return os.path.abspath(path)

    def _go_to_typed(self, raw, confirm):
        """Jumps anywhere on the machine from a typed path -- the escape hatch for
        directories no shortcut reaches. With `confirm`, the typed item is also
        the answer, as when a name is entered in the file name row."""
        path = self._resolve_typed(raw)
        if os.path.isdir(path):
            self._navigate(path)
            if confirm and self.mode == "select_folder":
                self._confirm()
            return

        if os.path.isfile(path):
            if self.mode == "select_folder":
                self._navigate(os.path.dirname(path))  # A file names the folder holding it.
                return
            if not self._matches_filter(os.path.basename(path)):
                self.show_all_types = True  # A typed file always wins over the filter.
            self._navigate(os.path.dirname(path))
            self.selected.add(path)
            self.cursor = self.anchor = path
            self._sync_name_field()
            if confirm:
                self._confirm()
            else:
                self._scroll_to(self._index_of(path))
                self.refresh_ui()
            return

        self._sync_path_field()
        self.status = "No such file or folder." if not os.path.exists(path) else "Not a folder this browser can open."
        self.refresh_ui()

    def _submit_path(self):
        if self.path_field.text.strip().strip('"'):
            self._go_to_typed(self.path_field.text, confirm=False)
        else:
            self._sync_path_field()

    # ------------------------------------------------------------------ #
    #                              SELECTION                             #
    # ------------------------------------------------------------------ #

    def _index_of(self, path):
        if path is None:
            return None
        for i, entry in enumerate(self.entries):
            if self._full_path(entry.name) == path:
                return i
        return None

    def _clear_current_selection(self):
        """Clears this folder's highlight. A multi-select keeps its picks from other folders."""
        self.selected_folder = None
        if self.mode == "open_files":
            self.selected -= {self._full_path(e.name) for e in self.entries}
        else:
            self.selected.clear()

    def _select_index(self, index, ctrl=False, shift=False):
        entry = self.entries[index]
        full = self._full_path(entry.name)
        multi = self.mode == "open_files"
        anchor_index = self._index_of(self.anchor)

        if shift and multi and anchor_index is not None:
            low, high = sorted((anchor_index, index))
            picks = {self._full_path(e.name) for e in self.entries[low:high + 1] if e.kind == "file"}
            if not ctrl:
                self._clear_current_selection()
            self.selected_folder = None
            self.selected |= picks
        elif entry.kind == "dir":
            if not (ctrl and multi):
                self._clear_current_selection()
            self.selected_folder = full
        elif ctrl and multi:
            self.selected_folder = None
            self.selected ^= {full}
        else:
            self._clear_current_selection()
            self.selected.add(full)

        if not (shift and multi and anchor_index is not None):
            self.anchor = full
        self.cursor = full
        self._sync_name_field()

    def _row_click(self, entry):
        full = self._full_path(entry.name)
        now = pygame.time.get_ticks()
        mods = pygame.key.get_mods()
        ctrl, shift = bool(mods & pygame.KMOD_CTRL), bool(mods & pygame.KMOD_SHIFT)
        is_double = self._last_click[0] == full and now - self._last_click[1] <= self.DOUBLE_CLICK_MS
        self._last_click = (None, 0) if is_double else (full, now)

        # A modified click only edits the selection, so quick Ctrl-clicks can
        # build a multi-select without confirming it.
        if is_double and not (ctrl or shift):
            self._activate(entry)
            return
        self._select_index(self.entries.index(entry), ctrl, shift)
        self.refresh_ui()

    def _activate(self, entry):
        if entry.kind == "dir":
            self._navigate(self._full_path(entry.name))
            return
        self.selected.add(self._full_path(entry.name))
        self._confirm()

    def _selection_text(self):
        """What the name row shows for the current selection."""
        if self.selected_folder:
            return os.path.basename(self.selected_folder) or self.selected_folder
        names = sorted(os.path.basename(path) for path in self.selected)
        return names[0] if len(names) == 1 else " ".join(f'"{name}"' for name in names)

    def _sync_name_field(self):
        self.name_field.text = self._selection_text()
        self.name_field.active = False
        self._update_confirm()

    # ------------------------------------------------------------------ #
    #                              TOGGLES                               #
    # ------------------------------------------------------------------ #

    def _toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.scroll_y = 0
        self._load_entries()
        self.refresh_ui()

    def _set_show_all_types(self, show_all):
        self.show_all_types = show_all
        self.type_menu_open = False
        self.scroll_y = 0
        self._load_entries()
        self.refresh_ui()

    def _toggle_type_menu(self):
        self.type_menu_open = not self.type_menu_open
        self.refresh_ui()

    def _type_options(self):
        """The file type menu, as (label, show_all_types) pairs."""
        patterns = " ".join("*" + e for e in self.extensions)
        name = f"{self.extensions[0][1:].upper()} files" if len(self.extensions) == 1 else "Supported files"
        return [(f"{name} ({patterns})", False), ("All files (*.*)", True)]

    # ------------------------------------------------------------------ #
    #                              CONFIRM                               #
    # ------------------------------------------------------------------ #

    def _has_valid_selection(self):
        if self.mode == "select_folder":
            return bool(self.selected_folder) or self.current_dir != DRIVE_VIEW
        return bool(self.selected)

    def _confirm_text(self):
        if self.mode == "open_files" and self.selected:
            return f"{self.confirm_label} ({len(self.selected)})"
        return self.confirm_label

    def _update_confirm(self):
        """Open also works for a highlighted folder or a typed name, as in a native dialog."""
        if self.confirm_btn:
            self.confirm_btn.apply_state(enabled=self._has_valid_selection() or bool(self.name_field.text.strip()),
                                         text=self._confirm_text(), color="green")

    def _open_action(self):
        typed = self.name_field.text.strip()
        if typed != self._selection_text():
            if typed:
                self._go_to_typed(typed, confirm=True)
            else:
                self._sync_name_field()
            return
        if self.selected_folder and self.mode != "select_folder":
            self._navigate(self.selected_folder)
            return
        self._confirm()

    def _confirm(self):
        if not self._has_valid_selection():
            return
        if self.mode == "select_folder":
            result = self.selected_folder or self.current_dir
        elif self.mode == "open_files":
            result = sorted(self.selected)
        else:
            result = next(iter(self.selected))
        self.on_confirm(result)
        self.exit_screen()

    # ------------------------------------------------------------------ #
    #                                INPUT                               #
    # ------------------------------------------------------------------ #

    def handle_back_key(self):
        """Back first cancels a menu or a text edit. It closes the browser only after that."""
        if self.type_menu_open:
            self._toggle_type_menu()
        elif self.path_field.active:
            self._sync_path_field()
            self.refresh_ui()
        elif self.name_field.active:
            self._sync_name_field()
        else:
            super().handle_back_key()

    def handle_events(self, events):
        for event in events:
            if self.type_menu_open:
                self._menu_event(event)
            elif event.type == pygame.KEYDOWN and not self.listening_for:
                self._handle_key(event)
            else:
                path_was_active = self.path_field.active
                super().handle_events([event])
                if self.path_field.active != path_was_active:
                    if not self.path_field.active:
                        self._sync_path_field()
                    self.refresh_ui()

    def _menu_event(self, event):
        """An open menu takes every event, so a click cannot reach the controls under it."""
        for button in self._menu_buttons:
            button.handle_event(event)
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and not any(button.rect.collidepoint(event.pos) for button in self._menu_buttons)):
            self._toggle_type_menu()

    def _handle_key(self, event):
        mods = getattr(event, "mod", 0) | pygame.key.get_mods()
        if mods & pygame.KMOD_ALT:
            if event.key == pygame.K_LEFT:
                self._history_back()
            elif event.key == pygame.K_RIGHT:
                self._history_forward()
        elif event.key == pygame.K_BACKSPACE:
            self._go_up()
        elif event.key in (pygame.K_UP, pygame.K_DOWN):
            self._move_cursor(-1 if event.key == pygame.K_UP else 1, bool(mods & pygame.KMOD_SHIFT))
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._open_action()
        elif event.unicode.isprintable() and event.unicode and not mods & pygame.KMOD_CTRL:
            self._jump_to_typed(event.unicode)

    def _move_cursor(self, delta, shift):
        if not self.entries:
            return
        index = self._index_of(self.cursor)
        index = 0 if index is None else max(0, min(len(self.entries) - 1, index + delta))
        self._select_index(index, shift=shift)
        self._scroll_to(index)
        self.refresh_ui()

    def _jump_to_typed(self, character):
        """Typing with no field focused selects the first name that starts with the keys pressed."""
        now = pygame.time.get_ticks()
        prefix, last = self._type_ahead
        prefix = prefix + character.casefold() if now - last <= TYPE_AHEAD_RESET_MS else character.casefold()
        self._type_ahead = (prefix, now)
        for index, entry in enumerate(self.entries):
            if entry.name.casefold().startswith(prefix):
                self._select_index(index)
                self._scroll_to(index)
                self.refresh_ui()
                return

    def _scroll_to(self, index):
        if index is None:
            return
        top = index * self.ROW_HEIGHT
        view_h = self.rows_rect.height
        if top + self.scroll_y < 0:
            self.scroll_y = -top
        elif top + self.ROW_HEIGHT + self.scroll_y > view_h:
            self.scroll_y = view_h - top - self.ROW_HEIGHT

    def additional_events(self, event):
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.rows_rect.collidepoint(event.pos)
                and not any(isinstance(el, FileRow) and el.rect.collidepoint(event.pos) for el in self.elements)):
            self._clear_current_selection()
            self._sync_name_field()
            self.refresh_ui()
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    # ------------------------------------------------------------------ #
    #                              RENDERING                             #
    # ------------------------------------------------------------------ #

    def _icon(self, name):
        """The standalone map tools load no symbols, so an icon can be None there."""
        if name not in self._icons:
            self._icons[name] = ui_elements.scale_icon(name, self.ICON_SIZE)
        return self._icons[name]

    def _entry_icon(self, entry):
        if self.current_dir == DRIVE_VIEW:
            return self._icon(DRIVE_ICON)
        if entry.kind == "dir":
            return self._icon(FOLDER_ICON)
        return self._icon(EXTENSION_ICONS.get(os.path.splitext(entry.name)[1].lower(), FILE_ICON))

    def _chrome_button(self, x, y, size, text, callback, font_preset="button_small"):
        """A column header or breadcrumb: quieter than the action buttons around it."""
        button = Button(x, y, size, "grey", text, callback, font_preset=font_preset)
        button.set_colors(CHROME_COLOR, CHROME_HOVER_COLOR)
        return button

    def _row_cells(self, entry):
        text = {"name": entry.name, "size": format_size(entry.size),
                "type": entry.type_label, "modified": format_modified(entry.modified)}
        cells = []
        for key, _label, _width, align in self.COLUMNS:
            x, width = self.column_rects[key]
            inset = self.CELL_PAD + (self.ICON_SIZE + self.CELL_PAD if key == "name" else 0)
            cells.append((text[key], x + inset, width - inset - self.CELL_PAD, align))
        return cells

    def _add_toolbar(self):
        for i, (label, callback, enabled) in enumerate((("<", self._history_back, bool(self.back_stack)),
                                                        (">", self._history_forward, bool(self.forward_stack)),
                                                        ("^", self._go_up, self._can_go_up()))):
            button = Button(self.nav_x + i * (self.NAV_W + self.NAV_GAP), self.toolbar_y,
                            (self.NAV_W, self.TOOLBAR_H), "light_blue", label, callback, font_preset="button_small")
            button.apply_state(enabled=enabled, color="light_blue")
            self.elements.append(button)

        self.elements.append(self.path_field)
        self._crumbs, self._crumb_seps = [], []
        if not self.path_field.active:
            self._add_breadcrumbs()

    def _add_breadcrumbs(self):
        """Lays the path out from its deepest folder, dropping parents that do not fit."""
        font = fonts.get("button_small")
        bar = self.path_field.rect
        segments = breadcrumbs(self.current_dir)
        overflow_w = font.size(c.ELLIPSIS)[0] + self.CRUMB_SEP_W
        available = bar.width - 2 * self.CRUMB_PAD - overflow_w

        kept, used = [], 0
        for label, path in reversed(segments):
            width = min(font.size(label)[0] + self.CRUMB_PAD, self.CRUMB_MAX_W)
            if kept and used + width + self.CRUMB_SEP_W > available:
                break
            kept.append((label, path, width))
            used += width + self.CRUMB_SEP_W
        kept.reverse()

        x = bar.x + self.CRUMB_PAD // 2
        y = bar.centery - self.CRUMB_H // 2
        separators = []
        if len(kept) < len(segments):
            separators.append((c.ELLIPSIS, x))
            x += overflow_w - self.CRUMB_SEP_W
        for i, (label, path, width) in enumerate(kept):
            if i or len(kept) < len(segments):
                separators.append((">", x))
                x += self.CRUMB_SEP_W
            crumb = self._chrome_button(x, y, (width, self.CRUMB_H),
                                        _fit_text(label, font, width - self.CRUMB_PAD),
                                        lambda p=path: self._navigate(p))
            self._crumbs.append(crumb)
            self.elements.append(crumb)
            x += width

        for text, sep_x in separators:
            surf = fonts.get("normal").render(text, True, c.UI_TEXT_LIGHT)
            self._crumb_seps.append((surf, (sep_x + 4, bar.centery - surf.get_height() // 2)))

    def _add_places(self):
        place_w, place_h = c.SIZES["browser_place"]
        font = fonts.get("button_small")
        x = self.sidebar_rect.x + self.PANE_GAP
        for i, (label, path) in enumerate(self.places):
            icon = self._icon(DRIVE_ICON if path == DRIVE_VIEW else FOLDER_ICON)
            button = Button(x, self.sidebar_rect.y + self.PANE_GAP + i * (place_h + self.PLACE_GAP),
                            "browser_place", "light_blue", _fit_text(label, font, place_w - 46),
                            lambda p=path: self._navigate(p), image=icon, font_preset="button_small")
            button.is_selected = self._is_current(path)
            self.elements.append(button)

    def _add_list(self):
        for key, label, _width, _align in self.COLUMNS:
            x, width = self.column_rects[key]
            if key == self.COLUMNS[-1][0]:
                width += self.SCROLLBAR_W
            arrow = (" v" if self.sort_descending else " ^") if key == self.sort_key else ""
            header = self._chrome_button(x, self.header_y, (width, self.HEADER_H), label + arrow,
                                         lambda k=key: self._set_sort(k))
            header.text_align = "left"
            self.elements.append(header)

        rows = self.rows_rect
        self.scroll_content_rect = rows
        for i, y in self.layout_list_rows(len(self.entries), self.ROW_HEIGHT, rows.y, view_h=rows.height,
                                          cull_top=rows.top, cull_bottom=rows.bottom):
            entry = self.entries[i]
            full = self._full_path(entry.name)
            self.add_list_row(FileRow(pygame.Rect(rows.x, y, rows.width, self.ROW_HEIGHT),
                                      self._entry_icon(entry), self._row_cells(entry),
                                      full in self.selected or full == self.selected_folder,
                                      lambda e=entry: self._row_click(e)))

    def _add_form(self):
        btn_size = (self.FORM_BTN_W, self.FORM_ROW_H)
        self.elements.append(self.name_field)
        self.confirm_btn = Button(self.form_btn_x, self.form_y, btn_size, "green", self._confirm_text(),
                                  self._open_action, font_preset="button_small")
        self._update_confirm()
        self.elements.append(self.confirm_btn)

        type_y = self.form_y + self.FORM_ROW_STEP
        self.elements.append(Button(self.form_btn_x, type_y, btn_size, "red", "Cancel", self.exit_screen,
                                    font_preset="button_small", sound_kind="back"))

        self._menu_buttons = []
        if self.extensions and self.mode != "select_folder":
            self._add_type_menu(type_y)

        toggle_x = self.panel_rect.right - self.PAD - self.HIDDEN_TOGGLE_W
        self.elements.append(self.toggle(toggle_x, type_y + self.FORM_ROW_STEP, self.HIDDEN_TOGGLE_W,
                                         self.show_hidden, "Show hidden files", self._toggle_hidden))

    def _add_type_menu(self, y):
        font = fonts.get("button_small")
        options = self._type_options()
        size = (self.form_field_w, self.FORM_ROW_H)
        current = next(label for label, show_all in options if show_all == self.show_all_types)
        text_w = self.form_field_w - 2 * self.CRUMB_PAD - font.size("  v")[0]
        dropdown = Button(self.form_field_x, y, size, "light_blue", f"{_fit_text(current, font, text_w)}  v",
                          self._toggle_type_menu, font_preset="button_small")
        dropdown.text_align = "left"
        self.elements.append(dropdown)

        if not self.type_menu_open:
            return
        # The menu opens upward so that it stays inside the panel.
        for i, (label, show_all) in enumerate(options):
            option = Button(self.form_field_x, y - (len(options) - i) * self.MENU_ROW_H,
                            (self.form_field_w, self.MENU_ROW_H), "grey", _fit_text(label, font, text_w),
                            lambda v=show_all: self._set_show_all_types(v), font_preset="button_small")
            option.set_colors(CHROME_COLOR, CHROME_HOVER_COLOR)
            option.text_align = "left"
            option.is_selected = show_all == self.show_all_types
            self._menu_buttons.append(option)

    def _build_status_line(self):
        """Computed on refresh_ui so that the frame draw does not count entries."""
        if self.status:
            return self.status, STATUS_ERROR_COLOR
        if self.mode == "select_folder":
            folder = self.selected_folder or ("" if self.current_dir == DRIVE_VIEW else self.current_dir)
            return (f"Selected folder: {folder}" if folder else "Click a folder to select it"), STATUS_INFO_COLOR

        def count(number, noun):
            return f"{number} {noun}" if number == 1 else f"{number} {noun}s"

        folders = sum(entry.kind == "dir" for entry in self.entries)
        parts = [count(folders, "drive" if self.current_dir == DRIVE_VIEW else "folder")]
        if self.current_dir != DRIVE_VIEW:
            parts.append(count(len(self.entries) - folders, "file"))
        text = ", ".join(parts)
        if self.selected:
            text += f"  |  {len(self.selected)} selected"
            elsewhere = len(self.selected - {self._full_path(e.name) for e in self.entries})
            if elsewhere:
                text += f" ({elsewhere} in other folders)"
        return text, STATUS_INFO_COLOR

    def refresh_ui(self):
        self.elements = []
        self._add_toolbar()
        self._add_places()
        self._add_list()
        self._add_form()

        text, color = self._build_status_line()
        small = fonts.get("small")
        width = self.panel_rect.right - self.PAD - self.HIDDEN_TOGGLE_W - self.PANE_GAP - self.form_label_x
        fit = _fit_path if self.mode == "select_folder" and not self.status else _fit_text
        self._status_line = small.render(fit(text, small, width), True, color)

    def draw_body(self, surface):
        ui_elements.draw_pixel_panel(surface, self.sidebar_rect, PANE_BG, recessed=True, border_width=self.PANE_BORDER)
        ui_elements.draw_pixel_panel(surface, self.list_rect, PANE_BG, recessed=True, border_width=self.PANE_BORDER)

        name_label = "Folder name:" if self.mode == "select_folder" else "File name:"
        self._draw_form_label(surface, name_label, self.form_y)
        if self.extensions and self.mode != "select_folder":
            self._draw_form_label(surface, "Files of type:", self.form_y + self.FORM_ROW_STEP)

        status_y = self.form_y + 2 * self.FORM_ROW_STEP + self.FORM_ROW_H // 2
        surface.blit(self._status_line, self._status_line.get_rect(midleft=(self.form_label_x, status_y)))

        if not self.entries and not self.status:
            msg = fonts.get("normal").render("Nothing here.", True, c.UI_TEXT_LIGHT)
            surface.blit(msg, msg.get_rect(center=self.rows_rect.center))

    def _draw_form_label(self, surface, text, y):
        label = fonts.get("normal").render(text, True, c.UI_TEXT_BRIGHT)
        surface.blit(label, label.get_rect(midleft=(self.form_label_x, y + self.FORM_ROW_H // 2)))

    def draw_foreground(self, surface):
        for surf, pos in self._crumb_seps:
            surface.blit(surf, pos)
        self.draw_list_scrollbar(surface, self.rows_rect.right, self.rows_rect.y, self.rows_rect.height,
                                 width=self.SCROLLBAR_W)
        # Rows draw after the other elements, so the menu draws here to stay on top of them.
        for button in self._menu_buttons:
            button.draw(surface)


# ---------------------------------------------------------------------- #
#                            BLOCKING ENTRY POINT                        #
# ---------------------------------------------------------------------- #

def run_file_browser(title, start_dir=None, mode="open_file", extensions=None,
                     confirm_label=None, game_state=None, tk_parent=None, on_result=None):
    """Answers on_result(path) -- or (list of paths), or None if cancelled.

    Usable from the game (a display is already up, so this hands off to the
    modal stack and returns immediately) and from the standalone scripts/maps
    tools and Tk editor windows (a window is created for the duration and
    on_result fires synchronously before this returns -- see run_screen).
    """

    result = {}
    screen_runner.run_screen(lambda: FileBrowserScreen(game_state, title, start_dir,
                                         lambda picked: result.setdefault("picked", picked),
                                         mode=mode, extensions=extensions,
                                         confirm_label=confirm_label),
               on_done=lambda screen: on_result(result.get("picked")) if on_result else None,
               tk_parent=tk_parent, caption=title)
