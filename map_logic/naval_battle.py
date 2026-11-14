"""Naval tactical profiles, firing mounts, and hull geometry shared by combat and UI."""

import math
from dataclasses import dataclass

import data.constants as c


RANK_GAP = 260.0
FRONT_GAP = 4200.0
SPAWN_MARGIN = 200.0
ARENA_WIDTH = FRONT_GAP + 2 * (SPAWN_MARGIN + (c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE - 1) * RANK_GAP)
ARENA_SIZE = (ARENA_WIDTH, ARENA_WIDTH / 2)
ENGAGEMENT_RANGE = 1800.0
WITHDRAW_RANGE = 2300.0
LANE_GAP = 240.0
FALLOFF_START = 1400.0
MOBILITY = (4.0, 35.0, 0.6)
AIM_SPEED = 60.0
RAM_APPROACH_RANGE = 600.0
RAM_SUPPORT_RANGE = 500.0
RAM_MIN_UNIT_SPEED = 1.0
TORPEDO_RADIUS = 3.0
TORPEDO_LOOKAHEAD = 8.0  # Ships need time to turn and accelerate before an approaching torpedo arrives.
TORPEDO_LAUNCH_LOOKAHEAD = 3.0
TORPEDO_LAUNCH_CLEARANCE = 12.0
EVASION_CLEARANCE = 12.0
EVASION_SAMPLE_SECONDS = 0.2  # Motion still uses fixed ticks; hull checks cover each sampled interval.
EVASION_TURN_ANGLES = tuple(math.radians(angle) for angle in (-90, -45, 45, 90))
HULL_SWEEP_ERROR = 1.0  # Maximum extra corner clearance from approximating a rotating hull.
MUZZLE_CLEARANCE = 5.0
MAX_LEAD_PASSES = 5

# Shapes select artwork and firing arrangements independently of library statistics.
FAMILY_SHAPES = {
    "Carrack": "carrack", "Ironclad": "ironclad", "Destroyer": "destroyer",
    "Pre-Dreadnought": "pre_dreadnought", "Dreadnought": "dreadnought",
    "Battleship": "battleship", "Aircraft Carrier": "aircraft_carrier", "Submarine": "submarine",
}
ARTWORK = {shape: (family, family if shape in {"destroyer", "pre_dreadnought", "dreadnought", "battleship"} else "Destroyer" if shape == "aircraft_carrier" else None) for family, shape in FAMILY_SHAPES.items()}
ARTWORK["convoy"] = ("Convoy", None)
SHAPES = frozenset(ARTWORK)
CONTACT_MASS = {"carrack": 8.0, "ironclad": 12.0, "destroyer": 14.0, "pre_dreadnought": 20.0, "dreadnought": 28.0, "battleship": 30.0, "aircraft_carrier": 26.0, "submarine": 10.0, "convoy": 6.0}


@dataclass(frozen=True)
class Mount:
    forward: float  # Fraction of hull length from its center.
    sideways: float  # Fraction of hull width from its center.
    bearing: float  # Center of the firing sector relative to the hull.
    arc: float  # Full sector width, in radians.
    weapon: str
    attack_share: float


BROADSIDES = (Mount(0.0, 0.5, math.pi / 2, math.radians(70), "artillery_shell", 1.0), Mount(0.0, -0.5, -math.pi / 2, math.radians(70), "artillery_shell", 1.0))
TURRETS = (Mount(0.32, 0.0, 0.0, math.radians(270), "artillery_shell", 0.5), Mount(-0.32, 0.0, math.pi, math.radians(270), "artillery_shell", 0.5))
FORWARD_TORPEDO = (Mount(0.5, 0.0, 0.0, math.radians(30), "torpedo", 1.0),)
# Convoys retain the shared transport attack, with one forward deck gun.
CONVOY_GUN = (Mount(0.5, 0.0, 0.0, math.radians(90), "artillery_shell", 1.0),)


def mounts(shape):
    if shape in {"carrack", "ironclad"}:
        return BROADSIDES
    if shape == "submarine":
        return FORWARD_TORPEDO
    return CONVOY_GUN if shape == "convoy" else TURRETS


def wrap(angle):
    return (angle + math.pi) % math.tau - math.pi


def sector(fighter, slot):
    mount = mounts(fighter.shape)[slot]
    return fighter.angle + mount.bearing, mount.arc


def aim_allowed(fighter, slot, angle):
    bearing, arc = sector(fighter, slot)
    return abs(wrap(angle - bearing)) <= arc / 2 + 1e-9


def can_fire(fighter, slot, point, tolerance):
    if point is None:
        return False
    start = mount_position(fighter, slot)
    desired = math.atan2(point[1] - start[1], point[0] - start[0])
    return (math.dist(start, point) <= fighter.weapon(slot)["range"] and aim_allowed(fighter, slot, desired)
            and abs(wrap(desired - fighter.weapon_aim(slot))) <= tolerance)


def slew(fighter, slot, desired, dt):
    bearing, arc = sector(fighter, slot)
    current = max(-arc / 2, min(arc / 2, wrap(fighter.weapon_aim(slot) - bearing)))
    goal = max(-arc / 2, min(arc / 2, wrap(desired - bearing)))
    step = math.radians(AIM_SPEED) * dt
    return (bearing + current + max(-step, min(step, goal - current))) % math.tau


def mount_position(fighter, slot):
    mount = mounts(fighter.shape)[slot]
    width, height = c.TACTICAL_BODIES[fighter.shape][:2]
    forward, sideways = width * mount.forward, height * mount.sideways
    co, si = math.cos(fighter.angle), math.sin(fighter.angle)
    return fighter.x + co * forward - si * sideways, fighter.y + si * forward + co * sideways


def muzzle_position(fighter, slot, angle=None):
    """Start outside the hull, so the launching ship never immediately hits itself."""
    start = mount_position(fighter, slot)
    angle = fighter.weapon_aim(slot) if angle is None else angle
    reach = fighter.radius * 2
    end = start[0] + math.cos(angle) * reach, start[1] + math.sin(angle) * reach
    interval = hull_interval(start, end, fighter, padding=TORPEDO_RADIUS)
    distance = (interval[1] * reach if interval is not None else 0.0) + MUZZLE_CLEARANCE
    return start[0] + math.cos(angle) * distance, start[1] + math.sin(angle) * distance


def clamp_launch_angle(fighter, slot, angle):
    bearing, arc = sector(fighter, slot)
    return bearing + max(-arc / 2, min(arc / 2, wrap(angle - bearing)))


def torpedo_corridor_contact(shot, target, duration, spread, clearance):
    """Conservatively cover every dispersed ray against a hull moving straight.

    Refine the cone width using the last possible contact time. Each refinement
    still covers the whole previous contact interval, including its widest end.
    """
    start = shot.x, shot.y
    end = shot.x + (shot.vx - target.vx) * duration, shot.y + (shot.vy - target.vy) * duration
    widening = math.hypot(shot.vx, shot.vy) * math.tan(spread)
    latest = duration
    for _ in range(3):
        interval = hull_interval(start, end, target, padding=TORPEDO_RADIUS + clearance + widening * latest)
        if interval is None:
            return None
        latest = interval[1] * duration
    return interval[0]


def hull_interval(start, end, fighter, *, padding=0.0, position=None, angle=None):
    """Entry/exit fractions of a swept point against the oriented hull rectangle."""
    center = (fighter.x, fighter.y) if position is None else position
    angle = fighter.angle if angle is None else angle
    co, si = math.cos(angle), math.sin(angle)
    width, height = c.TACTICAL_BODIES[fighter.shape][:2]
    enter, leave = 0.0, 1.0
    for axis, half in (((co, si), width / 2 + padding), ((-si, co), height / 2 + padding)):
        offset = (start[0] - center[0]) * axis[0] + (start[1] - center[1]) * axis[1]
        velocity = (end[0] - start[0]) * axis[0] + (end[1] - start[1]) * axis[1]
        if abs(velocity) < 1e-12:
            if abs(offset) > half:
                return None
            continue
        low, high = sorted(((-half - offset) / velocity, (half - offset) / velocity))
        enter, leave = max(enter, low), min(leave, high)
        if enter > leave:
            return None
    return enter, leave


def swept_hull_interval(start, end, fighter, start_position, end_position, start_angle, end_angle, padding=0.0):
    """Sweep the rotating bow and stern as well as the hull's translation.

    Each small angular segment uses its middle orientation with conservative
    corner padding, so no part of a rotating hull can slip between samples.
    """
    turn = wrap(end_angle - start_angle)
    relative = tuple((start[index] - start_position[index], end[index] - end_position[index]) for index in (0, 1))
    reach = fighter.radius + padding
    if any(min(a, b) > reach or max(a, b) < -reach for a, b in relative):
        return None
    if abs(turn) < 1e-12:
        return hull_interval(tuple(a for a, _ in relative), tuple(b for _, b in relative), fighter, position=(0.0, 0.0), angle=start_angle, padding=padding)
    steps = max(1, math.ceil(abs(turn) * fighter.radius / (2 * HULL_SWEEP_ERROR)))
    angular_padding = fighter.radius * abs(turn) / (2 * steps)
    for step in range(steps):
        low, high = step / steps, (step + 1) / steps
        first = tuple(a + (b - a) * low for a, b in relative)
        last = tuple(a + (b - a) * high for a, b in relative)
        interval = hull_interval(first, last, fighter, position=(0.0, 0.0), angle=start_angle + turn * (low + high) / 2, padding=padding + angular_padding)
        if interval is not None:
            return low + interval[0] / steps, low + interval[1] / steps
    return None


def hull_clearance(point, fighter, position, angle):
    """Distance from a point to the complete oriented hull, including both ends."""
    co, si = math.cos(angle), math.sin(angle)
    dx, dy = point[0] - position[0], point[1] - position[1]
    width, height = c.TACTICAL_BODIES[fighter.shape][:2]
    return math.hypot(max(0.0, abs(dx * co + dy * si) - width / 2), max(0.0, abs(-dx * si + dy * co) - height / 2))


def body_contact(first, second, velocity, other_velocity, dt, *, first_position=None, second_position=None, start_angle=None, padding=0.0):
    """Swept separating-axis hull contact, including ships crossing between ticks."""
    turn = 0.0 if start_angle is None else wrap(first.angle - start_angle)
    angles = (first.angle - turn / 2, second.angle)
    axes = [(math.cos(angle), math.sin(angle)) for angle in angles]
    axes += [(-axis[1], axis[0]) for axis in axes[:]]
    half_sizes = [c.TACTICAL_BODIES[ship.shape][:2] for ship in (first, second)]
    forward = axes[:2]
    enter, leave, contact_axis, smallest = 0.0, 1.0, None, math.inf
    motion = ((other_velocity[0] - velocity[0]) * dt, (other_velocity[1] - velocity[1]) * dt)
    first_position = (first.x, first.y) if first_position is None else first_position
    second_position = (second.x, second.y) if second_position is None else second_position
    delta = second_position[0] - first_position[0], second_position[1] - first_position[1]
    for axis in axes:
        extent = sum((abs(axis[0] * heading[0] + axis[1] * heading[1]) * size[0] + abs(-axis[0] * heading[1] + axis[1] * heading[0]) * size[1]) / 2 for heading, size in zip(forward, half_sizes)) + first.radius * abs(turn) / 2 + padding
        offset = delta[0] * axis[0] + delta[1] * axis[1]
        move = motion[0] * axis[0] + motion[1] * axis[1]
        if abs(move) < 1e-12:
            if abs(offset) > extent:
                return None
            low, high = -math.inf, math.inf
        else:
            low, high = sorted(((-extent - offset) / move, (extent - offset) / move))
        if low > enter or (enter == 0 and extent - abs(offset) < smallest):
            contact_axis = axis, extent
            smallest = extent - abs(offset)
        enter, leave = max(enter, low), min(leave, high)
        if enter > leave:
            return None
    axis, extent = contact_axis
    sign = 1.0 if (delta[0] + motion[0] * enter) * axis[0] + (delta[1] + motion[1] * enter) * axis[1] >= 0 else -1.0
    nx, ny = axis[0] * sign, axis[1] * sign
    overlap = max(0.0, extent - ((delta[0] + motion[0]) * nx + (delta[1] + motion[1]) * ny))
    return enter, nx, ny, overlap


def lead_point(target, start, weapon):
    """Predict the same fixed trajectory's flight time used at launch."""
    point = target.x, target.y
    for _ in range(MAX_LEAD_PASSES):
        flight = min(weapon["range"], math.dist(start, point)) / weapon["speed"]
        point = target.x + target.vx * flight, target.y + target.vy * flight
    return point


def shell_height(shot, seconds):
    return shot.height + shot.vertical_speed * seconds - shot.gravity * seconds * seconds / 2


def descending_time(height, vertical_speed, gravity, target_height=0.0):
    return (vertical_speed + math.sqrt(max(0.0, vertical_speed * vertical_speed + 2 * gravity * (height - target_height)))) / gravity


def projectile_contact(shot, target, dt, start_position, *, movement=None, start_angle=None, end_angle=None, padding=0.0):
    """Hull sweep in relative motion; airborne shells only hit at hull height."""
    dx, dy = (target.x - start_position[0], target.y - start_position[1]) if movement is None else movement
    start = shot.x, shot.y
    if shot.kind == "torpedo":
        angle = target.angle if start_angle is None else start_angle
        interval = swept_hull_interval(start, (shot.x + shot.vx * dt, shot.y + shot.vy * dt), target, start_position, (start_position[0] + dx, start_position[1] + dy), angle, target.angle if end_angle is None else end_angle, TORPEDO_RADIUS + padding)
        return None if interval is None else interval[0]
    end = shot.x + shot.vx * dt - dx, shot.y + shot.vy * dt - dy
    interval = hull_interval(start, end, target, position=start_position)
    if interval is None:
        return None
    enter, leave = interval
    # A shell can descend into the hull after first entering its horizontal footprint.
    candidates = sorted((enter * dt, descending_time(shot.height, shot.vertical_speed, shot.gravity, c.TACTICAL_NAVAL_HULL_HEIGHT)))
    for seconds in candidates:
        if enter * dt - 1e-9 <= seconds <= leave * dt + 1e-9 and -1e-7 <= shell_height(shot, seconds) <= c.TACTICAL_NAVAL_HULL_HEIGHT + 1e-7:
            return max(0.0, seconds / dt)
    return None
