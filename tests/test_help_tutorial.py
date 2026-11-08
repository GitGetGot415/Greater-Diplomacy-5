"""The Help window reads checked content, and its category list opens topics."""
import ast
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pygame

import data.constants as c
from ui.dialogs import message_box
from ui.dialogs.message_box import _NavigationIntroPopup

ROOT = Path(__file__).resolve().parents[1]
SHIPPED_PATH = str(ROOT / message_box.TUTORIAL_PATH)


def artificial_content(first_blocks=None):
    """Two categories, so navigation can cross a category boundary."""
    def text(value):
        return [{"type": "text", "text": value}]
    return {"categories": [
        {"title": "First", "topics": [
            {"title": "One", "subtitle": "Sub", "blocks": first_blocks or text("A")},
            {"title": "Two", "blocks": text("B")}]},
        {"title": "Second", "topics": [{"title": "Three", "blocks": text("C")}]},
    ]}


def shipped_blocks(content):
    for category in content["categories"]:
        for topic in category["topics"]:
            yield from topic["blocks"]


class HelpContentTests(unittest.TestCase):
    def test_shipped_content_loads(self):
        self.assertTrue(message_box.load_tutorial(SHIPPED_PATH)["categories"])

    def test_invalid_content_names_the_field_to_correct(self):
        steps_item = {"heading": "H", "text": "T"}
        cases = (
            ({"categories": []}, r"categories"),
            ({"categories": [{"topics": []}]}, r"categories\[0\]\.title"),
            (artificial_content([{"type": "chart"}]), r"blocks\[0\]\.type"),
            (artificial_content([{"type": "text", "text": "A", "align": "right"}]), r"blocks\[0\]\.align"),
            (artificial_content([{"type": "steps", "columns": 3, "items": [steps_item]}]), r"columns"),
            (artificial_content([{"type": "steps", "items": [{"heading": "H"}]}]), r"items\[0\]\.text"),
            (artificial_content([{"type": "mouse_buttons",
                                  "items": [{"image": "L.png", "heading": "H", "lines": [3]}]}]),
             r"lines\[0\]"),
            (artificial_content([{"type": "key_box", "heading": "H"}]), r"blocks\[0\]\.text"),
        )
        for content, field in cases:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                message_box.validate_tutorial(content)

    def test_unreadable_file_names_its_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory, "tutorial.json"))
            Path(path).write_text("{", encoding="utf-8")
            self.addCleanup(message_box.load_tutorial.cache_clear)
            with self.assertRaisesRegex(ValueError, re.escape(path)):
                message_box.load_tutorial(path)

    def test_every_named_icon_is_registered_at_startup(self):
        # main.py fills ui_elements.UI_ICONS. An unregistered name would leave
        # an empty icon slot in the shipped Help.
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        registered = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                    and any(isinstance(target, ast.Attribute) and target.attr == "UI_ICONS"
                            for target in node.targets)):
                registered.update(key.value for key in node.value.keys)
        self.assertTrue(registered)

        content = message_box.load_tutorial(SHIPPED_PATH)
        named = {category.get("icon") for category in content["categories"]}
        for block in shipped_blocks(content):
            named.update(item.get("icon") for item in block.get("items", []))
            named.update(marker.group(1) for marker in message_box._ICON_MARKER.finditer(block.get("text", "")))
        named.discard(None)
        self.assertLessEqual(named, registered)

    def test_every_mouse_image_exists(self):
        content = message_box.load_tutorial(SHIPPED_PATH)
        images = [item["image"] for block in shipped_blocks(content)
                  if block["type"] == "mouse_buttons" for item in block["items"]]
        for image in images:
            with self.subTest(image=image):
                self.assertTrue((ROOT / _NavigationIntroPopup.MOUSE_DIR / image).is_file())


class HelpPopupTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        self.addCleanup(setattr, _NavigationIntroPopup, "last_topic_index",
                        _NavigationIntroPopup.last_topic_index)
        self.map_stub = SimpleNamespace(navigation_intro_popup=None)

    def popup(self, content=None):
        with mock.patch.object(message_box, "load_tutorial", return_value=content or artificial_content()):
            return _NavigationIntroPopup(self.map_stub)

    def click(self, popup, pos):
        return popup.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))

    def rail_row(self, popup, kind, index):
        return next(rect for rect, row_kind, row_index in popup.rail_rows
                    if row_kind == kind and row_index == index)

    def test_category_rows_open_their_first_topic_and_topic_rows_select_topics(self):
        popup = self.popup()
        with mock.patch.object(message_box.ui_elements, "play_ui_sound") as sound:
            self.assertTrue(self.click(popup, self.rail_row(popup, "category", 1).center))
            self.assertEqual(popup.topics[popup.topic_index], (1, 0))
            sound.assert_called_once_with("select_category")

            # Clicking the open category closes it, leaving no topic selected.
            sound.reset_mock()
            self.assertTrue(self.click(popup, self.rail_row(popup, "category", 1).center))
            self.assertIsNone(popup.topic_index)
            self.assertFalse([index for _rect, kind, index in popup.rail_rows if kind == "topic"])
            sound.assert_called_once_with("select_category")
        self.assertIsNone(_NavigationIntroPopup.last_topic_index)
        popup.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))

        self.click(popup, self.rail_row(popup, "category", 0).center)
        # Only the open category lists its topics.
        self.assertEqual({index for _rect, kind, index in popup.rail_rows if kind == "topic"}, {0, 1})
        with mock.patch.object(message_box.ui_elements, "play_ui_sound") as sound:
            self.click(popup, self.rail_row(popup, "topic", 1).center)
        self.assertEqual(popup.topic_index, 1)
        sound.assert_called_once_with("select_sub_category")

    def test_next_continues_into_the_next_category(self):
        popup = self.popup()
        popup.select_topic(1)
        self.click(popup, popup.next_rect.center)
        self.assertEqual(popup.topics[popup.topic_index], (1, 0))
        self.assertEqual({index for _rect, kind, index in popup.rail_rows if kind == "topic"}, {2})

    def test_with_every_category_closed_next_starts_at_the_first_topic(self):
        popup = self.popup()
        popup.select_topic(None)
        self.assertEqual(popup._page_buttons_enabled(), (False, True))
        self.click(popup, popup.prev_rect.center)
        self.assertIsNone(popup.topic_index)
        self.click(popup, popup.next_rect.center)
        self.assertEqual(popup.topic_index, 0)

    def test_help_button_resumes_the_last_topic_and_a_fresh_game_starts_at_the_first(self):
        with mock.patch.object(message_box, "load_tutorial", return_value=artificial_content()):
            message_box.show_navigation_intro(self.map_stub)
            self.assertEqual(self.map_stub.navigation_intro_popup.topic_index, 0)
            self.map_stub.navigation_intro_popup.select_topic(2)

            message_box.show_navigation_intro(self.map_stub, resume=True)
            self.assertEqual(self.map_stub.navigation_intro_popup.topic_index, 2)

            message_box.show_navigation_intro(self.map_stub)
            self.assertEqual(self.map_stub.navigation_intro_popup.topic_index, 0)

            # A player who closed every category gets them closed again.
            self.map_stub.navigation_intro_popup.select_topic(None)
            message_box.show_navigation_intro(self.map_stub, resume=True)
            self.assertIsNone(self.map_stub.navigation_intro_popup.topic_index)

    def test_long_topics_scroll_with_the_wheel_and_scrollbar(self):
        long_text = " ".join(["word"] * 4000)
        popup = self.popup(artificial_content([{"type": "text", "text": long_text}]))
        self.assertGreater(popup.max_scroll, 0)

        wheel = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
        with mock.patch("pygame.mouse.get_pos", return_value=popup.content_rect.center):
            self.assertTrue(popup.handle_event(wheel))
        self.assertEqual(popup.scroll_y, c.SCROLL_STEP)
        # Away from the popup, the wheel still zooms the map.
        outside = (popup.rect.right + 5, popup.rect.bottom + 5)
        with mock.patch("pygame.mouse.get_pos", return_value=outside):
            self.assertFalse(popup.handle_event(wheel))
        self.assertEqual(popup.scroll_y, c.SCROLL_STEP)

        handle = popup.scroll_handle_rect.center
        position = popup.rect.topleft
        self.assertTrue(self.click(popup, handle))
        popup.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(handle[0], handle[1] + 60)))
        self.assertGreater(popup.scroll_y, c.SCROLL_STEP)
        # Dragging the scrollbar scrolls the topic instead of moving the window.
        self.assertEqual(popup.rect.topleft, position)
        popup.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=handle, button=1))
        self.assertIsNone(popup._scroll_drag_offset)

        # A newly selected topic starts at its top.
        popup.select_topic(1)
        self.assertEqual(popup.scroll_y, 0)

    def test_shipped_category_list_fits_with_any_category_open(self):
        """Rows past the list's bottom would be clipped and could not be clicked."""
        with mock.patch.object(message_box, "load_tutorial",
                               return_value=message_box.load_tutorial(SHIPPED_PATH)):
            popup = _NavigationIntroPopup(self.map_stub)
        for category_index, first_topic in popup.first_topic.items():
            popup.select_topic(first_topic)
            with self.subTest(category=popup.categories[category_index]["title"]):
                self.assertLessEqual(max(rect.bottom for rect, _kind, _index in popup.rail_rows),
                                     popup.rail_rect.bottom)


if __name__ == "__main__":
    unittest.main()
