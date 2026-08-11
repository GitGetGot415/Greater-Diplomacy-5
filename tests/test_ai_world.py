"""Parity between AIWorld's cached answers and the queries they stand in for.

AIWorld exists to make the strategy AI affordable, not to make it different.
Every method here has a counterpart in data/queries.py that the UI still calls,
and the two must agree exactly -- a cache that quietly rounds differently would
show up as the AI and the tooltip disagreeing about who is winning.

So this file is deliberately not a test of good answers. It builds one map with
every awkward case on it (a three-way border, a shared front with a third party
fighting on it, water separating two continents, cross-claims, a puppet, a
faction, an unplayable owner) and asserts method-by-method that the cached
answer is the uncached one.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.ai import ai_world


def unit(owner, attack=100, defense=10, health=1000):
    return {"owner": owner, "attack": attack, "defense": defense, "health": health}


def build_world():
    """A 12-province map laid out so every parity case has a witness.

    Tiles 1-3 Avaria, 4-6 Borland, 7-8 Carrow, 9 Dunmar, 10 unclaimed,
    11-12 ocean. Avaria/Borland and Borland/Carrow share land fronts; Carrow
    touches Avaria at tile 3/7 so there is a three-way corner. Dunmar is on the
    far side of the water, reachable only by sea.
    """
    layout = [
        # id, owner, terrain, neighbors, cores, units
        (1, "Avaria", "plains", [2, 11], ["Avaria"], [unit("Avaria", 120, 20)]),
        (2, "Avaria", "plains", [1, 3, 4], ["Avaria"], [unit("Avaria", 90), unit("Avaria", 300, 50)]),
        (3, "Avaria", "plains", [2, 4, 7], ["Avaria", "Carrow"], [unit("Avaria", 60)]),
        (4, "Borland", "plains", [2, 3, 5, 7], ["Borland"], [unit("Borland", 200, 30),
                                                             unit("Carrow", 80)]),
        (5, "Borland", "plains", [4, 6], ["Borland"], [unit("Borland", 150)]),
        (6, "Borland", "hills", [5, 10], ["Avaria"], []),
        (7, "Carrow", "plains", [3, 4, 8], ["Carrow"], [unit("Carrow", 175, 25)]),
        (8, "Carrow", "plains", [7, 12], ["Carrow"], [unit("Carrow", 40)]),
        (9, "Dunmar", "plains", [12], ["Dunmar"], [unit("Dunmar", 500, 100)]),
        (10, "Unclaimed", "plains", [6], [], []),
        (11, "Ocean", "ocean", [1, 12], [], []),
        (12, "Ocean", "ocean", [8, 9, 11], [], []),
    ]

    map_data, id_to_province = {}, {}
    for prov_id, owner, terrain, neighbors, cores, units in layout:
        prov = {"id": prov_id, "owner": owner, "terrain": terrain,
                "neighbors": list(neighbors), "cores": list(cores), "units": list(units)}
        map_data[str(prov_id)] = prov
        id_to_province[prov_id] = prov

    def nation(**over):
        base = {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
                "master": "", "faction": "", "is_faction_leader": False,
                "temp_modifiers": {}, "manpower": 5000, "materials": 8000, "fuel": 200}
        base.update(over)
        return base

    nation_data = {
        # Avaria and Borland are at war, and Carrow has a unit sitting on the
        # Borland tile fighting Borland too -- that is the third-party
        # distraction discount get_border_strength applies.
        "Avaria": nation(at_war_with=["Borland"], claims=[5],
                         faction="Entente", is_faction_leader=True,
                         puppets=["Dunmar"],
                         temp_modifiers={"Carrow": {"recent_war": -20, "general": 15}}),
        "Borland": nation(at_war_with=["Avaria", "Carrow"], claims=[3],
                          temp_modifiers={"Avaria": {"removed_cores": -30}}),
        "Carrow": nation(at_war_with=["Borland"], faction="Entente",
                         allied_with=["Avaria"]),
        "Dunmar": nation(master="Avaria", puppet_type=c.PUPPET_TYPE_AUTONOMOUS),
    }

    world = ai_world.AIWorld(map_data, nation_data, id_to_province, total_turns=7)
    return world, map_data, nation_data, id_to_province


NATIONS = ("Avaria", "Borland", "Carrow", "Dunmar")


class AIWorldParityTests(unittest.TestCase):
    def setUp(self):
        self.world, self.map_data, self.nation_data, self.id_to_province = build_world()

    def pairs(self):
        for a in NATIONS:
            for b in NATIONS:
                if a != b:
                    yield a, b

    # --- strength ------------------------------------------------------

    def test_military_strength_matches(self):
        for n in NATIONS:
            self.assertEqual(self.world.military(n),
                             queries.get_military_strength(n, self.map_data), n)

    def test_military_strength_of_an_armyless_nation_is_zero(self):
        """The sweep totals per owner, so a nation with no units is simply
        absent from the table -- it must still answer 0 rather than raise."""
        for absent in ("Unclaimed", "Nowhere"):
            self.assertEqual(self.world.military(absent),
                             queries.get_military_strength(absent, self.map_data), absent)

    def test_alliance_strength_matches(self):
        for n in NATIONS:
            self.assertEqual(self.world.alliance_strength(n),
                             queries.get_alliance_military_strength(n, self.map_data, self.nation_data), n)

    def test_economic_power_matches(self):
        for n in NATIONS:
            self.assertEqual(self.world.econ_power(n),
                             queries.get_economic_power(n, self.nation_data), n)

    def test_enemy_distraction_matches(self):
        for n in NATIONS:
            self.assertEqual(self.world.enemy_distraction(n),
                             queries.get_combined_enemy_strength(n, self.map_data, self.nation_data), n)

    def test_border_strength_matches_both_ways(self):
        for a, b in self.pairs():
            self.assertEqual(
                self.world.border_strength(a, b),
                queries.get_border_strength(a, b, self.map_data, self.id_to_province, self.nation_data),
                f"{a} vs {b}")

    def test_border_strength_is_symmetric_when_swapped(self):
        """The cache fills both orderings from one computation; they must agree."""
        for a, b in self.pairs():
            self.assertEqual(self.world.border_strength(a, b),
                             tuple(reversed(self.world.border_strength(b, a))), f"{a} vs {b}")

    def test_third_party_distraction_actually_fires(self):
        """Guards the fixture: tile 4 holds a Carrow unit at war with Borland,
        so Borland's strength there must be discounted when it faces Avaria."""
        undiscounted = sum(queries.calculate_unit_strength(u)
                           for u in self.id_to_province[4]["units"] if u["owner"] == "Borland")
        _, borland_front = self.world.border_strength("Avaria", "Borland")
        self.assertLess(borland_front, undiscounted + self.world.military("Borland"))
        self.assertGreater(borland_front, 0)

    # --- derived decisions ---------------------------------------------

    def test_thinks_it_can_win_matches(self):
        for a, b in self.pairs():
            self.assertEqual(
                self.world.thinks_it_can_win(a, b),
                queries.ai_thinks_it_can_win(a, b, self.map_data, self.nation_data, self.id_to_province),
                f"{a} vs {b}")

    def test_is_weaker_neighbor_matches(self):
        for a, b in self.pairs():
            self.assertEqual(self.world.is_weaker_neighbor(a, b),
                             queries.is_weaker_neighbor(a, b, self.map_data, self.nation_data),
                             f"{a} vs {b}")

    def test_power_ratio_agrees_with_its_own_thresholds(self):
        for a, b in self.pairs():
            border_ratio, global_ratio = self.world.power_ratio(a, b)
            expected = (border_ratio >= c.AI_WAR_STRENGTH_THRESHOLD
                        and global_ratio >= c.AI_GLOBAL_STRENGTH_THRESHOLD)
            self.assertEqual(self.world.thinks_it_can_win(a, b), expected, f"{a} vs {b}")

    # --- diplomacy -----------------------------------------------------

    def test_relation_matches_the_full_score(self):
        """Compared against the id_to_province form, i.e. claim penalty included."""
        for a, b in self.pairs():
            self.assertEqual(
                self.world.relation(a, b),
                queries.get_relation_score(a, b, self.nation_data, self.id_to_province),
                f"{a} -> {b}")

    def test_relation_counts_a_tile_once_when_cored_and_claimed(self):
        """Borland claims tile 3, which Carrow also cores -- the query counts a
        qualifying tile once however it qualifies, so the index must too."""
        self.nation_data["Carrow"]["claims"] = [3]
        world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)
        self.assertEqual(world.relation("Carrow", "Avaria"),
                         queries.get_relation_score("Carrow", "Avaria", self.nation_data,
                                                    self.id_to_province))

    def test_relation_to_self_is_zero(self):
        for n in NATIONS:
            self.assertEqual(self.world.relation(n, n), 0)

    def test_invalidate_relations_picks_up_a_new_modifier(self):
        before = self.world.relation("Avaria", "Carrow")
        queries.add_temporary_modifier("Avaria", "Carrow", "general", -50, self.nation_data)
        self.assertEqual(self.world.relation("Avaria", "Carrow"), before,
                         "stale until invalidated, which is the documented contract")
        self.world.invalidate_relations()
        self.assertEqual(self.world.relation("Avaria", "Carrow"), before - 50)

    def test_core_claim_targets_match(self):
        for n in NATIONS:
            self.assertEqual(self.world.core_claim_targets(n),
                             queries.get_nations_holding_our_cores_or_claims(n, self.map_data, self.nation_data),
                             n)

    def test_core_claim_targets_are_only_ever_consumed_in_sorted_order(self):
        """The war-target loop takes the first candidate that passes and breaks.

        A set compares equal however it iterates, so this returning the same
        nations as the query is not enough on its own -- if the two iterate them
        in different orders, the AI invades a different neighbour. Both callers
        in ai_diplomacy sort before iterating; this pins that the sorted forms
        agree, which is the property those callers actually depend on.
        """
        self.nation_data["Avaria"]["claims"] = [4, 5, 7, 8]
        world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)
        for n in NATIONS:
            self.assertEqual(
                sorted(world.core_claim_targets(n)),
                sorted(queries.get_nations_holding_our_cores_or_claims(
                    n, self.map_data, self.nation_data)), n)

    def test_core_claim_targets_exclude_unplayable_owners(self):
        self.map_data["10"]["cores"] = ["Avaria"]
        world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)
        self.assertNotIn("Unclaimed", world.core_claim_targets("Avaria"))

    def test_neighbors_match(self):
        for n in NATIONS:
            self.assertEqual(set(self.world.neighbors[n]),
                             queries.get_neighboring_nations(n, self.map_data, self.id_to_province),
                             n)

    def test_reachable_matches(self):
        for a, b in self.pairs():
            self.assertEqual(
                self.world.reachable(a, b),
                queries.is_nation_reachable(a, b, self.map_data, self.id_to_province, self.nation_data),
                f"{a} -> {b}")

    def test_dunmar_is_only_reachable_across_water(self):
        """Guards the fixture: without the ocean tiles Dunmar is an island."""
        self.assertNotIn("Dunmar", self.world.neighbors["Carrow"])
        self.assertTrue(self.world.reachable("Carrow", "Dunmar"))

    # --- indexes -------------------------------------------------------

    def test_provs_by_owner_matches_a_direct_scan(self):
        for n in NATIONS:
            expected = [p for p in self.map_data.values() if p.get("owner") == n]
            self.assertEqual(self.world.provs_by_owner[n], expected, n)

    def test_border_tiles_cover_both_sides_of_a_front(self):
        front = self.world.border_tiles[frozenset(("Avaria", "Borland"))]
        self.assertEqual(front, {2, 3, 4})

    def test_fixture_neighbour_lists_are_symmetric(self):
        """The invariant border_tiles leans on.

        AIWorld builds each front by sweeping every province once, so it reaches
        both sides of an adjacency from their own tiles. get_border_strength
        instead sweeps only the first nation's tiles and reaches across. The two
        agree exactly while neighbour lists are symmetric, which is a property of
        the map format -- build_national_border_graph assumes it too. If a map
        ever violates it the two would disagree about that one front, so the
        assumption is asserted here rather than left implicit.
        """
        for prov in self.map_data.values():
            for n_id in prov["neighbors"]:
                self.assertIn(prov["id"], self.id_to_province[n_id]["neighbors"],
                              f"{prov['id']} lists {n_id} but not vice versa")

    def test_coast_tiles_are_the_ones_touching_water(self):
        self.assertEqual(self.world.coast_tiles["Avaria"], {1})
        self.assertEqual(self.world.coast_tiles["Carrow"], {8})
        self.assertEqual(self.world.coast_tiles["Borland"], set())

    def test_combat_tiles_are_where_hostile_units_share_a_province(self):
        expected = {p["id"] for p in self.map_data.values()
                    if queries.is_province_in_active_combat(p, self.nation_data)}
        self.assertEqual(self.world.combat_tiles, expected)
        self.assertIn(4, expected, "fixture must contain at least one real battle")

    def test_rng_is_reproducible_for_a_given_turn(self):
        a = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province, total_turns=7)
        b = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province, total_turns=7)
        different_turn = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province, total_turns=8)
        self.assertEqual([a.rng.random() for _ in range(5)], [b.rng.random() for _ in range(5)])
        self.assertNotEqual([a.rng.random() for _ in range(5)],
                            [different_turn.rng.random() for _ in range(5)])


if __name__ == "__main__":
    unittest.main()
