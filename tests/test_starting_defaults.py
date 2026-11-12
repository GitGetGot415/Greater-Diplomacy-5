"""Check first-use preferences and preservation of saved player choices."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from data import queries
from data.io import keybind_io, settings_schema, starting_defaults
from screens.setup.scenario_settings import Scenario_Settings


class StartingDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.defaults = starting_defaults.read_starting_defaults()
        self.cache = mock.patch.object(starting_defaults, "_cached_defaults", return_value=self.defaults)
        self.cache.start()
        self.addCleanup(self.cache.stop)

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

    def test_schema_defaults_and_partial_legacy_settings_read_distribution_values(self):
        config = self.defaults["settings_config.json"]
        config.update(num_players=3, sfx_pitch=0.27, music_pitch=0.83, show_strategic_intro_popup=False, show_tactical_intro_popup=True,
                      target_fps=37, ocean_light_color=[4, 5, 6])
        self.assertEqual(set(config) - {"keybinds"}, {f.json_key for f in settings_schema.SETTINGS_FIELDS})
        expected = settings_schema.defaults()
        for name, value in config.items():
            if name != "keybinds":
                self.assertEqual(expected[name], tuple(value) if name.endswith("_color") else value)
        with mock.patch.object(keybind_io.os.path, "exists", return_value=True), \
                mock.patch.object(queries, "get_settings", return_value={"music_volume": 0.37}):
            loaded = keybind_io.load_settings_result(keybind_io.default_keybinds())
        self.assertEqual(loaded.values, dict(expected, music_volume=0.37))

    def test_writer_uses_json_for_omitted_options_and_preserves_explicit_values(self):
        self.defaults["settings_config.json"].update(ai_threads=7, show_fps=True, music_pitch=0.31)
        with mock.patch.object(queries, "save_cached_json") as save:
            keybind_io.save_settings({}, 0.2, 0.4, show_fps=False)
        values = save.call_args.args[1]
        self.assertEqual(values["ai_threads"], 7)
        self.assertEqual(values["music_pitch"], 0.31)
        self.assertFalse(values["show_fps"])

    def test_keybind_startup_reset_and_missing_action_fallback_agree(self):
        import pygame
        from screens.menus.keybinds import Keybinds
        names = self.defaults["settings_config.json"]["keybinds"]
        names.update(BACK="b", PAN_LEFT="a", MOUSE_LEFT_CLICK="z", ORDERS=None)
        self.defaults["settings_config.json"]["orders_key_changes_screen"] = False
        defaults = keybind_io.default_keybinds()
        with mock.patch.object(queries, "get_settings", return_value={"keybinds": {"PAN_LEFT": None}}):
            self.assertEqual(queries.get_keybind("BACK", pygame.K_ESCAPE), pygame.K_b)
            self.assertIsNone(queries.get_keybind("PAN_LEFT", pygame.K_LEFT))
            self.assertIsNone(queries.get_keybind("ORDERS", pygame.K_q))
            self.assertFalse(queries.get_keybind_changes_screen("ORDERS"))
        screen = object.__new__(Keybinds)
        screen.controller = SimpleNamespace(keybinds={}, orders_key_changes_screen=True,
                                            economy_key_changes_screen=False)
        screen.refresh_ui = mock.Mock()
        with mock.patch.object(queries, "save_global_settings") as save:
            screen.reset_defaults()
        self.assertEqual(screen.controller.keybinds, defaults)
        self.assertFalse(screen.controller.orders_key_changes_screen)
        save.assert_called_once_with(screen.controller)

    def test_general_settings_reset_uses_json_and_keeps_its_existing_scope(self):
        import data.constants as c
        from screens.menus.settings import Settings
        self.defaults["settings_config.json"].update(target_fps=39, show_fps=True,
                                                    checkerboard_water=True, show_strategic_intro_popup=False, show_tactical_intro_popup=True)
        screen = object.__new__(Settings)
        screen.controller = SimpleNamespace(**settings_schema.defaults(), keybinds={})
        screen.controller.gemini_api_key = "player-key"
        screen.controller.music_volume = 0.21
        screen.controller.target_fps = 80
        screen.target_fps = 80
        screen.refresh_ui = mock.Mock()
        screen.reset_setting = mock.Mock()
        with mock.patch.object(queries, "save_global_settings") as save, \
                mock.patch.object(c, "apply_runtime_settings") as apply:
            screen.reset_defaults()
        self.assertEqual(screen.controller.target_fps, 39)
        self.assertEqual(screen.target_fps, 39)
        self.assertTrue(screen.controller.show_fps)
        self.assertFalse(screen.controller.show_strategic_intro_popup)
        self.assertTrue(screen.controller.show_tactical_intro_popup)
        self.assertEqual(apply.call_args.args[0]["checkerboard_water"], True)
        self.assertEqual(screen.controller.gemini_api_key, "player-key")
        self.assertEqual(screen.controller.music_volume, 0.21)
        save.assert_called_once_with(screen.controller)

    def test_path_color_and_model_resets_read_json(self):
        from screens.menus.settings import Settings
        screen = object.__new__(Settings)
        screen.apply_setting = mock.Mock()
        for key, value in (("saves_dir", "fixture-saves"), ("ocean_light_color", [4, 5, 6])):
            self.defaults["settings_config.json"][key] = value
            screen.reset_setting(key)
            screen.apply_setting.assert_called_with(key, tuple(value) if isinstance(value, list) else value,
                                                    refresh=True)
        self.defaults["settings_config.json"]["gemini_model"] = "fixture-model"
        screen.field_attr = mock.Mock(return_value="gemini_model")
        screen.set_field = mock.Mock()
        screen.refresh_ui = mock.Mock()
        screen.reset_model_default()
        screen.set_field.assert_called_once_with("MOD", "fixture-model")

    def test_mouse_reset_reads_json(self):
        import data.constants as c
        from screens.menus.mouse_settings import Mouse_Settings
        actions = self.defaults["settings_config.json"]["mouse_button_actions"]
        actions["left"]["issue_orders"] = True
        screen = object.__new__(Mouse_Settings)
        screen.controller = SimpleNamespace(mouse_button_actions={})
        screen.refresh_ui = mock.Mock()
        with mock.patch.object(queries, "save_global_settings"), mock.patch.object(c, "apply_runtime_settings"):
            screen.reset_defaults()
        self.assertEqual(screen.controller.mouse_button_actions, actions)
        screen.controller.mouse_button_actions["left"]["issue_orders"] = False
        self.assertTrue(actions["left"]["issue_orders"])

    def test_audio_reset_reads_each_configured_value_and_updates_playback(self):
        import data.constants as c
        from screens.menus.music_player import Music_Player
        from ui import sound_effects
        config = self.defaults["settings_config.json"]
        config.update(sfx_volume=0.23, music_volume=0.67, sfx_pitch=0.34,
                      music_pitch=0.78, music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_DYNAMIC)
        player = object.__new__(Music_Player)
        player.controller = SimpleNamespace(music=None, now_playing="None")
        player.refresh_ui = mock.Mock()
        with mock.patch.object(queries, "save_global_settings") as save, \
                mock.patch.object(sound_effects, "set_sfx_volume") as volume, \
                mock.patch.object(sound_effects, "set_sfx_pitch") as pitch:
            player.reset_audio_defaults()
        for key in ("sfx_volume", "music_volume", "sfx_pitch", "music_pitch", "music_pitch_timeline"):
            self.assertEqual(getattr(player.controller, key), config[key])
        volume.assert_called_once_with(config["sfx_volume"])
        pitch.assert_called_once_with(config["sfx_pitch"])
        self.assertTrue(save.called)

    def test_constants_and_provider_fallbacks_read_json_before_game_startup(self):
        # Use a fresh interpreter so constants initialize from the artificial defaults.
        script = '''
from data.io import starting_defaults
defaults = starting_defaults.read_starting_defaults()
defaults["settings_config.json"].update(target_fps=39, show_fps=True, ai_threads=6,
    ocean_light_color=[4, 5, 6], ai_immersion_level="FULL")
defaults["scenario_settings.json"].update(fog_of_war=False, truce_turns=3,
    turns_to_wait_before_war=7, ai_war_declaration_chance=0.23)
defaults["hildehrand_choice.json"].update(variant="fixture.png", gradient_dithering=True)
defaults["ai_defaults"].update(local_threads=2, reenable_mode="GEMINI", ollama_url="http://fixture/api/chat")
starting_defaults._cached_defaults = lambda: defaults
import data.constants as c
assert (c.TARGET_FPS, c.SHOW_FPS, c.DEFAULT_AI_THREADS) == (39, True, 6)
assert c.OCEAN_LIGHT_BLUE == (4, 5, 6)
assert c.DEFAULT_FOG_OF_WAR is False and c.DEFAULT_TRUCE_TURNS == 3
assert c.TURNS_TO_WAIT_BEFORE_WAR == 7 and c.AI_WAR_DECLARATION_CHANCE == 0.23
assert c.DEFAULT_AI_THREADS_LOCAL == 2 and c.AI_MODE_REENABLE_FALLBACK == "GEMINI"
from data import queries
assert queries.DEFAULT_PORTRAIT == "fixture.png" and queries.DEFAULT_PORTRAIT_DITHERING is True
from map_logic.ai import ai_settings
queries.get_settings = lambda: {}
assert ai_settings.get_ai_immersion_level() == "FULL"
assert ai_settings.get_ollama_url() == "http://fixture/api/chat"
'''
        result = subprocess.run([sys.executable, "-c", script], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_portrait_defaults_reset_and_saved_round_trip(self):
        from screens.menus.edit_portrait import Edit_Portrait
        defaults = self.defaults["hildehrand_choice.json"]
        defaults.update(variant="fixture.png", gradient=False, gradient_strength=0.4,
                        gradient_stepped=True, gradient_bands=7, gradient_dithering=True)
        menu = SimpleNamespace()
        menu.set_hildehrand_choice = mock.Mock()
        screen = object.__new__(Edit_Portrait)
        screen.controller = SimpleNamespace(states={"MENU": menu})
        screen.refresh_ui = mock.Mock()
        screen.reset_settings()
        menu.set_hildehrand_choice.assert_called_once_with(defaults["variant"])
        for suffix, key in (("gradient", "gradient"), ("gradient_strength", "gradient_strength"),
                            ("gradient_stepped", "gradient_stepped"), ("gradient_bands", "gradient_bands"),
                            ("gradient_dithering", "gradient_dithering")):
            self.assertEqual(getattr(menu, "hildehrand_" + suffix), defaults[key])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "portrait.json")
            entry = dict(queries._JSON_CACHE["hildehrand_choice"], path=str(path), data=None)
            with mock.patch.dict(queries._JSON_CACHE, {"hildehrand_choice": entry}), \
                    mock.patch.object(queries.content, "discover_character_images", return_value=["saved.png"]):
                self.assertEqual(queries.get_hildehrand_choice(), defaults["variant"])
                self.assertEqual(queries.get_hildehrand_gradient(), (False, 0.4, True, 7))
                self.assertTrue(queries.get_hildehrand_dithering())
                queries.save_hildehrand_portrait("saved.png", True, 0.8, False, 5, gradient_dithering=False)
                entry["data"] = None
                self.assertEqual(queries.get_hildehrand_choice(), "saved.png")
                self.assertEqual(queries.get_hildehrand_gradient(), (True, 0.8, False, 5))
                self.assertFalse(queries.get_hildehrand_dithering())
                entry["data"] = {"variant": "saved.png"}
                self.assertEqual(queries.get_hildehrand_gradient(), (False, 0.4, True, 7))
                self.assertTrue(queries.get_hildehrand_dithering())

    def test_random_setup_reset_reads_json_and_clamps_to_available_content(self):
        import data.constants as c
        from screens.setup.random_setup import Random_Setup
        defaults = self.defaults["random_setup"]
        defaults.update(start_year=c.START_YEAR + 3, num_countries=90, island_filter=3,
                        single_tile_start=True, resource_chance=0.43, base_days_per_turn=11, map_index=8)
        screen = object.__new__(Random_Setup)
        screen.max_countries = 4
        screen.available_maps = ["fixture"]
        screen.reset_to_defaults()
        self.assertEqual(screen.current_year, defaults["start_year"])
        self.assertEqual(screen.current_countries, 4)
        self.assertEqual(screen.current_island_size, 3)
        self.assertTrue(screen.single_tile_start)
        self.assertEqual(screen.resource_chance, 0.43)
        self.assertEqual(screen.base_days_per_turn, 11)
        self.assertEqual(screen.map_index, 0)


if __name__ == "__main__":
    unittest.main()
