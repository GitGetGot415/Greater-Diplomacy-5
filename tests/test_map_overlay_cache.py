"""Covers what makes the units view cheap enough to zoom out in.

Drawing the map in units view used to cost 443ms a frame -- two and a half
frames a second -- on a late-game army spread over a full map, and the cost was
almost entirely repeated work: the same icon resolved, scaled and composed once
per tile per frame, hundreds of times over, when a zoomed-out map is showing a
few dozen distinct pictures.

Three things fixed it, and all three are only correct if the cached thing really
is a function of its key. That is what these pin:

  - a symbol name resolves to the same file every time, so the regex walk over
    every loaded symbol can be memoised (it was 40% of a frame on its own)
  - a scaled symbol depends on nothing but its name, color, alpha and size, so
    it can be shared -- which means callers must not mutate it, and the four
    that used to call set_alpha on the result now ask for the alpha instead
  - a unit box depends on nothing but the flag color, the unit type, the count,
    whether it is the tactical player's own, and its size
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import data.constants as c
from data import queries
from map_logic.rendering import overlay_renderer, symbol_loader
from tests import app_harness


class SymbolCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()

    def setUp(self):
        symbol_loader.clear_caches()
        self.name = next(iter(symbol_loader.SYMBOLS))

    def test_the_same_request_gets_the_same_surface(self):
        first = symbol_loader.get_symbol(self.name, 2.0)
        second = symbol_loader.get_symbol(self.name, 2.0)
        self.assertIs(first, second)

    def test_a_different_size_is_a_different_surface(self):
        small = symbol_loader.get_symbol(self.name, 1.0)
        big = symbol_loader.get_symbol(self.name, 4.0)
        self.assertIsNot(small, big)
        self.assertGreater(big.get_width(), small.get_width())

    def test_zooms_that_round_to_one_size_share_it(self):
        """Zoom is continuous and lerps between notches, so the cache has to be
        keyed on the pixel size rather than the float that produced it."""
        first = symbol_loader.get_symbol(self.name, 2.0)
        second = symbol_loader.get_symbol(self.name, 2.0001)
        self.assertIs(first, second)

    def test_color_is_part_of_the_key(self):
        red = symbol_loader.get_symbol(self.name, 2.0, color=(255, 0, 0))
        blue = symbol_loader.get_symbol(self.name, 2.0, color=(0, 0, 255))
        self.assertIsNot(red, blue)
        self.assertIsNot(red, symbol_loader.get_symbol(self.name, 2.0))

    def test_alpha_is_part_of_the_key(self):
        """The whole reason get_symbol takes an alpha. "Hammer" at 1.5x is both
        the construction badge and the main menu's mods button; when the badge
        faded the surface it was handed, whichever drew last decided how solid
        the other one looked."""
        solid = symbol_loader.get_symbol(self.name, 2.0)
        faded = symbol_loader.get_symbol(self.name, 2.0, alpha=180)

        self.assertIsNot(solid, faded)
        self.assertEqual(faded.get_alpha(), 180)
        self.assertEqual(solid.get_alpha(), 255)

    def test_an_unknown_name_is_still_None(self):
        self.assertIsNone(symbol_loader.get_symbol("Not A Real Symbol", 2.0))

    def test_a_name_that_resolves_by_fallback_still_does(self):
        """The memoised path has to give the same answer as the regex walk --
        a unit is asked for by its full name, "Infantry Type 1936"."""
        self.assertEqual(symbol_loader._resolve_name("Infantry Type 1936"),
                         symbol_loader._resolve_name_uncached("Infantry Type 1936"))

    def test_a_carried_unit_still_draws_its_carrier(self):
        self.assertEqual(symbol_loader._resolve_name("Convoy (Infantry Type 1940)"),
                         symbol_loader._resolve_name_uncached("Convoy (Infantry Type 1940)"))

    def test_the_cache_is_dropped_rather_than_grown_without_limit(self):
        symbol_loader.SCALED_SYMBOLS.update(
            {("filler", None, 255, (n, n)): None
             for n in range(symbol_loader.SCALED_CACHE_LIMIT)})

        symbol_loader.get_symbol(self.name, 2.0)

        self.assertEqual(len(symbol_loader.SCALED_SYMBOLS), 1)

    def test_reloading_the_art_drops_what_was_derived_from_it(self):
        """A mod can replace a .png under a name already resolved and scaled."""
        symbol_loader.get_symbol(self.name, 2.0)
        symbol_loader.load_symbols()

        self.assertEqual(symbol_loader.SCALED_SYMBOLS, {})
        self.assertEqual(symbol_loader.RESOLVED_NAMES, {})


class CombatDisplayTests(unittest.TestCase):
    def setUp(self):
        self.old_display_mode = c.BATTLE_DISPLAY_MODE
        self.addCleanup(setattr, c, "BATTLE_DISPLAY_MODE", self.old_display_mode)

        self.mine = {"owner": "A"}
        self.enemy = {"owner": "B"}
        self.province = {
            "id": "battle",
            "center": (100, 100),
            "units": [self.mine, self.enemy],
        }
        self.map = SimpleNamespace(
            player_country="A",
            visible_provinces=None,
            partial_visible_provinces=set(),
            is_editor=False,
            id_to_province={"battle": self.province},
            nation_data={},
        )
        self.prediction = {
            "type": "province",
            "loc": "battle",
            "forces": {"A": [self.mine], "B": [self.enemy]},
        }

    def records(self, mode):
        c.BATTLE_DISPLAY_MODE = mode
        with mock.patch.object(queries, "get_combat_predictions",
                               return_value=[self.prediction]), \
             mock.patch.object(queries, "get_all_friendly_nations",
                               return_value={"A"}), \
             mock.patch.object(queries, "is_province_in_active_combat",
                               return_value=True), \
             mock.patch.object(queries, "get_combat_location_category",
                               return_value=queries.COMBAT_LOCATION_DEFENSE), \
             mock.patch.object(overlay_renderer, "combat_outlook_color",
                               return_value=(255, 255, 0)), \
             mock.patch.object(overlay_renderer, "estimated_combat_turns",
                               return_value=1):
            return overlay_renderer.combat_bubble_records(self.map)

    def test_full_display_keeps_active_battle_units_visible(self):
        compact = self.records("COMPACT")[0]
        full = self.records("FULL")[0]

        self.assertEqual(compact["hidden_unit_ids"],
                         {id(self.mine), id(self.enemy)})
        self.assertEqual(full["hidden_unit_ids"], set())

    def test_full_display_makes_active_bubble_translucent(self):
        record = {"category": queries.COMBAT_LOCATION_DEFENSE,
                  "color": (255, 255, 0), "potential": False}
        predicted_record = dict(record, potential=True)
        surface = pygame.Surface((20, 20), pygame.SRCALPHA)
        with mock.patch.object(symbol_loader, "get_symbol",
                               return_value=surface) as get_symbol:
            c.BATTLE_DISPLAY_MODE = "FULL"
            overlay_renderer._combat_bubble_symbol(record, 1.0)
            active_alpha = get_symbol.call_args.kwargs["alpha"]
            self.assertEqual(active_alpha, overlay_renderer.COMBAT_BUBBLE_FULL_ALPHA)

            overlay_renderer._combat_bubble_symbol(predicted_record, 1.0)
            predicted_alpha = get_symbol.call_args.kwargs["alpha"]
            self.assertEqual(predicted_alpha,
                             overlay_renderer.COMBAT_BUBBLE_FULL_PREDICTION_ALPHA)
            self.assertLess(predicted_alpha, active_alpha)

            c.BATTLE_DISPLAY_MODE = "COMPACT"
            overlay_renderer._combat_bubble_symbol(record, 1.0)
            self.assertEqual(get_symbol.call_args.kwargs["alpha"], 255)


class UnitBoxCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()

    def setUp(self):
        overlay_renderer.UNIT_BOXES.clear()

    def box(self, **kwargs):
        args = dict(symbol_name="Infantry", border_color=(200, 30, 30), count=3,
                    inverted=False, size=(40, 20))
        args.update(kwargs)
        return overlay_renderer.unit_box(**args)

    def test_two_tiles_showing_the_same_thing_share_one_box(self):
        self.assertIs(self.box(), self.box())

    def test_the_count_is_drawn_on_it_so_it_is_part_of_the_key(self):
        self.assertIsNot(self.box(count=3), self.box(count=4))

    def test_so_is_the_nation_color(self):
        self.assertIsNot(self.box(), self.box(border_color=(30, 30, 200)))

    def test_so_is_the_tactical_inversion(self):
        """Black on white is how the player finds their own division."""
        self.assertIsNot(self.box(), self.box(inverted=True))

    def test_the_box_is_drawn_at_the_size_asked_for(self):
        self.assertEqual(self.box(size=(40, 20)).get_size(), (40, 20))
        self.assertEqual(self.box(size=(60, 30)).get_size(), (60, 30))

    def test_the_unknown_box_is_shared_too(self):
        self.assertIs(overlay_renderer.unknown_box((40, 20)),
                      overlay_renderer.unknown_box((40, 20)))

    def test_the_cache_is_dropped_rather_than_grown_without_limit(self):
        overlay_renderer.UNIT_BOXES.update(
            {n: None for n in range(overlay_renderer.UNIT_BOX_CACHE_LIMIT)})

        self.box()

        self.assertEqual(len(overlay_renderer.UNIT_BOXES), 1)


class CullingTests(unittest.TestCase):
    """A province is culled by its centre, but what is drawn hangs off that
    centre, so the margin has to cover the overhang."""

    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        # boot_map's Map is shared with every other module in the suite, so put
        # back everything moved here -- the panel and smoke tests both read the
        # selection and the view mode this leaves behind.
        cam = self.map.camera
        self.addCleanup(setattr, self.map, "secondary_mode", self.map.secondary_mode)
        self.addCleanup(setattr, self.map, "selected_province", self.map.selected_province)
        self.addCleanup(setattr, cam, "zoom", cam.zoom)
        self.addCleanup(setattr, cam, "target_zoom", cam.target_zoom)
        self.addCleanup(cam.pos.update, cam.pos.x, cam.pos.y)

        self.map.set_view_mode("UNITS")
        self.map.selected_province = None
        self.real_draw = overlay_renderer.draw_unit_icon
        self.drawn = []

        def spy(map_screen, surface, sx, sy, province, is_partial=False):
            self.drawn.append((sx, sy))

        overlay_renderer.draw_unit_icon = spy
        self.addCleanup(setattr, overlay_renderer, "draw_unit_icon", self.real_draw)

    def test_the_margin_clears_the_overhang_of_a_crowded_tile(self):
        self.map.camera.zoom = c.MAX_CAMERA_ZOOM
        self.map.camera.tilt_factor = 1.0
        _w, h, scale = overlay_renderer.unit_box_size(self.map)

        # Six nations on one tile is a crowded but perfectly ordinary battle,
        # and the stack is centred, so half of it is what sits outside the cull.
        overhang = ((h * 6) + max(2, int(4 * scale)) * 5) // 2

        self.assertGreater(overlay_renderer.CULL_MARGIN, overhang)

    def look_at(self, province, zoom):
        """Centres the camera on a province, the way clicking one would."""
        cam = self.map.camera
        cam.zoom = cam.target_zoom = zoom
        cam.pos.update(province["center"][0] - (self.surface.get_width() / 2) / zoom,
                       province["center"][1] - (self.surface.get_height() / 2) / zoom)
        cam.update(self.map, self.surface.get_height())

    def a_visible_garrison(self):
        """A province with units on it that the player is allowed to see."""
        return next(p for p in self.map.map_data.values()
                    if p.get("units")
                    and (self.map.visible_provinces is None
                         or p["id"] in self.map.visible_provinces))

    def test_only_tiles_near_the_viewport_are_drawn(self):
        """The height half of the cull was missing, so a zoomed-in map composed
        and blitted icons for every tile above and below the viewport."""
        self.look_at(self.a_visible_garrison(), 6.0)

        overlay_renderer.draw_overlay_content(self.map, self.surface)

        self.assertTrue(self.drawn, "nothing drawn at all -- the test is not looking")
        bottom = self.surface.get_height() + overlay_renderer.CULL_MARGIN
        self.assertTrue(all(-overlay_renderer.CULL_MARGIN < sy < bottom
                            for _sx, sy in self.drawn))

    def test_zoomed_out_the_whole_map_is_still_drawn(self):
        """The cull must not start hiding tiles that are genuinely on screen."""
        garrison = self.a_visible_garrison()

        self.look_at(garrison, self.map.min_zoom)
        overlay_renderer.draw_overlay_content(self.map, self.surface)
        zoomed_out = len(self.drawn)

        self.drawn = []
        self.look_at(garrison, 6.0)
        overlay_renderer.draw_overlay_content(self.map, self.surface)

        self.assertGreater(zoomed_out, len(self.drawn))


if __name__ == "__main__":
    unittest.main()
