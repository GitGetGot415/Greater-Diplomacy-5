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
        cls.map = app_harness.boot_map()
        cls.map.selection_mode = False
        cls.map.force_skip_llm = True

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
            "living": len(queries.get_living_nations(game_map.map_data)),
        }

    @staticmethod
    def run_turns(game_map, surface, count):
        from map_logic.turn_processing import turn_manager

        async def play():
            for _ in range(count):
                turn_manager.advance_time(game_map)
                await turn_manager._resolve_turn_and_refresh(game_map)
                game_map.refresh_ui()
                game_map.draw(surface)

        asyncio.run(play())

    def test_time_advances(self):
        self.assertNotEqual(self.after["date"], self.before["date"])
        self.assertEqual(self.after["turns"], self.before["turns"] + TURNS)

    def test_nobody_is_wiped_out_in_five_turns(self):
        """A sudden collapse in the living-nation count means a turn processor
        blew up somewhere and left the map half-resolved."""
        self.assertEqual(self.after["living"], self.before["living"])

    def test_the_ai_builds_things(self):
        """Covers the ai_construction purchase loop and the economy processor:
        queues fill and completed orders turn into units."""
        self.assertGreater(self.after["queued"], 0, "the AI queued nothing in five turns")
        self.assertGreater(self.after["units"], self.before["units"],
                           "no queued order ever completed into a unit")

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
