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
from tests import run_process_probes


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

                class Example(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls):
                        cls.calls = 0

                    def test_first(self):
                        print('FIXTURE_PID', os.getpid())
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
        with patch.object(run_tests, "ProcessPoolExecutor") as executor, \
                contextlib.redirect_stderr(io.StringIO()) as output:
            executor.return_value.__enter__.return_value.submit.return_value = future
            result, _, _ = run_tests.run_parallel([], True, 1)
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(len(result.errors), 1)
        self.assertIn("stopped without complete results", output.getvalue())

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
