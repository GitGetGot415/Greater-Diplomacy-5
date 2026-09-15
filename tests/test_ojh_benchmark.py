"""Contract tests for map_tools/ojh_benchmark.py, the Objective Judge Horizon hooks.

The tool's whole value is that a benchmark turn is the game's own turn, so the
turn test plays one real turn of a real scenario and checks that both
background phases ran and that nothing the tool patched is left patched. It
uses its own Map, not app_harness.boot_map()'s cached one, so a Spectator turn
played here cannot leak into the other tests' map.
"""

import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout

from tests import app_harness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_tool():
    path = os.path.join(ROOT, "map_tools", "ojh_benchmark.py")
    spec = importlib.util.spec_from_file_location("ojh_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SceneStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_percentiles_and_one_percent_low_come_from_the_slowest_frames(self):
        fast, slow = 0.010, 0.100
        frames = [fast] * 99 + [slow]
        count, total, p50, p95, p99, low = self.tool.scene_statistics(frames)
        self.assertEqual(count, 100)
        self.assertAlmostEqual(total, fast * 99 + slow)
        self.assertAlmostEqual(p50, fast * 1000.0)
        self.assertAlmostEqual(p99, fast * 1000.0)
        self.assertAlmostEqual(low, 1.0 / slow)

    def test_too_few_frames_report_no_scene(self):
        self.assertIsNone(self.tool.scene_statistics([0.01]))
        out = io.StringIO()
        with redirect_stdout(out):
            self.tool.report_scene("menu", [])
        self.assertTrue(out.getvalue().startswith("OJH noscene menu "))

    def test_scene_line_follows_the_ojh_protocol(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.tool.report_scene("map-start", [0.02, 0.03, 0.025])
        fields = out.getvalue().split()
        self.assertEqual(fields[:3], ["OJH", "scene", "map-start"])
        self.assertEqual(len(fields), 9)
        self.assertEqual(int(fields[3]), 3)
        for value in fields[4:]:
            float(value)


class PlayTurnTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        app_harness.boot()
        import main
        from map_logic.ai import ai_handler
        from map_logic.turn_processing import turn_manager
        self.ai_handler = ai_handler
        self.turn_manager = turn_manager
        self.saved_force_skip = ai_handler.FORCE_SKIP
        with redirect_stdout(io.StringIO()):
            self.map = main.Map(load_path=app_harness.SCENARIO_PATH, is_scenario=True, num_players=1)
        self.map.player_country = "Spectator"
        self.map.active_players = []
        self.map.selection_mode = False
        self.map.skip_ai_view = True

    def tearDown(self):
        self.ai_handler.FORCE_SKIP = self.saved_force_skip

    def test_one_turn_runs_both_phases_and_restores_run_background(self):
        import asyncio
        background = self.turn_manager.run_background
        turns_before = self.map.time_manager.total_turns
        with redirect_stdout(io.StringIO()):
            seconds = asyncio.run(self.tool.play_turn(self.map))
        self.assertGreater(seconds, 0.0)
        self.assertEqual(self.map.time_manager.total_turns, turns_before + 1)
        self.assertFalse(self.map.ai_is_thinking)
        self.assertFalse(self.map.is_refreshing)
        self.assertFalse(self.map.viewing_ai_moves)
        self.assertIsNone(self.map.thread_error)
        self.assertIs(self.turn_manager.run_background, background)

    def test_model_diplomacy_is_skipped_like_the_force_skip_button(self):
        import asyncio
        with redirect_stdout(io.StringIO()):
            asyncio.run(self.tool.play_turn(self.map))
        self.assertTrue(self.map.force_skip_llm)
        self.assertTrue(self.ai_handler.FORCE_SKIP)


if __name__ == "__main__":
    unittest.main()
