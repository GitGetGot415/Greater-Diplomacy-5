"""Plays several turns of a real scenario.

The broadest test in the suite: one turn touches the economy processor, AI
construction, AI movement, combat resolution, the diplomacy pass and a full
map re-render. Nothing else exercises those together, and most of them were
edited by this refactor.

The LLM is force-skipped, so the AI answers from its canned fallback table
rather than reaching for the network.
"""

import asyncio
import unittest

from tests import app_harness

TURNS = 5


class TurnLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        from data import queries
        from screens.menu_screens.map import Map
        cls.map = Map(load_path=app_harness.SCENARIO_PATH, is_scenario=True, num_players=1)
        cls.map.selection_mode = False
        cls.map.force_skip_llm = True
        country = sorted(queries.get_living_nations(cls.map.map_data))[0]
        cls.map.player_country = country
        cls.map.active_players = [country]
        cls.map.selected_province = next(province for province in cls.map.map_data.values()
                                          if province.get("owner") == country)
        cls.map.set_play_view_defaults()

        cls.before = cls.snapshot(cls.map)
        cls.run_turns(cls.map, cls.surface, TURNS)
        cls.after = cls.snapshot(cls.map)

    @staticmethod
    def snapshot(game_map):
        from data import queries
        return {
            "date": game_map.time_manager.get_date_string(),
            "turns": game_map.time_manager.total_turns,
            "units": sum(len(p.get("units", [])) for p in game_map.map_data.values()),
            "queued": sum(len(p.get("unit_queue", [])) + len(p.get("building_queue", []))
                          for p in game_map.map_data.values()),
            "living": set(queries.get_living_nations(game_map.map_data)),
        }

    @staticmethod
    def run_turns(game_map, surface, count):
        from map_logic.turn_processing import turn_manager, turn_processor
        from map_logic.ai import ai_handler
        from unittest.mock import patch
        import pygame

        async def play():
            for _ in range(count):
                # Await preparation before resolution. advance_time starts a background thread.
                await turn_processor.prepare_turn(game_map)
                game_map.turn_start_time = pygame.time.get_ticks()
                await turn_manager._resolve_turn_and_refresh(game_map)
                if game_map.thread_error:
                    raise RuntimeError(game_map.thread_error)
                game_map.refresh_ui()
                game_map.draw(surface)

        with patch.object(ai_handler, "FORCE_SKIP", True):
            asyncio.run(play())

    def test_time_advances(self):
        self.assertNotEqual(self.after["date"], self.before["date"])
        self.assertEqual(self.after["turns"], self.before["turns"] + TURNS)

    def test_landless_countries_have_exile_or_cleanup_state(self):
        """Defeats can occur during valid combat. Their state must remain consistent."""
        from data import queries
        for country in self.before["living"] - self.after["living"]:
            data = self.map.nation_data.get(country, {})
            with self.subTest(country=country):
                if data.get("faction"):
                    self.assertTrue(queries.is_government_in_exile(country, self.map.map_data, self.map.nation_data))
                else:
                    self.assertFalse(data.get("at_war_with"))
                    self.assertFalse(data.get("pending_diplomacy"))

    def test_the_ai_builds_things(self):
        """Check AI production execution without assuming net army growth after combat."""
        from data import queries
        from map_logic import production_actions
        from map_logic.turn_processing import economy_processor
        from tests.test_consolidated_actions import game
        context = game()
        province = context.map_data[1]
        library = queries.get_unit_library(context)
        before = len(province["units"])
        production_actions.submit_production(context, "A", province, "unit_queue",
                                             {"unit_type": "Fixture"}, authority="ai",
                                             policy=production_actions.AI_POLICY)
        for _ in range(library["Fixture"]["production_time"]):
            economy_processor.process_queues(context)
        self.assertEqual(province["unit_queue"], [])
        self.assertEqual(len(province["units"]), before + 1)
        created = province["units"][-1]
        self.assertEqual(created["type"], "Fixture")
        self.assertEqual(created["max_health"], library["Fixture"]["health"])

    def test_nations_keep_their_core_fields(self):
        for name, data in self.map.nation_data.items():
            if not isinstance(data, dict) or name == "GLOBAL_EVENTS":
                continue
            with self.subTest(nation=name):
                self.assertIsInstance(data.get("at_war_with", []), list)
                self.assertIsInstance(data.get("puppets", []), list)

    def test_resources_never_go_negative(self):
        """Every deduction path is meant to be guarded by an affordability
        check or clamped at zero."""
        from data import queries
        for name in queries.get_living_nations(self.map.map_data):
            data = self.map.nation_data.get(name, {})
            for resource in ("materials", "manpower", "fuel"):
                with self.subTest(nation=name, resource=resource):
                    self.assertGreaterEqual(data.get(resource, 0), 0)

    def test_the_map_still_draws(self):
        self.map.draw(self.surface)


if __name__ == "__main__":
    unittest.main()
