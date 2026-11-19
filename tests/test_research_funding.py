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
    def test_slider_sets_the_bonus_share_and_surplus_sets_the_cost(self):
        for days in (5, 30):
            base = c.BASE_RESEARCH_POINTS_PER_DAY * days
            country = {"research_queue": [project("tech", base * 2)]}
            for rate, share in ((0, 0), (0.01, 0.01495), (0.25, 0.34375), (0.5, 0.625), (1, 1)):
                country["research_funding_slider"] = rate
                for surplus in (10_000, 1_000_000):
                    with self.subTest(days=days, rate=rate, surplus=surplus):
                        spent, awards = queries.calculate_research_funding(country, surplus, {"tech": 0}, days_per_turn=days)
                        self.assertAlmostEqual(spent, surplus * rate)
                        self.assertAlmostEqual(awards.get("tech", 0), base * share)

    def test_splitting_redistributes_unused_shares_and_caps_spending(self):
        days = 5
        base = c.BASE_RESEARCH_POINTS_PER_DAY * days
        near_done = base * 0.34375
        country = {"materials": 100_000, "research_funding_slider": 1, "research_queue": [
            project("already_done", 10), project("near_done", 10 + near_done), project("far_off", 10 + base * 2),
        ]}
        normal = {"already_done": 10, "near_done": 10, "far_off": 10}
        surplus = 20_000
        spent, awards = queries.calculate_research_funding(country, surplus, normal, days_per_turn=days)
        self.assertEqual(spent, surplus)
        self.assertEqual(awards, {"near_done": near_done, "far_off": base - near_done})
        country["research_queue"].pop()
        spent, awards = queries.calculate_research_funding(country, surplus, normal, days_per_turn=days)
        self.assertAlmostEqual(spent, surplus * 0.25)
        self.assertEqual(awards, {"near_done": near_done})
        for net_materials in (0, -1):
            self.assertEqual(queries.calculate_research_funding(country, net_materials, normal, days_per_turn=days), (0, {}))
        finished = {**normal, "near_done": 10 + near_done}
        self.assertEqual(queries.calculate_research_funding(country, surplus, finished, days_per_turn=days), (0, {}))
        country["research_queue"].clear()
        self.assertEqual(queries.calculate_research_funding(country, surplus, {}, days_per_turn=days), (0, {}))

    def test_funding_preview_and_resolution_agree_after_upkeep_and_modifiers(self):
        tree = {"first": {"years": [1922]}, "second": {"years": [1920]}}
        for economic_value in (c.POLITICS_MIN, c.POLITICS_MAX):
            with self.subTest(economic_value=economic_value):
                policy_id = "prioritize_industrial_needs"
                country = {"materials": 8, "research_funding_slider": 0.1, "economic_value": economic_value,
                           "research": {}, "research_queue": [project(tech, 1_000) for tech in tree],
                           politics.POLICY_KEY: {policy_id: {"status": politics.POLICY_ACTIVE}}}
                game = BackendState()
                days = queries.get_days_per_turn(game.scenario_settings)
                unmodified_base = c.BASE_RESEARCH_POINTS_PER_DAY * days
                bonus_per_project = unmodified_base * 0.145 / len(tree)
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
                    self.assertEqual(spent, 10)
                    self.assertEqual(awards.keys(), tree.keys())
                    for bonus in awards.values():
                        self.assertAlmostEqual(bonus, bonus_per_project)
                    self.assertAlmostEqual(breakdown["funding"], sum(awards.values()))

                    asyncio.run(turn_processor.resolve_turn_logic(game))
                    date = queries.get_exact_year(game.time_manager)
                    base = unmodified_base * (0 if economic_value == c.POLITICS_MIN else 2)
                    policy_multiplier = politics.policy(policy_id)["effects"]["research"]
                    self.assertEqual(country["materials"], 98)
                    self.assertEqual(country["research_funding_slider"], 0.1)
                    self.assertAlmostEqual(breakdown["base"] + breakdown["economy"], base)
                    self.assertAlmostEqual(breakdown["policies"], base * (policy_multiplier - 1))
                    for entry in country["research_queue"]:
                        penalty = 0.5 ** max(0, tree[entry["tech_name"]]["years"][0] - date)
                        self.assertAlmostEqual(entry["points_remaining"], 1_000 - base * policy_multiplier * 1.5 * penalty - bonus_per_project)
                    self.assertAlmostEqual(sum(breakdown.values()), base * policy_multiplier + sum(awards.values()))

    def test_research_breakdown_is_per_slot_regardless_of_the_queue(self):
        game = BackendState()
        days = queries.get_days_per_turn(game.scenario_settings)
        base = c.BASE_RESEARCH_POINTS_PER_DAY * days
        country = {"economic_value": 0, "research_funding_slider": 0.5, "research": {}, "research_queue": []}
        game.nation_data["A"] = country
        with patch.object(queries, "calculate_all_economies", return_value={"A": economy(40, 20)}) as calculate:
            breakdown = queries.get_projected_research_breakdown(game, "A")
            funding = base * 0.625
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
        days = queries.get_days_per_turn(game.scenario_settings)
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
            with patch.object(queries, "get_research_funding_budget_and_bonus", wraps=queries.get_research_funding_budget_and_bonus) as preview:
                screen.refresh_economy_preview()
            preview.assert_called_once_with(country, 100, days)
            self.assertNotIn("research_funding", screen.econ_cache[2]["materials"])

            country["research_queue"].append(project("fixture", 1))
            with patch.object(queries, "get_research_funding_budget_and_bonus", wraps=queries.get_research_funding_budget_and_bonus) as preview:
                screen.refresh_economy_preview()
            preview.assert_called_once_with(country, 100, days)
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
