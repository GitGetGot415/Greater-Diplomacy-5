"""Naval terrain preparation, firing legality, physical projectiles, and setup callbacks."""

import copy
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pygame

import data.constants as c
from data import queries
from map_logic import custom_battle as combat, naval_battle as naval
from screens.game import custom_battle as ui
from tests.test_custom_battle import unit_stats
from ui.rendering.font_manager import fonts


def fixture_library():
    library = {f"Fixture {shape} I": dict(unit_stats(family, health=1000, attack=100, defense=0, speed=3), naval_unit=True) for family, shape in naval.FAMILY_SHAPES.items()}
    library["Fixture Land I"] = unit_stats(health=1000, attack=100, defense=0, speed=3)
    return library


class NavalBattleTests(unittest.TestCase):
    def setUp(self):
        self.library = fixture_library()
        # Projectile mechanics use explicit fixture pacing rather than current weapon tuning.
        self.enterContext(patch.dict(c.TACTICAL_WEAPONS, {
            "artillery_shell": dict(label="Fixture shell", interval=1.0, rounds=1, reload=1.0, speed=200.0, spread=0.0, damage=1.0, penetration=0.0, shell=True, soft_only=False, projectile="artillery_shell", range=2000.0, gravity=100.0),
            "torpedo": dict(label="Fixture torpedo", interval=1.0, rounds=1, reload=1.0, speed=100.0, spread=0.0, damage=1.0, penetration=0.0, shell=False, soft_only=False, projectile="torpedo", range=2000.0),
        }))
        self.enterContext(patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", 1.0))

    def simulation(self, friendly="destroyer", enemy="destroyer", *, controlled=0, terrain="ocean"):
        simulation = combat.BattleSimulation(self.library, [f"Fixture {friendly} I"], [f"Fixture {enemy} I"], terrain=terrain, controlled_index=controlled, seed=7)
        for index, fighter in enumerate(simulation.fighters):
            fighter.x, fighter.y = 1500 + index * 600, 1500
        return simulation

    def test_terrain_round_trip_keeps_identity_owner_and_health_fraction(self):
        for name in self.library:
            original = combat.create_battle_unit(name, "Fixture A", self.library, "plains")
            original["health"] *= 0.37
            ocean = combat.prepare_battle_unit(original, self.library, "ocean")
            land = combat.prepare_battle_unit(ocean, self.library, "plains")
            self.assertEqual((land["type"], land["unit_id"], land["owner"]), (original["type"], original["unit_id"], original["owner"]))
            self.assertAlmostEqual(land["health"] / land["max_health"], 0.37)
            self.assertIn(combat.unit_shape(ocean["type"], self.library), naval.SHAPES)
            self.assertFalse("Convoy (Truck (" in ocean["type"])
            if self.library[name]["naval_unit"]:
                self.assertEqual(ocean["type"], name)
                self.assertEqual(ocean["attack"], self.library[name]["attack"])
            else:
                self.assertEqual(ocean["type"], f"Convoy ({name})")
                self.assertEqual(ocean["attack"], c.CONVOY_ATK)

    def test_every_water_terrain_deploys_one_wounded_ship_per_division(self):
        before = copy.deepcopy(self.library)
        for terrain in c.WATER_TERRAINS:
            entries = [queries.create_unit_dict(name, "Fixture A", self.library) for name in self.library]
            for entry in entries:
                entry["health"] *= 0.37
            simulation = combat.BattleSimulation(self.library, entries, entries, terrain=terrain)
            self.assertEqual(len(simulation.fighters), len(entries) * 2)
            self.assertTrue(all(len(division) == 1 for division in simulation.divisions))
            self.assertTrue(all(fighter.naval for fighter in simulation.fighters))
            self.assertTrue(all(math.isclose(simulation.division_health_fraction(index), 0.37) for index in range(len(entries) * 2)))
            self.assertEqual(simulation.battlefield.features, [])
        self.assertEqual(self.library, before)

    def test_broadside_and_forward_sectors_follow_rotating_hull(self):
        for family in ("carrack", "ironclad", "submarine"):
            fighter = self.simulation(family).controlled
            for heading in (0.0, 0.9, math.pi):
                fighter.angle = heading
                if family == "submarine":
                    self.assertTrue(naval.aim_allowed(fighter, 0, heading))
                    self.assertFalse(naval.aim_allowed(fighter, 0, heading + math.pi / 2))
                else:
                    self.assertTrue(naval.aim_allowed(fighter, 0, heading + math.pi / 2))
                    self.assertTrue(naval.aim_allowed(fighter, 1, heading - math.pi / 2))
                    self.assertFalse(any(naval.aim_allowed(fighter, slot, heading) for slot in (0, 1)))
                    self.assertFalse(any(naval.aim_allowed(fighter, slot, heading + math.pi) for slot in (0, 1)))

    def test_two_turrets_cover_all_bearings_and_share_attack(self):
        fighter = self.simulation().controlled
        for degrees in range(360):
            self.assertTrue(any(naval.aim_allowed(fighter, slot, math.radians(degrees)) for slot in (0, 1)))
        self.assertFalse(naval.aim_allowed(fighter, 0, math.pi))
        self.assertFalse(naval.aim_allowed(fighter, 1, 0))
        self.assertAlmostEqual(sum(mount.attack_share for mount in naval.mounts(fighter.shape)), 1.0)
        self.assertNotEqual(naval.mount_position(fighter, 0), naval.mount_position(fighter, 1))

    def test_player_cannot_fire_outside_a_mount_sector_or_range(self):
        simulation = self.simulation("submarine")
        fighter = simulation.controlled
        for point in ((fighter.x, fighter.y + 300), (fighter.x - 300, fighter.y), (fighter.x + fighter.weapon_range + 100, fighter.y)):
            simulation.set_player_input(fire=True, aim_point=point)
            shots = []
            simulation._drive_player(fighter, 1.0, shots)
            self.assertEqual(shots, [])
        simulation.set_player_input(fire=True, aim_point=(fighter.x + 300, fighter.y))
        simulation._drive_player(fighter, 1.0, shots)
        self.assertEqual(shots, [(fighter, 0)])

    def test_mounts_aim_and_reload_independently(self):
        simulation = self.simulation()
        fighter = simulation.controlled
        fighter.secondary_aim = math.pi / 2
        simulation.set_player_input(fire=True, secondary_fire=True, aim_point=(fighter.x, fighter.y + 500))
        shots = []
        simulation._drive_player(fighter, 0.1, shots)
        self.assertNotEqual(fighter.aim, fighter.secondary_aim)
        self.assertTrue(any(slot == 1 for _, slot in shots))
        self.assertEqual(fighter.cooldown, 0)
        self.assertGreater(fighter.secondary_cooldown, 0)

    def test_ai_turrets_can_engage_different_targets_in_their_sectors(self):
        simulation = self.simulation(controlled=None)
        source, front = simulation.fighters
        rear = combat.Fighter(dict(front.data), 1, source.x - 600, source.y, front.shape, index=2)
        simulation._sides = [[source], [front, rear]]
        simulation.elapsed = 10
        shots = []
        simulation._drive_ai(source, combat._Grid([front, rear], combat.TARGET_CELL), 1.0, shots, (source.x, source.y), front)
        self.assertEqual({slot for _, slot in shots}, {0, 1})
        self.assertIs(source.secondary_target, rear)
        self.assertGreater(source.gun_points[0][0], source.x)
        self.assertLess(source.gun_points[1][0], source.x)

    def test_broadside_ai_turns_sideways_on_both_sides(self):
        simulation = self.simulation("carrack", "ironclad", controlled=None)
        simulation.elapsed = 10
        for fighter, target in (simulation.fighters, reversed(simulation.fighters)):
            throttle, heading = simulation._naval_course(fighter, target)
            toward = math.atan2(target.y - fighter.y, target.x - fighter.x)
            self.assertEqual(throttle, 0)
            self.assertAlmostEqual(abs(naval.wrap(heading - toward)), math.pi / 2)

    def test_shell_rises_falls_and_hits_a_stationary_ship(self):
        simulation = self.simulation()
        source, target = simulation.fighters
        source.gun_points[0] = (target.x, target.y)
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        self.assertEqual(shot.kind, "artillery_shell")
        self.assertGreater(naval.shell_height(shot, shot.remaining / 2), shot.height)
        self.assertAlmostEqual(naval.shell_height(shot, shot.remaining), 0)
        initial = {fighter.index: (fighter.x, fighter.y) for fighter in simulation.fighters}
        hits = []
        while shot.remaining > 1e-9:
            keep, hits = simulation._advance_naval_projectile(shot, 0.1, simulation.fighters, initial)
            if not keep:
                break
        self.assertEqual(hits[0][0], target)
        self.assertGreater(hits[0][1], 0)
        self.assertEqual(shot.source_data["attack"], source.data["attack"])

    def test_airborne_shell_passes_over_an_intervening_hull(self):
        simulation = self.simulation()
        source, target = simulation.fighters
        source.gun_points[0] = (target.x, target.y)
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        target.x = (shot.x + source.gun_points[0][0]) / 2
        fraction = naval.projectile_contact(shot, target, shot.remaining, (target.x, target.y))
        self.assertIsNone(fraction)

    def test_descending_shell_hits_within_one_long_sweep(self):
        simulation = self.simulation()
        source, target = simulation.fighters
        source.gun_points[0] = (target.x, target.y)
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        fraction = naval.projectile_contact(shot, target, shot.remaining, (target.x, target.y))
        self.assertIsNotNone(fraction)
        self.assertLessEqual(naval.shell_height(shot, shot.remaining * fraction), c.TACTICAL_NAVAL_HULL_HEIGHT + 1e-7)

    def test_shell_splashes_at_fixed_aim_point_after_target_moves(self):
        simulation = self.simulation()
        source, target = simulation.fighters
        source.gun_points[0] = (target.x, target.y)
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        target.y += 500
        initial = {fighter.index: (fighter.x, fighter.y) for fighter in simulation.fighters}
        keep, hits = simulation._advance_naval_projectile(shot, shot.remaining, simulation.fighters, initial)
        self.assertFalse(keep)
        self.assertEqual(hits, [])
        self.assertAlmostEqual(shot.x, source.gun_points[0][0])
        self.assertAlmostEqual(shot.height, 0)

    def test_torpedo_hits_first_ship_including_friendly_without_penetration(self):
        simulation = self.simulation("submarine")
        source, target = simulation.fighters
        source.gun_points[0] = (target.x, target.y)
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        target.side = source.side
        initial = {fighter.index: (fighter.x, fighter.y) for fighter in simulation.fighters}
        keep, hits = simulation._advance_naval_projectile(shot, shot.remaining, simulation.fighters, initial)
        self.assertFalse(keep)
        self.assertEqual(hits[0][0], target)
        self.assertGreater(hits[0][1], 0)
        self.assertEqual(shot.kind, "torpedo")

    def test_moving_ship_crosses_torpedo_between_ticks(self):
        simulation = self.simulation("submarine")
        source, target = simulation.fighters
        target.x, target.y, target.angle = 1600, 1700, math.pi / 2
        shot = combat.Projectile(source, dict(source.data), 1550, 1500, 100, 0, 1, height=0, weapon_data=dict(c.TACTICAL_WEAPONS["torpedo"]))
        self.assertIsNotNone(naval.projectile_contact(shot, target, 1, (1600, 1300)))

    def test_torpedo_muzzle_clears_hull_and_expired_miss_is_removed(self):
        simulation = self.simulation("submarine")
        source, target = simulation.fighters
        source.gun_points[0] = (target.x, target.y)
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        self.assertIsNone(naval.hull_interval((shot.x, shot.y), (shot.x, shot.y), source))
        target.y += 500
        initial = {fighter.index: (fighter.x, fighter.y) for fighter in simulation.fighters}
        keep, hits = simulation._advance_naval_projectile(shot, shot.remaining, simulation.fighters, initial)
        self.assertFalse(keep)
        self.assertEqual(hits, [])

    def test_player_and_ai_fire_four_rapid_single_torpedoes_then_reload(self):
        weapon = c.TACTICAL_WEAPONS["torpedo"]
        weapon.update(rounds=4, interval=0.01, reload=1.0)
        for controlled in (0, None):
            with self.subTest(controlled=controlled):
                simulation = self.simulation("submarine", controlled=controlled)
                source, target = simulation.fighters
                source.data["speed"] = target.data["speed"] = 0
                target.cooldown = target.secondary_cooldown = 1000
                fired = []
                simulation.on_shot = lambda fighter: fired.append((fighter, simulation.elapsed))
                if controlled is not None:
                    simulation.set_player_input(fire=True, aim_point=(target.x, target.y))
                for number in range(1, weapon["rounds"] + 1):
                    simulation.advance(combat.FIXED_STEP)
                    self.assertEqual(len(simulation.projectiles), number)
                    self.assertEqual(source.primary_rounds, number % weapon["rounds"])
                    wait = weapon["interval"] if number < weapon["rounds"] else weapon["reload"]
                    self.assertEqual(source.cooldown, wait)
                    self.assertEqual(source.reload_duration(), wait)
                self.assertTrue(all(shot.attack_share == source.attack_share for shot in simulation.projectiles))
                simulation.paused = True
                simulation.advance(weapon["reload"])
                self.assertEqual(source.cooldown, weapon["reload"])
                simulation.paused = False
                simulation.advance(weapon["reload"] / 2)
                self.assertEqual(len(fired), weapon["rounds"])
                for _ in range(math.ceil(weapon["reload"] / combat.FIXED_STEP) + 2):
                    simulation.advance(combat.FIXED_STEP)
                    if len(fired) > weapon["rounds"]:
                        break
                self.assertEqual(len(fired), weapon["rounds"] + 1)
                self.assertGreaterEqual(fired[-1][1] - fired[-2][1], weapon["reload"] - 1e-9)
                self.assertLessEqual(fired[-1][1] - fired[-2][1], weapon["reload"] + combat.FIXED_STEP + 1e-9)
                self.assertEqual(source.cooldown, weapon["interval"])

    def test_releasing_fire_does_not_queue_remaining_torpedoes(self):
        weapon = c.TACTICAL_WEAPONS["torpedo"]
        weapon.update(rounds=4, interval=0.01, reload=1.0)
        simulation = self.simulation("submarine")
        source, target = simulation.fighters
        source.data["speed"] = target.data["speed"] = 0
        target.cooldown = target.secondary_cooldown = 1000
        fired = []
        simulation.on_shot = fired.append
        simulation.set_player_input(fire=True, aim_point=(target.x, target.y))
        simulation.advance(2 * combat.FIXED_STEP)
        self.assertEqual(len(fired), 2)
        simulation.set_player_input()
        simulation.advance(weapon["reload"])
        self.assertEqual(len(fired), 2)
        simulation.set_player_input(fire=True, aim_point=(target.x, target.y))
        simulation.advance(2 * combat.FIXED_STEP)
        self.assertEqual(len(fired), 4)
        self.assertEqual(source.cooldown, weapon["reload"])

    def test_torpedo_stays_forward_and_clears_hull_at_sector_edges(self):
        c.TACTICAL_WEAPONS["torpedo"]["spread"] = 2.0
        simulation = self.simulation("submarine")
        source = simulation.controlled
        bearing, arc = naval.sector(source, 0)
        for aim in (bearing - arc / 2, bearing + arc / 2):
            source.aim = aim
            simulation.projectiles.clear()
            simulation._fire_shot(source)
            self.assertEqual(len(simulation.projectiles), 1)
            for shot in simulation.projectiles:
                self.assertTrue(naval.aim_allowed(source, 0, math.atan2(shot.vy, shot.vx)))
                self.assertIsNone(naval.hull_interval((shot.x, shot.y), (shot.x, shot.y), source))

    def test_ai_checks_the_current_torpedo_path_for_friendly_ships(self):
        simulation = self.simulation("submarine")
        source, target = simulation.fighters
        distance = 700
        angle = math.radians(6)
        ally = combat.Fighter(dict(target.data), source.side, source.x + distance * math.cos(angle), source.y + distance * math.sin(angle), "convoy", index=2)
        simulation._sides = [[source, ally], [target]]
        self.assertIsNone(simulation._naval_ally_in_line(source, target, 0))
        ally.y = source.y
        self.assertIs(simulation._naval_ally_in_line(source, target, 0), ally)

    def test_slow_ai_ships_on_both_sides_evade_even_when_ready_to_fire_or_ramming(self):
        for side in (0, 1):
            for friendly in (False, True):
                with self.subTest(side=side, friendly=friendly):
                    simulation = self.simulation(controlled=None)
                    unit, source = simulation.fighters[::1 if side == 0 else -1]
                    unit.data["speed"] = 1
                    source.side = unit.side if friendly else 1 - unit.side
                    unit.ram_committed = True
                    shot = combat.Projectile(source, dict(source.data), unit.x + 600, unit.y, -100, 0, 10, height=0, weapon_data=dict(c.TACTICAL_WEAPONS["torpedo"]))
                    simulation.projectiles = [shot]
                    simulation._sides = [[fighter for fighter in simulation.fighters if fighter.side == team] for team in (0, 1)]
                    with patch.object(simulation, "_ready_to_fire", return_value=True):
                        course = simulation._naval_evasion(unit, (0.0, unit.angle))
                    self.assertIsNotNone(unit.evasion_course)
                    self.assertFalse(unit.ram_committed)
                    self.assertEqual(simulation._naval_maneuver_score(unit, course, [shot])[0], math.inf)

    def test_ships_ignore_receding_expired_or_missing_torpedoes_and_keep_player_control(self):
        simulation = self.simulation(controlled=None)
        source, unit = simulation.fighters
        unit.data["speed"] = 1
        cases = ((unit.x + 600, unit.y, 100, 0, 10), (unit.x + 600, unit.y + 300, -100, 0, 10), (unit.x + 600, unit.y, -100, 0, 0.1))
        for x, y, vx, vy, remaining in cases:
            shot = combat.Projectile(source, dict(source.data), x, y, vx, vy, remaining, height=0, weapon_data=dict(c.TACTICAL_WEAPONS["torpedo"]))
            simulation.projectiles = [shot]
            self.assertEqual(simulation._naval_evasion(unit, (0.0, unit.angle)), (0.0, unit.angle))
            self.assertIsNone(unit.evasion_course)
        shot = combat.Projectile(source, dict(source.data), unit.x + 600, unit.y, -100, 0, 10, height=0, weapon_data=dict(c.TACTICAL_WEAPONS["torpedo"]))
        for controlled, speed in ((unit, 1), (None, 0)):
            simulation.controlled = controlled
            unit.data["speed"] = speed
            simulation.projectiles = [shot]
            self.assertEqual(simulation._naval_evasion(unit, (0.0, unit.angle)), (0.0, unit.angle))
            self.assertIsNone(unit.evasion_course)

    def test_a_slow_ship_maneuvers_away_from_a_torpedo_it_would_otherwise_hit(self):
        results = []
        for evades in (False, True):
            simulation = self.simulation("submarine")
            source, unit = simulation.fighters
            source.x = unit.x + 1200
            source.data["speed"] = 0
            unit.angle = 0
            unit.data["speed"] = 1
            unit.hold = 1
            unit.cooldown = unit.secondary_cooldown = 1000
            shot = combat.Projectile(source, dict(source.data), unit.x + 600, unit.y, -100, 0, 10, height=0, weapon_data=dict(c.TACTICAL_WEAPONS["torpedo"]))
            simulation.projectiles = [shot]
            if evades:
                simulation.advance(7)
            else:
                with patch.object(simulation, "_naval_evasion", side_effect=lambda unit, course: course):
                    simulation.advance(7)
            results.append((unit.data["health"], (unit.x, unit.y)))
        self.assertGreater(results[1][0], results[0][0])
        self.assertNotEqual(results[1][1], results[0][1])

    def long_hull_encounter(self):
        self.enterContext(patch.dict(c.TACTICAL_BODIES, {"destroyer": (200, 20, math.hypot(100, 10), 4.0)}))
        self.enterContext(patch.dict(combat.MOBILITY, {"destroyer": (1.0, 60.0, 0.1)}))
        simulation = self.simulation(controlled=None)
        source, unit = simulation.fighters
        unit.x = unit.y = 2000
        unit.angle = unit.speed = unit.turn_rate = 0
        unit.data["speed"] = 1
        source.x, source.y = 4000, 2000
        simulation._sides = [[source], [unit]]
        return simulation, source, unit

    def torpedo_at(self, source, x, y, vx, vy, remaining=6):
        return combat.Projectile(source, dict(source.data), x, y, vx, vy, remaining, height=0, weapon_data=dict(c.TACTICAL_WEAPONS["torpedo"]))

    def test_rotating_bow_and_stern_hit_between_clear_endpoint_orientations(self):
        simulation, source, unit = self.long_hull_encounter()
        for sign in (-1, 1):
            with self.subTest(end="bow" if sign > 0 else "stern"):
                shot = self.torpedo_at(source, unit.x + sign * 70, unit.y + sign * 70, 0, 0)
                unit.angle = 0
                self.assertIsNone(naval.projectile_contact(shot, unit, 1, (unit.x, unit.y)))
                unit.angle = math.pi / 2
                self.assertIsNone(naval.projectile_contact(shot, unit, 1, (unit.x, unit.y)))
                fraction = naval.projectile_contact(shot, unit, 1, (unit.x, unit.y), start_angle=0)
                self.assertIsNotNone(fraction)
                self.assertGreater(fraction, 0)
                self.assertLess(fraction, 1)
                keep, hits = simulation._advance_naval_projectile(shot, 1, [unit], {unit.index: (unit.x, unit.y)}, start_angles={unit.index: 0})
                self.assertFalse(keep)
                self.assertIs(hits[0][0], unit)

    def test_planner_rejects_bow_and_stern_turns_when_staying_straight_is_safe(self):
        simulation, source, unit = self.long_hull_encounter()
        for dx, dy, vx, heading in ((180, 50, -80, math.pi / 2), (-120, 50, 80, -math.pi / 2), (180, -50, -80, -math.pi / 2)):
            with self.subTest(offset=(dx, dy)):
                shot = self.torpedo_at(source, unit.x + dx, unit.y + dy, vx, 0)
                simulation.projectiles = [shot]
                unit.evasion_course = None
                unit.evasion_next_check = 0
                self.assertEqual(simulation._naval_maneuver_score(unit, (0.0, 0.0), [shot])[0], math.inf)
                self.assertNotEqual(simulation._naval_maneuver_score(unit, (1.0, heading), [shot])[0], math.inf)
                chosen = simulation._naval_evasion(unit, (1.0, heading))
                self.assertEqual(simulation._naval_maneuver_score(unit, chosen, [shot])[0], math.inf)

    def test_new_torpedo_replaces_an_active_maneuver_that_would_hit_the_stern(self):
        simulation, source, unit = self.long_hull_encounter()
        bow = self.torpedo_at(source, unit.x + 180, unit.y + 50, -80, 0)
        stern = self.torpedo_at(source, unit.x - 120, unit.y + 50, 80, 0)
        normal, active = (1.0, math.pi / 2), (1.0, -math.pi / 2)
        unit.evasion_course = active
        simulation.projectiles = [bow]
        self.assertEqual(simulation._naval_evasion(unit, normal), active)
        simulation.projectiles.append(stern)
        simulation.elapsed = unit.evasion_next_check
        self.assertNotEqual(simulation._naval_maneuver_score(unit, active, [bow, stern])[0], math.inf)
        chosen = simulation._naval_evasion(unit, normal)
        self.assertNotEqual(chosen, active)
        self.assertEqual(simulation._naval_maneuver_score(unit, chosen, [bow, stern])[0], math.inf)

    def test_live_turn_avoids_the_bow_hit_caused_by_the_old_sideways_dodge(self):
        results = []
        for evades in (False, True):
            simulation, source, unit = self.long_hull_encounter()
            simulation.controlled = source
            source.data["speed"] = 0
            unit.cooldown = unit.secondary_cooldown = 1000
            unit.dodge, unit.dodge_heading = 4.0, math.pi / 2
            simulation.projectiles = [self.torpedo_at(source, unit.x + 180, unit.y + 50, -80, 0)]
            if evades:
                simulation.advance(4)
            else:
                with patch.object(simulation, "_naval_evasion", side_effect=lambda unit, course: course):
                    simulation.advance(4)
            results.append(unit.data["health"])
        self.assertLess(results[0], results[1])

    def test_unavoidable_torpedo_prefers_a_maneuver_that_delays_contact(self):
        simulation, source, unit = self.long_hull_encounter()
        unit.data["speed"] = 0.05
        shot = self.torpedo_at(source, unit.x + 140, unit.y, -100, 0)
        simulation.projectiles = [shot]
        baseline = simulation._naval_maneuver_score(unit, (0.0, 0.0), [shot])
        chosen = simulation._naval_evasion(unit, (0.0, 0.0))
        result = simulation._naval_maneuver_score(unit, chosen, [shot])
        self.assertLess(result[0], math.inf)
        self.assertGreater(result[0], baseline[0])

    def test_prediction_does_not_modify_live_units_projectiles_or_randomness(self):
        simulation, source, unit = self.long_hull_encounter()
        shot = self.torpedo_at(source, unit.x + 180, unit.y + 50, -80, 0)
        simulation.projectiles = [shot]
        units = [copy.deepcopy(vars(fighter)) for fighter in simulation.fighters]
        position, remaining = (shot.x, shot.y), shot.remaining
        randomness = simulation._rng.getstate()
        simulation._naval_maneuver_score(unit, (1.0, math.pi / 2), [shot])
        self.assertEqual([vars(fighter) for fighter in simulation.fighters], units)
        self.assertEqual((shot.x, shot.y), position)
        self.assertEqual(shot.remaining, remaining)
        self.assertEqual(simulation._rng.getstate(), randomness)

    def test_maneuvers_cannot_leave_the_field_or_swing_into_a_friendly_hull(self):
        simulation, source, unit = self.long_hull_encounter()
        shot = self.torpedo_at(source, unit.x + 180, unit.y + 50, -80, 0)
        ally = combat.Fighter(dict(unit.data), unit.side, unit.x + 70, unit.y + 70, "convoy", index=2)
        simulation.fighters.append(ally)
        simulation._sides[unit.side].append(ally)
        self.assertIsNone(simulation._naval_maneuver_score(unit, (1.0, math.pi / 2), [shot]))
        simulation.fighters.remove(ally)
        simulation._sides[unit.side].remove(ally)
        unit.x = unit.radius + 1
        shot.x = unit.x + 180
        shot.y = unit.y + 500
        self.assertIsNone(simulation._naval_maneuver_score(unit, (1.0, math.pi), [shot]))
        self.assertIsNotNone(simulation._naval_maneuver_score(unit, (0.0, 0.0), [shot]))

    def test_evasion_uses_the_same_decision_for_identical_hulls_on_either_side(self):
        simulation, source, unit = self.long_hull_encounter()
        simulation.projectiles = [self.torpedo_at(source, unit.x + 180, unit.y + 50, -80, 0)]
        chosen = []
        for side in (0, 1):
            unit.side, source.side = side, 1 - side
            unit.evasion_course = None
            unit.evasion_next_check = 0
            simulation._sides = [[fighter for fighter in simulation.fighters if fighter.side == team] for team in (0, 1)]
            chosen.append(simulation._naval_evasion(unit, (1.0, math.pi / 2)))
        self.assertEqual(chosen[0], chosen[1])

    def test_naval_ram_is_available_at_naval_minimum_speed(self):
        simulation = self.simulation("battleship", "destroyer", controlled=None)
        source, target = simulation.fighters
        source.data["speed"] = naval.RAM_MIN_UNIT_SPEED
        source.pace = 0.6
        self.assertTrue(source.can_ram)
        self.assertIsNotNone(simulation._ram_point(source, target))
        source.ram_committed = True
        self.assertEqual(simulation._naval_course(source, target)[0], 1.0)

    def test_land_simulation_unloads_convoy_with_its_health_fraction(self):
        entry = combat.create_battle_unit("Fixture Land I", "Fixture A", self.library, "ocean")
        entry["health"] *= 0.37
        simulation = combat.BattleSimulation(self.library, [entry], ["Fixture Land I"], terrain="plains")
        self.assertAlmostEqual(simulation.division_health_fraction(0), 0.37)
        self.assertTrue(all(not fighter.naval for fighter in simulation.fighters))

    def test_hull_collision_uses_width_instead_of_a_large_circle(self):
        simulation = self.simulation()
        first, second = simulation.fighters
        width, height = c.TACTICAL_BODIES[first.shape][:2]
        second.x, second.y, second.angle = first.x, first.y + height + 5, first.angle
        self.assertIsNone(naval.body_contact(first, second, (0, 0), (0, 0), 1))
        second.x, second.y = first.x + width + 5, first.y
        self.assertIsNotNone(naval.body_contact(first, second, (50, 0), (-50, 0), 1))

    def test_naval_ram_deals_damage_and_friendly_contact_does_not(self):
        for friendly in (False, True):
            simulation = self.simulation()
            first, second = simulation.fighters
            first.speed, second.speed = 150, 150
            second.x = first.x + c.TACTICAL_BODIES[first.shape][0] + 2
            if friendly:
                second.side = first.side
            movements = [(first, 10, 0), (second, -10, 0)]
            crowds = [combat._Grid([first], combat.GRID_CELL), combat._Grid([second], combat.GRID_CELL)]
            hits = simulation._resolve_contacts(simulation.fighters, crowds, movements, 1 / 15)
            self.assertEqual(bool(hits), not friendly)

    def test_seeded_naval_simulation_is_independent_of_frame_partition(self):
        whole, partitioned = self.simulation(controlled=None), self.simulation(controlled=None)
        whole.advance(4)
        for _ in range(240):
            partitioned.advance(1 / 60)
        for first, second in zip(whole.fighters, partitioned.fighters):
            self.assertAlmostEqual(first.x, second.x)
            self.assertAlmostEqual(first.y, second.y)
            self.assertAlmostEqual(first.data["health"], second.data["health"])
        self.assertEqual(len(whole.projectiles), len(partitioned.projectiles))

    def test_water_random_candidates_exclude_outdated_and_future_ships(self):
        tree = {"fixture_ships": {"years": [1800, 2055, 2056, 2060, 2061]}}
        entries = (("Old Ship I", "Fixture Old", 1, 1800), ("Boundary Ship I", "Fixture Boundary", 1, 2055), ("Recent Ship I", "Fixture Recent", 1, 2056), ("Modern Ship I", "Fixture Modern", 1, 2060), ("Modern Ship II", "Fixture Modern", 2, 2061), ("Modern Land I", "Fixture Land", 1, 2060))
        library = {}
        for name, family, tier, year in entries:
            stats = dict(unit_stats(family, tier=tier), naval_unit=name != "Modern Land I")
            requirement = {"tech": "fixture_ships", "year": year}
            stats["metadata"].update(research=requirement, requirements=[requirement])
            library[name] = stats
        with patch.object(queries, "get_tech_tree", return_value=tree):
            for terrain in c.WATER_TERRAINS:
                with self.subTest(terrain=terrain):
                    self.assertEqual(set(combat.custom_unit_types_for_year(library, 2060, terrain)), {"Recent Ship I", "Modern Ship I"})
                    self.assertEqual(combat.custom_unit_types_for_year(library, 2061, terrain), ["Modern Ship II"])
                    self.assertEqual(combat.custom_unit_types_for_year(library, 2066, terrain), [])

    def test_water_random_candidates_resolve_numbered_research_and_skip_missing_dates(self):
        names = list(self.library)
        tree = {"fixture": {"years": [2060]}}
        self.library[names[0]]["metadata"]["research"] = {"tech": "missing_fixture", "level": 1}
        with patch.object(queries, "get_latest_units_for_year", return_value=names), patch.object(queries, "get_tech_tree", return_value=tree):
            self.assertEqual(set(combat.custom_unit_types_for_year(self.library, 2060, "ocean")), {name for name in names[1:] if self.library[name]["naval_unit"]})
            self.assertEqual(combat.custom_unit_types_for_year(self.library, 2065, "ocean"), [])


class NavalSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        fonts.init_fonts()

    def setUp(self):
        self.library = fixture_library()
        countries = {name: dict(name=name, is_playable=True, flag_data="DEFAULT") for name in ("Fixture A", "Fixture B")}
        self.enterContext(patch.object(queries, "get_unit_library", return_value=self.library))
        self.enterContext(patch.object(queries, "get_country_data", return_value=countries))
        self.enterContext(patch.object(combat, "normal_game_forecast", return_value=(None, None)))
        self.enterContext(patch.object(queries, "get_latest_units_for_year", return_value=list(self.library)))
        self.screen = ui.CustomBattleScreen()
        self.enterContext(patch.object(queries, "get_tech_tree", return_value={"fixture": {"years": [self.screen.generation_year]}}))
        self.controller = SimpleNamespace(set_tactical_battle_music=Mock(), set_music_volume_scale=Mock())
        self.screen.on_enter(self.controller, None)

    def test_selector_converts_existing_roster_and_keeps_settings_and_control(self):
        self.screen.add_unit(0, "Fixture battleship I")
        self.screen.add_unit(1, "Fixture Land I")
        self.screen.controlled_index = 0
        unit = self.screen.rosters[0][0]
        self.screen.set_unit_options(0, [unit], owner="Fixture B", health_percent=37)
        identity = unit["unit_id"]
        with patch("ui.dialogs.pickers.open_listbox_selector") as picker:
            self.screen.choose_terrain()
        self.assertTrue(set(c.WATER_TERRAINS) <= {value for _, value in picker.call_args.args[3]})
        picker.call_args.args[4]("ocean")
        self.assertIs(self.screen.rosters[0][0], unit)
        self.assertEqual((unit["type"], unit["owner"], unit["unit_id"]), ("Fixture battleship I", "Fixture B", identity))
        self.assertAlmostEqual(unit["health"] / unit["max_health"], 0.37)
        self.assertEqual(self.screen.controlled_index, 0)
        self.assertEqual(self.screen.rosters[1][0]["type"], "Convoy (Fixture Land I)")
        self.screen.duplicate_unit(0)
        self.assertEqual(self.screen.rosters[0][1]["health"], unit["health"])
        self.assertNotEqual(self.screen.rosters[0][1]["unit_id"], identity)
        self.screen.preview_battle()
        self.assertEqual(self.screen.simulation.terrain, "ocean")
        self.assertTrue(all(len(division) == 1 for division in self.screen.simulation.divisions))
        self.assertTrue(self.screen.simulation.paused)
        before = copy.deepcopy(self.screen.rosters)
        self.screen.set_terrain("plains")
        self.assertEqual(self.screen.rosters, before)
        self.screen.return_to_setup()
        self.screen.set_terrain("plains")
        self.assertEqual(unit["type"], "Truck (Fixture battleship I)")
        self.assertAlmostEqual(unit["health"] / unit["max_health"], 0.37)

    def test_naval_preview_uses_prepared_ship_and_convoy_symbols(self):
        self.screen.set_terrain("lakes")
        self.screen.add_unit(0, "Fixture submarine I")
        self.screen.add_unit(1, "Fixture Land I")
        self.screen.preview_battle()
        with patch.object(ui.symbol_loader, "get_symbol", return_value=None) as symbols:
            self.screen.card_surfaces.clear()
            for side in (0, 1):
                self.screen._cache_card(side, self.screen.rosters[side][0])
        self.assertEqual({call.args[0] for call in symbols.call_args_list}, {"Fixture submarine I", "Convoy (Fixture Land I)"})

    def test_terrain_change_refreshes_random_candidates_and_forecast(self):
        self.screen.add_unit(0, "Fixture destroyer I")
        self.screen.add_unit(1, "Fixture Land I")
        old_key = self.screen.forecast_key
        self.screen.set_terrain("inland_sea")
        self.assertNotEqual(self.screen.forecast_key, old_key)
        self.assertTrue(self.screen.random_candidates)
        self.assertTrue(all(self.library[name]["naval_unit"] for name in self.screen.random_candidates))
        self.screen.generate_armies()
        self.assertTrue(all(self.library[unit["type"]]["naval_unit"] for roster in self.screen.rosters for unit in roster))

    def test_year_change_refreshes_naval_random_without_restricting_manual_selection(self):
        year = 2060
        for name, stats in self.library.items():
            researched = year if name == "Fixture destroyer I" else year - combat.RANDOM_UNIT_AGE_LIMIT
            stats["metadata"]["research"] = {"tech": "fixture", "year": researched}
        self.screen.set_terrain("ocean")
        self.screen.update_generation_year(year - c.START_YEAR)
        self.assertEqual(self.screen.random_candidates, ["Fixture destroyer I"])
        button = self.screen.generate_button
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center), pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center)])
        self.assertTrue(all(unit["type"] == "Fixture destroyer I" for roster in self.screen.rosters for unit in roster))
        self.screen.clear_army(0)
        self.screen.add_unit(0, "Fixture ironclad I")
        self.assertEqual(self.screen.rosters[0][0]["type"], "Fixture ironclad I")
        before = copy.deepcopy(self.screen.rosters)
        self.screen.update_generation_year(year + combat.RANDOM_UNIT_AGE_LIMIT - c.START_YEAR)
        self.assertTrue(self.screen.generate_button.disabled)
        self.screen.generate_armies()
        self.assertEqual(self.screen.rosters, before)

    def test_preview_reorder_replay_and_start_keep_naval_terrain(self):
        self.screen.set_terrain("coastal_sea")
        for side in (0, 1):
            self.screen.add_unit(side, "Fixture destroyer I")
        self.screen.add_unit(0, "Fixture submarine I")
        self.screen.preview_battle()
        field = self.screen.simulation.battlefield
        self.assertTrue(self.screen._move_roster_entry(0, 1, 0))
        self.assertEqual(self.screen.simulation.battlefield.terrain, field.terrain)
        self.assertEqual(self.screen.simulation.battlefield.size, field.size)
        self.assertEqual(self.screen.simulation.battlefield.features, field.features)
        self.assertEqual(self.screen.simulation.divisions[0][0].shape, "submarine")
        self.screen.preview_intro_stage = None
        self.screen.start_battle()
        self.assertEqual(self.screen.mode, "battle")
        self.assertEqual(self.screen.simulation.arena_size, naval.ARENA_SIZE)
        self.assertGreater(self.screen.simulation.sight_range, combat.WEAPON_RANGE)
        self.screen.simulation.winner = 0
        self.screen.mode = "result"
        self.screen.preview_battle()
        self.assertEqual(self.screen.simulation.terrain, "coastal_sea")
        self.assertTrue(self.screen.simulation.paused)
