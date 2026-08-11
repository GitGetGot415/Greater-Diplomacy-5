"""Editing a nation's temperament, and having it stick.

ai_personality_overrides had a reader, two tests and no writer of any kind, so
the only way to set a personality was to hand-edit a scenario JSON. That matters
because without one the traits are procedural -- reproducible, but historically
arbitrary: this seed gives the 1939 German Reich an aggression of 0.51 and the
USSR 0.04.

What is asserted here is the contract the screen depends on, not its pixels:
edits must be authored (so nothing regenerates them), must actually change what
the AI decides, and must survive a save/load round trip.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_personality


class AuthoredTraitTests(unittest.TestCase):
    def setUp(self):
        self.nation_data = {"Avaria": {}}

    def edit(self, **traits):
        full = dict.fromkeys(ai_personality.TRAITS, 0.5)
        full.update(traits)
        return ai_personality.set_authored(self.nation_data, "Avaria", full)

    def test_an_edit_is_marked_as_authored(self):
        self.assertIn(self.edit(aggression=0.9)["_source"], ai_personality.AUTHORED_SOURCES)

    def test_an_authored_trait_is_never_regenerated(self):
        """The whole point: a later get() must not overwrite the editor."""
        self.edit(aggression=0.9)
        for _ in range(3):
            got = ai_personality.get(self.nation_data, "Avaria", {"ai_personality_seed": "other"})
            self.assertEqual(got["aggression"], 0.9)

    def test_a_scenario_override_does_not_beat_the_editor(self):
        self.edit(aggression=0.9)
        settings = {"ai_personality_overrides": {"Avaria": {"aggression": 0.1}}}
        self.assertEqual(
            ai_personality.get(self.nation_data, "Avaria", settings)["aggression"], 0.9)

    def test_out_of_range_values_are_clamped(self):
        stored = self.edit(aggression=4.0, caution=-2.0)
        self.assertLessEqual(stored["aggression"], 1.0)
        self.assertGreaterEqual(stored["caution"], 0.0)

    def test_every_trait_is_written(self):
        stored = self.edit()
        for name in ai_personality.TRAITS:
            self.assertIn(name, stored)

    def test_clearing_the_block_restores_procedural_traits(self):
        """What the screen's Reset button does -- back to being regenerated."""
        self.edit(aggression=0.9)
        self.nation_data["Avaria"].pop("personality")
        got = ai_personality.get(self.nation_data, "Avaria", {})
        self.assertEqual(got["_source"], "procedural")
        self.assertNotEqual(got["aggression"], 0.9)

    def test_an_edit_survives_a_save_round_trip(self):
        """personality lives inside nation_data, so it serializes for free --
        but only if it is plain JSON, which set_authored has to keep it."""
        import json
        self.edit(aggression=0.87, loyalty=0.12)
        reloaded = json.loads(json.dumps(self.nation_data))
        got = ai_personality.get(reloaded, "Avaria", {})
        self.assertAlmostEqual(got["aggression"], 0.87)
        self.assertAlmostEqual(got["loyalty"], 0.12)
        self.assertIn(got["_source"], ai_personality.AUTHORED_SOURCES)


class EditedTraitsChangeBehaviourTests(unittest.TestCase):
    """An editor that set a number nothing read would be worse than none."""

    def test_aggression_moves_war_desire(self):
        from map_logic.ai import ai_opinion, ai_world

        def desire(aggression):
            nation_data = {
                "Avaria": {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
                           "master": "", "faction": "", "temp_modifiers": {}, "relations": {},
                           "manpower": 5000, "materials": 5000, "fuel": 500, "war_durations": {}},
                "Borland": {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
                            "master": "", "faction": "", "temp_modifiers": {}, "relations": {},
                            "manpower": 5000, "materials": 5000, "fuel": 500, "war_durations": {}},
            }
            map_data = {
                "1": {"id": 1, "json_key": "1", "owner": "Avaria", "cores": ["Avaria"],
                      "neighbors": [2], "units": [], "resources": [], "buildings": [],
                      "is_coastal": False},
                "2": {"id": 2, "json_key": "2", "owner": "Borland", "cores": ["Avaria"],
                      "neighbors": [1], "units": [], "resources": [], "buildings": [],
                      "is_coastal": False},
            }
            full = dict.fromkeys(ai_personality.TRAITS, 0.5)
            full["aggression"] = aggression
            ai_personality.set_authored(nation_data, "Avaria", full)
            world = ai_world.AIWorld(map_data, nation_data, {1: map_data["1"], 2: map_data["2"]})
            return ai_opinion.war_desire(world, "Avaria", "Borland")

        self.assertGreater(desire(1.0), desire(0.0),
                           "a belligerent nation must want war more than a peaceable one")


if __name__ == "__main__":
    unittest.main()
