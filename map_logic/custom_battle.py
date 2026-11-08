"""Standalone land battles with optional player control and no campaign state."""

import math
import random
from dataclasses import dataclass, field

import data.constants as c
from data import queries
from data.state_access import session_for, world_for
from map_logic.system32 import combat_forecast, combat_rules


# These values translate campaign statistics into a real-time battlefield.
# They do not change campaign combat or add persistent unit statistics.
FIXED_STEP = 1.0 / 30.0
MOVE_PIXELS_PER_SPEED = 35.0
FIRE_INTERVAL = 2.0
WEAPON_RANGE = 400.0
BOMBARD_RANGE_PIXELS = 220.0
# Direct shots. Arcing artillery shells keep c.CUSTOM_BATTLE_PROJECTILE_SPEED as their ground speed.
DIRECT_PROJECTILE_SPEED = 1300.0
ARTILLERY_BLAST_RADIUS = 40.0
UNIT_RADIUS = 12.0
AI_HOLD_RANGE = 0.85  # AI units stop closing in at this share of their weapon range.
AIM_TOLERANCE = math.radians(4)  # AI units fire once the gun points this close to the aim angle.
RETARGET_SECONDS = 0.25  # AI units choose the nearest enemy again this often.
# Collision and separation cells, and the coarser cells of the nearest-enemy search.
GRID_CELL = 64.0
TARGET_CELL = 256.0
SPAWN_ROWS = 8
DIVISION_GAP = 120.0  # Between division centers at deployment.
SUBUNIT_GAP = 26.0  # Between the sub-units of one division.
# Distance between the two armies' front ranks at deployment, centered on the battlefield.
# A full army of 64 divisions still fits behind its front rank.
SPAWN_FRONT_GAP = 2000.0
RANDOM_ARMY_MIN_UNITS = 3
RANDOM_ARMY_MAX_UNITS = 5
RANDOM_UNIT_AGE_LIMIT = 5
# Placeholder countries for the normal-game forecast; real country IDs never use these names.
FORECAST_NATIONS = ("Custom Battle Friendly Army", "Custom Battle Enemy Army")
# Library families that get their own silhouette; sizes are in screens/game/custom_battle.py.
FAMILY_SHAPES = {
    "Light Tank": "light_tank",
    "Armored Car": "armored_car",
    "WW1 Armored Car": "armored_car",
    "Heavy Tank": "heavy_tank",
    "WW1 Railroad Gun": "railroad_gun",
    "WW2 Railroad Gun": "railroad_gun",
    "Landkreuzer P.1000 Ratte": "colossus",
    "Landkreuzer P.1500 Monster": "colossus",
    "Railgun": "railgun",  # Drawn like the Landkreuzers, but aims with a cone.
    "Motorized Infantry Type": "motorized",
    "Mechanized Infantry Type": "mechanized",
    "Infantry Fighting Vehicle Type": "ifv",
}
# Sub-units a division at full health becomes on the battlefield. A wounded division brings fewer.
SUBUNIT_COUNTS = {
    "infantry": 10, "cavalry": 10, "motorized": 10, "mechanized": 10, "ifv": 10,
    "armored_car": 5, "light_tank": 5, "tank": 5, "heavy_tank": 5, "artillery": 5,
    "railroad_gun": 1, "colossus": 1, "railgun": 1,
}
# (seconds to reach full speed, top turn speed in degrees per second, seconds to reach top turn speed)
MOBILITY = {
    "infantry": (0.3, 180, 0.15), "cavalry": (0.6, 150, 0.25),
    "motorized": (0.8, 120, 0.3), "mechanized": (0.9, 110, 0.3), "ifv": (1.0, 100, 0.35),
    "armored_car": (0.8, 130, 0.3), "light_tank": (1.0, 110, 0.35),
    "tank": (1.2, 90, 0.4), "heavy_tank": (1.6, 70, 0.5), "artillery": (1.2, 60, 0.4),
    "railroad_gun": (2.5, 25, 0.8), "colossus": (2.5, 30, 0.8), "railgun": (2.5, 25, 0.8),
}
# (firing cone width in degrees, or None to aim all the way around; gun turn speed in degrees per second)
AIM = {
    "infantry": (90, 240), "cavalry": (90, 240),
    "motorized": (90, 200), "mechanized": (90, 200), "ifv": (90, 180),
    "artillery": (60, 60), "railroad_gun": (20, 30), "railgun": (20, 30),
    "armored_car": (None, 180), "light_tank": (None, 150), "tank": (None, 120),
    "heavy_tank": (None, 90), "colossus": (None, 45),
}


def valid_starting_health(health, max_health):
    """A participating unit must start alive and within its library health limit."""
    return (isinstance(health, (int, float)) and not isinstance(health, bool)
            and 0 < health <= max_health)


def land_unit_types(library):
    """Keep library identifiers, including levels, and exclude ships and aircraft."""
    return [name for name, stats in library.items()
            if not stats.get("naval_unit") and not stats.get("air_role")]


def campaign_forces(player_unit, province, nation_data, library):
    """The campaign units (friendly, enemy) fighting a tactical player's land unit on its tile.

    The player's unit leads the friendly list. Returns None when that unit is not a land
    unit or no hostile land unit shares its tile. Each list holds at most one army's units.
    """
    land = set(land_unit_types(library))
    country = queries.get_unit_combat_owner(player_unit)
    enemies = queries.get_enemies(country, nation_data)
    friends = {country, *queries.get_all_friendly_nations(country, nation_data)}

    def fighting(units):
        return [unit for unit in units
                if unit.get("type") in land and unit.get("health", 0) > 0
                ][:c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE]

    units = province.get("units", [])
    friendly = fighting([player_unit] + [unit for unit in units if unit is not player_unit
                                         and queries.get_unit_combat_owner(unit) in friends])
    enemy = fighting([unit for unit in units if queries.get_unit_combat_owner(unit) in enemies])
    if not friendly or not enemy or friendly[0] is not player_unit:
        return None
    return friendly, enemy


def tactical_encounter(context, province):
    """The (friendly, enemy) campaign units of the tactical battle held on ``province``, or None.

    Only the tile holding the tactical player's land unit has one, and only while hostile land
    units share it. The battle deals that tile's damage, so campaign combat must skip the tile.
    """
    session = session_for(context)
    # Lightweight test doubles carry no tactical state.
    unit = getattr(session, "tactical_mode", False) and getattr(session, "player_unit", None)
    if not unit or not any(other is unit for other in province.get("units", [])):
        return None
    return campaign_forces(unit, province, world_for(context).nation_data, queries.get_unit_library(context))


def campaign_roster(units, library):
    """Battle roster entries for campaign units, keeping each unit's fraction of health."""
    roster = []
    for unit in units:
        entry = queries.create_unit_dict(unit["type"], unit["owner"], library)
        entry["health"] = unit["health"] / unit["max_health"] * entry["max_health"]
        roster.append(entry)
    return roster


def apply_campaign_result(simulation, units, province):
    """Write a finished battle back: each unit keeps its division's fraction of health and the dead are removed.

    ``units`` are the campaign units in roster order, friendly army then enemy army.
    """
    for index, unit in enumerate(units):
        unit["health"] = simulation.division_health_fraction(index) * unit["max_health"]
    province["units"] = [unit for unit in province["units"] if unit.get("health", 0) > 0]


def normal_game_forecast(friendly, enemy):
    """How this fight would end in the normal game: (winning army index or None, turns or None).

    The normal game's turn-by-turn forecast resolves it. Each army stands in for one of two
    countries at war with each other, so nationality, terrain width, forts, politics, and
    conscription do not apply. ``turns`` is None when the forecast finds no end.
    """
    nation_data = {nation: {"at_war_with": [other]}
                   for nation, other in zip(FORECAST_NATIONS, reversed(FORECAST_NATIONS))}
    sides = [[dict(unit, owner=nation) for unit in roster] for nation, roster in zip(FORECAST_NATIONS, (friendly, enemy))]
    outcome = combat_forecast.estimated_combat_outcome(sides, nation_data)
    return outcome["winner_side"], outcome["turns"]


def land_unit_types_for_year(library, year):
    """Choose the latest unlocked land tiers less than five research years old."""
    land = set(land_unit_types(library))
    candidates = []
    for name in queries.get_latest_units_for_year(library, year):
        if name not in land:
            continue
        researched = queries.get_unit_research_year(name, library)
        if researched is not None and 0 <= year - researched < RANDOM_UNIT_AGE_LIMIT:
            candidates.append(name)
    return candidates


def random_armies(candidates, *, rng=None):
    """Independently choose each army's size and types; repeated units are allowed."""
    if not candidates:
        raise ValueError("No land units are available for the selected year.")
    rng = random if rng is None else rng
    return [[rng.choice(candidates)
             for _ in range(rng.randint(RANDOM_ARMY_MIN_UNITS, RANDOM_ARMY_MAX_UNITS))]
            for side in (0, 1)]


def unit_shape(name, library):
    """Choose prototype geometry from existing family and capability metadata."""
    stats = library[name]
    family = queries.get_unit_metadata(name, library).get("family", "")
    # Named families come first: the railroad guns and super-tanks also bombard.
    if family in FAMILY_SHAPES:
        return FAMILY_SHAPES[family]
    if queries.get_bombardment_range(name, stats) > 0:
        return "artillery"
    if family == "Cavalry":
        return "cavalry"
    if queries.classify_unit_group(family, stats) == queries.UNIT_GROUP_TANKS:
        return "tank"
    # Vehicle infantry retain their own library family instead of being infantry circles.
    if family in {"Motorized Infantry Type", "Mechanized Infantry Type", "Infantry Fighting Vehicle Type"}:
        return "tank"
    return "infantry"


def firing_cone(shape):
    """The firing cone's full width in radians, or None when the gun aims all the way around."""
    cone = AIM[shape][0]
    return None if cone is None else math.radians(cone)


def shot_reach(fighter, aim_point):
    """How far a player's shot travels: an arcing shell lands at the pointer, up to the weapon's range."""
    if aim_point is None:
        return fighter.weapon_range
    return min(fighter.weapon_range, math.hypot(aim_point[0] - fighter.x, aim_point[1] - fighter.y))


def _wrap(angle):
    """The same angle between -pi and pi."""
    return (angle + math.pi) % math.tau - math.pi


def _approach(value, goal, step):
    return min(goal, value + step) if value < goal else max(goal, value - step)


@dataclass(eq=False)
class Fighter:
    """One sub-unit on the battlefield. A division becomes one or more sub-units."""

    data: dict
    side: int
    x: float
    y: float
    shape: str
    weapon_range: float
    attack_field: str
    division: int = 0  # Index into BattleSimulation.divisions.
    cooldown: float = 0.0
    angle: float = 0.0  # Hull heading: movement follows it.
    aim: float = 0.0  # Gun heading: shots follow it.
    speed: float = 0.0  # Signed forward speed in pixels per second.
    turn_rate: float = 0.0  # Radians per second.
    vx: float = 0.0
    vy: float = 0.0
    target: object = None  # AI only: the enemy it closes on and shoots at.
    retarget: float = 0.0  # AI only: seconds until it chooses the nearest enemy again.

    @property
    def alive(self):
        return self.data["health"] > 0

    @property
    def arcing(self):
        """Artillery-type weapons lob shells that hit only where they land."""
        return self.attack_field == "bombard_attack"

    @property
    def max_speed(self):
        return max(0, self.data["speed"]) * MOVE_PIXELS_PER_SPEED


@dataclass
class Projectile:
    """A shot in flight.

    A direct shot hits the first enemy it crosses. An arcing shell (``flight`` above zero)
    passes over everything and hits every enemy near the point where it lands.
    """

    source: Fighter
    source_data: dict  # The shooter as it fired, so a shot still lands after the shooter dies.
    x: float  # Ground position.
    y: float
    vx: float
    vy: float
    remaining: float  # Seconds left in flight.
    flight: float = 0.0  # Total seconds an arcing shell flies; zero for direct shots.

    @property
    def arcing(self):
        return self.flight > 0

    @property
    def progress(self):
        """How far through its flight an arcing shell is, from 0 to 1."""
        return 1.0 - self.remaining / self.flight if self.flight else 0.0


class _Grid:
    """Buckets one army's living sub-units by cell so nearby lookups skip the rest of the field."""

    def __init__(self, fighters, cell):
        self.cell = cell
        self.cells = {}
        for fighter in fighters:
            self.cells.setdefault(self._key(fighter.x, fighter.y), []).append(fighter)
        self.reach = math.ceil(max(c.CUSTOM_BATTLE_ARENA_SIZE) / cell) + 1

    def _key(self, x, y):
        return int(x // self.cell), int(y // self.cell)

    def within(self, left, top, right, bottom):
        """Sub-units in the cells touching this box."""
        x0, y0 = self._key(left, top)
        x1, y1 = self._key(right, bottom)
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                yield from self.cells.get((cx, cy), ())

    def around(self, x, y, radius):
        return self.within(x - radius, y - radius, x + radius, y + radius)

    def nearest(self, x, y):
        best, best_distance = None, math.inf
        cx, cy = self._key(x, y)
        for ring in range(self.reach + 1):
            for key in self._ring(cx, cy, ring):
                for fighter in self.cells.get(key, ()):
                    distance = (fighter.x - x) ** 2 + (fighter.y - y) ** 2
                    if distance < best_distance:
                        best, best_distance = fighter, distance
            # Sub-units in later rings are at least this many whole cells away.
            if best is not None and best_distance <= (ring * self.cell) ** 2:
                break
        return best

    @staticmethod
    def _ring(cx, cy, ring):
        if ring == 0:
            yield cx, cy
            return
        for dx in range(-ring, ring + 1):
            yield cx + dx, cy - ring
            yield cx + dx, cy + ring
        for dy in range(1 - ring, ring):
            yield cx - ring, cy + dy
            yield cx + ring, cy + dy


@dataclass
class BattleSimulation:
    """Accept unit names at full health or unit records with owner and starting health.

    Each roster entry is a division. It becomes one or more sub-units (``SUBUNIT_COUNTS``)
    that share the division's health; attack and defense are not divided.
    """

    library: dict
    friendly: list
    enemy: list
    controlled_index: object = None
    controlled: object = field(init=False, default=None)
    fighters: list = field(init=False, default_factory=list)
    divisions: list = field(init=False, default_factory=list)  # Sub-unit lists, friendly roster then enemy roster.
    projectiles: list = field(init=False, default_factory=list)
    winner: object = field(init=False, default=None)
    elapsed: float = field(init=False, default=0.0)
    paused: bool = field(init=False, default=False)
    _division_health: list = field(init=False, default_factory=list)  # Each division's full health.
    _accumulator: float = field(init=False, default=0.0)
    _throttle: float = field(init=False, default=0.0)
    _turn: float = field(init=False, default=0.0)
    _fire: bool = field(init=False, default=False)
    _aim_point: object = field(init=False, default=None)

    def __post_init__(self):
        if self.controlled_index is not None and (
                type(self.controlled_index) is not int or not 0 <= self.controlled_index < len(self.friendly)):
            raise ValueError("The controlled unit must be an existing friendly roster entry.")
        allowed = set(land_unit_types(self.library))
        for side, roster in enumerate((self.friendly, self.enemy)):
            if not roster or len(roster) > c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE:
                raise ValueError(f"Each army needs 1 to {c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE} land units.")
            if any((entry["type"] if isinstance(entry, dict) else entry) not in allowed
                   for entry in roster):
                raise ValueError("Custom battles accept only current land-unit identifiers.")
            rows = min(SPAWN_ROWS, len(roster))
            # The last column of divisions forms the front rank; earlier columns stand behind it.
            columns = math.ceil(len(roster) / rows)
            front = (c.CUSTOM_BATTLE_ARENA_SIZE[0] - SPAWN_FRONT_GAP) / 2
            for index, entry in enumerate(roster):
                name = entry["type"] if isinstance(entry, dict) else entry
                column, row = divmod(index, rows)
                x = front - (columns - 1 - column) * DIVISION_GAP
                if side:
                    x = c.CUSTOM_BATTLE_ARENA_SIZE[0] - x
                y = c.CUSTOM_BATTLE_ARENA_SIZE[1] / 2 + (row - (rows - 1) / 2) * DIVISION_GAP
                owner = entry["owner"] if isinstance(entry, dict) else "Enemy" if side else "Friendly"
                data = queries.create_unit_dict(name, owner, self.library)
                if isinstance(entry, dict):
                    if not valid_starting_health(entry["health"], data["max_health"]):
                        raise ValueError("Starting HP must be above zero and no greater than the unit's maximum HP.")
                    data["health"] = entry["health"]
                # Bombardment attack belongs to the unit library, not to saved instances.
                data["bombard_attack"] = self.library[name].get("bombard_attack", data["attack"])
                bombard_range = queries.get_bombardment_range(name, self.library[name])
                members = self._deploy_division(
                    data, side, x, y, unit_shape(name, self.library),
                    WEAPON_RANGE + bombard_range * BOMBARD_RANGE_PIXELS,
                    "bombard_attack" if bombard_range else "attack")
                if side == 0 and index == self.controlled_index:
                    self.controlled = members[0]

    def _deploy_division(self, data, side, x, y, shape, weapon_range, attack_field):
        """Split one division into sub-units around (x, y), front rank first.

        A division at fraction ``f`` of full health brings ceil(f * N) of its N sub-units,
        sharing its health equally: 63% of 10 is 7 sub-units at 90% each.
        """
        full = data["max_health"]
        size = SUBUNIT_COUNTS[shape]
        # The small allowance keeps float error from adding a sub-unit: 0.7 * 10 is 7.000000000000001.
        count = max(1, math.ceil(data["health"] / full * size - 1e-9))
        across = math.ceil(math.sqrt(count))
        ranks = math.ceil(count / across)
        facing = math.pi if side else 0.0
        division = len(self.divisions)
        members = []
        for number in range(count):
            rank, file = divmod(number, across)
            forward = ((ranks - 1) / 2 - rank) * SUBUNIT_GAP
            members.append(Fighter(
                dict(data, max_health=full / size, health=data["health"] / count), side,
                x - forward if side else x + forward,
                y + (file - (across - 1) / 2) * SUBUNIT_GAP,
                shape, weapon_range, attack_field, division=division, angle=facing, aim=facing,
                # Spread target searches across ticks instead of running them all at once.
                retarget=(len(self.fighters) + number) % round(RETARGET_SECONDS / FIXED_STEP) * FIXED_STEP))
        self.divisions.append(members)
        self._division_health.append(full)
        self.fighters.extend(members)
        return members

    def division_health_fraction(self, index):
        """The share of full health a division has left across all its sub-units."""
        return sum(fighter.data["health"] for fighter in self.divisions[index]) / self._division_health[index]

    @property
    def controlled_division_alive(self):
        """Whether any sub-unit of the controlled division survives.

        Losing the controlled sub-unit ends control for the rest of the battle; the player spectates.
        A tactical player still keeps the division in the campaign while any of its sub-units survives.
        """
        return self.controlled is not None and any(
            fighter.alive for fighter in self.divisions[self.controlled.division])

    def set_player_input(self, throttle=0.0, turn=0.0, fire=False, aim_point=None):
        """Receive held controls and the pointer in field coordinates.

        Movement, aiming, and firing still execute on fixed ticks. Without an aim point the gun holds its angle.
        """
        self._throttle = max(-1.0, min(1.0, throttle))
        self._turn = max(-1.0, min(1.0, turn))
        self._fire = bool(fire)
        self._aim_point = None if aim_point is None else (float(aim_point[0]), float(aim_point[1]))

    def advance(self, seconds):
        """Use fixed simulation ticks; paused time is never saved up for later."""
        if self.paused or self.winner is not None:
            return
        self._accumulator += max(0.0, seconds)
        while self._accumulator + 1e-9 >= FIXED_STEP and self.winner is None:
            self._accumulator = max(0.0, self._accumulator - FIXED_STEP)
            self._step(FIXED_STEP)

    @staticmethod
    def _accelerate(fighter, throttle, dt):
        """Ease the forward speed toward ``throttle`` times top speed; reverse uses the same rate."""
        seconds = MOBILITY[fighter.shape][0]
        top = fighter.max_speed
        fighter.speed = _approach(fighter.speed, throttle * top, top / seconds * dt)

    @staticmethod
    def _steer(fighter, turn, dt):
        """Ease the turn rate toward ``turn`` times the top turn speed, then turn the hull."""
        _seconds, degrees, seconds = MOBILITY[fighter.shape]
        top = math.radians(degrees)
        fighter.turn_rate = _approach(fighter.turn_rate, turn * top, top / seconds * dt)
        fighter.angle = (fighter.angle + fighter.turn_rate * dt) % math.tau

    @staticmethod
    def _slew_aim(fighter, desired, dt):
        """Turn the gun toward ``desired`` at the gun's turn speed, inside the firing cone if it has one.

        The cone is measured from the hull, so turning the hull carries the cone and the gun with it.
        """
        step = math.radians(AIM[fighter.shape][1]) * dt
        cone = firing_cone(fighter.shape)
        if cone is None:
            fighter.aim = (fighter.aim + max(-step, min(step, _wrap(desired - fighter.aim)))) % math.tau
            return
        half = cone / 2
        current = max(-half, min(half, _wrap(fighter.aim - fighter.angle)))
        goal = max(-half, min(half, _wrap(desired - fighter.angle)))
        fighter.aim = (fighter.angle + _approach(current, goal, step)) % math.tau

    @staticmethod
    def _attack(source, target, attack_field):
        """Shared health scaling and target capability rules own attack strength."""
        return sum(shot[1] for shot in combat_rules.damage_shots([source], [target], attack_field=attack_field))

    def _drive_player(self, fighter, dt, shots):
        self._steer(fighter, self._turn, dt)
        self._accelerate(fighter, self._throttle, dt)
        aim = self._aim_point
        self._slew_aim(fighter, fighter.aim if aim is None else math.atan2(aim[1] - fighter.y, aim[0] - fighter.x), dt)
        if self._fire and fighter.cooldown <= 0:
            shots.append((fighter, shot_reach(fighter, aim)))
            fighter.cooldown = FIRE_INTERVAL

    def _drive_ai(self, fighter, enemies, dt, shots):
        fighter.retarget -= dt
        if fighter.retarget <= 0:
            fighter.retarget += RETARGET_SECONDS
            fighter.target = None
        if fighter.target is None or not fighter.target.alive:
            fighter.target = enemies.nearest(fighter.x, fighter.y)
        target = fighter.target
        dx, dy = target.x - fighter.x, target.y - fighter.y
        distance = math.hypot(dx, dy)
        turning = _wrap(math.atan2(dy, dx) - fighter.angle)
        _seconds, degrees, seconds = MOBILITY[fighter.shape]
        # Ease off the turn before the hull lines up, since the turn rate cannot stop at once.
        self._steer(fighter, max(-1.0, min(1.0, turning / (math.radians(degrees) * seconds))), dt)
        closing = distance > fighter.weapon_range * AI_HOLD_RANGE
        self._accelerate(fighter, max(0.0, math.cos(turning)) if closing else 0.0, dt)
        flight = distance / (c.CUSTOM_BATTLE_PROJECTILE_SPEED if fighter.arcing else DIRECT_PROJECTILE_SPEED)
        lead_x, lead_y = target.x + target.vx * flight, target.y + target.vy * flight
        desired = math.atan2(lead_y - fighter.y, lead_x - fighter.x)
        self._slew_aim(fighter, desired, dt)
        if (fighter.cooldown <= 0 and distance <= fighter.weapon_range
                and abs(_wrap(desired - fighter.aim)) <= AIM_TOLERANCE
                and self._attack(fighter.data, target.data, fighter.attack_field) > 0):
            shots.append((fighter, min(fighter.weapon_range, math.hypot(lead_x - fighter.x, lead_y - fighter.y))))
            fighter.cooldown = FIRE_INTERVAL

    def _fire_shot(self, fighter, reach):
        direction_x, direction_y = math.cos(fighter.aim), math.sin(fighter.aim)
        data = dict(fighter.data)
        if fighter.arcing:
            flight = max(FIXED_STEP, reach / c.CUSTOM_BATTLE_PROJECTILE_SPEED)
            speed = reach / flight
            self.projectiles.append(Projectile(fighter, data, fighter.x, fighter.y, direction_x * speed,
                                               direction_y * speed, flight, flight))
        else:
            self.projectiles.append(Projectile(
                fighter, data, fighter.x, fighter.y, direction_x * DIRECT_PROJECTILE_SPEED,
                direction_y * DIRECT_PROJECTILE_SPEED,
                (fighter.weapon_range + UNIT_RADIUS * 2) / DIRECT_PROJECTILE_SPEED))

    def _step(self, dt):
        self.elapsed += dt
        living = [fighter for fighter in self.fighters if fighter.alive]
        sides = [[fighter for fighter in living if fighter.side == side] for side in (0, 1)]
        crowds = [_Grid(side, GRID_CELL) for side in sides]
        targets = [_Grid(side, TARGET_CELL) for side in sides]
        # All movement and fire decisions use the same pre-step positions.
        movements = []
        shots = []
        for fighter in living:
            if not sides[1 - fighter.side]:
                continue
            fighter.cooldown = max(0.0, fighter.cooldown - dt)
            player_controlled = fighter is self.controlled
            if player_controlled:
                self._drive_player(fighter, dt, shots)
            else:
                self._drive_ai(fighter, targets[1 - fighter.side], dt, shots)
            move = fighter.speed * dt
            mx, my = math.cos(fighter.angle) * move, math.sin(fighter.angle) * move
            # A small separation keeps accompanying units visible on an empty field.
            for other in (() if player_controlled else crowds[fighter.side].around(
                    fighter.x, fighter.y, UNIT_RADIUS * 2)):
                if other is fighter:
                    continue
                sx, sy = fighter.x - other.x, fighter.y - other.y
                gap = math.hypot(sx, sy)
                if 0 < gap < UNIT_RADIUS * 2:
                    push = min(UNIT_RADIUS * 2 - gap, fighter.max_speed * dt) / 2
                    mx += sx / gap * push
                    my += sy / gap * push
            movements.append((fighter, mx, my))
        for fighter, reach in shots:
            self._fire_shot(fighter, reach)
        for fighter, mx, my in movements:
            x = min(c.CUSTOM_BATTLE_ARENA_SIZE[0] - UNIT_RADIUS, max(UNIT_RADIUS, fighter.x + mx))
            y = min(c.CUSTOM_BATTLE_ARENA_SIZE[1] - UNIT_RADIUS, max(UNIT_RADIUS, fighter.y + my))
            fighter.vx, fighter.vy = (x - fighter.x) / dt, (y - fighter.y) / dt
            fighter.x, fighter.y = x, y

        # Accumulate impacts first so units destroyed together can both land their shots.
        hittable = [_Grid(side, GRID_CELL) for side in sides]
        hits = []
        remaining = []
        for shot in self.projectiles:
            enemies = hittable[1 - shot.source.side]
            if shot.arcing:
                # A shell in the air passes over units; it hits only where it lands.
                travel = min(dt, shot.remaining)
                shot.x += shot.vx * travel
                shot.y += shot.vy * travel
                shot.remaining -= dt
                if shot.remaining > 1e-9:
                    remaining.append(shot)
                    continue
                hits.extend((shot, target) for target in enemies.around(shot.x, shot.y, ARTILLERY_BLAST_RADIUS)
                            if math.hypot(target.x - shot.x, target.y - shot.y) <= ARTILLERY_BLAST_RADIUS)
                continue
            nx, ny = shot.x + shot.vx * dt, shot.y + shot.vy * dt
            collisions = []
            for target in enemies.within(min(shot.x, nx) - UNIT_RADIUS, min(shot.y, ny) - UNIT_RADIUS,
                                         max(shot.x, nx) + UNIT_RADIUS, max(shot.y, ny) + UNIT_RADIUS):
                fraction = self._collision_fraction(shot.x, shot.y, nx, ny, target)
                if fraction is not None:
                    collisions.append((fraction, target))
            if collisions:
                target = min(collisions, key=lambda item: item[0])[1]
                hits.append((shot, target))
            else:
                shot.x, shot.y = nx, ny
                shot.remaining -= dt
                if shot.remaining > 0:
                    remaining.append(shot)
        self.projectiles = remaining
        for shot, target in hits:
            # Attack is measured against the unit actually hit, so its capability rules apply.
            attack = self._attack(shot.source_data, target.data, shot.source.attack_field)
            # Tactical defense blocks a flat amount per hit, even when wounded.
            # Campaign combat instead scales defense with remaining health.
            loss = max(0.0, attack - target.data["defense"])
            # Whole health points keep equal, weakening armies from approaching
            # zero forever when the shared health-scaled attack has no floor.
            target.data["health"] = max(0.0, target.data["health"] - math.ceil(loss))
        alive_sides = {fighter.side for fighter in self.fighters if fighter.alive}
        if len(alive_sides) < 2:
            # Mutual destruction is a loss for the friendly army; there is no draw screen.
            self.winner = 0 if 0 in alive_sides else 1

    @staticmethod
    def _collision_fraction(x, y, nx, ny, target):
        """Swept collision prevents fast shells from skipping small unit shapes."""
        dx, dy = nx - x, ny - y
        length_squared = dx * dx + dy * dy
        fraction = max(0.0, min(1.0, ((target.x - x) * dx + (target.y - y) * dy)
                                / length_squared)) if length_squared else 0.0
        distance = math.hypot(target.x - (x + fraction * dx), target.y - (y + fraction * dy))
        return fraction if distance <= UNIT_RADIUS else None
