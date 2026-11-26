"""Which peace terms an AI puts forward, and when.

A losing AI used to offer only a white peace. A white peace hands every occupied
province back (deal_effects.restore_occupied), so the offer asked a clear winner
to give up everything it had taken, and the winner always refused. A winning AI
never offered terms at all.

Each AI now decides from its own position only. It never reads the other side's
verdict, which is that side's private business: two AIs that both read both
verdicts reached the same answer on the same turn and sent each other the same
deal (saves/same peace deals). A loser concedes more of its lost land the worse
it wants out.

The verdicts and wish for peace are patched here, so these tests pin down which
terms are chosen and whose verdict is read, apart from the tuning of
ai_opinion.peace_verdict itself (tests/test_ai_opinion.py covers that).
"""

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from map_logic.ai import ai_tuning
from map_logic.ai import ai_candidates, ai_diplomacy, ai_opinion, ai_world
from map_logic.diplomacy import deal, deal_effects, diplomacy_messages, peace_scope, war_actions
from tests.stub_map_screen import StubMapScreen


class Overrun:
    """FOE has overrun four of AV's provinces, each worth more than the last."""

    HUMANS = ()

    def setUp(self):
        self.game = StubMapScreen(["AV", "FOE"], human_players=self.HUMANS)
        self.taken = []
        for value in range(4):
            prov = self.game.add_province("AV", cores=["AV"])
            prov["buildings"] = ["Basic Factory"] * value
            self.taken.append(prov)
        self.kept = self.game.add_province("AV", cores=["AV"])
        self.game.border(self.game.home_of("AV")["id"], self.game.home_of("FOE")["id"],
                         *(p["id"] for p in self.taken), self.kept["id"])
        for nation in ("AV", "FOE"):
            war_actions.save_own_pre_war_map(self.game.world.map_data, self.game.world.nation_data, nation)
        self.game.set_war("AV", "FOE")
        for a, b in (("AV", "FOE"), ("FOE", "AV")):
            self.game.world.nation_data[a]["war_durations"] = {b: ai_tuning.MIN_TURNS_FOR_CEASEFIRE}
        for prov in self.taken:
            prov["owner"] = "FOE"
        self.world = ai_world.AIWorld(self.game.world.map_data, self.game.world.nation_data,
                                      self.game.world.id_to_province)
        self.asked = []

    def moved(self, terms):
        return {str(prov_id) for prov_id
                in deal.tile_transfers(terms, self.game.world.map_data, self.game.world.nation_data)}

    def ids(self, provs):
        return {str(p["id"]) for p in provs}

    def judge(self, accepts):
        """A stand-in peace_verdict: `accepts(nation, terms)` decides."""
        def verdict(_world, nation, _proposer, terms, _settings=None):
            self.asked.append(nation)
            return ai_opinion.Peace(accepts(nation, terms), 0.0, "", "")
        return patch.object(ai_opinion, "peace_verdict", side_effect=verdict)

    def offers(self, section, nation, enemy, *, appetite, leverage):
        bag = ai_candidates.Collector(nation, {})
        with patch.object(ai_opinion, "peace_appetite", return_value=appetite), \
                patch.object(ai_diplomacy.war_score, "for_treaty",
                             return_value={"mine": leverage, "theirs": 1.0 - leverage}):
            section(bag, self.game, nation, [enemy], [nation, enemy], self.world)
        return [candidate for candidate in bag.ranked() if candidate.action == "PEACE_TREATY"]

    def losing_offers(self, appetite=1.0):
        return self.offers(ai_diplomacy._offer_peace_when_losing, "AV", "FOE",
                           appetite=appetite, leverage=0.2)

    def winning_offers(self, leverage=0.8):
        return self.offers(ai_diplomacy._offer_terms_when_winning, "FOE", "AV",
                           appetite=0.1, leverage=leverage)

    def conceded(self, appetite):
        return self.moved(ai_diplomacy._concession_terms(self.game, "AV", "FOE", appetite, 0.2))


class ConcessionTests(Overrun, unittest.TestCase):
    """The more a loser wants out, the more of its lost land it gives up."""

    def test_a_clearly_losing_ai_offers_at_least_one_tile_at_the_threshold(self):
        self.assertEqual(self.conceded(ai_tuning.AI_PEACE_OFFER_THRESHOLD), self.ids(self.taken[:1]))

    def test_at_full_desperation_it_concedes_everything_occupied(self):
        self.assertEqual(self.conceded(1.0), self.ids(self.taken))

    def test_in_between_it_gives_up_the_least_valuable_land_first(self):
        halfway = (ai_tuning.AI_PEACE_OFFER_THRESHOLD + 1.0) / 2
        selected = self.conceded(halfway)
        self.assertGreater(len(selected), 1)
        self.assertLess(len(selected), len(self.taken))
        self.assertEqual(selected, self.ids(self.taken[:len(selected)]))

    def test_the_concession_never_shrinks_as_desperation_grows(self):
        steps = [ai_tuning.AI_PEACE_OFFER_THRESHOLD + (1.0 - ai_tuning.AI_PEACE_OFFER_THRESHOLD) * k / 8
                 for k in range(9)]
        sizes = [len(self.conceded(appetite)) for appetite in steps]
        self.assertEqual(sizes, sorted(sizes))

    def test_land_it_still_holds_is_never_on_the_table(self):
        self.assertNotIn(str(self.kept["id"]), self.conceded(1.0))

    def test_signed_terms_leave_the_conceded_land_with_its_holder(self):
        """Through the same execution path a signed treaty takes. The rest of
        the occupied land goes home, as a white peace sends it."""
        halfway = (ai_tuning.AI_PEACE_OFFER_THRESHOLD + 1.0) / 2
        terms = ai_diplomacy._concession_terms(self.game, "AV", "FOE", halfway, 0.2)
        ceded = self.moved(terms)
        deal_effects.execute(self.game, terms)
        self.assertEqual(self.ids(p for p in self.taken if p["owner"] == "FOE"), ceded)
        self.assertEqual(self.kept["owner"], "AV")


class OwnJudgementTests(Overrun, unittest.TestCase):
    """Each AI reads its own verdict only, never the other side's."""

    def test_a_loser_sends_the_terms_it_would_sign(self):
        with self.judge(lambda nation, terms: True):
            offers = self.losing_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(self.moved(offers[0].payload["parameters"]), self.ids(self.taken))
        self.assertEqual(set(self.asked), {"AV"})

    def test_a_loser_sends_nothing_it_would_refuse_itself(self):
        with self.judge(lambda nation, terms: False):
            self.assertEqual(self.losing_offers(), [])

    def test_a_loser_below_the_threshold_sends_nothing(self):
        with self.judge(lambda nation, terms: True):
            self.assertEqual(self.losing_offers(appetite=ai_tuning.AI_PEACE_OFFER_THRESHOLD - 0.01), [])

    def test_a_winner_offers_to_keep_what_it_holds(self):
        with self.judge(lambda nation, terms: True):
            offers = self.winning_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(self.moved(offers[0].payload["parameters"]), self.ids(self.taken))
        self.assertEqual(set(self.asked), {"FOE"})

    def test_a_winner_that_would_rather_fight_on_offers_nothing(self):
        with self.judge(lambda nation, terms: False):
            self.assertEqual(self.winning_offers(), [])

    def test_a_loser_concedes_its_single_occupied_province(self):
        for province in self.taken[1:]:
            province["owner"] = "AV"
        with self.judge(lambda nation, terms: True):
            offers = self.losing_offers(appetite=ai_tuning.AI_PEACE_OFFER_THRESHOLD)
        self.assertEqual(len(offers), 1)
        self.assertEqual(self.moved(offers[0].payload["parameters"]), self.ids(self.taken[:1]))

    def test_itemized_offer_is_displayed_and_applied_with_the_same_terms(self):
        self.game.session.active_players = ["FOE"]
        self.game.session.player_country = "FOE"
        for province in self.taken[1:]:
            province["owner"] = "AV"
        with self.judge(lambda nation, terms: True):
            offers = self.losing_offers(appetite=ai_tuning.AI_PEACE_OFFER_THRESHOLD)
        pending = self.game.world.nation_data["AV"].setdefault("pending_diplomacy", {})
        ai_diplomacy._execute_candidates(self.game, "AV", pending, offers)
        self.game.run_turn()
        inbox = self.game.world.nation_data["FOE"]["inbox"]
        delivered = next(message for message in inbox
                         if message["sender"] == "AV" and message.get("action") == "PEACE_TREATY")
        self.assertEqual(self.moved(delivered["parameters"]), self.ids(self.taken[:1]))
        self.game.answer("FOE", "AV", diplomacy_messages.RESPONSE_ACCEPT, "PEACE_TREATY")
        self.game.run_turn()
        self.assertEqual(self.taken[0]["owner"], "FOE")
        self.assertNotIn("FOE", self.game.world.nation_data["AV"]["at_war_with"])

    def test_a_winner_with_little_leverage_offers_nothing(self):
        with self.judge(lambda nation, terms: True):
            self.assertEqual(self.winning_offers(leverage=0.4), [])


class DeliveredOfferTests(Overrun, unittest.TestCase):
    """A country holding the enemy's delivered terms answers them instead of
    sending its own back across the table in the same turn."""

    def sued(self):
        bag = ai_candidates.Collector("AV", {}, context=self.game)
        with self.judge(lambda nation, terms: True), \
                patch.object(ai_opinion, "peace_appetite", return_value=1.0):
            ai_diplomacy._offer_peace_when_losing(bag, self.game, "AV", ["FOE"],
                                                  ["AV", "FOE"], self.world)
        return [cand for cand in bag.ranked() if cand.action == "PEACE_TREATY"]

    def test_a_delivered_peace_offer_blocks_a_mirror_offer(self):
        self.assertEqual(len(self.sued()), 1, "the fixture must offer without one")
        self.game.world.nation_data["FOE"]["pending_diplomacy"]["AV"] = {
            "action": "PEACE_TREATY", "turns": 1}
        self.assertEqual(self.sued(), [])

    def test_an_offer_still_being_drafted_does_not(self):
        """Only a delivered offer counts; a draft has not reached AV yet."""
        self.assertFalse(ai_candidates.mirrors_waiting_proposal(
            {"FOE": {"pending_diplomacy": {"AV": {"action": "PEACE_TREATY", "turns": 0}}}},
            "AV", "FOE", "PEACE_TREATY"))


class OccupationAppetiteTests(unittest.TestCase):
    """Losing homeland pushes a nation toward peace, not only its army."""

    def test_an_occupied_homeland_raises_the_wish_for_peace(self):
        game = StubMapScreen(["AV", "FOE"], human_players=())
        provs = [game.add_province("AV", cores=["AV"]) for _ in range(3)]
        for nation in ("AV", "FOE"):
            war_actions.save_own_pre_war_map(game.world.map_data, game.world.nation_data, nation)
        game.set_war("AV", "FOE")

        def appetite():
            world = ai_world.AIWorld(game.world.map_data, game.world.nation_data, game.world.id_to_province)
            return ai_opinion.peace_appetite(world, "AV", "FOE")

        intact = appetite()
        for prov in provs:
            prov["owner"] = "FOE"
        self.assertGreater(appetite(), intact)


class SeparatePeaceVerdictTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(("Member", "Ally", "Enemy", "Opponent"), human_players=())
        self.game.set_faction("Pact", "Ally", "Member")
        self.game.set_faction("Opposition", "Enemy", "Opponent")
        for country in ("Ally", "Member"):
            self.game.set_war(country, "Enemy")
        self.data = self.game.world.nation_data
        self.taken = self.game.add_province("Member", cores=["Member"])
        for _ in range(2):
            self.game.add_province("Member", cores=["Member"])
        self.game.home_of("Member")["cores"] = ["Member"]
        self.game.border(self.game.home_of("Ally")["id"], self.taken["id"])
        war_actions.save_own_pre_war_map(self.game.world.map_data, self.data, "Member")
        self.taken["owner"] = "Enemy"

    def terms(self, proposer, receiver, *clauses):
        mine, theirs = peace_scope.deal_sides(proposer, receiver, self.data)
        agreement = deal.new(deal.KIND_PEACE, mine, theirs, clauses or [deal.white_peace()])
        return peace_scope.with_separate_peace_cost(agreement, proposer, receiver, self.data)

    def verdict(self, agreement):
        world = ai_world.build(self.game)
        return ai_opinion.peace_verdict(world, "Member", "Enemy", agreement)

    def test_exactly_one_quarter_qualifies_in_both_directions_even_in_a_new_war(self):
        directions = (("Enemy", "Member"), ("Member", "Enemy"))
        with patch.object(ai_tuning, "AI_PEACE_MARGIN_BASE", 0), \
                patch.object(ai_tuning, "AI_PEACE_MARGIN_CAUTION", 0), \
                patch.object(ai_tuning, "AI_PEACE_PRIZE_W", 0), \
                patch.object(deal, "clause_value", return_value=0):
            for proposer, receiver in directions:
                self.assertTrue(self.verdict(self.terms(proposer, receiver)).accepted)
            self.game.add_province("Member", cores=["Member"])
            for proposer, receiver in directions:
                self.assertFalse(self.verdict(self.terms(proposer, receiver)).accepted)

    def test_supplied_allies_in_range_raise_the_value_of_fighting_for_ceded_land(self):
        from data.queries import supply

        tile = self.taken["id"]
        terms = self.terms("Enemy", "Member", deal.tiles_clause("Member", "Enemy", [tile]))
        restored = self.terms("Enemy", "Member")
        ally = self.game.home_of("Ally")
        ally["units"].append({"owner": "Ally", "type": "", "health": 100, "attack": 20,
                              "defense": 20, "speed": 1})
        with patch.object(supply, "SupplySnapshot", return_value=SimpleNamespace(
                status=lambda _unit: supply.SupplyStatus((1.0, 1.0, 1.0), 1.0))):
            world = ai_world.build(self.game)
            worth = deal.side_worth(terms, "Member", world.map_data, self.data)
            _, aid = ai_opinion._peace_continuation_value(world, "Member", terms, "Member", worth)
            self.assertGreater(aid, 0)
            self.assertEqual(ai_opinion._peace_continuation_value(
                world, "Member", restored, "Member", worth)[1], 0)
            after = ai_opinion.peace_verdict(world, "Member", "Enemy", terms)
            with patch.object(world, "allied_relief_value", return_value=0):
                before = ai_opinion.peace_verdict(world, "Member", "Enemy", terms)
            self.assertLess(after.slack, before.slack)
            margin = ai_tuning.AI_PEACE_MARGIN_BASE + (before.slack + after.slack) / 2
            with patch.object(ai_tuning, "AI_PEACE_MARGIN_BASE", margin):
                self.assertFalse(ai_opinion.peace_verdict(world, "Member", "Enemy", terms).accepted)
                with patch.object(world, "allied_relief_value", return_value=0):
                    self.assertTrue(ai_opinion.peace_verdict(world, "Member", "Enemy", terms).accepted)


if __name__ == "__main__":
    unittest.main()
