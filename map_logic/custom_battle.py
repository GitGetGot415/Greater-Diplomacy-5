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
FIXED_STEP = 1.0 / 30.0 # 33 milliseconds per step, or 30 simulation steps per second
MOVE_PIXELS_PER_SPEED = 60.0
FIRE_INTERVAL = c.TACTICAL_WEAPONS["rifle"]["reload"]
DAMAGE_SCALE = 1.0  # Applied after defense and rounding, so low-damage hits also slow down.
# Attack at zero HP: 0.0 = directly proportional to HP; 1.0 = wounds do not reduce attack.
# Values between 0 and 1 interpolate linearly. Applies to each surviving sub-unit.
TACTICAL_DAMAGE_AT_ZERO_HEALTH = 1.0
WEAPON_RANGE = 1200.0
PROJECTILE_SPEED = c.TACTICAL_WEAPONS["rifle"]["speed"]
ENGAGEMENT_RANGE = 300.0  # Preferred distances do not grow with maximum projectile reach.
WITHDRAW_RANGE = 500.0
FALLOFF_START = 400.0
MIN_RANGED_DAMAGE = 0.45
UNIT_RADIUS = c.TACTICAL_BODIES["infantry"][2]
MAX_UNIT_RADIUS = max(body[2] for body in c.TACTICAL_BODIES.values())
SHOT_SPREAD = math.radians(c.TACTICAL_WEAPONS["rifle"]["spread"])
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
CANNON_ARMOR_PRIORITY = 0.7  # Relative target score for nearby armored threats.
AIM_TOLERANCE = math.radians(4)  # AI units fire once the gun points this close to the aim angle.
RETARGET_SECONDS = 0.25  # AI units choose the nearest enemy again this often.
# Collision and separation cells, and the coarser cells of the nearest-enemy search.
GRID_CELL = 64.0
TARGET_CELL = 256.0
# Each division deploys as one vertical line of its sub-units, one division per rank.
# Roster order runs front to back: the first division stands closest to the enemy.
RANK_GAP = 56.0  # Between ranks, front to back; leaves room for the largest hull.
SUBUNIT_SPACING = 60.0  # Between neighboring sub-units along a division's line.
# Distance between the two armies' front ranks at deployment, centered on the battlefield.
SPAWN_FRONT_GAP = 2000.0
SPAWN_MARGIN = 100.0  # Between the battlefield edge and the last rank of the largest army.
# The battlefield is twice as wide as it is tall, with room for two full armies behind their front ranks.
ARENA_WIDTH = SPAWN_FRONT_GAP + 2 * (SPAWN_MARGIN + (c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE - 1) * RANK_GAP)
ARENA_SIZE = (ARENA_WIDTH, ARENA_WIDTH / 2)
APPROACH_LANE_GAP = 70.0
FLANK_ARRIVAL_DISTANCE = 45.0
FOOT_SHAPES = frozenset(("infantry", "cavalry"))  # Turn away to withdraw; vehicles reverse.
SOFT_TARGET_SHAPES = frozenset(("infantry", "cavalry", "motorized"))
RAM_MIN_UNIT_SPEED = 2.0  # Library movement speed required to deal impact damage.
RAM_SUPPORT_RANGE = 160.0   # Radius used to count friendly support, including the attacker itself
RAM_COMMIT_RANGE = 60.0 # Inside this distance, committed attackers stop dodging and finish the approach
RAM_WOUNDED_TARGET = 0.6 # At this % of health or lower, the AI will consider ramming this target
RAM_APPROACH_RANGE = 280.0 # Maximum distance at which the AI considers a ram target
RAM_MIN_HEALTH = 0.65 # The rammer needs this much HP to begin or continue a deliberate ram
RAM_MASS_ADVANTAGE = 2.0 # The AI attacker needs at least this much compared to the target’s mass
CONTACT_RELEASE_DISTANCE = UNIT_RADIUS * 3 # The two units must separate beyond this center-to-center distance before their next collision can deal ram damage
RAM_MIN_SPEED = 60.0 # Must go this fast for a ram to deal damage
RAM_MAX_STRENGTH = 1.5 # Caps the speed-strength multiplier
RAM_DAMAGE = 2.0 # Damage multiplier for how much Ramming does compared to a bullet shot
RAM_REFERENCE_SPEED = 120.0 # Damage multiplier applies at this speed
KNOCKBACK_MAX_SPEED = 100.0 # Caps each horizontal and vertical component of extra collision push
KNOCKBACK_SECONDS = 0.25 # Controls how quickly extra push fades. Larger values make the push persist longer
# Shots hurt allies too, so AI sub-units keep out of each other's way.
LINE_SHIFT_SECONDS = 0.6  # A loaded AI sub-unit whose shot would cross an ally sidesteps this long.
ALLY_BUMP_SPEED = RAM_MIN_SPEED * 0.5  # Speed allowance used by AI braking to approach allies without damaging them
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
    "infantry": 1.0, "cavalry": 3.0, "armored_car": 4.0, "motorized": 4.0,
    "light_tank": 6.0, "mechanized": 6.0, "ifv": 7.0, "tank": 9.0, "heavy_tank": 14.0,
}
RANDOM_ARMY_MIN_UNITS = 3
RANDOM_ARMY_MAX_UNITS = 5
RANDOM_UNIT_AGE_LIMIT = 5
# Placeholder countries for the normal-game forecast; real country IDs never use these names.
FORECAST_NATIONS = ("Custom Battle Friendly Army", "Custom Battle Enemy Army")
# Library families that get their own silhouette; TACTICAL_BODIES owns their sizes.
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


def campaign_sides(player_unit, province, nation_data):
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
    sides = campaign_sides(player_unit, province, nation_data)
    # Convoys caught on land unload before fighting. Recognize their divisions
    # without first building or simulating an automatic campaign battle.
    def land_type(unit):
        if unit.get("type", "").startswith("Convoy (") and not queries.is_water_province(province):
            return unit.get("original_type")
        return unit.get("type")

    friendly, enemy = ([unit for unit in side if land_type(unit) in land][:c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE]
                       for side in sides)
    if not friendly or friendly[0] is not player_unit or not (enemy or _artillery(sides[1], library)):
        return None
    return friendly, enemy


def campaign_artillery(player_unit, province, nation_data, library):
    """The land artillery-type units (friendly, enemy) on a tactical player's tile, which sit the battle out."""
    return tuple(_artillery(side, library) for side in campaign_sides(player_unit, province, nation_data))


def _remove_defeated_units(province, units):
    """Clear defeated units, including reserves that never deployed, before refreshing campaign combat."""
    for unit in units:
        unit["health"] = 0
    province["units"] = [unit for unit in province["units"] if unit.get("health", 0) > 0]


def win_against_artillery(player_unit, province, nation_data, library):
    """Hostile artillery alone cannot fight a tactical battle: the player wins at once and that artillery is destroyed."""
    _remove_defeated_units(province, campaign_sides(player_unit, province, nation_data)[1])


def tactical_encounter(context, province):
    """The (friendly, enemy) campaign units of the tactical encounter on ``province``, or None.

    Only the tile holding the tactical player's land unit has one, and only while hostile land
    units share it. The encounter deals that tile's damage, so campaign combat must skip the tile.
    """
    session = session_for(context)
    # Lightweight test doubles carry no tactical state.
    if (getattr(session, "multiplayer_mode", False)
            or getattr(session, "realtime_multiplayer", False)):
        return None
    unit = getattr(session, "tactical_mode", False) and getattr(session, "player_unit", None)
    if not unit or not any(other is unit for other in province.get("units", [])):
        return None
    return campaign_forces(unit, province, world_for(context).nation_data, queries.get_unit_library(context))


def tactical_meeting_side(context, prov1, prov2, units1, units2, *, pinned_units=None):
    """The tactical player's movement side, when a hostile crossing can become a tile encounter."""
    session = session_for(context)
    # Standalone rule tests can omit session fields. Multiplayer has no tactical encounters.
    if (not getattr(session, "tactical_mode", False)
            or getattr(session, "multiplayer_mode", False)
            or getattr(session, "realtime_multiplayer", False)):
        return None
    unit = getattr(session, "player_unit", None)
    if unit is None:
        return None
    for index, (side, opponents) in enumerate(((units1, units2), (units2, units1))):
        if any(other is unit for other in side):
            destination = (prov1, prov2)[1 - index]
            if unit.get("speed", 1) <= 0 or not queries.can_land_units_enter(
                    queries.get_unit_combat_owner(unit), destination, world_for(context).nation_data):
                return None
            # A separate incoming attack takes precedence over the player's
            # head-on crossing. Movement applies this same rule at every step.
            if pinned_units is None:
                pinned_units = queries.find_movement_pins(context)
            if id(unit) in pinned_units:
                return None
            # Only hostile land forces, including artillery sitting the battle out,
            # can start the existing tactical encounter flow.
            forces = campaign_forces(unit, {"units": [unit, *opponents]},
                                     world_for(context).nation_data, queries.get_unit_library(context))
            return index if forces is not None else None
    return None


def campaign_roster(units, library):
    """Battle roster entries for campaign units, keeping each unit's fraction of health."""
    roster = []
    for unit in units:
        entry = queries.create_unit_dict(unit["type"], unit["owner"], library)
        entry["health"] = unit["health"] / unit["max_health"] * entry["max_health"]
        roster.append(entry)
    return roster


def apply_campaign_result(simulation, units, province, artillery, *, side_units=None, player_unit=None):
    """Write a finished battle back: each unit keeps its division's fraction of health and the dead are removed.

    ``units`` are the campaign units in roster order, friendly army then enemy army.
    ``artillery`` is (friendly, enemy) from campaign_artillery. The losing side's artillery is
    destroyed; the winning side's is untouched. Campaign callers supply ``side_units`` from
    campaign_sides so the defeat also clears units beyond the deployment limit and other
    nonparticipants on the defeated side. Neutral units and winning reserves are untouched.
    A victory preserves the player's division at 1 HP if all of its sub-units were destroyed.
    """
    for index, unit in enumerate(units):
        unit["health"] = simulation.division_health_fraction(index) * unit["max_health"]
        if unit is player_unit and simulation.winner == 0 and unit["health"] <= 0:
            unit["health"] = 1
    defeated = (artillery if side_units is None else side_units)[1 - simulation.winner]
    _remove_defeated_units(province, defeated)


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


def weapon_target_allowed(weapon, shape):
    """Shared weapon restriction for AI choices and impacts, including friendly fire."""
    return (weapon is not None and weapon["damage"] > 0
            and (not weapon["soft_only"] or shape in SOFT_TARGET_SHAPES))


def division_deployment(unit, shape):
    """Spawn count and individual stats for a positive-health division, shared with roster previews."""
    size = SUBUNIT_COUNTS[shape]
    # The small allowance keeps float error from adding a sub-unit: 0.7 * 10 is 7.000000000000001.
    count = max(1, math.ceil(unit["health"] / unit["max_health"] * size - 1e-9))
    return count, dict(unit, max_health=unit["max_health"] / size, health=unit["health"] / count)


def division_attack(unit, library):
    """Total deployed attack before target defense, rounding, and tactical pacing."""
    shape = unit_shape(unit["type"], library)
    count, subunit = division_deployment(unit, shape)
    multiplier = combat_rules.effective_damage_multiplier(subunit, health_floor=TACTICAL_DAMAGE_AT_ZERO_HEALTH)
    return unit["attack"] * multiplier * count / SUBUNIT_COUNTS[shape]


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
    angle: float = 0.0  # Hull heading: movement follows it.
    aim: float = 0.0  # Gun heading: shots follow it.
    speed: float = 0.0  # Signed forward speed in pixels per second.
    turn_rate: float = 0.0  # Radians per second.
    index: int = 0
    lane: float = 0.0
    flank_goal: object = None
    flank_complete: bool = False
    ram_committed: bool = False
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
    primary_weapon: object = None  # None uses the shape's standard loadout.
    secondary_cooldown: float = 0.0
    primary_rounds: int = 0
    secondary_rounds: int = 0
    primary_wait: float = FIRE_INTERVAL
    secondary_wait: float = FIRE_INTERVAL
    muzzle: float = 0.0
    recoil: float = 0.0
    fired_weapon: int = 0  # Presentation callback reads which independent gun fired.
    secondary_target: object = None

    @property
    def radius(self):
        return c.TACTICAL_BODIES[self.shape][2]

    def weapon(self, slot=0):
        loadout = c.TACTICAL_VEHICLE_WEAPONS.get(self.shape)
        if slot == 1:
            return c.TACTICAL_WEAPONS[loadout[1]] if loadout else None
        name = loadout[0] if loadout else self.primary_weapon or "rifle"
        return c.TACTICAL_WEAPONS[name]

    def weapon_cooldown(self, slot=0):
        return self.secondary_cooldown if slot else self.cooldown

    def reload_duration(self, slot=0):
        return self.secondary_wait if slot else self.primary_wait

    @property
    def alive(self):
        return self.data["health"] > 0

    @property
    def max_speed(self):
        return max(0, self.data["speed"]) * MOVE_PIXELS_PER_SPEED

    @property
    def can_ram(self):
        return self.data["speed"] >= RAM_MIN_UNIT_SPEED


@dataclass
class Projectile:
    """A shot in flight; shells can pass bodies while their penetration budget lasts."""

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
    weapon_data: object = None  # Snapshot the gun as well as the shooter at launch.
    penetration: object = None
    power: float = 1.0
    hit_units: set = field(default_factory=set)

    def __post_init__(self):
        if self.weapon_data is None:
            self.weapon_data = dict(self.source.weapon())
        if self.penetration is None:
            self.penetration = self.weapon_data["penetration"]


class _Grid:
    """Buckets living sub-units by cell so nearby lookups skip the rest of the field."""

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
    on_hit: object = None  # Optional presentation callback: struck body and HP actually lost.
    on_kill: object = None  # Optional presentation callback: source, destroyed sub-unit, and shot/ram.
    controlled: object = field(init=False, default=None)
    fighters: list = field(init=False, default_factory=list)
    divisions: list = field(init=False, default_factory=list)  # Sub-unit lists, friendly roster then enemy roster.
    projectiles: list = field(init=False, default_factory=list)
    impacts: list = field(init=False, default_factory=list)  # (x, y, remaining seconds, shell).
    winner: object = field(init=False, default=None)
    elapsed: float = field(init=False, default=0.0)
    paused: bool = field(init=False, default=False)
    _division_health: list = field(init=False, default_factory=list)  # Each division's full health.
    _division_targets: list = field(init=False, default_factory=list)  # The enemy each division advances on.
    _division_retarget: list = field(init=False, default_factory=list)  # Seconds until each chooses again.
    _rng: object = field(init=False, default=None)
    _full_attacks: dict = field(init=False, default_factory=dict)  # Full-health attack per shooter/target type pair.
    _accumulator: float = field(init=False, default=0.0)
    _throttle: float = field(init=False, default=0.0)
    _turn: float = field(init=False, default=0.0)
    _move_direction: object = field(init=False, default=None)  # Optional battlefield direction from the mobile drive pad.
    _fire: bool = field(init=False, default=False)
    _secondary_fire: bool = field(init=False, default=False)
    _aim_point: object = field(init=False, default=None)
    _healthy_sides: list = field(init=False, default_factory=lambda: [True, True])
    _sides: list = field(init=False, default_factory=lambda: [[], []])  # Each side's living sub-units this tick.
    _contacts: set = field(init=False, default_factory=set)  # Rearm a ram only after the pair separates.

    def __post_init__(self):
        if self.controlled_index is not None and (
                type(self.controlled_index) is not int or not 0 <= self.controlled_index < len(self.friendly)):
            raise ValueError("The controlled unit must be an existing friendly roster entry.")
        self._rng = random.Random(self.seed)
        if self.battlefield is None:
            self.battlefield = battle_terrain.Battlefield.generate(
                self.terrain, ARENA_SIZE, MAX_UNIT_RADIUS, SPAWN_FRONT_GAP, self.seed,
                deployment_half_height=(max(SUBUNIT_COUNTS.values()) - 1) * SUBUNIT_SPACING / 2)
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

    def enemy_has_tanks(self):
        """Whether the enemy army deployed a tank. Tactical battle music uses this; friendly tanks do not count."""
        return any(fighter.side == 1 and fighter.shape in TANK_SHAPES for fighter in self.fighters)

    def _deploy_division(self, data, side, x, shape):
        """Split one division into sub-units standing in a vertical line at ``x``, centered top to bottom.

        A division at fraction ``f`` of full health brings ceil(f * N) of its N sub-units,
        sharing its health equally: 63% of 10 is 7 sub-units at 90% each.
        A line with fewer sub-units is shorter, since the spacing between them stays the same.
        """
        full = data["max_health"]
        size = SUBUNIT_COUNTS[shape]
        count, subunit = division_deployment(data, shape)
        facing = math.pi if side else 0.0
        division = len(self.divisions)
        # Spread target searches across ticks instead of running them all at once.
        stagger = round(RETARGET_SECONDS / FIXED_STEP)
        rng = self._rng
        flank = rng.choice((-1, 1))  # The whole division swings out to the same side.
        members = []
        metadata = queries.get_unit_metadata(data["type"], self.library)
        for number in range(count):
            slot = (number - (count - 1) / 2) * SUBUNIT_SPACING
            members.append(Fighter(
                dict(subunit), side,
                x, ARENA_SIZE[1] / 2 + slot, shape, division=division, attack_share=1 / size,
                angle=facing, aim=facing,
                index=len(self.fighters) + number,
                retarget=(len(self.fighters) + number) % stagger * FIXED_STEP, slot=slot,
                hold=rng.uniform(*AI_HOLD_RANGE), pace=rng.uniform(*AI_PACE),
                start_delay=rng.uniform(*AI_START_DELAY), wander=rng.uniform(0.0, AI_WANDER_ANGLE),
                wander_period=rng.uniform(*AI_WANDER_PERIOD), wander_phase=rng.uniform(0.0, math.tau),
                flank=flank,
                primary_weapon=(metadata.get("tactical_support") if number == 0 and count > 1
                                and metadata.get("tactical_support") else metadata.get("tactical_primary"))))
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
        Campaign survival is determined separately when the finished result is applied.
        """
        return self.controlled is not None and any(
            fighter.alive for fighter in self.divisions[self.controlled.division])

    def set_player_input(self, throttle=0.0, turn=0.0, fire=False, aim_point=None, secondary_fire=False, move_direction=None):
        """Receive held controls and the pointer in field coordinates.

        Movement, aiming, and firing still execute on fixed ticks. Without an aim point the gun holds its angle.
        A move direction replaces throttle and turn with a battlefield heading and proportional speed.
        """
        self._throttle = max(-1.0, min(1.0, throttle))
        self._turn = max(-1.0, min(1.0, turn))
        self._move_direction = None if move_direction is None else (float(move_direction[0]), float(move_direction[1]))
        self._fire = bool(fire)
        self._secondary_fire = bool(secondary_fire)
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
    def _heading_controls(fighter, throttle, heading):
        turning = _wrap(heading - fighter.angle)
        # Turn toward the heading before driving hard along it.
        throttle *= max(0.0, math.cos(turning))
        _seconds, degrees, seconds = MOBILITY[fighter.shape]
        # Ease off the turn before the hull lines up, since the turn rate cannot stop at once.
        turn = max(-1.0, min(1.0, turning / (math.radians(degrees) * seconds)))
        return throttle, turn

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
        """Use tactical wound scaling with shared target restrictions."""
        return sum(shot[1] for shot in combat_rules.damage_shots(
            [source], [target], health_floor=TACTICAL_DAMAGE_AT_ZERO_HEALTH))

    @classmethod
    def damage_amount(cls, source, target, attack_share, multiplier=1.0):
        """Tactical pacing follows full defense and division sharing for every attack kind.

        Round before pacing so even the smallest positive hits take longer than before.
        Wound scaling follows TACTICAL_DAMAGE_AT_ZERO_HEALTH for each surviving sub-unit.
        """
        loss = max(0.0, cls._attack(source, target) - target["defense"]) * attack_share
        return math.ceil(loss) * DAMAGE_SCALE * multiplier

    @classmethod
    def weapon_damage(cls, source, target, attack_share, weapon, target_shape, multiplier=1.0):
        # Machine guns cannot borrow a tank's anti-armor capability. The shared
        # target rules still apply to every weapon before tactical scaling.
        if not weapon_target_allowed(weapon, target_shape):
            return 0.0
        return cls.damage_amount(source, target, attack_share, weapon["damage"] * multiplier)

    @staticmethod
    def ranged_multiplier(distance):
        fraction = max(0.0, min(1.0, (distance - FALLOFF_START) / (WEAPON_RANGE - FALLOFF_START)))
        return 1.0 - fraction * (1.0 - MIN_RANGED_DAMAGE)

    def _firing_lane(self, fighter, target, start=None):
        start = (fighter.x, fighter.y) if start is None else start
        return self.battlefield.firing_blocker(start, (target.x, target.y)) is None

    @staticmethod
    def _lead_point(target, start, speed=PROJECTILE_SPEED):
        """Where ``target`` will be when a shot from ``start`` arrives, if it keeps moving the same way."""
        flight = math.dist(start, (target.x, target.y)) / speed
        return target.x + target.vx * flight, target.y + target.vy * flight

    def _ally_in_line(self, fighter, target, start=None, slot=0):
        """The nearest ally a shot from ``start`` at ``target`` could hit first, or None.

        The shot follows the gun's lead on ``target``. Each ally is checked where it will be when the
        shot passes, so allies walking into the line count. The danger zone widens with distance by
        the aim tolerance and shot spread, since AI shots can leave that far off the lead.
        """
        start = (fighter.x, fighter.y) if start is None else start
        weapon = fighter.weapon(slot)
        lead_x, lead_y = self._lead_point(target, start, weapon["speed"])
        dx, dy = lead_x - start[0], lead_y - start[1]
        distance = math.hypot(dx, dy)
        if not distance:
            return None
        ux, uy = dx / distance, dy / distance
        spread = math.tan(self._shot_spread(fighter, weapon) + AIM_TOLERANCE)
        best, best_along = None, WEAPON_RANGE if weapon["penetration"] > 0 else distance
        for ally in self._sides[fighter.side]:
            if ally is fighter:
                continue
            ox, oy = ally.x - start[0], ally.y - start[1]
            flight = max(0.0, ox * ux + oy * uy) / weapon["speed"]
            ox, oy = ox + ally.vx * flight, oy + ally.vy * flight
            along = ox * ux + oy * uy
            if 0 < along < best_along and abs(oy * ux - ox * uy) <= ally.radius + along * spread:
                # Cover beyond the target can safely stop a penetrating shell.
                end = start[0] + ux * along, start[1] + uy * along
                if self.battlefield.firing_blocker(start, end) is None:
                    best, best_along = ally, along
        return best

    def _clear_shot(self, fighter, target, start=None, slot=0):
        """A firing lane through terrain that keeps allies safe, including beyond a shell's target."""
        return (self._firing_lane(fighter, target, start)
                and self._ally_in_line(fighter, target, start, slot=slot) is None)

    def _ally_safe_throttle(self, fighter, throttle):
        """Brake ram-capable AI units before they hit allies fast enough to damage them."""
        if not throttle or not fighter.can_ram:
            return throttle
        direction = 1.0 if throttle > 0 else -1.0
        hx, hy = math.cos(fighter.angle) * direction, math.sin(fighter.angle) * direction
        acceleration = fighter.max_speed / MOBILITY[fighter.shape][0]
        limit = abs(throttle) * fighter.max_speed
        for ally in self._sides[fighter.side]:
            if ally is fighter:
                continue
            ox, oy = ally.x - fighter.x, ally.y - fighter.y
            along = ox * hx + oy * hy
            clearance = fighter.radius + ally.radius
            if along <= 0 or abs(oy * hx - ox * hy) > clearance:
                continue
            # Brake in time to arrive no faster than ALLY_BUMP_SPEED; the ally's own motion opens or closes the gap.
            gap = max(0.0, along - clearance)
            allowed = math.sqrt(ALLY_BUMP_SPEED ** 2 + 2 * acceleration * gap)
            limit = min(limit, ally.vx * hx + ally.vy * hy + allowed)
        return direction * max(0.0, limit) / fighter.max_speed

    @staticmethod
    def _queue_shot(fighter, shots, slot=0):
        weapon = fighter.weapon(slot)
        shots.append((fighter, slot))
        rounds = (fighter.secondary_rounds if slot else fighter.primary_rounds) + 1
        wait = weapon["reload"] if rounds >= weapon["rounds"] else weapon["interval"]
        rounds %= weapon["rounds"]
        if slot:
            fighter.secondary_rounds, fighter.secondary_cooldown, fighter.secondary_wait = rounds, wait, wait
        else:
            fighter.primary_rounds, fighter.cooldown, fighter.primary_wait = rounds, wait, wait

    def _drive_player(self, fighter, dt, shots):
        throttle, turn = self._throttle, self._turn
        if self._move_direction is not None:
            dx, dy = self._move_direction
            strength = min(1.0, math.hypot(dx, dy))
            throttle, turn = self._heading_controls(fighter, strength, math.atan2(dy, dx)) if strength else (0.0, 0.0)
        self._steer(fighter, turn, dt)
        self._accelerate(fighter, throttle, dt)
        aim = self._aim_point
        self._slew_aim(fighter, fighter.aim if aim is None else math.atan2(aim[1] - fighter.y, aim[0] - fighter.x), dt)
        if self._fire and fighter.cooldown <= 0:
            self._queue_shot(fighter, shots)
        if self._secondary_fire and fighter.weapon(1) is not None and fighter.secondary_cooldown <= 0:
            self._queue_shot(fighter, shots, 1)

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
        """Cache full attack per type pair, then account for the shooter's current wounds."""
        key = (shooter.data["type"], target.data["type"])
        if key not in self._full_attacks:
            full = dict(shooter.data, health=shooter.data["max_health"])
            self._full_attacks[key] = self._attack(full, target.data)
        multiplier = combat_rules.health_damage_multiplier(shooter.data, health_floor=TACTICAL_DAMAGE_AT_ZERO_HEALTH)
        return self._full_attacks[key] * multiplier > target.data["defense"]

    def _weapon_can_hurt(self, fighter, target, slot=0):
        weapon = fighter.weapon(slot)
        return weapon_target_allowed(weapon, target.shape) and self._can_hurt(fighter, target)

    def _choose_target(self, fighter, enemies, slot=0):
        """The enemy to shoot: the nearest, unless one close to it is wounded and this sub-unit can hurt it.

        A wounded enemy counts as nearer, and enemies this sub-unit cannot damage are passed over.
        Enemies behind terrain or allies come after those with a clear shot.
        """
        nearest = enemies.nearest(fighter.x, fighter.y)
        best, best_score = None, math.inf
        for enemy in enemies.around(nearest.x, nearest.y, TARGET_CHOICE_SLACK):
            if not self._weapon_can_hurt(fighter, enemy, slot):
                continue
            wounds = 1.0 - enemy.data["health"] / enemy.data["max_health"]
            score = math.hypot(enemy.x - fighter.x, enemy.y - fighter.y) * (1.0 - TARGET_WOUNDED_PULL * wounds)
            if fighter.weapon(slot)["shell"] and enemy.shape not in SOFT_TARGET_SHAPES:
                score *= CANNON_ARMOR_PRIORITY
            if not self._clear_shot(fighter, enemy, slot=slot):
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
            fighter.ram_committed = False
            if not self._firing_lane(fighter, fighter.target or objective):
                return 0.0, toward
            if fighter.shape not in FOOT_SHAPES:
                return (-fighter.pace, toward) if distance < WITHDRAW_RANGE else (0.0, toward)
            return (fighter.pace, away) if distance < WITHDRAW_RANGE else (0.0, toward)
        if fighter.ram_committed and (distance <= RAM_COMMIT_RANGE or fighter.dodge <= 0):
            point = self._ram_point(fighter, fighter.target)
            if point is not None:
                return fighter.pace, math.atan2(point[1] - fighter.y, point[0] - fighter.x)
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
                    max(fighter.radius, min(ARENA_SIZE[0] - fighter.radius,
                                        objective.x - forward * ENGAGEMENT_RANGE * hold)),
                    max(fighter.radius, min(ARENA_SIZE[1] - fighter.radius,
                                        objective.y + fighter.slot + fighter.lane + fighter.flank * FLANK_OFFSET)))
            goal_x, goal_y = fighter.flank_goal
            if math.hypot(goal_x - fighter.x, goal_y - fighter.y) <= FLANK_ARRIVAL_DISTANCE:
                fighter.flank_complete = True
                return 0.0, toward
        goal_y = max(fighter.radius, min(ARENA_SIZE[1] - fighter.radius, goal_y))
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
            if (self.battlefield.walkable(point, fighter.radius) and self._clear_shot(fighter, target, point)
                    and self.battlefield.route(start, point, fighter.radius)):
                return point
        return target.x, target.y

    def _cover_position(self, fighter, target):
        start = fighter.x, fighter.y
        candidates = []
        for index in range(FIRING_POSITION_ANGLES):
            angle = math.tau * index / FIRING_POSITION_ANGLES
            point = (fighter.x + math.cos(angle) * FIRING_POSITION_STEP,
                     fighter.y + math.sin(angle) * FIRING_POSITION_STEP)
            if (self.battlefield.walkable(point, fighter.radius)
                    and not self._firing_lane(fighter, target, point)):
                candidates.append(point)
        candidates.sort(key=lambda point: math.dist(start, point)
                        - math.dist(point, (target.x, target.y)) * COVER_DISTANCE_WEIGHT)
        return next((point for point in candidates if self.battlefield.route(start, point, fighter.radius)), None)

    def _terrain_course(self, fighter, throttle, heading, center, objective):
        """Route the existing behavior around terrain without changing its controller or side."""
        target = fighter.target
        start = fighter.x, fighter.y
        if fighter.ram_committed and (fighter.dodge <= 0 or math.dist(start, (target.x, target.y)) <= RAM_COMMIT_RANGE):
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
            elif (not flanking and fighter.dodge <= 0 and not fighter.ram_committed
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
            fighter.route = self.battlefield.route(start, goal, fighter.radius)
            if flanking and fighter.route:
                # A formation destination can fall inside an obstacle. Complete
                # the flank at its reachable replacement, then seek a clear shot.
                fighter.flank_goal = fighter.route[-1]
        while fighter.route and math.dist(start, fighter.route[0]) <= WAYPOINT_REACH:
            fighter.route.pop(0)
        while len(fighter.route) > 1 and self.battlefield.clear_path(start, fighter.route[1], fighter.radius):
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
            if not fighter.ram_committed:
                fighter.target = None
            fighter.secondary_target = None
        if fighter.target is None or not fighter.target.alive:
            fighter.target = self._choose_target(fighter, enemies)
        if fighter.weapon(1) is not None and (fighter.secondary_target is None or not fighter.secondary_target.alive):
            fighter.secondary_target = self._choose_target(fighter, enemies, 1)
        fighter.dodge = max(0.0, fighter.dodge - dt)
        target = fighter.target
        dx, dy = target.x - fighter.x, target.y - fighter.y
        distance = math.hypot(dx, dy)
        if fighter.dodge <= 0 and not fighter.ram_committed:
            for slot, gun_target in enumerate((target, fighter.secondary_target)):
                if (gun_target is None or fighter.weapon(slot) is None or fighter.weapon_cooldown(slot) > 0
                        or not self._weapon_can_hurt(fighter, gun_target, slot)
                        or math.dist((fighter.x, fighter.y), (gun_target.x, gun_target.y)) > WEAPON_RANGE
                        or not self._firing_lane(fighter, gun_target)):
                    continue
                ally = self._ally_in_line(fighter, gun_target, slot=slot)
                if ally is not None:
                    # Step out from behind the ally, away from its side of the firing line.
                    self._sidestep(fighter, ally.x, ally.y, gun_target.x - fighter.x,
                                   gun_target.y - fighter.y, LINE_SHIFT_SECONDS)
                    fighter.navigate_at = 0.0
                    break
        throttle, heading = self._ai_course(fighter, distance, math.atan2(dy, dx), center, objective)
        if self.battlefield.features:
            throttle, heading = self._terrain_course(fighter, throttle, heading, center, objective)
        throttle, turn = self._heading_controls(fighter, throttle, heading)
        throttle = self._ally_safe_throttle(fighter, throttle)
        self._steer(fighter, turn, dt)
        self._accelerate(fighter, throttle, dt)
        aim_slot = 0
        if (fighter.cooldown > 0 and fighter.secondary_target is not None
                and self._weapon_can_hurt(fighter, fighter.secondary_target, 1)):
            aim_slot = 1
        aim_target = fighter.secondary_target if aim_slot else target
        lead_x, lead_y = self._lead_point(aim_target, (fighter.x, fighter.y), fighter.weapon(aim_slot)["speed"])
        desired = math.atan2(lead_y - fighter.y, lead_x - fighter.x)
        self._slew_aim(fighter, desired, dt)
        for slot, gun_target in enumerate((target, fighter.secondary_target)):
            if gun_target is None or fighter.weapon(slot) is None:
                continue
            lead_x, lead_y = self._lead_point(gun_target, (fighter.x, fighter.y), fighter.weapon(slot)["speed"])
            desired = math.atan2(lead_y - fighter.y, lead_x - fighter.x)
            if (fighter.weapon_cooldown(slot) <= 0 and math.dist((fighter.x, fighter.y), (gun_target.x, gun_target.y)) <= WEAPON_RANGE
                    and abs(_wrap(desired - fighter.aim)) <= AIM_TOLERANCE
                    and self._weapon_can_hurt(fighter, gun_target, slot)
                    and self._clear_shot(fighter, gun_target, slot=slot)):
                self._queue_shot(fighter, shots, slot)

    @staticmethod
    def _shot_spread(fighter, weapon):
        movement = abs(fighter.speed) / fighter.max_speed if fighter.max_speed else 0.0
        turning = abs(fighter.turn_rate) / math.radians(MOBILITY[fighter.shape][1])
        spread = weapon["spread"] + c.TACTICAL_MOVING_SPREAD * movement + c.TACTICAL_TURNING_SPREAD * turning
        return math.radians(spread * (c.TACTICAL_SHELL_SPREAD_MULTIPLIER if weapon["shell"] else 1.0))

    def _fire_shot(self, fighter, slot=0):
        # The shot leaves slightly off the aim, so the same error misses more often at long range.
        weapon = fighter.weapon(slot)
        spread = self._shot_spread(fighter, weapon)
        angle = fighter.aim + self._rng.uniform(-spread, spread)
        speed = weapon["speed"]
        start = fighter.x, fighter.y
        target = fighter.secondary_target if slot else fighter.target
        point = self._aim_point if fighter is self.controlled else (
            (target.x, target.y) if target is not None else None)
        height = self.battlefield.elevation(start) + battle_terrain.WEAPON_HEIGHT
        vertical_speed = 0.0
        if point is not None and math.dist(start, point) > 0:
            vertical_speed = ((self.battlefield.elevation(point) + battle_terrain.WEAPON_HEIGHT - height)
                              * speed / math.dist(start, point))
        self.projectiles.append(Projectile(
            fighter, dict(fighter.data), fighter.x, fighter.y, math.cos(angle) * speed,
            math.sin(angle) * speed, WEAPON_RANGE / speed,
            height=height, vertical_speed=vertical_speed, weapon_data=dict(weapon)))
        fighter.fired_weapon = slot
        fighter.muzzle = c.TACTICAL_MUZZLE_SECONDS
        if weapon["shell"]:
            fighter.recoil = c.TACTICAL_MUZZLE_SECONDS
        if self.on_shot is not None:
            self.on_shot(fighter)

    def _can_dodge(self, unit):
        """Only fast AI sub-units sidestep; for slower ones the time spent turning away costs more aim than it saves."""
        return unit is not self.controlled and unit.data["speed"] >= DODGE_MIN_SPEED

    def _sidestep(self, unit, x, y, vx, vy, seconds):
        """Sidestep at right angles to a path through (x, y) along (vx, vy), away from it (a random side when dead on)."""
        # How far the unit sits to the left of the path; negative is to the right.
        offset = ((unit.y - y) * vx - (unit.x - x) * vy) / math.hypot(vx, vy)
        side = (1 if offset > 0 else -1) if abs(offset) > 1e-9 else self._rng.choice((-1, 1))
        unit.dodge = seconds
        unit.dodge_heading = math.atan2(vy, vx) + side * math.pi / 2

    def _start_dodge(self, unit, shot):
        """Sidestep at right angles to a shot's path, away from it."""
        self._sidestep(unit, shot.x, shot.y, shot.vx, shot.vy, DODGE_SECONDS)

    def _ready_to_fire(self, unit):
        """Whether an AI sub-unit is about to shoot: loaded, with a clear shot at its target in range.

        It then holds rather than dodging.
        """
        return any(unit.weapon(slot) is not None and unit.weapon_cooldown(slot) <= 0
                   and target is not None and target.alive and self._weapon_can_hurt(unit, target, slot)
                   and math.hypot(target.x - unit.x, target.y - unit.y) <= WEAPON_RANGE
                   and self._clear_shot(unit, target, slot=slot)
                   for slot, target in enumerate((unit.target, unit.secondary_target)))

    def _dodge_incoming(self, crowds):
        """AI sub-units that are not about to fire sidestep other sub-units' shots whose paths will pass close to them.

        Shots hurt allies too, so an ally's shot is dodged like an enemy's.
        """
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
            danger = DODGE_DANGER * MAX_UNIT_RADIUS / UNIT_RADIUS
            nearby = (unit for crowd in crowds for unit in crowd.within(
                min(shot.x, end_x) - danger, min(shot.y, end_y) - danger,
                max(shot.x, end_x) + danger, max(shot.y, end_y) + danger))
            for unit in nearby:
                if (unit is shot.source or not self._can_dodge(unit) or unit.dodge > 0 or self._ready_to_fire(unit)
                        or (unit.ram_committed and unit.target is not None
                            and math.hypot(unit.x - unit.target.x, unit.y - unit.target.y) <= RAM_COMMIT_RANGE)):
                    continue
                along = ((unit.x - shot.x) * shot.vx + (unit.y - shot.y) * shot.vy) / speed
                across = ((unit.y - shot.y) * shot.vx - (unit.x - shot.x) * shot.vy) / speed
                if 0 <= along <= reach and abs(across) <= DODGE_DANGER * unit.radius / UNIT_RADIUS:
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
        if target is None or not unit.can_ram:
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
        runup = max(0.0, math.dist((unit.x, unit.y), point) - unit.radius - target.radius)
        acceleration = unit.max_speed / MOBILITY[unit.shape][0]
        impact_speed = min(speed, math.sqrt(max(0.0, unit.speed) ** 2 + 2 * acceleration * runup))
        distance = math.dist((unit.x, unit.y), point)
        closing = impact_speed - ((target.vx * (point[0] - unit.x) + target.vy * (point[1] - unit.y)) / distance
                                  if distance else 0.0)
        if (impact_speed < RAM_MIN_SPEED or closing < RAM_MIN_SPEED
                or not self.battlefield.clear_path((unit.x, unit.y), point, unit.radius)):
            return None
        if any(other is not unit and other is not target and other.alive
               and battle_terrain.circle_contact((unit.x, unit.y), point, (other.x, other.y),
                                                  unit.radius + other.radius) is not None
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
                and (committed or (distance > RAM_COMMIT_RANGE
                     and (all(not self._weapon_can_hurt(target, unit, slot)
                              or target.weapon_cooldown(slot) > target.weapon(slot)["interval"] / 2
                              for slot in (0, 1))
                          or target.data["health"] <= target.data["max_health"] * RAM_WOUNDED_TARGET)))
                and self._ram_point(unit, target) is not None)

    def _prepare_rams(self, sides, crowds):
        """Choose safe ram approaches for eligible AI units on either side."""
        for side, units in enumerate(sides):
            for unit in units:
                if unit is self.controlled:
                    continue
                if not unit.can_ram:
                    unit.ram_committed = False
                    continue
                nearby = [enemy for enemy in crowds[1 - side].around(unit.x, unit.y, RAM_APPROACH_RANGE)
                          if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= RAM_APPROACH_RANGE]
                if not nearby:
                    unit.ram_committed = False
                    continue
                friends = [friend for friend in crowds[side].around(unit.x, unit.y, RAM_SUPPORT_RANGE)
                           if math.hypot(friend.x - unit.x, friend.y - unit.y) <= RAM_SUPPORT_RANGE
                           and self.battlefield.clear_path((unit.x, unit.y), (friend.x, friend.y), unit.radius)]
                threats = sum(1 for enemy in crowds[1 - side].around(unit.x, unit.y, WEAPON_RANGE)
                              if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= WEAPON_RANGE
                              and any(self._weapon_can_hurt(enemy, unit, slot)
                                      and self._firing_lane(enemy, unit)
                                      for slot in (0, 1)))
                candidates = sorted(nearby, key=lambda enemy: (
                    not (unit.ram_committed and enemy is unit.target),
                    math.hypot(enemy.x - unit.x, enemy.y - unit.y)))
                opportunity = next((enemy for enemy in candidates
                                    if self._ram_opportunity(unit, enemy, len(friends), threats)), None)
                unit.ram_committed = opportunity is not None
                if opportunity is not None:
                    unit.target = opportunity

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
        Contact between allies moves the bodies the same way but deals no ram damage.
        """
        positions = {unit.index: list(self.battlefield.move((unit.x, unit.y), (unit.x + mx, unit.y + my), unit.radius))
                     for unit, mx, my in movements}
        velocities = {unit.index: ((positions[unit.index][0] - unit.x) / dt,
                                   (positions[unit.index][1] - unit.y) / dt) for unit, _, _ in movements}
        max_move = max((math.hypot(mx, my) for _, mx, my in movements), default=0.0)
        retained = set()
        for pair in self._contacts:
            first, second = (self.fighters[index] for index in pair)
            if (first.alive and second.alive and math.hypot(first.x - second.x, first.y - second.y)
                    <= first.radius + second.radius + CONTACT_RELEASE_DISTANCE - UNIT_RADIUS * 2):
                retained.add(pair)
        damage = []
        for unit in living:
            vx, vy = velocities[unit.index]
            reach = math.hypot(vx, vy) * dt + max_move + unit.radius + MAX_UNIT_RADIUS
            for crowd in crowds:
                for other in crowd.around(unit.x, unit.y, reach):
                    if other.index <= unit.index:
                        continue
                    diameter = unit.radius + other.radius
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
                    if pair not in retained and closing >= RAM_MIN_SPEED:
                        for source, target, speed, mass, target_mass in (
                                (unit, other, vx * nx + vy * ny, first_mass, second_mass),
                                (other, unit, -ovx * nx - ovy * ny, second_mass, first_mass)):
                            # Rams only hurt enemies; allies still collide and separate.
                            if not source.can_ram or speed < RAM_MIN_SPEED or source.side == target.side:
                                continue
                            strength = min(RAM_MAX_STRENGTH, closing / RAM_REFERENCE_SPEED) * min(1.0, mass / target_mass)
                            damage.append((target, self.damage_amount(source.data, target.data, source.attack_share,
                                                                      RAM_DAMAGE * strength), source))
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
            x, y = self.battlefield.move((unit.x, unit.y), (x, y), unit.radius)
            unit.vx, unit.vy = (x - unit.x) / dt, (y - unit.y) / dt
            unit.x, unit.y = x, y
        return damage

    def _step(self, dt):
        if int(self.elapsed / RETARGET_SECONDS) != int((self.elapsed + dt) / RETARGET_SECONDS):
            self.battlefield.begin_decision_interval()
        self.elapsed += dt
        self.impacts = [(x, y, remaining - dt, shell) for x, y, remaining, shell in self.impacts if remaining > dt]
        living = [fighter for fighter in self.fighters if fighter.alive]
        sides = [[fighter for fighter in living if fighter.side == side] for side in (0, 1)]
        crowds = [_Grid(side, GRID_CELL) for side in sides]
        targets = [_Grid(side, TARGET_CELL) for side in sides]
        self._healthy_sides = [any(unit.data["health"] >= unit.data["max_health"] * FALL_BACK_HEALTH
                                  for unit in side) for side in sides]
        self._sides = sides
        objectives = self._division_objectives(targets, dt)
        self._prepare_rams(sides, crowds)
        self._dodge_incoming(crowds)
        # All movement and fire decisions use the same pre-step positions.
        movements = []
        shots = []
        for fighter in living:
            if not sides[1 - fighter.side]:
                movements.append((fighter, 0.0, 0.0))
                continue
            fighter.cooldown = max(0.0, fighter.cooldown - dt)
            fighter.secondary_cooldown = max(0.0, fighter.secondary_cooldown - dt)
            fighter.muzzle = max(0.0, fighter.muzzle - dt)
            fighter.recoil = max(0.0, fighter.recoil - dt)
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
        for fighter, slot in shots:
            self._fire_shot(fighter, slot)
        close_hits = [(target, loss, source, "ram")
                      for target, loss, source in self._resolve_contacts(living, crowds, movements, dt)]

        # Accumulate impacts first so units destroyed together can both land their shots.
        # A shot can hit any sub-unit but its shooter, so allies in its path take friendly fire.
        hittable = _Grid(living, GRID_CELL)
        remaining = []
        for shot in self.projectiles:
            flight = min(dt, shot.remaining)
            if flight <= 0:
                continue
            nx, ny = shot.x + shot.vx * flight, shot.y + shot.vy * flight
            next_height = shot.height + shot.vertical_speed * flight
            traveled = math.hypot(shot.vx, shot.vy) * flight
            terrain_hit = self.battlefield.first_hit((shot.x, shot.y), (nx, ny), shot.height, next_height)
            collisions = []
            for target in hittable.within(min(shot.x, nx) - MAX_UNIT_RADIUS, min(shot.y, ny) - MAX_UNIT_RADIUS,
                                          max(shot.x, nx) + MAX_UNIT_RADIUS, max(shot.y, ny) + MAX_UNIT_RADIUS):
                if target is shot.source or target.index in shot.hit_units:
                    continue
                fraction = self._collision_fraction(shot.x, shot.y, nx, ny, target)
                ground = self.battlefield.elevation((target.x, target.y))
                impact_height = shot.height + (next_height - shot.height) * (fraction or 0.0)
                if fraction is not None and ground <= impact_height <= ground + battle_terrain.BODY_HEIGHT:
                    collisions.append((fraction, target))
            stopped = False
            for fraction, target in sorted(collisions, key=lambda item: (item[0], item[1].index)):
                if terrain_hit is not None and terrain_hit[0] <= fraction:
                    break
                distance = shot.distance + traveled * fraction
                # Use the unit actually hit, including its target capability rules.
                # Full tactical defense still decides whether a hit can hurt.
                # Divide damage among the division's full sub-unit count before
                # applying weapon pacing, range falloff, and penetration losses.
                loss = self.weapon_damage(shot.source_data, target.data, shot.source.attack_share,
                                          shot.weapon_data, target.shape,
                                          shot.power * self.ranged_multiplier(distance))
                close_hits.append((target, loss, shot.source, "shot"))
                shot.hit_units.add(target.index)
                self.impacts.append((shot.x + (nx - shot.x) * fraction,
                                     shot.y + (ny - shot.y) * fraction,
                                     c.TACTICAL_IMPACT_SECONDS, shot.weapon_data["shell"]))
                if loss > 0 and self._can_dodge(target):
                    self._start_dodge(target, shot)
                resistance = c.TACTICAL_BODIES[target.shape][3]
                if shot.penetration <= resistance:
                    stopped = True
                    break
                shot.penetration -= resistance
                shot.power *= c.TACTICAL_PENETRATION_DAMAGE_RETAINED
            if stopped:
                continue
            if terrain_hit is not None:
                fraction = terrain_hit[0]
                self.impacts.append((shot.x + (nx - shot.x) * fraction,
                                     shot.y + (ny - shot.y) * fraction,
                                     c.TACTICAL_IMPACT_SECONDS, shot.weapon_data["shell"]))
            else:
                shot.x, shot.y = nx, ny
                shot.height = next_height
                shot.distance += traveled
                shot.remaining -= flight
                if shot.remaining > 0:
                    remaining.append(shot)
        self.projectiles = remaining
        for target, loss, source, cause in close_hits:
            previous_health = target.data["health"]
            target.data["health"] = max(0.0, previous_health - loss)
            if cause == "shot" and self.on_hit is not None:
                self.on_hit(target, previous_health - target.data["health"])
            if previous_health > 0 and not target.alive and self.on_kill is not None:
                self.on_kill(source, target, cause)
        alive_sides = {fighter.side for fighter in self.fighters if fighter.alive}
        if len(alive_sides) < 2:
            # Mutual destruction is a loss for the friendly army; there is no draw screen.
            self.winner = 0 if 0 in alive_sides else 1

    @staticmethod
    def _collision_fraction(x, y, nx, ny, target, radius=None):
        """First swept contact prevents fast shells and bodies from skipping their targets."""
        return battle_terrain.circle_contact((x, y), (nx, ny), (target.x, target.y),
                                              target.radius if radius is None else radius)
