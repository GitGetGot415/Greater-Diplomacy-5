"""The battlefield camera: zoom, panning, following, and coordinate conversion."""

import pygame

from screens.game import custom_battle_layout as layout
from screens.game import custom_battle_sprites as sprites
import data.constants as c


class BattleCamera:
    """The battlefield camera: zoom, panning, following, and coordinate conversion."""

    @staticmethod
    def view_rect():
        """Actual battle fills the whole screen."""
        return pygame.Rect(0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)

    @property
    def zoom(self):
        return layout.ZOOM_LEVELS[self.zoom_index]

    def _view_span(self):
        """How much of the battlefield the screen shows at the current zoom."""
        return c.SCREEN_WIDTH / self.zoom, c.SCREEN_HEIGHT / self.zoom

    def _center_camera(self, x, y):
        width, height = self._view_span()
        self._move_camera(x - width / 2, y - height / 2)

    def _follow_controlled_camera(self, fighter, pointer):
        """Show more ground toward the pointer while keeping the controlled unit visible."""
        view = self.view_rect()
        # Use the view center, so moving the camera cannot amplify its own offset.
        dx = max(-view.width / 2, min(view.width / 2, pointer[0] - view.centerx))
        dy = max(-view.height / 2, min(view.height / 2, pointer[1] - view.centery))
        self._center_camera(fighter.x + dx * layout.AIM_CAMERA_OFFSET / self.zoom,
                            fighter.y + dy * layout.AIM_CAMERA_OFFSET / self.zoom)

    def _move_camera(self, left, top):
        """Keep the view inside the battlefield, or center the battlefield when it is smaller than the view."""
        self.camera = [(arena - span) / 2 if span >= arena else max(0.0, min(arena - span, start))
                       for start, span, arena in zip((left, top), self._view_span(), self.simulation.arena_size)]

    def zoom_by(self, steps, pos):
        """Step through ZOOM_LEVELS, keeping the battlefield point under ``pos`` in place."""
        controlling = (self.mode == "battle" and self.simulation is not None
                       and self.simulation.controlled is not None and self.simulation.controlled.alive)
        minimum = layout.ZOOM_LEVELS.index(layout.CONTROLLED_MIN_ZOOM) if controlling else 0
        index = max(minimum, min(len(layout.ZOOM_LEVELS) - 1, self.zoom_index + steps))
        if index == self.zoom_index:
            return
        anchor = self.to_field(pos)
        self.zoom_index = index
        sprites.clear_rotated_sprites()
        if self.simulation is not None:
            self._cache_terrain_art()
        self._move_camera(anchor[0] - pos[0] / self.zoom, anchor[1] - pos[1] / self.zoom)
        self.update_battle_music_volume()
        self._refresh_visibility()

    def to_field(self, pos):
        """A screen position in battlefield coordinates."""
        return pos[0] / self.zoom + self.camera[0], pos[1] / self.zoom + self.camera[1]

    def to_screen(self, x, y):
        """A battlefield position on the screen."""
        return round((x - self.camera[0]) * self.zoom), round((y - self.camera[1]) * self.zoom)

    def _driving(self):
        """The player steers and fires only while the controlled sub-unit lives; afterward the player spectates."""
        return (self.mode == "battle" and not self.simulation.paused
                and self.simulation.controlled is not None and self.simulation.controlled.alive)
