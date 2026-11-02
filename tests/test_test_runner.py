"""Check test isolation, timing, discovery, and failure reporting."""

import contextlib
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
import io
from pathlib import Path
import re
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest.mock import patch

import run_tests
from tests import add_test_cases, run_process_probes


@contextlib.contextmanager
def runner_modules(sources):
    """Create importable test modules for fresh worker interpreters."""
    with tempfile.TemporaryDirectory() as directory:
        package = Path(directory, "gd5_runner_fixture")
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        for name, source in sources.items():
            (package / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
        try:
            with patch.object(sys, "path", [directory, *sys.path]):
                yield [f"gd5_runner_fixture.{name}" for name in sources if name != "shared"]
        finally:
            for name in list(sys.modules):
                if name == "gd5_runner_fixture" or name.startswith("gd5_runner_fixture."):
                    del sys.modules[name]


class ParallelRunnerTests(unittest.TestCase):
    def test_spawned_workers_keep_fixtures_hooks_and_process_state_separate(self):
        sources = {
            "shared": "value = 'clean'",
            "first": """
                import os
                import unittest
                from gd5_runner_fixture import shared
                module_calls = 0

                def setUpModule():
                    global module_calls
                    module_calls += 1

                def tearDownModule():
                    assert module_calls == 1

                class Example(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls):
                        cls.calls = 0

                    def test_first(self):
                        print('FIXTURE_PID', os.getpid())
                        self.assertEqual(module_calls, 1)
                        self.assertEqual(shared.value, 'clean')
                        shared.value = 'changed'
                        type(self).calls += 1

                    def test_second(self):
                        self.assertEqual(self.calls, 1)
                        self.assertEqual(shared.value, 'changed')
            """,
            "second": """
                import os
                import unittest
                from gd5_runner_fixture import shared

                def function_case():
                    print('FIXTURE_PID', os.getpid())
                    assert shared.value == 'clean'

                class Hooks(unittest.TestCase):
                    @unittest.skip('optional fixture')
                    def test_skip(self):
                        pass

                    @unittest.expectedFailure
                    def test_expected_failure(self):
                        self.fail('expected')

                class Excluded(unittest.TestCase):
                    def test_not_selected_by_hook(self):
                        self.fail('load_tests was ignored')

                def load_tests(loader, tests, pattern):
                    return loader.suiteClass([
                        unittest.FunctionTestCase(function_case),
                        loader.loadTestsFromTestCase(Hooks),
                    ])
            """,
        }
        with runner_modules(sources) as names, contextlib.redirect_stdout(io.StringIO()) as output:
            result, discovery, execution = run_tests.run_parallel(names, True, 2)
        self.assertTrue(result.wasSuccessful(), (result.failures, result.errors))
        self.assertEqual(result.testsRun, 5)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(len(result.expectedFailures), 1)
        self.assertEqual(len(result.test_times), 5)
        self.assertIn("function_case", {name for _, name in result.test_times})
        self.assertEqual(len(set(re.findall(r"FIXTURE_PID (\d+)", output.getvalue()))), 2)
        self.assertGreaterEqual(discovery, 0)
        self.assertGreaterEqual(execution, 0)

    def test_worker_reports_failures_subtests_setup_errors_and_unexpected_successes(self):
        source = """
            import unittest

            class Example(unittest.TestCase):
                def test_failure(self):
                    self.fail('ordinary failure')

                def test_error(self):
                    raise RuntimeError('ordinary error')

                @unittest.expectedFailure
                def test_unexpected_success(self):
                    pass

                def test_subtests(self):
                    for value in range(2):
                        with self.subTest(value=value):
                            self.fail('subtest failure')

            class SetupFailure(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise RuntimeError('setup error')

                def test_unreachable(self):
                    raise AssertionError('must not run')
        """
        with runner_modules({"outcomes": source}) as names, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result, _, _ = run_tests.run_parallel(names, True, 2)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.testsRun, 4)
        self.assertEqual(len(result.failures), 3)
        self.assertEqual(len(result.errors), 2)
        self.assertEqual(len(result.unexpectedSuccesses), 1)
        self.assertIn("setup error", output.getvalue())
        self.assertIn("subtest failure", output.getvalue())

    def test_missing_module_is_an_error_instead_of_an_empty_success(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result, _, _ = run_tests.run_parallel(["gd5_missing_test_module"], True, 2)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors), 1)
        self.assertIn("ModuleNotFoundError", result.errors[0][1])

    def test_crashed_worker_fails_the_run_without_a_report(self):
        future = Future()
        future.set_exception(BrokenProcessPool("native worker crash"))
        with patch.object(run_tests, "load_suite", return_value=run_tests.TimingSuite()), \
                patch.object(run_tests, "ProcessPoolExecutor") as executor, \
                contextlib.redirect_stderr(io.StringIO()) as output:
            executor.return_value.__enter__.return_value.submit.return_value = future
            result, _, _ = run_tests.run_parallel([], True, 1)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 1)
        self.assertIn("stopped without complete results", output.getvalue())

    def test_independent_cases_run_once_each_with_separate_process_state(self):
        source = """
            import os
            import unittest
            value = 'clean'

            class Independent(unittest.TestCase):
                parallel_cases = True

                @classmethod
                def setUpClass(cls):
                    cls.calls = 0

                def setUp(self):
                    self.assertEqual(value, 'clean')
                    self.assertEqual(self.calls, 0)
                    type(self).calls += 1
                    print('CASE_PID', os.getpid())

                def test_first(self):
                    global value
                    value = 'changed'

                def test_second(self):
                    global value
                    value = 'changed'
        """
        with runner_modules({"independent": source}) as names, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            result, _, _ = run_tests.run_parallel(names, True, 2)
        self.assertTrue(result.wasSuccessful(), (result.failures, result.errors))
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(len(result.work_times), 2)
        self.assertEqual(len(set(re.findall(r"CASE_PID (\d+)", output.getvalue()))), 2)

    def test_missing_scheduled_case_cannot_report_an_empty_success(self):
        suite = run_tests.TimingSuite([unittest.FunctionTestCase(lambda: None)])
        with patch.object(run_tests, "load_suite", return_value=suite), \
                self.assertRaisesRegex(RuntimeError, "discovery changed"):
            run_tests.run_serial([], True, selected={"case:missing"})

    def test_default_full_run_uses_available_workers_and_returns_failure_status(self):
        result = run_tests.TimingResult(io.StringIO(), False, 0)
        result.testsRun = 1
        result.unexpectedSuccesses.append("unexpected success")
        with patch.object(run_tests.os, "cpu_count", return_value=2), \
                patch.object(run_tests, "run_parallel", return_value=(result, 0.0, 0.0)) as run, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            status = run_tests.main(["--quiet", "--durations", "0"])
        run.assert_called_once_with([], True, 2)
        self.assertEqual(status, 1)
        self.assertIn("1 unexpected successes", output.getvalue())

    def test_invalid_worker_count_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            run_tests.main(["--jobs", "0"])
        self.assertEqual(raised.exception.code, 2)

    def test_default_full_run_caps_worker_count_at_eight(self):
        result = run_tests.TimingResult(io.StringIO(), False, 0)
        with patch.object(run_tests.os, "cpu_count", return_value=16), \
                patch.object(run_tests, "run_parallel", return_value=(result, 0.0, 0.0)) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_tests.main(["--quiet", "--durations", "0"]), 0)
        run.assert_called_once_with([], True, 8)


class WorkSchedulingTests(unittest.TestCase):
    def test_longest_groups_are_balanced_without_missing_or_repeating_work(self):
        items = {name: run_tests.TimingSuite([unittest.FunctionTestCase(lambda: None)])
                 for name in ("short", "long", "medium", "tiny")}
        times = {"short": 2, "long": 9, "medium": 8, "tiny": 1, "removed": 1000}
        assignments = run_tests.balance_work(items, 2, times)
        self.assertEqual(assignments, [{"long", "tiny"}, {"medium", "short"}])
        self.assertEqual(sum(map(len, assignments)), len(items))
        self.assertEqual(set.union(*assignments), set(items))

    def test_first_run_uses_test_counts_and_zero_times_do_not_concentrate_work(self):
        def group(count):
            return run_tests.TimingSuite(unittest.FunctionTestCase(lambda: None) for _ in range(count))

        items = {"short": group(1), "long": group(10), "medium": group(9)}
        self.assertEqual(run_tests.balance_work(items, 2, {}), [{"long"}, {"medium", "short"}])
        assignments = run_tests.balance_work(items, 2, dict.fromkeys(items, 0))
        self.assertTrue(all(assignments))

    def test_only_opted_in_cases_are_separated_from_the_module_suite(self):
        class Regular(unittest.TestCase):
            def test_work(self):
                pass

        class Independent(Regular):
            parallel_cases = True

        regular = run_tests.TimingSuite([Regular("test_work")])
        untouched = run_tests.TimingSuite([regular])
        items = run_tests.work_items(run_tests.TimingSuite([untouched]))
        self.assertIs(next(iter(items.values()))._tests[0], untouched)
        module = run_tests.TimingSuite([regular, run_tests.TimingSuite([Independent("test_work")])])
        items = run_tests.work_items(run_tests.TimingSuite([module]))
        self.assertEqual(len(items), 2)
        self.assertEqual(sum(item.countTestCases() for item in items.values()), 2)
        self.assertEqual(sum(label.startswith("case:") for label in items), 1)

    def test_content_cases_bind_their_own_input_and_support_named_selection(self):
        seen = []

        class Content(unittest.TestCase):
            pass

        def content(self, value):
            seen.append(value)

        add_test_cases(Content, content, [("one file", 11), ("other-file", 29)])
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Content)
        result = unittest.TestResult()
        suite.run(result)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.testsRun, 2)
        self.assertEqual(seen, [11, 29])
        Content("test_content_001_other_file").run(result)
        self.assertEqual(seen, [11, 29, 29])


class TimingCacheTests(unittest.TestCase):
    def test_round_trip_merges_focused_timings_without_removing_other_groups(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(run_tests, "TIMINGS_PATH", str(Path(directory, "timings.json"))):
            run_tests.save_work_times([(3.5, "first"), (7, "second")])
            run_tests.save_work_times([(2, "first")])
            self.assertEqual(run_tests.read_work_times(), {"first": 2, "second": 7})

    def test_missing_malformed_and_invalid_values_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "timings.json")
            with patch.object(run_tests, "TIMINGS_PATH", str(path)):
                self.assertEqual(run_tests.read_work_times(), {})
                for text in ("not json", "[]", "null"):
                    path.write_text(text, encoding="utf-8")
                    self.assertEqual(run_tests.read_work_times(), {})
                path.write_text('{"valid": 3, "zero": 0, "negative": -1, "text": "2", '
                                '"bool": true, "nan": NaN, "infinite": Infinity}', encoding="utf-8")
                self.assertEqual(run_tests.read_work_times(), {"valid": 3, "zero": 0})
                path.write_text('{"too_large": ' + str(10 ** 400) + '}', encoding="utf-8")
                self.assertEqual(run_tests.read_work_times(), {})

    def test_unwritable_cache_keeps_previous_data_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "timings.json")
            path.write_text('{"previous": 1}', encoding="utf-8")
            with patch.object(run_tests, "TIMINGS_PATH", str(path)), \
                    patch.object(run_tests.os, "replace", side_effect=PermissionError("read only")), \
                    contextlib.redirect_stderr(io.StringIO()) as output:
                run_tests.save_work_times([(2, "new")])
                self.assertEqual(run_tests.read_work_times(), {"previous": 1})
            self.assertIn("Could not save test timings", output.getvalue())
            self.assertEqual(list(Path(directory).iterdir()), [path])


class ProcessProbeTests(unittest.TestCase):
    def test_probes_overlap_and_results_keep_input_order(self):
        ready = threading.Barrier(2)
        second_finished = threading.Event()

        def check(value):
            ready.wait(timeout=5)
            if value == "first":
                if not second_finished.wait(timeout=5):
                    raise AssertionError("second probe did not finish")
            else:
                second_finished.set()
            return value

        self.assertEqual(run_process_probes(check, ["first", "second"], workers=2),
                         ["first", "second"])

    def test_probe_errors_are_reported_to_the_caller(self):
        def check(value):
            raise RuntimeError(value)

        with self.assertRaisesRegex(RuntimeError, "failed probe"):
            run_process_probes(check, ["failed probe"], workers=1)


class TimingTests(unittest.TestCase):
    def test_group_time_includes_shared_setup_and_test_time_includes_cleanup(self):
        clock = [0.0]

        class Example(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                clock[0] += 3

            def setUp(self):
                clock[0] += 1

            def test_work(self):
                clock[0] += 2

            def tearDown(self):
                clock[0] += 1

            @classmethod
            def tearDownClass(cls):
                clock[0] += 4

        suite = run_tests.TimingSuite([Example("test_work")])
        with patch.object(run_tests.time, "perf_counter", side_effect=lambda: clock[0]):
            result = run_tests.TimingResult(io.StringIO(), False, 0)
            suite.run(result)

        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.test_times[0][0], 4)
        self.assertEqual(result.group_times[0][0], 11)

    def test_setup_failure_remains_a_failure_and_has_a_group_time(self):
        class Example(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("fixture failed")

            def test_work(self):
                raise AssertionError("must not run")

        result = run_tests.TimingResult(io.StringIO(), False, 0)
        run_tests.TimingSuite([Example("test_work")]).run(result)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.testsRun, 0)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(len(result.group_times), 1)

    def test_selected_failure_returns_nonzero(self):
        class Example(unittest.TestCase):
            def test_work(self):
                self.fail("expected failure")

        suite = run_tests.TimingSuite([Example("test_work")])
        with patch.object(unittest.TestLoader, "loadTestsFromNames", return_value=suite) as load, \
                patch.object(unittest.TestLoader, "discover", side_effect=AssertionError("unexpected discovery")), \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()):
            status = run_tests.main(["tests.selected", "--quiet", "--durations", "0"])
        self.assertEqual(status, 1)
        load.assert_called_once_with(["tests.selected"])
        self.assertIn("1 failed, 0 errored", output.getvalue())

    def test_default_discovery_keeps_skips_and_reports_timings(self):
        class Example(unittest.TestCase):
            @unittest.skip("optional dependency")
            def test_work(self):
                raise AssertionError("must not run")

        suite = run_tests.TimingSuite([Example("test_work")])
        with patch.object(unittest.TestLoader, "discover", return_value=suite) as discover, \
                contextlib.redirect_stdout(io.StringIO()) as output, \
                contextlib.redirect_stderr(io.StringIO()):
            status = run_tests.main(["--jobs", "1", "--quiet", "--durations", "1"])
        self.assertEqual(status, 0)
        discover.assert_called_once_with(start_dir=run_tests.TESTS_DIR, top_level_dir=run_tests.ROOT)
        self.assertIn("1 skipped", output.getvalue())
        self.assertIn("Slowest groups", output.getvalue())

    def test_odtl_discovery_includes_every_function_without_executing_it(self):
        from tests import test_odtl

        suite = unittest.defaultTestLoader.loadTestsFromModule(test_odtl)
        actual = {test.id() for test in suite}
        expected = {name for name, value in vars(test_odtl).items()
                    if name.startswith("test_") and callable(value)}
        self.assertTrue(expected)
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
