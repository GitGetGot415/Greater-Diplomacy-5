"""Touch gestures reuse UI dispatch, camera math, and existing order guards."""

from types import SimpleNamespace
import unittest
from unittest import mock

import pygame

from data import constants as c, platform as game_platform
from data.io import settings_schema
from screens.game import map_input
from ui.camera.camera_handler import MapCamera
from ui.navigation.screen import Screen
from ui.navigation.touch_input import TouchInput, HOLD_MILLISECONDS
from ui.widgets.ui_elements import Button, Slider


def finger(kind, position, number=1):
    return pygame.event.Event(kind, touch_id=1, finger_id=number,
                              x=position[0] / c.SCREEN_WIDTH,
                              y=position[1] / c.SCREEN_HEIGHT, dx=0, dy=0)


def mouse(kind, position=(500, 300), *, touch=False):
    values = {"pos": position}
    if touch is not None:
        values["touch"] = touch
    if kind == pygame.MOUSEMOTION:
        values.update(buttons=(1, 0, 0), rel=(0, 0))
    else:
        values["button"] = 1
    return pygame.event.Event(kind, values)


class TouchGestureTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        self.owner = Screen()
        self.map = SimpleNamespace(camera=MapCamera(1), min_zoom=1)
        self.owner.touch_map_at = lambda pos: self.map
        with mock.patch("ui.navigation.touch_input.detect_control_mode", return_value="MOBILE"):
            self.touch = TouchInput()
        self.now = 0
        self.ticks = mock.patch("ui.navigation.touch_input.pygame.time.get_ticks", side_effect=lambda: self.now)
        self.ticks.start()
        self.addCleanup(self.ticks.stop)

    def send(self, *events, owner=None, mode="MOBILE"):
        return self.touch.process_events(events, owner or self.owner, mode)

    def press(self, pos=(500, 300)):
        return self.send(finger(pygame.FINGERDOWN, pos))

    def release(self, pos=(500, 300)):
        return self.send(finger(pygame.FINGERUP, pos))

    def test_tap_waits_for_release_and_generates_one_primary_click(self):
        self.assertEqual(self.press(), [])
        click = self.release()
        self.assertEqual([event.type for event in click],
                         [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP])
        self.assertEqual([event.button for event in click], [1, 1])
        self.assertTrue(all(event.pos == (500, 300) for event in click))

    def test_hold_generates_only_one_secondary_click_on_release(self):
        self.press()
        self.now = HOLD_MILLISECONDS + 1
        self.assertEqual(self.send(), [])
        self.assertEqual([event.button for event in self.release()], [3, 3])

    def test_hold_progress_matches_release_readiness_for_touch_and_mouse(self):
        for down, up in ((finger(pygame.FINGERDOWN, (500, 300)),
                          finger(pygame.FINGERUP, (500, 300))),
                         (mouse(pygame.MOUSEBUTTONDOWN), mouse(pygame.MOUSEBUTTONUP))):
            with self.subTest(input=pygame.event.event_name(down.type)):
                self.now = 0
                self.assertIsNone(self.touch.hold_progress())
                self.send(down)
                self.assertEqual(self.touch.hold_progress(), 0.0)
                self.now = HOLD_MILLISECONDS // 2
                self.assertEqual(self.touch.hold_progress(), 0.5)
                self.now = HOLD_MILLISECONDS - 1
                self.assertLess(self.touch.hold_progress(), 1.0)
                self.assertEqual([event.button for event in self.send(up)], [1, 1])
                self.assertIsNone(self.touch.hold_progress())

                self.send(down)
                self.now += HOLD_MILLISECONDS
                self.assertEqual(self.touch.hold_progress(), 1.0)
                self.now += HOLD_MILLISECONDS
                self.assertEqual(self.touch.hold_progress(), 1.0)
                self.assertEqual(self.send(), [])
                self.assertEqual([event.button for event in self.send(up)], [3, 3])
                self.assertIsNone(self.touch.hold_progress())

    def test_drag_and_pinch_cancel_hold_progress(self):
        self.press()
        self.now = HOLD_MILLISECONDS
        self.assertEqual(self.touch.hold_progress(), 1.0)
        self.send(finger(pygame.FINGERMOTION, (540, 330)))
        self.assertIsNone(self.touch.hold_progress())
        self.assertEqual(self.release((540, 330)), [])

        self.press()
        self.send(finger(pygame.FINGERDOWN, (600, 300), 2))
        self.assertIsNone(self.touch.hold_progress())

    def test_canceled_holds_clear_progress_before_the_next_screen(self):
        for cancellation in ("focus", "screen", "mode"):
            with self.subTest(cancellation=cancellation):
                self.press()
                self.now += HOLD_MILLISECONDS // 2
                self.assertEqual(self.touch.hold_progress(), 0.5)
                if cancellation == "focus":
                    self.send(pygame.event.Event(pygame.WINDOWFOCUSLOST))
                elif cancellation == "screen":
                    self.send(owner=Screen())
                else:
                    self.send(mode="DESKTOP")
                self.assertIsNone(self.touch.hold_progress())
                self.assertEqual(self.release(), [])

    def test_map_drag_pans_at_live_zoom_without_clicking_or_box_selecting(self):
        self.map.camera.zoom = 2
        self.map.camera.tilt_factor = 0.5
        self.press()
        self.assertEqual(self.send(finger(pygame.FINGERMOTION, (540, 330))), [])
        self.assertEqual(self.map.camera.pos, pygame.Vector2(-20, -30))
        self.assertEqual(self.release((540, 330)), [])

    def test_moved_touch_cannot_become_a_hold_after_returning_to_start(self):
        self.press()
        self.send(finger(pygame.FINGERMOTION, (540, 330)))
        self.send(finger(pygame.FINGERMOTION, (500, 300)))
        self.now = HOLD_MILLISECONDS + 1
        self.assertEqual(self.release(), [])

    def test_pinch_zooms_then_consumes_both_releases(self):
        self.press((500, 300))
        self.send(finger(pygame.FINGERDOWN, (600, 300), 2))
        self.assertEqual(self.send(finger(pygame.FINGERMOTION, (700, 300), 2)), [])
        self.assertEqual(self.map.camera.target_zoom, 2)
        self.assertEqual(self.map.camera._touch_zoom_anchor, (600, 300))
        self.now = HOLD_MILLISECONDS + 1
        self.assertEqual(self.send(finger(pygame.FINGERUP, (700, 300), 2)), [])
        self.assertEqual(self.release(), [])
        self.press()
        self.assertEqual(len(self.release()), 2)

    def test_second_finger_over_ui_cancels_the_map_touch(self):
        self.owner.touch_map_at = lambda pos: self.map if pos[0] < 650 else None
        self.press()
        self.send(finger(pygame.FINGERDOWN, (700, 300), 2))
        self.send(finger(pygame.FINGERMOTION, (750, 300), 2))
        self.send(finger(pygame.FINGERUP, (750, 300), 2))
        self.assertEqual(self.release(), [])
        self.assertEqual(self.map.camera.target_zoom, 1)

    def test_canceling_ui_drag_releases_widgets_and_scroll_state(self):
        self.owner.touch_map_at = lambda pos: None
        slider = Slider(450, 300, 200, "Fixture", 0.5, mock.Mock())
        self.owner.elements = [slider]
        start = slider.handle_rect.center
        self.press(start)
        self.owner.handle_events(self.send(finger(pygame.FINGERMOTION,
                                                  (start[0] + 30, start[1]))))
        self.assertTrue(slider.dragging)
        self.send(finger(pygame.FINGERDOWN, (600, 350), 2))
        self.assertFalse(slider.dragging)
        self.assertEqual(self.send(finger(pygame.FINGERUP, (600, 350), 2)), [])
        self.assertEqual(self.release((start[0] + 30, start[1])), [])

    def test_ui_drag_scrolls_existing_content_without_panning_the_map(self):
        self.owner.touch_map_at = lambda pos: None
        self.owner.scroll_content_rect = pygame.Rect(400, 200, 300, 300)
        self.owner.scroll_y = -100
        self.owner.max_scroll = -400
        self.press()
        events = self.send(finger(pygame.FINGERMOTION, (500, 330)))
        for event in events:
            self.owner.handle_content_drag(event)
        self.assertEqual(self.owner.scroll_y, -70)
        self.assertEqual(self.map.camera.pos, pygame.Vector2())
        for event in self.release((500, 330)):
            self.owner.handle_content_drag(event)
        self.assertFalse(self.owner.is_content_dragging())

    def test_ui_tap_activates_button_once_and_synthetic_mouse_is_filtered(self):
        self.owner.touch_map_at = lambda pos: None
        callback = mock.Mock()
        self.owner.elements = [Button(450, 275, (100, 50), "blue", "Fixture", callback,
                                      sound_kind=None)]
        self.press()
        self.owner.handle_events(self.release())
        self.assertEqual(self.send(pygame.event.Event(pygame.MOUSEBUTTONUP,
            pos=(500, 300), button=1, touch=True)), [])
        callback.assert_called_once_with()

    def test_touch_slider_drag_does_not_require_a_physical_mouse_button(self):
        self.owner.touch_map_at = lambda pos: None
        changed = mock.Mock()
        slider = Slider(450, 300, 200, "Fixture", 0.5, changed)
        self.owner.elements = [slider]
        start = slider.handle_rect.center
        self.press(start)
        with mock.patch("pygame.mouse.get_pressed", return_value=(0, 0, 0)):
            self.owner.handle_events(self.send(finger(pygame.FINGERMOTION,
                                                      (start[0] + 30, start[1]))))
        changed.assert_called_once()
        self.owner.handle_events(self.release((start[0] + 30, start[1])))
        self.assertFalse(slider.dragging)

    def test_dragging_inside_a_button_never_activates_the_button(self):
        self.owner.touch_map_at = lambda pos: None
        callback = mock.Mock()
        self.owner.elements = [Button(450, 275, (100, 50), "blue", "Fixture", callback,
                                      sound_kind=None)]
        self.press()
        self.owner.handle_events(self.send(finger(pygame.FINGERMOTION, (520, 300))))
        self.owner.handle_events(self.release((520, 300)))
        callback.assert_not_called()

    def test_dragging_over_confirmation_does_not_confirm(self):
        from ui.dialogs.yes_no import _YesNoModal
        dialog = _YesNoModal(pygame.display.get_surface(), "Fixture", "Confirm?",
                             mock.Mock(), "Yes", "No", None)
        self.owner = dialog
        point = dialog.yes_rect.center
        self.press(point)
        dialog.handle_events(self.send(finger(pygame.FINGERMOTION,
                                              (point[0] + 12, point[1]))))
        dialog.handle_events(self.release((point[0] + 12, point[1])))
        self.assertFalse(dialog._resolved)

    def test_dragging_over_skip_does_not_cancel_ai_processing(self):
        game = SimpleNamespace(show_player_ready_screen=False, show_exit_confirmation=False,
            is_saving=False, ai_is_thinking=True, force_skip_llm=False,
            force_skip_btn_rect=pygame.Rect(450, 275, 100, 50))
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                  pos=(500, 300), mobile_touch=True, mobile_drag=True)
        with (mock.patch.object(map_input.turn_progress, "threads_panel_available", return_value=False),
              mock.patch.object(map_input.ai_handler, "abort_ai_generation") as abort):
            self.assertTrue(map_input._handle_blocking_state(game, event, 500, 300))
            self.assertFalse(game.force_skip_llm)
            abort.assert_not_called()

    def test_focus_loss_cancels_click_and_next_touch_works(self):
        self.press()
        self.send(pygame.event.Event(pygame.WINDOWFOCUSLOST))
        self.assertEqual(self.release(), [])
        self.press()
        self.assertEqual(len(self.release()), 2)

    def test_screen_change_consumes_held_touch_instead_of_clicking_new_screen(self):
        self.press()
        self.assertEqual(self.send(finger(pygame.FINGERUP, (500, 300)), owner=Screen()), [])

    def test_mode_change_discards_gesture_and_does_not_leave_stale_fingers(self):
        self.press()
        self.assertEqual(self.send(finger(pygame.FINGERUP, (500, 300)), mode="DESKTOP"), [])
        self.press()
        self.assertEqual(len(self.release()), 2)

    def test_auto_resolves_once_and_real_mouse_events_are_preserved(self):
        for mode in ("AUTO", "MOBILE", "DESKTOP"):
            event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(500, 300), button=3, touch=False)
            self.assertEqual(self.send(event, mode=mode), [event])
        with mock.patch("ui.navigation.touch_input.detect_control_mode", side_effect=AssertionError):
            self.send(finger(pygame.FINGERDOWN, (500, 300)), mode="AUTO")
            self.assertEqual(len(self.send(finger(pygame.FINGERUP, (500, 300)), mode="AUTO")), 2)

    def test_mobile_mouse_input_uses_taps_holds_and_map_dragging(self):
        for touch in (False, True, None):
            with self.subTest(touch=touch):
                self.assertEqual(self.send(mouse(pygame.MOUSEBUTTONDOWN, touch=touch)), [])
                self.assertEqual([event.button for event in self.send(
                    mouse(pygame.MOUSEBUTTONUP, touch=touch))], [1, 1])
                self.send(mouse(pygame.MOUSEBUTTONDOWN, touch=touch))
                self.now += HOLD_MILLISECONDS + 1
                self.assertEqual([event.button for event in self.send(
                    mouse(pygame.MOUSEBUTTONUP, touch=touch))], [3, 3])
                self.map.camera.pos = pygame.Vector2()
                self.send(mouse(pygame.MOUSEBUTTONDOWN, touch=touch))
                self.assertEqual(self.send(mouse(pygame.MOUSEMOTION, (540, 330), touch=touch)), [])
                self.assertEqual(self.map.camera.pos, pygame.Vector2(-40, -30))
                self.assertEqual(self.send(mouse(pygame.MOUSEBUTTONUP, (540, 330), touch=touch)), [])

    def test_compatibility_mouse_before_or_after_finger_does_not_duplicate_tap(self):
        for mouse_first, touch in ((True, True), (False, True), (True, False),
                                    (False, False), (True, None), (False, None)):
            with self.subTest(mouse_first=mouse_first, touch=touch):
                down = [mouse(pygame.MOUSEBUTTONDOWN, touch=touch),
                        finger(pygame.FINGERDOWN, (500, 300))]
                up = [mouse(pygame.MOUSEBUTTONUP, touch=touch),
                      finger(pygame.FINGERUP, (500, 300))]
                if not mouse_first:
                    down.reverse()
                    up.reverse()
                self.assertEqual(self.send(*down), [])
                self.assertEqual(len(self.touch.pointers), 1)
                self.assertEqual([event.button for event in self.send(*up)], [1, 1])
                self.assertFalse(self.touch.pointers)

    def test_compatibility_mouse_motion_does_not_double_the_finger_pan(self):
        self.send(mouse(pygame.MOUSEBUTTONDOWN), finger(pygame.FINGERDOWN, (500, 300)))
        self.send(mouse(pygame.MOUSEMOTION, (540, 330)),
                  finger(pygame.FINGERMOTION, (540, 330)))
        self.assertEqual(self.map.camera.pos, pygame.Vector2(-40, -30))
        self.assertEqual(self.send(mouse(pygame.MOUSEBUTTONUP, (540, 330)),
                                   finger(pygame.FINGERUP, (540, 330))), [])

    def test_auto_on_desktop_preserves_primary_mouse_and_mobile_overrides_it(self):
        self.touch.automatic_mode = "DESKTOP"
        event = mouse(pygame.MOUSEBUTTONDOWN)
        self.assertEqual(self.send(event, mode="AUTO"), [event])
        self.assertEqual(self.send(event, mode="MOBILE"), [])
        self.send(mouse(pygame.MOUSEMOTION, (540, 330)), mode="MOBILE")
        self.assertEqual(self.map.camera.pos, pygame.Vector2(-40, -30))

    def test_mouse_mode_change_consumes_old_gesture_and_next_mobile_click_works(self):
        self.send(mouse(pygame.MOUSEBUTTONDOWN))
        self.send(mouse(pygame.MOUSEBUTTONUP), mode="DESKTOP")
        self.assertEqual(self.send(mouse(pygame.MOUSEBUTTONDOWN)), [])
        self.assertEqual([event.button for event in self.send(mouse(pygame.MOUSEBUTTONUP))], [1, 1])

    def test_mobile_mouse_hover_and_wheel_remain_immediate(self):
        motion = pygame.event.Event(pygame.MOUSEMOTION, pos=(500, 300), buttons=(0, 0, 0), rel=(1, 1))
        wheel = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)
        self.assertEqual(self.send(motion, wheel), [motion, wheel])

    def test_secondary_touch_uses_existing_order_handler_and_permission_guard(self):
        self.press()
        self.now = HOLD_MILLISECONDS + 1
        events = self.release()
        game = SimpleNamespace(_ignore_left_until_release=False, _ignore_right_until_release=False,
            secondary_mode="UNITS", unit_selection_drag=None, can_select_map_units=lambda: True,
            selected_unit_records=lambda: [("unit", "origin")], issue_selected_move_orders=mock.Mock())
        destination = {"id": "destination"}
        bindings = {button: {action: False for action in actions}
                    for button, actions in c.default_mouse_button_actions().items()}
        with (mock.patch.object(c, "MOUSE_BUTTON_ACTIONS", bindings),
              mock.patch.object(map_input.queries, "get_clicked_province", return_value=destination),
              mock.patch("pygame.key.get_mods", return_value=0)):
            for event in events:
                map_input._handle_map_unit_selection(game, event, False)
            game.issue_selected_move_orders.assert_called_once_with(destination, append=False)
            game.issue_selected_move_orders.reset_mock()
            game.can_select_map_units = lambda: False
            for event in events:
                map_input._handle_map_unit_selection(game, event, False)
            game.issue_selected_move_orders.assert_not_called()
            game.can_select_map_units = lambda: True
            for event in events:
                map_input._handle_map_unit_selection(game, event, True)
            game.issue_selected_move_orders.assert_not_called()


class ControlModeTests(unittest.TestCase):
    def test_explicit_desktop_mode_keeps_touch_compatibility_mouse_clicks(self):
        with mock.patch("ui.navigation.touch_input.detect_control_mode", return_value="MOBILE"):
            touch = TouchInput()
        click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20), button=1, touch=True)
        self.assertEqual(touch.process_events([click], Screen(), "DESKTOP"), [click])

    def test_browser_detection_handles_android_ios_ipados_and_desktop(self):
        import platform
        cases = (("Android", "Linux", 5, "MOBILE"),
                 ("iPhone", "iPhone", 5, "MOBILE"),
                 ("Macintosh", "MacIntel", 5, "MOBILE"),
                 ("Macintosh", "MacIntel", 0, "DESKTOP"),
                 ("Windows", "Win32", 5, "DESKTOP"))
        for agent, device, touches, expected in cases:
            browser = SimpleNamespace(navigator=SimpleNamespace(
                userAgent=agent, platform=device, maxTouchPoints=touches))
            with (self.subTest(agent=agent, touches=touches),
                  mock.patch.object(game_platform, "IS_WEB", True),
                  mock.patch.object(platform, "window", browser, create=True)):
                self.assertEqual(game_platform.detect_control_mode(), expected)

    def test_settings_control_cycles_saves_and_cancels_an_unfinished_gesture(self):
        from screens.menus.settings import Settings
        screen = object.__new__(Settings)
        screen.control_mode = "AUTO"
        screen.controller = SimpleNamespace(**settings_schema.defaults(), touch_input=mock.Mock())
        screen.refresh_ui = mock.Mock()
        with (mock.patch.object(c, "CONTROL_MODE", c.CONTROL_MODE),
              mock.patch("screens.menus.settings.queries.save_global_settings") as save):
            for mode in ("MOBILE", "DESKTOP", "AUTO"):
                screen.cycle_control_mode()
                self.assertEqual(screen.controller.control_mode, mode)
                self.assertEqual(c.CONTROL_MODE, mode)
            self.assertEqual(save.call_count, 3)
            self.assertEqual(screen.controller.touch_input.cancel.call_count, 3)


class MobileWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def test_live_map_and_orders_expose_map_but_not_controls(self):
        from tests import app_harness
        with app_harness.patch_map(self.map, selected_province=None,
                navigation_intro_popup=None, diplomatic_popups=[], army_editor_state=None,
                army_custom_symbol_state=None, show_player_ready_screen=False,
                show_exit_confirmation=False, is_saving=False, ai_is_thinking=False):
            point = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
            self.assertIs(self.map.touch_map_at(point), self.map)
            self.assertIsNone(self.map.touch_map_at(self.map.top_bar_rect.center))
            for name in ("ORDERS", "TACTICAL_ORDERS"):
                orders = self.controller.states[name]
                with self.subTest(screen=name):
                    self.assertIs(orders.touch_map_at(point), self.map)
                    self.assertIsNone(orders.touch_map_at(orders.panel_rect.center))

    def test_live_map_drag_reaches_shared_camera_without_selecting_a_province(self):
        from tests import app_harness
        with (app_harness.patch_map(self.map, selected_province=None,
                navigation_intro_popup=None, diplomatic_popups=[], show_player_ready_screen=False,
                show_exit_confirmation=False, is_saving=False, ai_is_thinking=False),
              mock.patch.object(self.map.camera, "pan_by") as pan,
              mock.patch.object(self.map, "issue_selected_move_orders") as order):
            touch = TouchInput()
            for event in (finger(pygame.FINGERDOWN, (600, 350)),
                          finger(pygame.FINGERMOTION, (640, 380)),
                          finger(pygame.FINGERUP, (640, 380))):
                self.map.handle_events(touch.process_events([event], self.map, "MOBILE"))
            pan.assert_called_once_with((640, 380), (600, 350))
            order.assert_not_called()
            self.assertIsNone(self.map.selected_province)

    def test_mobile_mouse_drag_works_in_map_and_both_order_screens(self):
        from tests import app_harness
        with (app_harness.patch_map(self.map, selected_province=None,
                navigation_intro_popup=None, diplomatic_popups=[], show_player_ready_screen=False,
                show_exit_confirmation=False, is_saving=False, ai_is_thinking=False),
              mock.patch.object(self.map.camera, "pan_by") as pan):
            for owner in (self.map, self.controller.states["ORDERS"],
                          self.controller.states["TACTICAL_ORDERS"]):
                with self.subTest(screen=type(owner).__name__):
                    touch = TouchInput()
                    pan.reset_mock()
                    for event in (mouse(pygame.MOUSEBUTTONDOWN, (600, 350)),
                                  mouse(pygame.MOUSEMOTION, (640, 380)),
                                  mouse(pygame.MOUSEBUTTONUP, (640, 380))):
                        owner.handle_events(touch.process_events([event], owner, "MOBILE"))
                    pan.assert_called_once_with((640, 380), (600, 350))
