"""Standing orders must survive the AI's per-turn movement re-plan.

ai_construction issues DISBAND, then ai_movement runs a few lines later in
prepare_turn and used to clear every AI unit's order back to MOVE. DISBAND is
only executed later still, by movement_processor, so the order was always gone
by the time anything could act on it -- which meant no AI unit had ever been
disbanded in the game's history: peacetime militia accumulated forever and the
obsolete-unit cull never ran once.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_movement


class FakeScreen:
    def __init__(self, units):
        self.map_data = {
            "p1": {"id": 1, "json_key": "p1", "owner": "Avaria", "neighbors": [],
                   "units": units}
        }
        self.id_to_province = {1: self.map_data["p1"]}
        self.nation_data = {"Avaria": {}}


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

    def gun(self, kind="Artillery III"):
        return {"type": kind, "owner": "Avaria", "health": 200,
                "order": {"type": "MOVE", "path": []}}

    def test_a_gun_shells_an_adjacent_enemy_instead_of_charging_it(self):
        screen = BombardmentScreen(near_units=[enemy()])
        gun = self.gun()
        fired = ai_movement._try_bombard(screen, "Avaria", gun, screen.map_data["home"])
        self.assertTrue(fired)
        self.assertEqual(gun["order"], {"type": "BOMBARD", "target_id": 2})

    def test_a_gun_with_nothing_in_range_is_left_to_move(self):
        screen = BombardmentScreen()
        gun = self.gun()
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", gun, screen.map_data["home"]))
        self.assertEqual(gun["order"], {"type": "MOVE", "path": []})

    def test_an_ordinary_unit_never_bombards(self):
        screen = BombardmentScreen(near_units=[enemy()])
        rifles = self.gun("Infantry Type 1936")
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", rifles,
                                                  screen.map_data["home"]))

    def test_range_two_reaches_past_the_next_tile(self):
        """A Railgun outranges an Artillery piece, and must use it."""
        screen = BombardmentScreen(far_units=[enemy()])
        short, long = self.gun("Artillery III"), self.gun("WW2 Railroad Gun")
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", short,
                                                  screen.map_data["home"]))
        self.assertTrue(ai_movement._try_bombard(screen, "Avaria", long,
                                                 screen.map_data["home"]))
        self.assertEqual(long["order"]["target_id"], 3)

    def test_the_heaviest_enemy_stack_is_picked(self):
        screen = BombardmentScreen(near_units=[enemy(attack=10, health=10)],
                                   far_units=[enemy(attack=900, health=5000)])
        gun = self.gun("WW2 Railroad Gun")
        ai_movement._try_bombard(screen, "Avaria", gun, screen.map_data["home"])
        self.assertEqual(gun["order"]["target_id"], 3)

    def test_a_tile_holding_only_non_enemies_is_not_shelled(self):
        neutral = dict(enemy(), owner="Cirenia")
        screen = BombardmentScreen(near_units=[neutral])
        gun = self.gun()
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", gun,
                                                  screen.map_data["home"]))

    def test_a_gun_riding_a_convoy_cannot_fire(self):
        """The loaded name is not in the unit library and not in the table."""
        screen = BombardmentScreen(near_units=[enemy()])
        loaded = self.gun("Convoy (Artillery III)")
        self.assertFalse(ai_movement._try_bombard(screen, "Avaria", loaded,
                                                  screen.map_data["home"]))


#: Everything _build_target_assignments hands to _assign_unit_orders. Kept in
#: one place and checked against the real builder below, because a hand-rolled
#: double that quietly lacks a key the real one supplies is a test that passes
#: for the wrong reason -- or, as here, fails in a file about bombardment.
ASSIGNMENT_KEYS = ("target_destinations", "naval_destinations",
                   "target_assignments", "naval_assignments",
                   "target_stacks", "naval_stacks")


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
        ai_movement._assign_unit_orders(
            screen, "Avaria", [(ship, screen.map_data["home"])], empty_ctx(),
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


if __name__ == "__main__":
    unittest.main()
