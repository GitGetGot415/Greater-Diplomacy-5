"""Covers the itemized-deal schema that replaced the peace-terms sentence.

Terms used to be a string like "Demand Claims (Territories demanded: 12, 44 +
cores)", read back with a regex and matched with str.startswith in three
different places that did not agree with each other. The two things that matter
here are that a deal never lies about itself -- validate catches a term naming a
nation that is not party to it, or a province its giver does not hold -- and
that every old shape still loads, because a save can have one travelling.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.diplomacy import deal


def province(prov_id, owner, cores=(), units=(), buildings=(), resources=None):
    return {"id": prov_id, "owner": owner, "cores": list(cores),
            "units": [{"owner": u} for u in units], "buildings": list(buildings),
            "resources": resources or {}}


def world(*provinces):
    return {str(p["id"]): p for p in provinces}


class ConstructionTests(unittest.TestCase):
    def test_a_deal_names_both_sides(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"], [deal.white_peace()])
        self.assertEqual(deal.parties(agreement), ["A", "B"])
        self.assertEqual(deal.side_of(agreement, "A"), "a")
        self.assertEqual(deal.side_of(agreement, "B"), "b")
        self.assertIsNone(deal.side_of(agreement, "C"))
        self.assertEqual(deal.opponents_of(agreement, "A"), ["B"])

    def test_add_clause_does_not_touch_the_original(self):
        """Deals are immutable once queued: snapshot_history copies nation_data
        only two levels deep, so a deal edited in place would rewrite the past."""
        original = deal.new(deal.KIND_PEACE, ["A"], ["B"], [deal.white_peace()])
        extended = deal.add_clause(original, deal.tiles_clause("B", "A", [3]))

        self.assertEqual(len(deal.clauses(original)), 1)
        self.assertEqual(len(deal.clauses(extended)), 2)
        self.assertIsNot(original["sides"]["a"], extended["sides"]["a"])

    def test_tiles_clause_dedupes_and_sorts(self):
        clause = deal.tiles_clause("B", "A", [7, 3, 7, "5"])
        self.assertEqual(clause["ids"], [3, 5, 7])

    def test_a_ceasefire_is_a_deal_with_one_clause(self):
        agreement = deal.ceasefire_deal("A", "B")
        self.assertTrue(deal.is_white_peace(agreement))
        self.assertTrue(deal.ends_war(agreement))

    def test_a_trade_does_not_end_a_war(self):
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.resources_clause("A", "B", "fuel", 100)])
        self.assertFalse(deal.ends_war(agreement))
        self.assertFalse(deal.is_white_peace(agreement))


class AffectedNationTests(unittest.TestCase):
    def test_affected_nations_are_the_ones_giving_something_up(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B", "C"], [
            deal.tiles_clause("B", "A", [3]),
            deal.resources_clause("C", "A", "materials", 500),
        ])
        self.assertEqual(deal.affected_nations(agreement), ["B", "C"])

    def test_without_nation_strips_only_that_nations_terms(self):
        """What a faction member's refusal to ratify does: their column comes
        out, the rest of the treaty stands."""
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B", "C"], [
            deal.tiles_clause("B", "A", [3]),
            deal.tiles_clause("C", "A", [4]),
        ])
        remaining = deal.without_nation(agreement, "C")

        self.assertEqual(len(deal.clauses(remaining)), 1)
        self.assertEqual(deal.clauses(remaining)[0]["from"], "B")
        self.assertEqual(remaining["sides"]["b"], ["B"])
        self.assertEqual(len(deal.clauses(agreement)), 2, "original untouched")


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.map_data = world(province(3, "B"), province(4, "B"), province(9, "C"))
        self.nation_data = {"A": {}, "B": {}, "C": {}}

    def good(self):
        return deal.new(deal.KIND_PEACE, ["A"], ["B"],
                        [deal.tiles_clause("B", "A", [3, 4])])

    def test_a_sound_deal_has_no_problems(self):
        self.assertEqual(deal.validate(self.good(), self.map_data, self.nation_data), [])

    def test_a_deal_with_no_terms_is_rejected(self):
        empty = deal.new(deal.KIND_PEACE, ["A"], ["B"])
        self.assertTrue(any("no terms" in p for p in deal.validate(empty)))

    def test_a_nation_cannot_be_on_both_sides(self):
        both = deal.new(deal.KIND_PEACE, ["A", "B"], ["B"], [deal.white_peace()])
        self.assertTrue(any("both sides" in p for p in deal.validate(both)))

    def test_a_term_cannot_name_an_outsider(self):
        meddling = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                            [deal.tiles_clause("C", "A", [9])])
        problems = deal.validate(meddling, self.map_data, self.nation_data)
        self.assertTrue(any("not party" in p for p in problems))

    def test_a_giver_must_still_hold_what_it_promises(self):
        self.map_data["3"]["owner"] = "A"
        problems = deal.validate(self.good(), self.map_data, self.nation_data)
        self.assertTrue(any("no longer holds province 3" in p for p in problems))

    def test_a_payment_of_nothing_is_not_a_term(self):
        empty_payment = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                                 [deal.resources_clause("A", "B", "fuel", 0)])
        self.assertTrue(any("nothing" in p for p in deal.validate(empty_payment)))

    def test_a_white_peace_does_not_belong_in_a_trade(self):
        confused = deal.new(deal.KIND_TRADE, ["A"], ["B"], [deal.white_peace()])
        problems = deal.validate(confused)
        self.assertTrue(any("only belongs in a peace treaty" in p for p in problems))

    def test_cannot_vassalize_someone_elses_puppet(self):
        self.nation_data["B"]["master"] = "C"
        grab = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                        [{"type": deal.VASSALIZE, "master": "A", "subject": "B"}])
        problems = deal.validate(grab, self.map_data, self.nation_data)
        self.assertTrue(any("already a puppet" in p for p in problems))


class LegacyStringTests(unittest.TestCase):
    """Saves written before the rework can have any of these in flight."""

    def test_ceasefire_becomes_a_white_peace(self):
        agreement = deal.from_legacy_string(c.PEACE_WHITE_PEACE, "A", "B")
        self.assertTrue(deal.is_white_peace(agreement))

    def test_demand_claims_takes_from_the_target(self):
        terms = f"{c.PEACE_DEMAND_CLAIMS} (Territories demanded: 12, 44, 91 + cores)"
        clause = deal.clauses(deal.from_legacy_string(terms, "A", "B"))[0]

        self.assertEqual(clause["type"], deal.TILES)
        self.assertEqual((clause["from"], clause["to"]), ("B", "A"))
        self.assertEqual(clause["ids"], [12, 44, 91])
        self.assertTrue(clause["plus_originals"],
                        "the old treaties also recovered occupied homeland")

    def test_surrender_takes_from_the_proposer(self):
        terms = f"{c.PEACE_SURRENDER} (Territories surrendered: 3, 7 + cores)"
        clause = deal.clauses(deal.from_legacy_string(terms, "A", "B"))[0]

        self.assertEqual((clause["from"], clause["to"]), ("A", "B"))
        self.assertEqual(clause["ids"], [3, 7])

    def test_prose_reads_as_the_white_peace_it_always_executed_as(self):
        """The AI's own offers carried a sentence where the terms belonged, and
        treaty_effects then fell back to PEACE_WHITE_PEACE. Same outcome, but
        now it is written down rather than an accident of an empty parameter."""
        agreement = deal.from_legacy_string(
            "This war has cost us both too much. We propose terms.", "A", "B")
        self.assertTrue(deal.is_white_peace(agreement))

    def test_coerce_reads_the_old_four_key_trade_dict(self):
        agreement = deal.coerce(
            {"give_materials": 500, "take_fuel": 200, "puppet_state": "NONE"}, "A", "B")

        moves = {(cl["from"], cl["to"], cl["resource"]): cl["amount"]
                 for cl in deal.clauses(agreement)}
        self.assertEqual(moves[("A", "B", "materials")], 500)
        self.assertEqual(moves[("B", "A", "fuel")], 200)

    def test_coerce_reads_the_old_puppet_toggle(self):
        agreement = deal.coerce({"give_fuel": 1, "puppet_state": "SENDER"}, "A", "B")
        vassalage = [cl for cl in deal.clauses(agreement) if cl["type"] == deal.VASSALIZE]
        self.assertEqual(vassalage[0]["master"], "A")
        self.assertEqual(vassalage[0]["subject"], "B")

    def test_coerce_passes_a_real_deal_straight_through(self):
        agreement = deal.ceasefire_deal("A", "B")
        self.assertIs(deal.coerce(agreement, "A", "B"), agreement)

    def test_peace_hint_stops_a_dict_being_read_as_a_trade(self):
        agreement = deal.coerce({}, "A", "B", kind=deal.KIND_PEACE)
        self.assertTrue(deal.is_white_peace(agreement))


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.nation_data = {"A": {"claims": []}, "B": {"claims": []}}

    def value_of(self, prov, giver="B", receiver="A"):
        map_data = world(prov)
        clause = deal.tiles_clause(giver, receiver, [prov["id"]])
        return deal.clause_value(clause, map_data, self.nation_data)

    def test_a_bare_province_is_worth_the_base(self):
        self.assertEqual(self.value_of(province(1, "B")), c.DEAL_VALUE_TILE_BASE)

    def test_buildings_and_resources_add_value(self):
        rich = province(1, "B", buildings=["Basic Factory"], resources={"Oil": 3})
        self.assertGreater(self.value_of(rich), c.DEAL_VALUE_TILE_BASE)

    def test_a_givers_core_costs_more_to_lose(self):
        plain = self.value_of(province(1, "B"))
        cored = self.value_of(province(1, "B", cores=["B"]))
        self.assertAlmostEqual(cored, plain * c.DEAL_VALUE_CORE_MULT)

    def test_a_claim_makes_a_province_cheaper_to_demand(self):
        """The whole remaining job of claims now that they no longer gate the
        peace screen's buttons."""
        plain = self.value_of(province(1, "B"))
        self.nation_data["A"]["claims"] = [1]
        claimed = self.value_of(province(1, "B"))
        self.assertAlmostEqual(claimed, plain * c.DEAL_VALUE_CLAIM_MULT)

    def test_occupied_land_is_half_lost_already(self):
        plain = self.value_of(province(1, "B"))
        held = self.value_of(province(1, "B", units=["A"]))
        self.assertAlmostEqual(held, plain * c.DEAL_VALUE_OCCUPIED_MULT)

    def test_a_white_peace_costs_nobody_anything(self):
        self.assertEqual(deal.clause_value(deal.white_peace(), {}, {}), 0.0)

    def test_net_value_is_positive_for_the_side_receiving(self):
        map_data = world(province(1, "B"), province(2, "A"))
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [1])])

        self.assertGreater(deal.net_value(agreement, "A", map_data, self.nation_data), 0)
        self.assertLess(deal.net_value(agreement, "B", map_data, self.nation_data), 0)

    def test_demand_fraction_is_zero_for_the_winner(self):
        map_data = world(province(1, "B"), province(2, "A"))
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [1])])
        self.assertEqual(deal.demand_fraction(agreement, "A", map_data, self.nation_data), 0.0)

    def test_losing_your_only_province_is_a_total_demand(self):
        map_data = world(province(1, "B"), province(2, "A"))
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [1])])
        self.assertAlmostEqual(
            deal.demand_fraction(agreement, "B", map_data, self.nation_data), 1.0)

    def test_a_member_rates_a_deal_by_its_own_column_when_asked_to(self):
        """A faction leader weighs the bloc's ledger; a member asked to ratify
        weighs only what it is personally giving up."""
        map_data = world(province(1, "B"), province(2, "C"), province(3, "A"))
        nation_data = {"A": {}, "B": {}, "C": {}}
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B", "C"],
                             [deal.tiles_clause("C", "A", [2])])

        self.assertEqual(deal.net_value(agreement, "B", map_data, nation_data,
                                        whole_side=False), 0.0)
        self.assertLess(deal.net_value(agreement, "C", map_data, nation_data,
                                       whole_side=False), 0.0)
        self.assertLess(deal.net_value(agreement, "B", map_data, nation_data), 0.0)


class DescriptionTests(unittest.TestCase):
    def test_every_clause_type_says_something(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"], [
            deal.white_peace(),
            deal.tiles_clause("B", "A", [3, 4]),
            deal.resources_clause("B", "A", "materials", 500),
            {"type": deal.VASSALIZE, "master": "A", "subject": "B"},
            {"type": deal.DEMILITARIZE, "nation": "B", "turns": 10},
            {"type": deal.MILITARY_ACCESS, "grantor": "B", "grantee": "A"},
            {"type": deal.FACTION_EXIT, "nation": "B"},
            {"type": deal.WAR_EXIT, "nation": "B", "against": "A"},
        ])
        lines = deal.describe(agreement, viewer="A")
        self.assertEqual(len(lines), 8)
        self.assertTrue(all(line.strip() for line in lines))

    def test_the_viewer_is_called_you(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [3])])
        self.assertIn("to you", deal.describe(agreement, viewer="A")[0])

    def test_a_spectator_sees_both_nations_named(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [3])])
        line = deal.describe(agreement)[0]
        self.assertIn("B cede", line)
        self.assertIn("to A", line)

    def test_a_bloc_deal_names_who_else_is_bound(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B", "C"], [deal.white_peace()])
        self.assertTrue(any("Bound by these terms" in line
                            for line in deal.describe(agreement, viewer="A")))

    def test_describe_ignores_something_that_is_not_a_deal(self):
        self.assertEqual(deal.describe("Ceasefire"), [])


if __name__ == "__main__":
    unittest.main()
