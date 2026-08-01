"""Pygame-rendered replacements for tkinter's messagebox.askyesno / simpledialog.askinteger.

Every call blocks until the user answers, exactly like the tkinter dialogs they
replace, so existing call sites (`if ask_yes_no(...): ...`) don't need to change shape.

If a pygame display is already running (the normal in-game case) the dialog is
drawn as an overlay on top of it. If no display exists yet (standalone tkinter
tools like data/editors/country_editor.py, run outside the game), a small
temporary pygame window is created just for the dialog and torn down afterward.
"""
import pygame
from map_logic.rendering.font_manager import fonts

_STANDALONE_SIZE = (520, 320)


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
    surface = pygame.display.get_surface()
    if surface is not None:
        return surface, False

    if not pygame.get_init():
        pygame.init()
    surface = pygame.display.set_mode(_STANDALONE_SIZE)
    pygame.display.set_caption("Confirm")
    return surface, True


def _release_surface(owns_display):
    if owns_display:
        pygame.display.quit()


def _wrap_text(text, font, max_width):
    lines = []
    for raw_line in text.split("\n"):
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if font.size(candidate)[0] <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def ask_yes_no(title, message, tk_parent=None, yes_label="Yes", no_label="No"):
    """Blocking pygame confirmation dialog. Returns True/False."""
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    title_font = fonts.get("heading2")
    msg_font = fonts.get("normal")
    btn_font = fonts.get("button")

    box_w = min(520, surface.get_width() - 40)
    lines = _wrap_text(message, msg_font, box_w - 40)
    box_h = max(200, 130 + len(lines) * (msg_font.get_height() + 2))
    box_rect = pygame.Rect(0, 0, box_w, box_h)
    box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

    yes_rect = pygame.Rect(box_rect.centerx - 140, box_rect.bottom - 55, 120, 40)
    no_rect = pygame.Rect(box_rect.centerx + 20, box_rect.bottom - 55, 120, 40)

    background = surface.copy()
    clock = pygame.time.Clock()
    result = False
    waiting = True

    try:
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    result = False
                    waiting = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                        result, waiting = True, False
                    elif event.key in (pygame.K_ESCAPE, pygame.K_n):
                        result, waiting = False, False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if yes_rect.collidepoint(event.pos):
                        result, waiting = True, False
                    elif no_rect.collidepoint(event.pos):
                        result, waiting = False, False

            surface.blit(background, (0, 0))
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))

            pygame.draw.rect(surface, (40, 40, 40), box_rect)
            pygame.draw.rect(surface, (200, 200, 200), box_rect, 2)

            title_surf = title_font.render(title, True, (255, 255, 255))
            surface.blit(title_surf, title_surf.get_rect(center=(box_rect.centerx, box_rect.y + 35)))

            y = box_rect.y + 75
            for line in lines:
                line_surf = msg_font.render(line, True, (210, 210, 210))
                surface.blit(line_surf, line_surf.get_rect(center=(box_rect.centerx, y)))
                y += msg_font.get_height() + 2

            mx, my = pygame.mouse.get_pos()
            yes_color = (0, 190, 0) if yes_rect.collidepoint(mx, my) else (0, 150, 0)
            no_color = (190, 0, 0) if no_rect.collidepoint(mx, my) else (150, 0, 0)
            pygame.draw.rect(surface, yes_color, yes_rect, border_radius=4)
            pygame.draw.rect(surface, no_color, no_rect, border_radius=4)

            yes_surf = btn_font.render(yes_label, True, (255, 255, 255))
            no_surf = btn_font.render(no_label, True, (255, 255, 255))
            surface.blit(yes_surf, yes_surf.get_rect(center=yes_rect.center))
            surface.blit(no_surf, no_surf.get_rect(center=no_rect.center))

            pygame.display.flip()
            clock.tick(60)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

    return result


def ask_integer(title, message, minvalue=None, maxvalue=None, initial=None, tk_parent=None):
    """Blocking pygame numeric-entry dialog. Returns an int, or None if cancelled."""
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    title_font = fonts.get("heading2")
    msg_font = fonts.get("normal")
    btn_font = fonts.get("button")

    box_w = min(480, surface.get_width() - 40)
    lines = _wrap_text(message, msg_font, box_w - 40)
    box_h = max(230, 120 + len(lines) * (msg_font.get_height() + 2) + 90)
    box_rect = pygame.Rect(0, 0, box_w, box_h)
    box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

    input_rect = pygame.Rect(box_rect.centerx - 100, box_rect.bottom - 110, 200, 40)
    ok_rect = pygame.Rect(box_rect.centerx - 140, box_rect.bottom - 55, 120, 40)
    cancel_rect = pygame.Rect(box_rect.centerx + 20, box_rect.bottom - 55, 120, 40)

    text = str(initial) if initial is not None else ""
    error_text = ""

    def _validate():
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

    background = surface.copy()
    clock = pygame.time.Clock()
    result = None
    waiting = True

    try:
        while waiting:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    result, waiting = None, False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        result, waiting = None, False
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        value, error_text = _validate()
                        if value is not None:
                            result, waiting = value, False
                    elif event.key == pygame.K_BACKSPACE:
                        text = text[:-1]
                        error_text = ""
                    elif event.unicode.isdigit() or (event.unicode == "-" and not text):
                        text += event.unicode
                        error_text = ""
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if ok_rect.collidepoint(event.pos):
                        value, error_text = _validate()
                        if value is not None:
                            result, waiting = value, False
                    elif cancel_rect.collidepoint(event.pos):
                        result, waiting = None, False

            surface.blit(background, (0, 0))
            overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            surface.blit(overlay, (0, 0))

            pygame.draw.rect(surface, (40, 40, 40), box_rect)
            pygame.draw.rect(surface, (200, 200, 200), box_rect, 2)

            title_surf = title_font.render(title, True, (255, 255, 255))
            surface.blit(title_surf, title_surf.get_rect(center=(box_rect.centerx, box_rect.y + 35)))

            y = box_rect.y + 75
            for line in lines:
                line_surf = msg_font.render(line, True, (210, 210, 210))
                surface.blit(line_surf, line_surf.get_rect(center=(box_rect.centerx, y)))
                y += msg_font.get_height() + 2

            pygame.draw.rect(surface, (20, 20, 20), input_rect)
            border_color = (220, 80, 80) if error_text else (200, 200, 200)
            pygame.draw.rect(surface, border_color, input_rect, 2)
            input_surf = msg_font.render(text or " ", True, (255, 255, 255))
            surface.blit(input_surf, input_surf.get_rect(midleft=(input_rect.x + 10, input_rect.centery)))

            if error_text:
                err_surf = fonts.get("small").render(error_text, True, (230, 100, 100))
                surface.blit(err_surf, err_surf.get_rect(center=(box_rect.centerx, input_rect.y - 14)))

            mx, my = pygame.mouse.get_pos()
            ok_color = (0, 190, 0) if ok_rect.collidepoint(mx, my) else (0, 150, 0)
            cancel_color = (190, 0, 0) if cancel_rect.collidepoint(mx, my) else (150, 0, 0)
            pygame.draw.rect(surface, ok_color, ok_rect, border_radius=4)
            pygame.draw.rect(surface, cancel_color, cancel_rect, border_radius=4)

            ok_surf = btn_font.render("OK", True, (255, 255, 255))
            cancel_surf = btn_font.render("Cancel", True, (255, 255, 255))
            surface.blit(ok_surf, ok_surf.get_rect(center=ok_rect.center))
            surface.blit(cancel_surf, cancel_surf.get_rect(center=cancel_rect.center))

            pygame.display.flip()
            clock.tick(60)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

    return result
