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


class LayoutTests(DealScreenTestCase):
    """Nothing may be drawn on top of anything else, or outside the panel.

    The screen shipped with five separate collisions and nobody could see any of
    them from the code: every position was a hand-picked offset off panel_rect
    and no test ever compared two of them. The 28px column heading was blitted
    four pixels above the 18px row label at the same x, so "YOU RECEIVE" and
    "Provinces:" were printed over each other; the hint line landed inside the
    first toggle; the verdict clipped the Send button; and Send itself hung six
    pixels below the panel. This is the same trick test_editor_menu_layout plays
    on the left bar, for the same reason.
    """

    def rects(self, screen):
        boxes = [(f"input {key}", rect) for key, rect in screen.input_rects().items()]
        boxes += [(getattr(el, "text", "button"), el.rect) for el in screen.elements
                  if getattr(el, "rect", None) is not None
                  and screen.panel_rect.colliderect(el.rect)]
        return boxes

    def loaded(self):
        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.give_ids.add(self.my_province()["id"])
        screen.vassalize = True
        screen.refresh_ui()
        return screen

    def test_no_two_controls_share_ground(self):
        boxes = self.rects(self.loaded())
        self.assertGreater(len(boxes), 5, "nothing was laid out at all")
        for i, (name_a, rect_a) in enumerate(boxes):
            for name_b, rect_b in boxes[i + 1:]:
                if rect_a.colliderect(rect_b):
                    self.fail(f"{name_a} at {tuple(rect_a)} overlaps "
                              f"{name_b} at {tuple(rect_b)}")

    def test_every_control_is_inside_the_panel(self):
        screen = self.loaded()
        for name, rect in self.rects(screen):
            self.assertTrue(screen.panel_rect.contains(rect),
                            f"{name} at {tuple(rect)} leaves the panel "
                            f"{tuple(screen.panel_rect)}")

    def test_the_panel_stays_on_screen(self):
        panel = self.screen().panel_rect
        self.assertGreaterEqual(panel.x, 0)
        self.assertGreaterEqual(panel.y, c.TOP_UI_HEIGHT)
        self.assertLessEqual(panel.right, c.SCREEN_WIDTH)
        self.assertLessEqual(panel.bottom, c.SCREEN_HEIGHT - c.BOT_UI_HEIGHT)

    def test_a_bloc_wide_title_still_fits_the_window(self):
        """It used to join both sides' full rosters and hand the result to
        draw_centered_title, which centres on the screen and never clips -- so a
        fourteen-nation peace ran off both edges at once."""
        from map_logic.rendering.font_manager import fonts

        for i in range(12):
            self.map.nation_data.setdefault(f"Ally{i}", dict(self.map.nation_data[self.player]))
        screen = self.screen()
        screen.my_side = [self.player] + [f"Ally{i}" for i in range(12)]
        screen.their_side = [self.enemy]
        screen.role = "BLOC_LEADER"

        width = fonts.get("heading1").size(screen.get_panel_title())[0]
        self.assertLess(width, c.SCREEN_WIDTH)


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
    def greedy(self):
        screen = self.screen()
        for prov in self.map.map_data.values():
            if prov.get("owner") == self.enemy:
                screen.take_ids.add(prov["id"])
        screen.refresh_ui()
        return screen

    def test_a_status_quo_offer_reads_as_more_acceptable_than_a_land_grab(self):
        """The acceptance line asks exactly what the engine will ask when the
        answer comes back. The old screen asked a different function, which
        refused any claims demand outright -- so it could say REJECT and then
        watch the AI accept."""
        gentle = self.screen()
        gentle.refresh_ui()

        self.assertNotEqual(gentle.verdict_text, "")
        self.assertFalse(self.greedy().verdict_accepted,
                         "demanding their whole country should not read as acceptable")

    def test_the_verdict_matches_what_the_engine_would_decide(self):
        from map_logic.ai import ai_opinion

        screen = self.screen()
        screen.take_ids.add(self.their_province()["id"])
        screen.refresh_ui()

        engine = ai_opinion.accepts_peace(screen.world, self.enemy, self.player,
                                          screen.build_deal(), self.map.scenario_settings)
        self.assertEqual(screen.verdict_accepted, engine)

    def test_the_verdict_is_graded_rather_than_a_yes_or_no(self):
        """The whole point of the exercise. A single ACCEPT/REFUSE word makes the
        negotiation a lock to be picked: nudge a number until it flips, then
        send. Five steps, and a sentence saying which term is deciding it."""
        screen = self.greedy()
        filled, total = screen.verdict_dots
        self.assertEqual(total, len(c.AI_VERDICT_BANDS))
        self.assertTrue(1 <= filled <= total)

    def test_the_verdict_says_why(self):
        screen = self.greedy()
        self.assertIn("--", screen.verdict_text)
        self.assertGreater(len(screen.verdict_text.split("--")[1].strip()), 10)

    def test_a_worse_offer_scores_worse(self):
        """Read off the slack rather than the dots: both offers can land in the
        same bucket without the underlying reading being the same."""
        gentle = self.screen()
        gentle.refresh_ui()
        self.assertLess(self.greedy().verdict_slack, gentle.verdict_slack)

    def test_a_trade_gets_a_verdict_too(self):
        """It got no line at all -- the branch set verdict_text to "" -- which
        is the one screen where the player most needs to know."""
        screen = self.screen(kind=deal_mod.KIND_TRADE)
        screen.give_mats_str = "4000"
        screen.refresh_ui()

        self.assertTrue(screen.verdict_text)
        self.assertIsNotNone(screen.verdict_dots)


class ProjectedMapTests(DealScreenTestCase):
    """The treaty preview colours the countries in the deal and greys the rest.

    It used to draw an ellipse over the ordinary political map for each province
    that changed hands -- a scattering of dots among two hundred countries
    painted exactly as they always are, which shows where a treaty bites and
    nothing at all about who it is between.
    """

    def treaty_screen(self):
        from map_logic.diplomacy import deal as dm
        from screens.map_related_screens.peace_screen import View_Peace_Treaty_Screen

        # They are demanding one of ours, so the preview has something to repaint.
        wanted = self.my_province()["id"]
        agreement = dm.new(dm.KIND_PEACE, [self.enemy], [self.player],
                           [dm.white_peace(),
                            dm.tiles_clause(self.player, self.enemy, [wanted])])
        self.map.nation_data[self.enemy]["pending_diplomacy"][self.player] = {
            "action": "PEACE_TREATY", "turns": 1, "parameters": agreement}
        return View_Peace_Treaty_Screen(self.map, self.enemy), wanted

    def test_the_terms_box_is_sized_to_the_terms_and_stays_on_screen(self):
        """It was a fixed 460px wide with the height derived from the raw line
        count, no wrapping and no clip -- so a bloc treaty's terms ran off the
        right of the window and past the bottom of the screen at about
        twenty-six of them."""
        screen, _wanted = self.treaty_screen()
        screen.terms = [f"a term about province {i} and who it belongs to now"
                        for i in range(60)]
        screen.lines = screen._wrapped()
        screen.draw(self.surface)

        self.assertLessEqual(screen.panel_rect.bottom, c.SCREEN_HEIGHT)
        self.assertLessEqual(screen.panel_rect.right, c.SCREEN_WIDTH)

    def test_a_long_treaty_can_be_scrolled(self):
        screen, _wanted = self.treaty_screen()
        screen.terms = [f"term {i}" for i in range(60)]
        screen.lines = screen._wrapped()
        screen.panel_rect.height = screen.PANEL.height
        screen.draw(self.surface)

        self.assertLess(screen.max_scroll, 0, "there is more text than room for it")
        self.assertTrue(screen.is_over_ui(screen.panel_rect.center),
                        "the wheel has to reach the list, not the camera")

    def test_the_preview_paints_and_restores_the_players_own_map(self):
        screen, _wanted = self.treaty_screen()
        before = self.map.active_map
        screen.draw(self.surface)
        self.assertIs(self.map.active_map, before,
                      "the preview outlived the screen that wanted it")

    def test_a_bystander_is_greyed_and_a_party_is_not(self):
        from map_logic.rendering import refresh_map

        others = [n for n in self.map.nation_data
                  if isinstance(self.map.nation_data[n], dict)
                  and n not in (self.player, self.enemy)
                  and any(p.get("owner") == n for p in self.map.map_data.values())]
        self.assertTrue(others, "need a nation outside the deal")

        painted = {}
        original = refresh_map._build_map_surface

        def spy(map_screen, get_data):
            for prov in map_screen.map_data.values():
                painted[prov["id"]] = get_data(prov)
            return original(map_screen, get_data)

        refresh_map._build_map_surface = spy
        try:
            screen, wanted = self.treaty_screen()
            screen.draw(self.surface)
        finally:
            refresh_map._build_map_surface = original

        outsider = next(p for p in self.map.map_data.values()
                        if p.get("owner") == others[0])
        self.assertEqual(painted[outsider["id"]][1], refresh_map.BYSTANDER_COLOR)

        mine = self.my_province()
        self.assertNotEqual(painted[mine["id"]][1], refresh_map.BYSTANDER_COLOR)

    def test_a_transferred_province_is_painted_for_its_new_owner(self):
        from map_logic.rendering import refresh_map

        painted = {}
        original = refresh_map._build_map_surface

        def spy(map_screen, get_data):
            for prov in map_screen.map_data.values():
                painted[prov["id"]] = get_data(prov)
            return original(map_screen, get_data)

        refresh_map._build_map_surface = spy
        try:
            screen, wanted = self.treaty_screen()
            screen.draw(self.surface)
        finally:
            refresh_map._build_map_surface = original

        # The clause hands one of the player's provinces to the enemy; the
        # preview has to show it in the enemy's colour, not the player's.
        self.assertEqual(self.map.id_to_province[wanted].get("owner"), self.player,
                         "nothing has actually changed hands yet")
        self.assertEqual(painted[wanted][0], self.enemy)
        self.assertEqual(painted[wanted][1],
                         self.map.nation_colors.get(self.enemy))


if __name__ == "__main__":
    unittest.main()
