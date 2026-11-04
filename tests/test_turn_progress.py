"""Turn progress distinguishes pending, unused, and completed AI workloads."""

import asyncio
from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest import mock

from data.state_access import BackendState
from map_logic.ai import ai_letters, ai_movement
from map_logic.system32 import turn_manager, turn_processor
from ui.panels import turn_progress


class ProgressValuesTests(unittest.TestCase):
    def test_unknown_workload_remains_calculating(self):
        self.assertEqual(turn_progress.turn_progress_values(0, -1), (0.0, "Calculating..."))

    def test_no_work_is_complete_and_not_applicable(self):
        self.assertEqual(turn_progress.turn_progress_values(0, 0), (1.0, "N/A"))

    def test_known_workload_uses_its_actual_completion_count(self):
        self.assertEqual(turn_progress.turn_progress_values(2, 5), (0.4, "2/5"))


class TurnCounterTests(unittest.TestCase):
    def trigger(self, *, disabled=False, mode="OFF", countries=("A", "B")):
        context = BackendState()
        context.scenario_settings = {"ai_disabled": disabled}
        context.draw = mock.Mock()
        for phase in ("letters", "proactive_tasks", "proactive_llm_tasks", "responsive_tasks", "movement_tasks"):
            setattr(context.session, phase + "_total", 9)
            setattr(context.session, phase + "_completed", 8)
        with mock.patch.object(turn_manager.queries, "get_active_ai_nations", return_value=list(countries)), \
                mock.patch.object(turn_manager.ai_handler, "get_ai_mode", return_value=mode), \
                mock.patch.object(turn_manager.ai_handler, "FORCE_SKIP", True), \
                mock.patch.object(turn_manager.ai_handler, "CURRENT_TURN_ID", 0), \
                mock.patch.object(turn_manager.pygame.display, "get_surface"), \
                mock.patch.object(turn_manager.pygame.display, "flip"), \
                mock.patch.object(turn_manager, "run_background") as background:
            turn_manager.trigger_ai_thread(context)
        background.assert_called_once_with(turn_manager.run_ai_processing_thread, context)
        return context

    def test_model_off_leaves_rule_based_work_active(self):
        context = self.trigger()
        self.assertEqual(context.proactive_tasks_total, 2)
        self.assertEqual(context.movement_tasks_total, 2)
        for phase in ("letters", "proactive_llm_tasks", "responsive_tasks"):
            self.assertEqual(getattr(context, phase + "_total"), 0)
            self.assertEqual(getattr(context, phase + "_completed"), 0)

    def test_enabled_model_workloads_remain_pending_until_prepared(self):
        context = self.trigger(mode="FIXTURE_PROVIDER")
        for phase in ("letters", "proactive_llm_tasks", "responsive_tasks"):
            self.assertEqual(getattr(context, phase + "_total"), -1)
            self.assertEqual(getattr(context, phase + "_completed"), 0)

    def test_disabled_ai_and_empty_ai_rosters_have_no_pending_work(self):
        for settings in ({"disabled": True}, {"countries": ()}):
            with self.subTest(settings=settings):
                context = self.trigger(mode="FIXTURE_PROVIDER", **settings)
                for phase in ("letters", "proactive_tasks", "proactive_llm_tasks", "responsive_tasks", "movement_tasks"):
                    self.assertEqual(getattr(context, phase + "_total"), 0)
                    self.assertEqual(getattr(context, phase + "_completed"), 0)

    def test_direct_disabled_ai_turn_clears_previous_movement_and_model_work(self):
        context = BackendState()
        context.scenario_settings = {"ai_disabled": True}
        for phase in ("letters", "movement_tasks", "responsive_tasks"):
            setattr(context, phase + "_total", -1)
            setattr(context, phase + "_completed", 4)
        with mock.patch.object(turn_processor.ai_llm_runner, "begin_turn"), \
                mock.patch.object(turn_processor.scripted_events, "process_scripted_events"), \
                mock.patch.object(turn_processor.diplomacy_processor, "process_diplomacy_turn"), \
                mock.patch.object(turn_processor.ai_movement, "process_ai_unit_orders") as movement:
            asyncio.run(turn_processor.prepare_turn(context))
        movement.assert_not_called()
        for phase in ("letters", "movement_tasks", "responsive_tasks"):
            self.assertEqual(getattr(context, phase + "_total"), 0)
            self.assertEqual(getattr(context, phase + "_completed"), 0)

    def test_model_off_letters_clear_previous_counts(self):
        context = BackendState()
        context.letters_total, context.letters_completed = 3, 2
        with mock.patch.object(ai_letters.ai_handler, "get_ai_mode", return_value="OFF"):
            ai_letters.process_letters(context)
        self.assertEqual((context.letters_completed, context.letters_total), (0, 0))

    def test_no_letter_writers_clear_the_pending_total(self):
        context = BackendState()
        context.letters_total = -1
        with mock.patch.object(ai_letters.ai_handler, "get_ai_mode", return_value="FIXTURE_PROVIDER"), \
                mock.patch.object(ai_letters.ai_world, "for_screen"), \
                mock.patch.object(ai_letters.queries, "get_living_nations", return_value={"A", "B"}), \
                mock.patch.object(ai_letters.queries, "get_active_ai_nations", return_value=["A", "B"]), \
                mock.patch.object(ai_letters.ai_evaluation, "llm_enabled_for", return_value=None):
            ai_letters.process_letters(context)
        self.assertEqual((context.letters_completed, context.letters_total), (0, 0))


class MovementCounterTests(unittest.TestCase):
    def plan(self, *, fail=False, countries=("Empty", "Air", "Ground")):
        context = BackendState()
        air, ground = {"kind": "air"}, {"kind": "ground"}
        air_base, ground_base = {"units": [air]}, {"units": [ground]}
        units = {"Empty": [], "Air": [(air, air_base)], "Ground": [(ground, ground_base)]}
        provinces = {name: [] for name in countries}
        seen, cleanup = [], []

        def assign_air(_context, country, _units):
            seen.append((country, context.movement_tasks_completed, context.movement_tasks_total))
            if fail:
                raise ValueError("Fixture planning failure")

        replacements = {
            "_build_shared_pathing_caches": (set(), set(), {}),
            "_reset_orders_and_collect_units": (units, provinces),
            "_gather_enemies": [], "_compute_unsafe_waters": {},
            "_discover_borders_and_targets": {"all_enemy_coasts": [], "enemy_coastal_waters": []},
            "_track_battles_and_convoys": {"active_battles": set()},
            "_build_target_assignments": {"target_destinations": []}, "_repair_havens": {},
        }
        with ExitStack() as patches:
            for name, value in replacements.items():
                patches.enter_context(mock.patch.object(ai_movement, name, return_value=value))
            patches.enter_context(mock.patch.object(ai_movement, "_assign_air_orders", side_effect=assign_air))
            patches.enter_context(mock.patch.object(ai_movement, "_assign_maintenance_orders"))
            patches.enter_context(mock.patch.object(ai_movement, "_cancel_opposing_transitions",
                side_effect=lambda *args: cleanup.append(context.movement_tasks_completed)))
            patches.enter_context(mock.patch.object(ai_movement.queries, "get_active_ai_nations", return_value=list(countries)))
            patches.enter_context(mock.patch.object(ai_movement.queries, "get_all_friendly_nations", return_value=set()))
            patches.enter_context(mock.patch.object(ai_movement.queries, "is_air_unit", side_effect=lambda unit, **kw: unit["kind"] == "air"))
            patches.enter_context(mock.patch.object(ai_movement.queries, "is_air_transport", return_value=False))
            patches.enter_context(mock.patch.object(ai_movement.ai_world, "for_screen",
                return_value=SimpleNamespace(land_entry_ids=lambda country: set())))
            if fail:
                with self.assertRaises(ValueError):
                    ai_movement._generate_unit_orders(context)
            else:
                ai_movement._generate_unit_orders(context)
        return context, seen, cleanup

    def test_no_order_and_air_only_passes_advance_country_progress(self):
        context, seen, cleanup = self.plan()
        self.assertEqual(seen, [("Air", 1, 3), ("Ground", 2, 3)])
        self.assertEqual(cleanup, [2])
        self.assertEqual((context.movement_tasks_completed, context.movement_tasks_total), (3, 3))

    def test_failed_country_is_not_counted_as_complete(self):
        context, seen, cleanup = self.plan(fail=True)
        self.assertEqual((context.movement_tasks_completed, context.movement_tasks_total), (1, 3))
        self.assertEqual(cleanup, [])

    def test_empty_roster_has_no_movement_work(self):
        context, seen, cleanup = self.plan(countries=())
        self.assertEqual((context.movement_tasks_completed, context.movement_tasks_total), (0, 0))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
