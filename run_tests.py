"""Runs the whole test suite.

Right-click this file in the editor and pick "Run Python File in Terminal" --
no arguments, no typing. Everything under tests/ named test_*.py is picked up
automatically, so new test files need no wiring up here.
Audio uses a silent driver; the application harness skips startup music and
the native desktop audio engine.
Full runs use up to four processes. Use --jobs 1 for sequential execution.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
import contextlib
import io
import multiprocessing
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(ROOT, "tests")


class TimingResult(unittest.TextTestResult):
    """Measure each test, including its setup and cleanup."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_times = []
        self.group_times = []

    def startTest(self, test):
        super().startTest(test)
        self._test_started = time.perf_counter()

    def stopTest(self, test):
        self.test_times.append((time.perf_counter() - self._test_started, test.id()))
        super().stopTest(test)


class TimingSuite(unittest.TestSuite):
    """Measure test groups, including shared fixture work outside test methods."""

    def run(self, result, debug=False):
        tests = list(self)
        # The loader groups methods by class. Parent suites contain suites.
        is_group = bool(tests) and all(isinstance(test, unittest.TestCase) for test in tests)
        started = time.perf_counter()
        try:
            return super().run(result, debug)
        finally:
            if is_group:
                if isinstance(tests[0], unittest.FunctionTestCase):
                    label = tests[0]._testFunc.__module__
                else:
                    label = tests[0].id().rsplit(".", 1)[0]
                result.group_times.append((time.perf_counter() - started, label))


def configure_environment():
    """Configure headless drivers before discovery in each interpreter."""
    # Works no matter which directory the editor launched us from
    sys.path.insert(0, ROOT)
    from tests import configure_test_audio
    configure_test_audio()
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    if os.name == "nt":
        # Inherit a non-modal native error policy in test subprocesses. A
        # crashing dependency still returns a failing exit code, but cannot
        # strand the test runner behind a Windows Application Error dialog.
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    # Native V8/SDL audio stress tests are opt-in via
    # GD5_RUN_NATIVE_AUDIO_TESTS=1; ordinary test runs avoid native audio
    # stress processes.


def run_serial(names, quiet, *, shard=0, shards=1):
    """Keep each discovered module suite together, including discovery hooks."""
    configure_environment()
    loader = unittest.TestLoader()
    loader.suiteClass = TimingSuite
    started = time.perf_counter()
    if names:
        suite = loader.loadTestsFromNames(names)
    else:
        suite = loader.discover(start_dir=TESTS_DIR, top_level_dir=ROOT)
    if shards > 1:
        # Discovery yields one suite per module. Do not flatten these suites:
        # class fixtures and module load_tests hooks must retain their behavior.
        suite = loader.suiteClass(list(suite)[shard::shards])
    discovery_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result = unittest.TextTestRunner(
        verbosity=0 if quiet else 2, resultclass=TimingResult).run(suite)
    execution_seconds = time.perf_counter() - started
    return result, discovery_seconds, execution_seconds


RESULT_LISTS = ("failures", "errors", "skipped", "expectedFailures", "unexpectedSuccesses",
                "test_times", "group_times")


def run_worker(names, quiet, shard, shards):
    """Return printable results without sending game objects between processes."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result, discovery, execution = run_serial(names, quiet, shard=shard, shards=shards)
    data = {"testsRun": result.testsRun, "discovery": discovery, "execution": execution,
            "output": output.getvalue()}
    for field in RESULT_LISTS:
        values = getattr(result, field)
        if field in ("test_times", "group_times"):
            data[field] = values
        elif field == "unexpectedSuccesses":
            data[field] = [str(test) for test in values]
        else:
            data[field] = [(str(test), detail) for test, detail in values]
    return data


def run_parallel(names, quiet, jobs):
    """Use fresh interpreters so workers cannot share patches or SDL state."""
    result = TimingResult(io.StringIO(), False, 0)
    discovery_seconds = execution_seconds = 0.0
    # Spawn isolates native libraries. A process must not execute two shards,
    # even when one shard finishes before all processes have started.
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn"),
                             max_tasks_per_child=1) as pool:
        futures = {pool.submit(run_worker, names, quiet, shard, jobs): shard + 1 for shard in range(jobs)}
        for future in as_completed(futures):
            number = futures[future]
            try:
                data = future.result()
            except BrokenProcessPool as exc:
                # A native crash must fail the run even without a test report.
                message = f"Worker {number}/{jobs} stopped without complete results: {exc}"
                result.errors.append((f"worker {number}", message))
                print(message, file=sys.stderr)
                continue
            print(f"\nWorker {number}/{jobs}:")
            print(data["output"], end="")
            result.testsRun += data["testsRun"]
            for field in RESULT_LISTS:
                getattr(result, field).extend(data[field])
            discovery_seconds += data["discovery"]
            execution_seconds += data["execution"]
    return result, discovery_seconds, execution_seconds


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", help="Optional unittest module, class, or method names.")
    parser.add_argument("--durations", type=int, default=10,
                        help="Show this many slow tests and groups; zero hides timing details.")
    parser.add_argument("-q", "--quiet", action="store_true", help="Hide per-test progress.")
    parser.add_argument("-j", "--jobs", type=int,
                        help="Worker processes; default: up to four for full runs, one for focused runs.")
    args = parser.parse_args(argv)
    if args.durations < 0:
        parser.error("--durations must be zero or greater")
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be one or greater")
    jobs = args.jobs if args.jobs is not None else (1 if args.tests else min(4, os.cpu_count() or 1))
    started = time.perf_counter()
    if jobs == 1:
        result, discovery_seconds, execution_seconds = run_serial(args.tests, args.quiet)
    else:
        result, discovery_seconds, execution_seconds = run_parallel(args.tests, args.quiet, jobs)

    print()
    if jobs == 1:
        print(f"Discovery: {discovery_seconds:.3f}s; execution: {execution_seconds:.3f}s")
    else:
        print(f"Parallel wall time: {time.perf_counter() - started:.3f}s ({jobs} workers)")
        print(f"Worker totals: discovery: {discovery_seconds:.3f}s; execution: {execution_seconds:.3f}s")
    if args.durations:
        for title, timings in (("Slowest tests (includes per-test setup and cleanup)", result.test_times),
                               ("Slowest groups (includes shared fixture work)", result.group_times)):
            print(title + ":")
            for seconds, name in sorted(timings, reverse=True)[:args.durations]:
                print(f"  {seconds:8.3f}s  {name}")
    if result.wasSuccessful():
        print(f"All {result.testsRun} tests passed; {len(result.skipped)} skipped.")
    else:
        print(f"{len(result.failures)} failed, {len(result.errors)} errored, "
              f"{len(result.unexpectedSuccesses)} unexpected successes, out of {result.testsRun} tests.")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
