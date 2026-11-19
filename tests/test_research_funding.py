"""Research funding spends surplus income and awards unmodified progress."""

import asyncio
import json
import unittest
from unittest.mock import Mock, patch

import data.constants as c
from data import queries
from data.map import load_map
from data.state_access import BackendState
from map_logic import politics
from map_logic.ai import ai_research
from map_logic.system32 import turn_processor
from map_logic.system32.time_handler import TimeHandler
from tests.stub_map_screen import map_double


def project(name, points):
    return {"tech_name": name, "points_remaining": points}


def economy(income, upkeep):
    report = {key: dict.fromkeys(c.ECON_RESOURCE_KEYS, 0) for key in ("total_inc", "upkeep")}
    report["total_inc"]["materials"] = income
    report["upkeep"]["materials"] = upkeep
    report["breakdown"] = {key: {} for key in c.ECON_RESOURCE_KEYS}
    return report


class ResearchFundingTests(unittest.TestCase):
    def test_logarithmic_income_conversion(self):
        country = {"research_funding_slider": 0.1, "research_queue": [project("tech", 1_000)]}
        small_spend, small_awards = queries.calculate_research_funding(country, 100, {"tech": 0})
        large_spend, large_awards = queries.calculate_research_funding(country, 1_000_000, {"tech": 0})
        self.assertEqual((small_spend, large_spend), (10, 100_000))
        self.assertAlmostEqual(small_awards["tech"], 10)
        self.assertAlmostEqual(large_awards["tech"], 132.87856641840545)

    def test_splitting_redistributes_unused_shares_and_caps_spending(self):
        country = {"research_funding_slider": 1, "research_queue": [
            project("already_done", 10), project("near_done", 12), project("far_off", 100),
        ]}
        normal = {"already_done": 10, "near_done": 10, "far_off": 10}
        spent, awards = queries.calculate_research_funding(country, 10, normal)
        self.assertEqual(spent, 10)
        self.assertEqual(awards, {"near_done": 2, "far_off": 8})
        country["research_queue"].pop()
        spent, awards = queries.calculate_research_funding(country, 100_000, normal)
        self.assertLess(spent, 100_000)
        self.assertAlmostEqual(queries.get_funded_research_points(spent), 2)
        self.assertEqual(awards, {"near_done": 2})
        self.assertEqual(queries.calculate_research_funding(country, -1, normal), (0, {}))
        self.assertEqual(queries.calculate_research_funding(country, 100, {**normal, "near_done": 12}), (0, {}))
        country["research_queue"].clear()
        self.assertEqual(queries.calculate_research_funding(country, 100, {}), (0, {}))

    def test_funding_preview_and_resolution_agree_after_upkeep_and_modifiers(self):
        tree = {"first": {"years": [1922]}, "second": {"years": [1920]}}
        for economic_value in (c.POLITICS_MIN, c.POLITICS_MAX):
            with self.subTest(economic_value=economic_value):
                policy_id = "prioritize_industrial_needs"
                country = {"materials": 8, "research_funding_slider": 0.1, "economic_value": economic_value,
                           "research": {}, "research_queue": [project(tech, 1_000) for tech in tree],
                           politics.POLICY_KEY: {policy_id: {"status": politics.POLICY_ACTIVE}}}
                game = BackendState()
                game.player_country = "A"
                game.active_players = ["A"]
                game.time_manager = TimeHandler(start_year=1920)
                game.nation_data["A"] = country
                province = {"id": 1, "json_key": "1", "terrain": "plains", "neighbors": [],
                            "owner": "A", "cores": ["A"], "units": []}
                game.map_data[1] = game.id_to_province[1] = province
                report = economy(120, 20)
                with patch.object(queries, "get_tech_tree", return_value=tree), \
                        patch.object(queries, "get_faction_research_bonus", return_value=0.5), \
                        patch.object(queries, "calculate_all_economies", return_value={"A": report}):
                    income, upkeep, economy_breakdown = queries.get_economy_projections("A", game.map_data, game.nation_data, context=game)
                    spent, awards = queries.get_projected_research_funding(game, "A")
                    breakdown = queries.get_projected_research_breakdown(game, "A")
                    self.assertEqual(income["materials"] - upkeep["materials"], 90)
                    self.assertEqual(economy_breakdown["materials"]["research_funding"], -10)
                    self.assertEqual((spent, awards), (10, {"first": 5, "second": 5}))
                    self.assertAlmostEqual(breakdown["funding"], sum(awards.values()))

                    days = queries.get_days_per_turn(game.scenario_settings)
                    asyncio.run(turn_processor.resolve_turn_logic(game))
                    date = queries.get_exact_year(game.time_manager)
                    base = c.BASE_RESEARCH_POINTS_PER_DAY * days * (0 if economic_value == c.POLITICS_MIN else 2)
                    policy_multiplier = politics.policy(policy_id)["effects"]["research"]
                    self.assertEqual(country["materials"], 98)
                    self.assertEqual(country["research_funding_slider"], 0.1)
                    self.assertAlmostEqual(breakdown["base"] + breakdown["economy"], base)
                    self.assertAlmostEqual(breakdown["policies"], base * (policy_multiplier - 1))
                    for entry in country["research_queue"]:
                        penalty = 0.5 ** max(0, tree[entry["tech_name"]]["years"][0] - date)
                        self.assertAlmostEqual(entry["points_remaining"], 1_000 - base * policy_multiplier * 1.5 * penalty - 5)
                    self.assertAlmostEqual(sum(breakdown.values()), base * policy_multiplier + sum(awards.values()))

    def test_research_breakdown_is_per_slot_regardless_of_the_queue(self):
        game = BackendState()
        days = queries.get_days_per_turn(game.scenario_settings)
        base = c.BASE_RESEARCH_POINTS_PER_DAY * days
        country = {"economic_value": 0, "research_funding_slider": 0.5, "research": {}, "research_queue": []}
        game.nation_data["A"] = country
        with patch.object(queries, "calculate_all_economies", return_value={"A": economy(40, 20)}) as calculate:
            breakdown = queries.get_projected_research_breakdown(game, "A")
            funding = queries.get_funded_research_points(10)
            self.assertAlmostEqual(breakdown["funding"], funding)
            self.assertAlmostEqual(sum(breakdown.values()), base + funding)

            country["research_queue"] = [project("almost_done", 1)]
            self.assertEqual(queries.get_projected_research_breakdown(game, "A"), breakdown)
            country["research_queue"] = [project("ongoing", base * 4), project("new_project", base * 5)]
            self.assertEqual(queries.get_projected_research_breakdown(game, "A"), breakdown)

            calculate.return_value = {"A": economy(10, 20)}
            self.assertEqual(sum(queries.get_projected_research_breakdown(game, "A").values()), base)

    def test_save_and_selected_history_restore_the_country_rate(self):
        game = map_double(player_country="A", time_manager=TimeHandler(start_year=1920),
                          nation_data={"A": {"research_funding_slider": 0.32}}, history={})
        turn_processor.snapshot_history(game)
        game.nation_data["A"]["research_funding_slider"] = 0.6
        saved = json.loads(json.dumps(queries.build_save_dict(game)))
        history = json.loads(json.dumps(game.history))
        self.assertEqual(queries.get_research_funding_rate(saved["nation_data"]["A"]), 0.6)
        load_map._apply_history_snapshot(saved, history, game.time_manager.total_turns)
        self.assertEqual(queries.get_research_funding_rate(saved["nation_data"]["A"]), 0.32)
        self.assertEqual(queries.get_research_funding_rate({}), 0)

    def test_ai_funds_from_surplus_with_a_reserve_and_preserves_human_choices(self):
        country = {"materials": 10, "research_queue": [project(str(i), 300) for i in range(c.RESEARCH_SLOTS)]}
        game = map_double(player_country="A", nation_data={"A": country})
        with patch.object(queries, "get_active_ai_nations", return_value=["A"]), \
                patch.object(queries, "get_tech_tree", return_value={"fixture": {"max_lvl": 1}}), \
                patch.object(queries, "calculate_all_economies", return_value={"A": economy(100, 10)}), \
                patch.object(ai_research.ai_world, "for_screen", return_value=None):
            ai_research.process_ai_research(game)
            self.assertEqual(country["research_funding_slider"], c.AI_RESEARCH_FUNDING_RATE)
            country["materials"] = 9
            ai_research.process_ai_research(game)
            self.assertEqual(country["research_funding_slider"], 0)
            country["research_funding_slider"] = 0.32
            ai_research.process_ai_research(game, countries=["A"])
            self.assertEqual(country["research_funding_slider"], 0.32)

    def test_slider_track_click_updates_funding_preview_and_handle_still_drags(self):
        import pygame
        from screens.game.economy import Economy_Screen
        from ui.widgets.ui_elements import Slider

        pygame.init()
        pygame.display.set_mode((1, 1))
        country = {"research_queue": [project("fixture", 1_000)]}
        game = map_double(player_country="A", nation_data={"A": country}, time_manager=TimeHandler(start_year=1920),
                          invalidate_map_presentation_cache=Mock())
        screen = Economy_Screen()
        with patch.object(queries, "calculate_all_economies", return_value={"A": economy(120, 20)}), \
                patch.object(queries, "get_tech_tree", return_value={"fixture": {"years": [1920]}}):
            screen.start_economy(game)
            slider = next(control for control in screen.elements
                          if isinstance(control, Slider) and control.callback == screen.set_research_funding)
            track_pos = slider.rect.center
            screen.handle_events([pygame.event.Event(kind, button=1, pos=track_pos)
                                  for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)])
            self.assertEqual(country["research_funding_slider"], 0.5)
            self.assertEqual(screen.econ_cache[2]["materials"]["research_funding"], -50)
            game.invalidate_map_presentation_cache.assert_called_once()

            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slider.handle_rect.center),
                pygame.event.Event(pygame.MOUSEMOTION, pos=(slider.rect.x + slider.rect.width // 4, slider.rect.y), mobile_touch=True),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=track_pos),
            ])
            self.assertEqual(country["research_funding_slider"], 0.25)
            self.assertEqual(screen.econ_cache[2]["materials"]["research_funding"], -25)

            country["research_queue"].clear()
            with patch.object(queries, "get_funded_research_points", wraps=queries.get_funded_research_points) as preview:
                screen.refresh_economy_preview()
            preview.assert_called_once_with(25)
            self.assertNotIn("research_funding", screen.econ_cache[2]["materials"])

            country["research_queue"].append(project("fixture", 1))
            with patch.object(queries, "get_funded_research_points", wraps=queries.get_funded_research_points) as preview:
                screen.refresh_economy_preview()
            preview.assert_called_once_with(25)
            self.assertNotIn("research_funding", screen.econ_cache[2]["materials"])

            game.tactical_mode = True
            screen.set_research_funding(0.75)
            self.assertEqual(country["research_funding_slider"], 0.25)

    def test_map_hud_uses_cached_economy_projection_until_input_changes(self):
        from screens.game.map import Map

        game = map_double(player_country="A", nation_data={"A": {}}, _resource_hud_economy_key=None,
                          time_manager=TimeHandler(start_year=1920))
        report = economy(90, 20)
        projection = report["total_inc"], report["upkeep"], report["breakdown"]
        with patch.object(queries, "get_economy_projections", return_value=projection) as calculate:
            Map._refresh_resource_hud_economy(game)
            first_draw = queries.get_resource_hud_strings(game, include_net=True)
            Map._refresh_resource_hud_economy(game)
            self.assertEqual(queries.get_resource_hud_strings(game, include_net=True), first_draw)
            calculate.assert_called_once()

            game._presentation_cache_revision = 1
            Map._refresh_resource_hud_economy(game)
            self.assertEqual(calculate.call_count, 2)
