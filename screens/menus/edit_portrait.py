"""Main menu portrait editor: picks the portrait and sets its button gradient."""

import pygame

import data.constants as c
from ui.dialogs import pickers
from ui.navigation.game_state import GameState
from ui.widgets import ui_elements
from ui.widgets.ui_elements import Button, Slider, make_back_button

# --- Layout ---
PREVIEW_RECT = pygame.Rect(80, 110, 480, 460)
PREVIEW_FLOOR_PAD = 20
CONTROLS_X = 640
CONTROLS_Y = 150
CONTROLS_GAP_Y = 70
SLIDER_W = 400
SLIDER_LABEL_PAD = 25
PREVIEW_COLOR = (28, 34, 45)
PREVIEW_BORDER = (80, 125, 170)


class Edit_Portrait(GameState):
    """The Menu owns the portrait settings and their saving; this screen is the
    editor for them, so the menu shows every change as soon as the player goes back."""

    back_state = "MENU"
    title = "Edit Portrait"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self._strength_changed = False
        # Controls are built by refresh_ui() on entry, when the menu exists.

    @property
    def menu(self):
        return self.controller.states["MENU"]

    def open_picker(self):
        menu = self.menu
        pickers.open_character_picker(self, menu.hildehrand_choice, menu.set_hildehrand_choice)

    def toggle_gradient(self):
        self.menu.toggle_hildehrand_gradient()
        self.refresh_ui()

    def set_strength(self, strength):
        self.menu.set_hildehrand_gradient_strength(strength)
        self._strength_changed = True

    def additional_events(self, event):
        # Saving on every slider step would rewrite the file dozens of times per drag.
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._strength_changed:
            self._strength_changed = False
            self.menu.save_hildehrand_settings()

    def refresh_ui(self):
        menu = self.menu
        enabled = menu.hildehrand_gradient
        self.elements = [
            make_back_button(self.exit_screen),
            Button(CONTROLS_X, CONTROLS_Y, "medium", "purple", "Choose Portrait", self.open_picker),
            Button(CONTROLS_X, CONTROLS_Y + CONTROLS_GAP_Y, "medium", "green" if enabled else "red",
                   f"Gradient: {'ON' if enabled else 'OFF'}", self.toggle_gradient),
            Slider(CONTROLS_X, CONTROLS_Y + 2 * CONTROLS_GAP_Y + SLIDER_LABEL_PAD, SLIDER_W,
                   "Gradient Strength", menu.hildehrand_gradient_strength, self.set_strength,
                   visual_max=c.HILDEHRAND_GRADIENT_MAX_STRENGTH,
                   allowed_max=c.HILDEHRAND_GRADIENT_MAX_STRENGTH),
        ]

    def additional_draw(self, surface):
        ui_elements.draw_pixel_panel(surface, PREVIEW_RECT, PREVIEW_COLOR, PREVIEW_BORDER, gradient_strength=0.0)
        image = self.menu.hildehrand_image
        if image:
            feet = (PREVIEW_RECT.centerx, PREVIEW_RECT.bottom - PREVIEW_FLOOR_PAD)
            old_clip = surface.get_clip()
            surface.set_clip(PREVIEW_RECT.clip(old_clip))
            surface.blit(image, image.get_rect(midbottom=feet))
            surface.set_clip(old_clip)
