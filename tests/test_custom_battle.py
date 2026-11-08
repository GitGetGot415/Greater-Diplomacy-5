"""Standalone battle mechanics, setup input, and safe pause/exit navigation."""

import copy
import math
import random
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pygame

import data.constants as c
from map_logic import custom_battle as combat
from screens.game.custom_battle import CustomBattleScreen
from ui.rendering.font_manager import fonts


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
                         {"Car 2", "Foot 1910", "Motorized 1910", "Tank 1"})

    def test_year_is_inclusive_and_advances_levels_without_keeping_obsolete_tiers(self):
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1912)),
                         {"Car 2", "Foot 1910"})
        self.assertEqual(set(combat.land_unit_types_for_year(self.library, 1920)),
                         {"Car 3", "Foot 1918", "Motorized 1910", "Tank 1"})
        self.assertEqual(combat.land_unit_types_for_year(self.library, 1799), [])

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

    def test_projectile_impacts_use_shared_defense(self):
        from map_logic.system32 import combat_processor
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        source, target = simulation.fighters
        target.data.update(defense=15, health=50, max_health=100)
        expected = dict(target.data)
        combat_processor.apply_group_damage(30, [expected])
        simulation.projectiles = [combat.Projectile(source, target.x - 5, target.y, 300, 0, 30, 1)]
        simulation.advance(combat.FIXED_STEP)
        self.assertEqual(target.data["health"], math.floor(expected["health"]))

    def test_simultaneous_destruction_is_a_loss_and_finished_battle_stays_finished(self):
        simulation = combat.BattleSimulation(self.library, ["Fixture I"], ["Fixture I"])
        simulation.advance(60)
        self.assertEqual(simulation.winner, 1)
        elapsed = simulation.elapsed
        simulation.advance(60)
        self.assertEqual(simulation.elapsed, elapsed)


class CustomBattleScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.surface = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        fonts.init_fonts()

    def setUp(self):
        self.library = fixture_library()
        self.screen = CustomBattleScreen()
        with patch("data.queries.get_unit_library", return_value=self.library):
            self.screen.on_enter(SimpleNamespace(), None)

    def click(self, label):
        button = next(button for button in self.screen.elements if button.text == label)
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center)])

    def fill_armies(self):
        self.screen.add_unit(0, "Fixture II")
        self.screen.add_unit(1, "Fixture I")

    def test_year_slider_and_generate_button_replace_both_armies(self):
        library, tree = dated_fixture_content()
        with patch("data.queries.get_unit_library", return_value=library), \
                patch("data.queries.get_tech_tree", return_value=tree):
            self.screen.on_enter(SimpleNamespace(), None)
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
                self.click("Randomly Generate")
            self.assertEqual(tuple(map(len, self.screen.rosters)), (3, 5))
            self.assertTrue(set(sum(self.screen.rosters, [])) <= {"Car 2", "Foot 1910"})
            self.assertEqual(self.screen.selected, [None, None])
            self.assertEqual(self.screen.mode, "setup")
            self.screen.draw(self.surface)

    def test_generation_with_no_eligible_units_preserves_existing_rosters(self):
        library, tree = dated_fixture_content()
        with patch("data.queries.get_unit_library", return_value=library), \
                patch("data.queries.get_tech_tree", return_value=tree):
            self.screen.on_enter(SimpleNamespace(), None)
            self.screen.update_generation_year(0)
            self.screen.add_unit(0, "Car 1")
            self.assertTrue(self.screen.generate_button.disabled)
            self.click("Randomly Generate")
            self.assertEqual(self.screen.rosters[0], ["Car 1"])
            self.screen.generate_armies()
            self.assertEqual(self.screen.rosters[0], ["Car 1"])

    def drag_card(self, start, end):
        self.screen.handle_events([
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=start),
            pygame.event.Event(pygame.MOUSEMOTION, pos=end, rel=(end[0] - start[0], end[1] - start[1]),
                               buttons=(1, 0, 0)),
            pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=end)])

    def test_start_requires_two_armies_and_picker_can_add_repeated_levels(self):
        self.click("Start")
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
        self.click("Start")
        self.screen.simulation.advance(60)
        self.screen.update()
        self.assertEqual(self.screen.mode, "result")
        self.assertEqual(self.screen.simulation.winner, 0)
        self.screen.draw(self.surface)
        self.click("Run Again")
        self.assertEqual(self.screen.mode, "battle")
        self.assertEqual(self.screen.simulation.elapsed, 0)
        self.screen.simulation.advance(60)
        self.screen.update()
        self.click("Edit Armies")
        self.assertEqual(self.screen.mode, "setup")

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
