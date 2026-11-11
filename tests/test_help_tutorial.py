"""The Help window reads checked content, and its category list opens topics."""
import ast
import copy
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

    def test_mode_fields_accept_only_supported_modes_and_name_invalid_fields(self):
        for level in ("category", "topic"):
            for mode in ("strategic", "tactical", None, "", "both", [], True):
                with self.subTest(level=level, mode=mode):
                    content = artificial_content()
                    category = content["categories"][0]
                    entry = category if level == "category" else category["topics"][0]
                    entry["mode"] = mode
                    if mode in ("strategic", "tactical"):
                        self.assertIs(message_box.validate_tutorial(content), content)
                    else:
                        field = "categories[0]" + (".topics[0]" if level == "topic" else "") + ".mode"
                        with self.assertRaisesRegex(ValueError, re.escape(field)):
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
        self.map_stub = SimpleNamespace(navigation_intro_popup=None, tactical_mode=False)
        settings = mock.patch.object(message_box.queries, "get_settings", return_value={})
        self.saved_settings = settings.start()
        self.addCleanup(settings.stop)

    def popup(self, content=None):
        with mock.patch.object(message_box, "load_tutorial", return_value=content or artificial_content()):
            return _NavigationIntroPopup(self.map_stub)

    def click(self, popup, pos):
        return popup.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))

    def rail_row(self, popup, kind, index):
        return next(rect for rect, row_kind, row_index in popup.rail_rows
                    if row_kind == kind and row_index == index)

    def test_checkbox_only_changes_the_current_modes_startup_preference(self):
        for tactical_mode in (False, True):
            with self.subTest(tactical_mode=tactical_mode):
                self.map_stub.tactical_mode = tactical_mode
                name = message_box.settings_schema.intro_popup_setting(tactical_mode)
                other = message_box.settings_schema.intro_popup_setting(not tactical_mode)
                saved = {name: True, other: True, "keybinds": {"BACK": None}}
                self.saved_settings.return_value = saved
                popup = self.popup()
                self.assertFalse(popup.dont_show_again)
                with mock.patch.object(message_box.queries, "save_cached_json") as save:
                    self.click(popup, popup.checkbox_rect.center)
                expected = dict(saved, **{name: False})
                save.assert_called_once_with("settings", expected)
                self.saved_settings.return_value = expected
                reopened = self.popup()
                self.assertTrue(reopened.dont_show_again)
                with mock.patch.object(message_box.queries, "save_cached_json") as save:
                    self.click(reopened, reopened.checkbox_rect.center)
                save.assert_called_once_with("settings", saved)

    def test_checkbox_uses_the_new_modes_preference_after_a_mode_change(self):
        self.saved_settings.return_value = {"show_strategic_intro_popup": False, "show_tactical_intro_popup": True}
        popup = self.popup()
        self.assertTrue(popup.dont_show_again)
        self.map_stub.tactical_mode = True
        with mock.patch.object(message_box.queries, "save_cached_json") as save:
            self.click(popup, popup.checkbox_rect.center)
        self.assertTrue(popup.dont_show_again)
        save.assert_called_once_with("settings", {"show_strategic_intro_popup": False, "show_tactical_intro_popup": False})

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

    def test_every_shipped_category_and_topic_can_be_opened(self):
        """Category additions must remain reachable through the real Help navigation."""
        content = message_box.load_tutorial(SHIPPED_PATH)
        for tactical in (False, True):
            self.map_stub.tactical_mode = tactical
            popup = self.popup(content)
            for category_index, category in enumerate(popup.categories):
                with self.subTest(tactical=tactical, category=category["title"]):
                    popup.select_topic(None)
                    self.assertTrue(self.click(popup, self.rail_row(popup, "category", category_index).center))
                    self.assertEqual(popup.topics[popup.topic_index], (category_index, 0))
                    for topic_index in range(len(category["topics"])):
                        index = popup.first_topic[category_index] + topic_index
                        self.assertTrue(self.click(popup, self.rail_row(popup, "topic", index).center))
                        self.assertEqual(popup.topics[popup.topic_index], (category_index, topic_index))

    def test_shipped_categories_follow_the_requested_mode_restrictions(self):
        strategic_only = {"Aircraft", "Production", "Economy", "Research", "Diplomacy", "Units & Orders", "Combat"}
        content = message_box.load_tutorial(SHIPPED_PATH)
        for tactical in (False, True):
            with self.subTest(tactical=tactical):
                self.map_stub.tactical_mode = tactical
                titles = {category["title"] for category in self.popup(content).categories}
                self.assertEqual("Tactical Mode" in titles, tactical)
                if tactical:
                    self.assertTrue(titles.isdisjoint(strategic_only))
                else:
                    self.assertLessEqual(strategic_only, titles)

    def test_categories_and_topics_filter_without_mutating_cached_content(self):
        content = artificial_content()
        first, second = content["categories"]
        first["topics"][0]["mode"] = "strategic"
        first["topics"][1]["mode"] = "tactical"
        first["topics"].append({"title": "Shared", "blocks": [{"type": "text", "text": "Both modes"}]})
        second["mode"] = "strategic"
        content["categories"].append({
            "title": "Conflicting restrictions", "mode": "strategic", "topics": [
                {"title": "Hidden", "mode": "tactical", "blocks": [{"type": "text", "text": "Hidden"}]}]})
        original = copy.deepcopy(content)
        for tactical in (False, True):
            with self.subTest(tactical=tactical):
                self.map_stub.tactical_mode = tactical
                popup = self.popup(content)
                self.assertEqual([topic["title"] for topic in popup.categories[0]["topics"]],
                                 ["Two" if tactical else "One", "Shared"])
                self.assertEqual([category["title"] for category in popup.categories],
                                 ["First"] if tactical else ["First", "Second"])
        self.assertEqual(content, original)

    def test_previous_next_and_resume_use_visible_topics_and_stable_source_indices(self):
        content = artificial_content()
        content["categories"][0]["topics"][0]["mode"] = "tactical"
        content["categories"][1]["mode"] = "strategic"
        with mock.patch.object(message_box, "load_tutorial", return_value=content):
            message_box.show_navigation_intro(self.map_stub)
            popup = self.map_stub.navigation_intro_popup
            self.assertEqual(popup.topics[popup.topic_index], (0, 0))  # Shared "Two", source index 1.
            self.assertEqual(_NavigationIntroPopup.last_topic_index, 1)
            self.click(popup, popup.next_rect.center)
            self.assertEqual(popup.topics[popup.topic_index], (1, 0))
            self.click(popup, popup.prev_rect.center)
            self.assertEqual(_NavigationIntroPopup.last_topic_index, 1)

            self.map_stub.tactical_mode = True
            message_box.show_navigation_intro(self.map_stub, resume=True)
            popup = self.map_stub.navigation_intro_popup
            self.assertEqual(popup.topics[popup.topic_index], (0, 1))  # Same source topic, new visible index.

            self.map_stub.tactical_mode = False
            message_box.show_navigation_intro(self.map_stub)
            self.map_stub.navigation_intro_popup.select_topic(1)  # Strategic-only source topic 2.
            self.map_stub.tactical_mode = True
            message_box.show_navigation_intro(self.map_stub, resume=True)
            popup = self.map_stub.navigation_intro_popup
            self.assertEqual(popup.topic_index, 0)  # Hidden remembered topic falls back to visible content.
            self.assertEqual(popup._page_buttons_enabled(), (False, True))
            self.click(popup, popup.next_rect.center)
            self.assertEqual(popup._page_buttons_enabled(), (True, False))

    def test_open_help_refreshes_on_mode_changes_without_rebuilding_each_frame(self):
        content = artificial_content()
        content["categories"][0]["mode"] = "strategic"
        content["categories"][1]["mode"] = "tactical"
        with mock.patch.object(message_box, "load_tutorial", return_value=content):
            popup = _NavigationIntroPopup(self.map_stub)
            surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
            with mock.patch.object(popup, "_prepare_categories", wraps=popup._prepare_categories) as prepare:
                popup.draw(surface)
                prepare.assert_not_called()
                self.map_stub.tactical_mode = True
                popup.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
                self.assertEqual([category["title"] for category in popup.categories], ["Second"])
                self.assertEqual(popup.topic_index, 0)
                popup.draw(surface)
                prepare.assert_called_once()
                self.map_stub.tactical_mode = False
                popup.draw(surface)
                self.assertEqual([category["title"] for category in popup.categories], ["First"])
                self.assertEqual(prepare.call_count, 2)

    def test_all_hidden_content_leaves_a_safe_empty_help_window(self):
        content = artificial_content()
        for category in content["categories"]:
            category["mode"] = "tactical"
        popup = self.popup(content)
        self.assertEqual(popup.categories, [])
        self.assertEqual(popup.topics, ())
        self.assertIsNone(popup.topic_index)
        self.assertEqual(popup._page_buttons_enabled(), (False, False))
        self.click(popup, popup.next_rect.center)
        self.assertIsNone(popup.topic_index)
        popup.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))

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
