"""Turn progress distinguishes pending, unused, and completed AI workloads."""

import asyncio
from contextlib import ExitStack
import random
from types import SimpleNamespace
import unittest
from unittest import mock

from data.session_state import LOCAL_PLAY, REALTIME, TOURNAMENT
from data.state_access import BackendState
from map_logic.actions.player_actions import PlayerActionError
from map_logic.ai import ai_letters, ai_movement
from map_logic.system32 import turn_manager, turn_processor
from screens.game.map import Map
from ui.panels import turn_progress


class LocalEndTurnCheckTests(unittest.TestCase):
    """Ending a local turn uses the draft validator that multiplayer submissions use."""

    def context(self, **session):
        feedback = []
        context = BackendState(feedback=feedback.append)
        context.world.nation_data["A"] = {"materials": 0, "manpower": 0, "fuel": 0, "research": {}, "at_war_with": []}
        context.world.nation_data["The Rot"] = dict(context.world.nation_data["A"])
        province = {"id": 1, "json_key": "1", "owner": "A", "cores": ["A"], "neighbors": [],
                    "units": [], "building_queue": [], "unit_queue": [], "buildings": []}
        context.world.map_data["1"] = province
        context.world.id_to_province[1] = province
        context.session.player_country = "A"
        for name, value in session.items():
            setattr(context.session, name, value)
        return context, feedback

    def end_turn(self, context, *, rejection=None):
        validate = mock.patch.object(turn_manager.PlayerActions, "validate_draft",
                                     side_effect=rejection, autospec=True)
        with validate as check, mock.patch.object(turn_manager, "trigger_ai_thread") as trigger:
            turn_manager.advance_time(context)
        return check, trigger

    def test_a_rejected_local_draft_keeps_the_turn_open(self):
        context, feedback = self.context()
        check, trigger = self.end_turn(context, rejection=PlayerActionError("Fixture refusal."))
        check.assert_called_once()
        trigger.assert_not_called()
        self.assertEqual(feedback, ["Order update rejected: Fixture refusal."])

    def test_a_valid_local_draft_ends_the_turn(self):
        context, feedback = self.context()
        with mock.patch.object(turn_manager, "trigger_ai_thread") as trigger:
            turn_manager.advance_time(context)
        trigger.assert_called_once_with(context)
        self.assertEqual(feedback, [])

    def test_an_idle_unit_with_an_empty_order_does_not_block_a_move(self):
        context, feedback = self.context()
        origin = context.world.id_to_province[1]
        destination = dict(origin, id=2, json_key="2", neighbors=[1], units=[])
        context.world.map_data["2"] = destination
        context.world.id_to_province[2] = destination
        origin["neighbors"] = [2]
        idle = {"unit_id": "idle", "owner": "A", "type": "Fixture Infantry", "order": {}}
        moving = {"unit_id": "moving", "owner": "A", "type": "Fixture Infantry", "order": {"type": "MOVE", "path": [2]}}
        origin["units"] = [idle, moving]

        with mock.patch.object(turn_manager, "trigger_ai_thread") as trigger:
            turn_manager.advance_time(context)

        trigger.assert_called_once_with(context)
        self.assertEqual(feedback, [])
        self.assertEqual(moving["order"], {"type": "MOVE", "path": [2]})

    def test_a_nonempty_order_still_requires_a_valid_type(self):
        for order in ({"path": [2]}, {"type": []}):
            with self.subTest(order=order):
                context, feedback = self.context()
                context.world.id_to_province[1]["units"] = [
                    {"unit_id": "invalid", "owner": "A", "type": "Fixture Infantry", "order": order}]

                with mock.patch.object(turn_manager, "trigger_ai_thread") as trigger:
                    turn_manager.advance_time(context)

                trigger.assert_not_called()
                self.assertTrue(feedback)

    def test_networked_tactical_and_countryless_turns_skip_the_local_check(self):
        for session in ({"mode": TOURNAMENT}, {"mode": REALTIME}, {"tactical_mode": True},
                        {"player_country": "Spectator"}, {"player_country": "The Rot"}):
            with self.subTest(session=session):
                context, _feedback = self.context(**session)
                check, trigger = self.end_turn(context, rejection=PlayerActionError("Fixture refusal."))
                check.assert_not_called()
                trigger.assert_called_once_with(context)


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
        context.world.scenario_settings = {"ai_disabled": disabled}
        context.draw = mock.Mock()
        for phase in ("letters", "proactive_tasks", "proactive_llm_tasks", "responsive_tasks", "movement_tasks"):
            context.session.progress[phase].total = 9
            context.session.progress[phase].completed = 8
        with mock.patch.object(turn_processor.queries, "get_active_ai_nations", return_value=list(countries)), \
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
        self.assertEqual(context.session.progress["proactive_tasks"].total, 2)
        self.assertEqual(context.session.progress["movement_tasks"].total, 2)
        for phase in ("letters", "proactive_llm_tasks", "responsive_tasks"):
            self.assertEqual(context.session.progress[phase].total, 0)
            self.assertEqual(context.session.progress[phase].completed, 0)

    def test_enabled_model_workloads_remain_pending_until_prepared(self):
        context = self.trigger(mode="FIXTURE_PROVIDER")
        for phase in ("letters", "proactive_llm_tasks", "responsive_tasks"):
            self.assertEqual(context.session.progress[phase].total, -1)
            self.assertEqual(context.session.progress[phase].completed, 0)

    def test_disabled_ai_and_empty_ai_rosters_have_no_pending_work(self):
        for settings in ({"disabled": True}, {"countries": ()}):
            with self.subTest(settings=settings):
                context = self.trigger(mode="FIXTURE_PROVIDER", **settings)
                for phase in ("letters", "proactive_tasks", "proactive_llm_tasks", "responsive_tasks", "movement_tasks"):
                    self.assertEqual(context.session.progress[phase].total, 0)
                    self.assertEqual(context.session.progress[phase].completed, 0)

    def test_multi_turn_setup_counts_ai_without_advancing_random_state(self):
        context = BackendState()
        for country in ("A", "B", "C"):
            context.world.nation_data[country] = {"is_playable": True}
            context.world.map_data[country] = {"owner": country}
        context.session.active_players = ["A"]
        with mock.patch.object(turn_processor.ai_handler, "get_ai_mode", return_value="FIXTURE_PROVIDER"):
            for disabled, expected in ((False, 2), (True, 0)):
                with self.subTest(disabled=disabled):
                    context.world.scenario_settings = {"ai_disabled": disabled}
                    random_before = random.getstate()
                    turn_processor.initialize_ai_progress(context, multi_turn=True)
                    self.assertEqual(random.getstate(), random_before)
                    for phase in ("proactive_tasks", "movement_tasks"):
                        progress = context.session.progress[phase]
                        self.assertEqual((progress.completed, progress.total), (0, expected))
                    for phase in ("letters", "proactive_llm_tasks", "responsive_tasks"):
                        progress = context.session.progress[phase]
                        self.assertEqual((progress.completed, progress.total), (0, 0))

    def test_direct_disabled_ai_turn_clears_previous_movement_and_model_work(self):
        context = BackendState()
        context.world.scenario_settings = {"ai_disabled": True}
        for phase in ("letters", "movement_tasks", "responsive_tasks"):
            context.session.progress[phase].total = -1
            context.session.progress[phase].completed = 4
        with mock.patch.object(turn_processor.ai_llm_runner, "begin_turn"), \
                mock.patch.object(turn_processor.scripted_events, "process_scripted_events"), \
                mock.patch.object(turn_processor.diplomacy_processor, "process_diplomacy_turn"), \
                mock.patch.object(turn_processor.ai_movement, "process_ai_unit_orders") as movement:
            asyncio.run(turn_processor.prepare_turn(context))
        movement.assert_not_called()
        for phase in ("letters", "movement_tasks", "responsive_tasks"):
            self.assertEqual(context.session.progress[phase].total, 0)
            self.assertEqual(context.session.progress[phase].completed, 0)

    def test_model_off_letters_clear_previous_counts(self):
        context = BackendState()
        context.session.progress["letters"].total, context.session.progress["letters"].completed = 3, 2
        with mock.patch.object(ai_letters.ai_handler, "get_ai_mode", return_value="OFF"):
            ai_letters.process_letters(context)
        self.assertEqual((context.session.progress["letters"].completed, context.session.progress["letters"].total), (0, 0))

    def test_no_letter_writers_clear_the_pending_total(self):
        context = BackendState()
        context.session.progress["letters"].total = -1
        with mock.patch.object(ai_letters.ai_handler, "get_ai_mode", return_value="FIXTURE_PROVIDER"), \
                mock.patch.object(ai_letters.ai_world, "for_screen"), \
                mock.patch.object(ai_letters.queries, "get_living_nations", return_value={"A", "B"}), \
                mock.patch.object(ai_letters.queries, "get_active_ai_nations", return_value=["A", "B"]), \
                mock.patch.object(ai_letters.ai_evaluation, "llm_enabled_for", return_value=None):
            ai_letters.process_letters(context)
        self.assertEqual((context.session.progress["letters"].completed, context.session.progress["letters"].total), (0, 0))


class MultiTurnProgressTests(unittest.TestCase):
    def test_counter_advances_after_success_and_abort_finishes_the_current_turn(self):
        for stop, expected in (("finish", 3), ("abort", 2), ("failure", 1)):
            with self.subTest(stop=stop):
                context = BackendState()
                progress = context.session.progress["multi_turns"]
                progress.total = 3
                counts_during_resolution = []

                async def resolve(state):
                    counts_during_resolution.append(progress.completed)
                    if progress.completed == 1:
                        if stop == "failure":
                            raise ValueError("fixture error")
                        if stop == "abort":
                            state.session.multi_turn_abort_requested = True

                with mock.patch.object(turn_processor, "prepare_turn"), \
                        mock.patch.object(turn_processor, "resolve_turn_logic", side_effect=resolve), \
                        mock.patch.object(turn_processor.ai_handler, "FORCE_SKIP", False):
                    asyncio.run(Map._run_multi_turn_thread(context, 3))

                self.assertEqual(progress.completed, expected)
                self.assertEqual(progress.total, 2 if stop == "abort" else 3)
                self.assertEqual(counts_during_resolution, [0, 1, 2] if stop == "finish" else [0, 1])
                self.assertEqual(bool(context.session.thread_error), stop == "failure")
                self.assertTrue(context.session.multi_turn_processing_complete)

    def test_history_keeps_the_same_last_two_turns_of_a_batch(self):
        context = BackendState()
        context.session.player_country = "A"
        progress = context.session.progress["multi_turns"]
        progress.total = 4
        recorded = []

        def snapshot(state):
            recorded.append(state.world.time_manager.total_turns)

        with mock.patch.object(turn_processor, "prepare_turn"), \
                mock.patch.object(turn_processor, "snapshot_history", side_effect=snapshot), \
                mock.patch.object(turn_processor.c, "RECORD_HISTORY", True), \
                mock.patch.object(turn_processor.ai_handler, "FORCE_SKIP", False):
            asyncio.run(Map._run_multi_turn_thread(context, 4))

        self.assertFalse(context.session.thread_error)
        self.assertEqual(recorded, [3, 4])


class MovementCounterTests(unittest.TestCase):
    def plan(self, *, fail=False, countries=("Empty", "Air", "Ground")):
        context = BackendState()
        air, ground = {"kind": "air"}, {"kind": "ground"}
        air_base, ground_base = {"units": [air]}, {"units": [ground]}
        units = {"Empty": [], "Air": [(air, air_base)], "Ground": [(ground, ground_base)]}
        provinces = {name: [] for name in countries}
        seen, cleanup = [], []

        def assign_air(_context, country, _units, **_kwargs):
            seen.append((country, context.session.progress["movement_tasks"].completed, context.session.progress["movement_tasks"].total))
            if fail:
                raise ValueError("Fixture planning failure")

        replacements = {
            "_build_shared_pathing_caches": (set(), set(), {}),
            "_reset_orders_and_collect_units": (units, provinces),
            "_gather_enemies": [], "_compute_unsafe_waters": {},
            "_discover_borders_and_targets": {"all_enemy_coasts": [], "enemy_coastal_waters": [],
                                               "enemy_targets": set(), "unclaimed_targets": set(), "coastal_approaches": {}, "naval_approaches": {}},
            "_track_battles_and_convoys": {"active_battles": set(), "lost_battles": set()},
            "_build_target_assignments": {"target_destinations": [], "naval_destinations": []}, "_repair_havens": {},
        }
        with ExitStack() as patches:
            for name, value in replacements.items():
                patches.enter_context(mock.patch.object(ai_movement, name, return_value=value))
            patches.enter_context(mock.patch.object(ai_movement, "_assign_air_orders", side_effect=assign_air))
            patches.enter_context(mock.patch.object(ai_movement, "_assign_maintenance_orders"))
            patches.enter_context(mock.patch.object(ai_movement, "_cancel_opposing_transitions",
                side_effect=lambda *args: cleanup.append(context.session.progress["movement_tasks"].completed)))
            patches.enter_context(mock.patch.object(ai_movement.queries, "get_active_ai_nations", return_value=list(countries)))
            patches.enter_context(mock.patch.object(ai_movement.queries, "get_all_friendly_nations", return_value=set()))
            patches.enter_context(mock.patch.object(ai_movement.queries, "is_air_unit", side_effect=lambda unit, **kw: unit["kind"] == "air"))
            patches.enter_context(mock.patch.object(ai_movement.queries, "is_air_transport", return_value=False))
            patches.enter_context(mock.patch.object(ai_movement.ai_world, "for_screen",
                return_value=SimpleNamespace(land_entry_ids=lambda country: set(), visible_provinces=lambda country: None,
                                             provs_by_owner={})))
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
        self.assertEqual((context.session.progress["movement_tasks"].completed, context.session.progress["movement_tasks"].total), (3, 3))

    def test_failed_country_is_not_counted_as_complete(self):
        context, seen, cleanup = self.plan(fail=True)
        self.assertEqual((context.session.progress["movement_tasks"].completed, context.session.progress["movement_tasks"].total), (1, 3))
        self.assertEqual(cleanup, [])

    def test_empty_roster_has_no_movement_work(self):
        context, seen, cleanup = self.plan(countries=())
        self.assertEqual((context.session.progress["movement_tasks"].completed, context.session.progress["movement_tasks"].total), (0, 0))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
