"""Regression coverage for map-level unit routing without a live display."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

import pygame

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import queries
import data.constants as c
from map_logic.camera import camera_handler
from map_logic.rendering import overlay_renderer
from screens.menu_screens.map import Map
from screens.map_related_screens.orders import Orders_Screen
from ui import event_handler
from map_logic.setup import player_setup


def province(province_id, neighbors):
    return {"id": province_id, "neighbors": neighbors, "owner": "Unclaimed",
            "terrain": "Plains", "units": []}


class RouteFindingTests(unittest.TestCase):
    def setUp(self):
        self.p1 = province(1, [2])
        self.p2 = province(2, [1, 3, 4])
        self.p3 = province(3, [2])
        self.p4 = province(4, [2, 5])
        self.p5 = province(5, [4])
        self.by_id = {p["id"]: p for p in (self.p1, self.p2, self.p3, self.p4, self.p5)}
        self.nations = {"A": {"at_war_with": []}}

    def test_shortest_legal_path_is_deterministic(self):
        unit = {"owner": "A", "type": "Infantry"}
        self.assertEqual(queries.find_unit_move_path(unit, self.p1, 3, self.by_id, self.nations),
                         [2, 3])

    def test_unreachable_destination_returns_none(self):
        unit = {"owner": "A", "type": "Infantry"}
        self.p2["neighbors"].remove(4)
        self.p4["neighbors"].remove(2)
        self.assertIsNone(queries.find_unit_move_path(unit, self.p1, 5, self.by_id, self.nations))


class MapOrderTests(unittest.TestCase):
    def make_map(self):
        game = object.__new__(Map)
        p1, p2, p3 = province(1, [2]), province(2, [1, 3]), province(3, [2])
        slow = {"owner": "A", "type": "Infantry", "speed": 1}
        fast = {"owner": "A", "type": "Infantry", "speed": 2}
        p1["units"] = [slow]
        p2["units"] = [fast]
        game.map_data = {"one": p1, "two": p2, "three": p3}
        game.id_to_province = {1: p1, 2: p2, 3: p3}
        game.nation_data = {"A": {"at_war_with": []}}
        game.player_country = "A"
        game.selection_mode = game.is_editor = game.viewing_ai_moves = game.ai_is_thinking = False
        game.tactical_mode = False
        game.selected_unit_ids = {id(slow), id(fast)}
        game.unit_selection_drag = None
        game.show_feedback = lambda _text: None
        return game, slow, fast, p3

    def test_each_selected_unit_gets_its_own_route(self):
        game, slow, fast, destination = self.make_map()
        self.assertTrue(game.issue_selected_move_orders(destination))
        self.assertEqual(slow["order"]["path"], [2, 3])
        self.assertEqual(fast["order"]["path"], [3])

    def test_shift_destination_appends_after_existing_waypoint(self):
        game, slow, fast, destination = self.make_map()
        self.assertTrue(game.issue_selected_move_orders(game.id_to_province[2]))
        self.assertTrue(game.issue_selected_move_orders(destination, append=True))
        self.assertEqual(slow["order"]["path"], [2, 3])
        self.assertEqual(fast["order"]["path"], [3])

    def test_unreachable_member_keeps_all_orders_unchanged(self):
        game, slow, fast, destination = self.make_map()
        fast["type"] = "Battleship"
        self.assertFalse(game.issue_selected_move_orders(destination))
        self.assertNotIn("order", slow)
        self.assertNotIn("order", fast)

    def test_selection_rectangle_draws_when_dragged_up_and_left(self):
        """pygame.Rect.normalize mutates; it must never be used as a return value."""
        game = object.__new__(Map)
        game.unit_selection_drag = {"start": (200, 200), "current": (100, 100)}
        with patch("screens.menu_screens.map.map_renderer.draw_map_screen"):
            Map.additional_draw(game, pygame.Surface((400, 300)))

    def test_plain_click_focuses_one_member_and_shift_click_adds_another(self):
        game, slow, fast, _destination = self.make_map()

        self.assertTrue(game.click_select_map_units([slow]))
        self.assertEqual([unit for unit, _province in game.selected_unit_records()], [slow])
        self.assertFalse(game.click_select_map_units([slow]))
        self.assertEqual(game.selected_unit_records(), [])

        game.selected_unit_ids = {id(slow)}
        self.assertTrue(game.click_select_map_units([fast], additive=True))
        self.assertEqual({id(unit) for unit, _province in game.selected_unit_records()},
                         {id(slow), id(fast)})

    def test_selecting_an_army_refocuses_the_orders_target(self):
        unit = {"unit_id": "unit-a", "owner": "A", "type": "Infantry"}
        second_unit = {"unit_id": "unit-b", "owner": "A", "type": "Infantry"}
        origin = province(1, [])
        second_origin = province(2, [])
        origin["center"] = (100, 100)
        second_origin["center"] = (300, 200)
        origin["units"] = [unit]
        second_origin["units"] = [second_unit]
        game = object.__new__(Map)
        game.player_country = "A"
        game.nation_data = {"A": {"armies": [{
            "id": "army-a", "unit_ids": ["unit-a", "unit-b"]}]}}
        game.map_data = {"origin": origin, "second": second_origin}
        game.can_select_map_units = lambda: True
        game.select_map_units = Mock()
        game.focus_camera_on_army = Mock()

        self.assertTrue(Map.select_army(game, "army-a", open_orders=False))

        game.select_map_units.assert_called_once_with([unit, second_unit])
        self.assertIs(game.selected_province, origin)
        game.focus_camera_on_army.assert_called_once_with([
            (unit, origin), (second_unit, second_origin)])

    def test_army_camera_focus_uses_the_average_member_position(self):
        first = {"owner": "A"}
        second = {"owner": "A"}
        first_province = {"center": (100, 100)}
        second_province = {"center": (300, 200)}
        game = object.__new__(Map)
        game.loop_map = False
        game.map_w = 1000
        game.camera = object()
        game.total_ui_h = 120

        with patch("screens.menu_screens.map.camera_handler.center_camera_on_province") as center:
            self.assertTrue(Map.focus_camera_on_army(
                game, [(first, first_province), (second, second_province)]))

        center.assert_called_once_with(
            game.camera, (200, 150), c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            game.total_ui_h, x_offset=c.ORDERS_PANEL_CAMERA_X_OFFSET)


class OrdersSelectionRowsTests(unittest.TestCase):
    def test_roster_keeps_each_selected_unit_and_its_own_origin(self):
        """The Orders panel must not collapse a cross-province group to one tile."""
        first = province(1, [])
        second = province(2, [])
        unit_a = {"owner": "A", "type": "Infantry"}
        unit_b = {"owner": "A", "type": "Infantry"}
        first["units"] = [unit_a]
        second["units"] = [unit_b]

        map_stub = type("MapStub", (), {
            "selected_unit_records": lambda self: [(unit_a, first), (unit_b, second)],
        })()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = map_stub
        screen.target_province = first

        rows = screen._visible_rows()

        self.assertEqual([(unit, origin, index) for _key, unit, origin, index in rows],
                         [(unit_a, first, 0), (unit_b, second, 0)])
        self.assertEqual(rows[0][0], 0)
        self.assertEqual(rows[1][0], (2, 0))

    def test_clicking_another_army_member_preserves_roster_scroll(self):
        origin = province(1, [])
        first = {"unit_id": "first", "owner": "A", "type": "Infantry"}
        second = {"unit_id": "second", "owner": "A", "type": "Infantry"}
        origin["units"] = [first, second]

        class MapStub:
            player_country = "A"
            tactical_mode = False

            def __init__(self):
                self.selected_ids = {id(first)}
                self.selected_province = None
                self.nation_data = {"A": {"armies": [{
                    "id": "army", "unit_ids": ["first", "second"]}]}}
                self.map_data = {1: origin}

            def click_select_map_units(self, units, additive=False):
                unit_ids = {id(unit) for unit in units}
                self.selected_ids = (self.selected_ids | unit_ids
                                     if additive else unit_ids)
                return bool(self.selected_ids & unit_ids)

            def is_unit_selected(self, unit):
                return id(unit) in self.selected_ids

            def selected_unit_records(self):
                return [(unit, origin) for unit in origin["units"]
                        if id(unit) in self.selected_ids]

        screen = object.__new__(Orders_Screen)
        screen.map_screen = MapStub()
        screen.target_province = origin
        screen.read_only = False
        screen.scroll_y = -80
        screen.selected_unit_index = 0
        screen.bombarding_unit_index = None
        screen.refresh_ui = lambda: None

        self.assertEqual([unit for _key, unit, _province, _index in screen._visible_rows()],
                         [first, second])
        with patch("screens.map_related_screens.orders.pygame.key.get_mods", return_value=0):
            screen.toggle_selected_unit(second, origin)

        self.assertEqual(screen.scroll_y, -80)
        self.assertIs(screen.target_province, origin)
        self.assertEqual(screen.map_screen.selected_ids, {id(second)})
        self.assertEqual([unit for _key, unit, _province, _index in screen._visible_rows()],
                         [first, second])

    def test_select_all_uses_every_owned_unit_and_clears_the_selection(self):
        """Select All is map-wide; clearing it leaves no stale Orders rows."""
        first = province(1, [])
        second = province(2, [])
        unit_a = {"owner": "A", "type": "Infantry"}
        unit_b = {"owner": "A", "type": "Infantry"}
        first["units"] = [unit_a]
        second["units"] = [unit_b]

        class MapStub:
            player_country = "A"
            tactical_mode = False
            map_data = {1: first, 2: second}

            def __init__(self):
                self.selected_ids = {id(unit_a)}

            def selected_unit_records(self):
                return [(unit, province)
                        for province in self.map_data.values()
                        for unit in province["units"] if id(unit) in self.selected_ids]

            def is_unit_selected(self, unit):
                return id(unit) in self.selected_ids

            def select_map_units(self, units, additive=False):
                if not additive:
                    self.selected_ids.clear()
                self.selected_ids.update(id(unit) for unit in units)

            def deselect_map_units(self, units):
                self.selected_ids.difference_update(id(unit) for unit in units)

        screen = object.__new__(Orders_Screen)
        screen.map_screen = MapStub()
        screen.target_province = first
        screen.read_only = False
        screen.selected_unit_index = None
        screen.bombarding_unit_index = None
        screen.refresh_ui = lambda: None

        screen.select_unit("ALL")
        self.assertEqual(screen.map_screen.selected_ids, {id(unit_a), id(unit_b)})

        screen.select_unit("ALL")
        self.assertEqual(screen.map_screen.selected_ids, set())
        self.assertEqual(screen._visible_rows(), [])

    def test_per_unit_action_can_target_a_selected_unit_on_another_tile(self):
        """A row action must never fall back to the panel's focused province."""
        focused = province(1, [])
        remote = province(2, [])
        focused_unit = {"owner": "A", "type": "Infantry"}
        remote_unit = {"owner": "A", "type": "Infantry"}
        focused["units"] = [focused_unit]
        remote["units"] = [remote_unit]

        map_stub = type("MapStub", (), {
            "player_country": "A",
            "tactical_mode": False,
            "show_feedback": lambda self, _message: None,
        })()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = map_stub
        screen.target_province = focused
        screen.refresh_ui = lambda: None

        screen.disband_unit(0, remote)

        self.assertNotIn("order", focused_unit)
        self.assertEqual(remote_unit["order"]["type"], "DISBAND")


class OrdersBatchCommandsTests(unittest.TestCase):
    def _screen(self, first, second):
        origin = province(1, [])
        remote = province(2, [])
        origin["buildings"] = ["Basic Factory"]
        remote["buildings"] = ["Basic Factory"]
        origin["units"] = [first]
        remote["units"] = [second]
        feedback = []
        map_stub = type("MapStub", (), {
            "player_country": "A",
            "tactical_mode": False,
            "nation_data": {"A": {"materials": 1000, "manpower": 1000,
                                    "fuel": 1000, "research": {}}},
            "scenario_settings": {"free_repairs": False},
            "selected_unit_records": lambda self: [(first, origin), (second, remote)],
            "show_feedback": lambda self, message: feedback.append(message),
        })()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = map_stub
        screen.unit_library = {"Infantry": {"cost_materials": 100,
                                             "cost_manpower": 50,
                                             "cost_fuel": 0}}
        screen.refresh_ui = lambda: None
        screen._mark_draft_changed = Mock()
        return screen, map_stub, feedback

    def test_disband_selected_orders_every_ready_selected_unit(self):
        first = {"owner": "A", "type": "Infantry"}
        second = {"owner": "A", "type": "Infantry"}
        screen, _map_stub, feedback = self._screen(first, second)

        screen.disband_selected_units()

        self.assertEqual(first["order"]["type"], "DISBAND")
        self.assertEqual(second["order"]["type"], "DISBAND")
        self.assertIn("2 selected units", feedback[-1])

    def test_disband_selected_replaces_existing_movement_orders(self):
        first = {"owner": "A", "type": "Infantry", "order": {"path": [2]}}
        second = {"owner": "A", "type": "Infantry", "order": {"path": [3]}}
        screen, _map_stub, _feedback = self._screen(first, second)

        screen.disband_selected_units()

        self.assertEqual(first["order"]["type"], "DISBAND")
        self.assertEqual(second["order"]["type"], "DISBAND")

    def test_repair_selected_is_atomic_when_the_group_is_unaffordable(self):
        first = {"owner": "A", "type": "Infantry", "health": 0, "max_health": 100}
        second = {"owner": "A", "type": "Infantry", "health": 0, "max_health": 100}
        screen, map_stub, feedback = self._screen(first, second)
        map_stub.nation_data["A"]["materials"] = 150

        screen.repair_selected_units()

        self.assertNotIn("order", first)
        self.assertNotIn("order", second)
        self.assertEqual(map_stub.nation_data["A"]["materials"], 150)
        self.assertIn("Cannot afford repairs", feedback[-1])

    def test_repair_selected_replaces_existing_movement_orders(self):
        first = {"owner": "A", "type": "Infantry", "health": 0, "max_health": 100,
                 "order": {"path": [2]}}
        second = {"owner": "A", "type": "Infantry", "health": 0, "max_health": 100,
                  "order": {"path": [3]}}
        screen, map_stub, _feedback = self._screen(first, second)

        screen.repair_selected_units()

        self.assertEqual(first["order"]["type"], "REPAIR")
        self.assertEqual(second["order"]["type"], "REPAIR")
        self.assertEqual(map_stub.nation_data["A"]["materials"], 800)

    def test_upgrade_selected_uses_each_units_legal_upgrade_target(self):
        first = {"owner": "A", "type": "Infantry", "order": {"path": [2]}}
        second = {"owner": "A", "type": "Infantry", "order": {"path": [3]}}
        screen, _map_stub, feedback = self._screen(first, second)

        with patch("screens.map_related_screens.orders.queries.get_upgrade_target",
                   return_value="Infantry Type 1940"):
            screen.upgrade_selected_units()

        self.assertEqual(first["order"]["target_type"], "Infantry Type 1940")
        self.assertEqual(second["order"]["target_type"], "Infantry Type 1940")
        self.assertIn("2 selected units", feedback[-1])

    def test_cancel_selected_disband_removes_every_selected_disband_order(self):
        first = {"owner": "A", "type": "Infantry", "order": {"type": "DISBAND"}}
        second = {"owner": "A", "type": "Infantry", "order": {"type": "DISBAND"}}
        screen, _map_stub, feedback = self._screen(first, second)

        screen.cancel_selected_batch_orders("DISBAND")

        self.assertNotIn("order", first)
        self.assertNotIn("order", second)
        self.assertIn("Cancelled disband", feedback[-1])

    def test_cancel_selected_repair_refunds_every_selected_repair_order(self):
        refund = {"cost_materials": 100, "cost_manpower": 50, "cost_fuel": 0}
        first = {"owner": "A", "type": "Infantry",
                 "order": {"type": "REPAIR", "refund": refund}}
        second = {"owner": "A", "type": "Infantry",
                  "order": {"type": "REPAIR", "refund": refund}}
        screen, map_stub, _feedback = self._screen(first, second)
        map_stub.nation_data["A"]["materials"] = 800
        map_stub.nation_data["A"]["manpower"] = 900

        screen.cancel_selected_batch_orders("REPAIR")

        self.assertNotIn("order", first)
        self.assertNotIn("order", second)
        self.assertEqual(map_stub.nation_data["A"]["materials"], 1000)
        self.assertEqual(map_stub.nation_data["A"]["manpower"], 1000)

    def test_cancel_selected_upgrade_removes_every_selected_upgrade_order(self):
        first = {"owner": "A", "type": "Infantry", "order": {"type": "UPGRADE"}}
        second = {"owner": "A", "type": "Infantry", "order": {"type": "UPGRADE"}}
        screen, _map_stub, _feedback = self._screen(first, second)

        screen.cancel_selected_batch_orders("UPGRADE")

        self.assertNotIn("order", first)
        self.assertNotIn("order", second)


class MapOrderGestureTests(unittest.TestCase):
    def test_orders_move_release_on_a_map_bar_does_not_target_a_tile(self):
        map_stub = type("MapStub", (), {
            "top_bar_rect": pygame.Rect(0, 0, 800, 60),
            "bot_bar_rect": pygame.Rect(0, 540, 800, 60),
            "selection_mode": False,
            "hide_raised_rect": False,
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [],
            "selected_unit_records": lambda self: [(object(), object())],
        })()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = map_stub
        screen.panel_rect = pygame.Rect(800, 100, 200, 300)
        screen.is_dragging_scrollbar = False
        screen.is_content_dragging = lambda _attr: False
        screen.read_only = False

        with (patch("screens.map_related_screens.orders.event_handler.resolve_map_mouse_gesture_conflict"),
              patch("screens.map_related_screens.orders.event_handler.mouse_button_has_action",
                    return_value=True),
              patch("screens.map_related_screens.orders.pygame.mouse.get_pos",
                    return_value=(400, 300)),
              patch("screens.map_related_screens.orders.queries.get_clicked_province") as hit_test):
            screen.additional_events(pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=(400, 550), button=3))

        hit_test.assert_not_called()

    def test_armed_bombardment_click_sets_target_before_selection_gesture(self):
        origin = province(1, [2])
        destination = province(2, [1])
        gun = {"owner": "A", "type": "Artillery I"}
        origin["units"] = [gun]
        screen = object.__new__(Orders_Screen)
        screen.panel_rect = pygame.Rect(0, 0, 100, 100)
        screen.bombarding_unit_index = 0
        screen.bombarding_unit_actual_index = 0
        screen.bombarding_unit_province = origin
        screen.exit_screen = Mock()
        screen.refresh_ui = lambda: None
        screen.map_screen = type("MapStub", (), {
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [],
            "id_to_province": {1: origin, 2: destination},
            "show_feedback": lambda self, _message: None,
        })()

        with (patch("screens.map_related_screens.orders.event_handler.resolve_map_mouse_gesture_conflict"),
              patch("screens.map_related_screens.orders.pygame.mouse.get_pos",
                    return_value=(150, 150)),
              patch("screens.map_related_screens.orders.queries.get_clicked_province",
                    return_value=destination)):
            screen.additional_events(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(150, 150)))
            screen.additional_events(
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(150, 150)))

        self.assertEqual(gun["order"], {"type": "BOMBARD", "target_id": 2})
        screen.exit_screen.assert_not_called()
        self.assertIsNone(screen.map_screen.unit_selection_drag)
        self.assertFalse(screen._consume_bombard_target_release)

    def test_unit_hover_prefers_the_topmost_visible_stack(self):
        lower = {"rect": pygame.Rect(10, 10, 30, 30), "units": []}
        upper = {"rect": pygame.Rect(10, 10, 30, 30), "units": []}
        map_stub = type("MapStub", (), {"unit_hover_hitboxes": [lower, upper]})()

        self.assertIs(event_handler._unit_stack_at(map_stub, (20, 20)), upper)
        self.assertIsNone(event_handler._unit_stack_at(map_stub, (100, 100)))

    def test_tactical_country_selection_can_click_a_rendered_unit_box(self):
        unit = {"owner": "A", "type": "Infantry"}
        origin = province(1, [])
        origin["units"] = [unit]
        map_stub = type("MapStub", (), {
            "unit_hover_hitboxes": [{
                "rect": pygame.Rect(10, 10, 20, 20),
                "province": origin,
                "units": [unit],
            }],
        })()

        with patch("ui.event_handler.player_setup.select_tactical_unit") as select_unit:
            self.assertTrue(event_handler._select_tactical_unit_stack(map_stub, (15, 15)))

        select_unit.assert_called_once_with(map_stub, origin, candidate_units=[unit])

    def test_short_right_click_orders_selected_units(self):
        unit = {"owner": "A", "type": "Infantry"}
        destination = province(2, [])
        calls = []
        map_stub = type("MapStub", (), {
            "secondary_mode": "UNITS",
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [],
            "selected_unit_ids": {id(unit)},
            "can_select_map_units": lambda self: True,
            "selected_unit_records": lambda self: [(unit, province(1, []))],
            "issue_selected_move_orders": lambda self, dest, append=False: calls.append((dest, append)),
        })()

        with (patch("ui.event_handler.queries.get_clicked_province", return_value=destination),
              patch("ui.event_handler.pygame.key.get_mods", return_value=0)):
            self.assertTrue(event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20), button=3), False))
            self.assertTrue(event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(20, 20), button=3), False))

        self.assertEqual(calls, [(destination, False)])

    def test_left_drag_box_selects_unit_stacks(self):
        first = {"owner": "A", "type": "Infantry"}
        second = {"owner": "A", "type": "Infantry"}
        selected, opened = [], []
        origin = province(1, [])
        map_stub = type("MapStub", (), {
            "secondary_mode": "UNITS",
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [
                {"rect": pygame.Rect(10, 10, 20, 20), "province": origin, "units": [first]},
                {"rect": pygame.Rect(50, 10, 20, 20), "province": origin, "units": [second]},
            ],
            "can_select_map_units": lambda self: True,
            "select_map_units": lambda self, units, additive=False: selected.extend(units),
            "open_orders_for_unit_stack": lambda self, prov, units: opened.append((prov, units)),
        })()

        with patch("ui.event_handler.pygame.key.get_mods", return_value=0):
            self.assertTrue(event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(15, 15), button=1), False))
            self.assertTrue(event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEMOTION, pos=(75, 35)), False))
            self.assertTrue(event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(75, 35), button=1), False))

        self.assertEqual(selected, [first, second])
        self.assertEqual(opened, [(origin, [first, second])])

    def test_left_click_on_a_member_of_a_group_focuses_it_and_opens_orders(self):
        unit = {"owner": "A", "type": "Infantry"}
        other = {"owner": "A", "type": "Infantry"}
        origin = province(1, [])
        other_origin = province(2, [])
        origin["units"] = [unit]
        other_origin["units"] = [other]
        map_stub = object.__new__(Map)
        map_stub.secondary_mode = "UNITS"
        map_stub.unit_selection_drag = None
        map_stub.unit_stack_hitboxes = [{
            "rect": pygame.Rect(10, 10, 20, 20),
            "province": origin, "units": [unit],
        }]
        map_stub.map_data = {"one": origin, "two": other_origin}
        map_stub.nation_data = {"A": {"at_war_with": []}}
        map_stub.player_country = "A"
        map_stub.selection_mode = map_stub.is_editor = False
        map_stub.viewing_ai_moves = map_stub.ai_is_thinking = False
        map_stub.tactical_mode = False
        map_stub.selected_unit_ids = {id(unit), id(other)}
        map_stub.show_feedback = lambda _text: None
        opened = []
        map_stub.open_orders_for_unit_stack = lambda prov, units: opened.append((prov, units))

        with patch("ui.event_handler.pygame.key.get_mods", return_value=0):
            event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(15, 15), button=1), False)
            self.assertTrue(event_handler._handle_map_unit_selection(
                map_stub, pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(15, 15), button=1), False))

        self.assertEqual([member for member, _province in map_stub.selected_unit_records()], [unit])
        self.assertEqual(opened, [(origin, [unit])])

    def test_right_press_cancels_an_unfinished_left_drag_rectangle(self):
        map_stub = type("MapStub", (), {
            "secondary_mode": "UNITS",
            "unit_selection_drag": {"start": (10, 10), "current": (80, 80)},
            "unit_stack_hitboxes": [],
            "selected_unit_ids": set(),
            "can_select_map_units": lambda self: True,
            "_ignore_right_until_release": False,
        })()

        event_handler.resolve_map_mouse_gesture_conflict(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20), button=3))

        self.assertIsNone(map_stub.unit_selection_drag)
        self.assertTrue(map_stub._ignore_right_until_release)

    def test_middle_press_cancels_a_left_drag_without_selecting_on_release(self):
        map_stub = type("MapStub", (), {
            "unit_selection_drag": {"start": (10, 10), "current": (80, 80)},
            "_ignore_left_until_release": False,
        })()

        event_handler.resolve_map_mouse_gesture_conflict(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(20, 20), button=2))

        self.assertIsNone(map_stub.unit_selection_drag)
        self.assertTrue(map_stub._ignore_left_until_release)

        map_stub.secondary_mode = "UNITS"
        map_stub.can_select_map_units = lambda: True
        self.assertTrue(event_handler._handle_map_unit_selection(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(40, 40), button=1), False))
        self.assertFalse(map_stub._ignore_left_until_release)

    def test_orders_map_click_returns_to_the_clicked_province_menu(self):
        screen = object.__new__(Orders_Screen)
        screen.panel_rect = pygame.Rect(100, 100, 200, 200)
        screen.bombarding_unit_index = None
        screen.is_dragging_scrollbar = False
        screen.is_content_dragging = lambda _attr: False
        screen.exit_screen = Mock()
        screen.return_to_province_menu = False
        screen.entered_from_combat_bubble = True
        screen.map_screen = type("MapStub", (), {
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [],
        })()

        with (patch("screens.map_related_screens.orders.event_handler.resolve_map_mouse_gesture_conflict"),
              patch("screens.map_related_screens.orders.event_handler._select_map_province",
                    return_value=True) as select_province,
              patch("screens.map_related_screens.orders.pygame.key.get_mods", return_value=0),
              patch("screens.map_related_screens.orders.pygame.mouse.get_pos", return_value=(5, 5))):
            screen.additional_events(
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(5, 5), button=1))
            screen.additional_events(
                pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(5, 5), button=1))

        screen.exit_screen.assert_called_once_with()
        select_province.assert_called_once_with(screen.map_screen, (5, 5), navigate=False)
        self.assertTrue(screen.return_to_province_menu)
        self.assertFalse(screen.entered_from_combat_bubble)
        self.assertIsNone(screen.map_screen.unit_selection_drag)

    def test_orders_left_drag_can_begin_on_open_map_space(self):
        first = {"owner": "A", "type": "Infantry"}
        second = {"owner": "A", "type": "Infantry"}
        selected = []
        origin = province(1, [])
        map_stub = type("MapStub", (), {
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [
                {"rect": pygame.Rect(20, 20, 20, 20), "province": origin, "units": [first]},
                {"rect": pygame.Rect(60, 20, 20, 20), "province": origin, "units": [second]},
            ],
            "unit_hover_hitboxes": [],
            "_ignore_left_until_release": False,
            "_ignore_right_until_release": False,
            "is_unit_selected": lambda self, unit: False,
            "select_map_units": lambda self, units, additive=False: selected.extend(units),
            "selected_unit_records": lambda self: [(unit, origin) for unit in selected],
        })()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = map_stub
        screen.panel_rect = pygame.Rect(100, 100, 200, 200)
        screen.is_dragging_scrollbar = False
        screen.is_content_dragging = lambda _attr: False
        screen.selected_unit_index = None
        screen.read_only = False
        screen._replace_roster_with_selection = lambda: None
        screen.refresh_ui = lambda: None

        with (patch("screens.map_related_screens.orders.pygame.key.get_mods", return_value=0),
              patch("screens.map_related_screens.orders.pygame.mouse.get_pos", return_value=(5, 5))):
            screen.additional_events(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=(5, 5), button=1))
            screen.additional_events(pygame.event.Event(
                pygame.MOUSEMOTION, pos=(90, 50)))
            screen.additional_events(pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=(90, 50), button=1))

        self.assertEqual(selected, [first, second])

    def test_orders_stack_click_does_not_refocus_an_individual_unit(self):
        unit = {"owner": "A", "type": "Infantry"}
        origin = province(1, [])
        origin["units"] = [unit]
        focus = Mock()
        map_stub = type("MapStub", (), {
            "unit_selection_drag": None,
            "unit_stack_hitboxes": [{
                "rect": pygame.Rect(10, 10, 20, 20),
                "province": origin,
                "units": [unit],
            }],
            "_ignore_left_until_release": False,
            "_ignore_right_until_release": False,
            "player_country": "A",
            "click_select_map_units": lambda self, _units, additive=False: True,
            "is_unit_selected": lambda self, candidate: candidate is unit,
            "selected_unit_records": lambda self: [(unit, origin)],
            "focus_camera_on_army": focus,
        })()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = map_stub
        screen.panel_rect = pygame.Rect(100, 100, 200, 200)
        screen.is_dragging_scrollbar = False
        screen.is_content_dragging = lambda _attr: False
        screen.bombarding_unit_index = None
        screen.refresh_ui = lambda: None

        with (patch("screens.map_related_screens.orders.pygame.key.get_mods", return_value=0),
              patch("screens.map_related_screens.orders.pygame.mouse.get_pos", return_value=(15, 15))):
            screen.additional_events(pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=(15, 15), button=1))
            screen.additional_events(pygame.event.Event(
                pygame.MOUSEBUTTONUP, pos=(15, 15), button=1))

        self.assertIs(screen.target_province, origin)
        focus.assert_not_called()


class MapViewDefaultTests(unittest.TestCase):
    def test_play_view_defaults_keep_country_selection_presentation_separate(self):
        map_screen = object.__new__(Map)
        map_screen.secondary_modes = ["UNITS", "ECONOMY", "BLANK"]
        map_screen.secondary_mode = "BLANK"
        map_screen.sec_idx = 0
        map_screen.show_country_names = True

        Map.set_play_view_defaults(map_screen)

        self.assertEqual(map_screen.secondary_mode, "UNITS")
        self.assertEqual(map_screen.sec_idx, 0)
        self.assertFalse(map_screen.show_country_names)

    def test_country_selection_defaults_show_names_without_unit_overlay(self):
        map_screen = object.__new__(Map)
        map_screen.secondary_modes = ["UNITS", "ECONOMY", "BLANK"]
        map_screen.secondary_mode = "BLANK"
        map_screen.sec_idx = 2
        map_screen.show_country_names = False

        Map.set_country_selection_view_defaults(map_screen)

        self.assertEqual(map_screen.secondary_mode, "BLANK")
        self.assertEqual(map_screen.sec_idx, 2)
        self.assertTrue(map_screen.show_country_names)

    def test_tactical_view_defaults_show_units_without_country_names(self):
        map_screen = object.__new__(Map)
        map_screen.secondary_modes = ["UNITS", "ECONOMY", "BLANK"]
        map_screen.secondary_mode = "BLANK"
        map_screen.sec_idx = 2
        map_screen.show_country_names = True

        Map.set_tactical_view_defaults(map_screen)

        self.assertEqual(map_screen.secondary_mode, "UNITS")
        self.assertEqual(map_screen.sec_idx, 0)
        self.assertFalse(map_screen.show_country_names)

    def test_confirming_a_country_applies_the_play_view_defaults(self):
        applied = []
        focused = []
        map_stub = type("MapStub", (), {
            "pending_selection": "A",
            "active_players": [],
            "tactical_mode": False,
            "selected_province": None,
            "hovered_province": None,
            "hover_glow_surf": None,
            "num_players": 1,
            "set_play_view_defaults": lambda self: applied.append(True),
            "focus_camera_on_country": lambda self, country_id, animate=False: focused.append(
                (country_id, animate)),
            "show_feedback": lambda self, _message: None,
            "refresh_map_layers": lambda self, *_layers: None,
        })()

        with patch("screens.menu_screens.map.render_buttons"):
            player_setup.confirm_player_country(map_stub)

        self.assertEqual(map_stub.player_country, "A")
        self.assertFalse(map_stub.selection_mode)
        self.assertEqual(applied, [True])
        self.assertEqual(focused, [("A", True)])

    def test_starting_spectator_applies_the_play_view_defaults(self):
        applied = []
        map_stub = type("MapStub", (), {
            "active_players": [],
            "selection_mode": True,
            "pending_selection": None,
            "pending_unit": None,
            "selected_province": None,
            "hovered_province": None,
            "hover_glow_surf": None,
            "set_play_view_defaults": lambda self: applied.append(True),
            "show_feedback": lambda self, _message: None,
            "refresh_map_layers": lambda self, *_layers: None,
        })()

        with patch("screens.menu_screens.map.render_buttons"):
            player_setup.start_spectator(map_stub)

        self.assertEqual(map_stub.player_country, "Spectator")
        self.assertFalse(map_stub.selection_mode)
        self.assertEqual(applied, [True])

    def test_country_focus_uses_core_center_and_unit_visible_zoom(self):
        map_screen = object.__new__(Map)
        map_screen.map_data = {
            "first": {"owner": "A", "cores": ["A"], "center": (100, 100)},
            "second": {"owner": "A", "cores": ["A"], "center": (300, 200)},
        }
        map_screen.loop_map = False
        map_screen.map_w = 1000
        map_screen.min_zoom = 0.5
        map_screen.total_ui_h = 120
        map_screen.camera = type("CameraStub", (), {
            "zoom": 0.5,
            "target_zoom": 0.5,
            "pos": pygame.Vector2(),
            "target_pos": pygame.Vector2(),
            "tilt_factor": 1.0,
            "focus_animation": False,
        })()

        self.assertTrue(Map.focus_camera_on_country(map_screen, "A", animate=True))
        self.assertTrue(map_screen.camera.focus_animation)
        expected_zoom = overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM + 0.1
        self.assertEqual(map_screen.camera.target_zoom, expected_zoom)
        self.assertAlmostEqual(
            map_screen.camera.target_pos.x,
            200 - c.SCREEN_WIDTH / expected_zoom / 2,
        )
        self.assertAlmostEqual(
            map_screen.camera.target_pos.y,
            150 - (c.SCREEN_HEIGHT - map_screen.total_ui_h) / expected_zoom / 2,
        )

    def test_animated_focus_keeps_its_destination_while_zooming(self):
        camera = camera_handler.MapCamera(0.5)
        camera_handler.focus_camera_on_position(
            camera, (2500, 1500), c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            120, 2.1, animate=True)
        expected_target = pygame.Vector2(camera.target_pos)
        map_stub = type("MapStub", (), {
            "loop_map": False,
            "map_w": 5000,
            "map_h": 5000,
            "top_ui_height": 60,
            "total_ui_h": 120,
            "selection_mode": False,
            "hide_raised_rect": False,
        })()

        camera.update(map_stub, c.SCREEN_HEIGHT)

        self.assertEqual(camera.target_pos, expected_target)
        self.assertGreater(camera.zoom, 0.5)
        self.assertLess(camera.zoom, camera.target_zoom)


if __name__ == "__main__":
    unittest.main()
