"""The lane manager, against a real booted game.

tests/test_screen_smoke.py only walks controller.states, and this is a modal
pushed onto the stack rather than a registered state, so nothing else would ever
construct it. The build-and-paint half here is that missing coverage; the rest is
the part worth testing on its own -- that what the screen writes onto a unit is
read back by the resolver, and that an impossible order is ignored rather than
raising in the middle of a turn.
"""

import copy
import unittest
from unittest import mock


import pygame

import data.constants as c
from data import queries
from map_logic.system32 import combat_rules
from screens.game import battle_screen, battle_editor
from tests import app_harness
from ui.panels import army_panel


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
        # Battle commands require an ordinary player planning phase, rather
        # than the scenario-selection state in which the harness boots.
        for attribute in ("selection_mode", "is_editor", "ai_is_thinking", "viewing_ai_moves"):
            self.enterContext(mock.patch.object(game_map, attribute, False))
        stats = {"attack": 20, "defense": 0, "health": 100, "speed": 1,
                 "cost_materials": 50, "cost_manpower": 10, "cost_fuel": 0,
                 "production_time": 1, "naval_unit": False}
        library = {"Infantry": stats, "Test Gun": dict(stats, bombard_attack=30, bombard_range=1)}
        self.enterContext(mock.patch.object(queries, "get_unit_library", return_value=library))
        # Orders no longer recentres ordinary unit selections. Keep this
        # rendering fixture independent of camera state left by another test.
        previous_camera_pos = pygame.Vector2(game_map.camera.pos)
        previous_camera_target = pygame.Vector2(game_map.camera.target_pos)
        self.addCleanup(game_map.camera.pos.update,
                        previous_camera_pos.x, previous_camera_pos.y)
        self.addCleanup(game_map.camera.target_pos.update,
                        previous_camera_target.x, previous_camera_target.y)
        game_map.camera.pos.update(0, 0)
        game_map.camera.target_pos.update(0, 0)
        names = [n for n in game_map.nation_data
                 if queries.is_playable(n, game_map.nation_data)][:4]
        self.a, self.b, self.x, self.y = names

        for name, faction, enemies in ((self.a, "Fixture Coalition", [self.x, self.y]),
                                       (self.b, "Fixture Coalition", [self.x, self.y]),
                                       (self.x, "", [self.a, self.b, self.y]),
                                       (self.y, "", [self.a, self.b, self.x])):
            self.enterContext(mock.patch.dict(game_map.nation_data[name],
                                             faction=faction, at_war_with=list(enemies)))

        from map_logic.diplomacy import faction_records
        original_factions = copy.deepcopy(game_map.world.factions)
        self.addCleanup(faction_records.restore, game_map, original_factions)
        faction_records.restore(game_map)

        self.province = next(p for p in game_map.map_data.values()
                             if not queries.is_water_province(p))
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
        return combat_rules.build_battle(
            [self.province["units"]], self.map.nation_data,
            terrain=self.province.get("terrain"))

    def mine(self, battle):
        """The player's own half of the first side it fights on."""
        for lane in battle.lanes:
            for side in (lane.a, lane.b):
                if self.a in side.nations:
                    return next(m for m in side.members if m.nation == self.a)
        return None


class BuildAndPaintTests(BattleScreenTestCase):
    def test_battle_and_sidebar_field_the_terrain_front_rank(self):
        from ui.panels import sidebar_info
        from tests.combat_fixtures import unit

        previous_terrain = self.province["terrain"]
        self.addCleanup(self.province.__setitem__, "terrain", previous_terrain)
        self.province["units"] = [unit(n, attack=10)
                                  for n in (self.a, self.x)
                                  for _ in range(c.COMBAT_WIDTH)]
        for terrain in ("mountain", "plains", "hills"):
            with self.subTest(terrain=terrain):
                self.province["terrain"] = terrain
                width = combat_rules.combat_width_for_terrain(terrain)
                slots = combat_rules.lane_slots(1, width)
                screen = self.screen()
                self.assertEqual(screen.battle.lanes[0].slots, slots)
                self.assertEqual(len(screen.battle.lanes[0].a.front), slots)

                with mock.patch.object(screen, "label") as label:
                    screen.draw_body(self.surface)
                summary = label.call_args_list[0].args[1]
                self.assertIn(f"{screen.battle.width} of {width}", summary)

                roster_battles = []
                build_battle = combat_rules.build_battle

                def record_battle(*args, **kwargs):
                    battle = build_battle(*args, **kwargs)
                    roster_battles.append(battle)
                    return battle

                with mock.patch.object(combat_rules, "build_battle",
                                       side_effect=record_battle):
                    sidebar_info.prepare_unit_roster(self.map, self.province)
                    sidebar_info.draw_unit_roster(
                        self.map, self.surface, self.province,
                        self.province["units"], True, 0, 0, 370)
                self.assertEqual(roster_battles[0].lanes[0].slots, slots)

    def test_the_screen_builds_and_paints(self):
        screen = self.screen()
        screen.refresh_ui()
        screen.draw(self.surface)

        self.assertTrue(screen.battle.lanes)
        self.assertTrue(screen.elements)

    def test_color_help_opens_shared_popup_with_one_sound_and_preserves_orders(self):
        from screens.game.orders import Orders_Screen
        from ui.navigation import modal_stack
        from ui.widgets import ui_elements

        for embedded in (False, True):
            with self.subTest(embedded=embedded):
                if embedded:
                    orders = Orders_Screen()
                    orders.start_with_province(self.province, self.map)
                    orders.go_to_battle()
                    screen = orders.battle_screen
                else:
                    screen = self.screen()
                screen._select(1)
                before = copy.deepcopy(self.province["units"])
                button = next(element for element in screen.elements
                              if getattr(element, "callback", None) == screen.show_color_help)
                with mock.patch.object(ui_elements, "play_ui_sound") as sound:
                    screen.handle_events([
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=button.rect.center, button=1),
                        pygame.event.Event(pygame.MOUSEBUTTONUP, pos=button.rect.center, button=1)])
                    sound.assert_called_once_with("info")
                modal = modal_stack.active()
                self.assertIsNotNone(modal)
                try:
                    modal.draw(self.surface)
                    modal.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
                    modal.update()
                    self.assertFalse(screen.done)
                    self.assertEqual(screen.selected_lane, 1)
                    self.assertEqual(self.province["units"], before)
                finally:
                    if modal_stack.active() is modal:
                        modal_stack.pop()

    def test_overview_preserves_the_shared_fort_defense_entries(self):
        screen = self.screen()
        unit = self.province["units"][0]
        row = screen.combat_row_data[id(unit)]
        detailed_entries = [(c.ICON_ATTACK, "20"), (c.ICON_HEALTH, "100"),
                            (c.ICON_DEFENSE, "7 + 5")]
        with mock.patch.dict(row, defense=7, fort=5, entries=detailed_entries):
            with mock.patch.object(battle_screen, "draw_wrapped_icon_row") as draw_stats:
                screen._card_surface(unit, (84, battle_screen.CARD_H), False)
            entries = dict(entry for call in draw_stats.call_args_list for entry in call.args[2])
            self.assertEqual(entries[c.ICON_DEFENSE], dict(detailed_entries)[c.ICON_DEFENSE])
            self.assertEqual(row["defense"], 7)
            self.assertEqual(row["fort"], 5)
            self.assertEqual(dict(row["entries"])[c.ICON_DEFENSE], "7 + 5")

    def test_it_survives_an_idle_event_pump(self):
        screen = self.screen()
        screen.handle_events([pygame.event.Event(pygame.MOUSEMOTION, pos=(640, 360), rel=(0, 0),
                                                 buttons=(0, 0, 0)),
                              pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
        screen.draw(self.surface)

    def test_embedded_battle_builds_and_paints_beside_orders(self):
        from screens.game.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()

        orders.draw(self.surface)

        self.assertIsNotNone(orders.battle_screen)
        self.assertTrue(orders.battle_screen.embedded)
        self.assertFalse(army_panel._visible(self.map, orders))

    def test_combat_bubble_entry_opens_the_battle_inspector(self):
        from screens.game.orders import Orders_Screen

        self.map._orders_entered_from_combat_bubble = True
        self.map.clear_map_unit_selection()
        orders = Orders_Screen()
        with mock.patch.object(self.map, "select_map_units") as select_units:
            orders.start_with_province(self.province, self.map)

        select_units.assert_not_called()
        self.assertIsNotNone(orders.battle_screen)
        self.assertTrue(orders.battle_screen.embedded)
        self.assertFalse(hasattr(self.map, "_orders_entered_from_combat_bubble"))

    def test_combat_bubble_orders_exit_returns_to_the_map(self):
        from screens.game.orders import Orders_Screen

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

    def test_selecting_the_other_lane_repaints(self):
        screen = self.screen()
        self.assertGreater(len(screen.battle.lanes), 1)

        screen._select(1)
        screen.draw(self.surface)

        self.assertEqual(screen.selected_lane, 1)

    def test_lane_outlook_is_rebuilt_for_the_selected_lane(self):
        screen = self.screen()
        self.assertIsInstance(screen.lane_outcome, dict)

        with mock.patch.object(screen, "_estimate_lane_outcome",
                               wraps=screen._estimate_lane_outcome) as estimate:
            screen._select(1)

        self.assertEqual(estimate.call_args.args[0].index, 1)
        self.assertIsInstance(screen.lane_outcome, dict)

    def test_combat_outlook_estimate_identifies_the_expected_winner(self):
        from ui.rendering import overlay_renderer

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


class BattleEditorTests(BattleScreenTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(combat_rules, "combat_width_for_terrain", return_value=12))
        self.enterContext(mock.patch.object(c, "MIN_LANE_SLOTS_PER_SIDE", 1))
        self.enterContext(mock.patch.object(c, "AI_ROTATE_HEALTH_FRACTION", 0.5))

    def editor(self):
        from screens.game.battle_editor import BattleEditorScreen
        return BattleEditorScreen(self.screen())

    def own_row(self, screen, pane):
        return next((rect, unit) for rect, (unit, _note) in screen.row_paint[pane]
                    if screen.can_command(unit))

    def test_disabled_front_spaces_reject_reserve_drops_without_changing_capacity(self):
        screen = self.editor()
        pane = battle_screen.PANE_FRONT
        start, reserve = self.own_row(screen, battle_screen.PANE_RESERVE)
        disabled = next(rect for rect in screen.disabled_slots[pane]
                        if screen.regions[pane].collidepoint(rect.center))
        self.assertFalse(any(rect.collidepoint(disabled.center)
                             for rect, _index in screen.empty_slots[pane]))
        before = copy.deepcopy(self.province['units'])
        positions = {index: [id(unit) if unit is not None else None for unit in slots]
                     for index, slots in screen.front_slots.items()}

        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start.center, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=disabled.center, button=1)])

        self.assertIsNone(screen.drag_unit)
        self.assertEqual(self.province['units'], before)
        self.assertEqual({index: [id(unit) if unit is not None else None for unit in slots]
                          for index, slots in screen.front_slots.items()}, positions)
        lane, _near, _far = screen.current()
        self.assertFalse(screen.drop_unit(reserve, pane, slot_index=len(screen.front_slots[lane.index])))
        self.assertEqual(self.province['units'], before)

    def test_overview_unit_clicks_do_not_change_orders(self):
        screen = self.screen()
        before = copy.deepcopy(self.province["units"])
        pane = battle_screen.PANE_FRONT
        reserve_ids = {id(unit) for unit in screen.bench()}
        for is_reserve in (False, True):
            rect = next(rect for rect, (unit, _note) in screen.row_paint[pane]
                        if screen.can_command(unit) and (id(unit) in reserve_ids) == is_reserve)
            pos = rect.clip(screen.regions[pane]).center
            with mock.patch.object(pygame.mouse, "get_pos", return_value=pos):
                screen.handle_events([
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
                    pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
        self.assertEqual(self.province["units"], before)

    def test_help_button_opens_shared_popup_without_changing_the_edit(self):
        from ui.navigation import modal_stack
        from ui.widgets import ui_elements
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(front, battle_screen.PANE_RESERVE)
        before = copy.deepcopy(self.province["units"])
        positions = {key: [id(unit) if unit is not None else None for unit in slots]
                     for key, slots in screen.front_slots.items()}
        help_button = next(element for element in screen.elements if getattr(element, "text", "") == "Help")
        with mock.patch.object(ui_elements, "play_ui_sound") as sound:
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=help_button.rect.center, button=1),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=help_button.rect.center, button=1)])
            sound.assert_called_once_with("info")
        modal = modal_stack.active()
        self.assertIsNotNone(modal)
        try:
            modal.draw(self.surface)
            modal.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
            modal.update()
            self.assertFalse(screen.done)
            self.assertEqual(self.province["units"], before)
            self.assertEqual({key: [id(unit) if unit is not None else None for unit in slots]
                              for key, slots in screen.front_slots.items()}, positions)
        finally:
            if modal_stack.active() is modal:
                modal_stack.pop()

    def test_organize_control_opens_confirmation_and_cancel_preserves_the_edit(self):
        from ui.navigation import modal_stack
        from ui.widgets import ui_elements
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(front, battle_screen.PANE_RESERVE)
        before = copy.deepcopy(self.province['units'])
        positions = {key: [id(unit) if unit is not None else None for unit in slots]
                     for key, slots in screen.front_slots.items()}
        organize = next(element for element in screen.elements if getattr(element, 'text', '') == 'Organize')
        with mock.patch.object(ui_elements, 'play_ui_sound') as sound:
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=organize.rect.center, button=1),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=organize.rect.center, button=1)])
            sound.assert_called_once_with('click')
        modal = modal_stack.active()
        self.assertIsNotNone(modal)
        try:
            self.assertTrue(screen._organize_confirmation_open)
            self.assertEqual(self.province['units'], before)
            screen.confirm_organize()
            self.assertIs(modal_stack.active(), modal)
            modal.draw(self.surface)
            modal.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
            modal.update()
            self.assertFalse(screen._organize_confirmation_open)
            self.assertEqual(self.province['units'], before)
            self.assertEqual({key: [id(unit) if unit is not None else None for unit in slots]
                              for key, slots in screen.front_slots.items()}, positions)
        finally:
            if modal_stack.active() is modal:
                modal_stack.pop()

    def test_confirmed_organize_runs_automatic_assignment_once(self):
        screen = self.editor()
        ours = screen.my_units()
        ours[0].update(health=1, max_health=100)
        for unit in ours:
            unit['lane_target'] = self.x
        before = copy.deepcopy(self.province['units'])
        with mock.patch.object(battle_editor.dialogs, 'ask_yes_no') as ask:
            screen.confirm_organize()
        self.assertEqual(self.province['units'], before)
        answered = ask.call_args.kwargs['on_result']
        answered(True)
        self.assertTrue(all('lane_target' not in unit for unit in ours))
        self.assertEqual(ours[0].get('combat_stance'), 'RESERVE')
        self.assertTrue(all('combat_stance' not in unit for unit in ours[1:]))
        with mock.patch.object(screen, 'reset_assignments') as apply:
            answered(True)
        apply.assert_not_called()

    def test_organize_confirmation_rejects_changed_state_or_permissions(self):
        screen = self.editor()
        for change in ('state', 'permission', 'closed'):
            with self.subTest(change=change):
                with mock.patch.object(battle_editor.dialogs, 'ask_yes_no') as ask:
                    screen.confirm_organize()
                answered = ask.call_args.kwargs['on_result']
                before = copy.deepcopy(self.province['units'])
                with mock.patch.object(battle_editor.unit_actions, 'reset_battle_orders') as apply:
                    if change == 'state':
                        self.map.invalidate_map_presentation_cache()
                        answered(True)
                    elif change == 'permission':
                        with mock.patch.object(self.map, 'can_select_map_units', return_value=False):
                            answered(True)
                    else:
                        screen._finish_exit()
                        answered(True)
                apply.assert_not_called()
                self.assertEqual(self.province['units'], before)

    def test_outlook_uses_the_overview_forecast_for_the_selected_lane(self):
        screen = self.editor()
        forecast = {"winner_side": 0, "turns": 3}
        with mock.patch.object(screen.overview, "_estimate_lane_outcome", return_value=forecast) as estimate, \
                mock.patch.object(screen.overview, "_paint_outcome",
                                  wraps=screen.overview._paint_outcome) as paint:
            screen._select(1)
        self.assertEqual(estimate.call_args.args[0].index, 1)
        self.assertIs(screen.lane_outcome, forecast)
        self.assertIs(paint.call_args.kwargs["outcome"], forecast)

    def test_outlook_refreshes_after_unit_changes_and_reset(self):
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        first = {"winner_side": 0, "turns": 2}
        second = {"winner_side": 1, "turns": 4}
        with mock.patch.object(screen.overview, "_estimate_lane_outcome", side_effect=[first, second]) as estimate:
            self.assertTrue(screen.drop_unit(front, battle_screen.PANE_RESERVE))
            self.assertIs(screen.lane_outcome, first)
            screen.reset_assignments()
            self.assertIs(screen.lane_outcome, second)
        self.assertEqual(estimate.call_count, 2)

    def test_edit_changes_controller_state_and_exit_restores_orders(self):
        from types import SimpleNamespace
        from main import Controller
        from screens.game.battle_editor import BattleEditorScreen
        from screens.game.orders import Orders_Screen
        from ui.navigation import modal_stack

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()
        screen = orders.battle_screen
        orders.scroll_y = orders.max_scroll_y
        orders.refresh_ui()
        previous_scroll = orders.scroll_y
        previous_selection = set(self.map.selected_unit_ids)
        screen._select(1)
        editor = BattleEditorScreen()
        app = SimpleNamespace(states={"MAP": self.map, "ORDERS": orders,
                                      "BATTLE_EDITOR": editor}, active_state=orders)
        previous_modal = modal_stack.active()
        edit = next(element for element in screen.elements if getattr(element, "text", "") == "Edit")
        edit.callback()
        self.assertEqual(orders.next_state, "BATTLE_EDITOR")
        Controller.flip_state(app)
        self.assertIs(app.active_state, editor)
        self.assertIs(modal_stack.active(), previous_modal)
        editor.exit_screen()
        Controller.flip_state(app)
        self.assertIs(app.active_state, orders)
        self.assertIs(orders.battle_screen, screen)
        self.assertEqual(orders.scroll_y, previous_scroll)
        self.assertEqual(set(self.map.selected_unit_ids), previous_selection)
        self.assertEqual(screen.selected_lane, 1)
        self.assertFalse(screen.done)

    def test_dragging_a_reserve_onto_a_front_unit_swaps_them(self):
        screen = self.editor()
        start_rect, reserve = self.own_row(screen, battle_screen.PANE_RESERVE)
        end_rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        start, end = start_rect.center, end_rect.center
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1),
            pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(1, 1), buttons=(1, 0, 0))])
        screen.draw(self.surface)
        screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1)])
        _lane, near, _far = screen.current()
        self.assertIn(id(reserve), {id(unit) for unit in near.front})
        self.assertNotIn(id(front), screen.seated())
        self.assertNotIn("combat_stance", front)
        self.assertIsNone(screen.drag_unit)

    def test_dragging_a_front_unit_to_reserves_clears_its_lane_pin(self):
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        _lane, _near, far = screen.current()
        front["lane_target"] = far.nations[0]
        self.assertTrue(screen.drop_unit(front, battle_screen.PANE_RESERVE))
        self.assertNotIn("lane_target", front)
        self.assertNotIn("combat_stance", front)
        self.assertNotIn(id(front), screen.seated())

    def test_units_move_between_front_reserves_and_held_without_duplicates(self):
        screen = self.editor()
        lane, _near, far = screen.current()
        _rect, unit = self.own_row(screen, battle_screen.PANE_FRONT)
        index = next(index for index, current in enumerate(screen.front_slots[lane.index]) if current is unit)
        unit['lane_target'] = far.nations[0]
        roster = [id(current) for current in self.province['units']]

        self.assertTrue(screen.drop_unit(unit, battle_editor.PANE_HELD))
        self.assertEqual(unit.get('combat_stance'), 'RESERVE')
        self.assertNotIn('lane_target', unit)
        self.assertNotIn(id(unit), screen.seated())
        self.assertEqual(sum(current is unit for current in screen.current()[1].reserve), 1)

        self.assertTrue(screen.drop_unit(unit, battle_screen.PANE_RESERVE))
        self.assertNotIn('combat_stance', unit)
        self.assertNotIn(id(unit), screen.seated())
        self.assertEqual(sum(current is unit for current in screen.current()[1].reserve), 1)
        self.assertFalse(screen.drop_unit(unit, battle_screen.PANE_RESERVE))

        self.assertTrue(screen.drop_unit(unit, battle_editor.PANE_HELD))
        self.assertTrue(screen.drop_unit(unit, battle_screen.PANE_FRONT, slot_index=index))
        self.assertNotIn('combat_stance', unit)
        self.assertEqual(unit.get('lane_target'), far.nations[0])
        self.assertIs(screen.front_slots[lane.index][index], unit)
        self.assertFalse(any(current is unit for current in screen.current()[1].reserve))
        self.assertEqual([id(current) for current in self.province['units']], roster)

    def test_dragging_a_reserve_to_held_and_back_changes_its_hold_preference(self):
        screen = self.editor()
        start, unit = self.own_row(screen, battle_screen.PANE_RESERVE)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start.center, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=screen.regions[battle_editor.PANE_HELD].center, button=1)])
        self.assertEqual(unit.get('combat_stance'), 'RESERVE')
        self.assertNotIn(id(unit), screen.seated())
        start = next(rect for rect, (current, _note) in screen.row_paint[battle_editor.PANE_HELD] if current is unit)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start.center, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=screen.regions[battle_screen.PANE_RESERVE].center, button=1)])
        self.assertNotIn('combat_stance', unit)
        self.assertNotIn(id(unit), screen.seated())
        self.assertIsNone(screen.drag_unit)

    def three_way_editor_with_lone_defender(self):
        library = queries.get_unit_library()
        defender = queries.create_unit_dict("Infantry", self.a, library)
        self.province["units"] = [defender] + [
            queries.create_unit_dict("Infantry", owner, library)
            for owner in (self.x, self.y) for _ in range(3)]
        screen = self.editor()
        self.assertEqual(screen.battle.shares[id(defender)], 2)
        return screen, defender

    def test_placing_a_lone_defender_in_either_lane_restores_both_fronts(self):
        for enemy in (self.x, self.y):
            with self.subTest(enemy=enemy):
                screen, defender = self.three_way_editor_with_lone_defender()
                required = [lane for lane in screen.battle.lanes
                            if any(unit is defender for unit in screen.overview.near_far(lane)[0].front)]
                chosen = next(lane for lane in required if enemy in screen.overview.near_far(lane)[1].nations)
                screen._select(chosen.index)
                self.assertTrue(screen.drop_unit(defender, battle_screen.PANE_RESERVE))
                others = {index: [id(unit) if unit is not None else None for unit in slots]
                          for index, slots in screen.front_slots.items()
                          if index not in {lane.index for lane in required}}
                units_before = list(self.province["units"])
                foreign_before = copy.deepcopy(units_before[1:])
                start, unit = self.own_row(screen, battle_screen.PANE_RESERVE)
                end = screen.empty_slots[battle_screen.PANE_FRONT][0][0].center
                self.assertIs(unit, defender)
                screen.handle_events([
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start.center, button=1),
                    pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1)])
                for lane in required:
                    screen._select(lane.index)
                    self.assertEqual(sum(unit is defender for unit in screen.front_slots[lane.index]), 1)
                    self.assertIn(id(defender), {id(unit) for unit in screen.current()[1].front})
                for index, positions in others.items():
                    self.assertEqual([id(unit) if unit is not None else None
                                      for unit in screen.front_slots[index]], positions)
                self.assertEqual([id(unit) for unit in self.province["units"]],
                                 [id(unit) for unit in units_before])
                self.assertEqual(self.province["units"][1:], foreign_before)
                self.assertFalse(screen._reserves_will_fill_gaps())

    def test_returning_shared_defender_to_reserves_removes_all_its_copies(self):
        screen, defender = self.three_way_editor_with_lone_defender()
        required = [lane.index for lane in screen.battle.lanes
                    if any(unit is defender for unit in screen.overview.near_far(lane)[0].front)]
        screen._select(required[0])
        screen.drop_unit(defender, battle_screen.PANE_RESERVE)
        screen.drop_unit(defender, battle_screen.PANE_FRONT)
        screen._select(required[1])
        self.assertTrue(screen.drop_unit(defender, battle_screen.PANE_RESERVE))
        self.assertFalse(any(unit is defender for slots in screen.front_slots.values() for unit in slots))
        self.assertEqual(sum(unit is defender for unit in screen.current()[1].reserve), 1)

    def test_placing_an_unshared_unit_preserves_other_lanes_deliberate_gaps(self):
        screen = self.editor()
        first_lane, _near, _far = screen.current()
        _rect, first = self.own_row(screen, battle_screen.PANE_FRONT)
        first_index = next(index for index, unit in enumerate(screen.front_slots[first_lane.index]) if unit is first)
        screen.drop_unit(first, battle_screen.PANE_RESERVE)
        other_lane = next(lane for lane in screen.battle.lanes if lane.index != first_lane.index
                          and any(unit is not None and screen.can_command(unit)
                                  for unit in screen.front_slots[lane.index]))
        screen._select(other_lane.index)
        _rect, other = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(other, battle_screen.PANE_RESERVE)
        expected = [id(unit) if unit is not None else None for unit in screen.front_slots[other_lane.index]]
        screen._select(first_lane.index)
        self.assertTrue(screen.drop_unit(first, battle_screen.PANE_FRONT, slot_index=first_index))
        self.assertEqual(screen.battle.shares[id(first)], 1)
        self.assertEqual([id(unit) if unit is not None else None
                          for unit in screen.front_slots[other_lane.index]], expected)

    def test_dropping_outside_the_lists_changes_nothing(self):
        screen = self.editor()
        rect, _unit = self.own_row(screen, battle_screen.PANE_RESERVE)
        before = copy.deepcopy(self.province["units"])
        outside = (0, 0)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=outside, button=1)])
        self.assertEqual(self.province["units"], before)
        self.assertIsNone(screen.drag_unit)

    def test_removing_a_front_unit_leaves_its_slot_empty(self):
        screen = self.editor()
        lane, _near, _far = screen.current()
        before = list(screen.front_slots[lane.index])
        front = next(unit for unit in before if unit is not None and screen.can_command(unit))
        index = next(index for index, unit in enumerate(before) if unit is front)
        self.assertTrue(screen.drop_unit(front, battle_screen.PANE_RESERVE))
        expected = list(before)
        expected[index] = None
        self.assertEqual([id(unit) if unit is not None else None for unit in screen.front_slots[lane.index]],
                         [id(unit) if unit is not None else None for unit in expected])
        self.assertIn(id(front), {id(unit) for unit in screen.current()[1].reserve})

        screen._select(next(index for index in range(len(screen.battle.lanes)) if index != lane.index))
        screen._select(lane.index)
        screen.refresh_ui()
        screen.update()
        self.assertIsNone(screen.front_slots[lane.index][index])

    def test_dragging_a_reserve_into_the_empty_slot_keeps_other_units_in_place(self):
        screen = self.editor()
        lane, _near, _far = screen.current()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        index = next(index for index, unit in enumerate(screen.front_slots[lane.index]) if unit is front)
        self.assertTrue(screen.drop_unit(front, battle_screen.PANE_RESERVE))
        expected = list(screen.front_slots[lane.index])
        reserve_rect, reserve = next((rect, unit) for rect, (unit, _note)
                                     in screen.row_paint[battle_screen.PANE_RESERVE]
                                     if screen.can_command(unit) and unit is not front)
        end = next(rect.center for rect, slot in screen.empty_slots[battle_screen.PANE_FRONT] if slot == index)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=reserve_rect.center, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1)])
        expected[index] = reserve
        self.assertEqual([id(unit) if unit is not None else None for unit in screen.front_slots[lane.index]],
                         [id(unit) if unit is not None else None for unit in expected])

    def test_all_own_front_units_can_be_removed_without_autofill(self):
        screen = self.editor()
        own_front = {id(unit): unit for slots in screen.front_slots.values() for unit in slots
                     if unit is not None and screen.can_command(unit)}
        for unit in own_front.values():
            self.assertTrue(screen.drop_unit(unit, battle_screen.PANE_RESERVE))
        self.assertTrue(all(unit is None or not screen.can_command(unit)
                            for slots in screen.front_slots.values() for unit in slots))
        screen.reset_assignments()
        self.assertTrue(any(unit is not None and screen.can_command(unit)
                            for slots in screen.front_slots.values() for unit in slots))

    def test_front_card_can_be_moved_to_a_vacant_position(self):
        # Give the player enough front slots to rearrange two of their cards.
        self.enterContext(mock.patch.object(combat_rules, "combat_width_for_terrain", return_value=24))
        screen = self.editor()
        lane, near, _far = screen.current()
        ours = [unit for unit in near.front if screen.can_command(unit)]
        removed, moved = ours[:2]
        original = list(screen.front_slots[lane.index])
        empty_index = next(index for index, unit in enumerate(original) if unit is removed)
        old_index = next(index for index, unit in enumerate(original) if unit is moved)
        self.assertTrue(screen.drop_unit(removed, battle_screen.PANE_RESERVE))
        self.assertTrue(screen.drop_unit(moved, battle_screen.PANE_FRONT, slot_index=empty_index))
        self.assertIs(screen.front_slots[lane.index][empty_index], moved)
        self.assertIsNone(screen.front_slots[lane.index][old_index])

    def test_exit_preserves_the_normal_combat_coverage_rule(self):
        from ui import dialogs
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        self.assertTrue(screen.drop_unit(front, battle_screen.PANE_RESERVE))
        self.assertTrue(any(unit is None for slots in screen.front_slots.values() for unit in slots))
        with mock.patch.object(dialogs, "ask_yes_no") as ask:
            screen.exit_screen()
        self.assertFalse(screen.done)
        ask.call_args.kwargs["on_result"](True)
        self.assertTrue(screen.done)
        for lane in screen.overview.battle.lanes:
            self.assertTrue(lane.a.front)
            self.assertTrue(lane.b.front)

    def test_exit_popup_continue_editing_keeps_the_arrangement(self):
        from ui.navigation import modal_stack
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(front, battle_screen.PANE_RESERVE)
        before = copy.deepcopy(self.province["units"])
        positions = {key: [id(unit) if unit is not None else None for unit in slots]
                     for key, slots in screen.front_slots.items()}
        exit_button = next(element for element in screen.elements if getattr(element, "text", "") == "Exit")
        exit_button.callback()
        modal = modal_stack.active()
        self.assertIsNotNone(modal)
        try:
            self.assertEqual(modal.no_label, "Continue Editing")
            self.assertEqual(modal.yes_label, "Leave As Is")
            modal.draw(self.surface)
            modal.handle_events([pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=modal.no_rect.center, button=1)])
            modal.update()
            self.assertFalse(screen.done)
            self.assertFalse(screen._exit_confirmation_open)
            self.assertEqual(self.province["units"], before)
            self.assertEqual({key: [id(unit) if unit is not None else None for unit in slots]
                              for key, slots in screen.front_slots.items()}, positions)
        finally:
            if modal_stack.active() is modal:
                modal_stack.pop()

    def test_exit_popup_escape_continues_editing(self):
        from ui.navigation import modal_stack
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(front, battle_screen.PANE_RESERVE)
        screen.handle_back_key()
        modal = modal_stack.active()
        self.assertIsNotNone(modal)
        try:
            modal.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
            modal.update()
            self.assertFalse(screen.done)
            self.assertFalse(screen._exit_confirmation_open)
            self.assertTrue(any(unit is None for slots in screen.front_slots.values() for unit in slots))
        finally:
            if modal_stack.active() is modal:
                modal_stack.pop()

    def test_back_checks_unselected_lanes_and_opens_only_one_popup(self):
        from ui import dialogs
        screen = self.editor()
        lane, _near, _far = screen.current()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(front, battle_screen.PANE_RESERVE)
        screen._select(next(index for index in range(len(screen.battle.lanes)) if index != lane.index))
        with mock.patch.object(dialogs, "ask_yes_no") as ask:
            screen.handle_back_key()
            screen.handle_back_key()
        ask.assert_called_once()
        self.assertFalse(screen.done)
        ask.call_args.kwargs["on_result"](False)
        self.assertFalse(screen.done)

    def test_filled_front_exits_without_a_popup(self):
        from ui import dialogs
        screen = self.editor()
        with mock.patch.object(dialogs, "ask_yes_no") as ask:
            screen.exit_screen()
        ask.assert_not_called()
        self.assertTrue(screen.done)

    def test_unfillable_empty_slots_do_not_trigger_a_popup(self):
        from ui import dialogs
        library = queries.get_unit_library()
        self.province["units"] = [queries.create_unit_dict("Infantry", owner, library)
                                  for owner in (self.a, self.x)]
        screen = self.editor()
        self.assertTrue(any(unit is None for slots in screen.front_slots.values() for unit in slots))
        with mock.patch.object(dialogs, "ask_yes_no") as ask:
            screen.exit_screen()
        ask.assert_not_called()
        self.assertTrue(screen.done)

    def test_forced_exit_after_country_change_does_not_ask_for_confirmation(self):
        from ui import dialogs
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        screen.drop_unit(front, battle_screen.PANE_RESERVE)
        with mock.patch.object(dialogs, "ask_yes_no") as ask, \
                mock.patch.object(self.map, "player_country", self.x):
            screen.update()
        ask.assert_not_called()
        self.assertTrue(screen.done)

    def test_reset_removes_manual_pins_and_rotates_wounded_units(self):
        screen = self.editor()
        ours = screen.my_units()
        hurt = ours[0]
        hurt["health"], hurt["max_health"] = 1, 100
        for unit in ours:
            unit["lane_target"] = self.x
            unit["combat_stance"] = "RESERVE"
        screen.reset_assignments()
        self.assertTrue(all("lane_target" not in unit for unit in ours))
        self.assertEqual(hurt.get("combat_stance"), "RESERVE")
        self.assertTrue(all("combat_stance" not in unit for unit in ours[1:]))

    def test_foreign_units_and_allied_front_rows_cannot_be_changed(self):
        screen = self.editor()
        _rect, reserve = self.own_row(screen, battle_screen.PANE_RESERVE)
        _lane, near, far = screen.current()
        ally = next(unit for unit in near.front if unit["owner"] != self.a)
        enemy = far.front[0]
        before = copy.deepcopy(self.province["units"])
        self.assertFalse(screen.drop_unit(reserve, battle_screen.PANE_FRONT, ally))
        self.assertFalse(screen.drop_unit(enemy, battle_screen.PANE_RESERVE))
        self.assertFalse(screen.drop_unit(enemy, battle_editor.PANE_HELD))
        self.assertFalse(screen.drop_unit(ally, battle_editor.PANE_HELD))
        self.assertEqual(self.province["units"], before)

    def test_tactical_reset_leaves_other_divisions_unchanged(self):
        self.map.tactical_mode = True
        self.map.player_unit = next(unit for unit in self.province["units"] if unit["owner"] == self.a)
        self.addCleanup(setattr, self.map, "tactical_mode", False)
        self.addCleanup(setattr, self.map, "player_unit", None)
        screen = self.editor()
        others = [unit for unit in self.province["units"] if unit is not self.map.player_unit]
        for unit in others:
            unit["combat_stance"] = "RESERVE"
        before = copy.deepcopy(others)
        screen.reset_assignments()
        self.assertEqual(others, before)

    def test_stale_unit_reference_cannot_be_dropped(self):
        screen = self.editor()
        _rect, reserve = self.own_row(screen, battle_screen.PANE_RESERVE)
        self.province["units"] = [unit for unit in self.province["units"] if unit is not reserve]
        before = copy.deepcopy(self.province["units"])
        self.assertFalse(screen.drop_unit(reserve, battle_screen.PANE_FRONT))
        self.assertEqual(self.province["units"], before)

    def test_snapshot_change_during_drag_cancels_the_drop(self):
        screen = self.editor()
        start, _reserve = self.own_row(screen, battle_screen.PANE_RESERVE)
        end, _front = self.own_row(screen, battle_screen.PANE_FRONT)
        before = copy.deepcopy(self.province["units"])
        screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start.center, button=1)])
        self.map.invalidate_map_presentation_cache()
        screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end.center, button=1)])
        self.assertEqual(self.province["units"], before)
        self.assertIsNone(screen.drag_unit)

    def test_invalid_batch_changes_no_units(self):
        from map_logic.actions import unit_actions
        screen = self.editor()
        own = screen.my_units()[0]
        foreign = next(unit for unit in self.province["units"] if unit["owner"] != self.a)
        before = copy.deepcopy(self.province["units"])
        for changes in ([(own, None, True), (foreign, None, True)],
                        [(own, None, True), (own, [self.x], False)]):
            with self.assertRaises(ValueError):
                unit_actions.apply_battle_orders(self.map, self.a, self.province, changes)
            self.assertEqual(self.province["units"], before)

    def test_horizontal_front_scrollbars_reach_empty_slots_and_allow_drops(self):
        self.enterContext(mock.patch.object(combat_rules, "combat_width_for_terrain", return_value=120))
        screen = self.editor()
        _rect, unit = self.own_row(screen, battle_screen.PANE_FRONT)
        self.assertTrue(screen.drop_unit(unit, battle_screen.PANE_RESERVE))
        pane = battle_screen.PANE_FRONT
        initially_visible = {index for rect, index in screen.empty_slots[pane]
                             if screen.regions[pane].collidepoint(rect.center)}
        before = copy.deepcopy(self.province["units"])
        positions = {index: list(slots) for index, slots in screen.front_slots.items()}
        for pane in (battle_screen.PANE_FRONT, battle_screen.PANE_ENEMY):
            screen.draw(self.surface)
            other_scrolls = {name: screen.pane_scroll(name) for name in screen.regions if name != pane}
            with mock.patch.object(pygame.mouse, "get_pos", return_value=screen.regions[pane].center):
                screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
            self.assertLess(screen.pane_scroll(pane), 0)
            screen.draw(self.surface)
            track = getattr(screen, screen.scroll_attrs(pane)["track_attr"])
            self.assertIsNotNone(track)
            pos = (track.right - 1, track.centery)
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
            self.assertEqual(screen.pane_scroll(pane), screen.pane_scroll_limit(pane))
            self.assertEqual(other_scrolls, {name: screen.pane_scroll(name) for name in other_scrolls})
        self.assertEqual(self.province["units"], before)
        self.assertEqual(screen.front_slots, positions)

        pane = battle_screen.PANE_FRONT
        target, index = next((rect.center, index) for rect, index in screen.empty_slots[pane]
                             if index not in initially_visible
                             and screen.regions[pane].collidepoint(rect.center))
        source = next(rect.center for rect, (candidate, _note)
                      in screen.row_paint[battle_screen.PANE_RESERVE] if candidate is unit)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=source, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=target, button=1)])
        lane, _near, _far = screen.current()
        self.assertIs(screen.front_slots[lane.index][index], unit)

    def test_reserve_scrollbar_browses_cards_without_changing_orders(self):
        from screens.game.battle_editor import PANE_ENEMY_RESERVE
        library = queries.get_unit_library()
        self.province["units"].extend(
            queries.create_unit_dict("Infantry", self.a, library) for _ in range(30))
        screen = self.editor()
        screen.draw(self.surface)
        pane = battle_screen.PANE_RESERVE
        attrs = screen.scroll_attrs(pane)
        track = getattr(screen, attrs["track_attr"])
        self.assertIsNotNone(track)
        before = copy.deepcopy(self.province["units"])
        pos = (track.centerx, track.bottom - 2)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
        self.assertLess(screen.pane_scroll(pane), 0)
        self.assertEqual(screen.pane_scroll(pane), screen.pane_scroll_limit(pane))
        self.assertEqual(screen.pane_scroll(PANE_ENEMY_RESERVE), 0)
        self.assertEqual(self.province["units"], before)

    def test_held_scrollbar_browses_units_without_changing_orders(self):
        library = queries.get_unit_library()
        held = [queries.create_unit_dict('Infantry', self.a, library) for _ in range(30)]
        for unit in held:
            unit['combat_stance'] = 'RESERVE'
        self.province['units'].extend(held)
        screen = self.editor()
        screen.draw(self.surface)
        pane = battle_editor.PANE_HELD
        track = getattr(screen, screen.scroll_attrs(pane)['track_attr'])
        before = copy.deepcopy(self.province['units'])
        pos = (track.centerx, track.bottom - 2)
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1)])
        self.assertLess(screen.pane_scroll(pane), 0)
        self.assertEqual(screen.pane_scroll(pane), screen.pane_scroll_limit(pane))
        self.assertEqual(screen.pane_scroll(battle_screen.PANE_RESERVE), 0)
        self.assertEqual(self.province['units'], before)

    def test_enemy_cards_cannot_be_dragged(self):
        screen = self.editor()
        rect, (_unit, _note) = screen.row_paint[battle_screen.PANE_ENEMY][0]
        before = copy.deepcopy(self.province["units"])
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=rect.center, button=1),
            pygame.event.Event(pygame.MOUSEBUTTONUP, pos=screen.regions[battle_screen.PANE_FRONT].center,
                               button=1)])
        self.assertIsNone(screen.drag_unit)
        self.assertEqual(self.province["units"], before)

    def test_enemy_reserves_and_held_are_separate_visible_read_only_groups(self):
        screen = self.editor()
        _lane, _near, far = screen.current()
        enemies = [unit for unit in self.province['units']
                   if unit['owner'] in far.nations and id(unit) not in screen.seated()]
        available, held, hidden = enemies[:3]
        held['combat_stance'] = hidden['combat_stance'] = 'RESERVE'
        with mock.patch.object(queries, 'filter_visible_units',
                               side_effect=lambda units, *args: [unit for unit in units if unit is not hidden]):
            screen.refresh_ui()
        listed_reserves = [unit for _rect, (unit, _note) in screen.row_paint[battle_editor.PANE_ENEMY_RESERVE]]
        listed_held = [unit for _rect, (unit, _note) in screen.row_paint[battle_editor.PANE_ENEMY_HELD]]
        self.assertIn(id(available), {id(unit) for unit in listed_reserves})
        self.assertIn(id(held), {id(unit) for unit in listed_held})
        self.assertTrue(all(unit.get('combat_stance') != 'RESERVE' for unit in listed_reserves))
        self.assertTrue(all(unit.get('combat_stance') == 'RESERVE' for unit in listed_held))
        self.assertNotIn(id(hidden), {id(unit) for unit in listed_reserves + listed_held})
        before = copy.deepcopy(self.province['units'])
        for pane, unit in ((battle_editor.PANE_ENEMY_RESERVE, available), (battle_editor.PANE_ENEMY_HELD, held)):
            start = next(rect for rect, (current, _note) in screen.row_paint[pane] if current is unit)
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start.center, button=1),
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=screen.regions[battle_editor.PANE_HELD].center, button=1)])
            self.assertIsNone(screen.drag_unit)
        self.assertEqual(self.province['units'], before)

    def test_idle_frames_use_cached_battle_data(self):
        screen = self.editor()
        with mock.patch.object(combat_rules, "build_battle") as build, \
                mock.patch.object(screen.overview, "_estimate_lane_outcome") as estimate:
            screen.draw(self.surface)
            screen.update()
            screen.draw(self.surface)
        build.assert_not_called()
        estimate.assert_not_called()

    def test_submitted_realtime_turn_disables_changes(self):
        from types import SimpleNamespace
        screen = self.editor()
        _rect, front = self.own_row(screen, battle_screen.PANE_FRONT)
        player = SimpleNamespace(submitted=True, eliminated=False)
        session = SimpleNamespace(phase="TURN", players={"fixture": player})
        with mock.patch.object(self.map, "realtime_multiplayer", True), \
                mock.patch.object(self.map, "realtime_session", session), \
                mock.patch.object(self.map, "realtime_player_id", "fixture"):
            before = copy.deepcopy(self.province["units"])
            self.assertFalse(screen.drop_unit(front, battle_screen.PANE_RESERVE))
            self.assertFalse(screen.drop_unit(front, battle_editor.PANE_HELD))
            screen.reset_assignments()
            self.assertEqual(self.province["units"], before)


class SideReserveTests(BattleScreenTestCase):
    """Each side's reserves include its allies.

    An ally's reserves are what steps into the front rank as it dies, so a side
    that reads three against six may be nothing of the kind. Listing only our own
    made every fight look like we were holding it alone.
    """

    def our_side(self, screen):
        _lane, near, _far = screen.current()
        return near

    def listed_units(self, screen, pane):
        """Collect every card through the pane's independent scroll range."""
        listed = set()
        scroll = 0
        while True:
            setattr(screen, screen.scroll_attrs(pane)["attr"], scroll)
            screen.refresh_ui()
            listed.update(id(unit) for _rect, (unit, _note)
                          in screen.row_paint[pane])
            limit = screen.pane_scroll_limit(pane)
            if scroll <= limit:
                return listed
            step = max(1, screen.regions[pane].height - battle_screen.ROW_H)
            scroll = max(limit, scroll - step)

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

    def test_reserve_cards_do_not_register_clickable_controls(self):
        screen = self.screen()
        self.assertTrue(screen.row_paint[battle_screen.PANE_FRONT])
        self.assertFalse([el for el in screen.elements
                          if getattr(el, "pane", None) in battle_screen.UNIT_PANES])

    def test_both_sides_reserves_remain_reachable(self):
        screen = self.screen()
        _lane, near, far = screen.current()
        self.assertEqual(self.listed_units(screen, battle_screen.PANE_FRONT),
                         {id(unit) for unit in list(near.front) + screen.side_bench(near)})
        self.assertEqual(self.listed_units(screen, battle_screen.PANE_ENEMY),
                         {id(unit) for unit in list(far.front) + list(far.reserve)})

    def test_scrolling_enemy_reserves_preserves_the_other_rosters(self):
        # Small explicit fronts leave enough reserves to exercise scrolling,
        # independent of terrain width and front-rank tuning.
        self.province["units"].extend(
            queries.create_unit_dict("Infantry", nation, queries.get_unit_library())
            for nation in (self.x, self.y) for _ in range(12))
        with mock.patch.object(combat_rules, "lane_slots", return_value=2):
            screen = self.screen()
            screen._select(max(range(len(screen.battle.lanes)), key=lambda index:
                               len(screen.near_far(screen.battle.lanes[index])[1].reserve)))
            screen.draw(self.surface)
            pane = battle_screen.PANE_ENEMY
            others = {name: screen.pane_scroll(name) for name in screen.regions if name != pane}
            with mock.patch.object(pygame.mouse, "get_pos", return_value=screen.regions[pane].center):
                screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])

        self.assertLess(screen.pane_scroll(pane), 0)
        self.assertEqual(others, {name: screen.pane_scroll(name) for name in others})

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
        self.map.player_country = next(
            n for n in self.map.nation_data
            if queries.is_playable(n, self.map.nation_data)
            and n not in (self.a, self.b, self.x, self.y))
        self.addCleanup(setattr, self.map, "player_country", self.a)

        screen = self.screen()
        _lane, near, far = screen.current()
        for pane, side in ((battle_screen.PANE_FRONT, near),
                           (battle_screen.PANE_ENEMY, far)):
            self.assertEqual(self.listed_units(screen, pane),
                             {id(unit) for unit in list(side.front) + list(side.reserve)})


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
        self.assertTrue(screen.row_paint[battle_screen.PANE_FRONT])
        self.assertFalse([el for el in screen.elements
                          if getattr(el, "pane", None) in battle_screen.UNIT_PANES])
        self.assertTrue(all(not screen.can_command(unit)
                            for unit in self.province["units"]))

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

    def test_overview_cards_cannot_issue_orders_in_tactical_mode(self):
        screen = self.screen()
        self.assertFalse([el for el in screen.elements
                          if getattr(el, "pane", None) in battle_screen.UNIT_PANES])
        self.assertEqual(screen.my_units(), [self.map.player_unit])

    def test_clearing_lane_orders_leaves_the_rest_of_the_army_alone(self):
        screen = self.screen()
        others = [u for u in self.province["units"]
                  if u["owner"] == self.a and u is not self.map.player_unit]
        for unit in others:
            unit["combat_stance"] = "RESERVE"

        screen.clear_orders()

        for unit in others:
            self.assertEqual(unit.get("combat_stance"), "RESERVE")


class RowOrderingTests(BattleScreenTestCase):
    """The viewer's units appear first in each lane."""

    def test_rosters_list_frontline_then_available_reserves_then_held(self):
        # Explicit small fronts leave both kinds of reserves on each side.
        for unit in self.province["units"][::3]:
            unit["combat_stance"] = "RESERVE"
        before = copy.deepcopy(self.province["units"])
        with mock.patch.object(combat_rules, "lane_slots", return_value=2):
            screen = self.screen()
        _lane, near, far = screen.current()
        for pane, side in ((battle_screen.PANE_FRONT, near),
                           (battle_screen.PANE_ENEMY, far)):
            front_ids = {id(unit) for unit in side.front}
            reserves = screen.side_bench(side) if screen.is_mine(side) else side.reserve
            expected = list(side.front)
            expected.extend(unit for unit in reserves if unit.get("combat_stance") != "RESERVE")
            expected.extend(unit for unit in reserves if unit.get("combat_stance") == "RESERVE")
            listed = [unit for _rect, (unit, _note) in screen.row_paint[pane]]
            self.assertEqual([id(unit) for unit in listed], [id(unit) for unit in expected])
            self.assertEqual({id(unit) for unit in listed[:len(side.front)]}, front_ids)
        self.assertTrue(any(unit.get("combat_stance") == "RESERVE" for unit in screen.side_bench(near)))
        self.assertTrue(any(unit.get("combat_stance") != "RESERVE" for unit in screen.side_bench(near)))
        self.assertEqual(self.province["units"], before)

    def test_your_side_is_listed_first_whichever_half_of_the_lane_it_is(self):
        screen = self.screen()
        for lane in screen.battle.lanes:
            near, _far = screen.near_far(lane)
            if screen.is_mine(lane.a) or screen.is_mine(lane.b):
                self.assertTrue(screen.is_mine(near))


class ReadOnlyOrdersTests(BattleScreenTestCase):
    """The Orders screen on a province the player commands nothing in."""

    def orders_screen(self, player):
        from screens.game.orders import Orders_Screen

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
        from screens.game.orders import Orders_Screen

        self.map.player_country = self.a if player is None else player
        previous_selection_mode = self.map.selection_mode
        self.map.selection_mode = False
        self.addCleanup(setattr, self.map, "selection_mode", previous_selection_mode)
        screen = Orders_Screen()
        screen.start_with_province(self.province, self.map)
        return screen

    def preserve_materials(self, nation):
        before = nation.get("materials", 0)
        self.addCleanup(nation.__setitem__, "materials", before)
        return before

    def test_leaving_orders_clears_the_map_unit_selection(self):
        was_selection_mode = self.map.selection_mode
        self.map.selection_mode = False
        self.addCleanup(setattr, self.map, "selection_mode", was_selection_mode)
        self.map.clear_map_unit_selection()
        self.addCleanup(self.map.clear_map_unit_selection)

        screen = self.orders_screen()
        self.assertTrue(self.map.selected_unit_records())

        screen.exit_screen()

        self.assertEqual(self.map.selected_unit_ids, set())
        self.assertIsNone(self.map.unit_selection_drag)

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

    def test_orders_roster_keeps_per_unit_actions_for_a_selected_group(self):
        # The test harness starts in selection mode, which deliberately blocks
        # map commands.  Orders' map-wide roster is exercised in the normal
        # playable Units view instead.
        was_selection_mode = self.map.selection_mode
        self.map.selection_mode = False
        self.addCleanup(setattr, self.map, "selection_mode", was_selection_mode)
        owned_indices = [index for index, unit in enumerate(self.province["units"])
                         if unit["owner"] == self.a]
        for index in owned_indices:
            self.province["units"][index]["order"] = {
                "type": "MOVE", "path": []}

        screen = self.orders_screen()
        screen.draw(self.surface)

        # The roster now means exactly the current command selection, not all
        # units sharing the province.  This is what lets it represent a group
        # selected across many provinces without leaking foreign orders.
        visible_indices = set(screen.unit_row_icons)
        self.assertEqual(visible_indices, set(owned_indices))
        self.assertEqual(len(screen.action_buttons), len(owned_indices) * 6)

        for selected_index in owned_indices:
            buttons = [button for button in screen.action_buttons
                       if button.unit_index == selected_index]
            self.assertEqual(len(buttons), 6)
            self.assertEqual({button.action_slot for button in buttons}, set(range(6)))

        focused_unit = self.province["units"][owned_indices[0]]

        # Empty MOVE dictionaries are idle placeholders. They need no cancel control.
        self.assertEqual(screen.cancel_rects, [])
        summary, _color = screen._order_summary(owned_indices[0], focused_unit)
        self.assertEqual(summary, "Ready")

        # Clicking a selected member of a larger group focuses that member.
        screen.toggle_selected_unit(focused_unit)
        self.assertEqual({id(unit) for unit, _province in self.map.selected_unit_records()},
                         {id(focused_unit)})
        screen.draw(self.surface)
        self.assertEqual(set(screen.unit_row_icons), {owned_indices[0]})

        # Clicking the sole selected member retains the normal deselect action.
        screen.toggle_selected_unit(focused_unit)
        self.assertEqual(self.map.selected_unit_records(), [])

        # Select All reselects the group, then clears it on a second click.
        screen.select_unit("ALL")
        screen.select_unit("ALL")
        self.assertEqual(self.map.selected_unit_records(), [])
        screen.draw(self.surface)
        self.assertEqual(set(screen.unit_row_icons), set())

    def test_left_clicking_open_map_space_leaves_orders(self):
        import pygame as pg

        screen = self.orders_screen()
        screen.exit_screen = mock.Mock()
        self.map.unit_hover_hitboxes = []

        screen.additional_events(
            pg.event.Event(pg.MOUSEBUTTONDOWN, pos=(640, 360), button=1))
        screen.additional_events(
            pg.event.Event(pg.MOUSEBUTTONUP, pos=(640, 360), button=1))

        screen.exit_screen.assert_called_once_with()

    def test_drawing_orders_suppresses_only_its_embedded_map_flag(self):
        from ui.bars import flag_renderer

        screen = self.orders_screen()
        self.map.hide_flag = False
        with mock.patch.object(flag_renderer, "flag_icons") as flag_assets:
            screen.draw(self.surface)

        flag_assets.flag_surface.assert_not_called()
        self.assertFalse(self.map.hide_flag)


class ButtonSwapTests(BattleScreenTestCase):
    """Orders remains the map entry point, including while the tile fights."""

    def visible_pair(self):
        from screens.game import map as map_module

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

        from screens.game import map as map_module

        enabled = {}

        def set_btn(btn, visible, is_enabled, text, color="green"):
            enabled[id(btn)] = (visible, is_enabled)

        map_module.set_orders_or_battle(self.map, set_btn, False)
        self.assertEqual(enabled[id(self.map.btn_go_orders)], (True, True))
        self.assertEqual(enabled[id(self.map.btn_go_battle)], (False, False))

    def test_orders_screen_offers_battle_button_for_a_fighting_tile(self):
        from screens.game.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)

        labels = [getattr(el, "text", "") for el in orders.elements]
        self.assertIn("Manage Battle", labels)

    def test_orders_opens_battle_beside_itself(self):
        from screens.game.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()

        self.assertIsInstance(orders.battle_screen, battle_screen.Battle_Screen)
        self.assertTrue(orders.battle_screen.embedded)
        self.assertIs(orders.battle_screen.origin_screen, orders)
        self.assertEqual(orders.battle_screen.panel_rect, orders.battle_panel_rect())

    def test_closing_embedded_battle_keeps_orders_open(self):
        from screens.game.orders import Orders_Screen

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
        from screens.game.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        orders.go_to_battle()

        orders.exit_screen()

        self.assertIsNone(orders.battle_screen)
        self.assertTrue(orders.done)

    def test_closing_battle_modal_reveals_its_orders_screen(self):
        from screens.game.orders import Orders_Screen

        orders = Orders_Screen()
        orders.start_with_province(self.province, self.map)
        battle = battle_screen.Battle_Screen(
            self.map, self.province, origin_screen=orders)

        battle.exit_screen()

        self.assertTrue(battle.done)
        self.assertFalse(orders.done)
        self.assertIs(self.map.selected_province, self.province)

    def test_preemptive_fighting_tile_enters_orders_before_battle(self):
        from screens.game import map_input 
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
        with mock.patch.object(map_input, "_resync_view_mode_row"):
            map_input.navigate_view_mode(self.map, "UNITS")

        self.assertTrue(self.map.done)
        self.assertEqual(self.map.next_state, "ORDERS")


class TacticalOrdersScreenTests(BattleScreenTestCase):
    """Tactical mode has its own Orders screen for the one division it commands."""

    GROUP_CONTROLS = {"Select All", "Clear ALL Orders", "Ungroup", "Set Mission"}

    def setUp(self):
        super().setUp()
        for attribute, value in (("tactical_mode", True), ("player_country", self.a)):
            self.enterContext(mock.patch.object(self.map, attribute, value))
        own = [unit for unit in self.province["units"] if unit["owner"] == self.a]
        self.player_unit, self.peer = own[0], own[1]
        self.enterContext(mock.patch.object(self.map, "player_unit", self.player_unit))
        self.addCleanup(self.map.clear_map_unit_selection)
        self.map.clear_map_unit_selection()

    def tactical_screen(self, province=None):
        from screens.game.tactical_orders import Tactical_Orders_Screen

        screen = Tactical_Orders_Screen()
        screen.start_with_province(province or self.province, self.map)
        return screen

    def test_every_orders_route_names_the_tactical_screen(self):
        from screens.game import map_input

        self.assertEqual(map_input.orders_state(self.map), "TACTICAL_ORDERS")
        with mock.patch.object(self.map, "tactical_mode", False):
            self.assertEqual(map_input.orders_state(self.map), "ORDERS")

        old_navigation = c.MAP_NAVIGATION_MODE
        self.addCleanup(setattr, c, "MAP_NAVIGATION_MODE", old_navigation)
        # go_to_orders_screen leaves a one-shot flag for the screen it opens.
        self.addCleanup(lambda: vars(self.map).pop("_orders_return_to_province_menu", None))
        for attribute in ("done", "next_state", "secondary_mode"):
            self.enterContext(mock.patch.object(self.map, attribute, getattr(self.map, attribute)))
        for navigation in ("CLASSIC", "PREEMPTIVE"):
            with self.subTest(navigation=navigation):
                c.MAP_NAVIGATION_MODE = navigation
                self.map.done = False
                self.map.next_state = None
                with mock.patch.object(map_input, "_resync_view_mode_row"):
                    map_input.go_to_orders_screen(self.map)
                self.assertTrue(self.map.done)
                self.assertEqual(self.map.next_state, "TACTICAL_ORDERS")

    def test_closing_a_direct_battle_returns_to_tactical_orders(self):
        for attribute in ("done", "next_state"):
            self.enterContext(mock.patch.object(self.map, attribute, getattr(self.map, attribute)))
        self.map.done = False
        battle = battle_screen.Battle_Screen(self.map, self.province)

        battle.exit_screen()

        self.assertEqual(self.map.next_state, "TACTICAL_ORDERS")

    def test_only_the_division_gets_commands_and_no_group_controls_exist(self):
        screen = self.tactical_screen()

        labels = {getattr(element, "text", "") for element in screen.elements}
        self.assertFalse(labels & self.GROUP_CONTROLS)
        self.assertIn("Manage Battle", labels)
        self.assertTrue(screen.action_buttons)
        self.assertEqual({button.unit_index for button in screen.action_buttons},
                         {screen._player_row_key})
        self.assertTrue(self.map.is_unit_selected(self.player_unit))
        listed = [unit for _key, unit, _province, _index in screen._other_rows]
        self.assertNotIn(self.player_unit, listed)
        self.assertEqual(len(listed), len(self.province["units"]) - 1)

    def test_listed_units_cannot_be_ordered(self):
        screen = self.tactical_screen()
        peer_index = self.province["units"].index(self.peer)
        order = {"type": "MOVE", "path": [self.province["id"]]}
        self.peer["order"] = order
        self.addCleanup(self.peer.pop, "order", None)

        screen.cancel_unit_order(peer_index, self.province)
        screen.disband_unit(peer_index, self.province)
        screen.start_renaming(peer_index, self.province)

        self.assertIs(self.peer["order"], order)
        self.assertIsNone(screen.renaming_unit_index)
        self.assertNotIn(self.peer, [unit for unit, _province in self.map.selected_unit_records()])

    def test_army_peers_elsewhere_are_not_listed(self):
        far = next(p for p in self.map.map_data.values()
                   if p is not self.province and not queries.is_water_province(p))
        far_peer = queries.create_unit_dict("Infantry", self.a, queries.get_unit_library(self.map))
        self.enterContext(mock.patch.dict(far, units=[far_peer]))
        nation = self.map.nation_data[self.a]
        self.enterContext(mock.patch.dict(nation, armies=list(nation.get("armies", []))))
        queries.ensure_unit_ids(self.map.map_data)
        queries.create_army(self.a, [self.player_unit["unit_id"], far_peer["unit_id"]],
                            self.map.nation_data, self.map.map_data)

        screen = self.tactical_screen()

        listed = [unit for _key, unit, _province, _index in screen._other_rows]
        self.assertNotIn(far_peer, listed)
        self.assertTrue(all(province is self.province
                            for _key, _unit, province, _index in screen._other_rows))

    def test_clicking_another_stack_lists_that_tile_without_commands(self):
        far = next(p for p in self.map.map_data.values()
                   if p is not self.province and not queries.is_water_province(p))
        screen = self.tactical_screen()

        screen.inspect_province(far)

        self.assertIs(screen.target_province, far)
        self.assertTrue(self.map.is_unit_selected(self.player_unit))
        self.assertEqual({button.unit_index for button in screen.action_buttons},
                         {screen._player_row_key})

    def test_screen_builds_and_paints(self):
        screen = self.tactical_screen()
        screen.open_battle_panel()

        screen.draw(self.surface)

        self.assertIsNotNone(screen.battle_screen)


if __name__ == "__main__":
    unittest.main()
