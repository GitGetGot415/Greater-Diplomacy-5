"""The shared chrome for a modal tool window: dimmed freeze-frame, bordered
panel, centred title.

Seven screens repeated the same four-line __init__ and the same four-step draw,
each with slightly different values -- overlay alpha 190 or 210, panel fill
(35,35,45) or (40,40,40), title offset +12, +14 or +20. Those are now one look,
taken from the palette in data/constants.py, with the numbers still overridable
per screen for anything that genuinely needs to differ.

The class was previously buried in ui/scripted_events_editor.py as _ModalScreen,
which meant every other screen would have had to import a private name out of an
unrelated 1200-line editor to reuse it. That module keeps the old name as an
alias, so nothing that referred to it breaks.

Import-graph note: this deliberately imports only gameState, ui_bars, ui_elements
and the font manager at module scope. data.queries and ui.confirm_dialog are
pulled in inside the methods that need them, since both would otherwise close a
cycle back through screens.menu_screens.map.
"""

import pygame

import data.constants as c
from gameState import GameState
from map_logic.rendering.font_manager import fonts
from ui import text_utils
from ui.bars import ui_bars
from ui.scroll_panes import ScrollPanes
from ui_elements import Button


class ModalScreen(ScrollPanes, GameState):
    """A dimmed freeze-frame behind a bordered panel -- the shape every converted
    tool window in ui/ uses. Subclasses fill in draw_body() and refresh_ui()."""

    PANEL_SIZE = (1240, 680)
    PAD = 16
    ROW_HEIGHT = 34

    #: Chrome, overridable per screen. Defaults are the shared modal look.
    OVERLAY_ALPHA = c.MODAL_OVERLAY_ALPHA
    PANEL_BG = c.MODAL_BG
    PANEL_BORDER = c.MODAL_BORDER
    PANEL_BORDER_WIDTH = 3
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET
    TITLE_PRESET = "heading2"
    #: Painted behind the panel when there was no frame to freeze.
    FALLBACK_BG = (20, 20, 28)

    def __init__(self, game_state, title, panel_size=None):
        super().__init__()
        # Only used to resolve custom keybinds (BACK/ORDERS) and to host sub-pickers.
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        self.panel_rect = pygame.Rect(0, 0, *(panel_size or self.PANEL_SIZE))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

    @property
    def listening_for(self):
        """Keeps the global BACK keybind from closing the screen mid-edit.

        Six screens declared this same property, three of them character for
        character. Any focused text field counts, so a subclass only needs to
        override when its editable state lives somewhere other than `elements`.
        """
        return any(getattr(el, "active", False) for el in self.elements)

    # -- widgets -------------------------------------------------------- #

    def _assign(self, attr, value):
        """Sets an attribute and re-renders -- the callback shape combos and toggles want."""
        setattr(self, attr, value)
        self.refresh_ui()

    def _sized(self, btn, width):
        btn.rect.width = width
        return btn

    def button(self, x, y, width, color, text, callback, preset="list_row"):
        return self._sized(Button(x, y, preset, color, text, callback, font_preset="button_small"), width)

    def combo(self, x, y, width, value, options, title, on_pick, color="light_blue"):
        """A combobox: shows the current value, opens the shared modal list picker."""
        label = text_utils.truncate_chars(str(value) if str(value) else "-", max(4, (width - 14) // 9))
        return self.button(x, y, width, color, label,
                           lambda: self._choose(title, options, on_pick))

    def _choose(self, title, options, on_pick):
        from data import queries
        from ui import confirm_dialog

        options = list(options)
        if not options:
            confirm_dialog.show_warning("Nothing to pick", f"There are no {title.lower()} to choose from.")
            return
        queries.open_listbox_selector(self.map_screen, title, f"Select {title}:", options, on_pick)
        self.refresh_ui()

    def toggle(self, x, y, width, checked, text, callback):
        label = text_utils.truncate_chars(f"[{'X' if checked else '  '}] {text}",
                                          max(4, (width - 14) // 9))
        btn = self.button(x, y, width, "green" if checked else "grey", label, callback)
        btn.is_selected = checked
        return btn

    # -- field <-> data sync -------------------------------------------- #

    def sync_entries(self):
        """Pulls live text out of on-screen fields before they get rebuilt or saved.

        A field carrying `entry_ref` (the dict it edits) and `entry_key` writes
        itself back. Three editors each had their own version of this keyed on a
        different marker attribute; this is the general one.
        """
        for el in self.elements:
            entry = getattr(el, "entry_ref", None)
            if entry is not None:
                entry[el.entry_key] = el.text

    # -- drawing -------------------------------------------------------- #

    def label(self, surface, text, pos, color=c.UI_TEXT_DIM, preset="small"):
        surface.blit(fonts.get(preset).render(text, True, color), pos)

    def draw_body(self, surface):
        """Panel content drawn under the buttons -- labels, dividers, previews."""
        pass

    def draw_foreground(self, surface):
        """Drawn after the buttons. Scrollbars go here: they must sit on top of
        the rows they scroll, and the rows are drawn by draw_elements."""
        pass

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        else:
            surface.fill(self.FALLBACK_BG)
        ui_bars.draw_fullscreen_overlay(surface, self.OVERLAY_ALPHA)

        ui_bars.draw_panel_frame(surface, self.panel_rect, self.title,
                                 bg=self.PANEL_BG, border=self.PANEL_BORDER,
                                 border_width=self.PANEL_BORDER_WIDTH,
                                 title_dy=self.TITLE_Y_OFFSET,
                                 font_preset=self.TITLE_PRESET)

        self.draw_body(surface)
        self.draw_elements(surface)
        self.draw_foreground(surface)
