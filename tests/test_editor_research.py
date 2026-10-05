"""Editor research uses the player timeline and shared prerequisite rules."""
import copy
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

import data.constants as c
from data import queries
from screens.editor_screens import research_screens
from screens.map_related_screens.research import Research_Screen, CATEGORY_LABELS
from tests import app_harness
from tests.test_map_save_format import sample_map_screen


def tech_tree():
    """Create artificial levels, dates, and nested prerequisite branches."""
    requirements = {
        "root": (4, {}), "branch": (3, {"root": 2}), "tip": (2, {"branch": 2}),
        "left": (3, {"root": 1}), "right": (3, {"root": 1}),
        "choice": (1, {"OR": [{"left": 2}, {"right": 1}]}),
        "both": (2, {"AND": [{"branch": 1}, {"left": 1}]}),
        "match": (4, {"root": "MATCH_LEVEL"}),
        "offset": (3, {"root": "MATCH_LEVEL+1"}),
        "lower": (4, {"root": "MATCH_LEVEL-1"}),
    }
    categories = ("INFANTRY", "TANKS", "NAVY", "AEROSPACE", "INDUSTRY")
    return {key: {"category": categories[index % len(categories)], "display_name": key.title(),
                  "max_lvl": levels, "cost": 100, "req": req,
                  "years": [c.START_YEAR + index * 6 + level * 2 for level in range(levels)]}
            for index, (key, (levels, req)) in enumerate(requirements.items())}


class PrerequisiteTests(unittest.TestCase):
    def setUp(self):
        self.tree = tech_tree()

    def edit(self, research, key, level, researched=True):
        return queries.edited_research_levels(research, key, level, researched, self.tree)

    def test_grant_adds_transitive_prerequisites_and_previous_levels(self):
        before = {"legacy_tech": 7}
        after = self.edit(before, "tip", 2)
        self.assertEqual(after, {"legacy_tech": 7, "root": 2, "branch": 2, "tip": 2})
        self.assertEqual(before, {"legacy_tech": 7})
        for key, level in after.items():
            if key in self.tree:
                for target in range(1, level + 1):
                    self.assertTrue(queries.check_tech_requirements(after, self.tree[key]["req"], target))

    def test_or_grants_only_the_smallest_missing_branch(self):
        self.assertEqual(self.edit({}, "choice", 1), {"root": 1, "right": 1, "choice": 1})
        self.assertEqual(self.edit({"root": 1, "left": 2}, "choice", 1),
                         {"root": 1, "left": 2, "choice": 1})

    def test_grant_repairs_missing_prerequisites_of_an_existing_required_tech(self):
        self.assertEqual(self.edit({"branch": 2}, "tip", 1),
                         {"root": 2, "branch": 2, "tip": 1})

    def test_and_and_nested_or_keep_all_required_branches(self):
        self.tree["both"]["req"] = {"AND": [{"branch": 1}, {"OR": [{"left": 2}, {"right": 1}]}]}
        after = self.edit({}, "both", 1)
        self.assertEqual(after, {"root": 2, "branch": 1, "right": 1, "both": 1})

    def test_dynamic_requirements_apply_to_each_granted_level(self):
        for key, level, root_level in (("match", 4, 4), ("offset", 3, 4), ("lower", 4, 3)):
            with self.subTest(key=key):
                after = self.edit({}, key, level)
                self.assertEqual(after["root"], root_level)
                self.assertEqual(after[key], level)

    def test_remove_truncates_family_and_transitive_dependents(self):
        before = {"root": 4, "branch": 3, "tip": 2, "match": 4, "offset": 3,
                  "lower": 4, "left": 1, "right": 1, "choice": 1, "legacy_tech": 7}
        after = self.edit(before, "root", 2, False)
        self.assertEqual(after, {"root": 1, "branch": 0, "tip": 0, "match": 1, "offset": 0,
                                 "lower": 2, "left": 1, "right": 1, "choice": 1, "legacy_tech": 7})
        self.assertEqual(before["root"], 4)

    def test_or_dependency_survives_until_its_last_satisfied_branch_is_removed(self):
        before = {"root": 2, "left": 2, "right": 1, "choice": 1}
        after = self.edit(before, "left", 1, False)
        self.assertEqual(after["choice"], 1)
        self.assertEqual(self.edit(after, "right", 1, False)["choice"], 0)

    def test_unrelated_inconsistent_legacy_research_is_preserved(self):
        self.assertEqual(self.edit({"root": 2, "tip": 2}, "root", 2, False)["tip"], 2)

    def test_unavailable_branch_is_skipped_and_errors_leave_input_unchanged(self):
        self.tree["choice"]["req"] = {"OR": [{"missing": 1}, {"right": 1}]}
        self.assertEqual(self.edit({}, "choice", 1)["right"], 1)
        self.tree["root"]["req"] = {"branch": 1}
        before = {"legacy_tech": 7}
        with self.assertRaises(ValueError):
            self.edit(before, "branch", 1)
        self.assertEqual(before, {"legacy_tech": 7})

    def test_invalid_targets_are_rejected(self):
        for key, level in (("missing", 1), ("root", 0), ("root", 5), ("root", True), ("root", "1")):
            with self.subTest(key=key, level=level), self.assertRaises(ValueError):
                self.edit({}, key, level)


class EditorResearchStateTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(queries, "get_tech_tree", return_value=tech_tree()))
        self.game = SimpleNamespace(is_editor=True, tactical_mode=False, multiplayer_mode=False,
                                    realtime_multiplayer=False,
                                    map_data={1: {"owner": "A"}, 2: {"owner": "B"}},
                                    nation_data={"A": {"research": {}}, "B": {"research": {"root": 1}}},
                                    default_research={"root": 1})

    def test_click_toggles_only_the_selected_country_and_keeps_dictionary_references(self):
        country = self.game.nation_data["A"]
        research = country["research"]
        queries.toggle_starting_research(self.game, "A", "tip", 2)
        self.assertIs(country["research"], research)
        self.assertEqual(research, {"root": 2, "branch": 2, "tip": 2})
        queries.toggle_starting_research(self.game, "A", "branch", 1)
        self.assertEqual(research, {"root": 2, "branch": 0, "tip": 0})
        self.assertEqual(self.game.nation_data["B"], {"research": {"root": 1}})
        self.assertEqual(self.game.default_research, {"root": 1})

    def test_changed_and_invalid_projects_and_paused_progress_are_cleared(self):
        country = self.game.nation_data["A"]
        country.update(research={"root": 2, "branch": 1}, research_queue=[
            {"tech_name": "root", "points_remaining": 20},
            {"tech_name": "tip", "points_remaining": 20},
            {"tech_name": "right", "points_remaining": 20}],
            research_progress={"branch": 20, "tip": 30, "right": 40}, current_research="tip")
        queue = country["research_queue"]
        queries.toggle_starting_research(self.game, "A", "root", 2)
        self.assertIs(country["research_queue"], queue)
        self.assertEqual(queue, [{"tech_name": "right", "points_remaining": 20}])
        self.assertEqual(country["research_progress"], {"right": 40})
        self.assertIsNone(country["current_research"])

    def test_invalid_editor_permissions_and_removed_countries_cannot_change_research(self):
        for flags in ({"is_editor": False}, {"tactical_mode": True}, {"multiplayer_mode": True},
                      {"realtime_multiplayer": True}):
            before = copy.deepcopy(self.game.nation_data)
            with self.subTest(flags=flags), ExitStack() as stack:
                for key, value in flags.items():
                    stack.enter_context(patch.object(self.game, key, value))
                with self.assertRaises(ValueError):
                    queries.toggle_starting_research(self.game, "A", "root", 1)
            self.assertEqual(self.game.nation_data, before)
        self.game.map_data[1]["owner"] = "B"
        with self.assertRaises(ValueError):
            queries.toggle_starting_research(self.game, "A", "root", 1)

    def test_malformed_clicks_do_not_change_country_state(self):
        before = copy.deepcopy(self.game.nation_data)
        for key, level in (("missing", 1), ("root", "1"), ("root", True), ("root", 5)):
            with self.subTest(key=key, level=level), self.assertRaises(ValueError):
                queries.toggle_starting_research(self.game, "A", key, level)
            self.assertEqual(self.game.nation_data, before)

    def test_edited_research_uses_existing_save_schema_and_country_loader(self):
        saved_map = sample_map_screen()
        saved_map.is_editor = True
        queries.toggle_starting_research(saved_map, "Avaria", "tip", 2)
        saved = json.loads(json.dumps(queries.build_save_dict(saved_map)))
        loaded = queries.merge_country_templates(saved["nation_data"])
        self.assertEqual(loaded["Avaria"]["research"], saved_map.nation_data["Avaria"]["research"])
        self.assertEqual(saved["default_research"], saved_map.default_research)


class EditorResearchTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        self.tree = tech_tree()
        self.enterContext(patch.object(queries, "get_tech_tree", return_value=self.tree))
        self.enterContext(patch.object(self.map, "is_editor", True))
        self.enterContext(patch.object(self.map, "tactical_mode", False))
        self.enterContext(patch.object(self.map, "realtime_multiplayer", False, create=True))
        self.enterContext(patch.object(self.map, "multiplayer_mode", False, create=True))
        self.enterContext(patch.object(self.map, "nation_data", copy.deepcopy(self.map.nation_data)))
        self.enterContext(patch.object(self.map, "default_research", copy.deepcopy(self.map.default_research)))
        self.country = next(iter(queries.get_living_nations(self.map.map_data)))
        self.map.nation_data[self.country].update(research={}, research_queue=[], research_progress={})
        self.enterContext(patch.object(self.map, "show_feedback", Mock()))
        self.screen = Research_Screen()
        self.screen.start_research(self.map, editor_country=self.country)

    def node(self, key, level):
        self.screen.set_category(self.tree[key]["category"])
        target = next(node for node in self.screen.nodes[self.screen.current_category]
                      if node["key"] == key and node["lvl"] == level)
        x = self.screen.year_to_x(target["year"], include_scroll=False)
        return next(button for button in self.screen.elements if getattr(button, "is_tech_node", False)
                    and button.base_x + button.rect.width / 2 == x)

    def test_country_list_opens_the_shared_tree_and_refreshes_after_closing(self):
        editor = research_screens.Research_List_Screen(self.map)
        with patch.object(research_screens, "_run_pygame_sub_screen") as launch:
            editor.edit_country(self.country)
        opened = launch.call_args.args[1]
        self.assertIsInstance(opened, Research_Screen)
        self.assertEqual(opened.subject, self.country)
        self.assertTrue(opened.editing_starting_research)
        self.assertEqual(launch.call_args.kwargs["on_done"], editor.refresh_ui)

    def test_node_click_grants_locked_levels_and_clicking_completed_level_removes_them(self):
        self.node("tip", 2).callback()
        research = self.map.nation_data[self.country]["research"]
        self.assertEqual(research, {"root": 2, "branch": 2, "tip": 2})
        self.assertIsNone(self.screen.active_modal)
        self.assertEqual(self.node("branch", 1).color, c.UI_COLORS["green"][0])
        self.node("branch", 1).callback()
        self.assertEqual(research, {"root": 2, "branch": 0, "tip": 0})

    def test_mouse_click_on_a_locked_visible_node_applies_the_editor_rule(self):
        button = self.node("tip", 2)
        self.screen.scroll_x = self.screen.target_scroll_x = c.SCREEN_WIDTH // 2 - button.rect.centerx
        self.screen.enforce_scroll_bounds()
        self.screen._sync_tech_node_positions()
        self.assertTrue(pygame.Rect(0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT).contains(button.rect))
        with patch.object(pygame.mouse, "get_pos", return_value=button.rect.center):
            self.screen.handle_events([pygame.event.Event(event_type, button=1, pos=button.rect.center)
                                       for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)])
        self.assertEqual(self.map.nation_data[self.country]["research"], {"root": 2, "branch": 2, "tip": 2})

    def test_stale_editor_callback_rechecks_permissions(self):
        button = self.node("root", 1)
        self.map.is_editor = False
        button.callback()
        self.assertEqual(self.map.nation_data[self.country]["research"], {})
        self.screen.start_or_resume_research("root")
        self.assertEqual(self.map.nation_data[self.country]["research_queue"], [])

    def test_completed_overview_clicks_toggle_the_displayed_level(self):
        self.node("root", 2).callback()
        self.screen.set_category("COMPLETED")
        row = next(button for button in self.screen.elements
                   if getattr(button, "editor_tech_key", None) == "root")
        row.callback()
        self.assertEqual(self.map.nation_data[self.country]["research"]["root"], 1)
        self.assertEqual(self.screen.current_category, "COMPLETED")

    def test_map_default_colors_apply_per_level_and_follow_immediate_edits(self):
        self.map.default_research = {"root": 2, "branch": 1}
        self.screen.refresh_ui()
        self.assertEqual(self.node("root", 1).color, c.UI_COLORS["purple"][0])
        self.assertEqual(self.node("root", 2).color, c.UI_COLORS["purple"][0])
        self.assertEqual(self.node("root", 3).color, c.UI_COLORS["grey"][0])
        self.node("root", 2).callback()
        self.assertEqual(self.node("root", 1).color, c.UI_COLORS["pink"][0])
        self.assertEqual(self.node("root", 2).color, c.UI_COLORS["pink"][0])
        self.assertEqual(self.node("root", 3).color, c.UI_COLORS["blue"][0])
        self.node("root", 1).callback()
        self.assertEqual(self.node("root", 2).color, c.UI_COLORS["purple"][0])
        self.assertEqual(self.map.default_research, {"root": 2, "branch": 1})
        self.screen.set_category("COMPLETED")
        row = next(button for button in self.screen.elements if getattr(button, "editor_tech_key", None) == "root")
        self.assertEqual(row.color, c.UI_COLORS["purple"][0])
        self.screen.toggle_editor_tech("root", 2)
        row = next(button for button in self.screen.elements if getattr(button, "editor_tech_key", None) == "root")
        self.assertEqual(row.color, c.UI_COLORS["pink"][0])

    def test_map_default_colors_are_absent_in_player_and_spectator_trees(self):
        self.map.default_research = {"root": 2}
        self.map.nation_data[self.country]["research"] = {"root": 1}
        for player, mode in ((self.country, "VIEW"), ("Spectator", "VIEW"), ("Spectator", "EDIT")):
            with self.subTest(player=player, mode=mode), ExitStack() as stack:
                stack.enter_context(patch.object(self.map, "is_editor", False))
                stack.enter_context(patch.object(self.map, "player_country", player))
                stack.enter_context(patch.object(self.map, "viewing_research_country", self.country, create=True))
                stack.enter_context(patch.object(self.map, "viewing_research_mode", mode, create=True))
                self.screen.start_research(self.map)
                self.assertEqual(self.node("root", 1).color, c.UI_COLORS["green"][0])
                self.assertEqual(self.node("root", 2).color, c.UI_COLORS["blue"][0])

    def test_spectator_edit_uses_shared_prerequisites_and_dependent_removal(self):
        with patch.object(self.map, "is_editor", False), patch.object(self.map, "player_country", "Spectator"), \
                patch.object(self.map, "viewing_research_country", self.country, create=True), \
                patch.object(self.map, "viewing_research_mode", "EDIT", create=True):
            self.screen.start_research(self.map)
            self.node("tip", 2).callback()
            self.assertEqual(self.screen.subject_data["research"], {"root": 2, "branch": 2, "tip": 2})
            self.node("branch", 1).callback()
            self.assertEqual(self.screen.subject_data["research"], {"root": 2, "branch": 0, "tip": 0})

    def test_reopening_for_an_ordinary_player_clears_editor_mode(self):
        self.map.is_editor = False
        self.enterContext(patch.object(self.map, "viewing_research_country", "", create=True))
        self.screen.start_research(self.map)
        self.assertFalse(self.screen.editing_starting_research)
        self.assertEqual(self.screen.subject, self.map.player_country)

    def test_tabs_timeline_scrollbar_and_editor_help_fit_and_draw_from_cache(self):
        for size in ((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), (1280, 720)):
            with self.subTest(size=size), patch.object(c, "SCREEN_WIDTH", size[0]), patch.object(c, "SCREEN_HEIGHT", size[1]):
                self.screen.refresh_ui()
                bounds = pygame.Rect((0, 0), size)
                labels = [CATEGORY_LABELS.get(category, category) for category in self.screen.categories]
                tabs = [button for button in self.screen.elements if getattr(button, "text", None) in labels]
                self.assertEqual(len(tabs), len(labels))
                for button in tabs:
                    self.assertTrue(bounds.contains(button.rect))
                for first, second in zip(tabs, tabs[1:]):
                    self.assertLessEqual(first.rect.right, second.rect.left)
                self.assertTrue(bounds.contains(self.screen.hud_slots_rect()))
                surface = pygame.Surface(size)
                with patch.object(queries, "walk_tech_requirements", side_effect=AssertionError("frame prerequisites")), \
                        patch.object(queries, "check_tech_requirements", side_effect=AssertionError("frame legality")), \
                        patch.object(queries, "get_living_nations", side_effect=AssertionError("frame country scan")):
                    self.screen.update()
                    self.screen.draw(surface)
                self.assertTrue(bounds.contains(self.screen.hscroll_track_rect))
                before = self.screen.target_scroll_x
                self.screen.additional_events(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1))
                self.assertNotEqual(self.screen.target_scroll_x, before)
        self.screen.set_category("COMPLETED")
        self.screen.draw(self.surface)
        self.assertTrue(self.screen.completed_text_surfaces)


if __name__ == "__main__":
    unittest.main()
