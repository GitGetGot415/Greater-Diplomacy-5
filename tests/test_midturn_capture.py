"""A tile that changed hands mid-turn is still a tile you can take.

saves/GERMAN TANK IN YUGOSLAVIA BUT NOT TAKEN, province 818, turn 22:

  * turn 21 left the tile Italian and empty
  * a Yugoslav Artillery VII walked in during movement and took it back, so the
    tile read Yugoslavia while _turn_start_owner still read Italy
  * a German Light Tank VI walked in behind it and killed the artillery
  * check_for_post_combat_captures judged the tank's right to the tile against
    the turn-start owner alone -- Italy, an Axis ally -- decided Germany was not
    allowed to capture anything here, and left an undefended enemy province in
    Yugoslav hands with a German tank parked on it

The substitution was meant to be permissive: it exists so that whoever happens
to move first in process_movement's step loop does not get an advantage from the
order of execution. But it replaced the current owner instead of joining it, so
it also threw away every capturer whose war is with the tile's *new* owner.
Both claims are read now, which is what these tests pin.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.turn_processing import combat_processor


class StubMapScreen:
    """Just enough of map_screen to run the capture pass standalone."""

    def __init__(self):
        self.map_data = {}
        self.id_to_province = {}
        self.nation_data = {}
        self.scenario_settings = {}
        self.tactical_mode = False
        # conquer_province repaints a pygame surface unless one of these says a
        # repaint would be pointless. There is no surface here, so it always is.
        self.is_editor = False
        self.viewing_ai_moves = True
        self.ai_is_thinking = False
        self.centers_need_update = False

    def add_nation(self, name, at_war_with=(), faction=""):
        self.nation_data[name] = {
            "name": name,
            "at_war_with": list(at_war_with),
            "allied_with": [],
            "claims": [],
            "faction": faction,
        }

    def add_province(self, pid, owner, turn_start_owner=None, units=(), cores=()):
        prov = {
            "id": pid,
            "owner": owner,
            "_turn_start_owner": owner if turn_start_owner is None else turn_start_owner,
            "terrain": "hills",
            "is_coastal": False,
            "cores": list(cores),
            "units": list(units),
            "building_queue": [],
        }
        self.map_data[pid] = prov
        self.id_to_province[pid] = prov
        return prov


def unit(owner, health=2450):
    return {
        "type": "Light Tank VI",
        "owner": owner,
        "order": {"type": "MOVE", "path": []},
        "speed": 3,
        "health": health,
        "max_health": 2800,
        "attack": 1950,
        "defense": 130,
        "morale": 82.5,
    }


def three_nations():
    """Germany and Italy are Axis allies; both are at war with Yugoslavia."""
    screen = StubMapScreen()
    screen.add_nation("German Reich", at_war_with=["Yugoslavia"], faction="Axis")
    screen.add_nation("Italy", at_war_with=["Yugoslavia"], faction="Axis")
    screen.add_nation("Yugoslavia", at_war_with=["German Reich", "Italy"])
    return screen


class MidTurnFlipTests(unittest.TestCase):
    def test_the_tile_its_enemy_retook_this_turn_is_still_takeable(self):
        """Province 818 itself: taken from an ally, retaken by an enemy, cleared."""
        screen = three_nations()
        tank = unit("German Reich")
        prov = screen.add_province(818, "Yugoslavia", turn_start_owner="Italy",
                                   units=[tank], cores=["Yugoslavia"])

        combat_processor.check_for_post_combat_captures(screen)

        self.assertEqual(prov["owner"], "German Reich")

    def test_a_tile_taken_from_an_ally_earlier_in_the_turn_is_still_takeable(self):
        """The case the turn-start reading was written for, still working.

        Italy took the tile from Yugoslavia during movement; the German unit
        standing on it is at peace with Italy but at war with the owner it had
        when the turn began, and must not be locked out by the order the two
        moves happened to resolve in.
        """
        screen = three_nations()
        tank = unit("German Reich")
        prov = screen.add_province(818, "Italy", turn_start_owner="Yugoslavia",
                                   units=[tank], cores=["Yugoslavia"])

        combat_processor.check_for_post_combat_captures(screen)

        self.assertEqual(prov["owner"], "German Reich")

    def test_an_ally_at_peace_with_both_owners_captures_nothing(self):
        """The rule the substitution was protecting: no stealing in peacetime."""
        screen = three_nations()
        screen.add_nation("Spain")
        tourist = unit("Spain")
        prov = screen.add_province(818, "Yugoslavia", turn_start_owner="Italy",
                                   units=[tourist], cores=["Yugoslavia"])

        combat_processor.check_for_post_combat_captures(screen)

        self.assertEqual(prov["owner"], "Yugoslavia")

    def test_the_turn_start_owner_still_standing_here_keeps_its_tile(self):
        """Unchanged by the union: a garrison that survived holds the ground."""
        screen = three_nations()
        prov = screen.add_province(818, "Italy", turn_start_owner="Yugoslavia",
                                   units=[unit("Yugoslavia"), unit("German Reich", health=10)],
                                   cores=["Yugoslavia"])

        combat_processor.check_for_post_combat_captures(screen)

        self.assertEqual(prov["owner"], "Yugoslavia")


if __name__ == "__main__":
    unittest.main()
