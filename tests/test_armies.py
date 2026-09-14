"""Regression coverage for persistent army organization and tray geometry."""

import unittest
from types import SimpleNamespace

import pygame

import data.constants as c
from data import queries
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
             "symbol": "", "symbol_color": list(c.DEFAULT_ARMY_SYMBOL_COLOR)}])

    def test_army_presentation_round_trips_and_invalid_legacy_art_is_removed(self):
        queries.normalize_armies(self.nations, self.world)
        unit_id = self.first["units"][0]["unit_id"]
        army = queries.create_army("A", [unit_id], self.nations, self.world)
        symbol = queries.army_symbol_choices()[0]
        updated = queries.update_army_presentation(
            "A", army["id"], "Northern Command", symbol, [12, 90, 230],
            self.nations, self.world)
        self.assertEqual(updated["name"], "Northern Command")
        self.assertEqual(updated["symbol"], symbol)
        self.assertEqual(updated["symbol_color"], [12, 90, 230])
        updated["symbol"] = "No Longer Installed"
        updated["symbol_color"] = [999, 0, 0]
        queries.normalize_armies(self.nations, self.world)
        normalized = self.nations["A"]["armies"][0]
        self.assertEqual(normalized["symbol"], "")
        self.assertEqual(normalized["symbol_color"], list(c.DEFAULT_ARMY_SYMBOL_COLOR))

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
