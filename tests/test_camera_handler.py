"""Camera wrapping behavior for looping and bounded maps."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pygame

from data import constants as c
from map_logic.camera.camera_handler import MapCamera


def _map(loop_map):
    return SimpleNamespace(
        loop_map=loop_map,
        map_w=1000,
        map_h=800,
        total_ui_h=100,
        top_ui_height=50,
    )


class MapCameraBoundsTests(unittest.TestCase):
    def test_normal_zoom_keeps_the_world_point_under_the_cursor(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = 2
        camera.target_zoom = 4
        camera.pos = pygame.Vector2(100, 50)
        self_map = _map(loop_map=False)
        cursor = (640, 350)
        expected_world = pygame.Vector2(
            cursor[0] / camera.zoom + camera.pos.x,
            ((cursor[1] - self_map.top_ui_height) / camera.zoom) + camera.pos.y,
        )

        with patch("map_logic.camera.camera_handler.pygame.mouse.get_pos", return_value=cursor):
            camera.update(self_map, 720)

        visible_world = pygame.Vector2(
            cursor[0] / camera.zoom + camera.pos.x,
            ((cursor[1] - self_map.top_ui_height) / camera.zoom) + camera.pos.y,
        )
        # Camera positions are intentionally rounded to hundredths after each
        # update, so retain the world point within that display-level precision.
        self.assertAlmostEqual(visible_world.x, expected_world.x, places=2)
        self.assertAlmostEqual(visible_world.y, expected_world.y, places=2)

    def test_manual_zoom_cancels_an_automatic_focus_animation(self):
        camera = MapCamera(min_zoom=2)
        camera.focus_animation = True
        camera.target_zoom = 4
        self_map = _map(False)
        self_map.min_zoom = 2

        with patch("map_logic.camera.camera_handler.pygame.mouse.get_pressed", return_value=(0, 0, 0)):
            camera.handle_input(pygame.event.Event(pygame.MOUSEWHEEL, y=1), self_map, False)

        self.assertFalse(camera.focus_animation)
        self.assertGreater(camera.target_zoom, 4)

    def test_middle_drag_uses_cursor_distance_at_the_current_zoom_and_tilt(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.tilt_factor = 0.5
        self_map = _map(loop_map=False)

        camera.handle_input(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(100, 100), button=2),
            self_map, False)
        camera.handle_input(
            pygame.event.Event(pygame.MOUSEMOTION, pos=(130, 120), rel=(99, 99),
                               buttons=(0, 1, 0)), self_map, False)

        # The intentionally incorrect rel is ignored.  Moving the pointer by
        # 30x20 screen pixels moves the rendered map by exactly 30x20 pixels.
        self.assertEqual(camera.pos.x, -15)
        self.assertEqual(camera.pos.y, -20)
        self.assertEqual(camera.target_pos, camera.pos)

    def test_right_drag_pans_only_when_the_caller_allows_it(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        self_map = _map(loop_map=False)

        with patch("map_logic.camera.camera_handler.pygame.mouse.get_pressed",
                   return_value=(0, 0, 0)):
            camera.handle_input(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(100, 100), button=3),
                self_map, False, allow_right_drag=True)
            camera.handle_input(
                pygame.event.Event(pygame.MOUSEMOTION, pos=(130, 120), rel=(99, 99),
                                   buttons=(0, 0, 1)), self_map, False,
                allow_right_drag=True)

        self.assertEqual(camera.pos, pygame.Vector2(-15, -10))
        self.assertTrue(camera.finish_right_drag())

        with patch("map_logic.camera.camera_handler.pygame.mouse.get_pressed",
                   return_value=(0, 0, 0)):
            camera.handle_input(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(130, 120), button=3),
                self_map, False)
            camera.handle_input(
                pygame.event.Event(pygame.MOUSEMOTION, pos=(160, 140), rel=(30, 20),
                                   buttons=(0, 0, 1)), self_map, False)

        self.assertEqual(camera.pos, pygame.Vector2(-15, -10))

    def test_arrow_keys_pan_by_the_shared_screen_distance(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.tilt_factor = 0.5
        self_map = _map(loop_map=False)

        camera.handle_input(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT),
                            self_map, False)
        camera.handle_input(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN),
                            self_map, False)

        self.assertEqual(camera.target_pos.x, c.CAMERA_KEYBOARD_PAN_PIXELS / camera.zoom)
        self.assertEqual(camera.target_pos.y,
                         c.CAMERA_KEYBOARD_PAN_PIXELS / (camera.zoom * camera.tilt_factor))

    def test_rebound_pan_key_moves_in_its_configured_direction(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        self_map = _map(loop_map=False)

        def keybind(action, default):
            return pygame.K_a if action == "PAN_LEFT" else default

        with patch("map_logic.camera.camera_handler.queries.get_keybind",
                   side_effect=keybind):
            camera.handle_input(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a),
                                self_map, False)

        self.assertEqual(camera.target_pos.x,
                         -c.CAMERA_KEYBOARD_PAN_PIXELS / camera.zoom)

    def test_held_arrow_key_pans_continuously_without_key_repeat_delay(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        self_map = _map(loop_map=False)

        class PressedKeys:
            def __getitem__(self, key):
                return key == pygame.K_RIGHT

        with (patch("map_logic.camera.camera_handler.pygame.display.get_surface",
                    return_value=object()),
              patch("map_logic.camera.camera_handler.pygame.key.get_pressed",
                    return_value=PressedKeys()),
              patch("map_logic.camera.camera_handler.pygame.time.get_ticks",
                    side_effect=(1000, 1050))):
            camera.handle_input(
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT),
                self_map, False)
            camera.update(self_map, 720)

        expected_screen_distance = (
            c.CAMERA_KEYBOARD_PAN_PIXELS
            + c.CAMERA_KEYBOARD_PAN_PIXELS_PER_SECOND * 0.05)
        self.assertEqual(camera.target_pos.x,
                         expected_screen_distance / camera.zoom)

    def test_cleared_pan_bindings_do_not_index_the_pressed_key_state(self):
        camera = MapCamera(min_zoom=2)

        class PressedKeys:
            def __getitem__(self, key):
                raise AssertionError(f"cleared keybind was indexed: {key!r}")

        with (patch("map_logic.camera.camera_handler.pygame.display.get_surface",
                    return_value=object()),
              patch("map_logic.camera.camera_handler.pygame.key.get_pressed",
                    return_value=PressedKeys()),
              patch("map_logic.camera.camera_handler.queries.get_keybind",
                    return_value=None)):
            camera._pan_held_navigation_keys()

    def test_conflicting_right_button_cancels_middle_drag_until_release(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        self_map = _map(loop_map=False)
        camera.handle_input(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(100, 100), button=2),
            self_map, False)

        camera.cancel_middle_drag()
        camera.handle_input(
            pygame.event.Event(pygame.MOUSEMOTION, pos=(150, 150), rel=(50, 50),
                               buttons=(0, 1, 1)), self_map, False)

        self.assertEqual(camera.pos, pygame.Vector2(0, 0))
        self.assertTrue(camera._ignore_middle_until_release)

        camera.handle_input(
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(150, 150), button=2),
            self_map, False)
        self.assertFalse(camera._ignore_middle_until_release)

    def test_non_looping_pan_uses_direct_distance_instead_of_shortest_wrap(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.pos = pygame.Vector2(10, 100)
        camera.target_pos = pygame.Vector2(990, 100)

        camera.update(_map(loop_map=False), 720)

        # A wrapped calculation would move left from 10 to 8. A bounded map
        # must instead advance toward its right-hand target, then clamp there.
        self.assertGreater(camera.pos.x, 10)

    def test_looping_pan_keeps_shortest_wrapped_distance(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.pos = pygame.Vector2(10, 100)
        camera.target_pos = pygame.Vector2(990, 100)

        camera.update(_map(loop_map=True), 720)

        self.assertLess(camera.pos.x, 10)

    def test_non_looping_map_exposes_left_edge_beside_raised_ui(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.pos = pygame.Vector2(-500, 100)
        camera.target_pos = pygame.Vector2(-500, 100)

        camera.update(_map(loop_map=False), 720)

        self.assertEqual(camera.pos.x, -c.UI_LEFT_OFFSET / camera.zoom)

    def test_non_looping_selection_map_does_not_reserve_raised_ui_space(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.pos = pygame.Vector2(-500, 100)
        camera.target_pos = pygame.Vector2(-500, 100)
        self_map = _map(loop_map=False)
        self_map.selection_mode = True

        camera.update(self_map, 720)

        self.assertEqual(camera.pos.x, 0)


if __name__ == "__main__":
    unittest.main()
