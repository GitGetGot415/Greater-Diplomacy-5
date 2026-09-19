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
CARD_HEIGHT = 450
CARD_HEADER_Y = CARD_TOP_Y + 18
CARD_IMAGE_CENTER_Y = CARD_TOP_Y + 108
CARD_ACTION_START_Y = CARD_TOP_Y + 145
CARD_ACTION_GAP_Y = 58
WARNING_TOP_Y = CARD_TOP_Y + CARD_HEIGHT + 22
MOUSE_IMAGE_DIR = os.path.join(c.ASSETS_ROOT_DIR, "mouse")


def mouse_control_warnings(actions):
    """Describe overlapping gestures without rejecting an intentional setup."""
    warnings = []
    for _number, button, label in c.MOUSE_BUTTONS:
        assigned = actions[button]
        if assigned["box_select_units"] and (
                assigned["pan_map"] or assigned["pan_map_outside_orders"]):
            warnings.append(
                f"{label} mouse: box-selecting also pans the map, which can make selection difficult.")
        # ``pan_map_outside_orders`` cannot overlap an order click because the
        # two actions deliberately apply in different workspaces. Full map pan
        # can, so only that combination warrants a warning.
        if assigned["issue_orders"] and assigned["pan_map"]:
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
        self.controller.mouse_button_actions = actions
        c.apply_runtime_settings({"mouse_button_actions": actions})
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
                self.elements.append(
                    Button(card.centerx - c.SIZES["setting_option"][0] // 2,
                           CARD_ACTION_START_Y + row * CARD_ACTION_GAP_Y,
                           "setting_option", "green" if enabled else "red",
                           f"{label}: {'ON' if enabled else 'OFF'}",
                           lambda b=button, a=action: self.toggle_action(b, a),
                           font_preset="tiny"))

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
                y = (CARD_ACTION_START_Y + row * CARD_ACTION_GAP_Y
                     + c.SIZES["setting_option"][1] + 2)
                surface.blit(help_surface, help_surface.get_rect(center=(card.centerx, y)))

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
