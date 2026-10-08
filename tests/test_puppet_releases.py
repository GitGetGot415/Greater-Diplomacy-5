"""Check nation release choices, spectator permissions, and delayed resolution."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_processor, puppet_actions
from screens.map_related_screens import puppets_screen
from tests import app_harness
from tests.test_map_save_format import sample_map_screen


def release_map(player="Master"):
    def country(name, **fields):
        data = dict(name=name, adjective="", color=[30, 50, 70], is_playable=True,
                    puppets=[], master="", puppet_type="", faction="", at_war_with=[],
                    allied_with=[], pending_diplomacy={}, research={})
        data.update(fields)
        return data

    nations = {"Master": country("Master Display", adjective="Masterish", faction="Pact",
                                 at_war_with=["Enemy"], research={"fixture_tech": 2}),
               "Core": country("Core Display"), "Second": country("Second Display"),
               "Other": country("Other Display"), "Enemy": country("Enemy Display")}
    provinces = {}
    for pid, owner, cores in ((1, "Master", ["Core"]),
                              (2, "Master", ["Master", "Core", "Second"]),
                              (3, "Master", ["Second"]),
                              (4, "Other", ["Core"]), (5, "Master", ["Master"])):
        provinces[str(pid)] = dict(id=pid, json_key=str(pid), owner=owner, cores=cores,
                                   terrain="plains", neighbors=[], units=[], building_queue=[],
                                   unit_queue=[], map_color=[pid, 0, 0], buildings=[], resources={})
    return SimpleNamespace(nation_data=nations, map_data=provinces,
                           id_to_province={p["id"]: p for p in provinces.values()},
                           player_country=player, is_editor=False, tactical_mode=False,
                           multiplayer_mode=False, realtime_multiplayer=False,
                           viewing_ai_moves=False, ai_is_thinking=True, centers_need_update=False,
                           nation_colors={}, map_mode="POLITICAL", show_feedback=mock.Mock(),
                           camera=mock.Mock())


class PuppetReleaseRuleTests(unittest.TestCase):
    def setUp(self):
        self.map = release_map()

    def canonical(self, entries, old=()):
        return puppet_actions.canonical_puppet_release_queue(
            self.map.map_data, self.map.nation_data, "Master", entries, old)

    def release(self, release_type=c.PUPPET_TYPE_INTEGRATED, keep_cores=False):
        return puppet_actions.finalize_create_puppet(
            self.map.map_data, self.map.nation_data, "Master", "Core", self.map, keep_cores, release_type)

    def test_each_choice_uses_the_expected_master_faction_and_wars(self):
        for release_type in c.PUPPET_RELEASE_TYPES:
            with self.subTest(release_type=release_type):
                self.map = release_map()
                created = self.release(release_type)
                data = self.map.nation_data[created]
                independent = release_type == c.PUPPET_RELEASE_INDEPENDENT
                self.assertEqual(data["master"], "" if independent else "Master")
                self.assertEqual(data["puppet_type"], "" if independent else release_type)
                self.assertEqual(data["faction"], "" if independent else "Pact")
                self.assertEqual(data["at_war_with"], [] if independent else ["Enemy"])
                self.assertEqual(created in self.map.nation_data["Master"]["puppets"], not independent)
                self.assertEqual(bool(data.get("is_created_integrated_puppet")),
                                 release_type == c.PUPPET_TYPE_INTEGRATED)
                self.assertEqual(data["research"], self.map.nation_data["Master"]["research"])
                self.assertIsNot(data["research"], self.map.nation_data["Master"]["research"])
                self.assertEqual(self.map.map_data["1"]["owner"], created)
                self.assertEqual(self.map.map_data["2"]["owner"], created)
                self.assertEqual(self.map.map_data["4"]["owner"], "Other")

    def test_keep_cores_uses_the_same_territory_rule_for_all_choices(self):
        for release_type in c.PUPPET_RELEASE_TYPES:
            self.map = release_map()
            expected = queries.get_puppet_release_provinces("Master", "Core", self.map.map_data, True)
            created = self.release(release_type, keep_cores=True)
            self.assertEqual({p["id"] for p in self.map.map_data.values() if p["owner"] == created},
                             {p["id"] for p in expected})
            self.assertEqual(self.map.map_data["2"]["owner"], "Master")

    def test_no_land_or_invalid_type_creates_no_country(self):
        original = copy.deepcopy(self.map.nation_data)
        self.map.map_data["1"]["owner"] = "Other"
        self.map.map_data["2"]["owner"] = "Other"
        self.assertIsNone(self.release())
        self.assertEqual(self.map.nation_data, original)
        self.map = release_map()
        self.assertIsNone(self.release("Unknown"))

    def test_legacy_queue_defaults_to_integrated_and_keeps_its_countdown(self):
        old = [{"core_nation": "Core", "keep_cores": False, "turns_left": 2}]
        canonical = self.canonical(old, old)
        self.assertEqual(canonical[0]["release_type"], c.PUPPET_TYPE_INTEGRATED)
        self.assertEqual(canonical[0]["turns_left"], 2)
        self.map.nation_data["Master"]["release_puppet_queue"] = old
        diplomacy_processor._process_claim_queues(self.map)
        self.assertEqual(self.map.map_data["1"]["owner"], "Master")
        diplomacy_processor._process_claim_queues(self.map)
        created = self.map.map_data["1"]["owner"]
        self.assertEqual(self.map.nation_data[created]["puppet_type"], c.PUPPET_TYPE_INTEGRATED)

    def test_resolution_preserves_each_queued_choice(self):
        for release_type in c.PUPPET_RELEASE_TYPES:
            self.map = release_map()
            self.map.nation_data["Master"]["release_puppet_queue"] = self.canonical(
                [{"core_nation": "Core", "release_type": release_type}])
            diplomacy_processor._process_claim_queues(self.map)
            created = self.map.map_data["1"]["owner"]
            self.assertEqual(self.map.nation_data[created]["puppet_type"],
                             "" if release_type == c.PUPPET_RELEASE_INDEPENDENT else release_type)
            self.assertEqual(self.map.nation_data["Master"]["release_puppet_queue"], [])

    def test_releases_consume_overlapping_core_land_in_queue_order(self):
        entries = self.canonical([{"core_nation": "Core", "release_type": c.PUPPET_RELEASE_INDEPENDENT},
                                  {"core_nation": "Second", "release_type": c.PUPPET_TYPE_AUTONOMOUS}])
        self.map.nation_data["Master"]["release_puppet_queue"] = entries
        diplomacy_processor._process_claim_queues(self.map)
        first, second = self.map.map_data["1"]["owner"], self.map.map_data["3"]["owner"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.map.map_data["2"]["owner"], first)

    def test_new_country_does_not_copy_the_source_release_queue(self):
        self.map.nation_data["Core"]["release_puppet_queue"] = [{"core_nation": "Other", "turns_left": 3}]
        created = self.release()
        self.assertEqual(self.map.nation_data[created]["release_puppet_queue"], [])
        self.assertEqual(len(self.map.nation_data["Core"]["release_puppet_queue"]), 1)

    def test_malformed_duplicate_foreign_and_empty_land_requests_are_rejected(self):
        for entries in (None, [None], [{"core_nation": []}], [{"core_nation": "Core", "keep_cores": "yes"}],
                        [{"core_nation": "Core", "release_type": "Unknown"}],
                        [{"core_nation": "Core", "release_type": []}],
                        [{"core_nation": "Core"}, {"core_nation": "Core"}],
                        [{"core_nation": "Master"}], [{"core_nation": "Enemy"}]):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.canonical(entries)

    def test_existing_options_require_cancellation_before_changes(self):
        old = self.canonical([{"core_nation": "Core"}])
        for field, value in (("release_type", c.PUPPET_TYPE_AUTONOMOUS), ("keep_cores", True)):
            requested = dict(old[0], **{field: value})
            with self.assertRaises(ValueError):
                self.canonical([requested], old)
        self.assertEqual(self.canonical([], old), [])

    def test_new_requests_cannot_set_their_own_countdown(self):
        self.assertEqual(self.canonical([{"core_nation": "Core", "turns_left": 0}])[0]["turns_left"], 1)

    def test_release_type_survives_save_dict_round_trip_and_resolution(self):
        for release_type in c.PUPPET_RELEASE_TYPES:
            saved_map = sample_map_screen()
            saved_map.nation_data = self.map.nation_data
            saved_map.map_data = self.map.map_data
            saved_map.nation_data["Master"]["release_puppet_queue"] = self.canonical(
                [{"core_nation": "Core", "release_type": release_type}])
            payload = json.loads(json.dumps(queries.build_save_dict(saved_map)))
            loaded = release_map()
            loaded.nation_data = payload["nation_data"]
            queries.merge_country_templates(loaded.nation_data)
            loaded.map_data = queries.map_data_with_saved_provinces(loaded.map_data, payload["provinces"])
            loaded.id_to_province = {p["id"]: p for p in loaded.map_data.values()}
            diplomacy_processor._process_claim_queues(loaded)
            created = loaded.map_data["1"]["owner"]
            self.assertEqual(loaded.nation_data[created]["puppet_type"],
                             "" if release_type == c.PUPPET_RELEASE_INDEPENDENT else release_type)


class PuppetReleaseControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.surface = app_harness.boot()

    def setUp(self):
        self.map = release_map()

    def test_opening_always_starts_integrated_and_buttons_change_the_choice(self):
        screen = puppets_screen.Create_Puppet_Screen(self.map)
        self.assertEqual(screen.release_type, c.PUPPET_TYPE_INTEGRATED)
        for release_type in c.PUPPET_RELEASE_TYPES:
            button = next(element for element in screen.elements if getattr(element, "text", None) == release_type)
            button.callback()
            self.assertEqual(screen.release_type, release_type)
        self.assertEqual(puppets_screen.Create_Puppet_Screen(self.map).release_type, c.PUPPET_TYPE_INTEGRATED)

    def test_spectator_picker_keeps_the_viewer_and_queues_for_the_selected_country(self):
        self.map.player_country = "Spectator"
        with mock.patch.object(queries, "open_listbox_selector") as picker, \
                mock.patch.object(puppets_screen, "_run_pygame_sub_screen") as launch:
            puppets_screen.open_puppets_menu(self.map)
            picker.assert_called_once()
            callback = picker.call_args.args[4]
            callback("Master")
            screen = launch.call_args.args[1]
        self.assertEqual(self.map.player_country, "Spectator")
        self.assertEqual(screen.releasing_country, "Master")
        screen.set_release_type(c.PUPPET_TYPE_AUTONOMOUS)
        screen.queue_creation("Core")
        self.assertEqual(self.map.nation_data["Master"]["release_puppet_queue"][0]["release_type"],
                         c.PUPPET_TYPE_AUTONOMOUS)
        self.assertNotIn("Spectator", self.map.nation_data)
        screen.cancel_queue("Core")
        self.assertEqual(self.map.nation_data["Master"]["release_puppet_queue"], [])

    def test_normal_player_still_opens_the_subject_manager(self):
        with mock.patch.object(puppets_screen, "_run_pygame_sub_screen") as launch:
            puppets_screen.open_puppets_menu(self.map)
        self.assertIsInstance(launch.call_args.args[1], puppets_screen.Puppets_Screen)

    def test_cannot_queue_twice_or_queue_land_reserved_by_another_release(self):
        screen = puppets_screen.Create_Puppet_Screen(self.map)
        screen.queue_creation("Core")
        screen.queue_creation("Core")
        self.assertEqual(len(self.map.nation_data["Master"]["release_puppet_queue"]), 1)
        self.map.map_data["3"]["owner"] = "Other"
        screen.queue_creation("Second")
        self.assertEqual(len(self.map.nation_data["Master"]["release_puppet_queue"]), 1)

    def test_player_cannot_release_for_another_country(self):
        screen = puppets_screen.Create_Puppet_Screen(self.map, "Other")
        screen.queue_creation("Core")
        self.assertNotIn("release_puppet_queue", self.map.nation_data["Other"])

    def test_permission_changes_block_queued_releases_and_cancellation(self):
        self.map.player_country = "Spectator"
        screen = puppets_screen.Create_Puppet_Screen(self.map, "Master")
        screen.queue_creation("Core")
        for attr in ("tactical_mode", "is_editor", "multiplayer_mode", "realtime_multiplayer"):
            setattr(self.map, attr, True)
            screen.cancel_queue("Core")
            screen.queue_creation("Second")
            self.assertEqual(len(self.map.nation_data["Master"]["release_puppet_queue"]), 1)
            setattr(self.map, attr, False)

    def test_submitted_realtime_player_cannot_change_release_queue(self):
        self.map.realtime_multiplayer = True
        self.map.realtime_player_id = "player"
        self.map.realtime_session = SimpleNamespace(phase="TURN", players={
            "player": SimpleNamespace(submitted=True, eliminated=False)})
        screen = puppets_screen.Create_Puppet_Screen(self.map)
        screen.queue_creation("Core")
        self.assertNotIn("release_puppet_queue", self.map.nation_data["Master"])

    def test_draw_uses_cached_territory_previews(self):
        screen = puppets_screen.Create_Puppet_Screen(self.map)
        screen.queue_creation("Core")
        with mock.patch.object(queries, "get_puppet_release_provinces", side_effect=AssertionError("Frame calculation")), \
                mock.patch.object(puppets_screen.overlay_renderer, "draw_map_highlight"):
            screen.draw_content(self.surface)
            screen.draw_content(self.surface)


if __name__ == "__main__":
    unittest.main()
