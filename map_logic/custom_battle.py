"""Standalone land battles with optional player control and no campaign state."""

import math
import random
from dataclasses import dataclass, field

import data.constants as c
from data import queries
from data.io import starting_defaults
from data.state_access import session_for, world_for
from map_logic import battle_terrain
from map_logic.system32 import combat_forecast, combat_rules


# These values translate campaign statistics into a real-time battlefield.
# They do not change campaign combat or add persistent unit statistics.
FIXED_STEP = 1.0 / 30.0
MOVE_PIXELS_PER_SPEED = 35.0
FIRE_INTERVAL = 2.0
DAMAGE_SCALE = 0.5  # Applied after defense and rounding, so low-damage hits also slow down.
WEAPON_RANGE = 1500.0
PROJECTILE_SPEED = 1000.0
ENGAGEMENT_RANGE = 600.0  # Preferred distances do not grow with maximum projectile reach.
WITHDRAW_RANGE = 900.0
FALLOFF_START = 500.0
MIN_RANGED_DAMAGE = 0.45
UNIT_RADIUS = 12.0
SHOT_SPREAD = math.radians(1.5)  # Every shot leaves up to this far off its aim, either way, so range costs hits.
# Each AI sub-unit draws its own temperament from these (low, high) ranges at deployment.
AI_HOLD_RANGE = (0.6, 0.95)  # Share of engagement distance at which it stops closing in.
AI_PACE = (0.7, 1.0)  # Cruising throttle.
AI_START_DELAY = (0.0, 1.5)  # Seconds before it first moves.
AI_WANDER_PERIOD = (4.0, 9.0)  # Seconds per weave from side to side while advancing.
AI_WANDER_ANGLE = math.radians(20)  # Widest weave either side of its course.
# Divisions advance as loose groups: a sub-unit this far ahead of its division's center slows to wait.
COHESION_SLACK = 60.0
COHESION_THROTTLE = 0.4  # Share of its pace while it waits.
# How AI sub-units of each battlefield shape fight. Shapes not listed advance and hold.
BEHAVIORS = {
    "cavalry": "charge", "armored_car": "skirmish",
    "light_tank": "flank", "tank": "flank", "heavy_tank": "flank",
}
FLANK_OFFSET = 300.0  # Flanking tanks head this far to one side of their division's objective.
CHARGE_CLOSE = 0.25  # Cavalry charges in to this share of engagement distance, then withdraws.
SKIRMISH_HOLD = 0.9  # Armored cars stop at this share of engagement distance...
SKIRMISH_BACK_OFF = 0.6  # ...and back away from an enemy closer than this share.
# Reacting to the fight.
FALL_BACK_HEALTH = 0.45  # Leave enough health to disengage under fire.
DODGE_MIN_SPEED = 3  # Library speed a sub-unit needs before it sidesteps at all; slower units keep aiming.
DODGE_SECONDS = 0.6  # A sub-unit that is hit, or sees a shot coming, sidesteps for this long.
DODGE_LOOKAHEAD = 0.6  # Seconds ahead a sub-unit that is not about to fire watches incoming shots.
DODGE_DANGER = UNIT_RADIUS * 2  # It sidesteps a shot whose path will pass this close.
TARGET_CHOICE_SLACK = 200.0  # Enemies this close to the nearest enemy are also considered as targets...
TARGET_WOUNDED_PULL = 0.5  # ...and a wounded one counts as up to this share closer.
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
ARENA_SIZE = (SPAWN_FRONT_GAP + 2 * (SPAWN_MARGIN + (c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE - 1) * RANK_GAP), 1800.0)
APPROACH_LANE_GAP = 70.0
FLANK_ARRIVAL_DISTANCE = 45.0
MELEE_SHAPES = frozenset(("infantry", "cavalry"))
MELEE_REACH = UNIT_RADIUS * 2 + 6
MELEE_INTERVAL = 1.0
MELEE_DAMAGE = 0.7  # Faster attacks give greater sustained damage, replacing gunfire.
MELEE_ARC = math.radians(60)  # Either side of the gun's aim; also applies to manual fire.
MELEE_APPROACH_RANGE = 160.0
MELEE_COMMIT_RANGE = 60.0
MELEE_MIN_HEALTH = 0.55
MELEE_WOUNDED_TARGET = 0.6
MELEE_SUPPORT_RATIO = 1.5
RAM_APPROACH_RANGE = 280.0
RAM_MIN_HEALTH = 0.65
RAM_MASS_ADVANTAGE = 2.0
CONTACT_RELEASE_DISTANCE = UNIT_RADIUS * 3
RAM_MIN_SPEED = 60.0
RAM_REFERENCE_SPEED = 120.0
RAM_MAX_STRENGTH = 1.5
RAM_DAMAGE = 0.6
KNOCKBACK_MAX_SPEED = 100.0
KNOCKBACK_SECONDS = 0.25
TANK_SHAPES = frozenset(("tank", "light_tank", "heavy_tank"))
NAVIGATION_SECONDS = 0.8
WAYPOINT_REACH = 25.0
FIRING_POSITION_ANGLES = 12
FIRING_POSITION_RINGS = (1.0, 0.6, 0.3)
FIRING_POSITION_STEP = 200.0
FIRING_DISTANCE_WEIGHT = 0.25
COVER_DISTANCE_WEIGHT = 0.1
# Relative contact mass is independent of health, price, and campaign defense.
CONTACT_MASS = {
    "infantry": 1.0, "cavalry": 2.0, "armored_car": 4.0, "motorized": 4.0,
    "light_tank": 6.0, "mechanized": 6.0, "ifv": 7.0, "tank": 9.0, "heavy_tank": 14.0,
}
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
    "infantry": 4, "cavalry": 4, "motorized": 4, "mechanized": 4, "ifv": 4,
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
    attack_share: float = 1.0  # The share of its division's damage each hit carries: 1 / its full sub-unit count.
    cooldown: float = 0.0
    reload_interval: float = FIRE_INTERVAL
    angle: float = 0.0  # Hull heading: movement follows it.
    aim: float = 0.0  # Gun heading: shots follow it.
    speed: float = 0.0  # Signed forward speed in pixels per second.
    turn_rate: float = 0.0  # Radians per second.
    index: int = 0
    lane: float = 0.0
    flank_goal: object = None
    flank_complete: bool = False
    melee_committed: bool = False
    ram_committed: bool = False
    melee_targets: tuple = ()
    push_vx: float = 0.0
    push_vy: float = 0.0
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
    flank: int = 1  # Which side its division swings out to when flanking: 1 or -1.
    # AI only: state while fighting.
    withdrawing: bool = False  # A charging sub-unit pulling back before it charges again.
    dodge: float = 0.0  # Seconds of sidestepping left.
    dodge_heading: float = 0.0  # The sidestep's direction: at right angles to the shot it avoids.
    route: list = field(default_factory=list)
    route_revision: int = -1
    navigate_at: float = 0.0
    position_goal: object = None
    position_target: object = None

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
    distance: float = 0.0  # Actual path traveled, including the partial segment at impact.
    height: float = battle_terrain.WEAPON_HEIGHT
    vertical_speed: float = 0.0


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
    that share the division's health. Each sub-unit keeps the full attack and defense stats, but the
    damage of each of its hits is divided by its division's full sub-unit count.
    ``seed`` fixes the random temperaments and shot spread, so a battle can be replayed.
    """

    library: dict
    friendly: list
    enemy: list
    controlled_index: object = None
    seed: object = None
    on_shot: object = None  # Optional presentation callback; headless battles remain silent.
    terrain: str = field(default_factory=lambda: starting_defaults.get_starting_value(
        "random_setup", "custom_battle_terrain"))
    battlefield: object = None  # Optional explicit geometry for headless encounters and fixtures.
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
    _hurts: dict = field(init=False, default_factory=dict)  # (shooter type, target type) -> can it do damage.
    _accumulator: float = field(init=False, default=0.0)
    _throttle: float = field(init=False, default=0.0)
    _turn: float = field(init=False, default=0.0)
    _fire: bool = field(init=False, default=False)
    _aim_point: object = field(init=False, default=None)
    _healthy_sides: list = field(init=False, default_factory=lambda: [True, True])
    _contacts: set = field(init=False, default_factory=set)  # Rearm a ram only after the pair separates.

    def __post_init__(self):
        if self.controlled_index is not None and (
                type(self.controlled_index) is not int or not 0 <= self.controlled_index < len(self.friendly)):
            raise ValueError("The controlled unit must be an existing friendly roster entry.")
        self._rng = random.Random(self.seed)
        if self.battlefield is None:
            self.battlefield = battle_terrain.Battlefield.generate(
                self.terrain, ARENA_SIZE, UNIT_RADIUS, SPAWN_FRONT_GAP, self.seed)
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
                lane = (index - (len(roster) - 1) / 2) * APPROACH_LANE_GAP
                for fighter in members:
                    fighter.lane = lane
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
        flank = rng.choice((-1, 1))  # The whole division swings out to the same side.
        members = []
        for number in range(count):
            slot = (number - (count - 1) / 2) * SUBUNIT_SPACING
            members.append(Fighter(
                dict(data, max_health=full / size, health=data["health"] / count), side,
                x, ARENA_SIZE[1] / 2 + slot, shape, division=division, attack_share=1 / size,
                angle=facing, aim=facing,
                index=len(self.fighters) + number,
                retarget=(len(self.fighters) + number) % stagger * FIXED_STEP, slot=slot,
                hold=rng.uniform(*AI_HOLD_RANGE), pace=rng.uniform(*AI_PACE),
                start_delay=rng.uniform(*AI_START_DELAY), wander=rng.uniform(0.0, AI_WANDER_ANGLE),
                wander_period=rng.uniform(*AI_WANDER_PERIOD), wander_phase=rng.uniform(0.0, math.tau),
                flank=flank))
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
        """Living tactical sub-units keep full attack; shared target restrictions still apply."""
        return sum(shot[1] for shot in combat_rules.damage_shots([source], [target], scale_health=False))

    @classmethod
    def damage_amount(cls, source, target, attack_share, multiplier=1.0):
        """Tactical pacing follows full defense and division sharing for every attack kind.

        Round before pacing so even the smallest positive hits take longer than before.
        Each surviving sub-unit keeps its attack strength as health falls.
        """
        loss = max(0.0, cls._attack(source, target) - target["defense"]) * attack_share
        return math.ceil(loss) * DAMAGE_SCALE * multiplier

    @staticmethod
    def ranged_multiplier(distance):
        fraction = max(0.0, min(1.0, (distance - FALLOFF_START) / (WEAPON_RANGE - FALLOFF_START)))
        return 1.0 - fraction * (1.0 - MIN_RANGED_DAMAGE)

    def _firing_lane(self, fighter, target, start=None, clear_trees=True):
        start = (fighter.x, fighter.y) if start is None else start
        hit = self.battlefield.firing_blocker(start, (target.x, target.y))
        return hit is None or (clear_trees and fighter.shape in TANK_SHAPES
                               and hit[1] is not None and hit[1].kind == "tree")

    def _queue_attack(self, fighter, shots):
        """Shooting and close attacks share one reload and the same manual fire control."""
        eligible = [target for target in fighter.melee_targets
                    if abs(_wrap(math.atan2(target.y - fighter.y, target.x - fighter.x) - fighter.aim)) <= MELEE_ARC]
        target = min(eligible, key=lambda enemy: math.hypot(enemy.x - fighter.x, enemy.y - fighter.y), default=None)
        shots.append((fighter, target))
        fighter.reload_interval = MELEE_INTERVAL if target is not None else FIRE_INTERVAL
        fighter.cooldown = fighter.reload_interval

    def _drive_player(self, fighter, dt, shots):
        self._steer(fighter, self._turn, dt)
        self._accelerate(fighter, self._throttle, dt)
        aim = self._aim_point
        self._slew_aim(fighter, fighter.aim if aim is None else math.atan2(aim[1] - fighter.y, aim[0] - fighter.x), dt)
        if self._fire and fighter.cooldown <= 0:
            self._queue_attack(fighter, shots)

    @staticmethod
    def advance_point(fighter, center, objective, offset=0.0):
        """Where a sub-unit heads while closing in: beside its division's objective, at its own place in the line.

        Sideways places keep their deployment order, so a division arrives spread out rather than in one clump.
        ``offset`` moves the whole division's destination further to one side, for flanking.
        """
        dx, dy = objective.x - center[0], objective.y - center[1]
        length = math.hypot(dx, dy)
        if length:
            dx, dy = dx / length, dy / length
        else:
            dx, dy = (-1.0, 0.0) if fighter.side else (1.0, 0.0)
        # Rotate the course a quarter turn so a positive slot stays on the side it deployed on.
        sideways = (-1.0 if fighter.side else 1.0) * (fighter.slot + offset)
        return (objective.x - dy * sideways, objective.y + dx * sideways), (dx, dy)

    def _can_hurt(self, shooter, target):
        """Whether a sub-unit can damage this target type; cached per type pair."""
        key = (shooter.data["type"], target.data["type"])
        if key not in self._hurts:
            self._hurts[key] = self._attack(shooter.data, target.data) > target.data["defense"]
        return self._hurts[key]

    def _choose_target(self, fighter, enemies):
        """The enemy to shoot: the nearest, unless one close to it is wounded and this sub-unit can hurt it.

        A wounded enemy counts as nearer, and enemies this sub-unit cannot damage are passed over.
        """
        nearest = enemies.nearest(fighter.x, fighter.y)
        best, best_score = None, math.inf
        for enemy in enemies.around(nearest.x, nearest.y, TARGET_CHOICE_SLACK):
            if not self._can_hurt(fighter, enemy):
                continue
            wounds = 1.0 - enemy.data["health"] / enemy.data["max_health"]
            score = math.hypot(enemy.x - fighter.x, enemy.y - fighter.y) * (1.0 - TARGET_WOUNDED_PULL * wounds)
            if not self._firing_lane(fighter, enemy):
                score += WEAPON_RANGE
            if score < best_score:
                best, best_score = enemy, score
        return best or nearest

    def _ai_course(self, fighter, distance, toward, center, objective):
        """(throttle share, heading) for an AI sub-unit. ``toward`` is the heading to the enemy it shoots at.

        Reactions come first: a badly hurt sub-unit falls back, and one that was just hit sidesteps.
        Otherwise its shape's behavior decides (BEHAVIORS).
        """
        away = toward + math.pi
        if (fighter.data["health"] < fighter.data["max_health"] * FALL_BACK_HEALTH
                and self._healthy_sides[fighter.side]):
            # Retreat while healthier allies cover the withdrawal. The last wounded
            # troops keep fighting, so two depleted armies do not both flee forever.
            fighter.melee_committed = False
            fighter.ram_committed = False
            if not self._firing_lane(fighter, fighter.target or objective, clear_trees=False):
                return 0.0, toward
            if fighter.shape not in MELEE_SHAPES:
                return (-fighter.pace, toward) if distance < WITHDRAW_RANGE else (0.0, toward)
            return (fighter.pace, away) if distance < WITHDRAW_RANGE else (0.0, toward)
        if fighter.ram_committed and (distance <= MELEE_COMMIT_RANGE or fighter.dodge <= 0):
            point = self._ram_point(fighter, fighter.target)
            if point is not None:
                return fighter.pace, math.atan2(point[1] - fighter.y, point[0] - fighter.x)
            return fighter.pace, toward
        if fighter.melee_committed:
            if distance <= MELEE_COMMIT_RANGE:
                return (fighter.pace if distance > MELEE_REACH else 0.0), toward
            if fighter.dodge <= 0:
                return fighter.pace, toward
        if fighter.dodge > 0:
            return fighter.pace, fighter.dodge_heading
        behavior = BEHAVIORS.get(fighter.shape)
        hold = fighter.hold
        if behavior == "skirmish":
            if distance < ENGAGEMENT_RANGE * SKIRMISH_BACK_OFF:
                return -fighter.pace, toward
            hold = SKIRMISH_HOLD
        elif behavior == "charge":
            if fighter.withdrawing and distance < ENGAGEMENT_RANGE * fighter.hold:
                return fighter.pace, away
            fighter.withdrawing = distance <= ENGAGEMENT_RANGE * CHARGE_CLOSE
            if fighter.withdrawing:
                return fighter.pace, away
            hold = CHARGE_CLOSE
        flanking = behavior == "flank" and not fighter.flank_complete
        if (distance <= ENGAGEMENT_RANGE * hold and not flanking
                and self._firing_lane(fighter, fighter.target or objective)):
            # In position: face the enemy it shoots at, so a firing cone covers it.
            return 0.0, toward
        if self.elapsed < fighter.start_delay:
            return 0.0, toward
        (goal_x, goal_y), (course_x, course_y) = self.advance_point(
            fighter, center, objective, fighter.lane)
        if flanking:
            if fighter.flank_goal is None:
                forward = -1.0 if fighter.side else 1.0
                fighter.flank_goal = (
                    max(UNIT_RADIUS, min(ARENA_SIZE[0] - UNIT_RADIUS,
                                        objective.x - forward * ENGAGEMENT_RANGE * hold)),
                    max(UNIT_RADIUS, min(ARENA_SIZE[1] - UNIT_RADIUS,
                                        objective.y + fighter.slot + fighter.lane + fighter.flank * FLANK_OFFSET)))
            goal_x, goal_y = fighter.flank_goal
            if math.hypot(goal_x - fighter.x, goal_y - fighter.y) <= FLANK_ARRIVAL_DISTANCE:
                fighter.flank_complete = True
                return 0.0, toward
        goal_y = max(UNIT_RADIUS, min(ARENA_SIZE[1] - UNIT_RADIUS, goal_y))
        weave = fighter.wander * math.sin(math.tau * self.elapsed / fighter.wander_period + fighter.wander_phase)
        throttle = fighter.pace
        # A sub-unit well ahead of its division slows down to let the division catch up; charging cavalry does not.
        if (behavior != "charge"
                and (fighter.x - center[0]) * course_x + (fighter.y - center[1]) * course_y > COHESION_SLACK):
            throttle *= COHESION_THROTTLE
        return throttle, math.atan2(goal_y - fighter.y, goal_x - fighter.x) + weave

    def _firing_position(self, fighter, target):
        """Find an accessible firing position; blocked shots never count as holding a position."""
        start = fighter.x, fighter.y
        preferred = ENGAGEMENT_RANGE * fighter.hold
        candidates = []
        toward = math.atan2(fighter.y - target.y, fighter.x - target.x)
        for scale in FIRING_POSITION_RINGS:
            for index in range(FIRING_POSITION_ANGLES):
                angle = toward + math.tau * index / FIRING_POSITION_ANGLES
                candidates.append((target.x + math.cos(angle) * preferred * scale,
                                   target.y + math.sin(angle) * preferred * scale))
        distance = math.dist(start, (target.x, target.y))
        if distance:
            fraction = min(1.0, FIRING_POSITION_STEP / distance)
            candidates.append((fighter.x + (target.x - fighter.x) * fraction,
                               fighter.y + (target.y - fighter.y) * fraction))
        # A nearby crest can be a better firing position than a long detour.
        candidates.extend((feature.x, feature.y) for feature in self.battlefield.nearby(
            start, start, ENGAGEMENT_RANGE) if feature.kind == "hill")
        candidates.sort(key=lambda point: math.dist(start, point)
                        + abs(math.dist(point, (target.x, target.y)) - preferred) * FIRING_DISTANCE_WEIGHT)
        for point in candidates:
            if (self.battlefield.walkable(point) and self._firing_lane(fighter, target, point)
                    and self.battlefield.route(start, point)):
                return point
        return target.x, target.y

    def _cover_position(self, fighter, target):
        start = fighter.x, fighter.y
        candidates = []
        for index in range(FIRING_POSITION_ANGLES):
            angle = math.tau * index / FIRING_POSITION_ANGLES
            point = (fighter.x + math.cos(angle) * FIRING_POSITION_STEP,
                     fighter.y + math.sin(angle) * FIRING_POSITION_STEP)
            if (self.battlefield.walkable(point)
                    and not self._firing_lane(fighter, target, point, clear_trees=False)):
                candidates.append(point)
        candidates.sort(key=lambda point: math.dist(start, point)
                        - math.dist(point, (target.x, target.y)) * COVER_DISTANCE_WEIGHT)
        return next((point for point in candidates if self.battlefield.route(start, point)), None)

    def _terrain_course(self, fighter, throttle, heading, center, objective):
        """Route the existing behavior around terrain without changing its controller or side."""
        target = fighter.target
        start = fighter.x, fighter.y
        if fighter.ram_committed and (fighter.dodge <= 0 or math.dist(start, (target.x, target.y)) <= MELEE_COMMIT_RANGE):
            return throttle, heading
        if not throttle:
            fighter.route.clear()
            return throttle, heading
        revision = self.battlefield.revision
        reconsider = (self.elapsed >= fighter.navigate_at or fighter.route_revision != revision
                      or fighter.position_target is not target)
        retreating = (fighter.data["health"] < fighter.data["max_health"] * FALL_BACK_HEALTH
                      and self._healthy_sides[fighter.side])
        if reconsider:
            fighter.navigate_at = self.elapsed + NAVIGATION_SECONDS
            fighter.route_revision = revision
            fighter.position_target = target
            fighter.position_goal = None
            flanking = BEHAVIORS.get(fighter.shape) == "flank" and not fighter.flank_complete
            if retreating:
                fighter.position_goal = self._cover_position(fighter, target)
            elif (not flanking and fighter.dodge <= 0 and not fighter.melee_committed
                  and not fighter.withdrawing and throttle > 0):
                if not self._firing_lane(fighter, target):
                    fighter.position_goal = self._firing_position(fighter, target)
            if fighter.position_goal is not None:
                goal = fighter.position_goal
            elif flanking and fighter.flank_goal is not None and fighter.dodge <= 0:
                goal = fighter.flank_goal
            elif throttle < 0 or retreating or fighter.withdrawing or fighter.dodge > 0:
                direction = heading + (math.pi if throttle < 0 else 0.0)
                goal = (fighter.x + math.cos(direction) * FIRING_POSITION_STEP,
                        fighter.y + math.sin(direction) * FIRING_POSITION_STEP)
            else:
                goal, _ = self.advance_point(fighter, center, objective, fighter.lane)
            fighter.route = self.battlefield.route(start, goal)
            if flanking and fighter.route:
                # A formation destination can fall inside an obstacle. Complete
                # the flank at its reachable replacement, then seek a clear shot.
                fighter.flank_goal = fighter.route[-1]
        while fighter.route and math.dist(start, fighter.route[0]) <= WAYPOINT_REACH:
            fighter.route.pop(0)
        while len(fighter.route) > 1 and self.battlefield.clear_path(start, fighter.route[1]):
            fighter.route.pop(0)
        if not fighter.route:
            # Reconsider a reached or invalid destination on the next decision.
            fighter.navigate_at = 0.0
            return 0.0, heading
        point = fighter.route[0]
        direction = math.atan2(point[1] - fighter.y, point[0] - fighter.x)
        if throttle < 0 and not fighter.position_goal:
            return throttle, direction + math.pi
        return abs(throttle), direction

    def _drive_ai(self, fighter, enemies, dt, shots, center, objective):
        fighter.retarget -= dt
        if fighter.retarget <= 0:
            fighter.retarget += RETARGET_SECONDS
            if not (fighter.melee_committed or fighter.ram_committed):
                fighter.target = None
        if fighter.target is None or not fighter.target.alive:
            fighter.target = self._choose_target(fighter, enemies)
        fighter.dodge = max(0.0, fighter.dodge - dt)
        target = fighter.target
        dx, dy = target.x - fighter.x, target.y - fighter.y
        distance = math.hypot(dx, dy)
        throttle, heading = self._ai_course(fighter, distance, math.atan2(dy, dx), center, objective)
        if self.battlefield.features:
            throttle, heading = self._terrain_course(fighter, throttle, heading, center, objective)
        turning = _wrap(heading - fighter.angle)
        # Turn toward the heading before driving hard along it.
        throttle *= max(0.0, math.cos(turning))
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
                and self._attack(fighter.data, target.data) > 0 and self._firing_lane(fighter, target)):
            self._queue_attack(fighter, shots)

    def _fire_shot(self, fighter):
        # The shot leaves slightly off the aim, so the same error misses more often at long range.
        angle = fighter.aim + self._rng.uniform(-SHOT_SPREAD, SHOT_SPREAD)
        start = fighter.x, fighter.y
        point = self._aim_point if fighter is self.controlled else (
            (fighter.target.x, fighter.target.y) if fighter.target is not None else None)
        height = self.battlefield.elevation(start) + battle_terrain.WEAPON_HEIGHT
        vertical_speed = 0.0
        if point is not None and math.dist(start, point) > 0:
            vertical_speed = ((self.battlefield.elevation(point) + battle_terrain.WEAPON_HEIGHT - height)
                              * PROJECTILE_SPEED / math.dist(start, point))
        self.projectiles.append(Projectile(
            fighter, dict(fighter.data), fighter.x, fighter.y, math.cos(angle) * PROJECTILE_SPEED,
            math.sin(angle) * PROJECTILE_SPEED, WEAPON_RANGE / PROJECTILE_SPEED,
            height=height, vertical_speed=vertical_speed))
        if self.on_shot is not None:
            self.on_shot(fighter)

    def _can_dodge(self, unit):
        """Only fast AI sub-units sidestep; for slower ones the time spent turning away costs more aim than it saves."""
        return unit is not self.controlled and unit.data["speed"] >= DODGE_MIN_SPEED

    def _start_dodge(self, unit, shot):
        """Sidestep at right angles to a shot's path, away from it (to a random side when it is dead on)."""
        # How far the unit sits to the left of the shot's path; negative is to the right.
        offset = ((unit.y - shot.y) * shot.vx - (unit.x - shot.x) * shot.vy) / math.hypot(shot.vx, shot.vy)
        side = (1 if offset > 0 else -1) if abs(offset) > 1e-9 else self._rng.choice((-1, 1))
        unit.dodge = DODGE_SECONDS
        unit.dodge_heading = math.atan2(shot.vy, shot.vx) + side * math.pi / 2

    def _ready_to_fire(self, unit):
        """Whether an AI sub-unit is about to shoot: loaded, with its target in range. It then holds rather than dodging."""
        target = unit.target
        return (unit.cooldown <= 0 and target is not None and target.alive
                and math.hypot(target.x - unit.x, target.y - unit.y) <= WEAPON_RANGE
                and self._firing_lane(unit, target))

    def _dodge_incoming(self, crowds):
        """AI sub-units that are not about to fire sidestep enemy shots whose paths will pass close to them."""
        for shot in self.projectiles:
            speed = math.hypot(shot.vx, shot.vy)
            lookahead = min(DODGE_LOOKAHEAD, shot.remaining)
            reach = speed * lookahead
            end_x, end_y = shot.x + shot.vx / speed * reach, shot.y + shot.vy / speed * reach
            blocked = self.battlefield.first_hit((shot.x, shot.y), (end_x, end_y), shot.height,
                                                 shot.height + shot.vertical_speed * lookahead)
            if blocked is not None:
                reach *= blocked[0]
                end_x, end_y = shot.x + shot.vx / speed * reach, shot.y + shot.vy / speed * reach
            for unit in crowds[1 - shot.source.side].within(
                    min(shot.x, end_x) - DODGE_DANGER, min(shot.y, end_y) - DODGE_DANGER,
                    max(shot.x, end_x) + DODGE_DANGER, max(shot.y, end_y) + DODGE_DANGER):
                if (not self._can_dodge(unit) or unit.dodge > 0 or self._ready_to_fire(unit)
                        or ((unit.melee_committed or unit.ram_committed) and unit.target is not None
                            and math.hypot(unit.x - unit.target.x, unit.y - unit.target.y) <= MELEE_COMMIT_RANGE)):
                    continue
                along = ((unit.x - shot.x) * shot.vx + (unit.y - shot.y) * shot.vy) / speed
                across = ((unit.y - shot.y) * shot.vx - (unit.x - shot.x) * shot.vy) / speed
                if 0 <= along <= reach and abs(across) <= DODGE_DANGER:
                    self._start_dodge(unit, shot)

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

    def _ram_point(self, unit, target):
        """Predict a reachable impact with enough run-up; a nearby target need not be catchable."""
        if target is None:
            return None
        speed = unit.max_speed * unit.pace
        if speed < RAM_MIN_SPEED:
            return None
        dx, dy = target.x - unit.x, target.y - unit.y
        a = target.vx ** 2 + target.vy ** 2 - speed ** 2
        b = 2 * (dx * target.vx + dy * target.vy)
        c = dx * dx + dy * dy
        if abs(a) < 1e-9:
            times = [-c / b] if abs(b) > 1e-9 else []
        else:
            discriminant = b * b - 4 * a * c
            times = [] if discriminant < 0 else [(-b - math.sqrt(discriminant)) / (2 * a),
                                                 (-b + math.sqrt(discriminant)) / (2 * a)]
        arrival = min((time for time in times if time > 0), default=math.inf)
        if arrival > RAM_APPROACH_RANGE / RAM_MIN_SPEED:
            return None
        point = target.x + target.vx * arrival, target.y + target.vy * arrival
        runup = max(0.0, math.dist((unit.x, unit.y), point) - UNIT_RADIUS * 2)
        acceleration = unit.max_speed / MOBILITY[unit.shape][0]
        impact_speed = min(speed, math.sqrt(max(0.0, unit.speed) ** 2 + 2 * acceleration * runup))
        distance = math.dist((unit.x, unit.y), point)
        closing = impact_speed - ((target.vx * (point[0] - unit.x) + target.vy * (point[1] - unit.y)) / distance
                                  if distance else 0.0)
        if (impact_speed < RAM_MIN_SPEED or closing < RAM_MIN_SPEED
                or not self.battlefield.clear_path((unit.x, unit.y), point)):
            return None
        if any(other is not unit and other is not target and other.alive
               and battle_terrain.circle_contact((unit.x, unit.y), point, (other.x, other.y),
                                                  UNIT_RADIUS * 2) is not None
               for other in self.fighters):
            return None
        return point

    def _ram_opportunity(self, unit, target, support, threats):
        distance = math.hypot(target.x - unit.x, target.y - unit.y)
        committed = unit.ram_committed and unit.target is target
        return (unit.data["health"] >= unit.data["max_health"] * RAM_MIN_HEALTH
                and distance <= RAM_APPROACH_RANGE
                and CONTACT_MASS[unit.shape] >= CONTACT_MASS[target.shape] * RAM_MASS_ADVANTAGE
                and self._can_hurt(unit, target) and threats <= support
                and tuple(sorted((unit.index, target.index))) not in self._contacts
                and (committed or (distance > MELEE_COMMIT_RANGE
                     and (target.cooldown > FIRE_INTERVAL / 2
                          or target.data["health"] <= target.data["max_health"] * MELEE_WOUNDED_TARGET)))
                and self._ram_point(unit, target) is not None)

    def _prepare_close_combat(self, sides, crowds):
        """Find contact attacks for both controllers; only AI chooses whether to close in."""
        for side, units in enumerate(sides):
            for unit in units:
                unit.melee_targets = ()
                approach = MELEE_APPROACH_RANGE if unit.shape in MELEE_SHAPES else RAM_APPROACH_RANGE
                nearby = [enemy for enemy in crowds[1 - side].around(unit.x, unit.y, approach)
                          if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= approach]
                if unit.shape in MELEE_SHAPES:
                    contacts = [enemy for enemy in nearby
                                if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= MELEE_REACH
                                and self._can_hurt(unit, enemy)
                                and self.battlefield.clear_path((unit.x, unit.y), (enemy.x, enemy.y))]
                    unit.melee_targets = tuple(contacts)
                if unit is self.controlled:
                    continue
                if not nearby:
                    unit.melee_committed = unit.ram_committed = False
                    continue
                target = unit.target
                if target is None or not target.alive or not (unit.melee_committed or unit.ram_committed):
                    target = min(nearby, key=lambda enemy: math.hypot(enemy.x - unit.x, enemy.y - unit.y), default=None)
                friends = [friend for friend in crowds[side].around(unit.x, unit.y, MELEE_APPROACH_RANGE)
                           if math.hypot(friend.x - unit.x, friend.y - unit.y) <= MELEE_APPROACH_RANGE
                           and self.battlefield.clear_path((unit.x, unit.y), (friend.x, friend.y))]
                threats = sum(1 for enemy in crowds[1 - side].around(unit.x, unit.y, WEAPON_RANGE)
                              if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= WEAPON_RANGE
                              and self._can_hurt(enemy, unit)
                              and self._firing_lane(enemy, unit, clear_trees=False))
                if unit.shape not in MELEE_SHAPES:
                    unit.melee_committed = False
                    candidates = sorted(nearby, key=lambda enemy: (
                        not (unit.ram_committed and enemy is unit.target),
                        math.hypot(enemy.x - unit.x, enemy.y - unit.y)))
                    opportunity = next((enemy for enemy in candidates
                                        if self._ram_opportunity(unit, enemy, len(friends), threats)), None)
                    unit.ram_committed = opportunity is not None
                    if opportunity is not None:
                        unit.target = opportunity
                    continue
                unit.ram_committed = False
                safe = (target is not None and target.shape in MELEE_SHAPES
                        and unit.data["health"] >= unit.data["max_health"] * MELEE_MIN_HEALTH
                        and math.hypot(target.x - unit.x, target.y - unit.y) <= MELEE_APPROACH_RANGE
                        and self._can_hurt(unit, target)
                        and self.battlefield.clear_path((unit.x, unit.y), (target.x, target.y))
                        and threats <= len(friends) * MELEE_SUPPORT_RATIO)
                opportunity = safe and (
                    unit.melee_committed
                    or target.data["health"] <= target.data["max_health"] * MELEE_WOUNDED_TARGET
                    or len(friends) >= len(nearby) * MELEE_SUPPORT_RATIO
                    or (len(nearby) == 1 and target.cooldown > FIRE_INTERVAL / 2))
                unit.melee_committed = bool(opportunity)
                if opportunity:
                    unit.target = target

    @staticmethod
    def _set_contact_velocity(unit, vx, vy):
        """Inelastic contact stops closing motion; remaining sideways motion decays quickly."""
        forward = vx * math.cos(unit.angle) + vy * math.sin(unit.angle)
        unit.speed = max(-unit.max_speed, min(unit.max_speed, forward))
        unit.push_vx = max(-KNOCKBACK_MAX_SPEED, min(KNOCKBACK_MAX_SPEED, vx - unit.speed * math.cos(unit.angle)))
        unit.push_vy = max(-KNOCKBACK_MAX_SPEED, min(KNOCKBACK_MAX_SPEED, vy - unit.speed * math.sin(unit.angle)))

    def _resolve_contacts(self, living, crowds, movements, dt):
        """Resolve each swept body pair once, with no bounce and one ram per approach.

        Relative motion catches head-on crossings between ticks. Contact mass decides
        which body yields, while the normal closing speed rejects glancing impacts.
        Friendly contact separates bodies but never causes damage.
        """
        positions = {unit.index: list(self.battlefield.move((unit.x, unit.y), (unit.x + mx, unit.y + my)))
                     for unit, mx, my in movements}
        velocities = {unit.index: ((positions[unit.index][0] - unit.x) / dt,
                                   (positions[unit.index][1] - unit.y) / dt) for unit, _, _ in movements}
        max_move = max((math.hypot(mx, my) for _, mx, my in movements), default=0.0)
        retained = set()
        for pair in self._contacts:
            first, second = (self.fighters[index] for index in pair)
            if first.alive and second.alive and math.hypot(first.x - second.x, first.y - second.y) <= CONTACT_RELEASE_DISTANCE:
                retained.add(pair)
        damage = []
        diameter = UNIT_RADIUS * 2
        for unit in living:
            vx, vy = velocities[unit.index]
            reach = math.hypot(vx, vy) * dt + max_move + diameter
            for crowd in crowds:
                for other in crowd.around(unit.x, unit.y, reach):
                    if other.index <= unit.index:
                        continue
                    ovx, ovy = velocities[other.index]
                    fraction = self._collision_fraction(
                        unit.x, unit.y, unit.x + (vx - ovx) * dt, unit.y + (vy - ovy) * dt,
                        other, radius=diameter)
                    if fraction is None:
                        continue
                    dx = other.x - unit.x + (ovx - vx) * dt * fraction
                    dy = other.y - unit.y + (ovy - vy) * dt * fraction
                    length = math.hypot(dx, dy)
                    nx, ny = (dx / length, dy / length) if length > 1e-9 else (1.0, 0.0)
                    first_mass, second_mass = CONTACT_MASS[unit.shape], CONTACT_MASS[other.shape]
                    total = first_mass + second_mass
                    first_pos, second_pos = positions[unit.index], positions[other.index]
                    overlap = max(0.0, diameter - ((second_pos[0] - first_pos[0]) * nx
                                                   + (second_pos[1] - first_pos[1]) * ny))
                    first_pos[0] -= nx * overlap * second_mass / total
                    first_pos[1] -= ny * overlap * second_mass / total
                    second_pos[0] += nx * overlap * first_mass / total
                    second_pos[1] += ny * overlap * first_mass / total
                    closing = max(0.0, (vx - ovx) * nx + (vy - ovy) * ny)
                    pair = (unit.index, other.index)
                    if pair not in retained and unit.side != other.side and closing >= RAM_MIN_SPEED:
                        for source, target, speed, mass, target_mass in (
                                (unit, other, vx * nx + vy * ny, first_mass, second_mass),
                                (other, unit, -ovx * nx - ovy * ny, second_mass, first_mass)):
                            if source.shape in MELEE_SHAPES or speed < RAM_MIN_SPEED:
                                continue
                            strength = min(RAM_MAX_STRENGTH, closing / RAM_REFERENCE_SPEED) * min(1.0, mass / target_mass)
                            damage.append((target, self.damage_amount(source.data, target.data, source.attack_share,
                                                                      RAM_DAMAGE * strength)))
                    retained.add(pair)
                    if closing > 0:
                        impulse = closing / (1 / first_mass + 1 / second_mass)
                        vx, vy = vx - nx * impulse / first_mass, vy - ny * impulse / first_mass
                        ovx, ovy = ovx + nx * impulse / second_mass, ovy + ny * impulse / second_mass
                        velocities[unit.index], velocities[other.index] = (vx, vy), (ovx, ovy)
                        self._set_contact_velocity(unit, vx, vy)
                        self._set_contact_velocity(other, ovx, ovy)
        self._contacts = retained
        for unit in living:
            x, y = positions[unit.index]
            x, y = self.battlefield.move((unit.x, unit.y), (x, y))
            unit.vx, unit.vy = (x - unit.x) / dt, (y - unit.y) / dt
            unit.x, unit.y = x, y
        return damage

    def _step(self, dt):
        if int(self.elapsed / RETARGET_SECONDS) != int((self.elapsed + dt) / RETARGET_SECONDS):
            self.battlefield.begin_decision_interval()
        self.elapsed += dt
        living = [fighter for fighter in self.fighters if fighter.alive]
        sides = [[fighter for fighter in living if fighter.side == side] for side in (0, 1)]
        crowds = [_Grid(side, GRID_CELL) for side in sides]
        targets = [_Grid(side, TARGET_CELL) for side in sides]
        self._healthy_sides = [any(unit.data["health"] >= unit.data["max_health"] * FALL_BACK_HEALTH
                                  for unit in side) for side in sides]
        objectives = self._division_objectives(targets, dt)
        self._prepare_close_combat(sides, crowds)
        self._dodge_incoming(crowds)
        # All movement and fire decisions use the same pre-step positions.
        movements = []
        shots = []
        for fighter in living:
            if not sides[1 - fighter.side]:
                movements.append((fighter, 0.0, 0.0))
                continue
            fighter.cooldown = max(0.0, fighter.cooldown - dt)
            player_controlled = fighter is self.controlled
            if player_controlled:
                self._drive_player(fighter, dt, shots)
            else:
                self._drive_ai(fighter, targets[1 - fighter.side], dt, shots, *objectives[fighter.division])
            move = fighter.speed * dt
            mx = math.cos(fighter.angle) * move + fighter.push_vx * dt
            my = math.sin(fighter.angle) * move + fighter.push_vy * dt
            decay = max(0.0, 1.0 - dt / KNOCKBACK_SECONDS)
            fighter.push_vx *= decay
            fighter.push_vy *= decay
            movements.append((fighter, mx, my))
        close_hits = []
        for fighter, melee_target in shots:
            if melee_target is None:
                self._fire_shot(fighter)
            else:
                close_hits.append((melee_target, self.damage_amount(
                    fighter.data, melee_target.data, fighter.attack_share, MELEE_DAMAGE)))
        close_hits.extend(self._resolve_contacts(living, crowds, movements, dt))

        # Accumulate impacts first so units destroyed together can both land their shots.
        hittable = [_Grid(side, GRID_CELL) for side in sides]
        hits = []
        remaining = []
        for shot in self.projectiles:
            enemies = hittable[1 - shot.source.side]
            flight = min(dt, shot.remaining)
            if flight <= 0:
                continue
            nx, ny = shot.x + shot.vx * flight, shot.y + shot.vy * flight
            next_height = shot.height + shot.vertical_speed * flight
            traveled = math.hypot(shot.vx, shot.vy) * flight
            terrain_hit = self.battlefield.first_hit((shot.x, shot.y), (nx, ny), shot.height, next_height)
            collisions = []
            for target in enemies.within(min(shot.x, nx) - UNIT_RADIUS, min(shot.y, ny) - UNIT_RADIUS,
                                         max(shot.x, nx) + UNIT_RADIUS, max(shot.y, ny) + UNIT_RADIUS):
                fraction = self._collision_fraction(shot.x, shot.y, nx, ny, target)
                ground = self.battlefield.elevation((target.x, target.y))
                impact_height = shot.height + (next_height - shot.height) * (fraction or 0.0)
                if fraction is not None and ground <= impact_height <= ground + battle_terrain.BODY_HEIGHT:
                    collisions.append((fraction, target))
            impact = min(collisions, key=lambda item: item[0], default=None)
            if terrain_hit is not None and (impact is None or terrain_hit[0] <= impact[0]):
                feature = terrain_hit[1]
                if feature is not None and shot.source.shape in TANK_SHAPES:
                    # A shell spends its impact clearing one tree; it never passes through that tree.
                    self.battlefield.destroy_tree(feature)
            elif impact is not None:
                fraction, target = impact
                shot.distance += traveled * fraction
                hits.append((shot, target))
            else:
                shot.x, shot.y = nx, ny
                shot.height = next_height
                shot.distance += traveled
                shot.remaining -= flight
                if shot.remaining > 0:
                    remaining.append(shot)
        self.projectiles = remaining
        for shot, target in hits:
            # Attack is measured against the unit actually hit, so its capability rules apply.
            # Tactical defense blocks a flat amount per hit, even when wounded.
            # Campaign combat instead scales defense with remaining health.
            # A sub-unit's hit carries its share of its division's damage, so a full division hits as hard as
            # one unsplit unit while the full attack against full defense still decides who can hurt whom.
            loss = self.damage_amount(shot.source_data, target.data, shot.source.attack_share,
                                      self.ranged_multiplier(shot.distance))
            close_hits.append((target, loss))
            if loss > 0 and target.alive and self._can_dodge(target):
                self._start_dodge(target, shot)
        for target, loss in close_hits:
            target.data["health"] = max(0.0, target.data["health"] - loss)
        alive_sides = {fighter.side for fighter in self.fighters if fighter.alive}
        if len(alive_sides) < 2:
            # Mutual destruction is a loss for the friendly army; there is no draw screen.
            self.winner = 0 if 0 in alive_sides else 1

    @staticmethod
    def _collision_fraction(x, y, nx, ny, target, radius=UNIT_RADIUS):
        """First swept contact prevents fast shells and bodies from skipping their targets."""
        return battle_terrain.circle_contact((x, y), (nx, ny), (target.x, target.y), radius)
