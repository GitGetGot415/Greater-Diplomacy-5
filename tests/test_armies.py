"""Regression coverage for persistent army organization and tray geometry."""

import unittest
from types import SimpleNamespace

import pygame

import data.constants as c
from data import queries
from ui import army_panel, map_top_right_layout


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


class ArmyLayoutTests(unittest.TestCase):
    def test_one_army_uses_a_compact_tray_and_province_view_hides_it(self):
        map_ref = SimpleNamespace(realtime_multiplayer=False, selected_province=None,
                                  selection_mode=False, is_editor=False,
                                  player_country="A", tactical_mode=False)
        tray = map_top_right_layout.army_tray_rect(map_ref, 1)
        self.assertLess(tray.height, 100)
        self.assertTrue(army_panel._visible(map_ref))
        map_ref.selected_province = {"id": 1}
        self.assertFalse(army_panel._visible(map_ref))

    def test_realtime_tray_reserves_status_details_and_bottom_bar(self):
        details = SimpleNamespace(rect=pygame.Rect(c.SCREEN_WIDTH - 120, 140, 80, 24), visible=True)
        map_ref = SimpleNamespace(realtime_multiplayer=True,
                                  realtime_connection_error="", btn_realtime_details=details)
        tray = map_top_right_layout.army_tray_rect(map_ref, 5)
        status = map_top_right_layout.realtime_status_rect()
        self.assertGreaterEqual(tray.top, max(status.bottom, details.rect.bottom) +
                                map_top_right_layout.PANEL_GAP)
        self.assertLessEqual(tray.bottom, c.SCREEN_HEIGHT - c.BOT_UI_HEIGHT -
                             map_top_right_layout.PANEL_GAP)
