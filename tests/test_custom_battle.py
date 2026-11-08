"""Standalone battle mechanics, setup input, and safe pause/exit navigation."""

import copy
import math
import random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pygame

import data.constants as c
from map_logic import custom_battle as combat
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


class BattleSimulationTests(unittest.TestCase):
    def setUp(self):
        self.library = fixture_library()

    def test_catalog_and_constructor_reject_air_sea_unknown_and_empty_rosters(self):
        self.assertEqual(set(combat.land_unit_types(self.library)),
                         {"Fixture I", "Fixture II", "Fixture Gun I"})
        for roster in ([], ["missing"], ["Fixture Ship I"], ["Fixture Plane I"],
                       ["Fixture I"] * (c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE + 1)):
            with self.subTest(roster=roster[:2]), self.assertRaises(ValueError):
                combat.BattleSimulation(self.library, roster, ["Fixture I"])

    def test_units_use_library_stats_without_mutating_content_or_rosters(self):
        before = copy.deepcopy(self.library)
        roster = ["Fixture I", "Fixture II", "Fixture Gun I"]
        simulation = combat.BattleSimulation(self.library, roster, ["Fixture I"])
        for fighter, name in zip(simulation.fighters, roster):
            for field in ("health", "attack", "defense", "speed"):
                self.assertEqual(fighter.data[field], self.library[name][field])
        simulation.advance(30)
        self.assertEqual(self.library, before)
        self.assertEqual(roster, ["Fixture I", "Fixture II", "Fixture Gun I"])

    def test_automatic_battle_reaches_win_and_loss(self):
        for friendly, enemy, expected in (("Fixture II", "Fixture I", 0),
                                          ("Fixture I", "Fixture II", 1)):
            with self.subTest(friendly=friendly):
                simulation = combat.BattleSimulation(self.library, [friendly], [enemy])
                simulation.advance(60)
                self.assertEqual(simulation.winner, expected)
                self.assertTrue(all(not fighter.alive for fighter in simulation.fighters
                                    if fighter.side != expected))

    def test_fixed_steps_are_independent_of_frame_partition(self):
        whole = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture II"])
        partitioned = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture II"])
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

    def test_bombardment_uses_library_weapon_and_longer_range(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture Gun I"], ["Fixture I"])
        gun, infantry = simulation.fighters
        self.assertEqual(gun.data["bombard_attack"], self.library["Fixture Gun I"]["bombard_attack"])
        self.assertGreater(gun.weapon_range, infantry.weapon_range)

    def test_projectile_impacts_subtract_full_defense_even_when_wounded_on_either_side(self):
        for target_side in (0, 1):
            for health, defense, expected_health in (
                    (100, 15, 85), (50, 15, 35), (50, 30, 50), (50, 40, 50), (10, 0, 0)):
                with self.subTest(target_side=target_side, health=health, defense=defense):
                    simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
                    target = simulation.fighters[target_side]
                    source = simulation.fighters[1 - target_side]
                    target.data.update(defense=defense, health=health, max_health=100)
                    simulation.projectiles = [combat.Projectile(
                        source, target.x - 5, target.y, 300, 0, 30, 1)]
                    simulation.advance(combat.FIXED_STEP)
                    self.assertEqual(target.data["health"], expected_health)

    def test_defense_blocks_each_simultaneous_hit_separately(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        source, target = simulation.fighters
        target.data.update(defense=20, health=100, max_health=100)
        simulation.projectiles = [combat.Projectile(
            source, target.x - 5, target.y, 300, 0, 30, 1) for _ in range(2)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(target.data["health"], 80)

    def test_simultaneous_destruction_is_a_loss_and_finished_battle_stays_finished(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        simulation.advance(60)
        self.assertEqual(simulation.winner, 1)
        elapsed = simulation.elapsed
        simulation.advance(60)
        self.assertEqual(simulation.elapsed, elapsed)

    def test_controlled_unit_only_moves_along_its_heading_and_turns_in_place(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        player = simulation.controlled
        x, y = player.x, player.y
        simulation.advance(0.1)
        self.assertEqual((player.x, player.y, player.angle), (x, y, 0.0))
        player.angle = math.pi / 2
        simulation.set_player_input(throttle=1)
        simulation.advance(0.1)
        self.assertAlmostEqual(player.x, x)
        self.assertGreater(player.y, y)
        simulation.set_player_input(throttle=-1)
        simulation.advance(0.1)
        self.assertAlmostEqual(player.x, x)
        self.assertAlmostEqual(player.y, y)
        simulation.set_player_input(turn=1)
        simulation.advance(0.1)
        self.assertGreater(player.angle, math.pi / 2)
        self.assertAlmostEqual(player.x, x)
        self.assertAlmostEqual(player.y, y)
        simulation.set_player_input(turn=-1)
        simulation.advance(0.1)
        self.assertAlmostEqual(player.angle, math.pi / 2)

    def test_manual_fire_uses_heading_and_cooldown_even_when_space_is_held(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        player = simulation.controlled
        player.angle = math.pi / 2
        with patch.object(combat, "Projectile", wraps=combat.Projectile) as projectiles:
            simulation.advance(combat.FIXED_STEP)
            self.assertEqual(projectiles.call_count, 0)
            simulation.set_player_input(fire=True)
            simulation.advance(combat.FIXED_STEP)
            self.assertEqual(projectiles.call_count, 1)
            shot = simulation.projectiles[0]
            self.assertAlmostEqual(shot.vx, 0)
            self.assertGreater(shot.vy, 0)
            simulation.advance(combat.FIRE_INTERVAL / 2)
            self.assertEqual(projectiles.call_count, 1)
            simulation.set_player_input(fire=False)
            simulation.set_player_input(fire=True)
            simulation.advance(combat.FIRE_INTERVAL / 2 + 2 * combat.FIXED_STEP)
            self.assertEqual(projectiles.call_count, 2)

    def test_manual_shots_can_miss_and_hit_without_homing(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=0)
        player, target = simulation.fighters
        target.x, target.y = player.x + 100, player.y
        target.data["speed"] = 0
        initial_health = target.data["health"]
        player.angle = math.pi / 2
        simulation.set_player_input(fire=True)
        simulation.advance(0.3)
        self.assertEqual(target.data["health"], initial_health)
        player.angle = 0
        player.cooldown = 0
        simulation.advance(0.3)
        self.assertLess(target.data["health"], initial_health)

    def test_controlled_index_must_refer_to_a_friendly_entry(self):
        for index in (-1, 1, True, "0"):
            with self.subTest(index=index), self.assertRaises(ValueError):
                combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"], controlled_index=index)


class CustomBattleScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        fonts.init_fonts()

    def setUp(self):
        self.library = fixture_library()
        self.screen = battle_screen.CustomBattleScreen()
        self.controller = SimpleNamespace(set_tactical_battle_music=Mock())
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
            self.assertEqual(self.screen.rosters[0], ["Car 1"])
            with patch("map_logic.custom_battle.random.randint", side_effect=[3, 5]):
                self.click("Random")
            self.assertEqual(tuple(map(len, self.screen.rosters)), (3, 5))
            self.assertTrue(set(sum(self.screen.rosters, [])) <= {"Car 2", "Foot 1910"})
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
            self.assertEqual(self.screen.rosters[0], ["Car 1"])
            self.screen.generate_armies()
            self.assertEqual(self.screen.rosters[0], ["Car 1"])

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
        self.assertEqual(self.screen.rosters[0], ["Fixture II", "Fixture II"])
        self.assertFalse(options["close_on_select"])

    def test_reordering_and_invalid_drop_preserve_armies(self):
        for name in ("Fixture I", "Fixture II", "Fixture Gun I"):
            self.screen.add_unit(0, name)
        self.screen.draw(self.surface)
        self.drag_card(self.screen.card_rect(0, 0).center, self.screen.card_rect(0, 2).center)
        self.assertEqual(self.screen.rosters[0], ["Fixture II", "Fixture Gun I", "Fixture I"])
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
        self.click("Simulate")
        self.click("Start")
        self.screen.simulation.advance(60)
        self.screen.update()
        self.assertEqual(self.screen.mode, "result")
        self.assertEqual(self.screen.simulation.winner, 0)
        self.screen.draw(self.surface)
        self.click("Run Again")
        self.assertEqual(self.screen.mode, "preview")
        self.assertEqual(self.screen.simulation.elapsed, 0)
        self.click("Start")
        self.screen.simulation.advance(60)
        self.screen.update()
        self.click("Edit Armies")
        self.assertEqual(self.screen.mode, "setup")

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
                                   pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)])
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

    def test_roster_preview_allows_scrolling_without_selection_or_reordering(self):
        self.fill_armies()
        for _ in range(10):
            self.screen.add_unit(0, "Fixture I")
        self.click("Control")
        self.screen.roster_0_scroll = 0
        self.click("Simulate")
        self.screen.draw(self.surface)
        rosters = copy.deepcopy(self.screen.rosters)
        selected = list(self.screen.selected)
        controlled = self.screen.controlled_index
        self.drag_card(self.screen.card_rect(0, 0).center, self.screen.card_rect(0, 1).center)
        self.assertEqual(self.screen.rosters, rosters)
        self.assertEqual(self.screen.selected, selected)
        self.assertEqual(self.screen.controlled_index, controlled)
        self.assertIsNone(self.screen.drag)
        with patch("pygame.mouse.get_pos", return_value=self.screen.panes[0].center):
            self.screen.handle_events([pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)])
        self.assertLess(self.screen.roster_0_scroll, 0)
        self.assertEqual(self.screen.rosters, rosters)
        self.assertFalse(any(button.text in {"Add Friendly", "Add Enemy", "Remove", "Control",
                                             "Release Control", "Random", "Simulate"}
                             for button in self.screen.elements))
        self.assertFalse(any(isinstance(element, Slider) for element in self.screen.elements))
        self.click("Exit")
        self.assertEqual(self.screen.mode, "setup")
        self.assertEqual(self.screen.rosters, rosters)

    def test_music_override_spans_preview_and_actual_and_ends_on_exit_or_result(self):
        music = self.controller.set_tactical_battle_music
        music.reset_mock()
        self.fill_armies()
        music.assert_not_called()
        self.click("Simulate")
        music.assert_called_once_with(True)
        self.click("Start")
        self.click("Pause")
        self.click("Resume")
        music.assert_called_once_with(True)
        self.click("Exit")
        self.assertEqual(music.call_args.args, (False,))
        self.click("Simulate")
        self.screen.handle_back_key()
        self.assertEqual(music.call_args.args, (False,))
        self.click("Simulate")
        self.click("Start")
        self.screen.simulation.advance(60)
        self.screen.update()
        self.assertEqual(self.screen.mode, "result")
        self.assertEqual(music.call_args.args, (False,))

    def test_control_follows_reordered_entries_and_clears_when_removed(self):
        for name in ("Fixture I", "Fixture II", "Fixture Gun I"):
            self.screen.add_unit(0, name)
        self.click("Control")
        self.assertEqual(self.screen.controlled_index, 2)
        self.drag_card(self.screen.card_rect(0, 2).center, self.screen.card_rect(0, 0).center)
        self.assertEqual(self.screen.controlled_index, 0)
        self.screen.add_unit(1, "Fixture I")
        self.click("Simulate")
        self.assertEqual(self.screen.simulation.controlled.data["type"], "Fixture Gun I")
        self.click("Exit")
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

    def test_player_key_events_move_and_fire_and_pause_clears_held_input(self):
        self.fill_armies()
        self.click("Control")
        self.click("Simulate")
        self.click("Start")
        player = self.screen.simulation.controlled
        initial_x = player.x
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)])
        with patch("pygame.time.get_ticks", return_value=self.screen.last_tick + 100):
            self.screen.update()
        self.assertGreater(player.x, initial_x)
        self.assertTrue(any(shot.source is player for shot in self.screen.simulation.projectiles))
        self.click("Pause")
        self.assertFalse(self.screen.held_keys)
        self.click("Resume")
        stopped_x = player.x
        with patch("pygame.time.get_ticks", return_value=self.screen.last_tick + 100):
            self.screen.update()
        self.assertEqual(player.x, stopped_x)
        self.screen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w),
                                   pygame.event.Event(pygame.WINDOWFOCUSLOST)])
        self.assertTrue(self.screen.simulation.paused)
        self.assertFalse(self.screen.held_keys)

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
        self.screen.rosters[0] = ["Fixture I"] * c.CUSTOM_BATTLE_MAX_UNITS_PER_SIDE
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
        self.screen.rosters[0] = ["Fixture I"] * 12
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
