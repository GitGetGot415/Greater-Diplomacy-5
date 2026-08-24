"""Nothing that walks may end a turn standing in the ocean.

saves/HOW DO YOU LAUNCH ARTILLERY FROM THE OCEAN, province 620 (coastal_sea),
turn 24. Three loaded convoys sat there with an amphibious assault queued
against Spanish-held 769 on the shore. Spanish units crossed the other way, and
resolve_meeting_engagement asked whether *either* end of the swap was land
before unpacking every convoy in the fight -- so all three unloaded into the
sea. What was left was an Artillery VII and two infantry divisions floating in
open water; the artillery went on to shell Spain from there, and the AI
re-equipped both infantry to Infantry Type 1943 the turn after (see
tests/test_ai_maintenance.py for that half).

A side of a meeting engagement is still standing in its own province, so that is
the tile that decides whether it unloads -- which is how process_combat had
always read the same rule. process_beached_units is the net under it: it puts
anything found adrift back aboard a convoy, so the saves the old rule damaged
heal themselves on the next turn.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import queries
from map_logic.turn_processing import combat_processor, movement_processor


class StubMapScreen:
    """Just enough of map_screen to resolve one fight standalone."""

    def __init__(self):
        self.map_data = {}
        self.id_to_province = {}
        self.nation_data = {}
        self.tactical_mode = False
        self.is_editor = False
        self.viewing_ai_moves = True
        self.ai_is_thinking = False
        self.centers_need_update = False

    def add_nation(self, name, at_war_with=()):
        self.nation_data[name] = {
            "name": name,
            "at_war_with": list(at_war_with),
            "allied_with": [],
            "claims": [],
        }

    def add_province(self, pid, owner, units=(), terrain="forest", neighbors=()):
        prov = {
            "id": pid,
            "owner": owner,
            "_turn_start_owner": owner,
            "terrain": terrain,
            "is_coastal": False,
            "cores": [owner],
            "neighbors": list(neighbors),
            "units": list(units),
            "building_queue": [],
        }
        self.map_data[pid] = prov
        self.id_to_province[pid] = prov
        return prov


def unit(owner, kind="Infantry Type 1943", path=(), health=2000, attack=430,
         defense=0, naval=False):
    return {
        "type": kind,
        "owner": owner,
        "order": {"type": "MOVE", "path": list(path)},
        "speed": 1,
        "health": health,
        "max_health": health,
        "attack": attack,
        "defense": defense,
        "morale": 50.0,
        "naval_unit": naval,
    }


def convoy(owner, carrying="Artillery VII", path=()):
    """A loaded convoy, built the way process_conversions builds one."""
    u = unit(owner, kind=carrying, path=path, health=400, attack=480)
    queries.load_transport(u, "Convoy")
    return u


def shoreline_swap():
    """The 620/769 crossing: a convoy at sea, an invasion, and a defender.

    Returns (screen, sea province, land province, convoy afloat, convoy ashore).
    """
    screen = StubMapScreen()
    screen.add_nation("United States of America", at_war_with=["Spain"])
    screen.add_nation("Spain", at_war_with=["United States of America"])

    afloat = convoy("United States of America", path=[769])
    ashore = convoy("Spain", carrying="Infantry Type 1943", path=[620])

    sea = screen.add_province(620, "Ocean", units=[afloat], terrain="coastal_sea",
                              neighbors=[769])
    land = screen.add_province(769, "Spain", units=[ashore], neighbors=[620])
    return screen, sea, land, afloat, ashore


class MeetingEngagementUnpackingTests(unittest.TestCase):
    def test_a_convoy_fighting_from_the_sea_stays_loaded(self):
        screen, sea, land, afloat, ashore = shoreline_swap()

        combat_processor.resolve_meeting_engagement(
            sea, land, [afloat], [ashore], screen.nation_data)

        self.assertTrue(afloat["type"].startswith("Convoy"),
                        "a convoy was unloaded into open water")

    def test_a_convoy_fighting_from_the_shore_still_unpacks(self):
        screen, sea, land, afloat, ashore = shoreline_swap()

        combat_processor.resolve_meeting_engagement(
            sea, land, [afloat], [ashore], screen.nation_data)

        self.assertEqual(ashore["type"], "Infantry Type 1943",
                         "a convoy caught on land should unload and fight")

    def test_the_sides_are_read_the_same_way_round_either_way(self):
        """meeting_sides hands the pair over sorted by id, so the sea tile can
        arrive as either argument. The tile a unit stands on is what decides,
        not the slot it was passed in."""
        screen, sea, land, afloat, ashore = shoreline_swap()

        combat_processor.resolve_meeting_engagement(
            land, sea, [ashore], [afloat], screen.nation_data)

        self.assertTrue(afloat["type"].startswith("Convoy"))
        self.assertEqual(ashore["type"], "Infantry Type 1943")


class BeachedUnitTests(unittest.TestCase):
    """The net under the fix, and what repairs the save that found it."""

    def test_a_land_unit_adrift_is_put_back_aboard_a_convoy(self):
        screen = StubMapScreen()
        screen.add_nation("United Kingdom")
        gun = unit("United Kingdom", kind="Artillery VII", health=400, attack=480)
        gun["health"] = 200.0  # half strength, as the gun in province 620 was
        screen.add_province(620, "Ocean", units=[gun], terrain="coastal_sea")

        movement_processor.process_beached_units(screen)

        self.assertEqual(gun["type"], "Convoy (Artillery VII)")
        self.assertTrue(gun["naval_unit"])
        # Health rides across as a percentage both ways, so the round trip is
        # lossless: half a gun goes aboard and half a gun comes ashore.
        queries.revert_transport(gun)
        self.assertEqual(gun["type"], "Artillery VII")
        self.assertAlmostEqual(gun["health"], 200.0)

    def test_it_keeps_its_orders_so_a_landing_still_happens(self):
        screen = StubMapScreen()
        screen.add_nation("United States of America")
        stranded = unit("United States of America", path=[769])
        screen.add_province(620, "Ocean", units=[stranded], terrain="coastal_sea",
                            neighbors=[769])

        movement_processor.process_beached_units(screen)

        self.assertEqual(stranded["order"]["path"], [769])

    def test_a_warship_at_sea_is_left_alone(self):
        screen = StubMapScreen()
        screen.add_nation("United States of America")
        ship = unit("United States of America", kind="Destroyer VIII", naval=True)
        screen.add_province(620, "Ocean", units=[ship], terrain="coastal_sea")

        movement_processor.process_beached_units(screen)

        self.assertEqual(ship["type"], "Destroyer VIII")

    def test_an_army_on_dry_land_is_left_alone(self):
        screen = StubMapScreen()
        screen.add_nation("Spain")
        infantry = unit("Spain")
        screen.add_province(769, "Spain", units=[infantry])

        movement_processor.process_beached_units(screen)

        self.assertEqual(infantry["type"], "Infantry Type 1943")


class BombardmentFromWaterTests(unittest.TestCase):
    """Field guns have nothing to stand on out there. Battleships do."""

    def barrage(self, gun_type, naval):
        screen = StubMapScreen()
        screen.add_nation("United Kingdom", at_war_with=["Spain"])
        screen.add_nation("Spain", at_war_with=["United Kingdom"])

        gun = unit("United Kingdom", kind=gun_type, attack=480, naval=naval)
        gun["order"] = {"type": "BOMBARD", "target_id": 769}
        target = unit("Spain")

        screen.add_province(620, "Ocean", units=[gun], terrain="coastal_sea",
                            neighbors=[769])
        screen.add_province(769, "Spain", units=[target], neighbors=[620])

        combat_processor.process_bombardments(screen)
        return target

    def test_an_artillery_piece_afloat_cannot_fire(self):
        target = self.barrage("Artillery VII", naval=False)
        self.assertEqual(target["health"], target["max_health"])

    def test_a_battleship_still_shells_the_shore(self):
        target = self.barrage("Battleship", naval=True)
        self.assertLess(target["health"], target["max_health"])


if __name__ == "__main__":
    unittest.main()
