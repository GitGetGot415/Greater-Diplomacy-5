"""Shared shape of the small dialogs in this package -- see ui/dialogs/__init__.py
for the overview.

DialogScreen is a ModalScreen sized to its message and centred on the surface it
opens over. open_dialog runs one through screen_runner.run_screen: on the modal
stack in game, or in its own window for the standalone dev tools.
"""
import pygame
import data.constants as c
from data.io import keybind_io
from ui.background_styles import DIALOG_STYLES
from ui.navigation import screen_runner
from ui.navigation.modal_screen import ModalScreen
from ui.navigation.screen import resolve_keybind
from ui.rendering.font_manager import fonts
from ui import sound_effects
from ui.widgets import text_utils
from ui.widgets.ui_elements import Button

# The window a standalone tool opens for one dialog.
_STANDALONE_SIZE = (520, 320)
_STANDALONE_CAPTION = "Confirm"


def _lighten(color, amount=40):
    """Hover tint for a dialog action button."""
    return tuple(min(255, channel + amount) for channel in color)


class DialogScreen(ModalScreen):
    """A titled message box with answer buttons.

    A subclass sets its box width and extra height, adds its buttons with
    add_button, and draws anything else in draw_body. A dialog closes with
    answer(); run_screen then pops it and delivers the result.
    """
    #: Widest the box gets before it starts wrapping instead of growing.
    BOX_MAX_W = 520
    #: Minimum box height, and the fixed chrome above/below the message body.
    BOX_MIN_H = 200
    BOX_CHROME_H = 130
    #: Title centre and first body line centre, below the box top.
    TITLE_DY = 35
    BODY_DY = 75
    BODY_ALIGN = "center"
    #: Space between the box edge and the wrapped message, on each side.
    TEXT_MARGIN = 20
    #: Whether on_result takes the answer. The message popups just signal "closed".
    PASSES_RESULT = True
    #: The answer when a standalone tool's window is closed instead of the dialog being answered.
    DEFAULT_RESULT = None

    # These dialogs keep their own darker, higher-contrast look rather than the
    # modal panel palette: they interrupt whatever is on screen, including the
    # panels in that palette, so they have to read as sitting above it.
    OVERLAY_ALPHA = 180
    PANEL_STYLE = DIALOG_STYLES["main"]
    PANEL_BORDER = c.UI_TEXT_LIGHT
    PANEL_BORDER_WIDTH = 2
    TITLE_PRESET = "heading2"

    def __init__(self, surface, title, message, extra_h=0):
        super().__init__(None, title)
        self.background = surface.copy()
        self.result = self.DEFAULT_RESULT
        self.msg_font = fonts.get("normal")
        # draw_screen_panel places the title by its top edge.
        self.TITLE_Y_OFFSET = self.TITLE_DY - fonts.get(self.TITLE_PRESET).get_height() // 2

        box_w = min(self.BOX_MAX_W, surface.get_width() - 40)
        self.lines = (text_utils.wrap_text(message, self.msg_font, box_w - 2 * self.TEXT_MARGIN)
                      if message else [])
        box_h = max(self.BOX_MIN_H, self.BOX_CHROME_H + self.body_height() + extra_h)
        self.panel_rect = pygame.Rect(0, 0, box_w, box_h)
        self.panel_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

    def body_height(self):
        return len(self.lines) * (self.msg_font.get_height() + 2)

    # -- answers -------------------------------------------------------- #

    def answer(self, result=None, sound=None):
        """Closes the dialog with `result`. Only the first answer counts."""
        if self.done:
            return
        if sound:
            sound_effects.play_ui_sound(sound)
        self.result = result
        self.done = True

    def is_cancel_key(self, key):
        """Escape, and the rebindable BACK key, cancel every dialog."""
        return key in (pygame.K_ESCAPE, resolve_keybind(self, "BACK", keybind_io.default_keybind("BACK")))

    def cancel(self):
        """What Escape and BACK do."""
        self.answer(self.DEFAULT_RESULT)

    def handle_back_key(self):
        self.cancel()

    def handle_events(self, events):
        for event in events:
            if self.done:
                return
            for element in self.elements:
                element.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        if event.type == pygame.KEYDOWN:
            self.handle_key(event)

    def handle_key(self, event):
        """A key press. Escape and BACK cancel unless a subclass says otherwise."""
        if self.is_cancel_key(event.key):
            self.cancel()

    # -- drawing -------------------------------------------------------- #

    def add_button(self, rect, label, color, hover_color, callback, sound_kind=None):
        """An answer button in the dialog's own colors. Most answers play no sound."""
        button = Button(*rect.topleft, rect.size, "blue", label, callback, sound_kind=sound_kind)
        button.set_colors(color, hover_color)
        self.elements.append(button)
        return button

    def draw_body_lines(self, surface, offset_y=0):
        """Renders the wrapped message and returns the y below the last line."""
        y = self.panel_rect.y + self.BODY_DY + offset_y
        left_x, right_x = self.panel_rect.x + 40, self.panel_rect.right - 40
        for line in self.lines:
            line_surf = self.msg_font.render(line, True, (210, 210, 210))
            if self.BODY_ALIGN == "left":
                rect = line_surf.get_rect(midleft=(left_x, y))
            elif self.BODY_ALIGN == "right":
                rect = line_surf.get_rect(midright=(right_x, y))
            else:
                rect = line_surf.get_rect(center=(self.panel_rect.centerx, y))
            surface.blit(line_surf, rect)
            y += self.msg_font.get_height() + 2
        return y

    def draw_body(self, surface):
        self.draw_body_lines(surface)


def open_dialog(make_dialog, on_result, tk_parent=None):
    """Opens a dialog and answers on_result when it closes.

    make_dialog(surface) builds the dialog over the current display. tk_parent
    is a tkinter widget a standalone tool hides while its dialog is open.
    """
    def deliver(dialog):
        if on_result:
            if dialog.PASSES_RESULT:
                on_result(dialog.result)
            else:
                on_result()

    screen_runner.run_screen(lambda: make_dialog(pygame.display.get_surface()), deliver,
                             tk_parent=tk_parent, caption=_STANDALONE_CAPTION, size=_STANDALONE_SIZE)
