"""Pygame-rendered replacements for tkinter's messagebox.askyesno / simpledialog.askinteger.

Every function here is callback-based: instead of returning a value, it takes
an on_result callback and invokes it once the user answers. Two things drive
that shape (see ui/modal_stack.py for the full rationale):

- When a main-loop-managed display already exists (the normal in-game case),
  the dialog is pushed onto the modal stack and answered on a later frame --
  it can't block the caller, since blocking is exactly what freezes a pygbag
  browser tab (main.py's loop never gets to yield to the browser).
- When no display exists yet (standalone tkinter dev tools like
  data/editors/country_editor.py, run outside the game's main loop entirely),
  there's no modal stack pumping frames, so the dialog falls back to running
  its own short-lived blocking loop and calls on_result() right before
  returning -- same callback shape, just resolved synchronously.

Call sites always look the same either way: `ask_yes_no(title, msg, on_result=...)`.
"""
import pygame
import webbrowser
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
    """Hover tint for a solid-coloured action button."""
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


class _YesNoModal(_BaseModal):
    BOX_MAX_W = 520

    def __init__(self, surface, title, message, on_result, yes_label, no_label):
        super().__init__(surface, title, message, on_result)
        self.yes_rect = pygame.Rect(self.box_rect.centerx - 140, self.box_rect.bottom - 55, 120, 40)
        self.no_rect = pygame.Rect(self.box_rect.centerx + 20, self.box_rect.bottom - 55, 120, 40)
        self.yes_label = yes_label
        self.no_label = no_label

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                    self._finish(True)
                elif event.key in (pygame.K_ESCAPE, pygame.K_n, _back_key()):
                    self._finish(False)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.yes_rect.collidepoint(event.pos):
                    self._finish(True)
                elif self.no_rect.collidepoint(event.pos):
                    self._finish(False)

    def draw_content(self, surface):
        self.draw_button(surface, self.yes_rect, self.yes_label, (0, 150, 0), (0, 190, 0))
        self.draw_button(surface, self.no_rect, self.no_label, (150, 0, 0), (190, 0, 0))


def _ask_yes_no_standalone(title, message, on_result, tk_parent, yes_label, no_label):
    result = _run_blocking(
        lambda surf: _YesNoModal(surf, title, message, None, yes_label, no_label),
        tk_parent, default_result=False)
    on_result(bool(result))


def ask_yes_no(title, message, on_result, tk_parent=None, yes_label="Yes", no_label="No"):
    """Answers on_result(True/False) once the user picks Yes or No.

    tk_parent, if given, is a tkinter widget to hide for the dialog's duration --
    only meaningful for the standalone dev-tool path (no game display up yet).
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _ask_yes_no_standalone(title, message, on_result, tk_parent, yes_label, no_label)
        return

    modal_stack.push(_YesNoModal(surface, title, message, on_result, yes_label, no_label))


class _TextInputModal(_BaseModal):
    BOX_MAX_W = 480
    BOX_MIN_H = 230
    BOX_CHROME_H = 210   # 120 of chrome plus the 90 the input row occupies

    def __init__(self, surface, title, message, initial_text, on_result, char_allowed, validate):
        super().__init__(surface, title, message, on_result)
        self.char_allowed = char_allowed
        self.validate = validate

        self.input_rect = pygame.Rect(self.box_rect.x + 40, self.box_rect.bottom - 110,
                                      self.box_rect.width - 80, 40)
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 140, self.box_rect.bottom - 55, 120, 40)
        self.cancel_rect = pygame.Rect(self.box_rect.centerx + 20, self.box_rect.bottom - 55, 120, 40)

        self.text = str(initial_text) if initial_text is not None else ""
        self.error_text = ""

    def _submit(self):
        value, self.error_text = self.validate(self.text)
        if self.error_text == "":
            self._finish(value)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, _back_key()):
                    self._finish(None)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._submit()
                elif event.key == pygame.K_BACKSPACE:
                    self.text = self.text[:-1]
                    self.error_text = ""
                elif event.unicode and self.char_allowed(event.unicode, self.text):
                    self.text += event.unicode
                    self.error_text = ""
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._submit()
                elif self.cancel_rect.collidepoint(event.pos):
                    self._finish(None)

    def draw_content(self, surface):
        pygame.draw.rect(surface, (20, 20, 20), self.input_rect)
        border_color = (220, 80, 80) if self.error_text else c.UI_TEXT_LIGHT
        pygame.draw.rect(surface, border_color, self.input_rect, 2)
        input_surf = self.msg_font.render(self.text or " ", True, (255, 255, 255))
        surface.set_clip(self.input_rect.inflate(-10, -6))
        surface.blit(input_surf, input_surf.get_rect(midleft=(self.input_rect.x + 10,
                                                             self.input_rect.centery)))
        surface.set_clip(None)

        if self.error_text:
            err_surf = fonts.get("small").render(self.error_text, True, (230, 100, 100))
            surface.blit(err_surf, err_surf.get_rect(center=(self.box_rect.centerx,
                                                             self.input_rect.y - 14)))

        self.draw_button(surface, self.ok_rect, "OK", (0, 150, 0), (0, 190, 0))
        self.draw_button(surface, self.cancel_rect, "Cancel", (150, 0, 0), (190, 0, 0))


def _run_text_input_dialog_standalone(title, message, initial_text, tk_parent, char_allowed,
                                      validate, on_result):
    on_result(_run_blocking(
        lambda surf: _TextInputModal(surf, title, message, initial_text, None,
                                     char_allowed, validate),
        tk_parent, default_result=None))


def _run_text_input_dialog(title, message, initial_text, tk_parent, char_allowed, validate, on_result):
    """Shared single-line text-entry modal used by ask_integer and ask_string.

    char_allowed(unicode_char, current_text) -> bool decides which typed characters are accepted.
    validate(text) -> (value, error_message); value is None (with a message) when the text isn't acceptable yet.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _run_text_input_dialog_standalone(title, message, initial_text, tk_parent, char_allowed, validate, on_result)
        return

    modal_stack.push(_TextInputModal(surface, title, message, initial_text, on_result, char_allowed, validate))


def ask_integer(title, message, on_result, minvalue=None, maxvalue=None, initial=None, tk_parent=None):
    """Answers on_result(int) once confirmed, or on_result(None) if cancelled."""

    def char_allowed(ch, current_text):
        return ch.isdigit() or (ch == "-" and not current_text)

    def validate(text):
        if not text:
            return None, "Enter a number."
        try:
            value = int(text)
        except ValueError:
            return None, "Enter a whole number."
        if minvalue is not None and value < minvalue:
            return None, f"Minimum is {minvalue}."
        if maxvalue is not None and value > maxvalue:
            return None, f"Maximum is {maxvalue}."
        return value, ""

    initial_text = str(initial) if initial is not None else ""
    _run_text_input_dialog(title, message, initial_text, tk_parent, char_allowed, validate, on_result)


def ask_string(title, message, on_result, initial="", tk_parent=None, allow_empty=True):
    """Answers on_result(str) once confirmed, or on_result(None) if cancelled."""

    def char_allowed(ch, current_text):
        return ch.isprintable()

    def validate(text):
        if not allow_empty and not text.strip():
            return None, "This field cannot be empty."
        return text, ""

    _run_text_input_dialog(title, message, initial, tk_parent, char_allowed, validate, on_result)


_KIND_ACCENTS = {
    "info": (80, 150, 220),
    "success": (60, 170, 90),
    "warning": (210, 160, 40),
    "error": (200, 70, 70),
}


class _MessageModal(_BaseModal):
    BOX_MAX_W = 520
    BOX_CHROME_H = 170   # 110 of chrome plus the 60 the OK row occupies
    BORDER_WIDTH = 3
    PASSES_RESULT = False

    def __init__(self, surface, title, message, on_result, kind):
        self.accent = _KIND_ACCENTS.get(kind, _KIND_ACCENTS["info"])
        super().__init__(surface, title, message, on_result)
        self.BORDER_COLOR = self.accent
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                                 pygame.K_SPACE, _back_key()):
                    self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()

    def draw_content(self, surface):
        self.draw_button(surface, self.ok_rect, "OK", self.accent, _lighten(self.accent))


def _show_message_standalone(title, message, tk_parent, kind, on_result):
    _run_blocking(lambda surf: _MessageModal(surf, title, message, None, kind), tk_parent)
    if on_result:
        on_result()


def show_message(title, message, tk_parent=None, kind="info", on_result=None):
    """Drop-in replacement for messagebox.showinfo / showwarning / showerror.

    `kind` picks the accent colour: "info", "success", "warning", or "error".
    on_result, if given, is called (with no arguments) once the user dismisses it.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _show_message_standalone(title, message, tk_parent, kind, on_result)
        return

    modal_stack.push(_MessageModal(surface, title, message, on_result, kind))


def show_info(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="info", on_result=on_result)


def show_success(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="success", on_result=on_result)


def show_warning(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="warning", on_result=on_result)


def show_error(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="error", on_result=on_result)


_LINK_COLOR = (100, 100, 255)
_LINK_HOVER_COLOR = (255, 255, 0)


class _PersonInfoModal(_BaseModal):
    """Popup for a Credits entry: a title, an optional free-text info section,
    and an optional list of clickable links below it."""

    BOX_MAX_W = 560
    BOX_MIN_H = 220
    BOX_CHROME_H = 180   # 110 of chrome plus the 70 the Close row occupies
    BORDER_COLOR = _KIND_ACCENTS["info"]
    BORDER_WIDTH = 3
    PASSES_RESULT = False

    def __init__(self, surface, name, info_text, links, on_result, align="center"):
        self.align = align if align in ("left", "center", "right") else "center"
        self.BODY_ALIGN = self.align
        self.links = links or []
        self.link_font = fonts.get("normal")

        links_h = len(self.links) * (self.link_font.get_height() + 8)
        super().__init__(surface, name, info_text, on_result,
                         extra_h=links_h + (20 if self.links else 0))

        self.name = name
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)
        self.text_y_start = self.box_rect.y + self.BODY_DY

        left_x, right_x = self.box_rect.x + 40, self.box_rect.right - 40
        self.link_rects = []
        y = self.text_y_start + self.body_height() + (20 if self.links else 0)
        for link in self.links:
            w = self.link_font.size(link.get("text", ""))[0]
            if self.align == "left":
                x = left_x
            elif self.align == "right":
                x = right_x - w
            else:
                x = self.box_rect.centerx - w // 2
            self.link_rects.append(pygame.Rect(x, y, w, self.link_font.get_height()))
            y += self.link_font.get_height() + 8

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                                 pygame.K_SPACE, _back_key()):
                    self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()
                    return
                for rect, link in zip(self.link_rects, self.links):
                    if link.get("url") and rect.collidepoint(event.pos):
                        webbrowser.open(link["url"])
                        return

    def draw_content(self, surface):
        mx, my = pygame.mouse.get_pos()
        for rect, link in zip(self.link_rects, self.links):
            has_url = bool(link.get("url"))
            is_hovered = has_url and rect.collidepoint(mx, my)
            color = _LINK_HOVER_COLOR if is_hovered else (_LINK_COLOR if has_url else c.UI_TEXT_LIGHT)
            surface.blit(self.link_font.render(link.get("text", ""), True, color), rect.topleft)
            if is_hovered:
                pygame.draw.line(surface, color, (rect.left, rect.bottom), (rect.right, rect.bottom), 2)

        accent = _KIND_ACCENTS["info"]
        self.draw_button(surface, self.ok_rect, "Close", accent, _lighten(accent))


def _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result):
    _run_blocking(lambda surf: _PersonInfoModal(surf, name, info_text, links, None, align),
                  tk_parent)
    if on_result:
        on_result()


def show_person_info(name, info_text="", links=None, align="center", tk_parent=None, on_result=None):
    """Popup with free-text info about `name`, plus a list of clickable links below it.

    links is a list of {"text": str, "url": str} dicts; each renders as its own
    clickable line and opens its url in a browser when clicked. align controls
    the info text's horizontal alignment: "left", "center" (default), or "right".
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result)
        return

    modal_stack.push(_PersonInfoModal(surface, name, info_text, links, on_result, align))
