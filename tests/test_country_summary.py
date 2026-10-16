"""Country flag navigation, shared summary data, and inspection permissions."""

import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

import data.constants as c
from data import queries
from map_logic import politics
from map_logic.turn_processing import combat_rules
from screens.map_related_screens.country_summary import CountrySummaryScreen, open_country_summary
from tests.stub_map_screen import StubMapScreen
from ui import event_handler, modal_stack
from ui.bars import flag_renderer


def unit(owner, attack=80, kind="Summary fixture"):
    return {"owner": owner, "type": kind, "attack": attack, "defense": 0,
            "health": 500, "max_health": 1000, "speed": 1, "morale": 50}


def world():
    game = StubMapScreen(["A", "B", "C"])
    game.selected_province = None
    game.hide_top_info = game.hide_flag = game.selection_mode = False
    game.show_player_ready_screen = game.show_exit_confirmation = game.is_saving = False
    game.ai_is_thinking = game.viewing_ai_moves = False
    game.feedback_text = ""
    game.scenario_settings = {"fog_of_war": True}
    game.visible_provinces = {game.home_of("A")["id"], game.home_of("B")["id"]}
    for country, data in game.nation_data.items():
        data.update(name=f"Display {country}", research={}, manpower=200,
                    conscription_slider=0.25, mat_to_fuel_slider=0.1)
        game.home_of(country)["units"] = [unit(country)]
    for key, province in game.map_data.items():
        province["json_key"] = key
        province["terrain"] = "plains"
    return game


class CountrySummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def setUp(self):
        self.library = patch.object(queries, "get_unit_library", return_value={
            name: {"attack": 80, "defense": 0, "health": 1000,
                   "cost_manpower": 100, "cost_materials": 200, "cost_fuel": 10}
            for name in ("Summary fixture", "Submarine fixture", "Transport fixture")})
        self.library.start()
        self.addCleanup(self.library.stop)

    def test_own_summary_matches_shared_damage_and_economy_rules(self):
        game = world()
        game.nation_data["A"][politics.VALUE_KEY] = c.POLITICS_MAX
        game.nation_data["A"][politics.POLICY_KEY] = {
            "total_mobilisation": {"status": politics.POLICY_ACTIVE}}
        summary = queries.get_country_summary(game, "A")
        troops = game.home_of("A")["units"]
        expected_damage = sum(troop["attack"] * combat_rules.effective_damage_multiplier(
            troop, game.nation_data) for troop in troops)
        self.assertEqual(summary["name"], "Display A")
        self.assertTrue(summary["military"]["complete"])
        self.assertEqual(summary["military"]["damage_output"], expected_damage)
        self.assertEqual(summary["military"]["raw_damage_output"], combat_rules.volley(troops))
        self.assertAlmostEqual(summary["military"]["raw_damage_output"]
                               * summary["military"]["damage_multiplier"], expected_damage)
        self.assertEqual(summary["military"]["damage_multiplier"],
                         queries.get_country_damage_multiplier("A", game.nation_data))
        income, expenses, _breakdown = queries.get_economy_projections(
            "A", game.map_data, copy.deepcopy(game.nation_data))
        for row in summary["economy"]["resources"]:
            self.assertEqual(row["income"], income[row["resource"]])
            self.assertEqual(row["expenses"], expenses[row["resource"]])
            self.assertEqual(row["net"], row["income"] - row["expenses"])
        self.assertEqual(summary["politics"]["value"], c.POLITICS_MAX)
        self.assertEqual(summary["politics"]["research_multiplier"], politics.research_multiplier(game.nation_data, "A"))

    def test_foreign_totals_exclude_fogged_units_hidden_submarines_and_cargo(self):
        game = world()
        visible = game.home_of("B")["units"][0]
        plane = unit("B", kind="Transport fixture")
        plane["air_cargo"] = [unit("B", attack=999)]
        game.home_of("B")["units"].extend([unit("B", kind="Submarine fixture"), plane])
        hidden = game.add_province("B", units=[unit("B", attack=999)])
        self.assertNotIn(hidden["id"], game.visible_provinces)
        summary = queries.get_country_summary(game, "B")
        self.assertFalse(summary["military"]["complete"])
        self.assertEqual(summary["military"]["unit_count"], 2)
        self.assertEqual(summary["military"]["damage_output"],
                         combat_rules.volley([visible, plane], nation_data=game.nation_data))
        self.assertEqual(summary["military"]["raw_damage_output"], combat_rules.volley([visible, plane]))
        self.assertFalse(summary["economy"]["available"])
        self.assertEqual(summary["economy"]["resources"], [])
        self.assertNotIn("conscription", summary["economy"])
        self.assertNotIn("conversion", summary["economy"])

    def test_own_cargo_counts_without_revealing_foreign_cargo(self):
        game = world()
        game.home_of("A")["units"][0]["air_cargo"] = [unit("A")]
        self.assertEqual(queries.get_country_summary(game, "A")["military"]["unit_count"], 2)

    def test_politics_factions_and_subjects_use_existing_country_state(self):
        game = world()
        game.nation_data["A"].update(faction="Fixture Pact", is_faction_leader=True, puppets=["C"])
        game.nation_data["B"].update(faction="Fixture Pact")
        game.nation_data["C"].update(master="A")
        summary = queries.get_country_summary(game, "A")
        self.assertEqual(summary["diplomacy"]["faction_members"], ["A", "B"])
        self.assertEqual(summary["diplomacy"]["faction_leader"], "A")
        self.assertEqual(summary["diplomacy"]["puppets"], ["C"])
        screen = CountrySummaryScreen(game, "A")
        self.assertEqual("".join(text for text, _flag in screen._country_parts(["A", "B"])),
                         "Display A, Display B")
        self.assertEqual(queries.get_country_summary(game, "C")["diplomacy"]["master"], "A")

    def test_local_inspection_does_not_initialize_subject_economy_or_change_state(self):
        game = world()
        game.nation_data["C"].update(master="A", puppet_type=c.PUPPET_TYPE_INTEGRATED)
        before = copy.deepcopy((game.nation_data, game.map_data))
        queries.get_country_summary(game, "A")
        self.assertEqual((game.nation_data, game.map_data), before)

    def test_foreign_economy_access_depends_on_actual_mode_and_fog(self):
        game = world()
        self.assertFalse(queries.can_view_country_economy(game, "B"))
        game.scenario_settings["fog_of_war"] = False
        self.assertTrue(queries.can_view_country_economy(game, "B"))
        for mode in ("multiplayer_mode", "realtime_multiplayer"):
            with self.subTest(mode=mode):
                setattr(game, mode, True)
                self.assertFalse(queries.can_view_country_economy(game, "B"))
                self.assertTrue(queries.can_view_country_economy(game, "A"))
                setattr(game, mode, False)
        game.player_country = "Spectator"
        game.scenario_settings["fog_of_war"] = True
        self.assertTrue(queries.can_view_country_economy(game, "B"))
        self.assertTrue(queries.get_country_summary(game, "B")["military"]["complete"])
        game.player_country = c.TOURNAMENT_SPECTATOR
        self.assertFalse(queries.can_view_country_economy(game, "B"))

    def test_network_filtered_foreign_records_do_not_become_zero_economy_figures(self):
        game = world()
        game.home_of("A")["neighbors"] = [game.home_of("B")["id"]]
        snapshot = {"nation_data": game.nation_data,
                    "provinces": {province["json_key"]: province for province in game.map_data.values()}}
        filtered = queries.player_snapshot_projection(game, snapshot, "A")
        game.nation_data = filtered["nation_data"]
        game.realtime_multiplayer = True
        self.assertNotIn("materials", game.nation_data["B"])
        with patch.object(queries, "get_economy_projections", side_effect=AssertionError("Private economy queried")):
            summary = queries.get_country_summary(game, "B")
        self.assertFalse(summary["economy"]["available"])
        self.assertEqual(summary["economy"]["resources"], [])
        self.assertNotIn("conscription", summary["economy"])
        self.assertNotIn("conversion", summary["economy"])

    def test_faction_members_and_direct_subjects_share_economies_in_each_mode(self):
        for mode in ("local", "multiplayer_mode", "realtime_multiplayer"):
            for relationship in ("faction", "puppet", "overlord"):
                with self.subTest(mode=mode, relationship=relationship):
                    game = world()
                    if mode != "local":
                        setattr(game, mode, True)
                    if relationship == "faction":
                        game.nation_data["A"]["faction"] = game.nation_data["B"]["faction"] = "Fixture Pact"
                    else:
                        master, subject = ("A", "B") if relationship == "puppet" else ("B", "A")
                        game.nation_data[subject]["master"] = master
                        game.nation_data[master]["puppets"] = [subject]
                    for viewer, target in (("A", "B"), ("B", "A")):
                        game.player_country = viewer
                        self.assertTrue(queries.can_view_country_economy(game, target))
                        self.assertFalse(queries.can_view_country_economy(game, "C"))
                        if mode == "realtime_multiplayer":
                            game.country_economy_summaries = queries.get_shared_country_economy_summaries(
                                viewer, game.map_data, game.nation_data)
                        economy = queries.get_country_summary(game, target)["economy"]
                        self.assertTrue(economy["available"])
                        self.assertTrue(economy["resources"])
                        self.assertEqual(economy["conscription"], game.nation_data[target]["conscription_slider"])
                        self.assertEqual(economy["conversion"], game.nation_data[target]["mat_to_fuel_slider"])

    def test_shared_network_totals_match_host_without_revealing_private_source_data(self):
        game = world()
        game.nation_data["A"]["faction"] = game.nation_data["B"]["faction"] = "Fixture Pact"
        hidden = game.add_province("B", units=[unit("B")])
        hidden.update(json_key="hidden", terrain="plains")
        game.nation_data["B"].update(inbox=[{"secret": True}], research_queue=[{"secret": True}])
        expected = queries.get_country_summary(game, "B")["economy"]
        before = copy.deepcopy((game.map_data, game.nation_data))
        snapshot = {"nation_data": game.nation_data,
                    "provinces": {province["json_key"]: province for province in game.map_data.values()}}
        filtered = queries.player_snapshot_projection(game, snapshot, "A")
        self.assertEqual((game.map_data, game.nation_data), before)
        self.assertEqual(set(filtered["country_economy_summaries"]), {"B"})
        for field in ("research", "research_queue", "inbox", "materials", "manpower", "fuel"):
            self.assertNotIn(field, filtered["nation_data"]["B"])
        game.realtime_multiplayer = True
        game.nation_data = filtered["nation_data"]
        game.map_data = filtered["provinces"]
        game.country_economy_summaries = filtered["country_economy_summaries"]
        with patch.object(queries, "calculate_all_economies", side_effect=AssertionError("Client recalculated totals")):
            self.assertEqual(queries.get_country_summary(game, "B")["economy"], expected)
        game.nation_data["B"]["faction"] = ""
        self.assertFalse(queries.get_country_summary(game, "B")["economy"]["available"])

    def test_shared_network_economy_stays_private_without_authoritative_totals(self):
        game = world()
        game.realtime_multiplayer = True
        game.nation_data["A"]["faction"] = game.nation_data["B"]["faction"] = "Fixture Pact"
        with patch.object(queries, "get_economy_projections", side_effect=AssertionError("Filtered economy queried")):
            summary = queries.get_country_summary(game, "B")
        self.assertEqual(summary["economy"], {"available": False, "resources": []})

    def test_tournament_projection_keeps_shared_totals_before_removing_private_plans(self):
        from data.io import multiplayer_io
        game = world()
        game.nation_data["B"].update(master="A", puppet_type=c.PUPPET_TYPE_INTEGRATED)
        game.nation_data["A"]["puppets"] = ["B"]
        expected = queries.get_country_summary(game, "B")["economy"]
        multiplayer_io.strip_sensitive_data_for_player(game, "A")
        with patch.object(queries, "get_economy_projections", side_effect=AssertionError("Stripped economy queried")):
            self.assertEqual(queries.get_country_summary(game, "B")["economy"], expected)
        multiplayer_io.strip_sensitive_data_for_tournament_spectator(game)
        self.assertEqual(game.country_economy_summaries, {})
        self.assertFalse(queries.get_country_summary(game, "B")["economy"]["available"])

    def test_legacy_country_uses_existing_slider_defaults_without_writing_them(self):
        game = world()
        game.nation_data["A"].pop("conscription_slider")
        game.nation_data["A"].pop("mat_to_fuel_slider")
        before = copy.deepcopy(game.nation_data)
        summary = queries.get_country_summary(game, "A")
        self.assertEqual((summary["economy"]["conscription"], summary["economy"]["conversion"]), (1.0, 0.0))
        self.assertEqual(game.nation_data, before)

    def test_flag_selects_own_country_foreign_owner_and_own_fallback_on_water(self):
        game = world()
        self.assertEqual(flag_renderer.summary_country(game), "A")
        game.selected_province = game.home_of("B")
        self.assertEqual(flag_renderer.summary_country(game), "B")
        game.selected_province = {"owner": "Ocean"}
        self.assertEqual(flag_renderer.summary_country(game), "A")

    def test_hidden_flags_and_blocked_map_phases_have_no_summary_hitbox(self):
        game = world()
        for field in ("hide_flag", "hide_top_info", "selection_mode", "show_player_ready_screen",
                      "show_exit_confirmation", "is_saving", "ai_is_thinking", "viewing_ai_moves"):
            with self.subTest(field=field):
                setattr(game, field, True)
                self.assertIsNone(flag_renderer.flag_button_rect(game))
                setattr(game, field, False)
        game.player_country = "Spectator"
        self.assertIsNone(flag_renderer.flag_button_rect(game))
        game.selected_province = game.home_of("B")
        self.assertIsNotNone(flag_renderer.flag_button_rect(game))

    def test_flag_click_opens_the_displayed_country_without_selecting_map_tiles(self):
        game = world()
        for selected, expected in ((None, "A"), (game.home_of("B"), "B")):
            with self.subTest(country=expected):
                game.selected_province = selected
                event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=flag_renderer.FLAG_RECT.center)
                with patch("ui.diplomatic_popups.handle_events", return_value=False), \
                        patch("screens.map_related_screens.country_summary.open_country_summary") as open_summary, \
                        patch.object(event_handler, "_select_map_province", side_effect=AssertionError("Click reached map")):
                    event_handler.handle_map_events(game, event)
                open_summary.assert_called_once_with(game, expected)
                self.assertIs(game.selected_province, selected)
                self.assertTrue(event_handler.map_ui_bar_at_position(game, event.pos))

    def test_view_remains_read_only_for_own_foreign_and_tactical_countries(self):
        for country, tactical in (("A", False), ("B", False), ("A", True)):
            with self.subTest(country=country, tactical=tactical):
                game = world()
                game.tactical_mode = tactical
                game.player_unit = game.home_of("A")["units"][0] if tactical else None
                before = copy.deepcopy((game.nation_data, game.map_data))
                screen = CountrySummaryScreen(game, country)
                for element in screen.elements:
                    element.callback()
                self.assertTrue(screen.done)
                self.assertEqual((game.nation_data, game.map_data), before)

    def test_frame_drawing_and_scrolling_use_cached_summary_data(self):
        game = world()
        screen = CountrySummaryScreen(game, "A")
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        with patch.object(queries, "get_country_summary", side_effect=AssertionError("Frame summary")), \
                patch.object(queries, "get_economy_projections", side_effect=AssertionError("Frame economy")), \
                patch("ui.flag_icons.flag_surface", side_effect=AssertionError("Frame flags")), \
                patch("screens.map_related_screens.country_summary.render_inline_text",
                      side_effect=AssertionError("Frame text layout")), \
                patch.object(combat_rules, "volley", side_effect=AssertionError("Frame damage")):
            screen.draw(surface)
            screen.additional_events(pygame.event.Event(pygame.MOUSEWHEEL, y=-1))
            screen.draw(surface)

    def test_long_relationship_lists_scroll_and_return_to_the_top(self):
        game = world()
        game.nation_data["A"]["puppets"] = [f"Fixture subject {index}" for index in range(150)]
        screen = CountrySummaryScreen(game, "A")
        screen.additional_events(pygame.event.Event(pygame.MOUSEWHEEL, y=-1))
        self.assertLess(screen.scroll_y, 0)
        initial_scroll = screen.scroll_y
        screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEDOWN))
        self.assertGreaterEqual(screen.scroll_y, screen.max_scroll)
        screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEUP))
        self.assertEqual(screen.scroll_y, initial_scroll)
        screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_PAGEUP))
        self.assertEqual(screen.scroll_y, 0)

    def test_modal_open_and_back_preserve_country_and_tile_selection(self):
        game = world()
        selected = game.home_of("B")
        game.selected_province = selected
        with patch.object(modal_stack, "_stack", []):
            open_country_summary(game, "B")
            modal = modal_stack.active()
            self.assertIsInstance(modal.screen, CountrySummaryScreen)
            self.assertEqual(modal.screen.country_id, "B")
            modal.screen.elements[0].callback()
            modal.update()
            self.assertTrue(modal_stack.is_empty())
        self.assertIs(game.selected_province, selected)
        self.assertEqual(game.player_country, "A")


if __name__ == "__main__":
    unittest.main()
