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
from map_logic.rendering import overlay_renderer, map_renderer, symbol_loader
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
        carried["order"] = {"type": "AIR_ATTACK"}
        self.assertEqual(queries.unit_map_stack_key(carried), ("NAVAL", None))
        carried["type"] = "Truck (Test Plane)"
        self.assertTrue(queries.unit_matches_view_filter(carried, "LAND"))
        self.assertEqual(queries.unit_map_stack_key(carried), ("LAND", None))
        self.assertFalse(queries.unit_matches_view_filter(carried, "AIR"))
        with self.assertRaises(ValueError):
            queries.unit_matches_view_filter(carried, "invalid")

    def draw_training_badge(self, *, suppressed=(), alphas=None):
        self.game.secondary_mode = "UNITS"
        self.game.visible_provinces = getattr(self.game, "visible_provinces", None)
        badge = pygame.Surface((12, 12))
        badge.fill((20, 90, 160))
        surface = pygame.Surface((400, 400))
        with (patch.object(queries, "world_to_screen", return_value=(100, 100)),
              patch.object(overlay_renderer, "combat_bubble_records", return_value=[]),
              patch.object(overlay_renderer, "compact_army_groups", return_value=[]),
              patch.object(overlay_renderer, "compact_area_unit_groups", return_value=[]),
              patch.object(overlay_renderer, "army_group_presentation", return_value=([], [], set(suppressed))),
              patch.object(overlay_renderer, "strategic_unit_fade_alphas", return_value=alphas or {}),
              patch.object(overlay_renderer, "draw_unit_icon"),
              patch.object(overlay_renderer, "status_icon", return_value=badge) as icons):
            overlay_renderer.draw_overlay_content(self.game, surface, draw_combat=False)
        return [call.args[1] for call in icons.call_args_list], surface

    def test_empty_factory_training_badge_uses_queued_category_for_every_filter(self):
        self.province["units"] = []
        for unit in self.units:
            self.province["unit_queue"] = [{"unit_type": unit["type"], "turns_remaining": 2}]
            self.game._presentation_cache_revision += 1
            for view_filter in queries.UNIT_VIEW_FILTERS:
                with self.subTest(unit=unit["type"], filter=view_filter):
                    self.game.unit_view_filter = view_filter
                    icons, surface = self.draw_training_badge()
                    expected = queries.unit_matches_view_filter(unit, view_filter)
                    self.assertEqual(icons, [c.ICON_TRAINING] if expected else [])
                    self.assertEqual(surface.get_at((100, 100))[:3], (20, 90, 160) if expected else (0, 0, 0))
                    index = overlay_renderer._unit_render_index(self.game)
                    self.assertEqual(index.records, ())
                    self.assertEqual(index.total_units, 0)

    def test_training_badge_does_not_depend_on_filtered_or_compact_garrisons(self):
        self.province["unit_queue"] = [{"unit_type": self.units[0]["type"]}]
        self.province["units"] = self.units[2:]
        self.game.unit_view_filter = "LAND"
        self.assertEqual(self.draw_training_badge()[0], [c.ICON_TRAINING])
        self.province["units"] = self.units[:1]
        self.game._presentation_cache_revision += 1
        self.assertEqual(self.draw_training_badge(suppressed=[id(self.units[0])])[0], [c.ICON_TRAINING])
        self.assertEqual(self.draw_training_badge(alphas={id(self.units[0]): 0})[0], [c.ICON_TRAINING])

    def test_fog_hides_training_even_when_the_queue_is_present(self):
        self.province["units"] = []
        self.province["unit_queue"] = [{"unit_type": self.units[0]["type"]}]
        self.game.visible_provinces = set()
        for partial in (set(), {self.province["id"]}):
            with self.subTest(partial=partial):
                self.game.partial_visible_provinces = partial
                self.assertEqual(self.draw_training_badge()[0], [])

    def test_queue_edits_refresh_cached_training_without_frame_classification(self):
        self.province["units"] = []
        overlay_renderer._unit_render_index(self.game)
        self.province["unit_queue"] = [{"unit_type": self.units[0]["type"]}]
        self.game._presentation_cache_revision += 1
        overlay_renderer._unit_render_index(self.game)
        with patch.object(queries, "is_training_troops", side_effect=AssertionError("Frame checked training")):
            self.assertEqual(self.draw_training_badge()[0], [c.ICON_TRAINING])
        self.province["unit_queue"].clear()
        self.game._presentation_cache_revision += 1
        self.assertEqual(self.draw_training_badge()[0], [])

    def mission_units(self):
        orders = ({}, {}, {"type": "AIR_PATROL"},
                  {"type": "AIR_PATROL", "priority": "STRONGEST"},
                  {"type": "AIR_ATTACK", "target_id": 2},
                  {"type": "AIR_ATTACK", "target_id": 3},
                  {"type": "AIR_REPOSITION", "target_id": 2})
        planes = [dict(self.units[2], unit_id=f"plane-{index}", order=order)
                  for index, order in enumerate(orders)]
        self.province["units"] = self.units[:2] + planes
        self.game._presentation_cache_revision += 1
        return planes

    def test_map_separates_domains_and_air_missions_with_matching_hitboxes(self):
        planes = self.mission_units()
        self.game.camera.tilt_factor = 0.2
        surface = pygame.Surface((400, 400))
        overlay_renderer.draw_unit_icon(self.game, surface, 200, 200, self.province)
        groups = self.game.unit_stack_hitboxes
        expected = [self.units[:1], self.units[1:2], planes[:2], planes[2:3],
                    planes[3:4], planes[4:6], planes[6:]]
        self.assertCountEqual([tuple(unit["unit_id"] for unit in group["units"]) for group in groups],
                              [tuple(unit["unit_id"] for unit in members) for members in expected])
        self.assertEqual([box["units"] for box in self.game.unit_hover_hitboxes],
                         [box["units"] for box in groups])
        for index, group in enumerate(groups):
            for other in groups[index + 1:]:
                self.assertFalse(group["rect"].colliderect(other["rect"]))
            self.assertEqual(group["rect"].size, overlay_renderer.unit_box_size(self.game)[:2])
            if group["units"][0] in planes[2:]:
                size = overlay_renderer._army_emblem_size(group["rect"].height)
                badge_center = (group["rect"].right + overlay_renderer.AIR_MISSION_GAP + size // 2,
                                group["rect"].centery)
                self.assertIsNone(event_handler._unit_stack_at(self.game, badge_center))
                self.assertTrue(all(not box["rect"].collidepoint(badge_center)
                                    for box in self.game.unit_hover_hitboxes))

    def test_mission_badges_match_army_emblem_sizes_and_keep_opacity(self):
        native = pygame.Surface((12, 12), pygame.SRCALPHA)
        native.fill((255, 220, 0))
        for mission in ("WEAKEST", "STRONGEST", "STRIKE", "MOVE"):
            for height, alpha in ((8, 255), (30, 100), (60, 255)):
                with self.subTest(mission=mission, height=height, alpha=alpha):
                    surface = pygame.Surface((100, 100), pygame.SRCALPHA)
                    box = pygame.Rect(10, 10, 20, height)
                    name = c.AIR_MISSION_ICONS[mission]
                    size = overlay_renderer._army_emblem_size(height)
                    with patch.object(symbol_loader, "get_symbol", return_value=native) as symbol:
                        overlay_renderer._draw_air_mission(surface, box, name, alpha)
                    symbol.assert_called_once_with(name, 1, style="classic",
                                                   fit_size=(size, size))
                    badge_right = box.right + overlay_renderer.AIR_MISSION_GAP + size
                    self.assertEqual(surface.get_at((badge_right - 2, box.centery)).a, alpha)

    def test_zoomed_out_markers_separate_domains_and_combine_air_missions(self):
        self.mission_units()
        self.game.camera.zoom = 0.2
        self.game.camera.pos = pygame.Vector2()
        self.game.top_ui_height = 100
        members = self.province["units"]
        self.game.nation_data["A"]["armies"] = [{
            "id": "mixed", "unit_ids": [unit["unit_id"] for unit in members]}]
        army_groups = overlay_renderer.compact_army_groups(self.game, set())
        self.game.nation_data["A"]["armies"] = []
        area_groups = overlay_renderer.compact_area_unit_groups(self.game, set(), set())
        for groups in (army_groups, area_groups):
            self.assertEqual(len(groups), 3)
            self.assertEqual(len({group["presentation_id"] for group in groups}), len(groups))
            for group in groups:
                domains = {queries.unit_display_domain(unit) for unit in group["units"]}
                self.assertEqual(len(domains), 1)
                if domains == {"AIR"}:
                    self.assertEqual(group["units"], members[2:])
            self.game.unit_stack_hitboxes = []
            with patch.object(overlay_renderer, "_draw_air_mission") as badges:
                overlay_renderer.draw_compact_army_groups(self.game, pygame.Surface((400, 400)), groups)
            badges.assert_not_called()
            boxes = self.game.unit_stack_hitboxes
            for index, box in enumerate(boxes):
                for other in boxes[index + 1:]:
                    self.assertFalse(box["rect"].colliderect(other["rect"]))

    def test_stack_classification_is_cached_until_orders_or_viewer_change(self):
        planes = self.mission_units()
        index = overlay_renderer._unit_render_index(self.game)
        with patch.object(queries, "unit_map_stack_key", side_effect=AssertionError):
            overlay_renderer.draw_unit_icon(self.game, pygame.Surface((400, 400)),
                                            200, 200, self.province)
        planes[0]["order"] = {"type": "AIR_ATTACK", "target_id": 2}
        self.game._presentation_cache_revision += 1
        updated = overlay_renderer._unit_render_index(self.game)
        self.assertIsNot(index, updated)
        self.assertEqual(updated.stack_keys[id(planes[0])], ("AIR", "STRIKE"))
        self.game.player_country = "B"
        self.assertEqual(overlay_renderer._unit_render_index(self.game).stack_keys[id(planes[0])],
                         ("AIR", "NONE"))

    def test_mission_change_preserves_the_compact_marker_without_restarting_animation(self):
        planes = self.mission_units()
        self.province["units"] = planes[:1]
        self.game.camera.zoom = 0.2
        duration_ms = round(overlay_renderer.ARMY_GROUP_TRANSITION_SECONDS * 1000)
        with patch.object(c, "ARMY_GROUP_ANIMATIONS", True), \
             patch.object(overlay_renderer.pygame.time, "get_ticks", return_value=0):
            idle_groups = overlay_renderer.compact_area_unit_groups(self.game, set(), set())
            overlay_renderer.army_group_presentation(self.game, idle_groups, set())
        with patch.object(overlay_renderer.pygame.time, "get_ticks", return_value=duration_ms):
            _groups, moving, _suppressed = overlay_renderer.army_group_presentation(self.game, idle_groups, set())
            self.assertEqual(moving, [])
            planes[0]["order"] = {"type": "AIR_ATTACK", "target_id": 2}
            self.game._presentation_cache_revision += 1
            strike_groups = overlay_renderer.compact_area_unit_groups(self.game, set(), set())
            groups, moving, suppressed = overlay_renderer.army_group_presentation(
                self.game, strike_groups, set())
        self.assertEqual([group["presentation_id"] for group in groups],
                         [group["presentation_id"] for group in idle_groups])
        self.assertEqual(moving, [])
        self.assertEqual(suppressed, {id(planes[0])})

    def test_zoomed_out_aircraft_keep_their_armies_separate(self):
        planes = self.mission_units()
        self.game.camera.zoom = 0.2
        self.game.nation_data["A"]["armies"] = [
            {"id": "first", "unit_ids": [unit["unit_id"] for unit in planes[:3]]},
            {"id": "second", "unit_ids": [unit["unit_id"] for unit in planes[3:5]]}]
        groups = overlay_renderer.compact_army_groups(self.game, set())
        self.assertEqual([group["army"]["id"] for group in groups], ["first", "second"])
        self.assertEqual([group["units"] for group in groups], [planes[:3], planes[3:5]])
        areas = overlay_renderer.compact_area_unit_groups(
            self.game, set(), {id(unit) for unit in planes[:5]})
        air_areas = [group for group in areas if group["units"][0]["type"] == "Test Plane"]
        self.assertEqual([group["units"] for group in air_areas], [planes[5:]])

    def test_zoomed_out_selected_and_transition_aircraft_hide_mission_badges(self):
        self.mission_units()
        self.game.camera.zoom = 0.2
        self.game.is_unit_selected = lambda _unit: True
        with patch.object(overlay_renderer, "_draw_air_mission") as badges:
            overlay_renderer.draw_unit_icon(self.game, pygame.Surface((400, 400)),
                                            200, 200, self.province)
        badges.assert_not_called()
        air_boxes = [box for box in self.game.unit_stack_hitboxes
                     if box["units"][0]["type"] == "Test Plane"]
        self.assertEqual([box["units"] for box in air_boxes], [self.province["units"][2:]])
        self.game.unit_stack_hitboxes = []
        self.game.camera.pos = pygame.Vector2()
        self.game.top_ui_height = 0
        plane = self.province["units"][-1]
        with patch.object(overlay_renderer, "_draw_air_mission") as badges:
            overlay_renderer.draw_army_group_transition_units(
                self.game, pygame.Surface((400, 400)),
                [{"unit": plane, "province": self.province, "position": (100, 100)}])
        badges.assert_not_called()

    def test_foreign_or_fogged_orders_do_not_reveal_missions(self):
        planes = self.mission_units()
        self.game.player_country = "B"
        with patch.object(overlay_renderer, "_draw_air_mission", wraps=overlay_renderer._draw_air_mission) as badges:
            overlay_renderer.draw_unit_icon(self.game, pygame.Surface((400, 400)),
                                            200, 200, self.province)
        self.assertTrue(all(call.args[2] is None for call in badges.call_args_list))
        for viewer, preview in (("Spectator", False), ("B", True)):
            self.game.player_country = viewer
            self.game.viewing_ai_moves = preview
            self.assertEqual(overlay_renderer._unit_render_index(self.game).stack_keys[id(planes[4])],
                             ("AIR", "STRIKE"))
        with patch.object(overlay_renderer, "_draw_air_mission") as badges:
            overlay_renderer.draw_unit_icon(self.game, pygame.Surface((400, 400)),
                                            200, 200, self.province, is_partial=True)
        badges.assert_not_called()

    def test_tactical_view_keeps_every_division_separate_at_all_zooms(self):
        self.mission_units()
        self.game.tactical_mode = True
        self.game.player_unit = self.province["units"][-1]
        for zoom in (0.2, 4):
            self.game.camera.zoom = zoom
            self.game.unit_stack_hitboxes = []
            overlay_renderer.draw_unit_icon(self.game, pygame.Surface((400, 400)),
                                            200, 200, self.province)
            self.assertEqual(len(self.game.unit_stack_hitboxes), len(self.province["units"]))
            self.assertTrue(all(len(box["units"]) == 1 for box in self.game.unit_stack_hitboxes))

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
        for width in (1024, c.SCREEN_WIDTH):
            with self.subTest(width=width), patch.object(c, "SCREEN_WIDTH", width):
                popup = _NavigationIntroPopup(SimpleNamespace())
                popup.page_index = 1
                popup.draw(pygame.Surface((width, c.SCREEN_HEIGHT)))
                self.assertLess(popup.unit_view_note_rect.bottom, popup.prev_rect.top)
                self.assertTrue(popup.rect.contains(popup.unit_view_note_rect))

    def test_tutorial_filter_icons_stay_right_of_their_names_and_use_cached_lines(self):
        from ui import text_utils
        from ui.confirm_dialog import message_box
        icons = {}
        colors = {}
        for index, view_filter in enumerate(queries.UNIT_VIEW_FILTERS):
            color = (40 + index * 30, 20, 70)
            icon = pygame.Surface((20, 14))
            icon.fill(color)
            icons[view_filter.lower()] = icon
            colors[view_filter] = color
        with patch.dict(message_box.ui_elements.UI_ICONS, icons), \
                patch.object(message_box, "render_inline_text", wraps=text_utils.render_inline_text) as render:
            popup = _NavigationIntroPopup(SimpleNamespace())
        groups = [icon for text, icon in render.call_args.args[0] if icon is not None]
        self.assertEqual(len(groups), len(queries.UNIT_VIEW_FILTERS))
        for view_filter, group in zip(queries.UNIT_VIEW_FILTERS, groups):
            icon_rect = pygame.mask.from_threshold(group, colors[view_filter], (1, 1, 1, 255)).get_bounding_rects()[0]
            name_width = popup.body_font.size(view_filter.title())[0]
            self.assertGreater(icon_rect.left, name_width)
            self.assertLessEqual(icon_rect.right, group.get_width())
            self.assertLessEqual(icon_rect.bottom, group.get_height())
        self.assertTrue(all(line.get_width() <= popup.rect.width - 2 * popup.SUBTITLE_SIDE_PADDING
                            for line in popup.unit_view_note_lines))
        popup.page_index = 1
        with patch.object(message_box, "render_inline_text", side_effect=AssertionError("Frame prepared tutorial")):
            popup.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))

    def test_tutorial_image_markers_control_order_position_and_size(self):
        from ui import text_utils
        from ui.confirm_dialog import message_box
        icon = pygame.Surface((20, 10))
        icon.fill((17, 83, 121))
        note = "[icon:air:32] first\nChanged [icon:naval:12] repeated [icon:air] end"
        with patch.object(_NavigationIntroPopup, "UNIT_VIEW_NOTE", note), \
                patch.dict(message_box.ui_elements.UI_ICONS, {"air": icon, "naval": icon}), \
                patch.object(message_box, "render_inline_text", wraps=text_utils.render_inline_text) as render:
            popup = _NavigationIntroPopup(SimpleNamespace())
        parts = render.call_args.args[0]
        groups = [image for text, image in parts if image is not None]
        self.assertEqual(len(groups), 3)
        for group, size in zip(groups, (32, 12, popup.body_font.get_height())):
            rect = pygame.mask.from_threshold(group, (17, 83, 121), (1, 1, 1, 255)).get_bounding_rects()[0]
            self.assertEqual(rect.size, (size, round(size / 2)))
        self.assertEqual(groups[0].get_width(), 32)
        self.assertIn((" first\n", None), parts)
        self.assertEqual(parts[-1], (" end", None))

    def test_tutorial_without_markers_keeps_plain_text(self):
        from ui import text_utils
        from ui.confirm_dialog import message_box
        note = "Air and Naval can appear without images."
        with patch.object(_NavigationIntroPopup, "UNIT_VIEW_NOTE", note), \
                patch.object(message_box, "render_inline_text", wraps=text_utils.render_inline_text) as render:
            _NavigationIntroPopup(SimpleNamespace())
        self.assertEqual(render.call_args.args[0], [(note, None)])


if __name__ == "__main__":
    unittest.main()
