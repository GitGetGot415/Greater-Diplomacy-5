"""Weapon timing, penetration, deployment, and continuous tactical controls."""

import copy
import math
import unittest
from unittest.mock import patch

import pygame

from data import constants as c, queries
from data.generators import recipes
from map_logic import battle_terrain, custom_battle as combat
from screens.game import custom_battle as battle_screen
from tests import test_custom_battle as battle_fixtures
from ui.navigation.touch_input import TouchInput


def weapon(*, shell=False, soft=False, interval=0.2, rounds=3, reload=0.8,
           speed=900.0, damage=0.4, penetration=0.0):
    return dict(label="Fixture gun", interval=interval, rounds=rounds, reload=reload,
                speed=speed, spread=0.0, damage=damage, penetration=penetration,
                shell=shell, soft_only=soft)


class TacticalWeaponTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(combat.SUBUNIT_COUNTS, infantry=1))
        self.enterContext(patch.dict(c.TACTICAL_WEAPONS, {
            "fixture_rifle": weapon(),
            "fixture_cannon": weapon(shell=True, interval=1.4, rounds=1, reload=1.4,
                                     speed=2400, damage=2, penetration=3),
            "fixture_mg": weapon(soft=True, interval=0.1, rounds=4, reload=0.5,
                                 speed=1200, damage=0.15),
        }))
        self.enterContext(patch.dict(c.TACTICAL_VEHICLE_WEAPONS, tank=("fixture_cannon", "fixture_mg")))
        self.enterContext(patch.dict(c.TACTICAL_BODIES, infantry=(15, 15, 8.0, 1.0),
                                    tank=(40, 28, 20.0, 4.0)))
        self.library = {name: battle_fixtures.unit_stats(health=1000, attack=80, defense=0, speed=0)
                        for name in ("Shooter I", "Target I")}
        for stats in self.library.values():
            stats["metadata"]["tactical_primary"] = "fixture_rifle"

    def encounter(self, *, targets=1, controlled=0):
        field = battle_terrain.Battlefield("plains", combat.ARENA_SIZE, combat.UNIT_RADIUS)
        simulation = combat.BattleSimulation(self.library, ["Shooter I"], ["Target I"] * targets,
                                             controlled_index=controlled, seed=8, battlefield=field)
        for index, fighter in enumerate(simulation.fighters):
            fighter.x, fighter.y = 1000 + index * 100, 500
            fighter.cooldown = fighter.secondary_cooldown = 1000
        return simulation

    def test_primary_and_secondary_fire_together_and_reload_independently(self):
        simulation = self.encounter()
        source = simulation.controlled
        source.shape = "tank"
        source.cooldown = source.secondary_cooldown = 0
        fired = []
        simulation.on_shot = lambda fighter: fired.append(fighter.fired_weapon)
        simulation.set_player_input(fire=True, secondary_fire=True)
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(fired, [0, 1])
        cannon_wait = source.cooldown
        simulation.advance(0.2)
        self.assertEqual(fired.count(0), 1)
        self.assertGreater(fired.count(1), 1)
        self.assertLess(source.cooldown, cannon_wait)
        self.assertEqual(source.primary_rounds, 0)
        self.assertGreater(source.secondary_rounds, 0)

    def test_one_weapon_ignores_secondary_input(self):
        simulation = self.encounter()
        source = simulation.controlled
        source.cooldown = 0
        simulation.set_player_input(secondary_fire=True)
        simulation.advance(1)
        self.assertEqual(simulation.projectiles, [])
        self.assertEqual(source.primary_rounds, 0)

    def test_magazine_uses_shot_interval_then_full_reload(self):
        source = self.encounter().controlled
        profile = source.weapon()
        for shot in range(profile["rounds"]):
            queue = []
            combat.BattleSimulation._queue_shot(source, queue)
            self.assertEqual(queue, [(source, 0)])
            expected = profile["reload"] if shot == profile["rounds"] - 1 else profile["interval"]
            self.assertEqual(source.cooldown, expected)
            self.assertEqual(source.reload_duration(), expected)
        self.assertEqual(source.primary_rounds, 0)

    def test_pause_does_not_reload_or_queue_missed_rounds(self):
        simulation = self.encounter()
        source = simulation.controlled
        source.cooldown = 0.4
        simulation.set_player_input(fire=True)
        simulation.paused = True
        simulation.advance(100)
        self.assertEqual(source.cooldown, 0.4)
        self.assertEqual(source.primary_rounds, 0)
        simulation.paused = False
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(simulation.projectiles, [])

    def test_projectile_snapshots_weapon_and_uses_its_speed_and_reach(self):
        simulation = self.encounter()
        source = simulation.controlled
        source.shape = "tank"
        simulation._fire_shot(source)
        shot = simulation.projectiles[0]
        self.assertEqual(math.hypot(shot.vx, shot.vy), source.weapon()["speed"])
        self.assertEqual(shot.remaining * source.weapon()["speed"], combat.WEAPON_RANGE)
        snapshot = copy.deepcopy(shot.weapon_data)
        source.shape = "infantry"
        self.assertEqual(shot.weapon_data, snapshot)
        self.assertTrue(shot.weapon_data["shell"])

    def test_faster_projectiles_require_less_target_lead(self):
        target = self.encounter().fighters[1]
        target.vy = 60
        slow = combat.BattleSimulation._lead_point(target, (1000, 500), 500)
        fast = combat.BattleSimulation._lead_point(target, (1000, 500), 2000)
        self.assertGreater(slow[1], fast[1])

    def test_movement_and_hull_rotation_increase_spread(self):
        source = self.encounter().controlled
        source.data["speed"] = 2
        stationary = combat.BattleSimulation._shot_spread(source, source.weapon())
        source.speed = source.max_speed
        moving = combat.BattleSimulation._shot_spread(source, source.weapon())
        source.turn_rate = math.radians(combat.MOBILITY[source.shape][1])
        turning = combat.BattleSimulation._shot_spread(source, source.weapon())
        self.assertGreater(moving, stationary)
        self.assertGreater(turning, moving)

    def test_penetration_orders_hits_and_loses_power_before_stopping(self):
        simulation = self.encounter(targets=4)
        source, *targets = simulation.fighters
        source.shape = "tank"
        shot = combat.Projectile(source, dict(source.data), source.x, source.y, 18000, 0, 1)
        simulation.projectiles = [shot]
        simulation.advance(combat.FIXED_STEP)
        losses = [fighter.data["max_health"] - fighter.data["health"] for fighter in targets]
        expected = simulation.weapon_damage(source.data, targets[0].data, source.attack_share,
                                            shot.weapon_data, targets[0].shape)
        self.assertAlmostEqual(losses[0], expected)
        self.assertAlmostEqual(losses[1], expected * c.TACTICAL_PENETRATION_DAMAGE_RETAINED)
        self.assertAlmostEqual(losses[2], expected * c.TACTICAL_PENETRATION_DAMAGE_RETAINED ** 2)
        self.assertEqual(losses[3], 0)
        self.assertEqual(simulation.projectiles, [])

    def test_shell_spread_scales_base_movement_and_turning_without_affecting_bullets(self):
        source = self.encounter().controlled
        source.data["speed"] = 2
        source.speed = source.max_speed
        source.turn_rate = math.radians(combat.MOBILITY[source.shape][1])
        bullet = dict(source.weapon(), spread=4.0)
        shell = dict(bullet, shell=True)
        with patch.object(c, "TACTICAL_MOVING_SPREAD", 2.0), patch.object(
                c, "TACTICAL_TURNING_SPREAD", 3.0), patch.object(c, "TACTICAL_SHELL_SPREAD_MULTIPLIER", 0.25):
            self.assertAlmostEqual(combat.BattleSimulation._shot_spread(source, bullet), math.radians(9.0))
            self.assertAlmostEqual(combat.BattleSimulation._shot_spread(source, shell), math.radians(9.0 * 0.25))
            source.speed = source.turn_rate = 0
            self.assertAlmostEqual(combat.BattleSimulation._shot_spread(source, shell), math.radians(4.0 * 0.25))

    def test_only_the_lethal_hit_records_a_kill_including_friendly_fire(self):
        simulation = self.encounter(targets=2)
        source, target, bystander = simulation.fighters
        target.side = source.side
        target.data["health"] = 1
        kills = []
        simulation.on_kill = lambda killer, victim, cause: kills.append((killer, victim, cause))
        simulation.projectiles = [combat.Projectile(source, dict(source.data), source.x, source.y, 18000, 0, 1)
                                  for _ in range(2)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(kills, [(source, target, "shot")])
        self.assertTrue(bystander.alive)
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(len(kills), 1)

    def test_penetrating_kills_credit_the_shooter_even_after_its_death(self):
        simulation = self.encounter(targets=2)
        source, first, second = simulation.fighters
        source.shape = "tank"
        first.data["health"] = second.data["health"] = 1
        shot = combat.Projectile(source, dict(source.data), source.x, source.y, 18000, 0, 1)
        source.data["health"] = 0
        kills = []
        simulation.on_kill = lambda killer, victim, cause: kills.append((killer, victim, cause))
        simulation.projectiles = [shot]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(kills, [(source, first, "shot"), (source, second, "shot")])

    def test_shell_cannot_damage_the_same_body_again_on_later_ticks(self):
        simulation = self.encounter(targets=2)
        source, first, second = simulation.fighters
        source.shape = "tank"
        second.x = 1800
        hits = []
        simulation.on_hit = lambda target, damage: hits.append((target, damage))
        simulation.projectiles = [combat.Projectile(source, dict(source.data), first.x - first.radius - 1,
                                                   first.y, 300, 0, 2)]
        simulation.advance(combat.FIXED_STEP)
        health = first.data["health"]
        self.assertLess(health, first.data["max_health"])
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(first.data["health"], health)
        self.assertEqual(len(hits), 1)
        self.assertIs(hits[0][0], first)
        self.assertEqual(hits[0][1], first.data["max_health"] - health)

    def test_armor_stops_a_shell_and_machine_gun_cannot_borrow_cannon_damage(self):
        simulation = self.encounter(targets=2)
        source, armor, behind = simulation.fighters
        source.shape = armor.shape = "tank"
        self.assertEqual(simulation.weapon_damage(source.data, armor.data, source.attack_share,
                                                 source.weapon(1), armor.shape), 0)
        simulation.projectiles = [combat.Projectile(source, dict(source.data), source.x, source.y, 18000, 0, 1)]
        simulation.advance(combat.FIXED_STEP)
        self.assertLess(armor.data["health"], armor.data["max_health"])
        self.assertEqual(behind.data["health"], behind.data["max_health"])

    def test_weapon_scaling_preserves_full_defense_and_shared_target_immunity(self):
        simulation = self.encounter()
        source, target = simulation.fighters
        profile = source.weapon()
        target.data["defense"] = source.data["attack"] + 1
        self.assertEqual(simulation.weapon_damage(source.data, target.data, 1, profile, target.shape), 0)
        target.data["defense"] = source.data["attack"] / 2
        expected = simulation.damage_amount(source.data, target.data, 1) * profile["damage"]
        self.assertEqual(simulation.weapon_damage(source.data, target.data, 1, profile, target.shape), expected)
        with patch("data.queries.unit_target_damage_multiplier", return_value=0.0):
            self.assertEqual(simulation.weapon_damage(source.data, target.data, 1, profile, target.shape), 0)

    def test_penetrating_shell_can_hit_an_ally_after_its_target_and_ai_checks_that_lane(self):
        simulation = self.encounter(targets=2)
        source, target, ally = simulation.fighters
        source.shape = "tank"
        ally.side = source.side
        simulation._sides = [[source, ally], [target]]
        self.assertIs(simulation._ally_in_line(source, target), ally)
        self.assertIsNone(simulation._ally_in_line(source, target, slot=1))
        simulation.projectiles = [combat.Projectile(source, dict(source.data), source.x, source.y, 18000, 0, 1)]
        simulation.advance(combat.FIXED_STEP)
        self.assertLess(target.data["health"], target.data["max_health"])
        self.assertLess(ally.data["health"], ally.data["max_health"])

    def test_terrain_stops_penetration_without_destroying_trees(self):
        for slot in (0, 1):
            with self.subTest(slot=slot):
                simulation = self.encounter(targets=2)
                source, first, second = simulation.fighters
                source.shape = "tank"
                tree = battle_terrain.Feature("tree", 1150, 500, 10, 100)
                simulation.battlefield = battle_terrain.Battlefield("plains", combat.ARENA_SIZE, 8, [tree])
                simulation.projectiles = [combat.Projectile(source, dict(source.data), source.x, source.y,
                                                           18000, 0, 1, weapon_data=dict(source.weapon(slot)))]
                simulation.advance(combat.FIXED_STEP)
                self.assertFalse(tree.destroyed)
                self.assertEqual(second.data["health"], second.data["max_health"])

    def test_both_ai_sides_use_independent_weapons(self):
        simulation = self.encounter(controlled=None)
        for fighter in simulation.fighters:
            fighter.shape = "tank"
            fighter.cooldown = fighter.secondary_cooldown = 0
        first, second = simulation.fighters
        second.shape = "infantry"
        for source, target in ((first, second), (second, first)):
            with self.subTest(side=source.side):
                source.shape, target.shape = "tank", "infantry"
                source.cooldown = source.secondary_cooldown = 0
                source.target = source.secondary_target = target
                source.aim = source.angle = math.atan2(target.y - source.y, target.x - source.x)
                simulation._sides = [[fighter for fighter in simulation.fighters if fighter.side == side]
                                     for side in (0, 1)]
                shots = []
                simulation._drive_ai(source, combat._Grid([target], combat.TARGET_CELL), combat.FIXED_STEP,
                                     shots, (source.x, source.y), target)
                self.assertEqual(shots, [(source, 0), (source, 1)])

    def test_deployment_uses_active_metadata_without_adding_campaign_fields(self):
        self.library["Shooter I"]["metadata"]["tactical_support"] = "fixture_mg"
        record = queries.create_unit_dict("Shooter I", "Fixture", self.library)
        before = copy.deepcopy(record)
        with patch.dict(combat.SUBUNIT_COUNTS, infantry=4):
            simulation = combat.BattleSimulation(self.library, [record], ["Target I"], controlled_index=0)
        weapons = [fighter.primary_weapon for fighter in simulation.divisions[0]]
        self.assertEqual(weapons.count("fixture_mg"), 1)
        self.assertEqual(weapons.count("fixture_rifle"), 3)
        self.assertEqual(simulation.controlled.primary_weapon, "fixture_rifle")
        self.assertEqual(record, before)
        self.assertNotIn("tactical_primary", simulation.controlled.data)

    def test_optional_metadata_rejects_unknown_weapon_names(self):
        self.library["Shooter I"]["metadata"]["tactical_primary"] = "missing"
        with self.assertRaisesRegex(ValueError, "tactical_primary"):
            self.encounter()

    def test_equipment_generator_assigns_weapons_from_the_stage_table(self):
        stats = dict(health=100, attack=20, defense=0, speed=1, cost_materials=1,
                     cost_manpower=1, cost_fuel=0, production_time=1)
        family = recipes.EquipmentFamily("Infantry Type", ["1900"], stats, research_key="infantry_type",
                                         research_years=[1900], stage_names=["Fixture Infantry I"])
        with patch.dict(recipes.EQUIPMENT_STAGES, infantry_type=[(1900, "Fixture Infantry")]), patch.dict(
                recipes.EQUIPMENT_TACTICAL_WEAPONS, infantry_type=[("fixture_rifle", "fixture_mg")]):
            _, entry = family.entries()[0]
        self.assertEqual(entry["metadata"]["tactical_primary"], "fixture_rifle")
        self.assertEqual(entry["metadata"]["tactical_support"], "fixture_mg")

    def test_content_without_optional_weapon_metadata_uses_standard_rifle(self):
        for stats in self.library.values():
            del stats["metadata"]["tactical_primary"]
        simulation = self.encounter()
        self.assertIs(simulation.controlled.weapon(), c.TACTICAL_WEAPONS["rifle"])

    def test_body_radius_controls_projectile_collision_and_terrain_clearance(self):
        simulation = self.encounter()
        target = simulation.fighters[1]
        with patch.dict(c.TACTICAL_BODIES, infantry=(12, 12, 6, 1), tank=(36, 24, 18, 4)):
            target.shape = "infantry"
            self.assertIsNone(simulation._collision_fraction(1000, 512, 1200, 512, target))
            target.shape = "tank"
            self.assertIsNotNone(simulation._collision_fraction(1000, 512, 1200, 512, target))
            field = battle_terrain.Battlefield("plains", (500, 500), 6,
                                              [battle_terrain.Feature("rock", 250, 200, 20, 100)])
            self.assertTrue(field.clear_path((100, 230), (400, 230), 6))
            self.assertFalse(field.clear_path((100, 230), (400, 230), 18))
            path = field.route((100, 230), (400, 230), 18)
            self.assertTrue(path)
            start = (100, 230)
            for point in path:
                self.assertTrue(field.clear_path(start, point, 18))
                start = point
            self.assertEqual(field.move((100, 100), (0, 100), 18), (18, 100))


class TacticalHitSoundTests(unittest.TestCase):
    setUpClass = classmethod(battle_fixtures.CustomBattleScreenTests.setUpClass.__func__)
    setUp = battle_fixtures.CustomBattleScreenTests.setUp
    fill_armies = battle_fixtures.CustomBattleScreenTests.fill_armies
    click = battle_fixtures.CustomBattleScreenTests.click

    def start_battle(self):
        self.fill_armies()
        self.click("Simulate")
        self.click("Start")
        simulation = self.screen.simulation
        for index, fighter in enumerate(simulation.fighters):
            fighter.x, fighter.y = 1000 + index * 100, 500
            fighter.data.update(speed=0, health=1000, max_health=1000)
            fighter.cooldown = fighter.secondary_cooldown = 1000
        return simulation

    def test_unarmored_hits_use_each_flesh_variant_on_both_sides_with_zoom_scaling(self):
        simulation = self.start_battle()
        self.screen.zoom_index = 0
        for target in simulation.fighters:
            for shape in combat.SOFT_TARGET_SHAPES:
                target.shape = shape
                with self.subTest(side=target.side, shape=shape), patch.object(
                        battle_screen.random, "choice", side_effect=battle_screen.FLESH_HIT_SOUNDS) as choice, patch(
                        "ui.widgets.ui_elements.play_ui_sound") as sound:
                    for _ in battle_screen.FLESH_HIT_SOUNDS:
                        self.screen._play_hit_sound(target, 5)
                    self.assertEqual([entry.args[0] for entry in sound.call_args_list],
                                     list(battle_screen.FLESH_HIT_SOUNDS))
                    self.assertTrue(all(entry.kwargs["volume_scale"] == battle_screen.BATTLE_SFX_VOLUME * self.screen.zoom_volume_share()
                                        for entry in sound.call_args_list))
                    self.assertTrue(all(entry.args == (battle_screen.FLESH_HIT_SOUNDS,)
                                        for entry in choice.call_args_list))

    def test_armored_ricochets_include_zero_and_exactly_one_percent_but_not_larger_hits(self):
        simulation = self.start_battle()
        for target in simulation.fighters:
            for shape in combat.MOBILITY.keys() - combat.SOFT_TARGET_SHAPES:
                target.shape = shape
                for damage, ricochet in ((0, True), (5, True), (10, True), (10.001, False), (20, False)):
                    with self.subTest(side=target.side, shape=shape, damage=damage), patch.object(
                            battle_screen.random, "choice", return_value=battle_screen.RICOCHET_SOUNDS[0]) as choice, patch(
                            "ui.widgets.ui_elements.play_ui_sound") as sound:
                        self.screen._play_hit_sound(target, damage)
                        if ricochet:
                            choice.assert_called_once_with(battle_screen.RICOCHET_SOUNDS)
                            sound.assert_called_once_with(battle_screen.RICOCHET_SOUNDS[0],
                                                          volume_scale=battle_screen.BATTLE_SFX_VOLUME * self.screen.zoom_volume_share())
                        else:
                            choice.assert_not_called()
                            sound.assert_not_called()

    def test_projectile_impact_sound_uses_actual_hp_lost_including_remaining_hp_limit(self):
        simulation = self.start_battle()
        source, target = simulation.fighters
        target.shape = "tank"
        target.data["health"] = 1
        simulation.projectiles = [combat.Projectile(source, dict(source.data),
                                                   target.x - target.radius - 1, target.y, 300, 0, 1)]
        with patch.object(simulation, "weapon_damage", return_value=11), patch.object(
                self.screen, "_play_hit_sound", wraps=self.screen._play_hit_sound) as hit, patch(
                "screens.game.custom_battle.random.choice", return_value=battle_screen.RICOCHET_SOUNDS[0]), patch(
                "ui.widgets.ui_elements.play_ui_sound") as sound:
            simulation.on_hit = hit
            simulation.advance(combat.FIXED_STEP)
        hit.assert_called_once_with(target, 1)
        sound.assert_called_once_with(battle_screen.RICOCHET_SOUNDS[0], volume_scale=battle_screen.BATTLE_SFX_VOLUME * self.screen.zoom_volume_share())
        self.assertEqual(target.data["health"], 0)

    def test_each_simultaneous_hit_uses_its_actual_hp_loss(self):
        simulation = self.start_battle()
        source, target = simulation.fighters
        target.shape = "tank"
        target.data["health"] = 15
        simulation.projectiles = [combat.Projectile(source, dict(source.data),
                                                   target.x - target.radius - 1, target.y, 300, 0, 1)
                                  for _ in range(2)]
        with patch.object(simulation, "weapon_damage", return_value=11), patch.object(
                self.screen, "_play_hit_sound", wraps=self.screen._play_hit_sound) as hit, patch(
                "screens.game.custom_battle.random.choice", return_value=battle_screen.RICOCHET_SOUNDS[0]), patch(
                "ui.widgets.ui_elements.play_ui_sound") as sound:
            simulation.on_hit = hit
            simulation.advance(combat.FIXED_STEP)
        self.assertEqual([entry.args[1] for entry in hit.call_args_list], [11, 4])
        sound.assert_called_once_with(battle_screen.RICOCHET_SOUNDS[0], volume_scale=battle_screen.BATTLE_SFX_VOLUME * self.screen.zoom_volume_share())

    def check_projectile_sound(self, hit_kind):
        simulation = self.start_battle()
        source, target = simulation.fighters
        if hit_kind == "terrain":
            simulation.battlefield = battle_terrain.Battlefield("plains", combat.ARENA_SIZE, 8,
                [battle_terrain.Feature("rock", 1050, 500, 10, 100)])
        simulation.projectiles = [combat.Projectile(source, dict(source.data), source.x,
            source.y + (100 if hit_kind == "miss" else 0), 6000, 0, 1)]
        with patch.object(battle_screen.random, "choice", return_value=battle_screen.FLESH_HIT_SOUNDS[0]), patch(
                "ui.widgets.ui_elements.play_ui_sound") as sound:
            simulation.advance(combat.FIXED_STEP)
        if hit_kind == "body":
            sound.assert_called_once_with(battle_screen.FLESH_HIT_SOUNDS[0],
                                          volume_scale=battle_screen.BATTLE_SFX_VOLUME * self.screen.zoom_volume_share())
        else:
            sound.assert_not_called()

    def test_projectile_body_hit_plays_exactly_one_hit_sound(self):
        self.check_projectile_sound("body")

    def test_projectile_miss_does_not_play_a_hit_sound(self):
        self.check_projectile_sound("miss")

    def test_projectile_terrain_hit_does_not_play_a_body_hit_sound(self):
        self.check_projectile_sound("terrain")

    def test_ram_damage_does_not_trigger_projectile_hit_sounds(self):
        simulation = self.start_battle()
        target = simulation.fighters[1]
        with patch.object(simulation, "_resolve_contacts", return_value=[(target, 5, simulation.fighters[0])]), patch(
                "ui.widgets.ui_elements.play_ui_sound") as sound:
            simulation.advance(combat.FIXED_STEP)
        self.assertEqual(target.data["health"], 995)
        sound.assert_not_called()


class TacticalTouchTests(unittest.TestCase):
    setUpClass = classmethod(battle_fixtures.CustomBattleScreenTests.setUpClass.__func__)
    setUp = battle_fixtures.CustomBattleScreenTests.setUp
    fill_armies = battle_fixtures.CustomBattleScreenTests.fill_armies
    click = battle_fixtures.CustomBattleScreenTests.click

    def start_controlled(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        self.screen.simulation.controlled.shape = "tank"
        with patch("ui.navigation.touch_input.detect_control_mode", return_value="MOBILE"):
            touch = TouchInput()
        touch.process_events([], self.screen, "MOBILE")
        return touch

    def send(self, touch, kind, position, finger=1):
        event = pygame.event.Event(kind, touch_id=1, finger_id=finger,
                                   x=position[0] / c.SCREEN_WIDTH, y=position[1] / c.SCREEN_HEIGHT)
        self.screen.handle_events(touch.process_events([event], self.screen, "MOBILE"))

    def test_two_thumbs_drive_aim_and_fire_both_weapons_without_mouse_clicks(self):
        touch = self.start_controlled()
        drive, aim = (self.screen._touch_pad_rect(role) for role in ("drive", "aim"))
        self.screen._select_touch_weapon("Both")
        self.send(touch, pygame.FINGERDOWN, (drive.centerx, drive.top), 1)
        self.send(touch, pygame.FINGERDOWN, (aim.right - 1, aim.centery), 2)
        self.assertEqual(len(self.screen.touch_pointers), 2)
        self.assertFalse(self.screen.firing)
        with patch.object(self.screen.simulation, "advance"):
            self.screen.update()
        simulation = self.screen.simulation
        self.assertEqual(simulation._move_direction, (0.0, -1.0))
        self.assertTrue(simulation._fire)
        self.assertTrue(simulation._secondary_fire)
        self.assertGreater(simulation._aim_point[0], simulation.controlled.x)
        self.send(touch, pygame.FINGERUP, aim.center, 2)
        self.assertEqual(len(self.screen.touch_pointers), 1)
        with patch.object(simulation, "advance"):
            self.screen.update()
        self.assertFalse(simulation._fire)
        self.assertEqual(simulation._move_direction, (0.0, -1.0))

    def test_drive_pad_passes_screen_directions_and_releases_in_its_dead_zone(self):
        touch = self.start_controlled()
        drive = self.screen._touch_pad_rect("drive")
        self.send(touch, pygame.FINGERDOWN, drive.center)
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1)):
            with self.subTest(direction=(dx, dy)):
                position = (drive.centerx + dx * drive.width / 2, drive.centery + dy * drive.height / 2)
                self.send(touch, pygame.FINGERMOTION, position)
                with patch.object(self.screen.simulation, "advance"):
                    self.screen.update()
                expected = pygame.Vector2(dx, dy).normalize()
                actual = self.screen.simulation._move_direction
                self.assertAlmostEqual(actual[0], expected.x)
                self.assertAlmostEqual(actual[1], expected.y)
        self.send(touch, pygame.FINGERMOTION, drive.center)
        with patch.object(self.screen.simulation, "advance"):
            self.screen.update()
        self.assertEqual(self.screen.simulation._move_direction, (0.0, 0.0))
        self.send(touch, pygame.FINGERUP, drive.center)
        with patch.object(self.screen.simulation, "advance"):
            self.screen.update()
        self.assertEqual(self.screen.simulation._move_direction, (0.0, 0.0))
        self.assertFalse(self.screen.touch_pointers)

    def test_selector_works_while_drive_finger_is_held(self):
        touch = self.start_controlled()
        drive = self.screen._touch_pad_rect("drive")
        self.send(touch, pygame.FINGERDOWN, (drive.centerx, drive.top), 1)
        button = next(button for button in self.screen.touch_weapon_buttons if button.text == "Secondary")
        self.send(touch, pygame.FINGERDOWN, button.rect.center, 2)
        self.send(touch, pygame.FINGERUP, button.rect.center, 2)
        self.assertEqual(self.screen.touch_weapon_mode, "Secondary")
        self.assertEqual(len(self.screen.touch_pointers), 1)

    def test_death_removes_weapon_selector_from_input_and_pause_does_not_restore_it(self):
        self.screen.add_unit(0, "Fixture I")
        touch = self.start_controlled()
        simulation = self.screen.simulation
        self.screen._select_touch_weapon("Both")
        buttons = list(self.screen.touch_weapon_buttons)
        self.assertEqual(len(buttons), 3)
        with patch.object(simulation, "advance", side_effect=lambda dt: simulation.controlled.data.update(health=0)):
            self.screen.update()
        self.assertTrue(any(fighter.alive and fighter.side == 0 for fighter in simulation.fighters))
        self.assertEqual(self.screen.mode, "battle")
        self.assertFalse(self.screen.touch_weapon_buttons)
        self.assertTrue(all(button not in self.screen.elements for button in buttons))
        for button in buttons:
            self.send(touch, pygame.FINGERDOWN, button.rect.center)
            self.send(touch, pygame.FINGERUP, button.rect.center)
        self.assertEqual(self.screen.touch_weapon_mode, "Both")
        self.screen.toggle_pause()
        self.assertFalse(self.screen.touch_weapon_buttons)
        self.screen.toggle_pause()
        self.assertFalse(self.screen.touch_weapon_buttons)

    def test_focus_loss_clears_both_thumbs_and_fire(self):
        touch = self.start_controlled()
        for finger, role in enumerate(("drive", "aim"), start=1):
            rect = self.screen._touch_pad_rect(role)
            self.send(touch, pygame.FINGERDOWN, (rect.centerx, rect.top), finger)
        event = pygame.event.Event(pygame.WINDOWFOCUSLOST)
        self.screen.handle_events(touch.process_events([event], self.screen, "MOBILE"))
        self.assertEqual(self.screen.touch_pointers, {})
        self.assertFalse(touch.direct_pointers)
        self.assertTrue(self.screen.simulation.paused)
        self.assertFalse(self.screen.simulation._fire)
        self.assertFalse(self.screen.simulation._secondary_fire)
        self.assertIsNone(self.screen.simulation._move_direction)

    def test_single_weapon_still_fires_after_secondary_was_selected_for_a_vehicle(self):
        touch = self.start_controlled()
        self.screen._select_touch_weapon("Secondary")
        self.screen.simulation.controlled.shape = "infantry"
        aim = self.screen._touch_pad_rect("aim")
        self.send(touch, pygame.FINGERDOWN, (aim.right - 1, aim.centery), 2)
        with patch.object(self.screen.simulation, "advance"):
            self.screen.update()
        self.assertTrue(self.screen.simulation._fire)
        self.assertFalse(self.screen.simulation._secondary_fire)

    def test_screen_change_cancels_held_pads_until_fingers_are_released(self):
        touch = self.start_controlled()
        drive = self.screen._touch_pad_rect("drive")
        self.send(touch, pygame.FINGERDOWN, (drive.centerx, drive.top), 1)
        replacement = battle_screen.CustomBattleScreen()
        touch.process_events([], replacement, "MOBILE")
        self.assertFalse(self.screen.touch_pointers)
        self.assertFalse(touch.direct_pointers)
        event = pygame.event.Event(pygame.FINGERUP, touch_id=1, finger_id=1,
                                   x=drive.centerx / c.SCREEN_WIDTH, y=drive.top / c.SCREEN_HEIGHT)
        self.assertEqual(touch.process_events([event], replacement, "MOBILE"), [])

    def test_desktop_mouse_buttons_independently_fire_and_release(self):
        self.start_controlled()
        self.screen.set_touch_mode(False)
        point = self.screen.view_rect().center
        for button in (1, 3):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=button, pos=point)])
        self.assertTrue(self.screen.firing)
        self.assertTrue(self.screen.secondary_firing)
        self.screen.handle_events([pygame.event.Event(pygame.MOUSEBUTTONUP, button=3, pos=point)])
        self.assertTrue(self.screen.firing)
        self.assertFalse(self.screen.secondary_firing)

    def test_vehicle_machine_gun_uses_rifle_sound_instead_of_cannon_sound(self):
        self.start_controlled()
        source = self.screen.simulation.controlled
        with patch("ui.widgets.ui_elements.play_ui_sound") as sound:
            self.screen.simulation._fire_shot(source, 1)
        self.assertEqual(sound.call_args.args[0], "heavy_gunshot")


if __name__ == "__main__":
    unittest.main()
