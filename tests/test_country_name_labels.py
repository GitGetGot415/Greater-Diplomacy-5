"""Country name labels are rendered only for countries placed on the map."""

import unittest
from types import SimpleNamespace
from unittest import mock

from tests import app_harness


def _blob(owner):
    return {"owner": owner, "cx": 0, "cy": 0, "length": 10, "thickness": 10, "spread": 1, "count": 5, "angle": 0}


class CountryNameLabelTests(unittest.TestCase):
    def setUp(self):
        app_harness.boot()
        import pygame
        from ui.rendering import country_names
        self.pygame = pygame
        self.country_names = country_names
        self.game = SimpleNamespace(
            show_country_names=True, tactical_mode=False, selection_mode=False, base_layer="POLITICAL",
            loop_map=False, map_w=100,
            nation_data={"OWNER": {"name": "Owner", "faction": "Pact"}, "PLAIN": {"name": "Plain"},
                         "CORE_ONLY": {"name": "Core Only"}, "UNPLACED": {"name": "Unplaced", "faction": "Pact"}},
            country_text_blobs=[_blob("OWNER"), _blob("PLAIN")], core_text_blobs=[_blob("CORE_ONLY")])
        # Every label lands off screen, so the test checks the cache without transforming text.
        patcher = mock.patch.object(country_names.queries, "world_to_screen", return_value=(-10000, 0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def draw(self):
        self.country_names.draw_country_names(self.game, self.pygame.Surface((10, 10)))

    def test_only_countries_with_a_landmass_or_core_get_labels(self):
        self.draw()
        self.assertEqual(set(self.game.country_name_surfs), {"OWNER", "PLAIN", "CORE_ONLY"})
        self.assertEqual(set(self.game.faction_name_surfs), {"OWNER"})

    def test_a_country_placed_later_gets_its_label_after_the_blobs_refresh(self):
        self.draw()
        # update_country_centers clears the cache whenever it replaces the blobs.
        self.country_names.clear_country_name_cache(self.game)
        self.game.country_text_blobs.append(_blob("UNPLACED"))
        self.draw()
        self.assertIn("UNPLACED", self.game.country_name_surfs)
        self.assertIn("UNPLACED", self.game.faction_name_surfs)

    def test_labels_wait_for_the_landmass_blobs(self):
        del self.game.country_text_blobs
        self.draw()
        self.assertFalse(hasattr(self.game, "country_name_surfs"))


if __name__ == "__main__":
    unittest.main()
