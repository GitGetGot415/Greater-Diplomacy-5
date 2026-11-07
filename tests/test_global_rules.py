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
from data.world_nations import WorldNations
from map_logic.ai import ai_evaluation
from map_logic.ai.scripted_events import process_scripted_events
from map_logic.diplomacy import global_rules, treaty_effects
from tests.test_scripted_diplomacy_actions import event
from map_logic.diplomacy.action_definitions import availability

ROOT = Path(__file__).resolve().parents[1]


def rule(country, rule_type, target, strength=global_rules.STRONG, bypass=True):
    return {"country": country, "rule": rule_type, "target": target, "strength": strength,
            "bypass_scripted_events": bypass}


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

    def test_decent_and_weak_rules_bind_ai_senders_but_not_human_players(self):
        # A and B are human. C and D are AI.
        for strength in (global_rules.DECENT, global_rules.WEAK):
            with self.subTest(strength=strength):
                self.game.global_rules = [rule("A", global_rules.DECLARE_WAR, "C", strength),
                                          rule("C", global_rules.DECLARE_WAR, "A", strength)]

                self.assertTrue(self.allowed("A", "C", "WAR_DECLARATION"))
                self.assertFalse(self.allowed("C", "A", "WAR_DECLARATION"))

    def test_an_ai_refuses_and_cannot_accept_what_a_decent_rule_forbids(self):
        self.game.set_war("A", "C")
        self.game.global_rules = [rule("A", global_rules.MAKE_PEACE, "C", global_rules.DECENT)]
        self.assertTrue(self.allowed("A", "C", "CEASEFIRE"))

        # The game passes country records that resolve to their world.
        nation_data = WorldNations(self.game, self.game.nation_data)
        verdict = ai_evaluation.evaluate_verdict(nation_data, self.game.map_data, "C", "A", "CEASEFIRE")
        outcome = treaty_effects.apply_treaty_effect(self.game, "CEASEFIRE", "A", "C")

        self.assertFalse(verdict.accepted)
        self.assertIn("may never", verdict.reason)
        self.assertIn("may never", outcome.blocked)
        self.assertTrue(queries.are_at_war("A", "C", self.game.nation_data))

    def test_an_ai_may_accept_what_a_weak_rule_forbids(self):
        self.game.set_war("A", "C")
        self.game.global_rules = [rule("A", global_rules.MAKE_PEACE, "C", global_rules.WEAK)]
        self.assertFalse(self.allowed("C", "A", "CEASEFIRE"))

        nation_data = WorldNations(self.game, self.game.nation_data)
        verdict_check = global_rules.forbidden_reason(
            nation_data, "A", "C", "CEASEFIRE", choices=(global_rules.Choice(True, accepting=True),))
        outcome = treaty_effects.apply_treaty_effect(self.game, "CEASEFIRE", "A", "C")

        self.assertEqual(verdict_check, "")
        self.assertIsNone(outcome.blocked)
        self.assertFalse(queries.are_at_war("A", "C", self.game.nation_data))

    def test_decent_and_weak_rules_let_human_players_agree_with_each_other(self):
        for strength in (global_rules.DECENT, global_rules.WEAK):
            with self.subTest(strength=strength):
                self.game.global_rules = [rule("A", global_rules.TRADE, "B", strength)]
                accepting = global_rules.Choice(global_rules.is_ai_controlled(self.game, "B"), accepting=True)

                self.assertTrue(self.allowed("A", "B", "TRADE"))
                self.assertEqual(global_rules.forbidden_reason(
                    self.game, "A", "B", "TRADE", choices=(accepting,)), "")

    def test_scripted_events_break_a_rule_only_when_it_does_not_bypass_them(self):
        for bypass in (True, False):
            with self.subTest(bypass=bypass):
                self.game.global_rules = [rule("C", global_rules.DECLARE_WAR, "D", bypass=bypass)]

                self.assertFalse(self.allowed("C", "D", "WAR_DECLARATION"))
                self.assertEqual(
                    availability(self.game, "C", "D", "WAR_DECLARATION", scripted=True).allowed, not bypass)

    def test_a_scripted_declaration_reaches_war_when_the_rule_lets_events_through(self):
        self.game.global_rules = [rule("C", global_rules.DECLARE_WAR, "D", bypass=False)]
        self.game.nation_data["C"]["scripted_events"] = [event("Declare War", "D")]

        process_scripted_events(self.game)
        self.game.run_turn()

        self.assertTrue(queries.are_at_war("C", "D", self.game.nation_data))

    def test_a_scripted_declaration_is_skipped_when_the_rule_bypasses_events(self):
        self.game.global_rules = [rule("C", global_rules.DECLARE_WAR, "D")]
        self.game.nation_data["C"]["scripted_events"] = [event("Declare War", "D")]

        process_scripted_events(self.game)

        self.assertEqual(self.game.pending_action("C", "D"), "")

    def test_a_scripted_acceptance_follows_the_bypass_setting(self):
        self.game.global_rules = [rule("A", global_rules.TRADE, "C", global_rules.DECENT, bypass=False)]

        outcome = treaty_effects.apply_treaty_effect(self.game, "TRADE", "A", "C", scripted=True)
        self.assertIsNone(outcome.blocked)

        self.game.global_rules[0]["bypass_scripted_events"] = True
        outcome = treaty_effects.apply_treaty_effect(self.game, "TRADE", "A", "C", scripted=True)
        self.assertIn("may never", outcome.blocked)

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
