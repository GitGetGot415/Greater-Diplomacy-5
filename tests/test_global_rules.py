"""Global rules from the Scripted Events editor forbid diplomatic outcomes for a whole game."""

import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.stub_map_screen import StubMapScreen
import data.constants as c
from data import queries
from data.map import load_map
from map_logic.diplomacy import global_rules, treaty_effects
from map_logic.diplomacy.action_definitions import availability

ROOT = Path(__file__).resolve().parents[1]


def rule(country, rule_type, target):
    return {"country": country, "rule": rule_type, "target": target}


class GlobalRuleTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B", "C", "D", "P"], human_players=("A", "B"))
        self.game.scenario_settings["use_scripted_events"] = True

    def allowed(self, sender, target, action):
        return availability(self.game, sender, target, action).allowed

    def test_a_directional_rule_forbids_only_the_named_direction(self):
        self.game.global_rules = [rule("A", global_rules.DECLARE_WAR, "B")]

        result = availability(self.game, "A", "B", "WAR_DECLARATION")

        self.assertFalse(result.allowed)
        self.assertIn("may never", result.reason)
        self.assertTrue(self.allowed("B", "A", "WAR_DECLARATION"))

    def test_disabling_scripted_events_disables_the_rules(self):
        self.game.global_rules = [rule("A", global_rules.DECLARE_WAR, "B")]
        self.game.scenario_settings["use_scripted_events"] = False

        self.assertTrue(self.allowed("A", "B", "WAR_DECLARATION"))

    def test_a_peace_rule_covers_the_members_a_leaders_peace_binds(self):
        self.game.set_faction("X", "C", "A")
        self.game.set_war("A", "B")
        self.game.set_war("C", "B")
        self.game.global_rules = [rule("A", global_rules.MAKE_PEACE, "B")]

        self.assertFalse(self.allowed("C", "B", "CEASEFIRE"))
        self.assertFalse(self.allowed("B", "C", "PEACE_TREATY"))

    def test_a_faction_rule_covers_every_member_and_the_joiners_subjects(self):
        self.game.set_faction("X", "C", "B")
        self.game.nation_data["A"]["puppets"] = ["P"]
        self.game.nation_data["P"].update(master="A", puppet_type=c.PUPPET_TYPE_AUTONOMOUS)
        self.game.global_rules = [rule("B", global_rules.SHARE_FACTION, "P")]

        self.assertFalse(self.allowed("C", "A", "FACTION_INVITE"))
        self.assertFalse(self.allowed("A", "C", "JOIN_FACTION_REQ"))
        self.assertTrue(self.allowed("C", "D", "FACTION_INVITE"))

    def test_a_war_rule_covers_answering_a_call_to_arms(self):
        self.game.set_faction("X", "C", "A")
        self.game.set_war("C", "B")
        self.game.global_rules = [rule("A", global_rules.DECLARE_WAR, "B")]

        self.assertFalse(self.allowed("C", "A", "CALL_TO_ARMS"))
        self.assertFalse(self.allowed("A", "C", "JOIN_WARS"))

    def test_acceptance_is_refused_when_the_board_changed_while_the_offer_waited(self):
        self.game.set_faction("X", "C", "D")
        self.game.global_rules = [rule("A", global_rules.SHARE_FACTION, "B")]
        self.assertTrue(self.allowed("A", "C", "JOIN_FACTION_REQ"))
        self.game.nation_data["B"]["faction"] = "X"

        outcome = treaty_effects.apply_treaty_effect(self.game, "JOIN_FACTION_REQ", "A", "C")

        self.assertIn("may never", outcome.blocked)
        self.assertEqual(self.game.nation_data["A"]["faction"], "")

    def test_a_refused_trade_returns_the_proposers_escrow(self):
        self.game.global_rules = [rule("B", global_rules.TRADE, "A")]
        before = self.game.nation_data["A"]["materials"]

        outcome = treaty_effects.apply_treaty_effect(self.game, "TRADE", "A", "B", escrow={"materials": 50})

        self.assertTrue(outcome.blocked)
        self.assertEqual(self.game.nation_data["A"]["materials"], before + 50)

    def test_the_send_phase_drops_a_draft_written_before_the_rule(self):
        self.game.propose("A", "B", "WAR_DECLARATION")
        self.game.global_rules = [rule("A", global_rules.DECLARE_WAR, "B")]

        self.game.run_turn()

        self.assertFalse(queries.are_at_war("A", "B", self.game.nation_data))

    def test_crossed_ceasefires_do_not_settle_a_forbidden_peace(self):
        self.game.set_war("A", "B")
        self.game.propose("A", "B", "CEASEFIRE")
        self.game.propose("B", "A", "CEASEFIRE")
        self.game.global_rules = [rule("A", global_rules.MAKE_PEACE, "B")]

        self.game.run_turn()

        self.assertTrue(queries.are_at_war("A", "B", self.game.nation_data))

    def test_find_rule_matches_mutual_rules_in_either_order(self):
        rules = [rule("A", global_rules.TRADE, "B"), rule("A", global_rules.GUARANTEE, "B")]

        self.assertTrue(global_rules.find_rule(rules, global_rules.TRADE, "B", "A"))
        self.assertTrue(global_rules.find_rule(rules, global_rules.GUARANTEE, "A", "B"))
        self.assertIsNone(global_rules.find_rule(rules, global_rules.GUARANTEE, "B", "A"))


class GlobalRuleSaveTests(unittest.TestCase):
    @staticmethod
    def built_in_map():
        base = ROOT / c.BASE_MAPS_DIR
        return next(base / name for name in sorted(os.listdir(base))
                    if (base / name / "map_data.json").is_file())

    def test_older_saves_have_no_rules_and_new_rules_survive_a_reload(self):
        source = self.built_in_map()
        _meta, provinces, _history = load_map.read_save_files(source)
        key, province = next(iter(provinces.items()))
        province = copy.deepcopy(province)
        province.update(owner="Fixture", units=[], unit_queue=[], building_queue=[])
        # A save written before global rules existed has no global_rules field.
        older = {"version": c.GAME_VERSION,
                 "date": {"year": c.START_YEAR, "month": 0, "day": 1, "total_turns": 0},
                 "nation_data": {"Fixture": {"is_playable": True}},
                 "player_country": "Fixture", "active_players": ["Fixture"]}
        settings = queries.get_default_scenario_settings()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(source / "id_map.png", root / "id_map.png")
            (root / "meta.json").write_text(json.dumps(older))
            (root / "map_data.json").write_text(json.dumps({key: province}))
            game = load_map.load_backend_state(root, skip_initial_income=True, scenario_settings=settings)
            self.assertEqual(game.world.global_rules, [])

            rules = [rule("Fixture", global_rules.MAKE_PEACE, "Other")]
            game.world.global_rules = copy.deepcopy(rules)
            (root / "meta.json").write_text(json.dumps(queries.build_save_dict(game, include_provinces=False)))
            restored = load_map.load_backend_state(root, skip_initial_income=True, scenario_settings=settings)
            self.assertEqual(restored.world.global_rules, rules)


if __name__ == "__main__":
    unittest.main()
