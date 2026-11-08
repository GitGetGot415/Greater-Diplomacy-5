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
WEAPON_RANGE = 1000.0
PROJECTILE_SPEED = 1000.0
UNIT_RADIUS = 12.0
SHOT_SPREAD = math.radians(1.5)  # Every shot leaves up to this far off its aim, either way, so range costs hits.
# Each AI sub-unit draws its own temperament from these (low, high) ranges at deployment.
AI_HOLD_RANGE = (0.6, 0.95)  # Share of weapon range at which it stops closing in.
AI_PACE = (0.7, 1.0)  # Cruising throttle.
AI_START_DELAY = (0.0, 1.5)  # Seconds before it first moves.
AI_WANDER_PERIOD = (4.0, 9.0)  # Seconds per weave from side to side while advancing.
AI_WANDER_ANGLE = math.radians(20)  # Widest weave either side of its course.
# Divisions advance as loose groups: a sub-unit this far ahead of its division's center slows to wait.
COHESION_SLACK = 60.0
COHESION_THROTTLE = 0.4  # Share of its pace while it waits.
AIM_TOLERANCE = math.radians(4)  # AI units fire once the gun points this close to the aim angle.
RETARGET_SECONDS = 0.25  # AI units choose the nearest enemy again this often.
# Collision and separation cells, and the coarser cells of the nearest-enemy search.
GRID_CELL = 64.0
TARGET_CELL = 256.0
# Each division deploys as one vertical line of its sub-units, one division per rank.
# Roster order runs front to back: the first division stands closest to the enemy.
RANK_GAP = 40.0  # Between ranks, front to back.
SUBUNIT_SPACING = 50.0  # Between neighboring sub-units along a division's line.
# Distance between the two armies' front ranks at deployment, centered on the battlefield.
SPAWN_FRONT_GAP = 2000.0
SPAWN_MARGIN = 100.0  # Between the battlefield edge and the last rank of the largest army.
# The battlefield is wide enough for two full armies behind their front ranks.
ARENA_SIZE = (SPAWN_FRONT_GAP + 2 * (SPAWN_MARGIN + (c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE - 1) * RANK_GAP), 1100.0)
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
    "Motorized Infantry Type": "motorized",
    "Mechanized Infantry Type": "mechanized",
    "Infantry Fighting Vehicle Type": "ifv",
}
# Sub-units a division at full health becomes on the battlefield. A wounded division brings fewer.
SUBUNIT_COUNTS = {
    "infantry": 6, "cavalry": 6, "motorized": 6, "mechanized": 6, "ifv": 6,
    "armored_car": 3, "light_tank": 3, "tank": 3, "heavy_tank": 3,
}
# (seconds to reach full speed, top turn speed in degrees per second, seconds to reach top turn speed)
MOBILITY = {
    "infantry": (0.3, 180, 0.15), "cavalry": (0.6, 150, 0.25),
    "motorized": (0.8, 120, 0.3), "mechanized": (0.9, 110, 0.3), "ifv": (1.0, 100, 0.35),
    "armored_car": (0.8, 130, 0.3), "light_tank": (1.0, 110, 0.35),
    "tank": (1.2, 90, 0.4), "heavy_tank": (1.6, 70, 0.5),
}
# (firing cone width in degrees, or None to aim all the way around; gun turn speed in degrees per second)
AIM = {
    "infantry": (90, 240), "cavalry": (90, 240),
    "motorized": (90, 200), "mechanized": (90, 200), "ifv": (90, 180),
    "armored_car": (None, 180), "light_tank": (None, 150), "tank": (None, 120),
    "heavy_tank": (None, 90),
}


def valid_starting_health(health, max_health):
    """A participating unit must start alive and within its library health limit."""
    return (isinstance(health, (int, float)) and not isinstance(health, bool)
            and 0 < health <= max_health)


def is_artillery(name, library):
    """Artillery-type units (everything that can bombard) take no part in tactical battles."""
    return queries.get_bombardment_range(name, library.get(name)) > 0


def _is_land(stats):
    return not stats.get("naval_unit") and not stats.get("air_role")


def land_unit_types(library):
    """Units that can fight tactical battles: library identifiers, including levels, of land units.

    Ships, aircraft, and artillery-type units are excluded.
    """
    return [name for name, stats in library.items() if _is_land(stats) and not is_artillery(name, library)]


def _campaign_sides(player_unit, province, nation_data):
    """Every living unit on the tile on the player's side (player's unit first) and on the enemy side."""
    country = queries.get_unit_combat_owner(player_unit)
    enemies = queries.get_enemies(country, nation_data)
    friends = {country, *queries.get_all_friendly_nations(country, nation_data)}
    units = [unit for unit in province.get("units", []) if unit.get("health", 0) > 0]
    friendly = ([unit for unit in units if unit is player_unit]
                + [unit for unit in units if unit is not player_unit
                   and queries.get_unit_combat_owner(unit) in friends])
    return friendly, [unit for unit in units if queries.get_unit_combat_owner(unit) in enemies]


def _artillery(units, library):
    return [unit for unit in units if unit.get("type") in library
            and _is_land(library[unit["type"]]) and is_artillery(unit["type"], library)]


def campaign_forces(player_unit, province, nation_data, library):
    """The campaign units (friendly, enemy) fighting a tactical player's land unit on its tile.

    The player's unit leads the friendly list. Returns None when that unit cannot fight a
    tactical battle or no hostile land unit shares its tile. Artillery sits the battle out,
    so the enemy list is empty when hostile artillery alone shares the tile: the player wins
    without a battle (win_against_artillery). Each list holds at most one army's units.
    """
    land = set(land_unit_types(library))
    sides = _campaign_sides(player_unit, province, nation_data)
    friendly, enemy = ([unit for unit in side if unit.get("type") in land][:c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE]
                       for side in sides)
    if not friendly or friendly[0] is not player_unit or not (enemy or _artillery(sides[1], library)):
        return None
    return friendly, enemy


def campaign_artillery(player_unit, province, nation_data, library):
    """The land artillery-type units (friendly, enemy) on a tactical player's tile, which sit the battle out."""
    return tuple(_artillery(side, library) for side in _campaign_sides(player_unit, province, nation_data))


def win_against_artillery(player_unit, province, nation_data, library):
    """Hostile artillery alone cannot fight a tactical battle: the player wins at once and that artillery is destroyed."""
    for unit in campaign_artillery(player_unit, province, nation_data, library)[1]:
        unit["health"] = 0
    province["units"] = [unit for unit in province["units"] if unit.get("health", 0) > 0]


def tactical_encounter(context, province):
    """The (friendly, enemy) campaign units of the tactical encounter on ``province``, or None.

    Only the tile holding the tactical player's land unit has one, and only while hostile land
    units share it. The encounter deals that tile's damage, so campaign combat must skip the tile.
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


def apply_campaign_result(simulation, units, province, artillery):
    """Write a finished battle back: each unit keeps its division's fraction of health and the dead are removed.

    ``units`` are the campaign units in roster order, friendly army then enemy army.
    ``artillery`` is (friendly, enemy) from campaign_artillery. The losing side's artillery is
    destroyed; the winning side's is untouched.
    """
    for index, unit in enumerate(units):
        unit["health"] = simulation.division_health_fraction(index) * unit["max_health"]
    for unit in artillery[1 - simulation.winner]:
        unit["health"] = 0
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
    if family in FAMILY_SHAPES:
        return FAMILY_SHAPES[family]
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
    division: int = 0  # Index into BattleSimulation.divisions.
    cooldown: float = 0.0
    angle: float = 0.0  # Hull heading: movement follows it.
    aim: float = 0.0  # Gun heading: shots follow it.
    speed: float = 0.0  # Signed forward speed in pixels per second.
    turn_rate: float = 0.0  # Radians per second.
    vx: float = 0.0
    vy: float = 0.0
    target: object = None  # AI only: the enemy it shoots at, its nearest.
    retarget: float = 0.0  # AI only: seconds until it chooses the nearest enemy again.
    slot: float = 0.0  # Sideways place in its division's line: positive is downward at deployment.
    # AI only: its temperament, drawn at deployment (see the AI_* ranges).
    hold: float = 0.85
    pace: float = 1.0
    start_delay: float = 0.0
    wander: float = 0.0  # Radians.
    wander_period: float = 6.0
    wander_phase: float = 0.0

    @property
    def alive(self):
        return self.data["health"] > 0

    @property
    def max_speed(self):
        return max(0, self.data["speed"]) * MOVE_PIXELS_PER_SPEED


@dataclass
class Projectile:
    """A shot in flight. It hits the first enemy it crosses."""

    source: Fighter
    source_data: dict  # The shooter as it fired, so a shot still lands after the shooter dies.
    x: float
    y: float
    vx: float
    vy: float
    remaining: float  # Seconds left in flight.


class _Grid:
    """Buckets one army's living sub-units by cell so nearby lookups skip the rest of the field."""

    def __init__(self, fighters, cell):
        self.cell = cell
        self.cells = {}
        for fighter in fighters:
            self.cells.setdefault(self._key(fighter.x, fighter.y), []).append(fighter)
        self.reach = math.ceil(max(ARENA_SIZE) / cell) + 1

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
    ``seed`` fixes the random temperaments and shot spread, so a battle can be replayed.
    """

    library: dict
    friendly: list
    enemy: list
    controlled_index: object = None
    seed: object = None
    controlled: object = field(init=False, default=None)
    fighters: list = field(init=False, default_factory=list)
    divisions: list = field(init=False, default_factory=list)  # Sub-unit lists, friendly roster then enemy roster.
    projectiles: list = field(init=False, default_factory=list)
    winner: object = field(init=False, default=None)
    elapsed: float = field(init=False, default=0.0)
    paused: bool = field(init=False, default=False)
    _division_health: list = field(init=False, default_factory=list)  # Each division's full health.
    _division_targets: list = field(init=False, default_factory=list)  # The enemy each division advances on.
    _division_retarget: list = field(init=False, default_factory=list)  # Seconds until each chooses again.
    _rng: object = field(init=False, default=None)
    _accumulator: float = field(init=False, default=0.0)
    _throttle: float = field(init=False, default=0.0)
    _turn: float = field(init=False, default=0.0)
    _fire: bool = field(init=False, default=False)
    _aim_point: object = field(init=False, default=None)

    def __post_init__(self):
        if self.controlled_index is not None and (
                type(self.controlled_index) is not int or not 0 <= self.controlled_index < len(self.friendly)):
            raise ValueError("The controlled unit must be an existing friendly roster entry.")
        self._rng = random.Random(self.seed)
        allowed = set(land_unit_types(self.library))
        for side, roster in enumerate((self.friendly, self.enemy)):
            if not roster or len(roster) > c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE:
                raise ValueError(f"Each army needs 1 to {c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE} land units.")
            if any((entry["type"] if isinstance(entry, dict) else entry) not in allowed
                   for entry in roster):
                raise ValueError("Custom battles accept only current land-unit identifiers.")
            front = (ARENA_SIZE[0] - SPAWN_FRONT_GAP) / 2
            for index, entry in enumerate(roster):
                name = entry["type"] if isinstance(entry, dict) else entry
                # The first roster entry stands in the front rank, the last one furthest back.
                x = front - index * RANK_GAP
                if side:
                    x = ARENA_SIZE[0] - x
                owner = entry["owner"] if isinstance(entry, dict) else "Enemy" if side else "Friendly"
                data = queries.create_unit_dict(name, owner, self.library)
                if isinstance(entry, dict):
                    if not valid_starting_health(entry["health"], data["max_health"]):
                        raise ValueError("Starting HP must be above zero and no greater than the unit's maximum HP.")
                    data["health"] = entry["health"]
                members = self._deploy_division(data, side, x, unit_shape(name, self.library))
                if side == 0 and index == self.controlled_index:
                    self.controlled = members[len(members) // 2]  # The middle of the line.

    def _deploy_division(self, data, side, x, shape):
        """Split one division into sub-units standing in a vertical line at ``x``, centered top to bottom.

        A division at fraction ``f`` of full health brings ceil(f * N) of its N sub-units,
        sharing its health equally: 63% of 10 is 7 sub-units at 90% each.
        A line with fewer sub-units is shorter, since the spacing between them stays the same.
        """
        full = data["max_health"]
        size = SUBUNIT_COUNTS[shape]
        # The small allowance keeps float error from adding a sub-unit: 0.7 * 10 is 7.000000000000001.
        count = max(1, math.ceil(data["health"] / full * size - 1e-9))
        facing = math.pi if side else 0.0
        division = len(self.divisions)
        # Spread target searches across ticks instead of running them all at once.
        stagger = round(RETARGET_SECONDS / FIXED_STEP)
        rng = self._rng
        members = []
        for number in range(count):
            slot = (number - (count - 1) / 2) * SUBUNIT_SPACING
            members.append(Fighter(
                dict(data, max_health=full / size, health=data["health"] / count), side,
                x, ARENA_SIZE[1] / 2 + slot, shape, division=division, angle=facing, aim=facing,
                retarget=(len(self.fighters) + number) % stagger * FIXED_STEP, slot=slot,
                hold=rng.uniform(*AI_HOLD_RANGE), pace=rng.uniform(*AI_PACE),
                start_delay=rng.uniform(*AI_START_DELAY), wander=rng.uniform(0.0, AI_WANDER_ANGLE),
                wander_period=rng.uniform(*AI_WANDER_PERIOD), wander_phase=rng.uniform(0.0, math.tau)))
        self.divisions.append(members)
        self._division_health.append(full)
        self._division_targets.append(None)
        self._division_retarget.append(division % stagger * FIXED_STEP)
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
    def _attack(source, target):
        """Shared health scaling and target capability rules own attack strength."""
        return sum(shot[1] for shot in combat_rules.damage_shots([source], [target]))

    def _drive_player(self, fighter, dt, shots):
        self._steer(fighter, self._turn, dt)
        self._accelerate(fighter, self._throttle, dt)
        aim = self._aim_point
        self._slew_aim(fighter, fighter.aim if aim is None else math.atan2(aim[1] - fighter.y, aim[0] - fighter.x), dt)
        if self._fire and fighter.cooldown <= 0:
            shots.append(fighter)
            fighter.cooldown = FIRE_INTERVAL

    @staticmethod
    def advance_point(fighter, center, objective):
        """Where a sub-unit heads while closing in: beside its division's objective, at its own place in the line.

        Sideways places keep their deployment order, so a division arrives spread out rather than in one clump.
        """
        dx, dy = objective.x - center[0], objective.y - center[1]
        length = math.hypot(dx, dy)
        if length:
            dx, dy = dx / length, dy / length
        else:
            dx, dy = (-1.0, 0.0) if fighter.side else (1.0, 0.0)
        # Rotate the course a quarter turn so a positive slot stays on the side it deployed on.
        sideways = -1.0 if fighter.side else 1.0
        return (objective.x - dy * sideways * fighter.slot, objective.y + dx * sideways * fighter.slot), (dx, dy)

    def _drive_ai(self, fighter, enemies, dt, shots, center, objective):
        fighter.retarget -= dt
        if fighter.retarget <= 0:
            fighter.retarget += RETARGET_SECONDS
            fighter.target = None
        if fighter.target is None or not fighter.target.alive:
            fighter.target = enemies.nearest(fighter.x, fighter.y)
        target = fighter.target
        dx, dy = target.x - fighter.x, target.y - fighter.y
        distance = math.hypot(dx, dy)
        closing = distance > WEAPON_RANGE * fighter.hold
        throttle = 0.0
        if closing:
            (goal_x, goal_y), (course_x, course_y) = self.advance_point(fighter, center, objective)
            weave = fighter.wander * math.sin(math.tau * self.elapsed / fighter.wander_period + fighter.wander_phase)
            turning = _wrap(math.atan2(goal_y - fighter.y, goal_x - fighter.x) + weave - fighter.angle)
            if self.elapsed >= fighter.start_delay:
                throttle = fighter.pace * max(0.0, math.cos(turning))
                # A sub-unit well ahead of its division slows down to let the division catch up.
                if (fighter.x - center[0]) * course_x + (fighter.y - center[1]) * course_y > COHESION_SLACK:
                    throttle *= COHESION_THROTTLE
        else:
            # Holding position: face the enemy it shoots at, so a firing cone covers it.
            turning = _wrap(math.atan2(dy, dx) - fighter.angle)
        _seconds, degrees, seconds = MOBILITY[fighter.shape]
        # Ease off the turn before the hull lines up, since the turn rate cannot stop at once.
        self._steer(fighter, max(-1.0, min(1.0, turning / (math.radians(degrees) * seconds))), dt)
        self._accelerate(fighter, throttle, dt)
        flight = distance / PROJECTILE_SPEED
        lead_x, lead_y = target.x + target.vx * flight, target.y + target.vy * flight
        desired = math.atan2(lead_y - fighter.y, lead_x - fighter.x)
        self._slew_aim(fighter, desired, dt)
        if (fighter.cooldown <= 0 and distance <= WEAPON_RANGE
                and abs(_wrap(desired - fighter.aim)) <= AIM_TOLERANCE
                and self._attack(fighter.data, target.data) > 0):
            shots.append(fighter)
            fighter.cooldown = FIRE_INTERVAL

    def _fire_shot(self, fighter):
        # The shot leaves slightly off the aim, so the same error misses more often at long range.
        angle = fighter.aim + self._rng.uniform(-SHOT_SPREAD, SHOT_SPREAD)
        self.projectiles.append(Projectile(
            fighter, dict(fighter.data), fighter.x, fighter.y, math.cos(angle) * PROJECTILE_SPEED,
            math.sin(angle) * PROJECTILE_SPEED, (WEAPON_RANGE + UNIT_RADIUS * 2) / PROJECTILE_SPEED))

    def _division_objectives(self, targets, dt):
        """Each division with living sub-units and enemies left: its center and the enemy it advances on.

        The objective is the nearest enemy to the division's center, chosen again every RETARGET_SECONDS.
        """
        objectives = {}
        for index, members in enumerate(self.divisions):
            alive = [fighter for fighter in members if fighter.alive]
            if not alive or not targets[1 - alive[0].side].cells:
                continue
            center = (sum(fighter.x for fighter in alive) / len(alive), sum(fighter.y for fighter in alive) / len(alive))
            self._division_retarget[index] -= dt
            if self._division_retarget[index] <= 0:
                self._division_retarget[index] += RETARGET_SECONDS
                self._division_targets[index] = None
            objective = self._division_targets[index]
            if objective is None or not objective.alive:
                objective = self._division_targets[index] = targets[1 - alive[0].side].nearest(*center)
            objectives[index] = center, objective
        return objectives

    def _step(self, dt):
        self.elapsed += dt
        living = [fighter for fighter in self.fighters if fighter.alive]
        sides = [[fighter for fighter in living if fighter.side == side] for side in (0, 1)]
        crowds = [_Grid(side, GRID_CELL) for side in sides]
        targets = [_Grid(side, TARGET_CELL) for side in sides]
        objectives = self._division_objectives(targets, dt)
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
                self._drive_ai(fighter, targets[1 - fighter.side], dt, shots, *objectives[fighter.division])
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
        for fighter in shots:
            self._fire_shot(fighter)
        for fighter, mx, my in movements:
            x = min(ARENA_SIZE[0] - UNIT_RADIUS, max(UNIT_RADIUS, fighter.x + mx))
            y = min(ARENA_SIZE[1] - UNIT_RADIUS, max(UNIT_RADIUS, fighter.y + my))
            fighter.vx, fighter.vy = (x - fighter.x) / dt, (y - fighter.y) / dt
            fighter.x, fighter.y = x, y

        # Accumulate impacts first so units destroyed together can both land their shots.
        hittable = [_Grid(side, GRID_CELL) for side in sides]
        hits = []
        remaining = []
        for shot in self.projectiles:
            enemies = hittable[1 - shot.source.side]
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
            attack = self._attack(shot.source_data, target.data)
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
