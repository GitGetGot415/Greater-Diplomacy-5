"""Pins how the AI answers every kind of proposal.

evaluate_verdict is the diplomatic brain -- it decides accept or reject before
the model is ever consulted -- and until this file it had no test coverage of
any kind. It was just lifted out of evaluate_diplomatic_proposal unchanged, so
what is written down here is current behaviour, warts included, not desired
behaviour. Phase 3 changes several of these deliberately and this file is where
that shows up.

Three of the cases below are the ones worth arguing about later, and are marked
where they appear:

  - a claims demand is refused unconditionally, which is why AI wars never end
    with territory changing hands
  - a trade is accepted only if the AI gives literally nothing
  - relations gate exactly one branch, and a shared enemy bypasses even that
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.ai import ai_evaluation
from map_logic.diplomacy import deal


def nation(**over):
    base = {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
            "master": "", "puppet_type": "", "faction": "", "is_faction_leader": False,
            "temp_modifiers": {}, "pending_diplomacy": {},
            "manpower": 5000, "materials": 8000, "fuel": 500, "war_durations": {}}
    base.update(over)
    return base


class VerdictTestCase(unittest.TestCase):
    def setUp(self):
        self.nation_data = {"Avaria": nation(), "Borland": nation()}
        # Three provinces each, so a peace deal can ask for a piece of a nation
        # rather than only for all of it -- demanding somebody's last province
        # is demanding they cease to exist, and is refused on those grounds
        # however badly the war is going.
        self.map_data = {}
        for prov_id, owner in ((1, "Avaria"), (2, "Borland"), (3, "Avaria"),
                               (4, "Borland"), (5, "Avaria"), (6, "Borland")):
            self.map_data[str(prov_id)] = {
                "id": prov_id, "owner": owner, "cores": [owner],
                "neighbors": [prov_id - 1, prov_id + 1], "units": []}

    def verdict(self, action, custom_msg="", ai="Avaria", sender="Borland"):
        return ai_evaluation.evaluate_verdict(
            self.nation_data, self.map_data, ai, sender, action, custom_msg)

    def accepts(self, action, **kw):
        return self.verdict(action, **kw).accepted

    def offer(self, **params):
        """Records a proposal from Borland to Avaria carrying trade terms."""
        self.nation_data["Borland"]["pending_diplomacy"]["Avaria"] = {
            "action": "TRADE", "turns": 1, "parameters": params}

    def garrison(self, prov_key, owner, count=8):
        """Stacks an army somewhere, so one side is visibly winning.

        The shape matters: calculate_unit_strength reads attack/defense/health,
        and a unit dict missing those scores zero -- which leaves both sides'
        strength resting entirely on their stockpiles and every war looking
        perfectly even.
        """
        self.map_data[prov_key]["units"] = [
            {"owner": owner, "attack": 400, "defense": 200, "health": 1000}
            for _ in range(count)]


class ShapeTests(VerdictTestCase):
    def test_a_rule_with_no_judgement_in_it_is_certain(self):
        for action in ("JOIN_WARS", "REQ_MILITARY_ACCESS"):
            v = self.verdict(action)
            self.assertEqual((v.confidence, v.reason), (1.0, ""), action)

    def test_a_peace_call_reports_how_close_it_was(self):
        """A marginal call is exactly where a leader's own judgement should be
        allowed to differ from the staff's, which is what the model reads this
        for. It was flat 1.0 while the decision was a string comparison."""
        v = self.verdict("CEASEFIRE")
        self.assertLess(v.confidence, 1.0)
        self.assertTrue(v.reason)

    def test_an_unknown_action_is_refused(self):
        self.assertFalse(self.accepts("SOMETHING_UNHANDLED"))


class FactionTests(VerdictTestCase):
    def test_a_nation_at_war_and_unaligned_takes_any_faction_offer(self):
        self.nation_data["Avaria"]["at_war_with"] = ["Carrow"]
        self.assertTrue(self.accepts("FACTION_INVITE"))
        self.assertTrue(self.accepts("CREATE_FACTION"))

    def test_but_not_from_the_nation_it_is_fighting(self):
        self.nation_data["Avaria"]["at_war_with"] = ["Borland"]
        self.nation_data["Borland"]["at_war_with"] = ["Avaria"]
        self.assertFalse(self.accepts("FACTION_INVITE"))

    def test_a_nation_at_peace_ignores_faction_offers(self):
        self.assertFalse(self.accepts("FACTION_INVITE"))

    def test_a_nation_already_in_a_faction_ignores_them_too(self):
        self.nation_data["Avaria"].update(at_war_with=["Carrow"], faction="Entente")
        self.assertFalse(self.accepts("FACTION_INVITE"))

    def test_faction_mates_get_help(self):
        self.nation_data["Avaria"]["faction"] = "Entente"
        self.nation_data["Borland"]["faction"] = "Entente"
        self.assertTrue(self.accepts("JOIN_WARS"))
        self.assertTrue(self.accepts("CALL_TO_ARMS"))

    def test_strangers_do_not(self):
        self.assertFalse(self.accepts("JOIN_WARS"))
        self.assertFalse(self.accepts("CALL_TO_ARMS"))


class FactionLeaderTests(VerdictTestCase):
    """The only branch in the whole function that reads a relation score."""

    def setUp(self):
        super().setUp()
        self.nation_data["Avaria"].update(faction="Entente", is_faction_leader=True)

    def test_good_relations_get_you_in(self):
        self.nation_data["Avaria"]["temp_modifiers"] = {
            "Borland": {"general": c.AI_RELATION_FACTION_THRESHOLD}}
        self.assertTrue(self.accepts("JOIN_FACTION_REQ"))

    def test_poor_relations_do_not(self):
        self.nation_data["Avaria"]["temp_modifiers"] = {"Borland": {"general": -40}}
        self.assertFalse(self.accepts("JOIN_FACTION_REQ"))

    def test_a_shared_enemy_gets_you_in_regardless_of_relations(self):
        """Which is why relations almost never actually decide anything here."""
        self.nation_data["Avaria"].update(at_war_with=["Carrow"],
                                          temp_modifiers={"Borland": {"general": -200}})
        self.nation_data["Borland"]["at_war_with"] = ["Carrow"]
        self.assertTrue(self.accepts("JOIN_FACTION_REQ"))

    def test_the_threshold_is_exactly_inclusive(self):
        for offset, expected in ((0, True), (-1, False)):
            self.nation_data["Avaria"]["temp_modifiers"] = {
                "Borland": {"general": c.AI_RELATION_FACTION_THRESHOLD + offset}}
            self.assertEqual(self.accepts("JOIN_FACTION_REQ"), expected, offset)

    def test_a_nation_that_is_not_the_leader_does_not_decide(self):
        self.nation_data["Avaria"]["is_faction_leader"] = False
        self.nation_data["Avaria"]["temp_modifiers"] = {"Borland": {"general": 200}}
        self.assertFalse(self.accepts("JOIN_FACTION_REQ"))

    def test_the_claim_penalty_is_skipped_here(self):
        """Documents a real quirk: this call omits id_to_province, so cross-claims
        that the tooltip counts against the relationship are invisible to the one
        decision relations feed. Phase 3 routes this through AIWorld instead."""
        self.nation_data["Avaria"]["temp_modifiers"] = {
            "Borland": {"general": c.AI_RELATION_FACTION_THRESHOLD}}
        self.map_data["2"]["cores"].append("Avaria")     # Avaria claims Borland's tile
        id_to_province = {p["id"]: p for p in self.map_data.values()}

        full = queries.get_relation_score("Avaria", "Borland", self.nation_data, id_to_province)
        partial = queries.get_relation_score("Avaria", "Borland", self.nation_data)
        self.assertLess(full, partial, "the claim should have cost relations")
        self.assertTrue(self.accepts("JOIN_FACTION_REQ"),
                        "but the verdict uses the score without it")


class MilitaryAccessTests(VerdictTestCase):
    def test_a_shared_enemy_opens_the_border(self):
        self.nation_data["Avaria"]["at_war_with"] = ["Carrow"]
        self.nation_data["Borland"]["at_war_with"] = ["Carrow"]
        self.assertTrue(self.accepts("REQ_MILITARY_ACCESS"))

    def test_no_shared_enemy_keeps_it_shut(self):
        self.nation_data["Avaria"]["at_war_with"] = ["Carrow"]
        self.nation_data["Borland"]["at_war_with"] = ["Dunmar"]
        self.assertFalse(self.accepts("REQ_MILITARY_ACCESS"))

    def test_two_nations_at_peace_refuse(self):
        self.assertFalse(self.accepts("REQ_MILITARY_ACCESS"))


class PuppetTests(VerdictTestCase):
    def test_a_puppet_obeys_its_master(self):
        self.nation_data["Avaria"]["master"] = "Borland"
        for action in ("FACTION_INVITE", "CREATE_FACTION", "JOIN_FACTION_REQ"):
            self.assertTrue(self.accepts(action), action)

    def test_but_not_a_third_party(self):
        self.nation_data["Avaria"]["master"] = "Carrow"
        self.assertFalse(self.accepts("FACTION_INVITE"))


class PeaceTests(VerdictTestCase):
    def setUp(self):
        super().setUp()
        self.nation_data["Avaria"]["at_war_with"] = ["Borland"]
        self.nation_data["Borland"]["at_war_with"] = ["Avaria"]

    def demand(self, ids, giver="Avaria", taker="Borland"):
        """Records a peace proposal from Borland asking Avaria for territory."""
        agreement = deal.new(deal.KIND_PEACE, [taker], [giver],
                             [deal.white_peace(), deal.tiles_clause(giver, taker, ids)])
        self.nation_data["Borland"]["pending_diplomacy"]["Avaria"] = {
            "action": "PEACE_TREATY", "turns": 1, "parameters": agreement}
        return agreement

    def test_a_demand_for_land_is_weighed_rather_than_refused_outright(self):
        """Was: refused unconditionally, which is why no AI war ever ended with
        territory changing hands. A nation being ground down for a hundred turns
        by a stronger enemy now gives up a province to stop it."""
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 99}
        self.garrison("2", "Borland")
        self.demand([1])
        self.assertTrue(self.accepts("PEACE_TREATY"))

    def test_but_a_winning_nation_does_not_hand_over_its_land(self):
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 99}
        self.garrison("1", "Avaria")
        self.demand([1])
        self.assertFalse(self.accepts("PEACE_TREATY"))

    def test_a_ceasefire_is_refused_while_the_war_is_young(self):
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 0}
        self.assertFalse(self.accepts("CEASEFIRE", custom_msg=c.PEACE_WHITE_PEACE))

    def test_a_ceasefire_is_taken_once_the_war_has_run_and_it_cannot_win(self):
        self.nation_data["Avaria"]["war_durations"] = {"Borland": c.MIN_TURNS_FOR_CEASEFIRE + 1}
        self.assertTrue(self.accepts("CEASEFIRE", custom_msg=c.PEACE_WHITE_PEACE))

    def test_prose_no_longer_changes_the_verdict(self):
        """The regression this file predicted. custom_msg doubled as the peace
        type, so "Our terms: Demand Claims" matched no prefix and was waved
        through by a catch-all -- the same demand accepted purely because it had
        been worded politely. Terms are data now and the wording is just wording."""
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 99}
        self.garrison("1", "Avaria")
        self.demand([1])

        bare = self.accepts("PEACE_TREATY")
        with_prose = self.accepts("PEACE_TREATY", custom_msg="Our terms, respectfully offered.")
        self.assertEqual(bare, with_prose)
        self.assertFalse(with_prose)

    def test_an_offer_carrying_no_terms_at_all_is_read_as_a_white_peace(self):
        """What every AI peace offer used to be: a sentence and nothing else.
        It is judged as the white peace it always executed as, rather than
        falling through to an unconditional yes."""
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 0}
        self.assertFalse(self.accepts("PEACE_TREATY",
                                      custom_msg="This war has cost us both too much."))


class TradeTests(VerdictTestCase):
    def test_a_pure_gift_is_accepted(self):
        self.offer(give_materials=500)
        self.assertTrue(self.accepts("TRADE"))

    def test_an_even_swap_is_refused(self):
        """The AI accepts a trade only if it gives literally nothing, which is
        why no AI has ever agreed to a deal a player would think fair."""
        self.offer(give_materials=500, take_materials=500)
        self.assertFalse(self.accepts("TRADE"))

    def test_a_wildly_generous_offer_is_still_refused_if_it_costs_anything(self):
        self.offer(give_materials=100000, take_fuel=1)
        self.assertFalse(self.accepts("TRADE"))

    def test_an_empty_offer_is_refused(self):
        self.offer()
        self.assertFalse(self.accepts("TRADE"))

    def test_fuel_counts_the_same_as_materials(self):
        self.offer(give_fuel=200)
        self.assertTrue(self.accepts("TRADE"))

    def test_a_puppet_clause_kills_the_deal(self):
        self.offer(give_materials=500, puppet_state="VASSALIZE")
        self.assertFalse(self.accepts("TRADE"))

    def test_an_integrated_puppet_may_now_trade_on_its_own_account(self):
        """The restriction is lifted: subjects trade like anyone else."""
        self.offer(give_materials=500)
        self.nation_data["Avaria"].update(master="Carrow", puppet_type=c.PUPPET_TYPE_INTEGRATED)
        self.assertTrue(self.accepts("TRADE"))

    def test_and_can_be_traded_with(self):
        self.offer(give_materials=500)
        self.nation_data["Borland"].update(master="Carrow", puppet_type=c.PUPPET_TYPE_INTEGRATED)
        self.assertTrue(self.accepts("TRADE"))

    def test_a_master_can_still_trade_with_its_own_integrated_puppet(self):
        self.offer(give_materials=500)
        self.nation_data["Borland"].update(master="Avaria", puppet_type=c.PUPPET_TYPE_INTEGRATED)
        self.assertTrue(self.accepts("TRADE"))


class ProposalWiringTests(VerdictTestCase):
    """evaluate_diplomatic_proposal must report exactly the extracted verdict."""

    def test_the_canned_reply_carries_the_verdict_through(self):
        from map_logic.ai import ai_settings

        original = ai_settings.get_ai_mode
        try:
            ai_settings.get_ai_mode = lambda: "OFF"
            self.offer(give_materials=500)
            for action, expected in (("TRADE", True), ("JOIN_WARS", False)):
                reply = ai_evaluation.evaluate_diplomatic_proposal(
                    self.nation_data, self.map_data, ["Avaria", "Borland"],
                    "Avaria", "Borland", action, "", human_players=["Avaria"])
                self.assertEqual(reply["accepted"], expected, action)
                self.assertEqual(
                    reply["accepted"],
                    self.verdict(action).accepted,
                    f"{action}: the reply and the verdict must never disagree")
        finally:
            ai_settings.get_ai_mode = original


if __name__ == "__main__":
    unittest.main()
