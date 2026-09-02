"""Regression coverage for tournament move serialization and host import.

Tournament players submit only their own country record.  Shared faction state
and integrated-puppet appearance edits therefore need explicit, host-validated
commands rather than relying on that one record to describe the whole world.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data.io import multiplayer_io


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
        "allied_with": [],
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

    def import_moves(self, host, paths):
        with mock.patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
            return multiplayer_io.load_move_files(host, paths, self.keys)

    def player_data(self, country_id, host, **extra):
        result = {
            "nation_data": dict(host.nation_data[country_id]),
            "provinces": {},
            "tournament_session": host.multiplayer_session_key,
            "tournament_turn": host.time_manager.total_turns,
        }
        result.update(extra)
        return result

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

    def test_legacy_faction_rename_is_repaired_on_import(self):
        host = Host()
        legacy_data = {"nation_data": dict(host.nation_data["Leader"]), "provinces": {}}
        legacy_data["nation_data"]["faction"] = "New Pact"

        with tempfile.TemporaryDirectory() as directory:
            path = self.write_move(directory, "legacy.gd5move", "Leader", legacy_data)
            summary = self.import_moves(host, [path])

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
        self.assertEqual(data["faction_renames"][0]["new_name"], "New Pact")
        self.assertEqual(data["appearance_updates"][0]["country_id"], "Subject")

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


if __name__ == "__main__":
    unittest.main()
