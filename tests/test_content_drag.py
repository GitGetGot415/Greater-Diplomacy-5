"""Check content drag direction, input separation, and scroll limits."""

from types import SimpleNamespace
import unittest
from unittest import mock

import pygame

from ui.navigation.screen import Screen
from screens.game import map_input
from screens.game.messages import Messages_Screen


def drag_events(start=(50, 50), delta=(0, 30)):
    end = (start[0] + delta[0], start[1] + delta[1])
    return (
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1),
        pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=delta, buttons=(1, 0, 0)),
        pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1),
    )


class ContentDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.display.init()
        pygame.display.set_mode((1, 1))

    def screen(self):
        screen = Screen()
        screen.refresh_ui = mock.Mock()
        screen.scroll_y = -150
        screen.max_scroll = -500
        screen.scroll_content_rect = pygame.Rect(0, 0, 200, 200)
        return screen

    def test_direct_content_drag_follows_the_pointer_on_both_axes(self):
        for axis, delta in (("y", (0, 30)), ("y", (0, -30)), ("x", (30, 0)), ("x", (-30, 0))):
            with self.subTest(axis=axis, delta=delta):
                screen = self.screen()
                for event in drag_events(delta=delta):
                    screen.handle_content_drag(event, axis=axis)
                self.assertEqual(screen.scroll_y, -150 + delta[0 if axis == "x" else 1])
                self.assertIsNone(screen.content_drag_state)

    def test_standard_list_drag_follows_the_pointer_and_cancels_a_pressed_row(self):
        screen = self.screen()
        row = SimpleNamespace(is_pressed=True)
        screen.elements = [row]
        for event in drag_events():
            screen.handle_list_scroll(event, content_rect_attr="scroll_content_rect")
        self.assertEqual(screen.scroll_y, -120)
        self.assertFalse(row.is_pressed)
        self.assertFalse(screen.is_content_dragging())

    def test_small_motion_preserves_clicks_and_scroll_limits_clamp_drags(self):
        screen = self.screen()
        row = SimpleNamespace(is_pressed=True)
        screen.elements = [row]
        for event in drag_events(delta=(0, 2)):
            screen.handle_content_drag(event)
        self.assertEqual(screen.scroll_y, -150)
        self.assertTrue(row.is_pressed)
        for delta, expected in (((0, 1000), 0), ((0, -1000), -500)):
            with self.subTest(delta=delta):
                for event in drag_events(delta=delta):
                    screen.handle_content_drag(event)
                self.assertEqual(screen.scroll_y, expected)

    def test_scrollbar_drag_and_wheel_keep_their_directions(self):
        screen = self.screen()
        screen.scroll_track_rect = pygame.Rect(180, 0, 20, 200)
        screen.scroll_handle_rect = pygame.Rect(180, 40, 20, 40)
        for event in drag_events(start=screen.scroll_handle_rect.center):
            screen.handle_list_scroll(event, content_rect_attr="scroll_content_rect")
        self.assertLess(screen.scroll_y, -150)
        self.assertFalse(screen.is_dragging_scrollbar)
        self.assertFalse(screen.is_content_dragging())
        before = screen.scroll_y
        screen.handle_list_scroll(pygame.event.Event(pygame.MOUSEWHEEL, y=-1, x=0))
        self.assertLess(screen.scroll_y, before)

    def test_map_panels_convert_positive_offsets_to_the_same_content_direction(self):
        for panel in ("country_actions", *map_input.MAP_PANELS):
            with self.subTest(panel=panel):
                screen = self.screen()
                screen.selected_province = {"id": 1}
                screen.selection_mode = False
                for name in ("country_actions", *map_input.MAP_PANELS):
                    setattr(screen, f"{name}_scroll_rect", None)
                    setattr(screen, f"{name}_scroll_y", 150)
                    setattr(screen, f"{name}_scroll_max", 500)
                setattr(screen, f"{panel}_scroll_rect", screen.scroll_content_rect)
                for event in drag_events():
                    map_input._handle_panel_scrolling(screen, event, *event.pos)
                self.assertEqual(getattr(screen, f"{panel}_scroll_y"), 120)

    def test_message_thread_drag_pulls_the_thread_down(self):
        screen = object.__new__(Messages_Screen)
        screen.map_screen = SimpleNamespace(tactical_mode=False)
        screen.selected_recipient = None
        screen.draft_edit_rects = []
        screen.forward_button_rects = []
        screen.is_dragging_messages = True
        screen.msg_scroll_y = 150
        screen.max_msg_scroll = 500
        screen.scroll_content_rect = pygame.Rect(0, 0, 200, 200)
        event = drag_events(start=(700, 100))[1]
        screen.additional_events(event)
        self.assertEqual(screen.msg_scroll_y, 180)
        screen.additional_events(drag_events(start=(700, 100))[2])
        self.assertFalse(screen.is_dragging_messages)


if __name__ == "__main__":
    unittest.main()
