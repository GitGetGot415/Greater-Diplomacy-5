import pygame
import os
from data import queries
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _lighten, _run_blocking
from ui.bars import ui_bars
import data.constants as c
from map_logic.rendering.font_manager import fonts
import ui_elements
from ui.text_utils import wrap_text

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
    SUBTITLE_Y_OFFSET = 55
    SUBTITLE_SIDE_PADDING = 24
    SUBTITLE_LINE_GAP = 2
    # This is what edits how offset the tutorial popup is when it spawns!
    INITIAL_CENTER_Y_OFFSET = -32
    BORDER_COLOR = _KIND_ACCENTS["info"]
    MOUSE_DIR = os.path.join(c.ASSETS_ROOT_DIR, "mouse")
    NAVIGATION_BUTTONS = (
        ("Left.png", "LEFT MOUSE", (
            "Click a unit stack to select it; Shift-click adds more.",
            "Drag in Units view to box-select units."
        )),
        ("Middle.png", "MIDDLE MOUSE", (
            "Hold and drag to pan the map.",
            "Scroll up or down to zoom in or out."
        )),
        ("Right.png", "RIGHT MOUSE", (
            "Right-click a province to move selected units.",
            "Shift+right-click queues a waypoint.",
        )),
    )
    MAP_UI_BUTTONS = (
        ("Terrain", "terrain", "Shows the terrain map."),
        ("Political", "political", "Shows the actual countries on the map."),
        ("Relations", "relations", "Shows diplomatic relations."),
        ("Cores", "core", "Shows the territory each country has cores on."),
        ("Factions", "faction", "Shows factions."),
        ("Resources", "resource", "Shows province resources."),
        ("Blank", "blank", "Hides the secondary map overlay."),
        ("Units", "unit", "Shows unit stacks and their commands."),
        ("Economy", "industry", "Shows economic map information."),
        ("Names", "names", "Shows or hides country names."),
    )
    ARMY_STEPS = (
        ("Select units", "Click stacks or left-click and drag to select multiple stacks in Units view."),
        ("Create an army", "In Orders, click + Create Army in the Army tray. (Located on the right side of the screen)"),
        ("Personalize", "Click a card to select the units in said army. Pressing the E button edits its name and emblem."),
        ("Need to Assign more units?", "With units selected, right-click an army card."),
    )
    DIPLOMACY_STEPS = (
        ("Mail", "mail", "Open the Mail tab (located to the left) to read, reply to, or start conversations."),
        ("Country actions", "political", "Click another country's tile to see available diplomatic actions you can take against them."),
    )
    PAGE_TITLES = ("Map Navigation", "Map UI", "Other Countries", "Armies")
    PAGE_SUBTITLES = (
        "Your country is centered automatically when a game opens or after you choose it. If you're familiar with how HOI4 map controls work, then this should be very easy to understand.",
        "These buttons are important! Located on the bottom left of the screen, they edit the appearance of the map, giving you the information you need to play effectively.",
        "Reach other countries through the Mail tab or directly from their territory on the map.",
        "Learn how to create, organize, and personalize armies. For now, this feature is purely decorative and serves only to organize your units.",
    )

    def __init__(self, map_screen):
        self.map_screen = map_screen
        self.rect = pygame.Rect(0, 0, self.WIDTH, self.HEIGHT)
        self.rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2 + self.INITIAL_CENTER_Y_OFFSET)
        self.page_index = 0
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
        self.close_rect = pygame.Rect(self.rect.right - 34, self.rect.y + 11,
                                      22, 22)
        self.checkbox_rect = pygame.Rect(self.rect.x + 30, self.rect.bottom - 43,
                                         20, 20)
        self.prev_rect = pygame.Rect(self.rect.right - 118, self.rect.bottom - 51,
                                     36, 32)
        self.next_rect = pygame.Rect(self.rect.right - 72, self.rect.bottom - 51,
                                     36, 32)

    def _subtitle_lines(self):
        """Wrap the current page subtitle inside the draggable popup's bounds."""
        return wrap_text(
            self.PAGE_SUBTITLES[self.page_index], self.body_font,
            self.rect.width - (2 * self.SUBTITLE_SIDE_PADDING))

    def _persist_checkbox(self):
        settings = dict(queries.get_settings() or {})
        settings["show_intro_popup"] = not self.dont_show_again
        queries.save_cached_json("settings", settings)

    def dismiss(self):
        if getattr(self.map_screen, "navigation_intro_popup", None) is self:
            self.map_screen.navigation_intro_popup = None

    def change_page(self, direction):
        self.page_index = max(0, min(
            self.page_index + direction, len(self.PAGE_TITLES) - 1))

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
            # Escape is handled globally by the map.  In particular, it closes
            # the province menu before this popup receives the same event; do
            # not mistake that close for a request to dismiss the tutorial.
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.dismiss()
                return True
            return False

        # Middle/right mouse belong to map pan and unit selection even when
        # their drag crosses this popup.  Only left mouse operates its chrome.
        if (event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)
                and getattr(event, "button", None) in (2, 3)):
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_rect.collidepoint(event.pos):
                self.dismiss()
                return True
            if self.prev_rect.collidepoint(event.pos):
                self.change_page(-1)
                return True
            if self.next_rect.collidepoint(event.pos):
                self.change_page(1)
                return True
            if self.checkbox_rect.collidepoint(event.pos):
                self.dont_show_again = not self.dont_show_again
                self._persist_checkbox()
                return True
            if self.rect.collidepoint(event.pos):
                self.is_dragging = True
                self.drag_offset = (event.pos[0] - self.rect.x,
                                    event.pos[1] - self.rect.y)
                return True
            return False

        if event.type == pygame.MOUSEMOTION:
            if self.is_dragging:
                self._move_to(event.pos[0] - self.drag_offset[0],
                              event.pos[1] - self.drag_offset[1])
                return True
            buttons = getattr(event, "buttons", ())
            middle_or_right_held = ((len(buttons) > 1 and buttons[1])
                                    or (len(buttons) > 2 and buttons[2])
                                    or getattr(self.map_screen, "unit_selection_drag", None)
                                    or getattr(getattr(self.map_screen, "camera", None),
                                               "_middle_drag_last_pos", None) is not None)
            if middle_or_right_held:
                return False
            return self.rect.collidepoint(event.pos)

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

        page_number = self.body_font.render(
            f"{self.page_index + 1}/{len(self.PAGE_TITLES)}", True, (190, 205, 220))
        surface.blit(page_number, (self.rect.x + 14, self.rect.y + 16))

        title = self.title_font.render(self.PAGE_TITLES[self.page_index], True, (255, 255, 255))
        surface.blit(title, title.get_rect(center=(self.rect.centerx, self.header_rect.centery)))
        subtitle_lines = self._subtitle_lines()
        subtitle_line_h = self.body_font.get_height() + self.SUBTITLE_LINE_GAP
        subtitle_y = self.rect.y + self.SUBTITLE_Y_OFFSET
        for line in subtitle_lines:
            subtitle = self.body_font.render(line, True, (205, 215, 225))
            surface.blit(subtitle, subtitle.get_rect(center=(self.rect.centerx, subtitle_y)))
            subtitle_y += subtitle_line_h
        content_y_offset = max(0, len(subtitle_lines) - 1) * subtitle_line_h

        pygame.draw.rect(surface, (150, 0, 0), self.close_rect)
        pygame.draw.rect(surface, (255, 255, 255), self.close_rect, 1)
        x_label = self.body_font.render("X", True, (255, 255, 255))
        surface.blit(x_label, x_label.get_rect(center=self.close_rect.center))

        if self.page_index == 0:
            column_w = self.rect.width // 3
            image_y = self.rect.y + 88 + content_y_offset
            text_y = self.rect.y + 197 + content_y_offset
            for index, (filename, heading, lines) in enumerate(self.NAVIGATION_BUTTONS):
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
        elif self.page_index == 1:
            column_x = (self.rect.x + 35, self.rect.centerx + 18)
            row_h = 44
            for index, (label, icon_name, description) in enumerate(self.MAP_UI_BUTTONS):
                column, row = divmod(index, 5)
                x = column_x[column]
                y = self.rect.y + 92 + content_y_offset + row * row_h
                icon = ui_elements.UI_ICONS.get(icon_name)
                if icon:
                    scale = min(28 / icon.get_width(), 28 / icon.get_height())
                    icon_size = (max(1, round(icon.get_width() * scale)),
                                 max(1, round(icon.get_height() * scale)))
                    icon = pygame.transform.smoothscale(icon, icon_size)
                    surface.blit(icon, icon.get_rect(center=(x + 14, y + 18)))
                else:
                    # The registry is populated during game bootstrap. Keep a
                    # stable reserved icon slot for lightweight test/tool views.
                    pygame.draw.rect(surface, (75, 85, 100), (x, y + 4, 28, 28), 1)
                label_surf = self.label_font.render(label, True, (130, 205, 255))
                surface.blit(label_surf, (x + 36, y))
                desc_surf = self.body_font.render(description, True, (225, 225, 225))
                surface.blit(desc_surf, (x + 36, y + self.label_font.get_height() + 2))
        elif self.page_index == 2:
            step_x = self.rect.x + 56
            step_y = self.rect.y + 108 + content_y_offset
            step_gap = 72
            for index, (heading, icon_name, description) in enumerate(self.DIPLOMACY_STEPS, start=1):
                y = step_y + (index - 1) * step_gap
                icon = ui_elements.UI_ICONS.get(icon_name)
                if icon:
                    scale = min(28 / icon.get_width(), 28 / icon.get_height())
                    icon_size = (max(1, round(icon.get_width() * scale)),
                                 max(1, round(icon.get_height() * scale)))
                    icon = pygame.transform.smoothscale(icon, icon_size)
                    surface.blit(icon, icon.get_rect(center=(step_x, y + 13)))
                else:
                    pygame.draw.rect(surface, (75, 85, 100),
                                     (step_x - 14, y - 1, 28, 28), 1)
                heading_surf = self.label_font.render(heading, True, (130, 205, 255))
                surface.blit(heading_surf, (step_x + 25, y))
                description_surf = self.body_font.render(description, True, (225, 225, 225))
                surface.blit(description_surf,
                             (step_x + 25, y + self.label_font.get_height() + 2))
        else:
            step_x = self.rect.x + 56
            step_y = self.rect.y + 91 + content_y_offset
            step_gap = 51
            for index, (heading, description) in enumerate(self.ARMY_STEPS, start=1):
                y = step_y + (index - 1) * step_gap
                pygame.draw.circle(surface, (70, 115, 160), (step_x, y + 13), 14)
                number = self.label_font.render(str(index), True, (255, 255, 255))
                surface.blit(number, number.get_rect(center=(step_x, y + 13)))
                heading_surf = self.label_font.render(heading, True, (130, 205, 255))
                surface.blit(heading_surf, (step_x + 25, y))
                description_surf = self.body_font.render(description, True, (225, 225, 225))
                surface.blit(description_surf,
                             (step_x + 25, y + self.label_font.get_height() + 2))

        pygame.draw.rect(surface, (230, 230, 230), self.checkbox_rect, 2)
        if self.dont_show_again:
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topleft,
                             self.checkbox_rect.bottomright, 3)
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topright,
                             self.checkbox_rect.bottomleft, 3)
        label = self.body_font.render("Don't show this popup when starting a game", True, (225, 225, 225))
        surface.blit(label, (self.checkbox_rect.right + 9, self.checkbox_rect.y + 2))

        for rect, label, enabled in (
                (self.prev_rect, "<", self.page_index > 0),
                (self.next_rect, ">", self.page_index < len(self.PAGE_TITLES) - 1)):
            hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
            color = _lighten(self.BORDER_COLOR) if hovered else (
                self.BORDER_COLOR if enabled else (70, 75, 85))
            pygame.draw.rect(surface, color, rect, border_radius=4)
            button = self.label_font.render(label, True, (255, 255, 255) if enabled else (145, 145, 145))
            surface.blit(button, button.get_rect(center=rect.center))


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
