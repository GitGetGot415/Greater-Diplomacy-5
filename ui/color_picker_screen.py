"""Native pygame replacement for tkinter's colorchooser.askcolor.

RGB sliders and a hex field stay in sync with each other and with a live
swatch; on_confirm((r, g, b)) fires only from the OK button, matching
askcolor's "None on cancel" contract.
"""
import re
import pygame
from gameState import GameState
import data.constants as c
from ui.bars import ui_bars
from ui_elements import Button, TextField, Slider
from map_logic.rendering.font_manager import fonts

_HEX_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


class ColorPickerScreen(GameState):
    PANEL_SIZE = (460, 440)

    def __init__(self, game_state, title, initial_color, on_confirm):
        super().__init__()
        self.map_screen = getattr(game_state, "map_screen", None) or game_state
        self.title = title
        self.on_confirm = on_confirm

        r, g, b = (int(v) for v in initial_color[:3])
        self.current_color = [r, g, b]

        surface = pygame.display.get_surface()
        self.background = surface.copy() if surface else None

        panel_w, panel_h = self.PANEL_SIZE
        self.panel_rect = pygame.Rect(0, 0, panel_w, panel_h)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

        slider_x = self.panel_rect.x + 40
        slider_w = self.panel_rect.width - 80
        self.sliders = [
            Slider(slider_x, self.panel_rect.y + 150, slider_w, f"R: {r}", r, self._make_channel_cb(0),
                  visual_max=255, allowed_max=255),
            Slider(slider_x, self.panel_rect.y + 210, slider_w, f"G: {g}", g, self._make_channel_cb(1),
                  visual_max=255, allowed_max=255),
            Slider(slider_x, self.panel_rect.y + 270, slider_w, f"B: {b}", b, self._make_channel_cb(2),
                  visual_max=255, allowed_max=255),
        ]

        self.hex_field = TextField(slider_x, self.panel_rect.y + 320, 140, 36,
                                   self._to_hex(), max_length=6, on_submit=self._sync_from_hex)

        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              SYNC                                   #
    # ------------------------------------------------------------------ #

    def _to_hex(self):
        return "{:02X}{:02X}{:02X}".format(*self.current_color)

    def _make_channel_cb(self, index):
        def _on_change(value):
            self.current_color[index] = int(value)
            slider = self.sliders[index]
            label = "RGB"[index]
            slider.text = f"{label}: {int(value)}"
            self.hex_field.text = self._to_hex()
        return _on_change

    def _sync_from_hex(self):
        text = self.hex_field.text.strip().lstrip("#")
        if not _HEX_RE.match(text):
            self.hex_field.text = self._to_hex()
            return
        self.current_color = [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]
        for i, slider in enumerate(self.sliders):
            slider.value = self.current_color[i]
            ratio = slider.value / slider.visual_max
            slider.handle_rect.centerx = slider.rect.left + int(slider.rect.width * ratio)
            slider.text = f"{'RGB'[i]}: {self.current_color[i]}"
        self.hex_field.text = self._to_hex()

    # ------------------------------------------------------------------ #
    #                              CONFIRM                                #
    # ------------------------------------------------------------------ #

    def _confirm(self):
        self.on_confirm(tuple(self.current_color))
        self.exit_screen()

    def refresh_ui(self):
        self.elements = list(self.sliders) + [
            self.hex_field,
            Button(self.panel_rect.centerx - 130, self.panel_rect.bottom - 55, "small", "green", "OK", self._confirm),
            Button(self.panel_rect.centerx + 10, self.panel_rect.bottom - 55, "small", "red", "Cancel", self.exit_screen),
        ]

    def draw(self, surface):
        if self.background:
            surface.blit(self.background, (0, 0))
        ui_bars.draw_fullscreen_overlay(surface, 190)

        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(40, 40, 40),
                               border_color=(100, 150, 255), border_width=3)
        ui_bars.draw_centered_title(surface, self.title, self.panel_rect.y + 20, "heading2")

        swatch_rect = pygame.Rect(0, 0, 80, 80)
        swatch_rect.center = (self.panel_rect.right - 80, self.panel_rect.y + 90)
        pygame.draw.rect(surface, self.current_color, swatch_rect)
        pygame.draw.rect(surface, (255, 255, 255), swatch_rect, 2)

        hex_label = fonts.get("normal").render("Hex:", True, c.UI_TEXT_BRIGHT)
        surface.blit(hex_label, hex_label.get_rect(midright=(self.hex_field.rect.x - 4, self.hex_field.rect.centery)))

        for el in self.elements:
            el.draw(surface)
