"""Aircraft destination rules, random defense, and evacuation before ground attacks."""
import unittest
from unittest.mock import Mock, patch

from data import queries
import data.constants as c
from data.io import multiplayer_io
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError
from map_logic.ai import ai_movement
from map_logic.turn_processing import air_processor, combat_rules, movement_processor
from screens.menu_screens.map import Map
from tests.test_air_mechanics import world, tile, wing


class AirMoveSafetyTests(unittest.TestCase):
    def setUp(self):
        library = dict(queries.get_unit_library())
        library["Test Wing"] = dict(library["Monoplane Bomber"], air_range_px=80)
        library["Test Missile"] = dict(library["V1 Flying Bomb"], air_range_px=80)
        library_patch = patch.object(queries, "get_unit_library", return_value=library)
        library_patch.start()
        self.addCleanup(library_patch.stop)
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.enemy = tile(self.game, 2, 30, owner="B")
        self.safe = tile(self.game, 3, 70)
        self.plane = wing(self.base, "Test Wing")
        self.game.can_select_map_units = lambda: True
        self.game.selected_unit_records = lambda: [(self.plane, self.base)]
        self.game.invalidate_map_presentation_cache = Mock()
        self.game.show_feedback = Mock()

    def move(self, target):
        return Map.issue_selected_move_orders(self.game, target)

    def test_enemy_move_becomes_strike_and_survivor_stays_at_base(self):
        self.assertTrue(self.move(self.enemy))
        self.assertEqual(self.plane["order"]["type"], "AIR_ATTACK")
        air_processor.process_air_orders(self.game)
        self.assertIn(self.plane, self.base["units"])
        self.assertNotIn(self.plane, self.enemy["units"])
        self.assertEqual(self.enemy["owner"], "B")

    def test_friendly_land_with_hostile_units_is_struck_without_landing(self):
        wing(self.safe, "Infantry Type 1910", "B")
        self.assertTrue(self.move(self.safe))
        self.assertEqual(self.plane["order"], queries.canonical_air_order(
            self.game, self.plane, self.base, {"type": "AIR_ATTACK", "target_id": self.safe["id"]}))
        air_processor.process_air_orders(self.game)
        self.assertIn(self.plane, self.base["units"])
        self.assertNotIn(self.plane, self.safe["units"])

    def test_friendly_empty_land_is_repositioned(self):
        self.assertTrue(self.move(self.safe))
        self.assertEqual(self.plane["order"]["type"], "AIR_REPOSITION")
        air_processor.process_air_orders(self.game)
        self.assertIn(self.plane, self.safe["units"])

    def test_fogged_units_do_not_turn_a_click_into_a_strike(self):
        wing(self.safe, "Infantry Type 1910", "B")
        self.game.visible_provinces = {self.base["id"]}
        self.assertFalse(queries.air_move_is_strike(self.game, self.plane, self.safe))
        self.assertTrue(queries.air_move_is_strike(self.game, self.plane, self.enemy))

    def test_unclaimed_destination_rejects_flight_and_missile_ground_movement(self):
        self.safe["owner"] = "Unclaimed"
        self.base["neighbors"] = [self.safe["id"]]
        for name in ("Test Wing", "Test Missile"):
            with self.subTest(unit=name):
                self.plane["type"] = name
                before = dict(self.plane["order"])
                self.assertFalse(self.move(self.safe))
                self.assertEqual(self.plane["order"], before)
                self.assertIsNone(queries.find_unit_move_path(self.plane, self.base,
                    self.safe["id"], self.game.id_to_province, self.game.nation_data))

    def test_missile_click_on_hostile_units_uses_a_strike(self):
        self.plane["type"] = "Test Missile"
        wing(self.safe, "Infantry Type 1910", "B")
        self.assertTrue(self.move(self.safe))
        self.assertEqual(self.plane["order"]["type"], "AIR_ATTACK")

    def test_mixed_selection_out_of_range_preserves_all_orders(self):
        remote = tile(self.game, 4, 800)
        distant = wing(remote, "Test Wing")
        self.game.selected_unit_records = lambda: [(self.plane, self.base), (distant, remote)]
        before = [dict(unit["order"]) for unit in (self.plane, distant)]
        self.assertFalse(self.move(self.enemy))
        self.assertEqual([unit["order"] for unit in (self.plane, distant)], before)

    def test_both_multiplayer_hosts_validate_random_patrol_and_destination_rules(self):
        def validate(order):
            command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                       "unit_id": self.plane["unit_id"], "order": order}
            real = MapRealtimeDriver(self.game).validate_draft("A", [command])[0]["order"]
            _, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A",
                {"aircraft_orders": [{"unit_id": self.plane["unit_id"], "order": order}]}, {})
            self.assertEqual(real, drafts[0][1])
            return real

        self.assertEqual(validate({"type": "AIR_PATROL", "priority": "RANDOM"})["priority"], "RANDOM")
        wing(self.safe, "Infantry Type 1910", "B")
        self.assertEqual(validate({"type": "AIR_ATTACK", "target_id": 3})["type"], "AIR_ATTACK")
        self.safe["owner"] = "Unclaimed"
        for order in ({"type": "AIR_REPOSITION", "target_id": 2},
                      {"type": "AIR_REPOSITION", "target_id": 3},
                      {"type": "AIR_PATROL", "priority": []},
                      {"type": "AIR_ATTACK", "target_id": 2, "base_id": 3}):
            with self.subTest(order=order):
                command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                           "unit_id": self.plane["unit_id"], "order": order}
                with self.assertRaises(RealtimeError):
                    MapRealtimeDriver(self.game).validate_draft("A", [command])
                with self.assertRaises(ValueError):
                    multiplayer_io._validate_aircraft_orders(self.game, "A",
                        {"aircraft_orders": [{"unit_id": self.plane["unit_id"], "order": order}]}, {})

    def test_ai_relocates_before_striking_when_ground_units_can_reach_base(self):
        attacker = wing(self.enemy, "Infantry Type 1910", "B")
        attacker["speed"] = 1
        self.enemy["neighbors"] = [self.base["id"]]
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A", [(self.plane, self.base)])
        self.assertEqual(self.plane["order"]["type"], "AIR_REPOSITION")
        self.assertEqual(self.plane["order"]["target_id"], self.safe["id"])
        air_processor.process_air_orders(self.game)
        self.assertIn(self.plane, self.safe["units"])

    def test_ai_avoids_other_threatened_bases_and_respects_hidden_units(self):
        attacker = wing(self.enemy, "Infantry Type 1910", "B")
        attacker["speed"] = 1
        self.enemy["neighbors"] = [self.base["id"], self.safe["id"]]
        inland = tile(self.game, 4, 110)
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A", [(self.plane, self.base)])
        self.assertEqual(self.plane["order"]["target_id"], inland["id"])
        with patch.object(c, "USE_FOG_OF_WAR", True), patch.object(
                queries, "get_visible_provinces", return_value=({1, 3, 4}, set())):
            self.assertEqual(ai_movement._air_base_threats(self.game, "A", {1, 3, 4}), set())
            ai_movement._assign_air_orders(self.game, "A", [(self.plane, self.base)])
        self.assertEqual(self.plane["order"]["type"], "AIR_PATROL")

    def test_tactical_division_keeps_its_order_during_evacuation(self):
        self.game.tactical_mode = True
        self.game.player_unit = self.plane
        self.plane["order"] = {"type": "AIR_PATROL", "base_id": 1, "priority": "RANDOM"}
        before = dict(self.plane["order"])
        wing(self.enemy, "Infantry Type 1910", "B")
        self.enemy["neighbors"] = [1]
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A", [(self.plane, self.base)])
        self.assertEqual(self.plane["order"], before)

    def test_threat_reach_uses_ground_speed_and_legal_edges_without_enemy_orders(self):
        attacker = wing(self.enemy, "Infantry Type 1910", "B")
        middle = tile(self.game, 4, 40)
        self.enemy["neighbors"] = [middle["id"]]
        middle["neighbors"] = [self.base["id"]]
        attacker["order"] = {"type": "MOVE", "path": []}
        with patch.object(c, "USE_FOG_OF_WAR", False):
            attacker["speed"] = 1
            self.assertNotIn(1, ai_movement._air_base_threats(self.game, "A", None))
            attacker["speed"] = 2
            self.assertIn(1, ai_movement._air_base_threats(self.game, "A", None))
            middle["terrain"] = c.WATER_TERRAINS[0]
            self.assertNotIn(1, ai_movement._air_base_threats(self.game, "A", None))

    def test_legacy_patrol_default_and_invalid_saved_landing_cancel_safely(self):
        self.plane["order"] = {"type": "AIR_PATROL"}
        queries.normalize_air_orders(self.game.map_data)
        self.assertEqual(self.plane["order"]["priority"], queries.AIR_DEFAULT_PRIORITY)
        self.plane["order"] = {"type": "AIR_REPOSITION", "base_id": 1, "target_id": 2}
        air_processor.process_air_orders(self.game)
        self.assertIn(self.plane, self.base["units"])
        self.assertEqual(self.plane["order"], {"type": "MOVE", "path": []})

    def test_resolution_rejects_old_missile_and_convoy_paths_into_unclaimed_land(self):
        self.safe["owner"] = "Unclaimed"
        self.base["neighbors"] = [self.safe["id"]]
        self.base["is_coastal"] = self.safe["is_coastal"] = True
        for name, carried in (("Test Missile", False), ("Test Wing", True)):
            with self.subTest(unit=name, carried=carried):
                self.plane["type"] = name
                if carried:
                    queries.load_transport(self.plane, "Convoy")
                self.plane["order"] = {"type": "MOVE", "path": [self.safe["id"]]}
                movement_processor.process_movement(self.game)
                self.assertIn(self.plane, self.base["units"])
                self.assertNotIn(self.plane, self.safe["units"])
                self.assertEqual(self.plane["order"]["path"], [])

    def test_random_priority_shuffles_missions_once_before_interception(self):
        self.plane["owner"] = "B"
        self.base["owner"] = "B"
        self.plane["order"] = {"type": "AIR_PATROL", "base_id": 1, "priority": "RANDOM"}
        self.enemy["owner"] = self.safe["owner"] = "B"
        launch = tile(self.game, 4, 50)
        wing(launch, "Test Wing", order={"type": "AIR_ATTACK", "target_id": 2})
        wing(launch, "Test Wing", order={"type": "AIR_ATTACK", "target_id": 3})
        seen = []
        build = combat_rules.build_battle

        def record(sides, *args, **kwargs):
            if kwargs.get("air_combat"):
                seen.append(next(u["order"]["target_id"] for u in sides[0]
                                 if u["order"]["type"] == "AIR_ATTACK"))
            return build(sides, *args, **kwargs)

        with patch.object(air_processor.random, "shuffle", side_effect=lambda items: items.reverse()) as shuffle, \
                patch.object(combat_rules, "build_battle", side_effect=record):
            air_processor.process_air_orders(self.game)
        shuffle.assert_called_once()
        self.assertEqual(seen[0], 3)


if __name__ == "__main__":
    unittest.main()
