"""Which unit the AI panic-builds on a threatened core, chosen from data.

The panic unit used to be the best tier of the Militia family, by name. With
militia set to two turns no panic build ever happened, and another unit made to
build in one turn was never considered. Now any buildable land unit that builds
in one turn and can be recruited in the province qualifies, and the purchase
loop's own valuation picks among them.

Legality is patched here: production_actions.prepare_production owns it, and
these tests are about the choice, not the recruitment rules.
"""

import unittest
from unittest.mock import patch

from data import queries
from map_logic.actions import production_actions
from map_logic.ai import ai_construction, ai_unit_eval
from tests.stub_map_screen import MapDouble, fill_state_defaults


def value(name, score, time=1, role=ai_unit_eval.ROLE_LINE):
    stats = {"production_time": time, "cost_materials": 10, "cost_manpower": 10, "cost_fuel": 0}
    return ai_unit_eval.UnitValue(name=name, role=role, score=score, combat=1.0, offense=0.5,
                                  durability=1.0, soak=100, pain=1.0, stats=stats, naval=False)


def legal_only(*names):
    """A stand-in prepare_production that accepts only these unit types."""
    def check(_context, _nation, _prov, _queue, intent, **_kw):
        if intent["unit_type"] not in names:
            raise ValueError("That province cannot recruit this unit.")
    return patch.object(production_actions, "prepare_production", side_effect=check)


class PanicUnitChoiceTests(unittest.TestCase):
    def pick(self, candidates, legal):
        with legal_only(*legal):
            return ai_construction._panic_unit(None, "Avaria", {"id": 1}, candidates, {})

    def test_the_best_one_turn_unit_wins(self):
        candidates = {"Militia": value("Militia", 1.0), "Cavalry": value("Cavalry", 2.0)}
        self.assertEqual(self.pick(candidates, ("Militia", "Cavalry")), "Cavalry")

    def test_a_unit_that_takes_longer_is_never_panic_built(self):
        candidates = {"Militia": value("Militia", 1.0, time=2),
                      "Tanks": value("Tanks", 9.0, time=6, role=ai_unit_eval.ROLE_ASSAULT)}
        self.assertIsNone(self.pick(candidates, ("Militia", "Tanks")))

    def test_slow_militia_leave_the_job_to_another_one_turn_unit(self):
        candidates = {"Militia": value("Militia", 5.0, time=2), "Cavalry": value("Cavalry", 1.0)}
        self.assertEqual(self.pick(candidates, ("Militia", "Cavalry")), "Cavalry")

    def test_a_unit_the_province_cannot_recruit_is_skipped(self):
        candidates = {"Militia": value("Militia", 1.0), "Cavalry": value("Cavalry", 2.0)}
        self.assertEqual(self.pick(candidates, ("Militia",)), "Militia")

    def test_ships_and_aircraft_are_not_panic_builds(self):
        candidates = {"Boat": value("Boat", 9.0, role=ai_unit_eval.ROLE_NAVAL),
                      "Plane": value("Plane", 9.0, role=ai_unit_eval.ROLE_AIR),
                      "Militia": value("Militia", 1.0)}
        self.assertEqual(self.pick(candidates, ("Boat", "Plane", "Militia")), "Militia")


class Screen(MapDouble):
    def __init__(self):
        home = {"id": 1, "json_key": "1", "owner": "Avaria", "cores": ["Avaria"],
                "neighbors": [2], "units": [], "unit_queue": [], "building_queue": [],
                "buildings": ["Basic Factory"], "terrain": "plains", "is_coastal": False}
        border = {"id": 2, "json_key": "2", "owner": "Borland", "cores": ["Borland"],
                  "neighbors": [1], "units": [{"type": "Rifles", "owner": "Borland", "health": 100}],
                  "unit_queue": [], "building_queue": [], "buildings": [], "terrain": "plains",
                  "is_coastal": False}
        self.world.map_data = {"1": home, "2": border}
        self.world.id_to_province = {1: home, 2: border}
        self.world.scenario_settings = {}
        self.world.nation_data = {
            "Avaria": {"at_war_with": ["Borland"], "puppets": [], "master": "", "faction": "",
                       "research": {}, "materials": 10000, "manpower": 10000, "fuel": 10000},
            "Borland": {"at_war_with": ["Avaria"], "puppets": [], "master": "", "faction": "",
                        "research": {}},
        }
        fill_state_defaults(self)


class PanicBuildTests(unittest.TestCase):
    def test_the_chosen_unit_is_what_gets_queued(self):
        screen = Screen()
        home = screen.world.id_to_province[1]
        queued = []
        candidates = {"Militia": value("Militia", 1.0), "Cavalry": value("Cavalry", 2.0)}
        state = {"upk_man": 0, "upk_mat": 0, "upk_fuel": 0}
        library = {name: v.stats for name, v in candidates.items()}
        with legal_only("Militia", "Cavalry"), \
                patch.object(production_actions, "submit_production",
                             side_effect=lambda *a, **k: queued.append(a[4]["unit_type"])):
            ai_construction._panic_build_and_tally_forces(
                screen, "Avaria", screen.world.nation_data["Avaria"], [home], library, state,
                {name: v.role for name, v in candidates.items()},
                panic_candidates=candidates)
        self.assertEqual(queued, ["Cavalry"])


def fighter(owner, attack, health):
    """A unit read entirely from its own fields; no library entry backs it."""
    return {"type": "Fixture Rifles", "owner": owner, "attack": attack, "defense": 0,
            "health": health, "max_health": health, "speed": 1}


class QueueClearingTests(unittest.TestCase):
    """A queue on a tile under attack is cleared only when the tile will fall.

    A captured province keeps its queues and the captor finishes them, so
    clearing a queue the enemy is about to take is a refund; clearing one on a
    tile that holds throws away progress. The pass now asks the shared battle
    forecast movement retreats by, instead of comparing raw strength sums.
    """

    REFUND = {"cost_materials": 40, "cost_manpower": 30, "cost_fuel": 0}

    def fight(self, ours, theirs):
        screen = Screen()
        home = screen.world.id_to_province[1]
        home["units"] = [ours, theirs]
        home["unit_queue"] = [{"unit_type": "Fixture Rifles", "turns_remaining": 3,
                               "refund": dict(self.REFUND)}]
        data = screen.world.nation_data["Avaria"]
        ai_construction._panic_build_and_tally_forces(
            screen, "Avaria", data, [home], {}, {"upk_man": 0, "upk_mat": 0, "upk_fuel": 0}, {})
        return home, data

    def test_a_tile_the_forecast_holds_keeps_its_queue(self):
        # The enemy hits hard but dies to the first return volley, while ours
        # outlasts that volley. Raw strength reads this as a losing fight.
        enemy_attack = 100
        ours = fighter("Avaria", attack=1, health=enemy_attack + 1)
        theirs = fighter("Borland", attack=enemy_attack, health=1)
        self.assertGreater(queries.calculate_unit_strength(theirs),
                           queries.calculate_unit_strength(ours))
        home, data = self.fight(ours, theirs)
        self.assertEqual(len(home["unit_queue"]), 1)
        self.assertEqual(data["materials"], 10000)

    def test_a_tile_about_to_fall_is_cleared_and_refunded(self):
        home, data = self.fight(fighter("Avaria", attack=1, health=10),
                                fighter("Borland", attack=1000, health=1000))
        self.assertEqual(home["unit_queue"], [])
        self.assertEqual(data["materials"], 10000 + self.REFUND["cost_materials"])
        self.assertEqual(data["manpower"], 10000 + self.REFUND["cost_manpower"])


if __name__ == "__main__":
    unittest.main()
