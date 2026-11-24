"""Conscription damage must agree across combat, previews, and saved state."""

import json
import math
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


import pygame

import data.constants as c
from data import queries
from map_logic import politics
from map_logic.system32 import combat_processor, combat_rules
from screens.game.economy import Economy_Screen
from tests.stub_map_screen import StubMapScreen as EconomyMap
from tests.stub_map_screen import sample_map_screen
from tests.combat_fixtures import StubBattleMap
from tests.politics_fixtures import policy_fixtures
from ui.panels.sidebar_info import unit_roster_row
from ui.widgets.ui_elements import Slider

from tests.combat_fixtures import install_neutral_territory
from data.session_state import REALTIME

# Territory damage is a politics rule; these tests measure combat mechanics.
install_neutral_territory(globals())


def fixture_unit(owner):
    return {"owner": owner, "type": "Conscription fixture", "health": 1000,
            "max_health": 1000, "attack": 80, "bombard_attack": 60,
            "defense": 0, "speed": 1, "order": {"type": "IDLE"}}


def damage_caption(rate):
    """The economy screen caption for a conscription rate, from the shared bonus rule."""
    return f"dmg modifier: +{queries.get_conscription_damage_bonus({'conscription_slider': rate}):.2%}"


class ConscriptionCurveTests(unittest.TestCase):
    def bonus(self, rate):
        return queries.get_conscription_damage_bonus({"conscription_slider": rate})

    def test_requested_conscription_and_damage_pairs(self):
        # The requested rule: full, half, quarter, and zero conscription give none,
        # a quarter, a half, and all of the maximum bonus.
        for rate, share in ((1.0, 0.0), (0.5, 0.25), (0.25, 0.5), (0.0, 1.0)):
            with self.subTest(rate=rate):
                self.assertAlmostEqual(self.bonus(rate), share * c.CONSCRIPTION_MAX_DAMAGE_BONUS)

    def test_intermediate_values_follow_exponential_segments(self):
        self.assertAlmostEqual(self.bonus(0.375), math.sqrt(self.bonus(0.5) * self.bonus(0.25)))
        self.assertAlmostEqual(self.bonus(0.125), math.sqrt(self.bonus(0.25) * self.bonus(0.0)))
        self.assertAlmostEqual(self.bonus(0.75), self.bonus(0.5) * (math.sqrt(2.0) - 1.0))

    def test_bonus_increases_faster_toward_zero_conscription(self):
        bonuses = [self.bonus(1.0 - step / 100.0) for step in range(101)]
        increments = [end - start for start, end in zip(bonuses, bonuses[1:])]
        self.assertTrue(all(increment > 0 for increment in increments))
        self.assertTrue(all(end > start for start, end in zip(increments, increments[1:])))

    def test_segments_have_no_jump_or_slope_break_at_half(self):
        epsilon = 1e-7
        left = self.bonus(0.5 - epsilon)
        center = self.bonus(0.5)
        right = self.bonus(0.5 + epsilon)
        self.assertAlmostEqual(left, center, places=6)
        self.assertAlmostEqual(right, center, places=6)
        self.assertAlmostEqual((left - center) / epsilon, (center - right) / epsilon, places=6)

    def test_missing_setting_defaults_to_full_and_out_of_range_values_are_bounded(self):
        country = {}
        self.assertEqual(queries.get_conscription_damage_bonus(country), 0.0)
        self.assertEqual(country, {})
        self.assertEqual(self.bonus(-1), self.bonus(0))
        self.assertEqual(self.bonus(2), self.bonus(1))

    def test_existing_save_field_round_trips_and_legacy_loading_needs_no_new_fields(self):
        for rate in (None, 0.0, 0.25, 0.5, 1.0):
            with self.subTest(rate=rate):
                game = sample_map_screen()
                if rate is not None:
                    game.world.nation_data["Avaria"]["conscription_slider"] = rate
                before = queries.get_conscription_damage_bonus(game.world.nation_data["Avaria"])
                saved = json.loads(json.dumps(queries.build_save_dict(game)))
                with patch.object(queries, "get_country_data", return_value={"Avaria": {"research": {}}}):
                    loaded = queries.merge_country_templates(saved["nation_data"])
                self.assertEqual(loaded["Avaria"].get("conscription_slider"), rate)
                self.assertEqual(queries.get_conscription_damage_bonus(loaded["Avaria"]), before)


class ConscriptionCombatTests(unittest.TestCase):
    def setUp(self):
        self.library = patch.object(queries, "get_unit_library", return_value={
            "Conscription fixture": {"attack": 80, "defense": 0, "health": 1000,
                                     "bombard_attack": 60, "bombard_range": 1},
        })
        self.library.start()
        self.addCleanup(self.library.stop)

    def game(self):
        game = StubBattleMap()
        game.add_nation("A", at_war_with=["B"])
        game.add_nation("B", at_war_with=["A"])
        game.world.nation_data["A"]["conscription_slider"] = 0.25
        return game

    def test_combat_map_forecast_unit_panel_and_ai_projection_agree(self):
        for rate in (1.0, 0.5, 0.25, 0.0):
            with self.subTest(rate=rate):
                game = self.game()
                game.world.nation_data["A"]["conscription_slider"] = rate
                attacker, defender = fixture_unit("A"), fixture_unit("B")
                province = game.add_province("p1", "B", units=[attacker, defender])
                expected = attacker["attack"] * (1.0 + queries.get_conscription_damage_bonus(game.world.nation_data["A"]))
                roster = unit_roster_row(attacker, province, game.world.nation_data, True)
                battle = combat_rules.build_battle([province["units"]], game.world.nation_data)
                incoming = combat_rules.projected_incoming_damage(battle, game.world.nation_data)
                self.assertAlmostEqual(roster["attack"], expected)
                self.assertAlmostEqual(incoming[id(defender)], expected)
                combat_processor.process_combat(game)
                self.assertAlmostEqual(defender["max_health"] - defender["health"], expected)
                self.assertAlmostEqual(attacker["max_health"] - attacker["health"], defender["attack"])

    @policy_fixtures({"id": "damage_fixture", "effects": {"damage": 1.25}})
    def test_bonus_multiplies_health_politics_and_policy_without_changing_raw_stats(self):
        game = self.game()
        country = game.world.nation_data["A"]
        country.update({"political_value": c.POLITICS_MAX, politics.QUALITY_VALUE_KEY: c.POLITICS_MAX,
                        politics.POLICY_KEY: {"damage_fixture": {"status": politics.POLICY_ACTIVE}}})
        attacker = fixture_unit("A")
        attacker["health"] /= 2
        original_attack = attacker["attack"]
        expected = (combat_rules.health_damage_multiplier(attacker)
                    * politics.damage_multiplier(game.world.nation_data, "A")
                    * (1.0 + queries.get_conscription_damage_bonus(country)))
        self.assertAlmostEqual(combat_rules.effective_damage_multiplier(attacker, game.world.nation_data), expected)
        self.assertEqual(attacker["attack"], original_attack)
        self.assertEqual(combat_rules.effective_damage_multiplier(attacker),
                         combat_rules.health_damage_multiplier(attacker))

    def test_each_unit_keeps_its_owners_bonus_in_a_mixed_volley(self):
        game = self.game()
        first, second = fixture_unit("A"), fixture_unit("B")
        # Volunteer control does not replace the original owner's national modifiers.
        first["volunteer_host"] = "B"
        expected = (first["attack"] * (1.0 + queries.get_conscription_damage_bonus(game.world.nation_data["A"]))
                    + second["attack"])
        self.assertAlmostEqual(combat_rules.volley([first, second], nation_data=game.world.nation_data), expected)

    def test_bombardment_and_its_unit_panel_apply_the_same_bonus(self):
        game = self.game()
        gun, defender = fixture_unit("A"), fixture_unit("B")
        gun["order"] = {"type": "BOMBARD", "target_id": "p2"}
        origin = game.add_province("p1", "A", units=[gun])
        target = game.add_province("p2", "B", units=[defender])
        origin["neighbors"], target["neighbors"] = ["p2"], ["p1"]
        expected = unit_roster_row(gun, origin, game.world.nation_data, False)["bombard"][0]
        with patch.dict(c.BOMBARDMENT_UNITS, {"Conscription fixture": 1}, clear=True):
            combat_processor.process_bombardments(game)
        self.assertGreater(expected, gun["bombard_attack"])
        self.assertAlmostEqual(defender["max_health"] - defender["health"], expected)


class ConscriptionSliderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def screen(self, tactical=False):
        game = EconomyMap(["A", "B"])
        game.session.tactical_mode = tactical
        game.player_manpower = game.player_materials = game.player_fuel = 100
        game.session.player_unit = fixture_unit("A") if tactical else None
        game.feedback_text = ""
        game.invalidate_map_presentation_cache = Mock()
        screen = Economy_Screen()
        screen.start_economy(game)
        return screen, game

    def test_drag_updates_saved_setting_damage_caption_and_map_cache_immediately(self):
        screen, game = self.screen()
        slider = next(element for element in screen.elements if isinstance(element, Slider))
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slider.handle_rect.center))
        with patch("pygame.mouse.get_pressed", return_value=(True, False, False)):
            slider.handle_event(pygame.event.Event(
                pygame.MOUSEMOTION, pos=(slider.rect.x + slider.rect.width // 4, slider.rect.y)))
        self.assertEqual(game.world.nation_data["A"]["conscription_slider"], 0.25)
        self.assertEqual(screen.conscription_damage_caption, damage_caption(0.25))
        game.invalidate_map_presentation_cache.assert_called_once_with()
        expected = queries.get_economy_projections("A", game.world.map_data, game.world.nation_data)
        self.assertEqual(screen.econ_cache, expected)

    def test_fractional_bonus_is_shown_and_full_conscription_still_shows_zero(self):
        screen, _game = self.screen()
        self.assertEqual(screen.conscription_damage_caption, "dmg modifier: +0.00%")
        screen.set_conscription(0.375)
        self.assertEqual(screen.conscription_damage_caption, damage_caption(0.375))

    def test_draw_reuses_previews_without_running_rules(self):
        screen, _game = self.screen()
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        with patch.object(queries, "get_conscription_damage_bonus", side_effect=AssertionError("frame damage query")), \
                patch.object(queries, "get_economy_projections", side_effect=AssertionError("frame economy query")):
            screen.draw(surface)
            screen.draw(surface)

    def test_tactical_players_cannot_change_national_conscription(self):
        screen, game = self.screen(tactical=True)
        before = dict(game.world.nation_data["A"])
        screen.set_conscription(0.0)
        self.assertEqual(game.world.nation_data["A"], before)

    def test_submitted_realtime_players_cannot_start_a_drag_or_change_setting(self):
        screen, game = self.screen()
        game.session.mode = REALTIME
        game.realtime_player_id = "player"
        game.realtime_session = SimpleNamespace(
            phase="TURN", players={"player": SimpleNamespace(submitted=True, eliminated=False)})
        slider = next(element for element in screen.elements if isinstance(element, Slider))
        before = dict(game.world.nation_data["A"])
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=slider.handle_rect.center))
        screen.set_conscription(0.0)
        self.assertFalse(slider.dragging)
        self.assertEqual(game.world.nation_data["A"], before)
        game.invalidate_map_presentation_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
