"""Main menu portrait editor: picks the portrait and sets its button gradient."""

import pygame

import data.constants as c
from data import queries
from ui.background_styles import PORTRAIT_EDITOR_STYLES
from ui.dialogs import pickers
from ui.navigation.screen import Screen
from ui.widgets import ui_elements
from ui.widgets.ui_elements import Button, Slider, make_back_button, make_toggle_button

# --- Layout ---
PREVIEW_RECT = pygame.Rect(80, 110, 480, 460)
PREVIEW_FLOOR_PAD = 20
CONTROLS_X = 640
CONTROLS_Y = 150
CONTROLS_GAP_Y = 70
BUTTON_SLIDER_GAP_X = 30
SLIDER_W = 300
SLIDER_LABEL_PAD = 10   # Lowers a slider so its label, drawn above it, lines up with the button.
PREVIEW_BORDER = (80, 125, 170)


class _BandSlider(Slider):
    """Whole-number slider: shows and reports the band count, never below the minimum."""

    @staticmethod
    def bands_for(value):
        return max(c.HILDEHRAND_GRADIENT_MIN_BANDS, round(value))

    def get_display_string(self):
        if self.disabled:
            return super().get_display_string()
        return f"{self.text}: {self.bands_for(self.value)}"


class Edit_Portrait(Screen):
    """The Menu owns the portrait settings and their saving; this screen is the
    editor for them, so the menu shows every change as soon as the player goes back."""

    back_state = "MENU"
    title = "Edit Portrait"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self._slider_changed = False
        self.strength_slider = None
        self.bands_slider = None

    def on_enter(self, app, previous):
        self.refresh_ui()
        # Controls are built by refresh_ui() on entry, when the menu exists.

    @property
    def menu(self):
        return self.controller.states["MENU"]

    def open_picker(self):
        menu = self.menu
        pickers.open_character_picker(self, menu.hildehrand_choice, menu.set_hildehrand_choice)

    def reset_settings(self):
        menu = self.menu
        menu.hildehrand_gradient = c.HILDEHRAND_GRADIENT_DEFAULT_ENABLED
        menu.hildehrand_gradient_strength = c.HILDEHRAND_GRADIENT_DEFAULT_STRENGTH
        menu.hildehrand_gradient_stepped = c.HILDEHRAND_GRADIENT_DEFAULT_STEPPED
        menu.hildehrand_gradient_bands = c.HILDEHRAND_GRADIENT_DEFAULT_BANDS
        menu.hildehrand_gradient_dithering = queries.DEFAULT_PORTRAIT_DITHERING
        menu.set_hildehrand_choice(queries.DEFAULT_PORTRAIT)
        self._slider_changed = False
        self.refresh_ui()

    def toggle_gradient(self):
        self.menu.toggle_hildehrand_gradient()
        self.refresh_ui()

    def toggle_stepped(self):
        if not self.menu.hildehrand_gradient:
            return
        self.menu.toggle_hildehrand_gradient_stepped()
        self.refresh_ui()

    def toggle_dithering(self):
        self.menu.toggle_hildehrand_gradient_dithering()
        self.refresh_ui()

    def set_strength(self, strength):
        self.menu.set_hildehrand_gradient_strength(strength)
        self._slider_changed = True

    def set_bands(self, value):
        self.menu.set_hildehrand_gradient_bands(_BandSlider.bands_for(value))
        self._slider_changed = True

    def additional_events(self, event):
        # Saving on every slider step would rewrite the file dozens of times per drag.
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self._slider_changed:
            self._slider_changed = False
            self.menu.save_hildehrand_settings()

    def refresh_ui(self):
        menu = self.menu
        enabled = menu.hildehrand_gradient
        stepped = menu.hildehrand_gradient_stepped
        button_w, button_h = c.SIZES["medium"]
        slider_x = CONTROLS_X + button_w + BUTTON_SLIDER_GAP_X
        gradient_y = CONTROLS_Y + CONTROLS_GAP_Y
        style_y = CONTROLS_Y + 2 * CONTROLS_GAP_Y
        slider_dy = (button_h - 20) // 2 + SLIDER_LABEL_PAD

        self.strength_slider = Slider(
            slider_x, gradient_y + slider_dy, SLIDER_W, "Gradient Strength",
            menu.hildehrand_gradient_strength, self.set_strength,
            visual_max=c.HILDEHRAND_GRADIENT_MAX_STRENGTH,
            allowed_max=c.HILDEHRAND_GRADIENT_MAX_STRENGTH)
        self.bands_slider = _BandSlider(
            slider_x, style_y + slider_dy, SLIDER_W, "Color Bands",
            menu.hildehrand_gradient_bands, self.set_bands,
            visual_max=c.HILDEHRAND_GRADIENT_MAX_BANDS,
            allowed_max=c.HILDEHRAND_GRADIENT_MAX_BANDS)
        # Each slider reads OFF while the option it belongs to is off. Bands also need the
        # gradient itself: the Stepped button is disabled without it.
        self.strength_slider.disabled = not enabled
        self.bands_slider.disabled = not (enabled and stepped)
        stepped_button = make_toggle_button(CONTROLS_X, style_y, "medium", "Stepped", stepped, self.toggle_stepped)
        stepped_button.disabled = not enabled
        dithering = menu.hildehrand_gradient_dithering
        dithering_button = make_toggle_button(
            CONTROLS_X, CONTROLS_Y + 3 * CONTROLS_GAP_Y, "medium", "Dithering", dithering, self.toggle_dithering)
        dithering_button.disabled = not (enabled and stepped)
        self.elements = [
            make_back_button(self.exit_screen),
            Button(CONTROLS_X, CONTROLS_Y, "medium", "purple", "Choose Portrait", self.open_picker),
            make_toggle_button(CONTROLS_X, gradient_y, "medium", "Gradient", enabled, self.toggle_gradient),
            stepped_button,
            dithering_button,
            Button(CONTROLS_X, CONTROLS_Y + 4 * CONTROLS_GAP_Y, "medium", "red", "Reset to Default", self.reset_settings),
            self.strength_slider,
            self.bands_slider,
        ]

    def additional_draw(self, surface):
        style = PORTRAIT_EDITOR_STYLES["preview"]
        ui_elements.draw_pixel_panel(surface, PREVIEW_RECT, style["color"], PREVIEW_BORDER,
                                     gradient_strength=style["gradient_strength"])
        image = self.menu.hildehrand_image
        if image:
            feet = (PREVIEW_RECT.centerx, PREVIEW_RECT.bottom - PREVIEW_FLOOR_PAD)
            old_clip = surface.get_clip()
            surface.set_clip(PREVIEW_RECT.clip(old_clip))
            surface.blit(image, image.get_rect(midbottom=feet))
            surface.set_clip(old_clip)
