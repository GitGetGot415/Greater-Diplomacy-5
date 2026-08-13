"""Builds and paints the deal builder against a real scenario.

The map-layered diplomacy overlays are opened through _run_pygame_sub_screen
rather than living in Controller.states, so test_screen_smoke has never been
able to reach any of them -- the screens that draw over the live map, hit-test
provinces and price a treaty every keystroke were the ones with no coverage at
all. This drives the new one: assemble terms, pick provinces off the map, paint
it, and pump the events it keys off.
"""

import unittest

import pygame

import data.constants as c
from data import queries
from map_logic.diplomacy import deal as deal_mod
from tests import app_harness


class DealScreenTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        from map_logic.diplomacy.war_actions import link_war

        self.surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        # app_harness.boot_map() hands back one shared Map for the whole run, and
        # earlier modules move provinces around on it -- so who owns what is
        # settled here, from the live map, rather than cached from whatever the
        # scenario looked like when it was first loaded.
        landed = [n for n in sorted(queries.get_living_nations(self.map.map_data))
                  if n not in c.UNPLAYABLE_NATIONS and n in self.map.nation_data]
        self.assertGreaterEqual(len(landed), 2, "need two nations holding land")
        self.player, self.enemy = landed[0], landed[1]

        self.map.player_country = self.player
        self.map.active_players = [self.player]
        self.map.selected_province = self.my_province()

        for nation in (self.player, self.enemy):
            data = self.map.nation_data[nation]
            data["at_war_with"] = []
            data["pending_diplomacy"] = {}
            data["faction"] = ""
            data["is_faction_leader"] = False
            data["master"] = ""
            data.setdefault("war_durations", {})
        link_war(self.map.nation_data, self.player, self.enemy)
        self.map.nation_data[self.player]["war_durations"][self.enemy] = 10
        self.map.nation_data[self.enemy]["war_durations"][self.player] = 10

    def screen(self, kind=deal_mod.KIND_PEACE):
        from screens.map_related_screens.deal_screen import Deal_Screen
        return Deal_Screen(self.map, self.enemy, kind)

    def their_province(self):
        return next(p for p in self.map.map_data.values() if p.get("owner") == self.enemy)

    def my_province(self):
        return next(p for p in self.map.map_data.values() if p.get("owner") == self.player)


class RenderTests(DealScreenTestCase):
    def test_a_peace_deal_builds_and_paints(self):
        screen = self.screen()
        screen.refresh_ui()
        screen.draw(self.surface)

    def test_a_trade_builds_and_paints(self):
        screen = self.screen(deal_mod.KIND_TRADE)
        screen.refresh_ui()
        screen.draw(self.surface)

    def test_it_paints_with_terms_on_the_table(self):
        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.give_ids.add(self.my_province()["id"])
        screen.take_mats_str = "2400"
        screen.vassalize = True
        screen.demilitarize = True
        screen.refresh_ui()
        screen.draw(self.surface)

    def test_it_survives_an_idle_event_pump(self):
        screen = self.screen()
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEMOTION, pos=(400, 300), rel=(1, 1),
                               buttons=(0, 0, 0)),
            pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False,
                               precise_x=0.0, precise_y=-1.0),
        ])
        screen.draw(self.surface)

    def test_the_leverage_bar_is_only_for_wars(self):
        self.assertIsNotNone(self.screen().leverage)
        self.assertIsNone(self.screen(deal_mod.KIND_TRADE).leverage)


class PickingTests(DealScreenTestCase):
    def test_picking_toggles_a_province_in_and_out(self):
        screen = self.screen()
        screen.set_picking("TAKE")
        target = self.their_province()

        screen.toggle_province(target)
        self.assertIn(target["id"], screen.take_ids)
        screen.toggle_province(target)
        self.assertNotIn(target["id"], screen.take_ids)

    def test_you_cannot_demand_your_own_territory(self):
        screen = self.screen()
        screen.set_picking("TAKE")
        screen.toggle_province(self.my_province())
        self.assertEqual(screen.take_ids, set())

    def test_you_cannot_offer_theirs(self):
        screen = self.screen()
        screen.set_picking("GIVE")
        screen.toggle_province(self.their_province())
        self.assertEqual(screen.give_ids, set())

    def test_picking_the_same_column_twice_turns_it_off(self):
        screen = self.screen()
        screen.set_picking("TAKE")
        screen.set_picking("TAKE")
        self.assertIsNone(screen.picking)


class AssemblyTests(DealScreenTestCase):
    def test_an_untouched_peace_screen_offers_a_white_peace(self):
        agreement = self.screen().build_deal()
        self.assertTrue(deal_mod.is_white_peace(agreement))
        self.assertEqual(deal_mod.validate(agreement, self.map.map_data,
                                           self.map.nation_data), [])

    def test_every_control_turns_into_a_clause(self):
        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.give_ids.add(self.my_province()["id"])
        screen.take_mats_str = "2400"
        screen.give_fuel_str = "800"
        screen.vassalize = True
        screen.demilitarize = True
        screen.military_access = True

        kinds = [cl["type"] for cl in deal_mod.clauses(screen.build_deal())]
        for expected in (deal_mod.WHITE_PEACE, deal_mod.TILES, deal_mod.RESOURCES,
                         deal_mod.VASSALIZE, deal_mod.DEMILITARIZE,
                         deal_mod.MILITARY_ACCESS):
            self.assertIn(expected, kinds)

    def test_the_assembled_deal_is_always_valid(self):
        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.take_fuel_str = "500"
        self.assertEqual(deal_mod.validate(screen.build_deal(), self.map.map_data,
                                           self.map.nation_data), [])

    def test_a_trade_carries_no_white_peace(self):
        screen = self.screen(deal_mod.KIND_TRADE)
        screen.take_mats_str = "100"
        kinds = [cl["type"] for cl in deal_mod.clauses(screen.build_deal())]
        self.assertNotIn(deal_mod.WHITE_PEACE, kinds)

    def test_demanded_and_offered_land_move_in_opposite_directions(self):
        screen = self.screen()
        theirs, mine = self.their_province(), self.my_province()
        screen.take_ids.add(theirs["id"])
        screen.give_ids.add(mine["id"])

        transfers = deal_mod.tile_transfers(screen.build_deal())
        self.assertEqual(transfers[theirs["id"]], self.player)
        self.assertEqual(transfers[mine["id"]], self.enemy)

    def test_sending_queues_the_deal_as_the_offers_terms(self):
        from map_logic.diplomacy import diplomacy_messages

        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.confirm()

        pending = diplomacy_messages.get_pending(self.map.nation_data, self.player, self.enemy)
        self.assertEqual(pending.get("action"), "PEACE_TREATY")
        self.assertTrue(deal_mod.is_deal(pending.get("parameters")))

    def test_a_bare_status_quo_is_sent_as_a_ceasefire(self):
        from map_logic.diplomacy import diplomacy_messages

        screen = self.screen()
        screen.confirm()
        self.assertEqual(
            diplomacy_messages.get_pending(self.map.nation_data, self.player, self.enemy)
            .get("action"), "CEASEFIRE")

    def test_reopening_an_offer_restores_its_terms(self):
        first = self.screen()
        wanted = self.their_province()["id"]
        first.take_ids.add(wanted)
        first.take_mats_str = "1500"
        first.confirm()

        reopened = self.screen()
        self.assertTrue(reopened.is_editing)
        self.assertIn(wanted, reopened.take_ids)
        self.assertEqual(reopened.take_mats_str, "1500")


class VerdictTests(DealScreenTestCase):
    def test_a_status_quo_offer_reads_as_more_acceptable_than_a_land_grab(self):
        """The acceptance line asks exactly what the engine will ask when the
        answer comes back. The old screen asked a different function, which
        refused any claims demand outright -- so it could say REJECT and then
        watch the AI accept."""
        gentle = self.screen()
        gentle.refresh_ui()

        greedy = self.screen()
        for prov in self.map.map_data.values():
            if prov.get("owner") == self.enemy:
                greedy.take_ids.add(prov["id"])
        greedy.refresh_ui()

        self.assertNotEqual(gentle.verdict_text, "")
        self.assertIn("REFUSE", greedy.verdict_text,
                      "demanding their whole country should not read as acceptable")

    def test_the_verdict_matches_what_the_engine_would_decide(self):
        from map_logic.ai import ai_opinion

        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.refresh_ui()

        engine = ai_opinion.accepts_peace(screen.world, self.enemy, self.player,
                                          screen.build_deal(), self.map.scenario_settings)
        self.assertEqual("ACCEPT" in screen.verdict_text, engine)


if __name__ == "__main__":
    unittest.main()
