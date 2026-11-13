"""Check editor metadata, scenario names, save collisions, and older-save defaults."""

import asyncio
import base64
import copy
import json
import os
import tempfile
import unittest
from types import MethodType, SimpleNamespace
from unittest import mock

from data import constants as c, queries
from data import platform
from data.map import load_map, save_map
from screens.editors import menus as editor_menus
from screens.editors import standalone_export
from screens.editors.date_economy_screens import Editor_Metadata_Screen
from screens.editors.standalone_export import Standalone_Export_Screen
from tests.stub_map_screen import map_double


def editor():
    return map_double(
        is_editor=True, player_country="Editor", editor_scenario_name="",
        map_data={"p": {"id": 1, "json_key": "p", "owner": "A", "cores": ["A"], "units": []}},
        raw_json_data={"p": {"id": 1, "owner": "A"}}, nation_data={"A": {"materials": 4}},
        scenario_metadata={}, terrain_map=object(), id_map=object(), show_feedback=mock.Mock())


class ScenarioMetadataTests(unittest.TestCase):
    def setUp(self):
        self.game = editor()
        self.directory = os.path.realpath(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(c, "SCENARIOS_CUSTOM_DIR", self.directory))
        self.enterContext(mock.patch.object(queries, "get_country_data", return_value={}))
        self.enterContext(mock.patch("data.queries.saves.get_research_years", return_value={}))
        self.picker = self.enterContext(mock.patch.object(
            editor_menus.pickers, "open_file_browser", side_effect=self.pick_default))

    @staticmethod
    def pick_default(_context, _title, start_dir, **kwargs):
        return kwargs["on_result"](os.path.join(start_dir, kwargs["initial_name"]))

    def test_apply_validates_before_changing_state_and_preserves_unknown_metadata(self):
        self.game.scenario_metadata = {"extension": {"keep": True}}
        queries.set_editor_metadata(self.game, " My Scenario ", "Author", "Description")
        self.assertEqual(self.game.editor_scenario_name, "My Scenario")
        self.assertEqual(self.game.scenario_metadata,
                         {"author": "Author", "description": "Description", "extension": {"keep": True}})
        before = copy.deepcopy(self.game.scenario_metadata)
        for name, author, description in (("../outside", "A", "D"), ("Name", None, "D"), ("Name", "A", [])):
            with self.subTest(name=name), self.assertRaises(ValueError):
                queries.set_editor_metadata(self.game, name, author, description)
            self.assertEqual(self.game.scenario_metadata, before)
            self.assertEqual(self.game.editor_scenario_name, "My Scenario")

    def test_permissions_rechecked_when_metadata_is_applied(self):
        for key, value in (("is_editor", False), ("multiplayer_mode", True), ("realtime_multiplayer", True),
                           ("tactical_mode", True), ("is_saving", True), ("is_refreshing", True),
                           ("ai_is_thinking", True), ("viewing_ai_moves", True)):
            with self.subTest(key=key), mock.patch.object(self.game, key, value), self.assertRaises(ValueError):
                queries.set_editor_metadata(self.game, "Name", "Author", "Description")
        self.assertEqual(self.game.scenario_metadata, {})

    def test_names_cannot_escape_the_scenario_directory(self):
        for name in ("../outside", "..", ".", "a/b", "a\\b", "C:outside", "bad?name", "ends.", "CON", "nul.txt"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                save_map.editor_save_path(name)
        self.assertEqual(queries.validated_scenario_name("  "), "")
        self.assertEqual(save_map.editor_save_path("Valid name"), os.path.join(self.directory, "Valid name"))

    def test_serializer_stores_author_and_description_without_the_folder_name(self):
        queries.set_editor_metadata(self.game, "Folder Name", "Creator", "Some text")
        saved = queries.build_save_dict(self.game, include_provinces=False)
        self.assertEqual(saved["scenario_metadata"], {"author": "Creator", "description": "Some text"})
        self.assertNotIn("editor_scenario_name", saved)
        self.assertNotIn("scenario_name", saved)
        saved["scenario_metadata"]["author"] = "Other"
        self.assertEqual(self.game.scenario_metadata["author"], "Creator")

    def test_older_maps_default_to_empty_metadata_and_name_uses_current_folder(self):
        self.game.scenario_metadata = {"author": "Previous author"}
        load_map.restore_scenario_metadata(self.game, {}, os.path.join(self.directory, "Renamed Folder"))
        self.assertEqual(self.game.scenario_metadata, {"author": "", "description": ""})
        self.assertEqual(self.game.editor_scenario_name, "Renamed Folder")
        load_map.restore_scenario_metadata(self.game, None)
        self.assertEqual(self.game.editor_scenario_name, "")
        self.game.is_editor = False
        load_map.restore_scenario_metadata(self.game, {}, os.path.join(self.directory, "Saved Game"))
        self.assertEqual(self.game.editor_scenario_name, "")

    def test_named_and_unnamed_saves_prefill_the_destination_picker(self):
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            ready = mock.Mock()
            self.game.editor_scenario_name = "Chosen Name"
            editor_menus.prepare_editor_save(self.game, ready)
            ready.assert_called_once_with(os.path.join(self.directory, "Chosen Name"), False)
            self.assertEqual(self.picker.call_args.kwargs["initial_name"], "Chosen Name")
            ready.reset_mock()
            self.game.editor_scenario_name = ""
            with mock.patch.object(editor_menus, "datetime") as clock:
                clock.now.return_value.strftime.return_value = "timestamp"
                editor_menus.prepare_editor_save(self.game, ready)
            ready.assert_called_once_with(os.path.join(self.directory, "MapExport_timestamp"), False)
            ask.assert_not_called()

    def test_canceling_the_destination_picker_does_not_prepare_a_save(self):
        self.picker.side_effect = lambda *_args, **kwargs: kwargs["on_result"](None)
        ready = mock.Mock()
        editor_menus.prepare_editor_save(self.game, ready)
        ready.assert_not_called()
        self.assertEqual(os.listdir(self.directory), [])

    def test_editor_save_rechecks_permissions_after_destination_selection(self):
        self.picker.side_effect = None
        ready = mock.Mock()
        editor_menus.prepare_editor_save(self.game, ready)
        self.game.multiplayer_mode = True
        self.picker.call_args.kwargs["on_result"](os.path.join(self.directory, "Chosen"))
        ready.assert_not_called()

    def test_collision_offers_overwrite_numbered_copy_and_cancel(self):
        self.game.editor_scenario_name = "Existing"
        for name in ("Existing", "Existing-1", "Existing-2"):
            os.mkdir(os.path.join(self.directory, name))
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            ready = mock.Mock()
            editor_menus.prepare_editor_save(self.game, ready)
            ready.assert_not_called()
            callback = ask.call_args.args[2]
            callback(None)
            ready.assert_not_called()
            callback(False)
            ready.assert_called_once_with(os.path.join(self.directory, "Existing-3"), False)
            ready.reset_mock()
            callback(True)
            ready.assert_called_once_with(os.path.join(self.directory, "Existing"), True)
            ready.reset_mock()
            self.game.realtime_multiplayer = True
            callback(True)
            ready.assert_not_called()

    def test_numbered_copy_skips_files_and_rechecks_names_at_confirmation(self):
        self.game.editor_scenario_name = "Existing"
        os.mkdir(os.path.join(self.directory, "Existing"))
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            ready = mock.Mock()
            editor_menus.prepare_editor_save(self.game, ready)
            with open(os.path.join(self.directory, "Existing-1"), "w") as handle:
                handle.write("Preserve")
            ask.call_args.args[2](False)
            ready.assert_called_once_with(os.path.join(self.directory, "Existing-2"), False)

    def test_save_preparation_rejects_invalid_names_before_prompting_or_writing(self):
        self.game.editor_scenario_name = "../outside"
        ready = mock.Mock()
        with mock.patch("ui.dialogs.show_error") as error, mock.patch("ui.dialogs.ask_yes_no") as ask:
            editor_menus.prepare_editor_save(self.game, ready)
        error.assert_called_once()
        ask.assert_not_called()
        ready.assert_not_called()

    def test_save_preparation_requires_an_idle_local_editor(self):
        ready = mock.Mock()
        for key, value in (("is_editor", False), ("multiplayer_mode", True), ("realtime_multiplayer", True),
                           ("tactical_mode", True), ("is_saving", True), ("is_refreshing", True),
                           ("ai_is_thinking", True), ("viewing_ai_moves", True)):
            with self.subTest(key=key), mock.patch.object(self.game, key, value), \
                    mock.patch("ui.dialogs.ask_yes_no") as ask:
                editor_menus.prepare_editor_save(self.game, ready)
                ask.assert_not_called()
                ready.assert_not_called()

    def write_scenario(self, name=None, overwrite=False, save_path=None):
        self.game.is_saving = True
        with mock.patch.object(save_map.pygame.image, "save"), \
                mock.patch.object(queries, "scrub_default_images"), \
                mock.patch.object(save_map, "sync_persisted_dir") as sync:
            result = asyncio.run(save_map.save_map_data(self.game, name, overwrite=overwrite, save_path=save_path))
        return result, sync

    def test_disk_round_trip_uses_exact_folder_name_and_survives_renaming(self):
        queries.set_editor_metadata(self.game, "Exact Name", "Créateur", "Map description")
        path, sync = self.write_scenario()
        self.assertEqual(path, os.path.join(self.directory, "Exact Name"))
        sync.assert_called_once_with(self.directory)
        saved, _map, _history = load_map.read_save_files(path)
        self.assertEqual(saved["scenario_metadata"], {"author": "Créateur", "description": "Map description"})
        self.assertNotIn("name", saved["scenario_metadata"])
        loaded = editor()
        load_map.restore_scenario_metadata(loaded, saved, os.path.join(self.directory, "Renamed"))
        self.assertEqual(loaded.editor_scenario_name, "Renamed")
        self.assertEqual(loaded.scenario_metadata, saved["scenario_metadata"])
        self.assertFalse(self.game.is_saving)

    def test_existing_folder_requires_explicit_overwrite_in_the_writer(self):
        path = os.path.join(self.directory, "Existing")
        os.mkdir(path)
        meta_path = os.path.join(path, "meta.json")
        with open(meta_path, "w") as handle:
            handle.write("Preserve previous scenario")
        with mock.patch("builtins.print"):
            result, _sync = self.write_scenario("Existing")
        self.assertIsNone(result)
        with open(meta_path) as handle:
            self.assertEqual(handle.read(), "Preserve previous scenario")
        self.assertFalse(self.game.is_saving)
        result, _sync = self.write_scenario("Existing", overwrite=True)
        self.assertEqual(result, path)
        with open(meta_path) as handle:
            self.assertIsInstance(json.load(handle), dict)

    def test_chosen_paths_outside_the_default_roots_round_trip_for_games_and_maps(self):
        for is_editor in (True, False):
            with self.subTest(is_editor=is_editor), tempfile.TemporaryDirectory() as outside:
                self.game.is_editor = is_editor
                self.game.scenario_metadata = {"author": "Creator", "description": "Chosen destination"}
                destination = os.path.join(outside, "Chosen Name")
                path, _sync = self.write_scenario(save_path=destination)
                self.assertEqual(path, destination)
                saved, map_data, _history = load_map.read_save_files(path)
                self.assertEqual(saved["scenario_metadata"], self.game.scenario_metadata)
                self.assertEqual(saved["nation_data"], self.game.nation_data)
                self.assertIn("p", map_data)
                self.assertEqual(os.listdir(self.directory), [])

    def test_selected_destination_still_requires_overwrite_in_the_writer(self):
        destination = os.path.join(self.directory, "Chosen")
        os.mkdir(destination)
        previous = os.path.join(destination, "meta.json")
        with open(previous, "w") as handle:
            handle.write("Keep existing save")
        self.game.is_editor = False
        with mock.patch("builtins.print"):
            path, _sync = self.write_scenario(save_path=destination)
        self.assertIsNone(path)
        with open(previous) as handle:
            self.assertEqual(handle.read(), "Keep existing save")

    def test_save_copy_writes_numbered_folder_and_preserves_previous_scenario(self):
        previous = os.path.join(self.directory, "Existing")
        os.mkdir(previous)
        previous_meta = os.path.join(previous, "meta.json")
        with open(previous_meta, "w") as handle:
            handle.write("Keep the previous scenario")
        self.game.editor_scenario_name = "Existing"
        ready = mock.Mock()
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            editor_menus.prepare_editor_save(self.game, ready)
            ask.call_args.args[2](False)
        destination, overwrite = ready.call_args.args
        path, _sync = self.write_scenario(overwrite=overwrite, save_path=destination)
        self.assertEqual(path, os.path.join(self.directory, "Existing-1"))
        self.assertEqual(self.game.editor_scenario_name, "Existing-1")
        with open(previous_meta) as handle:
            self.assertEqual(handle.read(), "Keep the previous scenario")

    def test_unnamed_writer_keeps_timestamp_export_naming(self):
        with mock.patch.object(save_map, "datetime") as clock:
            clock.now.return_value.strftime.return_value = "timestamp"
            path, _sync = self.write_scenario()
        self.assertEqual(path, os.path.join(self.directory, "MapExport_timestamp"))

    def test_realtime_snapshot_metadata_is_public_and_copied_from_the_server(self):
        from data.multiplayer.realtime.session import apply_authoritative_snapshot

        client = map_double(player_country="A", nation_data={"A": {}}, map_data={},
                            refresh_all_maps=mock.Mock())
        metadata = {"author": "Author", "description": "Description"}
        apply_authoritative_snapshot(client, {"scenario_metadata": metadata, "nation_data": {"A": {}}})
        self.assertEqual(client.scenario_metadata, metadata)
        self.assertIsNot(client.scenario_metadata, metadata)
        apply_authoritative_snapshot(client, {"nation_data": {"A": {}}})
        self.assertEqual(client.scenario_metadata, {"author": "", "description": ""})

    def test_editor_metadata_screen_applies_through_shared_permission_checks(self):
        screen = object.__new__(Editor_Metadata_Screen)
        screen.map_screen = self.game
        screen.fields = {key: SimpleNamespace(text=value, active=False)
                         for key, value in (("name", "Name"), ("author", "Author"), ("description", "Description"))}
        screen.done = False
        self.assertEqual(self.game.scenario_metadata, {})
        screen.apply()
        self.assertTrue(screen.done)
        self.assertEqual(self.game.editor_scenario_name, "Name")
        self.assertEqual(self.game.scenario_metadata, {"author": "Author", "description": "Description"})
        self.game.multiplayer_mode = True
        screen.done = False
        with mock.patch("ui.dialogs.show_error") as error:
            screen.apply()
        error.assert_called_once()
        self.assertFalse(screen.done)

    def test_metadata_standalone_button_opens_the_separate_export_screen(self):
        screen = object.__new__(Editor_Metadata_Screen)
        screen.map_screen = mock.Mock()
        screen.done = False
        screen.open_standalone_export()
        self.assertTrue(screen.done)
        screen.map_screen.change_state.assert_called_once_with("STANDALONE_EXPORT")

    def test_standalone_export_screen_exports_only_a_saved_scenario_and_returns_to_the_map(self):
        screen = object.__new__(Standalone_Export_Screen)
        screen.map_screen, screen.done, screen.next_state = self.game, False, None
        self.game.editor_scenario_name = "Fixture"
        with mock.patch("ui.dialogs.show_error") as error, \
                mock.patch.object(standalone_export.screen_runner, "run_loading") as loading:
            screen.export()
        error.assert_called_once()
        loading.assert_not_called()

        scenario_dir = os.path.join(self.directory, "Fixture")
        os.makedirs(scenario_dir)
        destination = os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "Fixture")
        with mock.patch.object(standalone_export.standalone_game, "export_dir", return_value=destination), \
                mock.patch.object(standalone_export.standalone_game, "export_steps",
                                  return_value="fixture steps") as steps, \
                mock.patch.object(standalone_export.screen_runner, "run_loading") as loading:
            screen.export()
        steps.assert_called_once_with(scenario_dir, "Fixture",
                                      queries.normalized_standalone_export_settings({}))
        self.assertEqual(loading.call_args.args[0], "fixture steps")

        screen.exit_screen()
        self.assertEqual((screen.done, screen.next_state), (True, "MAP"))

    @staticmethod
    def png_bytes():
        return base64.b64decode(queries.encode_rgba_to_b64(bytes([10, 20, 30, 255]) * 6, (3, 2)))

    def test_standalone_export_settings_default_to_the_background_color_and_repair_bad_values(self):
        defaults = {"background_color": list(c.DEFAULT_BG_COLOR), "background_image": "", "image_fit": "fill",
                    "image_smoothing": True, "interesting_countries": [],
                    "music": {"album_name": "", "starting_song": "", "songs": [], "icon": "", "base_albums": []}}
        for value in (None, {}, [], {"background_color": [1, 2, 300], "background_image": 5},
                      {"image_fit": "tile", "image_smoothing": "no"},
                      {"background_color": (1, 2, 3)}, {"interesting_countries": "A"}):
            with self.subTest(value=value):
                self.assertEqual(queries.normalized_standalone_export_settings(value), defaults)
        kept = {"background_color": [1, 2, 3], "extension": {"keep": True}}
        self.assertEqual(queries.normalized_standalone_export_settings(kept),
                         {**defaults, **kept})

    def test_interesting_countries_keep_valid_entries_once_in_order(self):
        saved = [{"country": "B", "rank": "minor", "description": "Second", "extra": 1},
                 {"country": "A", "rank": "major"},
                 {"country": "B", "rank": "major", "description": "Repeated"},
                 {"country": "C", "rank": "regional"}, {"country": "", "rank": "major"}, {"rank": "minor"}, "D",
                 {"country": "E", "rank": "major", "description": 5}]
        result = queries.normalized_standalone_export_settings({"interesting_countries": saved})
        self.assertEqual(result["interesting_countries"], [
            {"country": "B", "rank": "minor", "description": "Second", "extra": 1},
            {"country": "A", "rank": "major", "description": ""},
            {"country": "E", "rank": "major", "description": ""}])

    def test_only_owned_playable_countries_can_start_a_game(self):
        map_data = {"a": {"owner": "A"}, "b": {"owner": "B"}, "c": {"owner": "C"}, "o": {"owner": "Ocean"}}
        nation_data = {"A": {"is_playable": True}, "B": {"is_playable": False}, "C": {"is_playable": True},
                       "D": {"is_playable": True}, "Ocean": {"is_playable": True}}
        self.assertEqual(queries.playable_start_countries(map_data, nation_data), ["A", "C"])

    def test_a_country_chosen_before_the_map_opens_confirms_like_a_map_selection(self):
        from screens.setup import player_setup
        game = map_double(map_data={"a": {"owner": "A"}, "b": {"owner": "B"}},
                          nation_data={"A": {"is_playable": True}, "B": {}}, show_feedback=mock.Mock())
        with mock.patch.object(player_setup, "confirm_player_country") as confirm:
            player_setup.start_as_country(game, "A")
            confirm.assert_called_once_with(game)
            self.assertEqual(game.pending_selection, "A")
            confirm.reset_mock()
            game.pending_selection = None
            player_setup.start_as_country(game, "B")
            confirm.assert_not_called()
            self.assertIsNone(game.pending_selection)

    def test_standalone_export_settings_change_only_with_valid_values_in_an_idle_editor(self):
        queries.set_standalone_export_setting(self.game, "background_color", [1, 2, 3])
        queries.set_standalone_background_image(self.game, self.png_bytes())
        settings = self.game.standalone_export_settings
        self.assertEqual(settings["background_color"], [1, 2, 3])
        self.assertEqual(base64.b64decode(settings["background_image"]), self.png_bytes())
        before = copy.deepcopy(settings)
        repeated = [{"country": "A", "rank": "major", "description": ""}] * 2
        for key, value in (("menu_background", "solid"), ("background_color", [1, 2, 300]),
                           ("interesting_countries", repeated), ("image_fit", "tile"), ("image_smoothing", 0)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                queries.set_standalone_export_setting(self.game, key, value)
        queries.set_standalone_export_setting(self.game, "interesting_countries", repeated[:1])
        self.assertEqual(settings["interesting_countries"], repeated[:1])
        settings["interesting_countries"] = []
        with self.assertRaises(ValueError):
            queries.set_standalone_background_image(self.game, b"GIF89a not a png")
        self.game.multiplayer_mode = True
        with self.assertRaises(ValueError):
            queries.set_standalone_export_setting(self.game, "background_image", "")
        self.assertEqual(settings, before)
        # Clear Image stores empty text in an idle editor.
        self.game.multiplayer_mode = False
        queries.set_standalone_export_setting(self.game, "background_image", "")
        self.assertEqual(settings["background_image"], "")

    def test_standalone_export_settings_survive_a_disk_round_trip(self):
        queries.set_editor_metadata(self.game, "Exported", "Author", "Description")
        queries.set_standalone_export_setting(self.game, "background_color", [7, 8, 9])
        queries.set_standalone_background_image(self.game, self.png_bytes())
        music = queries.normalized_standalone_export_settings({"music": {"album_name": "Fixture Soundtrack", "starting_song": "Intro.mp3", "songs": [{"name": "Intro.mp3", "data": base64.b64encode(b"fixture audio").decode("ascii")}], "icon": self.game.standalone_export_settings["background_image"]}})["music"]
        queries.set_standalone_export_setting(self.game, "music", music)
        path, _sync = self.write_scenario()
        saved, _map, _history = load_map.read_save_files(path)
        loaded = editor()
        load_map.restore_scenario_metadata(loaded, saved, path)
        self.assertEqual(loaded.standalone_export_settings,
                         queries.normalized_standalone_export_settings(self.game.standalone_export_settings))
        older = editor()
        older.standalone_export_settings["background_color"] = [7, 8, 9]
        load_map.restore_scenario_metadata(older, {}, path)
        self.assertEqual(older.standalone_export_settings, queries.normalized_standalone_export_settings({}))

    def test_export_writes_the_settings_to_game_json_and_the_game_reads_them(self):
        settings = queries.normalized_standalone_export_settings({"background_color": [4, 5, 6]})
        destination = os.path.join(self.enterContext(tempfile.TemporaryDirectory()), "Fixture")
        with mock.patch.object(standalone_export.standalone_game, "export_dir", return_value=destination), \
                mock.patch.object(standalone_export.standalone_game, "_export_copies", return_value=[]), \
                mock.patch.object(standalone_export.standalone_game, "write_preference_defaults"):
            list(standalone_export.standalone_game.export_steps(self.directory, "Fixture", settings))
        with open(os.path.join(destination, standalone_export.standalone_game.GAME_FILE), encoding="utf-8") as stream:
            game = json.load(stream)
        self.assertEqual(game["standalone_export_settings"], settings)
        with mock.patch.object(standalone_export.standalone_game, "GAME", game):
            self.assertEqual(standalone_export.standalone_game.export_settings(), settings)
        with mock.patch.object(standalone_export.standalone_game, "GAME", {"title": "Older export"}):
            self.assertEqual(standalone_export.standalone_game.export_settings(),
                             queries.normalized_standalone_export_settings({}))

    def test_custom_scenarios_are_in_the_browser_persistence_roots(self):
        self.assertIn(c.SCENARIOS_CUSTOM_DIR, platform._persisted_roots())

    def test_metadata_replaces_mail_only_for_the_editor(self):
        from screens.game import map_buttons
        from screens.editors import menus

        game = mock.Mock(is_editor=True, player_country="Editor")
        def button(_x, _y, _size, _color, text, callback, **_appearance):
            return SimpleNamespace(text=text, callback=callback)
        with mock.patch.object(map_buttons, "Button", side_effect=button), \
                mock.patch.object(map_buttons, "Slider"):
            map_buttons._build_left_bar_buttons(game)
        with mock.patch.object(menus, "open_editor_metadata") as metadata, \
                mock.patch.object(menus, "open_spectator_messages") as messages:
            game.btn_gp_msgs.callback()
            metadata.assert_called_once_with(game)
            game.is_editor = False
            game.player_country = "Spectator"
            game.btn_gp_msgs.callback()
            messages.assert_called_once_with(game)
            game.player_country = "A"
            game.btn_gp_msgs.callback()
            game.change_state.assert_called_once_with("MESSAGES")

    def test_map_save_button_waits_for_collision_choice_before_starting_work(self):
        from screens.game import map as map_module

        game = self.game
        game.editor_scenario_name = "Existing"
        game.save_map_data = MethodType(map_module.Map.save_map_data, game)
        game.draw = mock.Mock()
        os.mkdir(os.path.join(self.directory, "Existing"))
        with mock.patch("ui.dialogs.ask_yes_no") as ask, \
                mock.patch.object(map_module, "run_background") as background, \
                mock.patch.object(map_module.pygame.display, "get_surface"), \
                mock.patch.object(map_module.pygame.display, "flip"):
            game.save_map_data()
            self.assertFalse(game.is_saving)
            background.assert_not_called()
            ask.call_args.args[2](None)
            background.assert_not_called()
            ask.call_args.args[2](True)
            background.assert_called_once_with(save_map.save_map_data, game, None, overwrite=True,
                                               save_path=os.path.join(self.directory, "Existing"))
            self.assertTrue(game.is_saving)

    def test_game_save_button_waits_for_the_picker_before_starting_work(self):
        from screens.game import map as map_module

        game = self.game
        game.is_editor = False
        game.save_map_data = MethodType(map_module.Map.save_map_data, game)
        game.draw = mock.Mock()
        self.picker.side_effect = None
        destination = os.path.join(self.directory, "Chosen")
        with mock.patch.object(c, "SAVES_DIR", self.directory), \
                mock.patch.object(map_module, "run_background") as background, \
                mock.patch.object(map_module.pygame.display, "get_surface"), \
                mock.patch.object(map_module.pygame.display, "flip"):
            game.save_map_data()
            self.assertEqual(self.picker.call_args.args[2], self.directory)
            background.assert_not_called()
            self.assertFalse(game.is_saving)
            callback = self.picker.call_args.kwargs["on_result"]
            callback(None)
            background.assert_not_called()
            callback(destination)
            background.assert_called_once_with(save_map.save_map_data, game, None, overwrite=False,
                                               save_path=destination)

    def test_completed_realtime_save_chooses_a_destination_before_changing_replay_state(self):
        from screens.game import map as map_module

        game = self.game
        game.is_editor = False
        game.realtime_multiplayer = True
        game.realtime_session = SimpleNamespace(phase="GAME_OVER", completed_metadata=mock.Mock(return_value={}))
        game.realtime_server_map = mock.Mock()
        game.save_map_data = MethodType(map_module.Map.save_map_data, game)
        self.picker.side_effect = None
        game.save_map_data()
        game.realtime_session.completed_metadata.assert_not_called()
        callback = self.picker.call_args.kwargs["on_result"]
        callback(None)
        game.realtime_server_map.save_map_data.assert_not_called()
        destination = os.path.join(self.directory, "Replay")
        callback(destination)
        game.realtime_server_map.save_map_data.assert_called_once_with(None, overwrite=False, save_path=destination)

    def test_completed_realtime_client_can_save_its_own_replay_without_recursing(self):
        from screens.game import map as map_module

        game = self.game
        game.is_editor = False
        game.realtime_multiplayer = True
        game.realtime_session = SimpleNamespace(phase="GAME_OVER", completed_metadata=lambda: {"offline_view": "spectator"})
        game.realtime_server_map = None
        game.save_map_data = MethodType(map_module.Map.save_map_data, game)
        game.draw = mock.Mock()
        self.picker.side_effect = None
        destination = os.path.join(self.directory, "Replay")
        with mock.patch.object(map_module, "run_background") as background, \
                mock.patch.object(map_module.pygame.display, "get_surface"), \
                mock.patch.object(map_module.pygame.display, "flip"):
            game.save_map_data()
            self.picker.call_args.kwargs["on_result"](destination)
            background.assert_called_once_with(save_map.save_map_data, game, None, overwrite=False,
                                               save_path=destination)
            self.assertEqual(game.player_country, "Spectator")
            self.assertEqual(game.realtime_match_metadata, {"offline_view": "spectator"})


if __name__ == "__main__":
    unittest.main()
