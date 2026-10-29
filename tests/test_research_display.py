"""Check presentation data loading, override resolution, and research input."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data import research_display


def display_config():
    """Create artificial settings independent of bundled presentation values."""
    return {
        "defaults": {"button_size": "base", "icon_scale": 1.5, "large_icon_scale": 3},
        "button_sizes": {"base": [80, 50], "category": [120, 60]},
        "categories": {"INDUSTRY": {"button_size": "category", "icon_scale": 2}},
        "technologies": {"sample": {"icon_scale": 2.5, "levels": {
            "2": {"button_size": [280, 92], "icon_scale": 3.5}}}},
        "layout": {"row_y": [200, 270, 340, 410, 480, 550], "default_row_y": 350,
                   "row_center_offset": 30, "pixels_per_year": 40, "modal_icon_box": 100},
        "styles": {"test": {"button_scale": 1.5, "icon_scales": {
            "generic.png": 0.5, "specific.png": 0.25},
            "button_scale_overrides": {"Example": {"width": 3, "height": 2}}}},
    }


class DisplayDataTests(unittest.TestCase):
    def test_settings_follow_precedence_without_mutating_cached_data(self):
        config = display_config()
        original = copy.deepcopy(config)
        with patch.object(research_display, "get_config", return_value=config):
            self.assertEqual(research_display.node_settings("unknown", "unknown", 1)["icon_scale"], 1.5)
            self.assertEqual(research_display.node_settings(
                "unknown", "unknown", 1, large_icon=True)["icon_scale"], 3)
            category = research_display.node_settings("unknown", "INDUSTRY", 1, large_icon=True)
            self.assertEqual(category["button_size"], "category")
            self.assertEqual(category["icon_scale"], 2)
            self.assertEqual(research_display.node_settings("sample", "INDUSTRY", 1)["icon_scale"], 2.5)
            level = research_display.node_settings("sample", "INDUSTRY", 2)
            self.assertEqual(level["button_size"], [280, 92])
            self.assertEqual(level["icon_scale"], 3.5)
            self.assertEqual(research_display.node_settings("sample", "INDUSTRY", 3)["icon_scale"], 2.5)
        self.assertEqual(config, original)

    def test_loader_caches_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "research_display.json")
            config = display_config()
            path.write_text(json.dumps(config), encoding="utf-8")
            loaded = research_display.get_config(str(path))
            path.write_text("invalid JSON", encoding="utf-8")
            self.assertIs(research_display.get_config(str(path)), loaded)
            self.assertEqual(loaded, config)

    def test_invalid_settings_identify_the_file(self):
        for value in (0, -1, True, float("inf"), "large"):
            config = display_config()
            config["defaults"]["icon_scale"] = value
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory, "research_display.json")
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "research_display.json.*icon_scale"):
                    research_display.get_config(str(path))

    def test_unknown_presets_and_invalid_pixel_pairs_are_rejected(self):
        for value in ("missing", [0, 30], [20], [20, 30.5], [True, 30]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                research_display.button_dimensions(value, display_config())

    def test_missing_or_malformed_files_explain_how_to_fix_them(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "research_display.json")
            with self.assertRaisesRegex(ValueError, "Correct the research display file"):
                research_display.get_config(str(path))
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Correct the research display file"):
                research_display.get_config(str(path))


class StyleCompatibilityTests(unittest.TestCase):
    def setUp(self):
        # Import after the headless application harness has configured pygame.
        from tests import app_harness
        app_harness.boot()
        from ui.rendering import symbol_loader
        self.symbols = symbol_loader
        self.config = display_config()
        self.enterContext(patch.object(research_display, "get_config", return_value=self.config))
        self.enterContext(patch.object(self.symbols, "STYLE_RESEARCH_DISPLAY", {}))

    def test_custom_style_files_override_matching_entries_only(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "research_scale.json").write_text(json.dumps({
                "button_scale": 2, "icon_scales": {"generic.png": 0.75}}), encoding="utf-8")
            self.symbols._load_research_display("test", directory)
        settings = self.symbols.STYLE_RESEARCH_DISPLAY["test"]
        self.assertEqual(settings["button_scale"], 2)
        self.assertEqual(settings["icon_scales"], {"generic.png": 0.75, "specific.png": 0.25})
        self.assertEqual(settings["button_scale_overrides"],
                         self.config["styles"]["test"]["button_scale_overrides"])
        self.assertEqual(self.config, display_config())

    def test_image_adjustments_follow_country_variant_and_classic_fallback(self):
        from data import constants as c
        from data import queries
        import pygame
        image = pygame.Surface((10, 10))
        variants = [{"countries": frozenset({"A"}), "surface": image, "filename": "specific.png"}]
        with tempfile.TemporaryDirectory() as directory:
            self.symbols._load_research_display("test", directory)
        with patch.object(c, "UNIT_ART_STYLE", "test"), \
                patch.object(self.symbols, "STYLE_SYMBOLS", {"test": {"Example I": variants}}), \
                patch.object(self.symbols, "STYLE_FILENAME_ART", {}), \
                patch.object(self.symbols, "RESOLVED_NAMES", {}), \
                patch.object(self.symbols, "SYMBOLS", {"Example I": image}), \
                patch.object(queries, "get_unit_library", return_value={}):
            self.assertEqual(self.symbols.get_research_scale("Example I", country="A"), 0.25)
            self.assertEqual(self.symbols.get_research_button_scale_overrides(
                "Example I", country="A"), (3, 2))
            self.assertEqual(self.symbols.get_research_scale("Example I", country="B"), 1)
            self.assertEqual(self.symbols.get_research_button_scale_overrides(
                "Example I", country="B"), (1, 1))
            self.assertEqual(self.symbols.get_research_button_scale(), 1.5)

    def test_classic_patterns_apply_to_resolved_art_and_style_fallbacks(self):
        from data import queries
        import pygame
        image = pygame.Surface((10, 10))
        self.config["styles"]["classic"] = {"icon_scales": {
            "Example*.png": 3, "Example I.png": 4}}
        with tempfile.TemporaryDirectory() as directory:
            self.symbols._load_research_display("classic", directory)
            self.symbols._load_research_display("test", directory)
        variants = [{"countries": frozenset({"A"}), "surface": image, "filename": "specific.png"}]
        with patch.object(self.symbols, "STYLE_SYMBOLS", {"test": {"Example I": variants}}), \
                patch.object(self.symbols, "STYLE_FILENAME_ART", {}), \
                patch.object(self.symbols, "RESOLVED_NAMES", {}), \
                patch.object(self.symbols, "SYMBOLS", {
                    "Example I": image, "Example II": image, "Unlisted": image}), \
                patch.object(queries, "get_unit_library", return_value={}):
            self.assertEqual(self.symbols.get_research_scale("Example I", "classic"), 4)
            self.assertEqual(self.symbols.get_research_scale("Example II", "classic"), 3)
            self.assertEqual(self.symbols.get_research_scale("Unlisted", "classic"), 1)
            self.assertEqual(self.symbols.get_research_scale("Example I", "test", "A"), 0.25)
            self.assertEqual(self.symbols.get_research_scale("Example I", "test", "B"), 4)


class ResearchInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        from data import constants as c, queries
        from screens.game.research import Research_Screen
        from ui.rendering import symbol_loader
        nation_data = copy.deepcopy(self.map.nation_data)
        nation_data[self.map.player_country].update(research={"sample": 1}, research_queue=[])
        self.enterContext(patch.object(self.map, "nation_data", nation_data))
        self.enterContext(patch.object(self.map, "tactical_mode", False))
        self.enterContext(patch.object(self.map, "viewing_research_country", "", create=True))
        self.enterContext(patch.object(c, "UNIT_ART_STYLE", "classic"))
        tree = {"sample": {"display_name": "Renamed technology", "category": "INDUSTRY",
                           "max_lvl": 2, "years": [self.map.time_manager.year - 10,
                                                    self.map.time_manager.year],
                           "cost": 100, "req": {}}}
        self.enterContext(patch.object(queries, "get_tech_tree", return_value=tree))
        self.enterContext(patch.object(research_display, "get_config", return_value=display_config()))
        self.enterContext(patch.object(symbol_loader, "get_symbol", return_value=None))
        self.screen = Research_Screen()
        self.screen.start_research(self.map)

    def click_second_level(self):
        import pygame
        from ui.widgets import ui_elements
        node = next(element for element in self.screen.elements
                    if getattr(element, "is_tech_node", False) and element.text.endswith(" II"))
        # This point is outside the original small button but inside the configured button.
        point = (node.rect.right - 2, node.rect.centery)
        with patch.object(pygame.mouse, "get_pos", return_value=point), \
                patch.object(ui_elements, "play_ui_sound"):
            for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                node.handle_event(pygame.event.Event(event_type, button=1, pos=point))
        self.assertEqual(self.screen.active_modal["tech_key"], "sample")
        self.assertEqual(self.screen.active_modal["level"], 2)

    def test_click_in_resized_button_opens_the_correct_level(self):
        self.click_second_level()

    def test_rebuild_scans_units_once_for_all_nodes(self):
        from data import queries
        with patch.object(queries, "get_unit_unlock_index", wraps=queries.get_unit_unlock_index) as build:
            self.screen.refresh_ui()
        self.assertEqual(build.call_count, 1)

    def test_prepared_unit_index_matches_the_default_lookup(self):
        from data import queries
        index = queries.get_unit_unlock_index(self.map)
        for key, data in queries.get_tech_tree(self.map).items():
            for level in range(1, data["max_lvl"] + 1):
                self.assertEqual(
                    queries.get_tech_unlocks(key, level, context=self.map, unit_unlocks=index),
                    queries.get_tech_unlocks(key, level, context=self.map))

    def test_frames_reuse_prepared_settings_and_scrolling_keeps_input_working(self):
        import pygame
        with patch.object(research_display, "node_settings", side_effect=AssertionError("frame settings")):
            self.screen.additional_events(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1))
            self.screen.update()
            self.screen.draw(self.surface)
        self.assertLess(self.screen.target_scroll_x, 0)
        self.click_second_level()
