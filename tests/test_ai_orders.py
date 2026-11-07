"""Standing orders must survive the AI's per-turn movement re-plan.

ai_construction issues DISBAND, then ai_movement runs a few lines later in
prepare_turn and used to clear every AI unit's order back to MOVE. DISBAND is
only executed later still, by movement_processor, so the order was always gone
by the time anything could act on it -- which meant no AI unit had ever been
disbanded in the game's history: peacetime militia accumulated forever and the
obsolete-unit cull never ran once.
"""

import unittest


import data.constants as c
from tests.stub_map_screen import fill_state_defaults
from map_logic.ai import ai_movement


class FakeScreen:
    def __init__(self, units):
        self.map_data = {
            "p1": {"id": 1, "json_key": "p1", "owner": "Avaria", "neighbors": [],
                   "units": units}
        }
        self.id_to_province = {1: self.map_data["p1"]}
        self.nation_data = {"Avaria": {}}
        fill_state_defaults(self)


def unit(order):
    return {"type": "Militia I", "owner": "Avaria", "health": 500, "order": order}


class OrderResetTests(unittest.TestCase):

    def reset(self, units):
        screen = FakeScreen(units)
        return ai_movement._reset_orders_and_collect_units(screen, ["Avaria"])

    def test_a_disband_order_survives_the_reset(self):
        u = unit({"type": "DISBAND", "turns_left": 1})
        self.reset([u])
        self.assertEqual(u["order"]["type"], "DISBAND")

    def test_a_converting_unit_is_left_alone(self):
        u = unit({"type": "CONVERT", "turns_left": 2, "to": "Convoy"})
        self.reset([u])
        self.assertEqual(u["order"]["type"], "CONVERT")
        self.assertEqual(u["order"]["turns_left"], 2, "the timer must not restart")

    def test_a_committed_unit_is_not_offered_for_re_tasking(self):
        """Leaving the order alone but still handing the unit to the movement
        planner would just get the order overwritten a moment later."""
        busy = unit({"type": "DISBAND", "turns_left": 1})
        free = unit({"type": "MOVE", "path": [7]})
        nation_units, _ = self.reset([busy, free])
        collected = [u for u, _prov in nation_units["Avaria"]]
        self.assertEqual(collected, [free])

    def test_an_ordinary_move_order_is_still_cleared(self):
        """The re-plan is the point; a stale path must not survive."""
        u = unit({"type": "MOVE", "path": [3, 4, 5]})
        self.reset([u])
        self.assertEqual(u["order"], {"type": "MOVE", "path": []})

    def test_a_bombard_order_is_cleared_so_the_ai_re_aims(self):
        """Bombardment is decided fresh each turn from where the enemy is now."""
        u = unit({"type": "BOMBARD", "target_id": 9})
        self.reset([u])
        self.assertEqual(u["order"], {"type": "MOVE", "path": []})

    def test_the_preserved_set_is_the_shared_one(self):
        """Both this and the player's 'cannot move while busy' check read the
        same constant, so they cannot drift apart."""
        for kind in c.MULTI_TURN_ORDER_TYPES:
            self.assertIn(kind, c.ORDERS_BLOCKING_MOVEMENT)


class BombardmentScreen:
    """Three tiles in a row: home - near - far."""

    def __init__(self, near_units=(), far_units=()):
        self.map_data = {
            "home": {"id": 1, "json_key": "home", "owner": "Avaria", "neighbors": [2],
                     "units": []},
            "near": {"id": 2, "json_key": "near", "owner": "Bruland", "neighbors": [1, 3],
                     "units": list(near_units)},
            "far": {"id": 3, "json_key": "far", "owner": "Bruland", "neighbors": [2],
                    "units": list(far_units)},
        }
        self.id_to_province = {p["id"]: p for p in self.map_data.values()}
        self.nation_data = {"Avaria": {"at_war_with": ["Bruland"]},
                            "Bruland": {"at_war_with": ["Avaria"]}}


def enemy(attack=500, health=2000):
    return {"type": "Infantry Type 1936", "owner": "Bruland",
            "attack": attack, "defense": 0, "health": health}


class BombardmentTests(unittest.TestCase):
    """The AI had no bombardment code at all -- it bought guns, priced them for
    a barrage, then walked them into melee to swing a much smaller melee attack.
    """

    def setUp(self):
        from unittest.mock import patch
        from data import queries
        base = {"health": 200, "attack": 10, "defense": 0, "speed": 1,
                "cost_materials": 10, "cost_manpower": 10, "cost_fuel": 0, "production_time": 1}
        library = {"Fixture Gun": dict(base, bombard_attack=30, bombard_range=1),
                   "Fixture Long Gun": dict(base, bombard_attack=30, bombard_range=2),
                   "Fixture Rifles": dict(base)}
        self.enterContext(patch.object(queries, "get_unit_library", return_value=library))

    def gun(self, screen, kind="Fixture Gun"):
        unit = {"type": kind, "owner": "Avaria", "health": 200,
                "order": {"type": "MOVE", "path": []}}
        screen.map_data["home"]["units"].append(unit)
        return unit

    def test_a_gun_shells_an_adjacent_enemy_instead_of_charging_it(self):
        screen = BombardmentScreen(near_units=[enemy()])
        gun = self.gun(screen)
        fired = ai_movement._try_bombard(screen, "Avaria", gun, screen.map_data["home"])
        self.assertTrue(fired)
        self.assertEqual(gun["order"], {"type": "BOMBARD", "target_id": 2})

    def test_a_gun_with_nothing_in_range_is_left_to_move(self):
        screen = BombardmentScreen()
        gun = self.gun(screen)
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", gun, screen.map_data["home"]))
        self.assertEqual(gun["order"], {"type": "MOVE", "path": []})

    def test_an_ordinary_unit_never_bombards(self):
        screen = BombardmentScreen(near_units=[enemy()])
        rifles = self.gun(screen, "Fixture Rifles")
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", rifles,
                                                  screen.map_data["home"]))

    def test_range_two_reaches_past_the_next_tile(self):
        """The artificial long-range gun can reach the farther tile."""
        screen = BombardmentScreen(far_units=[enemy()])
        short, long = self.gun(screen, "Fixture Gun"), self.gun(screen, "Fixture Long Gun")
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", short,
                                                  screen.map_data["home"]))
        self.assertTrue(ai_movement._try_bombard(screen, "Avaria", long,
                                                 screen.map_data["home"]))
        self.assertEqual(long["order"]["target_id"], 3)

    def test_the_heaviest_enemy_stack_is_picked(self):
        screen = BombardmentScreen(near_units=[enemy(attack=10, health=10)],
                                   far_units=[enemy(attack=900, health=5000)])
        gun = self.gun(screen, "Fixture Long Gun")
        ai_movement._try_bombard(screen, "Avaria", gun, screen.map_data["home"])
        self.assertEqual(gun["order"]["target_id"], 3)

    def test_a_tile_holding_only_non_enemies_is_not_shelled(self):
        neutral = dict(enemy(), owner="Cirenia")
        screen = BombardmentScreen(near_units=[neutral])
        gun = self.gun(screen)
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", gun,
                                                  screen.map_data["home"]))

    def test_a_gun_riding_a_convoy_cannot_fire(self):
        """The loaded name is not in the unit library and not in the table."""
        screen = BombardmentScreen(near_units=[enemy()])
        loaded = self.gun(screen, "Convoy (Fixture Gun)")
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", loaded,
                                                  screen.map_data["home"]))


#: Everything _build_target_assignments hands to _assign_unit_orders. Kept in
#: one place and checked against the real builder below, because a hand-rolled
#: double that quietly lacks a key the real one supplies is a test that passes
#: for the wrong reason -- or, as here, fails in a file about bombardment.
ASSIGNMENT_KEYS = ("target_destinations", "naval_destinations",
                   "target_assignments", "naval_assignments",
                   "target_stacks", "naval_stacks", "target_capacity")


def empty_ctx(**over):
    ctx = {"unsafe_waters": set(), "friendly_nations": {"Avaria"}, "war_borders": set(),
           "peace_borders": set(), "coastal_borders": set(), "unclaimed_targets": set(),
           "active_battles": set(), "lost_battles": {}, "at_war": True}
    ctx.update({key: [] if key.endswith("destinations") else {} for key in ASSIGNMENT_KEYS})
    ctx.update(over)
    return ctx


class CtxFixtureTests(unittest.TestCase):
    def test_the_fixture_carries_what_the_real_builder_produces(self):
        built = ai_movement._build_target_assignments(
            [], {"peace_borders": set(), "coastal_borders": set(), "war_borders": set(),
                 "unclaimed_targets": set(), "all_unclaimed_coasts": set(),
                 "enemy_targets": set(), "all_enemy_coasts": set(),
                 "enemy_coastal_waters": set(), "expedition_targets": set()},
            {"active_battles": set(), "friendly_convoys": set(), "convoy_in_combat": set(),
             "convoy_near_ship": set(), "convoy_near_coast": set()},
            at_war=True)
        self.assertEqual(set(built), set(ASSIGNMENT_KEYS))


class BombardmentPriorityTests(unittest.TestCase):
    """Where the barrage sits relative to the retreat decisions.

    A gun that can shell should shell rather than charge -- but a fleet that is
    losing should still withdraw rather than stand and fire, which is what putting
    the attempt ahead of the naval retreat check would have caused.
    """

    def screen_with_a_losing_fleet(self):
        screen = BombardmentScreen()
        home = screen.map_data["home"]
        home["neighbors"] = [2, 3]
        screen.map_data["far"]["neighbors"] = [1, 2]
        # A sea tile to run to, and an overwhelming enemy fleet in our own.
        for key in ("home", "near", "far"):
            screen.map_data[key]["terrain"] = "ocean"
        ship = {"type": "Aircraft Carrier III", "owner": "Avaria", "health": 500,
                "attack": 10, "defense": 0, "order": {"type": "MOVE", "path": []}}
        home["units"] = [ship, dict(enemy(attack=99999, health=99999))]
        screen.map_data["near"]["units"] = [enemy()]
        return screen, ship

    def test_a_losing_fleet_withdraws_instead_of_shelling(self):
        screen, ship = self.screen_with_a_losing_fleet()
        units_info = [(ship, screen.map_data["home"])]
        battles = ai_movement._track_battles_and_convoys(
            screen, "Avaria", units_info, {"Avaria"}, set(), set(), set())
        self.assertEqual(battles["lost_battles"], {1})
        ai_movement._assign_unit_orders(
            screen, "Avaria", units_info, empty_ctx(lost_battles=battles["lost_battles"]),
            {1, 2, 3}, {1, 2, 3}, {})
        self.assertNotEqual(ship["order"].get("type"), "BOMBARD")
        self.assertTrue(ship["order"].get("path"), "it should be running")

    def test_a_gun_holding_a_contested_tile_fires_while_it_holds(self):
        """Bombarding does not stop a unit fighting where it stands, so a gun
        pinned in a melee has no reason not to also shell the tile next door."""
        screen = BombardmentScreen(near_units=[enemy()])
        home = screen.map_data["home"]
        gun = {"type": "Artillery III", "owner": "Avaria", "health": 200,
               "attack": 100, "defense": 0, "order": {"type": "MOVE", "path": []}}
        home["units"] = [gun, dict(enemy(attack=1, health=1))]
        ai_movement._assign_unit_orders(
            screen, "Avaria", [(gun, home)], empty_ctx(), {1, 2, 3}, set(), {})
        self.assertEqual(gun["order"], {"type": "BOMBARD", "target_id": 2})


class ImmediateLossAttackTests(unittest.TestCase):
    def context(self, target_id=2):
        ctx = empty_ctx(
            enemy_targets={target_id},
            target_destinations=[target_id],
            target_assignments={target_id: 0},
            target_stacks={target_id: 0},
            expedition_targets=set(),
        )
        return ctx

    def screen(self, defender):
        screen = BombardmentScreen(near_units=[defender])
        attacker_prov = screen.map_data["home"]
        attacker_prov["units"] = []
        attacker_prov["neighbors"] = [2]
        screen.map_data["near"]["neighbors"] = [1]
        return screen

    def attacker(self, attack=100, health=100):
        return {"type": "Infantry Type 1936", "owner": "Avaria",
                "attack": attack, "defense": 0, "health": health,
                "max_health": health, "speed": 1,
                "order": {"type": "MOVE", "path": []}}

    def defender(self, attack=100, health=100):
        return {"type": "Infantry Type 1936", "owner": "Bruland",
                "attack": attack, "defense": 0, "health": health,
                "max_health": health}

    def test_it_does_not_charge_when_the_first_exchange_wipes_the_attacker(self):
        screen = self.screen(self.defender(attack=1000, health=1000))
        attacker = self.attacker(attack=1, health=1)
        screen.map_data["home"]["units"] = [attacker]

        ai_movement._assign_unit_orders(
            screen, "Avaria", [(attacker, screen.map_data["home"])],
            self.context(), {1, 2}, set(), {1: [2], 2: [1]})

        self.assertEqual(attacker["order"], {"type": "MOVE", "path": []})

    def test_it_still_charges_when_the_attacker_can_survive(self):
        screen = self.screen(self.defender(attack=1, health=1000))
        attacker = self.attacker(attack=100, health=100)
        screen.map_data["home"]["units"] = [attacker]

        ai_movement._assign_unit_orders(
            screen, "Avaria", [(attacker, screen.map_data["home"])],
            self.context(), {1, 2}, set(), {1: [2], 2: [1]})

        self.assertEqual(attacker["order"]["path"], [2])


def fixture_unit(owner="Avaria", attack=100, health=100, max_health=None, defense=0):
    """A unit read entirely from its own fields; no library entry backs it."""
    return {"type": "Fixture Rifles", "owner": owner, "attack": attack,
            "defense": defense, "health": health,
            "max_health": max_health or health, "speed": 1,
            "order": {"type": "MOVE", "path": []}}


class GridScreen:
    """Provinces from {id: (owner, neighbors)}; Avaria and Bruland at war."""

    def __init__(self, layout, scenario_settings=None):
        self.map_data = {}
        for pid, (owner, neighbors) in layout.items():
            self.map_data[str(pid)] = {"id": pid, "json_key": str(pid), "owner": owner,
                                       "cores": [owner], "neighbors": list(neighbors),
                                       "units": [], "buildings": [], "terrain": "plains",
                                       "is_coastal": False}
        self.id_to_province = {p["id"]: p for p in self.map_data.values()}
        self.nation_data = {"Avaria": {"at_war_with": ["Bruland"]},
                            "Bruland": {"at_war_with": ["Avaria"]},
                            "Cirenia": {"at_war_with": []}}
        self.scenario_settings = dict(scenario_settings or {})
        fill_state_defaults(self)

    def place(self, pid, *units):
        self.id_to_province[pid]["units"].extend(units)
        return [(unit, self.id_to_province[pid]) for unit in units]


class WoundedUnitsDoNotChargeTests(unittest.TestCase):
    """A routed stack used to walk straight back into the tile it fled."""

    context = ImmediateLossAttackTests.context
    screen = ImmediateLossAttackTests.screen
    attacker = ImmediateLossAttackTests.attacker
    defender = ImmediateLossAttackTests.defender

    def test_a_wounded_unit_does_not_charge_a_target_it_would_survive(self):
        screen = self.screen(self.defender(attack=1, health=1000))
        hurt = self.attacker(attack=100, health=100)
        hurt["health"] = int(hurt["max_health"] * c.AI_REPAIR_HEALTH_FRACTION) - 1
        screen.map_data["home"]["units"] = [hurt]

        ai_movement._assign_unit_orders(
            screen, "Avaria", [(hurt, screen.map_data["home"])],
            self.context(), {1, 2}, set(), {1: [2], 2: [1]})

        self.assertEqual(hurt["order"], {"type": "MOVE", "path": []})


class LoneGuardTests(unittest.TestCase):
    """One guard stays on each quiet border, war or no war."""

    def test_a_lone_guard_holds_its_peace_border_in_wartime(self):
        # 1 and 3 border neutral Cirenia; 4 joins them. A guard stands on 1.
        screen = GridScreen({1: ("Avaria", [2, 4]), 2: ("Cirenia", [1]),
                             3: ("Avaria", [4, 5]), 4: ("Avaria", [1, 3]),
                             5: ("Cirenia", [3])})
        units_info = screen.place(1, fixture_unit())
        borders = {"peace_borders": {1, 3}, "coastal_borders": set(), "war_borders": set(),
                   "unclaimed_targets": set(), "all_unclaimed_coasts": set(),
                   "enemy_targets": set(), "all_enemy_coasts": set(),
                   "enemy_coastal_waters": set(), "expedition_targets": set()}
        battles = {"active_battles": set(), "lost_battles": set(), "friendly_convoys": set(),
                   "convoy_in_combat": set(), "convoy_near_ship": set(),
                   "convoy_near_coast": set()}
        built = ai_movement._build_target_assignments(units_info, borders, battles, at_war=True)
        # The weighted count carries the rear-guard penalty; the unit count does not.
        self.assertGreater(built["target_assignments"][1], 1)
        ctx = empty_ctx(**borders, **battles, **built)
        neighbors = {pid: list(p["neighbors"]) for pid, p in screen.id_to_province.items()}

        ai_movement._assign_unit_orders(screen, "Avaria", units_info, ctx,
                                        set(screen.id_to_province), set(), neighbors)

        self.assertEqual(units_info[0][0]["order"]["path"], [])


class SurpriseAttackSettingTests(unittest.TestCase):
    """The flag is read from this game's settings, not the global settings file."""

    def enemies(self, world_flag, global_flag):
        from unittest.mock import patch
        from data import queries
        screen = GridScreen({1: ("Avaria", [])}, {"surprise_attack": world_flag})
        screen.nation_data["Avaria"]["queued_ai_actions"] = [
            {"action": "WAR_DECLARATION", "target": "Cirenia"}]
        with patch.object(queries, "get_scenario_settings",
                          return_value={"surprise_attack": global_flag}):
            return ai_movement._gather_enemies(screen, "Avaria")

    def test_the_games_own_setting_wins(self):
        self.assertIn("Cirenia", self.enemies(True, False))
        self.assertNotIn("Cirenia", self.enemies(False, True))


class ForecastRetreatTests(unittest.TestCase):
    """A battle is lost when the shared forecast says so within a few exchanges."""

    def tile(self, ours, theirs, reinforcements=()):
        screen = GridScreen({1: ("Avaria", [2]), 2: ("Avaria", [1])})
        screen.place(1, *ours, *theirs)
        screen.place(2, *reinforcements)
        return screen, screen.id_to_province[1]

    def test_a_hopeless_fight_is_lost(self):
        screen, prov = self.tile([fixture_unit(attack=1)],
                                 [fixture_unit("Bruland", attack=1000, health=1000)])
        self.assertTrue(ai_movement._tile_is_lost(screen, "Avaria", prov, {"Avaria"}))

    def test_a_slow_defeat_counts_before_the_last_turn(self):
        """The old check read one exchange: a stack that would die over a few
        turns was never 'lost', so it bled out a unit at a time."""
        enemy_attack = 100
        health = enemy_attack * (c.AI_RETREAT_FORECAST_TURNS - 0.5)
        screen, prov = self.tile([fixture_unit(attack=1, health=health)],
                                 [fixture_unit("Bruland", attack=enemy_attack, health=100000)])
        self.assertTrue(ai_movement._tile_is_lost(screen, "Avaria", prov, {"Avaria"}))

    def test_a_winning_fight_is_not(self):
        screen, prov = self.tile([fixture_unit(attack=1000, health=1000)],
                                 [fixture_unit("Bruland", attack=1)])
        self.assertFalse(ai_movement._tile_is_lost(screen, "Avaria", prov, {"Avaria"}))

    def test_reinforcements_that_turn_it_keep_the_tile(self):
        help_ = [fixture_unit(attack=5000, health=5000)]
        screen, prov = self.tile([fixture_unit(attack=1)],
                                 [fixture_unit("Bruland", attack=1000, health=1000)], help_)
        self.assertFalse(ai_movement._tile_is_lost(screen, "Avaria", prov, {"Avaria"}, help_))


class RetreatTileTests(unittest.TestCase):
    """Each unit falls back to its own best tile."""

    def setUp(self):
        # 1 is the battle; 2 is plain, 3 has an enemy on it, 4 has a factory.
        self.screen = GridScreen({1: ("Avaria", [2, 3, 4]), 2: ("Avaria", [1]),
                                  3: ("Avaria", [1]), 4: ("Avaria", [1])})
        self.screen.place(3, fixture_unit("Bruland"))
        self.unit = fixture_unit()
        self.screen.place(1, self.unit)

    def pick(self, havens):
        return ai_movement._retreat_tile(self.screen, "Avaria", self.unit,
                                         self.screen.id_to_province[1], {"Avaria"},
                                         set(), havens)

    def test_a_repair_haven_comes_first(self):
        self.assertEqual(self.pick({4}), 4)

    def test_a_tile_with_a_visible_enemy_is_never_chosen(self):
        self.assertEqual(self.pick(set()), 2)


class CoastThreatTests(unittest.TestCase):
    """A quiet coast is guarded only when something could land on it.

    Tile 1 is Avaria's coast. Water 10 and 11 lie off it; across them is the
    shore at 20. saves/runv3 had more than half of some armies guarding beaches
    no enemy could reach.
    """

    def setUp(self):
        from unittest.mock import patch
        from data import queries
        library = dict(queries.get_unit_library())
        library["Fixture Warship"] = {"naval_unit": True, "attack": 500, "defense": 100,
                                      "health": 2000, "speed": 2, "cost_materials": 10,
                                      "cost_manpower": 10, "cost_fuel": 0}
        self.enterContext(patch.object(queries, "get_unit_library", return_value=library))

    def screen(self, shore_owner="Bruland", fog=False):
        screen = GridScreen({1: ("Avaria", [10]), 10: ("Ocean", [1, 11]),
                             11: ("Ocean", [10, 20]), 20: (shore_owner, [11])},
                            {"fog_of_war": fog})
        for pid in (10, 11):
            screen.id_to_province[pid]["terrain"] = "ocean"
        for pid in (1, 20):
            screen.id_to_province[pid]["is_coastal"] = True
        return screen

    def threatened(self, screen, enemies=("Bruland",)):
        return ai_movement._threatened_coasts(screen, "Avaria", {1}, list(enemies), {"Avaria"})

    def ship(self, owner, kind="Fixture Warship"):
        return {"type": kind, "owner": owner, "attack": 500, "defense": 100,
                "health": 2000, "max_health": 2000}

    def test_an_enemy_shore_across_the_water_is_a_threat(self):
        self.assertEqual(self.threatened(self.screen()), {1})

    def test_a_sea_with_only_friendly_shores_is_not(self):
        self.assertEqual(self.threatened(self.screen(shore_owner="Avaria")), set())

    def test_at_peace_no_coast_is_guarded(self):
        self.assertEqual(self.threatened(self.screen(), enemies=()), set())

    def test_naval_supremacy_removes_the_threat(self):
        screen = self.screen()
        screen.place(10, self.ship("Avaria"))
        self.assertEqual(self.threatened(screen), set())

    def test_but_not_against_an_equal_enemy_fleet(self):
        screen = self.screen()
        screen.place(10, self.ship("Avaria"))
        screen.place(11, self.ship("Bruland"))
        self.assertEqual(self.threatened(screen), {1})

    def test_a_visible_enemy_convoy_is_a_threat_even_with_no_enemy_shore(self):
        screen = self.screen(shore_owner="Cirenia")
        screen.place(11, fixture_unit("Bruland") | {"type": "Convoy (Fixture Rifles)"})
        self.assertEqual(self.threatened(screen), {1})

    def test_a_hidden_submarine_is_not(self):
        screen = self.screen(shore_owner="Cirenia", fog=True)
        screen.place(11, self.ship("Bruland", kind="Submarine Fixture"))
        self.assertEqual(self.threatened(screen), set())

    def test_only_threatened_quiet_coasts_are_destinations(self):
        screen = self.screen(shore_owner="Cirenia")
        borders = ai_movement._discover_borders_and_targets(
            screen, "Avaria", [screen.id_to_province[1]], ["Bruland"], {"Avaria"})
        self.assertEqual(borders["coastal_borders"], set())


if __name__ == "__main__":
    unittest.main()
