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
itself, because the map button's badge reads "am I still drifting" and a
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

    @staticmethod
    def drift_buttons(screen):
        return [element for element in screen.elements if hasattr(element, "politics_axis")]

    def button(self, screen, axis, direction):
        return next(element for element in self.drift_buttons(screen)
                    if (element.politics_axis, element.politics_direction) == (axis, direction))

    @staticmethod
    def tab(screen, group):
        return next(element for element in screen.elements if getattr(element, "politics_group", None) == group)

    def test_tactical_mode_disables_all_direction_controls(self):
        screen = self.screen(True)

        self.assertTrue(screen.is_valid_player)
        self.assertFalse(screen.can_edit)
        self.assertEqual(len(self.drift_buttons(screen)), 6)
        self.assertTrue(all(button.disabled for button in self.drift_buttons(screen)))

    def test_tactical_mode_guard_does_not_change_the_direction(self):
        screen = self.screen(True)
        before = screen.drift

        for axis in politics.AXES:
            screen.set_drift(1, axis["id"])

        self.assertEqual(screen.drift, before)
        for axis in politics.AXES:
            self.assertEqual(politics.axis_drift(screen.map_screen.nation_data, "A", axis["id"]), 0)

    def test_strategic_mode_keeps_direction_controls_editable(self):
        screen = self.screen(False)

        self.assertTrue(screen.can_edit)
        self.assertTrue(all(not button.disabled for button in self.drift_buttons(screen)))

    def test_direction_buttons_queue_independent_steps_and_preview_the_turn(self):
        screen = self.screen(False)
        self.button(screen, politics.POLITICAL, 1).callback()
        self.button(screen, politics.ECONOMIC, -1).callback()
        nation_data = screen.map_screen.nation_data

        self.assertEqual((politics.economic_value(nation_data, "A"), screen.value), (0, 0))
        self.assertEqual((politics.economic_drift(nation_data, "A"), screen.drift), (-1, 1))
        self.assertEqual(screen._previews, {politics.POLITICAL: c.POLITICS_STEP, politics.ECONOMIC: -c.POLITICS_STEP,
                                            politics.QUALITY: 0, politics.STRATEGY: 0})
        from screens.game.politics_screen import DRIFT_MARKER
        self.assertTrue(self.tab(screen, politics.CIVILIAN).text.endswith(DRIFT_MARKER))
        self.assertFalse(self.tab(screen, politics.MILITARY).text.endswith(DRIFT_MARKER))
        politics.tick(screen.map_screen)
        self.assertEqual(politics.economic_value(nation_data, "A"), -c.POLITICS_STEP)
        self.assertEqual(screen.value, c.POLITICS_STEP)
        self.assertEqual(screen.map_screen.invalidate_map_presentation_cache.call_count, 2)

        # The Military tab steers its own two axes with the same controls.
        self.tab(screen, politics.MILITARY).callback()
        self.assertEqual(screen.group, politics.MILITARY)
        self.assertEqual({button.politics_axis for button in self.drift_buttons(screen)},
                         {politics.QUALITY, politics.STRATEGY})
        self.button(screen, politics.QUALITY, 1).callback()
        self.button(screen, politics.STRATEGY, -1).callback()
        self.assertEqual(politics.axis_drift(nation_data, "A", politics.QUALITY), 1)
        self.assertEqual(politics.axis_drift(nation_data, "A", politics.STRATEGY), -1)
        self.assertTrue(self.tab(screen, politics.MILITARY).text.endswith(DRIFT_MARKER))
        self.assertTrue(self.button(screen, politics.QUALITY, 1).is_selected)

    def test_policy_activation_follows_current_position_while_drifting(self):
        policy = {"id": "eligibility_fixture", "name": "Eligibility Fixture", "effects": {}, "min_politics": 0}
        with patch.object(politics, "POLICIES", (policy,)), patch.dict(politics.POLICIES_BY_ID, {policy["id"]: policy}):
            screen = self.screen(False)
            self.button(screen, politics.POLITICAL, 1).callback()  # Centralise from the strict boundary.
            self.assertTrue(screen.elements[-1].disabled)

            politics.tick(screen.map_screen)
            screen.refresh_ui()
            self.assertFalse(screen.elements[-1].disabled)

            self.button(screen, politics.POLITICAL, -1).callback()  # Liberalise back across the boundary.
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
        controls = [element for element in screen.elements if not hasattr(element, "politics_group")]
        self.assertEqual(len(controls), 1, "foreign view has no policy or drift controls")
        # Directions are private, so the view shows only where B is.
        self.assertEqual(screen._previews[politics.POLITICAL], 4)
        self.assertEqual(screen._previews[politics.ECONOMIC], c.POLITICS_START)
        screen.set_drift(1)
        screen.set_drift(-1, politics.ECONOMIC)
        self.assertEqual(politics.drift(map_screen.nation_data, "B"), -1)
        self.assertEqual(politics.economic_drift(map_screen.nation_data, "B"), 1)
        # Viewing the Military axes is not editing.
        self.tab(screen, politics.MILITARY).callback()
        self.assertEqual(screen.group, politics.MILITARY)
        self.assertEqual(self.drift_buttons(screen), [])

    def test_policy_scrollbar_moves_cards_opposite_to_handle(self):
        screen = self.screen(False)
        screen.policies_rect.width = 500
        screen.refresh_ui()
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
        self.assertEqual(len(screen.rows), len(politics.AXES))
        slider = screen.rows[1][0]
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=slider.handle_rect.center, button=1))
        slider.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=slider.rect.midleft, mobile_touch=True))
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=slider.rect.midleft, button=1))
        self.assertEqual(politics.economic_value(map_screen.nation_data, "A"), c.POLITICS_START)
        screen.elements[2].callback()

        self.assertTrue(screen.done)
        self.assertEqual(politics.value(map_screen.nation_data, "A"), 4)
        self.assertEqual(politics.economic_value(map_screen.nation_data, "A"), c.POLITICS_MIN)
        for axis in politics.AXES:
            self.assertEqual(politics.axis_drift(map_screen.nation_data, "A", axis["id"]), 0)
        map_screen.refresh_map_layers.assert_called_once_with("relations")

        # The military sliders save the same way.
        screen = Politics_Edit_Screen(map_screen, "A")
        screen._set(2, 1.0)
        screen._set(3, 0.0)
        screen.save()
        self.assertEqual(politics.axis_value(map_screen.nation_data, "A", politics.QUALITY), c.POLITICS_MAX)
        self.assertEqual(politics.axis_value(map_screen.nation_data, "A", politics.STRATEGY), c.POLITICS_MIN)
        self.assertEqual(politics.value(map_screen.nation_data, "A"), 4)

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
            forward = relations._political_affinity("A", "B", data)
            self.assertEqual(relations._political_affinity("B", "A", data), forward)
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

    def test_reputation_is_how_everyone_else_sees_a_country(self):
        """The design's own examples: political axis only, economies at the centre."""
        edge = c.POLITICS_MAX

        def opinion(viewer, viewed):
            data = {"Viewer": {politics.VALUE_KEY: viewer}, "Viewed": {politics.VALUE_KEY: viewed}}
            self.assertEqual(queries.get_relation_score("Viewer", "Viewer", data), 0)
            return queries.get_relation_score("Viewer", "Viewed", data)

        self.assertEqual(opinion(-edge, edge), -20)   # libertarian of authoritarian
        self.assertEqual(opinion(edge, -edge), 0)     # authoritarian of libertarian
        self.assertEqual(opinion(edge, edge), 0)
        self.assertEqual(opinion(-edge, -edge), 20)
        for other in range(c.POLITICS_MIN, c.POLITICS_MAX + 1):
            with self.subTest(other=other):
                # A fully authoritarian country stops caring about ideology.
                self.assertEqual(opinion(edge, other), 0)


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
        """Which is what puts the map button's badge out by itself."""
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

    def test_every_axis_drifts_and_tick_reports_whose_quality_moved(self):
        """The turn rescales maximum health only for the countries this names."""
        screen = StubTurnScreen({name: {} for name in ("A", "B", "C")})
        for axis in politics.AXES:
            politics.set_axis_drift(screen.nation_data, "A", axis["id"], 1)
        politics.set_axis_drift(screen.nation_data, "B", politics.STRATEGY, -1)
        politics.set_axis_value(screen.nation_data, "C", politics.QUALITY, c.POLITICS_MAX)
        politics.set_axis_drift(screen.nation_data, "C", politics.QUALITY, 1)
        self.assertEqual(politics.tick(screen), {"A"})
        for axis in politics.AXES:
            self.assertEqual(politics.axis_value(screen.nation_data, "A", axis["id"]), c.POLITICS_STEP)
        self.assertEqual(politics.axis_value(screen.nation_data, "B", politics.STRATEGY), -c.POLITICS_STEP)
        self.assertEqual(politics.axis_drift(screen.nation_data, "C", politics.QUALITY), 0)

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

    def test_policies_require_economics_or_quality_below_their_bound(self):
        for policy_id, axis, bound in (("prioritize_industrial_needs", politics.ECONOMIC, -2),
                                       ("siphon_military_funding", politics.QUALITY, 3)):
            with self.subTest(policy=policy_id):
                screen = self.screen_at()
                nation_data = screen.nation_data
                politics.set_axis_value(nation_data, "A", axis, bound)
                self.assertFalse(politics.requirements_met(nation_data, "A", policy_id))
                self.assertFalse(politics.activate_or_cancel_policy(nation_data, "A", policy_id))
                draft = {policy_id: {"status": politics.POLICY_ACTIVATING}}
                with self.assertRaises(ValueError):
                    politics.canonicalize_policy_draft(nation_data, "A", draft)

                politics.set_axis_value(nation_data, "A", axis, bound - 1)
                self.assertIn(policy_id, politics.canonicalize_policy_draft(nation_data, "A", draft))
                self.activate_and_finish(screen, policy_id)
                politics.set_axis_drift(nation_data, "A", axis, 1)
                politics.tick(screen)
                self.assertIsNone(politics.policy_state(nation_data, "A", policy_id))

    def test_cancel_can_be_undone_before_the_next_processed_turn(self):
        screen = self.screen_at(0, -3)
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
        screen = self.screen_at(0, -3)
        self.activate_and_finish(screen, "prioritize_industrial_needs")
        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        politics.tick(screen)

        self.assertIsNone(politics.policy_state(screen.nation_data, "A"))

    def test_unprocessed_activation_cancels_immediately(self):
        screen = self.screen_at(0, -3)
        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        politics.activate_or_cancel_policy(screen.nation_data, "A", "prioritize_industrial_needs")

        self.assertIsNone(politics.policy_state(
            screen.nation_data, "A", "prioritize_industrial_needs"))
        self.assertNotIn(politics.POLICY_KEY, screen.nation_data["A"])

    def test_each_eligible_policy_has_its_own_activation_and_effect(self):
        screen = self.screen_at(economic_value=-3)
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

    def test_a_centrist_nation_deals_its_core_territory_modifier_at_home(self):
        self.assertAlmostEqual(self.damage_dealt_by_a(c.POLITICS_START),
                               unit("A")["attack"] * politics.effect_at("core_territory_damage", c.POLITICS_START))

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
        # B fights on A's core, which is non-core territory for B.
        self.assertAlmostEqual(damage_taken(a_units),
                               unit("B")["attack"] * axis_damage_multiplier(c.POLITICS_MAX)
                               * politics.effect_at("non_core_territory_damage", c.POLITICS_START))

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
        # Both fight on C's core, which is non-core territory for each.
        base = unit("A")["attack"] * politics.effect_at("non_core_territory_damage", c.POLITICS_START)
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


class TerritoryDamageTests(unittest.TestCase):
    """Strategy's damage modifier depends on whose core the tile is."""

    def dealt(self, tile_owner, cores, strategy=c.POLITICS_START):
        screen = StubBattleMap()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        politics.set_axis_value(screen.nation_data, "A", politics.STRATEGY, strategy)
        prov = screen.add_province("p1", tile_owner, units=[unit("A"), unit("B")], cores=cores)
        b_units = [u for u in prov["units"] if u["owner"] == "B"]
        combat_processor.process_combat(screen)
        return damage_taken(b_units)

    def test_core_and_non_core_modifiers_follow_strategy(self):
        attack = unit("A")["attack"]
        for strategy in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            with self.subTest(strategy=strategy):
                self.assertAlmostEqual(self.dealt("A", ["A"], strategy),
                                       attack * politics.effect_at("core_territory_damage", strategy))
                self.assertAlmostEqual(self.dealt("B", ["B"], strategy),
                                       attack * politics.effect_at("non_core_territory_damage", strategy))

    def test_retaking_an_occupied_core_keeps_the_core_modifier(self):
        self.assertAlmostEqual(self.dealt("B", ["A", "B"]),
                               unit("A")["attack"] * politics.effect_at("core_territory_damage", c.POLITICS_START))

    def test_disable_cores_counts_every_owned_tile_as_core(self):
        attack = unit("A")["attack"]
        with patch.object(c, "DISABLE_CORES", True):
            self.assertAlmostEqual(self.dealt("A", []),
                                   attack * politics.effect_at("core_territory_damage", c.POLITICS_START))
            self.assertAlmostEqual(self.dealt("B", ["A"]),
                                   attack * politics.effect_at("non_core_territory_damage", c.POLITICS_START))


    def test_each_side_of_a_border_clash_fights_on_its_own_tile(self):
        nation_data = {"A": {"at_war_with": ["B"]}, "B": {"at_war_with": ["A"]}}
        a_home = {"id": "p1", "owner": "A", "cores": ["A"]}
        b_home = {"id": "p2", "owner": "B", "cores": ["B"]}
        a_unit, b_unit = unit("A"), unit("B")
        battle = combat_rules.build_battle([[a_unit], [b_unit]], nation_data, tiles=(a_home, b_home))
        shots = {id(targets[0]): attack for targets, attack in combat_rules.exchange(battle, nation_data)}
        core = politics.effect_at("core_territory_damage", c.POLITICS_START)
        self.assertAlmostEqual(shots[id(b_unit)], a_unit["attack"] * core)
        self.assertAlmostEqual(shots[id(a_unit)], b_unit["attack"] * core)


class DefenseAndHealthTests(unittest.TestCase):
    def test_strategy_scales_unit_defense_and_fort_defense(self):
        defender = unit("A", defense=50)
        province = {"owner": "A", "cores": ["A"], "buildings": ["Fort Lvl 2"], "units": [defender]}
        for strategy in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            with self.subTest(strategy=strategy):
                nation_data = {"A": {politics.STRATEGY_VALUE_KEY: strategy}}
                multiplier = politics.effect_at("defense", strategy)
                self.assertAlmostEqual(combat_rules.damage_after_defense(defender, 200, nation_data),
                                       200 - 50 * multiplier)
                self.assertAlmostEqual(
                    queries.get_fort_defense_bonus(province, defender, nation_data, combat_active=True),
                    2 * c.FORT_DEFENSE_PER_LEVEL * multiplier)

    def test_quality_rescales_maximum_health_and_keeps_the_health_fraction(self):
        library = {"Infantry": {"health": 1000, "attack": 10, "defense": 0, "speed": 1}}
        soldier = {"type": "Infantry", "owner": "A", "health": 500, "max_health": 1000}
        map_data = {1: {"owner": "A", "units": [soldier]}}
        for quality in (c.POLITICS_MIN, c.POLITICS_MAX, c.POLITICS_START):
            with self.subTest(quality=quality):
                nation_data = {"A": {politics.QUALITY_VALUE_KEY: quality}}
                queries.refresh_unit_stats(map_data, nation_data, library)
                expected = round(1000 * politics.effect_at("max_health", quality))
                self.assertEqual(soldier["max_health"], expected)
                self.assertAlmostEqual(soldier["health"] / soldier["max_health"], 0.5)
                self.assertEqual(queries.create_unit_dict("Infantry", "A", library, nation_data)["max_health"], expected)


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
                       * combat_rules.effective_damage_multiplier(attacker, screen.nation_data, province=prov))
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


class QualityResearchYearTests(unittest.TestCase):
    """Quality moves the year the ahead-of-time penalty measures from."""

    def test_professional_researches_ten_months_ahead_and_numerous_ten_behind(self):
        tree = {"due_now": {"years": [1920]}, "ten_months_out": {"years": [1920 + 10 / 12]}}
        for quality in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
            with self.subTest(quality=quality):
                nation_data = {"A": {"research": {}, politics.QUALITY_VALUE_KEY: quality,
                                     "research_queue": [{"tech_name": name, "points_remaining": 10_000} for name in tree]}}
                progress = queries.get_normal_research_progress(nation_data, "A", tree, 10, 1920.0)
                base = queries.get_base_research_points(nation_data, "A", 10)
                year = 1920.0 + politics.effect_at("research_year_months", quality) / 12
                self.assertAlmostEqual(queries.get_research_year(nation_data, "A", 1920.0), year)
                for name, data in tree.items():
                    self.assertAlmostEqual(progress[name], base * queries.get_research_multiplier(year, data["years"][0]))
                if quality == c.POLITICS_MIN:
                    self.assertAlmostEqual(progress["ten_months_out"], base)
                if quality == c.POLITICS_MAX:
                    self.assertAlmostEqual(progress["due_now"], base * 0.5 ** (10 / 12))


class AircraftRangeTests(unittest.TestCase):
    def test_strategy_scales_every_mission_radius(self):
        from types import SimpleNamespace
        library = {"Fixture Bomber": {"air_role": "bomber", "air_range_px": 10}}
        bomber = {"type": "Fixture Bomber", "owner": "A"}
        with patch.object(queries, "get_unit_library", return_value=library):
            listed = {kind: queries.air_order_radius(bomber, kind) for kind in ("AIR_ATTACK", "AIR_REPOSITION")}
            for strategy in (c.POLITICS_MIN, c.POLITICS_START, c.POLITICS_MAX):
                with self.subTest(strategy=strategy):
                    context = SimpleNamespace(nation_data={"A": {politics.STRATEGY_VALUE_KEY: strategy}})
                    for kind, radius in listed.items():
                        self.assertAlmostEqual(queries.air_order_radius(bomber, kind, context=context),
                                               radius * politics.effect_at("aircraft_range", strategy))


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
    """The parts of an AIWorld that ai_politics reads."""

    def __init__(self, nation_data, ratios=None, neighbors=None):
        self.nation_data = nation_data
        self._ratios = ratios or {}
        self.neighbors = neighbors or {}
        self.provs_by_owner = {}
        self.units_by_owner = {}
        self.land_border_tiles = {}
        self.economies = {}

    def power_ratio(self, nation, other):
        return self._ratios.get((nation, other), (1.0, 1.0))


def ai_world_with(*nations, **kwargs):
    nation_data = {n: {"name": n, "at_war_with": []} for n in nations}
    return StubWorld(nation_data, **kwargs)


def at_war(world, a="A", b="B"):
    world.nation_data[a]["at_war_with"] = [b]
    world.nation_data[b]["at_war_with"] = [a]


class AIPoliticsTests(unittest.TestCase):
    def setUp(self):
        from map_logic.ai import ai_politics
        self.ai_politics = ai_politics

    def land(self, world, cored, uncored, nation="A"):
        world.provs_by_owner[nation] = ([{"owner": nation, "cores": [nation]} for _ in range(cored)]
                                        + [{"owner": nation, "cores": []} for _ in range(uncored)])

    # --- Political and Economic follow how much land is cored --------------

    def test_fully_cored_land_is_libertarian_and_market(self):
        world = ai_world_with("A")
        self.land(world, 5, 0)
        with patch.object(c, "DISABLE_CORES", False):
            self.assertEqual(self.ai_politics.desired_value(world, "A"), c.POLITICS_MIN)
            self.assertEqual(self.ai_politics.desired_economic_value(world, "A"), c.POLITICS_MAX)

    def test_uncored_land_pulls_toward_authority_and_planning(self):
        world = ai_world_with("A")
        with patch.object(c, "DISABLE_CORES", False):
            self.land(world, 4, 1)
            some = (self.ai_politics.desired_value(world, "A"), self.ai_politics.desired_economic_value(world, "A"))
            self.land(world, 1, 4)
            most = (self.ai_politics.desired_value(world, "A"), self.ai_politics.desired_economic_value(world, "A"))
        self.assertGreater(some[0], c.POLITICS_MIN)
        self.assertLess(some[1], c.POLITICS_MAX)
        self.assertEqual(most, (c.POLITICS_MAX, c.POLITICS_MIN))

    # --- Quality -------------------------------------------------------------

    def test_a_safe_well_garrisoned_solvent_nation_is_professional(self):
        world = ai_world_with("A")
        self.assertEqual(self.ai_politics.desired_quality_value(world, "A"), c.POLITICS_MIN)

    def test_losing_a_war_pulls_toward_numerous(self):
        def target(border, glob):
            world = ai_world_with("A", "B", ratios={("A", "B"): (border, glob)})
            at_war(world)
            return self.ai_politics.desired_quality_value(world, "A")

        self.assertGreater(target(0.2, 0.2), target(5.0, 5.0))
        self.assertGreater(target(5.0, 5.0), c.POLITICS_MIN)

    def test_a_long_thinly_held_border_pulls_toward_numerous(self):
        """A big country that cannot put a unit on every border tile wants more of them, cheaper."""
        world = ai_world_with("A")
        world.land_border_tiles["A"] = set(range(10))
        world.units_by_owner["A"] = [({"owner": "A", "type": "Fixture"}, {}) for _ in range(2)]
        with patch.object(queries, "is_air_unit", return_value=False):
            thin = self.ai_politics.desired_quality_value(world, "A")
            world.units_by_owner["A"] = [({"owner": "A", "type": "Fixture"}, {}) for _ in range(10)]
            manned = self.ai_politics.desired_quality_value(world, "A")
        self.assertGreater(thin, c.POLITICS_START)
        self.assertEqual(manned, c.POLITICS_MIN)

    def test_an_unaffordable_army_pulls_toward_numerous(self):
        """A resource-poor country that cannot pay its upkeep wants the cheaper army."""
        world = ai_world_with("A")
        income = {"manpower": 1000, "materials": 1000, "fuel": 1000}
        world.economies["A"] = {"total_inc": income, "upkeep": dict.fromkeys(income, 0)}
        self.assertEqual(self.ai_politics.desired_quality_value(world, "A"), c.POLITICS_MIN)
        world.economies["A"]["upkeep"] = dict(income)
        self.assertEqual(self.ai_politics.desired_quality_value(world, "A"), c.POLITICS_MAX)

    # --- Strategy ------------------------------------------------------------

    def test_strategy_is_balanced_at_peace_and_follows_the_war_at_war(self):
        world = ai_world_with("A", "B")
        self.assertEqual(self.ai_politics.desired_strategy_value(world, "A"), c.POLITICS_START)

        winning = ai_world_with("A", "B", ratios={("A", "B"): (5.0, 5.0)})
        losing = ai_world_with("A", "B", ratios={("A", "B"): (0.2, 0.2)})
        at_war(winning)
        at_war(losing)
        self.assertLess(self.ai_politics.desired_strategy_value(winning, "A"), c.POLITICS_START)
        self.assertGreater(self.ai_politics.desired_strategy_value(losing, "A"), c.POLITICS_START)

    def test_enemies_on_its_cores_turn_a_winning_nation_defensive(self):
        world = ai_world_with("A", "B", ratios={("A", "B"): (5.0, 5.0)})
        at_war(world)
        self.land(world, 3, 0)
        offensive = self.ai_politics.desired_strategy_value(world, "A")
        world.provs_by_owner["B"] = [{"owner": "B", "cores": ["A"]}]
        self.assertEqual(self.ai_politics.desired_strategy_value(world, "A"), c.POLITICS_MAX)
        self.assertLess(offensive, c.POLITICS_START)

    # --- Walking toward the targets --------------------------------------------

    def test_it_walks_every_axis_toward_its_target_and_stops_on_arrival(self):
        world = ai_world_with("A", "B")
        targets = {axis: desired(world, "A") for axis, desired in self.ai_politics.DESIRED_POSITIONS.items()}
        for axis, target in targets.items():
            politics.set_axis_value(world.nation_data, "A", axis, target)
        directions = self.ai_politics.decide(world, "A", world.nation_data)
        self.assertEqual(set(directions.values()), {0})

        for axis, target in targets.items():
            with self.subTest(axis=axis):
                if target > c.POLITICS_MIN:
                    politics.set_axis_value(world.nation_data, "A", axis, c.POLITICS_MIN)
                    self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data)[axis], 1)
                    self.assertEqual(politics.axis_drift(world.nation_data, "A", axis), 1)
                if target < c.POLITICS_MAX:
                    politics.set_axis_value(world.nation_data, "A", axis, c.POLITICS_MAX)
                    self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data)[axis], -1)
                politics.set_axis_value(world.nation_data, "A", axis, target)

    def test_a_war_turns_a_drifting_nation_around(self):
        """The target is recomputed every turn, so it reverses rather than snaps."""
        world = ai_world_with("A", "B", ratios={("A", "B"): (0.2, 0.2)})
        politics.set_axis_value(world.nation_data, "A", politics.QUALITY, -4)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data)[politics.QUALITY], -1)

        at_war(world)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data)[politics.QUALITY], 1)
        self.assertEqual(politics.axis_value(world.nation_data, "A", politics.QUALITY), -4,
                         "deciding must not move the value; only tick does that")

    def test_the_same_world_decides_the_same_way_twice(self):
        """No `random` -- see the note in ai_personality.procedural."""
        first = ai_world_with("A", "B", ratios={("A", "B"): (0.7, 1.3)})
        second = ai_world_with("A", "B", ratios={("A", "B"): (0.7, 1.3)})
        at_war(first)
        at_war(second)
        for desired in self.ai_politics.DESIRED_POSITIONS.values():
            self.assertEqual(desired(first, "A"), desired(second, "A"))


if __name__ == "__main__":
    unittest.main()
