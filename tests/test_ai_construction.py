"""Which buildings the AI puts up, and how many.

Construction used to wait for a flat materials hoard, then build one thing a
turn, choosing factory or recruitment centre by shuffling a list. It now values
each option the way the Production screen describes it to a player -- what the
building adds to that province (queries.group_yields) -- net of its real cost,
with the payback rule research already used (ai_tech_eval.building_net_value),
priced in the nation's own scarcity.

Every building here is a fixture; nothing reads the real library.
"""

import unittest
from unittest.mock import patch

from data import queries
from map_logic.ai import ai_construction, ai_tuning
from tests.stub_map_screen import map_double


def building(group, **prod):
    stats = {"group": group, "time": 2, "cost_materials": 100, "cost_manpower": 0, "cost_fuel": 0}
    for res in ("materials", "manpower", "fuel"):
        stats[f"prod_{res}"] = prod.get(res, 0)
    return stats


LIBRARY = {
    "Fixture Works": building("industry", materials=50),
    "Fixture Hall": building("recruitment", manpower=50),
}


def province(pid, *, factory=True, neighbors=()):
    # "Basic Factory" is outside the fixture library: it only satisfies the
    # Production screen's rule that recruitment needs a factory on the tile.
    return {"id": pid, "json_key": str(pid), "owner": "Avaria", "cores": ["Avaria"],
            "buildings": ["Basic Factory"] if factory else [], "building_queue": [],
            "unit_queue": [], "units": [], "neighbors": list(neighbors), "terrain": "plains"}


def economy(income, upkeep):
    """The state the purchase loop hands construction: income and upkeep per resource."""
    return {
        "econ": {"total_inc": dict(income), "upkeep": dict(upkeep)},
        "inc_man": income["manpower"], "inc_mat": income["materials"], "inc_fuel": income["fuel"],
        "upk_man": upkeep["manpower"], "upk_mat": upkeep["materials"], "upk_fuel": upkeep["fuel"],
    }


PLENTY = {"manpower": 10000, "materials": 10000, "fuel": 10000}
NOTHING = {"manpower": 0, "materials": 0, "fuel": 0}


class ConstructionTests(unittest.TestCase):
    def build(self, provinces, stock, state, library=LIBRARY, extra=None):
        screen = map_double()
        for prov in provinces + list(extra or ()):
            screen.world.map_data[str(prov["id"])] = prov
            screen.world.id_to_province[prov["id"]] = prov
        data = {"research": {}, "at_war_with": [], **stock}
        screen.world.nation_data["Avaria"] = data
        screen.world.nation_data["Borland"] = {"research": {}, "at_war_with": list(
            ["Avaria"] if "Borland" in data["at_war_with"] else [])}
        with patch("data.queries.get_building_required_tech", return_value=(None, 0)):
            ai_construction._apply_construction_logic(screen, "Avaria", data, provinces, library, state)
        return [[entry["item_name"] for entry in prov["building_queue"]] for prov in provinces]

    def test_a_nation_short_of_manpower_builds_recruitment(self):
        state = economy(PLENTY, {**NOTHING, "manpower": PLENTY["manpower"]})
        queued = self.build([province(1)], {"materials": 100000, "manpower": 0, "fuel": 0}, state)
        self.assertEqual(queued, [["Fixture Hall"]])

    def test_a_nation_short_of_materials_builds_industry(self):
        state = economy(PLENTY, {**NOTHING, "materials": PLENTY["materials"]})
        queued = self.build([province(1)], {"materials": 1000, "manpower": 100000, "fuel": 0}, state)
        self.assertEqual(queued, [["Fixture Works"]])

    def test_no_more_than_the_cap_a_turn_and_one_per_province(self):
        count = ai_tuning.AI_MAX_BUILDINGS_PER_TURN + 1
        provinces = [province(pid, factory=False) for pid in range(1, count + 1)]
        queued = self.build(provinces, {"materials": 100000, "manpower": 0, "fuel": 0},
                            economy(PLENTY, NOTHING))
        expected = [["Fixture Works"]] * ai_tuning.AI_MAX_BUILDINGS_PER_TURN + [[]]
        self.assertEqual(queued, expected, "equal options go to the lowest province ids")

    def test_a_building_never_eats_into_the_runway(self):
        drain = 10
        income = {**PLENTY, "materials": drain}
        upkeep = {**NOTHING, "materials": 2 * drain}
        # The price the AI pays, after the politics multiplier, not the library figure.
        cost = queries.get_building_cost("Fixture Works", "Avaria", {}, LIBRARY,
                                         {"Avaria": {"research": {}}})["cost_materials"]
        enough = cost + drain * ai_tuning.AI_CONSTRUCTION_RESERVE_TURNS
        state = economy(income, upkeep)
        self.assertEqual(self.build([province(1, factory=False)],
                                    {"materials": enough - 1, "manpower": 0, "fuel": 0}, state), [[]])
        self.assertEqual(self.build([province(1, factory=False)],
                                    {"materials": enough, "manpower": 0, "fuel": 0}, state),
                         [["Fixture Works"]])

    def test_a_province_at_the_front_is_not_built_on(self):
        front = province(1, factory=False, neighbors=[2])
        enemy_tile = {"id": 2, "json_key": "2", "owner": "Borland", "cores": ["Borland"],
                      "buildings": [], "building_queue": [], "units": [
                          {"type": "Fixture Rifles", "owner": "Borland", "health": 100}],
                      "neighbors": [1], "terrain": "plains"}
        stock = {"materials": 100000, "manpower": 0, "fuel": 0, "at_war_with": ["Borland"]}
        queued = self.build([front], stock, economy(PLENTY, NOTHING), extra=[enemy_tile])
        self.assertEqual(queued, [[]])

        enemy_tile["units"] = []
        front["building_queue"] = []
        queued = self.build([front], stock, economy(PLENTY, NOTHING), extra=[enemy_tile])
        self.assertEqual(queued, [["Fixture Works"]], "with nobody next door it builds")

    def test_a_building_that_adds_nothing_is_not_worth_its_cost(self):
        library = {"Fixture Folly": building("industry")}
        queued = self.build([province(1, factory=False)], {"materials": 100000, "manpower": 0, "fuel": 0},
                            economy(PLENTY, NOTHING), library=library)
        self.assertEqual(queued, [[]])


if __name__ == "__main__":
    unittest.main()
