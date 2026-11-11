"""Two ways units used to slip past a hostile unit without ever fighting it.

process_movement resolves a turn's movement one step at a time, and detaches
active movers from province["units"] while each simultaneous step is taken.
Finished movers remain visible to later arrivals. Its turn-start counterpart,
combat_rules.find_meeting_pairs, which fights a direct tile swap before any
movement starts, only looks at a unit's very first step,
and the step loop used to re-strip *every* mover before each later step, even
one that had already finished moving. Together those left two real gaps:

  * a unit that becomes adjacent to an enemy only partway through the turn
    (e.g. a 2-speed unit catching up to one that already took its step) could
    swap tiles with it for free, since neither ever saw the other as a
    "defender" -- test_a_multi_speed_unit_fights_a_mid_turn_swap.
  * a unit that finished its move early (used up a 1-speed order, or hit a
    defender) went invisible to everyone else's later steps too, so a faster
    enemy could walk straight through the tile it was resting in --
    test_a_finished_mover_still_blocks_a_later_arrival.

Both are exercised directly against movement_processor.process_movement with
a hand-built map, isolated from the rest of turn resolution.
"""

import unittest
from unittest.mock import patch


from tests.combat_fixtures import StubBattleMap

from map_logic.system32 import combat_processor, movement_processor
from map_logic import custom_battle


def make_unit(owner, path, speed=1, health=1000, attack=100, defense=50):
    return {
        "type": "Infantry",
        "owner": owner,
        "order": {"type": "MOVE", "path": list(path)},
        "speed": speed,
        "health": health,
        "max_health": health,
        "attack": attack,
        "defense": defense,
    }


class MidTurnSwapTests(unittest.TestCase):
    def test_a_turn_start_head_on_swap_bounces_both_sides(self):
        """Hostile armies trade one volley but remain on their own tiles."""
        screen = StubBattleMap(terrain="Plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        unit_a = make_unit("A", ["p2"])
        unit_b = make_unit("B", ["p1"])
        p1 = screen.add_province("p1", "A", units=[unit_a])
        p2 = screen.add_province("p2", "B", units=[unit_b])

        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)

        self.assertIn(unit_a, p1["units"])
        self.assertIn(unit_b, p2["units"])
        self.assertNotIn(unit_a, p2["units"])
        self.assertNotIn(unit_b, p1["units"])

    def test_a_multi_speed_unit_fights_a_mid_turn_swap(self):
        screen = StubBattleMap(terrain="Plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        unit_a = make_unit("A", ["p2", "p3"], speed=2)
        unit_b = make_unit("B", ["p3", "p2"], speed=2)

        screen.add_province("p1", "A", units=[unit_a])
        screen.add_province("p2", "A")
        screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[unit_b])

        # Not adjacent at turn start (p1 borders p2, not p4), so the
        # turn-start meeting-pairs pass -- which this test intentionally
        # never calls -- would not have caught them anyway. They only meet
        # after each has taken one step, on the p2<->p3 edge, at step 2.
        movement_processor.process_movement(screen)

        self.assertLess(unit_a["health"], 1000, "unit A should have taken damage in the swap")
        self.assertLess(unit_b["health"], 1000, "unit B should have taken damage in the swap")

        # Neither should have completed the crossing into the other's tile.
        self.assertEqual(unit_a["_current_province_id"], "p2")
        self.assertEqual(unit_b["_current_province_id"], "p3")
        self.assertNotIn(unit_a, screen.id_to_province["p3"]["units"])
        self.assertNotIn(unit_b, screen.id_to_province["p2"]["units"])


class TacticalSwapTests(unittest.TestCase):
    def setUp(self):
        self.library = {"Fixture Infantry I": {
            "health": 1000, "attack": 100, "defense": 0, "speed": 3,
            "naval_unit": False, "bombard_range": 0,
        }}
        self.enterContext(patch("data.queries.get_unit_library", return_value=self.library))

    def screen(self):
        screen = StubBattleMap(terrain="plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        screen.tactical_mode = True
        return screen

    def mover(self, owner, path, **stats):
        unit = make_unit(owner, path, **stats)
        unit["type"] = "Fixture Infantry I"
        return unit

    def test_tactical_unit_wins_turn_start_crossing_in_either_direction_without_damage(self):
        for player_country in ("A", "B"):
            with self.subTest(player_country=player_country):
                screen = self.screen()
                first = self.mover("A", ["p2"])
                second = self.mover("B", ["p1"])
                p1 = screen.add_province("p1", "A", units=[first])
                p2 = screen.add_province("p2", "B", units=[second])
                player, opponent = (first, second) if player_country == "A" else (second, first)
                player.update(health=1, max_health=1, attack=0, defense=0)
                opponent.update(attack=100000, defense=0)
                screen.player_unit = player
                origin, destination = (p1, p2) if player_country == "A" else (p2, p1)

                combat_processor.process_pinning(screen)
                combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                combat_processor.process_combat(screen)

                self.assertEqual((player["health"], opponent["health"]), (1, 1000))
                self.assertTrue(any(unit is player for unit in destination["units"]))
                self.assertTrue(any(unit is opponent for unit in destination["units"]))
                self.assertEqual(origin["units"], [])
                self.assertEqual(destination["owner"], opponent["owner"])
                self.assertIsNotNone(custom_battle.tactical_encounter(screen, destination))
                self.assertNotIn("_combat_locked", opponent)

    def test_tactical_mid_turn_crossing_stops_fast_unit_on_the_encounter_tile(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3", "p5"], speed=3, health=1, attack=0, defense=0)
        opponent = self.mover("B", ["p3", "p2"], speed=2, attack=100000, defense=0)
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player])
        screen.add_province("p2", "A")
        destination = screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[opponent])
        screen.add_province("p5", "B")

        combat_processor.process_pinning(screen)
        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)
        self.assertEqual(player["order"]["path"], ["p5"])
        self.assertEqual(opponent["order"]["path"], ["p2"])
        combat_processor.process_combat(screen)

        self.assertEqual({id(unit) for unit in destination["units"]}, {id(player), id(opponent)})
        self.assertEqual((player["health"], opponent["health"]), (1, 1000))
        self.assertEqual(destination["owner"], "B")
        self.assertEqual(player["order"]["path"], [])
        self.assertEqual(opponent["order"]["path"], [])
        self.assertIsNotNone(custom_battle.tactical_encounter(screen, destination))
        self.assertTrue(all("_skip_remaining_steps" not in unit for unit in (player, opponent)))

    def test_priority_does_not_apply_outside_tactical_play_or_in_either_multiplayer_mode(self):
        for mode in ("ordinary", "tournament", "realtime", "different_unit"):
            with self.subTest(mode=mode):
                screen = self.screen()
                first = self.mover("A", ["p2"])
                second = self.mover("B", ["p1"])
                p1 = screen.add_province("p1", "A", units=[first])
                p2 = screen.add_province("p2", "B", units=[second])
                screen.player_unit = first
                if mode == "ordinary":
                    screen.tactical_mode = False
                elif mode == "tournament":
                    screen.multiplayer_mode = True
                elif mode == "realtime":
                    screen.realtime_multiplayer = True
                else:
                    screen.player_unit = self.mover("A", [])
                    screen.add_province("p3", "A", units=[screen.player_unit])
                combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                self.assertEqual(p1["units"], [first])
                self.assertEqual(p2["units"], [second])
                self.assertLess(first["health"], first["max_health"])
                self.assertLess(second["health"], second["max_health"])

    def test_neutral_crossing_bystander_is_not_held_for_the_tactical_fight(self):
        screen = self.screen()
        screen.add_nation("C")
        screen.nation_data["A"]["military_access"] = ["C"]
        player = self.mover("A", ["p2"])
        opponent = self.mover("B", ["p1"])
        bystander = self.mover("C", ["p1"])
        screen.player_unit = player
        origin = screen.add_province("p1", "A", units=[player])
        destination = screen.add_province("p2", "B", units=[opponent, bystander])
        combat_processor.process_pinning(screen)
        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)
        combat_processor.process_combat(screen)
        self.assertEqual(origin["units"], [bystander])
        self.assertEqual({id(unit) for unit in destination["units"]}, {id(player), id(opponent)})
        self.assertEqual(bystander["health"], bystander["max_health"])

    def test_tactical_crossing_priority_requires_a_living_mobile_unit_and_legal_destination(self):
        for problem in ("dead", "immobile", "water", "naval_opponent"):
            with self.subTest(problem=problem):
                screen = self.screen()
                player = self.mover("A", ["p2"])
                opponent = self.mover("B", ["p1"])
                origin = screen.add_province("p1", "A", units=[player])
                destination = screen.add_province("p2", "B", units=[opponent])
                screen.player_unit = player
                if problem == "dead":
                    player["health"] = 0
                elif problem == "immobile":
                    player["speed"] = 0
                elif problem == "water":
                    destination["terrain"] = "ocean"
                else:
                    self.library["Fixture Ship I"] = {"naval_unit": True, "bombard_range": 0}
                    opponent["type"] = "Fixture Ship I"
                self.assertIsNone(custom_battle.tactical_meeting_side(
                    screen, origin, destination, [player], [opponent]))

    def test_unrelated_war_on_the_same_crossing_still_resolves_normally(self):
        for mid_turn in (False, True):
            with self.subTest(mid_turn=mid_turn):
                screen = self.screen()
                screen.add_nation("C", at_war_with=["D"])
                screen.add_nation("D", at_war_with=["C"])
                player = self.mover("A", ["p2"], attack=0, defense=0)
                opponent = self.mover("B", ["p1"], attack=0, defense=0)
                third = self.mover("C", ["p2"], attack=100, defense=0)
                fourth = self.mover("D", ["p1"], attack=100, defense=0)
                screen.player_unit = player
                origin = screen.add_province("p1", "A", units=[player, third])
                destination = screen.add_province("p2", "B", units=[opponent, fourth])
                if not mid_turn:
                    combat_processor.process_pinning(screen)
                    combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                combat_processor.process_combat(screen)
                self.assertEqual({id(unit) for unit in origin["units"]}, {id(third)})
                self.assertEqual({id(unit) for unit in destination["units"]},
                                 {id(player), id(opponent), id(fourth)})
                self.assertEqual((player["health"], opponent["health"]), (1000, 1000))
                self.assertEqual((third["health"], fourth["health"]), (900, 900))

    def resolve_without_automatic_combat(self, screen):
        """An eligible tactical engagement must reach preview without even a damage probe."""
        with patch.object(combat_processor.combat_rules, "build_battle",
                          side_effect=AssertionError("automatic tactical combat")):
            combat_processor.process_pinning(screen)
            combat_processor.process_meeting_engagements(screen)
            movement_processor.process_movement(screen)
            combat_processor.process_combat(screen)
            combat_processor.check_for_post_combat_captures(screen)

    def test_doomed_attacks_in_either_direction_wait_for_the_tactical_battle(self):
        for player_attacks in (False, True):
            with self.subTest(player_attacks=player_attacks):
                screen = self.screen()
                player = self.mover("A", ["p2"] if player_attacks else [],
                                    health=1 if player_attacks else 1000,
                                    attack=0 if player_attacks else 100000, defense=0)
                opponent = self.mover("B", [] if player_attacks else ["p1"],
                                      health=1000 if player_attacks else 1,
                                      attack=100000 if player_attacks else 0, defense=0)
                screen.player_unit = player
                p1 = screen.add_province("p1", "A", units=[player])
                p2 = screen.add_province("p2", "B", units=[opponent])
                before = player["health"], opponent["health"]

                self.resolve_without_automatic_combat(screen)

                destination = p2 if player_attacks else p1
                self.assertEqual((player["health"], opponent["health"]), before)
                self.assertEqual({id(unit) for unit in destination["units"]}, {id(player), id(opponent)})
                self.assertIsNotNone(custom_battle.tactical_encounter(screen, destination))

    def test_another_incoming_attack_overrides_tactical_crossing_priority(self):
        for reverse_order in (False, True):
            with self.subTest(reverse_order=reverse_order):
                screen = self.screen()
                player = self.mover("A", ["p2"], attack=100000, defense=0)
                head_on = self.mover("B", ["p1"], health=1, attack=0, defense=0)
                flanker = self.mover("B", ["p1"], health=1, attack=0, defense=0)
                screen.player_unit = player
                origin = screen.add_province("p1", "A", units=[player])
                destination = screen.add_province("p2", "B", units=[head_on])
                screen.add_province("p3", "B", units=[flanker])
                if reverse_order:
                    screen.map_data = dict(reversed(list(screen.map_data.items())))

                self.assertIsNone(custom_battle.tactical_meeting_side(
                    screen, origin, destination, [player], [head_on]))
                self.resolve_without_automatic_combat(screen)

                self.assertEqual({id(unit) for unit in origin["units"]},
                                 {id(player), id(head_on), id(flanker)})
                self.assertEqual(player["order"]["path"], [])
                self.assertEqual((head_on["health"], flanker["health"]), (1, 1))

    def test_an_attacker_killed_in_a_crossing_cannot_cancel_another_divisions_route(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            for later_step in (False, True):
                for reverse_order in (False, True):
                    with self.subTest(mode=mode, later_step=later_step, reverse_order=reverse_order):
                        screen = self.screen()
                        screen.tactical_mode = mode == "tactical"
                        screen.multiplayer_mode = mode == "tournament"
                        screen.realtime_multiplayer = mode == "realtime"
                        screen.add_nation("C", at_war_with=["B"])
                        screen.nation_data["B"]["at_war_with"].append("C")
                        player = self.mover("A", ["p1", "p2", "p4"] if later_step else ["p2", "p4"], speed=3 if later_step else 2, attack=0, defense=0)
                        attacker = self.mover("B", ["p3", "p1"] if later_step else ["p1"], speed=2, health=1, attack=0, defense=0)
                        interceptor = self.mover("C", ["p1", "p3"] if later_step else ["p3"], speed=2, attack=100000, defense=0)
                        screen.player_unit = player
                        origin = screen.add_province("p1", "B", units=[] if later_step else [player, interceptor])
                        screen.add_province("p2", "B")
                        screen.add_province("p3", "B", units=[] if later_step else [attacker])
                        destination = screen.add_province("p4", "B")
                        if later_step:
                            screen.add_province("p0", "A", units=[player])
                            screen.add_province("p5", "B", units=[attacker])
                            screen.add_province("p6", "C", units=[interceptor])
                        if reverse_order:
                            screen.map_data = dict(reversed(list(screen.map_data.items())))

                        combat_processor.process_pinning(screen)
                        self.assertTrue(player["order"]["path"], "An intention alone must not erase the route.")
                        combat_processor.process_meeting_engagements(screen)
                        movement_processor.process_movement(screen)

                        self.assertEqual(attacker["health"], 0)
                        self.assertEqual(player["health"], player["max_health"])
                        self.assertTrue(any(unit is player for unit in destination["units"]))
                        self.assertFalse(any(unit is player for unit in origin["units"]))
                        self.assertEqual(player["order"]["path"], [])
                        self.assertTrue(all(unit is not attacker for province in screen.map_data.values() for unit in province["units"]))
                        self.assertNotIn("_skip_remaining_steps", player)

    def test_an_attacker_stopped_at_its_origin_does_not_cost_the_defender_movement(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            for reverse_order in (False, True):
                with self.subTest(mode=mode, reverse_order=reverse_order):
                    screen = self.screen()
                    screen.tactical_mode = mode == "tactical"
                    screen.multiplayer_mode = mode == "tournament"
                    screen.realtime_multiplayer = mode == "realtime"
                    screen.add_nation("C", at_war_with=["B"])
                    screen.nation_data["B"]["at_war_with"].append("C")
                    player = self.mover("A", ["p2", "p4"], speed=2, attack=0, defense=0)
                    attacker = self.mover("B", ["p1"], attack=0, defense=0)
                    opponent = self.mover("C", [], attack=0, defense=0)
                    screen.player_unit = player
                    screen.add_province("p1", "A", units=[player])
                    screen.add_province("p2", "B")
                    origin = screen.add_province("p3", "B", units=[attacker, opponent])
                    destination = screen.add_province("p4", "B")
                    if reverse_order:
                        screen.map_data = dict(reversed(list(screen.map_data.items())))

                    combat_processor.process_pinning(screen)
                    combat_processor.process_meeting_engagements(screen)
                    movement_processor.process_movement(screen)

                    self.assertTrue(any(unit is player for unit in destination["units"]))
                    self.assertEqual({id(unit) for unit in origin["units"]}, {id(attacker), id(opponent)})
                    self.assertEqual(player["order"]["path"], [])
                    self.assertEqual(attacker["order"]["path"], ["p1"])

    def test_an_actual_arrival_cancels_the_route_even_if_combat_kills_the_attacker(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            with self.subTest(mode=mode):
                screen = self.screen()
                screen.tactical_mode = mode == "tactical"
                screen.multiplayer_mode = mode == "tournament"
                screen.realtime_multiplayer = mode == "realtime"
                player = self.mover("A", ["p2"], attack=100000, defense=0)
                attacker = self.mover("B", ["p1"], health=1, attack=0, defense=0)
                screen.player_unit = player
                origin = screen.add_province("p1", "B", units=[player])
                screen.add_province("p2", "B")
                screen.add_province("p3", "B", units=[attacker])

                combat_processor.process_pinning(screen)
                self.assertEqual(player["order"]["path"], ["p2"])
                combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                combat_processor.process_combat(screen)

                self.assertTrue(any(unit is player for unit in origin["units"]))
                self.assertEqual(player["order"]["path"], [])
                if mode == "tactical":
                    self.assertEqual(attacker["health"], 1)
                    self.assertIsNotNone(custom_battle.tactical_encounter(screen, origin))
                else:
                    self.assertEqual(attacker["health"], 0)

    def test_an_attacker_refused_entry_does_not_cost_the_defender_movement(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            for reverse_order in (False, True):
                with self.subTest(mode=mode, reverse_order=reverse_order):
                    screen = self.screen()
                    screen.tactical_mode = mode == "tactical"
                    screen.multiplayer_mode = mode == "tournament"
                    screen.realtime_multiplayer = mode == "realtime"
                    player = self.mover("A", ["p2", "p4"], speed=2, attack=0, defense=0)
                    attacker = self.mover("B", ["p1"], attack=0, defense=0)
                    screen.player_unit = player
                    screen.add_province("p1", "A", units=[player])
                    screen.add_province("p2", "B")
                    origin = screen.add_province("p3", "B", units=[attacker])
                    destination = screen.add_province("p4", "B")
                    if reverse_order:
                        screen.map_data = dict(reversed(list(screen.map_data.items())))
                    can_enter = movement_processor.queries.can_land_units_enter
                    with patch("data.queries.can_land_units_enter", side_effect=lambda owner, province, nations: False if owner == "B" and province["id"] == "p1" else can_enter(owner, province, nations)):
                        combat_processor.process_pinning(screen)
                        combat_processor.process_meeting_engagements(screen)
                        movement_processor.process_movement(screen)

                    self.assertTrue(any(unit is player for unit in destination["units"]))
                    self.assertEqual(origin["units"], [attacker])
                    self.assertEqual(player["health"], player["max_health"])
                    self.assertEqual(player["order"]["path"], [])

    def test_an_attacker_held_in_combat_cannot_override_a_tactical_crossing(self):
        for reverse_order in (False, True):
            with self.subTest(reverse_order=reverse_order):
                screen = self.screen()
                screen.add_nation("C", at_war_with=["B"])
                screen.nation_data["B"]["at_war_with"].append("C")
                player = self.mover("A", ["p2"], attack=0, defense=0)
                head_on = self.mover("B", ["p1"], attack=0, defense=0)
                flanker = self.mover("B", ["p1"], attack=0, defense=0)
                opponent = self.mover("C", [], attack=0, defense=0)
                screen.player_unit = player
                screen.add_province("p1", "A", units=[player])
                destination = screen.add_province("p2", "B", units=[head_on])
                screen.add_province("p3", "B", units=[flanker, opponent])
                if reverse_order:
                    screen.map_data = dict(reversed(list(screen.map_data.items())))

                combat_processor.process_pinning(screen)
                combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                combat_processor.process_combat(screen)

                self.assertEqual({id(unit) for unit in destination["units"]}, {id(player), id(head_on)})
                self.assertTrue(any(unit is flanker for unit in screen.id_to_province["p3"]["units"]))

    def test_returning_to_own_land_still_pins_a_hostile_division(self):
        screen = self.screen()
        player = self.mover("A", ["p2"])
        opponent = self.mover("B", ["p1"])
        screen.player_unit = player
        origin = screen.add_province("p1", "B", units=[player])
        screen.add_province("p2", "B")
        screen.add_province("p3", "B", units=[opponent])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in origin["units"]}, {id(player), id(opponent)})

    def test_a_friendly_first_step_does_not_hide_an_attack_this_turn(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            with self.subTest(mode=mode):
                screen = self.screen()
                screen.tactical_mode = mode == "tactical"
                screen.multiplayer_mode = mode == "tournament"
                screen.realtime_multiplayer = mode == "realtime"
                player = self.mover("A", ["p2", "p3"], speed=2)
                opponent = self.mover("B", ["p1"])
                screen.player_unit = player
                origin = screen.add_province("p1", "A", units=[player])
                screen.add_province("p2", "A")
                screen.add_province("p3", "B")
                screen.add_province("p4", "B", units=[opponent])

                movement_processor.process_movement(screen)

                self.assertEqual({id(unit) for unit in origin["units"]}, {id(player), id(opponent)})
                self.assertEqual(player["order"]["path"], [])

    def test_friendly_withdrawal_is_not_pinned_by_an_incoming_attack(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            for destination_fighting in (False, True):
                with self.subTest(mode=mode, destination_fighting=destination_fighting):
                    screen = self.screen()
                    screen.tactical_mode = mode == "tactical"
                    screen.multiplayer_mode = mode == "tournament"
                    screen.realtime_multiplayer = mode == "realtime"
                    player = self.mover("A", ["p2"])
                    attacker = self.mover("B", ["p1"])
                    screen.player_unit = player
                    origin = screen.add_province("p1", "A", units=[player, self.mover("B", [])])
                    destination = screen.add_province("p2", "A", units=(
                        [self.mover("B", [])] if destination_fighting else []))
                    screen.add_province("p3", "B", units=[attacker])

                    combat_processor.process_pinning(screen)
                    combat_processor.process_meeting_engagements(screen)
                    movement_processor.process_movement(screen)
                    combat_processor.process_combat(screen)

                    self.assertTrue(any(unit is player for unit in destination["units"]))
                    self.assertTrue(any(unit is attacker for unit in origin["units"]))
                    self.assertFalse(any(unit is player for unit in origin["units"]))
                    self.assertEqual(player["order"]["path"], [])

    def test_an_attack_queued_for_a_later_turn_does_not_block_withdrawal(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3"], speed=1)
        opponent = self.mover("B", ["p1"])
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player])
        withdrawal = screen.add_province("p2", "A")
        screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[opponent])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual(withdrawal["units"], [player])
        self.assertEqual(player["order"]["path"], ["p3"])

    def test_later_step_incoming_attack_pins_the_current_position(self):
        for mode in ("ordinary", "tactical", "tournament", "realtime"):
            with self.subTest(mode=mode):
                screen = self.screen()
                screen.tactical_mode = mode == "tactical"
                screen.multiplayer_mode = mode == "tournament"
                screen.realtime_multiplayer = mode == "realtime"
                player = self.mover("A", ["p2", "p3"], speed=2)
                opponent = self.mover("B", ["p5", "p2"], speed=2)
                screen.player_unit = player
                screen.add_province("p1", "A", units=[player])
                encounter = screen.add_province("p2", "A")
                screen.add_province("p3", "B")
                screen.add_province("p4", "B", units=[opponent])
                screen.add_province("p5", "B")

                movement_processor.process_movement(screen)

                self.assertEqual({id(unit) for unit in encounter["units"]}, {id(player), id(opponent)})
                self.assertEqual(player["order"]["path"], [])

    def test_later_step_flanker_overrides_a_head_on_tactical_crossing(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3"], speed=2)
        head_on = self.mover("B", ["p3", "p2"], speed=2)
        flanker = self.mover("B", ["p5", "p2"], speed=2)
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player])
        encounter = screen.add_province("p2", "A")
        screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[head_on])
        screen.add_province("p5", "B")
        screen.add_province("p6", "B", units=[flanker])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in encounter["units"]},
                         {id(player), id(head_on), id(flanker)})

    def test_simultaneous_arrivals_stop_before_either_unit_can_leave(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3"], speed=2)
        opponent = self.mover("B", ["p2", "p1"], speed=2)
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player])
        encounter = screen.add_province("p2", "Unclaimed")
        screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[opponent])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in encounter["units"]}, {id(player), id(opponent)})
        self.assertEqual((player["health"], opponent["health"]), (1000, 1000))

    def test_convoy_landing_reaches_a_tactical_battle_without_a_charge_probe(self):
        screen = self.screen()
        player = self.mover("A", [], attack=100000, defense=0)
        opponent = self.mover("B", ["p1"], health=1, attack=0, defense=0)
        # An explicit artificial transport retains the landed division's stats.
        opponent.update(type="Convoy (Fixture Infantry I)", naval_unit=True,
                        original_type="Fixture Infantry I", original_speed=1,
                        original_max_health=1, original_attack=0, original_defense=0)
        screen.player_unit = player
        encounter = screen.add_province("p1", "A", units=[player])
        screen.add_province("p2", "B", units=[opponent], terrain="ocean")

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in encounter["units"]}, {id(player), id(opponent)})
        self.assertEqual(opponent["type"], "Fixture Infantry I")
        self.assertEqual(opponent["health"], 1)

    def test_a_convoy_already_on_land_unloads_before_any_automatic_battle_calculation(self):
        screen = self.screen()
        player = self.mover("A", [])
        opponent = self.mover("B", [], health=1, attack=0, defense=0)
        opponent.update(type="Convoy (Fixture Infantry I)", naval_unit=True,
                        original_type="Fixture Infantry I", original_speed=1,
                        original_max_health=1, original_attack=0, original_defense=0)
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player, opponent])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual(opponent["type"], "Fixture Infantry I")
        self.assertEqual(opponent["health"], 1)

    def test_a_friendly_first_step_cannot_hide_an_attack_when_already_fighting(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3"], speed=2)
        opponent = self.mover("B", [])
        screen.player_unit = player
        encounter = screen.add_province("p1", "A", units=[player, opponent])
        screen.add_province("p2", "A")
        screen.add_province("p3", "B")

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in encounter["units"]}, {id(player), id(opponent)})
        self.assertEqual(player["order"]["path"], [])

    def test_an_exhausted_later_step_attacker_cannot_override_crossing_priority(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3"], speed=2)
        opponent = self.mover("B", ["p3", "p2"], speed=2)
        exhausted = self.mover("B", ["p5", "p2"], speed=1)
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player])
        screen.add_province("p2", "A")
        encounter = screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[opponent])
        rest = screen.add_province("p5", "B")
        screen.add_province("p6", "B", units=[exhausted])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in encounter["units"]}, {id(player), id(opponent)})
        self.assertEqual(rest["units"], [exhausted])
        self.assertEqual(exhausted["order"]["path"], ["p2"])

    def test_tactical_deferral_preserves_aircraft_warship_and_neutral_exposure_rules(self):
        self.library.update({
            "Fixture Ship I": {"naval_unit": True, "bombard_range": 0},
            "Fixture Plane I": {"naval_unit": False, "air_role": "fighter", "bombard_range": 0},
        })
        screen = self.screen()
        screen.add_nation("C")
        player = self.mover("A", [])
        opponent = self.mover("B", [])
        ship = self.mover("A", [])
        plane = self.mover("B", [])
        neutral = self.mover("C", [])
        ship["type"] = neutral["type"] = "Fixture Ship I"
        plane["type"] = "Fixture Plane I"
        screen.player_unit = player
        encounter = screen.add_province("p1", "A", units=[player, opponent, ship, plane, neutral])

        self.resolve_without_automatic_combat(screen)

        self.assertEqual({id(unit) for unit in encounter["units"]}, {id(player), id(opponent), id(neutral)})
        self.assertEqual((ship["health"], plane["health"]), (0, 0))
        self.assertEqual((player["health"], opponent["health"], neutral["health"]), (1000, 1000, 1000))


class FinishedMoverVisibilityTests(unittest.TestCase):
    def test_a_finished_mover_still_blocks_a_later_arrival(self):
        screen = StubBattleMap(terrain="Plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        # C has 1 speed and finishes moving on step 1 (index 0).
        unit_c = make_unit("A", ["c2"], speed=1)
        # D has 2 speed and only reaches c2 on its second step (index 1),
        # by which point C is done moving but should still be standing there.
        unit_d = make_unit("B", ["mid", "c2"], speed=2)

        screen.add_province("c1", "A", units=[unit_c])
        screen.add_province("c2", "A")
        screen.add_province("mid", "B")
        screen.add_province("d1", "B", units=[unit_d])

        movement_processor.process_movement(screen)

        c2 = screen.id_to_province["c2"]
        self.assertIn(unit_c, c2["units"], "the finished unit should still be resting in c2")
        self.assertIn(unit_d, c2["units"], "the arriving unit should have stopped alongside it, not through it")
        self.assertEqual(c2["owner"], "A", "an enemy present should block the capture, not just the advance")


if __name__ == "__main__":
    unittest.main()
