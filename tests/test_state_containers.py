"""Exercise canonical state ownership without constructing a game screen."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from data.game_state import WorldState
from data.session_state import SessionState
from data.state_access import BackendState, replace_mapping
from data import queries


class StateContainerTests(unittest.TestCase):
    def test_defaults_are_independent_and_compatibility_attributes_share_owners(self):
        first, second = BackendState(), BackendState()
        first.nation_data["A"] = {"materials": 3}
        first.active_players.append("A")
        self.assertEqual(second.world.nation_data, {})
        self.assertEqual(second.session.active_players, [])
        self.assertIs(first.nation_data, first.world.nation_data)
        self.assertIs(first.active_players, first.session.active_players)
        first.player_country = "A"
        first.session.viewing_country = "B"
        self.assertEqual(first.session.player_country, "A")
        self.assertEqual(first.session.viewing_country, "B")

    def test_resets_retain_mapping_references_and_drafts_isolate_assignments(self):
        context = BackendState()
        countries = context.world.nation_data
        replace_mapping(context.world, "nation_data", {"A": {}})
        self.assertIs(context.world.nation_data, countries)
        replace_mapping(context.world, "nation_data", countries)
        self.assertEqual(countries, {"A": {}})
        draft = copy.copy(context)
        draft.nation_data = {"B": {}}
        draft.active_players.append("B")
        self.assertEqual(context.world.nation_data, {"A": {}})
        self.assertEqual(context.session.active_players, [])

    def test_serialization_excludes_runtime_owners_callbacks_and_private_session_data(self):
        context = BackendState(WorldState(), SessionState(player_country="A"), feedback=lambda _: None)
        context.session.private_credential = "fixture-secret"
        context.world.nation_data["A"] = {}
        serialized = json.dumps(queries.build_save_dict(context))
        self.assertNotIn("fixture-secret", serialized)
        for name in ("world", "session", "feedback", "_air_geometry"):
            self.assertNotIn(name, json.loads(serialized))

    def test_backend_load_and_full_ai_turn_need_no_display_or_map_screen(self):
        script = '''
import asyncio, sys, pygame
from data.map.load_map import load_backend_state
from map_logic.ai import ai_handler
from map_logic.system32 import turn_processor
context = load_backend_state("scenarios/historical/1939", is_scenario=True)
assert pygame.display.get_surface() is None
assert "screens.game.map" not in sys.modules
assert not hasattr(context, "id_map")
context.session.force_skip_llm = True
ai_handler.FORCE_SKIP = True
before = context.world.time_manager.total_turns
asyncio.run(turn_processor.prepare_turn(context))
asyncio.run(turn_processor.resolve_turn_logic(context))
assert context.world.time_manager.total_turns == before + 1
assert pygame.display.get_surface() is None
assert "screens.game.map" not in sys.modules
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
