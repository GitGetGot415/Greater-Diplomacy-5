"""The AI must actually be able to reach the repair and upgrade orders.

Both mechanics existed and neither had ever been observed in a game. Repair
required industry on the tile a unit was *already* standing on, and nothing in
the AI ever sent one there, while _assign_unit_orders spends its time pushing
units toward the enemy -- so it could only fire on a unit that happened to be
shot up on top of its own factory. Upgrade additionally required a peace or
coastal *border*, which excludes every interior province in the game, which is
where a nation keeps its factories and their garrisons.

So this covers the walk home: committing to it, staying on it across the turn
boundary that wipes every other order, arriving, and giving up on it when the
destination stops being worth walking to.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_movement


def unit(owner="Avaria", u_type="Rifles", health=100, max_health=1000, speed=1):
    return {"type": u_type, "owner": owner, "health": health, "max_health": max_health,
            "speed": speed, "order": {"type": "MOVE", "path": []}}


def province(pid, units=(), owner="Avaria", neighbors=(), industry=False):
    return {"id": pid, "json_key": str(pid), "owner": owner, "cores": [owner],
            "neighbors": list(neighbors), "units": list(units), "unit_queue": [],
            "buildings": ["Basic Factory"] if industry else [],
            "terrain": "plains", "is_coastal": False}


class Screen:
    def __init__(self, provs, at_war=("Borland",)):
        self.map_data = {str(p["id"]): p for p in provs}
        self.id_to_province = {p["id"]: p for p in provs}
        self.scenario_settings = {}
        self.nation_data = {
            "Avaria": {"at_war_with": list(at_war), "allied_with": [], "puppets": [],
                       "master": "", "faction": "", "research": {},
                       "materials": 10000, "manpower": 10000, "fuel": 10000},
            "Borland": {"at_war_with": ["Avaria"], "allied_with": [], "puppets": [],
                        "master": "", "faction": "", "research": {}},
        }


def run(screen, provs, units_info, **ctx_over):
    """One maintenance pass over `units_info`, with a plausible ctx."""
    mine = [p for p in provs if p["owner"] == "Avaria"]
    ctx = {
        "war_borders": set(), "peace_borders": set(), "coastal_borders": set(),
        "active_battles": set(), "target_assignments": {},
        "friendly_nations": {"Avaria"}, "unsafe_waters": {},
    }
    ctx.update(ctx_over)
    ctx["repair_havens"] = ai_movement._repair_havens(screen, "Avaria", mine, ctx)

    allowed = {p["id"] for p in provs}
    neighbors = {p["id"]: list(p.get("neighbors", ())) for p in provs}
    ai_movement._assign_maintenance_orders(
        screen, "Avaria", units_info, ctx, allowed, set(), neighbors)
    return ctx


class HavenTests(unittest.TestCase):
    """Where a unit can be repaired at all."""

    def havens(self, provs, **ctx_over):
        screen = Screen(provs)
        ctx = {"war_borders": set(), "active_battles": set()}
        ctx.update(ctx_over)
        return ai_movement._repair_havens(
            screen, "Avaria", [p for p in provs if p["owner"] == "Avaria"], ctx)

    def test_a_factory_province_is_a_haven(self):
        self.assertEqual(self.havens([province(1, industry=True)]), {1})

    def test_a_province_with_no_industry_is_not(self):
        self.assertEqual(self.havens([province(1)]), set())

    def test_a_factory_with_an_enemy_standing_on_it_is_not(self):
        prov = province(1, [unit(owner="Borland")], industry=True)
        self.assertEqual(self.havens([prov]), set())

    def test_a_factory_on_the_war_border_is_not(self):
        """Arriving somewhere it is immediately in combat is where it came from."""
        self.assertEqual(self.havens([province(1, industry=True)], war_borders={1}), set())


class RepairOnTheSpotTests(unittest.TestCase):
    """A unit already standing on a factory."""

    def repair(self, health, **ctx_over):
        hurt = unit(health=health)
        prov = province(1, [hurt], industry=True)
        provs = [prov]
        run(Screen(provs), provs, [(hurt, prov)], **ctx_over)
        return hurt

    def test_a_hurt_unit_on_a_factory_repairs(self):
        self.assertEqual(self.repair(100)["order"]["type"], "REPAIR")

    def test_the_on_site_bar_is_looser_than_the_one_for_marching(self):
        """Sitting on the factory already, the turn is the whole cost."""
        health = int(1000 * (c.AI_REPAIR_HEALTH_FRACTION + c.AI_REPAIR_ON_SITE_FRACTION) / 2)
        self.assertEqual(self.repair(health)["order"]["type"], "REPAIR")

    def test_a_nearly_healthy_unit_is_left_alone(self):
        self.assertNotEqual(self.repair(999)["order"]["type"], "REPAIR")

    def test_a_unit_in_combat_does_not_repair(self):
        hurt = unit(health=100)
        prov = province(1, [hurt, unit(owner="Borland")], industry=True)
        provs = [prov]
        run(Screen(provs), provs, [(hurt, prov)])
        self.assertNotEqual(hurt["order"]["type"], "REPAIR")


class TheWalkHomeTests(unittest.TestCase):
    """The trip: 1 (front) -- 2 -- 3 (factory)."""

    def setup(self, health=100, **prov_over):
        hurt = unit(health=health)
        garrison = unit(health=1000)
        front = province(1, [hurt, garrison], neighbors=[2], **prov_over)
        middle = province(2, neighbors=[1, 3])
        home = province(3, neighbors=[2], industry=True)
        return hurt, [front, middle, home]

    def test_a_badly_hurt_unit_commits_to_the_march(self):
        hurt, provs = self.setup()
        run(Screen(provs), provs, [(hurt, provs[0])])
        self.assertEqual(hurt["repair_trip"], 3)
        self.assertEqual(hurt["order"]["path"], [2])

    def test_a_unit_only_mildly_hurt_does_not(self):
        """The march costs turns, so it takes the harder of the two bars."""
        hurt, provs = self.setup(health=int(1000 * c.AI_REPAIR_HEALTH_FRACTION) + 50)
        run(Screen(provs), provs, [(hurt, provs[0])])
        self.assertIsNone(hurt.get("repair_trip"))

    def test_the_trip_survives_the_order_wipe(self):
        """_reset_orders_and_collect_units clears every order every turn, which
        is why the commitment is a key on the unit and not an order."""
        hurt, provs = self.setup()
        screen = Screen(provs)
        run(screen, provs, [(hurt, provs[0])])

        ai_movement._reset_orders_and_collect_units(screen, ["Avaria"])
        self.assertEqual(hurt["repair_trip"], 3, "the walk home was forgotten")

    def test_it_keeps_walking_the_next_turn(self):
        hurt, provs = self.setup()
        hurt["repair_trip"] = 3
        run(Screen(provs), provs, [(hurt, provs[1])])  # now standing on the middle tile
        self.assertEqual(hurt["order"]["path"], [3])
        self.assertEqual(hurt["repair_trip"], 3)

    def test_arriving_starts_the_repair_and_ends_the_trip(self):
        hurt, provs = self.setup()
        hurt["repair_trip"] = 3
        provs[2]["units"] = [hurt]
        run(Screen(provs), provs, [(hurt, provs[2])])
        self.assertEqual(hurt["order"]["type"], "REPAIR")
        self.assertIsNone(hurt.get("repair_trip"))

    def test_a_destination_that_stops_being_a_haven_ends_the_trip(self):
        """Taken, overrun, or its factory levelled while the unit was walking."""
        hurt, provs = self.setup()
        hurt["repair_trip"] = 3
        provs[2]["buildings"] = []
        run(Screen(provs), provs, [(hurt, provs[1])])
        self.assertIsNone(hurt.get("repair_trip"))

    def test_healing_on_the_way_ends_the_trip(self):
        hurt, provs = self.setup()
        hurt["repair_trip"] = 3
        hurt["health"] = 1000
        run(Screen(provs), provs, [(hurt, provs[1])])
        self.assertIsNone(hurt.get("repair_trip"))


class NotAtTheCostOfTheFrontTests(unittest.TestCase):
    """The repair trip is the one order that walks a unit away from the war."""

    def try_trip(self, front_over=None, **ctx_over):
        hurt = unit(health=100)
        garrison = unit(health=1000)
        front = province(1, [hurt, garrison], neighbors=[2])
        front.update(front_over or {})
        middle = province(2, neighbors=[1, 3])
        home = province(3, neighbors=[2], industry=True)
        provs = [front, middle, home]
        run(Screen(provs), provs, [(hurt, front)], **ctx_over)
        return hurt.get("repair_trip")

    def test_it_will_not_leave_a_war_border(self):
        self.assertIsNone(self.try_trip(war_borders={1}))

    def test_it_will_not_leave_a_battle(self):
        self.assertIsNone(self.try_trip(active_battles={1}))

    def test_it_will_not_leave_a_tile_next_to_a_battle(self):
        self.assertIsNone(self.try_trip(active_battles={2}))

    def test_the_last_unit_on_a_tile_stays(self):
        hurt = unit(health=100)
        front = province(1, [hurt], neighbors=[2])
        provs = [front, province(2, neighbors=[1, 3]),
                 province(3, neighbors=[2], industry=True)]
        run(Screen(provs), provs, [(hurt, front)])
        self.assertIsNone(hurt.get("repair_trip"))

    def test_only_so_many_go_at_once(self):
        """Without a cap a bad turn at the front routs an army into the rear as
        a maintenance decision."""
        hurt = [unit(health=100) for _ in range(c.AI_MAX_REPAIR_TRIPS + 3)]
        front = province(1, hurt + [unit(health=1000)], neighbors=[2])
        provs = [front, province(2, neighbors=[1, 3]),
                 province(3, neighbors=[2], industry=True)]
        run(Screen(provs), provs, [(u, front) for u in hurt])
        walking = [u for u in hurt if u.get("repair_trip") is not None]
        self.assertEqual(len(walking), c.AI_MAX_REPAIR_TRIPS)

    def test_ships_and_convoys_do_not_march(self):
        """A ship cannot reach a factory and a convoy is mid-crossing."""
        for u_type in ("Destroyer I", "Convoy (Rifles)"):
            with self.subTest(u_type=u_type):
                sailor = unit(u_type=u_type, health=100)
                front = province(1, [sailor, unit(health=1000)], neighbors=[2])
                provs = [front, province(2, neighbors=[1, 3]),
                         province(3, neighbors=[2], industry=True)]
                run(Screen(provs), provs, [(sailor, front)])
                self.assertIsNone(sailor.get("repair_trip"))


class UpgradeReachabilityTests(unittest.TestCase):
    """An interior province is where the garrison with nothing to do lives."""

    def upgrade(self, prov_id=1, **ctx_over):
        idle = unit(health=1000, u_type="Militia I")
        prov = province(prov_id, [idle], industry=True)
        provs = [prov]

        import data.queries as queries
        real = queries.get_upgrade_target
        queries.get_upgrade_target = lambda t, r, lib, tree: "Militia II"
        try:
            run(Screen(provs, at_war=()), provs, [(idle, prov)], **ctx_over)
        finally:
            queries.get_upgrade_target = real
        return idle

    def test_a_quiet_interior_province_can_upgrade(self):
        """Not on any border, so the old peace/coastal-border test excluded it
        -- and a landlocked capital is in none of the three border sets."""
        self.assertEqual(self.upgrade()["order"]["type"], "UPGRADE")

    def test_a_war_border_does_not_upgrade(self):
        self.assertNotEqual(self.upgrade(war_borders={1})["order"]["type"], "UPGRADE")

    def test_a_tile_next_to_a_battle_does_not_upgrade(self):
        prov_neighbours = {"neighbors": [2]}
        idle = unit(health=1000, u_type="Militia I")
        prov = province(1, [idle], industry=True, **prov_neighbours)
        provs = [prov, province(2)]

        import data.queries as queries
        real = queries.get_upgrade_target
        queries.get_upgrade_target = lambda t, r, lib, tree: "Militia II"
        try:
            run(Screen(provs), provs, [(idle, prov)], active_battles={2})
        finally:
            queries.get_upgrade_target = real
        self.assertNotEqual(idle["order"]["type"], "UPGRADE")


class UpgradeIsAStandingOrderTests(unittest.TestCase):
    """UPGRADE was missing from MULTI_TURN_ORDER_TYPES."""

    def test_upgrade_blocks_movement_like_the_others(self):
        self.assertIn("UPGRADE", c.ORDERS_BLOCKING_MOVEMENT)

    def test_an_upgrade_order_survives_the_ai_order_wipe(self):
        upgrading = unit()
        upgrading["order"] = {"type": "UPGRADE", "turns_left": 1, "target_type": "Rifles II"}
        provs = [province(1, [upgrading])]
        screen = Screen(provs)

        ai_movement._reset_orders_and_collect_units(screen, ["Avaria"])

        self.assertEqual(upgrading["order"]["type"], "UPGRADE")


if __name__ == "__main__":
    unittest.main()
