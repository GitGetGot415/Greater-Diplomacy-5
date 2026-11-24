"""Covers the three panels layered over the map: Buildings/Garrison, Diplomatic
Info and the production queue overlay.

Each publishes a rect and a scroll ceiling under its own attribute prefix, and
screens/game/map_input.py gives all three identical treatment -- block map clicks
underneath, take the wheel, and be draggable. That used to be nine copy-pasted
blocks; these tests pin the behaviour the table-driven version has to keep.
"""

import unittest
from types import SimpleNamespace
from unittest import mock

import pygame

import data.constants as c
from tests import app_harness
from screens.game import map_input
from ui.information import ui_info_popup
from tests.stub_map_screen import map_double
def wheel(y, pos):
    pygame.mouse.get_pos = lambda: pos
    return pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y, flipped=False,
                              precise_x=0.0, precise_y=float(y))


class MapPanelScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.real_get_pos = pygame.mouse.get_pos

    def setUp(self):
        # The panels only exist with a province selected outside selection mode,
        # which is the state the map starts a scenario in.
        self.map.selected_province = next(
            province for province in self.map.world.map_data.values()
            if province.get("owner") not in c.UNPLAYABLE_NATIONS)
        self.map.session.selection_mode = False
        self.map.refresh_ui()
        self.map.draw(self.surface)

    def tearDown(self):
        pygame.mouse.get_pos = self.real_get_pos

    def test_all_three_panels_publish_a_rect(self):
        for name in map_input.MAP_PANELS:
            with self.subTest(panel=name):
                self.assertIsNotNone(map_input._panel_rect(self.map, name),
                                     f"{name} panel published no rect")

    def test_panels_are_only_live_with_a_selection(self):
        self.assertTrue(map_input._panels_are_live(self.map))
        self.map.session.selection_mode = True
        self.assertFalse(map_input._panels_are_live(self.map))
        self.map.session.selection_mode = False

    def test_wheel_over_a_panel_scrolls_it_and_not_the_others(self):
        for name in map_input.MAP_PANELS:
            with self.subTest(panel=name):
                rect = map_input._panel_rect(self.map, name)
                # Give the panel something to scroll; the ceiling is normally
                # set from the content height while drawing.
                for other in map_input.MAP_PANELS:
                    self.map.scroll_state(other).value = 0
                    setattr(self.map, f"{other}_scroll_max", 500)

                map_input.handle_map_events(self.map, wheel(-1, rect.center))

                self.assertGreater(self.map.scroll_state(name).value, 0,
                                   f"{name} did not scroll")
                for other in map_input.MAP_PANELS:
                    if other != name:
                        self.assertEqual(self.map.scroll_state(other).value, 0,
                                         f"{other} scrolled when {name} was under the cursor")

    def test_scroll_is_clamped_to_the_ceiling(self):
        name = map_input.MAP_PANELS[0]
        rect = map_input._panel_rect(self.map, name)
        self.map.scroll_state(name).value = 0
        setattr(self.map, f"{name}_scroll_max", 40)

        for _ in range(20):
            map_input.handle_map_events(self.map, wheel(-1, rect.center))
        self.assertEqual(self.map.scroll_state(name).value, 40)

        for _ in range(20):
            map_input.handle_map_events(self.map, wheel(1, rect.center))
        self.assertEqual(self.map.scroll_state(name).value, 0)

    def test_wheel_off_every_panel_does_not_scroll_them(self):
        for name in map_input.MAP_PANELS:
            self.map.scroll_state(name).value = 0
            setattr(self.map, f"{name}_scroll_max", 500)

        # Bottom-left corner, clear of all three published rects.
        away = (2, 2)
        self.assertFalse(any(r.collidepoint(away)
                             for r in (map_input._panel_rect(self.map, n)
                                       for n in map_input.MAP_PANELS)))
        map_input.handle_map_events(self.map, wheel(-1, away))

        for name in map_input.MAP_PANELS:
            self.assertEqual(self.map.scroll_state(name).value, 0)

    def test_a_panel_blocks_clicks_reaching_the_map(self):
        """Hovering a panel must set on_ui, or a click passes through to the
        province underneath it."""
        rect = map_input._panel_rect(self.map, map_input.MAP_PANELS[0])
        pygame.mouse.get_pos = lambda: rect.center
        before = self.map.hovered_province
        map_input.handle_map_events(
            self.map, pygame.event.Event(pygame.MOUSEMOTION, pos=rect.center,
                                         rel=(1, 1), buttons=(0, 0, 0)))
        self.assertIsNone(self.map.hovered_province,
                          f"hover reached the map through a panel (was {before})")

    def test_click_in_a_bar_uses_event_position_not_current_cursor(self):
        """A queued click on a bar cannot select the stale tile under the cursor."""
        self.map.session.selection_mode = True
        map_position = (self.surface.get_width() // 2,
                        self.surface.get_height() // 2)
        bar_position = self.map.top_bar_rect.center
        pygame.mouse.get_pos = lambda: map_position
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                   pos=bar_position, button=1)

        with mock.patch.object(map_input.player_setup,
                               "select_player_country") as select_country:
            map_input.handle_map_events(self.map, event)

        select_country.assert_not_called()

    def test_province_menu_blocks_combat_bubbles_behind_opaque_artwork(self):
        """Only the opaque portion of the province background blocks a bubble."""
        pos = (300, self.surface.get_height() // 2)
        pygame.mouse.get_pos = lambda: pos
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                   pos=pos, button=1)

        with mock.patch.object(
                map_input.overlay_renderer,
                "combat_bubble_at_screen_pos",
                return_value={"orders_province_id": "hidden"}) as hit_test:
            map_input.handle_map_events(self.map, event)

        hit_test.assert_not_called()

    def test_province_menu_blocks_tile_selection_behind_opaque_artwork(self):
        """Covered tiles cannot replace the province shown in the menu."""
        current = self.map.selected_province
        replacement = next(province for province in self.map.world.map_data.values()
                           if province is not current)
        pos = (300, self.surface.get_height() // 2)
        self.assertTrue(map_input.ui_bars.province_menu_occludes_map_position(
            pos, self.surface.get_size()))

        with mock.patch.object(map_input.queries, "get_clicked_province",
                               return_value=replacement) as hit_test:
            map_input.handle_map_events(
                self.map, pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=pos, button=1))

        hit_test.assert_not_called()
        self.assertIs(self.map.selected_province, current)

    def test_province_menu_keeps_its_transparent_map_window_clickable(self):
        """A visible province replaces the current selection through clear artwork."""
        current = self.map.selected_province
        replacement = next(province for province in self.map.world.map_data.values()
                           if (province is not current
                               and province.get("owner") not in c.UNPLAYABLE_NATIONS))
        original_mode = self.map.secondary_mode
        original_pos = pygame.Vector2(self.map.camera.pos)
        original_target_pos = pygame.Vector2(self.map.camera.target_pos)
        self.addCleanup(setattr, self.map, "selected_province", current)
        self.addCleanup(setattr, self.map, "secondary_mode", original_mode)
        self.addCleanup(setattr, self.map.camera, "pos", original_pos)
        self.addCleanup(setattr, self.map.camera, "target_pos", original_target_pos)
        pos = (self.surface.get_width() // 2, self.surface.get_height() // 2)
        pygame.mouse.get_pos = lambda: pos
        self.map.secondary_mode = "BLANK"

        with mock.patch.object(map_input.queries, "get_clicked_province",
                               return_value=replacement):
            map_input.handle_map_events(
                self.map, pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=pos, button=1))

        self.assertIs(self.map.selected_province, replacement)

class RelationIndicatorTests(unittest.TestCase):
    def test_only_hovered_opinion_shows_its_own_breakdown(self):
        pygame.font.init()
        player_tile = {"id": 1, "owner": "A", "cores": ["B"]}
        foreign_tile = {"id": 2, "owner": "B", "center": (20, 30)}
        game = map_double(
            selected_province=None, player_country="A", selection_mode=False,
            viewing_ai_moves=False, extreme_hidden_provinces=set(), camera=None, total_ui_h=0,
            _presentation_cache_revision=0, _relation_indicator_cache=None,
            small_font=pygame.font.Font(None, 14), id_to_province={1: player_tile, 2: foreign_tile},
            nation_data={"A": {"temp_modifiers": {"B": {"general": 6}}},
                         "B": {"claims": [1], "temp_modifiers": {"A": {"recent_war": -12}}}},
        )
        with (mock.patch.object(map_input, "map_ui_bar_at_position", return_value=False),
              mock.patch.object(map_input.queries, "get_clicked_province", return_value=foreign_tile),
              mock.patch.object(map_input.sidebar_info, "prepare_unit_roster"),
              mock.patch.object(map_input.camera_handler, "center_camera_on_province"),
              mock.patch.object(map_input.sound_effects, "play_ui_sound")):
            self.assertTrue(map_input._select_map_province(game, (400, 200), navigate=False))

        surface = pygame.Surface((400, 360))
        with mock.patch.object(ui_info_popup, "_draw_relation_breakdown") as draw_breakdown:
            for rect, modifier in zip(ui_info_popup.RELATION_ROW_RECTS, (-12, 6)):
                draw_breakdown.reset_mock()
                with mock.patch.object(pygame.mouse, "get_pos", return_value=rect.center):
                    ui_info_popup.draw_relation_indicators(game, surface)
                draw_breakdown.assert_called_once()
                _, score, factors = draw_breakdown.call_args.args[-1]
                self.assertEqual(score, c.REL_MOD_PER_CLAIM + modifier)
                self.assertCountEqual([value for _, value in factors], [c.REL_MOD_PER_CLAIM, modifier])

            draw_breakdown.reset_mock()
            with mock.patch.object(pygame.mouse, "get_pos", return_value=(400, 200)):
                ui_info_popup.draw_relation_indicators(game, surface)
            draw_breakdown.assert_not_called()


class ExitConfirmationTests(unittest.TestCase):
    """The quit-to-menu dialog is drawn by ui/rendering/map_renderer.py
    and clicked in screens/game/map_input.py. Its button geometry used to be written
    out in both, in two different coordinate frames, agreeing only by accident
    of the box's height."""

    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.real_get_pos = pygame.mouse.get_pos

    def setUp(self):
        self.map.show_exit_confirmation = True
        self.map.refresh_ui()
        self.map.draw(self.surface)

    def tearDown(self):
        pygame.mouse.get_pos = self.real_get_pos
        self.map.show_exit_confirmation = False

    def press(self, pos):
        pygame.mouse.get_pos = lambda: pos
        map_input.handle_map_events(
            self.map, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))

    def test_drawing_publishes_both_button_rects(self):
        self.assertIsNotNone(getattr(self.map, "exit_yes_rect", None))
        self.assertIsNotNone(getattr(self.map, "exit_no_rect", None))

    def test_clicking_anywhere_in_the_drawn_stay_button_cancels(self):
        """Every corner of the painted button has to answer, which is exactly
        what the two-coordinate-frame version could not guarantee."""
        rect = self.map.exit_no_rect
        for pos in (rect.center, (rect.left + 1, rect.top + 1), (rect.right - 1, rect.top + 1),
                    (rect.left + 1, rect.bottom - 1), (rect.right - 1, rect.bottom - 1)):
            with self.subTest(pos=pos):
                self.map.show_exit_confirmation = True
                self.press(pos)
                self.assertFalse(self.map.show_exit_confirmation,
                                 f"click at {pos} missed the drawn STAY button")

    def test_clicking_outside_both_buttons_does_nothing(self):
        self.press((self.map.exit_no_rect.right + 40, self.map.exit_no_rect.centery))
        self.assertTrue(self.map.show_exit_confirmation)

if __name__ == "__main__":
    unittest.main()
