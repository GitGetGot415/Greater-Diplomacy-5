"""Coverage for fort construction, layering data, and combat protection."""

import json
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.turn_processing import combat_processor


def unit(owner, attack=0, defense=0, health=100000):
    return {
        "type": "Infantry",
        "owner": owner,
        "health": health,
        "max_health": health,
        "attack": attack,
        "defense": defense,
        "morale": 50.0,
    }


class FortTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(c.BUILDING_DATA_PATH, "r", encoding="utf-8") as handle:
            cls.buildings = json.load(handle)

    def test_fort_chain_has_twenty_always_available_levels_and_costs(self):
        self.assertEqual(len([name for name in self.buildings if name.startswith("Fort Lvl ")]), 20)
        self.assertEqual(self.buildings["Fort Lvl 1"]["req"], None)
        self.assertEqual(self.buildings["Fort Lvl 1"]["time"], 1)
        for level in range(1, c.FORT_MAX_LEVEL + 1):
            name = f"Fort Lvl {level}"
            self.assertEqual(queries.get_building_required_tech(name), (None, 0))
            self.assertEqual(self.buildings[name]["cost_materials"], 5000 + level * 1000)
            if level > 1:
                self.assertEqual(self.buildings[name]["req"], f"Fort Lvl {level - 1}")

    def test_fort_bonus_only_protects_owner_and_faction_members_in_combat(self):
        province = {"owner": "A", "buildings": ["Fort Lvl 20"], "units": []}
        nations = {
            "A": {"faction": "Allies", "at_war_with": ["C"]},
            "B": {"faction": "Allies", "at_war_with": ["C"]},
            "C": {"faction": "Enemy", "at_war_with": ["A", "B"]},
        }
        province["units"] = [unit("A"), unit("C")]

        self.assertEqual(queries.get_fort_defense_bonus(province, unit("A"), nations), 200)
        self.assertEqual(queries.get_fort_defense_bonus(province, unit("B"), nations), 200)
        self.assertEqual(queries.get_fort_defense_bonus(province, unit("C"), nations), 0)

        province["units"] = [unit("A")]
        self.assertEqual(queries.get_fort_defense_bonus(province, unit("A"), nations), 0)

    def test_fort_bonus_reduces_damage_in_tile_combat(self):
        province = {
            "owner": "A",
            "buildings": ["Fort Lvl 20"],
            "units": [unit("A", defense=0), unit("C", attack=500)],
        }
        nations = {
            "A": {"at_war_with": ["C"]},
            "C": {"at_war_with": ["A"]},
        }

        # The helper is also the exact damage path used by combat resolution;
        # at full health a level-20 fort contributes 200 defense.
        target = province["units"][0]
        combat_processor.apply_group_damage(
            500, [target],
            lambda defender: queries.get_fort_defense_bonus(
                province, defender, nations, combat_active=True),
        )
        self.assertEqual(target["health"], 99700)


if __name__ == "__main__":
    unittest.main()
