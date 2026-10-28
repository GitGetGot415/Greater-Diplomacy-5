"""Regression coverage for tournament move serialization and host import.

Tournament players submit only their own country record.  Shared faction state
and integrated-puppet appearance edits therefore need explicit, host-validated
commands rather than relying on that one record to describe the whole world.
"""

import json
import copy
import os
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from data.multiplayer.tournament import files as multiplayer_io


class Time:
    day = 1
    month_index = 0
    year = 1939
    total_turns = 4


def nation(faction="", leader=False, master="", puppet_type="", name=None,
           color=None):
    return {
        "name": name or "Nation",
        "adjective": "National",
        "leader_name": "Leader",
        "leader_title": "President",
        "flag_data": "DEFAULT",
        "portrait_data": "DEFAULT",
        "color": list(color or (30, 40, 50)),
        "is_playable": True,
        "faction": faction,
        "is_faction_leader": leader,
        "faction_pressure": 0,
        "faction_tenure": 3,
        "master": master,
        "puppet_type": puppet_type,
        "puppets": [],
        "at_war_with": [],
        "pending_diplomacy": {},
        "diplo_responses": {},
        "materials": 100,
        "fuel": 100,
        "manpower": 100,
        "production_queue": [],
        "research_queue": [],
        "current_research": None,
    }


class Host:
    def __init__(self):
        self.time_manager = Time()
        self.multiplayer_session_key = "test-session"
        self.nation_data = {
            "Leader": nation("Old Pact", leader=True, name="Leader"),
            "Member": nation("Old Pact", name="Member"),
            "Subject": nation(master="Leader", puppet_type=c.PUPPET_TYPE_INTEGRATED,
                              name="Subject", color=(60, 70, 80)),
            "Outsider": nation(name="Outsider", color=(90, 100, 110)),
            "FACTION_WAR_MAPS": {"Old Pact": {"1": "Leader", "2": "Member"}},
        }
        self.nation_data["Leader"]["puppets"] = ["Subject"]
        self.nation_colors = {
            name: tuple(data["color"])
            for name, data in self.nation_data.items() if isinstance(data, dict) and "color" in data
        }
        self.map_data = {}
        self.scenario_settings = {}
        self.submitted_moves = set()
        self.syncs = 0

    def sync_units_to_data(self):
        self.syncs += 1


def synchronous_progress(jobs, worker, _caption, on_result):
    for job in jobs:
        result = worker(job)
        if result:
            on_result(result)


class TournamentMoveTests(unittest.TestCase):
    keys = {"Leader": "leader-key", "Member": "member-key"}

    def write_move(self, directory, file_name, country_id, player_data):
        path = os.path.join(directory, file_name)
        payload = {
            "country_id": country_id,
            "hash": multiplayer_io.hash_key(self.keys[country_id]),
            "data": multiplayer_io.encrypt_dict(player_data, self.keys[country_id]),
        }
        with open(path, "w") as file:
            json.dump(payload, file)
        return path

    def import_moves(self, host, paths, **options):
        with mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
            return multiplayer_io.load_move_files(host, paths, self.keys, **options)

    def player_data(self, country_id, host, **extra):
        result = {
            "nation_data": dict(host.nation_data[country_id]),
            "provinces": {},
            "game_version": c.GAME_VERSION,
            "tournament_session": host.multiplayer_session_key,
            "tournament_turn": host.time_manager.total_turns,
        }
        result.update(extra)
        return result

    def v46_move(self, country_id, host, **extra):
        """A move with the sections every v46 export wrote, and no version stamp."""
        result = self.player_data(country_id, host, aircraft_orders=[], release_subjects=[])
        result.pop("game_version")
        result.update(extra)
        return result

    def test_factory_output_research_intents_require_host_prerequisites_and_current_turn(self):
        tree = queries.get_tech_tree()
        cases = (("waltham_system", {}, {"basic_factory": 1}),
                 ("bessemer_process", {"basic_factory": 1}, {"waltham_system": 1}),
                 ("conveyor_belt", {"factory": tree["conveyor_belt"]["req"]["factory"] - 1},
                  dict(tree["conveyor_belt"]["req"])),
                 ("just_in_time_manufacturing", {"factory": tree["just_in_time_manufacturing"]["req"]["factory"] - 1},
                  dict(tree["just_in_time_manufacturing"]["req"])),
                 ("assembly_line", {"bessemer_process": 1}, {"factory": 1}),
                 ("factory", {}, {"bessemer_process": 1}),
                 ("factory", {"factory": 1, "bessemer_process": 1},
                  {"factory": 1, "bessemer_process": 1, "assembly_line": 1}),
                 ("factory", {"factory": 3, "bessemer_process": 1, "assembly_line": 1},
                  {"factory": 3, "bessemer_process": 1, "assembly_line": 1, "conveyor_belt": 1}),
                 ("factory", {"factory": 8, "bessemer_process": 1, "assembly_line": 1, "conveyor_belt": 1},
                  {"factory": 8, "bessemer_process": 1, "assembly_line": 1, "conveyor_belt": 1,
                   "just_in_time_manufacturing": 1}))
        for tech, locked, unlocked in cases:
            for mode in ("valid", "locked", "malformed", "stale", "wrong_key"):
                with self.subTest(tech=tech, mode=mode), tempfile.TemporaryDirectory() as directory:
                    host = Host()
                    host.nation_data["Leader"]["research"] = dict(locked if mode == "locked" else unlocked)
                    move = {"player_intents": [{"type": "research_queue",
                            "tech_names": tech if mode == "malformed" else [tech], "points_remaining": 0}],
                            "game_version": c.GAME_VERSION,
                            "tournament_session": host.multiplayer_session_key,
                            "tournament_turn": host.time_manager.total_turns - int(mode == "stale")}
                    before = copy.deepcopy(host.nation_data)
                    path = self.write_move(directory, "research.gd5move", "Leader", move)
                    if mode == "wrong_key":
                        with open(path) as file:
                            payload = json.load(file)
                        payload["hash"] = multiplayer_io.hash_key(self.keys["Member"])
                        with open(path, "w") as file:
                            json.dump(payload, file)
                    result = self.import_moves(host, [path])
                    self.assertEqual(result["loaded"], int(mode == "valid"), result["rejections"])
                    if mode == "valid":
                        self.assertEqual(host.nation_data["Leader"]["research_queue"],
                                         [{"tech_name": tech, "points_remaining": tree[tech]["cost"]}])
                        self.assertEqual(host.nation_data["Member"], before["Member"])
                    else:
                        self.assertEqual(host.nation_data, before)

    def stat_move(self, host):
        unit = {"unit_id": "test-unit", "owner": "Leader", "type": "Test ground unit",
                "health": 12, "max_health": 20, "attack": 4, "defense": 3,
                "speed": 2, "morale": 1, "level": 0}
        host.map_data = {"home": {"id": 1, "json_key": "P1", "owner": "Leader", "units": [unit]}}
        move = self.player_data("Leader", host, unit_snapshot=True,
                                provinces={"P1": {"units": [copy.deepcopy(unit)]}})
        move["provinces"]["P1"]["units"][0]["attack"] += 1
        return move

    def test_production_uses_shared_costs_and_rejects_cumulative_overspend(self):
        from map_logic.actions import production_actions
        from tests.test_unit_metadata import fixture_metadata
        library = {"Fixture recruit": {"metadata": fixture_metadata(level=0),
                                      "cost_materials": 11, "cost_manpower": 3, "cost_fuel": 2,
                                      "production_time": 4}}
        for affordable, complete in ((True, True), (False, True), (True, False), (False, False)):
            with self.subTest(affordable=affordable, complete=complete), tempfile.TemporaryDirectory() as directory:
                host = Host()
                cost = library["Fixture recruit"]["cost_materials"]
                host.nation_data["Leader"]["materials"] = 2 * cost if affordable else 2 * cost - 1
                host.map_data = {str(number): {"id": number, "json_key": str(number), "owner": "Leader",
                                              "cores": ["Leader"], "units": [], "unit_queue": []}
                                 for number in (1, 2)}
                with mock.patch.object(queries, "get_unit_library", return_value=library):
                    queues = {key: {"unit_queue": [production_actions.prepare_production(
                        host, "Leader", province, "unit_queue", {"unit_type": "Fixture recruit"}).order]}
                              for key, province in host.map_data.items()}
                    expected = copy.deepcopy(queues)
                    if not complete:
                        for update in queues.values():
                            update["unit_queue"][0].pop("refund")
                    move = self.player_data("Leader", host, provinces=queues)
                    for resource in c.ECON_RESOURCE_KEYS:
                        move["nation_data"][resource] -= 2 * library["Fixture recruit"][f"cost_{resource}"]
                    before = copy.deepcopy((host.nation_data, host.map_data))
                    path = self.write_move(directory, "production.gd5move", "Leader", move)
                    result = self.import_moves(host, [path], accept_stat_mismatches=True)
                self.assertEqual(result["loaded"], int(affordable))
                if affordable:
                    for key in host.map_data:
                        self.assertEqual(host.map_data[key]["unit_queue"], expected[key]["unit_queue"])
                else:
                    self.assertEqual((host.nation_data, host.map_data), before)
                    self.assertFalse(result["rejections"][0]["overridable"])

    def test_response_references_are_checked_before_country_merge(self):
        from map_logic.diplomacy import diplomacy_messages
        for correct in (True, False):
            with self.subTest(correct=correct), tempfile.TemporaryDirectory() as directory:
                host = Host()
                request = diplomacy_messages.set_pending(host.nation_data, "Member", "Leader", "TRADE", turns=1)
                move = self.player_data("Leader", host)
                move["nation_data"] = copy.deepcopy(move["nation_data"])
                move["nation_data"]["diplo_responses"] = {"Member": {
                    "action": "TRADE", "verdict": "ACCEPT", "message": "",
                    "request_id": request["request_id"] if correct else "cancelled-request"}}
                before = copy.deepcopy(host.nation_data)
                path = self.write_move(directory, "reply.gd5move", "Leader", move)
                result = self.import_moves(host, [path], accept_stat_mismatches=True)
                self.assertEqual(result["loaded"], int(correct))
                if not correct:
                    self.assertEqual(host.nation_data, before)
                    self.assertFalse(result["rejections"][0]["overridable"])

    def test_paid_older_queue_keeps_countdown_without_recharging_or_recruitment_checks(self):
        host = Host()
        paid = {"unit_type": "Retired fixture unit", "days_remaining": 2 * c.DEFAULT_DAYS_PER_TURN,
                "refund": {"cost_materials": 7}, "custom_field": {"keep": True}}
        # The v46 move keeps the day countdown. Loading already converted the host's own queue.
        converted = {key: value for key, value in paid.items() if key != "days_remaining"}
        converted["turns_remaining"] = 2
        host.map_data = {"home": {"id": 1, "json_key": "P1", "owner": "Leader", "units": [],
                                  "unit_queue": [copy.deepcopy(converted)]}}
        move = self.v46_move("Leader", host, provinces={"P1": {"unit_queue": [copy.deepcopy(paid)]}})
        before = copy.deepcopy(host.nation_data["Leader"])
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "paid.gd5move", "Leader", move)
            result = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(result["loaded"], 1, result["rejections"])
        self.assertEqual(host.map_data["home"]["unit_queue"], [converted])
        for resource in c.ECON_RESOURCE_KEYS:
            self.assertEqual(host.nation_data["Leader"][resource], before[resource])

    def test_older_reply_actions_bind_to_the_host_request_and_keep_travelling_requests(self):
        from map_logic.diplomacy import diplomacy_messages
        for reply in ({"action": "ACCEPT_TRADE", "message": "Reply"},
                      {"action": "REJECT_TRADE", "message": "Reply"}):
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as directory:
                host = Host()
                incoming = diplomacy_messages.set_pending(host.nation_data, "Member", "Leader", "TRADE", turns=1)
                outgoing = diplomacy_messages.set_pending(host.nation_data, "Leader", "Outsider", "TRADE", turns=1)
                move = self.v46_move("Leader", host)
                move["nation_data"] = copy.deepcopy(move["nation_data"])
                move["nation_data"]["pending_diplomacy"] = {"Member": reply, "Outsider": "TRADE"}
                before = copy.deepcopy(host.nation_data)
                path = self.write_move(directory, "older-reply.gd5move", "Leader", move)
                result = self.import_moves(host, [path], accept_older_versions=True)
                self.assertEqual(result["loaded"], 1, result["rejections"])
                response = host.nation_data["Leader"]["diplo_responses"]["Member"]
                self.assertEqual(response["request_id"], incoming["request_id"])
                self.assertEqual(response["verdict"], reply["action"].split("_")[0])
                self.assertEqual(host.nation_data["Leader"]["pending_diplomacy"]["Outsider"], outgoing)
                self.assertEqual(host.nation_data["Member"], before["Member"])

    def test_ratification_defaults_keep_the_host_round_and_reject_explicit_stale_ids(self):
        for answer in (None, {"verdict": "RATIFY"}, {"verdict": "RATIFY", "treaty_id": "expired"}):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory:
                host = Host()
                asked = {"treaty_id": "current", "signatory": "Member", "opponent": "Outsider",
                         "turns": 1, "deal": {"fixture": "authoritative"}}
                host.nation_data["Leader"]["pending_ratification"] = copy.deepcopy(asked)
                move = self.player_data("Leader", host)
                move["nation_data"].pop("pending_ratification")
                if answer is not None:
                    move["nation_data"]["pending_ratification"] = answer
                before = copy.deepcopy(host.nation_data)
                path = self.write_move(directory, "ratification.gd5move", "Leader", move)
                result = self.import_moves(host, [path])
                if answer and answer.get("treaty_id") == "expired":
                    self.assertEqual(result["loaded"], 0)
                    self.assertEqual(host.nation_data, before)
                else:
                    self.assertEqual(result["loaded"], 1, result["rejections"])
                    expected = dict(asked, **({"verdict": "RATIFY"} if answer else {}))
                    self.assertEqual(host.nation_data["Leader"]["pending_ratification"], expected)

    def test_imported_conscription_changes_only_the_submitting_countrys_damage_bonus(self):
        host = Host()
        host.nation_data["Member"]["conscription_slider"] = 0.5
        move = self.player_data("Leader", host)
        move["nation_data"]["conscription_slider"] = 0.25
        before_member = copy.deepcopy(host.nation_data["Member"])
        expected = queries.get_conscription_damage_bonus(move["nation_data"])
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "conscription.gd5move", "Leader", move)
            result = self.import_moves(host, [path])
        self.assertEqual(result["loaded"], 1)
        self.assertEqual(host.nation_data["Leader"]["conscription_slider"], 0.25)
        self.assertEqual(queries.get_conscription_damage_bonus(host.nation_data["Leader"]), expected)
        self.assertEqual(host.nation_data["Member"], before_member)

    def test_older_move_cannot_restore_the_removed_direct_alliance_field(self):
        host = Host()
        move = self.v46_move("Leader", host)
        move["nation_data"]["allied_with"] = ["Outsider"]
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "older-country.gd5move", "Leader", move)
            result = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(result["loaded"], 1)
        self.assertNotIn("allied_with", host.nation_data["Leader"])
        self.assertNotIn("Outsider", queries.get_all_friendly_nations("Leader", host.nation_data))
        self.assertEqual(host.nation_data["Leader"]["faction"], "Old Pact")

    def test_each_unreadable_or_unauthenticated_file_has_a_rejection_reason(self):
        host = Host()
        with tempfile.TemporaryDirectory() as directory:
            payloads = ["{", "[]", json.dumps({"country_id": []}),
                        json.dumps({"country_id": "Leader", "hash": "wrong"}),
                        json.dumps({"country_id": "Leader", "hash": multiplayer_io.hash_key(self.keys["Leader"]),
                                    "data": "broken"})]
            paths = [os.path.join(directory, "missing.gd5move")]
            for index, payload in enumerate(payloads):
                path = os.path.join(directory, f"bad-{index}.gd5move")
                with open(path, "w") as file:
                    file.write(payload)
                paths.append(path)
            summary = self.import_moves(host, paths, accept_stat_mismatches=True)
        self.assertEqual(summary["rejected"], len(paths))
        self.assertEqual([item["file_path"] for item in summary["rejections"]], paths)
        self.assertTrue(all(item["reason"] and not item["overridable"] for item in summary["rejections"]))
        self.assertEqual(summary["loaded"], 0)
        self.assertEqual(host.submitted_moves, set())

    def test_stat_mismatch_requires_explicit_acceptance_without_partial_changes(self):
        host = Host()
        move = self.stat_move(host)
        move["faction_renames"] = [{"old_name": "Old Pact", "new_name": "New Pact"}]
        before = copy.deepcopy((host.nation_data, host.map_data))
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "stats.gd5move", "Leader", move)
            rejected = self.import_moves(host, [path])
            self.assertEqual(rejected["rejected"], 1)
            self.assertTrue(rejected["rejections"][0]["overridable"])
            self.assertIn("attack", rejected["rejections"][0]["reason"])
            self.assertEqual((host.nation_data, host.map_data), before)
            self.assertEqual(host.submitted_moves, set())
            self.assertEqual(host.syncs, 0)
            accepted = self.import_moves(host, [path], accept_stat_mismatches=True)
        self.assertEqual(accepted["loaded"], 1)
        self.assertEqual(accepted["overridden"], 1)
        self.assertEqual(host.map_data["home"]["units"][0]["attack"], move["provinces"]["P1"]["units"][0]["attack"])
        self.assertEqual(host.nation_data["Member"]["faction"], "New Pact")

    def test_stat_override_never_bypasses_hard_failures(self):
        from map_logic import politics

        def invalid_policy(move):
            move["nation_data"][politics.POLICY_KEY] = {
                "research_subsidies": {"status": politics.POLICY_ACTIVE}}

        mutations = {
            "wrong turn": lambda move: move.update(tournament_turn=Time.total_turns - 1),
            "wrong session": lambda move: move.update(tournament_session="another-session"),
            "empty country": lambda move: move.update(nation_data={}),
            "missing section": lambda move: move.pop("provinces"),
            "malformed province": lambda move: move["provinces"].update(P1=[]),
            "unknown province": lambda move: move["provinces"].update(missing={}),
            "foreign unit": lambda move: move["provinces"]["P1"]["units"][0].update(owner="Member"),
            "broken stat": lambda move: move["provinces"]["P1"]["units"][0].update(attack="bad"),
            "nonfinite stat": lambda move: move["provinces"]["P1"]["units"][0].update(attack=float("nan")),
            "foreign aircraft": lambda move: move.update(aircraft_orders=[{"unit_id": "missing"}]),
            "invalid policy": invalid_policy,
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.stat_move(host)
                move["faction_renames"] = [{"old_name": "Old Pact", "new_name": "New Pact"}]
                mutate(move)
                before = copy.deepcopy((host.nation_data, host.map_data))
                path = self.write_move(directory, "bad.gd5move", "Leader", move)
                summary = self.import_moves(host, [path], accept_stat_mismatches=True)
                self.assertEqual(summary["loaded"], 0)
                self.assertEqual(summary["rejected"], 1)
                self.assertFalse(summary["rejections"][0]["overridable"])
                self.assertTrue(summary["rejections"][0]["reason"])
                self.assertEqual((host.nation_data, host.map_data), before)
                self.assertEqual(host.submitted_moves, set())

    def test_duplicate_during_host_review_cannot_be_overridden(self):
        host = Host()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "move.gd5move", "Leader", self.player_data("Leader", host))
            initial = self.import_moves(host, [path])
            self.assertEqual(initial["loaded"], 1)
            summary = self.import_moves(host, [path], accept_stat_mismatches=True,
                                        loaded_countries=initial["loaded_countries"])
        self.assertEqual(summary["rejected"], 1)
        self.assertFalse(summary["rejections"][0]["overridable"])
        self.assertIn("already", summary["rejections"][0]["reason"])

    def test_administrative_duration_can_be_overridden_but_disabled_actions_cannot(self):
        order, (setting, _) = next(iter(queries.ADMINISTRATIVE_ACTIONS.items()))
        for disabled in (False, True):
            with self.subTest(disabled=disabled), tempfile.TemporaryDirectory() as directory:
                host = Host()
                host.map_data = {"home": {"id": 1, "json_key": "P1", "owner": "Leader", "units": []}}
                host.scenario_settings = {"administrative_turn_overrides": {setting: 7},
                                          "administrative_disabled": [setting] if disabled else []}
                cost = queries.get_core_cost("Leader", host.map_data, host.scenario_settings)
                for resource in c.ECON_RESOURCE_KEYS:
                    host.nation_data["Leader"][resource] = cost[f"cost_{resource}"]
                move = self.player_data("Leader", host, provinces={"P1": {"building_queue": [
                    {"order_type": order, "turns_remaining": 8}]}})
                path = self.write_move(directory, "duration.gd5move", "Leader", move)
                rejected = self.import_moves(host, [path])
                self.assertEqual(rejected["rejections"][0]["overridable"], not disabled)
                accepted = self.import_moves(host, [path], accept_stat_mismatches=True)
                self.assertEqual(accepted["loaded"], int(not disabled))
                if not disabled:
                    self.assertEqual(host.map_data["home"]["building_queue"][0]["turns_remaining"], 8)

    def test_host_ui_reviews_each_file_and_waits_for_acceptance(self):
        from ui import dialogs as confirm_dialog
        from ui.panels import multiplayer_host_panel

        for choice in (False, True):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.stat_move(host)
                host.multiplayer_host_mode = True
                host.multiplayer_keys_dict = self.keys
                host.show_feedback = mock.Mock()
                host.refresh_all_maps = mock.Mock()
                move_path = self.write_move(directory, "stats.gd5move", "Leader", move)
                missing_path = os.path.join(directory, "missing.gd5move")
                completed = mock.Mock()
                with mock.patch.object(queries, "open_file_browser") as browser, \
                        mock.patch.object(confirm_dialog, "show_message") as message, \
                        mock.patch.object(confirm_dialog, "ask_yes_no") as ask, \
                        mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                    multiplayer_host_panel.load_multiplayer_moves(host, completed)
                    browser.call_args.kwargs["on_result"]([missing_path, move_path])
                    self.assertIn("missing.gd5move", message.call_args.args[1])
                    ask.assert_not_called()
                    message.call_args.kwargs["on_result"]()
                    self.assertIn("stats.gd5move", message.call_args.args[1])
                    self.assertIn("Leader", message.call_args.args[1])
                    self.assertIn("attack", message.call_args.args[1])
                    message.call_args.kwargs["on_result"]()
                    completed.assert_not_called()
                    ask.call_args.kwargs["on_result"](choice)
                completed.assert_called_once_with(choice)
                self.assertEqual(bool(host.submitted_moves), choice)
                self.assertEqual(host.refresh_all_maps.call_count, int(choice))

    def test_host_ui_rechecks_turn_and_permissions_after_confirmation(self):
        from ui import dialogs as confirm_dialog
        from ui.panels import multiplayer_host_panel

        for change in ("turn", "permission"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.stat_move(host)
                host.time_manager = Time()
                host.multiplayer_host_mode = True
                host.multiplayer_keys_dict = self.keys
                host.show_feedback = mock.Mock()
                path = self.write_move(directory, "stats.gd5move", "Leader", move)
                completed = mock.Mock()
                with mock.patch.object(queries, "open_file_browser") as browser, \
                        mock.patch.object(confirm_dialog, "show_message") as message, \
                        mock.patch.object(confirm_dialog, "ask_yes_no") as ask, \
                        mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                    multiplayer_host_panel.load_multiplayer_moves(host, completed)
                    browser.call_args.kwargs["on_result"]([path])
                    message.call_args.kwargs["on_result"]()
                    if change == "turn":
                        host.time_manager.total_turns += 1
                    else:
                        host.multiplayer_host_mode = False
                    ask.call_args.kwargs["on_result"](True)
                    if change == "turn":
                        self.assertIn("turn", message.call_args.args[1])
                        message.call_args.kwargs["on_result"]()
                completed.assert_called_once_with(False)
                self.assertEqual(host.submitted_moves, set())

    def test_nonhosts_cannot_open_move_import(self):
        from ui.panels import multiplayer_host_panel

        for flags in ({}, {"multiplayer_host_mode": True, "realtime_multiplayer": True}):
            host = Host()
            host.__dict__.update(flags)
            host.show_feedback = mock.Mock()
            completed = mock.Mock()
            with mock.patch.object(queries, "open_file_browser") as browser:
                multiplayer_host_panel.load_multiplayer_moves(host, completed)
            browser.assert_not_called()
            completed.assert_called_once_with(False)

    def test_unchanged_stats_legacy_units_and_changed_forms_need_no_override(self):
        for variation in ("unchanged", "legacy", "form"):
            with self.subTest(variation=variation), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.stat_move(host)
                unit = move["provinces"]["P1"]["units"][0]
                if variation == "unchanged":
                    unit["attack"] = host.map_data["home"]["units"][0]["attack"]
                elif variation == "legacy":
                    unit.pop("unit_id")
                else:
                    unit["type"] = "Another test ground unit"
                path = self.write_move(directory, "ordinary.gd5move", "Leader", move)
                summary = self.import_moves(host, [path])
                self.assertEqual(summary["loaded"], 1)
                self.assertEqual(summary["overridden"], 0)
                self.assertEqual(summary["rejections"], [])

    def test_import_discards_reserved_unassigned_entry_without_assigning_its_units(self):
        host = Host()
        unit = {"owner": "Leader", "type": "Infantry", "unit_id": "owned"}
        host.map_data = {"home": {"id": 1, "owner": "Leader", "units": [unit]}}
        player_data = self.player_data("Leader", host)
        player_data["nation_data"]["armies"] = [{
            "id": c.UNASSIGNED_ARMY_ID, "name": "Changed", "unit_ids": ["owned"],
            "symbol": "Star", "defense_area": [1]}]
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "leader.gd5move", "Leader", player_data)
            summary = self.import_moves(host, [path])
        self.assertEqual(summary["loaded"], 1)
        self.assertEqual(host.nation_data["Leader"]["armies"], [])
        self.assertEqual(queries.get_unassigned_army(
            "Leader", host.nation_data, host.map_data)["unit_ids"], ["owned"])

    def test_import_validates_release_types_and_host_owned_countdowns(self):
        for release_type in c.PUPPET_RELEASE_TYPES:
            with self.subTest(release_type=release_type):
                host = Host()
                host.map_data = {"land": {"id": 1, "owner": "Leader", "cores": ["Outsider"],
                                          "terrain": "plains", "units": []}}
                player_data = self.player_data("Leader", host, release_subjects=[
                    {"core_nation": "Outsider", "keep_cores": False, "release_type": release_type, "turns_left": 0}])
                with tempfile.TemporaryDirectory() as directory:
                    path = self.write_move(directory, "leader.gd5move", "Leader", player_data)
                    summary = self.import_moves(host, [path])
                self.assertEqual(summary["loaded"], 1)
                self.assertEqual(host.nation_data["Leader"]["release_puppet_queue"], [
                    {"core_nation": "Outsider", "keep_cores": False, "release_type": release_type, "turns_left": 1}])

    def test_import_rejects_invalid_foreign_duplicate_and_stale_release_requests(self):
        for country, entries, stale in (
                ("Leader", [None], False),
                ("Leader", [{"core_nation": "Outsider", "release_type": "Unknown"}], False),
                ("Leader", [{"core_nation": "Outsider"}, {"core_nation": "Outsider"}], False),
                ("Member", [{"core_nation": "Outsider"}], False),
                ("Leader", [{"core_nation": "Outsider"}], True)):
            with self.subTest(country=country, entries=entries, stale=stale):
                host = Host()
                host.map_data = {"land": {"id": 1, "owner": "Leader", "cores": ["Outsider"],
                                          "terrain": "plains", "units": []}}
                player_data = self.player_data(country, host, release_subjects=entries)
                if stale:
                    player_data["tournament_turn"] -= 1
                with tempfile.TemporaryDirectory() as directory:
                    path = self.write_move(directory, "move.gd5move", country, player_data)
                    summary = self.import_moves(host, [path])
                self.assertEqual(summary["rejected"], 1)
                self.assertEqual(summary["loaded"], 0)
                self.assertNotIn("release_puppet_queue", host.nation_data[country])

    def test_v46_release_requests_default_to_integrated(self):
        host = Host()
        host.map_data = {"land": {"id": 1, "owner": "Leader", "cores": ["Outsider"],
                                  "terrain": "plains", "units": []}}
        player_data = self.v46_move("Leader", host)
        player_data["release_subjects"] = [{"core_nation": "Outsider", "keep_cores": False}]
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "move.gd5move", "Leader", player_data)
            summary = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(summary["loaded"], 1)
        release = host.nation_data["Leader"]["release_puppet_queue"][0]
        self.assertEqual(release["release_type"], c.PUPPET_TYPE_INTEGRATED)
        self.assertEqual(release["turns_left"], 1)

    def previous_release_move(self, country_id, host):
        from data import migrations
        return self.v46_move(country_id, host, game_version=f"v{migrations.CURRENT_VERSION - 1}")

    def test_move_from_this_release_converts_without_host_review(self):
        host = Host()
        move = self.v46_move("Leader", host, release_subjects=[{"core_nation": "Outsider"}])
        host.map_data = {"land": {"id": 1, "owner": "Leader", "cores": ["Outsider"],
                                  "terrain": "plains", "units": []}}
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "this-release.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])
        self.assertEqual(summary["loaded"], 1, summary["rejections"])
        self.assertEqual(summary["converted"], 0)
        self.assertEqual(host.nation_data["Leader"]["release_puppet_queue"][0]["release_type"],
                         c.PUPPET_TYPE_INTEGRATED)

    def test_older_move_waits_for_host_conversion_then_validates_normally(self):
        host = Host()
        move = self.previous_release_move("Leader", host)
        move["nation_data"]["conscription_slider"] = 0.25
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "v46.gd5move", "Leader", move)
            before = copy.deepcopy(host.nation_data)
            held = self.import_moves(host, [path])
            self.assertEqual(held["loaded"], 0)
            self.assertEqual(held["rejections"][0]["override"], "version")
            self.assertEqual(host.nation_data, before)
            converted = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(converted["loaded"], 1, converted["rejections"])
        self.assertEqual(converted["converted"], 1)
        self.assertEqual(host.nation_data["Leader"]["conscription_slider"], 0.25)

    def test_converted_move_still_fails_normal_validation(self):
        host = Host()
        move = self.v46_move("Leader", host, tournament_turn=host.time_manager.total_turns + 1)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "v46.gd5move", "Leader", move)
            before = copy.deepcopy(host.nation_data)
            summary = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(summary["loaded"], 0)
        self.assertIn("turn", summary["rejections"][0]["reason"])
        self.assertEqual(host.nation_data, before)

    def test_moves_that_no_step_converts_are_refused_with_an_update_message(self):
        from data import migrations
        newer = {"game_version": f"v{migrations.CURRENT_VERSION + 1}"}
        too_old = {"game_version": f"v{migrations.CURRENT_VERSION - 2}"}
        for name, version in (("newer", newer), ("too old", too_old), ("before v46", None)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                host = Host()
                if version is None:
                    # Every v46 export wrote aircraft_orders. An older move is refused at conversion.
                    move = self.v46_move("Leader", host)
                    move.pop("aircraft_orders")
                else:
                    move = self.player_data("Leader", host, **version)
                path = self.write_move(directory, "move.gd5move", "Leader", move)
                before = copy.deepcopy(host.nation_data)
                summary = self.import_moves(host, [path], accept_older_versions=True)
                self.assertEqual(summary["loaded"], 0)
                self.assertFalse(summary["rejections"][0]["overridable"])
                self.assertIn("update", summary["rejections"][0]["reason"].lower())
                self.assertEqual(host.nation_data, before)

    def test_host_ui_converts_an_older_move_only_after_approval(self):
        from ui import dialogs as confirm_dialog
        from ui.panels import multiplayer_host_panel

        for choice in (False, True):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                host = Host()
                host.multiplayer_host_mode = True
                host.multiplayer_keys_dict = self.keys
                host.show_feedback = mock.Mock()
                host.refresh_all_maps = mock.Mock()
                path = self.write_move(directory, "older.gd5move", "Leader", self.previous_release_move("Leader", host))
                completed = mock.Mock()
                with mock.patch.object(queries, "open_file_browser") as browser, \
                        mock.patch.object(confirm_dialog, "show_message") as message, \
                        mock.patch.object(confirm_dialog, "ask_yes_no") as ask, \
                        mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                    multiplayer_host_panel.load_multiplayer_moves(host, completed)
                    browser.call_args.kwargs["on_result"]([path])
                    message.call_args.kwargs["on_result"]()
                    self.assertEqual(ask.call_args.args[0], "Convert older move?")
                    completed.assert_not_called()
                    ask.call_args.kwargs["on_result"](choice)
                completed.assert_called_once_with(choice)
                self.assertEqual(bool(host.submitted_moves), choice)

    def test_a_faction_exile_still_receives_a_tournament_move(self):
        host = Host()
        host.map_data = {"1": {"owner": "Leader"}}

        active = multiplayer_io.active_owners_of(host)

        self.assertIn("Leader", active)
        self.assertIn("Member", active)
        self.assertNotIn("Outsider", active)

    def test_faction_rename_keeps_every_member_together(self):
        host = Host()
        leader_move = self.player_data(
            "Leader", host,
            faction_renames=[{"old_name": "Old Pact", "new_name": "New Pact"}],
        )
        # This is what an ordinary member submitted from the still-old tournament
        # snapshot.  It must not undo the leader's rename when imported second.
        member_move = self.player_data("Member", host)

        with tempfile.TemporaryDirectory() as directory:
            paths = [
                self.write_move(directory, "leader.gd5move", "Leader", leader_move),
                self.write_move(directory, "member.gd5move", "Member", member_move),
            ]
            summary = self.import_moves(host, paths)

        self.assertEqual(summary["loaded"], 2)
        self.assertEqual(summary["faction_renames"], 1)
        self.assertEqual(host.nation_data["Leader"]["faction"], "New Pact")
        self.assertEqual(host.nation_data["Member"]["faction"], "New Pact")
        self.assertTrue(host.nation_data["Leader"]["is_faction_leader"])
        self.assertIn("New Pact", host.nation_data["FACTION_WAR_MAPS"])
        self.assertNotIn("Old Pact", host.nation_data["FACTION_WAR_MAPS"])

    def test_only_host_faction_leaders_can_send_imported_invitations(self):
        from tests.stub_map_screen import StubMapScreen
        from map_logic.diplomacy import diplomacy_processor

        for country_id in ("Leader", "Member"):
            with self.subTest(country_id=country_id):
                host = Host()
                move = self.player_data(country_id, host)
                # A player record cannot grant leadership on the host.
                move["nation_data"]["is_faction_leader"] = True
                move["nation_data"]["pending_diplomacy"] = {
                    "Outsider": {"action": "FACTION_INVITE", "turns": 0,
                                 "timer": 0, "message": "Please join."}}
                with tempfile.TemporaryDirectory() as directory:
                    path = self.write_move(directory, "invitation.gd5move", country_id, move)
                    summary = self.import_moves(host, [path])
                self.assertEqual(summary["loaded"], 1)
                game = StubMapScreen(["Leader", "Member", "Outsider"],
                                     human_players=["Leader", "Member", "Outsider"])
                for nation, data in host.nation_data.items():
                    game.nation_data.setdefault(nation, {}).update(data)
                diplomacy_processor._process_pass1_immediate_actions(game)
                self.assertEqual(bool(game.inbound("Outsider", country_id)), country_id == "Leader")
                if country_id == "Member":
                    self.assertFalse(game.nation_data[country_id]["is_faction_leader"])
                    self.assertEqual(game.pending_action(country_id, "Outsider"), "")

    def test_legacy_faction_rename_is_repaired_on_import(self):
        host = Host()
        # A v46 host without a session key exported moves without session or turn fields.
        legacy_data = {"nation_data": dict(host.nation_data["Leader"]), "provinces": {},
                       "aircraft_orders": [], "release_subjects": []}
        legacy_data["nation_data"]["faction"] = "New Pact"

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "legacy.gd5move", "Leader", legacy_data)
            summary = self.import_moves(host, [path], accept_older_versions=True)

        self.assertEqual(summary["loaded"], 1)
        self.assertEqual(summary["legacy"], 1)
        self.assertEqual(host.nation_data["Leader"]["faction"], "New Pact")
        self.assertEqual(host.nation_data["Member"]["faction"], "New Pact")

    def test_integrated_puppet_appearance_reaches_the_host(self):
        host = Host()
        appearance = {
            "name": "New Subject",
            "adjective": "Subjectian",
            "leader_name": "New Leader",
            "leader_title": "Governor",
            "flag_data": "flag-data",
            "portrait_data": "portrait-data",
            "color": [1, 2, 3],
        }
        move = self.player_data(
            "Leader", host,
            appearance_updates=[{"country_id": "Subject", "appearance": appearance}],
        )

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "appearance.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])

        self.assertEqual(summary["appearance_updates"], 1)
        for key, value in appearance.items():
            self.assertEqual(host.nation_data["Subject"][key], value)
        self.assertEqual(host.nation_colors["Subject"], (1, 2, 3))

    def test_rejects_wrong_turn_and_duplicate_submissions(self):
        host = Host()
        valid = self.player_data("Leader", host)
        wrong_turn = self.player_data("Member", host, tournament_turn=3)
        duplicate = self.player_data("Leader", host)

        with tempfile.TemporaryDirectory() as directory:
            paths = [
                self.write_move(directory, "valid.gd5move", "Leader", valid),
                self.write_move(directory, "wrong-turn.gd5move", "Member", wrong_turn),
                self.write_move(directory, "duplicate.gd5move", "Leader", duplicate),
            ]
            summary = self.import_moves(host, paths)

        self.assertEqual(summary["loaded"], 1)
        self.assertEqual(summary["rejected"], 2)
        self.assertEqual(host.submitted_moves, {"Leader"})

    def test_export_records_session_turn_and_pending_shared_updates(self):
        host = Host()
        host.player_country = "Leader"
        host.active_players = ["Leader"]
        host.current_player_index = 0
        host.loop_map = False
        host.scenario_settings = {}
        host.script_variables = []
        host.default_research = None
        host.multiplayer_pending_faction_renames = [
            {"old_name": "Old Pact", "new_name": "New Pact"}]
        host.multiplayer_pending_appearance_updates = {
            "Subject": {"name": "New Subject", "color": [1, 2, 3]}}

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.gd5move")
            multiplayer_io.export_move_file(host, path, self.keys["Leader"])
            with open(path, "r") as file:
                payload = json.load(file)

        data = multiplayer_io.decrypt_dict(payload["data"], self.keys["Leader"])
        self.assertEqual(data["tournament_session"], "test-session")
        self.assertEqual(data["tournament_turn"], 4)
        self.assertEqual(data["game_version"], c.GAME_VERSION)
        self.assertEqual(data["faction_renames"][0]["new_name"], "New Pact")
        self.assertEqual(data["appearance_updates"][0]["country_id"], "Subject")

    def test_export_includes_empty_unit_snapshot_and_puppet_siphons(self):
        host = Host()
        host.player_country = "Leader"
        host.active_players = ["Leader"]
        host.current_player_index = 0
        host.loop_map = False
        host.scenario_settings = {}
        host.script_variables = []
        host.default_research = None
        host.nation_data["Subject"]["siphon_rates"] = {
            "manpower": 0.25, "materials": 0.5, "fuel": 0.5}

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.gd5move")
            multiplayer_io.export_move_file(host, path, self.keys["Leader"])
            with open(path, "r") as file:
                payload = json.load(file)

        data = multiplayer_io.decrypt_dict(payload["data"], self.keys["Leader"])
        self.assertTrue(data["unit_snapshot"])
        self.assertEqual(data["puppet_siphon_updates"], [{
            "country_id": "Subject",
            "siphon_rates": {"manpower": 0.25, "materials": 0.5, "fuel": 0.5},
        }])

    def test_empty_unit_snapshot_removes_all_player_units(self):
        host = Host()
        host.map_data = {
            (1, 1): {"id": 1, "json_key": "P1", "units": [
                {"owner": "Leader", "type": "Infantry"},
                {"owner": "Member", "type": "Infantry"},
            ]},
        }
        move = self.player_data("Leader", host, unit_snapshot=True)

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "empty-army.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])

        self.assertEqual(summary["loaded"], 1)
        self.assertEqual(host.map_data[(1, 1)]["units"], [
            {"owner": "Member", "type": "Infantry"}])
        self.assertEqual(host.syncs, 1)

    def test_integrated_puppet_siphons_are_host_validated(self):
        host = Host()
        move = self.player_data("Leader", host, puppet_siphon_updates=[{
            "country_id": "Subject",
            "siphon_rates": {"manpower": 0.2, "materials": 0.4, "fuel": 0.5},
        }, {
            # A controller cannot alter a country it does not integrate.
            "country_id": "Outsider",
            "siphon_rates": {"manpower": 1, "materials": 1, "fuel": 1},
        }])

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "siphons.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])

        self.assertEqual(summary["puppet_siphon_updates"], 1)
        self.assertEqual(host.nation_data["Subject"]["siphon_rates"], {
            "manpower": 0.2, "materials": 0.4, "fuel": 0.5})
        self.assertNotIn("siphon_rates", host.nation_data["Outsider"])

    def test_policy_activation_round_trips_without_trusting_player_timers(self):
        from map_logic import politics

        host = Host()
        host.nation_data["Leader"]["political_value"] = -3
        move = self.player_data("Leader", host)
        move["nation_data"][politics.POLICY_KEY] = {
            "research_subsidies": {"status": politics.POLICY_ACTIVATING,
                                   "turns_remaining": 999},
        }

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "policy.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])

        state = politics.policy_state(host.nation_data, "Leader", "research_subsidies")
        self.assertEqual(summary["loaded"], 1)
        self.assertEqual(state["status"], politics.POLICY_ACTIVATING)
        self.assertEqual(state["turns_remaining"], politics.POLICY_ACTIVATION_TURNS)

    def test_tournament_round_trip_and_malformed_key_entry(self):
        host = Host()
        host.player_country = "Leader"
        host.active_players = ["Leader"]
        host.current_player_index = 0
        host.loop_map = False
        host.scenario_settings = {}
        host.script_variables = []
        host.default_research = None

        with tempfile.TemporaryDirectory() as directory:
            tour_path = os.path.join(directory, "turn.gd5tour")
            with mock.patch.object(multiplayer_io.c, "TOURNAMENT_SAVES_DIR", directory), \
                    mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                multiplayer_io.export_tournament(host, tour_path, "host-key", self.keys)
                loaded = multiplayer_io.load_tournament(tour_path, "host-key")

            self.assertTrue(loaded[0])
            self.assertEqual(loaded[1], "HOST")
            self.assertEqual(loaded[6], "test-session")

            malformed_path = os.path.join(directory, "malformed.gd5tour")
            with open(malformed_path, "w") as file:
                json.dump({"verification_table": {
                    multiplayer_io.hash_key("host-key"): []}}, file)
            malformed = multiplayer_io.load_tournament(malformed_path, "host-key")

        self.assertFalse(malformed[0])
        self.assertEqual(malformed[-1], "Invalid key")

    def test_public_spectator_key_loads_as_a_distinct_fog_limited_role(self):
        host = Host()
        host.player_country = "Leader"
        host.active_players = ["Leader"]
        host.current_player_index = 0
        host.loop_map = False
        host.scenario_settings = {}
        host.script_variables = []
        host.default_research = None
        host.map_data = {
            (1, 1): {"id": 1, "json_key": "P1", "owner": "Leader", "units": [
                {"owner": "Leader", "type": "Infantry", "order": {"type": "MOVE"}},
            ]},
        }

        with tempfile.TemporaryDirectory() as directory:
            tour_path = os.path.join(directory, "turn.gd5tour")
            with mock.patch.object(multiplayer_io.c, "TOURNAMENT_SAVES_DIR", directory), \
                    mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                multiplayer_io.export_tournament(host, tour_path, "host-key", self.keys)
                with open(tour_path, "r") as file:
                    payload = json.load(file)
                loaded = multiplayer_io.load_tournament(tour_path, "Spectator")

        self.assertTrue(loaded[0])
        self.assertEqual(loaded[1], c.TOURNAMENT_SPECTATOR_ROLE)
        self.assertIsNone(loaded[2])
        self.assertEqual(loaded[4], {})
        spectator_entry = payload["verification_table"][
            multiplayer_io.hash_key(c.TOURNAMENT_SPECTATOR_KEY)]
        self.assertNotIn("sk", multiplayer_io.decrypt_dict(
            spectator_entry["enc_session"], c.TOURNAMENT_SPECTATOR_KEY))
        spectator_save = multiplayer_io.decrypt_dict(
            payload["spectator_game_data"], c.TOURNAMENT_SPECTATOR_KEY)
        self.assertEqual(spectator_save["nation_data"]["Leader"]["materials"], 0)
        self.assertNotIn("order", spectator_save["provinces"]["P1"]["units"][0])

        spectator_map = Host()
        spectator_map.map_data = host.map_data
        multiplayer_io.strip_sensitive_data_for_tournament_spectator(spectator_map)
        self.assertEqual(spectator_map.player_country, c.TOURNAMENT_SPECTATOR)
        self.assertEqual(spectator_map.active_players, [c.TOURNAMENT_SPECTATOR])
        self.assertEqual(spectator_map.nation_data["Leader"]["inbox"], [])
        self.assertNotIn("order", spectator_map.map_data[(1, 1)]["units"][0])

        visibility_screen = SimpleNamespace(
            player_country=c.TOURNAMENT_SPECTATOR,
            map_data={}, nation_data=spectator_map.nation_data,
            id_to_province={})
        self.assertEqual(multiplayer_io.queries.get_visible_provinces(visibility_screen),
                         (set(), set()))
        self.assertFalse(multiplayer_io.queries.is_unit_visible_to(
            {"type": "Submarine"}, c.TOURNAMENT_SPECTATOR, {}, spectator_map.nation_data))

    def test_spectator_is_reserved_and_cannot_be_a_master_key(self):
        host = Host()
        with tempfile.TemporaryDirectory() as directory, \
                self.assertRaisesRegex(ValueError, "reserved"):
            multiplayer_io.export_tournament(
                host, os.path.join(directory, "turn.gd5tour"), "  spectator  ", self.keys)

    def test_decrypt_rejects_bad_input_without_hiding_internal_errors(self):
        self.assertIsNone(multiplayer_io.decrypt_dict("not an encrypted payload", "key"))
        with mock.patch.object(multiplayer_io, "generate_fernet_key_from_password",
                               side_effect=RuntimeError("broken implementation")):
            with self.assertRaisesRegex(RuntimeError, "broken implementation"):
                multiplayer_io.decrypt_dict("YWJjZA==:token", "key")


if __name__ == "__main__":
    unittest.main()
