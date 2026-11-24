"""How ships steer, fire, and evade in a tactical battle."""

import math
from dataclasses import replace

import data.constants as c
from map_logic import battle_terrain, naval_battle as naval, tactical_rules as rules
from map_logic import tactical_units as units


class NavalBehavior:
    """BattleSimulation methods for naval courses, firing, evasion, and shells."""

    def _naval_ally_in_line(self, fighter, target, slot):
        weapon = fighter.weapon(slot)
        if weapon["projectile"] == "torpedo":
            return self._torpedo_ally_in_path(fighter, slot, predict_motion=False)
        mount = naval.mount_position(fighter, slot)
        point = naval.lead_point(target, mount, weapon)
        angle = math.atan2(point[1] - mount[1], point[0] - mount[0])
        # Launch from the muzzle with the real shot's arc, so the check sees what the fired shell will reach.
        start = naval.muzzle_position(fighter, slot, angle)
        flight, height, vertical = self._shell_arc(start, point, weapon)
        shot = units.Projectile(fighter, fighter.data, *start, math.cos(angle) * weapon["speed"], math.sin(angle) * weapon["speed"], flight, height=height, vertical_speed=vertical, gravity=weapon.get("gravity", 0.0), weapon_data=weapon)
        return next((ally for ally in self._sides[fighter.side] if ally is not fighter and naval.projectile_contact(shot, ally, flight, (ally.x, ally.y), movement=(ally.vx * flight, ally.vy * flight)) is not None), None)

    def _torpedo_ally_in_path(self, fighter, slot, *, predict_motion=True):
        """Check the actual muzzle/aim and its whole spread before an AI launch."""
        weapon = fighter.weapon(slot)
        angle = naval.clamp_launch_angle(fighter, slot, fighter.weapon_aim(slot))
        spread = self._shot_spread(fighter, weapon)
        start = naval.muzzle_position(fighter, slot, angle)
        edges = [naval.muzzle_position(fighter, slot, naval.clamp_launch_angle(fighter, slot, angle + error)) for error in (-spread, spread)]
        clearance = naval.TORPEDO_LAUNCH_CLEARANCE + max(math.dist(start, edge) for edge in edges)
        duration = weapon["range"] / weapon["speed"]
        shot = units.Projectile(fighter, fighter.data, *start, math.cos(angle) * weapon["speed"], math.sin(angle) * weapon["speed"], duration, height=0, weapon_data=weapon)
        for ally in self._sides[fighter.side]:
            if ally is fighter or not ally.alive:
                continue
            if naval.torpedo_corridor_contact(shot, ally, duration, spread, clearance) is not None:
                return ally
            if not predict_motion:
                continue
            horizon = min(naval.TORPEDO_LAUNCH_LOOKAHEAD, duration)
            end = shot.x + shot.vx * horizon, shot.y + shot.vy * horizon
            reach = ally.radius + ally.max_speed * horizon + clearance + math.tan(spread) * weapon["speed"] * horizon + math.hypot(ally.push_vx, ally.push_vy) * rules.KNOCKBACK_SECONDS
            if battle_terrain.circle_contact(start, end, (ally.x, ally.y), reach) is None:
                continue
            trial, ray = replace(ally), replace(shot)
            # Before a ship's first drive command, preserve its current motion.
            controls = ally.naval_controls
            if controls is None:
                controls = (ally.speed / ally.max_speed if ally.max_speed else 0.0, ally.turn_rate / math.radians(rules.MOBILITY[ally.shape][1]))
            elapsed = 0.0
            while elapsed < horizon - 1e-9:
                dt = min(rules.FIXED_STEP, horizon - elapsed)
                initial, heading = (trial.x, trial.y), trial.angle
                self._predict_naval_tick(trial, *controls, dt)
                trial.x, trial.y = self.battlefield.move(initial, (trial.x, trial.y), trial.radius)
                padding = clearance + math.tan(spread) * weapon["speed"] * (elapsed + dt)
                if naval.projectile_contact(ray, trial, dt, initial, start_angle=heading, padding=padding) is not None:
                    return ally
                ray.x += ray.vx * dt
                ray.y += ray.vy * dt
                elapsed += dt
        return None

    def _naval_firing_course(self, fighter, ally, target):
        """Clear a blocked torpedo path while still closing in, validated against hulls and edges.

        The ship steers TORPEDO_CLEARING_ANGLE off the line to its target, on the side away from
        the blocking ally, or on the other side if that is unsafe. It decides again every tick,
        so it turns back toward the target as soon as the path is clear.
        When turning either way is unsafe, as for two hulls bow to bow, back straight away to open
        room for the turn; hold only if backing away is unsafe too.
        """
        if fighter.max_speed <= 0:
            return 0.0, fighter.angle
        dx, dy = target.x - fighter.x, target.y - fighter.y
        self._sidestep(fighter, ally.x, ally.y, dx, dy, 0.0)
        toward = math.atan2(dy, dx)
        side = 1 if rules.wrap_angle(fighter.dodge_heading - toward) > 0 else -1
        for heading in (toward + side * naval.TORPEDO_CLEARING_ANGLE, toward - side * naval.TORPEDO_CLEARING_ANGLE):
            course = fighter.pace, heading
            if self._naval_maneuver_score(fighter, course, []) is not None:
                fighter.dodge_heading = heading
                return course
        reverse = -fighter.pace, fighter.angle
        if self._naval_maneuver_score(fighter, reverse, []) is not None:
            return reverse
        return 0.0, fighter.angle

    @staticmethod
    def torpedo_escape_seconds(target):
        """Seconds a ship needs to move half its hull length clear of a torpedo aimed at its center.

        It escapes by braking, reversing, or speeding up along its length, so the most it can change
        speed is its top speed plus its current speed: full reverse from full ahead.
        """
        distance = c.TACTICAL_BODIES[target.shape][0] / 2 + naval.TORPEDO_RADIUS
        acceleration = target.max_speed / rules.MOBILITY[target.shape][0]
        return rules.time_to_shift(distance, target.max_speed + abs(target.speed), acceleration)

    def _naval_launch_ready(self, fighter, slot, target, point=None):
        """Whether a mount could fire at ``target`` now, apart from its aim settling and allies in the way.

        The weapon must be able to hurt the target, the aim point must be within range and the mount's
        arc, and an AI torpedo must arrive within its launch window (_torpedo_in_window).
        """
        if target is None or not target.alive or not self._weapon_can_hurt(fighter, target, slot):
            return False
        start = naval.mount_position(fighter, slot)
        if point is None:
            point = naval.lead_point(target, start, fighter.weapon(slot))
        return (math.dist(start, point) <= fighter.weapon(slot)["range"]
                and naval.aim_allowed(fighter, slot, math.atan2(point[1] - start[1], point[0] - start[0]))
                and self._torpedo_in_window(fighter, slot, target, point))

    def _torpedo_in_window(self, fighter, slot, target, point):
        """An AI torpedo launches only when it arrives at ``point`` within TORPEDO_LAUNCH_WINDOW_STRETCH
        times the seconds ``target`` needs to move clear of it."""
        weapon = fighter.weapon(slot)
        if weapon["projectile"] != "torpedo" or point is None:
            return True
        flight = math.dist(naval.mount_position(fighter, slot), point) / weapon["speed"]
        return flight <= self.torpedo_escape_seconds(target) * naval.TORPEDO_LAUNCH_WINDOW_STRETCH

    def _naval_course(self, fighter, target):
        dx, dy = target.x - fighter.x, target.y - fighter.y
        distance = math.hypot(dx, dy)
        toward = math.atan2(dy, dx)
        if fighter.dodge > 0:
            return fighter.pace, fighter.dodge_heading
        if fighter.ram_committed:
            point = self._ram_point(fighter, target)
            if point is not None:
                return 1.0, math.atan2(point[1] - fighter.y, point[0] - fighter.x)
        if fighter.data["health"] < fighter.data["max_health"] * rules.FALL_BACK_HEALTH and self._healthy_sides[fighter.side]:
            return (fighter.pace, toward + math.pi) if distance < naval.WITHDRAW_RANGE else (0.0, toward)
        if self.elapsed < fighter.start_delay:
            return 0.0, fighter.angle
        reach = min(naval.ENGAGEMENT_RANGE, fighter.weapon_range * 0.8)
        if all(mount.weapon == "torpedo" for mount in naval.mounts(fighter.shape)):
            # A torpedo-only ship closes in until its torpedoes arrive before the target can move clear.
            reach = min(reach, fighter.weapon(0)["speed"] * self.torpedo_escape_seconds(target))
        preferred = reach * fighter.hold
        broadside = naval.mounts(fighter.shape) is naval.BROADSIDES
        if distance > preferred:
            if broadside and distance <= fighter.weapon_range:
                # Close in at an angle, so the nearer broadside bears on the way.
                offsets = (naval.BROADSIDE_APPROACH_ANGLE, -naval.BROADSIDE_APPROACH_ANGLE)
                return fighter.pace, min((toward + offset for offset in offsets), key=lambda angle: abs(rules.wrap_angle(angle - fighter.angle)))
            return fighter.pace, toward
        if broadside:
            # Present the nearer broadside instead of pointing the bow at the enemy.
            heading = min((toward + math.pi / 2, toward - math.pi / 2), key=lambda angle: abs(rules.wrap_angle(angle - fighter.angle)))
            return 0.0, heading
        return (-fighter.pace if distance < preferred * rules.SKIRMISH_BACK_OFF else 0.0), toward

    def _drive_naval(self, fighter, dt, shots, enemies=None):
        """Both sides and the player use the same mount sectors and firing checks."""
        controlled = fighter is self.controlled
        if controlled:
            throttle, turn = self._throttle, self._turn
            if self._move_direction is not None:
                dx, dy = self._move_direction
                strength = min(1.0, math.hypot(dx, dy))
                throttle, turn = self._heading_controls(fighter, strength, math.atan2(dy, dx)) if strength else (0.0, 0.0)
        else:
            blocked_course = None
            fighter.retarget -= dt
            if fighter.target is None or not fighter.target.alive or fighter.retarget <= 0:
                fighter.retarget = rules.RETARGET_SECONDS
                if not fighter.ram_committed:
                    fighter.target = self._choose_target(fighter, enemies)
                fighter.secondary_target = None
            fighter.dodge = max(0.0, fighter.dodge - dt)
            if fighter.dodge <= 0 and not fighter.ram_committed:
                for slot in range(len(naval.mounts(fighter.shape))):
                    # Clear a line of fire only when that weapon could fire down it now.
                    if fighter.weapon_cooldown(slot) > 0 or not self._naval_launch_ready(fighter, slot, fighter.target):
                        continue
                    ally = self._naval_ally_in_line(fighter, fighter.target, slot)
                    if ally is not None:
                        if fighter.weapon(slot)["projectile"] == "torpedo":
                            blocked_course = self._naval_firing_course(fighter, ally, fighter.target)
                        else:
                            self._sidestep(fighter, ally.x, ally.y, fighter.target.x - fighter.x, fighter.target.y - fighter.y, rules.LINE_SHIFT_SECONDS)
                        break
            throttle, heading = blocked_course or self._naval_course(fighter, fighter.target)
            if blocked_course is None and fighter.dodge <= 0 and not fighter.ram_committed:
                throttle, heading = self._pass_allies(fighter, throttle, heading)
            throttle, heading = self._naval_evasion(fighter, (throttle, heading))
            throttle, turn = self._heading_controls(fighter, throttle, heading)
            throttle = self._ally_safe_throttle(fighter, throttle)
        fighter.naval_controls = throttle, turn
        self._steer(fighter, turn, dt)
        self._accelerate(fighter, throttle, dt)
        for slot, mount in enumerate(naval.mounts(fighter.shape)):
            weapon = fighter.weapon(slot)
            start = naval.mount_position(fighter, slot)
            if controlled:
                point = self._aim_point
                wants_fire = self._secondary_fire if slot else self._fire
            else:
                target = fighter.target
                # A second turret may engage another enemy when the first target is outside its sector.
                candidates = [target, *(enemy for bucket in enemies.cells.values() for enemy in bucket if enemy is not target)]
                legal = [enemy for enemy in candidates if self._weapon_can_hurt(fighter, enemy, slot) and naval.aim_allowed(fighter, slot, math.atan2(enemy.y - start[1], enemy.x - start[0]))]
                gun_target = min(legal, key=lambda enemy: math.dist(start, (enemy.x, enemy.y)), default=target)
                if slot:
                    fighter.secondary_target = gun_target
                point = naval.lead_point(gun_target, start, weapon)
                wants_fire = self._naval_launch_ready(fighter, slot, gun_target, point) and self._clear_shot(fighter, gun_target, slot=slot)
            fighter.gun_points[slot] = point
            if point is None:
                continue
            desired = math.atan2(point[1] - start[1], point[0] - start[0])
            aim = naval.slew(fighter, slot, desired, dt)
            if slot:
                fighter.secondary_aim = aim
            else:
                fighter.aim = aim
            if wants_fire and fighter.weapon_cooldown(slot) <= 0 and naval.can_fire(fighter, slot, point, rules.AIM_TOLERANCE):
                self._queue_shot(fighter, shots, slot)

    def _fire_naval_shot(self, fighter, slot):
        weapon = fighter.weapon(slot)
        if not naval.aim_allowed(fighter, slot, fighter.weapon_aim(slot)):
            return
        point = fighter.gun_points[slot]
        if point is not None and not naval.can_fire(fighter, slot, point, rules.AIM_TOLERANCE):
            return
        if weapon["projectile"] == "torpedo" and fighter is not self.controlled and self._torpedo_ally_in_path(fighter, slot) is not None:
            return
        start = naval.muzzle_position(fighter, slot)
        flight, height, vertical = self._shell_arc(start, point, weapon)
        angle = fighter.weapon_aim(slot) + self._rng.uniform(-self._shot_spread(fighter, weapon), self._shot_spread(fighter, weapon))
        gravity = weapon.get("gravity", 0.0)
        remaining = flight if gravity else weapon["range"] / weapon["speed"]
        if weapon["projectile"] == "torpedo":
            angle = naval.clamp_launch_angle(fighter, slot, angle)
            start = naval.muzzle_position(fighter, slot, angle)
            self._consume_shot(fighter, slot)
            # A torpedo has no range limit: it runs until it leaves the map.
            remaining = naval.time_to_leave_map(start, angle, weapon["speed"], self.battlefield.size)
        self.projectiles.append(units.Projectile(fighter, dict(fighter.data), *start, math.cos(angle) * weapon["speed"], math.sin(angle) * weapon["speed"], remaining, height=height, vertical_speed=vertical, gravity=gravity, weapon_data=dict(weapon), attack_share=fighter.attack_share * naval.mounts(fighter.shape)[slot].attack_share))
        fighter.fired_weapon = slot
        fighter.muzzle = fighter.mount_muzzles[slot] = c.TACTICAL_MUZZLE_SECONDS
        fighter.recoil = fighter.mount_recoils[slot] = c.TACTICAL_MUZZLE_SECONDS if gravity else 0.0
        if self.on_shot is not None:
            self.on_shot(fighter)

    def _predict_naval_tick(self, trial, throttle, turn, dt):
        """Advance an isolated motion prediction with the live steering/acceleration rules."""
        self._steer(trial, turn, dt)
        self._accelerate(trial, throttle, dt)
        trial.x += (math.cos(trial.angle) * trial.speed + trial.push_vx) * dt
        trial.y += (math.sin(trial.angle) * trial.speed + trial.push_vy) * dt
        decay = max(0.0, 1.0 - dt / rules.KNOCKBACK_SECONDS)
        trial.push_vx *= decay
        trial.push_vy *= decay

    def _naval_maneuver_score(self, unit, course, threats):
        """Predict only hull motion, using the live steering and acceleration helpers."""
        trial = replace(unit)
        shots = [replace(shot) for shot in threats]
        horizon = min(naval.TORPEDO_LOOKAHEAD, max((shot.remaining for shot in shots), default=naval.TORPEDO_LAUNCH_LOOKAHEAD))
        drift = math.hypot(unit.push_vx, unit.push_vy) * rules.KNOCKBACK_SECONDS
        allies = [ally for ally in self.fighters if ally is not unit and ally.alive and ally.side == unit.side
                  and math.dist((unit.x, unit.y), (ally.x, ally.y)) <= unit.radius + ally.radius + drift + unit.max_speed * max(horizon, rules.MOBILITY[unit.shape][0] / 2) + math.hypot(ally.vx, ally.vy) * horizon]
        elapsed, hit_at, clearance = 0.0, math.inf, math.inf
        while elapsed < horizon - 1e-9:
            dt = min(naval.EVASION_SAMPLE_SECONDS, horizon - elapsed)
            initial, angle = (trial.x, trial.y), trial.angle
            poses = [(0.0, trial.x, trial.y, trial.angle)]
            segment = 0.0
            while segment < dt - 1e-9:
                tick = min(rules.FIXED_STEP, dt - segment)
                throttle, turn = self._heading_controls(trial, *course)
                throttle = self._ally_safe_throttle(trial, throttle, original=unit, time_ahead=elapsed + segment, allies=allies)
                self._predict_naval_tick(trial, throttle, turn, tick)
                if not self.battlefield.walkable((trial.x, trial.y), trial.radius):
                    return None
                segment += tick
                poses.append((segment, trial.x, trial.y, trial.angle))
            # Bound every fixed-tick departure from the sampled straight/rotating sweep.
            # Padding makes the cheaper sampled collision checks conservative, never narrower.
            turn_angle = rules.wrap_angle(trial.angle - angle)
            padding = max(math.dist((x, y), (initial[0] + (trial.x - initial[0]) * time / dt, initial[1] + (trial.y - initial[1]) * time / dt)) + trial.radius * abs(rules.wrap_angle(heading - angle - turn_angle * time / dt)) for time, x, y, heading in poses)
            for ally in allies:
                # Allies keep their current motion; the planner never runs another unit's AI.
                center = ally.x + ally.vx * elapsed, ally.y + ally.vy * elapsed
                if math.dist(initial, center) > trial.radius + ally.radius + (trial.max_speed + math.hypot(ally.vx, ally.vy)) * dt:
                    continue
                movement = (trial.x - initial[0]) / dt, (trial.y - initial[1]) / dt
                if naval.body_contact(trial, ally, movement, (ally.vx, ally.vy), dt, first_position=initial, second_position=center, start_angle=angle, padding=padding) is not None:
                    return None
            for shot in shots:
                flight = min(dt, shot.remaining)
                if flight <= 0:
                    continue
                motion = (trial.x - initial[0]) * flight / dt, (trial.y - initial[1]) * flight / dt
                fraction = naval.projectile_contact(shot, trial, flight, initial, movement=motion, start_angle=angle, end_angle=angle + turn_angle * flight / dt, padding=padding)
                if fraction is not None:
                    hit_at = min(hit_at, elapsed + fraction * flight)
                shot.x += shot.vx * flight
                shot.y += shot.vy * flight
                if shot.gravity:
                    shot.height = naval.shell_height(shot, flight)
                    shot.vertical_speed -= shot.gravity * flight
                shot.remaining -= flight
                # A shell still above hull height passes over, so only its falling end counts toward clearance.
                if not shot.gravity or (shot.height <= c.TACTICAL_NAVAL_HULL_HEIGHT and naval.shell_descending(shot, 0.0)):
                    clearance = min(clearance, naval.hull_clearance((shot.x, shot.y), trial, (trial.x, trial.y), trial.angle) - naval.TORPEDO_RADIUS - padding)
            elapsed += dt
            if hit_at != math.inf:
                break
        return hit_at, clearance, -abs(rules.wrap_angle(course[1] - unit.angle)), -abs(course[0] - unit.speed / unit.max_speed)

    def _naval_threats(self, unit):
        """Torpedoes and falling shells, from either side, that could reach this hull wherever it steers.

        A torpedo counts within TORPEDO_LOOKAHEAD. A shell counts only along the falling end of its
        flight, where it drops through hull height before it lands; higher up it passes overhead.
        """
        drift = unit.radius + math.hypot(unit.push_vx, unit.push_vy) * rules.KNOCKBACK_SECONDS
        threats = []
        for shot in self.projectiles:
            if shot.source is unit or shot.remaining <= 0:
                continue
            if shot.kind == "torpedo":
                start, end = 0.0, min(naval.TORPEDO_LOOKAHEAD, shot.remaining)
            elif shot.gravity:
                start, end = rules.falling_window(shot, c.TACTICAL_NAVAL_HULL_HEIGHT)
            else:
                continue
            path = [(shot.x + shot.vx * seconds, shot.y + shot.vy * seconds) for seconds in (start, end)]
            if battle_terrain.circle_contact(*path, (unit.x, unit.y), drift + unit.max_speed * end) is not None:
                threats.append(shot)
        return threats

    def _naval_evasion(self, unit, normal_course):
        """Steer clear of torpedoes and falling shells together.

        Keep safe maneuvers stable, and reject turns that sweep the bow or stern into danger.
        """
        if unit is self.controlled or unit.max_speed <= 0:
            unit.evasion_course = None
            return normal_course
        threats = self._naval_threats(unit)
        if not threats:
            unit.evasion_course = None
            return normal_course
        if unit.evasion_course is not None:
            unit.ram_committed = False
        if self.elapsed < unit.evasion_next_check:
            return unit.evasion_course or normal_course
        # Spread decisions across fixed ticks, as deployment already does for target selection.
        cycle = max(1, round(rules.RETARGET_SECONDS / rules.FIXED_STEP))
        tick = round(self.elapsed / rules.FIXED_STEP)
        unit.evasion_next_check = (tick + ((unit.index - tick) % cycle or cycle)) * rules.FIXED_STEP
        normal_score = self._naval_maneuver_score(unit, normal_course, threats)
        if normal_score is not None and normal_score[0] == math.inf and (unit.evasion_course is None or normal_score[1] >= naval.EVASION_CLEARANCE):
            unit.evasion_course = None
            return normal_course
        if unit.evasion_course is not None:
            score = self._naval_maneuver_score(unit, unit.evasion_course, threats)
            if score is not None and score[0] == math.inf:
                return unit.evasion_course
        courses = [normal_course, (unit.speed / unit.max_speed, unit.angle), (1.0, unit.angle), (0.0, unit.angle), (-1.0, unit.angle)]
        courses.extend((1.0, unit.angle + angle) for angle in naval.EVASION_TURN_ANGLES)
        best, best_score = normal_course, normal_score
        for course in dict.fromkeys(courses):
            if course == normal_course:
                continue
            score = self._naval_maneuver_score(unit, course, threats)
            if score is not None and (best_score is None or score > best_score):
                best, best_score = course, score
            # A straight escape with comfortable clearance avoids an unnecessary hull swing.
            if best_score is not None and best_score[0] == math.inf and best_score[1] >= naval.EVASION_CLEARANCE and abs(rules.wrap_angle(best[1] - unit.angle)) < 1e-9:
                break
        unit.evasion_course = best
        unit.ram_committed = False
        return best

    def _advance_naval_projectile(self, shot, dt, living, start_positions, *, start_angles=None):
        flight = min(dt, shot.remaining)
        if flight <= 0:
            return False, []
        if shot.gravity:
            flight = min(flight, naval.descending_time(shot.height, shot.vertical_speed, shot.gravity))
        collisions = []
        for target in living:
            initial = start_positions[target.index]
            # A projectile expiring partway through a tick sees that same share of ship motion.
            movement = (target.x - initial[0]) * flight / dt, (target.y - initial[1]) * flight / dt
            initial_angle = target.angle if start_angles is None else start_angles[target.index]
            fraction = naval.projectile_contact(shot, target, flight, initial, movement=movement, start_angle=initial_angle, end_angle=initial_angle + rules.wrap_angle(target.angle - initial_angle) * flight / dt)
            if fraction is not None:
                collisions.append((fraction, target.index, target))
        hit = min(collisions, default=None, key=lambda item: (item[0], item[1]))
        if hit is not None:
            fraction, _, target = hit
            x, y = shot.x + shot.vx * flight * fraction, shot.y + shot.vy * flight * fraction
            # Naval weapons have no range falloff: a hit does full damage at any distance.
            loss = self.weapon_damage(shot.source_data, target.data, shot.attack_share, shot.weapon_data, target.shape)
            self.impacts.append((x, y, c.TACTICAL_IMPACT_SECONDS, self._impact_kind(shot)))
            return False, [(target, loss, shot.source, "shot", shot.kind, (x, y))]
        shot.x += shot.vx * flight
        shot.y += shot.vy * flight
        shot.height = naval.shell_height(shot, flight)
        shot.vertical_speed -= shot.gravity * flight
        shot.remaining -= flight
        if shot.remaining <= 1e-9 or (shot.gravity and shot.height <= 1e-7):
            self.impacts.append((shot.x, shot.y, c.TACTICAL_IMPACT_SECONDS, self._impact_kind(shot)))
            return False, []
        return True, []
