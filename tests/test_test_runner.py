"""Check test isolation, timing, discovery, and failure reporting."""

import contextlib
import io
import threading
import unittest
from unittest.mock import patch

import run_tests
from tests import run_process_probes


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
            status = run_tests.main(["--quiet", "--durations", "1"])
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
