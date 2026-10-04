"""Aircraft destination rules, random defense, and evacuation before ground attacks."""
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

from data import queries
import data.constants as c
from data.io import multiplayer_io
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError
from map_logic.ai import ai_movement
from map_logic.turn_processing import air_processor, combat_rules, movement_processor
from screens.menu_screens.map import Map
from tests.test_air_mechanics import world, tile, wing


class AirMissionPlanningTests(unittest.TestCase):
    def setUp(self):
        stats = {"attack": 800, "defense": 0, "health": 1000, "speed": 0,
                 "cost_materials": 1000, "cost_manpower": 100, "cost_fuel": 0,
                 "production_time": 2, "air_role": "aircraft", "air_range_px": 80}
        self.library = dict(queries.get_unit_library())
        self.library.update({
            "Support Wing": stats,
            "Screen Wing": dict(stats, attack=100, health=2000, air_attack_multiplier=20),
            "Incoming Wing": dict(stats, attack=600),
            "Ground Target": {key: value for key, value in dict(stats, attack=0, health=2000).items()
                              if not key.startswith("air_")},
        })
        library_patch = patch.object(queries, "get_unit_library", return_value=self.library)
        library_patch.start()
        self.addCleanup(library_patch.stop)
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.enemy = tile(self.game, 2, 30, owner="B")
        self.screen = wing(self.base, "Screen Wing")
        self.support = wing(self.base, "Support Wing")
        self.incoming = wing(self.enemy, "Incoming Wing", "B")
        self.ground = wing(self.enemy, "Ground Target", "B")

    def plan(self):
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A",
                [(self.support, self.base), (self.screen, self.base)])

    def test_capable_interceptor_defends_while_other_wing_strikes(self):
        self.plan()
        self.assertEqual(self.screen["order"]["type"], "AIR_PATROL")
        self.assertEqual(self.support["order"]["type"], "AIR_ATTACK")
        self.assertEqual(self.screen["order"], queries.canonical_air_order(
            self.game, self.screen, self.base, self.screen["order"]))

    def test_another_interceptor_strikes_after_cover_saturates(self):
        another = wing(self.base, "Screen Wing")
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A",
                [(self.screen, self.base), (another, self.base)])
        self.assertEqual(self.screen["order"]["type"], "AIR_PATROL")
        self.assertEqual(another["order"]["type"], "AIR_ATTACK")

    def test_planned_defense_intercepts_and_support_strike_resolves(self):
        self.incoming["order"] = queries.canonical_air_order(self.game, self.incoming, self.enemy,
            {"type": "AIR_ATTACK", "target_id": self.base["id"]})
        self.plan()
        ground_health = self.ground["health"]
        air_processor.process_air_orders(self.game)
        self.assertLessEqual(self.incoming["health"], 0)
        self.assertGreater(self.screen["health"], 0)
        self.assertLess(self.ground["health"], ground_health)
        self.assertIn(self.support, self.base["units"])

    def test_fort_damage_is_valued_only_for_capable_aircraft(self):
        self.enemy["units"].clear()
        self.enemy["buildings"] = ["Fort Lvl 1"]
        before = deepcopy(self.enemy)
        self.assertEqual(ai_movement._air_exchange_value(
            self.game, [self.support], [], target=self.enemy), 0)
        self.library["Support Wing"]["air_damages_forts"] = True
        self.assertGreater(ai_movement._air_exchange_value(
            self.game, [self.support], [], target=self.enemy), 0)
        self.assertEqual(self.enemy, before)

    def test_hidden_aircraft_do_not_trigger_defense_or_change_the_forecast(self):
        hidden = tile(self.game, 3, 50, owner="B")
        self.enemy["units"].remove(self.incoming)
        hidden["units"].append(self.incoming)
        with patch.object(c, "USE_FOG_OF_WAR", True), patch.object(
                queries, "get_visible_provinces", return_value=({1, 2}, set())):
            ai_movement._assign_air_orders(self.game, "A", [(self.screen, self.base)])
        self.assertEqual(self.screen["order"]["type"], "AIR_ATTACK")

    def test_enemy_orders_do_not_change_mission_choice_and_forecasts_do_not_mutate_units(self):
        before = deepcopy(self.game.map_data)
        ai_movement._air_exchange_value(self.game, [self.screen], [self.incoming], air_combat=True)
        self.assertEqual(self.game.map_data, before)
        for order in ({"type": "AIR_ATTACK", "target_id": 1}, {"type": "AIR_PATROL"}, None):
            with self.subTest(order=order):
                self.incoming["order"] = order
                self.plan()
                self.assertEqual(self.screen["order"]["type"], "AIR_PATROL")

    def test_out_of_range_or_immune_threat_does_not_trigger_defense(self):
        remote = tile(self.game, 3, 800, owner="B")
        self.enemy["units"].remove(self.incoming)
        remote["units"].append(self.incoming)
        self.plan()
        self.assertEqual(self.screen["order"]["type"], "AIR_ATTACK")
        remote["units"].remove(self.incoming)
        self.enemy["units"].append(self.incoming)
        self.library["Incoming Wing"]["air_interception_immune"] = True
        self.plan()
        self.assertEqual(self.screen["order"]["type"], "AIR_ATTACK")

    def test_tactical_patrol_counts_as_cover_without_changing_its_order(self):
        self.game.tactical_mode = True
        self.game.player_unit = self.screen
        self.screen["order"] = queries.canonical_air_order(self.game, self.screen, self.base,
            {"type": "AIR_PATROL", "priority": "RANDOM"})
        before = dict(self.screen["order"])
        self.plan()
        self.assertEqual(self.screen["order"], before)
        self.assertEqual(self.support["order"]["type"], "AIR_ATTACK")


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

    def test_active_air_missions_block_movement_atomically_until_canceled(self):
        from screens.map_related_screens.orders import Orders_Screen
        other = wing(self.base, "Test Wing")
        self.game.selected_unit_records = lambda: [(other, self.base), (self.plane, self.base)]
        screen = Orders_Screen()
        screen.map_screen = self.game
        screen.refresh_ui = Mock()
        screen._mark_draft_changed = Mock()
        missions = [{"type": "AIR_PATROL", "priority": priority}
                    for priority in queries.AIR_INTERCEPTION_PRIORITIES]
        missions += [{"type": "AIR_ATTACK", "target_id": self.enemy["id"]},
                     {"type": "AIR_REPOSITION", "target_id": self.safe["id"]}]
        for mission in missions:
            for destination in (self.safe, self.enemy):
                for append in (False, True):
                    with self.subTest(mission=mission, destination=destination["id"], append=append):
                        other["order"] = {"type": "MOVE", "path": []}
                        self.plane["order"] = queries.canonical_air_order(
                            self.game, self.plane, self.base, mission)
                        before = deepcopy([other["order"], self.plane["order"]])
                        self.game.invalidate_map_presentation_cache.reset_mock()
                        self.assertFalse(Map.issue_selected_move_orders(self.game, destination, append))
                        self.assertEqual([other["order"], self.plane["order"]], before)
                        self.game.invalidate_map_presentation_cache.assert_not_called()
                        screen.open_air_mission_select(self.base["units"].index(self.plane), self.base)
                        self.assertFalse(queries.air_unit_has_mission(self.plane))
                        self.assertTrue(Map.issue_selected_move_orders(self.game, destination, append))

    def test_one_use_weapon_ground_route_requires_cancellation_before_retargeting(self):
        self.plane["type"] = "Test Missile"
        self.base["neighbors"] = [self.safe["id"]]
        self.assertTrue(self.move(self.safe))
        before = deepcopy(self.plane["order"])
        self.assertFalse(self.move(self.enemy))
        self.assertEqual(self.plane["order"], before)
        self.plane["order"] = {"type": "MOVE", "path": []}
        self.assertTrue(self.move(self.enemy))
        self.assertEqual(self.plane["order"]["type"], "AIR_ATTACK")

    def test_preview_uses_the_current_mission_or_the_visible_hover_target(self):
        from screens.map_related_screens.orders import Orders_Screen
        screen = Orders_Screen()
        screen.map_screen = self.game
        screen._air_range_records = [(self.plane, self.base)]

        def check(destination, kind):
            screen._refresh_air_range_previews(destination)
            expected = [(self.base, queries.air_order_radius(self.plane, kind))]
            self.assertEqual(screen.air_range_previews,
                             expected if kind == "AIR_REPOSITION" else [])
            self.assertEqual(screen.air_strike_range_previews,
                             [] if kind == "AIR_REPOSITION" else expected)

        check(None, "AIR_REPOSITION")
        check(self.safe, "AIR_REPOSITION")
        check(self.enemy, "AIR_ATTACK")
        enemy = wing(self.safe, "Infantry Type 1910", "B")
        check(self.safe, "AIR_ATTACK")
        self.game.visible_provinces = {self.base["id"]}
        check(self.safe, "AIR_REPOSITION")
        check(self.enemy, "AIR_ATTACK")
        self.safe["units"].remove(enemy)
        for kind in queries.AIR_ORDER_TYPES:
            self.plane["order"] = queries.canonical_air_order(self.game, self.plane, self.base,
                {"type": kind, "target_id": self.safe["id"] if kind == "AIR_REPOSITION"
                 else self.enemy["id"]})
            for destination in (None, self.safe, self.enemy):
                with self.subTest(kind=kind, destination=destination):
                    check(destination, kind)
        self.plane["type"] = "Test Missile"
        self.plane["order"] = {"type": "MOVE", "path": []}
        check(self.safe, "AIR_ATTACK")

    def test_army_target_area_preserves_an_aircrafts_active_ground_route(self):
        self.plane["type"] = "Test Missile"
        self.base["neighbors"] = [self.safe["id"]]
        queries.ensure_unit_ids(self.game.map_data)
        army = queries.create_army("A", [self.plane["unit_id"]],
            self.game.nation_data, self.game.map_data)
        self.plane["order"] = {"type": "MOVE", "path": [self.safe["id"]]}
        before = deepcopy(self.plane["order"])
        for target in (self.base, self.safe):
            with self.subTest(target=target["id"]):
                army["defense_area"] = [target["id"]]
                self.assertEqual(queries.queue_army_defense_orders(self.game, "A", army["id"]), 0)
                self.assertEqual(self.plane["order"], before)
        self.plane["order"] = {"type": "MOVE", "path": []}
        self.assertEqual(queries.queue_army_defense_orders(self.game, "A", army["id"]), 1)

    def test_cancel_then_move_drafts_remain_valid_for_both_multiplayer_hosts(self):
        from screens.map_related_screens.orders import Orders_Screen
        screen = Orders_Screen()
        screen.map_screen = self.game
        screen.refresh_ui = Mock()
        screen._mark_draft_changed = Mock()
        for destination in (self.safe, self.enemy):
            with self.subTest(destination=destination["id"]):
                patrol = queries.canonical_air_order(self.game, self.plane, self.base,
                    {"type": "AIR_PATROL", "priority": "RANDOM"})
                self.plane["order"] = patrol
                screen.open_air_mission_select(0, self.base)
                self.assertTrue(self.move(destination))
                draft = deepcopy(self.plane["order"])
                # Hosts retain their original patrol until the final draft arrives.
                self.plane["order"] = patrol
                command = {"type": "unit_order", "province_id": self.base["id"],
                    "unit_index": 0, "unit_id": self.plane["unit_id"], "order": draft}
                self.assertEqual(MapRealtimeDriver(self.game).validate_draft("A", [command])[0]["order"], draft)
                _, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A",
                    {"aircraft_orders": [{"unit_id": self.plane["unit_id"], "order": draft}]}, {})
                self.assertEqual(drafts[0][1], draft)
                self.assertEqual(self.plane["order"], patrol)

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
