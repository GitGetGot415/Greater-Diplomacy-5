"""Editable map-mouse gestures, backed by one persisted action matrix."""

import os

import pygame

import data.constants as c
from data import queries
from gameState import GameState
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars
from ui_elements import Button, make_back_button


CARD_MARGIN_X = 32
CARD_GAP_X = 18
CARD_TOP_Y = 88
CARD_HEIGHT = 390
CARD_HEADER_Y = CARD_TOP_Y + 18
CARD_IMAGE_CENTER_Y = CARD_TOP_Y + 90
CARD_ACTION_START_Y = CARD_TOP_Y + 145
CARD_ACTION_GAP_Y = 60
WARNING_TOP_Y = CARD_TOP_Y + CARD_HEIGHT + 22
MOUSE_SETTINGS_RESET_Y = c.SCREEN_HEIGHT - 70
MOUSE_IMAGE_DIR = os.path.join(c.ASSETS_ROOT_DIR, "mouse")
MOUSE_ACTION_BUTTON_SIZE = (250, 32)
MOUSE_PAN_BUTTON_SIZE = (160, 32)
MOUSE_EXCLUDE_BUTTON_SIZE = (32, 32)
MOUSE_PAN_INDENT_X = 8
MOUSE_PAN_EXCLUDE_GAP_X = 6
MOUSE_ACTION_HELP_GAP_Y = 8
PAN_ACTION = "pan_map"
EXCLUDE_ORDERS_ACTION = "exclude_orders"
EXCLUDE_ORDERS_LABEL = "Exclude Orders"


def mouse_control_warnings(actions):
    """Describe overlapping gestures without rejecting an intentional setup."""
    warnings = []
    for _number, button, label in c.MOUSE_BUTTONS:
        assigned = actions[button]
        if assigned["box_select_units"] and assigned[PAN_ACTION]:
            warnings.append(
                f"{label} mouse: box-selecting also pans the map, which can make selection difficult.")
        # Excluding Orders makes the two gestures context-exclusive; full map
        # pan can overlap a move click, so only that combination warrants a warning.
        if (assigned["issue_orders"] and assigned[PAN_ACTION]
                and not assigned[EXCLUDE_ORDERS_ACTION]):
            warnings.append(
                f"{label} mouse: giving move orders also pans the map, which can make orders difficult.")
    return warnings


class Mouse_Settings(GameState):
    """Settings sub-screen for actions assigned to left, middle and right mouse."""

    back_state = "SETTINGS"
    title = "Mouse Settings"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self.refresh_ui()

    @staticmethod
    def _card_rect(index):
        available_width = c.SCREEN_WIDTH - (2 * CARD_MARGIN_X) - (2 * CARD_GAP_X)
        card_width = available_width // 3
        return pygame.Rect(CARD_MARGIN_X + index * (card_width + CARD_GAP_X), CARD_TOP_Y,
                           card_width, CARD_HEIGHT)

    def toggle_action(self, button, action):
        actions = c.normalize_mouse_button_actions(self.controller.mouse_button_actions)
        actions[button][action] = not actions[button][action]
        if action == PAN_ACTION and not actions[button][action]:
            actions[button][EXCLUDE_ORDERS_ACTION] = False
        self.controller.mouse_button_actions = actions
        c.apply_runtime_settings({"mouse_button_actions": actions})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def reset_defaults(self):
        """Restore the tutorial's original left/middle/right mouse layout."""
        self.controller.mouse_button_actions = c.default_mouse_button_actions()
        c.apply_runtime_settings({"mouse_button_actions": self.controller.mouse_button_actions})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def refresh_ui(self):
        actions = c.normalize_mouse_button_actions(self.controller.mouse_button_actions)
        # A save loaded from an older build receives its new defaults before
        # the player can toggle anything, so the screen and live controls agree.
        self.controller.mouse_button_actions = actions
        self.elements = [make_back_button(self.exit_screen)]
        for index, (_number, button, _label) in enumerate(c.MOUSE_BUTTONS):
            card = self._card_rect(index)
            for row, (action, label, _help) in enumerate(c.MOUSE_CONTROL_ACTIONS):
                enabled = actions[button][action]
                pan_label = "Pan outside Orders" if (
                    action == PAN_ACTION and actions[button][EXCLUDE_ORDERS_ACTION]) else label
                action_x = card.centerx - MOUSE_ACTION_BUTTON_SIZE[0] // 2
                option_x = (action_x + MOUSE_PAN_INDENT_X if action == PAN_ACTION
                            else action_x)
                option_size = (MOUSE_PAN_BUTTON_SIZE if action == PAN_ACTION
                               else MOUSE_ACTION_BUTTON_SIZE)
                self.elements.append(
                    Button(option_x,
                           CARD_ACTION_START_Y + row * CARD_ACTION_GAP_Y,
                           option_size, "green" if enabled else "red",
                           f"{pan_label}: {'ON' if enabled else 'OFF'}",
                           lambda b=button, a=action: self.toggle_action(b, a),
                           font_preset="tiny"))
                if action == PAN_ACTION:
                    exclude = Button(
                        option_x + MOUSE_PAN_BUTTON_SIZE[0] + MOUSE_PAN_EXCLUDE_GAP_X,
                        CARD_ACTION_START_Y + row * CARD_ACTION_GAP_Y,
                        MOUSE_EXCLUDE_BUTTON_SIZE,
                        "green" if actions[button][EXCLUDE_ORDERS_ACTION] else "red",
                        "X" if actions[button][EXCLUDE_ORDERS_ACTION] else "",
                        lambda b=button: self.toggle_action(b, EXCLUDE_ORDERS_ACTION),
                        font_preset="tiny")
                    exclude.disabled = not enabled
                    self.elements.append(exclude)
        self.elements.append(
            Button(c.SCREEN_WIDTH // 2 - c.SIZES["medium"][0] // 2,
                   MOUSE_SETTINGS_RESET_Y, "medium", "red", "Reset Defaults",
                   self.reset_defaults)
        )

    def additional_draw(self, surface):
        title_font = fonts.get("heading2")
        label_font = fonts.get("small")
        body_font = fonts.get("tiny")
        actions = c.normalize_mouse_button_actions(self.controller.mouse_button_actions)

        for index, (_number, button, label) in enumerate(c.MOUSE_BUTTONS):
            card = self._card_rect(index)
            pygame.draw.rect(surface, (28, 34, 45), card, border_radius=6)
            pygame.draw.rect(surface, (80, 125, 170), card, 2, border_radius=6)
            heading = title_font.render(f"{label} Mouse", True, (145, 210, 255))
            surface.blit(heading, heading.get_rect(center=(card.centerx, CARD_HEADER_Y)))

            image = ui_bars.get_ui_image(f"{label}.png", directory=MOUSE_IMAGE_DIR)
            scale = min(58 / image.get_width(), 68 / image.get_height())
            image = pygame.transform.smoothscale(
                image, (max(1, round(image.get_width() * scale)),
                        max(1, round(image.get_height() * scale))))
            surface.blit(image, image.get_rect(center=(card.centerx, CARD_IMAGE_CENTER_Y)))

            for row, (_action, _name, help_text) in enumerate(c.MOUSE_CONTROL_ACTIONS):
                help_surface = body_font.render(help_text, True, (185, 195, 207))
                button_height = (MOUSE_PAN_BUTTON_SIZE[1] if _action == PAN_ACTION
                                 else MOUSE_ACTION_BUTTON_SIZE[1])
                y = (CARD_ACTION_START_Y + row * CARD_ACTION_GAP_Y
                     + button_height + MOUSE_ACTION_HELP_GAP_Y)
                surface.blit(help_surface, help_surface.get_rect(center=(card.centerx, y)))
                if _action == PAN_ACTION:
                    exclude_color = ((185, 195, 207) if actions[button][PAN_ACTION]
                                     else (105, 110, 120))
                    exclude_x = (card.centerx - MOUSE_ACTION_BUTTON_SIZE[0] // 2
                                 + MOUSE_PAN_INDENT_X + MOUSE_PAN_BUTTON_SIZE[0]
                                 + MOUSE_PAN_EXCLUDE_GAP_X + MOUSE_EXCLUDE_BUTTON_SIZE[0] + 5)
                    label_y = CARD_ACTION_START_Y + row * CARD_ACTION_GAP_Y + 1
                    for line in EXCLUDE_ORDERS_LABEL.split():
                        exclude_label = body_font.render(line, True, exclude_color)
                        surface.blit(exclude_label, (exclude_x, label_y))
                        label_y += exclude_label.get_height() - 1

        warnings = mouse_control_warnings(actions)
        if warnings:
            heading = label_font.render("Control warning", True, (255, 195, 85))
            surface.blit(heading, (CARD_MARGIN_X, WARNING_TOP_Y))
            for index, warning in enumerate(warnings):
                line = body_font.render(warning, True, (255, 220, 155))
                surface.blit(line, (CARD_MARGIN_X, WARNING_TOP_Y + 24 + index * 20))
        else:
            line = body_font.render("No overlapping mouse gestures are enabled.",
                                    True, (135, 215, 155))
            surface.blit(line, (CARD_MARGIN_X, WARNING_TOP_Y))
