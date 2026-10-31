"""Compare production adapters and reject drafts without partial payment."""

import copy
import unittest
from unittest.mock import patch

import data.constants as c
from data.state_access import BackendState
from data.multiplayer.realtime.session import MapRealtimeDriver, RealtimeError
from data.multiplayer.tournament.v46_moves import _validate_production_projection
from map_logic.actions import production_actions as actions
from tests.research_fixtures import fixture_metadata


class ProductionActionTests(unittest.TestCase):
    def setUp(self):
        self.library = {"fixture model": {"metadata": fixture_metadata(level=0),
                                        "cost_materials": 11, "cost_manpower": 3, "cost_fuel": 2,
                                        "production_time": 4}}
        self.context = BackendState()
        self.context.session.player_country = "A"
        self.context.world.nation_data["A"] = {"materials": 20, "manpower": 20, "fuel": 20,
                                              "research": {}, "at_war_with": []}
        for number in (1, 2):
            province = {"id": number, "json_key": str(number), "owner": "A", "cores": ["A"],
                        "units": [], "building_queue": [], "unit_queue": [], "buildings": []}
            self.context.world.map_data[str(number)] = province
            self.context.world.id_to_province[number] = province
        self.enterContext(patch("data.queries.get_unit_library", return_value=self.library))
        self.province = self.context.world.id_to_province[1]
        self.intent = {"unit_type": "fixture model"}

    def test_player_ai_and_realtime_use_the_same_payment_and_queue(self):
        states = [copy.deepcopy(self.context) for _ in range(3)]
        for state, authority in zip(states[:2], ("player", "ai")):
            actions.submit_production(state, "A", state.world.id_to_province[1], "unit_queue",
                                      self.intent, authority=authority)
        driver = MapRealtimeDriver(states[2].world, states[2].session)
        command = driver.validate_draft("A", [{"type": "province_queue", "province_id": 1,
                                               "queue": "unit_queue", "items": [self.intent]}])[0]
        actions.apply_queue_change(states[2], "A", command)
        for state in states[1:]:
            self.assertEqual(state.world.map_data, states[0].world.map_data)
            self.assertEqual(state.world.nation_data, states[0].world.nation_data)
        self.assertEqual(command["items"][0]["turns_remaining"], self.library["fixture model"]["production_time"])

    def test_affordability_rejection_and_stale_permissions_leave_state_unchanged(self):
        for change in ({"tactical_mode": True}, {"player_country": "B"}):
            context = copy.deepcopy(self.context)
            for key, value in change.items():
                setattr(context.session, key, value)
            before = copy.deepcopy((context.world.map_data, context.world.nation_data))
            with self.assertRaises(ValueError):
                actions.submit_production(context, "A", context.world.id_to_province[1], "unit_queue", self.intent)
            self.assertEqual((context.world.map_data, context.world.nation_data), before)
        self.context.world.nation_data["A"]["materials"] = 0
        before = copy.deepcopy((self.context.world.map_data, self.context.world.nation_data))
        with self.assertRaises(ValueError):
            actions.submit_production(self.context, "A", self.province, "unit_queue", self.intent)
        self.assertEqual((self.context.world.map_data, self.context.world.nation_data), before)

    def test_cancellation_returns_recorded_payment_after_library_edits(self):
        before = copy.deepcopy(self.context.world.nation_data["A"])
        actions.submit_production(self.context, "A", self.province, "unit_queue", self.intent)
        self.library["fixture model"]["cost_materials"] += 99
        actions.cancel_production(self.context, "A", self.province, "unit_queue", 0)
        self.assertEqual(self.context.world.nation_data["A"], before)
        self.assertEqual(self.province["unit_queue"], [])

    def test_aggregate_budget_and_duplicate_projections_are_atomic(self):
        driver = MapRealtimeDriver(self.context)
        commands = [{"type": "province_queue", "province_id": number,
                     "queue": "unit_queue", "items": [self.intent]} for number in (1, 2)]
        before = copy.deepcopy((self.context.world.map_data, self.context.world.nation_data))
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", commands)
        self.assertEqual((self.context.world.map_data, self.context.world.nation_data), before)
        with self.assertRaisesRegex(RealtimeError, "one projection"):
            driver.validate_draft("A", [commands[0], commands[0]])
        self.assertEqual((self.context.world.map_data, self.context.world.nation_data), before)
        with self.assertRaises(ValueError):
            _validate_production_projection(self.context, "A", {
                str(number): {"unit_queue": [self.intent]} for number in (1, 2)})
        self.assertEqual((self.context.world.map_data, self.context.world.nation_data), before)

    def test_paid_entries_keep_their_progress_and_are_not_charged_twice(self):
        result = actions.submit_production(self.context, "A", self.province, "unit_queue", self.intent)
        result.order["turns_remaining"] -= 1
        command = actions.reconstruct_queue(self.context, "A", self.province, "unit_queue", [result.order])
        self.assertEqual(command["items"], [result.order])
        self.assertEqual(command["new_costs"], [])
        self.assertEqual(command["cancelled"], [])

    def test_ai_building_manpower_policy_is_explicit(self):
        fixture = {"Fixture Building": {"group": "fixture", "time": 3,
                                        "cost_materials": 4, "cost_manpower": 5, "cost_fuel": 1}}
        intent = {"order_type": "BUILDING", "item_name": "Fixture Building"}
        with patch("data.queries.get_building_required_tech", return_value=(None, 0)):
            player = actions.prepare_production(self.context, "A", self.province, "building_queue", intent,
                                                 building_library=fixture)
            ai = actions.prepare_production(self.context, "A", self.province, "building_queue", intent,
                                             building_library=fixture, policy=actions.AI_POLICY)
        self.assertEqual(player.cost["cost_manpower"], fixture["Fixture Building"]["cost_manpower"])
        self.assertEqual(ai.cost["cost_manpower"], 0)
        for resource in c.ECON_RESOURCE_KEYS:
            if resource != "manpower":
                self.assertEqual(ai.cost[f"cost_{resource}"], player.cost[f"cost_{resource}"])


class AdministrativeLegalityTests(unittest.TestCase):
    """Execution owns the coring rules, so no client can skip them."""

    def setUp(self):
        self.context = BackendState()
        self.context.world.nation_data["A"] = {"materials": 0, "manpower": 10 ** 6, "fuel": 0, "research": {}}
        for number, neighbors, cores in ((1, [2], ["A"]), (2, [1], []), (3, [], [])):
            province = {"id": number, "json_key": str(number), "owner": "A", "cores": cores, "neighbors": neighbors,
                        "units": [], "building_queue": [], "unit_queue": [], "buildings": []}
            self.context.world.map_data[str(number)] = province
            self.context.world.id_to_province[number] = province
        self.connected, self.isolated = (self.context.world.id_to_province[number] for number in (2, 3))

    def prepare(self, province, order_type):
        return actions.prepare_production(self.context, "A", province, "building_queue", {"order_type": order_type})

    def test_coring_requires_a_connected_or_coastal_tile(self):
        self.assertEqual(self.prepare(self.connected, "CORE").order["order_type"], "CORE")
        with self.assertRaisesRegex(ValueError, "coast"):
            self.prepare(self.isolated, "CORE")
        self.isolated["is_coastal"] = True
        self.assertEqual(self.prepare(self.isolated, "CORE").order["order_type"], "CORE")

    def test_a_country_with_no_cores_can_core_anywhere(self):
        self.context.world.id_to_province[1]["cores"] = []
        self.assertEqual(self.prepare(self.isolated, "CORE").order["order_type"], "CORE")

    def test_removing_cores_requires_a_garrison_and_a_connected_tile(self):
        for province in (self.connected, self.isolated):
            province["cores"] = ["B"]
        with self.assertRaisesRegex(ValueError, "units"):
            self.prepare(self.connected, "REMOVE_CORE")
        self.connected["units"] = [{"owner": "B"}]
        with self.assertRaisesRegex(ValueError, "units"):
            self.prepare(self.connected, "REMOVE_CORE")
        self.connected["units"] = [{"owner": "A"}]
        self.assertEqual(self.prepare(self.connected, "REMOVE_CORE").order["order_type"], "REMOVE_CORE")
        self.isolated["units"] = [{"owner": "A"}]
        with self.assertRaisesRegex(ValueError, "coast"):
            self.prepare(self.isolated, "REMOVE_CORE")

    def test_realtime_rejects_an_illegal_order_and_keeps_an_accepted_one(self):
        driver = MapRealtimeDriver(self.context)
        before = copy.deepcopy((self.context.world.map_data, self.context.world.nation_data))
        with self.assertRaisesRegex(RealtimeError, "coast"):
            driver.validate_draft("A", [{"type": "province_queue", "province_id": 3, "queue": "building_queue",
                                         "items": [{"order_type": "CORE"}]}])
        self.assertEqual((self.context.world.map_data, self.context.world.nation_data), before)
        # An order the server already accepted stays valid if the tile later loses its connection.
        accepted = self.prepare(self.connected, "CORE").order
        self.connected["building_queue"] = [accepted]
        self.context.world.id_to_province[1]["cores"] = ["B"]
        self.context.world.id_to_province[3]["cores"] = ["A"]
        command = driver.validate_draft("A", [{"type": "province_queue", "province_id": 2, "queue": "building_queue",
                                               "items": [copy.deepcopy(accepted)]}])[0]
        self.assertEqual(command["items"], [accepted])
        self.assertEqual(command["new_costs"], [])
