"""Which peace terms an AI puts forward, and when.

A losing AI used to offer only a white peace. A white peace hands every occupied
province back (deal_effects.restore_occupied), so the offer asked a clear winner
to give up everything it had taken, and the winner always refused. A winning AI
never offered terms at all. Wars against a clear winner ran until the loser was
gone.

The verdicts are patched here, so these tests pin down which terms are chosen
and who is asked, apart from the tuning of ai_opinion.peace_verdict itself
(tests/test_ai_opinion.py covers that arithmetic).
"""

import unittest
from unittest.mock import patch

import data.constants as c
from map_logic.ai import ai_candidates, ai_diplomacy, ai_opinion, ai_world
from map_logic.diplomacy import deal, deal_effects, war_actions
from tests.stub_map_screen import StubMapScreen


class Overrun:
    """FOE has overrun two of AV's provinces. Shared by the test classes below."""

    HUMANS = ()

    def setUp(self):
        self.game = StubMapScreen(["AV", "FOE"], human_players=self.HUMANS)
        self.taken = [self.game.add_province("AV", cores=["AV"]) for _ in range(2)]
        self.kept = self.game.add_province("AV", cores=["AV"])
        self.game.border(self.game.home_of("AV")["id"], self.game.home_of("FOE")["id"],
                         *(p["id"] for p in self.taken), self.kept["id"])
        for nation in ("AV", "FOE"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_war("AV", "FOE")
        for a, b in (("AV", "FOE"), ("FOE", "AV")):
            self.game.nation_data[a]["war_durations"] = {b: c.MIN_TURNS_FOR_CEASEFIRE}
        for prov in self.taken:
            prov["owner"] = "FOE"
        self.world = ai_world.AIWorld(self.game.map_data, self.game.nation_data,
                                      self.game.id_to_province)
        self.asked = []

    def moved(self, terms):
        return {str(prov_id) for prov_id
                in deal.tile_transfers(terms, self.game.map_data, self.game.nation_data)}

    def taken_ids(self):
        return {str(p["id"]) for p in self.taken}

    def judge(self, accepts):
        """A stand-in peace_verdict: `accepts(nation, terms)` decides."""
        def verdict(_world, nation, _proposer, terms, _settings=None):
            self.asked.append(nation)
            return ai_opinion.Peace(accepts(nation, terms), 0.0, "", "")
        return patch.object(ai_opinion, "peace_verdict", side_effect=verdict)

    def offers(self, section, nation, enemy, *, appetite, leverage):
        bag = ai_candidates.Collector(nation, {})
        with patch.object(ai_opinion, "peace_appetite", return_value=appetite), \
                patch.object(ai_diplomacy.war_score, "between",
                             return_value={"mine": leverage, "theirs": 1.0 - leverage}):
            section(bag, self.game, nation, [enemy], [nation, enemy], self.world)
        return [candidate for candidate in bag.ranked() if candidate.action == "PEACE_TREATY"]

    def losing_offers(self):
        return self.offers(ai_diplomacy._offer_peace_when_losing, "AV", "FOE",
                           appetite=0.95, leverage=0.2)

    def winning_offers(self):
        return self.offers(ai_diplomacy._offer_terms_when_winning, "FOE", "AV",
                           appetite=0.1, leverage=0.8)



class PeaceOfferTests(Overrun, unittest.TestCase):
    # --- the terms ---------------------------------------------------------

    def test_status_quo_terms_hand_over_exactly_what_is_occupied(self):
        terms = ai_diplomacy._status_quo_terms(self.game, "AV", "FOE")
        self.assertEqual(self.moved(terms), self.taken_ids())

    def test_and_executing_them_leaves_the_holder_in_place(self):
        """Through the same execution path a signed treaty takes."""
        deal_effects.execute(self.game, ai_diplomacy._status_quo_terms(self.game, "AV", "FOE"))
        self.assertTrue(all(prov["owner"] == "FOE" for prov in self.taken))
        self.assertEqual(self.kept["owner"], "AV")

    # --- the losing side ---------------------------------------------------

    def test_a_loser_offers_the_cheapest_terms_both_sides_accept(self):
        with self.judge(lambda nation, terms: True):
            offers = self.losing_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(self.moved(offers[0].payload["parameters"]), set())

    def test_a_loser_concedes_the_occupied_land_when_the_winner_insists(self):
        def winner_wants_its_gains(nation, terms):
            return nation == "AV" or self.moved(terms) == self.taken_ids()
        with self.judge(winner_wants_its_gains):
            offers = self.losing_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(self.moved(offers[0].payload["parameters"]), self.taken_ids())

    def test_nothing_is_sent_when_no_terms_would_be_signed(self):
        """A refused offer spends the cooldown; an unsendable one is not sent."""
        with self.judge(lambda nation, terms: nation == "AV"):
            self.assertEqual(self.losing_offers(), [])

    def test_a_loser_does_not_sign_away_land_it_would_refuse_itself(self):
        with self.judge(lambda nation, terms: nation == "FOE"):
            self.assertEqual(self.losing_offers(), [])

    # --- the winning side --------------------------------------------------

    def test_a_winner_offers_to_keep_what_it_holds(self):
        with self.judge(lambda nation, terms: True):
            offers = self.winning_offers()
        self.assertEqual(len(offers), 1)
        self.assertEqual(self.moved(offers[0].payload["parameters"]), self.taken_ids())

    def test_a_winner_that_would_rather_fight_on_offers_nothing(self):
        with self.judge(lambda nation, terms: nation != "FOE"):
            self.assertEqual(self.winning_offers(), [])

    def test_a_winner_with_little_leverage_offers_nothing(self):
        with self.judge(lambda nation, terms: True):
            offers = self.offers(ai_diplomacy._offer_terms_when_winning, "FOE", "AV",
                                 appetite=0.1, leverage=0.4)
        self.assertEqual(offers, [])

    def test_both_sides_are_asked_when_both_are_ai(self):
        with self.judge(lambda nation, terms: True):
            self.winning_offers()
        self.assertEqual(set(self.asked), {"FOE", "AV"})


class HumanTargetTests(Overrun, unittest.TestCase):
    """A human's answer is never predicted: only the AI's own verdict is read."""

    HUMANS = ("AV",)

    def test_only_the_ai_is_asked(self):
        with self.judge(lambda nation, terms: True):
            offers = self.winning_offers()
        self.assertEqual(set(self.asked), {"FOE"})
        self.assertEqual(len(offers), 1)


class OccupationAppetiteTests(unittest.TestCase):
    """Item 13: losing homeland pushes a nation toward peace, not only its army."""

    def test_an_occupied_homeland_raises_the_wish_for_peace(self):
        game = StubMapScreen(["AV", "FOE"], human_players=())
        provs = [game.add_province("AV", cores=["AV"]) for _ in range(3)]
        for nation in ("AV", "FOE"):
            war_actions.save_own_pre_war_map(game.map_data, game.nation_data, nation)
        game.set_war("AV", "FOE")

        def appetite():
            world = ai_world.AIWorld(game.map_data, game.nation_data, game.id_to_province)
            return ai_opinion.peace_appetite(world, "AV", "FOE")

        intact = appetite()
        for prov in provs:
            prov["owner"] = "FOE"
        self.assertGreater(appetite(), intact)


if __name__ == "__main__":
    unittest.main()
