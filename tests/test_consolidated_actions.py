"""Check shared action boundaries with artificial content and independent worlds."""

import copy
import json
import random
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from data import migrations, queries
from data.game_state import WorldState
from data.state_access import BackendState
from data.multiplayer.tournament import files as tournament_files
from data.multiplayer.realtime.session import MapRealtimeDriver, apply_authoritative_snapshot
from map_logic.actions import unit_actions
from map_logic.actions.player_actions import PlayerActions, collect_map_commands
from map_logic.diplomacy import faction_actions, faction_leadership, faction_records
from map_logic.diplomacy.action_definitions import availability
from tests.research_fixtures import fixture_metadata
from tests.stub_map_screen import synchronous_progress


def game():
    context = BackendState()
    context.player_country = "A"
    context.active_players = ["A"]
    context.scenario_settings = {"free_repairs": False, "fog_of_war": False}
    context.multiplayer_session_key = "fixture-session"
    for name in ("A", "B", "C"):
        context.nation_data[name] = {
            "name": name, "adjective": name, "leader_name": "", "leader_title": "",
            "color": [1, 2, 3], "flag_data": "DEFAULT", "portrait_data": "DEFAULT",
            "materials": 100, "manpower": 100, "fuel": 100,
            "research": {"fixture_track": 1}, "at_war_with": [], "puppets": [],
            "faction": "", "is_faction_leader": False}
    defaults = {
        "unit_library": {"Fixture": {"health": 20, "attack": 2, "defense": 1, "speed": 1,
            "cost_materials": 40, "cost_manpower": 10, "cost_fuel": 4, "production_time": 2,
            "metadata": fixture_metadata(), "bombard_range": 1}},
        "building_library": {}, "tech_tree": {}}
    context.world.runtime_rules.rebuild(context.scenario_settings, defaults)
    unit = {"unit_id": "fixture-unit", "owner": "A", "type": "Fixture",
            "max_health": 20, "health": 10, "attack": 2, "defense": 1, "speed": 1}
    for number in (1, 2):
        province = {"id": number, "json_key": str(number), "owner": "A", "cores": ["A"],
                    "terrain": "plains", "buildings": ["Basic Factory"],
                    "neighbors": [3 - number], "units": [unit] if number == 1 else []}
        context.map_data[number] = context.id_to_province[number] = province
    return context


class RuntimeOwnerTests(unittest.TestCase):
    def test_library_based_ai_interfaces_retain_their_worlds_research_tree(self):
        from map_logic.ai.ai_unit_eval import buildable_units
        first, second = game(), game()
        for context, year in ((first, 2000), (second, 1900)):
            library = queries.get_unit_library(context)
            library["Fixture"]["metadata"]["requirements"] = [{"tech": "fixture_years", "minimum_year": 2000}]
            queries.get_tech_tree(context)["fixture_years"] = {"years": [year]}
        research = {"fixture_years": 1}
        for _ in range(2):
            self.assertTrue(queries.is_unit_unlocked("Fixture", research, queries.get_unit_library(first)))
            self.assertFalse(queries.is_unit_unlocked("Fixture", research, queries.get_unit_library(second)))
            self.assertEqual(buildable_units(research, queries.get_unit_library(first)), ["Fixture"])
            self.assertEqual(buildable_units(research, queries.get_unit_library(second)), [])
    def test_planning_frames_reuse_forecasts_until_state_changes(self):
        from screens.game.map import cached_bilateral_response_indicator
        context = game()
        context._presentation_cache_revision = 0
        with patch("screens.game.map.bilateral_response_indicator", return_value="YES") as forecast:
            for _ in range(3):
                self.assertEqual(cached_bilateral_response_indicator(context, "B", "TRADE"), "YES")
            self.assertEqual(forecast.call_count, 1)
            queries.set_country_faction(context.nation_data, "A", "Pact")
            cached_bilateral_response_indicator(context, "B", "TRADE")
            self.assertEqual(forecast.call_count, 2)

    def test_world_libraries_indexes_and_draft_copies_are_independent(self):
        first, second = game(), game()
        library = queries.get_unit_library(first)
        first.scenario_settings["unit_range_overrides"] = {"Fixture": {"bombard_range": 3}}
        defaults = {key: copy.deepcopy(value) for key, value in second.world.runtime_rules.libraries.items()}
        first.world.runtime_rules.rebuild(first.scenario_settings, defaults)
        self.assertIs(queries.get_unit_library(first), library)
        self.assertEqual(queries.get_bombardment_range("Fixture", context=first), 3)
        self.assertEqual(queries.get_bombardment_range("Fixture", context=second), 1)
        queries.get_unit_research_index(library, context=first)
        second_index = queries.get_unit_research_index(queries.get_unit_library(second), context=second)
        draft = copy.copy(first)
        queries.get_unit_library(draft)["Fixture"]["cost_materials"] = 999
        draft.scenario_settings["free_repairs"] = True
        self.assertEqual(library["Fixture"]["cost_materials"], 40)
        self.assertFalse(first.scenario_settings["free_repairs"])
        first.world.runtime_rules.rebuild({}, defaults)
        self.assertEqual(first.world.runtime_rules.indexes, {})
        self.assertIs(queries.get_unit_research_index(queries.get_unit_library(second), context=second), second_index)

    def test_world_combat_settings_and_diplomacy_caches_do_not_cross(self):
        from map_logic.system32 import combat_rules
        first, second = game(), game()
        unit = first.map_data[1]["units"][0]
        first.scenario_settings["damage_at_zero_health"] = 0
        second.scenario_settings["damage_at_zero_health"] = 1
        self.assertEqual(combat_rules.health_damage_multiplier(unit, first.nation_data), .5)
        self.assertEqual(combat_rules.health_damage_multiplier(unit, second.nation_data), 1)
        queries.set_country_faction(first.nation_data, "A", "Fixture Pact")
        queries.set_country_faction(first.nation_data, "B", "Fixture Pact")
        with queries.diplomacy_snapshot():
            self.assertIn("B", queries.friendly_nations_view("A", first.nation_data))
            self.assertNotIn("B", queries.friendly_nations_view("A", second.nation_data))


class FactionOwnerTests(unittest.TestCase):
    def test_identity_survives_rename_succession_snapshot_and_unknown_fields(self):
        context = game()
        before_random = random.getstate()
        queries.set_country_faction(context.nation_data, "A", "Fixture Pact")
        queries.set_country_faction(context.nation_data, "B", "Fixture Pact")
        queries.set_faction_leadership(context.nation_data, "A", True)
        identity = queries.get_country_faction_id(context, "A")
        record = context.world.factions[identity]
        record["future"] = {"retained": True}
        queries.save_faction_pre_war_map("Fixture Pact", context.map_data, context.nation_data)
        self.assertTrue(faction_actions.rename_faction(context.nation_data, "A", "Fixture Pact", "Renamed Pact"))
        faction_leadership.transfer(context.nation_data, "A", "B")
        self.assertEqual(queries.get_country_faction_id(context, "B"), identity)
        self.assertEqual(record["members"], ["A", "B"])
        self.assertEqual(record["pre_war_borders"], {"1": "A", "2": "A"})
        snapshot = json.loads(json.dumps(queries.build_save_dict(context)))
        # Canonical records take precedence over stale country projections.
        snapshot["nation_data"]["A"]["faction"] = "Stale"
        restored = BackendState()
        apply_authoritative_snapshot(restored, snapshot)
        self.assertEqual(restored.world.factions, context.world.factions)
        self.assertEqual(restored.nation_data["A"]["faction"], "Renamed Pact")
        self.assertEqual(random.getstate(), before_random)

    def test_legacy_conversion_is_reproducible_and_keeps_country_border_history_separate(self):
        nations = {"A": {"faction": "Pact", "is_faction_leader": True},
                   "B": {"faction": "Pact"}, "FACTION_WAR_MAPS": {"Pact": {"1": "A"}},
                   "WAR_PRE_MAPS": {"A": {"2": "A"}}}
        self.assertEqual(faction_records.canonical_records(nations), faction_records.canonical_records(copy.deepcopy(nations)))
        context = BackendState(WorldState(nation_data=nations))
        faction_records.restore(context)
        identity = queries.get_country_faction_id(context, "A")
        self.assertEqual(context.world.factions[identity]["pre_war_borders"], {"1": "A"})
        self.assertEqual(context.nation_data["WAR_PRE_MAPS"], {"A": {"2": "A"}})
        faction_actions.disband_faction(context.nation_data, "Pact")
        self.assertEqual(context.world.factions, {})
        self.assertEqual(context.nation_data["WAR_PRE_MAPS"], {"A": {"2": "A"}})

    def test_projection_filters_unknown_private_faction_data(self):
        context = game()
        queries.set_country_faction(context.nation_data, "A", "Pact")
        queries.set_faction_leadership(context.nation_data, "A", True)
        identity = queries.get_country_faction_id(context, "A")
        context.world.factions[identity]["private_plan"] = "hidden"
        snapshot = queries.player_snapshot_projection(context, queries.build_save_dict(context), "B")
        self.assertNotIn("private_plan", snapshot["factions"][identity])


class SharedActionTests(unittest.TestCase):
    def test_previews_repeated_repairs_and_cancellation_do_not_duplicate_payment(self):
        context = game()
        province = context.map_data[1]
        unit = province["units"][0]
        before = copy.deepcopy(context.nation_data["A"])
        result = unit_actions.prepare_action(context, "A", province, unit, {"type": "REPAIR"})
        self.assertEqual(context.nation_data["A"], before)
        self.assertEqual(result.cost["cost_materials"], 20)
        unit_actions.apply_action(context, "A", province, unit, {"type": "REPAIR"})
        paid = copy.deepcopy(context.nation_data["A"])
        unit["order"]["turns_left"] = 3
        unit_actions.apply_action(context, "A", province, unit, {"type": "REPAIR"})
        self.assertEqual(context.nation_data["A"], paid)
        self.assertEqual(unit["order"]["turns_left"], 3)
        unit_actions.cancel_action(context, "A", province, unit)
        self.assertEqual(context.nation_data["A"], before)
        unit_actions.cancel_action(context, "A", province, unit)
        self.assertEqual(context.nation_data["A"], before)

    def test_local_tournament_and_realtime_apply_the_same_choices(self):
        local, realtime, tournament = game(), game(), game()
        province = local.map_data[1]
        unit_actions.apply_action(local, "A", province, province["units"][0], {"type": "REPAIR"})
        commands = collect_map_commands(local, "A")
        PlayerActions(realtime).apply_drafts({"A": commands})
        with tempfile.TemporaryDirectory() as directory:
            move = str(Path(directory, "fixture.gd5move"))
            tournament_files.export_move_file(local, move, "fixture-key")
            with patch.object(tournament_files, "run_with_progress", synchronous_progress):
                for _ in range(2):
                    summary = tournament_files.load_move_files(tournament, [move], {"A": "fixture-key"})
                    self.assertEqual(summary["loaded"], 1, summary)
        for other in (realtime, tournament):
            for key in ("materials", "manpower", "fuel"):
                self.assertEqual(other.nation_data["A"][key], local.nation_data["A"][key])
            self.assertEqual(other.map_data[1]["units"][0]["order"], local.map_data[1]["units"][0]["order"])

    def test_invalid_complete_draft_and_combined_budget_leave_state_unchanged(self):
        context = game()
        context.nation_data["A"]["materials"] = 50
        commands = [{"type": "unit_order", "province_id": 1, "unit_id": "fixture-unit",
                     "order": {"type": "REPAIR"}},
                    {"type": "province_queue", "province_id": 1, "queue": "unit_queue",
                     "items": [{"unit_type": "Fixture"}]}]
        before = copy.deepcopy((context.map_data, context.nation_data))
        with self.assertRaises(ValueError):
            PlayerActions(context).apply_drafts({"A": commands})
        self.assertEqual((context.map_data, context.nation_data), before)
        with self.assertRaises(ValueError):
            MapRealtimeDriver(context).validate_draft("B", commands[:1])
        self.assertEqual((context.map_data, context.nation_data), before)

    def test_cancelling_an_unsent_request_does_not_require_current_legality(self):
        from map_logic.diplomacy import diplomacy_processor
        context = game()
        queries.set_country_faction(context.nation_data, "A", "Pact")
        queries.set_faction_leadership(context.nation_data, "A", True)
        diplomacy_processor.toggle_diplomacy_action(context.nation_data, "A", "B", "FACTION_INVITE")
        queries.set_faction_leadership(context.nation_data, "A", False)
        self.assertFalse(availability(context, "A", "B", "FACTION_INVITE").allowed)
        diplomacy_processor.toggle_diplomacy_action(context.nation_data, "A", "B", "FACTION_INVITE")
        self.assertNotIn("B", context.nation_data["A"]["pending_diplomacy"])

    def test_queue_refund_can_pay_for_repair_before_domain_application(self):
        context = game()
        context.nation_data["A"]["materials"] = 0
        context.map_data[1]["unit_queue"] = [{"unit_type": "Fixture", "turns_remaining": 2,
                                              "refund": {"cost_materials": 20}}]
        commands = [{"type": "unit_order", "province_id": 1, "unit_id": "fixture-unit",
                     "order": {"type": "REPAIR"}},
                    {"type": "province_queue", "province_id": 1, "queue": "unit_queue", "items": []}]
        for _ in range(2):
            PlayerActions(context).apply_drafts({"A": commands})
            self.assertEqual(context.nation_data["A"]["materials"], 0)
            self.assertEqual(context.map_data[1]["unit_queue"], [])
            self.assertEqual(context.map_data[1]["units"][0]["order"]["type"], "REPAIR")

    def test_complete_drafts_preserve_repeat_and_cancel_volunteer_reservations(self):
        from map_logic.diplomacy import diplomacy_lifecycle, volunteers
        local, host = game(), game()
        for context in (local, host):
            context.nation_data["B"]["at_war_with"] = ["C"]
            context.nation_data["C"]["at_war_with"] = ["B"]
            context.nation_data["A"]["armies"] = [{"id": "fixture-army", "name": "Fixture army",
                                                       "unit_ids": ["fixture-unit"]}]
            queries.normalize_armies(context.nation_data, context.map_data)
        unit = host.map_data[1]["units"][0]
        diplomacy_lifecycle.put_request(local.nation_data, "A", "B", volunteers.ACTION)
        _, error = volunteers.create_offer(local, "A", "B", [(local.map_data[1], local.map_data[1]["units"][0])])
        self.assertFalse(error)
        commands = collect_map_commands(local, "A")
        for _ in range(2):
            PlayerActions(host).apply_drafts({"A": commands})
            queries.normalize_armies(host.nation_data, host.map_data)
            mission = volunteers.missions(host.nation_data, "A")["B"]
            self.assertIs(mission["held_units"][0]["unit"], unit)
            self.assertEqual(host.nation_data["A"]["armies"][0]["unit_ids"], [unit["unit_id"]])
            self.assertNotIn(unit, host.map_data[1]["units"])
        cancelled = copy.deepcopy(host)
        volunteers.cancel_offer(cancelled, "A", "B")
        PlayerActions(host).apply_drafts({"A": collect_map_commands(cancelled, "A")})
        self.assertIn(unit, host.map_data[1]["units"])
        self.assertEqual(volunteers.missions(host.nation_data, "A"), {})

    def test_shared_diplomacy_checks_subject_control_and_self_targeted_actions(self):
        context = game()
        command = {"type": "country_diplomacy", "pending": {"B": {"action": "ANNEX_PUPPET"}}}
        before = copy.deepcopy(context.nation_data)
        with self.assertRaises(ValueError):
            PlayerActions(context).apply_drafts({"A": [command]})
        self.assertEqual(context.nation_data, before)
        queries.set_country_faction(context.nation_data, "A", "Pact")
        queries.set_country_faction(context.nation_data, "B", "Pact")
        queries.set_faction_leadership(context.nation_data, "A", True)
        command["pending"] = {"A": {"action": "DISBAND_FACTION"}}
        self.assertEqual(PlayerActions(context).validate_draft("A", [command])[0]["pending"]["A"]["action"],
                         "DISBAND_FACTION")
