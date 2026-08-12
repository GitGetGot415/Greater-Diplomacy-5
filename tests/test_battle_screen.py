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
    """A real province, with a two-lane fight forced onto it."""

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
                                      (self.x, [self.y], [self.a, self.b]),
                                      (self.y, [self.x], [self.a, self.b])):
            game_map.nation_data[name]["allied_with"] = list(allies)
            game_map.nation_data[name]["at_war_with"] = list(enemies)

        self.province = next(p for p in game_map.map_data.values()
                             if not queries.is_water_province(p))
        library = queries.get_unit_library()
        self.province["units"] = [queries.create_unit_dict("Infantry", name, library)
                                  for name in names for _ in range(5)]

        game_map.selected_province = self.province
        game_map.visible_provinces = None
        game_map.player_country = self.a
        self.addCleanup(self.province.pop, "units", None)

    def screen(self):
        return battle_screen.Battle_Screen(self.map, self.province)

    def battle(self):
        return combat_rules.build_battle([self.province["units"]], self.map.nation_data)

    def mine(self, battle):
        for lane in battle.lanes:
            for side in (lane.a, lane.b):
                if side.nation == self.a:
                    return side
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

    def test_selecting_the_other_lane_repaints(self):
        screen = self.screen()
        self.assertGreater(len(screen.battle.lanes), 1)

        screen._select(1)
        screen.draw(self.surface)

        self.assertEqual(screen.selected_lane, 1)

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
                    if self.a in (lane.a.nation, lane.b.nation))
        opponent = lane.b.nation if lane.a.nation == self.a else lane.a.nation

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


class ButtonSwapTests(BattleScreenTestCase):
    """Manage Battle takes Give Orders' slot exactly while the tile is fighting."""

    def visible_pair(self):
        from screens.menu_screens import map as map_module

        shown = {}

        def set_btn(btn, visible, enabled, text, color="green"):
            shown[id(btn)] = visible

        map_module.set_orders_or_battle(self.map, set_btn, True)
        return shown[id(self.map.btn_go_orders)], shown[id(self.map.btn_go_battle)]

    def test_a_fighting_tile_shows_the_battle_button(self):
        self.assertEqual(self.visible_pair(), (False, True))

    def test_a_quiet_tile_shows_give_orders(self):
        self.province["units"] = [
            queries.create_unit_dict("Infantry", self.a, queries.get_unit_library())]
        self.assertEqual(self.visible_pair(), (True, False))


if __name__ == "__main__":
    unittest.main()
