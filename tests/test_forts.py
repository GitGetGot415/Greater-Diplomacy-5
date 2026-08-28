"""Coverage for fort construction, layering data, and combat protection."""

import json
import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.rendering import overlay_renderer
from map_logic.turn_processing import combat_processor
import ui_elements


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

    def test_combat_location_categories_share_the_fort_territory_rule(self):
        province = {"owner": "A", "buildings": [], "units": []}
        nations = {
            "A": {"faction": "Allies"},
            "B": {"faction": "Allies"},
            "C": {"faction": "Axis"},
        }

        self.assertTrue(queries.is_fort_defended_territory(province, "B", nations))
        self.assertEqual(
            queries.get_combat_location_category(province, "B", nations),
            queries.COMBAT_LOCATION_DEFENSE)
        self.assertEqual(
            queries.get_combat_location_category(province, "C", nations),
            queries.COMBAT_LOCATION_OFFENSE)
        self.assertEqual(
            queries.get_combat_location_category(None, "C", nations, midpoint=True),
            queries.COMBAT_LOCATION_MIDPOINT)

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

    def test_fort_bonus_is_not_reduced_when_the_defender_is_wounded(self):
        province = {"owner": "A", "buildings": ["Fort Lvl 5"], "units": []}
        nations = {"A": {"at_war_with": ["B"]}, "B": {"at_war_with": ["A"]}}
        target = unit("A", health=100000)
        target["max_health"] = 100000
        target["health"] = 50000
        province["units"] = [target]

        combat_processor.apply_group_damage(
            100, [target],
            lambda defender: queries.get_fort_defense_bonus(
                province, defender, nations, combat_active=True),
        )

        # The unit has no base defense. Its wounded state must not turn the
        # level-5 fort's +50 into +25.
        self.assertEqual(target["health"], 49950)

    def test_artillery_damages_fort_and_refunds_queued_upgrade(self):
        class Screen:
            pass

        screen = Screen()
        gun = {
            "type": "Artillery III", "owner": "B", "health": 1000,
            "max_health": 1000, "bombard_attack": 100,
            "order": {"type": "BOMBARD", "target_id": 2},
        }
        defender = unit("A")
        source = {"id": 1, "owner": "B", "neighbors": [2], "units": [gun]}
        target = {
            "id": 2, "owner": "A", "neighbors": [1],
            "buildings": ["Fort Lvl 5"], "units": [defender],
            "building_queue": [{
                "order_type": "BUILDING", "item_name": "Fort Lvl 6",
                "refund": {"cost_materials": 7000,
                            "cost_manpower": 0, "cost_fuel": 0},
            }],
        }
        screen.map_data = {1: source, 2: target}
        screen.id_to_province = {1: source, 2: target}
        screen.nation_data = {
            "A": {"materials": 0, "at_war_with": ["B"]},
            "B": {"at_war_with": ["A"]},
        }

        combat_processor.process_bombardments(screen)

        self.assertEqual(queries.get_fort_level(target), 4)
        self.assertEqual(target["building_queue"], [])
        self.assertEqual(screen.nation_data["A"]["materials"], 7000)
        self.assertEqual(gun["order"], {"type": "MOVE", "path": []})

    def test_ui_shows_fort_defense_as_a_separate_bonus(self):
        with patch.object(ui_elements, "draw_icon_row") as draw_row:
            ui_elements.draw_combat_stats(
                None, None, "", 0, 0, 100, 1, 0, 0, (200, 200, 200),
                labeled=False, defense_bonus=50,
            )

        entries = draw_row.call_args.args[3]
        self.assertIn((c.ICON_DEFENSE, "0 + 50"), entries)

    def test_fort_alignment_scales_with_camera_zoom(self):
        class Camera:
            zoom = 2.0

        class MapScreen:
            camera = Camera()

        map_screen = MapScreen()
        self.assertEqual(overlay_renderer.fort_horizontal_alignment(map_screen), 1)

        map_screen.camera.zoom = c.MAX_CAMERA_ZOOM
        self.assertEqual(overlay_renderer.fort_horizontal_alignment(map_screen), 8)


if __name__ == "__main__":
    unittest.main()
