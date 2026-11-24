"""Sub-units, projectiles, and the spatial grid a tactical battle moves them through."""

import math
from dataclasses import dataclass, field

import data.constants as c
from map_logic import battle_terrain, naval_battle as naval, tactical_rules as rules


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
    evasion_course: object = None  # Temporary naval (throttle, heading), reconsidered as torpedoes and falling shells move.
    evasion_next_check: float = 0.0
    naval_controls: object = None  # Last applied throttle/turn, for short ally-motion predictions.
    route: list = field(default_factory=list)
    route_revision: int = -1
    navigate_at: float = 0.0
    position_goal: object = None
    ally_blocked: bool = False  # Within weapon range with a clear terrain lane, but an ally in its line of fire.
    position_target: object = None
    primary_weapon: object = None  # None uses the shape's standard loadout.
    secondary_cooldown: float = 0.0
    primary_rounds: int = 0
    secondary_rounds: int = 0
    primary_wait: float = rules.FIRE_INTERVAL
    secondary_wait: float = rules.FIRE_INTERVAL
    muzzle: float = 0.0
    recoil: float = 0.0
    fired_weapon: int = 0  # Presentation callback reads which independent gun fired.
    secondary_target: object = None
    secondary_aim: float = 0.0
    gun_points: list = field(default_factory=lambda: [None, None])
    mount_muzzles: list = field(default_factory=lambda: [0.0, 0.0])
    mount_recoils: list = field(default_factory=lambda: [0.0, 0.0])

    @property
    def naval(self):
        return self.shape in naval.SHAPES

    @property
    def weapon_range(self):
        return max((self.weapon(slot).get("range", rules.WEAPON_RANGE) for slot in (0, 1) if self.weapon(slot) is not None), default=rules.WEAPON_RANGE)

    def weapon_aim(self, slot=0):
        return self.secondary_aim if slot and self.naval else self.aim

    @property
    def radius(self):
        return c.TACTICAL_BODIES[self.shape][2]

    def weapon(self, slot=0):
        if self.naval:
            mounts = naval.mounts(self.shape)
            return c.TACTICAL_WEAPONS[mounts[slot].weapon] if slot < len(mounts) else None
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
        return max(0, self.data["speed"]) * rules.MOVE_PIXELS_PER_SPEED

    @property
    def can_ram(self):
        return self.data["speed"] >= (naval.RAM_MIN_UNIT_SPEED if self.naval else rules.RAM_MIN_UNIT_SPEED)


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
    gravity: float = 0.0
    attack_share: object = None

    def __post_init__(self):
        if self.weapon_data is None:
            self.weapon_data = dict(self.source.weapon())
        if self.penetration is None:
            self.penetration = self.weapon_data["penetration"]
        if self.attack_share is None:
            self.attack_share = self.source.attack_share

    @property
    def kind(self):
        return self.weapon_data.get("projectile", "direct")


class SpatialGrid:
    """Buckets living sub-units by cell so nearby lookups skip the rest of the field."""

    def __init__(self, fighters, cell):
        self.cell = cell
        self.cells = {}
        for fighter in fighters:
            self.cells.setdefault(self._key(fighter.x, fighter.y), []).append(fighter)
        self.reach = math.ceil(max(*rules.ARENA_SIZE, *naval.ARENA_SIZE) / cell) + 1

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
