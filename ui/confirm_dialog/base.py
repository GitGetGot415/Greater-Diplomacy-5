"""Shared modal skeleton and standalone/blocking-loop plumbing for every
dialog in this package -- see ui/confirm_dialog/__init__.py for the overview.
"""
import pygame
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts
from ui import modal_stack
from ui import text_utils
from ui.bars import ui_bars

_STANDALONE_SIZE = (520, 320)

# These dialogs keep their own darker, higher-contrast look rather than the
# modal panel palette: they interrupt whatever is on screen, including the
# panels in that palette, so they have to read as sitting above it.
_DIALOG_BG = (40, 40, 40)
_DIALOG_OVERLAY_ALPHA = 180


def _lighten(color, amount=40):
    """Hover tint for a solid-colored action button."""
    return tuple(min(255, channel + amount) for channel in color)


def _back_key():
    """The rebound BACK key, so these dialogs dismiss on it same as everything else."""
    return queries.get_keybind("BACK", pygame.K_ESCAPE)


def _hide_tk_chain(tk_widget):
    """Withdraws a tkinter widget and every ancestor window so the pygame dialog isn't hidden behind a topmost tk window."""
    hidden = []
    widget = tk_widget
    seen = set()
    while widget is not None and id(widget) not in seen:
        seen.add(id(widget))
        try:
            if widget.winfo_exists() and widget.state() != "withdrawn":
                hidden.append(widget)
                widget.withdraw()
        except Exception:
            pass
        widget = getattr(widget, "master", None)
    return hidden


def _show_tk_chain(hidden):
    for widget in reversed(hidden):
        try:
            widget.deiconify()
        except Exception:
            pass


def _acquire_surface():
    return ui_bars.acquire_surface(_STANDALONE_SIZE, "Confirm")


def _release_surface(owns_display):
    ui_bars.release_surface(owns_display)


def _wrap_text(text, font, max_width):
    """Kept as the name checkbox_list_screen and scripted_events_editor already
    import; the implementation now lives in ui/text_utils.py."""
    return text_utils.wrap_text(text, font, max_width)


class _BaseModal:
    """Shared skeleton for the four dialogs below.

    Each one used to repeat the same __init__ prologue (snapshot the surface,
    pick three fonts, wrap the message, centre a box), the same update/_finish
    pair, and the same draw prologue (freeze-frame, dim, box, centred title,
    wrapped body). Subclasses now declare their box width and extra height and
    fill in draw_content().
    """

    #: Widest the box gets before it starts wrapping instead of growing.
    BOX_MAX_W = 520
    #: Minimum box height, and the fixed chrome above/below the message body.
    BOX_MIN_H = 200
    BOX_CHROME_H = 130
    BORDER_COLOR = c.UI_TEXT_LIGHT
    BORDER_WIDTH = 2
    TITLE_DY = 35
    BODY_DY = 75
    BODY_ALIGN = "center"
    #: Whether on_result takes the answer. The message popups just signal "closed".
    PASSES_RESULT = True

    def __init__(self, surface, title, message, on_result, extra_h=0):
        self.on_result = on_result
        self.background = surface.copy()
        self._resolved = False
        self._result = None

        self.title = title
        self.title_font = fonts.get("heading2")
        self.msg_font = fonts.get("normal")
        self.btn_font = fonts.get("button")

        box_w = min(self.BOX_MAX_W, surface.get_width() - 40)
        self.lines = _wrap_text(message, self.msg_font, box_w - 40) if message else []
        box_h = max(self.BOX_MIN_H, self.BOX_CHROME_H + self.body_height() + extra_h)

        self.box_rect = pygame.Rect(0, 0, box_w, box_h)
        self.box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

    def body_height(self):
        return len(self.lines) * (self.msg_font.get_height() + 2)

    # -- resolution ----------------------------------------------------- #

    def update(self):
        if self._resolved:
            modal_stack.pop()
            if self.on_result:
                if self.PASSES_RESULT:
                    self.on_result(self._result)
                else:
                    self.on_result()

    def _finish(self, result=None):
        self._resolved = True
        self._result = result

    # -- drawing -------------------------------------------------------- #

    def draw_button(self, surface, rect, label, color, hover_color):
        """One of the dialog's action buttons, tinted while hovered."""
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surface, hover_color if hovered else color, rect, border_radius=4)
        surf = self.btn_font.render(label, True, (255, 255, 255))
        surface.blit(surf, surf.get_rect(center=rect.center))

    def draw_body_lines(self, surface):
        """Renders the wrapped message and returns the y below the last line."""
        y = self.box_rect.y + self.BODY_DY
        left_x, right_x = self.box_rect.x + 40, self.box_rect.right - 40
        for line in self.lines:
            line_surf = self.msg_font.render(line, True, (210, 210, 210))
            if self.BODY_ALIGN == "left":
                rect = line_surf.get_rect(midleft=(left_x, y))
            elif self.BODY_ALIGN == "right":
                rect = line_surf.get_rect(midright=(right_x, y))
            else:
                rect = line_surf.get_rect(center=(self.box_rect.centerx, y))
            surface.blit(line_surf, rect)
            y += self.msg_font.get_height() + 2
        return y

    def draw_content(self, surface):
        """Whatever sits below the message: input box, buttons, links."""
        pass

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        ui_bars.draw_fullscreen_overlay(surface, _DIALOG_OVERLAY_ALPHA)

        pygame.draw.rect(surface, _DIALOG_BG, self.box_rect)
        pygame.draw.rect(surface, self.BORDER_COLOR, self.box_rect, self.BORDER_WIDTH)

        title_surf = self.title_font.render(self.title, True, (255, 255, 255))
        surface.blit(title_surf,
                     title_surf.get_rect(center=(self.box_rect.centerx, self.box_rect.y + self.TITLE_DY)))

        self.draw_body_lines(surface)
        self.draw_content(surface)


def _run_blocking(make_modal, tk_parent, default_result=None):
    """Runs a dialog to completion with its own frame loop, and returns the answer.

    Only reachable when no display exists yet -- the standalone dev tools in
    data/editors and the map_tools scripts, which run outside the game's main
    loop. In-game the dialog goes on the modal stack instead; a nested loop
    here would never yield to the browser and would freeze a pygbag tab
    (see ui/modal_stack.py).

    This was written out once per dialog, differing only in the modal class and
    the sentinel returned on QUIT.
    """
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    modal = make_modal(surface)
    clock = pygame.time.Clock()
    result = default_result

    try:
        while True:
            events = pygame.event.get()
            if any(event.type == pygame.QUIT for event in events):
                break
            modal.handle_events(events)
            if modal._resolved:
                result = modal._result
                break

            modal.draw(surface)
            pygame.display.flip()
            clock.tick(c.TARGET_FPS)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

    return result
