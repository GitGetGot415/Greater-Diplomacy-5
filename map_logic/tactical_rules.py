"""Tactical battle tuning, unit shapes, eligibility, and the geometry the simulation shares."""

from dataclasses import dataclass
import math

import data.constants as c
from data import queries
from map_logic import naval_battle as naval
from map_logic.system32 import combat_rules

# These values translate campaign statistics into a real-time battlefield.
# They do not change campaign combat or add persistent unit statistics.
FIXED_STEP = 1.0 / 30.0 # 33 milliseconds per step, or 30 simulation steps per second


MOVE_PIXELS_PER_SPEED = 60.0


FIRE_INTERVAL = c.TACTICAL_WEAPONS["rifle"]["reload"]


DAMAGE_SCALE = 1.0  # Applied after defense and rounding, so low-damage hits also slow down.


# Attack at zero HP: 0.0 = directly proportional to HP; 1.0 = wounds do not reduce attack.
# Values between 0 and 1 interpolate linearly. Applies to each surviving sub-unit.
TACTICAL_DAMAGE_AT_ZERO_HEALTH = 1.0


WEAPON_RANGE = 800.0


PROJECTILE_SPEED = c.TACTICAL_WEAPONS["rifle"]["speed"]


ENGAGEMENT_RANGE = 300.0  # Preferred distances do not grow with maximum projectile reach.


WITHDRAW_RANGE = 500.0


FALLOFF_START = 400.0


MIN_RANGED_DAMAGE = 0.45


UNIT_RADIUS = c.TACTICAL_BODIES["infantry"][2]


MAX_UNIT_RADIUS = max(body[2] for shape, body in c.TACTICAL_BODIES.items() if shape not in naval.SHAPES)


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


# Each division deploys as one vertical line of its sub-units. Each column (rank) holds one division,
# centered, or two divisions, one above the other. Roster order runs front to back, then top to
# bottom within a column: the first column stands closest to the enemy.
RANK_GAP = 56.0  # Between ranks, front to back; leaves room for the largest hull.


SUBUNIT_SPACING = 60.0  # Between neighboring sub-units along a division's line.


# Distance between the two armies' front ranks at deployment, centered on the battlefield.
SPAWN_FRONT_GAP = 2000.0


SPAWN_MARGIN = 100.0  # Between the battlefield edge and the last rank of the largest army.


# The battlefield is twice as wide as it is tall, with room for two full armies behind their front ranks.
ARENA_WIDTH = SPAWN_FRONT_GAP + 2 * (SPAWN_MARGIN + (c.CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE - 1) * RANK_GAP)


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


# An AI ship steers PASS_ALLY_ANGLE off its course to pass a slower allied hull it would reach within
# PASS_ALLY_SECONDS at top speed, rather than queuing behind it.
PASS_ALLY_SECONDS = 1.5


PASS_ALLY_ANGLE = math.radians(30)


TANK_SHAPES = frozenset(("tank", "light_tank", "heavy_tank"))


NAVIGATION_SECONDS = 0.8


WAYPOINT_REACH = 25.0


FIRING_POSITION_ANGLES = 12


FIRING_POSITION_RINGS = (1.0, 0.6, 0.3)


FIRING_POSITION_STEP = 200.0


# Side-steps across the line of fire, as shares of FIRING_POSITION_STEP: a shot blocked close by often needs only a short move.
FIRING_POSITION_SIDESTEPS = (0.2, 0.4, 0.6, 0.8)


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


SUBUNIT_COUNTS.update({shape: 1 for shape in naval.SHAPES})


MOBILITY.update({shape: naval.MOBILITY for shape in naval.SHAPES})


AIM.update({shape: (None, naval.AIM_SPEED) for shape in naval.SHAPES})


CONTACT_MASS.update(naval.CONTACT_MASS)


def stack_offset():
    """How far above and below the battlefield's middle two divisions sharing a column stand.

    The two longest lines keep one sub-unit spacing between them.
    """
    return max(SUBUNIT_COUNTS.values()) * SUBUNIT_SPACING / 2


def deployment_half_height():
    """Half the height of a column holding two of the longest lines; trees stay out of this band."""
    return stack_offset() + (max(SUBUNIT_COUNTS.values()) - 1) * SUBUNIT_SPACING / 2


def valid_starting_health(health, max_health):
    """A participating unit must start alive and within its library health limit."""
    return (isinstance(health, (int, float)) and not isinstance(health, bool)
            and 0 < health <= max_health)


def is_artillery(name, library):
    """Artillery-type units (everything that can bombard) take no part in tactical battles."""
    return queries.get_bombardment_range(name, library.get(name)) > 0


def is_land_stats(stats):
    return not stats.get("naval_unit") and not stats.get("air_role")


def land_unit_types(library):
    """Units that can fight tactical battles: library identifiers, including levels, of land units.

    Ships, aircraft, and artillery-type units are excluded.
    """
    return [name for name, stats in library.items() if is_land_stats(stats) and not is_artillery(name, library)]


def packed_ship_type(name, library):
    """Return the carried ship's identifier for a current naval Truck, otherwise None."""
    if isinstance(name, str) and name.startswith("Truck (") and name.endswith(")"):
        ship = name[len("Truck ("):-1]
        if library.get(ship, {}).get("naval_unit"):
            return ship
    return None


def campaign_unit_eligible(name, library):
    """Land fighters and packed ships can deploy; unpacked warships cannot."""
    return bool(packed_ship_type(name, library) or (
        name in library and is_land_stats(library[name]) and not is_artillery(name, library)))


def naval_campaign_unit_eligible(name, library):
    """Warships and convoys carrying a deployable land unit fight naval tactical battles at sea."""
    if isinstance(name, str) and name.startswith("Convoy (") and name.endswith(")"):
        return campaign_unit_eligible(name[len("Convoy ("):-1], library)
    return bool(library.get(name, {}).get("naval_unit"))


def tactical_unit_eligible(name, library):
    """Divisions a tactical player may command: land fighters, packed ships, and warships."""
    return campaign_unit_eligible(name, library) or bool(library.get(name, {}).get("naval_unit"))


def custom_unit_types(library):
    """Selectable units; terrain determines their fighting or transport form."""
    return [name for name, stats in library.items()
            if stats.get("naval_unit") or campaign_unit_eligible(name, library)]


def battle_unit_type(name, library):
    """The library identity under a current tactical transport wrapper."""
    for carrier in ("Truck", "Convoy"):
        if name.startswith(carrier + " (") and name.endswith(")") and name[len(carrier) + 2:-1] in library:
            return name[len(carrier) + 2:-1]
    return name


def create_battle_unit(name, owner, library, terrain=None):
    """Build the terrain's current form through the shared transport rules."""
    name = battle_unit_type(name, library)
    unit = queries.create_unit_dict(name, owner, library)
    water = terrain in c.WATER_TERRAINS
    if water and not library[name].get("naval_unit"):
        queries.load_transport(unit, "Convoy")
    elif not water and library[name].get("naval_unit"):
        queries.load_transport(unit, "Truck")
    return unit


def prepare_battle_unit(entry, library, terrain):
    """Prepare a copy, preserving identity, settings, and the current HP fraction."""
    name = entry["type"]
    base = battle_unit_type(name, library)
    expected = base if bool(library[base].get("naval_unit")) == (terrain in c.WATER_TERRAINS) else f"{'Convoy' if terrain in c.WATER_TERRAINS else 'Truck'} ({base})"
    if name == expected:
        return dict(entry)
    unit = create_battle_unit(base, entry["owner"], library, terrain)
    unit["health"] = entry["health"] / entry["max_health"] * unit["max_health"]
    if "unit_id" in entry:
        unit["unit_id"] = entry["unit_id"]
    return unit


def unit_shape(name, library):
    """Choose prototype geometry from existing family and capability metadata."""
    if name.startswith("Convoy (") and battle_unit_type(name, library) != name:
        return "convoy"
    if packed_ship_type(name, library):
        return "motorized"
    if library.get(name, {}).get("naval_unit"):
        return naval.FAMILY_SHAPES.get(queries.get_unit_metadata(name, library)["family"], "destroyer")
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


def wrap_angle(angle):
    """The same angle between -pi and pi."""
    return (angle + math.pi) % math.tau - math.pi


def step_toward(value, goal, step):
    return min(goal, value + step) if value < goal else max(goal, value - step)


def time_to_shift(distance, speed_change, acceleration):
    """Seconds a unit needs to end up ``distance`` from where its steady motion would take it.

    It accelerates at ``acceleration`` until its speed has changed by ``speed_change``, then holds
    that speed. A unit that cannot change speed never shifts.
    """
    if distance <= 0:
        return 0.0
    if speed_change <= 0 or acceleration <= 0:
        return math.inf
    ramp = speed_change * speed_change / (2 * acceleration)
    if distance <= ramp:
        return math.sqrt(2 * distance / acceleration)
    return speed_change / acceleration + (distance - ramp) / speed_change


def falling_window(shot, hit_height):
    """Seconds from now until a falling shell drops through ``hit_height``, and until it lands.

    Only that end of its flight can hit a body; before it, the shell passes overhead.
    """
    land = shot.remaining
    return max(0.0, min(land, naval.descending_time(shot.height, shot.vertical_speed, shot.gravity, hit_height))), land


@dataclass(frozen=True)
class DomainConfig:
    """Arena and contact thresholds shared across land and naval tactical battles."""
    naval: bool
    arena_size: tuple
    front_gap: float
    rank_gap: float
    lane_gap: float
    ram_approach_range: float
    ram_support_range: float


LAND_DOMAIN = DomainConfig(
    False, ARENA_SIZE, SPAWN_FRONT_GAP, RANK_GAP, APPROACH_LANE_GAP,
    RAM_APPROACH_RANGE, RAM_SUPPORT_RANGE)
NAVAL_DOMAIN = DomainConfig(
    True, naval.ARENA_SIZE, naval.FRONT_GAP, naval.RANK_GAP, naval.LANE_GAP,
    naval.RAM_APPROACH_RANGE, naval.RAM_SUPPORT_RANGE)


def domain_config(is_naval):
    """Return the tactical domain configuration for land or naval terrain."""
    return NAVAL_DOMAIN if is_naval else LAND_DOMAIN
