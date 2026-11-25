"""How land sub-units aim, move, dodge, and ram in a tactical battle."""

import math

from data import queries
from map_logic import battle_terrain, naval_battle as naval, tactical_rules as rules
from map_logic.system32 import combat_rules


class LandBehavior:
    """BattleSimulation methods for land targeting, lines of fire, dodging, and rams."""

    def _firing_lane(self, fighter, target, start=None):
        start = (fighter.x, fighter.y) if start is None else start
        return self.battlefield.firing_blocker(start, (target.x, target.y)) is None

    @staticmethod
    def _lead_point(target, start, speed=rules.PROJECTILE_SPEED):
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
        spread = math.tan(self._shot_spread(fighter, weapon) + rules.AIM_TOLERANCE)
        best, best_along = None, rules.WEAPON_RANGE if weapon["penetration"] > 0 else distance
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
        if fighter.naval:
            return self._naval_ally_in_line(fighter, target, slot) is None
        return (self._firing_lane(fighter, target, start)
                and self._ally_in_line(fighter, target, start, slot=slot) is None)

    def _allies_ahead(self, fighter, hx, hy, *, original=None, time_ahead=0.0, allies=None):
        """Allies whose bodies lie across the path from ``fighter`` along the unit vector (hx, hy).

        Yields (ally, gap before the bodies touch, the ally's speed along the path, the ally's offset
        to the left of the path; negative is to the right).
        """
        for ally in self._sides[fighter.side] if allies is None else allies:
            if ally is (fighter if original is None else original):
                continue
            ox, oy = ally.x + ally.vx * time_ahead - fighter.x, ally.y + ally.vy * time_ahead - fighter.y
            along = ox * hx + oy * hy
            clearance = fighter.radius + ally.radius
            beside = oy * hx - ox * hy
            if along <= 0 or abs(beside) > clearance:
                continue
            yield ally, max(0.0, along - clearance), ally.vx * hx + ally.vy * hy, beside

    def _ally_safe_throttle(self, fighter, throttle, *, original=None, time_ahead=0.0, allies=None):
        """Brake ram-capable AI units before they hit allies fast enough to damage them."""
        if not throttle or not fighter.can_ram:
            return throttle
        direction = 1.0 if throttle > 0 else -1.0
        hx, hy = math.cos(fighter.angle) * direction, math.sin(fighter.angle) * direction
        acceleration = fighter.max_speed / rules.MOBILITY[fighter.shape][0]
        limit = abs(throttle) * fighter.max_speed
        for _ally, gap, ally_speed, _beside in self._allies_ahead(fighter, hx, hy, original=original, time_ahead=time_ahead, allies=allies):
            # Brake in time to arrive no faster than ALLY_BUMP_SPEED; the ally's own motion opens or closes the gap.
            allowed = math.sqrt(rules.ALLY_BUMP_SPEED ** 2 + 2 * acceleration * gap)
            limit = min(limit, ally_speed + allowed)
        return direction * max(0.0, limit) / fighter.max_speed

    def _pass_allies(self, fighter, throttle, heading):
        """Bend a ship's forward course to pass a slower ally that lies across it, on the side away from that ally.

        Only units that brake for allies (_ally_safe_throttle) pass them. Ships use it; land units keep
        braking in formation, because in headless battles land units that bent around allies lost more
        often. The check follows the intended straight course, so the bend ends once the ship is
        alongside the ally or past it. An ally dead ahead is passed on the side its division flanks to.
        """
        if throttle <= 0 or not fighter.can_ram:
            return throttle, heading
        hx, hy = math.cos(heading), math.sin(heading)
        speed = throttle * fighter.max_speed
        blocking = [(gap, beside) for _ally, gap, ally_speed, beside in self._allies_ahead(fighter, hx, hy)
                    if ally_speed < speed and gap <= fighter.max_speed * rules.PASS_ALLY_SECONDS]
        if not blocking:
            return throttle, heading
        _gap, beside = min(blocking)
        side = (1 if beside > 0 else -1) if abs(beside) > 1e-9 else fighter.flank
        return throttle, heading - side * rules.PASS_ALLY_ANGLE

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
        key = (shooter.data["type"], target.data["type"], queries.unit_supply_multiplier(shooter.data))
        if key not in self._full_attacks:
            full = dict(shooter.data, health=shooter.data["max_health"])
            self._full_attacks[key] = self._attack(full, target.data)
        multiplier = combat_rules.health_damage_multiplier(shooter.data, health_floor=rules.TACTICAL_DAMAGE_AT_ZERO_HEALTH)
        return self._full_attacks[key] * multiplier > target.data["defense"]

    def _weapon_can_hurt(self, fighter, target, slot=0):
        weapon = fighter.weapon(slot)
        return rules.weapon_target_allowed(weapon, target.shape) and self._can_hurt(fighter, target)

    def _choose_target(self, fighter, enemies, slot=0):
        """The enemy to shoot: the nearest, unless one close to it is wounded and this sub-unit can hurt it.

        A wounded enemy counts as nearer, and enemies this sub-unit cannot damage are passed over.
        Enemies behind terrain or allies come after those with a clear shot.
        """
        nearest = enemies.nearest(fighter.x, fighter.y)
        best, best_score = None, math.inf
        for enemy in enemies.around(nearest.x, nearest.y, rules.TARGET_CHOICE_SLACK):
            if not self._weapon_can_hurt(fighter, enemy, slot):
                continue
            wounds = 1.0 - enemy.data["health"] / enemy.data["max_health"]
            score = math.hypot(enemy.x - fighter.x, enemy.y - fighter.y) * (1.0 - rules.TARGET_WOUNDED_PULL * wounds)
            if fighter.weapon(slot)["shell"] and enemy.shape not in rules.SOFT_TARGET_SHAPES:
                score *= rules.CANNON_ARMOR_PRIORITY
            if not self._clear_shot(fighter, enemy, slot=slot):
                score += rules.WEAPON_RANGE
            if score < best_score:
                best, best_score = enemy, score
        return best or nearest

    def _ai_course(self, fighter, distance, toward, center, objective):
        """(throttle share, heading) for an AI sub-unit. ``toward`` is the heading to the enemy it shoots at.

        Reactions come first: a badly hurt sub-unit falls back, and one that was just hit sidesteps.
        Otherwise its shape's behavior decides (BEHAVIORS). Within weapon range, a sub-unit whose shot
        an ally blocks is never in position; _terrain_course finds it a clear firing position.
        """
        away = toward + math.pi
        fighter.ally_blocked = False
        if (fighter.data["health"] < fighter.data["max_health"] * rules.FALL_BACK_HEALTH
                and self._healthy_sides[fighter.side]):
            # Retreat while healthier allies cover the withdrawal. The last wounded
            # troops keep fighting, so two depleted armies do not both flee forever.
            fighter.ram_committed = False
            if not self._firing_lane(fighter, fighter.target or objective):
                return 0.0, toward
            if fighter.shape not in rules.FOOT_SHAPES:
                return (-fighter.pace, toward) if distance < rules.WITHDRAW_RANGE else (0.0, toward)
            return (fighter.pace, away) if distance < rules.WITHDRAW_RANGE else (0.0, toward)
        if fighter.ram_committed and (distance <= rules.RAM_COMMIT_RANGE or fighter.dodge <= 0):
            point = self._ram_point(fighter, fighter.target)
            if point is not None:
                return fighter.pace, math.atan2(point[1] - fighter.y, point[0] - fighter.x)
            return fighter.pace, toward
        if fighter.dodge > 0:
            return fighter.pace, fighter.dodge_heading
        behavior = rules.BEHAVIORS.get(fighter.shape)
        hold = fighter.hold
        if behavior == "skirmish":
            if distance < rules.ENGAGEMENT_RANGE * rules.SKIRMISH_BACK_OFF:
                return -fighter.pace, toward
            hold = rules.SKIRMISH_HOLD
        elif behavior == "charge":
            if fighter.withdrawing and distance < rules.ENGAGEMENT_RANGE * fighter.hold:
                return fighter.pace, away
            fighter.withdrawing = distance <= rules.ENGAGEMENT_RANGE * rules.CHARGE_CLOSE
            if fighter.withdrawing:
                return fighter.pace, away
            hold = rules.CHARGE_CLOSE
        flanking = behavior == "flank" and not fighter.flank_complete
        target = fighter.target or objective
        lane = not flanking and self._firing_lane(fighter, target)
        # Within weapon range, an ally in the line of fire sends it to a clear firing position, closing in or parked.
        fighter.ally_blocked = lane and distance <= rules.WEAPON_RANGE and self._ally_in_line(fighter, target) is not None
        if distance <= rules.ENGAGEMENT_RANGE * hold and lane and not fighter.ally_blocked:
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
                    max(fighter.radius, min(rules.ARENA_SIZE[0] - fighter.radius,
                                        objective.x - forward * rules.ENGAGEMENT_RANGE * hold)),
                    max(fighter.radius, min(rules.ARENA_SIZE[1] - fighter.radius,
                                        objective.y + fighter.slot + fighter.lane + fighter.flank * rules.FLANK_OFFSET)))
            goal_x, goal_y = fighter.flank_goal
            if math.hypot(goal_x - fighter.x, goal_y - fighter.y) <= rules.FLANK_ARRIVAL_DISTANCE:
                fighter.flank_complete = True
                return 0.0, toward
        goal_y = max(fighter.radius, min(rules.ARENA_SIZE[1] - fighter.radius, goal_y))
        weave = fighter.wander * math.sin(math.tau * self.elapsed / fighter.wander_period + fighter.wander_phase)
        throttle = fighter.pace
        # A sub-unit well ahead of its division slows down to let the division catch up; charging cavalry does not.
        if (behavior != "charge"
                and (fighter.x - center[0]) * course_x + (fighter.y - center[1]) * course_y > rules.COHESION_SLACK):
            throttle *= rules.COHESION_THROTTLE
        return throttle, math.atan2(goal_y - fighter.y, goal_x - fighter.x) + weave

    def _firing_position(self, fighter, target):
        """An accessible firing position with a shot clear of terrain and allies, or None.

        Blocked shots never count as holding a position.
        """
        start = fighter.x, fighter.y
        preferred = rules.ENGAGEMENT_RANGE * fighter.hold
        candidates = []
        toward = math.atan2(fighter.y - target.y, fighter.x - target.x)
        for scale in rules.FIRING_POSITION_RINGS:
            for index in range(rules.FIRING_POSITION_ANGLES):
                angle = toward + math.tau * index / rules.FIRING_POSITION_ANGLES
                candidates.append((target.x + math.cos(angle) * preferred * scale,
                                   target.y + math.sin(angle) * preferred * scale))
        distance = math.dist(start, (target.x, target.y))
        if distance:
            fraction = min(1.0, rules.FIRING_POSITION_STEP / distance)
            candidates.append((fighter.x + (target.x - fighter.x) * fraction,
                               fighter.y + (target.y - fighter.y) * fraction))
            ux, uy = (target.x - fighter.x) / distance, (target.y - fighter.y) / distance
            candidates.extend((fighter.x - uy * side * share * rules.FIRING_POSITION_STEP, fighter.y + ux * side * share * rules.FIRING_POSITION_STEP)
                              for share in rules.FIRING_POSITION_SIDESTEPS for side in (-1, 1))
        # A nearby crest can be a better firing position than a long detour.
        candidates.extend((feature.x, feature.y) for feature in self.battlefield.nearby(
            start, start, rules.ENGAGEMENT_RANGE) if feature.kind == "hill")
        candidates.sort(key=lambda point: math.dist(start, point)
                        + abs(math.dist(point, (target.x, target.y)) - preferred) * rules.FIRING_DISTANCE_WEIGHT)
        for point in candidates:
            if (self.battlefield.walkable(point, fighter.radius) and self._clear_shot(fighter, target, point)
                    and self.battlefield.route(start, point, fighter.radius)):
                return point
        return None

    def _cover_position(self, fighter, target):
        start = fighter.x, fighter.y
        candidates = []
        for index in range(rules.FIRING_POSITION_ANGLES):
            angle = math.tau * index / rules.FIRING_POSITION_ANGLES
            point = (fighter.x + math.cos(angle) * rules.FIRING_POSITION_STEP,
                     fighter.y + math.sin(angle) * rules.FIRING_POSITION_STEP)
            if (self.battlefield.walkable(point, fighter.radius)
                    and not self._firing_lane(fighter, target, point)):
                candidates.append(point)
        candidates.sort(key=lambda point: math.dist(start, point)
                        - math.dist(point, (target.x, target.y)) * rules.COVER_DISTANCE_WEIGHT)
        return next((point for point in candidates if self.battlefield.route(start, point, fighter.radius)), None)

    def _terrain_course(self, fighter, throttle, heading, center, objective):
        """Route the existing behavior around terrain without changing its controller or side."""
        target = fighter.target
        start = fighter.x, fighter.y
        if fighter.ram_committed and (fighter.dodge <= 0 or math.dist(start, (target.x, target.y)) <= rules.RAM_COMMIT_RANGE):
            return throttle, heading
        if not throttle:
            fighter.route.clear()
            fighter.position_goal = None
            return throttle, heading
        revision = self.battlefield.revision
        reconsider = (self.elapsed >= fighter.navigate_at or fighter.route_revision != revision
                      or fighter.position_target is not target)
        retreating = (fighter.data["health"] < fighter.data["max_health"] * rules.FALL_BACK_HEALTH
                      and self._healthy_sides[fighter.side])
        if reconsider:
            fighter.navigate_at = self.elapsed + rules.NAVIGATION_SECONDS
            fighter.route_revision = revision
            fighter.position_target = target
            fighter.position_goal = None
            flanking = rules.BEHAVIORS.get(fighter.shape) == "flank" and not fighter.flank_complete
            if retreating:
                fighter.position_goal = self._cover_position(fighter, target)
            elif (not flanking and fighter.dodge <= 0 and not fighter.ram_committed
                  and not fighter.withdrawing and throttle > 0):
                if not self._firing_lane(fighter, target):
                    fighter.position_goal = self._firing_position(fighter, target) or (target.x, target.y)
                elif fighter.ally_blocked:
                    # An ally stands in the line of fire: move to a nearby position with a clear shot, if there is one.
                    fighter.position_goal = self._firing_position(fighter, target)
            if fighter.position_goal is not None:
                goal = fighter.position_goal
            elif flanking and fighter.flank_goal is not None and fighter.dodge <= 0:
                goal = fighter.flank_goal
            elif throttle < 0 or retreating or fighter.withdrawing or fighter.dodge > 0:
                direction = heading + (math.pi if throttle < 0 else 0.0)
                goal = (fighter.x + math.cos(direction) * rules.FIRING_POSITION_STEP,
                        fighter.y + math.sin(direction) * rules.FIRING_POSITION_STEP)
            else:
                goal, _ = self.advance_point(fighter, center, objective, fighter.lane)
            fighter.route = self.battlefield.route(start, goal, fighter.radius)
            if flanking and fighter.route:
                # A formation destination can fall inside an obstacle. Complete
                # the flank at its reachable replacement, then seek a clear shot.
                fighter.flank_goal = fighter.route[-1]
        while fighter.route and math.dist(start, fighter.route[0]) <= rules.WAYPOINT_REACH:
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
        if fighter.naval:
            self._drive_naval(fighter, dt, shots, enemies)
            return
        fighter.retarget -= dt
        if fighter.retarget <= 0:
            fighter.retarget += rules.RETARGET_SECONDS
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
        throttle, heading = self._ai_course(fighter, distance, math.atan2(dy, dx), center, objective)
        # Open ground needs no routing, except to reach a firing position clear of allies.
        if self.battlefield.features or fighter.ally_blocked or fighter.position_goal is not None:
            throttle, heading = self._terrain_course(fighter, throttle, heading, center, objective)
        # A loaded sub-unit with an ally in its line of fire, and no firing position to head for,
        # steps out from behind the ally from the next tick.
        if fighter.dodge <= 0 and not fighter.ram_committed and fighter.position_goal is None:
            for slot, gun_target in enumerate((target, fighter.secondary_target)):
                if (gun_target is None or fighter.weapon(slot) is None or fighter.weapon_cooldown(slot) > 0
                        or not self._weapon_can_hurt(fighter, gun_target, slot)
                        or math.dist((fighter.x, fighter.y), (gun_target.x, gun_target.y)) > rules.WEAPON_RANGE
                        or not self._firing_lane(fighter, gun_target)):
                    continue
                ally = self._ally_in_line(fighter, gun_target, slot=slot)
                if ally is not None:
                    # Step out from behind the ally, away from its side of the firing line.
                    self._sidestep(fighter, ally.x, ally.y, gun_target.x - fighter.x,
                                   gun_target.y - fighter.y, rules.LINE_SHIFT_SECONDS)
                    fighter.navigate_at = 0.0
                    break
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
            if (fighter.weapon_cooldown(slot) <= 0 and math.dist((fighter.x, fighter.y), (gun_target.x, gun_target.y)) <= rules.WEAPON_RANGE
                    and abs(rules.wrap_angle(desired - fighter.aim)) <= rules.AIM_TOLERANCE
                    and self._weapon_can_hurt(fighter, gun_target, slot)
                    and self._clear_shot(fighter, gun_target, slot=slot)):
                self._queue_shot(fighter, shots, slot)

    def _can_dodge(self, unit):
        """Only fast AI sub-units sidestep; for slower ones the time spent turning away costs more aim than it saves."""
        return unit is not self.controlled and unit.data["speed"] >= rules.DODGE_MIN_SPEED

    def _sidestep(self, unit, x, y, vx, vy, seconds):
        """Sidestep at right angles to a path through (x, y) along (vx, vy), away from it.

        Dead on the path, the unit steps away from its nearest other ally, so two units sharing a
        column do not step into each other; with no ally beside the path, it picks a random side.
        """
        length = math.hypot(vx, vy)

        def offset(point):
            # How far a point sits to the left of the path; negative is to the right.
            return ((point[1] - y) * vx - (point[0] - x) * vy) / length

        own = offset((unit.x, unit.y))
        if abs(own) > 1e-9:
            side = 1 if own > 0 else -1
        else:
            others = [ally for ally in self._sides[unit.side] if ally is not unit and (ally.x, ally.y) != (x, y)]
            nearest = min(others, key=lambda ally: math.dist((ally.x, ally.y), (unit.x, unit.y)), default=None)
            beside = 0.0 if nearest is None else offset((nearest.x, nearest.y))
            side = (-1 if beside > 0 else 1) if abs(beside) > 1e-9 else self._rng.choice((-1, 1))
        unit.dodge = seconds
        unit.dodge_heading = math.atan2(vy, vx) + side * math.pi / 2

    def _start_dodge(self, unit, shot):
        """Sidestep at right angles to a shot's path, away from it."""
        self._sidestep(unit, shot.x, shot.y, shot.vx, shot.vy, rules.DODGE_SECONDS)

    def _ready_to_fire(self, unit):
        """Whether an AI sub-unit is about to shoot: loaded, with a clear shot at its target in range.

        It then holds rather than dodging.
        """
        if unit.naval:
            def ready(slot, target):
                point = naval.lead_point(target, naval.mount_position(unit, slot), unit.weapon(slot))
                return (naval.can_fire(unit, slot, point, rules.AIM_TOLERANCE) and self._torpedo_in_window(unit, slot, target, point)
                        and self._clear_shot(unit, target, slot=slot))
            return any(unit.weapon(slot) is not None and unit.weapon_cooldown(slot) <= 0
                       and target is not None and target.alive and self._weapon_can_hurt(unit, target, slot) and ready(slot, target)
                       for slot, target in enumerate((unit.target, unit.secondary_target)))
        return any(unit.weapon(slot) is not None and unit.weapon_cooldown(slot) <= 0
                   and target is not None and target.alive and self._weapon_can_hurt(unit, target, slot)
                   and math.hypot(target.x - unit.x, target.y - unit.y) <= unit.weapon_range
                   and self._clear_shot(unit, target, slot=slot)
                   for slot, target in enumerate((unit.target, unit.secondary_target)))

    def _dodge_incoming(self, crowds):
        """AI sub-units that are not about to fire sidestep other sub-units' shots whose paths will pass close to them.

        Shots hurt allies too, so an ally's shot is dodged like an enemy's.
        """
        for shot in self.projectiles:
            if shot.kind == "torpedo":
                # Ships choose one maneuver against every torpedo and falling shell in _naval_evasion.
                continue
            if shot.gravity:
                self._dodge_falling_shell(shot, crowds)
                continue
            speed = math.hypot(shot.vx, shot.vy)
            lookahead = min(rules.DODGE_LOOKAHEAD, shot.remaining)
            reach = speed * lookahead
            end_x, end_y = shot.x + shot.vx / speed * reach, shot.y + shot.vy / speed * reach
            blocked = self.battlefield.first_hit((shot.x, shot.y), (end_x, end_y), shot.height,
                                                 shot.height + shot.vertical_speed * lookahead)
            if blocked is not None:
                reach *= blocked[0]
                end_x, end_y = shot.x + shot.vx / speed * reach, shot.y + shot.vy / speed * reach
            danger = rules.DODGE_DANGER * self.max_radius / rules.UNIT_RADIUS
            nearby = (unit for crowd in crowds for unit in crowd.within(
                min(shot.x, end_x) - danger, min(shot.y, end_y) - danger,
                max(shot.x, end_x) + danger, max(shot.y, end_y) + danger))
            for unit in nearby:
                if (unit is shot.source or not self._can_dodge(unit) or unit.dodge > 0 or self._ready_to_fire(unit)
                        or (unit.ram_committed and unit.target is not None
                            and math.hypot(unit.x - unit.target.x, unit.y - unit.target.y) <= rules.RAM_COMMIT_RANGE)):
                    continue
                along = ((unit.x - shot.x) * shot.vx + (unit.y - shot.y) * shot.vy) / speed
                across = ((unit.y - shot.y) * shot.vx - (unit.x - shot.x) * shot.vy) / speed
                if 0 <= along <= reach and abs(across) <= rules.DODGE_DANGER * unit.radius / rules.UNIT_RADIUS:
                    self._start_dodge(unit, shot)

    def _dodge_falling_shell(self, shot, crowds):
        """AI land units where a falling shell comes down step clear, whatever their speed, if they can in time.

        A falling shell is slow and lands where it was aimed, so even a slow unit can escape one.
        A unit dodges only when it can turn side-on and get clear before the shell drops onto it;
        otherwise it keeps aiming. Units about to fire hold, as they do for other shots.
        Ships steer clear of falling shells in _naval_evasion instead.
        """
        speed = math.hypot(shot.vx, shot.vy)
        land_x, land_y = shot.x + shot.vx * shot.remaining, shot.y + shot.vy * shot.remaining
        danger = rules.DODGE_DANGER * self.max_radius / rules.UNIT_RADIUS
        nearby = (unit for crowd in crowds for unit in crowd.within(
            min(shot.x, land_x) - danger, min(shot.y, land_y) - danger, max(shot.x, land_x) + danger, max(shot.y, land_y) + danger))
        for unit in nearby:
            if (unit.naval or unit is shot.source or unit is self.controlled or unit.dodge > 0 or self._ready_to_fire(unit)
                    or (unit.ram_committed and unit.target is not None
                        and math.hypot(unit.x - unit.target.x, unit.y - unit.target.y) <= rules.RAM_COMMIT_RANGE)):
                continue
            low, land = rules.falling_window(shot, self.battlefield.elevation((unit.x, unit.y)) + battle_terrain.BODY_HEIGHT)
            along = ((unit.x - shot.x) * shot.vx + (unit.y - shot.y) * shot.vy) / speed
            across = ((unit.y - shot.y) * shot.vx - (unit.x - shot.x) * shot.vy) / speed
            reach = rules.DODGE_DANGER * unit.radius / rules.UNIT_RADIUS
            if not (speed * low <= along <= speed * land and abs(across) <= reach):
                continue
            arrival = along / speed
            seconds, degrees, _turn_seconds = rules.MOBILITY[unit.shape]
            # Turning side-on takes up to a quarter turn; then the unit accelerates clear of the path.
            escape = math.pi / 2 / math.radians(degrees) + rules.time_to_shift(reach - abs(across), unit.max_speed, unit.max_speed / seconds)
            if escape <= arrival:
                self._sidestep(unit, shot.x, shot.y, shot.vx, shot.vy, arrival)

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
                self._division_retarget[index] += rules.RETARGET_SECONDS
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
        speed = unit.max_speed if unit.naval else unit.max_speed * unit.pace
        if speed < rules.RAM_MIN_SPEED:
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
        if arrival > rules.domain_config(unit.naval).ram_approach_range / rules.RAM_MIN_SPEED:
            return None
        point = target.x + target.vx * arrival, target.y + target.vy * arrival
        runup = max(0.0, math.dist((unit.x, unit.y), point) - unit.radius - target.radius)
        acceleration = unit.max_speed / rules.MOBILITY[unit.shape][0]
        impact_speed = min(speed, math.sqrt(max(0.0, unit.speed) ** 2 + 2 * acceleration * runup))
        distance = math.dist((unit.x, unit.y), point)
        closing = impact_speed - ((target.vx * (point[0] - unit.x) + target.vy * (point[1] - unit.y)) / distance
                                  if distance else 0.0)
        minimum_impact = rules.RAM_MIN_SPEED - (1e-9 if unit.naval else 0.0)
        if (impact_speed < minimum_impact or closing < minimum_impact
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
        domain = rules.domain_config(unit.naval)
        return (unit.data["health"] >= unit.data["max_health"] * rules.RAM_MIN_HEALTH
                and distance <= domain.ram_approach_range
                and rules.CONTACT_MASS[unit.shape] >= rules.CONTACT_MASS[target.shape] * rules.RAM_MASS_ADVANTAGE
                and self._can_hurt(unit, target) and threats <= support
                and tuple(sorted((unit.index, target.index))) not in self._contacts
                and (committed or (distance > rules.RAM_COMMIT_RANGE
                     and (all(not self._weapon_can_hurt(target, unit, slot)
                              or target.weapon_cooldown(slot) > target.weapon(slot)["interval"] / 2
                              for slot in (0, 1))
                          or target.data["health"] <= target.data["max_health"] * rules.RAM_WOUNDED_TARGET)))
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
                domain = rules.domain_config(unit.naval)
                ram_range = domain.ram_approach_range
                support_range = domain.ram_support_range
                nearby = [enemy for enemy in crowds[1 - side].around(unit.x, unit.y, ram_range)
                          if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= ram_range]
                if not nearby:
                    unit.ram_committed = False
                    continue
                friends = [friend for friend in crowds[side].around(unit.x, unit.y, support_range)
                           if math.hypot(friend.x - unit.x, friend.y - unit.y) <= support_range
                           and self.battlefield.clear_path((unit.x, unit.y), (friend.x, friend.y), unit.radius)]
                threats = sum(1 for enemy in crowds[1 - side].around(unit.x, unit.y, self.sight_range)
                              if math.hypot(enemy.x - unit.x, enemy.y - unit.y) <= enemy.weapon_range
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
        unit.push_vx = max(-rules.KNOCKBACK_MAX_SPEED, min(rules.KNOCKBACK_MAX_SPEED, vx - unit.speed * math.cos(unit.angle)))
        unit.push_vy = max(-rules.KNOCKBACK_MAX_SPEED, min(rules.KNOCKBACK_MAX_SPEED, vy - unit.speed * math.sin(unit.angle)))
