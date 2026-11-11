"""Standalone battle mechanics, setup input, and safe pause/exit navigation."""

import copy
import math
import os
import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pygame

import data.constants as c
from data import queries
from map_logic import custom_battle as combat
from map_logic import battle_terrain
from screens.game import custom_battle as battle_screen
from ui.rendering.font_manager import fonts
from ui.widgets.ui_elements import Slider


def unit_stats(family="Fixture Infantry", *, tier=1, health=100, attack=40,
               defense=0, speed=3, **extra):
    return dict(
        health=health, attack=attack, defense=defense, speed=speed, naval_unit=False,
        metadata=dict(family=family, tier_order=tier, display_name=f"{family} {tier}",
                      research={"tech": "fixture", "level": tier}, requirements=[],
                      recruitment={"industry": "none", "coastal": False},
                      production_group="Infantry"), **extra)


def fixture_library():
    return {
        "Fixture I": unit_stats(),
        "Fixture II": unit_stats(tier=2, attack=200),
        "Fixture III": unit_stats(tier=3, attack=120),
        # Artillery: it can bombard, so it takes no part in tactical battles.
        "Fixture Gun I": unit_stats("Fixture Gun", bombard_range=2, bombard_attack=130),
        "Fixture Ship I": dict(unit_stats(), naval_unit=True),
        "Fixture Plane I": unit_stats(air_role="fighter", air_range_px=100),
    }


def dated_fixture_content():
    tree = {
        "cars": {"years": [1900, 1912, 1920]},
        "tanks": {"years": [1916]},
        "infantry_type": {"years": [1890, 1910, 1918]},
        "trucks": {"years": [1914]},
        "ships": {"years": [1800]},
        "planes": {"years": [1900]},
    }

    def stats(family, tier, research, requirements=None, **extra):
        result = unit_stats(family, tier=tier, **extra)
        result["metadata"].update(research=research,
                                  requirements=[research] if requirements is None else requirements)
        return result

    library = {
        **{f"Car {tier}": stats("Fixture Car", tier, {"tech": "cars", "level": tier})
           for tier in (3, 1, 2)},
        "Tank 1": stats("Fixture Tank", 1, {"tech": "tanks", "level": 1}),
        **{f"Foot {year}": stats("Infantry Type", year, {"tech": "infantry_type", "year": year})
           for year in (1918, 1890, 1910)},
        "Motorized 1910": stats("Motorized Infantry Type", 1910,
                                {"tech": "motorized_infantry", "year": 1910},
                                [{"tech": "trucks", "level": 1},
                                 {"tech": "infantry_type", "minimum_year": 1910}]),
        "Ship 1": dict(stats("Fixture Ship", 1, {"tech": "ships", "level": 1}), naval_unit=True),
        "Plane 1": stats("Fixture Plane", 1, {"tech": "planes", "level": 1}, air_role="fighter"),
    }
    return library, tree


class RandomBattleTests(unittest.TestCase):
    def setUp(self):
        self.library, self.tree = dated_fixture_content()
        self.enterContext(patch("data.queries.get_tech_tree", return_value=self.tree))

    def test_latest_eligible_family_tiers_exclude_future_units_and_additional_gates(self):
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1913)),
                         {"Car 2", "Foot 1910"})
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1916)),
                         {"Car 2", "Tank 1"})
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1914)),
                         {"Car 2", "Foot 1910", "Motorized 1910"})

    def test_year_is_inclusive_and_advances_levels_without_keeping_obsolete_tiers(self):
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1912)),
                         {"Car 2", "Foot 1910"})
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1920)),
                         {"Car 3", "Foot 1918", "Tank 1"})
        self.assertEqual(combat.land_unit_types_for_year(self.library, 1799), [])

    def test_numbered_and_year_based_units_are_excluded_at_exactly_five_years(self):
        self.assertIn("Car 2", combat.land_unit_types_for_year(self.library, 1916))
        self.assertNotIn("Car 2", combat.land_unit_types_for_year(self.library, 1917))
        self.assertIn("Foot 1910", combat.land_unit_types_for_year(self.library, 1914))
        self.assertNotIn("Foot 1910", combat.land_unit_types_for_year(self.library, 1915))
        self.assertEqual(combat.land_unit_types_for_year(self.library, 1925), [])

    def test_random_armies_have_independent_three_to_five_unit_counts_and_valid_types(self):
        candidates = combat.land_unit_types_for_year(self.library, 1913)
        rng = random.Random(7)
        with patch.object(rng, "randint", side_effect=[3, 5]) as counts:
            friendly, enemy = combat.random_armies(candidates, rng=rng)
        self.assertEqual((len(friendly), len(enemy)), (3, 5))
        self.assertEqual([call.args for call in counts.call_args_list], [(3, 5), (3, 5)])
        self.assertTrue(set(friendly + enemy) <= set(candidates))
        with self.assertRaises(ValueError):
            combat.random_armies([])


def single_subunits():
    """One sub-unit per fixture division, so a test can follow one unit per roster entry."""
    return patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 1})


def hold_still(simulation):
    """Stop every unit from moving or firing on its own, so only a test's shots act."""
    for fighter in simulation.fighters:
        fighter.data["speed"] = 0
        fighter.cooldown = 1000


class BattleSimulationTests(unittest.TestCase):
    def setUp(self):
        self.library = fixture_library()
        self.enterContext(single_subunits())
        self.enterContext(patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", 1.0))

    def test_catalog_and_constructor_reject_air_sea_artillery_unknown_and_empty_rosters(self):
        self.assertEqual(set(combat.land_unit_types(self.library)), {"Fixture I", "Fixture II", "Fixture III"})
        for roster in ([], ["missing"], ["Fixture Ship I"], ["Fixture Plane I"], ["Fixture Gun I"],
                       ["Fixture I"] * (c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE + 1)):
            with self.subTest(roster=roster[:2]), self.assertRaises(ValueError):
                combat.BattleSimulation(self.library, roster, ["Fixture I"])

    def test_units_use_library_stats_without_mutating_content_or_rosters(self):
        before = copy.deepcopy(self.library)
        roster = ["Fixture I", "Fixture II", "Fixture III"]
        simulation = combat.BattleSimulation(self.library, roster, ["Fixture I"])
        for fighter, name in zip(simulation.fighters, roster):
            for field in ("health", "attack", "defense", "speed"):
                self.assertEqual(fighter.data[field], self.library[name][field])
        simulation.advance(30)
        self.assertEqual(self.library, before)
        self.assertEqual(roster, ["Fixture I", "Fixture II", "Fixture III"])

    def test_enemy_has_tanks_counts_only_enemy_tank_shapes(self):
        """Tactical battle music picks the tank songs from this rule. Friendly tanks do not count."""
        self.library["Fixture Armor I"] = unit_stats("Fixture Armor")
        self.assertFalse(combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture II"]).enemy_has_tanks())
        for shape in combat.TANK_SHAPES:
            with self.subTest(shape=shape), patch.dict(combat.FAMILY_SHAPES, {"Fixture Armor": shape}):
                self.assertFalse(combat.BattleSimulation(
                    self.library, ["Fixture I", "Fixture Armor I"], ["Fixture I"]).enemy_has_tanks())
                self.assertTrue(combat.BattleSimulation(
                    self.library, ["Fixture I"], ["Fixture I", "Fixture Armor I"]).enemy_has_tanks())

    def test_automatic_battle_reaches_win_and_loss(self):
        # Fixture I cannot damage this armored Fixture II, so the result never depends on lucky shots.
        self.library["Fixture II"]["defense"] = self.library["Fixture I"]["attack"]
        for friendly, enemy, expected in (("Fixture II", "Fixture I", 0),
                                          ("Fixture I", "Fixture II", 1)):
            with self.subTest(friendly=friendly):
                simulation = combat.BattleSimulation(self.library, [friendly], [enemy], seed=1)
                simulation.advance(60)
                self.assertEqual(simulation.winner, expected)
                self.assertTrue(all(not fighter.alive for fighter in simulation.fighters
                                    if fighter.side != expected))

    def test_roster_records_preserve_starting_health_and_nationality_without_mutation(self):
        friendly = queries.create_unit_dict("Fixture I", "First Country", self.library)
        enemy = queries.create_unit_dict("Fixture I", "Second Country", self.library)
        friendly["health"] = 25
        enemy["health"] = 75
        before = copy.deepcopy([friendly, enemy])
        simulation = combat.BattleSimulation(self.library, [friendly], [enemy])
        self.assertEqual([(unit.data["owner"], unit.data["health"], unit.data["max_health"])
                          for unit in simulation.fighters],
                         [("First Country", 25, 100), ("Second Country", 75, 100)])
        simulation.advance(60)
        self.assertEqual([friendly, enemy], before)

    def test_roster_records_reject_dead_overhealed_and_invalid_starting_health(self):
        unit = queries.create_unit_dict("Fixture I", "First Country", self.library)
        for health in (0, -1, 101, True, "25", float("nan")):
            with self.subTest(health=health), self.assertRaises(ValueError):
                combat.BattleSimulation(self.library, [dict(unit, health=health)], ["Fixture I"])

    def test_fixed_steps_are_independent_of_frame_partition(self):
        whole = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture II"], seed=7)
        partitioned = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture II"], seed=7)
        whole.advance(3)
        for _ in range(180):
            partitioned.advance(1 / 60)
        for first, second in zip(whole.fighters, partitioned.fighters):
            self.assertAlmostEqual(first.x, second.x)
            self.assertAlmostEqual(first.y, second.y)
            self.assertAlmostEqual(first.data["health"], second.data["health"])

    def test_pause_freezes_combat_without_accumulating_paused_time(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        simulation.advance(1)
        before = [(f.x, f.y, f.data["health"]) for f in simulation.fighters]
        simulation.paused = True
        simulation.advance(100)
        self.assertEqual(before, [(f.x, f.y, f.data["health"]) for f in simulation.fighters])
        self.assertAlmostEqual(simulation.elapsed, 1)
        simulation.paused = False
        simulation.advance(combat.FIXED_STEP)
        self.assertAlmostEqual(simulation.elapsed, 1 + combat.FIXED_STEP)

    def test_projectile_impacts_subtract_full_defense_even_when_wounded_on_either_side(self):
        for target_side in (0, 1):
            for health, defense in ((100, 15), (50, 15), (50, 30), (50, 40), (10, 0)):
                with self.subTest(target_side=target_side, health=health, defense=defense):
                    simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
                    target = simulation.fighters[target_side]
                    source = simulation.fighters[1 - target_side]
                    target.data.update(defense=defense, health=health, max_health=100)
                    simulation.projectiles = [combat.Projectile(
                        source, dict(source.data, attack=30), target.x - 5, target.y, 300, 0, 1)]
                    simulation.advance(combat.FIXED_STEP)
                    self.assertEqual(target.data["health"], max(0, health - max(0, 30 - defense) * combat.DAMAGE_SCALE))

    def test_defense_blocks_each_simultaneous_hit_separately(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        source, target = simulation.fighters
        target.data.update(defense=20, health=100, max_health=100)
        simulation.projectiles = [combat.Projectile(
            source, dict(source.data, attack=30), target.x - 5, target.y, 300, 0, 1) for _ in range(2)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(target.data["health"], 100 - 2 * 10 * combat.DAMAGE_SCALE)

    def test_tactical_attack_ignores_wounds_while_campaign_attack_still_scales(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        source, target = simulation.fighters
        healthy = dict(source.data, health=100, max_health=100, attack=40)
        wounded = dict(healthy, health=1)
        target.data["defense"] = 10
        before = copy.deepcopy(wounded)
        with patch.object(c, "DAMAGE_AT_ZERO_HEALTH", 0):
            for multiplier in (1.0, combat.RAM_DAMAGE):
                self.assertEqual(simulation.damage_amount(wounded, target.data, 1, multiplier),
                                 simulation.damage_amount(healthy, target.data, 1, multiplier))
            full_campaign = sum(shot[1] for shot in combat.combat_rules.damage_shots([healthy], [target.data]))
            wounded_campaign = sum(shot[1] for shot in combat.combat_rules.damage_shots([wounded], [target.data]))
            self.assertLess(wounded_campaign, full_campaign)
        self.assertEqual(wounded, before)
        for capability in (0.0, 2.0):
            with patch("data.queries.unit_target_damage_multiplier", return_value=capability):
                self.assertEqual(simulation._attack(wounded, target.data), wounded["attack"] * capability)

    def test_tactical_health_floor_supports_proportional_partial_and_constant_attack(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        source, target = simulation.fighters
        source.data.update(attack=80, max_health=100)
        target.data["defense"] = 0
        for floor, health, expected in ((0, 0, 0), (0, 25, 0.25), (0, 100, 1),
                                         (0.5, 0, 0.5), (0.5, 25, 0.625), (0.5, 100, 1),
                                         (1, 0, 1), (1, 25, 1), (1, 100, 1)):
            with self.subTest(floor=floor, health=health), \
                    patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", floor), \
                    patch.object(c, "DAMAGE_AT_ZERO_HEALTH", 0.9):
                source.data["health"] = health
                self.assertAlmostEqual(simulation._attack(source.data, target.data), 80 * expected)
                for attack_kind in (1.0, combat.RAM_DAMAGE):
                    self.assertAlmostEqual(simulation.damage_amount(source.data, target.data, 0.5, attack_kind),
                                           math.ceil(80 * expected * 0.5) * combat.DAMAGE_SCALE * attack_kind)

    def test_ai_damage_capability_cache_tracks_current_wounds(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        source, target = simulation.fighters
        source.data.update(attack=40, max_health=100, health=25)
        target.data["defense"] = 20
        with patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", 0):
            self.assertFalse(simulation._can_hurt(source, target))
            source.data["health"] = 100
            self.assertTrue(simulation._can_hurt(source, target))
            source.data["health"] = 25
            self.assertFalse(simulation._can_hurt(source, target))
        self.assertTrue(simulation._can_hurt(source, target))

    def test_displayed_division_attack_matches_sum_of_deployed_subunits(self):
        unit = queries.create_unit_dict("Fixture I", "First Country", self.library)
        unit["attack"] = 100
        self.library["Fixture I"]["attack"] = 100
        for size in (1, 3, 10):
            for health in (1, 63, 70, 100):
                for floor in (0, 0.5, 1):
                    with self.subTest(size=size, health=health, floor=floor), \
                            patch.dict(combat.SUBUNIT_COUNTS, {"infantry": size}), \
                            patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", floor):
                        unit["health"] = health
                        simulation = combat.BattleSimulation(self.library, [unit], ["Fixture I"])
                        target = simulation.divisions[1][0]
                        attack = sum(simulation._attack(fighter.data, target.data) * fighter.attack_share
                                     for fighter in simulation.divisions[0])
                        self.assertAlmostEqual(combat.division_attack(unit, self.library), attack)
                        if size == 10 and health == 63:
                            self.assertAlmostEqual(attack, {0: 63, 0.5: 66.5, 1: 70}[floor])

    def test_shots_fired_when_wounded_keep_full_damage_after_shooter_dies(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        hold_still(simulation)
        source, target = simulation.fighters
        source.data["health"] = 1
        target.data["defense"] = 10
        snapshot = dict(source.data)
        simulation.projectiles = [combat.Projectile(source, snapshot, target.x - 5, target.y, 300, 0, 1)]
        source.data["health"] = 0
        simulation.advance(combat.FIXED_STEP)
        expected = simulation.damage_amount(dict(snapshot, health=snapshot["max_health"]), target.data, 1)
        self.assertGreater(expected, 0)
        self.assertEqual(target.data["health"], target.data["max_health"] - expected)

    def test_shot_damage_uses_the_unit_hit_and_lands_after_the_shooter_dies(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I", "Fixture I"])
        hold_still(simulation)
        source, first, second = simulation.fighters
        first.x, first.y = 1000, 500
        second.x, second.y = 1100, 500
        shot = combat.Projectile(source, dict(source.data, attack=30), second.x - 5, second.y, 300, 0, 1)
        simulation.projectiles = [shot]
        source.data["health"] = 1  # The shot was fired at full strength.
        with patch.object(combat.combat_rules, "damage_shots", wraps=combat.combat_rules.damage_shots) as damage:
            simulation.advance(combat.FIXED_STEP)
        # Target choice also measures damage; only this shot's impact is checked here.
        self.assertEqual([call.args[1] for call in damage.call_args_list if call.args[0][0] is shot.source_data],
                         [[second.data]])
        self.assertEqual((first.data["health"], second.data["health"]), (100, 100 - 30 * combat.DAMAGE_SCALE))

    def plains_simulation(self, friendly, enemy):
        return combat.BattleSimulation(self.library, friendly, enemy, seed=1, battlefield=battle_terrain.Battlefield(
            "plains", combat.ARENA_SIZE, combat.UNIT_RADIUS, ()))

    def test_shots_hit_the_first_ally_or_enemy_they_cross_but_never_their_shooter(self):
        simulation = self.plains_simulation(["Fixture I", "Fixture I"], ["Fixture I"])
        hold_still(simulation)
        shooter, ally, enemy = simulation.fighters
        shooter.x, shooter.y = 1000, 500
        ally.x, ally.y = 1020, 500
        enemy.x, enemy.y = 1100, 500
        simulation.projectiles = [combat.Projectile(shooter, dict(shooter.data), shooter.x, shooter.y, 300, 0, 1)]
        simulation.advance((ally.x - shooter.x) / 300)
        loss = combat.BattleSimulation.damage_amount(shooter.data, ally.data, shooter.attack_share)
        self.assertGreater(loss, 0)
        self.assertEqual([unit.data["health"] for unit in simulation.fighters],
                         [shooter.data["max_health"], ally.data["max_health"] - loss, enemy.data["max_health"]])

    def test_ai_holds_fire_and_sidesteps_while_an_ally_blocks_its_shot(self):
        simulation = self.plains_simulation(["Fixture I", "Fixture I"], ["Fixture I"])
        shooter, ally, enemy = simulation.fighters
        shooter.x, shooter.y = 1000, 500
        ally.x, ally.y = 1100, 505  # Just below the firing line.
        enemy.x, enemy.y = 1400, 500
        shooter.angle = shooter.aim = 0.0
        simulation._sides = [[shooter, ally], [enemy]]

        def drive():
            shooter.cooldown, shooter.dodge, shooter.target, shooter.retarget = 0, 0, enemy, 1000
            shots = []
            simulation._drive_ai(shooter, combat._Grid([enemy], combat.TARGET_CELL), combat.FIXED_STEP,
                                 shots, (shooter.x, shooter.y), enemy)
            return shots

        self.assertEqual(drive(), [])
        self.assertEqual(shooter.dodge, combat.LINE_SHIFT_SECONDS)
        self.assertLess(math.sin(shooter.dodge_heading), 0)  # Upward, away from the ally.
        ally.y = 500 + combat.UNIT_RADIUS * 4
        self.assertEqual(drive(), [(shooter, 0)])
        self.assertEqual(shooter.dodge, 0)

    def test_simultaneous_destruction_is_a_loss_and_finished_battle_stays_finished(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        hold_still(simulation)
        friendly, enemy = simulation.fighters
        # Each takes a killing shot on the same tick.
        simulation.projectiles = [
            combat.Projectile(enemy, dict(enemy.data), friendly.x + 5, friendly.y, -300, 0, 1),
            combat.Projectile(friendly, dict(friendly.data), enemy.x - 5, enemy.y, 300, 0, 1)]
        for fighter in simulation.fighters:
            fighter.data["health"] = 1
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(simulation.winner, 1)
        elapsed = simulation.elapsed
        simulation.advance(60)
        self.assertEqual(simulation.elapsed, elapsed)

    def test_controlled_unit_eases_into_speed_and_turns_along_its_heading(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        player = simulation.controlled
        speed_seconds, turn_degrees, turn_seconds = combat.MOBILITY[player.shape]
        top_speed = player.max_speed
        x, y = player.x, player.y
        simulation.advance(0.1)
        self.assertEqual((player.x, player.y, player.angle, player.speed), (x, y, 0.0, 0.0))
        player.angle = math.pi / 2
        simulation.set_player_input(throttle=1)
        simulation.advance(combat.FIXED_STEP)
        self.assertAlmostEqual(player.speed, top_speed / speed_seconds * combat.FIXED_STEP)
        self.assertLess(player.speed, top_speed)
        simulation.advance(speed_seconds)
        self.assertAlmostEqual(player.speed, top_speed)
        self.assertAlmostEqual(player.x, x)
        self.assertGreater(player.y, y)
        # Reversing first slows down, then backs up along the same heading.
        simulation.set_player_input(throttle=-1)
        simulation.advance(combat.FIXED_STEP)
        self.assertGreater(player.speed, 0)
        simulation.advance(2 * speed_seconds)
        self.assertAlmostEqual(player.speed, -top_speed)
        simulation.set_player_input()
        simulation.advance(2 * speed_seconds)
        self.assertEqual(player.speed, 0)
        x, y = player.x, player.y
        simulation.set_player_input(turn=1)
        simulation.advance(combat.FIXED_STEP)
        top_turn = math.radians(turn_degrees)
        self.assertAlmostEqual(player.turn_rate, top_turn / turn_seconds * combat.FIXED_STEP)
        simulation.advance(turn_seconds)
        self.assertAlmostEqual(player.turn_rate, top_turn)
        self.assertGreater(player.angle, math.pi / 2)
        self.assertEqual((player.x, player.y), (x, y))

    def test_gun_turns_toward_the_pointer_at_its_own_speed_inside_the_firing_cone(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        hold_still(simulation)  # The enemy must not close in and destroy the player during the test.
        player = simulation.controlled
        cone, gun_degrees = combat.AIM[player.shape]
        self.assertIsNotNone(cone)
        below = (player.x, player.y + 100)  # Straight down, outside the cone of a unit facing right.
        simulation.set_player_input(aim_point=below)
        simulation.advance(combat.FIXED_STEP)
        self.assertAlmostEqual(player.aim, math.radians(gun_degrees) * combat.FIXED_STEP)
        simulation.advance(5)
        self.assertAlmostEqual(player.aim, math.radians(cone) / 2)
        # Turning the hull carries the cone, so the gun can now reach the pointer.
        player.angle = math.pi / 2
        simulation.advance(5)
        self.assertAlmostEqual(player.aim, math.pi / 2)
        with patch.dict(combat.AIM, {player.shape: (None, gun_degrees)}):
            player.angle = 0.0
            simulation.set_player_input(aim_point=(player.x - 100, player.y))
            simulation.advance(5)
            self.assertAlmostEqual(player.aim, math.pi)

    def test_manual_fire_follows_the_gun_and_waits_for_reload_while_held(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        player = simulation.controlled
        player.aim = math.pi / 4  # The hull still faces right.
        with patch.object(combat, "Projectile", wraps=combat.Projectile) as projectiles:
            simulation.advance(combat.FIXED_STEP)
            self.assertEqual(projectiles.call_count, 0)
            simulation.set_player_input(fire=True)
            simulation.advance(combat.FIXED_STEP)
            self.assertEqual(projectiles.call_count, 1)
            shot = simulation.projectiles[0]
            self.assertLessEqual(abs(math.atan2(shot.vy, shot.vx) - math.pi / 4), combat.SHOT_SPREAD)
            self.assertAlmostEqual(math.hypot(shot.vx, shot.vy), combat.PROJECTILE_SPEED)
            simulation.advance(combat.FIRE_INTERVAL / 2)
            self.assertEqual(projectiles.call_count, 1)
            simulation.set_player_input(fire=False)
            simulation.set_player_input(fire=True)
            simulation.advance(combat.FIRE_INTERVAL / 2 + 2 * combat.FIXED_STEP)
            self.assertEqual(projectiles.call_count, 2)

    def test_shot_callback_runs_once_per_player_or_ai_projectile_and_stays_silent_during_reload_and_pause(self):
        fired = Mock()
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"],
                                             controlled_index=0, seed=2, on_shot=fired)
        player, enemy = simulation.fighters
        player.data["speed"] = enemy.data["speed"] = 0
        enemy.x, enemy.y = player.x + combat.WEAPON_RANGE / 2, player.y
        simulation.set_player_input(fire=True)
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual([call.args[0] for call in fired.call_args_list], [player, enemy])
        simulation.advance(combat.FIRE_INTERVAL / 2)
        self.assertEqual(fired.call_count, 2)
        simulation.paused = True
        simulation.advance(combat.FIRE_INTERVAL * 2)
        self.assertEqual(fired.call_count, 2)

    def test_manual_shots_can_miss_and_hit_without_homing(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        player, target = simulation.fighters
        target.x, target.y = player.x + 100, player.y
        target.data["speed"] = 0
        initial_health = target.data["health"]
        player.angle = player.aim = math.pi / 2
        simulation.set_player_input(fire=True)
        simulation.advance(0.3)
        self.assertEqual(target.data["health"], initial_health)
        player.angle = player.aim = 0
        player.cooldown = 0
        simulation.advance(0.3)
        self.assertLess(target.data["health"], initial_health)

    def test_ai_units_fire_only_once_their_gun_points_at_the_target(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        shooter, target = simulation.fighters
        target.data["speed"] = shooter.data["speed"] = 0
        target.cooldown = 1000
        # Outside the cone of a unit facing right, and far enough that a shot needs several ticks to arrive.
        target.x, target.y = shooter.x, shooter.y + 4 * combat.PROJECTILE_SPEED * combat.FIXED_STEP
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(simulation.projectiles, [])
        for _ in range(round(5 / combat.FIXED_STEP)):
            simulation.advance(combat.FIXED_STEP)
            if simulation.projectiles:
                break
        shot, = simulation.projectiles
        self.assertLessEqual(abs(combat._wrap(math.atan2(shot.vy, shot.vx) - math.pi / 2)),
                             combat.AIM_TOLERANCE + combat.SHOT_SPREAD)

    def test_controlled_index_must_refer_to_a_friendly_entry(self):
        for index in (-1, 1, True, "0"):
            with self.subTest(index=index), self.assertRaises(ValueError):
                combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=index)

    def test_divisions_split_into_sub_units_that_share_only_health(self):
        stats = self.library["Fixture I"]
        for size, percent, count in ((10, 100, 10), (10, 70, 7), (10, 63, 7), (10, 60, 6),
                                     (5, 70, 4), (5, 1, 1), (1, 63, 1)):
            with self.subTest(size=size, percent=percent), \
                    patch.dict(combat.SUBUNIT_COUNTS, {"infantry": size}):
                unit = queries.create_unit_dict("Fixture I", "First Country", self.library)
                unit["health"] = unit["max_health"] * percent / 100
                simulation = combat.BattleSimulation(self.library, [unit], ["Fixture I"])
                division = simulation.divisions[0]
                self.assertEqual(len(division), count)
                self.assertEqual(len({id(fighter.data) for fighter in division}), count)
                for fighter in division:
                    self.assertAlmostEqual(fighter.data["max_health"], stats["health"] / size)
                    self.assertAlmostEqual(fighter.data["health"], unit["health"] / count)
                    self.assertEqual((fighter.data["attack"], fighter.data["defense"]),
                                     (stats["attack"], stats["defense"]))
                    self.assertEqual(fighter.division, 0)
                self.assertAlmostEqual(simulation.division_health_fraction(0), percent / 100)
                self.assertEqual(len(simulation.fighters), count + len(simulation.divisions[1]))

    def test_each_division_deploys_as_a_centered_line_with_the_first_entry_in_front(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}):
            wounded = queries.create_unit_dict("Fixture I", "First Country", self.library)
            wounded["health"] = wounded["max_health"] / 2
            simulation = combat.BattleSimulation(self.library, ["Fixture I", wounded, "Fixture I"], ["Fixture I"])
        middle = combat.ARENA_SIZE[1] / 2
        front, short, back = simulation.divisions[:3]
        for division in (front, short, back):
            # One vertical line: same x, evenly spaced from top to bottom, centered on the battlefield.
            self.assertEqual({fighter.x for fighter in division}, {division[0].x})
            ys = [fighter.y for fighter in division]
            for upper, lower in zip(ys, ys[1:]):
                self.assertAlmostEqual(lower - upper, combat.SUBUNIT_SPACING)
            self.assertAlmostEqual(sum(ys) / len(ys), middle)
        self.assertLess(max(f.y for f in short) - min(f.y for f in short),
                        max(f.y for f in front) - min(f.y for f in front))
        # The enemy is to the right of the friendly army, so the first entry stands furthest right.
        self.assertAlmostEqual(front[0].x - short[0].x, combat.RANK_GAP)
        self.assertAlmostEqual(short[0].x - back[0].x, combat.RANK_GAP)
        self.assertGreater(simulation.divisions[3][0].x, front[0].x)

    def test_armies_deploy_the_same_gap_apart_whatever_their_size(self):
        width, height = combat.ARENA_SIZE
        for size in (1, 5, c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE):
            with self.subTest(size=size):
                simulation = combat.BattleSimulation(self.library, ["Fixture I"] * size, ["Fixture I"] * size)
                friendly_front = max(f.x for f in simulation.fighters if f.side == 0)
                enemy_front = min(f.x for f in simulation.fighters if f.side == 1)
                self.assertAlmostEqual(enemy_front - friendly_front, combat.SPAWN_FRONT_GAP)
                self.assertTrue(all(combat.UNIT_RADIUS <= f.x <= width - combat.UNIT_RADIUS
                                    and combat.UNIT_RADIUS <= f.y <= height - combat.UNIT_RADIUS
                                    for f in simulation.fighters))

    def test_sub_units_of_one_division_deploy_without_overlapping(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}):
            simulation = combat.BattleSimulation(self.library, ["Fixture I"] * 9, ["Fixture I"])
        for first in simulation.fighters:
            for second in simulation.fighters:
                if first is not second:
                    self.assertGreaterEqual(math.hypot(first.x - second.x, first.y - second.y),
                                            combat.UNIT_RADIUS * 2)

    def test_campaign_result_keeps_each_divisions_remaining_share_of_health(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}):
            simulation = combat.BattleSimulation(self.library, ["Fixture I", "Fixture I"], ["Fixture I"])
        wounded, healthy = simulation.divisions[0], simulation.divisions[1]
        for fighter in wounded[:4]:
            fighter.data["health"] = 0
        wounded[4].data["health"] /= 2
        for fighter in simulation.divisions[2]:
            fighter.data["health"] = 0
        units = [queries.create_unit_dict("Fixture I", "First Country", self.library) for _ in range(3)]
        for unit in units:
            unit["max_health"] = 1000  # Campaign health is written back as the same fraction.
        province = {"units": list(units)}
        simulation.winner = 0
        combat.apply_campaign_result(simulation, units, province, ([], []))
        self.assertAlmostEqual(units[0]["health"], 550)
        self.assertAlmostEqual(units[1]["health"], 1000)
        self.assertEqual(province["units"], units[:2])
        self.assertEqual(len(healthy), 10)

    def test_artillery_sits_out_campaign_battles_and_only_the_losers_is_destroyed(self):
        nations = {"Fixture A": {"at_war_with": ["Fixture B"]}, "Fixture B": {"at_war_with": ["Fixture A"]}}
        player, foe = (queries.create_unit_dict("Fixture I", owner, self.library) for owner in ("Fixture A", "Fixture B"))
        our_gun, their_gun = (queries.create_unit_dict("Fixture Gun I", owner, self.library)
                              for owner in ("Fixture A", "Fixture B"))
        tile = [our_gun, player, their_gun, foe]
        province = {"units": list(tile)}
        self.assertEqual(combat.campaign_forces(player, province, nations, self.library), ([player], [foe]))
        artillery = combat.campaign_artillery(player, province, nations, self.library)
        self.assertEqual(artillery, ([our_gun], [their_gun]))
        # Hostile artillery alone is an encounter with no enemy army: the player wins without a battle.
        lone = {"units": [our_gun, player, their_gun]}
        self.assertEqual(combat.campaign_forces(player, lone, nations, self.library), ([player], []))
        combat.win_against_artillery(player, lone, nations, self.library)
        self.assertEqual(lone["units"], [our_gun, player])
        self.assertEqual(their_gun["health"], 0)
        self.assertIsNone(combat.campaign_forces(player, {"units": [player, our_gun]}, nations, self.library))
        for winner, survivor, destroyed in ((0, our_gun, their_gun), (1, their_gun, our_gun)):
            with self.subTest(winner=winner):
                for unit in tile:
                    unit["health"] = unit["max_health"]
                province["units"] = list(tile)
                simulation = combat.BattleSimulation(self.library, [player], [foe])
                simulation.winner = winner
                combat.apply_campaign_result(simulation, [player, foe], province, artillery)
                self.assertEqual(survivor["health"], survivor["max_health"])
                self.assertNotIn(destroyed, province["units"])
                self.assertIn(survivor, province["units"])

    def test_losing_the_controlled_sub_unit_ends_control_without_taking_over_another(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}):
            simulation = combat.BattleSimulation(self.library, ["Fixture I", "Fixture I"], ["Fixture I"],
                                                 controlled_index=1)
        hold_still(simulation)
        division = simulation.divisions[1]
        first = simulation.controlled
        self.assertIs(first, division[len(division) // 2])  # The middle of the line.
        first.data["health"] = 0
        simulation.advance(combat.FIXED_STEP)
        self.assertIs(simulation.controlled, first)
        self.assertFalse(simulation.controlled.alive)
        # The division's other sub-units still count for the campaign, and they fight on automatically.
        self.assertTrue(simulation.controlled_division_alive)
        for fighter in division:
            fighter.data["health"] = 0
        simulation.advance(combat.FIXED_STEP)
        self.assertFalse(simulation.controlled_division_alive)
        self.assertIsNone(simulation.winner)  # The rest of the friendly army fights on.

    def test_normal_game_forecast_treats_the_armies_as_countries_at_war(self):
        from map_logic.system32 import combat_forecast

        def roster(name, owner, count=1):
            return [queries.create_unit_dict(name, owner, self.library) for _ in range(count)]

        strong, weak = roster("Fixture II", "First Country", 2), roster("Fixture I", "First Country")
        before = copy.deepcopy([strong, weak])
        with patch("data.queries.get_unit_library", return_value=self.library):
            winner, turns = combat.normal_game_forecast(strong, weak)
            # The same countries on both sides still fight, and nationality changes nothing.
            self.assertEqual(combat.normal_game_forecast(roster("Fixture II", "Second Country", 2), weak),
                             (winner, turns))
            self.assertEqual(combat.normal_game_forecast(weak, strong)[0], 1)
            nations = {combat.FORECAST_NATIONS[0]: {"at_war_with": [combat.FORECAST_NATIONS[1]]}}
            expected = combat_forecast.estimated_combat_outcome(
                [[dict(unit, owner=nation) for unit in side]
                 for nation, side in zip(combat.FORECAST_NATIONS, (strong, weak))], nations)
        self.assertEqual((winner, turns), (expected["winner_side"], expected["turns"]))
        self.assertEqual(winner, 0)
        self.assertGreaterEqual(turns, 1)
        self.assertEqual([strong, weak], before)

    def test_sub_units_draw_their_own_temperament_and_a_seed_repeats_it(self):
        def temperaments(seed):
            with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 6}):
                simulation = combat.BattleSimulation(self.library, ["Fixture I"] * 3, ["Fixture I"], seed=seed)
            return [(f.hold, f.pace, f.start_delay, f.wander, f.wander_period, f.wander_phase)
                    for f in simulation.fighters]

        first = temperaments(3)
        self.assertEqual(first, temperaments(3))
        self.assertNotEqual(first, temperaments(4))
        self.assertGreater(len(set(first)), 1)
        for hold, pace, delay, wander, period, phase in first:
            self.assertTrue(combat.AI_HOLD_RANGE[0] <= hold <= combat.AI_HOLD_RANGE[1])
            self.assertTrue(combat.AI_PACE[0] <= pace <= combat.AI_PACE[1])
            self.assertTrue(combat.AI_START_DELAY[0] <= delay <= combat.AI_START_DELAY[1])
            self.assertTrue(0 <= wander <= combat.AI_WANDER_ANGLE)
            self.assertTrue(combat.AI_WANDER_PERIOD[0] <= period <= combat.AI_WANDER_PERIOD[1])

    def ready_division(self, simulation, index):
        """Remove the random temperament from one division so a test can measure its movement."""
        for fighter in simulation.divisions[index]:
            fighter.start_delay, fighter.pace, fighter.wander, fighter.hold = 0.0, 1.0, 0.0, combat.AI_HOLD_RANGE[0]
        return simulation.divisions[index]

    def test_ai_sub_units_wait_out_their_start_delay(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        unit, = self.ready_division(simulation, 0)
        unit.start_delay = 1.0
        start = unit.x
        simulation.advance(0.5)
        self.assertEqual(unit.x, start)
        simulation.advance(1.5)
        self.assertGreater(unit.x, start)

    def test_divisions_close_in_keeping_their_line_order_on_either_side(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 6}):
            simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        for side, division in enumerate(simulation.divisions):
            center = (sum(f.x for f in division) / len(division), sum(f.y for f in division) / len(division))
            # Straight across from the division's center, so the sideways offsets are purely vertical.
            objective = SimpleNamespace(x=simulation.divisions[1 - side][0].x, y=center[1])
            points =[combat.BattleSimulation.advance_point(fighter, center, objective)[0] for fighter in division]
            # Each sub-unit heads beside the objective at its own place, top to bottom as it deployed.
            self.assertEqual([round(y - objective.y, 6) for x, y in points], [round(f.slot, 6) for f in division])
            self.assertTrue(all(round(x, 6) == round(objective.x, 6) for x, y in points))

    def test_a_sub_unit_ahead_of_its_division_slows_down_to_wait(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 6}):
            simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        division = self.ready_division(simulation, 0)
        leader, *rest = division
        leader.x += combat.COHESION_SLACK * 4  # Toward the enemy, well ahead of the others.
        simulation.advance(1.0)
        self.assertLess(leader.speed, leader.max_speed * combat.COHESION_THROTTLE + 1e-6)
        self.assertTrue(all(fighter.speed > leader.speed for fighter in rest))

    def course_setup(self, shape):
        """An AI sub-unit with a neutral temperament, given a battlefield shape so it takes that shape's behavior."""
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        unit, = self.ready_division(simulation, 0)
        unit.shape = shape
        enemy = simulation.divisions[1][0]
        # The enemy straight ahead, on the division's own course.
        return simulation, unit, (unit.x, unit.y), SimpleNamespace(x=unit.x + 2000, y=unit.y), enemy

    def test_infantry_keeps_advancing_without_halting_until_in_position(self):
        simulation, unit, center, objective, _enemy = self.course_setup("infantry")
        far = combat.WEAPON_RANGE * 2
        for second in range(10):
            simulation.elapsed = float(second)
            self.assertEqual(simulation._ai_course(unit, far, 0.0, center, objective)[0], unit.pace)
        in_position = combat.ENGAGEMENT_RANGE * unit.hold
        self.assertEqual(simulation._ai_course(unit, in_position, 0.3, center, objective), (0.0, 0.3))

    def test_tanks_swing_out_to_one_side_of_the_objective(self):
        simulation, unit, center, objective, _enemy = self.course_setup("tank")
        for flank in (1, -1):
            unit.flank = flank
            unit.flank_goal = None
            throttle, heading = simulation._ai_course(unit, combat.WEAPON_RANGE * 2, 0.0, center, objective)
            goal_x, goal_y = unit.flank_goal
            self.assertAlmostEqual(heading, math.atan2(goal_y - unit.y, goal_x - unit.x))
            self.assertAlmostEqual(goal_y - objective.y, unit.slot + flank * combat.FLANK_OFFSET)
            self.assertGreater(throttle, 0)

    def test_cavalry_charges_in_close_then_withdraws_and_charges_again(self):
        simulation, unit, center, objective, _enemy = self.course_setup("cavalry")
        toward = 0.0
        inside_hold = combat.ENGAGEMENT_RANGE * (unit.hold + combat.CHARGE_CLOSE) / 2
        # It keeps charging inside the distance where other units would hold.
        self.assertEqual(simulation._ai_course(unit, inside_hold, toward, center, objective)[0], unit.pace)
        close = combat.ENGAGEMENT_RANGE * combat.CHARGE_CLOSE
        self.assertEqual(simulation._ai_course(unit, close, toward, center, objective), (unit.pace, math.pi))
        self.assertTrue(unit.withdrawing)
        self.assertEqual(simulation._ai_course(unit, inside_hold, toward, center, objective), (unit.pace, math.pi))
        back = combat.ENGAGEMENT_RANGE * unit.hold
        self.assertEqual(simulation._ai_course(unit, back, toward, center, objective)[1] % math.tau, 0.0)
        self.assertFalse(unit.withdrawing)

    def test_armored_cars_keep_long_range_and_back_away_from_close_enemies(self):
        simulation, unit, center, objective, _enemy = self.course_setup("armored_car")
        toward = 0.0
        too_close = combat.ENGAGEMENT_RANGE * combat.SKIRMISH_BACK_OFF * 0.9
        self.assertEqual(simulation._ai_course(unit, too_close, toward, center, objective), (-unit.pace, toward))
        in_position = combat.ENGAGEMENT_RANGE * (combat.SKIRMISH_BACK_OFF + combat.SKIRMISH_HOLD) / 2
        self.assertEqual(simulation._ai_course(unit, in_position, toward, center, objective), (0.0, toward))
        self.assertGreater(simulation._ai_course(unit, combat.WEAPON_RANGE, toward, center, objective)[0], 0)

    def test_badly_hurt_sub_units_fall_back_out_of_range_and_hit_ones_sidestep(self):
        simulation, unit, center, objective, _enemy = self.course_setup("infantry")
        toward = 0.0
        unit.data["health"] = unit.data["max_health"] * combat.FALL_BACK_HEALTH * 0.9
        self.assertEqual(simulation._ai_course(unit, combat.WITHDRAW_RANGE * 0.5, toward, center, objective),
                         (unit.pace, math.pi))
        self.assertEqual(simulation._ai_course(unit, combat.WITHDRAW_RANGE, toward, center, objective), (0.0, toward))
        unit.data["health"] = unit.data["max_health"]
        unit.dodge, unit.dodge_heading = combat.DODGE_SECONDS, -math.pi / 2
        self.assertEqual(simulation._ai_course(unit, combat.WEAPON_RANGE * 0.5, toward, center, objective),
                         (unit.pace, -math.pi / 2))

    def test_a_hit_starts_a_sidestep_only_for_fast_ai_units(self):
        for controlled, speed, dodges in ((None, combat.DODGE_MIN_SPEED, True), (0, combat.DODGE_MIN_SPEED, False),
                                          (None, combat.DODGE_MIN_SPEED - 1, False)):
            with self.subTest(controlled=controlled, speed=speed):
                simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"],
                                                     controlled_index=controlled)
                hold_still(simulation)
                target, source = simulation.fighters
                target.data["speed"] = speed
                simulation.projectiles = [combat.Projectile(
                    source, dict(source.data, attack=30), target.x + 5, target.y, -300, 0, 1)]
                simulation.advance(combat.FIXED_STEP)
                self.assertLess(target.data["health"], target.data["max_health"])
                self.assertEqual(target.dodge > 0, dodges)

    def test_fast_sub_units_not_about_to_fire_sidestep_shots_headed_their_way(self):
        speed = combat.PROJECTILE_SPEED
        lookahead = speed * combat.DODGE_LOOKAHEAD

        def watch(start_dx, start_dy, velocity=-speed, *, controlled=None, ready=False, own_shot=False,
                  ally_shot=False, unit_speed=combat.DODGE_MIN_SPEED):
            simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"],
                                                 controlled_index=controlled)
            hold_still(simulation)  # Both reloading, so neither is about to fire.
            unit, shooter = simulation.fighters
            unit.data["speed"] = unit_speed
            shooter.x = unit.x + combat.WEAPON_RANGE / 2
            if ready:
                unit.cooldown, unit.target = 0, shooter
            source = unit if own_shot else shooter
            if ally_shot:
                source = combat.Fighter(dict(unit.data), unit.side, unit.x - 100, unit.y, unit.shape)
            simulation.projectiles = [combat.Projectile(
                source, dict(source.data), unit.x + start_dx, unit.y + start_dy, velocity, 0, 1)]
            crowds = [combat._Grid([f for f in simulation.fighters if f.side == side], combat.GRID_CELL)
                      for side in (0, 1)]
            simulation._dodge_incoming(crowds)
            return unit

        # A shot about to pass just below the unit: it steps up, away from the shot's path.
        unit = watch(lookahead / 2, combat.UNIT_RADIUS)
        self.assertEqual(unit.dodge, combat.DODGE_SECONDS)
        self.assertAlmostEqual(math.cos(unit.dodge_heading), 0)
        self.assertLess(math.sin(unit.dodge_heading), 0)
        # Shots hurt allies too, so an ally's shot is dodged like an enemy's.
        self.assertEqual(watch(lookahead / 2, 0, ally_shot=True).dodge, combat.DODGE_SECONDS)
        for label, case in (
                ("passing wide", dict(start_dx=lookahead / 2, start_dy=combat.DODGE_DANGER * 2)),
                ("moving away", dict(start_dx=-lookahead / 2, start_dy=0)),
                ("still far off", dict(start_dx=lookahead + 100, start_dy=0)),
                ("about to fire", dict(start_dx=lookahead / 2, start_dy=0, ready=True)),
                ("player's unit", dict(start_dx=lookahead / 2, start_dy=0, controlled=0)),
                ("its own shot", dict(start_dx=lookahead / 2, start_dy=0, own_shot=True)),
                ("too slow", dict(start_dx=lookahead / 2, start_dy=0, unit_speed=combat.DODGE_MIN_SPEED - 1))):
            with self.subTest(label):
                self.assertEqual(watch(**case).dodge, 0)

    def test_each_hit_carries_the_shooters_share_of_its_divisions_damage(self):
        for size in (1, 3, 6):
            with self.subTest(size=size), patch.dict(combat.SUBUNIT_COUNTS, {"infantry": size}):
                simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
                hold_still(simulation)
                source = simulation.divisions[0][0]
                target = simulation.divisions[1][0]
                self.assertAlmostEqual(source.attack_share, 1 / size)
                # The full attack still meets the full defense; only the damage that gets through is divided.
                self.assertEqual(source.data["attack"], self.library["Fixture I"]["attack"])
                target.data.update(defense=10, health=500, max_health=500)
                simulation.projectiles = [combat.Projectile(
                    source, dict(source.data, attack=70, health=source.data["max_health"]),
                    target.x - 5, target.y, 300, 0, 1)]
                simulation.advance(combat.FIXED_STEP)
                self.assertEqual(target.data["health"], 500 - math.ceil((70 - 10) / size) * combat.DAMAGE_SCALE)

    def test_targets_prefer_a_wounded_enemy_near_the_nearest_and_skip_ones_they_cannot_hurt(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"] * 3)
        shooter, nearest, wounded, armored = simulation.fighters
        nearest.x, nearest.y = shooter.x + 500, shooter.y
        wounded.x, wounded.y = shooter.x + 560, shooter.y
        armored.x, armored.y = shooter.x + 400, shooter.y
        armored.data["type"] = "Fixture Armor"  # A type of its own, so its defense is judged separately.
        armored.data["defense"] = shooter.data["attack"] * 2
        enemies = combat._Grid([nearest, wounded, armored], combat.TARGET_CELL)
        self.assertIs(simulation._choose_target(shooter, enemies), nearest)
        wounded.data["health"] = wounded.data["max_health"] * 0.2
        self.assertIs(simulation._choose_target(shooter, enemies), wounded)

    def test_shots_leave_slightly_off_aim_so_long_range_shots_can_miss(self):
        for distance, hits in ((100, True), (900, False)):
            with self.subTest(distance=distance):
                simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
                hold_still(simulation)
                player, target = simulation.fighters
                target.x, target.y = player.x + distance, player.y
                player.cooldown = 0
                # The largest error each time: a near target is still hit, a far one is missed.
                simulation._rng = SimpleNamespace(uniform=lambda low, high: high, choice=lambda options: options[0])
                simulation.set_player_input(fire=True)
                simulation.advance(1.0)
                self.assertEqual(target.data["health"] < target.data["max_health"], hits)
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0, seed=2)
        hold_still(simulation)
        player = simulation.controlled
        angles = set()
        for _ in range(20):
            player.cooldown = 0
            simulation.projectiles = []
            simulation.set_player_input(fire=True)
            simulation.advance(combat.FIXED_STEP)
            shot, = simulation.projectiles
            angles.add(round(math.atan2(shot.vy, shot.vx), 9))
        self.assertGreater(len(angles), 1)
        self.assertTrue(all(abs(angle - player.aim) <= combat.SHOT_SPREAD for angle in angles))

    def test_nearest_enemy_search_matches_checking_every_unit(self):
        rng = random.Random(5)
        width, height = combat.ARENA_SIZE
        units = [SimpleNamespace(x=rng.uniform(0, width), y=rng.uniform(0, height)) for _ in range(200)]
        for cell in (combat.GRID_CELL, combat.TARGET_CELL):
            grid = combat._Grid(units, cell)
            for _ in range(100):
                x, y = rng.uniform(0, width), rng.uniform(0, height)
                expected = min(math.hypot(unit.x - x, unit.y - y) for unit in units)
                found = grid.nearest(x, y)
                self.assertAlmostEqual(math.hypot(found.x - x, found.y - y), expected)
        self.assertIsNone(combat._Grid([], combat.GRID_CELL).nearest(10, 10))


class CloseCombatTests(unittest.TestCase):
    def setUp(self):
        self.library = fixture_library()
        self.enterContext(single_subunits())
        self.enterContext(patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", 1.0))

    def encounter(self, *, controlled=None, shapes=("infantry", "infantry"), gap=None):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"],
                                             controlled_index=controlled, seed=3)
        for index, (unit, shape) in enumerate(zip(simulation.fighters, shapes)):
            unit.shape = shape
            unit.x, unit.y = 1000 + index * (combat.UNIT_RADIUS * 2 + 4 if gap is None else gap), 500
            unit.angle = unit.aim = index * math.pi
            unit.wander = unit.start_delay = 0
        return simulation

    def test_player_and_ai_fire_bullets_at_point_blank_with_normal_reload(self):
        for controlled in (None, 0):
            for health in (100, 1):
                with self.subTest(controlled=controlled, health=health):
                    simulation = self.encounter(controlled=controlled)
                    simulation.on_shot = Mock()
                    hold_still(simulation)
                    source, target = simulation.fighters
                    source.cooldown = 0
                    source.data["health"] = health
                    target.data["defense"] = 10
                    expected = simulation.damage_amount(source.data, target.data, source.attack_share)
                    simulation.set_player_input(fire=True)
                    with patch.object(simulation, "_fire_shot", wraps=simulation._fire_shot) as fire:
                        simulation.advance(combat.FIXED_STEP)
                        self.assertEqual(fire.call_count, 1)
                        simulation.on_shot.assert_called_once_with(source)
                        self.assertAlmostEqual(target.data["health"], target.data["max_health"] - expected)
                        self.assertEqual(source.cooldown, combat.FIRE_INTERVAL)
                        simulation.advance(combat.FIRE_INTERVAL / 2)
                        self.assertEqual(fire.call_count, 1)
                        simulation.advance(combat.FIRE_INTERVAL / 2 + combat.FIXED_STEP)
                        self.assertEqual(fire.call_count, 2)

    def test_point_blank_shooting_requires_fire_and_aim_and_respects_defense(self):
        for firing, aim, defense, damages in ((False, 0, 0, False), (True, math.pi, 0, False),
                                              (True, 0, 100, False), (True, 0, 0, True)):
            with self.subTest(firing=firing, aim=aim, defense=defense):
                simulation = self.encounter(controlled=0)
                hold_still(simulation)
                player, target = simulation.fighters
                player.cooldown = 0
                player.angle = player.aim = aim
                target.data["defense"] = defense
                simulation.set_player_input(fire=firing)
                simulation.advance(combat.FIXED_STEP)
                self.assertEqual(target.data["health"] < 100, damages)

    def test_ram_eligibility_uses_unit_speed_for_every_shape_and_side_including_allies(self):
        for shape in combat.CONTACT_MASS:
            for speed in (combat.RAM_MIN_UNIT_SPEED - 0.01, combat.RAM_MIN_UNIT_SPEED,
                          combat.RAM_MIN_UNIT_SPEED + 1):
                for source_side in (0, 1):
                    for allied in (False, True):
                        with self.subTest(shape=shape, speed=speed, side=source_side, allied=allied):
                            simulation = self.encounter(gap=combat.UNIT_RADIUS * 2 + 1)
                            source, target = simulation.fighters[::1 if source_side == 0 else -1]
                            source.shape = shape
                            source.data["speed"] = speed
                            if allied:
                                target.side = source.side
                            direction = 1 if source_side == 0 else -1
                            hits = self.move_contact(simulation, [
                                (source, direction * combat.RAM_REFERENCE_SPEED * combat.FIXED_STEP, 0),
                                (target, 0, 0)])
                            loss = sum(loss for victim, loss, _source in hits if victim is target)
                            self.assertEqual(loss > 0, not allied and speed >= combat.RAM_MIN_UNIT_SPEED)

    def test_ram_damage_speed_and_mass_multipliers_apply_after_bullet_damage(self):
        for closing in (combat.RAM_MIN_SPEED, combat.RAM_REFERENCE_SPEED,
                        combat.RAM_REFERENCE_SPEED * combat.RAM_MAX_STRENGTH * 2):
            for mass_ratio in (0.5, 1, 2):
                with self.subTest(closing=closing, mass_ratio=mass_ratio):
                    simulation = self.encounter(shapes=("cavalry", "infantry"),
                                                gap=combat.UNIT_RADIUS * 2 + 1)
                    source, target = simulation.fighters
                    target.data["defense"] = 10
                    bullet = simulation.damage_amount(source.data, target.data, source.attack_share)
                    with patch.dict(combat.CONTACT_MASS, cavalry=mass_ratio, infantry=1):
                        hits = self.move_contact(simulation, [(source, closing * combat.FIXED_STEP, 0),
                                                             (target, 0, 0)])
                    strength = min(combat.RAM_MAX_STRENGTH, closing / combat.RAM_REFERENCE_SPEED)
                    expected = bullet * combat.RAM_DAMAGE * strength * min(1, mass_ratio)
                    self.assertAlmostEqual(sum(loss for victim, loss, _source in hits if victim is target), expected)

    def test_ram_impact_damage_does_not_fall_with_attacker_health(self):
        losses = []
        for health in (100, 1):
            simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.UNIT_RADIUS * 2 + 2)
            source, target = simulation.fighters
            source.data["health"] = health
            target.data["defense"] = 10
            hits = self.move_contact(simulation, [(source, combat.RAM_REFERENCE_SPEED * combat.FIXED_STEP, 0),
                                                   (target, 0, 0)])
            losses.append(sum(loss for victim, loss, _source in hits if victim is target))
        self.assertGreater(losses[0], 0)
        self.assertEqual(losses[0], losses[1])

    def test_simultaneous_point_blank_bullets_can_destroy_both_units(self):
        self.library["Fixture I"]["attack"] = 1000
        simulation = self.encounter()
        simulation.advance(combat.FIXED_STEP)
        self.assertTrue(all(not unit.alive for unit in simulation.fighters))
        self.assertEqual(simulation.winner, 1)

    def test_ai_ram_eligibility_uses_speed_for_every_shape_on_both_sides(self):
        for shape in combat.CONTACT_MASS:
            target_shape = "tank" if shape == "infantry" else "infantry"
            for speed in (combat.RAM_MIN_UNIT_SPEED - 0.01, combat.RAM_MIN_UNIT_SPEED):
                for side in (0, 1):
                    with self.subTest(shape=shape, speed=speed, side=side):
                        simulation = self.encounter(gap=120)
                        unit, target = simulation.fighters[::1 if side == 0 else -1]
                        unit.shape, unit.pace = shape, 1
                        unit.data["speed"] = speed
                        target.shape = target_shape
                        target.data["health"] = target.data["max_health"] * combat.RAM_WOUNDED_TARGET / 2
                        target.cooldown = 0
                        sides = [[fighter for fighter in simulation.fighters if fighter.side == team]
                                 for team in (0, 1)]
                        with patch.dict(combat.CONTACT_MASS, {shape: 4, target_shape: 1}):
                            simulation._prepare_rams(sides, [combat._Grid(team, combat.GRID_CELL) for team in sides])
                        self.assertEqual(unit.ram_committed, speed >= combat.RAM_MIN_UNIT_SPEED)
                        if unit.ram_committed:
                            self.assertIs(unit.target, target)

    def test_ram_commitment_ignores_dodge_only_during_final_approach_and_aborts_when_hurt(self):
        simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.RAM_COMMIT_RANGE - 1)
        unit, target = simulation.fighters
        unit.ram_committed, unit.dodge, unit.dodge_heading = True, 1.0, math.pi / 2
        unit.target = target
        center = (unit.x, unit.y)
        throttle, heading = simulation._ai_course(unit, target.x - unit.x, 0, center, target)
        self.assertGreater(throttle, 0)
        self.assertEqual(heading, 0)
        course = simulation._ai_course(unit, combat.RAM_COMMIT_RANGE + 1, 0, center, target)
        self.assertEqual(course[1], unit.dodge_heading)
        unit.data["health"] = unit.data["max_health"] * combat.FALL_BACK_HEALTH / 2
        simulation._ai_course(unit, combat.RAM_COMMIT_RANGE, 0, center, target)
        self.assertFalse(unit.ram_committed)

    def test_ai_rams_only_with_runup_mass_advantage_and_safe_approach(self):
        for shape, target_shape, health, speed, gap, expected in (
                ("tank", "infantry", 20, 3, 120, True),
                ("tank", "tank", 20, 3, 120, False),
                ("tank", "infantry", 100, 3, 120, False),
                ("tank", "infantry", 20, 0, 120, False),
                ("tank", "infantry", 20, 3, 20, False)):
            with self.subTest(target_shape=target_shape, health=health, speed=speed, gap=gap):
                simulation = self.encounter(shapes=(shape, target_shape), gap=gap)
                unit, target = simulation.fighters
                unit.data["speed"], target.data["health"] = speed, health
                target.cooldown = 0
                sides = [[unit], [target]]
                simulation._prepare_rams(sides, [combat._Grid(side, combat.GRID_CELL) for side in sides])
                self.assertEqual(unit.ram_committed, expected)

    def test_distant_supporting_enemy_fire_prevents_an_ai_ram(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"] * 3, seed=2)
        unit, target, *support = simulation.fighters
        unit.shape = "tank"
        unit.x, unit.y = 1000, 500
        target.x, target.y = unit.x + combat.RAM_SUPPORT_RANGE / 2, unit.y
        target.data["health"] = 20
        for enemy in support:
            enemy.x, enemy.y = unit.x + (combat.RAM_SUPPORT_RANGE + combat.WEAPON_RANGE) / 2, unit.y
        sides = [[unit], [target, *support]]
        simulation._prepare_rams(sides, [combat._Grid(side, combat.GRID_CELL) for side in sides])
        self.assertFalse(unit.ram_committed)

    def test_flank_is_completed_even_after_entering_weapon_hold_range(self):
        simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.ENGAGEMENT_RANGE / 2)
        unit, target = simulation.fighters
        unit.hold, unit.pace = 0.9, 1.0
        throttle, _heading = simulation._ai_course(unit, target.x - unit.x, 0, (unit.x, unit.y), target)
        self.assertGreater(throttle, 0)
        self.assertFalse(unit.flank_complete)
        unit.x, unit.y = unit.flank_goal
        simulation._ai_course(unit, combat.ENGAGEMENT_RANGE / 2, 0, (unit.x, unit.y), target)
        self.assertTrue(unit.flank_complete)

    def test_both_armies_advance_together_and_divisions_get_different_lanes(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"] * 3, ["Fixture I"] * 3, seed=3)
        starts = [(unit.x, unit.y) for unit in simulation.fighters]
        simulation.advance(2)
        self.assertTrue(any(unit.x > start[0] for unit, start in zip(simulation.fighters[:3], starts[:3])))
        self.assertTrue(any(unit.x < start[0] for unit, start in zip(simulation.fighters[3:], starts[3:])))
        self.assertEqual(len({division[0].lane for division in simulation.divisions[:3]}), 3)

    def test_ai_movement_uses_the_same_rules_on_both_sides_for_every_shape(self):
        for shape in combat.MOBILITY:
            for situation in ("advance", "hold", "flank", "withdraw", "ram"):
                with self.subTest(shape=shape, situation=situation):
                    gap = combat.ENGAGEMENT_RANGE * (2 if situation in ("advance", "flank") else 0.7)
                    simulation = self.encounter(shapes=(shape, shape), gap=gap)
                    first, second = simulation.fighters
                    for unit in simulation.fighters:
                        unit.hold, unit.pace = 0.8, 1.0
                        unit.cooldown, unit.retarget = 1000, 1000
                        unit.flank = 1
                        unit.flank_complete = situation != "flank"
                        unit.ram_committed = situation == "ram"
                        if situation == "withdraw":
                            unit.data["health"] = unit.data["max_health"] * combat.FALL_BACK_HEALTH / 2
                    for unit, target in ((first, second), (second, first)):
                        unit.target = target
                        simulation._drive_ai(unit, combat._Grid([target], combat.TARGET_CELL), combat.FIXED_STEP,
                                             [], (unit.x, unit.y), target)
                    self.assertAlmostEqual(first.speed, second.speed)
                    self.assertAlmostEqual(abs(first.turn_rate), abs(second.turn_rate))

    def test_infantry_on_both_sides_holds_at_its_preferred_firing_distance(self):
        simulation = self.encounter(gap=combat.ENGAGEMENT_RANGE * 0.7)
        first, second = simulation.fighters
        for unit, target in ((first, second), (second, first)):
            unit.hold, unit.pace = 0.8, 1.0
            unit.cooldown = 1000
            simulation._drive_ai(unit, combat._Grid([target], combat.TARGET_CELL), combat.FIXED_STEP,
                                 [], (unit.x, unit.y), target)
            self.assertEqual(unit.speed, 0)

    def test_depleted_armies_keep_fighting_instead_of_both_retreating_forever(self):
        simulation = self.encounter(gap=combat.WEAPON_RANGE / 2)
        for unit in simulation.fighters:
            unit.data["health"] = unit.data["max_health"] * combat.FALL_BACK_HEALTH / 2
        simulation.advance(90)
        self.assertIsNotNone(simulation.winner)

    def test_reversing_vehicle_retreat_keeps_the_hull_facing_the_enemy(self):
        simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.WITHDRAW_RANGE / 2)
        unit, target = simulation.fighters
        unit.data["health"] = unit.data["max_health"] * combat.FALL_BACK_HEALTH / 2
        throttle, heading = simulation._ai_course(unit, target.x - unit.x, 0, (unit.x, unit.y), target)
        self.assertLess(throttle, 0)
        self.assertEqual(heading, 0)

    def move_contact(self, simulation, movements):
        living = [unit for unit in simulation.fighters if unit.alive]
        crowds = [combat._Grid([unit for unit in living if unit.side == side], combat.GRID_CELL) for side in (0, 1)]
        return simulation._resolve_contacts(living, crowds, movements, combat.FIXED_STEP)

    def test_fast_ram_displaces_light_target_slows_attacker_and_cannot_repeat_while_touching(self):
        simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.UNIT_RADIUS * 2 + 2)
        attacker, target = simulation.fighters
        speed = combat.RAM_REFERENCE_SPEED
        damage = self.move_contact(simulation, [(attacker, speed * combat.FIXED_STEP, 0), (target, 0, 0)])
        self.assertEqual(len(damage), 1)
        self.assertIs(damage[0][0], target)
        self.assertGreater(damage[0][1], 0)
        self.assertGreater(target.x, 1000 + combat.UNIT_RADIUS * 2 + 2)
        self.assertLess(attacker.speed, speed)
        again = self.move_contact(simulation, [(attacker, speed * combat.FIXED_STEP, 0), (target, 0, 0)])
        self.assertEqual(again, [])
        target.x += combat.CONTACT_RELEASE_DISTANCE * 2
        self.move_contact(simulation, [(attacker, 0, 0), (target, 0, 0)])
        target.x = attacker.x + combat.UNIT_RADIUS * 2 + 2
        self.assertTrue(self.move_contact(simulation, [(attacker, speed * combat.FIXED_STEP, 0), (target, 0, 0)]))

    def test_stationary_and_glancing_contacts_never_deal_ram_damage(self):
        for delta in ((0, 0), (0, 10)):
            with self.subTest(delta=delta):
                simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.UNIT_RADIUS * 2)
                attacker, target = simulation.fighters
                damage = self.move_contact(simulation, [(attacker, *delta), (target, 0, 0)])
                self.assertEqual(damage, [])

    def test_fast_contact_with_an_ally_deals_no_ram_damage_but_an_enemy_takes_it(self):
        for same_side in (True, False):
            with self.subTest(same_side=same_side):
                simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.UNIT_RADIUS * 2 + 2)
                attacker, target = simulation.fighters
                if same_side:
                    target.side = attacker.side
                damage = self.move_contact(simulation, [(attacker, combat.RAM_REFERENCE_SPEED * combat.FIXED_STEP, 0),
                                                        (target, 0, 0)])
                if same_side:
                    self.assertEqual(damage, [])
                else:
                    self.assertEqual(len(damage), 1)
                    self.assertIs(damage[0][0], target)
                    self.assertGreater(damage[0][1], 0)

    def test_ram_capable_ai_units_brake_before_hitting_allies_for_every_shape(self):
        for shape in combat.CONTACT_MASS:
            with self.subTest(shape=shape):
                simulation = self.encounter(shapes=(shape, "infantry"), gap=combat.UNIT_RADIUS * 2 + 2)
                unit, ally = simulation.fighters
                ally.side = unit.side
                unit.angle = 0.0
                unit.data["speed"] = combat.RAM_MIN_UNIT_SPEED
                simulation._sides = [[unit, ally], []]
                braked = simulation._ally_safe_throttle(unit, 1.0)
                self.assertLess(braked * unit.max_speed, combat.RAM_MIN_SPEED)
                self.assertGreaterEqual(braked, 0)
                # Backing away, passing beside, or following a departing ally keeps full throttle.
                self.assertEqual(simulation._ally_safe_throttle(unit, -1.0), -1.0)
                ally.y += unit.radius + ally.radius + 10
                self.assertEqual(simulation._ally_safe_throttle(unit, 1.0), 1.0)
                ally.y, ally.vx = unit.y, unit.max_speed
                self.assertEqual(simulation._ally_safe_throttle(unit, 1.0), 1.0)
                # Units below the speed cutoff cannot deal ram damage and need no braking.
                unit.data["speed"] = combat.RAM_MIN_UNIT_SPEED - 1
                ally.vx = 0.0
                self.assertEqual(simulation._ally_safe_throttle(unit, 1.0), 1.0)

    def test_ram_damage_reaches_campaign_results_through_normal_simulation(self):
        simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.UNIT_RADIUS * 2 + 2)
        attacker, target = simulation.fighters
        attacker.speed = combat.RAM_REFERENCE_SPEED
        attacker.cooldown = target.cooldown = 1000
        with patch.object(simulation, "_drive_ai"):
            simulation.advance(combat.FIXED_STEP)
        self.assertLess(target.data["health"], target.data["max_health"])
        units = [queries.create_unit_dict("Fixture I", owner, self.library) for owner in ("First", "Second")]
        province = {"units": list(units)}
        simulation.winner = 0
        combat.apply_campaign_result(simulation, units, province, ([], []))
        self.assertEqual(units[1]["health"], target.data["health"])

    def test_ram_kill_credits_the_attacker(self):
        simulation = self.encounter(shapes=("tank", "infantry"), gap=combat.UNIT_RADIUS * 2 + 2)
        attacker, target = simulation.fighters
        attacker.speed = combat.RAM_REFERENCE_SPEED
        target.data["health"] = 1
        kills = []
        simulation.on_kill = lambda source, victim, cause: kills.append((source, victim, cause))
        with patch.object(simulation, "_drive_ai"):
            simulation.advance(combat.FIXED_STEP)
        self.assertEqual(kills, [(attacker, target, "ram")])

    def test_player_infantry_and_cavalry_ram_without_firing_or_using_the_gun_reload(self):
        for shape in ("infantry", "cavalry"):
            with self.subTest(shape=shape):
                simulation = self.encounter(controlled=0, shapes=(shape, "infantry"),
                                            gap=combat.UNIT_RADIUS * 2 + 2)
                source, target = simulation.fighters
                source.data["speed"] = combat.RAM_MIN_UNIT_SPEED
                source.speed = source.max_speed
                source.cooldown = combat.FIRE_INTERVAL / 2
                target.cooldown = 1000
                simulation.on_shot = Mock()
                simulation.set_player_input(throttle=1, fire=False)
                with patch.object(simulation, "_drive_ai"):
                    simulation.advance(combat.FIXED_STEP)
                self.assertLess(target.data["health"], target.data["max_health"])
                self.assertAlmostEqual(source.cooldown, combat.FIRE_INTERVAL / 2 - combat.FIXED_STEP)
                simulation.on_shot.assert_not_called()

    def test_equal_head_on_vehicles_stop_without_bouncing_or_crossing_even_at_high_speed(self):
        simulation = self.encounter(shapes=("tank", "tank"), gap=100)
        first, second = simulation.fighters
        damage = self.move_contact(simulation, [(first, 100, 0), (second, -100, 0)])
        self.assertAlmostEqual(first.speed, 0)
        self.assertAlmostEqual(second.speed, 0)
        self.assertAlmostEqual(second.x - first.x, first.radius + second.radius)
        self.assertEqual(len(damage), 2)

    def test_units_below_speed_cutoff_separate_without_ram_damage_and_rams_respect_armor(self):
        simulation = self.encounter(gap=10)
        first, second = simulation.fighters
        for unit in simulation.fighters:
            unit.data["speed"] = combat.RAM_MIN_UNIT_SPEED - 1
        self.assertEqual(self.move_contact(simulation, [(first, 5, 0), (second, -5, 0)]), [])
        self.assertAlmostEqual(second.x - first.x, first.radius + second.radius)
        simulation = self.encounter(shapes=("tank", "heavy_tank"), gap=combat.UNIT_RADIUS * 2)
        first, second = simulation.fighters
        second.data["defense"] = first.data["attack"] * 2
        damage = self.move_contact(simulation, [(first, combat.RAM_REFERENCE_SPEED * combat.FIXED_STEP, 0), (second, 0, 0)])
        self.assertTrue(all(loss == 0 for target, loss, _source in damage))


class TacticalTerrainTests(unittest.TestCase):
    def setUp(self):
        self.library = fixture_library()
        self.enterContext(single_subunits())
        self.enterContext(patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", 1.0))

    def field(self, *features):
        return battle_terrain.Battlefield("plains", combat.ARENA_SIZE, combat.UNIT_RADIUS, features)

    def encounter(self, *features, controlled=None):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"],
                                             seed=4, controlled_index=controlled, battlefield=self.field(*features))
        first, second = simulation.fighters
        first.x, first.y, second.x, second.y = 1000, 500, 1400, 500
        return simulation

    def test_each_terrain_repeats_with_seed_and_keeps_deployment_and_routes_clear(self):
        recipes = {
            "plains": (0, 5, 0, 0), "desert": (0, 0, 0, 0),
            "hills": (2, 0, 0, 0), "forest": (0, 12, 0, 0),
            "jungle": (0, 16, 0, 2), "mountain": (3, 0, 2, 1),
            "swamp": (0, 10, 0, 3),
        }
        self.enterContext(patch.dict(battle_terrain.TERRAIN_RECIPES, recipes, clear=True))
        for terrain in battle_terrain.TERRAIN_NAMES:
            with self.subTest(terrain=terrain):
                first = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], terrain=terrain, seed=4)
                second = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], terrain=terrain, seed=4)
                describe = lambda field: [(f.kind, f.x, f.y, f.radius, f.height) for f in field.features]
                self.assertEqual(describe(first.battlefield), describe(second.battlefield))
                self.assertTrue(all(first.battlefield.walkable((unit.x, unit.y)) for unit in first.fighters))
                start, end = [(unit.x, unit.y) for unit in first.fighters]
                path = first.battlefield.route(start, end)
                self.assertTrue(path)
                for point in path:
                    self.assertTrue(first.battlefield.clear_path(start, point))
                    start = point
                self.assertEqual(path[-1], end)
                if not any(recipes[terrain]):
                    self.assertEqual(first.battlefield.features, [])
                else:
                    self.assertTrue(first.battlefield.features)

    def test_trees_spread_beyond_the_front_gap_and_keep_full_armies_clear(self):
        width, height = combat.ARENA_SIZE
        front = (width - combat.SPAWN_FRONT_GAP) / 2
        roster = ["Fixture I"] * c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}):
            for terrain in ("forest", "jungle", "swamp"):
                for seed in (0, 4, 19):
                    with self.subTest(terrain=terrain, seed=seed):
                        simulation = combat.BattleSimulation(
                            self.library, roster, roster, terrain=terrain, seed=seed)
                        field = simulation.battlefield
                        trees = [feature for feature in field.features if feature.kind == "tree"]
                        self.assertTrue(any(tree.x < front for tree in trees))
                        self.assertTrue(any(tree.x > width - front for tree in trees))
                        self.assertTrue(any(tree.y < height / 4 for tree in trees))
                        self.assertTrue(any(tree.y > height * 3 / 4 for tree in trees))
                        self.assertTrue(all(field.walkable((unit.x, unit.y)) for unit in simulation.fighters))

    def test_individual_trees_cover_available_ground_without_dense_clusters(self):
        width = height = 4000
        cells = 4
        with patch.dict(battle_terrain.TERRAIN_RECIPES, {"forest": (0, 256, 0, 0)}):
            for seed in (0, 4, 19):
                with self.subTest(seed=seed):
                    field = battle_terrain.Battlefield.generate(
                        "forest", (width, height), 12, 3800, seed, deployment_half_height=0)
                    counts = {(x, y): 0 for x in range(cells) for y in range(cells)}
                    for tree in field.features:
                        counts[int(tree.x * cells / width), int(tree.y * cells / height)] += 1
                    self.assertTrue(all(counts.values()))
                    self.assertLess(max(counts.values()), 2 * len(field.features) / len(counts))

    def test_tree_trunks_set_the_hitbox_and_foliage_uses_a_shared_size_range(self):
        trees = [feature for seed in range(5) for feature in battle_terrain.Battlefield.generate(
            "jungle", combat.ARENA_SIZE, combat.UNIT_RADIUS, combat.SPAWN_FRONT_GAP, seed).features
                 if feature.kind == "tree"]
        self.assertEqual({tree.trunk for tree in trees}, set(battle_terrain.TREE_TRUNK_RADII))
        for tree in trees:
            self.assertEqual(tree.radius, battle_terrain.TREE_TRUNK_RADII[tree.trunk])
            smallest, largest = battle_terrain.TREE_FOLIAGE_RADII
            self.assertTrue(smallest <= tree.foliage_radius <= largest)
            self.assertTrue(-1.0 <= tree.shade <= 1.0)
        # Every trunk size the generator can choose has an image to draw it. Foliage is drawn without images.
        for size in battle_terrain.TREE_TRUNK_RADII:
            self.assertTrue(os.path.isfile(os.path.join(battle_screen.TERRAIN_ART_DIR, f"Trunk {size}.png")))

    def test_generated_terrain_keeps_gap_between_same_and_different_feature_types(self):
        recipes = {terrain: (10, 50, 10, 10) for terrain in ("mountain", "swamp")}
        with patch.dict(battle_terrain.TERRAIN_RECIPES, recipes), \
                patch.object(battle_terrain, "HILL_RADIUS", (80, 100)), \
                patch.object(battle_terrain, "HAZARD_RADIUS", (40, 60)):
            for terrain in recipes:
                for seed in (0, 4, 19):
                    with self.subTest(terrain=terrain, seed=seed):
                        field = battle_terrain.Battlefield.generate(
                            terrain, (2000, 2000), 12, 1600, seed, deployment_half_height=75)
                        expected = {"tree", "hill", "rock", battle_terrain.GAP_KINDS[terrain]}
                        self.assertEqual({feature.kind for feature in field.features}, expected)
                        for index, feature in enumerate(field.features):
                            for other in field.features[index + 1:]:
                                self.assertGreaterEqual(math.dist((feature.x, feature.y), (other.x, other.y)),
                                                        feature.radius + other.radius + battle_terrain.TERRAIN_FEATURE_GAP)

    def test_ground_hazards_block_motion_but_allow_shots_and_paths_go_around(self):
        for kind in ("chasm", "marsh"):
            with self.subTest(kind=kind):
                field = self.field(battle_terrain.Feature(kind, 1200, 500, 80))
                start, end = (1000, 500), (1400, 500)
                self.assertFalse(field.clear_path(start, end))
                self.assertIsNone(field.firing_blocker(start, end))
                self.assertNotEqual(field.move(start, end), end)
                route = field.route(start, end)
                self.assertTrue(route)
                for point in route:
                    self.assertTrue(field.clear_path(start, point))
                    start = point

    def test_destination_inside_obstacle_routes_to_open_ground(self):
        field = self.field(battle_terrain.Feature("rock", 1200, 500, 80, 150))
        start = (1000, 500)
        route = field.route(start, (1200, 500))
        self.assertTrue(route)
        self.assertTrue(field.walkable(route[-1]))
        for point in route:
            self.assertTrue(field.clear_path(start, point))
            start = point

    def test_tank_flank_uses_reachable_replacement_for_obstructed_destination(self):
        simulation = self.encounter(battle_terrain.Feature("rock", 1200, 500, 80, 150))
        unit, target = simulation.fighters
        unit.shape, unit.target, unit.flank_goal, unit.pace, unit.start_delay = "tank", target, (1200, 500), 1, 0
        simulation._terrain_course(unit, 1, 0, (unit.x, unit.y), target)
        self.assertNotEqual(unit.flank_goal, (1200, 500))
        self.assertTrue(simulation.battlefield.walkable(unit.flank_goal))
        unit.x, unit.y = unit.flank_goal
        simulation._ai_course(unit, math.dist((unit.x, unit.y), (target.x, target.y)),
                               0, (unit.x, unit.y), target)
        self.assertTrue(unit.flank_complete)

    def test_hill_blocks_low_shots_and_climbing_the_crest_opens_fire(self):
        field = self.field(battle_terrain.Feature("hill", 1200, 500, 150, 100))
        self.assertTrue(field.clear_path((1000, 500), (1400, 500)))
        self.assertIsNotNone(field.firing_blocker((1000, 500), (1400, 500)))
        self.assertIsNone(field.firing_blocker((1200, 500), (1400, 500)))
        self.assertIsNone(field.firing_blocker((1000, 500), (1200, 500)))

    def test_only_tank_shells_remove_trees_and_the_clearing_shot_stops(self):
        for shape in ("infantry", *combat.TANK_SHAPES):
            with self.subTest(shape=shape):
                tree = battle_terrain.Feature("tree", 1200, 500, 20, 100)
                simulation = self.encounter(tree)
                hold_still(simulation)
                source, target = simulation.fighters
                source.shape = shape
                before = target.data["health"]
                simulation.projectiles = [combat.Projectile(
                    source, dict(source.data), source.x, source.y, 18000, 0, 1)]
                simulation.advance(combat.FIXED_STEP)
                self.assertEqual(target.data["health"], before)
                self.assertEqual(simulation.projectiles, [])
                self.assertEqual(tree.destroyed, shape in combat.TANK_SHAPES)
                self.assertEqual(simulation.battlefield.revision, int(tree.destroyed))
                self.assertEqual(simulation.battlefield.firing_blocker((1000, 500), (1400, 500)) is None,
                                 tree.destroyed)

    def test_nonpenetrating_shot_hits_a_unit_before_terrain_further_along_the_shot(self):
        tree = battle_terrain.Feature("tree", 1500, 500, 20, 100)
        simulation = self.encounter(tree)
        hold_still(simulation)
        source, target = simulation.fighters
        source.shape = "tank"
        simulation.projectiles = [combat.Projectile(source, dict(source.data), 1000, 500, 18000, 0, 1,
                                                  penetration=0)]
        simulation.advance(combat.FIXED_STEP)
        self.assertLess(target.data["health"], target.data["max_health"])
        self.assertFalse(tree.destroyed)

    def test_tree_removal_invalidates_navigation_and_opens_a_direct_route(self):
        tree = battle_terrain.Feature("tree", 1200, 500, 20, 100)
        field = self.field(tree)
        start, end = (1000, 500), (1400, 500)
        self.assertGreater(len(field.route(start, end)), 1)
        field.destroy_tree(tree)
        self.assertEqual(field.route(start, end), [end])
        field.destroy_tree(tree)
        self.assertEqual(field.revision, 1)

    def test_ground_collision_applies_to_player_motion_and_contact_displacement(self):
        for controlled in (None, 0):
            with self.subTest(controlled=controlled):
                simulation = self.encounter(battle_terrain.Feature("rock", 1100, 500, 45, 150),
                                             controlled=controlled)
                source, target = simulation.fighters
                living = simulation.fighters
                crowds = [combat._Grid([unit], combat.GRID_CELL) for unit in living]
                simulation._resolve_contacts(living, crowds, [(source, 300, 0), (target, 0, 0)], combat.FIXED_STEP)
                self.assertLess(source.x, 1100)
                self.assertTrue(simulation.battlefield.walkable((source.x, source.y)))

    def test_ranged_falloff_counts_partial_impact_distance_after_defense(self):
        simulation = self.encounter()
        hold_still(simulation)
        source, target = simulation.fighters
        target.data["defense"] = 10
        traveled = combat.FALLOFF_START + 200
        simulation.projectiles = [combat.Projectile(
            source, dict(source.data), target.x - combat.UNIT_RADIUS - 5, target.y, 300, 0, 1,
            distance=traveled)]
        source.x -= 300  # Shooter movement cannot change a shot's traveled distance.
        simulation.advance(combat.FIXED_STEP)
        expected = simulation.damage_amount(source.data, target.data, source.attack_share,
                                             simulation.ranged_multiplier(traveled + 5))
        self.assertAlmostEqual(target.data["health"], target.data["max_health"] - expected)
        self.assertEqual(simulation.ranged_multiplier(0), 1)
        self.assertAlmostEqual(simulation.ranged_multiplier(combat.WEAPON_RANGE * 2), combat.MIN_RANGED_DAMAGE)
        self.assertEqual(simulation.damage_amount(source.data, dict(target.data, defense=10000), 1,
                                                  simulation.ranged_multiplier(combat.WEAPON_RANGE)), 0)

    def test_expiring_projectile_cannot_hit_beyond_its_remaining_reach(self):
        simulation = self.encounter()
        hold_still(simulation)
        source, target = simulation.fighters
        simulation.projectiles = [combat.Projectile(
            source, dict(source.data), target.x - combat.UNIT_RADIUS - 10, target.y, 1000, 0, 0.001)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(target.data["health"], target.data["max_health"])
        self.assertEqual(simulation.projectiles, [])

    def test_ai_does_not_dodge_a_projectile_stopped_by_cover(self):
        for covered in (False, True):
            with self.subTest(covered=covered):
                features = [battle_terrain.Feature("rock", 1200, 500, 50, 150)] if covered else []
                simulation = self.encounter(*features)
                source, target = simulation.fighters
                target.data["speed"] = combat.DODGE_MIN_SPEED
                target.cooldown = combat.FIRE_INTERVAL
                simulation.projectiles = [combat.Projectile(source, dict(source.data), 1000, 500, 1250, 0, 1)]
                crowds = [combat._Grid([unit], combat.GRID_CELL) for unit in simulation.fighters]
                simulation._dodge_incoming(crowds)
                self.assertEqual(target.dodge > 0, not covered)

    def test_projectiles_hit_raised_ground_before_units_behind_the_crest(self):
        simulation = self.encounter(battle_terrain.Feature("hill", 1200, 500, 150, 100))
        hold_still(simulation)
        source, target = simulation.fighters
        simulation.projectiles = [combat.Projectile(source, dict(source.data), 1000, 500, 18000, 0, 1)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(target.data["health"], target.data["max_health"])
        self.assertEqual(simulation.projectiles, [])

    def test_ram_approach_rejects_intervening_bodies(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"] * 2, ["Fixture I"], seed=2)
        unit, friend, target = simulation.fighters
        unit.x, unit.y, unit.shape, unit.pace = 1000, 500, "tank", 1
        friend.x, friend.y = 1100, 500
        target.x, target.y = 1200, 500
        self.assertIsNone(simulation._ram_point(unit, target))
        friend.y += unit.radius + friend.radius + 10
        self.assertIsNotNone(simulation._ram_point(unit, target))

    def test_blocked_units_seek_reachable_firing_positions_on_both_sides(self):
        simulation = self.encounter(battle_terrain.Feature("rock", 1200, 500, 60, 150))
        for unit, target in (simulation.fighters, list(reversed(simulation.fighters))):
            unit.hold, unit.pace, unit.start_delay = 0.8, 1, 0
            unit.target = target
            position = simulation._firing_position(unit, target)
            self.assertTrue(simulation._firing_lane(unit, target, position))
            self.assertTrue(simulation.battlefield.route((unit.x, unit.y), position))
            course = simulation._ai_course(unit, 400, 0, (unit.x, unit.y), target)
            self.assertGreater(course[0], 0)

    def test_increased_weapon_reach_does_not_move_preferred_positions(self):
        simulation = self.encounter()
        unit, target = simulation.fighters
        unit.hold, unit.target = 0.8, target
        distance = combat.ENGAGEMENT_RANGE * unit.hold
        with patch.object(combat, "WEAPON_RANGE", combat.WEAPON_RANGE * 3):
            self.assertEqual(simulation._ai_course(unit, distance, 0, (unit.x, unit.y), target), (0, 0))

    def test_rams_reject_blocked_approaches_and_targets_that_cannot_be_caught(self):
        simulation = self.encounter(battle_terrain.Feature("chasm", 1100, 500, 30))
        unit, target = simulation.fighters
        unit.shape, unit.pace = "tank", 1
        target.x = 1200
        self.assertIsNone(simulation._ram_point(unit, target))
        simulation.battlefield = self.field()
        self.assertIsNotNone(simulation._ram_point(unit, target))
        target.vx = unit.max_speed * 2
        self.assertIsNone(simulation._ram_point(unit, target))
        target.x = unit.x + combat.RAM_COMMIT_RANGE + 1
        target.vx = unit.max_speed - combat.RAM_MIN_SPEED / 2
        self.assertIsNone(simulation._ram_point(unit, target))

    def test_ram_selection_can_pass_over_a_nearer_unsuitable_target(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture III", "Fixture I"], seed=2)
        unit, armored, vulnerable = simulation.fighters
        unit.x, unit.y, unit.shape, unit.pace = 1000, 500, "tank", 1
        armored.x, armored.shape = 1100, "tank"
        armored.y = unit.y + unit.radius + armored.radius + 10
        armored.data["attack"] = 0  # Does not add a second damaging threat.
        armored.data["defense"] = unit.data["attack"] * 2
        vulnerable.x, vulnerable.y, vulnerable.data["health"] = 1120, 500, 20
        vulnerable.cooldown = 0
        sides = [[unit], [armored, vulnerable]]
        simulation._prepare_rams(sides, [combat._Grid(side, combat.GRID_CELL) for side in sides])
        self.assertTrue(unit.ram_committed)
        self.assertIs(unit.target, vulnerable)

    def test_cover_excludes_blocked_supporting_fire_from_ram_risk(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"] * 3, seed=2)
        unit, target, *support = simulation.fighters
        unit.x, unit.y, unit.shape, unit.pace = 1000, 500, "tank", 1
        target.x, target.y, target.data["health"] = 1120, 500, 20
        target.cooldown = 0
        for index, enemy in enumerate(support):
            enemy.x, enemy.y = unit.x + combat.WEAPON_RANGE * 0.8, unit.y - 10 + index * 20
        sides = [[unit], [target, *support]]
        crowds = [combat._Grid(side, combat.GRID_CELL) for side in sides]
        simulation.battlefield = self.field(battle_terrain.Feature(
            "rock", unit.x + combat.WEAPON_RANGE * 0.5, unit.y, 60, 150))
        simulation._prepare_rams(sides, crowds)
        self.assertTrue(unit.ram_committed)
        simulation.battlefield = self.field()
        simulation._prepare_rams(sides, crowds)
        self.assertFalse(unit.ram_committed)


class CustomBattleScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        fonts.init_fonts()

    def setUp(self):
        self.library = fixture_library()
        self.enterContext(single_subunits())
        self.enterContext(patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", 1.0))
        self.countries = {
            "Fixture A": {"name": "First Country", "is_playable": True, "flag_data": "DEFAULT"},
            "Fixture B": {"name": "Second Country", "is_playable": True, "flag_data": "DEFAULT"},
        }
        self.enterContext(patch("data.queries.get_country_data", return_value=self.countries))
        self.screen = battle_screen.CustomBattleScreen()
        self.controller = SimpleNamespace(set_tactical_battle_music=Mock(), set_music_volume_scale=Mock())
        with patch("data.queries.get_unit_library", return_value=self.library):
            self.screen.on_enter(self.controller, None)

    def click(self, label, *, finish_intro=True):
        button = next(button for button in self.screen.elements if button.text == label)
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center)])
        if finish_intro and self.screen.preview_intro_stage is not None:
            self.screen.draw(self.surface)
            duration = (battle_screen.PREVIEW_SLIDE_IN_SECONDS + battle_screen.PREVIEW_HOLD_SECONDS
                        + battle_screen.PREVIEW_SLIDE_OUT_SECONDS)
            with patch("pygame.time.get_ticks",
                       return_value=self.screen.preview_intro_started + math.ceil(duration * 1000)):
                self.screen.update()

    def fill_armies(self):
        self.screen.add_unit(0, "Fixture II")
        self.screen.add_unit(1, "Fixture I")

    def test_kill_feed_uses_simulation_kills_survives_results_and_clears_on_replay(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        simulation = self.screen.simulation
        simulation.battlefield = battle_terrain.Battlefield("plains", combat.ARENA_SIZE, combat.MAX_UNIT_RADIUS)
        source, target = simulation.fighters
        source.x, target.x = 1000, 1100
        source.y = target.y = 500
        source.cooldown = target.cooldown = 1000
        target.data["health"] = 1
        simulation.projectiles = [combat.Projectile(source, dict(source.data), source.x, source.y, 18000, 0, 1)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(list(self.screen.kill_feed), [(source, target, "shot")])
        self.screen.update()
        self.assertEqual(self.screen.mode, "result")
        with patch.object(self.screen, "_refresh_kill_feed", side_effect=AssertionError("uncached kill feed")):
            self.screen.draw(self.surface)
        self.assertEqual(len(self.screen.kill_feed), 1)
        self.click("Run Again")
        self.assertFalse(self.screen.kill_feed)
        self.assertIsNotNone(self.screen.kill_feed_surface)

    def test_kill_feed_keeps_history_and_scrolls_without_battlefield_input(self):
        from ui.navigation.touch_input import TouchInput
        self.fill_armies()
        self.screen.controlled_index = 0
        self.click("Simulate")
        self.click("Start")
        screen = self.screen
        source, target = screen.simulation.fighters
        for index in range(battle_screen.KILL_FEED_VISIBLE_ROWS + 3):
            victim = copy.copy(target)
            victim.data = dict(target.data, unit_id=f"victim-{index}")
            screen._record_kill(source, victim, "shot")
        self.assertEqual(len(screen.kill_feed), battle_screen.KILL_FEED_VISIBLE_ROWS + 3)
        zoom, camera = screen.zoom_index, list(screen.camera)
        with patch("pygame.mouse.get_pos", return_value=screen.kill_feed_content.center):
            screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-2)])
        self.assertEqual(screen.kill_feed_scroll, -2 * battle_screen.KILL_FEED_ROW_HEIGHT)
        self.assertEqual(screen.zoom_index, zoom)
        self.assertEqual(screen.camera, camera)
        previous_entry = screen.kill_feed[2]
        screen._record_kill(source, target, "ram")
        self.assertIs(screen.kill_feed[3], previous_entry)
        self.assertEqual(screen.kill_feed_scroll, -3 * battle_screen.KILL_FEED_ROW_HEIGHT)

        # Dragging the content down moves toward newer kills and never fires the controlled gun.
        point = screen.kill_feed_content.center
        before = screen.kill_feed_scroll
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(point[0], point[1] + 20),
                               rel=(0, 20), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(point[0], point[1] + 20))])
        self.assertEqual(screen.kill_feed_scroll, before + 20)
        self.assertFalse(screen.firing)
        self.assertIsNone(screen.pan_drag)
        self.assertFalse(screen.is_content_dragging("kill_feed_scroll"))

        # The shared scrollbar can reach the oldest kill and releases outside the feed.
        track = screen.kill_feed_track.copy()
        screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(track.centerx, track.bottom - 1)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(300, 300))])
        self.assertEqual(screen.kill_feed_scroll, screen.kill_feed_limit)
        self.assertFalse(screen.kill_feed_dragging)

        # Mobile drags use the same content direction.
        touch = TouchInput()
        before = screen.kill_feed_scroll
        for kind, y in ((pygame.FINGERDOWN, point[1]), (pygame.FINGERMOTION, point[1] + 20),
                        (pygame.FINGERUP, point[1] + 20)):
            event = pygame.event.Event(kind, touch_id=1, finger_id=1,
                                       x=point[0] / c.SCREEN_WIDTH, y=y / c.SCREEN_HEIGHT)
            screen.handle_events(touch.process_events([event], screen, "MOBILE"))
        self.assertGreater(screen.kill_feed_scroll, before)
        self.assertFalse(screen.firing)
        self.assertEqual(screen.zoom_index, zoom)
        self.assertEqual(screen.camera, camera)

        # Result mode still permits feed scrolling; the wheel outside still zooms the battlefield.
        screen.simulation.winner = 0
        screen.update()
        self.assertEqual(screen.mode, "result")
        with patch("pygame.mouse.get_pos", return_value=screen.kill_feed_content.center):
            screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=100)])
        self.assertEqual(screen.kill_feed_scroll, 0)
        self.assertEqual(screen.zoom_index, zoom)
        with patch("pygame.mouse.get_pos", return_value=(300, 300)):
            screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
        self.assertEqual(screen.zoom_index, zoom + 1)

    def test_kill_feed_scrollbar_handle_can_drag_between_rows_in_battle_and_results(self):
        self.fill_armies()
        self.screen.controlled_index = 0
        self.click("Simulate")
        self.click("Start")
        screen = self.screen
        source, target = screen.simulation.fighters
        for _ in range(battle_screen.KILL_FEED_VISIBLE_ROWS + 4):
            screen._record_kill(source, target, "shot")
        zoom, camera = screen.zoom_index, list(screen.camera)
        for mode in ("battle", "result"):
            with self.subTest(mode=mode):
                screen.mode = mode
                screen.simulation.winner = 0 if mode == "result" else None
                screen.kill_feed_scroll = 0
                screen._refresh_kill_feed()
                screen.refresh_ui()
                handle, track = screen.kill_feed_handle.copy(), screen.kill_feed_track.copy()
                point = (track.centerx, track.centery + 1)
                screen.handle_events([
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=handle.center),
                    pygame.event.Event(pygame.MOUSEMOTION, pos=point,
                                       rel=(0, point[1] - handle.centery), buttons=(1, 0, 0))])
                self.assertLess(screen.kill_feed_scroll, 0)
                self.assertGreater(screen.kill_feed_scroll, screen.kill_feed_limit)
                # A kill arriving mid-drag must also render from the scrollbar's offset.
                screen._record_kill(source, target, "ram")
                bottom = (track.centerx, track.bottom + 20)
                screen.handle_events([
                    pygame.event.Event(pygame.MOUSEMOTION, pos=bottom,
                                       rel=(0, bottom[1] - point[1]), buttons=(1, 0, 0)),
                    pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=bottom)])
                self.assertEqual(screen.kill_feed_scroll, screen.kill_feed_limit)
                self.assertFalse(screen.kill_feed_dragging)
                self.assertFalse(screen.is_content_dragging("kill_feed_scroll"))
                self.assertFalse(screen.firing)
                self.assertIsNone(screen.pan_drag)
                self.assertEqual(screen.zoom_index, zoom)
                self.assertEqual(screen.camera, camera)

    def test_regular_firing_uses_all_three_rifle_variants_on_both_sides(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        for side in (0, 1):
            source = self.screen.simulation.divisions[side][0]
            with patch.object(battle_screen.random, "choice", side_effect=battle_screen.RIFLE_SHOT_SOUNDS), patch(
                    "ui.widgets.ui_elements.play_ui_sound") as sound:
                for _ in battle_screen.RIFLE_SHOT_SOUNDS:
                    self.screen.simulation._fire_shot(source)
            self.assertEqual([call.args[0] for call in sound.call_args_list],
                             ["rifle_shot_1", "rifle_shot_2", "rifle_shot_3"])

    def test_only_controlled_nonshell_shots_use_heavy_gunshot(self):
        self.fill_armies()
        self.screen.add_unit(0, "Fixture I")
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        simulation = self.screen.simulation
        for source in simulation.fighters:
            for shape in combat.MOBILITY:
                source.shape = shape
                if source.weapon()["shell"]:
                    continue
                with self.subTest(side=source.side, controlled=source is simulation.controlled, shape=shape), patch(
                        "ui.widgets.ui_elements.play_ui_sound") as sound, patch.object(
                            battle_screen.random, "choice", return_value="rifle_shot_2") as choice:
                    source.shape = shape
                    simulation._fire_shot(source)
                    expected = "heavy_gunshot" if source is simulation.controlled else "rifle_shot_2"
                    sound.assert_called_once_with(expected, volume_scale=battle_screen.BATTLE_SFX_VOLUME * self.screen.zoom_volume_share())
                    if source is simulation.controlled:
                        choice.assert_not_called()
                    else:
                        choice.assert_called_once_with(battle_screen.RIFLE_SHOT_SOUNDS)

    def test_shells_use_all_three_tank_sounds_for_each_equipped_shape_on_both_sides(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        for source in self.screen.simulation.fighters:
            for shape in combat.MOBILITY:
                source.shape = shape
                if not source.weapon()["shell"]:
                    continue
                with self.subTest(side=source.side, shape=shape), patch(
                        "ui.widgets.ui_elements.play_ui_sound") as sound, patch.object(
                            battle_screen.random, "choice", side_effect=battle_screen.TANK_SHOT_SOUNDS) as choice:
                    source.shape = shape
                    for _ in battle_screen.TANK_SHOT_SOUNDS:
                        self.screen.simulation._fire_shot(source)
                    self.assertEqual([call.args[0] for call in sound.call_args_list],
                                     list(battle_screen.TANK_SHOT_SOUNDS))
                    self.assertTrue(all(call.args == (battle_screen.TANK_SHOT_SOUNDS,)
                                        for call in choice.call_args_list))

    def win_battle(self):
        """End actual battle with a friendly win, without relying on random aim and movement."""
        for fighter in self.screen.simulation.fighters:
            if fighter.side == 1:
                fighter.data["health"] = 0
        self.screen.simulation.advance(combat.FIXED_STEP)

    def roster_types(self, side):
        return [unit["type"] for unit in self.screen.rosters[side]]

    def click_card_settings(self, side, index):
        self.screen.draw(self.surface)
        button = self.screen.unit_buttons[side, index]
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center)])

    def test_gear_opens_unit_editor_and_picker_callbacks_edit_only_that_entry(self):
        self.fill_armies()
        self.screen.add_unit(0, "Fixture II")
        unit, duplicate = self.screen.rosters[0]
        before = copy.deepcopy(duplicate)
        with patch("ui.navigation.screen_runner._run_pygame_sub_screen") as opened, \
                patch("ui.widgets.ui_elements.play_ui_sound") as sound:
            self.click_card_settings(0, 0)
        self.assertIsNone(self.screen.drag)
        sound.assert_called_once_with("open_settings")
        editor = opened.call_args.args[1]
        self.assertEqual(editor.units, [unit])
        editor.draw(self.surface)
        with patch("ui.dialogs.pickers.open_listbox_selector") as picker:
            editor.elements[0].callback()
        items, callback = picker.call_args.args[3:5]
        self.assertEqual(items, [("First Country", "Fixture A"), ("Second Country", "Fixture B")])
        callback("Fixture B")
        slider = editor.elements[1]
        self.assertEqual((slider.visual_max, slider.allowed_max), (100, 100))
        slider.callback(25)
        self.assertEqual((unit["owner"], unit["health"]), ("Fixture B", 25))
        self.assertEqual(slider.text, "Starting HP: 25%")
        self.assertEqual(duplicate, before)
        slider.callback(0)  # The slider track starts at zero; starting HP stays above zero.
        self.assertEqual(unit["health"], unit["max_health"] * 0.01)
        editor.elements[-1].callback()
        self.assertTrue(editor.done)

    def test_unit_settings_follow_reorder_preview_combat_and_replay(self):
        self.fill_armies()
        self.screen.add_unit(0, "Fixture I")
        unit = self.screen.rosters[0][1]
        self.assertTrue(self.screen.set_unit_options(0, [unit], owner="Fixture B", health_percent=25))
        self.assertEqual(unit["health"], unit["max_health"] * 0.25)
        self.click("Control")
        self.drag_card(self.screen.card_rect(0, 1).center, self.screen.card_rect(0, 0).center)
        self.assertIs(self.screen.rosters[0][0], unit)
        self.assertEqual(self.screen.controlled_index, 0)
        before = copy.deepcopy(self.screen.rosters)
        self.click("Simulate")
        self.assertFalse(self.screen.unit_buttons)
        player = self.screen.simulation.controlled
        self.assertEqual((player.data["owner"], player.data["health"]), ("Fixture B", unit["health"]))
        self.assertFalse(self.screen.set_unit_options(0, [unit], health_percent=50))
        with patch("ui.navigation.screen_runner._run_pygame_sub_screen") as opened:
            self.screen.edit_unit(0, unit)
        opened.assert_not_called()
        self.click("Start")
        self.assertEqual(player.data["health"], unit["health"])
        player.data["health"] = 1
        self.screen.simulation.winner = 0
        self.screen.update()
        self.click("Run Again")
        self.assertEqual(self.screen.simulation.controlled.data["health"], unit["health"])
        self.assertEqual(self.screen.rosters, before)
        self.click("Retreat")
        self.assertEqual(self.screen.rosters, before)

    def test_settings_reject_invalid_values_and_removed_units(self):
        self.fill_armies()
        unit = self.screen.rosters[0][0]
        before = copy.deepcopy(unit)
        for options in ({"owner": "missing"}, {"health_percent": 0}, {"health_percent": -1},
                        {"health_percent": 101}, {"health_percent": True}, {"health_percent": "25"}):
            with self.subTest(options=options):
                self.assertFalse(self.screen.set_unit_options(0, [unit], **options))
                self.assertEqual(unit, before)
        self.click("Remove")
        self.assertFalse(self.screen.set_unit_options(0, [unit], health_percent=50))

    def test_setup_and_preview_cards_include_spawn_count_and_wound_setting(self):
        self.library["Fixture II"]["attack"] = 100
        self.fill_armies()
        unit = self.screen.rosters[0][0]
        for floor, attack in ((0, 63), (0.5, 66.5), (1, 70)):
            with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}), \
                    patch.object(combat, "TACTICAL_DAMAGE_AT_ZERO_HEALTH", floor):
                self.screen.set_unit_options(0, [unit], health_percent=63)
                for mode in ("setup", "preview"):
                    if mode == "preview":
                        self.click("Simulate")
                        self.assertEqual(len(self.screen.simulation.divisions[0]), 7)
                    with self.subTest(mode=mode, floor=floor), \
                            patch.object(battle_screen.ui_elements, "draw_wrapped_icon_row") as row:
                        self.screen.card_surfaces.clear()
                        self.screen._cache_card(0, unit)
                        entries = row.call_args.args[2]
                        self.assertIn((c.ICON_ATTACK, queries.format_number(attack)), entries)
                        self.assertIn((c.ICON_HEALTH, queries.format_number(unit["health"])), entries)
                self.screen.return_to_setup()

    def test_dragging_a_card_health_bar_sets_starting_hp_for_the_card_or_its_group(self):
        self.fill_armies()
        self.screen.add_unit(0, "Fixture I")
        self.screen.draw(self.surface)
        bar, _flag_x = self.screen._bar_geometry(battle_screen.EDIT_BAR_TOP)

        def drag_bar(index, fraction):
            card = self.screen.card_rect(0, index)
            y = card.y + bar.centery
            start = (card.x + bar.left + 1, y)
            end = (card.x + bar.left + round(bar.width * fraction), y)
            self.screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
                pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(0, 0), buttons=(1, 0, 0)),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end)])
            self.screen.draw(self.surface)

        first, second = self.screen.rosters[0]
        drag_bar(0, 0.5)
        self.assertEqual(first["health"], first["max_health"] * 0.5)
        self.assertEqual(second["health"], second["max_health"])
        self.assertIsNone(self.screen.drag)
        self.screen.group[0] = [0, 1]
        drag_bar(1, 0.25)
        for unit in (first, second):
            self.assertEqual(unit["health"], unit["max_health"] * 0.25)

    def finish_intro(self):
        self.screen.draw(self.surface)
        duration = (battle_screen.PREVIEW_SLIDE_IN_SECONDS + battle_screen.PREVIEW_HOLD_SECONDS
                    + battle_screen.PREVIEW_SLIDE_OUT_SECONDS)
        with patch("pygame.time.get_ticks",
                   return_value=self.screen.preview_intro_started + math.ceil(duration * 1000)):
            self.screen.update()

    def enter_campaign(self, ally_types=()):
        from tests.combat_fixtures import StubBattleMap
        map_screen = StubBattleMap()
        for name, enemy in (("Fixture A", "Fixture B"), ("Fixture B", "Fixture A")):
            map_screen.add_nation(name, at_war_with=[enemy])
        player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
        allies = [queries.create_unit_dict(name, "Fixture A", self.library) for name in ally_types]
        enemy = queries.create_unit_dict("Fixture I", "Fixture B", self.library)
        province = map_screen.add_province("p1", "Fixture A", units=[player, *allies, enemy])
        province["_turn_start_owner"] = "Fixture A"
        map_screen.player_unit = player
        map_screen.tactical_mode = True
        map_screen.invalidate_map_presentation_cache = Mock()
        map_screen.refresh_map_layers = Mock()
        map_screen.update_country_centers = Mock()
        custom = self.screen.rosters
        with patch("data.queries.get_unit_library", return_value=self.library):
            self.screen._enter_campaign(map_screen, province, [player, *allies], [enemy])
        self.finish_intro()
        return map_screen, province, custom

    def test_tactical_preview_reorder_keeps_each_result_on_its_own_campaign_unit(self):
        map_screen, province, _custom = self.enter_campaign(ally_types=["Fixture III"])
        player, ally, enemy = province["units"]
        self.drag_card(self.screen.card_rect(0, 1).center, self.screen.card_rect(0, 0).center)
        self.assertEqual(self.screen.campaign.units, [ally, player, enemy])
        self.assertEqual(self.screen.controlled_index, 1)
        self.assertEqual(self.screen.simulation.controlled.data["type"], player["type"])
        self.click("Start")
        simulation = self.screen.simulation
        simulation.divisions[0][0].data["health"] /= 2  # The ally, now in the front rank.
        for fighter in simulation.divisions[2]:
            fighter.data["health"] = 0
        simulation.winner = 0
        self.screen.update()
        self.assertEqual((ally["health"], player["health"]), (ally["max_health"] / 2, player["max_health"]))
        self.assertEqual(province["units"], [player, ally])

    def test_tactical_encounter_opens_preview_controlling_the_players_unit(self):
        self.fill_armies()
        map_screen, province, custom = self.enter_campaign()
        self.assertEqual(self.screen.mode, "preview")
        self.assertEqual(self.screen.controlled_index, 0)
        self.assertIs(self.screen.simulation.controlled.data["owner"], "Fixture A")
        self.assertIs(self.screen.country_data, map_screen.nation_data)
        labels = [button.text for button in self.screen.elements]
        self.assertNotIn("Exit", labels)
        start, retreat = (next(b for b in self.screen.elements if b.text == label)
                          for label in ("Start", "Retreat"))
        self.assertGreater(retreat.rect.left, start.rect.right)
        self.screen.handle_back_key()
        self.assertEqual(self.screen.mode, "preview")
        # Retreat opens the map chooser; backing out shows the same preview again.
        self.click("Retreat")
        self.assertEqual(self.screen.next_state, "TACTICAL_RETREAT")
        self.assertTrue(self.screen.choosing_retreat)
        self.screen.on_enter(self.controller, SimpleNamespace())
        self.assertEqual(self.screen.mode, "preview")
        self.assertIsNotNone(self.screen.campaign)
        self.assertFalse(self.screen.done)
        self.click("Retreat")
        self.screen.finish_retreat()
        self.assertIsNone(self.screen.campaign)
        self.assertIs(self.screen.rosters, custom)

    def test_terrain_picker_applies_only_to_custom_setup_and_survives_campaign_visits(self):
        with patch("screens.game.custom_battle.pickers.open_listbox_selector") as picker:
            terrain_button = next(button for button in self.screen.elements
                                  if button.callback == self.screen.choose_terrain)
            terrain_button.callback()
            picker.assert_called_once()
            picker.call_args.args[4]("jungle")
        self.assertEqual(self.screen.terrain, "jungle")
        self.fill_armies()
        self.click("Simulate")
        self.assertEqual(self.screen.simulation.battlefield.terrain, "jungle")
        self.screen.set_terrain("desert")
        self.assertEqual(self.screen.terrain, "jungle")
        self.screen.return_to_setup()
        _map, province, _custom = self.enter_campaign()
        self.assertEqual(self.screen.simulation.battlefield.terrain, province["terrain"])
        self.screen.set_terrain("desert")
        self.assertEqual(self.screen.terrain, "jungle")
        self.screen.finish_retreat()
        with patch("data.queries.get_unit_library", return_value=self.library):
            self.screen.on_enter(self.controller, None)
        self.assertEqual(self.screen.terrain, "jungle")

    def test_preview_reordering_preserves_the_generated_battlefield(self):
        self.screen.set_terrain("mountain")
        self.fill_armies()
        self.screen.add_unit(0, "Fixture II")
        self.click("Simulate")
        before = [(f.kind, f.x, f.y, f.radius, f.height) for f in self.screen.simulation.battlefield.features]
        self.drag_card(self.screen.card_rect(0, 1).center, self.screen.card_rect(0, 0).center)
        after = [(f.kind, f.x, f.y, f.radius, f.height) for f in self.screen.simulation.battlefield.features]
        self.assertEqual(before, after)

    def test_tactical_result_continues_to_map_and_spectates_only_after_death(self):
        for dies in (False, True):
            with self.subTest(dies=dies):
                self.screen.next_state = None
                self.screen.done = False
                map_screen, province, _custom = self.enter_campaign()
                self.click("Start")
                self.assertNotIn("Exit", [button.text for button in self.screen.elements])
                if dies:
                    self.screen.simulation.controlled.data["health"] = 0
                player, enemy = province["units"]
                half = player["max_health"] / 2
                self.screen.simulation.fighters[0].data["health"] = 0 if dies else half
                self.screen.simulation.fighters[1].data["health"] = enemy["max_health"] if dies else 0
                self.screen.simulation.winner = 1 if dies else 0
                self.screen.update()
                self.assertEqual(self.screen.mode, "result")
                self.assertFalse(self.screen.done)
                self.assertIsNone(self.screen.next_state)
                self.screen.draw(self.surface)
                self.check_result_navigation()
                # The result is written back as soon as the battle ends.
                if dies:
                    self.assertEqual(province["units"], [enemy])
                else:
                    self.assertEqual(province["units"], [player])
                    self.assertEqual(player["health"], half)
                self.assertEqual([b.text for b in self.screen.elements if b.text != ""], ["Pause", "Continue"])
                with patch("screens.game.custom_battle.player_setup.lose_tactical_unit") as lose:
                    self.click("Continue")
                self.assertEqual(self.screen.next_state, "MAP")
                self.assertIsNone(self.screen.campaign)
                self.assertEqual(lose.called, dies)
                if dies:
                    lose.assert_called_once_with(map_screen, province)

    def test_finished_custom_and_campaign_battles_keep_overlay_controls(self):
        for campaign in (False, True):
            with self.subTest(campaign=campaign):
                if campaign:
                    self.enter_campaign()
                else:
                    self.fill_armies()
                    self.click("Simulate")
                self.click("Start")
                self.win_battle()
                self.screen.update()
                simulation, encounter = self.screen.simulation, self.screen.campaign
                self.assertEqual(self.screen.mode, "result")
                self.assertTrue(self.screen.pause_button.disabled)
                paused = simulation.paused
                self.click("Pause")
                self.assertEqual(simulation.paused, paused)
                self.assertEqual(self.screen.mode, "result")
                self.controller.set_tactical_battle_music.reset_mock()
                for sound, state in (("open_music", "MUSIC_PLAYER"), ("open_settings", "SETTINGS")):
                    button = next(button for button in self.screen.elements if button.sound_kind == sound)
                    self.screen.handle_events([
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center),
                        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center)])
                    self.assertEqual(self.screen.next_state, state)
                    self.assertTrue(self.screen.viewing_overlay)
                    self.screen.on_enter(self.controller, SimpleNamespace())
                    self.assertEqual(self.screen.mode, "result")
                    self.assertIs(self.screen.simulation, simulation)
                    self.assertIs(self.screen.campaign, encounter)
                    self.assertFalse(self.screen.done)
                    with patch.object(simulation, "advance", side_effect=AssertionError("finished battle advanced")):
                        self.screen.update()
                self.controller.set_tactical_battle_music.assert_not_called()
                self.assertIn("Continue" if campaign else "Run Again", [button.text for button in self.screen.elements])

    def test_the_side_left_standing_takes_the_tile_when_the_battle_ends(self):
        from tests.combat_fixtures import StubBattleMap
        for player_dies, owner in ((True, "Fixture B"), (False, "Fixture A")):
            with self.subTest(player_dies=player_dies):
                world = StubBattleMap()
                for name, enemy in (("Fixture A", "Fixture B"), ("Fixture B", "Fixture A")):
                    world.add_nation(name, at_war_with=[enemy])
                player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
                foe = queries.create_unit_dict("Fixture I", "Fixture B", self.library)
                province = world.add_province("p1", "Fixture A", units=[player, foe])
                province["_turn_start_owner"] = "Fixture A"
                world.player_unit = player
                world.tactical_mode = True
                world.invalidate_map_presentation_cache = Mock()
                world.refresh_map_layers = Mock()
                world.update_country_centers = Mock()
                with patch("data.queries.get_unit_library", return_value=self.library):
                    self.screen._enter_campaign(world, province, [player], [foe])
                self.finish_intro()
                self.click("Start")
                fighters = self.screen.simulation.fighters
                fighters[0].data["health"] = 0 if player_dies else fighters[0].data["max_health"]
                fighters[1].data["health"] = foe["max_health"] if player_dies else 0
                self.screen.simulation.winner = 1 if player_dies else 0
                self.screen.update()
                self.assertEqual(province["owner"], owner)
                # A changed owner rebuilds every layer a turn's end rebuilds; no change rebuilds none.
                layers = [call.args[0] for call in world.refresh_map_layers.call_args_list]
                self.assertEqual(layers, list(battle_screen.player_setup.TILE_CAPTURE_LAYERS) if player_dies else [])
                self.assertEqual(world.update_country_centers.called, player_dies)

    def test_artillery_cannot_join_a_custom_army_or_be_the_tactical_division(self):
        from screens.setup import player_setup
        self.assertNotIn("Fixture Gun I", self.screen.unit_names)
        self.screen.add_unit(0, "Fixture Gun I")
        self.assertEqual(self.screen.rosters[0], [])
        gun = queries.create_unit_dict("Fixture Gun I", "Fixture A", self.library)
        foot = queries.create_unit_dict("Fixture I", "Fixture A", self.library)
        map_screen = SimpleNamespace(show_feedback=Mock(), pending_unit=None, pending_selection=None,
                                     selected_province=None)
        with patch("data.queries.get_unit_library", return_value=self.library), \
                patch("screens.setup.player_setup.ui_elements.play_ui_sound"):
            player_setup.select_tactical_unit(map_screen, {"owner": "Fixture A", "units": [gun, foot]})
            self.assertIs(map_screen.pending_unit, foot)
            map_screen.pending_unit = None
            only_artillery = {"owner": "Fixture A", "units": [gun]}
            player_setup.select_tactical_unit(map_screen, only_artillery)
        self.assertIsNone(map_screen.pending_unit)
        self.assertEqual(only_artillery["units"], [gun])  # No replacement division is spawned.

    def test_campaign_forces_lead_with_the_player_unit_and_need_a_land_enemy(self):
        nations = {"Fixture A": {"at_war_with": ["Fixture B"]}, "Fixture B": {"at_war_with": ["Fixture A"]}}
        player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
        ally = queries.create_unit_dict("Fixture I", "Fixture A", self.library)
        ally["health"] = ally["max_health"] / 2
        foe = queries.create_unit_dict("Fixture I", "Fixture B", self.library)
        ship = queries.create_unit_dict("Fixture Ship I", "Fixture B", self.library)
        province = {"units": [ally, player, foe, ship]}
        friendly, enemy = combat.campaign_forces(player, province, nations, self.library)
        self.assertEqual(friendly, [player, ally])
        self.assertEqual(enemy, [foe])
        roster = combat.campaign_roster(friendly, self.library)
        self.assertEqual(roster[1]["health"] / roster[1]["max_health"], 0.5)
        self.assertIsNone(combat.campaign_forces(player, {"units": [player, ally]}, nations, self.library))
        self.assertIsNone(combat.campaign_forces(player, {"units": [player, ship]}, nations, self.library))

    def test_campaign_forces_limit_both_armies_and_keep_the_player_first(self):
        nations = {"Fixture A": {"at_war_with": ["Fixture B"]}, "Fixture B": {"at_war_with": ["Fixture A"]}}
        player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
        cap = c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE
        allies = [queries.create_unit_dict("Fixture I", "Fixture A", self.library) for _ in range(cap + 1)]
        enemies = [queries.create_unit_dict("Fixture I", "Fixture B", self.library) for _ in range(cap + 1)]
        province = {"units": [*allies, *enemies, player]}
        friendly, enemy = combat.campaign_forces(player, province, nations, self.library)
        self.assertEqual(friendly, [player, *allies[:cap - 1]])
        self.assertEqual(enemy, enemies[:cap])
        self.assertEqual(province["units"], [*allies, *enemies, player])

    def test_tactical_result_clears_the_defeated_side_beyond_the_deployment_limit(self):
        from tests.combat_fixtures import StubBattleMap
        for winner in (0, 1):
            with self.subTest(winner=winner), patch.object(c, "CUSTOM_BATTLE_MAX_UNITS_PER_SIDE", 2), patch(
                    "data.queries.get_unit_library", return_value=self.library):
                world = StubBattleMap()
                world.add_nation("Fixture A", at_war_with=["Fixture B", "Fixture C"])
                world.add_nation("Fixture B", at_war_with=["Fixture A"])
                world.add_nation("Fixture C", at_war_with=["Fixture A"])
                world.add_nation("Neutral")
                player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
                friends = [player, *[queries.create_unit_dict("Fixture I", "Fixture A", self.library)
                                     for _ in range(3)]]
                enemies = [queries.create_unit_dict("Fixture I", "Fixture B", self.library) for _ in range(3)]
                enemies.append(queries.create_unit_dict("Fixture I", "Fixture C", self.library))
                volunteer = queries.create_unit_dict("Fixture I", "Neutral", self.library)
                volunteer["volunteer_host"] = "Fixture C"
                enemies.append(volunteer)
                for kind in ("Fixture Gun I", "Fixture Plane I", "Fixture Ship I"):
                    enemies.append(queries.create_unit_dict(kind, "Fixture C", self.library))
                neutral = queries.create_unit_dict("Fixture I", "Neutral", self.library)
                neutral_before = copy.deepcopy(neutral)
                province = world.add_province("p1", "Fixture B", units=[*friends, *enemies, neutral])
                world.player_unit, world.tactical_mode = player, True
                world.invalidate_map_presentation_cache = Mock()
                world.refresh_map_layers, world.update_country_centers = Mock(), Mock()
                friendly, enemy = combat.campaign_forces(player, province, world.nation_data, self.library)
                self.assertEqual(len(friendly), 2)
                self.assertEqual(len(enemy), 2)
                self.screen._enter_campaign(world, province, friendly, enemy)
                self.finish_intro()
                self.click("Start")
                simulation = self.screen.simulation
                for fighter in simulation.fighters:
                    if fighter.side != winner:
                        fighter.data["health"] = 0
                simulation.winner = winner
                self.screen.update()
                defeated, survivors = (enemies, friends) if winner == 0 else (friends, enemies)
                self.assertTrue(all(unit["health"] == 0 for unit in defeated))
                self.assertEqual(province["units"], [*survivors, neutral])
                self.assertTrue(all(unit["health"] == unit["max_health"] for unit in survivors))
                self.assertEqual(neutral, neutral_before)
                self.assertFalse(queries.is_province_in_active_combat(province, world.nation_data))
                self.assertEqual(province["owner"], "Fixture A" if winner == 0 else "Fixture B")
                self.assertIsNone(combat.campaign_forces(player, province, world.nation_data, self.library))
                world.invalidate_map_presentation_cache.assert_called()
                once = copy.deepcopy(province["units"])
                self.screen.update()
                self.assertEqual(province["units"], once)

    def test_incoming_units_are_removed_from_the_campaign_after_a_tactical_victory(self):
        from map_logic.system32 import combat_processor, movement_processor
        from tests.combat_fixtures import StubBattleMap
        for reverse_order in (False, True):
            with self.subTest(reverse_order=reverse_order), patch(
                    "data.queries.get_unit_library", return_value=self.library):
                world = StubBattleMap()
                world.add_nation("Fixture A", at_war_with=["Fixture B"])
                world.add_nation("Fixture B", at_war_with=["Fixture A"])
                player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
                attackers = [queries.create_unit_dict("Fixture I", "Fixture B", self.library) for _ in range(2)]
                province = world.add_province("p1", "Fixture A", units=[player])
                for index, attacker in enumerate(attackers, 2):
                    attacker["order"] = {"type": "MOVE", "path": ["p1"]}
                    world.add_province(f"p{index}", "Fixture B", units=[attacker])
                world.player_unit, world.tactical_mode = player, True
                world.invalidate_map_presentation_cache = Mock()
                world.refresh_map_layers, world.update_country_centers = Mock(), Mock()
                if reverse_order:
                    world.map_data = dict(reversed(list(world.map_data.items())))
                combat_processor.process_pinning(world)
                combat_processor.process_meeting_engagements(world)
                movement_processor.process_movement(world)
                combat_processor.process_combat(world)
                friendly, enemy = combat.campaign_forces(player, province, world.nation_data, self.library)
                self.assertEqual({id(unit) for unit in enemy}, {id(unit) for unit in attackers})
                self.screen._enter_campaign(world, province, friendly, enemy)
                self.finish_intro()
                self.click("Start")
                for fighter in self.screen.simulation.fighters:
                    if fighter.side == 1:
                        fighter.data["health"] = 0
                self.screen.simulation.winner = 0
                self.screen.update()
                self.assertTrue(all(attacker["health"] == 0 for attacker in attackers))
                self.assertEqual([unit for tile in world.map_data.values() for unit in tile["units"]], [player])
                # A later turn must not bring the defeated attackers back.
                movement_processor.process_movement(world)
                combat_processor.process_combat(world)
                self.assertIsNone(combat.tactical_encounter(world, province))
                self.assertEqual([unit for tile in world.map_data.values() for unit in tile["units"]], [player])

    def test_map_offers_one_tactical_preview_per_turn_for_a_fighting_land_unit(self):
        from screens.game.map import Map
        nations = {"Fixture A": {"at_war_with": ["Fixture B"]}, "Fixture B": {"at_war_with": ["Fixture A"]}}
        player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
        foe = queries.create_unit_dict("Fixture I", "Fixture B", self.library)
        province = {"id": 1, "units": [player, foe]}
        fake = SimpleNamespace(
            tactical_mode=True, player_unit=player, multiplayer_mode=False, realtime_multiplayer=False,
            _tactical_battle_turn=None, time_manager=SimpleNamespace(total_turns=4),
            map_data={"key": province}, nation_data=nations, tactical_battle_request=None, go_to=Mock())
        with patch("data.queries.get_unit_library", return_value=self.library):
            Map.open_tactical_battle(fake)
            Map.open_tactical_battle(fake)
        fake.go_to.assert_called_once_with("CUSTOM_BATTLE")
        self.assertEqual(fake.tactical_battle_request[0], province)
        self.assertIs(fake.tactical_battle_request[1][0]["type"], player["type"])
        foe_free = SimpleNamespace(**{**vars(fake), "go_to": Mock(), "_tactical_battle_turn": None,
                                      "map_data": {"key": {"id": 1, "units": [player]}}})
        with patch("data.queries.get_unit_library", return_value=self.library):
            Map.open_tactical_battle(foe_free)
        foe_free.go_to.assert_not_called()

    def test_map_wins_at_once_when_only_hostile_artillery_shares_the_tile(self):
        from screens.game.map import Map
        nations = {"Fixture A": {"at_war_with": ["Fixture B"]}, "Fixture B": {"at_war_with": ["Fixture A"]}}
        player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
        gun = queries.create_unit_dict("Fixture Gun I", "Fixture B", self.library)
        plane = queries.create_unit_dict("Fixture Plane I", "Fixture B", self.library)
        ship = queries.create_unit_dict("Fixture Ship I", "Fixture B", self.library)
        neutral = queries.create_unit_dict("Fixture I", "Neutral", self.library)
        nations["Neutral"] = {"at_war_with": []}
        province = {"id": 1, "units": [player, gun, plane, ship, neutral]}
        fake = SimpleNamespace(
            tactical_mode=True, player_unit=player, multiplayer_mode=False, realtime_multiplayer=False,
            _tactical_battle_turn=None, time_manager=SimpleNamespace(total_turns=4),
            map_data={"key": province}, nation_data=nations, tactical_battle_request=None, go_to=Mock())
        with patch("data.queries.get_unit_library", return_value=self.library), \
                patch("screens.game.map.player_setup.settle_tactical_tile") as settle:
            Map.open_tactical_battle(fake)
        fake.go_to.assert_not_called()
        self.assertIsNone(fake.tactical_battle_request)
        self.assertEqual(province["units"], [player, neutral])
        self.assertTrue(all(unit["health"] == 0 for unit in (gun, plane, ship)))
        self.assertFalse(queries.is_province_in_active_combat(province, nations))
        self.assertEqual(player["health"], player["max_health"])
        settle.assert_called_once_with(fake, province)

    def test_campaign_combat_skips_the_tactical_tile_so_the_battle_deals_the_damage(self):
        from map_logic.system32 import combat_processor
        from tests.combat_fixtures import StubBattleMap
        # Hostile artillery alone is still the tactical player's encounter: the player wins it without a battle.
        for tactical, foe_type in ((False, "Fixture I"), (True, "Fixture I"), (False, "Fixture Gun I"),
                                   (True, "Fixture Gun I")):
            with self.subTest(tactical=tactical, foe=foe_type):
                screen = StubBattleMap()
                for name, enemy in (("Fixture A", "Fixture B"), ("Fixture B", "Fixture A")):
                    screen.add_nation(name, at_war_with=[enemy])
                player = queries.create_unit_dict("Fixture II", "Fixture A", self.library)
                foe = queries.create_unit_dict(foe_type, "Fixture B", self.library)
                screen.add_province("p1", "Fixture A", units=[player, foe])
                screen.tactical_mode = tactical
                screen.player_unit = player
                with patch("data.queries.get_unit_library", return_value=self.library):
                    combat_processor.process_combat(screen)
                damaged = player["health"] < player["max_health"] or foe["health"] < foe["max_health"]
                self.assertEqual(damaged, not tactical)

    def test_retreat_routes_skip_enemy_units_enemy_land_and_blocked_edges(self):
        nations = {"Fixture A": {"at_war_with": ["Fixture B"]}, "Fixture B": {"at_war_with": ["Fixture A"]}}
        unit = {"type": "Fixture I", "owner": "Fixture A"}
        foe = {"type": "Fixture I", "owner": "Fixture B"}
        tiles = {1: {"id": 1, "neighbors": [2, 3, 4, 5], "units": [unit, foe]},
                 2: {"id": 2, "owner": "Fixture A", "units": []},
                 3: {"id": 3, "owner": "Fixture A", "units": [foe]},
                 4: {"id": 4, "owner": "Fixture A", "units": []},
                 5: {"id": 5, "owner": "Fixture B", "units": []}}
        with patch("data.queries.movement.can_unit_move_step",
                   side_effect=lambda _unit, _here, dest, *_args, **_kw: dest["id"] != 4):
            routes = queries.find_retreat_routes(unit, tiles[1], tiles, nations)
        self.assertEqual(routes, {2: [2]})

    def test_selection_square_groups_cards_and_edits_them_together(self):
        self.fill_armies()
        for _ in range(2):
            self.screen.add_unit(0, "Fixture I")
        first, second, third = self.screen.rosters[0]
        self.screen.draw(self.surface)
        start = (self.screen.card_rect(0, 0).left, self.screen.panes[0].top - 20)
        end = (self.screen.card_rect(0, 1).right - 1, self.screen.panes[0].centery)
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
            pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(0, 0), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end)])
        self.assertEqual(self.screen.group[0], [0, 1])
        self.assertEqual(self.screen.roster_0_scroll, 0)
        with patch("ui.navigation.screen_runner._run_pygame_sub_screen") as opened:
            self.click_card_settings(0, 1)
        editor = opened.call_args.args[1]
        self.assertEqual(editor.units, [first, second])
        before = copy.deepcopy(third)
        editor.draw(self.surface)
        self.assertTrue(self.screen.set_unit_options(0, editor.units, owner="Fixture B", health_percent=40))
        for unit in (first, second):
            self.assertEqual((unit["owner"], unit["health"]), ("Fixture B", unit["max_health"] * 0.4))
        self.assertEqual(third, before)
        # A click on empty panel space clears the group.
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=start)])
        self.assertEqual(self.screen.group[0], [])

    def test_gear_clicks_respect_roster_clipping_and_do_not_intercept_unit_drops(self):
        self.fill_armies()
        for _ in range(8):
            self.screen.add_unit(0, "Fixture I")
        with patch("ui.navigation.screen_runner._run_pygame_sub_screen") as opened:
            self.click_card_settings(0, 0)
            opened.assert_not_called()
        self.screen.roster_0_scroll = 0
        self.screen.draw(self.surface)
        unit = self.screen.rosters[0][0]
        self.drag_card(self.screen.card_rect(0, 0).center, self.screen.unit_buttons[0, 1].rect.center)
        self.assertIsNone(self.screen.drag)
        self.assertIs(self.screen.rosters[0][1], unit)

    def test_year_slider_and_generate_button_replace_both_armies(self):
        library, tree = dated_fixture_content()
        with patch("data.queries.get_unit_library", return_value=library), \
                patch("data.queries.get_tech_tree", return_value=tree):
            self.screen.on_enter(self.controller, None)
            self.screen.add_unit(0, "Car 1")
            slider = self.screen.year_slider
            x = slider.rect.x + round(slider.rect.width * (1913 - c.START_YEAR)
                                      / (c.END_YEAR - c.START_YEAR))
            with patch("pygame.mouse.get_pressed", return_value=(True, False, False)):
                self.screen.handle_events([
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slider.handle_rect.center),
                    pygame.event.Event(pygame.MOUSEMOTION, pos=(x, slider.rect.centery),
                                       rel=(10, 0), buttons=(1, 0, 0)),
                    pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(x, slider.rect.centery))])
            self.assertEqual(self.screen.generation_year, 1913)
            self.assertIs(self.screen.year_slider, slider)
            self.assertEqual(self.roster_types(0), ["Car 1"])
            countries = iter(["Fixture A", "Fixture B"] * 4)
            real_choice = random.choice

            def choose(options):
                # Only nationality picks are scripted; unit picks stay random.
                return next(countries) if options is self.screen.nationalities else real_choice(options)

            with patch("map_logic.custom_battle.random.randint", side_effect=[3, 5]), \
                    patch("screens.game.custom_battle.random.choice", side_effect=choose):
                self.click("Random")
            self.assertEqual(tuple(map(len, self.screen.rosters)), (3, 5))
            self.assertTrue({unit["type"] for roster in self.screen.rosters for unit in roster}
                            <= {"Car 2", "Foot 1910"})
            self.assertTrue(all(unit["health"] == unit["max_health"]
                                for roster in self.screen.rosters for unit in roster))
            # Every generated unit draws its own nationality from the playable countries.
            self.assertEqual([unit["owner"] for roster in self.screen.rosters for unit in roster],
                             ["Fixture A", "Fixture B"] * 4)
            self.assertEqual(self.screen.selected, [None, None])
            self.assertEqual(self.screen.mode, "setup")
            self.screen.draw(self.surface)

    def test_generation_with_no_eligible_units_preserves_existing_rosters(self):
        library, tree = dated_fixture_content()
        with patch("data.queries.get_unit_library", return_value=library), \
                patch("data.queries.get_tech_tree", return_value=tree):
            self.screen.on_enter(self.controller, None)
            self.screen.update_generation_year(0)
            self.screen.add_unit(0, "Car 1")
            self.assertTrue(self.screen.generate_button.disabled)
            self.click("Random")
            self.assertEqual(self.roster_types(0), ["Car 1"])
            self.screen.generate_armies()
            self.assertEqual(self.roster_types(0), ["Car 1"])

    def test_short_year_slider_wheel_selects_single_years_and_clamps_bounds(self):
        library, tree = dated_fixture_content()
        with patch("data.queries.get_unit_library", return_value=library), \
                patch("data.queries.get_tech_tree", return_value=tree):
            self.screen.on_enter(self.controller, None)
            self.screen.update_generation_year(1916 - c.START_YEAR)
            with patch("pygame.mouse.get_pos", return_value=self.screen.year_slider.rect.center):
                self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
                self.assertEqual(self.screen.generation_year, 1917)
                self.assertNotIn("Car 2", self.screen.random_candidates)
                self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
                self.assertEqual(self.screen.generation_year, 1916)
                self.assertIn("Car 2", self.screen.random_candidates)
                self.screen.update_generation_year(0)
                self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
                self.assertEqual(self.screen.generation_year, c.START_YEAR)
                self.screen.update_generation_year(c.END_YEAR - c.START_YEAR)
                self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
                self.assertEqual(self.screen.generation_year, c.END_YEAR)

    def drag_card(self, start, end):
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
            pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(end[0] - start[0], end[1] - start[1]),
                               buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end)])

    def test_simulate_requires_two_armies_and_picker_can_add_repeated_levels(self):
        self.click("Simulate")
        self.assertEqual(self.screen.mode, "setup")
        with patch("ui.dialogs.pickers.open_listbox_selector") as picker:
            self.click("Add Friendly")
        args, options = picker.call_args
        self.assertEqual({value for label, value in args[3]}, set(combat.land_unit_types(self.library)))
        args[4]("Fixture II")
        args[4]("Fixture II")
        self.assertEqual(self.roster_types(0), ["Fixture II", "Fixture II"])
        self.assertFalse(options["close_on_select"])

    def test_reordering_and_invalid_drop_preserve_armies(self):
        for name in ("Fixture I", "Fixture II", "Fixture III"):
            self.screen.add_unit(0, name)
        self.screen.draw(self.surface)
        self.drag_card(self.screen.card_rect(0, 0).center, self.screen.card_rect(0, 2).center)
        self.assertEqual(self.roster_types(0), ["Fixture II", "Fixture III", "Fixture I"])
        before = list(self.screen.rosters[0])
        self.drag_card(self.screen.card_rect(0, 0).center, self.screen.panes[1].center)
        self.assertEqual(self.screen.rosters[0], before)
        self.assertEqual(self.screen.rosters[1], [])

    def test_remove_pause_focus_loss_and_exit_callbacks(self):
        self.fill_armies()
        self.click("Remove")
        self.assertEqual(self.screen.rosters[0], [])
        self.screen.add_unit(0, "Fixture II")
        self.click("Simulate")
        self.click("Start")
        self.screen.draw(self.surface)
        self.click("Pause")
        self.assertTrue(self.screen.simulation.paused)
        self.click("Resume")
        self.assertFalse(self.screen.simulation.paused)
        self.screen.handle_events([pygame.event.Event(pygame.WINDOWFOCUSLOST)])
        self.assertTrue(self.screen.simulation.paused)
        self.screen.handle_back_key()
        self.assertFalse(self.screen.simulation.paused)
        self.click("Exit")
        self.assertEqual(self.screen.mode, "setup")
        self.assertTrue(all(self.screen.rosters))
        self.click("Exit")
        self.assertTrue(self.screen.done)
        self.assertEqual(self.screen.next_state, "MENU")

    def test_winner_screen_restart_and_edit_armies(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        self.win_battle()
        self.screen.update()
        self.assertEqual(self.screen.mode, "result")
        self.assertEqual(self.screen.simulation.winner, 0)
        self.assertFalse(self.screen.done)
        self.assertIsNone(self.screen.next_state)
        simulation = self.screen.simulation
        camera, zoom = list(self.screen.camera), self.screen.zoom_index
        final_state = [(fighter.x, fighter.y, fighter.data["health"]) for fighter in simulation.fighters]
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(100, 200))])
        with patch.object(simulation, "advance", wraps=simulation.advance) as advance:
            self.screen.update()
        advance.assert_not_called()
        self.assertFalse(self.screen.held_keys)
        self.assertFalse(self.screen.firing)
        self.assertEqual(self.screen.camera, camera)
        self.assertEqual(self.screen.zoom_index, zoom)
        self.assertEqual([(fighter.x, fighter.y, fighter.data["health"]) for fighter in simulation.fighters], final_state)
        self.check_result_navigation()
        self.screen.draw(self.surface)
        self.click("Run Again")
        self.assertEqual(self.screen.mode, "preview")
        self.assertEqual(self.screen.simulation.elapsed, 0)
        self.click("Start")
        self.win_battle()
        self.screen.update()
        self.click("Edit Armies")
        self.assertEqual(self.screen.mode, "setup")

    def check_result_navigation(self):
        simulation = self.screen.simulation
        final_state = [(fighter.x, fighter.y, fighter.data["health"]) for fighter in simulation.fighters]
        elapsed = simulation.elapsed
        # Each navigation check must start above the minimum, including repeated campaign cases.
        self.screen.zoom_index = battle_screen.DEFAULT_ZOOM_INDEX
        self.screen._center_camera(combat.ARENA_SIZE[0] / 2, combat.ARENA_SIZE[1] / 2)
        pointer = (100, 200)  # Empty battlefield space, outside result buttons.
        with patch("pygame.mouse.get_pos", return_value=pointer):
            initial_zoom = self.screen.zoom_index
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
            self.assertEqual(self.screen.zoom_index, initial_zoom - 1)
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
            self.assertEqual(self.screen.zoom_index, initial_zoom)
        start = list(self.screen.camera)
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pointer),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(pointer[0] + 50, pointer[1] - 30),
                               rel=(50, -30), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(pointer[0] + 50, pointer[1] - 30))])
        self.assertAlmostEqual(self.screen.camera[0], start[0] - 50 / self.screen.zoom)
        self.assertAlmostEqual(self.screen.camera[1], start[1] + 30 / self.screen.zoom)
        self.assertIsNone(self.screen.pan_drag)
        self.assertFalse(self.screen.firing)
        self.assertFalse(self.screen.secondary_firing)
        inspected_camera = list(self.screen.camera)
        with patch.object(simulation, "advance", wraps=simulation.advance) as advance:
            self.screen.update()
        advance.assert_not_called()
        self.assertEqual(self.screen.camera, inspected_camera)
        self.assertEqual(simulation.elapsed, elapsed)
        self.assertEqual([(fighter.x, fighter.y, fighter.data["health"]) for fighter in simulation.fighters], final_state)
        with patch("pygame.mouse.get_pos", return_value=pointer):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
                                       for _ in battle_screen.ZOOM_LEVELS])
        self.assertEqual(self.screen.zoom_index, 0)

    def test_preview_intro_times_cues_once_and_blocks_start_until_finished(self):
        self.fill_armies()
        with patch.object(battle_screen, "PREVIEW_SLIDE_IN_SECONDS", 0.2), \
                patch.object(battle_screen, "PREVIEW_HOLD_SECONDS", 0.3), \
                patch.object(battle_screen, "PREVIEW_SLIDE_OUT_SECONDS", 0.4), \
                patch("ui.widgets.ui_elements.play_ui_sound") as sound:
            self.click("Simulate", finish_intro=False)
            self.assertEqual([call.args[0] for call in sound.call_args_list], ["open_music"])
            simulation = self.screen.simulation
            with patch.object(simulation, "advance") as advance:
                # No timing or combat progresses before the initial black frame.
                self.screen.update()
                self.assertIsNone(self.screen.preview_intro_started)
                with patch("pygame.time.get_ticks", return_value=1000):
                    self.screen.draw(self.surface)
                for now, expected in (
                        (1199, ["open_music"]),
                        (1200, ["open_music", "select_unit_filter"]),
                        (1200, ["open_music", "select_unit_filter"]),
                        (1499, ["open_music", "select_unit_filter"]),
                        (1500, ["open_music", "select_unit_filter", "open_music"]),
                        (1500, ["open_music", "select_unit_filter", "open_music"]),
                        (1899, ["open_music", "select_unit_filter", "open_music"])):
                    with self.subTest(now=now), patch("pygame.time.get_ticks", return_value=now):
                        self.screen.update()
                        self.screen.draw(self.surface)
                        self.click("Start", finish_intro=False)
                        self.screen.start_battle()
                        self.assertEqual(self.screen.mode, "preview")
                        self.assertTrue(simulation.paused)
                        self.assertEqual([call.args[0] for call in sound.call_args_list], expected)
                with patch("pygame.time.get_ticks", return_value=1900):
                    self.screen.update()
                    self.screen.draw(self.surface)
                advance.assert_not_called()
            self.assertIsNone(self.screen.preview_intro_stage)
            self.assertEqual(simulation.elapsed, 0)
            self.click("Start")
            self.assertEqual(self.screen.mode, "battle")
            self.assertFalse(simulation.paused)

    def test_back_cancels_intro_and_reentry_handles_skipped_frames(self):
        from ui.navigation.screen import dispatch_global_keys
        self.fill_armies()
        self.click("Control")
        rosters = copy.deepcopy(self.screen.rosters)
        with patch("ui.widgets.ui_elements.play_ui_sound") as sound:
            self.click("Simulate", finish_intro=False)
            with patch("pygame.time.get_ticks", return_value=1000):
                self.screen.draw(self.surface)
            # A Back key rebound to a combat control must still allow cancellation.
            with patch("ui.navigation.screen.queries.get_keybind", return_value=pygame.K_w):
                dispatch_global_keys(self.screen, pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w))
            self.assertEqual(self.screen.mode, "setup")
            self.assertEqual(self.screen.rosters, rosters)
            self.assertIsNone(self.screen.preview_intro_stage)
            self.assertIsNone(self.screen.preview_intro_started)
            self.assertEqual(self.controller.set_tactical_battle_music.call_args.args, (False,))
            with patch("pygame.time.get_ticks", return_value=9000):
                self.screen.update()
                self.screen.draw(self.surface)
            self.assertEqual([call.args[0] for call in sound.call_args_list], ["open_music"])
            self.click("Simulate", finish_intro=False)
            with patch("pygame.time.get_ticks", return_value=10000):
                self.screen.draw(self.surface)
            with patch("pygame.time.get_ticks", return_value=20000):
                self.screen.update()
                self.screen.draw(self.surface)
                self.screen.update()
            self.assertIsNone(self.screen.preview_intro_stage)
            self.assertEqual([call.args[0] for call in sound.call_args_list],
                             ["open_music", "open_music", "select_unit_filter", "open_music"])
            self.assertTrue(self.screen.simulation.paused)

    def test_preview_freezes_deployment_and_only_preview_can_start_combat(self):
        self.fill_armies()
        self.assertNotIn("Start", [button.text for button in self.screen.elements])
        self.screen.start_battle()
        self.assertEqual(self.screen.mode, "setup")
        self.click("Control")
        self.click("Simulate")
        simulation = self.screen.simulation
        self.assertEqual(self.screen.mode, "preview")
        self.assertTrue(simulation.paused)
        before = [(f.x, f.y, f.angle, f.data["health"]) for f in simulation.fighters]
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                                      pos=self.screen.view_rect().center)])
        self.assertFalse(self.screen.firing)
        with patch.object(simulation, "advance", side_effect=AssertionError("preview executed combat")), \
                patch.object(self.screen, "_draw_battle", side_effect=AssertionError("preview opened battlefield")), \
                patch("ui.rendering.symbol_loader.get_symbol", side_effect=AssertionError("uncached unit art")):
            self.screen.update()
            self.screen.draw(self.surface)
        self.assertEqual(simulation.elapsed, 0)
        self.assertEqual(before, [(f.x, f.y, f.angle, f.data["health"]) for f in simulation.fighters])
        rosters = copy.deepcopy(self.screen.rosters)
        self.screen.add_unit(0, "Fixture I")
        self.screen.remove_unit(0)
        self.screen.generate_armies()
        self.screen.toggle_control()
        with patch("ui.dialogs.pickers.open_listbox_selector") as picker:
            self.screen.open_picker(0)
            picker.assert_not_called()
        self.assertEqual(self.screen.rosters, rosters)
        self.click("Start")
        self.assertEqual(self.screen.mode, "battle")
        self.assertIs(self.screen.simulation, simulation)
        self.assertFalse(simulation.paused)
        self.assertFalse(self.screen.held_keys)
        self.assertNotIn("Start", [button.text for button in self.screen.elements])

    def test_roster_preview_reorders_only_the_friendly_army_and_redeploys_it(self):
        self.fill_armies()
        self.screen.add_unit(0, "Fixture III")
        self.screen.add_unit(1, "Fixture II")
        for _ in range(10):
            self.screen.add_unit(0, "Fixture I")
        self.screen.selected[0] = 1
        self.click("Control")
        self.screen.roster_0_scroll = 0
        self.click("Simulate")
        self.screen.draw(self.surface)
        selected = list(self.screen.selected)
        enemy = list(self.screen.rosters[1])
        before = self.screen.simulation
        start, end = self.screen.card_rect(0, 1).center, self.screen.card_rect(0, 0).center
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
            pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(end[0] - start[0], 0), buttons=(1, 0, 0))])
        self.screen.draw(self.surface)  # The dragged card has no gear button in preview.
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end)])
        self.assertEqual(self.roster_types(0)[:2], ["Fixture III", "Fixture II"])
        self.assertEqual(self.screen.controlled_index, 0)
        self.assertEqual(self.screen.selected, selected)
        self.assertIsNone(self.screen.drag)
        # The paused battle deploys again: the leftmost card now stands in the front rank.
        simulation = self.screen.simulation
        self.assertIsNot(simulation, before)
        self.assertTrue(simulation.paused)
        front, second = simulation.divisions[:2]
        self.assertEqual(front[0].data["type"], "Fixture III")
        self.assertGreater(front[0].x, second[0].x)
        self.assertIs(simulation.controlled, front[0])
        self.drag_card(self.screen.card_rect(1, 0).center, self.screen.card_rect(1, 1).center)
        self.assertEqual(self.screen.rosters[1], enemy)
        rosters = copy.deepcopy(self.screen.rosters)
        with patch("pygame.mouse.get_pos", return_value=self.screen.panes[0].center):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
        self.assertLess(self.screen.roster_0_scroll, 0)
        self.assertEqual(self.screen.rosters, rosters)
        self.assertFalse(any(button.text in {"Add Friendly", "Add Enemy", "Remove", "Control",
                                             "Release Control", "Random", "Simulate"}
                             for button in self.screen.elements))
        self.assertFalse(any(isinstance(element, Slider) for element in self.screen.elements))
        self.click("Retreat")
        self.assertEqual(self.screen.mode, "setup")
        self.assertEqual(self.screen.rosters, rosters)

    def test_actual_battle_lowers_music_and_zooming_out_lowers_it_further(self):
        scale = self.controller.set_music_volume_scale
        self.fill_armies()
        self.click("Simulate")
        # Preview keeps full music volume.
        self.assertTrue(all(call.args == (1.0,) for call in scale.call_args_list))
        self.click("Start")
        default_zoom = battle_screen.ZOOM_LEVELS[battle_screen.DEFAULT_ZOOM_INDEX]
        expected = lambda: battle_screen.BATTLE_MUSIC_VOLUME * min(1.0, self.screen.zoom / default_zoom)
        self.assertAlmostEqual(scale.call_args.args[0], expected())
        center = self.screen.view_rect().center
        quieter = scale.call_args.args[0]
        for _ in battle_screen.ZOOM_LEVELS:
            self.screen.zoom_by(-1, center)
            self.assertAlmostEqual(scale.call_args.args[0], expected())
            self.assertLessEqual(scale.call_args.args[0], quieter)
            quieter = scale.call_args.args[0]
        self.assertLess(quieter, battle_screen.BATTLE_MUSIC_VOLUME)
        for _ in battle_screen.ZOOM_LEVELS:
            self.screen.zoom_by(1, center)
            self.assertAlmostEqual(scale.call_args.args[0], expected())
        # Zooming in past the default zoom never makes battle music louder than BATTLE_MUSIC_VOLUME.
        self.assertEqual(scale.call_args.args[0], battle_screen.BATTLE_MUSIC_VOLUME)
        self.click("Exit")
        self.assertEqual(scale.call_args.args, (1.0,))

    def test_zooming_out_lowers_shot_sounds(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        source = self.screen.simulation.divisions[0][0]
        center = self.screen.view_rect().center
        default_zoom = battle_screen.ZOOM_LEVELS[battle_screen.DEFAULT_ZOOM_INDEX]
        for steps in (2, -len(battle_screen.ZOOM_LEVELS)):
            self.screen.zoom_by(steps, center)
            with self.subTest(zoom=self.screen.zoom), patch("ui.widgets.ui_elements.play_ui_sound") as sound:
                self.screen.simulation._fire_shot(source)
                self.assertAlmostEqual(sound.call_args.kwargs["volume_scale"],
                                       battle_screen.BATTLE_SFX_VOLUME * min(1.0, self.screen.zoom / default_zoom))

    def test_editable_music_and_sfx_multipliers_apply_independently_at_every_zoom(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        source, target = self.screen.simulation.fighters
        default_zoom = battle_screen.ZOOM_LEVELS[battle_screen.DEFAULT_ZOOM_INDEX]
        for music, effects in ((0.3, 0.7), (0.0, 1.0), (1.0, 0.0)):
            with patch.object(battle_screen, "BATTLE_MUSIC_VOLUME", music), patch.object(
                    battle_screen, "BATTLE_SFX_VOLUME", effects):
                for index, zoom in enumerate(battle_screen.ZOOM_LEVELS):
                    with self.subTest(music=music, effects=effects, zoom=zoom), patch(
                            "ui.widgets.ui_elements.play_ui_sound") as sound:
                        self.screen.zoom_index = index
                        share = min(1.0, zoom / default_zoom)
                        self.screen.update_battle_music_volume()
                        self.assertAlmostEqual(self.controller.set_music_volume_scale.call_args.args[0], music * share)
                        self.screen.simulation._fire_shot(source)
                        target.shape = "infantry"
                        self.screen._play_hit_sound(target, 1)
                        target.shape = "tank"
                        self.screen._play_hit_sound(target, 0)
                        self.assertEqual(sound.call_count, 3)
                        for entry in sound.call_args_list:
                            self.assertAlmostEqual(entry.kwargs["volume_scale"], effects * share)

    def test_music_override_spans_preview_and_actual_and_ends_on_exit_or_result(self):
        music = self.controller.set_tactical_battle_music
        music.reset_mock()
        self.fill_armies()
        music.assert_not_called()
        self.click("Simulate")
        tanks = self.screen.simulation.enemy_has_tanks()
        music.assert_called_once_with(True, tanks=tanks)
        self.click("Start")
        self.click("Pause")
        self.click("Resume")
        music.assert_called_once_with(True, tanks=tanks)
        self.click("Exit")
        self.assertEqual(music.call_args.args, (False,))
        self.click("Simulate")
        self.screen.handle_back_key()
        self.assertEqual(music.call_args.args, (False,))
        self.click("Simulate")
        self.click("Start")
        self.win_battle()
        self.screen.update()
        self.assertEqual(self.screen.mode, "result")
        self.assertEqual(music.call_args.args, (False,))

    def test_control_follows_reordered_entries_and_clears_when_removed(self):
        for name in ("Fixture I", "Fixture II", "Fixture III"):
            self.screen.add_unit(0, name)
        self.click("Control")
        self.assertEqual(self.screen.controlled_index, 2)
        self.drag_card(self.screen.card_rect(0, 2).center, self.screen.card_rect(0, 0).center)
        self.assertEqual(self.screen.controlled_index, 0)
        self.screen.add_unit(1, "Fixture I")
        self.click("Simulate")
        self.assertEqual(self.screen.simulation.controlled.data["type"], "Fixture III")
        self.click("Retreat")
        self.drag_card(self.screen.card_rect(0, 2).center, self.screen.card_rect(0, 0).center)
        self.assertEqual(self.screen.controlled_index, 1)
        self.click("Remove")
        self.assertEqual(self.screen.controlled_index, 0)
        self.drag_card(self.screen.card_rect(0, 0).center, self.screen.card_rect(0, 0).center)
        self.click("Remove")
        self.assertIsNone(self.screen.controlled_index)

    def test_release_control_and_random_generation_return_to_automatic_armies(self):
        self.fill_armies()
        self.click("Control")
        self.assertEqual(self.screen.controlled_index, 0)
        self.click("Release Control")
        self.assertIsNone(self.screen.controlled_index)
        self.click("Control")
        self.screen.random_candidates = ["Fixture I", "Fixture II"]
        self.screen.refresh_ui()
        self.click("Random")
        self.assertIsNone(self.screen.controlled_index)

    def test_left_mouse_fires_at_point_blank_and_zoom_does_not_change_combat_coordinates(self):
        self.screen.add_unit(0, "Fixture I")
        self.screen.add_unit(1, "Fixture I")
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        simulation = self.screen.simulation
        player, target = simulation.fighters
        hold_still(simulation)
        player.cooldown = 0
        target.x, target.y = player.x + combat.UNIT_RADIUS * 2 + 4, player.y
        before_positions = [(unit.x, unit.y) for unit in simulation.fighters]
        self.screen.zoom_by(-100, self.screen.to_screen(player.x, player.y))
        self.assertEqual([(unit.x, unit.y) for unit in simulation.fighters], before_positions)
        pointer = self.screen.to_screen(target.x, target.y)
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pointer)])
        with patch("pygame.mouse.get_pos", return_value=pointer), patch(
                "pygame.time.get_ticks", return_value=self.screen.last_tick + 34):
            self.screen.update()
        self.assertLess(target.data["health"], target.data["max_health"])
        self.assertEqual(simulation.projectiles, [])
        self.screen.draw(self.surface)  # Also exercises the reload ring at the control zoom limit.
        self.click("Pause")
        self.assertFalse(self.screen.firing)

    def test_controlled_stats_follow_live_values_cache_unchanged_values_and_clear_after_death(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.assertIsNone(self.screen.controlled_stats_surface)
        self.click("Start")
        simulation = self.screen.simulation
        player = simulation.controlled
        player.speed, player.angle, player.cooldown = -50, math.radians(450), 1.21
        with patch.object(simulation, "advance"):
            self.screen.update()
            self.assertEqual(self.screen.controlled_stats_key, (-50, 90, 13))
            cached = self.screen.controlled_stats_surface
            self.screen.update()
            self.assertIs(self.screen.controlled_stats_surface, cached)
            self.click("Pause")
            self.screen.update()
            self.assertIs(self.screen.controlled_stats_surface, cached)
            player.cooldown = 0
            self.screen.update()
            self.assertEqual(self.screen.controlled_stats_key[-1], 0)
            self.assertIsNot(self.screen.controlled_stats_surface, cached)
            player.data["health"] = 0
            self.screen.update()
            self.assertIsNone(self.screen.controlled_stats_surface)
            self.assertIsNone(self.screen.controlled_stats_key)

    def test_uncontrolled_battle_has_no_controlled_stats(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        self.screen.update()
        self.assertIsNone(self.screen.controlled_stats_surface)

    def test_player_keys_move_left_mouse_fires_and_pause_clears_held_input(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        player = self.screen.simulation.controlled
        initial_x = player.x
        view = self.screen.view_rect()
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)])
        self.assertFalse(self.screen.firing)
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center)])
        self.assertTrue(self.screen.firing)
        # The pointer sits straight ahead of the unit, so the gun need not turn.
        ahead = self.screen.to_screen(player.x + 100, player.y)
        with patch("pygame.time.get_ticks", return_value=self.screen.last_tick + 100), \
                patch("pygame.mouse.get_pos", return_value=ahead):
            self.screen.update()
        self.assertGreater(player.x, initial_x)
        self.assertTrue(any(shot.source is player for shot in self.screen.simulation.projectiles))
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=view.center)])
        self.assertFalse(self.screen.firing)
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center)])
        self.click("Pause")
        self.assertFalse(self.screen.held_keys)
        self.assertFalse(self.screen.firing)
        self.click("Resume")
        player.speed = 0
        stopped_x = player.x
        with patch("pygame.time.get_ticks", return_value=self.screen.last_tick + 100):
            self.screen.update()
        self.assertEqual(player.x, stopped_x)
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.WINDOWFOCUSLOST)])
        self.assertTrue(self.screen.simulation.paused)
        self.assertFalse(self.screen.held_keys)

    def test_camera_follows_the_controlled_unit_or_pans_when_dragged(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        view = self.screen.view_rect()
        width, height = combat.ARENA_SIZE
        self.assertEqual(self.screen.camera, [(width - view.width) / 2, (height - view.height) / 2])
        start = self.screen.camera
        # The battlefield follows the pointer, so dragging right moves the view left.
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(view.centerx + 30, view.centery - 20),
                               rel=(30, -20), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(view.centerx + 30, view.centery - 20))])
        self.assertEqual(self.screen.camera, [start[0] - 30, start[1] + 20])
        self.assertFalse(self.screen.firing)
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(view.centerx + 5000, view.centery + 5000),
                               rel=(5000, 5000), buttons=(1, 0, 0))])
        self.assertEqual(self.screen.camera, [0.0, 0.0])
        self.click("Exit")
        self.click("Control")
        self.click("Simulate")
        with patch("pygame.mouse.get_pos", return_value=view.center):
            self.click("Start")
        player = self.screen.simulation.controlled
        camera = self.screen.camera
        self.assertEqual(self.screen.to_field(view.center),
                         (max(view.width / 2, player.x), player.y))
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(view.centerx + 30, view.centery),
                               rel=(30, 0), buttons=(1, 0, 0))])
        self.assertEqual(self.screen.camera, camera)
        self.assertTrue(self.screen.firing)
        self.screen.draw(self.surface)

    def test_controlled_camera_offsets_toward_aim_at_each_zoom_without_drifting(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        simulation = self.screen.simulation
        player = simulation.controlled
        player.x, player.y = (side / 2 for side in combat.ARENA_SIZE)
        view = self.screen.view_rect()
        for zoom_index in (battle_screen.DEFAULT_ZOOM_INDEX, battle_screen.DEFAULT_ZOOM_INDEX + 1):
            self.screen.zoom_index = zoom_index
            for dx, dy in ((0, 0), (200, 0), (-200, 0), (0, 100), (0, -100),
                           (200, 100), (-200, 100), (200, -100), (-200, -100)):
                pointer = view.centerx + dx, view.centery + dy
                with self.subTest(zoom=self.screen.zoom, direction=(dx, dy)), \
                        patch("pygame.mouse.get_pos", return_value=pointer), patch.object(simulation, "advance"):
                    self.screen.update()
                    expected = (player.x + dx * battle_screen.AIM_CAMERA_OFFSET / self.screen.zoom,
                                player.y + dy * battle_screen.AIM_CAMERA_OFFSET / self.screen.zoom)
                    for actual, wanted in zip(self.screen.to_field(view.center), expected):
                        self.assertAlmostEqual(actual, wanted)
                    self.assertEqual(simulation._aim_point, self.screen.to_field(pointer))
                    camera = self.screen.camera[:]
                    for _ in range(5):
                        self.screen.update()
                    self.assertEqual(self.screen.camera, camera)

    def test_controlled_camera_respects_edges_and_stops_following_after_death(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        simulation = self.screen.simulation
        player = simulation.controlled
        view = self.screen.view_rect()
        width, height = combat.ARENA_SIZE
        with patch.object(simulation, "advance"):
            for position, pointer, expected in (
                    ((combat.UNIT_RADIUS, combat.UNIT_RADIUS), view.topleft, [0, 0]),
                    ((width - combat.UNIT_RADIUS, height - combat.UNIT_RADIUS), view.bottomright,
                     [width - view.width / self.screen.zoom, height - view.height / self.screen.zoom])):
                player.x, player.y = position
                with patch("pygame.mouse.get_pos", return_value=pointer):
                    self.screen.update()
                self.assertEqual(self.screen.camera, expected)
            player.data["health"] = 0
            camera = self.screen.camera[:]
            with patch("pygame.mouse.get_pos", return_value=view.topleft):
                self.screen.update()
            self.assertEqual(self.screen.camera, camera)

    def test_edit_battle_forecasts_the_normal_game_only_when_the_armies_change(self):
        self.screen.add_unit(0, "Fixture II")
        self.assertIsNone(self.screen.forecast_surface)
        with patch.object(battle_screen.combat, "normal_game_forecast", return_value=(0, 3)) as forecast:
            self.screen.add_unit(1, "Fixture I")
            self.assertIsNotNone(self.screen.forecast_surface)
            self.assertEqual(forecast.call_count, 1)
            self.assertEqual(forecast.call_args.args, tuple(self.screen.rosters))
            # Selection and nationality leave the forecast alone; health changes it.
            self.screen.selected[0] = None
            self.screen.refresh_ui()
            self.screen.set_unit_options(1, self.screen.rosters[1], owner="Fixture A")
            self.assertEqual(forecast.call_count, 1)
            self.screen.set_unit_options(1, self.screen.rosters[1], health_percent=50)
            self.assertEqual(forecast.call_count, 2)
            self.screen.draw(self.surface)
        self.screen.remove_unit(1)
        self.screen.refresh_ui()
        self.assertIsNone(self.screen.forecast_surface)

    def test_controlled_zoom_uses_configured_minimum_and_unlocks_after_death(self):
        self.enterContext(patch.object(battle_screen, "CONTROLLED_MIN_ZOOM", battle_screen.ZOOM_LEVELS[1]))
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        pointer = self.screen.view_rect().center
        self.screen.zoom_by(-100, pointer)
        self.click("Start")
        minimum = battle_screen.CONTROLLED_MIN_ZOOM
        self.assertEqual(self.screen.zoom, minimum)
        self.screen.zoom_by(1, pointer)
        self.assertGreater(self.screen.zoom, minimum)
        with patch("pygame.mouse.get_pos", return_value=pointer):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
                                       for _ in battle_screen.ZOOM_LEVELS])
        self.assertEqual(self.screen.zoom, minimum)
        self.click("Pause")
        self.screen.zoom_by(-100, pointer)
        self.assertEqual(self.screen.zoom, minimum)
        self.screen.simulation.controlled.data["health"] = 0
        self.screen.zoom_by(-100, pointer)
        self.assertEqual(self.screen.zoom, battle_screen.ZOOM_LEVELS[0])

    def test_wheel_zooms_around_the_pointer_and_buttons_still_take_clicks(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        pointer = (500, 300)
        anchor = self.screen.to_field(pointer)
        with patch("pygame.mouse.get_pos", return_value=pointer):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1)])
        self.assertEqual(self.screen.zoom, battle_screen.ZOOM_LEVELS[battle_screen.DEFAULT_ZOOM_INDEX + 1])
        for got, expected in zip(self.screen.to_field(pointer), anchor):
            self.assertAlmostEqual(got, expected)
        # Dragging pans by battlefield distance, so it moves less on screen when zoomed in.
        start = self.screen.camera
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pointer),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(pointer[0] + 50, pointer[1]), rel=(50, 0), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(pointer[0] + 50, pointer[1]))])
        self.assertAlmostEqual(self.screen.camera[0], start[0] - 50 / self.screen.zoom)
        with patch("pygame.mouse.get_pos", return_value=pointer):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
                                       for _ in battle_screen.ZOOM_LEVELS])
        self.assertEqual(self.screen.zoom, battle_screen.ZOOM_LEVELS[0])
        # Zoomed out past an edge, the battlefield sits in the middle of the screen along that direction.
        width, height = combat.ARENA_SIZE
        span_width, span_height = self.screen._view_span()
        center = self.screen.to_screen(width / 2, height / 2)
        self.assertGreater(span_height, height)
        self.assertEqual(center[1], self.screen.view_rect().centery)
        if span_width > width:
            self.assertEqual(center[0], self.screen.view_rect().centerx)
        self.screen.draw(self.surface)
        self.click("Pause")
        self.assertTrue(self.screen.simulation.paused)

    def test_losing_the_controlled_sub_unit_spectates_but_keeps_a_surviving_division(self):
        with patch.dict(combat.SUBUNIT_COUNTS, {"infantry": 10}):
            map_screen, province, _custom = self.enter_campaign()
        self.click("Start")
        simulation = self.screen.simulation
        player, enemy = province["units"]
        view = self.screen.view_rect()
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center)])
        self.assertTrue(self.screen.firing)
        lost = simulation.controlled
        lost.data["health"] = 0
        self.screen.update()
        # Spectating: no unit takes the player's input, and dragging moves the view instead of firing.
        self.assertIs(simulation.controlled, lost)
        self.assertFalse(self.screen.held_keys)
        self.assertFalse(self.screen.firing)
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=view.center)])
        self.assertFalse(self.screen.firing)
        self.assertEqual(self.screen.pan_drag, view.center)
        for fighter in simulation.divisions[1]:
            fighter.data["health"] = 0
        simulation.winner = 0
        self.screen.update()
        self.assertEqual(province["units"], [player])
        self.assertAlmostEqual(player["health"], player["max_health"] * 0.9)
        with patch("screens.game.custom_battle.player_setup.lose_tactical_unit") as lose:
            self.click("Continue")
        lose.assert_not_called()
        self.assertEqual(self.screen.next_state, "MAP")

    def test_player_keys_are_reserved_from_rebound_menu_and_mouse_commands(self):
        from ui.navigation.screen import dispatch_global_keys, synthesize_keybind_mouse_events
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)
        with patch("ui.navigation.screen.queries.get_keybind", return_value=pygame.K_w):
            dispatch_global_keys(self.screen, event)
        self.assertFalse(self.screen.simulation.paused)
        translated = synthesize_keybind_mouse_events(
            [event], {"MOUSE_LEFT_CLICK": pygame.K_w}, reserved_keys=self.screen.reserved_keys)
        self.assertEqual(translated, [event])

    def test_unit_limit_is_rechecked_and_setup_draw_uses_cached_cards(self):
        self.screen.rosters[0] = [self.screen._new_unit(0, "Fixture I")
                                  for _ in range(c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE)]
        self.screen.refresh_ui()
        self.screen.add_unit(0, "Fixture II")
        self.assertEqual(len(self.screen.rosters[0]), c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE)
        with patch("map_logic.custom_battle.unit_shape", side_effect=AssertionError("uncached geometry")):
            self.screen.draw(self.surface)

    def test_back_cancels_drag_and_scroll_background_follows_pointer(self):
        self.fill_armies()
        point = self.screen.card_rect(0, 0).center
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point)])
        self.screen.handle_back_key()
        self.assertIsNone(self.screen.drag)
        self.assertEqual(self.screen.mode, "setup")
        self.screen.rosters[0] = [self.screen._new_unit(0, "Fixture I") for _ in range(12)]
        self.screen.refresh_ui()
        self.screen.draw(self.surface)
        self.screen.roster_0_scroll = -100
        # Gaps between cards use the shared content-drag direction.
        pane = self.screen.panes[0]
        first, second = (self.screen.card_rect(0, index) for index in (0, 1))
        point = ((first.right + second.left) // 2, pane.centery)
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point),
            pygame.event.Event(pygame.MOUSEMOTION, pos=(point[0] + 10, point[1]),
                               rel=(10, 0), buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(point[0] + 10, point[1]))])
        self.assertEqual(self.screen.roster_0_scroll, -90)

    def test_main_menu_button_and_controller_transition(self):
        from tests import app_harness
        # Boot menus without the unrelated online version check.
        with patch("screens.menus.menu.Menu.check_version"):
            controller, surface = app_harness.boot()
        original = controller.active_state
        menu = controller.states["MENU"]
        target = controller.states["CUSTOM_BATTLE"]
        try:
            menu.custom_battle_btn.callback()
            controller.active_state = menu
            controller.flip_state()
            self.assertIs(controller.active_state, target)
            self.assertEqual(target.mode, "setup")
            target.draw(surface)
            target.leave()
            controller.flip_state()
            self.assertIs(controller.active_state, menu)
        finally:
            controller.active_state = original
            menu.done = target.done = False


if __name__ == "__main__":
    unittest.main()
