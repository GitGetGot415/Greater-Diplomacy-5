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

import unittest
from unittest.mock import patch


import data.constants as c
from tests.stub_map_screen import fill_state_defaults
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
            "Avaria": {"at_war_with": list(at_war), "puppets": [],
                       "master": "", "faction": "", "research": {},
                       "materials": 10000, "manpower": 10000, "fuel": 10000},
            "Borland": {"at_war_with": ["Avaria"], "puppets": [],
                        "master": "", "faction": "", "research": {}},
        }
        fill_state_defaults(self)


def run(screen, provs, units_info, **ctx_over):
    """One maintenance pass over `units_info`, with a plausible ctx."""
    mine = [p for p in provs if p["owner"] == "Avaria"]
    ctx = {
        "war_borders": set(), "peace_borders": set(), "coastal_borders": set(),
        "active_battles": set(), "target_assignments": {},
        "friendly_nations": {"Avaria"}, "unsafe_waters": {},
    }
    ctx.update(ctx_over)
    ctx["repair_havens"] = ai_movement._repair_havens(screen, "Avaria", mine)

    allowed = {p["id"] for p in provs}
    neighbors = {p["id"]: list(p.get("neighbors", ())) for p in provs}
    ai_movement._assign_maintenance_orders(
        screen, "Avaria", units_info, ctx, allowed, set(), neighbors)
    return ctx


class HavenTests(unittest.TestCase):
    """Where a unit can be repaired at all."""

    def havens(self, provs):
        screen = Screen(provs)
        return ai_movement._repair_havens(
            screen, "Avaria", [p for p in provs if p["owner"] == "Avaria"])

    def test_a_factory_province_is_a_haven(self):
        self.assertEqual(self.havens([province(1, industry=True)]), {1})

    def test_a_province_with_no_industry_is_not(self):
        self.assertEqual(self.havens([province(1)]), set())

    def test_a_factory_with_an_enemy_standing_on_it_is_not(self):
        prov = province(1, [unit(owner="Borland")], industry=True)
        self.assertEqual(self.havens([prov]), set())

    def test_a_factory_on_the_war_border_still_is(self):
        """saves/NOT REPAIRING, province 295.

        A Soviet Heavy Tank III sat at 4% health on top of its own factory and
        marched off to take empty ground instead of repairing, because that
        tile borders four German provinces and the war-border test was being
        applied here. A unit already standing on a factory is not choosing
        where to be: it holds the tile either way, and at 4% health it is
        barely holding it. Where the tile sits does not enter into it.
        """
        self.assertEqual(self.havens([province(1, industry=True)]), {1})

    def test_a_war_border_is_still_not_somewhere_to_march_to(self):
        """The other half of the split -- see _march_havens."""
        havens = {1, 2}
        self.assertEqual(
            ai_movement._march_havens(havens, {"war_borders": {1}}), {2})


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

    def test_it_repairs_on_a_front_line_factory_too(self):
        """The province 295 case, end to end rather than at the haven set."""
        self.assertEqual(self.repair(100, war_borders={1})["order"]["type"], "REPAIR")

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
        provs[0]["units"].remove(hurt)
        provs[1]["units"].append(hurt)
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

    def try_trip(self, **ctx_over):
        hurt = unit(health=100)
        garrison = unit(health=1000)
        front = province(1, [hurt, garrison], neighbors=[2, 4])
        middle = province(2, neighbors=[1, 3])
        home = province(3, neighbors=[2], industry=True)
        side = province(4, neighbors=[1])
        provs = [front, middle, home, side]
        run(Screen(provs), provs, [(hurt, front)], **ctx_over)
        return hurt.get("repair_trip")

    def test_it_may_leave_a_war_border_another_unit_holds(self):
        """A stack that fell back from a lost battle stands on the war border.
        Keeping its wounded there is what sent them straight back in."""
        self.assertEqual(self.try_trip(war_borders={1}), 3)

    def test_it_may_leave_a_tile_next_to_a_battle(self):
        self.assertEqual(self.try_trip(active_battles={4}), 3)

    def test_it_will_not_march_to_a_war_border(self):
        """Arriving somewhere about to be attacked is what it was sent away
        from -- but only for a unit that is choosing where to be."""
        self.assertIsNone(self.try_trip(war_borders={3}))

    def test_it_will_not_walk_through_a_battle(self):
        self.assertIsNone(self.try_trip(active_battles={2}))

    def test_a_battle_tile_is_not_left_by_this_route(self):
        """Leaving a battle is _wounded_who_can_leave's decision."""
        self.assertIsNone(self.try_trip(active_battles={1}))

    def test_the_last_unit_on_a_tile_stays(self):
        hurt = unit(health=100)
        front = province(1, [hurt], neighbors=[2])
        provs = [front, province(2, neighbors=[1, 3]),
                 province(3, neighbors=[2], industry=True)]
        run(Screen(provs), provs, [(hurt, front)])
        self.assertIsNone(hurt.get("repair_trip"))

    def test_only_a_share_of_the_army_goes_at_once(self):
        """Without a cap a bad turn at the front routs an army into the rear as
        a maintenance decision. The cap scales with the army."""
        hurt = [unit(health=100) for _ in range(20)]
        front = province(1, hurt + [unit(health=1000)], neighbors=[2])
        provs = [front, province(2, neighbors=[1, 3]),
                 province(3, neighbors=[2], industry=True)]
        run(Screen(provs), provs, [(u, front) for u in hurt])
        walking = [u for u in hurt if u.get("repair_trip") is not None]
        self.assertEqual(len(walking), max(1, int(len(hurt) * c.AI_MAX_REPAIR_TRIP_SHARE)))

    def test_a_convoy_does_not_start_a_trip(self):
        """A convoy is a land unit mid-crossing; it finishes the crossing first."""
        sailor = unit(u_type="Convoy (Rifles)", health=100)
        front = province(1, [sailor, unit(health=1000)], neighbors=[2])
        provs = [front, province(2, neighbors=[1, 3]),
                 province(3, neighbors=[2], industry=True)]
        run(Screen(provs), provs, [(sailor, front)])
        self.assertIsNone(sailor.get("repair_trip"))


def sea(pid, neighbors=()):
    return {"id": pid, "json_key": str(pid), "owner": "Ocean", "cores": [],
            "neighbors": list(neighbors), "units": [], "unit_queue": [],
            "buildings": [], "terrain": "ocean", "is_coastal": False}


class ShipsSailHomeTests(unittest.TestCase):
    """A wounded warship sails to a friendly port with a factory."""

    def setUp(self):
        library = dict(ai_movement.queries.get_unit_library())
        library["Fixture Ship"] = {"naval_unit": True, "health": 1000, "attack": 10,
                                   "defense": 0, "speed": 1, "cost_materials": 10,
                                   "cost_manpower": 10, "cost_fuel": 0}
        self.enterContext(patch.object(ai_movement.queries, "get_unit_library",
                                       return_value=library))

    def fleet(self, port_industry=True):
        ship = unit(u_type="Fixture Ship", health=100)
        here = sea(10, neighbors=[11])
        here["units"] = [ship, unit(u_type="Fixture Ship", health=1000)]
        lane = sea(11, neighbors=[10, 3])
        port = province(3, neighbors=[11], industry=port_industry)
        port["is_coastal"] = True
        return ship, [here, lane, port]

    def sail(self, ship, provs):
        mine = [p for p in provs if p["owner"] == "Avaria"]
        screen = Screen(provs)
        ctx = {"war_borders": set(), "peace_borders": set(), "coastal_borders": set(),
               "active_battles": set(), "target_assignments": {},
               "friendly_nations": {"Avaria"}, "unsafe_waters": {}}
        ctx["repair_havens"] = ai_movement._repair_havens(screen, "Avaria", mine)
        water = {p["id"] for p in provs if p["terrain"] == "ocean"}
        neighbors = {p["id"]: list(p["neighbors"]) for p in provs}
        ai_movement._assign_maintenance_orders(
            screen, "Avaria", [(ship, provs[0])], ctx,
            {p["id"] for p in provs}, water, neighbors)

    def test_a_wounded_ship_sails_for_a_factory_port(self):
        ship, provs = self.fleet()
        self.sail(ship, provs)
        self.assertEqual(ship["repair_trip"], 3)
        self.assertEqual(ship["order"]["path"], [11])

    def test_a_port_without_industry_is_no_destination(self):
        ship, provs = self.fleet(port_industry=False)
        self.sail(ship, provs)
        self.assertIsNone(ship.get("repair_trip"))


class LeavingABattleTests(unittest.TestCase):
    """A wounded unit steps out of a fight the rest of its stack can hold.

    The front slots it holds are fixed by patching combat_rules.slots_held, so
    the rule is tested apart from combat-width tuning.
    """

    def battle(self, wounded=1, fresh=2, slots=2):
        hurt = [unit(health=100) for _ in range(wounded)]
        healthy = [unit(health=1000) for _ in range(fresh)]
        front = province(1, hurt + healthy + [unit(owner="Borland", health=1000)],
                         neighbors=[2])
        provs = [front, province(2, neighbors=[1, 3]),
                 province(3, neighbors=[2], industry=True)]
        with patch.object(ai_movement.combat_rules, "slots_held", return_value=slots):
            run(Screen(provs), provs, [(u, front) for u in hurt + healthy])
        return hurt

    def test_a_spare_wounded_unit_steps_out_and_heads_home(self):
        hurt = self.battle()[0]
        self.assertEqual(hurt["order"]["path"], [2])
        self.assertEqual(hurt["repair_trip"], 3)

    def test_not_when_the_front_would_be_short(self):
        hurt = self.battle(slots=3)[0]
        self.assertEqual(hurt["order"]["path"], [])
        self.assertIsNone(hurt.get("repair_trip"))

    def test_not_when_only_the_wounded_would_be_left(self):
        hurt = self.battle(wounded=2, fresh=0, slots=1)
        self.assertTrue(all(not u["order"]["path"] for u in hurt))


class UpgradeReachabilityTests(unittest.TestCase):
    """An interior province is where the garrison with nothing to do lives."""

    def upgrade(self, prov_id=1, industry=True, **ctx_over):
        idle = unit(health=1000, u_type="Militia I")
        prov = province(prov_id, [idle], industry=industry)
        provs = [prov]

        from data import queries
        from unittest.mock import patch
        from tests.research_fixtures import fixture_metadata
        library = {"Militia I": {"metadata": fixture_metadata(tier=1)},
                   "Militia II": {"metadata": fixture_metadata(tier=2, level=2)}}
        screen = Screen(provs, at_war=())
        screen.nation_data["Avaria"]["research"] = {"fixture_track": 2}
        with patch.object(queries, "get_unit_library", return_value=library):
            run(screen, provs, [(idle, prov)], **ctx_over)
        return idle

    def test_a_quiet_interior_province_can_upgrade(self):
        """Not on any border, so the old peace/coastal-border test excluded it
        -- and a landlocked capital is in none of the three border sets."""
        self.assertEqual(self.upgrade()["order"]["type"], "UPGRADE")

    def test_a_war_border_does_not_upgrade(self):
        self.assertNotEqual(self.upgrade(war_borders={1})["order"]["type"], "UPGRADE")

    def test_a_province_with_no_factory_does_not_upgrade(self):
        """The player's orders panel greys the Upgrade button out as "Needs
        Factory"; the AI used to ask nothing but whether the unit was idle.

        In saves/HOW DO YOU LAUNCH ARTILLERY FROM THE OCEAN two American
        divisions re-equipped themselves to Infantry Type 1943 while adrift in
        the sea off Spain -- no factory, no land, nothing but a quiet tile.
        A haven is a factory tile of ours with no enemy standing on it, which
        is the same pair of conditions the panel applies.
        """
        self.assertNotEqual(self.upgrade(industry=False)["order"]["type"], "UPGRADE")

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
