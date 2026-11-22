"""Four-axis compass rules, policies, and input.

The rule, as specified:

    Two Civilian axes (Political, Economic) and two Military axes (Quality,
    Strategy) each take one step per processed turn while a direction is set.
    Every effect is a row of c.POLITICS_AXIS_EFFECTS, interpolated linearly
    between the axis ends. Quality sets army damage; Political sets research.

Two things in there are easy to get quietly wrong and are pinned hardest here.
The first is *whose* multiplier applies: a volley is measured off a LaneSide's
front rank, which is a whole coalition's units, so applying one country's
multiplier to the total would leak a nation's politics into its allies' guns.
The second is what happens at the end of the axis -- the direction has to clear
itself, because the map button's arrow badge reads "am I still drifting" and a
country pressed against the wall forever would wear it forever.

The AI half is a target position rather than a direction, which is what stops
every country at war from ending up at +10 together.
"""

import unittest
from unittest.mock import Mock, patch


import data.constants as c
from map_logic.ai import ai_tuning
import pygame
from data import queries
from data.queries import relations
from map_logic import politics
from map_logic.system32 import combat_processor, combat_rules

from tests.stub_map_screen import map_double
from tests.combat_fixtures import damage_taken, StubBattleMap, unit


class StubTurnScreen:
    """Just the two attributes politics.tick reaches for."""

    def __init__(self, nation_data):
        self.nation_data = nation_data


class PoliticsScreenEditGuardTests(unittest.TestCase):
    """Tactical mode may read the axis but cannot steer it."""

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((1, 1))

    def screen(self, tactical_mode):
        from screens.game.politics_screen import Politics_Screen

        map_screen = map_double(invalidate_map_presentation_cache=Mock())
        map_screen.player_country = "A"
        map_screen.tactical_mode = tactical_mode
        map_screen.nation_data = {
            "A": {"political_value": 0, "political_drift": 0},
        }
        return Politics_Screen(map_screen)

    def test_tactical_mode_disables_all_direction_controls(self):
        screen = self.screen(True)

        self.assertTrue(screen.is_valid_player)
        self.assertFalse(screen.can_edit)
        self.assertTrue(all(button.disabled for button in screen.elements[1:7]))

    def test_tactical_mode_guard_does_not_change_the_direction(self):
        screen = self.screen(True)
        before = screen.drift

        screen.set_drift(1)
        screen.set_drift(1, economic=True)

        self.assertEqual(screen.drift, before)
        self.assertEqual(politics.economic_drift(screen.map_screen.nation_data, "A"), 0)

    def test_strategic_mode_keeps_direction_controls_editable(self):
        screen = self.screen(False)

        self.assertTrue(screen.can_edit)
        self.assertTrue(all(not button.disabled for button in screen.elements[1:7]))

    def test_direction_buttons_queue_independent_steps_and_preview_the_turn(self):
        screen = self.screen(False)
        screen.elements[3].callback()
        screen.elements[4].callback()
        nation_data = screen.map_screen.nation_data

        self.assertEqual((politics.economic_value(nation_data, "A"), screen.value), (0, 0))
        self.assertEqual((politics.economic_drift(nation_data, "A"), screen.drift), (-1, 1))
        self.assertEqual(screen._preview, (-c.POLITICS_STEP, c.POLITICS_STEP))
        political_effects, economic_effects = screen._axis_effect_rows
        self.assertEqual([projected for _label, _current, projected in political_effects],
                         [politics.effect_at("research", c.POLITICS_STEP),
                          politics.effect_at("coring_cost", c.POLITICS_STEP)])
        self.assertEqual([projected for _label, _current, projected in economic_effects],
                         [politics.effect_at("factory_output", -c.POLITICS_STEP),
                          politics.effect_at("deposit_output", -c.POLITICS_STEP)])
        politics.tick(screen.map_screen)
        self.assertEqual((politics.economic_value(nation_data, "A"), screen.value), screen._preview)
        self.assertEqual(screen.map_screen.invalidate_map_presentation_cache.call_count, 2)

        screen.elements[5].callback()
        _label, current_research, projected_research = screen._axis_effect_rows[0][0]
        self.assertEqual(current_research, politics.effect_at("research", screen.value))
        self.assertLess(projected_research, current_research)
        self.assertTrue(all(current == projected for _label, current, projected in screen._axis_effect_rows[1]))

    def test_policy_eligibility_preview_keeps_current_activation_requirements(self):
        policy = {"id": "preview_fixture", "name": "Preview Fixture", "effect_lines": (), "min_politics": 0}
        with patch.object(politics, "POLICIES", (policy,)), patch.dict(politics.POLICIES_BY_ID, {policy["id"]: policy}):
            screen = self.screen(False)
            screen.elements[3].callback()  # Centralise from the strict boundary.
            self.assertIsNotNone(screen._policy_rows[0][4])
            self.assertTrue(screen.elements[-1].disabled)

            politics.tick(screen.map_screen)
            screen.refresh_ui()
            self.assertIsNone(screen._policy_rows[0][4])
            self.assertFalse(screen.elements[-1].disabled)

            screen.elements[1].callback()  # Liberalise back across the boundary.
            self.assertIsNotNone(screen._policy_rows[0][4])
            self.assertFalse(screen.elements[-1].disabled)

            politics.tick(screen.map_screen)
            screen.refresh_ui()
            self.assertTrue(screen.elements[-1].disabled)

    def test_politics_and_blank_policies_panels_split_the_available_height(self):
        screen = self.screen(False)

        self.assertEqual(screen.politics_rect.height, screen.policies_rect.height)
        self.assertLess(screen.politics_rect.bottom, screen.policies_rect.y)
        self.assertEqual(screen.policies_rect.bottom, c.SCREEN_HEIGHT - 20)

    def test_foreign_politics_view_is_read_only(self):
        from screens.game.politics_screen import Politics_Screen

        map_screen = map_double()
        map_screen.player_country = "A"
        map_screen.tactical_mode = False
        map_screen.nation_data = {
            "A": {"political_value": 0, "political_drift": 0},
            "B": {"political_value": 4, "political_drift": -1, "economic_drift": 1},
        }
        screen = Politics_Screen(map_screen, country_id="B")

        self.assertTrue(screen.is_read_only)
        self.assertFalse(screen.can_edit)
        self.assertEqual(len(screen.elements), 1, "foreign view has no policy or drift controls")
        self.assertEqual(screen._preview, (c.POLITICS_START, 4))
        self.assertTrue(all(forecast is None for _definition, _state, _eligible, _requirement, forecast in screen._policy_rows))
        screen.set_drift(1)
        screen.set_drift(-1, economic=True)
        self.assertEqual(politics.drift(map_screen.nation_data, "B"), -1)
        self.assertEqual(politics.economic_drift(map_screen.nation_data, "B"), 1)

    def test_policy_scrollbar_moves_cards_opposite_to_handle(self):
        screen = self.screen(False)
        self.assertLess(screen.policy_scroll_min_x, 0)
        screen.policy_scroll_track_rect = pygame.Rect(100, 100, 500, 14)

        screen._snap_policy_scroll(screen.policy_scroll_track_rect.left)
        self.assertEqual(screen.policy_scroll_x, 0,
                         "dragging the scrollbar left moves the policy cards right")

        screen._snap_policy_scroll(screen.policy_scroll_track_rect.right)
        self.assertEqual(screen.policy_scroll_x, screen.policy_scroll_min_x,
                         "dragging the scrollbar right moves the policy cards left")

        # Directly dragging the cards retains the conventional, grab-and-pan
        # direction. Only the dedicated scrollbar is reversed.
        screen.policy_scroll_x = -100
        viewport = screen._policy_viewport_rect()
        start = viewport.center
        screen.additional_events(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=start, button=1))
        screen.additional_events(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(start[0] - 20, start[1]), rel=(-20, 0)))
        self.assertEqual(screen.policy_scroll_x, -120)

    def test_starting_economic_slider_saves_both_coordinates_and_clears_drift(self):
        from screens.editors.politics_editor import Politics_Edit_Screen

        map_screen = map_double(is_editor=True, map_data={1: {"owner": "A"}},
                                nation_data={"A": {"political_value": 4, "political_drift": -1,
                                                   "economic_drift": 1}},
                                refresh_map_layers=Mock(), show_feedback=Mock())
        screen = Politics_Edit_Screen(map_screen, "A")
        slider = screen.rows[1][0]
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=slider.handle_rect.center, button=1))
        slider.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=slider.rect.midleft, mobile_touch=True))
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=slider.rect.midleft, button=1))
        self.assertEqual(politics.economic_value(map_screen.nation_data, "A"), c.POLITICS_START)
        screen.elements[2].callback()

        self.assertTrue(screen.done)
        self.assertEqual(politics.value(map_screen.nation_data, "A"), 4)
        self.assertEqual(politics.economic_value(map_screen.nation_data, "A"), c.POLITICS_MIN)
        self.assertEqual(politics.drift(map_screen.nation_data, "A"), 0)
        self.assertEqual(politics.economic_drift(map_screen.nation_data, "A"), 0)
        map_screen.refresh_map_layers.assert_called_once_with("relations")

        screen = Politics_Edit_Screen(map_screen, "A")
        screen.elements[1].callback()
        self.assertEqual((screen.value, screen.economic_value), (c.POLITICS_START, c.POLITICS_START))
        map_screen.is_editor = False
        map_screen.player_country = "Spectator"
        map_screen.realtime_multiplayer = True
        screen.save()
        self.assertEqual(politics.economic_value(map_screen.nation_data, "A"), c.POLITICS_MIN)


class PoliticalAffinityTests(unittest.TestCase):
    def test_affinity_scores_agreement_and_opposition_on_both_axes(self):
        # Full agreement on one axis is worth the per-axis weight; full opposition costs it.
        edge, per_axis = c.POLITICS_MAX, relations._POLITICAL_AFFINITY_PER_AXIS
        half = edge // 2

        def score(a, b):
            data = {name: {politics.VALUE_KEY: political, politics.ECONOMIC_VALUE_KEY: economic}
                    for name, (political, economic) in (("A", a), ("B", b))}
            self.assertEqual(queries.get_relation_score("A", "A", data), 0)
            forward = queries.get_relation_score("A", "B", data)
            self.assertEqual(queries.get_relation_score("B", "A", data), forward)
            return forward

        for a, b, expected in (
            ((edge, edge), (edge, edge), 2 * per_axis),
            ((-edge, -edge), (-edge, -edge), 2 * per_axis),
            ((edge, edge), (edge, -edge), 0),
            ((edge, edge), (-edge, -edge), -2 * per_axis),
            ((edge, -edge), (0, -edge), per_axis),
        ):
            with self.subTest(a=a, b=b):
                self.assertEqual(score(a, b), expected)
        # Milder shared leanings add less goodwill than full agreement, but still some.
        for a, b in (((half, half), (half, half)), ((edge - 2, -half), (half + 1, -half))):
            with self.subTest(a=a, b=b):
                self.assertGreater(score(a, b), 0)
                self.assertLess(score(a, b), 2 * per_axis)


class EconomicDriftTests(unittest.TestCase):
    def test_reaching_the_economic_edge_stops_only_horizontal_movement(self):
        screen = screen_with(A=(0, -1))
        politics.set_economic_value(screen.nation_data, "A", c.POLITICS_MAX - c.POLITICS_STEP)
        politics.set_economic_drift(screen.nation_data, "A", 1)
        politics.tick(screen)

        self.assertEqual(politics.economic_value(screen.nation_data, "A"), c.POLITICS_MAX)
        self.assertEqual(politics.economic_drift(screen.nation_data, "A"), 0)
        self.assertEqual(politics.value(screen.nation_data, "A"), -c.POLITICS_STEP)
        self.assertEqual(politics.drift(screen.nation_data, "A"), -1)


def screen_with(**by_nation):
    """A nation_data holder where each nation is (value, drift)."""
    nation_data = {}
    for name, (value, drift) in by_nation.items():
        nation_data[name] = {"political_value": value, "political_drift": drift}
    return StubTurnScreen(nation_data)


def axis_damage_multiplier(value):
    """Expected Quality-only damage multiplier from the canonical tuning values."""
    low, high = c.POLITICS_AXIS_EFFECTS[politics.QUALITY]["damage"]
    return low + (high - low) * (value - c.POLITICS_MIN) / float(c.POLITICS_MAX - c.POLITICS_MIN)


def policy_effect(policy_id, effect):
    """Read a policy effect from the production definition, never a test literal."""
    return politics.policy(policy_id).get("effects", {}).get(effect, 1.0)


# ============================================================================ #
#                              THE MULTIPLIERS                                 #
# ============================================================================ #

class MultiplierTests(unittest.TestCase):
    def test_every_effect_runs_linearly_between_its_ends(self):
        """Each end is the table's value, and every step moves the same distance."""
        for axis, effects in c.POLITICS_AXIS_EFFECTS.items():
            for effect, (low, high) in effects.items():
                with self.subTest(effect=effect):
                    self.assertEqual(politics.EFFECT_AXES[effect], axis)
                    self.assertAlmostEqual(politics.effect_at(effect, c.POLITICS_MIN), low)
                    self.assertAlmostEqual(politics.effect_at(effect, c.POLITICS_MAX), high)
                    step = (high - low) / (c.POLITICS_MAX - c.POLITICS_MIN)
                    for value in range(c.POLITICS_MIN, c.POLITICS_MAX):
                        self.assertAlmostEqual(politics.effect_at(effect, value + 1)
                                               - politics.effect_at(effect, value), step)

    def test_effect_names_are_unique_across_axes(self):
        names = [effect for effects in c.POLITICS_AXIS_EFFECTS.values() for effect in effects]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(c.POLITICS_AXIS_EFFECTS), set(politics.AXES_BY_ID))

    def test_quality_sets_damage_and_political_sets_research(self):
        for value in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            with self.subTest(value=value):
                quality = {"A": {politics.QUALITY_VALUE_KEY: value, politics.VALUE_KEY: c.POLITICS_MAX,
                                 politics.ECONOMIC_VALUE_KEY: c.POLITICS_MAX}}
                political = {"A": {politics.VALUE_KEY: value, politics.ECONOMIC_VALUE_KEY: c.POLITICS_MAX,
                                   politics.QUALITY_VALUE_KEY: c.POLITICS_MAX}}
                self.assertAlmostEqual(politics.damage_multiplier(quality, "A"), politics.effect_at("damage", value))
                self.assertAlmostEqual(politics.research_multiplier(political, "A"), politics.effect_at("research", value))
        self.assertEqual(politics.effect_at("research", c.POLITICS_MAX), 0.0)

    def test_a_nation_nobody_has_touched_is_centrist(self):
        """An old save has none of these keys, and must play exactly as before."""
        nation_data = {"A": {}}
        self.assertEqual(politics.value(nation_data, "A"), c.POLITICS_START)
        self.assertEqual(politics.drift(nation_data, "A"), 0)
        self.assertEqual(politics.damage_multiplier(nation_data, "A"), 1.0)
        self.assertEqual(politics.research_multiplier(nation_data, "A"), 1.0)

    def test_a_nation_that_is_not_in_the_table_at_all_is_centrist(self):
        """Rebellions and splinter states are read before they are written."""
        self.assertEqual(politics.value({}, "Nobody"), c.POLITICS_START)
        self.assertEqual(politics.damage_multiplier({}, "Nobody"), 1.0)

    def test_a_corrupt_value_reads_as_centrist_rather_than_crashing(self):
        nation_data = {"A": {"political_value": "left", "political_drift": None}}
        self.assertEqual(politics.value(nation_data, "A"), c.POLITICS_START)
        self.assertEqual(politics.drift(nation_data, "A"), 0)


class BandTests(unittest.TestCase):
    """The word and the color are one statement, so they come from one table."""

    def test_every_band_names_a_real_palette(self):
        for _bound, label, palette in politics.BANDS:
            self.assertIn(palette, c.UI_COLORS, f"{label} is painted in a color that does not exist")

    def test_the_bands_cover_the_axis_in_order(self):
        bounds = [bound for bound, _label, _palette in politics.BANDS]
        self.assertEqual(bounds[-1], c.POLITICS_MAX)
        self.assertEqual(bounds, sorted(bounds))
        self.assertEqual(politics.palette(c.POLITICS_START),
                         politics.band(c.POLITICS_START)[2])

    def test_the_label_and_the_palette_never_disagree(self):
        expected = {label: palette for _bound, label, palette in politics.BANDS}
        for value in range(c.POLITICS_MIN, c.POLITICS_MAX + 1):
            self.assertEqual(politics.palette(value), expected[politics.label(value)])

    def test_economic_labels_follow_the_same_five_bands(self):
        economic_labels = {bound: politics.economic_label(bound) for bound, _label, _palette in politics.BANDS}
        self.assertEqual(len(set(economic_labels.values())), 5)
        for value in range(c.POLITICS_MIN, c.POLITICS_MAX + 1):
            with self.subTest(value=value):
                label = politics.economic_label(value)
                self.assertEqual(label, economic_labels[politics.band(value)[0]])
                self.assertEqual(label == "Mixed", -2 <= value <= 2)

    def test_a_value_off_the_axis_is_still_painted(self):
        self.assertEqual(politics.palette(c.POLITICS_MAX + c.POLITICS_STEP),
                         politics.BANDS[-1][2])
        self.assertEqual(politics.palette(c.POLITICS_MIN - c.POLITICS_STEP),
                         politics.BANDS[0][2])


# ============================================================================ #
#                                THE DRIFT                                     #
# ============================================================================ #

class DriftTests(unittest.TestCase):
    def test_one_step_per_processed_turn(self):
        screen = screen_with(A=(c.POLITICS_START, 1))
        politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"),
                         c.POLITICS_START + c.POLITICS_STEP)
        politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"),
                         c.POLITICS_START + 2 * c.POLITICS_STEP)

    def test_configured_turns_from_the_centre_reaches_an_end(self):
        screen = screen_with(A=(c.POLITICS_START, 1))
        turns = (c.POLITICS_MAX - c.POLITICS_START) // c.POLITICS_STEP
        for _ in range(turns):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)

    def test_configured_turns_crosses_the_whole_axis(self):
        screen = screen_with(A=(c.POLITICS_MIN, 1))
        turns = (c.POLITICS_MAX - c.POLITICS_MIN) // c.POLITICS_STEP
        for _ in range(turns):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)

    def test_holding_still_moves_nothing(self):
        screen = screen_with(A=(3, 0))
        for _ in range(5):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), 3)

    def test_reaching_the_end_clears_the_direction(self):
        """Which is what puts the map button's arrow badge out by itself."""
        screen = screen_with(A=(c.POLITICS_MAX - 1, 1))
        politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)
        self.assertEqual(politics.drift(screen.nation_data, "A"), 0)

    def test_the_value_never_leaves_the_axis(self):
        screen = screen_with(A=(c.POLITICS_MAX, 1), B=(c.POLITICS_MIN, -1))
        for _ in range(5):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)
        self.assertEqual(politics.value(screen.nation_data, "B"), c.POLITICS_MIN)

    def test_the_pseudo_nations_are_left_alone(self):
        """GLOBAL_EVENTS is a log, not a country."""
        screen = StubTurnScreen({"GLOBAL_EVENTS": {"political_drift": 1}})
        politics.tick(screen)
        self.assertNotIn("political_value", screen.nation_data["GLOBAL_EVENTS"])

    def test_each_nation_drifts_on_its_own(self):
        screen = screen_with(A=(0, 1), B=(0, -1), C=(0, 0))
        for _ in range(3):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), 3)
        self.assertEqual(politics.value(screen.nation_data, "B"), -3)
        self.assertEqual(politics.value(screen.nation_data, "C"), 0)


# ============================================================================ #
#                                POLICIES                                     #
# ============================================================================ #

class PolicyTests(unittest.TestCase):
    def screen_at(self, political_value=0, economic_value=0):
        return StubTurnScreen({"A": {"political_value": political_value, "economic_value": economic_value}})

    def activate_and_finish(self, screen, policy_id):
        self.assertTrue(politics.activate_or_cancel_policy(screen.nation_data, "A", policy_id))
        for _ in range(politics.POLICY_ACTIVATION_TURNS):
            politics.tick(screen)

    def test_policy_requirements_are_strict(self):
        for policy_id, bound, eligible in (("research_subsidies", -2, -3),
                                            ("prioritize_civilian_needs", 3, 2),
                                            ("recruitment_propaganda", -3, -2),
                                            ("total_mobilisation", 2, 3)):
            for economic in (c.POLITICS_MIN, c.POLITICS_MAX):
                with self.subTest(policy=policy_id, economic=economic):
                    screen = self.screen_at(political_value=bound, economic_value=economic)
                    self.assertFalse(politics.requirements_met(screen.nation_data, "A", policy_id))
                    politics.set_value(screen.nation_data, "A", eligible)
                    self.assertTrue(politics.requirements_met(screen.nation_data, "A", policy_id))

    def test_losing_a_requirement_cancels_before_the_turn_uses_the_effect(self):
        policy_id = "research_subsidies"
        screen = self.screen_at(political_value=-3, economic_value=c.POLITICS_MAX)
        self.activate_and_finish(screen, policy_id)
        politics.set_drift(screen.nation_data, "A", 1)

        politics.tick(screen)

        self.assertIsNone(politics.policy_state(screen.nation_data, "A"))
        self.assertAlmostEqual(politics.research_multiplier(screen.nation_data, "A"),
                               politics.effect_at("research", politics.value(screen.nation_data, "A")))

    def test_cancel_can_be_undone_before_the_next_processed_turn(self):
        screen = self.screen_at(0)
        self.activate_and_finish(screen, "prioritize_industrial_needs")
        self.assertTrue(politics.activate_or_cancel_policy(
            screen.nation_data, "A", "prioritize_industrial_needs"))
        self.assertEqual(politics.policy_state(screen.nation_data, "A")["status"],
                         politics.POLICY_CANCELLING)

        self.assertTrue(politics.activate_or_cancel_policy(
            screen.nation_data, "A", "prioritize_industrial_needs"))
        self.assertEqual(politics.policy_state(screen.nation_data, "A")["status"],
                         politics.POLICY_ACTIVE)
        self.assertAlmostEqual(politics.resource_multiplier(screen.nation_data, "A", "materials"),
                               policy_effect("prioritize_industrial_needs", "materials"))

    def test_cancellation_finishes_on_the_next_processed_turn(self):
        screen = self.screen_at(0)
        self.activate_and_finish(screen, "prioritize_industrial_needs")
        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        politics.tick(screen)

        self.assertIsNone(politics.policy_state(screen.nation_data, "A"))

    def test_unprocessed_activation_cancels_immediately(self):
        screen = self.screen_at(0)
        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        self.assertIsNone(politics.policy_state(
            screen.nation_data, "A", "prioritize_industrial_needs"))
        self.assertNotIn(politics.POLICY_KEY, screen.nation_data["A"])

    def test_each_eligible_policy_has_its_own_activation_and_effect(self):
        screen = self.screen_at()
        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_civilian_needs")
        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        for _ in range(politics.POLICY_ACTIVATION_TURNS):
            politics.tick(screen)

        self.assertEqual(politics.policy_state(screen.nation_data, "A", "prioritize_civilian_needs")["status"],
                         politics.POLICY_ACTIVE)
        self.assertEqual(politics.policy_state(screen.nation_data, "A", "prioritize_industrial_needs")["status"],
                         politics.POLICY_ACTIVE)
        self.assertAlmostEqual(politics.research_multiplier(screen.nation_data, "A"),
                               politics.effect_at("research", politics.value(screen.nation_data, "A"))
                               * policy_effect("prioritize_civilian_needs", "research")
                               * policy_effect("prioritize_industrial_needs", "research"))
        self.assertAlmostEqual(politics.resource_multiplier(screen.nation_data, "A", "manpower"),
                               policy_effect("prioritize_civilian_needs", "manpower")
                               * policy_effect("prioritize_industrial_needs", "manpower"))

    def test_resource_policy_changes_the_shared_economy_calculation(self):
        from data import queries

        policy_id = "research_subsidies"
        screen = self.screen_at(political_value=-3)
        screen.nation_data["A"]["research"] = {}
        map_data = {"p": {"owner": "A", "cores": ["A"], "resources": {},
                          "buildings": [], "units": []}}
        before = queries.calculate_all_economies(map_data, screen.nation_data)["A"]["total_inc"]

        self.activate_and_finish(screen, policy_id)
        after = queries.calculate_all_economies(map_data, screen.nation_data)["A"]["total_inc"]

        for resource in ("manpower", "materials", "fuel"):
            self.assertAlmostEqual(after[resource], before[resource]
                                   * policy_effect(policy_id, resource))

    def test_total_mobilisation_stacks_its_damage_bonus_on_the_axis_bonus(self):
        policy_id = "total_mobilisation"
        screen = self.screen_at(political_value=politics.policy(policy_id)["min_politics"] + 1)
        self.activate_and_finish(screen, policy_id)
        quality = politics.axis_value(screen.nation_data, "A", politics.QUALITY)
        self.assertAlmostEqual(politics.damage_multiplier(screen.nation_data, "A"),
                               axis_damage_multiplier(quality) * policy_effect(policy_id, "damage"))
        self.assertAlmostEqual(politics.research_multiplier(screen.nation_data, "A"),
                               politics.effect_at("research", politics.value(screen.nation_data, "A"))
                               * policy_effect(policy_id, "research"))


# ============================================================================ #
#                                THE DAMAGE                                    #
# ============================================================================ #

def two_nation_tile(a_value=c.POLITICS_START, b_value=c.POLITICS_START):
    """A and B at war on one tile, each with one unit. Returns (screen, prov)."""
    screen = StubBattleMap()
    screen.add_nation("A", at_war_with=["B"])
    screen.add_nation("B", at_war_with=["A"])
    politics.set_axis_value(screen.nation_data, "A", politics.QUALITY, a_value)
    politics.set_axis_value(screen.nation_data, "B", politics.QUALITY, b_value)
    prov = screen.add_province("p1", "A", units=[unit("A"), unit("B")])
    return screen, prov


class CombatDamageTests(unittest.TestCase):
    def damage_dealt_by_a(self, a_value):
        screen, prov = two_nation_tile(a_value=a_value)
        b_units = [u for u in prov["units"] if u["owner"] == "B"]
        combat_processor.process_combat(screen)
        return damage_taken(b_units)

    def test_a_centrist_nation_fights_exactly_as_it_always_did(self):
        self.assertAlmostEqual(self.damage_dealt_by_a(c.POLITICS_START),
                               unit("A")["attack"])

    def test_numerous_armies_hit_softer(self):
        base = self.damage_dealt_by_a(c.POLITICS_START)
        self.assertAlmostEqual(self.damage_dealt_by_a(c.POLITICS_MAX),
                               base * axis_damage_multiplier(c.POLITICS_MAX))

    def test_professional_armies_hit_harder(self):
        base = self.damage_dealt_by_a(c.POLITICS_START)
        self.assertAlmostEqual(self.damage_dealt_by_a(c.POLITICS_MIN),
                               base * axis_damage_multiplier(c.POLITICS_MIN))

    def test_it_applies_to_damage_dealt_while_defending_too(self):
        """A lane fight is simultaneous -- there is no attacker to single out."""
        screen, prov = two_nation_tile(b_value=c.POLITICS_MAX)
        a_units = [u for u in prov["units"] if u["owner"] == "A"]
        combat_processor.process_combat(screen)
        self.assertAlmostEqual(damage_taken(a_units),
                               self.damage_dealt_by_a(c.POLITICS_START)
                               * axis_damage_multiplier(c.POLITICS_MAX))

    def test_a_nations_politics_does_not_leak_into_its_allies_guns(self):
        """The multiplier is per unit, not per volley.

        A and B fight C side by side, sharing one LaneSide. If the multiplier
        were applied to the side's pooled attack, whichever of the two the code
        happened to read first would arm the other.
        """
        screen = StubBattleMap()
        screen.add_nation("A", at_war_with=["C"])
        screen.add_nation("B", at_war_with=["C"])
        screen.add_nation("C", at_war_with=["A", "B"])
        screen.nation_data["A"]["faction"] = screen.nation_data["B"]["faction"] = "Fixture Coalition"
        politics.set_axis_value(screen.nation_data, "A", politics.QUALITY, c.POLITICS_MAX)

        prov = screen.add_province("p1", "C", units=[unit("A"), unit("B"), unit("C")])
        c_units = [u for u in prov["units"] if u["owner"] == "C"]
        combat_processor.process_combat(screen)

        # A's politics applies only to A's volley, not its centrist ally B's.
        base = self.damage_dealt_by_a(c.POLITICS_START)
        self.assertAlmostEqual(
            damage_taken(c_units),
            base * (axis_damage_multiplier(c.POLITICS_MAX)
                    + axis_damage_multiplier(c.POLITICS_START)))

    def test_volley_without_nation_data_is_unmodified(self):
        """The callers that compare raw unit stats must see raw unit stats."""
        nation_data = {"A": {politics.QUALITY_VALUE_KEY: c.POLITICS_MAX}}
        units = [unit("A")]
        base = units[0]["attack"]
        self.assertAlmostEqual(combat_rules.volley(units), base)
        self.assertAlmostEqual(combat_rules.volley(units, None, nation_data),
                               base * axis_damage_multiplier(c.POLITICS_MAX))


class DisplayedDamageTests(unittest.TestCase):
    """What the panels print is what the fight delivers.

    The battle screen and the province sidebar both scale a unit's printed
    attack by how wounded it is. They have to scale it by the owner's politics
    too, or an authoritarian nation's roster advertises a number the resolver
    will not produce -- which is the same class of bug as the research screen
    quoting an unmodified pts/turn. One helper, read by both the screens and
    the resolver, is what keeps them from drifting.
    """

    def test_it_stacks_on_top_of_the_health_penalty(self):
        wounded = unit("A", attack=100, health=50000)
        wounded["max_health"] = 100000
        nation_data = {"A": {politics.QUALITY_VALUE_KEY: c.POLITICS_MAX}}

        health_multiplier = wounded["health"] / wounded["max_health"]
        self.assertAlmostEqual(combat_rules.health_damage_multiplier(wounded), health_multiplier)
        self.assertAlmostEqual(
            combat_rules.effective_damage_multiplier(wounded, nation_data),
            health_multiplier * axis_damage_multiplier(c.POLITICS_MAX))

    def test_it_runs_the_full_span(self):
        healthy = unit("A", attack=100)
        for value in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            nation_data = {"A": {politics.QUALITY_VALUE_KEY: value}}
            self.assertAlmostEqual(
                combat_rules.effective_damage_multiplier(healthy, nation_data),
                axis_damage_multiplier(value))

    def test_without_nation_data_it_is_the_bare_health_penalty(self):
        """The panels that price a unit type, not this country's copy of one."""
        wounded = unit("A", attack=100, health=50000)
        wounded["max_health"] = 100000
        self.assertAlmostEqual(combat_rules.effective_damage_multiplier(wounded),
                               wounded["health"] / wounded["max_health"])

    def test_the_printed_figure_matches_what_the_turn_deals(self):
        """The contract, end to end: one unit, one enemy, one exchange."""
        for value in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            screen, prov = two_nation_tile(a_value=value)
            attacker = next(u for u in prov["units"] if u["owner"] == "A")
            defenders = [u for u in prov["units"] if u["owner"] == "B"]

            printed = (attacker["attack"]
                       * combat_rules.effective_damage_multiplier(attacker, screen.nation_data))
            combat_processor.process_combat(screen)

            self.assertAlmostEqual(damage_taken(defenders), printed,
                                   msg=f"panel and resolver disagree at {value:+d}")

    def test_the_map_combat_bubble_reads_the_same_number(self):
        from ui.rendering import overlay_renderer

        for value in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            screen, _prov = two_nation_tile(a_value=value)
            friendly, enemy, involved = overlay_renderer.combat_strengths(
                [[unit("A"), unit("B")]], screen.nation_data, {"A"})
            self.assertTrue(involved)
            self.assertAlmostEqual(friendly, unit("A")["attack"] * axis_damage_multiplier(value))
            self.assertAlmostEqual(enemy, unit("B")["attack"],
                                   msg="the enemy's own politics is unaffected")


class BombardmentDamageTests(unittest.TestCase):
    def bombardment_damage(self, a_value):
        screen = StubBattleMap()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        politics.set_axis_value(screen.nation_data, "A", politics.QUALITY, a_value)

        gun = unit("A", kind="Artillery")
        gun["bombard_attack"] = 100
        gun["order"] = {"type": "BOMBARD", "target_id": "p2"}

        origin = screen.add_province("p1", "A", units=[gun])
        target = screen.add_province("p2", "B", units=[unit("B")])
        origin["neighbors"] = ["p2"]
        target["neighbors"] = ["p1"]

        defenders = list(target["units"])
        combat_processor.process_bombardments(screen)
        return damage_taken(defenders)

    def test_bombardment_scales_with_the_firing_nations_politics(self):
        centrist = self.bombardment_damage(c.POLITICS_START)
        if centrist <= 0:
            self.skipTest("this stub's artillery cannot reach -- see get_bombardment_range")
        self.assertAlmostEqual(self.bombardment_damage(c.POLITICS_MAX),
                               centrist * axis_damage_multiplier(c.POLITICS_MAX))
        self.assertAlmostEqual(self.bombardment_damage(c.POLITICS_MIN),
                               centrist * axis_damage_multiplier(c.POLITICS_MIN))


# ============================================================================ #
#                                THE RESEARCH                                  #
# ============================================================================ #

class ResearchTests(unittest.TestCase):
    """The resolver reads the multiplier off the nation whose queue it is on."""

    def points_after_one_turn(self, political_value, economic_value=c.POLITICS_MAX):
        from map_logic.system32 import research_processor

        class Screen:
            pass

        screen = Screen()
        screen.scenario_settings = {}
        screen.player_country = "A"
        screen.nation_data = {
            "A": {"research": {"infantry_type": 0},
                  "research_queue": [{"tech_name": "infantry_type",
                                      "points_remaining": 100000}],
                  "political_value": political_value, "economic_value": economic_value},
        }

        class Time:
            year, month_index, day, total_turns = 1910, 0, 1, 1

        screen.time_manager = Time()
        screen.show_feedback = lambda *_a, **_k: None

        before = screen.nation_data["A"]["research_queue"][0]["points_remaining"]
        research_processor.process_national_research(screen)
        after = screen.nation_data["A"]["research_queue"][0]["points_remaining"]
        return before - after

    def test_centrist_research_is_independent_of_the_economy(self):
        base = self.points_after_one_turn(c.POLITICS_START, c.POLITICS_MIN)
        self.assertGreater(base, 0)
        self.assertEqual(self.points_after_one_turn(c.POLITICS_START, c.POLITICS_MAX), base)

    def test_fully_libertarian_research_reaches_the_table_maximum(self):
        base = self.points_after_one_turn(c.POLITICS_START)
        self.assertAlmostEqual(self.points_after_one_turn(c.POLITICS_MIN),
                               base * c.POLITICS_AXIS_EFFECTS[politics.POLITICAL]["research"][0])

    def test_fully_authoritarian_research_stops(self):
        self.assertEqual(self.points_after_one_turn(c.POLITICS_MAX), 0)


class FactionResearchTests(unittest.TestCase):
    """Research sharing counts faction partners per exact completed level."""

    def nation_data(self):
        return {
            "A": {"faction": "Pact", "research": {"infantry_type": 0}},
            "B": {"faction": "Pact", "research": {"infantry_type": 1}},
            "C": {"faction": "Pact", "research": {"infantry_type": 2}},
            "Outside": {"faction": "Other", "research": {"infantry_type": 9}},
        }

    def test_only_faction_partners_with_the_target_level_share_research(self):
        from data import queries

        nation_data = self.nation_data()
        self.assertAlmostEqual(
            queries.get_faction_research_bonus("A", "infantry_type", 1, nation_data),
            2 * c.FACTION_RESEARCH_BONUS_PER_MEMBER)
        self.assertAlmostEqual(
            queries.get_faction_research_bonus("A", "infantry_type", 2, nation_data),
            c.FACTION_RESEARCH_BONUS_PER_MEMBER)
        self.assertAlmostEqual(
            queries.get_faction_research_bonus("A", "infantry_type", 3, nation_data), 0.0)

    def test_sharing_bonus_caps_at_fifty_percent(self):
        from data import queries

        nation_data = self.nation_data()
        for index in range(6):
            nation_data[f"Partner {index}"] = {
                "faction": "Pact", "research": {"infantry_type": 1}}
        self.assertAlmostEqual(
            queries.get_faction_research_bonus("A", "infantry_type", 1, nation_data),
            c.FACTION_RESEARCH_BONUS_CAP)

    def test_resolver_applies_the_shared_research_multiplier(self):
        from map_logic.system32 import research_processor

        class Screen:
            pass

        def points_spent(with_partner):
            screen = Screen()
            screen.scenario_settings = {}
            screen.player_country = "A"
            screen.nation_data = {
                "A": {"faction": "Pact" if with_partner else "",
                      "research": {"infantry_type": 0},
                      "research_queue": [{"tech_name": "infantry_type",
                                          "points_remaining": 100000}],
                      "political_value": c.POLITICS_START},
            }
            if with_partner:
                screen.nation_data["B"] = {
                    "faction": "Pact", "research": {"infantry_type": 1}}

            class Time:
                year, month_index, day, total_turns = 1910, 0, 1, 1

            screen.time_manager = Time()
            screen.show_feedback = lambda *_a, **_k: None
            before = screen.nation_data["A"]["research_queue"][0]["points_remaining"]
            research_processor.process_national_research(screen)
            after = screen.nation_data["A"]["research_queue"][0]["points_remaining"]
            return before - after

        self.assertAlmostEqual(points_spent(True), points_spent(False)
                               * (1.0 + c.FACTION_RESEARCH_BONUS_PER_MEMBER))


# ============================================================================ #
#                                  THE AI                                      #
# ============================================================================ #

class StubWorld:
    """The three things ai_politics asks an AIWorld for."""

    def __init__(self, nation_data, ratios=None, neighbors=None):
        self.nation_data = nation_data
        self._ratios = ratios or {}
        self.neighbors = neighbors or {}

    def power_ratio(self, nation, other):
        return self._ratios.get((nation, other), (1.0, 1.0))


def ai_world_with(*nations, **kwargs):
    nation_data = {n: {"name": n, "at_war_with": []} for n in nations}
    return StubWorld(nation_data, **kwargs)


class AIPoliticsTests(unittest.TestCase):
    def setUp(self):
        from map_logic.ai import ai_politics
        self.ai_politics = ai_politics

    def test_a_nation_at_peace_and_safe_leans_libertarian(self):
        world = ai_world_with("A", "B")
        self.assertLess(self.ai_politics.desired_value(world, "A"), 0)

    def test_a_nation_at_war_leans_authoritarian(self):
        world = ai_world_with("A", "B")
        world.nation_data["A"]["at_war_with"] = ["B"]
        world.nation_data["B"]["at_war_with"] = ["A"]
        self.assertGreater(self.ai_politics.desired_value(world, "A"), 0)

    def test_losing_a_war_centralises_harder_than_winning_one(self):
        def target(border, glob):
            world = ai_world_with("A", "B", ratios={("A", "B"): (border, glob)})
            world.nation_data["A"]["at_war_with"] = ["B"]
            world.nation_data["B"]["at_war_with"] = ["A"]
            return self.ai_politics.desired_value(world, "A")

        self.assertGreater(target(0.2, 0.2), target(5.0, 5.0))

    def test_a_war_it_is_winning_does_not_go_to_the_wall(self):
        """The nuance the whole target-position design exists for."""
        world = ai_world_with("A", "B", ratios={("A", "B"): (5.0, 5.0)})
        world.nation_data["A"]["at_war_with"] = ["B"]
        world.nation_data["B"]["at_war_with"] = ["A"]
        self.assertLess(self.ai_politics.desired_value(world, "A"), c.POLITICS_MAX)

    def test_a_threatening_neighbour_holds_a_peaceful_nation_nearer_the_centre(self):
        safe = ai_world_with("A", "B", neighbors={"A": {"B"}},
                             ratios={("A", "B"): (1.0, 5.0)})
        scared = ai_world_with("A", "B", neighbors={"A": {"B"}},
                               ratios={("A", "B"): (1.0, 0.1)})
        self.assertGreater(self.ai_politics.desired_value(scared, "A"),
                           self.ai_politics.desired_value(safe, "A"))

    def test_a_peaceful_nation_does_not_go_to_the_wall_either(self):
        world = ai_world_with("A", "B", neighbors={"A": {"B"}},
                              ratios={("A", "B"): (1.0, 100.0)})
        self.assertGreater(self.ai_politics.desired_value(world, "A"), c.POLITICS_MIN)

    def test_an_ally_next_door_is_not_a_menace(self):
        allied = ai_world_with("A", "B", neighbors={"A": {"B"}},
                               ratios={("A", "B"): (1.0, 0.1)})
        allied.nation_data["A"]["faction"] = allied.nation_data["B"]["faction"] = "Fixture Coalition"
        alone = ai_world_with("A", neighbors={"A": set()})
        self.assertEqual(self.ai_politics.desired_value(allied, "A"),
                         self.ai_politics.desired_value(alone, "A"))

    def test_it_walks_toward_the_target_and_stops_on_arrival(self):
        world = ai_world_with("A", "B")
        target = self.ai_politics.desired_value(world, "A")

        politics.set_value(world.nation_data, "A", 0)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), -1)

        politics.set_value(world.nation_data, "A", target)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), 0)
        self.assertEqual(politics.drift(world.nation_data, "A"), 0)

        politics.set_value(world.nation_data, "A", c.POLITICS_MIN)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), 1)

    def test_a_war_turns_a_drifting_nation_around(self):
        """The target is recomputed every turn, so it reverses rather than snaps."""
        world = ai_world_with("A", "B")
        politics.set_value(world.nation_data, "A", -4)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), -1)

        world.nation_data["A"]["at_war_with"] = ["B"]
        world.nation_data["B"]["at_war_with"] = ["A"]
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), 1)
        self.assertEqual(politics.value(world.nation_data, "A"), -4,
                         "deciding must not move the value; only tick does that")

    def test_the_same_world_decides_the_same_way_twice(self):
        """No `random` -- see the note in ai_personality.procedural."""
        first = ai_world_with("A", "B")
        second = ai_world_with("A", "B")
        self.assertEqual(self.ai_politics.desired_value(first, "A"),
                         self.ai_politics.desired_value(second, "A"))

    def test_economic_drift_responds_to_a_shortage_independently(self):
        world = ai_world_with("A")
        world.provs_by_owner = {"A": [{"buildings": ["Basic Factory"]}]}
        world.economies = {"A": {"upkeep": {"materials": 100, "fuel": 20},
                                 "total_inc": {"materials": 80, "fuel": 10},
                                 "breakdown": {"materials": {"buildings": 60},
                                               "fuel": {"buildings": 0}}}}
        politics.set_drift(world.nation_data, "A", 1)
        self.assertEqual(self.ai_politics.decide_economy(world, "A", world.nation_data), -1)
        self.assertEqual(politics.economic_value(world.nation_data, "A"), c.POLITICS_START)
        self.assertEqual(politics.drift(world.nation_data, "A"), 1)

        # A factory cannot help the remaining fuel deficit in this economy.
        world.nation_data["A"]["materials"] = 20 * ai_tuning.AI_DISBAND_RUNWAY_TURNS
        self.assertEqual(self.ai_politics.decide_economy(world, "A", world.nation_data), 1)
        self.assertEqual(politics.economic_drift(world.nation_data, "A"), 1)


if __name__ == "__main__":
    unittest.main()
