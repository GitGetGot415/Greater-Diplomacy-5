"""Map-only unit filters share classification, fog and rendered hitboxes."""
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import data.constants as c
from data import queries
from map_logic.rendering import overlay_renderer, map_renderer
from screens.menu_screens.map import Map, update_button_states
from tests import app_harness
from ui import event_handler, minimap, map_top_right_layout
from ui.bars import ui_bars
from ui.confirm_dialog.message_box import _NavigationIntroPopup
from ui.information import tooltip


class UnitViewFilterTests(unittest.TestCase):
    def setUp(self):
        # Deliberately artificial content tests domain rules without balance
        # assumptions about any particular unit from the shipped library.
        library = {"Test Land": {}, "Test Ship": {"naval_unit": True},
                   "Test Plane": {"air_role": "fighter"}}
        self.library_patch = patch.object(queries, "get_unit_library", return_value=library)
        self.library_patch.start()
        self.addCleanup(self.library_patch.stop)
        self.units = [{"type": name, "owner": "A", "unit_id": name}
                      for name in library]
        self.province = {"id": 1, "center": (100, 100), "units": self.units}
        self.game = SimpleNamespace(
            map_data={"one": self.province}, _presentation_cache_revision=0,
            unit_view_filter="ALL", player_country="A",
            nation_data={"A": {"armies": []}}, nation_colors={"A": (50, 100, 150)},
            camera=SimpleNamespace(zoom=4, tilt_factor=1),
            tactical_mode=False, player_unit=None, hovered_unit_stack=None,
            unit_hover_hitboxes=[], unit_stack_hitboxes=[], unit_selection_drag=None,
            is_unit_selected=lambda _unit: False, map_w=1000, loop_map=False)

    def test_current_form_drives_the_filter(self):
        for unit, expected in zip(self.units, ("LAND", "NAVAL", "AIR")):
            for view_filter in queries.UNIT_VIEW_FILTERS:
                self.assertEqual(queries.unit_matches_view_filter(unit, view_filter),
                                 view_filter in (expected, "ALL"))
        carried = {"type": "Convoy (Test Plane)", "original_type": "Test Plane"}
        self.assertTrue(queries.unit_matches_view_filter(carried, "NAVAL"))
        carried["type"] = "Truck (Test Plane)"
        self.assertTrue(queries.unit_matches_view_filter(carried, "LAND"))
        self.assertFalse(queries.unit_matches_view_filter(carried, "AIR"))
        with self.assertRaises(ValueError):
            queries.unit_matches_view_filter(carried, "invalid")

    def preview_lines(self, visible=True):
        pygame.font.init()
        font = pygame.font.Font(None, 16)
        self.game.small_font = SimpleNamespace(render=Mock(wraps=font.render))
        self.game.hovered_province = self.province
        self.game.base_layer = "POLITICAL"
        self.game.secondary_mode = "UNITS"
        with patch.object(queries, "is_province_visible", return_value=visible):
            tooltip.draw_tooltip(self.game, pygame.Surface((400, 400)))
        return [call.args[0] for call in self.game.small_font.render.call_args_list]

    def test_hover_preview_uses_cached_map_filter_membership(self):
        for view_filter in queries.UNIT_VIEW_FILTERS:
            with self.subTest(view_filter=view_filter):
                self.game.unit_view_filter = view_filter
                expected = overlay_renderer._unit_render_index(self.game).view_records
                with patch.object(queries, "unit_matches_view_filter", side_effect=AssertionError):
                    lines = self.preview_lines()
                listed = [unit for unit in self.units if any(unit["type"] in line for line in lines)]
                self.assertEqual(listed, [unit for unit, _province in expected])
                self.assertEqual(self.province["units"], self.units)

    def test_preview_limit_applies_after_category_filtering(self):
        self.game.unit_view_filter = "AIR"
        planes = [dict(self.units[2], unit_id=f"plane-{index}")
                  for index in range(tooltip.UNIT_PREVIEW_LIMIT + 2)]
        self.province["units"] = [self.units[0]] * tooltip.UNIT_PREVIEW_LIMIT + planes
        lines = self.preview_lines()
        self.assertEqual(sum(self.units[2]["type"] in line for line in lines),
                         tooltip.UNIT_PREVIEW_LIMIT)
        self.assertFalse(any(self.units[0]["type"] in line for line in lines))
        self.assertIn(str(len(planes) - tooltip.UNIT_PREVIEW_LIMIT), lines[-1])

    def test_preview_keeps_fog_and_submarine_visibility(self):
        self.game.unit_view_filter = "NAVAL"
        submarine = {"type": "Submarine I", "owner": "B"}
        queries.get_unit_library()[submarine["type"]] = {"naval_unit": True}
        self.province["units"] = [self.units[1], submarine]
        self.assertIn(submarine, overlay_renderer._unit_render_index(
            self.game).view_units_by_province[id(self.province)])
        lines = self.preview_lines()
        self.assertTrue(any(self.units[1]["type"] in line for line in lines))
        self.assertFalse(any(submarine["type"] in line for line in lines))
        self.game.partial_visible_provinces = {self.province["id"]}
        for view_filter in ("LAND", "AIR", "NAVAL"):
            self.game.unit_view_filter = view_filter
            partial_lines = self.preview_lines(visible=False)
            self.game.partial_visible_provinces = set()
            self.assertEqual(partial_lines, self.preview_lines(visible=False))
            self.game.partial_visible_provinces = {self.province["id"]}
            self.assertFalse(any(unit["type"] in line
                                 for unit in self.province["units"] for line in partial_lines))

    def test_selected_province_roster_retains_other_categories(self):
        from ui import sidebar_info
        self.game.unit_view_filter = "AIR"
        with (patch.object(queries, "is_province_in_active_combat", return_value=False),
              patch.object(sidebar_info.combat_rules, "build_battle",
                           return_value=SimpleNamespace(profiles={})),
              patch.object(sidebar_info, "unit_roster_row", return_value={})):
            sidebar_info.prepare_unit_roster(self.game, self.province)
        rows = self.game._unit_roster_cache[self.province["id"]][2]
        self.assertEqual(set(rows), {id(unit) for unit in self.units})

    def test_filter_membership_is_cached_and_world_units_are_preserved(self):
        self.game.unit_view_filter = "AIR"
        first = overlay_renderer._unit_render_index(self.game)
        self.assertEqual(first.view_records, ((self.units[2], self.province),))
        self.assertEqual(len(first.records), len(self.units))
        with patch.object(queries, "unit_matches_view_filter", side_effect=AssertionError):
            self.assertIs(overlay_renderer._unit_render_index(self.game), first)
        self.game.unit_view_filter = "LAND"
        second = overlay_renderer._unit_render_index(self.game)
        self.assertIsNot(first, second)
        self.assertEqual(second.view_records, ((self.units[0], self.province),))
        self.units[0]["type"] = "Test Plane"
        self.game._presentation_cache_revision += 1
        self.assertEqual(overlay_renderer._unit_render_index(self.game).view_records, ())
        self.assertEqual(len(self.province["units"]), len(self.units))

    def test_only_matching_visible_units_publish_selection_and_hover_boxes(self):
        surface = pygame.Surface((300, 300))
        for tactical in (False, True):
            self.game.tactical_mode = tactical
            self.game.player_unit = self.units[2] if tactical else None
            for view_filter, expected in (("NAVAL", [self.units[1]]),
                                          ("LAND", [self.units[0]]),
                                          ("AIR", [self.units[2]]),
                                          ("ALL", self.units)):
                self.game.unit_view_filter = view_filter
                self.game.unit_hover_hitboxes = []
                self.game.unit_stack_hitboxes = []
                overlay_renderer.draw_unit_icon(self.game, surface, 100, 100, self.province)
                self.assertEqual({id(unit) for box in self.game.unit_hover_hitboxes
                                  for unit in box["units"]}, {id(unit) for unit in expected})
                self.assertEqual({id(unit) for box in self.game.unit_stack_hitboxes
                                  for unit in box["units"]}, {id(unit) for unit in expected})
        self.game.unit_view_filter = "AIR"
        self.game.unit_hover_hitboxes = []
        with patch.object(queries, "filter_visible_units", return_value=[]):
            overlay_renderer.draw_unit_icon(self.game, surface, 100, 100, self.province)
        self.assertEqual(self.game.unit_hover_hitboxes, [])

    def test_mixed_armies_and_foreign_area_markers_count_only_matching_members(self):
        self.game.camera.zoom = overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM
        self.game.unit_view_filter = "AIR"
        self.game.nation_data["A"]["armies"] = [{
            "id": "mixed", "unit_ids": [unit["unit_id"] for unit in self.units]}]
        groups = overlay_renderer.compact_army_groups(self.game, set())
        self.assertEqual([group["units"] for group in groups], [[self.units[2]]])
        self.game.nation_data["A"]["armies"] = []
        self.game.player_country = "Spectator"
        groups = overlay_renderer.compact_area_unit_groups(self.game, set(), set())
        self.assertEqual([group["units"] for group in groups], [[self.units[2]]])
        self.game.visible_provinces = set()
        self.assertEqual(overlay_renderer.compact_area_unit_groups(self.game, set(), set()), [])

    def test_unknown_stacks_cannot_reveal_their_domain(self):
        surface = pygame.Surface((300, 300))
        with patch.object(overlay_renderer, "unknown_box",
                          return_value=pygame.Surface((20, 20))) as unknown:
            for view_filter in queries.UNIT_VIEW_FILTERS:
                self.game.unit_view_filter = view_filter
                unknown.reset_mock()
                overlay_renderer.draw_unit_icon(
                    self.game, surface, 100, 100, self.province, is_partial=True)
                self.assertEqual(unknown.call_count, int(view_filter == "ALL"))

    def test_combat_display_and_hit_testing_share_filtered_cached_forecasts(self):
        land, _ship, air = self.units
        records = [
            {"unit_ids": {id(land)}, "information_available": True},
            {"unit_ids": {id(air)}, "information_available": True},
            {"unit_ids": {id(air)}, "information_available": False},
        ]
        self.game.unit_view_filter = "AIR"
        self.game._combat_bubble_records_cache = (
            (self.game._presentation_cache_revision, self.game.player_country,
             id(None), id(None), c.BATTLE_DISPLAY_MODE), records)
        with (patch.object(overlay_renderer, "combat_bubbles_are_visible", return_value=True),
              patch.object(queries, "get_combat_predictions", side_effect=AssertionError)):
            first = overlay_renderer.combat_bubble_records(self.game)
            self.assertEqual(first, [records[1]])
            self.assertIs(overlay_renderer.combat_bubble_records(self.game), first)
            self.game.unit_view_filter = "LAND"
            self.assertEqual(overlay_renderer.combat_bubble_records(self.game), [records[0]])
            self.game.unit_view_filter = "ALL"
            self.assertIs(overlay_renderer.combat_bubble_records(self.game), records)


class UnitViewControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.game = Map(load_path=app_harness.SCENARIO_PATH, is_scenario=True)
        cls.game.player_country = sorted(queries.get_living_nations(cls.game.map_data))[0]
        cls.game.selection_mode = False

    def setUp(self):
        self.game.selected_province = None
        self.game.unit_view_filter = queries.DEFAULT_UNIT_VIEW_FILTER
        self.game.tactical_mode = False
        self.game.set_play_view_defaults()
        update_button_states(self.game)

    def test_defaults_callbacks_icons_and_shared_bar_layout(self):
        game = self.game
        self.assertEqual(game.unit_view_filter, "ALL")
        buttons = list(game.unit_view_buttons.values())
        self.assertEqual(tuple(game.unit_view_buttons), queries.UNIT_VIEW_FILTERS)
        self.assertTrue(all(button.visible and button.image is not None for button in buttons))
        self.assertEqual([button.is_selected for button in buttons], [False, False, False, True])
        bar = ui_bars.map_unit_view_bar_rect(game)
        self.assertTrue(all(bar.contains(button.rect) for button in buttons))
        self.assertTrue(all(top.rect.bottom < bottom.rect.top
                            and top.rect.centerx == bottom.rect.centerx
                            for top, bottom in zip(buttons, buttons[1:])))
        self.assertGreaterEqual(bar.left, game.raised_rect.right)
        self.assertLessEqual(bar.bottom, game.ui_background_rect.top)
        for button in buttons:
            self.assertGreater(max(button.image.get_size()), min(button.rect.size) / 2)
            self.assertLess(max(button.image.get_size()), min(button.rect.size))
        mini = minimap.minimap_rect(game, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        self.assertEqual(mini.bottom, c.SCREEN_HEIGHT - minimap.MINIMAP_MARGIN_Y)
        self.assertFalse(mini.colliderect(bar))
        self.assertLessEqual(map_top_right_layout.army_tray_rect(game, 100).bottom, mini.top)
        self.assertTrue(event_handler.map_ui_bar_at_position(game, bar.center))
        for view_filter, button in game.unit_view_buttons.items():
            game.selected_unit_ids.add("old selection")
            game.army_group_transition_states["old"] = {}
            before = queries.build_save_dict(game)
            button.callback()
            self.assertEqual(game.unit_view_filter, view_filter)
            self.assertEqual(game.secondary_mode, "UNITS")
            self.assertTrue(button.is_selected)
            self.assertEqual(game.selected_unit_ids, set())
            self.assertEqual(game.army_group_transition_states, {})
            after = queries.build_save_dict(game)
            before.pop("generated_at")
            after.pop("generated_at")
            self.assertEqual(after, before)
            path = Path("assets/images") / f"{view_filter.title()}.png"
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        with patch.object(ui_bars, "draw_textured_rect") as textured:
            ui_bars.draw_ui_bars(game, pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertTrue(any(call.args[1] == bar for call in textured.call_args_list))
        game.selected_province = next(iter(game.map_data.values()))
        update_button_states(game)
        self.assertFalse(any(button.visible for button in buttons))
        self.assertIsNone(ui_bars.map_unit_view_bar_rect(game))

    def test_filters_and_bar_only_appear_in_units_view(self):
        game = self.game
        mini = minimap.minimap_rect(game, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        for mode in ("UNITS", "ECONOMY", "RESOURCES", "BLANK", "UNITS"):
            game.set_view_mode(mode)
            update_button_states(game)
            self.assertEqual([button.visible for button in game.unit_view_buttons.values()],
                             [mode == "UNITS"] * len(queries.UNIT_VIEW_FILTERS))
            self.assertEqual(ui_bars.map_unit_view_bar_rect(game) is not None, mode == "UNITS")
            self.assertEqual(event_handler.map_ui_bar_at_position(
                game, game.unit_view_bar_rect.center), mode == "UNITS")
            self.assertEqual(minimap.minimap_rect(game, c.SCREEN_WIDTH, c.SCREEN_HEIGHT), mini)

    def test_changing_unit_filter_does_not_switch_or_announce_a_map_view(self):
        game = self.game
        for mode in ("UNITS", "ECONOMY"):
            game.secondary_mode = mode
            with (patch.object(game, "set_view_mode") as switch_view,
                  patch.object(game, "show_feedback") as feedback):
                game.set_unit_view_filter("AIR")
            self.assertEqual(game.secondary_mode, mode)
            switch_view.assert_not_called()
            feedback.assert_not_called()

    def test_order_arrows_follow_the_unit_filter(self):
        game = self.game
        library = {"Test Land": {}, "Test Ship": {"naval_unit": True},
                   "Test Plane": {"air_role": "fighter"}}
        units = [{"type": name, "owner": game.player_country,
                  "order": {"type": "MOVE", "path": [index + 2]}}
                 for index, name in enumerate(library)]
        origin = {"id": 1, "center": (100, 100), "units": units}
        with (patch.dict(game.__dict__, map_data={"one": origin},
                         _unit_render_index_cache=None),
              patch.object(queries, "get_unit_library", return_value=library),
              patch.object(overlay_renderer, "draw_overlay_content", return_value=[]),
              patch.object(overlay_renderer, "draw_midpoint_bounces"),
              patch.object(overlay_renderer, "draw_combat_bubbles"),
              patch.object(map_renderer.country_names, "draw_country_names"),
              patch.object(overlay_renderer, "draw_split_movement_path") as arrows):
            for view_filter, expected in (("LAND", [[2]]), ("NAVAL", [[3]]),
                                          ("AIR", [[4]]), ("ALL", [[2], [3], [4]])):
                game.unit_view_filter = view_filter
                arrows.reset_mock()
                map_renderer.draw_map_screen(
                    game, pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
                self.assertEqual([call.args[3] for call in arrows.call_args_list], expected)

    def test_tutorial_filter_note_fits_above_navigation_controls(self):
        popup = _NavigationIntroPopup(SimpleNamespace())
        popup.page_index = 1
        popup.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertLess(popup.unit_view_note_rect.bottom, popup.prev_rect.top)
        self.assertTrue(popup.rect.contains(popup.unit_view_note_rect))


if __name__ == "__main__":
    unittest.main()
