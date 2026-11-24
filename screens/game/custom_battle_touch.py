"""Touch pads and weapon buttons for driving a controlled unit."""

import pygame

from screens.game import custom_battle_layout as layout
import data.constants as c


class TouchControls:
    """Touch pads and weapon buttons for driving a controlled unit."""

    def set_touch_mode(self, enabled):
        if self.touch_mode != enabled:
            self.touch_mode = enabled
            self.clear_controls()
            if self.mode == "battle":
                self.refresh_ui()

    @staticmethod
    def _touch_pad_rect(role):
        left = (layout.TOUCH_PAD_MARGIN if role == "drive" else c.SCREEN_WIDTH - layout.TOUCH_PAD_MARGIN - layout.TOUCH_PAD_SIZE)
        return pygame.Rect(left, c.SCREEN_HEIGHT - layout.TOUCH_PAD_BOTTOM - layout.TOUCH_PAD_SIZE,
                           layout.TOUCH_PAD_SIZE, layout.TOUCH_PAD_SIZE)

    def _select_touch_weapon(self, mode):
        if self._driving() and self.simulation.controlled.weapon(1) is not None:
            self.touch_weapon_mode = mode
            for button in self.touch_weapon_buttons:
                button.apply_state(enabled=True, color="yellow" if button.text == mode else "grey")

    def handle_touch_pointer(self, kind, pointer, position):
        if pointer in self.touch_pointers:
            role, _ = self.touch_pointers[pointer]
            if kind == pygame.FINGERUP or not self._driving():
                del self.touch_pointers[pointer]
            else:
                self.touch_pointers[pointer] = role, position
            return True
        if kind != pygame.FINGERDOWN or not self.touch_mode or not self._driving():
            return False
        for role in ("drive", "aim"):
            if (self._touch_pad_rect(role).collidepoint(position)
                    and all(active != role for active, _ in self.touch_pointers.values())):
                self.touch_pointers[pointer] = role, position
                return True
        return False

    def _touch_axes(self, role):
        center = self._touch_pad_rect(role).center
        position = next((pos for active, pos in self.touch_pointers.values() if active == role), center)
        vector = pygame.Vector2(position) - center
        vector /= layout.TOUCH_PAD_SIZE / 2
        if vector.length() <= layout.TOUCH_DEAD_ZONE:
            return pygame.Vector2()
        if vector.length() > 1:
            vector.scale_to_length(1)
        return vector
