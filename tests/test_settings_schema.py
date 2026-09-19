"""Guards the persisted settings format.

Two contracts are load-bearing and neither is checked by anything else:

- the JSON key set written to data/json/settings_config.json
- the positional order of load_settings' return, which main.py unpacks by index

Both used to be restated five times across keybind_io, queries and main. They
are derived from one table now, which means a careless edit to that table could
silently shuffle every player's saved settings. The golden lists below are
written out by hand on purpose: they have to fail loudly if the table moves.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data.io import settings_schema

# The order load_settings has always returned, after the keybinds at index 0.
GOLDEN_ORDER = (
    "sfx_volume", "music_volume", "num_players", "ai_mode",
    "gemini_api_key", "chatgpt_api_key", "claude_api_key", "ollama_api_key",
    "gemini_model", "chatgpt_model", "claude_model", "ollama_model",
    "ai_immersion_level", "music_pitch", "sfx_pitch", "target_fps",
    "ai_threads", "show_fps", "show_intro_popup", "saves_dir",
    "custom_scenarios_dir", "ocean_light_color", "ocean_dark_color",
    "tournament_saves_dir", "checkerboard_water",
    "deepseek_api_key", "kimi_api_key", "deepseek_model", "kimi_model",
    "ai_turn_budget_seconds", "unit_art_style", "map_navigation_mode",
    "orders_key_changes_screen", "economy_key_changes_screen",
    "battle_display_mode",
    "mouse_button_actions",
)

GOLDEN_JSON_KEYS = set(GOLDEN_ORDER)


class SchemaContractTests(unittest.TestCase):
    def test_order_is_unchanged(self):
        """main.py unpacks this tuple by index. Appending is safe; reordering
        would hand every setting the value of a different one."""
        self.assertEqual(settings_schema.SETTINGS_ORDER, GOLDEN_ORDER)

    def test_json_keys_are_unchanged(self):
        """Renaming a key silently resets that setting for every player."""
        on_disk = {field.json_key for field in settings_schema.SETTINGS_FIELDS}
        self.assertEqual(on_disk, GOLDEN_JSON_KEYS)

    def test_tuple_length_matches_the_field_count(self):
        self.assertEqual(settings_schema.TUPLE_LENGTH, len(GOLDEN_ORDER) + 1)

    def test_every_field_has_a_usable_default(self):
        for name, value in settings_schema.defaults().items():
            with self.subTest(setting=name):
                self.assertIsNotNone(value)


class RoundTripTests(unittest.TestCase):
    def sample(self):
        values = settings_schema.defaults()
        values.update({"num_players": 3, "ai_mode": "OLLAMA", "target_fps": 144,
                       "show_fps": False, "saves_dir": "elsewhere",
                       "ocean_light_color": (1, 2, 3)})
        return values

    def test_json_round_trip(self):
        values = self.sample()
        self.assertEqual(settings_schema.from_json_dict(settings_schema.to_json_dict(values)),
                         values)

    def test_tuple_round_trip(self):
        values = self.sample()
        restored = settings_schema.from_tuple(settings_schema.to_tuple(values, {"BACK": 27}))
        self.assertEqual(restored, values)

    def test_keybinds_lead_the_tuple(self):
        binds = {"BACK": 27}
        self.assertIs(settings_schema.to_tuple(self.sample(), binds)[0], binds)

    def test_colors_come_back_as_tuples(self):
        """JSON has no tuple type, so a color saved as a list has to be
        coerced or it stops comparing equal to the constants."""
        values = settings_schema.from_json_dict({"ocean_light_color": [4, 5, 6]})
        self.assertEqual(values["ocean_light_color"], (4, 5, 6))

    def test_missing_keys_fall_back_to_defaults(self):
        values = settings_schema.from_json_dict({})
        self.assertEqual(values, settings_schema.defaults())

    def test_mouse_actions_migrate_partial_or_invalid_saved_data(self):
        values = settings_schema.from_json_dict({
            "mouse_button_actions": {
                "left": {"box_select_units": False, "unknown": True},
                "middle": "not an action mapping",
                "right": {"pan_map_outside_orders": True},
            }})
        actions = values["mouse_button_actions"]
        self.assertFalse(actions["left"]["box_select_units"])
        self.assertTrue(actions["left"]["select_units"])
        self.assertTrue(actions["middle"]["pan_map"])
        self.assertTrue(actions["right"]["pan_map"])
        self.assertTrue(actions["right"]["exclude_orders"])

    def test_legacy_key_names_are_still_read(self):
        """Settings files in the wild still use these older names."""
        values = settings_schema.from_json_dict(
            {"api_key": "legacy-gemini", "music_speed": 0.9, "sfx_speed": 0.1})
        self.assertEqual(values["gemini_api_key"], "legacy-gemini")
        self.assertEqual(values["music_pitch"], 0.9)
        self.assertEqual(values["sfx_pitch"], 0.1)

    def test_short_tuple_from_an_older_build_is_tolerated(self):
        """Replaces main.py's chain of `len(loaded_data) > N` guards."""
        full = settings_schema.to_tuple(self.sample(), {})
        restored = settings_schema.from_tuple(full[:6])
        self.assertEqual(restored["num_players"], 3)
        self.assertEqual(restored["target_fps"], settings_schema.defaults()["target_fps"])

    def test_empty_sequence_yields_defaults(self):
        self.assertEqual(settings_schema.from_tuple(()), settings_schema.defaults())


class ControllerTests(unittest.TestCase):
    class Fake:
        pass

    def test_apply_then_read_back(self):
        controller = self.Fake()
        values = settings_schema.defaults()
        values["num_players"] = 4
        settings_schema.apply_to_controller(controller, values)
        self.assertEqual(controller.num_players, 4)
        self.assertEqual(settings_schema.from_controller(controller), values)

    def test_reading_a_bare_controller_gives_defaults(self):
        self.assertEqual(settings_schema.from_controller(self.Fake()),
                         settings_schema.defaults())


class SaveSignatureTests(unittest.TestCase):
    def test_save_settings_takes_exactly_the_schema_names(self):
        """queries.save_global_settings splats from_controller() into this, so
        the parameter names and the schema names have to stay in step. They
        must stay in step whenever a persisted preference is added or replaced."""
        import inspect
        from data.io import keybind_io

        params = list(inspect.signature(keybind_io.save_settings).parameters)
        self.assertEqual(params[0], "keybind_dict")
        self.assertEqual(tuple(params[1:]), settings_schema.SETTINGS_ORDER)

    def test_from_controller_supplies_every_parameter(self):
        controller = ControllerTests.Fake()
        settings_schema.apply_to_controller(controller, settings_schema.defaults())
        self.assertEqual(set(settings_schema.from_controller(controller)),
                         set(settings_schema.SETTINGS_ORDER))


class RuntimeMirrorTests(unittest.TestCase):
    """data.constants mirrors a few settings for code too low-level to reach
    the Controller. Six call sites used to copy them across by hand."""

    def test_only_the_named_settings_are_mirrored(self):
        for name in c.RUNTIME_SETTINGS:
            with self.subTest(setting=name):
                self.assertIn(name, settings_schema.SETTINGS_ORDER)

    def test_every_mirrored_constant_exists(self):
        for constant in c.RUNTIME_SETTINGS.values():
            with self.subTest(constant=constant):
                self.assertTrue(hasattr(c, constant))

    def test_applying_writes_the_constants(self):
        originals = {n: getattr(c, n) for n in c.RUNTIME_SETTINGS.values()}
        try:
            c.apply_runtime_settings({"saves_dir": "somewhere",
                                      "checkerboard_water": not originals["CHECKERBOARD_WATER"]})
            self.assertEqual(c.SAVES_DIR, "somewhere")
            self.assertEqual(c.CHECKERBOARD_WATER, not originals["CHECKERBOARD_WATER"])
        finally:
            for name, value in originals.items():
                setattr(c, name, value)

    def test_settings_it_was_not_given_are_left_alone(self):
        """A screen that changed one setting passes just that one."""
        before = c.SCENARIOS_CUSTOM_DIR
        c.apply_runtime_settings({"saves_dir": c.SAVES_DIR})
        self.assertEqual(c.SCENARIOS_CUSTOM_DIR, before)


class NavigationIntroPopupTests(unittest.TestCase):
    def test_intro_popup_uses_mouse_assets_and_is_draggable(self):
        """The tutorial is a live map popup, not a snapshot modal screen."""
        import pygame
        from ui.confirm_dialog import message_box

        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        map_stub = type("MapStub", (), {"navigation_intro_popup": None})()
        popup = message_box._NavigationIntroPopup(map_stub)
        map_stub.navigation_intro_popup = popup
        self.assertEqual(popup.rect.center, (
            c.SCREEN_WIDTH // 2,
            c.SCREEN_HEIGHT // 2 + popup.INITIAL_CENTER_Y_OFFSET,
        ))
        self.assertGreater(popup.rect.width, 720)
        self.assertGreater(popup.rect.height, 370)
        self.assertEqual(len(popup.PAGE_TITLES), len(popup.PAGE_SUBTITLES))
        self.assertTrue(all(isinstance(text, str) and text
                            for text in popup.PAGE_TITLES + popup.PAGE_SUBTITLES))

        image = pygame.Surface((64, 74), pygame.SRCALPHA)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        with mock.patch.object(message_box.ui_bars, "get_ui_image", return_value=image) as get_image:
            popup.draw(surface)

        self.assertEqual(
            [call.args[0] for call in get_image.call_args_list],
            ["Left.png", "Middle.png", "Right.png"])
        self.assertTrue(all(call.kwargs["directory"] == popup.MOUSE_DIR
                            for call in get_image.call_args_list))
        self.assertEqual(len(popup.NAVIGATION_BUTTONS), 3)
        self.assertTrue(all(len(lines) >= 1
                            for _filename, _heading, lines in popup.NAVIGATION_BUTTONS))
        self.assertEqual(popup.KEYBOARD_NAVIGATION[0], "ARROW KEYS")
        self.assertTrue(popup.KEYBOARD_NAVIGATION[1])
        self.assertNotIn("mouse gestures", popup.KEYBOARD_NAVIGATION[1].lower())
        self.assertIn("mouse gestures", popup.MOUSE_GESTURE_SETTINGS_NOTE.lower())
        self.assertTrue(all(
            popup.body_font.size(line)[0] <= popup.navigation_caption_width
            for captions in popup.navigation_caption_lines
            for wrapped_lines in captions
            for line in wrapped_lines
        ))
        self.assertLess(popup.keyboard_navigation_rect.bottom,
                        popup.checkbox_rect.top)
        self.assertGreaterEqual(popup.mouse_gesture_note_rect.top,
                                popup.keyboard_navigation_rect.bottom)
        self.assertFalse(popup.mouse_gesture_note_rect.colliderect(
            popup.keyboard_navigation_rect))
        self.assertLessEqual(popup.mouse_gesture_note_rect.bottom,
                             popup.checkbox_rect.top)
        self.assertTrue(popup.rect.contains(popup.mouse_gesture_note_rect))

        # Unit selection and map panning pass through the panel while active.
        self.assertFalse(popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.rect.center, button=2)))
        self.assertFalse(popup.handle_event(pygame.event.Event(
            pygame.MOUSEMOTION, pos=popup.rect.center, rel=(5, 5), buttons=(0, 0, 1))))

        original = popup.rect.topleft
        # Any non-control part of the panel can be grabbed, not just its title.
        drag_point = popup.rect.center
        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=drag_point, button=1))
        popup.handle_event(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(drag_point[0] + 45, drag_point[1] + 25)))
        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONUP, pos=drag_point, button=1))
        self.assertNotEqual(popup.rect.topleft, original)

        # Escape closes the province/menu underneath the live popup; it must
        # not also discard the popup when the map receives that same key.
        self.assertFalse(popup.handle_event(pygame.event.Event(
            pygame.KEYDOWN, key=pygame.K_ESCAPE)))
        self.assertIs(map_stub.navigation_intro_popup, popup)

        with mock.patch.object(message_box.queries, "get_settings", return_value={}), \
             mock.patch.object(message_box.queries, "save_cached_json") as save:
            popup.handle_event(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=popup.checkbox_rect.center, button=1))
        save.assert_called_once_with("settings", {"show_intro_popup": False})

        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.next_rect.center, button=1))
        self.assertEqual(popup.page_index, 1)
        subtitle_lines = popup._subtitle_lines()
        self.assertTrue(subtitle_lines)
        self.assertTrue(all(popup.body_font.size(line)[0] <= popup.rect.width -
                            (2 * popup.SUBTITLE_SIDE_PADDING)
                            for line in subtitle_lines))
        self.assertEqual(len(popup.MAP_UI_BUTTONS), 10)
        self.assertTrue(all(icon for _label, icon, _description in popup.MAP_UI_BUTTONS))
        with mock.patch.object(message_box.ui_elements, "UI_ICONS", {
                icon: image for _label, icon, _description in popup.MAP_UI_BUTTONS}):
            popup.draw(surface)

        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.next_rect.center, button=1))
        self.assertEqual(popup.page_index, 2)
        self.assertEqual([icon for _heading, icon, _description in popup.DIPLOMACY_STEPS],
                         ["mail", "relations"])
        self.assertTrue(all(popup.body_font.size(line)[0] <= popup.rect.width -
                            (2 * popup.SUBTITLE_SIDE_PADDING)
                            for line in popup._subtitle_lines()))
        popup.draw(surface)

        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.next_rect.center, button=1))
        self.assertEqual(popup.page_index, 3)
        self.assertTrue(all(popup.body_font.size(line)[0] <= popup.rect.width -
                            (2 * popup.SUBTITLE_SIDE_PADDING)
                            for line in popup._subtitle_lines()))
        self.assertEqual(len(popup.ARMY_STEPS), 4)
        self.assertTrue(all(len(step) == 2 for step in popup.ARMY_STEPS))
        popup.draw(surface)

        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.prev_rect.center, button=1))
        self.assertEqual(popup.page_index, 2)

        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.prev_rect.center, button=1))
        self.assertEqual(popup.page_index, 1)

        popup.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=popup.close_rect.center, button=1))
        self.assertIsNone(map_stub.navigation_intro_popup)

    def test_map_message_popups_hide_for_a_province_menu_without_being_cleared(self):
        from ui import diplomatic_popups

        map_stub = type("MapStub", (), {"selected_province": None})()
        self.assertTrue(diplomatic_popups.map_message_popups_visible(map_stub))

        map_stub.selected_province = {"id": 1}
        self.assertFalse(diplomatic_popups.map_message_popups_visible(map_stub))

        map_stub.selected_province = None
        self.assertTrue(diplomatic_popups.map_message_popups_visible(map_stub))


class KeybindIoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pygame

        pygame.init()

    def test_load_settings_returns_the_documented_shape(self):
        from data.io import keybind_io
        import pygame

        result = keybind_io.load_settings({"BACK": pygame.K_ESCAPE})
        self.assertEqual(len(result), settings_schema.TUPLE_LENGTH)
        self.assertIsInstance(result[0], dict)
        self.assertIn("BACK", result[0])

    def test_older_keybind_map_gets_new_action_default(self):
        """Adding an action must not require players to delete old settings."""
        from data.io import keybind_io
        import pygame

        defaults = {"BACK": pygame.K_ESCAPE, "CLEAR_ORDERS": pygame.K_DELETE}
        loaded = keybind_io._load_keybinds(
            {"keybinds": {"BACK": pygame.key.name(pygame.K_q)}}, defaults)

        self.assertEqual(loaded["BACK"], pygame.K_q)
        self.assertEqual(loaded["CLEAR_ORDERS"], pygame.K_DELETE)

    def test_defaults_track_the_runtime_constants(self):
        """Several defaults live on data.constants and are overwritten at
        startup, so they have to be read when asked for, not at import."""
        original = c.TARGET_FPS
        try:
            c.TARGET_FPS = 999
            self.assertEqual(settings_schema.defaults()["target_fps"], 999)
        finally:
            c.TARGET_FPS = original

    def test_battle_display_defaults_to_full(self):
        self.assertEqual(settings_schema.defaults()["battle_display_mode"], "FULL")

    def test_intro_popup_defaults_to_enabled(self):
        self.assertTrue(settings_schema.defaults()["show_intro_popup"])


if __name__ == "__main__":
    unittest.main()
