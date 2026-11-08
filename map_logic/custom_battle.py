"""Standalone land battles with optional player control and no campaign state."""

import math
import random
from dataclasses import dataclass, field

import data.constants as c
from data import queries
from data.state_access import session_for, world_for
from map_logic.system32 import combat_rules


# These values translate campaign statistics into a small real-time arena.
# They do not change campaign combat or add persistent unit statistics.
FIXED_STEP = 1.0 / 30.0
MOVE_PIXELS_PER_SPEED = 35.0
FIRE_INTERVAL = 2.0
WEAPON_RANGE = 145.0
BOMBARD_RANGE_PIXELS = 65.0
UNIT_RADIUS = 12.0
SPAWN_ROWS = 8
SPAWN_GAP = 30.0
SPAWN_MARGIN = 70.0
RANDOM_ARMY_MIN_UNITS = 3
RANDOM_ARMY_MAX_UNITS = 5
RANDOM_UNIT_AGE_LIMIT = 5
PLAYER_TURN_SPEED = math.radians(150)
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
    "Railgun": "colossus",
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
    """Write a finished battle back: each unit keeps its fraction of health and the dead are removed.

    ``units`` are the campaign units in roster order, friendly army then enemy army.
    """
    for fighter, unit in zip(simulation.fighters, units):
        unit["health"] = fighter.data["health"] / fighter.data["max_health"] * unit["max_health"]
    province["units"] = [unit for unit in province["units"] if unit.get("health", 0) > 0]


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


@dataclass(eq=False)
class Fighter:
    data: dict
    side: int
    x: float
    y: float
    shape: str
    weapon_range: float
    attack_field: str
    cooldown: float = 0.0
    angle: float = 0.0
    vx: float = 0.0
    vy: float = 0.0

    @property
    def alive(self):
        return self.data["health"] > 0


@dataclass
class Projectile:
    source: Fighter
    x: float
    y: float
    vx: float
    vy: float
    attack: float
    remaining: float


@dataclass
class BattleSimulation:
    """Accept unit names at full health or unit records with owner and starting health."""

    library: dict
    friendly: list
    enemy: list
    controlled_index: object = None
    controlled: object = field(init=False, default=None)
    fighters: list = field(init=False, default_factory=list)
    projectiles: list = field(init=False, default_factory=list)
    winner: object = field(init=False, default=None)
    elapsed: float = field(init=False, default=0.0)
    paused: bool = field(init=False, default=False)
    _accumulator: float = field(init=False, default=0.0)
    _throttle: float = field(init=False, default=0.0)
    _turn: float = field(init=False, default=0.0)
    _fire: bool = field(init=False, default=False)

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
            for index, entry in enumerate(roster):
                name = entry["type"] if isinstance(entry, dict) else entry
                column, row = divmod(index, rows)
                x = SPAWN_MARGIN + column * SPAWN_GAP
                if side:
                    x = c.CUSTOM_BATTLE_ARENA_SIZE[0] - x
                y = c.CUSTOM_BATTLE_ARENA_SIZE[1] / 2 + (row - (rows - 1) / 2) * SPAWN_GAP
                owner = entry["owner"] if isinstance(entry, dict) else "Enemy" if side else "Friendly"
                data = queries.create_unit_dict(name, owner, self.library)
                if isinstance(entry, dict):
                    if not valid_starting_health(entry["health"], data["max_health"]):
                        raise ValueError("Starting HP must be above zero and no greater than the unit's maximum HP.")
                    data["health"] = entry["health"]
                # Bombardment attack belongs to the unit library, not to saved instances.
                data["bombard_attack"] = self.library[name].get("bombard_attack", data["attack"])
                bombard_range = queries.get_bombardment_range(name, self.library[name])
                self.fighters.append(Fighter(
                    data, side, x, y, unit_shape(name, self.library),
                    WEAPON_RANGE + bombard_range * BOMBARD_RANGE_PIXELS,
                    "bombard_attack" if bombard_range else "attack",
                    angle=math.pi if side else 0.0))
                if side == 0 and index == self.controlled_index:
                    self.controlled = self.fighters[-1]

    def set_player_input(self, throttle=0.0, turn=0.0, fire=False):
        """Receive held controls; movement and firing still execute on fixed ticks."""
        self._throttle = max(-1.0, min(1.0, throttle))
        self._turn = max(-1.0, min(1.0, turn))
        self._fire = bool(fire)

    def advance(self, seconds):
        """Use fixed simulation ticks; paused time is never saved up for later."""
        if self.paused or self.winner is not None:
            return
        self._accumulator += max(0.0, seconds)
        while self._accumulator + 1e-9 >= FIXED_STEP and self.winner is None:
            self._accumulator = max(0.0, self._accumulator - FIXED_STEP)
            self._step(FIXED_STEP)

    def _step(self, dt):
        self.elapsed += dt
        living = [fighter for fighter in self.fighters if fighter.alive]
        sides = [[fighter for fighter in living if fighter.side == side] for side in (0, 1)]
        # All movement and fire decisions use the same pre-step positions.
        movements = []
        shots = []
        for fighter in living:
            opponents = sides[1 - fighter.side]
            if not opponents:
                continue
            target = min(opponents, key=lambda other: (other.x - fighter.x) ** 2 + (other.y - fighter.y) ** 2)
            dx, dy = target.x - fighter.x, target.y - fighter.y
            distance = math.hypot(dx, dy)
            speed = max(0, fighter.data["speed"]) * MOVE_PIXELS_PER_SPEED
            player_controlled = fighter is self.controlled
            if player_controlled:
                fighter.angle = (fighter.angle + self._turn * PLAYER_TURN_SPEED * dt) % math.tau
                move = self._throttle * speed * dt
                mx, my = math.cos(fighter.angle) * move, math.sin(fighter.angle) * move
            else:
                fighter.angle = math.atan2(dy, dx)
                move = min(speed * dt, max(0, distance - fighter.weapon_range * 0.85))
                mx, my = (dx / distance * move, dy / distance * move) if distance else (0.0, 0.0)
            # A small separation keeps accompanying units visible on an empty field.
            for other in (() if player_controlled else sides[fighter.side]):
                if other is fighter:
                    continue
                sx, sy = fighter.x - other.x, fighter.y - other.y
                gap = math.hypot(sx, sy)
                if 0 < gap < UNIT_RADIUS * 2:
                    push = min(UNIT_RADIUS * 2 - gap, speed * dt) / 2
                    mx += sx / gap * push
                    my += sy / gap * push
            movements.append((fighter, mx, my))
            fighter.cooldown = max(0.0, fighter.cooldown - dt)
            wants_fire = self._fire if player_controlled else distance <= fighter.weapon_range
            if wants_fire and fighter.cooldown <= 0:
                # Shared health scaling and target capability rules own attack strength.
                attack = sum(shot[1] for shot in combat_rules.damage_shots(
                    [fighter.data], [target.data], attack_field=fighter.attack_field))
                if attack > 0:
                    shots.append((fighter, target, attack, distance))
                    fighter.cooldown = FIRE_INTERVAL
        for fighter, target, attack, distance in shots:
            if fighter is self.controlled:
                dx, dy = math.cos(fighter.angle), math.sin(fighter.angle)
            else:
                lead_time = distance / c.CUSTOM_BATTLE_PROJECTILE_SPEED
                dx = target.x + target.vx * lead_time - fighter.x
                dy = target.y + target.vy * lead_time - fighter.y
            length = math.hypot(dx, dy) or 1.0
            self.projectiles.append(Projectile(
                fighter, fighter.x, fighter.y, dx / length * c.CUSTOM_BATTLE_PROJECTILE_SPEED,
                dy / length * c.CUSTOM_BATTLE_PROJECTILE_SPEED, attack,
                (fighter.weapon_range + UNIT_RADIUS * 2) / c.CUSTOM_BATTLE_PROJECTILE_SPEED))
        for fighter, mx, my in movements:
            x = min(c.CUSTOM_BATTLE_ARENA_SIZE[0] - UNIT_RADIUS, max(UNIT_RADIUS, fighter.x + mx))
            y = min(c.CUSTOM_BATTLE_ARENA_SIZE[1] - UNIT_RADIUS, max(UNIT_RADIUS, fighter.y + my))
            fighter.vx, fighter.vy = (x - fighter.x) / dt, (y - fighter.y) / dt
            fighter.x, fighter.y = x, y

        # Accumulate impacts first so units destroyed together can both land their shots.
        hits = []
        remaining = []
        for shot in self.projectiles:
            nx, ny = shot.x + shot.vx * dt, shot.y + shot.vy * dt
            collisions = []
            for target in sides[1 - shot.source.side]:
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
            # Tactical defense blocks a flat amount per hit, even when wounded.
            # Campaign combat instead scales defense with remaining health.
            loss = max(0.0, shot.attack - target.data["defense"])
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
