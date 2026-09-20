"""Regression coverage for persistent army organization and tray geometry."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

import data.constants as c
from data import queries
from map_logic.rendering import overlay_renderer
from map_logic.rendering import country_names
from map_logic.rendering import symbol_loader
from gameState import GameState
from screens.map_related_screens.defense_area_screen import DefenseAreaScreen
from screens.map_related_screens.orders import Orders_Screen, PANEL_INSET, TOP_BTN_GAP_X
from ui import army_panel, map_top_right_layout, minimap


class CountryMapCenterTests(unittest.TestCase):
    def test_country_name_transform_cache_reuses_settled_camera_pixels(self):
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=1.0, tilt_factor=1.0))
        source = pygame.Surface((40, 12), pygame.SRCALPHA)
        shadow = pygame.Surface((40, 12), pygame.SRCALPHA)
        blob = {"length": 100, "thickness": 100, "angle": 0}

        with patch.object(country_names.pygame.transform, "scale",
                          wraps=pygame.transform.scale) as scale:
            first = country_names._transformed_name_surfaces(
                map_screen, source, shadow, blob)
            second = country_names._transformed_name_surfaces(
                map_screen, source, shadow, blob)

        self.assertIs(first[0], second[0])
        self.assertIs(first[1], second[1])
        self.assertEqual(scale.call_count, 2)

        map_screen.camera.zoom = 1.5
        third = country_names._transformed_name_surfaces(
            map_screen, source, shadow, blob)
        self.assertIsNot(first[0], third[0])

    def test_core_tiles_define_country_center_before_owned_tiles(self):
        world = {
            "core_a": {"owner": "A", "cores": ["A"], "center": (20, 40)},
            "core_b": {"owner": "B", "cores": ["A"], "center": (80, 60)},
            "owned_not_core": {"owner": "A", "cores": [], "center": (400, 400)},
        }

        self.assertEqual(queries.get_country_map_center("A", world), (50, 50))

    def test_owned_tiles_are_used_when_country_has_no_cores(self):
        world = {
            "first": {"owner": "A", "cores": [], "center": (20, 40)},
            "second": {"owner": "A", "cores": [], "center": (80, 60)},
            "foreign": {"owner": "B", "cores": [], "center": (400, 400)},
        }

        self.assertEqual(queries.get_country_map_center("A", world), (50, 50))

    def test_looping_country_center_wraps_across_map_edges(self):
        world = {
            "west": {"owner": "A", "cores": ["A"], "center": (5, 40)},
            "east": {"owner": "A", "cores": ["A"], "center": (95, 60)},
        }

        self.assertEqual(queries.get_country_map_center("A", world, True, 100), (0, 50))


class ArmyQueryTests(unittest.TestCase):
    def setUp(self):
        self.first = {"id": 1, "owner": "A", "units": [
            {"owner": "A", "type": "Infantry"},
            {"owner": "A", "type": "Infantry"},
        ]}
        self.second = {"id": 2, "owner": "A", "units": [
            {"owner": "A", "type": "Tank"},
        ]}
        self.world = {"one": self.first, "two": self.second}
        self.nations = {"A": {"armies": []}, "B": {"armies": []}}

    def test_legacy_units_gain_ids_and_armies_are_exclusive(self):
        queries.normalize_armies(self.nations, self.world)
        ids = [unit["unit_id"] for province in self.world.values()
               for unit in province["units"]]
        self.assertEqual(len(set(ids)), 3)
        first_army = queries.create_army("A", ids[:2], self.nations, self.world)
        self.assertEqual(first_army["unit_ids"], ids[:2])
        self.assertTrue(queries.assign_units_to_army(
            "A", first_army["id"], [ids[2]], self.nations, self.world))
        first_army = self.nations["A"]["armies"][0]
        self.assertEqual(set(first_army["unit_ids"]), set(ids))
        self.assertTrue(queries.ungroup_units("A", [ids[1]], self.nations, self.world))
        first_army = self.nations["A"]["armies"][0]
        self.assertNotIn(ids[1], first_army["unit_ids"])
        self.assertTrue(queries.disband_army("A", first_army["id"], self.nations, self.world))
        self.assertEqual(self.nations["A"]["armies"], [])
        self.assertEqual(sum(len(p["units"]) for p in self.world.values()), 3)

    def test_normalization_drops_foreign_missing_and_empty_armies(self):
        queries.ensure_unit_ids(self.world)
        own_id = self.first["units"][0]["unit_id"]
        self.nations["A"]["armies"] = [
            {"id": "keep", "name": "Army 1", "unit_ids": [own_id, "missing"]},
            {"id": "bad", "name": "Army 2", "unit_ids": ["foreign"]},
        ]
        queries.normalize_armies(self.nations, self.world)
        self.assertEqual(self.nations["A"]["armies"], [
            {"id": "keep", "name": "Army 1", "unit_ids": [own_id],
             "symbol": "", "symbol_color": list(c.DEFAULT_ARMY_SYMBOL_COLOR),
             "symbol_rotation": c.DEFAULT_ARMY_SYMBOL_ROTATION,
             "symbol_flipped": c.DEFAULT_ARMY_SYMBOL_FLIPPED,
             "custom_symbol": None,
             "defense_area": [],
             "frontline_country": None,
             "offensive_target": None,
             "order_mode": None}])

    def test_army_presentation_round_trips_and_invalid_legacy_art_is_removed(self):
        queries.normalize_armies(self.nations, self.world)
        unit_id = self.first["units"][0]["unit_id"]
        army = queries.create_army("A", [unit_id], self.nations, self.world)
        symbol = queries.army_symbol_choices()[0]
        custom_symbol = ([c.ARMY_CUSTOM_SYMBOL_RED + c.ARMY_CUSTOM_SYMBOL_EMPTY * 19]
                         + [c.ARMY_CUSTOM_SYMBOL_EMPTY * 20] * 19)
        updated = queries.update_army_presentation(
            "A", army["id"], "Northern Command", symbol, [12, 90, 230], 90,
            True, custom_symbol, self.nations, self.world)
        self.assertEqual(updated["name"], "Northern Command")
        self.assertEqual(updated["symbol"], "")
        self.assertEqual(updated["symbol_color"], [12, 90, 230])
        self.assertEqual(updated["symbol_rotation"], 90)
        self.assertTrue(updated["symbol_flipped"])
        self.assertEqual(updated["custom_symbol"], custom_symbol)
        updated["symbol"] = "No Longer Installed"
        updated["symbol_color"] = [999, 0, 0]
        updated["symbol_rotation"] = 45
        updated["symbol_flipped"] = "yes"
        updated["custom_symbol"] = ["invalid"]
        queries.normalize_armies(self.nations, self.world)
        normalized = self.nations["A"]["armies"][0]
        self.assertEqual(normalized["symbol"], "")
        self.assertEqual(normalized["symbol_color"], list(c.DEFAULT_ARMY_SYMBOL_COLOR))
        self.assertEqual(normalized["symbol_rotation"], c.DEFAULT_ARMY_SYMBOL_ROTATION)
        self.assertFalse(normalized["symbol_flipped"])
        self.assertIsNone(normalized["custom_symbol"])

    @patch("data.queries.random_army_symbol", return_value="Star")
    @patch("data.queries.random.choice", return_value=(12, 90, 230))
    def test_new_army_uses_a_random_persistent_color_for_member_bands(
            self, choose_color, choose_symbol):
        queries.normalize_armies(self.nations, self.world)
        member, ungrouped = self.first["units"]
        army = queries.create_army("A", [member["unit_id"]], self.nations, self.world)

        choose_symbol.assert_called_once_with()
        choose_color.assert_called_once_with(c.ARMY_SYMBOL_COLOR_CHOICES)
        self.assertEqual(army["symbol"], "Star")
        self.assertEqual(army["symbol_color"], [12, 90, 230])
        self.assertFalse(army["symbol_flipped"])
        self.assertEqual(queries.army_color_for_unit(member, self.nations), (12, 90, 230))
        self.assertIsNone(queries.army_color_for_unit(ungrouped, self.nations))

    def test_map_stack_groups_each_army_and_keeps_ungrouped_units_together(self):
        queries.normalize_armies(self.nations, self.world)
        first, second = self.first["units"]
        third = self.second["units"][0]
        first_army = queries.create_army("A", [first["unit_id"]],
                                         self.nations, self.world)
        second_army = queries.create_army("A", [second["unit_id"]],
                                          self.nations, self.world)

        groups = queries.group_units_by_army([first, second, third], self.nations)

        self.assertEqual([(army.get("id") if army else None, members)
                          for army, members in groups], [
                              (first_army["id"], [first]),
                              (second_army["id"], [second]),
                              (None, [third]),
                          ])

    @patch("data.queries.army_symbol_choices", return_value=["Banner", "Crown"])
    @patch("data.queries.random.choice", return_value="Crown")
    def test_random_army_symbol_chooses_only_installed_emblems(self, choose, choices):
        self.assertEqual(queries.random_army_symbol(), "Crown")
        choose.assert_called_once_with(["Banner", "Crown"])
        choices.assert_called_once_with()

    def test_orders_shows_unselected_peers_without_selecting_them(self):
        queries.normalize_armies(self.nations, self.world)
        first_unit, second_unit = self.first["units"]
        # The army's saved order is intentionally the reverse of its map
        # order, so a selected member proves it is not promoted to row one.
        queries.create_army("A", [second_unit["unit_id"], first_unit["unit_id"]],
                            self.nations, self.world)
        selected_ids = {first_unit["unit_id"]}
        map_stub = SimpleNamespace(
            player_country="A", nation_data=self.nations, map_data=self.world,
            selected_unit_records=lambda: [(first_unit, self.first)])
        orders = Orders_Screen.__new__(Orders_Screen)
        orders.map_screen = map_stub
        orders.target_province = self.first
        orders.read_only = False
        rows = orders._visible_rows()
        self.assertEqual([unit["unit_id"] for _key, unit, _province, _index in rows],
                         [second_unit["unit_id"], first_unit["unit_id"]])
        self.assertEqual(selected_ids, {first_unit["unit_id"]})

    def test_orders_title_uses_the_selected_army_name(self):
        queries.normalize_armies(self.nations, self.world)
        first_unit, second_unit = self.first["units"]
        army = queries.create_army(
            "A", [first_unit["unit_id"], second_unit["unit_id"]],
            self.nations, self.world)
        army["name"] = "Northern Command"
        orders = Orders_Screen.__new__(Orders_Screen)
        orders.map_screen = SimpleNamespace(nation_data=self.nations)

        self.assertEqual(orders._panel_title([first_unit]),
                         "ORDERS | Northern Command")
        self.assertEqual(orders._panel_title([first_unit, second_unit]),
                         "ORDERS | Northern Command")
        self.assertEqual(orders._panel_title([first_unit, self.second["units"][0]]),
                         "ORDERS | MAP COMMAND")

    def test_army_order_is_player_managed_and_persistent(self):
        queries.normalize_armies(self.nations, self.world)
        first_id = self.first["units"][0]["unit_id"]
        second_id = self.second["units"][0]["unit_id"]
        first_army = queries.create_army("A", [first_id], self.nations, self.world)
        second_army = queries.create_army("A", [second_id], self.nations, self.world)
        self.assertTrue(queries.move_army("A", second_army["id"], -1,
                                          self.nations, self.world))
        self.assertEqual([army["id"] for army in self.nations["A"]["armies"]],
                         [second_army["id"], first_army["id"]])
        self.assertFalse(queries.move_army("A", second_army["id"], -1,
                                           self.nations, self.world))

    def test_defense_area_queues_routes_now_and_only_returns_idle_units_later(self):
        self.first["neighbors"] = [self.second["id"]]
        self.second["neighbors"] = [self.first["id"]]
        queries.normalize_armies(self.nations, self.world)
        unit = self.first["units"][0]
        army = queries.create_army("A", [unit["unit_id"]], self.nations, self.world)
        saved = queries.set_army_defense_area(
            "A", army["id"], [self.second["id"], self.second["id"], 999],
            self.nations, self.world)
        self.assertEqual(saved["defense_area"], [self.second["id"]])

        map_ref = SimpleNamespace(
            nation_data=self.nations, map_data=self.world,
            id_to_province={province["id"]: province for province in self.world.values()},
            _units_with_move_order_this_turn=set())
        self.assertEqual(queries.queue_army_defense_orders(map_ref, "A", army["id"]), 1)
        self.assertEqual(unit["order"], {"type": "MOVE", "path": [self.second["id"]]})

        # A submitted route must not be replaced after its resolution, even if
        # movement stopped before reaching the area.  An idle later turn may.
        unit.pop("order")
        map_ref._units_with_move_order_this_turn = {id(unit)}
        self.assertEqual(queries.queue_idle_army_defense_orders(map_ref), 0)
        self.assertNotIn("order", unit)
        self.assertEqual(queries.queue_idle_army_defense_orders(map_ref), 1)
        self.assertEqual(unit["order"]["path"], [self.second["id"]])

    def test_defense_area_fills_gaps_before_balancing_reinforcements(self):
        third = {"id": 3, "owner": "A", "units": [], "neighbors": [1, 2]}
        fourth = {"id": 4, "owner": "A", "units": [], "neighbors": [1, 2]}
        self.first["neighbors"] = [third["id"], fourth["id"]]
        self.second["neighbors"] = [third["id"], fourth["id"]]
        self.world.update({"three": third, "four": fourth})
        queries.normalize_armies(self.nations, self.world)
        members = self.first["units"] + self.second["units"]
        army = queries.create_army(
            "A", [unit["unit_id"] for unit in members], self.nations, self.world)
        queries.set_army_defense_area(
            "A", army["id"], [third["id"], fourth["id"]], self.nations, self.world)
        map_ref = SimpleNamespace(
            nation_data=self.nations, map_data=self.world,
            id_to_province={province["id"]: province for province in self.world.values()})

        self.assertEqual(queries.queue_army_defense_orders(map_ref, "A", army["id"]), 3)
        destinations = [unit["order"]["path"][-1] for unit in members]
        self.assertEqual(set(destinations), {third["id"], fourth["id"]})
        self.assertLessEqual(abs(destinations.count(third["id"])
                                 - destinations.count(fourth["id"])), 1)

    def test_frontline_spreads_members_then_offensive_order_targets_that_country(self):
        members = self.first["units"] + self.second["units"]
        rear = {"id": 5, "owner": "A", "units": members, "neighbors": [1, 2]}
        self.first.update({"units": [], "neighbors": [3, 5]})
        self.second.update({"units": [], "neighbors": [4, 5]})
        enemy_one = {"id": 3, "owner": "B", "units": [], "neighbors": [1, 4]}
        enemy_two = {"id": 4, "owner": "B", "units": [], "neighbors": [2, 3]}
        self.world.update({"rear": rear, "enemy_one": enemy_one, "enemy_two": enemy_two})
        self.nations["A"]["at_war_with"] = ["B"]
        self.nations["B"]["at_war_with"] = ["A"]
        queries.normalize_armies(self.nations, self.world)
        army = queries.create_army(
            "A", [unit["unit_id"] for unit in members], self.nations, self.world)
        map_ref = SimpleNamespace(
            nation_data=self.nations, map_data=self.world,
            id_to_province={province["id"]: province for province in self.world.values()},
            _units_with_move_order_this_turn=set())

        saved = queries.set_army_frontline(
            "A", army["id"], "B", self.nations, self.world)
        self.assertEqual(saved["frontline_country"], "B")
        self.assertEqual(saved["order_mode"], c.ARMY_ORDER_FRONTLINE)
        self.assertEqual(queries.get_army_frontline_province_ids("A", "B", self.world), [1, 2])
        self.assertEqual(queries.queue_army_frontline_orders(map_ref, "A", army["id"]), 3)
        frontline_destinations = [unit["order"]["path"][-1] for unit in members]
        self.assertEqual(set(frontline_destinations), {1, 2})
        self.assertLessEqual(abs(frontline_destinations.count(1)
                                 - frontline_destinations.count(2)), 1)

        saved = queries.set_army_offensive_target(
            "A", army["id"], enemy_two["id"], self.nations, self.world)
        self.assertEqual(saved["offensive_target"], enemy_two["id"])
        self.assertEqual(saved["order_mode"], c.ARMY_ORDER_OFFENSIVE)
        self.assertEqual(queries.queue_army_offensive_orders(map_ref, "A", army["id"]), 3)
        self.assertTrue(all(unit["order"]["path"][-1] == enemy_two["id"]
                            for unit in members))

    def test_frontline_rejects_non_neighbors_and_clears_stale_objectives(self):
        self.first["neighbors"] = [3]
        enemy = {"id": 3, "owner": "B", "units": [], "neighbors": [1]}
        self.world["enemy"] = enemy
        queries.normalize_armies(self.nations, self.world)
        army = queries.create_army(
            "A", [self.first["units"][0]["unit_id"]], self.nations, self.world)
        self.assertIsNone(queries.set_army_frontline(
            "A", army["id"], "Missing", self.nations, self.world))
        self.assertIsNotNone(queries.set_army_frontline(
            "A", army["id"], "B", self.nations, self.world))
        self.assertIsNone(queries.set_army_offensive_target(
            "A", army["id"], self.first["id"], self.nations, self.world))
        self.assertIsNotNone(queries.set_army_offensive_target(
            "A", army["id"], enemy["id"], self.nations, self.world))

        enemy["owner"] = "A"
        queries.normalize_armies(self.nations, self.world)
        normalized = self.nations["A"]["armies"][0]
        self.assertIsNone(normalized["frontline_country"])
        self.assertIsNone(normalized["offensive_target"])
        self.assertIsNone(normalized["order_mode"])


class ArmyLayoutTests(unittest.TestCase):
    def test_army_order_controls_are_vertical_and_non_overlapping(self):
        card = pygame.Rect(100, 100, map_top_right_layout.PANEL_WIDTH,
                           map_top_right_layout.CARD_HEIGHT)
        controls = [army_panel._frontline_rect(card), army_panel._offensive_rect(card),
                    army_panel._move_up_rect(card), army_panel._move_down_rect(card),
                    army_panel._defense_rect(card), army_panel._edit_rect(card),
                    army_panel._close_rect(card)]
        self.assertTrue(all(card.contains(control) for control in controls))
        self.assertFalse(any(first.colliderect(second)
                             for index, first in enumerate(controls)
                             for second in controls[index + 1:]))

    def test_defense_picker_keeps_its_controls_at_the_top_of_the_map(self):
        pygame.font.init()
        map_ref = SimpleNamespace(
            player_country="A", nation_data={"A": {"armies": [
                {"id": "army", "name": "Army 1", "unit_ids": [], "defense_area": []}]}},
            map_data={})
        screen = DefenseAreaScreen(map_ref, "army")

        self.assertEqual(screen.panel_rect.top, DefenseAreaScreen.PANEL_TOP)
        self.assertEqual(screen.panel_rect.centerx, c.SCREEN_WIDTH // 2)
        self.assertLess(DefenseAreaScreen.SELECTION_MARKER_RADIUS, 14)

    def test_orders_draws_army_editor_over_its_button_elements(self):
        screen = object.__new__(Orders_Screen)
        screen.map_screen = object()
        draw_order = []

        with (patch.object(GameState, "draw", side_effect=lambda *_args: draw_order.append("orders")),
              patch("screens.map_related_screens.orders.army_panel.draw_editors_over_map",
                    side_effect=lambda *_args: draw_order.append("editor"))):
            screen.draw(pygame.Surface((100, 100)))

        self.assertEqual(draw_order, ["orders", "editor"])

    def test_army_flip_button_mirrors_the_y_axis_and_is_clickable(self):
        emblem = pygame.Surface((2, 1))
        emblem.set_at((0, 0), (220, 20, 20))
        emblem.set_at((1, 0), (20, 20, 220))
        mirrored = symbol_loader.orient_army_symbol(emblem, flipped=True)
        self.assertEqual(mirrored.get_at((0, 0))[:3], (20, 20, 220))
        self.assertEqual(mirrored.get_at((1, 0))[:3], (220, 20, 20))

        army = {"id": "army", "name": "Army 1", "unit_ids": ["unit"],
                "symbol": "", "symbol_color": [210, 70, 70],
                "symbol_rotation": 0, "symbol_flipped": False,
                "custom_symbol": None}
        map_stub = SimpleNamespace(player_country="A", nation_data={"A": {"armies": [army]}},
                                   map_data={})
        army_panel._open_editor(map_stub, army)
        rect = army_panel._editor_rect()
        flip = army_panel._flip_button_rect(rect)
        self.assertTrue(rect.contains(flip))
        self.assertTrue(army_panel._handle_editor_event(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=flip.center)))
        self.assertTrue(map_stub.army_editor_state["symbol_flipped"])

    def test_custom_emblem_red_uses_army_rgb_in_preview_and_map(self):
        size = c.ARMY_CUSTOM_SYMBOL_SIZE
        custom_symbol = [
            c.ARMY_CUSTOM_SYMBOL_RED + c.ARMY_CUSTOM_SYMBOL_BLACK
            + c.ARMY_CUSTOM_SYMBOL_EMPTY * (size - 2),
            *([c.ARMY_CUSTOM_SYMBOL_EMPTY * size] * (size - 1)),
        ]
        army_color = [25, 120, 225]
        other_color = (230, 45, 35)

        emblem = symbol_loader.get_custom_army_symbol(
            custom_symbol, size, tuple(army_color))
        other_emblem = symbol_loader.get_custom_army_symbol(
            custom_symbol, size, other_color)
        self.assertEqual(emblem.get_at((0, 0))[:3], tuple(army_color))
        self.assertEqual(emblem.get_at((1, 0))[:3], (0, 0, 0))
        self.assertEqual(other_emblem.get_at((0, 0))[:3], other_color)
        self.assertIsNot(emblem, other_emblem)

        army = {"symbol": "", "custom_symbol": custom_symbol,
                "symbol_color": army_color, "symbol_rotation": 0,
                "symbol_flipped": False}
        map_emblem = overlay_renderer.army_emblem_surface(army, size)
        self.assertEqual(map_emblem.get_at((0, 0))[:3], tuple(army_color))

        preview = pygame.Surface((size, size), pygame.SRCALPHA)
        army_panel._draw_emblem(preview, "", custom_symbol, army_color, 0,
                                (size // 2, size // 2), size)
        self.assertEqual(preview.get_at((0, 0))[:3], tuple(army_color))

    def test_back_closes_army_name_editor_before_its_parent_screen(self):
        army = {"id": "army", "name": "Army 1", "unit_ids": ["unit"],
                "symbol": "", "symbol_color": [210, 70, 70],
                "symbol_rotation": 0, "symbol_flipped": False,
                "custom_symbol": None}
        map_stub = SimpleNamespace(player_country="A", nation_data={"A": {"armies": [army]}},
                                   map_data={}, army_custom_symbol_state=None)
        army_panel._open_editor(map_stub, army)

        self.assertTrue(army_panel.handle_back_key(map_stub))
        self.assertIsNone(map_stub.army_editor_state)

    def test_tray_card_color_is_a_less_saturated_army_rgb(self):
        source = (220, 60, 70)
        fill, border = army_panel._tray_card_colors(source, selected=False)
        source_neutral = sum(source) / 3
        fill_neutral = sum(fill) / 3

        self.assertEqual(fill, army_panel._muted_army_color(source))
        self.assertNotEqual(fill, source)
        self.assertTrue(all(abs(channel - fill_neutral) < abs(original - source_neutral)
                            for channel, original in zip(fill, source)))
        self.assertTrue(all(channel < original for channel, original in zip(fill, source)))
        self.assertTrue(all(edge >= channel for edge, channel in zip(border, fill)))

    def test_orders_header_fits_ungroup_and_wraps_movement_guidance(self):
        controls_width = (c.SIZES["orders_header_button"][0]
                          + (2 * TOP_BTN_GAP_X)
                          + c.SIZES["orders_clear_button"][0]
                          + c.SIZES["orders_header_button"][0])
        self.assertLessEqual(
            controls_width + (2 * PANEL_INSET),
            Orders_Screen.PANEL_WIDTH)

        pygame.font.init()
        font = pygame.font.Font(None, 18)
        guidance = ("Right-click a province to move selected units. "
                    "Shift+right-click queues a waypoint.")
        lines = Orders_Screen._header_help_lines(guidance, font)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(font.size(line)[0] <= Orders_Screen.PANEL_WIDTH - (2 * PANEL_INSET)
                            for line in lines))

    def test_map_army_bands_show_each_player_member_but_never_foreign_members(self):
        first = {"owner": "A", "unit_id": "first"}
        second = {"owner": "A", "unit_id": "second"}
        foreign = {"owner": "B", "unit_id": "foreign"}
        nations = {
            "A": {"armies": [
                {"id": "one", "unit_ids": ["first"], "symbol_color": [220, 60, 70]},
                {"id": "two", "unit_ids": ["second"], "symbol_color": [50, 140, 230]},
            ]},
            "B": {"armies": [
                {"id": "other", "unit_ids": ["foreign"], "symbol_color": [70, 190, 100]},
            ]},
        }
        surface = pygame.Surface((100, 100))
        surface.fill((0, 0, 0))
        box = pygame.Rect(40, 30, 40, 20)

        band_left = overlay_renderer.draw_army_unit_bands(
            surface, [first, second], "A", "A", nations, box, box.width)
        self.assertLess(band_left, box.left)
        self.assertEqual(surface.get_at((band_left + 1, box.top + 2))[:3], (220, 60, 70))
        self.assertEqual(surface.get_at((band_left + 1, box.bottom - 2))[:3], (50, 140, 230))

        foreign_surface = pygame.Surface((100, 100))
        foreign_surface.fill((0, 0, 0))
        self.assertEqual(overlay_renderer.draw_army_unit_bands(
            foreign_surface, [foreign], "B", "A", nations, box, box.width), box.left)
        self.assertEqual(foreign_surface.get_at((box.left - 3, box.centery))[:3], (0, 0, 0))

    def test_map_renders_armies_as_distinct_stacks_with_one_emblem_each(self):
        first = {"owner": "A", "unit_id": "first", "type": "Infantry"}
        second = {"owner": "A", "unit_id": "second", "type": "Infantry"}
        third = {"owner": "A", "unit_id": "third", "type": "Tank"}
        first_army = {"id": "one", "unit_ids": ["first", "second"],
                       "symbol": "Star", "symbol_color": [220, 60, 70]}
        second_army = {"id": "two", "unit_ids": ["third"],
                        "symbol": "Crown", "symbol_color": [50, 140, 230]}
        nation_data = {"A": {"armies": [first_army, second_army]}}
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=4, tilt_factor=1), player_country="A",
            nation_data=nation_data, nation_colors={"A": (220, 60, 70)},
            tactical_mode=False, player_unit=None, hovered_unit_stack=None,
            unit_hover_hitboxes=[], unit_stack_hitboxes=[],
            unit_selection_drag=None, is_unit_selected=lambda _unit: False)
        province = {"units": [first, second, third]}
        surface = pygame.Surface((200, 200), pygame.SRCALPHA)

        with (patch.object(overlay_renderer, "unit_box",
                           side_effect=lambda *_args, **kwargs: pygame.Surface(
                               kwargs.get("size", _args[4]), pygame.SRCALPHA)) as boxes,
              patch.object(overlay_renderer, "draw_army_unit_bands",
                           side_effect=lambda _surface, _units, _owner, _player,
                                              _nations, box, _width, army=None: box.left),
              patch.object(overlay_renderer, "draw_army_emblem") as emblems):
            overlay_renderer.draw_unit_icon(
                map_screen, surface, 100, 100, province, units_are_visible=True)

        self.assertEqual([call.args[2] for call in boxes.call_args_list], [2, 1])
        self.assertEqual([call.args[1]["id"] for call in emblems.call_args_list],
                         ["one", "two"])
        self.assertEqual([stack["units"] for stack in map_screen.unit_stack_hitboxes],
                         [[first, second], [third]])

    def test_map_splits_selected_members_from_their_unselected_stack_mates(self):
        first_tile_units = [{"owner": "A", "unit_id": f"first-{index}",
                             "type": "Infantry"} for index in range(9)]
        second_tile_units = [{"owner": "A", "unit_id": f"second-{index}",
                              "type": "Infantry"} for index in range(6)]
        selected_ids = {unit["unit_id"] for unit in first_tile_units[:5]}
        selected_ids.update(unit["unit_id"] for unit in second_tile_units[:3])
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=4, tilt_factor=1), player_country="A",
            nation_data={"A": {"armies": []}}, nation_colors={"A": (220, 60, 70)},
            tactical_mode=False, player_unit=None, hovered_unit_stack=None,
            unit_hover_hitboxes=[], unit_stack_hitboxes=[], unit_selection_drag=None,
            is_unit_selected=lambda unit: unit["unit_id"] in selected_ids)
        surface = pygame.Surface((200, 200), pygame.SRCALPHA)

        with (patch.object(overlay_renderer, "unit_box",
                           side_effect=lambda *_args, **kwargs: pygame.Surface(
                               kwargs.get("size", _args[4]), pygame.SRCALPHA)) as boxes,
              patch.object(overlay_renderer, "draw_army_unit_bands",
                           side_effect=lambda _surface, _units, _owner, _player,
                                              _nations, box, _width, army=None: box.left),
              patch.object(overlay_renderer, "draw_army_emblem")):
            overlay_renderer.draw_unit_icon(
                map_screen, surface, 50, 50, {"units": first_tile_units},
                units_are_visible=True)
            overlay_renderer.draw_unit_icon(
                map_screen, surface, 150, 50, {"units": second_tile_units},
                units_are_visible=True)

        self.assertEqual([call.args[2] for call in boxes.call_args_list], [5, 4, 3, 3])
        self.assertEqual(
            [{unit["unit_id"] for unit in stack["units"]}
             for stack in map_screen.unit_stack_hitboxes],
            [selected_ids.intersection(unit["unit_id"] for unit in first_tile_units),
             {unit["unit_id"] for unit in first_tile_units[5:]},
             selected_ids.intersection(unit["unit_id"] for unit in second_tile_units),
             {unit["unit_id"] for unit in second_tile_units[3:]}])

    def test_zoomed_out_map_compresses_an_army_to_one_average_position_icon(self):
        first = {"owner": "A", "unit_id": "first", "type": "Infantry"}
        second = {"owner": "A", "unit_id": "second", "type": "Tank"}
        army = {"id": "one", "unit_ids": ["first", "second"], "symbol": "Star"}
        first_province = {"center": (20, 20), "units": [first]}
        second_province = {"center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM,
                                   tilt_factor=1),
            player_country="A", nation_data={"A": {"armies": [army]}},
            map_data={"first": first_province, "second": second_province},
            map_w=100, loop_map=False,
            nation_colors={"A": (220, 60, 70)}, tactical_mode=False,
            player_unit=None, hovered_unit_stack=None, unit_hover_hitboxes=[],
            unit_stack_hitboxes=[], unit_selection_drag=None,
            is_unit_selected=lambda _unit: False)
        surface = pygame.Surface((200, 200), pygame.SRCALPHA)

        with (patch.object(overlay_renderer, "compact_army_group_icon",
                           return_value=pygame.Surface((20, 20), pygame.SRCALPHA)) as icons,
              patch.object(queries, "world_to_screen", side_effect=lambda center, *_args:
                           center)):
            groups = overlay_renderer.compact_army_groups(map_screen, set())
            overlay_renderer.draw_compact_army_groups(map_screen, surface, groups)
            map_screen.is_unit_selected = lambda unit: unit is first
            partial_groups = overlay_renderer.compact_army_groups(map_screen, set())

        self.assertEqual([call.args[0]["id"] for call in icons.call_args_list], ["one", "one"])
        self.assertEqual(icons.call_args_list[0].args[4],
                         overlay_renderer.unit_box_size(map_screen)[:2])
        self.assertEqual(groups[0]["center"], (50, 30))
        self.assertEqual([stack["units"] for stack in map_screen.unit_stack_hitboxes],
                         [[first, second]])
        self.assertEqual(partial_groups[0]["units"], [second])
        self.assertEqual(partial_groups[0]["center"], (50, 30))

    def test_army_group_zoom_hides_partial_fog_unit_markers(self):
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(
                zoom=overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM,
                tilt_factor=1),
            tactical_mode=False, player_country="A", nation_data={})
        surface = pygame.Surface((100, 100), pygame.SRCALPHA)
        unit = {"owner": "B", "type": "Infantry"}

        with patch.object(overlay_renderer, "unknown_box") as unknown:
            overlay_renderer.draw_unit_icon(
                map_screen, surface, 50, 50, {"units": [unit]},
                is_partial=True, units=[unit], units_are_visible=True)

        unknown.assert_not_called()

        map_screen.camera.zoom = overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM + 0.1
        with patch.object(overlay_renderer, "unknown_box",
                          return_value=pygame.Surface((10, 10), pygame.SRCALPHA)) as unknown:
            overlay_renderer.draw_unit_icon(
                map_screen, surface, 50, 50, {"units": [unit]},
                is_partial=True, units=[unit], units_are_visible=True)

        unknown.assert_called_once()

        map_screen.is_unit_selected = lambda _unit: True
        self.assertEqual(overlay_renderer.compact_army_groups(map_screen, set()), [])

    def test_strategic_zoom_groups_unorganized_and_foreign_units_by_visible_area(self):
        organized = {"owner": "A", "unit_id": "organized", "type": "Infantry"}
        unorganized_one = {"owner": "A", "unit_id": "unorganized-one", "type": "Infantry"}
        unorganized_two = {"owner": "A", "unit_id": "unorganized-two", "type": "Tank"}
        foreign = {"owner": "B", "unit_id": "foreign", "type": "Infantry"}
        province = {"id": 1, "center": (20, 20), "units": [
            organized, unorganized_one, foreign]}
        nearby_province = {"id": 2, "center": (50, 20), "units": [unorganized_two]}
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM,
                                   tilt_factor=1),
            player_country="A", nation_data={"A": {"armies": [
                {"id": "one", "unit_ids": ["organized"]}]}, "B": {}},
            map_data={"province": province, "nearby": nearby_province},
            map_w=100, loop_map=False,
            nation_colors={"A": (220, 60, 70), "B": (70, 120, 220)})

        marker = pygame.Surface((20, 20), pygame.SRCALPHA)
        with patch.object(overlay_renderer, "compact_army_group_icon", return_value=marker):
            groups = overlay_renderer.compact_area_unit_groups(
                map_screen, set(), {id(organized)})

        self.assertEqual([group["units"] for group in groups], [
            [unorganized_one, unorganized_two], [foreign]])
        self.assertEqual(groups[0]["presentation_id"], ("area", "A", 1))
        self.assertEqual(groups[0]["center"], (35, 20))
        self.assertEqual(groups[1]["center"], (20, 20))

        map_screen.camera.zoom = 0.5
        with patch.object(overlay_renderer, "compact_army_group_icon", return_value=marker):
            zoomed_out_groups = overlay_renderer.compact_area_unit_groups(
                map_screen, set(), {id(organized)})
        self.assertEqual(
            [(group["units"], group["center"]) for group in zoomed_out_groups],
            [(group["units"], group["center"]) for group in groups])

        map_screen.visible_provinces = set()
        self.assertEqual(overlay_renderer.compact_area_unit_groups(
            map_screen, set(), {id(organized)}), [])

    def test_strategic_zoom_keeps_a_selected_unorganized_local_stack_expanded(self):
        selected_unit = {"owner": "A", "unit_id": "selected", "type": "Infantry"}
        other_local = {"owner": "A", "unit_id": "other", "type": "Tank"}
        foreign = {"owner": "B", "unit_id": "foreign", "type": "Infantry"}
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM,
                                   tilt_factor=1),
            player_country="A", nation_data={"A": {"armies": []}, "B": {}},
            map_data={"province": {"id": 1, "center": (20, 20), "units": [
                selected_unit, other_local, foreign]}}, map_w=100, loop_map=False,
            nation_colors={"A": (220, 60, 70), "B": (70, 120, 220)},
            is_unit_selected=lambda unit: unit is selected_unit,
            strategic_unit_fade_states={id(foreign): {"target_alpha": 0}})

        marker = pygame.Surface((20, 20), pygame.SRCALPHA)
        with patch.object(overlay_renderer, "compact_army_group_icon", return_value=marker):
            groups = overlay_renderer.compact_area_unit_groups(map_screen, set(), set())

        self.assertEqual([group["units"] for group in groups], [[foreign]])
        self.assertEqual(overlay_renderer.strategic_unit_fade_alphas(map_screen), {})
        self.assertEqual(map_screen.strategic_unit_fade_states, {})

    def test_tactical_zoom_never_compacts_or_fades_units(self):
        local = {"owner": "A", "unit_id": "local", "type": "Infantry"}
        foreign = {"owner": "B", "unit_id": "foreign", "type": "Infantry"}
        map_screen = SimpleNamespace(
            camera=SimpleNamespace(zoom=overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM),
            player_country="A", nation_data={"A": {"armies": []}, "B": {}},
            map_data={"province": {"units": [local, foreign]}}, tactical_mode=True,
            strategic_unit_fade_states={id(local): {"target_alpha": 0}})

        self.assertFalse(overlay_renderer.uses_compact_army_icons(map_screen))
        self.assertEqual(overlay_renderer.strategic_unit_fade_alphas(map_screen), {})
        self.assertEqual(map_screen.strategic_unit_fade_states, {})

    def test_tactical_mode_suppresses_country_names_even_when_the_toggle_is_on(self):
        map_screen = SimpleNamespace(show_country_names=True, tactical_mode=True)
        surface = pygame.Surface((100, 100))

        with patch.object(country_names.fonts, "get") as get_font:
            country_names.draw_country_names(map_screen, surface)

        get_font.assert_not_called()

    def test_army_group_transition_moves_units_to_the_average_marker(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"center": (20, 20), "units": [first]}
        second_province = {"center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100)
        desired = [{"army": {"id": "one"}, "units": [first, second],
                    "province": first_province, "center": (50, 30),
                    "icon": pygame.Surface((20, 20), pygame.SRCALPHA)}]
        transition_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)
        halfway_ms = transition_ms // 2

        with patch.object(pygame.time, "get_ticks", side_effect=[
                0, halfway_ms, transition_ms + 1, transition_ms + 1,
                transition_ms + 1 + halfway_ms]):
            groups, moving, suppressed = overlay_renderer.army_group_presentation(
                map_screen, desired, set())
            halfway_groups, halfway_moving, _suppressed = (
                overlay_renderer.army_group_presentation(map_screen, desired, set()))
            _finished_groups, finished_moving, _suppressed = (
                overlay_renderer.army_group_presentation(map_screen, desired, set()))
            expanding_groups, expanding_moving, _suppressed = (
                overlay_renderer.army_group_presentation(map_screen, [], set()))
            halfway_expanding_groups, halfway_expanding_moving, _suppressed = (
                overlay_renderer.army_group_presentation(map_screen, [], set()))

        self.assertEqual(suppressed, {id(first), id(second)})
        self.assertEqual([record["position"] for record in moving], [(20, 20), (80, 40)])
        self.assertEqual([record["position"] for record in halfway_moving],
                         [(35, 25), (65, 35)])
        self.assertEqual(groups[0]["alpha"], 0)
        self.assertEqual(halfway_groups[0]["alpha"], 128)
        self.assertEqual(finished_moving, [])
        self.assertEqual([record["position"] for record in expanding_moving],
                         [(50, 30), (50, 30)])
        self.assertEqual([record["position"] for record in halfway_expanding_moving],
                         [(35, 25), (65, 35)])
        self.assertEqual(expanding_groups[0]["alpha"], 255)
        self.assertEqual(halfway_expanding_groups[0]["alpha"], 128)

    def test_disabling_army_group_animations_switches_markers_immediately(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"center": (20, 20), "units": [first]}
        second_province = {"center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100,
            army_group_transition_states={"stale": {"phase": "compress"}})
        desired = [{"army": {"id": "one"}, "units": [first, second],
                    "province": first_province, "center": (50, 30),
                    "icon": pygame.Surface((20, 20), pygame.SRCALPHA)}]
        previous_setting = c.ARMY_GROUP_ANIMATIONS
        self.addCleanup(setattr, c, "ARMY_GROUP_ANIMATIONS", previous_setting)
        c.ARMY_GROUP_ANIMATIONS = False

        with patch.object(pygame.time, "get_ticks") as get_ticks:
            groups, moving, suppressed = overlay_renderer.army_group_presentation(
                map_screen, desired, set())

        self.assertEqual(groups, desired)
        self.assertEqual(moving, [])
        self.assertEqual(suppressed, {id(first), id(second)})
        self.assertEqual(map_screen.army_group_transition_states, {})
        get_ticks.assert_not_called()

    def test_nearby_unit_area_uses_the_same_compression_animation(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"id": 1, "center": (20, 20), "units": [first]}
        second_province = {"id": 2, "center": (50, 20), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100)
        desired = [{"army": None, "presentation_id": ("area", "A", 1),
                    "units": [first, second], "province": first_province,
                    "center": (35, 20),
                    "icon": pygame.Surface((20, 20), pygame.SRCALPHA)}]
        transition_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)
        halfway_ms = transition_ms // 2

        with patch.object(pygame.time, "get_ticks", side_effect=[0, halfway_ms]):
            groups, moving, suppressed = overlay_renderer.army_group_presentation(
                map_screen, desired, set())
            halfway_groups, halfway_moving, _suppressed = (
                overlay_renderer.army_group_presentation(map_screen, desired, set()))

        self.assertEqual(suppressed, {id(first), id(second)})
        self.assertEqual(groups[0]["alpha"], 0)
        self.assertEqual([record["position"] for record in moving], [(20, 20), (50, 20)])
        self.assertEqual(halfway_groups[0]["alpha"], 128)
        self.assertEqual([record["position"] for record in halfway_moving],
                         [(27.5, 20), (42.5, 20)])

    def test_nearby_area_member_changes_restart_its_animation_without_departures(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"id": 1, "center": (20, 20), "units": [first]}
        second_province = {"id": 2, "center": (50, 20), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100)
        icon = pygame.Surface((20, 20), pygame.SRCALPHA)
        combined_area = [{"army": None, "presentation_id": ("area", "A", 1),
                          "units": [first, second], "province": first_province,
                          "center": (35, 20), "icon": icon}]
        remaining_area = [{"army": None, "presentation_id": ("area", "A", 1),
                           "units": [first], "province": first_province,
                           "center": (20, 20), "icon": icon}]
        transition_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)

        with patch.object(pygame.time, "get_ticks", side_effect=[
                0, transition_ms + 1, transition_ms + 1]):
            overlay_renderer.army_group_presentation(map_screen, combined_area, set())
            overlay_renderer.army_group_presentation(map_screen, combined_area, set())
            _groups, moving, suppressed = overlay_renderer.army_group_presentation(
                map_screen, remaining_area, set())

        self.assertEqual(suppressed, {id(first)})
        self.assertEqual([record["unit"] for record in moving], [first])

    def test_deleted_army_departure_is_discarded_before_its_transition_draws(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"center": (20, 20), "units": [first]}
        second_province = {"center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100)
        icon = pygame.Surface((20, 20), pygame.SRCALPHA)
        combined_group = [{"army": {"id": "one"}, "units": [first, second],
                           "province": first_province, "center": (50, 30),
                           "icon": icon}]
        first_only_group = [{"army": {"id": "one"}, "units": [first],
                             "province": first_province, "center": (50, 30),
                             "icon": icon}]
        transition_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)

        with patch.object(pygame.time, "get_ticks", side_effect=[
                0, transition_ms + 1, transition_ms + 1, transition_ms + 2]):
            overlay_renderer.army_group_presentation(map_screen, combined_group, set())
            overlay_renderer.army_group_presentation(map_screen, combined_group, set())
            overlay_renderer.army_group_presentation(map_screen, first_only_group, set())
            second_province["units"].remove(second)
            _groups, moving, _suppressed = overlay_renderer.army_group_presentation(
                map_screen, first_only_group, set())

        self.assertNotIn(second, [record["unit"] for record in moving])

    def test_selecting_one_member_only_animates_that_member_out_of_marker(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"center": (20, 20), "units": [first]}
        second_province = {"center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100)
        icon = pygame.Surface((20, 20), pygame.SRCALPHA)
        combined_group = [{"army": {"id": "one"}, "units": [first, second],
                           "province": first_province, "center": (50, 30),
                           "icon": icon}]
        remaining_group = [{"army": {"id": "one"}, "units": [second],
                            "province": second_province, "center": (80, 40),
                            "icon": icon}]
        transition_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)
        halfway_ms = transition_ms // 2

        with patch.object(pygame.time, "get_ticks", side_effect=[
                0, transition_ms + 1, transition_ms + 1,
                transition_ms + 1 + halfway_ms]):
            overlay_renderer.army_group_presentation(map_screen, combined_group, set())
            overlay_renderer.army_group_presentation(map_screen, combined_group, set())
            groups, moving, suppressed = overlay_renderer.army_group_presentation(
                map_screen, remaining_group, set())
            _groups, halfway_moving, _suppressed = overlay_renderer.army_group_presentation(
                map_screen, remaining_group, set())

        self.assertEqual(groups[0]["units"], [second])
        self.assertEqual(groups[0].get("alpha", 255), 255)
        self.assertEqual(suppressed, {id(first), id(second)})
        self.assertEqual([record["unit"] for record in moving], [first])
        self.assertEqual([record["position"] for record in moving], [(50, 30)])
        self.assertEqual([record["unit"] for record in halfway_moving], [first])
        self.assertEqual([record["position"] for record in halfway_moving], [(35, 25)])

    def test_switching_selected_member_only_animates_the_new_selection(self):
        first = {"unit_id": "first"}
        second = {"unit_id": "second"}
        first_province = {"center": (20, 20), "units": [first]}
        second_province = {"center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            map_data={"first": first_province, "second": second_province},
            loop_map=False, map_w=100)
        icon = pygame.Surface((20, 20), pygame.SRCALPHA)
        combined_group = [{"army": {"id": "one"}, "units": [first, second],
                           "province": first_province, "center": (50, 30),
                           "icon": icon}]
        first_selected = [{"army": {"id": "one"}, "units": [second],
                           "province": first_province, "center": (50, 30),
                           "icon": icon}]
        second_selected = [{"army": {"id": "one"}, "units": [first],
                            "province": first_province, "center": (50, 30),
                            "icon": icon}]
        transition_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)
        halfway_ms = transition_ms // 2

        with patch.object(pygame.time, "get_ticks", side_effect=[
                0, transition_ms + 1, transition_ms + 1,
                transition_ms + 1, transition_ms + 1 + halfway_ms]):
            overlay_renderer.army_group_presentation(map_screen, combined_group, set())
            overlay_renderer.army_group_presentation(map_screen, combined_group, set())
            overlay_renderer.army_group_presentation(map_screen, first_selected, set())
            overlay_renderer.army_group_presentation(map_screen, second_selected, set())
            groups, moving, suppressed = overlay_renderer.army_group_presentation(
                map_screen, second_selected, set())

        self.assertEqual(groups[0]["center"], (50, 30))
        self.assertEqual(suppressed, {id(first), id(second)})
        self.assertEqual([record["unit"] for record in moving], [second])
        self.assertEqual([record["position"] for record in moving], [(65, 35)])

    def test_overlay_hides_every_compacted_army_member_from_its_provinces(self):
        first = {"owner": "A", "unit_id": "first", "type": "Infantry"}
        second = {"owner": "A", "unit_id": "second", "type": "Tank"}
        army = {"id": "one", "unit_ids": ["first", "second"], "symbol": "Star"}
        first_province = {"id": 1, "center": (20, 20), "units": [first]}
        second_province = {"id": 2, "center": (80, 40), "units": [second]}
        map_screen = SimpleNamespace(
            secondary_mode="UNITS", visible_provinces=None,
            camera=SimpleNamespace(zoom=overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM,
                                   tilt_factor=1),
            player_country="A", nation_data={"A": {"armies": [army]}},
            map_data={"first": first_province, "second": second_province},
            map_w=100, loop_map=False, nation_colors={"A": (220, 60, 70)},
            hovered_unit_stack=None, unit_hover_hitboxes=[], unit_stack_hitboxes=[],
            unit_selection_drag=None, is_unit_selected=lambda _unit: False)
        surface = pygame.Surface((200, 200), pygame.SRCALPHA)

        with (patch.object(overlay_renderer, "combat_bubble_records", return_value=[]),
              patch.object(overlay_renderer, "compact_army_group_icon",
                           return_value=pygame.Surface((20, 20), pygame.SRCALPHA)),
              patch.object(queries, "world_to_screen", side_effect=lambda center, *_args:
                           center),
              patch.object(overlay_renderer, "draw_unit_icon") as unit_stacks,
              patch.object(overlay_renderer, "draw_compact_army_groups") as groups):
            overlay_renderer.draw_overlay_content(map_screen, surface)

        self.assertEqual([call.kwargs["units"] for call in unit_stacks.call_args_list],
                         [[first], [second]])
        self.assertEqual(groups.call_args.args[2][0]["units"], [first, second])
        self.assertEqual(map_screen.compact_army_unit_object_ids, {id(first), id(second)})

    def test_blank_compact_army_icon_uses_a_larger_circular_marker(self):
        army = {"id": "army", "symbol": ""}
        best_unit = {"owner": "A", "type": "Tank"}
        fallback = pygame.Surface((48, 24), pygame.SRCALPHA)
        count_font = Mock(render=lambda *_args: pygame.Surface((8, 8), pygame.SRCALPHA))

        with (patch.object(overlay_renderer, "army_emblem_surface", return_value=None),
              patch.object(symbol_loader, "get_symbol", return_value=fallback) as symbol,
              patch.object(overlay_renderer.fonts, "get", return_value=count_font)):
            icon = overlay_renderer.compact_army_group_icon(
                army, best_unit, (220, 60, 70), "A", 24, 3)
            zoomed_out_icon = overlay_renderer.compact_army_group_icon(
                army, best_unit, (220, 60, 70), "A", 24, 3, zoom=0.5)

        self.assertEqual(icon.get_width(), icon.get_height())
        self.assertGreater(icon.get_width(), round(
            24 * c.UNIT_BOX_WIDTH / c.UNIT_BOX_HEIGHT))
        self.assertLess(zoomed_out_icon.get_width(), icon.get_width())
        self.assertEqual(icon.get_at((0, 0))[3], 0)
        self.assertEqual(symbol.call_args.args[0], "Tank")
        self.assertEqual(symbol.call_args.kwargs["color"], (220, 60, 70))

    def test_compact_army_icon_uses_only_the_army_emblem_inside_its_circle(self):
        army = {"id": "army", "symbol": "Star"}
        emblem = pygame.Surface((18, 18), pygame.SRCALPHA)
        emblem.fill((255, 0, 0, 255))
        count_font = Mock(render=lambda *_args: pygame.Surface((8, 8), pygame.SRCALPHA))

        with (patch.object(overlay_renderer, "army_emblem_surface", return_value=emblem),
              patch.object(symbol_loader, "get_symbol") as symbol,
              patch.object(overlay_renderer.fonts, "get", return_value=count_font)):
            icon = overlay_renderer.compact_army_group_icon(
                army, {"owner": "A", "type": "Tank"}, (220, 60, 70), "A", 24, 2)

        self.assertEqual(icon.get_width(), icon.get_height())
        self.assertGreater(icon.get_width(), round(
            24 * c.UNIT_BOX_WIDTH / c.UNIT_BOX_HEIGHT))
        self.assertEqual(icon.get_at((0, 0))[3], 0)
        self.assertEqual(icon.get_at((24, 33))[:3], (255, 0, 0))
        symbol.assert_not_called()

    def test_orders_tray_creates_armies_and_right_click_assigns_selection(self):
        world = {
            "one": {"id": 1, "owner": "A", "units": [
                {"owner": "A", "type": "Infantry"},
                {"owner": "A", "type": "Tank"},
            ]},
        }
        nations = {"A": {"armies": []}}
        queries.normalize_armies(nations, world)
        first_id, second_id = [unit["unit_id"] for unit in world["one"]["units"]]
        army = queries.create_army("A", [first_id], nations, world)
        selected_ids = [second_id]
        map_stub = SimpleNamespace(
            player_country="A", nation_data=nations, map_data=world,
            selected_province=world["one"], army_panel_visible_in_orders=True,
            selection_mode=False, is_editor=False, tactical_mode=False,
            realtime_multiplayer=False, map_w=1000, map_h=500,
            selected_map_unit_ids=lambda: selected_ids,
            can_select_map_units=lambda: True,
            assign_selection_to_army=lambda army_id: queries.assign_units_to_army(
                "A", army_id, selected_ids, nations, world),
            create_army_from_selection=lambda: queries.create_army(
                "A", selected_ids, nations, world),
            select_army=lambda *_args, **_kwargs: True,
        )
        orders = SimpleNamespace(read_only=False, refresh_ui=Mock())
        tray, armies = army_panel._layout(map_stub, show_create=True)
        card = map_top_right_layout.card_rect(tray, 0, map_stub.army_panel_scroll_y)
        army_panel.handle_event(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=3, pos=card.center),
            orders_screen=orders)
        self.assertEqual(set(nations["A"]["armies"][0]["unit_ids"]), {first_id, second_id})
        orders.refresh_ui.assert_called_once()
        self.assertTrue(army_panel.handle_event(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONUP, button=3, pos=card.center),
            orders_screen=orders))
        self.assertFalse(map_stub._army_tray_right_click_active)

        selected_ids[:] = [first_id]
        tray, armies = army_panel._layout(map_stub, show_create=True)
        create = army_panel._create_rect(tray, armies, map_stub.army_panel_scroll_y)
        army_panel.handle_event(
            map_stub, pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=create.center),
            orders_screen=orders)
        self.assertEqual(len(nations["A"]["armies"]), 2)

    @patch("ui.army_panel.queries.army_symbol_choices")
    def test_emblem_picker_wraps_compact_tiles_before_controls(self, choices):
        choices.return_value = [f"Emblem {index}"
                                for index in range(army_panel.SYMBOLS_PER_ROW)]
        rect = army_panel._editor_rect()
        tiles = army_panel._symbol_rects(rect)

        self.assertEqual(len(tiles), army_panel.SYMBOLS_PER_ROW + 2)
        self.assertIs(tiles[-1][0], army_panel.CUSTOM_SYMBOL_CHOICE)
        self.assertEqual(tiles[army_panel.SYMBOLS_PER_ROW][1].x,
                         tiles[0][1].x)
        self.assertGreater(tiles[army_panel.SYMBOLS_PER_ROW][1].y,
                           tiles[0][1].y)
        self.assertTrue(all(tile.right <= rect.right for _symbol, tile in tiles))
        self.assertGreater(army_panel._color_section_y(rect),
                           max(tile.bottom for _symbol, tile in tiles))
        self.assertLessEqual(army_panel._sample_rect(rect).bottom,
                             rect.bottom - 42)
        rotation_buttons = army_panel._rotation_button_rects(rect)
        self.assertEqual([rotation for rotation, _button in rotation_buttons],
                         list(c.ARMY_SYMBOL_ROTATIONS))
        self.assertTrue(all(button.right <= rect.right
                            for _rotation, button in rotation_buttons))

    def test_custom_emblem_canvas_is_exactly_twenty_pixels_square(self):
        pixels = army_panel._blank_custom_symbol()
        self.assertEqual(len(pixels), c.ARMY_CUSTOM_SYMBOL_SIZE)
        self.assertTrue(all(len(row) == c.ARMY_CUSTOM_SYMBOL_SIZE for row in pixels))
        canvas = pygame.Rect(50, 70, army_panel.CUSTOM_CANVAS_SIZE,
                             army_panel.CUSTOM_CANVAS_SIZE)
        state = {"pixels": pixels, "brush": c.ARMY_CUSTOM_SYMBOL_BLACK}
        self.assertTrue(army_panel._set_custom_pixel(state, canvas, canvas.center))
        custom_symbol = army_panel._custom_symbol_rows(pixels)
        self.assertIsNotNone(custom_symbol)
        self.assertEqual(len(custom_symbol), c.ARMY_CUSTOM_SYMBOL_SIZE)
        self.assertTrue(all(len(row) == c.ARMY_CUSTOM_SYMBOL_SIZE
                            for row in custom_symbol))

    def test_one_army_uses_a_compact_tray_and_province_view_hides_it(self):
        map_ref = SimpleNamespace(realtime_multiplayer=False, selected_province=None,
                                  selection_mode=False, is_editor=False,
                                  player_country="A", tactical_mode=False,
                                  map_w=1000, map_h=500)
        tray = map_top_right_layout.army_tray_rect(map_ref, 1)
        self.assertLess(tray.height, 100)
        self.assertTrue(army_panel._visible(map_ref))
        map_ref.selected_province = {"id": 1}
        self.assertFalse(army_panel._visible(map_ref))
        map_ref.army_panel_visible_in_orders = True
        self.assertTrue(army_panel._visible(map_ref))

    def test_realtime_tray_reserves_status_details_and_bottom_bar(self):
        details = SimpleNamespace(rect=pygame.Rect(c.SCREEN_WIDTH - 120, 140, 80, 24), visible=True)
        map_ref = SimpleNamespace(realtime_multiplayer=True,
                                  realtime_connection_error="", btn_realtime_details=details,
                                  map_w=1000, map_h=500)
        tray = map_top_right_layout.army_tray_rect(map_ref, 5)
        status = map_top_right_layout.realtime_status_rect()
        self.assertGreaterEqual(tray.top, max(status.bottom, details.rect.bottom) +
                                map_top_right_layout.PANEL_GAP)
        self.assertLessEqual(tray.bottom, c.SCREEN_HEIGHT - c.BOT_UI_HEIGHT -
                             map_top_right_layout.PANEL_GAP)
        self.assertLessEqual(tray.bottom, minimap.minimap_rect(
            map_ref, c.SCREEN_WIDTH, c.SCREEN_HEIGHT).top - map_top_right_layout.PANEL_GAP)


class MinimapTests(unittest.TestCase):
    def test_minimap_draws_the_active_map_layer(self):
        active_map = pygame.Surface((40, 20))
        active_map.fill((35, 140, 210))
        map_ref = SimpleNamespace(
            map_w=40, map_h=20, active_map=active_map,
            camera=SimpleNamespace(pos=SimpleNamespace(x=0, y=0), zoom=20, tilt_factor=1),
            total_ui_h=c.TOTAL_UI_HEIGHT)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        minimap.draw_minimap(map_ref, surface, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        rect = minimap.minimap_rect(map_ref, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        self.assertEqual(surface.get_at((rect.centerx, rect.centery))[:3], (35, 140, 210))

    def test_minimap_replaces_chroma_key_water_with_ocean_color(self):
        active_map = pygame.Surface((40, 20))
        active_map.fill(c.COLOR_CHROMA_PINK)
        active_map.set_colorkey(c.COLOR_CHROMA_PINK)
        map_ref = SimpleNamespace(
            map_w=40, map_h=20, active_map=active_map, bg_color=(17, 46, 83),
            camera=SimpleNamespace(pos=SimpleNamespace(x=0, y=0), zoom=20, tilt_factor=1),
            total_ui_h=c.TOTAL_UI_HEIGHT)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        minimap.draw_minimap(map_ref, surface, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        rect = minimap.minimap_rect(map_ref, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        self.assertEqual(surface.get_at((rect.centerx, rect.centery))[:3], (17, 46, 83))

    def test_minimap_composites_the_same_fog_layer_as_the_main_map(self):
        active_map = pygame.Surface((40, 20))
        active_map.fill((35, 140, 210))
        fog = pygame.Surface((40, 20), pygame.SRCALPHA)
        fog.fill((0, 0, 0, 180))
        map_ref = SimpleNamespace(
            map_w=40, map_h=20, active_map=active_map, fog_map=fog,
            camera=SimpleNamespace(pos=SimpleNamespace(x=0, y=0), zoom=20, tilt_factor=1),
            total_ui_h=c.TOTAL_UI_HEIGHT)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        minimap.draw_minimap(map_ref, surface, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        rect = minimap.minimap_rect(map_ref, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        pixel = surface.get_at((rect.centerx, rect.centery))[:3]
        self.assertLess(pixel[0], 35)
        self.assertLess(pixel[1], 140)
        self.assertLess(pixel[2], 210)
