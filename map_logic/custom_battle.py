"""Standalone land and naval battles with optional control and no campaign state."""

import math
import random
from dataclasses import dataclass, field

import data.constants as c
from data import queries
from data.io import starting_defaults
from map_logic import battle_terrain, naval_battle as naval, tactical_rules as rules
from map_logic import tactical_campaign as campaign, tactical_units as units
from map_logic.system32 import combat_rules
from map_logic.tactical_land_ai import LandBehavior
from map_logic.tactical_naval_ai import NavalBehavior


@dataclass
class BattleSimulation(LandBehavior, NavalBehavior):
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

    on_hit: object = None  # Optional presentation callback: struck body, HP actually lost, the projectile's kind, and the hit point.

    on_kill: object = None  # Optional presentation callback: source, destroyed sub-unit, and shot/ram.

    # Each roster entry's column (see valid_columns). None deploys one division per column.
    friendly_columns: object = None

    enemy_columns: object = None

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

    @property
    def naval(self):
        return self.terrain in c.WATER_TERRAINS

    @property
    def arena_size(self):
        return naval.ARENA_SIZE if self.naval else rules.ARENA_SIZE

    @property
    def sight_range(self):
        return max((fighter.weapon_range for fighter in self.fighters), default=rules.WEAPON_RANGE) if self.naval else rules.WEAPON_RANGE

    @property
    def max_radius(self):
        return max((c.TACTICAL_BODIES[shape][2] for shape in naval.SHAPES), default=rules.MAX_UNIT_RADIUS) if self.naval else rules.MAX_UNIT_RADIUS

    def __post_init__(self):
        if self.controlled_index is not None and (
                type(self.controlled_index) is not int or not 0 <= self.controlled_index < len(self.friendly)):
            raise ValueError("The controlled unit must be an existing friendly roster entry.")
        self._rng = random.Random(self.seed)
        if self.battlefield is not None:
            self.terrain = self.battlefield.terrain
        if self.battlefield is None:
            self.battlefield = battle_terrain.Battlefield.generate(
                self.terrain, self.arena_size, self.max_radius, naval.FRONT_GAP if self.naval else rules.SPAWN_FRONT_GAP, self.seed,
                deployment_half_height=rules.deployment_half_height())
        allowed = set(rules.custom_unit_types(self.library))
        for side, (roster, columns) in enumerate(((self.friendly, self.friendly_columns), (self.enemy, self.enemy_columns))):
            if not roster or len(roster) > c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE:
                raise ValueError(f"Each army needs 1 to {c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE} units.")
            if columns is None:
                columns = list(range(len(roster)))
            if not campaign.valid_columns(columns, len(roster)):
                raise ValueError(f"Each army needs one column number per unit, numbered from 0 without gaps, with at most "
                                 f"{c.CUSTOM_BATTLE_UNITS_PER_COLUMN} units per column and {c.CUSTOM_BATTLE_MAX_COLUMNS_PER_SIDE} columns.")
            if any(rules.battle_unit_type(entry["type"] if isinstance(entry, dict) else entry, self.library) not in allowed
                   for entry in roster):
                raise ValueError("Custom battles accept only current land-unit or ship identifiers.")
            front = (self.arena_size[0] - (naval.FRONT_GAP if self.naval else rules.SPAWN_FRONT_GAP)) / 2
            column_count = columns[-1] + 1
            offset = rules.stack_offset()
            for index, entry in enumerate(roster):
                name = entry["type"] if isinstance(entry, dict) else entry
                column = columns[index]
                # The first column stands in the front rank, the last one furthest back.
                x = front - column * (naval.RANK_GAP if self.naval else rules.RANK_GAP)
                # A column's only division stands centered; two stand one above the other.
                height = 0.0 if columns.count(column) == 1 else offset if index and columns[index - 1] == column else -offset
                if side:
                    x = self.arena_size[0] - x
                owner = entry["owner"] if isinstance(entry, dict) else "Enemy" if side else "Friendly"
                # Campaign Trucks retain their live stats. Other entries use the active library,
                # as land battles did before naval terrain was introduced.
                data = (dict(entry) if isinstance(entry, dict) and not self.naval and rules.packed_ship_type(name, self.library)
                        else rules.create_battle_unit(name, owner, self.library, self.terrain))
                if isinstance(entry, dict):
                    source_max = entry["max_health"] if self.naval or self.library.get(name, {}).get("naval_unit") or rules.battle_unit_type(name, self.library) != name else data["max_health"]
                    if not rules.valid_starting_health(entry["health"], source_max):
                        raise ValueError("Starting HP must be above zero and no greater than the unit's maximum HP.")
                    data["health"] = entry["health"] / source_max * data["max_health"]
                    if "_supply_multiplier" in entry:
                        data["_supply_multiplier"] = entry["_supply_multiplier"]
                members = self._deploy_division(data, side, x, rules.unit_shape(data["type"], self.library),
                                                self.arena_size[1] / 2 + height)
                # Each column approaches in its own lane; a stacked division keeps its height within it.
                lane = (column - (column_count - 1) / 2) * (naval.LANE_GAP if self.naval else rules.APPROACH_LANE_GAP) + height
                for fighter in members:
                    fighter.lane = lane
                if side == 0 and index == self.controlled_index:
                    self.controlled = members[len(members) // 2]  # The middle of the line.

    def enemy_has_tanks(self):
        """Whether the enemy army deployed a tank. Tactical battle music uses this; friendly tanks do not count."""
        return any(fighter.side == 1 and fighter.shape in rules.TANK_SHAPES for fighter in self.fighters)

    def _deploy_division(self, data, side, x, shape, y):
        """Split one division into sub-units standing in a vertical line at ``x``, centered on ``y``.

        A division at fraction ``f`` of full health brings ceil(f * N) of its N sub-units,
        sharing its health equally: 63% of 10 is 7 sub-units at 90% each.
        A line with fewer sub-units is shorter, since the spacing between them stays the same.
        """
        full = data["max_health"]
        size = rules.SUBUNIT_COUNTS[shape]
        count, subunit = rules.division_deployment(data, shape)
        facing = math.pi if side else 0.0
        division = len(self.divisions)
        # Spread target searches across ticks instead of running them all at once.
        stagger = round(rules.RETARGET_SECONDS / rules.FIXED_STEP)
        rng = self._rng
        flank = rng.choice((-1, 1))  # The whole division swings out to the same side.
        members = []
        metadata = queries.get_unit_metadata(data["type"], self.library)
        for number in range(count):
            slot = (number - (count - 1) / 2) * rules.SUBUNIT_SPACING
            members.append(units.Fighter(
                dict(subunit), side,
                x, y + slot, shape, division=division, attack_share=1 / size,
                angle=facing, aim=facing + naval.mounts(shape)[0].bearing if shape in naval.SHAPES else facing,
                secondary_aim=facing + naval.mounts(shape)[1].bearing if shape in naval.SHAPES and len(naval.mounts(shape)) > 1 else facing,
                index=len(self.fighters) + number,
                retarget=(len(self.fighters) + number) % stagger * rules.FIXED_STEP, slot=slot,
                hold=rng.uniform(*rules.AI_HOLD_RANGE), pace=rng.uniform(*rules.AI_PACE),
                start_delay=rng.uniform(*rules.AI_START_DELAY), wander=rng.uniform(0.0, rules.AI_WANDER_ANGLE),
                wander_period=rng.uniform(*rules.AI_WANDER_PERIOD), wander_phase=rng.uniform(0.0, math.tau),
                flank=flank,
                primary_weapon=(metadata.get("tactical_support") if number == 0 and count > 1
                                and metadata.get("tactical_support") else metadata.get("tactical_primary"))))
        self.divisions.append(members)
        self._division_health.append(full)
        self._division_targets.append(None)
        self._division_retarget.append(division % stagger * rules.FIXED_STEP)
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
        while self._accumulator + 1e-9 >= rules.FIXED_STEP and self.winner is None:
            self._accumulator = max(0.0, self._accumulator - rules.FIXED_STEP)
            self._step(rules.FIXED_STEP)

    @staticmethod
    def _accelerate(fighter, throttle, dt):
        """Ease the forward speed toward ``throttle`` times top speed; reverse uses the same rate."""
        seconds = rules.MOBILITY[fighter.shape][0]
        top = fighter.max_speed
        fighter.speed = rules.step_toward(fighter.speed, throttle * top, top / seconds * dt)

    @staticmethod
    def _heading_controls(fighter, throttle, heading):
        turning = rules.wrap_angle(heading - fighter.angle)
        # Turn toward the heading before driving hard along it.
        throttle *= max(0.0, math.cos(turning))
        _seconds, degrees, seconds = rules.MOBILITY[fighter.shape]
        # Ease off the turn before the hull lines up, since the turn rate cannot stop at once.
        turn = max(-1.0, min(1.0, turning / (math.radians(degrees) * seconds)))
        return throttle, turn

    @staticmethod
    def _steer(fighter, turn, dt):
        """Ease the turn rate toward ``turn`` times the top turn speed, then turn the hull."""
        _seconds, degrees, seconds = rules.MOBILITY[fighter.shape]
        top = math.radians(degrees)
        fighter.turn_rate = rules.step_toward(fighter.turn_rate, turn * top, top / seconds * dt)
        fighter.angle = (fighter.angle + fighter.turn_rate * dt) % math.tau

    @staticmethod
    def _slew_aim(fighter, desired, dt):
        """Turn the gun toward ``desired`` at the gun's turn speed, inside the firing cone if it has one.

        The cone is measured from the hull, so turning the hull carries the cone and the gun with it.
        """
        step = math.radians(rules.AIM[fighter.shape][1]) * dt
        cone = rules.firing_cone(fighter.shape)
        if cone is None:
            fighter.aim = (fighter.aim + max(-step, min(step, rules.wrap_angle(desired - fighter.aim)))) % math.tau
            return
        half = cone / 2
        current = max(-half, min(half, rules.wrap_angle(fighter.aim - fighter.angle)))
        goal = max(-half, min(half, rules.wrap_angle(desired - fighter.angle)))
        fighter.aim = (fighter.angle + rules.step_toward(current, goal, step)) % math.tau

    @staticmethod
    def _attack(source, target):
        """Use tactical wound scaling with shared target restrictions."""
        return sum(shot[1] for shot in combat_rules.damage_shots(
            [source], [target], health_floor=rules.TACTICAL_DAMAGE_AT_ZERO_HEALTH))

    @classmethod
    def damage_amount(cls, source, target, attack_share, multiplier=1.0):
        """Tactical pacing follows full defense and division sharing for every attack kind.

        Round before pacing so even the smallest positive hits take longer than before.
        Wound scaling follows TACTICAL_DAMAGE_AT_ZERO_HEALTH for each surviving sub-unit.
        """
        loss = max(0.0, cls._attack(source, target) - target["defense"]) * attack_share
        return math.ceil(loss) * rules.DAMAGE_SCALE * multiplier

    @classmethod
    def weapon_damage(cls, source, target, attack_share, weapon, target_shape, multiplier=1.0):
        # Machine guns cannot borrow a tank's anti-armor capability. The shared
        # target rules still apply to every weapon before tactical scaling.
        if not rules.weapon_target_allowed(weapon, target_shape):
            return 0.0
        return cls.damage_amount(source, target, attack_share, weapon["damage"] * multiplier)

    @staticmethod
    def ranged_multiplier(distance):
        """Land shots only; naval shots keep full damage at every distance."""
        fraction = max(0.0, min(1.0, (distance - rules.FALLOFF_START) / (rules.WEAPON_RANGE - rules.FALLOFF_START)))
        return 1.0 - fraction * (1.0 - rules.MIN_RANGED_DAMAGE)

    @staticmethod
    def _queue_shot(fighter, shots, slot=0):
        shots.append((fighter, slot))
        if not (fighter.naval and fighter.weapon(slot)["projectile"] == "torpedo"):
            BattleSimulation._consume_shot(fighter, slot)

    @staticmethod
    def _consume_shot(fighter, slot=0):
        """Advance the shared magazine/reload state only when a shot is accepted."""
        weapon = fighter.weapon(slot)
        rounds = (fighter.secondary_rounds if slot else fighter.primary_rounds) + 1
        wait = weapon["reload"] if rounds >= weapon["rounds"] else weapon["interval"]
        rounds %= weapon["rounds"]
        if slot:
            fighter.secondary_rounds, fighter.secondary_cooldown, fighter.secondary_wait = rounds, wait, wait
        else:
            fighter.primary_rounds, fighter.cooldown, fighter.primary_wait = rounds, wait, wait

    def _drive_player(self, fighter, dt, shots):
        if fighter.naval:
            self._drive_naval(fighter, dt, shots)
            return
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
    def _shot_spread(fighter, weapon):
        movement = abs(fighter.speed) / fighter.max_speed if fighter.max_speed else 0.0
        turning = abs(fighter.turn_rate) / math.radians(rules.MOBILITY[fighter.shape][1])
        spread = weapon["spread"] + c.TACTICAL_MOVING_SPREAD * movement + c.TACTICAL_TURNING_SPREAD * turning
        return math.radians(spread * (c.TACTICAL_SHELL_SPREAD_MULTIPLIER if weapon["shell"] else 1.0))

    def _fire_shot(self, fighter, slot=0):
        if fighter.naval:
            self._fire_naval_shot(fighter, slot)
            return
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
        self.projectiles.append(units.Projectile(
            fighter, dict(fighter.data), fighter.x, fighter.y, math.cos(angle) * speed,
            math.sin(angle) * speed, rules.WEAPON_RANGE / speed,
            height=height, vertical_speed=vertical_speed, weapon_data=dict(weapon)))
        fighter.fired_weapon = slot
        fighter.muzzle = c.TACTICAL_MUZZLE_SECONDS
        if weapon["shell"]:
            fighter.recoil = c.TACTICAL_MUZZLE_SECONDS
        if self.on_shot is not None:
            self.on_shot(fighter)

    @staticmethod
    def _shell_arc(start, point, weapon):
        """Flight seconds, launch height, and vertical speed of a naval shot landing at ``point``, or at full range."""
        distance = weapon["range"] if point is None else min(weapon["range"], math.dist(start, point))
        flight = max(rules.FIXED_STEP, distance / weapon["speed"])
        gravity = weapon.get("gravity", 0.0)
        if not gravity:
            return flight, 0.0, 0.0
        height = c.TACTICAL_NAVAL_HULL_HEIGHT
        return flight, height, gravity * flight / 2 - height / flight

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
                    <= first.radius + second.radius + rules.CONTACT_RELEASE_DISTANCE - rules.UNIT_RADIUS * 2):
                retained.add(pair)
        damage = []
        for unit in living:
            vx, vy = velocities[unit.index]
            reach = math.hypot(vx, vy) * dt + max_move + unit.radius + self.max_radius
            for crowd in crowds:
                for other in crowd.around(unit.x, unit.y, reach):
                    if other.index <= unit.index:
                        continue
                    diameter = unit.radius + other.radius
                    ovx, ovy = velocities[other.index]
                    if unit.naval and other.naval:
                        contact = naval.body_contact(unit, other, (vx, vy), (ovx, ovy), dt)
                        if contact is None:
                            continue
                        fraction, nx, ny, overlap = contact
                    else:
                        fraction = self._collision_fraction(unit.x, unit.y, unit.x + (vx - ovx) * dt, unit.y + (vy - ovy) * dt, other, radius=diameter)
                        if fraction is None:
                            continue
                        dx = other.x - unit.x + (ovx - vx) * dt * fraction
                        dy = other.y - unit.y + (ovy - vy) * dt * fraction
                        length = math.hypot(dx, dy)
                        nx, ny = (dx / length, dy / length) if length > 1e-9 else (1.0, 0.0)
                        overlap = max(0.0, diameter - ((positions[other.index][0] - positions[unit.index][0]) * nx + (positions[other.index][1] - positions[unit.index][1]) * ny))
                    first_mass, second_mass = rules.CONTACT_MASS[unit.shape], rules.CONTACT_MASS[other.shape]
                    total = first_mass + second_mass
                    first_pos, second_pos = positions[unit.index], positions[other.index]
                    first_pos[0] -= nx * overlap * second_mass / total
                    first_pos[1] -= ny * overlap * second_mass / total
                    second_pos[0] += nx * overlap * first_mass / total
                    second_pos[1] += ny * overlap * first_mass / total
                    closing = max(0.0, (vx - ovx) * nx + (vy - ovy) * ny)
                    pair = (unit.index, other.index)
                    if pair not in retained and closing >= rules.RAM_MIN_SPEED:
                        for source, target, speed, mass, target_mass in (
                                (unit, other, vx * nx + vy * ny, first_mass, second_mass),
                                (other, unit, -ovx * nx - ovy * ny, second_mass, first_mass)):
                            # Rams only hurt enemies; allies still collide and separate.
                            if not source.can_ram or speed < rules.RAM_MIN_SPEED or source.side == target.side:
                                continue
                            strength = min(rules.RAM_MAX_STRENGTH, closing / rules.RAM_REFERENCE_SPEED) * min(1.0, mass / target_mass)
                            damage.append((target, self.damage_amount(source.data, target.data, source.attack_share,
                                                                      rules.RAM_DAMAGE * strength), source))
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

    @staticmethod
    def _impact_kind(shot):
        """Shells and torpedoes splash; a naval bullet leaves the small mark of any bullet."""
        return shot.kind if shot.kind in {"artillery_shell", "torpedo"} else shot.weapon_data["shell"]

    def _step(self, dt):
        if int(self.elapsed / rules.RETARGET_SECONDS) != int((self.elapsed + dt) / rules.RETARGET_SECONDS):
            self.battlefield.begin_decision_interval()
        self.elapsed += dt
        self.impacts = [(x, y, remaining - dt, shell) for x, y, remaining, shell in self.impacts if remaining > dt]
        living = [fighter for fighter in self.fighters if fighter.alive]
        start_positions = {fighter.index: (fighter.x, fighter.y) for fighter in living} if self.naval else {}
        start_angles = {fighter.index: fighter.angle for fighter in living} if self.naval else {}
        sides = [[fighter for fighter in living if fighter.side == side] for side in (0, 1)]
        crowds = [units.SpatialGrid(side, rules.GRID_CELL) for side in sides]
        targets = [units.SpatialGrid(side, rules.TARGET_CELL) for side in sides]
        self._healthy_sides = [any(unit.data["health"] >= unit.data["max_health"] * rules.FALL_BACK_HEALTH
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
            if fighter.naval:
                fighter.mount_muzzles[:] = [max(0.0, value - dt) for value in fighter.mount_muzzles]
                fighter.mount_recoils[:] = [max(0.0, value - dt) for value in fighter.mount_recoils]
            player_controlled = fighter is self.controlled
            if player_controlled:
                self._drive_player(fighter, dt, shots)
            else:
                self._drive_ai(fighter, targets[1 - fighter.side], dt, shots, *objectives[fighter.division])
            move = fighter.speed * dt
            mx = math.cos(fighter.angle) * move + fighter.push_vx * dt
            my = math.sin(fighter.angle) * move + fighter.push_vy * dt
            decay = max(0.0, 1.0 - dt / rules.KNOCKBACK_SECONDS)
            fighter.push_vx *= decay
            fighter.push_vy *= decay
            movements.append((fighter, mx, my))
        for fighter, slot in shots:
            self._fire_shot(fighter, slot)
        close_hits = [(target, loss, source, "ram", None, None)
                      for target, loss, source in self._resolve_contacts(living, crowds, movements, dt)]

        # Accumulate impacts first so units destroyed together can both land their shots.
        # A shot can hit any sub-unit but its shooter, so allies in its path take friendly fire.
        hittable = units.SpatialGrid(living, rules.GRID_CELL)
        remaining = []
        for shot in self.projectiles:
            # Every naval mount's shot, including a convoy's bullet, sweeps ship hulls.
            if self.naval:
                keep, hits = self._advance_naval_projectile(shot, dt, living, start_positions, start_angles=start_angles)
                close_hits.extend(hits)
                if keep:
                    remaining.append(shot)
                continue
            flight = min(dt, shot.remaining)
            if flight <= 0:
                continue
            nx, ny = shot.x + shot.vx * flight, shot.y + shot.vy * flight
            next_height = shot.height + shot.vertical_speed * flight
            traveled = math.hypot(shot.vx, shot.vy) * flight
            terrain_hit = self.battlefield.first_hit((shot.x, shot.y), (nx, ny), shot.height, next_height)
            collisions = []
            for target in hittable.within(min(shot.x, nx) - rules.MAX_UNIT_RADIUS, min(shot.y, ny) - rules.MAX_UNIT_RADIUS,
                                          max(shot.x, nx) + rules.MAX_UNIT_RADIUS, max(shot.y, ny) + rules.MAX_UNIT_RADIUS):
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
                point = (shot.x + (nx - shot.x) * fraction, shot.y + (ny - shot.y) * fraction)
                close_hits.append((target, loss, shot.source, "shot", shot.kind, point))
                shot.hit_units.add(target.index)
                self.impacts.append((*point, c.TACTICAL_IMPACT_SECONDS, shot.weapon_data["shell"]))
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
        for target, loss, source, cause, projectile, point in close_hits:
            previous_health = target.data["health"]
            target.data["health"] = max(0.0, previous_health - loss)
            if cause == "shot" and self.on_hit is not None:
                self.on_hit(target, previous_health - target.data["health"], projectile, point)
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
