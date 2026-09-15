"""Regression coverage for persistent army organization and tray geometry."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

import data.constants as c
from data import queries
from map_logic.rendering import overlay_renderer
from screens.map_related_screens.orders import Orders_Screen
from ui import army_panel, map_top_right_layout, minimap


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
             "custom_symbol": None}])

    def test_army_presentation_round_trips_and_invalid_legacy_art_is_removed(self):
        queries.normalize_armies(self.nations, self.world)
        unit_id = self.first["units"][0]["unit_id"]
        army = queries.create_army("A", [unit_id], self.nations, self.world)
        symbol = queries.army_symbol_choices()[0]
        custom_symbol = ([c.ARMY_CUSTOM_SYMBOL_RED + c.ARMY_CUSTOM_SYMBOL_EMPTY * 19]
                         + [c.ARMY_CUSTOM_SYMBOL_EMPTY * 20] * 19)
        updated = queries.update_army_presentation(
            "A", army["id"], "Northern Command", symbol, [12, 90, 230], 90,
            custom_symbol, self.nations, self.world)
        self.assertEqual(updated["name"], "Northern Command")
        self.assertEqual(updated["symbol"], "")
        self.assertEqual(updated["symbol_color"], [12, 90, 230])
        self.assertEqual(updated["symbol_rotation"], 90)
        self.assertEqual(updated["custom_symbol"], custom_symbol)
        updated["symbol"] = "No Longer Installed"
        updated["symbol_color"] = [999, 0, 0]
        updated["symbol_rotation"] = 45
        updated["custom_symbol"] = ["invalid"]
        queries.normalize_armies(self.nations, self.world)
        normalized = self.nations["A"]["armies"][0]
        self.assertEqual(normalized["symbol"], "")
        self.assertEqual(normalized["symbol_color"], list(c.DEFAULT_ARMY_SYMBOL_COLOR))
        self.assertEqual(normalized["symbol_rotation"], c.DEFAULT_ARMY_SYMBOL_ROTATION)
        self.assertIsNone(normalized["custom_symbol"])

    @patch("data.queries.random.choice", return_value=(12, 90, 230))
    def test_new_army_uses_a_random_persistent_color_for_member_bands(self, choose_color):
        queries.normalize_armies(self.nations, self.world)
        member, ungrouped = self.first["units"]
        army = queries.create_army("A", [member["unit_id"]], self.nations, self.world)

        choose_color.assert_called_once_with(c.ARMY_SYMBOL_COLOR_CHOICES)
        self.assertEqual(army["symbol_color"], [12, 90, 230])
        self.assertEqual(queries.army_color_for_unit(member, self.nations), (12, 90, 230))
        self.assertIsNone(queries.army_color_for_unit(ungrouped, self.nations))

    def test_orders_shows_unselected_peers_without_selecting_them(self):
        queries.normalize_armies(self.nations, self.world)
        first_unit, second_unit = self.first["units"]
        queries.create_army("A", [first_unit["unit_id"], second_unit["unit_id"]],
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
        self.assertEqual({unit["unit_id"] for _key, unit, _province, _index in rows},
                         {first_unit["unit_id"], second_unit["unit_id"]})
        self.assertEqual(selected_ids, {first_unit["unit_id"]})

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


class ArmyLayoutTests(unittest.TestCase):
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
