"""Transport rules use artificial unit data and authoritative network state."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from data import queries
from data import constants as c
from data.io import multiplayer_io
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError, collect_map_commands
from map_logic.ai import ai_movement
from map_logic.ai import ai_unit_eval
from map_logic.turn_processing import air_processor, combat_processor, movement_processor, unit_events
from screens.map_related_screens.orders import Orders_Screen, _AirMissionSelectScreen
from tests import test_air_mechanics as air_tests
from tests.test_air_mechanics import install_air_fixture, world, tile, wing
from tests.test_tournament_moves import synchronous_progress


class TransportTests(unittest.TestCase):
    def setUp(self):
        install_air_fixture(self)
        library = queries.get_unit_library()
        library["Monoplane Transport"] = {
            "health": 1000, "attack": 0, "defense": 0, "speed": 1,
            "cost_materials": 500, "cost_manpower": 30, "cost_fuel": 20,
            "production_time": 2, "naval_unit": False,
            "air_role": "transport", "air_range_px": 100, "air_transport_capacity": 1}
        library["Monoplane Transport I"] = deepcopy(library["Monoplane Transport"])
        library["Fixture Cargo"] = {
            "health": 2800, "attack": 50, "defense": 0, "speed": 2,
            "cost_materials": 100, "cost_manpower": 40, "cost_fuel": 10,
            "production_time": 1, "naval_unit": False}
        with open(c.UNIT_DATA_PATH, "w", encoding="utf-8") as handle:
            json.dump(library, handle)
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.destination = tile(self.game, 2, 80)
        self.base["neighbors"] = [2]
        self.destination["neighbors"] = [1]
        queries.build_air_geometry(self.game)
        self.plane = wing(self.base, "Monoplane Transport")
        self.cargo = wing(self.base, "Fixture Cargo")

    def load(self):
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [self.cargo["unit_id"]])

    def screen(self):
        screen = Orders_Screen()
        screen.map_screen = self.game
        screen.target_province = self.base
        screen.refresh_ui = Mock()
        screen._mark_draft_changed = Mock()
        self.game.show_feedback = Mock()
        return screen

    def test_only_transport_aircraft_offer_transport_and_only_move_is_a_flight(self):
        self.assertEqual(queries.available_air_missions(self.game, self.plane, self.base),
                         {"NONE", "MOVE", "TRANSPORT"})
        combat = wing(self.base, "Monoplane Bomber I")
        self.assertNotIn("TRANSPORT", queries.available_air_missions(self.game, combat, self.base))
        for kind in ("AIR_ATTACK", "AIR_PATROL", "BOMBARD"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                queries.canonical_unit_order(self.game, "A", self.base, self.plane,
                    {"type": kind, "target_id": 2, "priority": "WEAKEST"})
        self.assertEqual({o["type"] for o in ai_movement.legal_air_candidates(self.game, self.plane, self.base)},
                         {"AIR_REPOSITION"})

    def test_transport_range_comes_from_data_and_rejects_distant_destinations(self):
        radius = queries.air_unit_stats(self.plane)["air_range_px"]
        self.assertEqual(queries.air_order_radius(self.plane, "AIR_REPOSITION"), radius)
        far = tile(self.game, 3, int(self.base["center"][0] + radius + 1))
        queries.build_air_geometry(self.game)
        with self.assertRaises(ValueError):
            queries.air_move_order(self.game, self.plane, self.base, far, "MOVE")

    def test_load_release_preserve_identity_health_and_allow_immediate_movement(self):
        self.cargo["order"] = {"type": "MOVE", "path": [2]}
        self.load()
        self.assertEqual(self.base["units"], [self.plane])
        self.assertIs(self.plane["air_cargo"][0], self.cargo)
        self.assertEqual(self.cargo["order"], {"type": "MOVE", "path": []})
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.cargo["order"] = queries.canonical_unit_order(self.game, "A", self.base, self.cargo,
                                                          {"type": "MOVE", "path": [2]})
        movement_processor.process_movement(self.game)
        self.assertIn(self.cargo, self.destination["units"])

    def test_flight_keeps_cargo_hidden_and_releases_at_destination(self):
        self.load()
        self.plane["order"] = queries.air_move_order(self.game, self.plane, self.base, self.destination, "MOVE")
        self.assertEqual(queries.air_unit_mission(self.plane), "MOVE")
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "TRANSPORT")
        self.assertEqual(queries.unit_map_stack_key(self.plane), ("AIR", "TRANSPORT"))
        air_processor.process_air_orders(self.game)
        self.assertEqual(self.base["units"], [])
        self.assertEqual(self.destination["units"], [self.plane])
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "TRANSPORT")
        queries.set_air_cargo(self.game, "A", self.plane, self.destination, [])
        self.assertIn(self.cargo, self.destination["units"])
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "NONE")

    def test_capacity_is_data_driven_and_rejections_are_atomic(self):
        second = wing(self.base, "Fixture Cargo")
        ids = [self.cargo["unit_id"], second["unit_id"]]
        before = deepcopy(self.game.map_data)
        with self.assertRaises(ValueError):
            queries.set_air_cargo(self.game, "A", self.plane, self.base, ids)
        self.assertEqual(self.game.map_data, before)
        queries.air_unit_stats(self.plane)["air_transport_capacity"] = 3
        queries.set_air_cargo(self.game, "A", self.plane, self.base, ids)
        self.assertEqual(self.plane["air_cargo"], [self.cargo, second])
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [second["unit_id"]])
        self.assertIn(self.cargo, self.base["units"])
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "TRANSPORT")

    def test_transport_transfer_does_not_depend_on_carrier_command_order(self):
        receiving = wing(self.base, "Monoplane Transport")
        self.load()
        commands = queries.air_transport_commands(self.game, "A")
        commands[0]["cargo_ids"] = []
        commands[1]["cargo_ids"] = [self.cargo["unit_id"]]
        queries.apply_air_transport_commands(self.game, "A", list(reversed(commands)))
        self.assertEqual(self.plane["air_cargo"], [])
        self.assertIs(receiving["air_cargo"][0], self.cargo)
        self.assertNotIn(self.cargo, self.base["units"])

    def test_paid_order_and_invalid_base_reject_cargo_changes_without_mutation(self):
        self.cargo["order"] = {"type": "REPAIR", "refund": {"cost_materials": 10}}
        before = deepcopy(self.game.map_data)
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.game.map_data, before)
        self.cargo["order"] = {"type": "MOVE", "path": []}
        self.load()
        wing(self.base, "Infantry Type 1910", "B")
        before = deepcopy(self.game.map_data)
        with self.assertRaises(ValueError):
            queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.assertEqual(self.game.map_data, before)

    def test_ai_loads_moves_and_releases_ground_reinforcements(self):
        enemy = tile(self.game, 3, 220, owner="B")
        queries.build_air_geometry(self.game)
        records = [(self.plane, self.base), (self.cargo, self.base)]
        relocation = queries.air_move_order(self.game, self.plane, self.base, self.destination, "MOVE")
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.base,
                                          [relocation], [enemy], records)
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        self.assertEqual(self.plane["order"], relocation)
        air_processor.process_air_orders(self.game)
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.destination, [], [enemy], records)
        self.assertEqual(self.plane["air_cargo"], [])
        self.assertIn((self.cargo, self.destination), records)

    def test_ai_transport_valuation_uses_capacity_range_and_separate_role(self):
        library = queries.get_unit_library()
        ctx = ai_unit_eval.context(dict.fromkeys(ai_unit_eval.RESOURCES, 1))
        value = ai_unit_eval.evaluate(["Monoplane Transport"], library, ctx)["Monoplane Transport"]
        self.assertEqual(value.role, ai_unit_eval.ROLE_TRANSPORT)
        library["Monoplane Transport"]["air_transport_capacity"] *= 2
        larger = ai_unit_eval.evaluate(["Monoplane Transport"], library, ctx)["Monoplane Transport"]
        self.assertGreater(larger.score, value.score)
        library["Monoplane Transport"]["air_range_px"] *= 2
        farther = ai_unit_eval.evaluate(["Monoplane Transport"], library, ctx)["Monoplane Transport"]
        self.assertGreater(farther.score, larger.score)

    def test_load_rejects_planes_ships_foreign_units_remote_units_and_tactical_division(self):
        candidates = [wing(self.base, "Battleship"), wing(self.base, "Monoplane Bomber I"),
                      wing(self.base, "Fixture Cargo", "B"), wing(self.destination, "Fixture Cargo")]
        for unit in candidates:
            with self.subTest(unit=unit["type"]), self.assertRaises(ValueError):
                queries.set_air_cargo(self.game, "A", self.plane, self.base, [unit["unit_id"]])
        self.game.tactical_mode = True
        self.game.player_unit = self.cargo
        with self.assertRaises(ValueError):
            self.load()

    def test_ship_packed_in_truck_can_be_cargo(self):
        ship = wing(self.base, "Battleship")
        queries.load_transport(ship, "Truck")
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [ship["unit_id"]])
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.assertEqual(ship["original_type"], "Battleship")
        self.assertTrue(ship["type"].startswith("Truck ("))

    def test_damage_matches_both_examples_and_compounds_from_current_health(self):
        self.load()
        for plane_hp, cargo_hp, cargo_max, damage, expected in (
                (500, 1400, 2800, 250, 700), (1000, 1000, 2000, 250, 250)):
            with self.subTest(plane_hp=plane_hp):
                self.plane["health"] = plane_hp
                self.cargo.update(health=cargo_hp, max_health=cargo_max)
                combat_processor.apply_group_damage(damage, [self.plane])
                self.assertEqual(self.cargo["health"], cargo_hp - expected)
                combat_processor.apply_group_damage(plane_hp - damage, [self.plane])
                self.assertEqual(self.cargo["health"], 0)

    def test_ground_destruction_kills_cargo_and_records_its_damage(self):
        self.load()
        wing(self.base, "Infantry Type 1910", "B")
        with unit_events.record_turn(self.game):
            queries.prepare_aircraft_for_ground_combat(self.base["units"], self.game.nation_data)
        self.assertEqual(self.cargo["health"], 0)
        self.assertEqual(self.plane["health"], 0)
        self.assertTrue(any(row["unit_id"] == self.cargo["unit_id"] for row in self.game.unit_event_log["events"]))

    def test_upkeep_ids_army_membership_and_migration_include_cargo(self):
        army = queries.create_army("A", [self.cargo["unit_id"]], self.game.nation_data, self.game.map_data)
        before = queries.calculate_all_economies(self.game.map_data, self.game.nation_data)["A"]["upkeep"]
        self.load()
        self.assertEqual(queries.calculate_all_economies(self.game.map_data, self.game.nation_data)["A"]["upkeep"], before)
        self.assertEqual(queries.ensure_unit_ids(self.game.map_data), [])
        queries.normalize_armies(self.game.nation_data, self.game.map_data)
        self.assertIn(self.cargo["unit_id"], army["unit_ids"])
        self.cargo["health"] /= 2
        queries.get_unit_library()["Fixture Cargo"]["health"] *= 2
        queries.migrate_units_to_current_stats(self.game.map_data, queries.get_unit_library())
        self.assertEqual(self.cargo["health"] / self.cargo["max_health"], 0.5)

    def test_carrier_ownership_changes_include_cargo_and_division_counts(self):
        from map_logic.diplomacy import volunteers
        before = volunteers.total_divisions(self.game, "A")
        self.load()
        self.assertEqual(volunteers.total_divisions(self.game, "A"), before)
        queries.set_unit_owner(self.plane, "B")
        self.assertEqual(self.plane["owner"], "B")
        self.assertEqual(self.cargo["owner"], "B")
        queries.set_air_cargo(self.game, "B", self.plane, self.base, [])
        self.assertIn(self.cargo, self.base["units"])

    def test_ui_picker_has_load_release_callbacks_and_rechecks_permission(self):
        screen = self.screen()
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]
        popup.select(popup.items[0])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.set_air_mission(self.plane, self.base, "TRANSPORT")
        popup = runner.call_args.args[1]
        screen.read_only = True
        popup.select(popup.items[0])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        screen.read_only = False
        screen.change_air_transport(self.plane, self.base, "RELEASE", self.cargo["unit_id"])
        self.assertIn(self.cargo, self.base["units"])

    def test_cargo_picker_stays_open_and_refreshes_after_each_load(self):
        queries.air_unit_stats(self.plane)["air_transport_capacity"] = 2
        second = wing(self.base, "Fixture Cargo")
        screen = self.screen()
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]

        for unit in (self.cargo, second):
            item = next(item for item in popup.items
                        if item[1] == ("LOAD", unit["unit_id"]))
            popup.select(item)
            self.assertFalse(popup.done)
            self.assertIn(unit, self.plane["air_cargo"])

        self.assertEqual(popup.prompt, "Cargo: 2 / 2. Choose a unit to load or release.")
        self.assertFalse(any(item[1][0] == "LOAD" for item in popup.items))
        self.assertEqual({item[1][1] for item in popup.items},
                         {self.cargo["unit_id"], second["unit_id"]})

    def test_disabled_mission_choices_remain_present_and_ignore_clicks(self):
        screen = self.screen()
        chosen = Mock()
        popup = _AirMissionSelectScreen(screen, c.AIR_MISSION_CHOICES, chosen,
            enabled_missions=queries.available_air_missions(self.game, self.plane, self.base))
        for index, (mission, _label, _icon) in enumerate(popup.choices):
            if mission in ("STRIKE", *queries.AIR_INTERCEPTION_PRIORITIES):
                self.assertTrue(popup.elements[index].disabled)
                popup.select(mission, chosen)
        chosen.assert_not_called()

    def test_cargo_picker_disables_loading_when_full_and_keeps_release_available(self):
        self.load()
        extra = wing(self.base, "Fixture Cargo")
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            self.screen().open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]
        load = next(item for item in popup.items if item[1][1] == extra["unit_id"])
        release = next(item for item in popup.items if item[1][0] == "RELEASE")
        self.assertFalse(popup._item_enabled(load))
        self.assertTrue(popup._item_enabled(release))
        popup.select(load)
        self.assertEqual(self.plane["air_cargo"], [self.cargo])

    def test_realtime_validation_and_application_keep_host_stats(self):
        client = deepcopy(self.game)
        plane, cargo = client.id_to_province[1]["units"]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [cargo["unit_id"]])
        cargo["health"] = 1
        commands = [command for command in collect_map_commands(client, "A")
                    if command["type"] in ("air_transport", "unit_order")]
        driver = MapRealtimeDriver(self.game)
        canonical = driver.validate_draft("A", commands)
        self.assertEqual(self.base["units"], [self.plane, self.cargo])
        with patch("map_logic.turn_processing.turn_processor.prepare_turn", new=AsyncMock()), \
                patch("map_logic.turn_processing.turn_processor.resolve_turn_logic", new=AsyncMock()):
            driver.process_turn({"A": canonical})
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        self.assertEqual(self.cargo["health"], self.cargo["max_health"])

    def test_realtime_release_accepts_ground_order_from_same_draft(self):
        self.load()
        client = deepcopy(self.game)
        plane = client.id_to_province[1]["units"][0]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [])
        client.id_to_province[1]["units"][1]["order"] = {"type": "MOVE", "path": [2]}
        commands = [command for command in collect_map_commands(client, "A")
                    if command["type"] in ("air_transport", "unit_order")]
        canonical = MapRealtimeDriver(self.game).validate_draft("A", commands)
        ground = next(command for command in canonical if command.get("unit_id") == self.cargo["unit_id"])
        self.assertEqual(ground["order"]["path"], [2])
        self.assertNotIn(self.cargo, self.base["units"])

    def test_network_rejects_foreign_malformed_duplicate_and_stale_transport(self):
        good = dict(queries.air_transport_commands(self.game, "A")[0], cargo_ids=[self.cargo["unit_id"]])
        driver = MapRealtimeDriver(self.game)
        for commands in ([dict(good, cargo_ids=["unknown"])], [dict(good, cargo_ids="bad")],
                         [dict(good, province_id=2)], [good, good],
                         [dict(good, cargo_ids=[self.cargo["unit_id"]] * 2)]):
            with self.subTest(commands=commands), self.assertRaises(RealtimeError):
                driver.validate_draft("A", commands)
            self.assertEqual(self.base["units"], [self.plane, self.cargo])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("B", [good])

    def test_tournament_rejects_foreign_transport_and_duplicate_cargo(self):
        foreign = wing(self.base, "Fixture Cargo", "B")
        wing(self.base, "Monoplane Transport")
        client = deepcopy(self.game)
        for transform in (lambda data: data["air_transport"][0].update(cargo_ids=[foreign["unit_id"]]),
                          lambda data: [command.update(cargo_ids=[self.cargo["unit_id"]])
                                        for command in data["air_transport"]]):
            with self.subTest(transform=transform):
                before = deepcopy(self.game.map_data)
                self.assertEqual(self.import_client(client, transform)["rejected"], 1)
                self.assertEqual(self.game.map_data, before)

    def test_loaded_carrier_disband_is_rejected_in_ui_and_execution(self):
        self.load()
        screen = self.screen()
        screen.disband_unit(0, self.base)
        self.assertNotEqual(self.plane["order"].get("type"), "DISBAND")
        with self.assertRaises(ValueError):
            queries.canonical_unit_order(self.game, "A", self.base, self.plane, {"type": "DISBAND"})
        self.plane["order"] = {"type": "DISBAND", "turns_left": 1}
        movement_processor.process_disbands(self.game)
        self.assertIn(self.plane, self.base["units"])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])

    def test_snapshot_hides_foreign_cargo_even_without_fog(self):
        self.load()
        snapshot = queries.build_save_dict(self.game)
        self.game.scenario_settings["fog_of_war"] = False
        projected = queries.player_snapshot_projection(self.game, snapshot, "B")
        foreign = projected["provinces"][self.base["json_key"]]["units"][0]
        self.assertNotIn("air_cargo", foreign)
        own = queries.player_snapshot_projection(self.game, snapshot, "A")
        self.assertEqual(own["provinces"][self.base["json_key"]]["units"][0]["air_cargo"], [self.cargo])

    def import_client(self, client, transform=None):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "transport.gd5move")
            multiplayer_io.export_move_file(client, path, "key")
            if transform:
                with open(path) as handle:
                    payload = json.load(handle)
                data = multiplayer_io.decrypt_dict(payload["data"], "key")
                transform(data)
                payload["data"] = multiplayer_io.encrypt_dict(data, "key")
                with open(path, "w") as handle:
                    json.dump(payload, handle)
            with patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                return multiplayer_io.load_move_files(self.game, [path], {"A": "key"})

    def test_tournament_load_and_release_use_commands_preserve_stats_and_orders(self):
        client = deepcopy(self.game)
        plane, cargo = client.id_to_province[1]["units"]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [cargo["unit_id"]])
        cargo["health"] = 1
        self.assertEqual(self.import_client(client)["loaded"], 1)
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        client = deepcopy(self.game)
        plane = client.id_to_province[1]["units"][0]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [])
        released = client.id_to_province[1]["units"][1]
        released["order"] = {"type": "MOVE", "path": [2]}
        released["health"] = 1
        self.assertEqual(self.import_client(client)["loaded"], 1)
        self.assertEqual(self.cargo["health"], self.cargo["max_health"])
        self.assertEqual(self.cargo["order"]["path"], [2])
        self.assertEqual(len(self.base["units"]), 2)

    def test_tournament_rejects_bad_transport_and_stale_turn_atomically(self):
        client = deepcopy(self.game)
        for transform in (lambda data: data["air_transport"][0].update(cargo_ids=["missing"]),
                          lambda data: data["air_transport"][0].update(province_id=2),
                          lambda data: data.update(tournament_turn=0)):
            with self.subTest(transform=transform):
                before = deepcopy(self.game.map_data)
                self.assertEqual(self.import_client(client, transform)["rejected"], 1)
                self.assertEqual(self.game.map_data, before)


class TransportSaveSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()

    def test_cargo_survives_actual_save_load_and_legacy_empty_defaults(self):
        case = TransportTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        with tempfile.TemporaryDirectory() as directory:
            game, _, _, _ = air_tests.AirAppSmokeTests.make_runtime_save(self, directory)
            base = game.id_to_province[1]
            plane = wing(base, "Monoplane Transport I")
            cargo = wing(base, "Fixture Cargo")
            queries.set_air_cargo(game, "A", plane, base, [cargo["unit_id"]])
            cargo["health"] /= 2
            from data.map import save_map
            from screens.menu_screens.map import Map
            with patch.object(c, "SAVES_DIR", directory):
                asyncio.run(save_map.save_map_data(game, "cargo"))
            loaded = Map(load_path=os.path.join(directory, "cargo"), skip_initial_income=True)
            restored = next(u for u in loaded.id_to_province[1]["units"] if u["unit_id"] == plane["unit_id"])
            self.assertEqual(restored["air_cargo"][0]["unit_id"], cargo["unit_id"])
            self.assertEqual(restored["air_cargo"][0]["health"], cargo["health"])
            self.assertFalse(any(u["unit_id"] == cargo["unit_id"] for u in loaded.id_to_province[1]["units"]))
            loaded.selection_mode = False
            loaded.player_country = "A"
            loaded.select_map_units([restored])
            screen = Orders_Screen()
            screen.start_with_province(loaded.id_to_province[1], loaded)
            with patch.object(queries, "get_air_targets", side_effect=AssertionError("frame range calculation")), \
                    patch.object(queries, "canonical_air_order", side_effect=AssertionError("frame air rule")):
                screen.draw(self.surface)
            queries.set_air_cargo(loaded, "A", restored, loaded.id_to_province[1], [])
            restored.pop("air_cargo")
            queries.normalize_air_orders(loaded.map_data)
            self.assertEqual(queries.air_unit_mission_icon(restored), "NONE")

    def test_real_content_matches_recipes_unlocks_and_png_assets(self):
        from data.generators.generate_data import build_unit_data_text, build_research_template_text
        names = [f"Monoplane Transport {c.ROMAN_NUMERALS[level]}" for level in range(1, 4)]
        generated_units = json.loads(build_unit_data_text())
        for name in names:
            with self.subTest(unit=name):
                self.assertEqual(queries.get_unit_library()[name], generated_units[name])
        key, level = queries.get_unit_research_requirement(names[0])
        tree = queries.get_tech_tree()
        self.assertEqual(tree[key], json.loads(build_research_template_text())[key])
        research = dict(tree[key]["req"])
        self.assertTrue(queries.check_tech_requirements(research, tree[key]["req"], level))
        research[key] = level
        for name in names:
            unit_level = queries.get_unit_research_requirement(name)[1]
            self.assertTrue(queries.is_unit_unlocked(name, dict(research, **{key: unit_level})))
        for path in ("assets/classic/Monoplane Transport.png", "assets/images/Air Transport.png"):
            self.assertEqual(Path(path).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
