"""Coverage for map save province state and backwards-compatible overlays."""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from unittest import mock

from data import queries
from ui.dialogs import file_exchange
from data.map import history_io, load_map, save_map
import data.constants as c
from tests.stub_map_screen import map_double, sample_map_screen


class MapSaveFormatTests(unittest.TestCase):
    def tactical_context(self):
        context = sample_map_screen()
        library = {"Fixture Infantry I": {"health": 100, "speed": 2, "attack": 10, "defense": 3,
                                          "naval_unit": False, "air_role": None, "bombard_range": 0}}
        self.enterContext(mock.patch.object(queries, "get_unit_library", return_value=library))
        player = {"unit_id": "controlled-division", "type": "Fixture Infantry I",
                  "owner": "Avaria", "health": 70, "max_health": 100,
                  "speed": 2, "attack": 10, "defense": 3, "custom_name": "Controlled division",
                  "order": {"type": "MOVE", "path": []}}
        other = dict(player, unit_id="other-division", custom_name="Other division")
        province = next(iter(context.map_data.values()))
        province.update(units=[other, player], buildings=[], unit_queue=[])
        context.tactical_mode, context.player_unit = True, player
        return context, province, player

    def test_tactical_control_survives_disk_load_as_the_same_live_division(self):
        from map_logic.actions import unit_actions
        context, _province, player = self.tactical_context()
        metadata = queries.build_save_dict(context, include_provinces=False)
        self.assertEqual(metadata["tactical_player_unit_id"], player["unit_id"])
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(queries, "get_country_data", return_value={}), \
                mock.patch.object(queries, "get_settings", return_value={}):
            with open(os.path.join(directory, "meta.json"), "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            with open(os.path.join(directory, "map_data.json"), "w", encoding="utf-8") as handle:
                json.dump(queries.build_map_data_save(context), handle)
            shutil.copyfile(os.path.join(c.BACKGROUNDS_DIR, "Province.png"), os.path.join(directory, "id_map.png"))
            loaded = load_map.load_backend_state(directory, skip_initial_income=True)
            units = next(iter(loaded.map_data.values()))["units"]
            self.assertTrue(loaded.tactical_mode)
            self.assertIs(loaded.player_unit, units[1])
            self.assertEqual(loaded.player_unit["unit_id"], player["unit_id"])
            self.assertTrue(unit_actions.unit_permission(loaded, "Avaria", units[1]))
            self.assertFalse(unit_actions.unit_permission(loaded, "Avaria", units[0]))
            self.assertEqual(queries.build_save_dict(loaded)["tactical_player_unit_id"], player["unit_id"])
            # A historical selection takes its own control reference, rather than the latest save's.
            from map_logic.system32.turn_processor import snapshot_history
            context.time_manager.get_date_string = lambda: "Fixture date"
            snapshot_history(context)
            history_io.write(directory, context.history)
            metadata["tactical_player_unit_id"] = "other-division"
            with open(os.path.join(directory, "meta.json"), "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            historical = load_map.load_backend_state(
                directory, history_turn=context.time_manager.total_turns, skip_initial_income=True)
            historical_units = next(iter(historical.map_data.values()))["units"]
            self.assertTrue(historical.tactical_mode)
            self.assertIs(historical.player_unit, historical_units[1])
            metadata.pop("tactical_player_unit_id")
            with open(os.path.join(directory, "meta.json"), "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            older = load_map.load_backend_state(directory, skip_initial_income=True)
            self.assertFalse(older.tactical_mode)
            self.assertIsNone(older.player_unit)
            self.assertEqual(older.player_country, "Avaria")

    def test_tactical_load_clears_stale_control_and_rejects_missing_dead_or_foreign_units(self):
        for problem in ("missing", "dead", "foreign"):
            with self.subTest(problem=problem):
                context, province, player = self.tactical_context()
                metadata = queries.build_save_dict(context)
                if problem == "missing":
                    province["units"].remove(player)
                elif problem == "dead":
                    player["health"] = 0
                else:
                    player["owner"] = "Other country"
                load_map._restore_tactical_player(context, metadata)
                self.assertFalse(context.tactical_mode)
                self.assertIsNone(context.player_unit)
                self.assertEqual(context.player_country, "Spectator")
                self.assertEqual(context.active_players, ["Spectator"])
        context, _province, _player = self.tactical_context()
        load_map._restore_tactical_player(context, {})
        self.assertFalse(context.tactical_mode)
        self.assertIsNone(context.player_unit)
        self.assertEqual(context.player_country, "Avaria")

    def test_tactical_metadata_cannot_enable_control_in_editors_scenarios_or_multiplayer(self):
        for mode in ("is_editor", "selection_mode", "multiplayer_mode", "realtime_multiplayer"):
            with self.subTest(mode=mode):
                context, _province, player = self.tactical_context()
                metadata = queries.build_save_dict(context)
                setattr(context, mode, True)
                self.assertIsNone(queries.build_save_dict(context)["tactical_player_unit_id"])
                load_map._restore_tactical_player(context, metadata)
                self.assertFalse(context.tactical_mode)
                self.assertIsNone(context.player_unit)
                self.assertEqual(context.player_country, "Avaria")

    def test_tactical_load_rejects_air_sea_artillery_and_unknown_types_without_removing_units(self):
        for stats in ({"naval_unit": True}, {"air_role": "fighter"}, {"bombard_range": 2}, None):
            with self.subTest(stats=stats):
                context, province, player = self.tactical_context()
                metadata = queries.build_save_dict(context)
                player["type"] = "Fixture Ineligible I"
                library = queries.get_unit_library(context)
                if stats is not None:
                    library[player["type"]] = stats
                load_map._restore_tactical_player(context, metadata)
                self.assertFalse(context.tactical_mode)
                self.assertIsNone(context.player_unit)
                self.assertEqual(context.player_country, "Spectator")
                self.assertTrue(any(unit is player for unit in province["units"]))

    def test_tactical_control_does_not_follow_a_leftover_player_reference_after_independence(self):
        context, _province, _player = self.tactical_context()
        context.tactical_mode = False
        self.assertIsNone(queries.build_save_dict(context)["tactical_player_unit_id"])

    def test_tactical_load_keeps_control_of_an_eligible_division_in_a_convoy(self):
        context, _province, player = self.tactical_context()
        metadata = queries.build_save_dict(context)
        player["original_type"] = player["type"]
        player["type"] = f"Convoy ({player['type']})"
        load_map._restore_tactical_player(context, metadata)
        self.assertTrue(context.tactical_mode)
        self.assertIs(context.player_unit, player)

    def test_realtime_player_projection_omits_tactical_control(self):
        context, _province, player = self.tactical_context()
        context.scenario_settings["fog_of_war"] = False
        snapshot = queries.build_save_dict(context)
        projected = queries.player_snapshot_projection(context, snapshot, "Avaria")
        self.assertNotIn("tactical_player_unit_id", projected)
        self.assertEqual(snapshot["tactical_player_unit_id"], player["unit_id"])

    def test_selected_history_uses_its_tactical_division_reference(self):
        from map_logic.system32.turn_processor import snapshot_history
        context, _province, player = self.tactical_context()
        context.time_manager.get_date_string = lambda: "Fixture date"
        snapshot_history(context)
        turn = str(context.time_manager.total_turns)
        self.assertEqual(context.history[turn]["tactical_player_unit_id"], player["unit_id"])
        metadata = queries.build_save_dict(context)
        metadata["tactical_player_unit_id"] = None
        load_map._apply_history_snapshot(metadata, context.history, turn)
        load_map._restore_tactical_player(context, metadata)
        self.assertIs(context.player_unit, player)
        self.assertTrue(context.tactical_mode)
        # Older snapshots do not inherit a later turn's tactical selection.
        context.history[turn].pop("tactical_player_unit_id")
        load_map._apply_history_snapshot(metadata, context.history, turn)
        load_map._restore_tactical_player(context, metadata)
        self.assertIsNone(context.player_unit)
        self.assertFalse(context.tactical_mode)
        context.tactical_mode = False
        snapshot_history(context)
        load_map._apply_history_snapshot(metadata, context.history, turn)
        load_map._restore_tactical_player(context, metadata)
        self.assertIsNone(context.player_unit)
        self.assertFalse(context.tactical_mode)

    def test_conversation_colors_normalize_only_at_the_save_boundary(self):
        raw = {"A": [1, 2, 3], "B": [True, 2, 3], "C": [-1, 2, 3],
               "D": [256, 2, 3], "E": [1, 2], "F": "123", "": [1, 2, 3]}
        self.assertEqual(queries.normalized_conversation_colors(raw), {"A": [1, 2, 3]})
        copied = queries.normalized_conversation_colors(raw)
        copied["A"][0] = 20
        self.assertEqual(raw["A"], [1, 2, 3])
        for invalid in (None, [], "invalid"):
            with self.subTest(value=invalid):
                self.assertEqual(queries.normalized_conversation_colors(invalid), {})

    def test_older_saves_new_scenarios_and_procedural_loads_clear_previous_colors(self):
        context = sample_map_screen()
        metadata = queries.build_save_dict(context)
        for saved, selection, editor in ((metadata, False, False), (None, False, False),
                                          (dict(metadata, conversation_colors={"A": [1, 2, 3]}), True, False),
                                          (dict(metadata, conversation_colors={"A": [1, 2, 3]}), False, True)):
            with self.subTest(saved=saved is not None, selection=selection, editor=editor):
                context.conversation_colors = {"Previous game": [4, 5, 6]}
                context.selection_mode = selection
                context.is_editor = editor
                load_map._restore_session_properties(context, saved)
                self.assertEqual(context.conversation_colors, {})
        context.conversation_colors = {"Previous game": [4, 5, 6]}
        load_map._clear_loaded_world(context)
        self.assertEqual(context.conversation_colors, {})

    def test_local_conversation_colors_are_not_in_multiplayer_snapshots(self):
        context = sample_map_screen()
        context.conversation_colors = {"Avaria": [1, 2, 3]}
        self.assertNotIn("conversation_colors", queries.build_save_dict(context))
        self.assertEqual(queries.build_save_dict(context, include_local_preferences=True)["conversation_colors"],
                         {"Avaria": [1, 2, 3]})

    def test_conversation_colors_survive_backend_disk_load_and_ignore_old_global_preferences(self):
        context = map_double(conversation_colors={"A": [12, 34, 56]})
        metadata = queries.build_save_dict(context, include_provinces=False, include_local_preferences=True)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(queries, "get_country_data", return_value={}), \
                mock.patch.object(queries, "get_settings", return_value={"conversation_colors": {"B": [1, 2, 3]}}):
            meta_path = os.path.join(directory, "meta.json")
            with open(meta_path, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            with open(os.path.join(directory, "map_data.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            # The backend reads dimensions from an existing PNG without drawing it.
            shutil.copyfile(os.path.join(c.BACKGROUNDS_DIR, "Province.png"), os.path.join(directory, "id_map.png"))
            loaded = load_map.load_backend_state(directory, skip_initial_income=True)
            self.assertEqual(loaded.session.conversation_colors, {"A": [12, 34, 56]})
            metadata.pop("conversation_colors")
            with open(meta_path, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            older = load_map.load_backend_state(directory, skip_initial_income=True)
            self.assertEqual(older.session.conversation_colors, {})

    def test_a_new_game_starts_with_no_world_events(self):
        """A scenario's leftover events reached every LLM prompt as current news.
        Loading a save in progress keeps its events."""
        log = ["WAR DECLARED: Atlantis has declared war on Lemuria!"]
        events = {"is_playable": False, "log": list(log), "news_flash": list(log)}
        context = map_double(nation_data={"GLOBAL_EVENTS": events})
        metadata = queries.build_save_dict(context, include_provinces=False)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(queries, "get_country_data", return_value={}), \
                mock.patch.object(queries, "get_settings", return_value={}):
            with open(os.path.join(directory, "meta.json"), "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            with open(os.path.join(directory, "map_data.json"), "w", encoding="utf-8") as handle:
                json.dump({}, handle)
            shutil.copyfile(os.path.join(c.BACKGROUNDS_DIR, "Province.png"), os.path.join(directory, "id_map.png"))
            for is_scenario, expected in ((True, []), (False, log)):
                with self.subTest(is_scenario=is_scenario):
                    loaded = load_map.load_backend_state(
                        directory, is_scenario=is_scenario, skip_initial_income=True,
                        scenario_settings=queries.get_default_scenario_settings())
                    record = loaded.nation_data["GLOBAL_EVENTS"]
                    self.assertEqual((record["log"], record["news_flash"]), (expected, expected))
                    self.assertFalse(record["is_playable"])

    def test_geometry_omits_only_fields_with_a_separate_state_record(self):
        raw = {"p": {"terrain": "fixture", "owner": "old", "unknown": {"keep": [1]}},
               "extra": {"owner": "preserved", "units": [{"fixture": True}]}}
        saved = {"p": {"owner": "new", "units": []}}
        geometry = queries.build_map_geometry_save(raw, saved)
        self.assertEqual(geometry, {
            "p": {"terrain": "fixture", "unknown": {"keep": [1]}}, "extra": raw["extra"]})
        self.assertEqual(queries.map_data_with_saved_provinces(geometry, saved),
                         queries.map_data_with_saved_provinces(raw, saved))
        geometry["p"]["unknown"]["keep"].append(2)
        self.assertEqual(raw["p"]["unknown"]["keep"], [1])

    def test_unassigned_is_rebuilt_from_saved_units_without_a_new_saved_field(self):
        from ui.panels import army_panel
        map_screen = sample_map_screen()
        army_panel.prepare(map_screen)
        before = map_screen.unassigned_army_card
        self.assertTrue(before["unit_ids"])
        snapshot = json.loads(history_io.dump_text(queries.build_save_dict(map_screen)))
        self.assertNotIn("unassigned_army_card", snapshot)
        self.assertEqual(snapshot["nation_data"]["Avaria"].get("armies", []), [])
        loaded = map_double(player_country=snapshot["player_country"],
                                 nation_data=snapshot["nation_data"],
                                 map_data=snapshot["provinces"])
        queries.normalize_armies(loaded.nation_data, loaded.map_data)
        army_panel.prepare(loaded)
        self.assertEqual(loaded.unassigned_army_card, before)

    def test_map_data_holds_current_province_state_and_meta_can_omit_duplicate(self):
        map_screen = sample_map_screen()

        network_snapshot = queries.build_save_dict(map_screen)
        disk_meta = queries.build_save_dict(map_screen, include_provinces=False)
        map_data = queries.build_map_data_save(map_screen)

        key = "(7, 0, 0)"
        self.assertEqual(map_data[key]["owner"], network_snapshot["provinces"][key]["owner"])
        self.assertEqual(map_data[key]["units"], network_snapshot["provinces"][key]["units"])
        self.assertEqual(map_data[key]["resources"], network_snapshot["provinces"][key]["resources"])
        self.assertEqual(map_data[key]["terrain"], "plains")
        self.assertNotIn("provinces", disk_meta)
        self.assertEqual(disk_meta["nation_data"], map_screen.nation_data)
        self.assertEqual(disk_meta["date"], {
            "day": 15, "month": 5, "year": 1939, "total_turns": 12,
        })
        self.assertEqual(disk_meta["scenario_settings"]["days_per_turn"], 30)

        # These are the actual text forms written by map save paths.
        self.assertEqual(json.loads(history_io.dump_text(disk_meta, indent=c.SAVE_INDENT)), disk_meta)
        self.assertEqual(json.loads(history_io.dump_text(map_data, indent=c.SAVE_INDENT)), map_data)
        self.assertEqual(map_screen.raw_json_data, {key: {"id": 7, "terrain": "plains"}})

    def test_full_save_dictionary_still_carries_multiplayer_province_snapshot(self):
        snapshot = queries.build_save_dict(sample_map_screen())
        self.assertEqual(snapshot["provinces"]["(7, 0, 0)"], {
            "owner": "Avaria",
            "cores": ["Avaria"],
            "is_coastal": True,
            "units": [{"type": "Infantry", "owner": "Avaria"}],
            "building_queue": [],
            "unit_queue": [{"type": "Infantry", "turns_left": 2}],
            "orders": [],
            "resources": {"Oil": 20},
            "buildings": ["Factory"],
        })

    def test_disk_save_writes_current_state_readably_without_meta_overlay(self):
        map_screen = sample_map_screen()
        map_screen.conversation_colors = {"Avaria": [12, 34, 56]}
        map_screen.is_editor = False
        map_screen.history = {"1": {"nation_data": {}, "provinces": {}}}
        map_screen.political_map = object()
        map_screen.terrain_map = object()
        map_screen.id_map = object()
        map_screen.cores_map = object()
        map_screen.show_feedback = lambda _message: None

        with tempfile.TemporaryDirectory() as temporary:
            save_dir = os.path.join(temporary, "compact-save")
            os.makedirs(save_dir)
            for filename in ("political.png", "cores.png"):
                with open(os.path.join(save_dir, filename), "wb") as handle:
                    handle.write(b"stale cached overlay")
            with mock.patch.object(c, "SAVES_DIR", temporary), \
                 mock.patch.object(save_map.queries, "scrub_default_images"), \
                 mock.patch.object(save_map.pygame.image, "save") as image_save, \
                 mock.patch.object(save_map, "sync_persisted_dir"):
                asyncio.run(save_map.save_map_data(map_screen, "compact-save"))

            with open(os.path.join(save_dir, "meta.json"), encoding="utf-8") as handle:
                meta_text = handle.read()
            with open(os.path.join(save_dir, "map_data.json"), encoding="utf-8") as handle:
                map_data_text = handle.read()
            meta = json.loads(meta_text)
            map_data = json.loads(map_data_text)
            saved_history = history_io.read(save_dir)
            has_political_cache = os.path.exists(os.path.join(save_dir, "political.png"))
            has_cores_cache = os.path.exists(os.path.join(save_dir, "cores.png"))

        self.assertNotIn("provinces", meta)
        self.assertEqual(meta["conversation_colors"], {"Avaria": [12, 34, 56]})
        loaded = sample_map_screen()
        load_map._restore_session_properties(loaded, meta)
        self.assertEqual(loaded.conversation_colors, map_screen.conversation_colors)
        loaded.conversation_colors["Avaria"][0] = 99
        self.assertEqual(map_screen.conversation_colors, {"Avaria": [12, 34, 56]})
        self.assertEqual(meta["nation_data"], map_screen.nation_data)
        self.assertEqual(meta["date"], {
            "day": 15, "month": 5, "year": 1939, "total_turns": 12,
        })
        self.assertEqual(map_data["(7, 0, 0)"], map_screen.map_data[(7, 0, 0)])
        self.assertEqual(meta_text, json.dumps(meta, indent=c.SAVE_INDENT))
        self.assertEqual(map_data_text, json.dumps(map_data, indent=c.SAVE_INDENT))
        self.assertGreater(meta_text.count("\n"), 1)
        self.assertGreater(map_data_text.count("\n"), 1)
        self.assertEqual(saved_history, map_screen.history)
        self.assertFalse(has_political_cache)
        self.assertFalse(has_cores_cache)
        self.assertCountEqual(
            [os.path.basename(call.args[1]) for call in image_save.call_args_list],
            ["terrain.png", "id_map.png"],
        )
        self.assertFalse(map_screen.is_saving)

    def test_built_in_maps_omit_regenerable_layers_and_empty_histories(self):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for map_root in (os.path.join(project_root, "base_maps"),
                         os.path.join(project_root, "scenarios")):
            for current, dirnames, filenames in os.walk(map_root):
                # Custom editor maps are gitignored user data, outside this cleanup.
                dirnames[:] = [name for name in dirnames if name != "map_editor"]
                self.assertFalse(
                    {"political.png", "cores.png", "history.json", "history.json.gz"}
                    & set(filenames),
                    f"unexpected generated map artifact in {current}",
                )

    def test_zip_export_pretty_prints_existing_compact_json_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            source_dir = os.path.join(temporary, "source")
            os.makedirs(source_dir)
            with open(os.path.join(source_dir, "meta.json"), "w", encoding="utf-8") as handle:
                handle.write('{"nation_data":{"Avaria":{"materials":200}},"date":{"year":1939}}')
            with open(os.path.join(source_dir, "terrain.png"), "wb") as handle:
                handle.write(b"not json")

            archive_path = os.path.join(temporary, "export.zip")

            def export_without_ui(_name, produce, _parent=None, **_kwargs):
                produce(archive_path)
                return archive_path

            with mock.patch.object(file_exchange, "export_file", export_without_ui):
                file_exchange.export_dir_as_zip(source_dir, "export.zip")

            with zipfile.ZipFile(archive_path) as archive:
                payload = archive.read("meta.json").decode("utf-8")
                binary_payload = archive.read("terrain.png")

        self.assertEqual(json.loads(payload), {
            "nation_data": {"Avaria": {"materials": 200}},
            "date": {"year": 1939},
        })
        self.assertGreater(payload.count("\n"), 1)
        self.assertEqual(binary_payload, b"not json")

    def test_legacy_meta_and_history_province_overlays_still_apply(self):
        map_data = {
            "(7, 0, 0)": {"id": 7, "terrain": "plains", "owner": "Avaria", "units": []},
        }
        legacy_overlay = {
            "(7, 0, 0)": {"owner": "Borland", "units": [{"type": "Infantry"}]},
            "(99, 0, 0)": {"owner": "Ignored missing province"},
        }

        result = queries.map_data_with_saved_provinces(map_data, legacy_overlay)

        self.assertEqual(result["(7, 0, 0)"], {
            "id": 7, "terrain": "plains", "owner": "Borland",
            "units": [{"type": "Infantry"}],
        })
        self.assertEqual(map_data["(7, 0, 0)"], {
            "id": 7, "terrain": "plains", "owner": "Avaria", "units": [],
        })

    def test_selected_history_turn_supplies_provinces_without_current_meta_overlay(self):
        save_meta = {
            "nation_data": {"Current": {"materials": 5}},
            "date": {"day": 1, "month": 0, "year": 1940, "total_turns": 8},
        }
        history = {
            "3": {
                "nation_data": {"Historical": {"materials": 12}},
                "provinces": {"(7, 0, 0)": {"owner": "Historical"}},
                "day": 15,
                "month": 4,
                "year": 1939,
            },
            "9": {"nation_data": {}, "provinces": {}},
        }

        self.assertTrue(load_map._apply_history_snapshot(save_meta, history, 3))
        raw_map = {"(7, 0, 0)": {"id": 7, "terrain": "plains", "owner": "Current"}}
        queries.overlay_saved_province_data(raw_map, save_meta["provinces"])

        self.assertEqual(raw_map["(7, 0, 0)"], {
            "id": 7, "terrain": "plains", "owner": "Historical",
        })
        self.assertEqual(save_meta["nation_data"], {"Historical": {"materials": 12}})
        self.assertEqual(save_meta["date"], {
            "day": 15, "month": 4, "year": 1939, "total_turns": 3,
        })
        self.assertEqual(set(history), {"3"})


if __name__ == "__main__":
    unittest.main()
