"""Shared combat fixtures: a battle map stand-in, combat units, and damage totals."""

from tests.stub_map_screen import fill_state_defaults


class StubBattleMap:
    """Just enough of map_screen to run movement, combat, and capture passes standalone."""

    def __init__(self, terrain="hills"):
        self.default_terrain = terrain
        self.map_data = {}
        self.id_to_province = {}
        self.nation_data = {}
        self.scenario_settings = {}
        # conquer_province repaints a pygame surface unless one of these says a
        # repaint would be pointless. There is no surface here, so it always is.
        self.is_editor = False
        self.viewing_ai_moves = True
        self.ai_is_thinking = False
        self.centers_need_update = False
        fill_state_defaults(self)

    def add_nation(self, name, at_war_with=(), faction=""):
        self.nation_data[name] = {
            "name": name,
            "at_war_with": list(at_war_with),
            "claims": [],
            "faction": faction,
        }
        return self.nation_data[name]

    def add_province(self, pid, owner, units=(), terrain=None, cores=None, neighbors=(),
                     turn_start_owner=None):
        prov = {
            "id": pid,
            "owner": owner,
            "_turn_start_owner": owner if turn_start_owner is None else turn_start_owner,
            "terrain": terrain or self.default_terrain,
            "is_coastal": False,
            "cores": [owner] if cores is None else list(cores),
            "neighbors": list(neighbors),
            "units": list(units),
            "building_queue": [],
        }
        self.map_data[pid] = prov
        self.id_to_province[pid] = prov
        return prov


def unit(owner, attack=100, health=100000, defense=0, path=(), kind="Infantry", speed=1):
    """A unit with enough health to survive the fight, so damage is readable.

    Defense defaults to 0 because apply_group_damage subtracts it flat from each
    defender's share -- with defense in play, "how much did A deal" stops being
    a single number and starts depending on who it landed on.
    """
    return {
        "type": kind,
        "owner": owner,
        "order": {"type": "MOVE", "path": list(path)},
        "speed": speed,
        "health": health,
        "max_health": health,
        "attack": attack,
        "defense": defense,
        "morale": 50.0,
    }


def damage_taken(units):
    return sum(u["max_health"] - u["health"] for u in units)
