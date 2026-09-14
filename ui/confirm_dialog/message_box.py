import pygame
import os
from data import queries
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _lighten, _run_blocking
from ui.bars import ui_bars
import data.constants as c
from map_logic.rendering.font_manager import fonts

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


class _NavigationIntroPopup:
    """Draggable, live-map navigation guide shown once for fresh games.

    Unlike a modal-stack dialog, this belongs to the map screen itself.  The
    player can still see the map and HUD behind it, and clicks outside the
    panel continue to use the normal map controls.
    """
    WIDTH = 720
    HEIGHT = 370
    HEADER_H = 46
    BORDER_COLOR = _KIND_ACCENTS["info"]
    MOUSE_DIR = os.path.join(c.ASSETS_ROOT_DIR, "mouse")
    BUTTONS = (
        ("Left.png", "LEFT MOUSE", (
            "Click a unit stack or province.",
            "Use Orders to toggle individual units.",
        )),
        ("Middle.png", "MIDDLE MOUSE", (
            "Hold and drag to pan the map.",
            "Scroll up or down to zoom in or out."
        )),
        ("Right.png", "RIGHT MOUSE", (
            "Drag in Units view to box-select units.",
            "Right-click a province to move selected units.",
        )),
    )

    def __init__(self, map_screen):
        self.map_screen = map_screen
        self.rect = pygame.Rect(0, 0, self.WIDTH, self.HEIGHT)
        self.rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.dont_show_again = False
        self.is_dragging = False
        self.drag_offset = (0, 0)
        self.title_font = fonts.get("heading2")
        self.label_font = fonts.get("small")
        self.body_font = fonts.get("tiny")
        self._layout()

    def _layout(self):
        self.header_rect = pygame.Rect(self.rect.x, self.rect.y,
                                       self.rect.width, self.HEADER_H)
        self.checkbox_rect = pygame.Rect(self.rect.x + 30, self.rect.bottom - 43,
                                         20, 20)
        self.continue_rect = pygame.Rect(self.rect.right - 150, self.rect.bottom - 51,
                                         120, 32)

    def _persist_checkbox(self):
        settings = dict(queries.get_settings() or {})
        settings["show_intro_popup"] = not self.dont_show_again
        queries.save_cached_json("settings", settings)

    def dismiss(self):
        if getattr(self.map_screen, "navigation_intro_popup", None) is self:
            self.map_screen.navigation_intro_popup = None

    def _move_to(self, x, y):
        self.rect.topleft = (x, y)
        display = pygame.display.get_surface()
        bounds = display.get_rect() if display is not None else pygame.Rect(
            0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        self.rect.clamp_ip(bounds)
        self._layout()

    def handle_event(self, event):
        """Handle popup-local input; True prevents that event reaching the map."""
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, _back_key()):
                self.dismiss()
                return True
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.continue_rect.collidepoint(event.pos):
                self.dismiss()
                return True
            if self.checkbox_rect.collidepoint(event.pos):
                self.dont_show_again = not self.dont_show_again
                self._persist_checkbox()
                return True
            if self.header_rect.collidepoint(event.pos):
                self.is_dragging = True
                self.drag_offset = (event.pos[0] - self.rect.x,
                                    event.pos[1] - self.rect.y)
                return True
            return self.rect.collidepoint(event.pos)

        if event.type == pygame.MOUSEMOTION and self.is_dragging:
            self._move_to(event.pos[0] - self.drag_offset[0],
                          event.pos[1] - self.drag_offset[1])
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_dragging = self.is_dragging
            self.is_dragging = False
            return was_dragging or self.rect.collidepoint(event.pos)

        if hasattr(event, "pos"):
            return self.rect.collidepoint(event.pos)
        return False

    def draw(self, surface):
        pygame.draw.rect(surface, (34, 38, 49), self.rect, border_radius=6)
        pygame.draw.rect(surface, self.BORDER_COLOR, self.rect, 2, border_radius=6)

        title = self.title_font.render("Map Navigation", True, (255, 255, 255))
        surface.blit(title, title.get_rect(center=(self.rect.centerx, self.header_rect.centery)))

        column_w = self.rect.width // 3
        image_y = self.rect.y + 68
        text_y = self.rect.y + 177
        for index, (filename, heading, lines) in enumerate(self.BUTTONS):
            center_x = self.rect.x + column_w * index + column_w // 2
            image = ui_bars.get_ui_image(filename, directory=self.MOUSE_DIR)
            # The supplied button images are deliberately tall and narrow;
            # fit them into this slot with one scale factor, never stretch
            # them to fill both dimensions.
            scale = min(72 / image.get_width(), 84 / image.get_height())
            scaled_size = (max(1, round(image.get_width() * scale)),
                           max(1, round(image.get_height() * scale)))
            image = pygame.transform.smoothscale(image, scaled_size)
            surface.blit(image, image.get_rect(center=(center_x, image_y + 42)))

            heading_surf = self.label_font.render(heading, True, (130, 205, 255))
            surface.blit(heading_surf, heading_surf.get_rect(center=(center_x, text_y)))
            line_y = text_y + 24
            for line in lines:
                line_surf = self.body_font.render(line, True, (225, 225, 225))
                surface.blit(line_surf, line_surf.get_rect(center=(center_x, line_y)))
                line_y += self.body_font.get_height() + 3

        pygame.draw.rect(surface, (230, 230, 230), self.checkbox_rect, 2)
        if self.dont_show_again:
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topleft,
                             self.checkbox_rect.bottomright, 3)
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topright,
                             self.checkbox_rect.bottomleft, 3)
        label = self.body_font.render("Don't show this popup again", True, (225, 225, 225))
        surface.blit(label, (self.checkbox_rect.right + 9, self.checkbox_rect.y + 2))

        hovered = self.continue_rect.collidepoint(pygame.mouse.get_pos())
        color = _lighten(self.BORDER_COLOR) if hovered else self.BORDER_COLOR
        pygame.draw.rect(surface, color, self.continue_rect, border_radius=4)
        button = self.label_font.render("Continue", True, (255, 255, 255))
        surface.blit(button, button.get_rect(center=self.continue_rect.center))


def _show_message_standalone(title, message, tk_parent, kind, on_result):
    _run_blocking(lambda surf: _MessageModal(surf, title, message, None, kind), tk_parent)
    if on_result:
        on_result()


def show_message(title, message, tk_parent=None, kind="info", on_result=None):
    """Drop-in replacement for messagebox.showinfo / showwarning / showerror.

    `kind` picks the accent color: "info", "success", "warning", or "error".
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


def show_navigation_intro(map_screen):
    """Show the fresh-game navigation tutorial over the active map and HUD."""
    map_screen.navigation_intro_popup = _NavigationIntroPopup(map_screen)
