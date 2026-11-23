"""Research funding spends a share of gross income and awards unmodified progress."""

import asyncio
import json
import math
import unittest
from unittest.mock import Mock, patch

import data.constants as c
from map_logic.ai import ai_tuning
from data import queries
from data.map import load_map
from data.state_access import BackendState
from map_logic import politics
from map_logic.ai import ai_research
from map_logic.system32 import turn_processor
from map_logic.system32.time_handler import TimeHandler
from tests.politics_fixtures import policy_fixtures
from tests.stub_map_screen import map_double


def project(name, points):
    return {"tech_name": name, "points_remaining": points}


def economy(income, upkeep, funding_rate=0):
    """Economy report fixture. Funding takes its share of gross income, as in the calculator."""
    spent = queries.get_research_funding_cost(funding_rate, income)
    report = {key: dict.fromkeys(c.ECON_RESOURCE_KEYS, 0) for key in ("total_inc", "upkeep")}
    report["total_inc"]["materials"] = income - spent
    report["upkeep"]["materials"] = upkeep
    report["breakdown"] = queries.empty_income_breakdown()
    report["breakdown"]["materials"]["research_funding"] = -spent
    report["gross_materials"] = income
    return report


def funded_economies(nation_data, reports):
    """Rebuild fixture reports from each country's current funding rate on every call."""
    return lambda *args, **kwargs: {name: economy(*report, queries.get_research_funding_rate(nation_data[name]))
                                    for name, report in reports.items()}


class ResearchFundingTests(unittest.TestCase):
    def test_slider_sets_the_bonus_share_and_gross_income_sets_the_cost(self):
        for days in (5, 30):
            base = c.BASE_RESEARCH_POINTS_PER_DAY * days
            country = {"research_queue": [project("tech", base * 2)]}
            for rate, share in ((0, 0), (0.01, 0.0199), (0.25, 0.4375), (0.5, 0.75), (1, 1)):
                country["research_funding_slider"] = rate
                for gross in (10_000, 1_000_000):
                    with self.subTest(days=days, rate=rate, gross=gross):
                        spent = queries.get_research_funding_cost(rate, gross)
                        awards = queries.get_research_funding_awards(country, spent, {"tech": 0}, days_per_turn=days)
                        self.assertEqual(spent, int(gross * rate))
                        self.assertAlmostEqual(awards.get("tech", 0), base * share)

    def test_splitting_redistributes_unused_shares_and_caps_spending(self):
        days = 5
        base = c.BASE_RESEARCH_POINTS_PER_DAY * days
        near_done = base * 0.34375
        country = {"materials": 100_000, "research_funding_slider": 1, "research_queue": [
            project("already_done", 10), project("near_done", 10 + near_done), project("far_off", 10 + base * 2),
        ]}
        normal = {"already_done": 10, "near_done": 10, "far_off": 10}
        spent = 20_000
        awards = queries.get_research_funding_awards(country, spent, normal, days_per_turn=days)
        self.assertEqual(awards, {"near_done": near_done, "far_off": base - near_done})
        # The slider always takes its full share. Points the queue cannot use are lost.
        country["research_queue"].pop()
        self.assertEqual(queries.get_research_funding_awards(country, spent, normal, days_per_turn=days), {"near_done": near_done})
        for gross in (0, -1):
            self.assertEqual(queries.get_research_funding_cost(1, gross), 0)
            self.assertEqual(queries.get_research_funding_awards(country, gross, normal, days_per_turn=days), {})
        finished = {**normal, "near_done": 10 + near_done}
        self.assertEqual(queries.get_research_funding_awards(country, spent, finished, days_per_turn=days), {})
        country["research_queue"].clear()
        self.assertEqual(queries.get_research_funding_awards(country, spent, {}, days_per_turn=days), {})

    def test_calculator_takes_funding_and_fuel_conversion_from_the_same_gross_income(self):
        game = BackendState()
        conversion_rate = 0.2
        refining = math.ceil(conversion_rate / c.FUEL_REFINING_CONVERSION_PER_LVL)
        country = {"research": {"fuel_refining": refining}, "research_queue": []}
        game.nation_data["A"] = country
        game.map_data[1] = game.id_to_province[1] = {"id": 1, "json_key": "1", "terrain": "plains", "neighbors": [],
                                                     "owner": "A", "cores": ["A"], "units": []}
        unfunded = queries.calculate_all_economies(game.map_data, game.nation_data, context=game)["A"]
        gross = unfunded["gross_materials"]
        self.assertGreater(gross, 0)
        country.update(research_funding_slider=0.5, mat_to_fuel_slider=conversion_rate)
        funded = queries.calculate_all_economies(game.map_data, game.nation_data, context=game)["A"]
        spent = queries.get_research_funding_cost(0.5, gross)
        self.assertEqual(funded["gross_materials"], gross)
        self.assertEqual(queries.get_research_funding_spent(funded["breakdown"]), spent)
        self.assertEqual(sum(funded["breakdown"]["materials"].values()), funded["total_inc"]["materials"])
        divisor = int(1 / c.FUEL_CONVERSION_RATIO)
        self.assertEqual(funded["breakdown"]["materials"]["conversion"], -(int(gross * conversion_rate) // divisor * divisor))
        # Funding is charged with nothing queued, and the queue does not change the charge.
        country["research_queue"] = [project("fixture", 1)]
        queued = queries.calculate_all_economies(game.map_data, game.nation_data, context=game)["A"]
        self.assertEqual(queued["breakdown"], funded["breakdown"])

    @policy_fixtures({"id": "research_fixture", "effects": {"research": 0.75}})
    def test_funding_preview_and_resolution_agree_after_upkeep_and_modifiers(self):
        tree = {"first": {"years": [1922]}, "second": {"years": [1920]}}
        for political_value in (c.POLITICS_MIN, c.POLITICS_MAX):
            with self.subTest(political_value=political_value):
                policy_id = "research_fixture"
                country = {"materials": 8, "research_funding_slider": 0.1, "political_value": political_value,
                           "research": {}, "research_queue": [project(tech, 1_000) for tech in tree],
                           politics.POLICY_KEY: {policy_id: {"status": politics.POLICY_ACTIVE}}}
                game = BackendState()
                days = queries.get_days_per_turn(game.scenario_settings)
                unmodified_base = c.BASE_RESEARCH_POINTS_PER_DAY * days
                bonus_per_project = unmodified_base * 0.19 / len(tree)
                game.player_country = "A"
                game.active_players = ["A"]
                game.time_manager = TimeHandler(start_year=1920)
                game.nation_data["A"] = country
                province = {"id": 1, "json_key": "1", "terrain": "plains", "neighbors": [],
                            "owner": "A", "cores": ["A"], "units": []}
                game.map_data[1] = game.id_to_province[1] = province
                with patch.object(queries, "get_tech_tree", return_value=tree), \
                        patch.object(queries, "get_faction_research_bonus", return_value=0.5), \
                        patch.object(queries, "calculate_all_economies", side_effect=funded_economies(game.nation_data, {"A": (120, 20)})):
                    income, upkeep, economy_breakdown = queries.get_economy_projections("A", game.map_data, game.nation_data, context=game)
                    awards = queries.get_projected_research_funding_awards(game, "A")
                    breakdown = queries.get_projected_research_breakdown(game, "A")
                    self.assertEqual(income["materials"] - upkeep["materials"], 88)
                    self.assertEqual(economy_breakdown["materials"]["research_funding"], -12)
                    self.assertEqual(queries.get_research_funding_spent(economy_breakdown), 12)
                    self.assertEqual(awards.keys(), tree.keys())
                    for bonus in awards.values():
                        self.assertAlmostEqual(bonus, bonus_per_project)
                    self.assertAlmostEqual(breakdown["funding"], sum(awards.values()))

                    asyncio.run(turn_processor.resolve_turn_logic(game))
                    date = queries.get_exact_year(game.time_manager)
                    base = unmodified_base * politics.effect_at("research", political_value)
                    policy_multiplier = politics.policy(policy_id)["effects"]["research"]
                    self.assertEqual(country["materials"], 96)
                    self.assertEqual(country["research_funding_slider"], 0.1)
                    self.assertAlmostEqual(breakdown["base"] + breakdown["politics"], base)
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
        with patch.object(queries, "calculate_all_economies", side_effect=funded_economies(game.nation_data, {"A": (40, 20)})) as calculate:
            breakdown = queries.get_projected_research_breakdown(game, "A")
            funding = base * 0.75
            self.assertAlmostEqual(breakdown["funding"], funding)
            self.assertAlmostEqual(sum(breakdown.values()), base + funding)

            country["research_queue"] = [project("almost_done", 1)]
            self.assertEqual(queries.get_projected_research_breakdown(game, "A"), breakdown)
            country["research_queue"] = [project("ongoing", base * 4), project("new_project", base * 5)]
            self.assertEqual(queries.get_projected_research_breakdown(game, "A"), breakdown)

            calculate.side_effect = funded_economies(game.nation_data, {"A": (0, 20)})
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
        ai_cost = queries.get_research_funding_cost(ai_tuning.AI_RESEARCH_FUNDING_RATE, 100)
        with patch.object(queries, "get_active_ai_nations", return_value=["A"]), \
                patch.object(queries, "get_tech_tree", return_value={"fixture": {"max_lvl": 1}}), \
                patch.object(queries, "calculate_all_economies", return_value={"A": economy(100, 10)}) as calculate, \
                patch.object(ai_research.ai_world, "for_screen", return_value=None):
            ai_research.process_ai_research(game)
            self.assertEqual(country["research_funding_slider"], ai_tuning.AI_RESEARCH_FUNDING_RATE)
            # Last turn's funding does not count against the surplus, so the rate holds steady.
            country["materials"] = 1_000
            calculate.return_value = {"A": economy(100, 100 - ai_cost - 1, ai_tuning.AI_RESEARCH_FUNDING_RATE)}
            ai_research.process_ai_research(game)
            self.assertEqual(country["research_funding_slider"], ai_tuning.AI_RESEARCH_FUNDING_RATE)
            calculate.return_value = {"A": economy(100, 100 - ai_cost, ai_tuning.AI_RESEARCH_FUNDING_RATE)}
            ai_research.process_ai_research(game)
            self.assertEqual(country["research_funding_slider"], 0)
            calculate.return_value = {"A": economy(100, 10)}
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
        with patch.object(queries, "calculate_all_economies", side_effect=funded_economies(game.nation_data, {"A": (120, 20)})), \
                patch.object(queries, "get_tech_tree", return_value={"fixture": {"years": [1920]}}):
            screen.start_economy(game)
            slider = next(control for control in screen.elements
                          if isinstance(control, Slider) and control.callback == screen.set_research_funding)
            track_pos = slider.rect.center
            screen.handle_events([pygame.event.Event(kind, button=1, pos=track_pos)
                                  for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)])
            self.assertEqual(country["research_funding_slider"], 0.5)
            self.assertEqual(screen.econ_cache[2]["materials"]["research_funding"], -60)
            game.invalidate_map_presentation_cache.assert_called_once()

            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slider.handle_rect.center),
                pygame.event.Event(pygame.MOUSEMOTION, pos=(slider.rect.x + slider.rect.width // 4, slider.rect.y), mobile_touch=True),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=track_pos),
            ])
            self.assertEqual(country["research_funding_slider"], 0.25)
            self.assertEqual(screen.econ_cache[2]["materials"]["research_funding"], -30)

            # Funding is charged with nothing queued, like the other income sliders.
            country["research_queue"].clear()
            screen.set_research_funding(0.75)
            self.assertEqual(screen.econ_cache[0]["materials"], 120 - 90)
            self.assertEqual(screen.econ_cache[2]["materials"]["research_funding"], -90)
            with patch.object(queries, "get_funded_research_points", wraps=queries.get_funded_research_points) as preview:
                screen.refresh_economy_preview()
            preview.assert_called_once_with(country, 90, days)
            screen.set_research_funding(0.25)

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
