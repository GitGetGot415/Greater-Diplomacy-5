"""Check first-use preferences and preservation of saved player choices."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from data import queries
from data.io import keybind_io, starting_defaults
from screens.setup.scenario_settings import Scenario_Settings


class StartingDefaultsTests(unittest.TestCase):
    def test_defaults_are_independent_copies(self):
        first = starting_defaults.get_starting_default("scenario_settings.json")
        expected = copy.deepcopy(first)
        first["unit_turn_overrides"]["Fixture"] = 5
        self.assertEqual(starting_defaults.get_starting_default("scenario_settings.json"), expected)

    def test_invalid_sections_report_the_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "defaults.json")
            for value in ([], {}, dict(starting_defaults.read_starting_defaults(), **{"active_albums.json": {}})):
                path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "defaults.json"):
                    starting_defaults.read_starting_defaults(path)

    def test_missing_preferences_use_defaults_and_save_choices(self):
        cases = {
            "scenario_settings": ({"fog_of_war": False}, {"fog_of_war": True}),
            "active_albums": (["Fixture"], []),
            "starting_song": ({"track": "assets/music/Fixture/start.ogg"}, {"track": None}),
            "shuffle_disabled_tracks": (["assets/music/Fixture/skip.ogg"], []),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for key, (default, saved) in cases.items():
                path = Path(temporary, f"{key}.json")
                entry = dict(queries._JSON_CACHE[key], path=str(path), data=None)
                with self.subTest(key=key), mock.patch.dict(queries._JSON_CACHE, {key: entry}), \
                        mock.patch.object(starting_defaults, "get_starting_default", return_value=copy.deepcopy(default)) as get:
                    self.assertEqual(queries._load_cached_json(key), default)
                    get.assert_called_once_with(entry["default"])
                    queries.save_cached_json(key, saved)
                    entry["data"] = None
                    get.reset_mock()
                    self.assertEqual(queries._load_cached_json(key), saved)
                    get.assert_not_called()

    def test_first_use_general_settings_and_keybinds(self):
        default = {"keybinds": {"BACK": None}, "music_volume": 0.23, "show_fps": True}
        with mock.patch.object(keybind_io.os.path, "exists", return_value=False), \
                mock.patch.object(starting_defaults, "get_starting_default", return_value=default):
            result = keybind_io.load_settings_result({"BACK": 27}, 0.4, 0.6)
        self.assertIsNone(result.keybinds["BACK"])
        self.assertEqual(result.values["music_volume"], default["music_volume"])
        self.assertTrue(result.values["show_fps"])
        self.assertEqual(result.values["sfx_volume"], 0.4)

    def test_existing_general_settings_keep_their_values(self):
        saved = {"keybinds": {"BACK": None}, "music_volume": 0.37}
        with mock.patch.object(keybind_io.os.path, "exists", return_value=True), \
                mock.patch.object(queries, "get_settings", return_value=saved), \
                mock.patch.object(starting_defaults, "get_starting_default") as get:
            result = keybind_io.load_settings_result({"BACK": 27})
        self.assertEqual(result.values["music_volume"], saved["music_volume"])
        self.assertIsNone(result.keybinds["BACK"])
        get.assert_not_called()

    def test_scenario_reset_uses_starting_values_and_keeps_editor_values(self):
        screen = object.__new__(Scenario_Settings)
        screen.settings = {"fog_of_war": True, "unit_turn_overrides": {"Fixture": 3}}
        screen._save_settings = mock.Mock()
        screen.refresh_ui = mock.Mock()
        defaults = queries.get_default_scenario_settings()
        defaults["fog_of_war"] = False
        with mock.patch.object(queries, "get_default_scenario_settings", return_value=defaults):
            screen.reset_defaults()
        self.assertFalse(screen.settings["fog_of_war"])
        self.assertEqual(screen.settings["unit_turn_overrides"], {"Fixture": 3})
        screen._save_settings.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
