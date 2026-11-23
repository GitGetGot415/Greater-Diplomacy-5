"""Cover tournament intent exports and host validation of current and older moves."""

import json
import copy
import os
import tempfile
import unittest
from unittest import mock


import data.constants as c
from tests.stub_map_screen import fill_state_defaults, map_double, synchronous_progress
from tests.research_fixtures import research_lock_cases
from tests.migration_fixtures import malformed_records
from tests.tournament_fixtures import fast_tournament_crypto
from data import queries
from data.runtime_rules import RuntimeRules
from ui.dialogs import pickers
from data.multiplayer.tournament import files as tournament_files
from map_logic import politics
from map_logic.actions import production_actions


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
        fill_state_defaults(self)

    def sync_units_to_data(self):
        self.syncs += 1


@fast_tournament_crypto()
class TournamentMoveTests(unittest.TestCase):
    keys = {"Leader": "leader-key", "Member": "member-key"}

    def write_move(self, directory, file_name, country_id, player_data):
        path = os.path.join(directory, file_name)
        payload = {
            "country_id": country_id,
            "hash": tournament_files.hash_key(self.keys[country_id]),
            "data": tournament_files.encrypt_dict(player_data, self.keys[country_id]),
        }
        with open(path, "w") as file:
            json.dump(payload, file)
        return path

    def import_moves(self, host, paths, **options):
        with mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
            return tournament_files.load_move_files(host, paths, self.keys, **options)

    def player_data(self, host, **extra):
        result = {
            "player_intents": [],
            "game_version": c.GAME_VERSION,
            "tournament_session": host.multiplayer_session_key,
            "tournament_turn": host.time_manager.total_turns,
        }
        result.update(extra)
        return result

    def test_battle_editor_assignments_survive_host_import_and_reject_bad_moves(self):
        for variant in ("valid", "unauthorized", "malformed", "stale"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as directory:
                host = Host()
                host.nation_data["Leader"]["at_war_with"] = ["Outsider"]
                host.nation_data["Outsider"]["at_war_with"] = ["Leader"]
                units = [{"unit_id": identity, "owner": owner, "type": "Battle Fixture"}
                         for identity, owner in (("reserve", "Leader"), ("front", "Leader"),
                                                 ("enemy", "Outsider"))]
                province = {"id": 1, "json_key": "battle", "owner": "Leader",
                            "terrain": "plains", "units": units}
                host.map_data = {"battle": province}
                host.id_to_province = {1: province}
                commands = [
                    {"type": "unit_order", "province_id": 1, "unit_id": "reserve",
                     "order": None, "lane_target": "Outsider", "combat_stance": None},
                    {"type": "unit_order", "province_id": 1, "unit_id": "front",
                     "order": None, "lane_target": None, "combat_stance": "RESERVE"}]
                if variant == "unauthorized":
                    commands[0]["unit_id"] = "enemy"
                elif variant == "malformed":
                    commands[0]["lane_target"] = ["Outsider"]
                move = self.player_data(host, player_intents=commands)
                if variant == "stale":
                    move["tournament_turn"] += 1
                before = copy.deepcopy(units)
                path = self.write_move(directory, "battle.gd5move", "Leader", move)
                result = self.import_moves(host, [path])
                if variant == "valid":
                    self.assertEqual(result["loaded"], 1, result["rejections"])
                    self.assertEqual(units[0]["lane_target"], "Outsider")
                    self.assertEqual(units[1]["combat_stance"], "RESERVE")
                    self.assertEqual(units[2], before[2])
                else:
                    self.assertEqual(result["loaded"], 0)
                    self.assertEqual(units, before)

    def test_forward_and_text_move_preserve_host_message_and_reject_invalid_references(self):
        from map_logic.diplomacy import diplomacy_messages as dm

        for compatibility_projection in (False, True):
            for mode in ("valid", "missing_source", "malformed_source", "stale", "wrong_key"):
                with self.subTest(compatibility_projection=compatibility_projection, mode=mode), tempfile.TemporaryDirectory() as directory:
                    host = Host()
                    source = {"message_id": "received-id", "sender": "Member", "content": "Original text", "read": False}
                    host.nation_data["Leader"]["inbox"] = [source]
                    local = copy.deepcopy(host.nation_data)
                    dm.queue_text_message(local, "Leader", "Outsider", "Ordinary text")
                    dm.queue_forwarded_message(local, "Leader", "Outsider", "Leader", source)
                    request = local["Leader"]["pending_diplomacy"]["Outsider"]
                    request["forwarded_message"]["content"] = "Forged text"
                    request["forwarded_source"] = "Member"
                    if mode == "missing_source":
                        request["forwarded_message"]["message_id"] = "not-received"
                    elif mode == "malformed_source":
                        request["forwarded_message"] = None
                    move = self.player_data(host)
                    if compatibility_projection:
                        move["nation_data"] = local["Leader"]
                    move["player_intents"] = [{"type": "country_diplomacy",
                        "pending": local["Leader"]["pending_diplomacy"], "responses": {},
                        "draft_lists": local["Leader"]["draft_lists"]}]
                    if mode == "stale":
                        move["tournament_turn"] -= 1
                    path = self.write_move(directory, "forward.gd5move", "Leader", move)
                    if mode == "wrong_key":
                        with open(path) as stream:
                            envelope = json.load(stream)
                        envelope["hash"] = tournament_files.hash_key("incorrect-key")
                        with open(path, "w") as stream:
                            json.dump(envelope, stream)
                    summary = self.import_moves(host, [path])
                    self.assertEqual(summary["loaded"], int(mode == "valid"), summary)
                    if mode == "valid":
                        pending = dm.get_pending(host.nation_data, "Leader", "Outsider")
                        self.assertEqual(pending["forwarded_message"], source)
                        self.assertEqual(pending["forwarded_source"], "Leader")
                        self.assertEqual(host.nation_data["Leader"]["draft_lists"], {"Outsider": ["Ordinary text"]})
                    else:
                        self.assertEqual(dm.get_pending(host.nation_data, "Leader", "Outsider"), {})

    def test_forward_after_previous_turn_preserves_reply_record_in_tournament_moves(self):
        from map_logic.actions.player_actions import collect_map_commands
        from map_logic.diplomacy import diplomacy_messages as dm

        for compatibility_projection in (False, True):
            for mode in ("valid", "missing_source", "stale_reference"):
                with self.subTest(compatibility_projection=compatibility_projection, mode=mode), tempfile.TemporaryDirectory() as directory:
                    host = Host()
                    source = {"message_id": "received-id", "sender": "Member", "content": "Original text", "read": False}
                    host.nation_data["Leader"]["inbox"] = [source]
                    previous = copy.deepcopy(dm.set_pending(host.nation_data, "Leader", "Outsider", "MSG:Previous turn", turns=1))
                    local = map_double(map_data={}, id_to_province={}, nation_colors={}, nation_data=copy.deepcopy(host.nation_data))
                    dm.queue_forwarded_message(local.nation_data, "Leader", "Outsider", "Leader", source)
                    command = next(item for item in collect_map_commands(local, "Leader") if item["type"] == "country_diplomacy")
                    request = dm.get_pending(local.nation_data, "Leader", "Outsider")
                    if mode == "missing_source":
                        request["forwarded_message"]["message_id"] = "not-received"
                        command["pending"]["Outsider"]["forwarded_message"]["message_id"] = "not-received"
                    elif mode == "stale_reference":
                        request["request_id"] = "expired-request"
                        command["pending"]["Outsider"]["request_id"] = "expired-request"
                    move = self.player_data(host)
                    if compatibility_projection:
                        move["nation_data"] = local.nation_data["Leader"]
                    move["player_intents"] = [command]
                    path = self.write_move(directory, "forward.gd5move", "Leader", move)
                    summary = self.import_moves(host, [path])
                    self.assertEqual(summary["loaded"], int(mode == "valid"), summary)
                    pending = dm.get_pending(host.nation_data, "Leader", "Outsider")
                    expected = dict(previous, forwarded_message=source, forwarded_source="Leader") if mode == "valid" else previous
                    self.assertEqual(pending, expected)

    def test_text_follow_up_preserves_sent_message_and_forward_in_tournament_moves(self):
        from map_logic.actions.player_actions import collect_map_commands
        from map_logic.diplomacy import diplomacy_messages as dm

        for compatibility_projection in (False, True):
            for mode in ("valid", "stale", "wrong_key", "duplicate"):
                with self.subTest(compatibility_projection=compatibility_projection, mode=mode), tempfile.TemporaryDirectory() as directory:
                    host = Host()
                    source = {"message_id": "source-id", "sender": "Member", "content": "Forward this", "read": False}
                    host.nation_data["Leader"]["inbox"] = [source]
                    previous = copy.deepcopy(dm.set_pending(host.nation_data, "Leader", "Outsider", "MSG:Previous turn", turns=1))
                    local = map_double(map_data={}, id_to_province={}, nation_colors={}, nation_data=copy.deepcopy(host.nation_data))
                    dm.queue_forwarded_message(local.nation_data, "Leader", "Outsider", "Leader", source)
                    dm.queue_text_message(local.nation_data, "Leader", "Outsider", "Follow-up")
                    move = self.player_data(host)
                    if compatibility_projection:
                        move["nation_data"] = local.nation_data["Leader"]
                    move["player_intents"] = [item for item in collect_map_commands(local, "Leader") if item["type"] == "country_diplomacy"]
                    if mode == "stale":
                        move["tournament_turn"] -= 1
                    path = self.write_move(directory, "follow_up.gd5move", "Leader", move)
                    if mode == "wrong_key":
                        with open(path) as stream:
                            payload = json.load(stream)
                        payload["hash"] = tournament_files.hash_key("wrong-key")
                        with open(path, "w") as stream:
                            json.dump(payload, stream)
                    summary = self.import_moves(host, [path])
                    allowed = mode in ("valid", "duplicate")
                    self.assertEqual(summary["loaded"], int(allowed), summary)
                    expected = dict(previous, forwarded_message=source, forwarded_source="Leader") if allowed else previous
                    self.assertEqual(dm.get_pending(host.nation_data, "Leader", "Outsider"), expected)
                    if allowed:
                        self.assertEqual(host.nation_data["Leader"]["draft_lists"], {"Outsider": ["Follow-up"]})
                    if mode == "duplicate":
                        duplicate = self.import_moves(host, [path], loaded_countries=summary["loaded_countries"])
                        self.assertEqual(duplicate["loaded"], 0, duplicate)
                        self.assertEqual(dm.get_pending(host.nation_data, "Leader", "Outsider"), expected)

    def test_factory_output_research_intents_require_host_prerequisites_and_current_turn(self):
        tree = queries.get_tech_tree()
        cases = research_lock_cases(tree)
        # These hosts have the same scenario settings and separate mutable state.
        rules = RuntimeRules()
        for tech, locked, unlocked in cases:
            for mode in ("valid", "locked", "malformed", "stale", "wrong_key"):
                with self.subTest(tech=tech, mode=mode), tempfile.TemporaryDirectory() as directory:
                    host = Host()
                    host.runtime_rules = rules
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
                        payload["hash"] = tournament_files.hash_key(self.keys["Member"])
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

    def test_production_uses_shared_costs_and_rejects_cumulative_overspend(self):
        from map_logic.actions import production_actions
        from tests.research_fixtures import fixture_metadata
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
                host.id_to_province = {province["id"]: province for province in host.map_data.values()}
                with mock.patch.object(queries, "get_unit_library", return_value=library):
                    expected = [production_actions.prepare_production(
                        host, "Leader", province, "unit_queue", {"unit_type": "Fixture recruit"}).order
                        for province in host.map_data.values()]
                    items = expected if complete else [{"unit_type": "Fixture recruit"} for _ in expected]
                    commands = [{"type": "province_queue", "province_id": number, "queue": "unit_queue", "items": [item]}
                                for number, item in enumerate(items, start=1)]
                    move = self.player_data(host, player_intents=commands)
                    before = copy.deepcopy((host.nation_data, host.map_data))
                    path = self.write_move(directory, "production.gd5move", "Leader", move)
                    result = self.import_moves(host, [path])
                self.assertEqual(result["loaded"], int(affordable), result["rejections"])
                if affordable:
                    for province, order in zip(host.map_data.values(), expected):
                        self.assertEqual(province["unit_queue"], [order])
                    self.assertEqual(host.nation_data["Leader"]["materials"], 0)
                else:
                    self.assertEqual((host.nation_data, host.map_data), before)
                    self.assertFalse(result["rejections"][0]["overridable"])

    def coring_host(self):
        host = Host()
        host.nation_data["Leader"]["manpower"] = 10 ** 6
        host.map_data = {str(number): {"id": number, "json_key": f"P{number}", "owner": "Leader",
                                       "cores": cores, "neighbors": neighbors, "units": [],
                                       "building_queue": [], "unit_queue": []}
                         for number, neighbors, cores in ((1, [2], ["Leader"]), (2, [1], []), (3, [], []))}
        host.id_to_province = {province["id"]: province for province in host.map_data.values()}
        return host

    def test_move_enforces_the_coring_rule(self):
        for province_id, legal in ((2, True), (3, False)):
            with self.subTest(province_id=province_id), tempfile.TemporaryDirectory() as directory:
                host = self.coring_host()
                before = copy.deepcopy(host.map_data)
                command = {"type": "province_queue", "province_id": province_id, "queue": "building_queue",
                           "items": [{"order_type": "CORE"}]}
                move = self.player_data(host, player_intents=[command])
                path = self.write_move(directory, "core.gd5move", "Leader", move)
                result = self.import_moves(host, [path])
                self.assertEqual(result["loaded"], int(legal), result["rejections"])
                if legal:
                    queue = host.id_to_province[province_id]["building_queue"]
                    self.assertEqual([item["order_type"] for item in queue], ["CORE"])
                else:
                    rejection = result["rejections"][0]
                    self.assertIn("coast", rejection["reason"])
                    self.assertFalse(rejection["overridable"])
                    self.assertEqual(host.map_data, before)

    def test_wartime_trade_intent_is_imported_by_host(self):
        with tempfile.TemporaryDirectory() as directory:
            host = Host()
            host.nation_data["Leader"]["at_war_with"] = ["Outsider"]
            host.nation_data["Outsider"]["at_war_with"] = ["Leader"]
            command = {"type": "country_diplomacy", "pending": {
                "Outsider": {"action": "TRADE", "message": "", "parameters": {"give_materials": 30}}}}
            move = self.player_data(host, player_intents=[command])
            path = self.write_move(directory, "trade.gd5move", "Leader", move)
            result = self.import_moves(host, [path])
            self.assertEqual(result["loaded"], 1, result["rejections"])
            request = host.nation_data["Leader"]["pending_diplomacy"]["Outsider"]
            self.assertEqual(request["action"], "TRADE")
            self.assertEqual(request["parameters"], {"give_materials": 30})
            self.assertEqual(host.nation_data["Leader"]["at_war_with"], ["Outsider"])

    def test_response_references_are_checked_before_applying_intents(self):
        from map_logic.diplomacy import diplomacy_messages
        for correct in (True, False):
            with self.subTest(correct=correct), tempfile.TemporaryDirectory() as directory:
                host = Host()
                request = diplomacy_messages.set_pending(host.nation_data, "Member", "Leader", "TRADE", turns=1)
                reply = {"action": "TRADE", "verdict": "ACCEPT", "message": "",
                         "request_id": request["request_id"] if correct else "cancelled-request"}
                move = self.player_data(host, player_intents=[
                    {"type": "country_diplomacy", "responses": {"Member": reply}}])
                before = copy.deepcopy(host.nation_data)
                path = self.write_move(directory, "reply.gd5move", "Leader", move)
                result = self.import_moves(host, [path])
                self.assertEqual(result["loaded"], int(correct))
                if not correct:
                    self.assertEqual(host.nation_data, before)
                    self.assertFalse(result["rejections"][0]["overridable"])

    def test_paid_older_queue_keeps_countdown_without_recharging_or_recruitment_checks(self):
        host = Host()
        paid = {"unit_type": "Retired fixture unit", "days_remaining": 2 * c.DEFAULT_DAYS_PER_TURN,
                "refund": {"cost_materials": 7}, "custom_field": {"keep": True}}
        # The older intent stores days. The host's loaded queue already uses turns.
        converted = {key: value for key, value in paid.items() if key != "days_remaining"}
        converted["turns_remaining"] = 2
        host.map_data = {"home": {"id": 1, "json_key": "P1", "owner": "Leader", "units": [],
                                  "unit_queue": [copy.deepcopy(converted)]}}
        host.id_to_province = {1: host.map_data["home"]}
        command = {"type": "province_queue", "province_id": 1, "queue": "unit_queue", "items": [copy.deepcopy(paid)]}
        move = self.previous_release_move(host, player_intents=[command],
                                          provinces={"P1": {"unit_queue": [paid]}})
        before = copy.deepcopy(host.nation_data["Leader"])
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "paid.gd5move", "Leader", move)
            result = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(result["loaded"], 1, result["rejections"])
        self.assertEqual(host.map_data["home"]["unit_queue"], [converted])
        for resource in c.ECON_RESOURCE_KEYS:
            self.assertEqual(host.nation_data["Leader"][resource], before[resource])

    def test_ratification_defaults_keep_the_host_round_and_reject_explicit_stale_ids(self):
        for answer in (None, {"verdict": "RATIFY"}, {"verdict": "RATIFY", "treaty_id": "expired"}):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory:
                host = Host()
                asked = {"treaty_id": "current", "signatory": "Member", "opponent": "Outsider",
                         "turns": 1, "deal": {"fixture": "authoritative"}}
                host.nation_data["Leader"]["pending_ratification"] = copy.deepcopy(asked)
                intents = [{"type": "ratification_response", **answer}] if answer is not None else []
                move = self.player_data(host, player_intents=intents)
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
        command = {"type": "country_preferences", "conscription_slider": 0.25}
        move = self.player_data(host, player_intents=[command])
        before_member = copy.deepcopy(host.nation_data["Member"])
        expected = queries.get_conscription_damage_bonus(command)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "conscription.gd5move", "Leader", move)
            result = self.import_moves(host, [path])
        self.assertEqual(result["loaded"], 1)
        self.assertEqual(host.nation_data["Leader"]["conscription_slider"], 0.25)
        self.assertEqual(queries.get_conscription_damage_bonus(host.nation_data["Leader"]), expected)
        self.assertEqual(host.nation_data["Member"], before_member)

    def test_older_move_cannot_restore_the_removed_direct_alliance_field(self):
        host = Host()
        projection = dict(host.nation_data["Leader"], allied_with=["Outsider"])
        move = self.previous_release_move(host, nation_data=projection)
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
                        json.dumps({"country_id": "Leader", "hash": tournament_files.hash_key(self.keys["Leader"]),
                                    "data": "broken"})]
            paths = [os.path.join(directory, "missing.gd5move")]
            for index, payload in enumerate(payloads):
                path = os.path.join(directory, f"bad-{index}.gd5move")
                with open(path, "w") as file:
                    file.write(payload)
                paths.append(path)
            summary = self.import_moves(host, paths)
        self.assertEqual(summary["rejected"], len(paths))
        self.assertEqual([item["file_path"] for item in summary["rejections"]], paths)
        self.assertTrue(all(item["reason"] and not item["overridable"] for item in summary["rejections"]))
        self.assertEqual(summary["loaded"], 0)
        self.assertEqual(host.submitted_moves, set())

    def test_snapshot_formats_are_rejected_without_conversion_or_partial_changes(self):
        for shape in ("country_only", "v46_snapshot", "current_stamp"):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.previous_release_move(host)
                del move["player_intents"]
                country = dict(host.nation_data["Leader"], faction="Untrusted")
                if shape == "country_only":
                    move = country
                else:
                    move.update(nation_data=country, provinces={})
                    if shape == "current_stamp":
                        move["game_version"] = c.GAME_VERSION
                before = copy.deepcopy((host.nation_data, host.map_data))
                path = self.write_move(directory, "snapshot.gd5move", "Leader", move)
                for approve in (False, True):
                    summary = self.import_moves(host, [path], accept_older_versions=approve)
                    self.assertEqual(summary["loaded"], 0)
                    self.assertFalse(summary["rejections"][0]["overridable"])
                    self.assertIn("Snapshot-format", summary["rejections"][0]["reason"])
                    self.assertEqual((host.nation_data, host.map_data), before)
                    self.assertEqual(host.submitted_moves, set())

    def test_malformed_move_does_not_stop_a_valid_move_in_the_same_batch(self):
        for payload in ({"provinces": [{}]}, {"player_intents": None}):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                host = Host()
                before = copy.deepcopy(host.nation_data["Leader"])
                bad = self.player_data(host, **payload)
                good = self.player_data(host)
                paths = [self.write_move(directory, "bad.gd5move", "Leader", bad),
                         self.write_move(directory, "good.gd5move", "Member", good)]
                summary = self.import_moves(host, paths)
                self.assertEqual(summary["rejected"], 1, summary)
                self.assertEqual(summary["loaded_countries"], ["Member"], summary)
                self.assertEqual(host.nation_data["Leader"], before)
                self.assertEqual(host.submitted_moves, {"Member"})

    def test_malformed_known_fields_reject_one_older_intent_move_and_continue_the_batch(self):
        for field, country, province in malformed_records():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                host = Host()
                before_country = copy.deepcopy(host.nation_data["Leader"])
                before_map = copy.deepcopy(host.map_data)
                bad = self.previous_release_move(host, provinces={"P1": copy.deepcopy(province)},
                                                 nation_data={**host.nation_data["Leader"], **copy.deepcopy(country)})
                good = self.player_data(host)
                paths = [self.write_move(directory, "bad.gd5move", "Leader", bad),
                         self.write_move(directory, "good.gd5move", "Member", good)]
                result = self.import_moves(host, paths, accept_older_versions=True)
                self.assertEqual((result["rejected"], result["loaded_countries"]), (1, ["Member"]), result)
                self.assertIn(field, result["rejections"][0]["reason"])
                self.assertFalse(result["rejections"][0]["overridable"])
                self.assertEqual(host.nation_data["Leader"], before_country)
                self.assertEqual(host.map_data, before_map)
                self.assertEqual(host.submitted_moves, {"Member"})

    def test_duplicate_during_host_review_cannot_be_overridden(self):
        host = Host()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "move.gd5move", "Leader", self.player_data(host))
            initial = self.import_moves(host, [path])
            self.assertEqual(initial["loaded"], 1)
            summary = self.import_moves(host, [path], accept_older_versions=True,
                                        loaded_countries=initial["loaded_countries"])
        self.assertEqual(summary["rejected"], 1)
        self.assertFalse(summary["rejections"][0]["overridable"])
        self.assertIn("already", summary["rejections"][0]["reason"])

    def test_host_sets_administrative_duration_and_rejects_disabled_orders(self):
        setting = queries.ADMINISTRATIVE_ACTIONS["CORE"][0]
        for disabled in (False, True):
            with self.subTest(disabled=disabled), tempfile.TemporaryDirectory() as directory:
                host = self.coring_host()
                host.scenario_settings = {"administrative_turn_overrides": {setting: c.MIN_CORE_CONSTRUCTION_TURNS + 1},
                                          "administrative_disabled": [setting] if disabled else [],
                                          "use_default_other": False}
                command = {"type": "province_queue", "province_id": 2, "queue": "building_queue",
                           "items": [{"order_type": "CORE", "turns_remaining": 8}]}
                move = self.player_data(host, player_intents=[command])
                path = self.write_move(directory, "duration.gd5move", "Leader", move)
                summary = self.import_moves(host, [path])
                self.assertEqual(summary["loaded"], int(not disabled), summary["rejections"])
                queue = host.id_to_province[2]["building_queue"]
                if disabled:
                    self.assertFalse(summary["rejections"][0]["overridable"])
                    self.assertEqual(queue, [])
                else:
                    self.assertEqual(queue[0]["turns_remaining"], c.MIN_CORE_CONSTRUCTION_TURNS + 1)

    def test_host_ui_reviews_each_file_and_waits_for_acceptance(self):
        from ui import dialogs 
        from ui.panels import multiplayer_host_panel

        for choice in (False, True):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.previous_release_move(host)
                host.multiplayer_host_mode = True
                host.multiplayer_keys_dict = self.keys
                host.show_feedback = mock.Mock()
                host.refresh_all_maps = mock.Mock()
                move_path = self.write_move(directory, "older.gd5move", "Leader", move)
                missing_path = os.path.join(directory, "missing.gd5move")
                completed = mock.Mock()
                with mock.patch.object(pickers, "open_file_browser") as browser, \
                        mock.patch.object(dialogs, "show_message") as message, \
                        mock.patch.object(dialogs, "ask_yes_no") as ask, \
                        mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
                    multiplayer_host_panel.load_multiplayer_moves(host, completed)
                    browser.call_args.kwargs["on_result"]([missing_path, move_path])
                    self.assertIn("missing.gd5move", message.call_args.args[1])
                    ask.assert_not_called()
                    message.call_args.kwargs["on_result"]()
                    self.assertIn("older.gd5move", message.call_args.args[1])
                    self.assertIn("Leader", message.call_args.args[1])
                    self.assertIn("host can convert", message.call_args.args[1])
                    message.call_args.kwargs["on_result"]()
                    completed.assert_not_called()
                    ask.call_args.kwargs["on_result"](choice)
                completed.assert_called_once_with(choice)
                self.assertEqual(bool(host.submitted_moves), choice)
                self.assertEqual(host.refresh_all_maps.call_count, int(choice))

    def test_host_ui_rechecks_turn_and_permissions_after_confirmation(self):
        from ui import dialogs 
        from ui.panels import multiplayer_host_panel

        for change in ("turn", "permission"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                host = Host()
                move = self.previous_release_move(host)
                host.time_manager = Time()
                host.multiplayer_host_mode = True
                host.multiplayer_keys_dict = self.keys
                host.show_feedback = mock.Mock()
                path = self.write_move(directory, "older.gd5move", "Leader", move)
                completed = mock.Mock()
                with mock.patch.object(pickers, "open_file_browser") as browser, \
                        mock.patch.object(dialogs, "show_message") as message, \
                        mock.patch.object(dialogs, "ask_yes_no") as ask, \
                        mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
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
            with mock.patch.object(pickers, "open_file_browser") as browser:
                multiplayer_host_panel.load_multiplayer_moves(host, completed)
            browser.assert_not_called()
            completed.assert_called_once_with(False)

    def test_import_rejects_reserved_unassigned_entry_without_assigning_its_units(self):
        host = Host()
        unit = {"owner": "Leader", "type": "Infantry", "unit_id": "owned"}
        host.map_data = {"home": {"id": 1, "owner": "Leader", "units": [unit]}}
        command = {"type": "army_roster", "armies": [{
            "id": c.UNASSIGNED_ARMY_ID, "name": "Changed", "unit_ids": ["owned"],
            "symbol": "Star", "defense_area": [1]}]}
        player_data = self.player_data(host, player_intents=[command])
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "leader.gd5move", "Leader", player_data)
            summary = self.import_moves(host, [path])
        self.assertEqual(summary["loaded"], 0)
        self.assertNotIn("armies", host.nation_data["Leader"])
        self.assertEqual(queries.get_unassigned_army(
            "Leader", host.nation_data, host.map_data)["unit_ids"], ["owned"])

    def test_import_validates_release_types_and_host_owned_countdowns(self):
        for release_type in c.PUPPET_RELEASE_TYPES:
            with self.subTest(release_type=release_type):
                host = Host()
                host.map_data = {"land": {"id": 1, "owner": "Leader", "cores": ["Outsider"],
                                          "terrain": "plains", "units": []}}
                releases = [{"core_nation": "Outsider", "keep_cores": False, "release_type": release_type, "turns_left": 0}]
                player_data = self.player_data(host, player_intents=[
                    {"type": "puppet_draft", "puppet_order": ["Subject"], "release_subjects": releases}])
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
                command = {"type": "puppet_draft", "puppet_order": host.nation_data[country]["puppets"],
                           "release_subjects": entries}
                player_data = self.player_data(host, player_intents=[command])
                if stale:
                    player_data["tournament_turn"] -= 1
                with tempfile.TemporaryDirectory() as directory:
                    path = self.write_move(directory, "move.gd5move", country, player_data)
                    summary = self.import_moves(host, [path])
                self.assertEqual(summary["rejected"], 1)
                self.assertEqual(summary["loaded"], 0)
                self.assertNotIn("release_puppet_queue", host.nation_data[country])

    def previous_release_move(self, host, **extra):
        from data import migrations
        return self.player_data(host, game_version=f"v{migrations.CURRENT_VERSION - 1}", **extra)

    def test_move_from_this_release_needs_no_conversion_or_host_review(self):
        host = Host()
        command = {"type": "puppet_draft", "puppet_order": ["Subject"],
                   "release_subjects": [{"core_nation": "Outsider", "release_type": c.PUPPET_TYPE_INTEGRATED}]}
        move = self.player_data(host, player_intents=[command])
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
        command = {"type": "country_preferences", "conscription_slider": 0.25}
        move = self.previous_release_move(host, player_intents=[command],
                                          nation_data=dict(host.nation_data["Leader"], conscription_slider=0.25))
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "older.gd5move", "Leader", move)
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
        move = self.previous_release_move(host, tournament_turn=host.time_manager.total_turns + 1)
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "older.gd5move", "Leader", move)
            before = copy.deepcopy(host.nation_data)
            summary = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(summary["loaded"], 0)
        self.assertIn("turn", summary["rejections"][0]["reason"])
        self.assertEqual(host.nation_data, before)

    def test_newer_moves_are_refused_with_an_update_message(self):
        from data import migrations
        with tempfile.TemporaryDirectory() as directory:
            host = Host()
            move = self.player_data(host, game_version=f"v{migrations.CURRENT_VERSION + 1}")
            path = self.write_move(directory, "move.gd5move", "Leader", move)
            before = copy.deepcopy(host.nation_data)
            summary = self.import_moves(host, [path], accept_older_versions=True)
        self.assertEqual(summary["loaded"], 0)
        self.assertFalse(summary["rejections"][0]["overridable"])
        self.assertIn("update", summary["rejections"][0]["reason"].lower())
        self.assertEqual(host.nation_data, before)

    def test_host_ui_converts_an_older_move_only_after_approval(self):
        from ui import dialogs 
        from ui.panels import multiplayer_host_panel

        for choice in (False, True):
            with self.subTest(choice=choice), tempfile.TemporaryDirectory() as directory:
                host = Host()
                host.multiplayer_host_mode = True
                host.multiplayer_keys_dict = self.keys
                host.show_feedback = mock.Mock()
                host.refresh_all_maps = mock.Mock()
                path = self.write_move(directory, "older.gd5move", "Leader", self.previous_release_move(host))
                completed = mock.Mock()
                with mock.patch.object(pickers, "open_file_browser") as browser, \
                        mock.patch.object(dialogs, "show_message") as message, \
                        mock.patch.object(dialogs, "ask_yes_no") as ask, \
                        mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
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

        active = tournament_files.active_owners_of(host)

        self.assertIn("Leader", active)
        self.assertIn("Member", active)
        self.assertNotIn("Outsider", active)

    def test_faction_rename_keeps_every_member_together(self):
        from map_logic.actions.player_actions import rename_player_faction

        host = Host()
        leader, member = Host(), Host()
        leader.player_country, member.player_country = "Leader", "Member"
        leader.multiplayer_mode = member.multiplayer_mode = True
        self.assertTrue(rename_player_faction(leader, "New Pact"))

        with tempfile.TemporaryDirectory() as directory:
            paths = [os.path.join(directory, f"{player.player_country}.gd5move") for player in (leader, member)]
            for player, path in zip((leader, member), paths):
                tournament_files.export_move_file(player, path, self.keys[player.player_country])
            summary = self.import_moves(host, paths)

        self.assertEqual(summary["loaded"], 2, summary["rejections"])
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
                # A compatibility country record cannot grant leadership on the host.
                projection = dict(host.nation_data[country_id], is_faction_leader=True)
                command = {"type": "country_diplomacy", "pending": {
                    "Outsider": {"action": "FACTION_INVITE", "turns": 0,
                                 "timer": 0, "message": "Please join."}}}
                move = self.player_data(host, nation_data=projection, player_intents=[command])
                with tempfile.TemporaryDirectory() as directory:
                    path = self.write_move(directory, "invitation.gd5move", country_id, move)
                    summary = self.import_moves(host, [path])
                self.assertEqual(summary["loaded"], int(country_id == "Leader"), summary["rejections"])
                game = StubMapScreen(["Leader", "Member", "Outsider"],
                                     human_players=["Leader", "Member", "Outsider"])
                for nation, data in host.nation_data.items():
                    game.nation_data.setdefault(nation, {}).update(data)
                diplomacy_processor._process_pass1_immediate_actions(game)
                self.assertEqual(bool(game.inbound("Outsider", country_id)), country_id == "Leader")
                if country_id == "Member":
                    self.assertFalse(game.nation_data[country_id]["is_faction_leader"])
                    self.assertEqual(game.pending_action(country_id, "Outsider"), "")

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
            host,
            player_intents=[{"type": "puppet_draft", "puppet_order": ["Subject"],
                             "appearances": {"Subject": appearance}}],
        )

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "appearance.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])

        self.assertEqual(summary["loaded"], 1, summary["rejections"])
        for key, value in appearance.items():
            self.assertEqual(host.nation_data["Subject"][key], value)
        self.assertEqual(host.nation_colors["Subject"], (1, 2, 3))

    def test_rejects_wrong_turn_and_duplicate_submissions(self):
        host = Host()
        valid = self.player_data(host)
        wrong_turn = self.player_data(host, tournament_turn=3)
        duplicate = self.player_data(host)

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
        from map_logic.actions.player_actions import rename_player_faction

        host = Host()
        host.conversation_colors = {"Leader": [12, 34, 56]}
        host.player_country = "Leader"
        host.multiplayer_mode = True
        host.active_players = ["Leader"]
        host.current_player_index = 0
        host.loop_map = False
        host.scenario_settings = {}
        host.script_variables = []
        host.default_research = None
        self.assertTrue(rename_player_faction(host, "New Pact"))
        host.nation_data["Subject"].update(name="New Subject", color=[1, 2, 3])
        host.pending_subject_appearances["Subject"] = queries.country_appearance_draft(host.nation_data["Subject"])
        authority = Host()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.gd5move")
            tournament_files.export_move_file(host, path, self.keys["Leader"])
            with open(path, "r") as file:
                payload = json.load(file)
            reopened = Host()
            reopened.multiplayer_mode = True
            reopened.player_country = "Leader"
            restored = self.import_moves(reopened, [path])
            self.assertEqual(restored["loaded"], 1, restored["rejections"])
            reexport = os.path.join(directory, "reopened.gd5move")
            tournament_files.export_move_file(reopened, reexport, self.keys["Leader"])
            summary = self.import_moves(authority, [reexport])

        data = tournament_files.decrypt_dict(payload["data"], self.keys["Leader"])
        self.assertEqual(set(data), {"tournament_session", "tournament_turn", "game_version", "player_intents"})
        self.assertEqual(data["tournament_session"], "test-session")
        self.assertEqual(data["tournament_turn"], 4)
        self.assertEqual(data["game_version"], c.GAME_VERSION)
        self.assertEqual(summary["loaded"], 1, summary["rejections"])
        self.assertEqual(authority.nation_data["Leader"]["faction"], "New Pact")
        self.assertEqual(authority.nation_data["Member"]["faction"], "New Pact")
        self.assertEqual(authority.nation_data["Subject"]["name"], "New Subject")
        self.assertEqual(authority.nation_data["Subject"]["color"], [1, 2, 3])
        self.assertEqual(host.conversation_colors, {"Leader": [12, 34, 56]})

    def test_export_carries_puppet_siphons_in_the_shared_intents(self):
        host = Host()
        host.player_country = "Leader"
        host.active_players = ["Leader"]
        host.current_player_index = 0
        host.loop_map = False
        host.scenario_settings = {}
        host.script_variables = []
        host.default_research = None
        rates = {"manpower": c.MAX_PUPPET_SIPHON / 2, "materials": c.MAX_PUPPET_SIPHON, "fuel": c.MAX_PUPPET_SIPHON}
        host.nation_data["Subject"]["siphon_rates"] = dict(rates)
        authority = Host()

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "out.gd5move")
            tournament_files.export_move_file(host, path, self.keys["Leader"])
            with open(path, "r") as file:
                payload = json.load(file)
            summary = self.import_moves(authority, [path])

        data = tournament_files.decrypt_dict(payload["data"], self.keys["Leader"])
        puppet = next(command for command in data["player_intents"] if command["type"] == "puppet_draft")
        self.assertEqual(puppet["siphons"], {"Subject": rates})
        self.assertEqual(summary["loaded"], 1, summary["rejections"])
        self.assertEqual(authority.nation_data["Subject"]["siphon_rates"], puppet["siphons"]["Subject"])

    def test_empty_compatibility_projection_preserves_host_units(self):
        host = Host()
        host.map_data = {
            (1, 1): {"id": 1, "json_key": "P1", "units": [
                {"owner": "Leader", "type": "Infantry"},
                {"owner": "Member", "type": "Infantry"},
            ]},
        }
        move = self.player_data(host, unit_snapshot=True)

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "empty-army.gd5move", "Leader", move)
            summary = self.import_moves(host, [path])

        self.assertEqual(summary["loaded"], 1)
        self.assertEqual([unit["owner"] for unit in host.map_data[(1, 1)]["units"]], ["Leader", "Member"])
        self.assertEqual(host.syncs, 1)

    def test_integrated_puppet_siphons_are_host_validated(self):
        rates = {"manpower": c.MAX_PUPPET_SIPHON * 0.4, "materials": c.MAX_PUPPET_SIPHON * 0.8, "fuel": c.MAX_PUPPET_SIPHON}
        for allowed in (True, False):
            with self.subTest(allowed=allowed), tempfile.TemporaryDirectory() as directory:
                host = Host()
                subject = "Subject" if allowed else "Outsider"
                command = {"type": "puppet_draft", "puppet_order": ["Subject"], "siphons": {subject: rates}}
                move = self.player_data(host, player_intents=[command])
                path = self.write_move(directory, "siphons.gd5move", "Leader", move)
                summary = self.import_moves(host, [path])
                self.assertEqual(summary["loaded"], int(allowed), summary["rejections"])
                self.assertEqual(host.nation_data["Subject"].get("siphon_rates"), rates if allowed else None)
                self.assertNotIn("siphon_rates", host.nation_data["Outsider"])

    def test_policy_activation_uses_host_timing_and_rejects_submitted_countdowns(self):
        policy_id = "on_ne_passe_pas"
        for inject_countdown in (False, True):
            with self.subTest(inject_countdown=inject_countdown), tempfile.TemporaryDirectory() as directory:
                host = Host()
                host.nation_data["Leader"][politics.STRATEGY_VALUE_KEY] = 3
                requested = {"status": politics.POLICY_ACTIVATING}
                if inject_countdown:
                    requested["turns_remaining"] = 999
                command = {"type": "country_preferences", politics.POLICY_KEY: {policy_id: requested}}
                move = self.player_data(host, player_intents=[command])
                path = self.write_move(directory, "policy.gd5move", "Leader", move)
                summary = self.import_moves(host, [path])
                state = politics.policy_state(host.nation_data, "Leader", policy_id)
                self.assertEqual(summary["loaded"], int(not inject_countdown), summary["rejections"])
                if inject_countdown:
                    self.assertIsNone(state)
                else:
                    self.assertEqual(state["status"], politics.POLICY_ACTIVATING)
                    self.assertEqual(state["turns_remaining"], politics.POLICY_ACTIVATION_TURNS)

    def test_economic_choices_export_changes_only_the_submitting_country(self):
        host = Host()
        player = Host()
        player.player_country = "Leader"
        politics.set_economic_value(host.nation_data, "Leader", 4)
        politics.set_economic_value(player.nation_data, "Leader", -6)
        politics.set_economic_drift(player.nation_data, "Leader", -1)
        politics.set_axis_drift(player.nation_data, "Leader", politics.QUALITY, 1)
        politics.set_axis_drift(player.nation_data, "Leader", politics.STRATEGY, -1)
        player.nation_data["Leader"]["research_funding_slider"] = 0.37
        host.nation_data["Member"]["research_funding_slider"] = 0.15
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "compass.gd5move")
            tournament_files.export_move_file(player, path, self.keys["Leader"])
            summary = self.import_moves(host, [path])

        self.assertEqual(summary["loaded"], 1, summary["rejections"])
        self.assertEqual(politics.economic_value(host.nation_data, "Leader"), 4)
        self.assertEqual(politics.economic_drift(host.nation_data, "Leader"), -1)
        self.assertEqual(politics.economic_drift(host.nation_data, "Member"), 0)
        self.assertEqual(politics.axis_drift(host.nation_data, "Leader", politics.QUALITY), 1)
        self.assertEqual(politics.axis_drift(host.nation_data, "Leader", politics.STRATEGY), -1)
        self.assertEqual(politics.axis_drift(host.nation_data, "Member", politics.QUALITY), 0)
        self.assertEqual(host.nation_data["Leader"]["research_funding_slider"], 0.37)
        self.assertEqual(host.nation_data["Member"]["research_funding_slider"], 0.15)

    def test_older_intents_preserve_the_hosts_economic_state(self):
        host = Host()
        politics.set_economic_value(host.nation_data, "Leader", 4)
        politics.set_economic_drift(host.nation_data, "Leader", -1)
        politics.set_axis_drift(host.nation_data, "Leader", politics.QUALITY, 1)
        politics.set_axis_drift(host.nation_data, "Leader", politics.STRATEGY, -1)
        host.nation_data["Leader"]["research_funding_slider"] = 0.2
        command = {"type": "country_preferences", "political_drift": 1}
        move = self.previous_release_move(host, player_intents=[command])
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "older-compass.gd5move", "Leader", move)
            summary = self.import_moves(host, [path], accept_older_versions=True)

        self.assertEqual(summary["loaded"], 1, summary["rejections"])
        self.assertEqual(politics.economic_value(host.nation_data, "Leader"), 4)
        self.assertEqual(politics.economic_drift(host.nation_data, "Leader"), -1)
        self.assertEqual(politics.axis_drift(host.nation_data, "Leader", politics.QUALITY), 1)
        self.assertEqual(politics.axis_drift(host.nation_data, "Leader", politics.STRATEGY), -1)
        self.assertEqual(politics.drift(host.nation_data, "Leader"), 1)
        self.assertEqual(host.nation_data["Leader"]["research_funding_slider"], 0.2)

    def test_tournament_rejects_malformed_unauthorized_or_stale_economic_intents(self):
        for axis in politics.AXES:
            for failure in ("malformed", "position", "edge", "funding", "stale"):
                with self.subTest(axis=axis["id"], failure=failure), tempfile.TemporaryDirectory() as directory:
                    host = Host()
                    preferences = {"type": "country_preferences", axis["drift_key"]: 1}
                    move = self.player_data(host, player_intents=[preferences])
                    if failure == "malformed":
                        preferences[axis["drift_key"]] = True
                    elif failure == "position":
                        preferences[axis["value_key"]] = 8
                    elif failure == "edge":
                        politics.set_axis_value(host.nation_data, "Leader", axis["id"], c.POLITICS_MAX)
                    elif failure == "funding":
                        preferences["research_funding_slider"] = 1.1
                    else:
                        move["tournament_turn"] -= 1
                    path = self.write_move(directory, "invalid-compass.gd5move", "Leader", move)
                    summary = self.import_moves(host, [path])

                    self.assertEqual(summary["loaded"], 0)
                    self.assertEqual(politics.axis_drift(host.nation_data, "Leader", axis["id"]), 0)

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
            with mock.patch.object(tournament_files.c, "TOURNAMENT_SAVES_DIR", directory), \
                    mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
                tournament_files.export_tournament(host, tour_path, "host-key", self.keys)
                loaded = tournament_files.load_tournament(tour_path, "host-key")

            self.assertTrue(loaded[0])
            self.assertEqual(loaded[1], "HOST")
            self.assertEqual(loaded[6], "test-session")

            malformed_path = os.path.join(directory, "malformed.gd5tour")
            with open(malformed_path, "w") as file:
                json.dump({"verification_table": {
                    tournament_files.hash_key("host-key"): []}}, file)
            malformed = tournament_files.load_tournament(malformed_path, "host-key")

        self.assertFalse(malformed[0])
        self.assertEqual(malformed[-1], "Invalid key")

    def test_tournament_archive_uses_each_players_key_for_their_peace_choice(self):
        host = Host()
        host.nation_data["Leader"]["peace_choices"] = {"Member": {"round_id": "round", "selected": "Leader"}}
        host.nation_data["Member"]["peace_choices"] = {"Leader": {"round_id": "round", "selected": "Member"}}
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(tournament_files.c, "TOURNAMENT_SAVES_DIR", directory), \
                mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
            path = os.path.join(directory, "choices.gd5tour")
            tournament_files.export_tournament(host, path, "host-key", self.keys)

            def load_countries(key):
                loaded = tournament_files.load_tournament(path, key)
                self.assertTrue(loaded[0], loaded)
                with open(os.path.join(loaded[3], "meta.json"), encoding="utf-8") as file:
                    return json.load(file)["nation_data"]

            shared = load_countries(self.keys["Leader"])
            self.assertEqual(shared["Leader"]["peace_choices"]["Member"]["selected"], "Leader")
            self.assertNotIn("peace_choices", shared["Member"])
            both = load_countries("host-key")
            self.assertEqual(both["Leader"]["peace_choices"]["Member"]["selected"], "Leader")
            self.assertEqual(both["Member"]["peace_choices"]["Leader"]["selected"], "Member")
            self.assertIn("peace_choices", host.nation_data["Leader"])

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
            with mock.patch.object(tournament_files.c, "TOURNAMENT_SAVES_DIR", directory), \
                    mock.patch.object(tournament_files, "run_with_progress", synchronous_progress):
                tournament_files.export_tournament(host, tour_path, "host-key", self.keys)
                with open(tour_path, "r") as file:
                    payload = json.load(file)
                loaded = tournament_files.load_tournament(tour_path, "Spectator")

        self.assertTrue(loaded[0])
        self.assertEqual(loaded[1], c.TOURNAMENT_SPECTATOR_ROLE)
        self.assertIsNone(loaded[2])
        self.assertEqual(loaded[4], {})
        spectator_entry = payload["verification_table"][
            tournament_files.hash_key(c.TOURNAMENT_SPECTATOR_KEY)]
        self.assertNotIn("sk", tournament_files.decrypt_dict(
            spectator_entry["enc_session"], c.TOURNAMENT_SPECTATOR_KEY))
        spectator_save = tournament_files.decrypt_dict(
            payload["spectator_game_data"], c.TOURNAMENT_SPECTATOR_KEY)
        self.assertEqual(spectator_save["nation_data"]["Leader"]["materials"], 0)
        self.assertNotIn("order", spectator_save["provinces"]["P1"]["units"][0])

        spectator_map = Host()
        spectator_map.map_data = host.map_data
        tournament_files.strip_sensitive_data_for_tournament_spectator(spectator_map)
        self.assertEqual(spectator_map.player_country, c.TOURNAMENT_SPECTATOR)
        self.assertEqual(spectator_map.active_players, [c.TOURNAMENT_SPECTATOR])
        self.assertEqual(spectator_map.nation_data["Leader"]["inbox"], [])
        self.assertNotIn("order", spectator_map.map_data[(1, 1)]["units"][0])

        visibility_screen = map_double(
            player_country=c.TOURNAMENT_SPECTATOR,
            map_data={}, nation_data=spectator_map.nation_data,
            id_to_province={})
        self.assertEqual(tournament_files.queries.get_visible_provinces(visibility_screen),
                         (set(), set()))
        self.assertFalse(tournament_files.queries.is_unit_visible_to(
            {"type": "Submarine"}, c.TOURNAMENT_SPECTATOR, {}, spectator_map.nation_data))

    def test_spectator_is_reserved_and_cannot_be_a_master_key(self):
        host = Host()
        with tempfile.TemporaryDirectory() as directory, \
                self.assertRaisesRegex(ValueError, "reserved"):
            tournament_files.export_tournament(
                host, os.path.join(directory, "turn.gd5tour"), "  spectator  ", self.keys)

    def test_decrypt_rejects_bad_input_without_hiding_internal_errors(self):
        self.assertIsNone(tournament_files.decrypt_dict("not an encrypted payload", "key"))
        with mock.patch.object(tournament_files, "generate_fernet_key_from_password",
                               side_effect=RuntimeError("broken implementation")):
            with self.assertRaisesRegex(RuntimeError, "broken implementation"):
                tournament_files.decrypt_dict("YWJjZA==:token", "key")


if __name__ == "__main__":
    unittest.main()
