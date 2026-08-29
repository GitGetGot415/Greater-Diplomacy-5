"""The lane manager, against a real booted game.

tests/test_screen_smoke.py only walks controller.states, and this is a modal
pushed onto the stack rather than a registered state, so nothing else would ever
construct it. The build-and-paint half here is that missing coverage; the rest is
the part worth testing on its own -- that what the screen writes onto a unit is
read back by the resolver, and that an impossible order is ignored rather than
raising in the middle of a turn.
"""

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import data.constants as c
from data import queries
from map_logic.turn_processing import combat_rules
from screens.map_related_screens import battle_screen
from tests import app_harness


class BattleScreenTestCase(unittest.TestCase):
    """A real province, with a three-lane fight forced onto it.

    A and B are allies, so they share one side. X and Y are at war with the pair
    and with each other, so they are two separate sides rather than one -- which
    is what gives the player two lanes to choose between and the tile a third
    they are only watching.
    """

    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        game_map = self.map
        names = [n for n in game_map.nation_data
                 if queries.is_playable(n, game_map.nation_data)][:4]
        self.a, self.b, self.x, self.y = names

        for name, allies, enemies in ((self.a, [self.b], [self.x, self.y]),
                                      (self.b, [self.a], [self.x, self.y]),
                                      (self.x, [], [self.a, self.b, self.y]),
                                      (self.y, [], [self.a, self.b, self.x])):
            game_map.nation_data[name]["allied_with"] = list(allies)
            game_map.nation_data[name]["at_war_with"] = list(enemies)

        self.province = next(p for p in game_map.map_data.values()
                             if not queries.is_water_province(p))
        library = queries.get_unit_library()
        # More than a side's lane cap can seat, so there is always a genuine
        # reserve left over to list -- at COMBAT_WIDTH's current tuning a
        # smaller muster gets almost entirely fielded, leaving nothing behind
        # for the reserve-column tests to find.
        self.province["units"] = [queries.create_unit_dict("Infantry", name, library)
                                  for name in names for _ in range(8)]

        game_map.selected_province = self.province
        game_map.visible_provinces = None
        game_map.player_country = self.a
        self.addCleanup(self.province.pop, "units", None)

    def screen(self):
        return battle_screen.Battle_Screen(self.map, self.province)

    def battle(self):
        return combat_rules.build_battle([self.province["units"]], self.map.nation_data)

    def mine(self, battle):
        """The player's own half of the first side it fights on."""
        for lane in battle.lanes:
            for side in (lane.a, lane.b):
                if self.a in side.nations:
                    return next(m for m in side.members if m.nation == self.a)
        return None


class BuildAndPaintTests(BattleScreenTestCase):
    def test_the_screen_builds_and_paints(self):
        screen = self.screen()
        screen.refresh_ui()
        screen.draw(self.surface)

        self.assertTrue(screen.battle.lanes)
        self.assertTrue(screen.elements)

    def test_it_survives_an_idle_event_pump(self):
        screen = self.screen()
        screen.handle_events([pygame.event.Event(pygame.MOUSEMOTION, pos=(640, 360), rel=(0, 0),
                                                 buttons=(0, 0, 0)),
                              pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
        screen.draw(self.surface)

    def test_embedded_battle_builds_and_paints_beside_orders(self):
        from screens.map_related_screens.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()

        orders.draw(self.surface)

        self.assertIsNotNone(orders.battle_screen)
        self.assertTrue(orders.battle_screen.embedded)
        self.assertGreater(orders.battle_screen.panel_rect.x, orders.panel_rect.right)

    def test_combat_bubble_entry_opens_the_battle_inspector(self):
        from screens.map_related_screens.orders import Orders_Screen

        self.map._orders_entered_from_combat_bubble = True
        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)

        self.assertIsNotNone(orders.battle_screen)
        self.assertTrue(orders.battle_screen.embedded)
        self.assertFalse(hasattr(self.map, "_orders_entered_from_combat_bubble"))

    def test_combat_bubble_orders_exit_returns_to_the_map(self):
        from screens.map_related_screens.orders import Orders_Screen

        old_navigation = c.MAP_NAVIGATION_MODE
        self.addCleanup(setattr, c, "MAP_NAVIGATION_MODE", old_navigation)
        c.MAP_NAVIGATION_MODE = "CLASSIC"

        self.map._orders_entered_from_combat_bubble = True
        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.exit_screen()

        self.assertTrue(orders.done)
        self.assertEqual(orders.next_state, "MAP")
        self.assertIsNone(self.map.selected_province)

    def test_narrow_unit_stat_rows_wrap_complete_entries(self):
        from map_logic.rendering.font_manager import fonts
        from ui_elements import draw_wrapped_icon_row

        font = fonts.get("small")
        with mock.patch("ui_elements.scale_icon", return_value=None):
            _, final_y = draw_wrapped_icon_row(
                self.surface, font,
                [("Attack", "100"), ("Defense", "0 + 50"),
                 ("Health", "100"), ("Speed", "1")],
                10, 10, (200, 200, 200), max_width=100)

        self.assertGreater(final_y, 10)

    def test_unit_side_heading_uses_column_width_for_flags(self):
        from types import SimpleNamespace

        screen = self.screen()
        side = SimpleNamespace(nations=[self.a, self.b, self.x, self.y])
        rect = pygame.Rect(0, 100, 184, 100)
        with mock.patch.object(screen, "_paint_side_flags") as paint_flags:
            screen._paint_side_heading(self.surface, rect, side, "1/5")

        self.assertEqual(paint_flags.call_args.kwargs["max_flags"], 4)

    def test_selecting_the_other_lane_repaints(self):
        screen = self.screen()
        self.assertGreater(len(screen.battle.lanes), 1)

        screen._select(1)
        screen.draw(self.surface)

        self.assertEqual(screen.selected_lane, 1)

    def test_lane_outlook_is_rebuilt_for_the_selected_lane(self):
        screen = self.screen()
        self.assertIsInstance(screen.lane_outcome, dict)
        self.assertEqual(
            screen.outcome_rect.top,
            screen.regions[battle_screen.PANE_LANES].bottom + battle_screen.OUTCOME_GAP)

        with mock.patch.object(screen, "_estimate_lane_outcome",
                               wraps=screen._estimate_lane_outcome) as estimate:
            screen._select(1)

        self.assertEqual(estimate.call_args.args[0].index, 1)
        self.assertIsInstance(screen.lane_outcome, dict)

    def test_combat_outlook_estimate_identifies_the_expected_winner(self):
        from map_logic.rendering import overlay_renderer

        library = queries.get_unit_library()
        winner = queries.create_unit_dict("Infantry", self.a, library)
        loser = queries.create_unit_dict("Infantry", self.x, library)
        winner["attack"] = 1000
        loser["attack"] = 0

        outcome = overlay_renderer.estimated_combat_outcome(
            [[winner], [loser]], self.map.nation_data)

        self.assertEqual(outcome["winner_side"], 0)
        self.assertEqual(outcome["turns"], 1)

    def test_a_tile_with_no_fight_on_it_says_so_rather_than_raising(self):
        self.province["units"] = [
            queries.create_unit_dict("Infantry", self.a, queries.get_unit_library())]

        screen = self.screen()
        screen.draw(self.surface)

        self.assertEqual(screen.battle.lanes, [])

    def test_fog_of_war_hides_the_order_of_battle(self):
        self.map.visible_provinces = set()
        self.addCleanup(setattr, self.map, "visible_provinces", None)

        screen = self.screen()
        screen.draw(self.surface)

        self.assertFalse(screen.visible)
        # Nothing but the footer buttons: no lane rows, no unit rows.
        self.assertFalse([el for el in screen.elements if getattr(el, "pane", None)])


class LaneOrderTests(BattleScreenTestCase):
    def test_sending_a_unit_to_a_lane_is_read_back_by_the_resolver(self):
        screen = self.screen()
        lane = next(lane for lane in screen.battle.lanes
                    if self.a in lane.a.nations or self.a in lane.b.nations)
        far = lane.b if self.a in lane.a.nations else lane.a
        opponent = far.nations[0]

        unit = screen.bench()[0]
        screen.send_to_lane(unit, lane)

        self.assertEqual(unit["lane_target"], opponent)
        seated = {id(u) for l in self.battle().lanes
                  for side in (l.a, l.b) for u in side.front}
        self.assertIn(id(unit), seated)

    def test_holding_a_unit_back_keeps_it_out_of_the_front(self):
        screen = self.screen()
        unit = self.mine(screen.battle).front[0]

        screen.toggle_stance(unit)

        self.assertEqual(unit["combat_stance"], "RESERVE")
        self.assertNotIn(id(unit), {id(u) for u in self.mine(self.battle()).front})

    def test_holding_is_a_toggle(self):
        screen = self.screen()
        unit = self.mine(screen.battle).front[0]

        screen.toggle_stance(unit)
        screen.toggle_stance(unit)

        self.assertNotIn("combat_stance", unit)

    def test_clearing_lane_orders_removes_both_keys(self):
        screen = self.screen()
        for unit in screen.my_units():
            unit["lane_target"] = "somewhere"
            unit["combat_stance"] = "RESERVE"

        screen.clear_orders()

        for unit in screen.my_units():
            self.assertNotIn("lane_target", unit)
            self.assertNotIn("combat_stance", unit)

    def test_an_impossible_lane_target_is_ignored_rather_than_raising(self):
        """A pin survives in the save; the enemy it names may not survive the war."""
        for unit in [u for u in self.province["units"] if u["owner"] == self.a]:
            unit["lane_target"] = "A Nation That Is Not Here"

        battle = self.battle()

        self.assertIn(self.a, battle.engaged)
        self.assertTrue(self.mine(battle).front)

    def test_the_screen_only_offers_the_player_s_own_units(self):
        screen = self.screen()
        self.assertTrue(screen.my_units())
        for unit in screen.my_units():
            self.assertEqual(unit["owner"], self.a)


class SideReserveTests(BattleScreenTestCase):
    """The reserve column is the side's, not just ours.

    An ally's reserves are what steps into the front rank as it dies, so a side
    that reads three against six may be nothing of the kind. Listing only our own
    made every fight look like we were holding it alone.
    """

    def our_side(self, screen):
        _lane, near, _far = screen.current()
        return near

    def rows(self, screen):
        return [el for el in screen.elements
                if getattr(el, "pane", None) == battle_screen.PANE_RESERVE]

    def test_our_ally_s_reserves_are_listed_beside_ours(self):
        screen = self.screen()

        owners = {u["owner"] for u in screen.side_bench(self.our_side(screen))}

        self.assertIn(self.a, owners)
        self.assertIn(self.b, owners)

    def test_ours_come_first(self):
        """The rows a player can actually act on are the ones at the top."""
        screen = self.screen()
        bench = screen.side_bench(self.our_side(screen))

        self.assertEqual([u["owner"] for u in bench[:len(screen.bench())]],
                         [self.a] * len(screen.bench()))

    def test_nobody_from_the_other_side_is_on_it(self):
        screen = self.screen()
        _lane, _near, far = screen.current()

        owners = {u["owner"] for u in screen.side_bench(self.our_side(screen))}

        self.assertFalse(owners & set(far.nations))

    def test_a_unit_already_fighting_is_not_in_reserve(self):
        screen = self.screen()
        seated = screen.seated()

        for unit in screen.side_bench(self.our_side(screen)):
            self.assertNotIn(id(unit), seated)

    def test_an_ally_s_row_is_dead(self):
        """They are not ours to move -- the whole reason they can be shown."""
        screen = self.screen()
        theirs = {id(u) for u in screen.side_bench(self.our_side(screen))
                  if u["owner"] != self.a}

        self.assertTrue(theirs)
        for rect, (unit, _note) in screen.row_paint[battle_screen.PANE_RESERVE]:
            if id(unit) in theirs:
                row = next(el for el in self.rows(screen) if el.rect == rect)
                self.assertTrue(getattr(row, "disabled", False))

    def test_our_own_rows_still_send_units_to_the_lane(self):
        screen = self.screen()
        editable = [el for el in self.rows(screen) if not getattr(el, "disabled", False)]

        # The outlook footer consumes enough vertical room for a full reserve
        # row to scroll below the first view. The rows remain editable, and the
        # signed scroll limit exposes the rest of them.
        self.assertTrue(editable)
        self.assertLessEqual(len(editable), len(screen.bench()))
        self.assertLess(screen.pane_scroll_limit(battle_screen.PANE_RESERVE), 0)

    def test_the_heading_counts_both(self):
        screen = self.screen()
        screen.draw(self.surface)

        allied = len(screen.side_bench(self.our_side(screen))) - len(screen.bench())
        self.assertTrue(allied)

    def test_in_tactical_mode_the_rest_of_the_host_country_shows_too(self):
        """One division is the player's; the other four are their host's, and
        the front column already lists them without giving anything away."""
        resting = self.screen().seated()
        self.map.tactical_mode = True
        self.map.player_unit = next(u for u in self.province["units"]
                                    if u["owner"] == self.a and id(u) not in resting)
        self.addCleanup(setattr, self.map, "tactical_mode", False)
        self.addCleanup(setattr, self.map, "player_unit", None)

        screen = self.screen()
        bench = screen.side_bench(self.our_side(screen))

        self.assertEqual([u for u in bench if screen.can_command(u)],
                         [self.map.player_unit])
        self.assertGreater(len([u for u in bench if u["owner"] == self.a]), 1)

    def test_an_observer_still_sees_both_sides(self):
        """Unchanged: a fight you are in shows your side's bench, one you are
        only watching shows everybody's."""
        self.map.player_country = next(
            n for n in self.map.nation_data
            if queries.is_playable(n, self.map.nation_data)
            and n not in (self.a, self.b, self.x, self.y))
        self.addCleanup(setattr, self.map, "player_country", self.a)

        screen = self.screen()
        _lane, near, far = screen.current()
        listed = {id(u) for _rect, (u, _note)
                  in screen.row_paint[battle_screen.PANE_RESERVE]}
        # Taller rows can require several scroll positions before every
        # reserve entry is visible; verify the whole pane is reachable.
        reserve_limit = screen.pane_scroll_limit(battle_screen.PANE_RESERVE)
        if reserve_limit < 0:
            view_h = screen.regions[battle_screen.PANE_RESERVE].height
            step = max(1, view_h - battle_screen.ROW_H)
            scroll = 0
            while scroll > reserve_limit:
                scroll = max(reserve_limit, scroll - step)
                screen._scroll_reserve = scroll
                screen.refresh_ui()
                listed.update(id(u) for _rect, (u, _note)
                              in screen.row_paint[battle_screen.PANE_RESERVE])

        self.assertEqual(listed, {id(u) for u in list(near.reserve) + list(far.reserve)})


class ObserverTests(BattleScreenTestCase):
    """A battle you are not in is still worth reading."""

    def setUp(self):
        super().setUp()
        # Somebody with no units anywhere near this tile.
        self.map.player_country = next(
            n for n in self.map.nation_data
            if queries.is_playable(n, self.map.nation_data)
            and n not in (self.a, self.b, self.x, self.y))

    def test_both_sides_of_a_foreign_lane_are_shown(self):
        screen = self.screen()
        lane, near, far = screen.current()

        self.assertIsNotNone(near)
        self.assertIsNotNone(far)
        self.assertEqual({near.nations, far.nations}, {lane.a.nations, lane.b.nations})
        self.assertFalse(screen.is_mine(near))
        self.assertFalse(screen.is_mine(far))

    def test_every_lane_is_listed_not_just_your_own(self):
        screen = self.screen()
        self.assertEqual(len(screen.battle.lanes), 3)
        self.assertEqual(screen.my_lanes(), [])
        self.assertEqual(len([el for el in screen.elements
                              if getattr(el, "pane", None) == battle_screen.PANE_LANES]), 3)

    def test_nothing_in_a_foreign_battle_is_editable(self):
        screen = self.screen()
        rows = [el for el in screen.elements
                if getattr(el, "pane", None) in (battle_screen.PANE_FRONT,
                                                 battle_screen.PANE_ENEMY,
                                                 battle_screen.PANE_RESERVE)]
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(getattr(row, "disabled", False),
                            "a unit the player does not command was clickable")

    def test_it_paints_and_switches_lanes(self):
        screen = self.screen()
        screen.draw(self.surface)
        screen._select(1)
        screen.draw(self.surface)
        self.assertEqual(screen.selected_lane, 1)

    def test_the_title_says_view_rather_than_manage(self):
        self.assertIn("View Battle", self.screen().get_panel_title())

    def test_there_is_nothing_to_clear(self):
        screen = self.screen()
        labels = [getattr(el, "text", "") for el in screen.elements]
        self.assertNotIn("Clear Lane Orders", labels)


class TacticalModeTests(BattleScreenTestCase):
    """Commanding one division, not a country.

    Orders_Screen has enforced this since tactical mode existed; the lane
    manager did not, so the one screen you open in the middle of a battle handed
    the whole army back.
    """

    def setUp(self):
        super().setUp()
        self.map.tactical_mode = True
        self.map.player_unit = next(u for u in self.province["units"]
                                    if u["owner"] == self.a)
        self.addCleanup(setattr, self.map, "tactical_mode", False)
        self.addCleanup(setattr, self.map, "player_unit", None)

    def test_only_the_tactical_unit_is_yours_to_move(self):
        screen = self.screen()

        self.assertEqual([id(u) for u in screen.my_units()],
                         [id(self.map.player_unit)])

    def test_your_own_countrymen_are_not_editable(self):
        screen = self.screen()
        theirs = [u for u in self.province["units"]
                  if u["owner"] == self.a and u is not self.map.player_unit]

        self.assertTrue(theirs)
        for unit in theirs:
            self.assertFalse(screen.can_command(unit))

    def test_the_bench_offers_nobody_else(self):
        screen = self.screen()

        for unit in screen.bench():
            self.assertIs(unit, self.map.player_unit)

    def test_a_row_for_a_unit_you_do_not_command_is_disabled(self):
        screen = self.screen()
        editable = [el for el in screen.elements
                    if getattr(el, "pane", None) in (battle_screen.PANE_FRONT,
                                                     battle_screen.PANE_RESERVE)
                    and not getattr(el, "disabled", False)]

        # At most the one division, wherever it happens to be standing.
        self.assertLessEqual(len(editable), 1)

    def test_clearing_lane_orders_leaves_the_rest_of_the_army_alone(self):
        screen = self.screen()
        others = [u for u in self.province["units"]
                  if u["owner"] == self.a and u is not self.map.player_unit]
        for unit in others:
            unit["combat_stance"] = "RESERVE"

        screen.clear_orders()

        for unit in others:
            self.assertEqual(unit.get("combat_stance"), "RESERVE")


class RowPaintingTests(BattleScreenTestCase):
    """Rows are painted over rather than labelled, so painting is the test."""

    def test_a_bombarding_unit_paints_its_guns_too(self):
        library = queries.get_unit_library()
        gunner = next((name for name, stats in library.items()
                       if "bombard_attack" in stats), None)
        self.assertIsNotNone(gunner, "no bombarding unit type in the library")

        self.province["units"].append(queries.create_unit_dict(gunner, self.a, library))
        screen = self.screen()
        screen.draw(self.surface)

    def test_every_row_carries_something_to_paint(self):
        screen = self.screen()
        painted = {pane: len(rows) for pane, rows in screen.row_paint.items()}
        rows = {}
        for el in screen.elements:
            pane = getattr(el, "pane", None)
            if pane:
                rows[pane] = rows.get(pane, 0) + 1

        self.assertTrue(rows)
        self.assertEqual(painted, rows)

    def test_your_side_is_listed_first_whichever_half_of_the_lane_it_is(self):
        screen = self.screen()
        for lane in screen.battle.lanes:
            near, _far = screen.near_far(lane)
            if screen.is_mine(lane.a) or screen.is_mine(lane.b):
                self.assertTrue(screen.is_mine(near))


class ReadOnlyOrdersTests(BattleScreenTestCase):
    """The Orders screen on a province the player commands nothing in."""

    def orders_screen(self, player):
        from screens.map_related_screens.orders import Orders_Screen

        self.map.player_country = player
        screen = Orders_Screen()
        screen.start_with_province(self.province, self.map)
        return screen

    def test_a_foreign_province_lists_every_unit_read_only(self):
        outsider = next(n for n in self.map.nation_data
                        if queries.is_playable(n, self.map.nation_data)
                        and n not in (self.a, self.b, self.x, self.y))
        screen = self.orders_screen(outsider)

        self.assertTrue(screen.read_only)
        self.assertIsNone(screen.selected_unit_index)
        screen.draw(self.surface)

    def test_a_read_only_province_accepts_no_move_orders(self):
        import pygame as pg

        outsider = next(n for n in self.map.nation_data
                        if queries.is_playable(n, self.map.nation_data)
                        and n not in (self.a, self.b, self.x, self.y))
        screen = self.orders_screen(outsider)
        before = [list(u.get("order", {}).get("path", [])) for u in self.province["units"]]

        screen.additional_events(
            pg.event.Event(pg.MOUSEBUTTONDOWN, pos=(640, 360), button=1))

        after = [list(u.get("order", {}).get("path", [])) for u in self.province["units"]]
        self.assertEqual(before, after)

    def test_your_own_province_is_still_editable(self):
        screen = self.orders_screen(self.a)

        self.assertFalse(screen.read_only)
        self.assertIsNotNone(screen.selected_unit_index)


class OrdersScreenRegressionTests(BattleScreenTestCase):
    """The compact Orders roster and its screen-specific Clear shortcut."""

    def orders_screen(self, player=None):
        from screens.map_related_screens.orders import Orders_Screen

        self.map.player_country = self.a if player is None else player
        screen = Orders_Screen()
        screen.start_with_province(self.province, self.map)
        return screen

    def preserve_materials(self, nation):
        before = nation.get("materials", 0)
        self.addCleanup(nation.__setitem__, "materials", before)
        return before

    def test_clear_orders_key_refunds_only_owned_orders(self):
        mine = next(unit for unit in self.province["units"]
                    if unit["owner"] == self.a)
        foreign = next(unit for unit in self.province["units"]
                       if unit["owner"] != self.a)
        mine["order"] = {
            "type": "REPAIR",
            "refund": {"cost_materials": 17, "cost_manpower": 0,
                       "cost_fuel": 0},
        }
        foreign_order = {"type": "MOVE", "path": [self.province["id"]]}
        foreign["order"] = foreign_order
        nation = self.map.nation_data[self.a]
        materials_before = self.preserve_materials(nation)

        screen = self.orders_screen()
        screen.bombarding_unit_index = self.province["units"].index(mine)
        screen.handle_clear_orders_key()

        self.assertNotIn("order", mine)
        self.assertIs(foreign["order"], foreign_order)
        self.assertEqual(nation["materials"], materials_before + 17)
        self.assertIsNone(screen.bombarding_unit_index)

    def test_clear_orders_key_is_ignored_while_renaming(self):
        index, unit = next((index, unit)
                           for index, unit in enumerate(self.province["units"])
                           if unit["owner"] == self.a)
        order = {
            "type": "REPAIR",
            "refund": {"cost_materials": 11, "cost_manpower": 0,
                       "cost_fuel": 0},
        }
        unit["order"] = order
        nation = self.map.nation_data[self.a]
        materials_before = self.preserve_materials(nation)
        screen = self.orders_screen()
        screen.start_renaming(index)

        screen.handle_clear_orders_key()

        self.assertIs(unit["order"], order)
        self.assertEqual(nation["materials"], materials_before)
        self.assertEqual(screen.renaming_unit_index, index)

    def test_clear_orders_key_is_ignored_on_a_read_only_roster(self):
        outsider = next(nation for nation in self.map.nation_data
                        if queries.is_playable(nation, self.map.nation_data)
                        and nation not in (self.a, self.b, self.x, self.y))
        unit = self.province["units"][0]
        order = {"type": "MOVE", "path": [self.province["id"]]}
        unit["order"] = order
        screen = self.orders_screen(outsider)

        screen.handle_clear_orders_key()

        self.assertTrue(screen.read_only)
        self.assertIs(unit["order"], order)

    def test_clear_orders_key_is_ignored_in_tactical_mode(self):
        unit = next(unit for unit in self.province["units"]
                    if unit["owner"] == self.a)
        order = {
            "type": "REPAIR",
            "refund": {"cost_materials": 13, "cost_manpower": 0,
                       "cost_fuel": 0},
        }
        unit["order"] = order
        nation = self.map.nation_data[self.a]
        materials_before = self.preserve_materials(nation)
        self.map.tactical_mode = True
        self.map.player_unit = unit
        self.addCleanup(setattr, self.map, "tactical_mode", False)
        self.addCleanup(setattr, self.map, "player_unit", None)
        screen = self.orders_screen()

        screen.handle_clear_orders_key()

        self.assertIs(unit["order"], order)
        self.assertEqual(nation["materials"], materials_before)

    def test_compact_rows_have_six_actions_and_stay_inside_the_panel(self):
        owned_indices = [index for index, unit in enumerate(self.province["units"])
                         if unit["owner"] == self.a]
        for index in owned_indices:
            self.province["units"][index]["order"] = {
                "type": "MOVE", "path": []}

        screen = self.orders_screen()
        screen.draw(self.surface)

        # The roster lists every unit fog of war lets the player see on this
        # tile, not just their own -- so at least one foreign row that still
        # fits inside the (unscrolled) viewport is expected alongside all of
        # the player's own rows.
        visible_indices = set(screen.unit_row_icons)
        self.assertTrue(set(owned_indices).issubset(visible_indices))
        foreign_visible = visible_indices - set(owned_indices)
        self.assertTrue(foreign_visible)

        self.assertEqual(len(screen.action_buttons), len(owned_indices) * 6)
        self.assertLessEqual(screen.row_height, 80 * 0.75)
        self.assertLessEqual(screen.PANEL_WIDTH, 570 * 0.85)

        for index in owned_indices:
            with self.subTest(unit_index=index):
                buttons = [button for button in screen.action_buttons
                           if button.unit_index == index]
                self.assertEqual(len(buttons), 6)
                self.assertEqual({button.action_slot for button in buttons}, set(range(6)))
                for button in buttons:
                    self.assertTrue(screen.panel_rect.contains(button.rect))
                    self.assertTrue(screen.scroll_content_rect.contains(button.rect))

        # A foreign unit's row is shown, but carries no command buttons of
        # its own -- that's the part of the roster the player can't touch.
        for index in foreign_visible:
            with self.subTest(foreign_unit_index=index):
                self.assertFalse(
                    [b for b in screen.action_buttons if b.unit_index == index])

        cancel_by_index = {index: rect for rect, index in screen.cancel_rects}
        self.assertEqual(len(screen.cancel_rects), len(owned_indices))
        self.assertEqual(set(cancel_by_index), set(owned_indices))
        for rect in cancel_by_index.values():
            self.assertTrue(screen.panel_rect.contains(rect))
            self.assertTrue(screen.scroll_content_rect.contains(rect))

    def test_drawing_orders_suppresses_only_its_embedded_map_flag(self):
        from ui.bars import flag_renderer

        screen = self.orders_screen()
        self.map.hide_flag = False
        with mock.patch.object(
                flag_renderer.queries, "decode_b64_to_surf",
                wraps=flag_renderer.queries.decode_b64_to_surf) as decode:
            screen.draw(self.surface)

        decode.assert_not_called()
        self.assertFalse(self.map.hide_flag)


class ButtonSwapTests(BattleScreenTestCase):
    """Orders remains the map entry point, including while the tile fights."""

    def visible_pair(self):
        from screens.menu_screens import map as map_module

        shown = {}

        def set_btn(btn, visible, enabled, text, color="green"):
            shown[id(btn)] = visible

        map_module.set_orders_or_battle(self.map, set_btn, True)
        return shown[id(self.map.btn_go_orders)], shown[id(self.map.btn_go_battle)]

    def test_a_fighting_tile_still_shows_the_orders_button(self):
        self.assertEqual(self.visible_pair(), (True, False))

    def test_a_quiet_tile_shows_give_orders(self):
        self.province["units"] = [
            queries.create_unit_dict("Infantry", self.a, queries.get_unit_library())]
        self.assertEqual(self.visible_pair(), (True, False))

    def test_a_battle_you_are_not_in_still_offers_orders(self):
        """Reading somebody else's front is available through Orders too."""
        self.map.player_country = next(
            n for n in self.map.nation_data
            if queries.is_playable(n, self.map.nation_data)
            and n not in (self.a, self.b, self.x, self.y))

        from screens.menu_screens import map as map_module

        enabled = {}

        def set_btn(btn, visible, is_enabled, text, color="green"):
            enabled[id(btn)] = (visible, is_enabled)

        map_module.set_orders_or_battle(self.map, set_btn, False)
        self.assertEqual(enabled[id(self.map.btn_go_orders)], (True, True))
        self.assertEqual(enabled[id(self.map.btn_go_battle)], (False, False))

    def test_orders_screen_offers_battle_button_for_a_fighting_tile(self):
        from screens.map_related_screens.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)

        labels = [getattr(el, "text", "") for el in orders.elements]
        self.assertIn("Manage Battle", labels)

    def test_orders_opens_battle_beside_itself(self):
        from screens.map_related_screens.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()

        self.assertIsInstance(orders.battle_screen, battle_screen.Battle_Screen)
        self.assertTrue(orders.battle_screen.embedded)
        self.assertIs(orders.battle_screen.origin_screen, orders)
        self.assertEqual(orders.battle_screen.panel_rect, orders.battle_panel_rect())

    def test_closing_embedded_battle_keeps_orders_open(self):
        from screens.map_related_screens.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()
        panel = orders.battle_screen

        panel.exit_screen()

        self.assertIsNone(orders.battle_screen)
        self.assertTrue(panel.done)
        self.assertFalse(orders.done)
        self.assertIs(self.map.selected_province, self.province)

    def test_closing_orders_removes_embedded_battle_with_it(self):
        from screens.map_related_screens.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()

        orders.exit_screen()

        self.assertIsNone(orders.battle_screen)
        self.assertTrue(orders.done)

    def test_closing_battle_modal_reveals_its_orders_screen(self):
        from screens.map_related_screens.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        battle = battle_screen.Battle_Screen(
            self.map, self.province, origin_screen=orders)

        battle.exit_screen()

        self.assertTrue(battle.done)
        self.assertFalse(orders.done)
        self.assertIs(self.map.selected_province, self.province)

    def test_preemptive_fighting_tile_enters_orders_before_battle(self):
        from ui import event_handler

        old_navigation = c.MAP_NAVIGATION_MODE
        old_done = self.map.done
        old_next_state = self.map.next_state
        old_secondary_mode = self.map.secondary_mode
        self.addCleanup(setattr, c, "MAP_NAVIGATION_MODE", old_navigation)
        self.addCleanup(setattr, self.map, "done", old_done)
        self.addCleanup(setattr, self.map, "next_state", old_next_state)
        self.addCleanup(setattr, self.map, "secondary_mode", old_secondary_mode)

        c.MAP_NAVIGATION_MODE = "PREEMPTIVE"
        self.map.done = False
        self.map.next_state = None
        with mock.patch.object(event_handler, "_resync_view_mode_row"):
            event_handler.navigate_view_mode(self.map, "UNITS")

        self.assertTrue(self.map.done)
        self.assertEqual(self.map.next_state, "ORDERS")


if __name__ == "__main__":
    unittest.main()
