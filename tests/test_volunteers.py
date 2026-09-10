"""Volunteer offers, travel, returns, and host-side military behaviour."""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.stub_map_screen import StubMapScreen
from data import queries
import data.constants as c
from map_logic.ai import ai_evaluation
from map_logic.diplomacy import diplomacy_logic, diplomacy_messages, volunteers
from map_logic.diplomacy import military_attaches
from map_logic.turn_processing import combat_processor
from map_logic.rendering import overlay_renderer
from map_logic.turn_processing import combat_rules
from screens.map_related_screens.battle_screen import Battle_Screen


def division(owner):
    return {"owner": owner, "type": "Infantry Type 1910", "health": 100,
            "max_health": 100, "attack": 10, "defense": 10, "speed": 1,
            "order": {"type": "MOVE", "path": []}}


class VolunteerTests(unittest.TestCase):
    def game(self, human_players=("A",)):
        game = StubMapScreen(["A", "B", "C"], human_players=human_players)
        game.set_war("B", "C")
        game.border(game.home_of("A")["id"], game.home_of("B")["id"])
        return game

    def offer(self, game, count=1):
        home = game.home_of("A")
        home["units"] = [division("A") for _ in range(count)]
        details, error = volunteers.create_offer(game, "A", "B", [(home, home["units"][0])])
        self.assertFalse(error)
        diplomacy_logic.toggle_diplomacy_action(
            game.nation_data, "A", "B", volunteers.ACTION,
            f"We offer {details['count']} volunteer divisions. They arrive in {details['travel_turns']} turns.",
            parameters=details)
        return details

    def test_cap_rounds_up_and_is_shared(self):
        game = self.game()
        home = game.home_of("A")
        home["units"] = [division("A") for _ in range(11)]
        self.assertEqual(volunteers.cap(game, "A"), 2)
        details, error = volunteers.create_offer(game, "A", "B", [(home, home["units"][0])])
        self.assertFalse(error)
        self.assertEqual(volunteers.remaining_capacity(game, "A"), 1)
        self.assertEqual(details["count"], 1)

    def test_ai_accepts_and_bordering_volunteers_deploy_immediately(self):
        game = self.game()
        self.offer(game)
        game.run_turn()  # offer arrives
        game.run_turn()  # AI accepts

        host_home = game.home_of("B")
        volunteer_units = [u for u in host_home["units"] if u.get("owner") == "A"]
        self.assertEqual(len(volunteer_units), 1)
        self.assertEqual(volunteer_units[0].get("volunteer_host"), "B")
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.DEPLOYED)

    def test_ai_rejects_volunteers_from_a_country_aiding_its_enemy(self):
        game = self.game()
        game.nation_data["A"]["volunteer_missions"] = {
            "C": {"state": volunteers.DEPLOYED}}

        verdict = ai_evaluation.evaluate_verdict(
            game.nation_data, game.map_data, "B", "A", volunteers.ACTION)

        self.assertFalse(verdict.accepted)

    def test_ai_rejects_volunteers_from_a_country_observing_its_enemy(self):
        game = self.game()
        game.nation_data["A"]["military_attaches"] = ["C"]

        verdict = ai_evaluation.evaluate_verdict(
            game.nation_data, game.map_data, "B", "A", volunteers.ACTION)

        self.assertFalse(verdict.accepted)

    def test_ai_schedules_conflicting_volunteers_for_next_turn_send_home(self):
        game = self.game()
        game.nation_data["A"]["volunteer_missions"] = {
            "B": {"state": volunteers.DEPLOYED, "travel_turns": 1, "held_units": []},
            "C": {"state": volunteers.DEPLOYED, "travel_turns": 1, "held_units": []},
        }

        scheduled = volunteers.schedule_conflict_send_homes_for_ai_hosts(game.nation_data)

        self.assertEqual(scheduled, [("A", "B"), ("A", "C")])
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.DEPLOYED)
        self.assertEqual(volunteers.process_scheduled_send_homes(game), [("A", "B"), ("A", "C")])
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.RETURNING)
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "C"), volunteers.RETURNING)

    def test_simultaneous_opposite_side_offers_accept_before_next_turn_send_home(self):
        game = self.game()
        home = game.home_of("A")
        home["units"] = [division("A") for _ in range(11)]
        for host in ("B", "C"):
            details, error = volunteers.create_offer(
                game, "A", host, [(home, home["units"][0])])
            self.assertFalse(error)
            diplomacy_logic.toggle_diplomacy_action(
                game.nation_data, "A", host, volunteers.ACTION,
                "We offer volunteer divisions.", parameters=details)

        game.run_turn()  # Both offers travel.
        game.run_turn()  # Both AI hosts accept and schedule a send-home.

        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.DEPLOYED)
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "C"), volunteers.OUTBOUND)
        self.assertEqual(game.nation_data["B"].get(volunteers.PENDING_SEND_HOME_KEY), ["A"])
        self.assertEqual(game.nation_data["C"].get(volunteers.PENDING_SEND_HOME_KEY), ["A"])

        game.run_turn()  # Both scheduled send-homes start now.

        self.assertFalse(volunteers.mission_state(game.nation_data, "A", "B"))
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "C"), volunteers.RETURNING)

    def test_player_host_can_send_foreign_volunteers_home(self):
        game = self.game(human_players=("B",))
        unit = division("A")
        unit["volunteer_host"] = "B"
        unit["volunteer_origin_id"] = game.home_of("A")["id"]
        game.home_of("B")["units"] = [unit]
        game.nation_data["A"]["volunteer_missions"] = {
            "B": {"state": volunteers.DEPLOYED, "travel_turns": 1, "held_units": []}}
        diplomacy_logic.toggle_diplomacy_action(
            game.nation_data, "B", "A", volunteers.SEND_HOME_ACTION)

        diplomacy_logic.process_diplomacy_turn(game)

        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.RETURNING)

    def test_rejection_restores_the_selected_origin(self):
        game = self.game(human_players=("A", "B"))
        self.offer(game)
        origin = game.home_of("A")
        game.run_turn()
        diplomacy_logic.toggle_diplomatic_response(
            game.nation_data, "B", "A", diplomacy_messages.RESPONSE_REJECT, volunteers.ACTION)
        game.run_turn()
        self.assertEqual(len(origin["units"]), 1)
        self.assertFalse(volunteers.mission_state(game.nation_data, "A", "B"))

    def test_same_turn_offer_withdrawal_restores_divisions(self):
        game = self.game()
        self.offer(game)
        self.assertFalse(game.home_of("A")["units"])
        volunteers.cancel_offer(game, "A", "B")
        self.assertEqual(len(game.home_of("A")["units"]), 1)
        self.assertFalse(game.pending_action("A", "B"))

    def test_recall_is_a_reversible_unilateral_turn_action(self):
        game = self.game()
        self.offer(game)
        game.run_turn()
        game.run_turn()
        diplomacy_logic.toggle_diplomacy_action(
            game.nation_data, "A", "B", volunteers.RECALL_ACTION,
            "We are recalling our volunteer divisions.")
        self.assertEqual(game.pending_action("A", "B"), volunteers.RECALL_ACTION)
        diplomacy_logic.toggle_diplomacy_action(
            game.nation_data, "A", "B", volunteers.RECALL_ACTION)
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.DEPLOYED)
        self.assertFalse(game.pending_action("A", "B"))

    def test_orders_uses_volunteer_host_for_neutral_territory_entry(self):
        from screens.map_related_screens.orders import Orders_Screen

        game = self.game()
        host_home = game.home_of("B")
        host_extension = game.add_province("B", cores=["B"])
        game.border(host_home["id"], host_extension["id"])
        unit = division("A")
        unit["volunteer_host"] = "B"
        host_home["units"] = [unit]
        screen = object.__new__(Orders_Screen)
        screen.map_screen = game
        screen.target_province = host_home
        self.assertTrue(screen.can_unit_enter(unit, host_extension))

    def test_recall_uses_return_travel_then_send_unit_home(self):
        game = self.game()
        self.offer(game)
        game.run_turn()
        game.run_turn()
        mission = game.nation_data["A"]["volunteer_missions"]["B"]
        mission["travel_turns"] = 1
        self.assertTrue(volunteers.recall(game, "A", "B"))
        self.assertFalse(game.home_of("A")["units"])
        game.run_turn()
        self.assertEqual(len(game.home_of("A")["units"]), 1)
        self.assertFalse(volunteers.mission_state(game.nation_data, "A", "B"))

    def test_one_turn_arrival_and_automatic_recall(self):
        game = StubMapScreen(["A", "B", "C"], human_players=("A",))
        game.set_war("B", "C")
        middle = game.add_province("Unclaimed")
        game.border(game.home_of("A")["id"], middle["id"])
        game.border(middle["id"], game.home_of("B")["id"])
        details = self.offer(game)
        self.assertEqual(details["travel_turns"], 1)
        game.run_turn()
        game.run_turn()  # accepted; one travel turn remains
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.OUTBOUND)
        game.run_turn()
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.DEPLOYED)

        game.nation_data["B"]["at_war_with"] = []
        game.nation_data["C"]["at_war_with"] = []
        game.run_turn()
        self.assertEqual(volunteers.mission_state(game.nation_data, "A", "B"), volunteers.RETURNING)
        game.run_turn()
        self.assertEqual(len(game.home_of("A")["units"]), 1)

    def test_volunteers_capture_factory_for_the_host_not_the_donor(self):
        game = self.game()
        enemy_home = game.home_of("C")
        enemy_home["buildings"] = ["Basic Factory"]
        host_home = game.home_of("B")
        host_home["buildings"] = ["Basic Factory"]
        host_home["building_queue"] = [{"item_name": "Factory Lvl 1"}]
        new_host_factory = game.add_province("B")
        new_host_factory["building_queue"] = [{"item_name": "Basic Factory"}]
        unit = division("A")
        unit["volunteer_host"] = "B"
        enemy_home["units"] = [unit]
        combat_processor.check_for_post_combat_captures(game)

        self.assertEqual(enemy_home["owner"], "B")
        self.assertEqual(queries.get_factory_count("A", game.map_data), 0)
        self.assertEqual(queries.get_factory_count("B", game.map_data), 3)
        self.assertEqual(
            queries.get_building_cost("Basic Factory", "A", game.map_data, {})["cost_manpower"],
            c.BASIC_FACTORY_BASE_COST_X,
        )
        self.assertEqual(
            queries.get_building_cost("Basic Factory", "B", game.map_data, {})["cost_manpower"],
            c.BASIC_FACTORY_BASE_COST_X + (3 * c.BASIC_FACTORY_COST_MULTIPLIER),
        )

    def test_destroyed_volunteers_free_capacity_and_clear_the_mission(self):
        game = self.game()
        home = game.home_of("A")
        home["units"] = [division("A") for _ in range(10)]
        details, error = volunteers.create_offer(
            game, "A", "B", [(home, home["units"][0])])
        self.assertFalse(error)
        diplomacy_logic.toggle_diplomacy_action(
            game.nation_data, "A", "B", volunteers.ACTION,
            "We offer a volunteer division.", parameters=details)
        game.run_turn()
        game.run_turn()
        host_home = game.home_of("B")
        host_home["units"] = [unit for unit in host_home["units"]
                              if unit.get("owner") != "A"]

        self.assertEqual(volunteers.remaining_capacity(game, "A"), 1)
        self.assertFalse(volunteers.mission_state(game.nation_data, "A", "B"))
        self.assertTrue(volunteers.available_units(game, "A"))

    def test_volunteer_battle_is_donor_controlled_and_gets_an_outlook(self):
        game = self.game()
        game.nation_data["B"]["color"] = (30, 120, 220)
        game.nation_data["C"]["color"] = (220, 50, 50)
        volunteer = division("A")
        volunteer["volunteer_host"] = "B"
        enemy = division("C")
        province = game.home_of("B")
        province["units"] = [volunteer, enemy]

        battle = combat_rules.build_battle([province["units"]], game.nation_data)
        screen = object.__new__(Battle_Screen)
        screen.player = "A"
        screen.battle = battle
        screen.province = province
        screen.map_screen = SimpleNamespace(tactical_mode=False, player_unit=None)

        lane = battle.lanes[0]
        self.assertTrue(screen.is_mine(lane.a) or screen.is_mine(lane.b))
        near, far = screen.near_far(lane)
        self.assertTrue(screen.is_mine(near))
        self.assertFalse(screen.is_mine(far))
        self.assertEqual(
            overlay_renderer.combat_outlook_color(
                [province["units"]], game.nation_data, {"A"}, "A",
                province=province),
            overlay_renderer._desaturated_country_color(
                game.nation_data["B"]["color"]))


if __name__ == "__main__":
    unittest.main()
