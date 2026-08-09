"""Covers the small shared edits to a nation's diplomatic bookkeeping.

Each of these was written out three or four times across
map_logic/diplomacy/diplomacy_agreements.py with a different guard style, and
the odd one out was always the one that could raise. The cases here are the
ones that used to differ between copies: a nation that has never been given the
key at all, and a list that is already in the state being asked for.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import diplomacy_agreements as agreements
from map_logic.system32 import combat_rules


class WarListTests(unittest.TestCase):
    def test_link_war_is_bidirectional(self):
        data = {"A": {}, "B": {}}
        agreements.link_war(data, "A", "B")
        self.assertEqual(data["A"]["at_war_with"], ["B"])
        self.assertEqual(data["B"]["at_war_with"], ["A"])

    def test_link_war_survives_a_nation_with_no_war_list(self):
        """join_faction_wars indexed nation_data directly here and raised
        KeyError for a nation that had never been to war."""
        data = {"A": {"at_war_with": []}}
        agreements.link_war(data, "A", "Newcomer")
        self.assertEqual(data["Newcomer"]["at_war_with"], ["A"])

    def test_link_war_does_not_duplicate(self):
        data = {"A": {"at_war_with": ["B"]}, "B": {"at_war_with": ["A"]}}
        agreements.link_war(data, "A", "B")
        self.assertEqual(data["A"]["at_war_with"], ["B"])

    def test_add_enemy_reports_whether_it_changed_anything(self):
        """finalize_war starts a war-duration counter off this answer, so a
        re-declaration must not reset the clock."""
        data = {"A": {}}
        self.assertTrue(agreements.add_enemy(data, "A", "B"))
        self.assertFalse(agreements.add_enemy(data, "A", "B"))

    def test_remove_enemy_reports_whether_it_changed_anything(self):
        data = {"A": {"at_war_with": ["B"]}}
        self.assertTrue(agreements.remove_enemy(data, "A", "B"))
        self.assertFalse(agreements.remove_enemy(data, "A", "B"))
        self.assertFalse(agreements.remove_enemy(data, "Nobody", "B"))


class MilitaryAccessTests(unittest.TestCase):
    def test_access_is_dropped_both_ways(self):
        data = {"A": {"military_access": ["B"]}, "B": {"military_access": ["A"]}}
        agreements.sever_military_access(data, "A", "B")
        self.assertEqual(data["A"]["military_access"], [])
        self.assertEqual(data["B"]["military_access"], [])

    def test_pending_requests_are_cancelled_too(self):
        """The request is moot once the two share a border by right."""
        data = {
            "A": {"pending_diplomacy": {"B": {"action": "REQ_MILITARY_ACCESS", "turns": 0}}},
            "B": {},
        }
        agreements.sever_military_access(data, "A", "B")
        self.assertNotIn("B", data["A"]["pending_diplomacy"])

    def test_an_unrelated_pending_action_is_left_alone(self):
        data = {"A": {"pending_diplomacy": {"B": {"action": "TRADE", "turns": 0}}}, "B": {}}
        agreements.sever_military_access(data, "A", "B")
        self.assertIn("B", data["A"]["pending_diplomacy"])

    def test_a_nation_with_no_access_list_is_survivable(self):
        agreements.sever_military_access({"A": {}, "B": {}}, "A", "B")


class CooldownTests(unittest.TestCase):
    def test_only_the_named_direction_is_cleared(self):
        """A new war clears the belligerent's own cooldowns; joining a war
        clears both sides'. Merging them into one bidirectional call would have
        widened what a declaration does."""
        data = {
            "A": {"diplo_cooldowns": {"B": {"CALL_TO_ARMS": 3, "JOIN_WARS": 3, "TRADE": 3}}},
            "B": {"diplo_cooldowns": {"A": {"CALL_TO_ARMS": 3}}},
        }
        agreements.clear_war_call_cooldowns(data, "A", "B")
        self.assertEqual(data["A"]["diplo_cooldowns"]["B"], {"TRADE": 3})
        self.assertEqual(data["B"]["diplo_cooldowns"]["A"], {"CALL_TO_ARMS": 3})

    def test_no_cooldowns_at_all_is_survivable(self):
        agreements.clear_war_call_cooldowns({"A": {}}, "A", "B")


class MeetingEngagementTests(unittest.TestCase):
    """combat_rules decides which tiles swapped garrisons. The prediction
    bubble and the turn resolver both read it, so they cannot disagree."""

    def board(self):
        return {
            1: {"id": 1, "units": [{"owner": "A", "type": "Infantry",
                                    "order": {"type": "MOVE", "path": [2]}}]},
            2: {"id": 2, "units": [{"owner": "B", "type": "Infantry",
                                    "order": {"type": "MOVE", "path": [1]}}]},
        }

    def nations(self):
        return {"A": {"at_war_with": ["B"]}, "B": {"at_war_with": ["A"]}}

    def test_a_head_on_swap_is_found_once(self):
        pairs = combat_rules.find_meeting_pairs(self.board(), self.nations())
        self.assertEqual(pairs, [(1, 2)])

    def test_nations_not_at_war_just_pass_each_other(self):
        pairs = combat_rules.find_meeting_pairs(self.board(), {"A": {}, "B": {}})
        self.assertEqual(pairs, [])

    def test_a_unit_that_is_not_moving_starts_nothing(self):
        board = self.board()
        board[2]["units"][0]["order"] = {"type": "BOMBARD", "target_id": 1}
        self.assertEqual(combat_rules.find_meeting_pairs(board, self.nations()), [])

    def test_the_sides_are_the_units_actually_crossing(self):
        board = self.board()
        board[1]["units"].append({"owner": "A", "type": "Artillery",
                                  "order": {"type": "MOVE", "path": []}})
        _p1, _p2, side_a, side_b = combat_rules.meeting_sides({1: board[1], 2: board[2]}, (1, 2))
        self.assertEqual([u["type"] for u in side_a], ["Infantry"])
        self.assertEqual([u["type"] for u in side_b], ["Infantry"])

    def test_hotseat_hides_moves_the_viewer_did_not_order(self):
        """visible_to is why a prediction can be narrower than the resolution:
        the player must not be shown an enemy's orders."""
        pairs = combat_rules.find_meeting_pairs(self.board(), self.nations(), visible_to={"A"})
        self.assertEqual(pairs, [])

    def test_the_resolver_sees_everything(self):
        pairs = combat_rules.find_meeting_pairs(self.board(), self.nations(), visible_to=None)
        self.assertEqual(pairs, [(1, 2)])

    def test_sides_respect_visibility_too(self):
        board = self.board()
        _p1, _p2, side_a, side_b = combat_rules.meeting_sides(
            {1: board[1], 2: board[2]}, (1, 2), visible_to={"A"})
        self.assertEqual(len(side_a), 1)
        self.assertEqual(side_b, [])


class ForceCategoryTests(unittest.TestCase):
    """The AI's army-balance buckets. Deliberately not the same rule as
    queries.classify_unit_group -- reconciling them would change what the AI
    builds."""

    def categories(self):
        from data import queries
        return queries

    def test_the_ai_counts_cavalry_as_armour(self):
        q = self.categories()
        self.assertEqual(q.ai_force_category("Cavalry"), q.AI_FORCE_TANKS)

    def test_the_production_screen_still_counts_cavalry_as_infantry(self):
        """If these two ever agree, one of them has been changed by accident."""
        q = self.categories()
        self.assertEqual(q.classify_unit_group("Cavalry", {}), q.UNIT_GROUP_INFANTRY)

    def test_infantry_wins_over_armour(self):
        q = self.categories()
        self.assertEqual(q.ai_force_category("Infantry Tank"), q.AI_FORCE_INFANTRY)

    def test_convoys_are_not_counted_at_all(self):
        self.assertIsNone(self.categories().ai_force_category("Convoy"))

    def test_an_empty_name_is_not_counted(self):
        self.assertIsNone(self.categories().ai_force_category(""))


if __name__ == "__main__":
    unittest.main()
