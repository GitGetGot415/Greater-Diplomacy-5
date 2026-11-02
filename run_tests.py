"""Runs the whole test suite.

Right-click this file in the editor and pick "Run Python File in Terminal" --
no arguments, no typing. Everything under tests/ named test_*.py is picked up
automatically, so new test files need no wiring up here.
Audio uses a silent driver; the application harness skips startup music and
the native desktop audio engine.
Full runs use up to eight processes. Use --jobs 1 for sequential execution.
The local .test_durations.json cache balances work using previous timings.
Ordinary modules stay together. Classes marked parallel_cases opt into splitting.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
import contextlib
import io
import json
import multiprocessing
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(ROOT, "tests")
TIMINGS_PATH = os.path.join(ROOT, ".test_durations.json")


class TimingResult(unittest.TextTestResult):
    """Measure each test, including its setup and cleanup."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.test_times = []
        self.group_times = []
        self.work_times = []

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
            if hasattr(self, "work_label"):
                result.work_times.append((time.perf_counter() - started, self.work_label))
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


def load_suite(names):
    """Apply the same discovery hooks in the planner and fresh workers."""
    configure_environment()
    loader = unittest.TestLoader()
    loader.suiteClass = TimingSuite
    if names:
        return loader.loadTestsFromNames(names)
    return loader.discover(start_dir=TESTS_DIR, top_level_dir=ROOT)


def work_items(suite):
    """Keep module suites intact unless a class explicitly permits independent cases."""
    def separate(node):
        if isinstance(node, unittest.TestCase):
            if getattr(type(node), "parallel_cases", False):
                return None, [node]
            return node, []
        remaining, independent = [], []
        for child in node:
            regular, cases = separate(child)
            if regular is not None:
                remaining.append(regular)
            independent.extend(cases)
        if not independent:
            return node, []
        return TimingSuite(remaining) if remaining else None, independent

    def first_test(node):
        if isinstance(node, unittest.TestCase):
            return node
        for child in node:
            first = first_test(child)
            if first is not None:
                return first
        return None

    items = {}
    for module_suite in suite:
        regular, independent = separate(module_suite)
        candidates = ([regular] if regular is not None else []) + independent
        for candidate in candidates:
            first = first_test(candidate)
            if first is None:
                continue
            # A group and its first independent case must have different keys.
            label = ("case:" if isinstance(candidate, unittest.TestCase) else "suite:") + first.id()
            if label in items:
                # Repeated command-line selections still run as often as requested.
                label += f":{len(items)}"
            group = TimingSuite([candidate])
            group.work_label = label
            items[label] = group
    return items


def read_work_times():
    """Ignore absent or invalid local timing data. It never selects tests."""
    try:
        with open(TIMINGS_PATH, encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(saved, dict):
        return {}
    return {name: seconds for name, seconds in saved.items()
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool)
            and 0 <= seconds <= sys.float_info.max}


def save_work_times(timings):
    """Replace the optional cache atomically, including results from focused runs."""
    if not timings:
        return
    saved = read_work_times()
    saved.update({name: seconds for seconds, name in timings})
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(TIMINGS_PATH),
                                         prefix=".test_durations.", suffix=".json", delete=False) as handle:
            temporary = handle.name
            json.dump(saved, handle, indent=2, sort_keys=True)
        os.replace(temporary, TIMINGS_PATH)
    except OSError as exc:
        print(f"Could not save test timings: {exc}", file=sys.stderr)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def balance_work(items, jobs, timings):
    """Assign the longest groups first. Use test counts before timings exist."""
    estimates = {label: timings.get(label, group.countTestCases() * 0.01)
                 for label, group in items.items()}
    assignments = [[] for _ in range(jobs)]
    loads = [0.0] * jobs
    for label in sorted(items, key=lambda name: estimates[name], reverse=True):
        index = min(range(jobs), key=lambda worker: (loads[worker], len(assignments[worker]), worker))
        assignments[index].append(label)
        loads[index] += estimates[label]
    # Keep discovery order within each process to reduce shared-fixture surprises.
    return [set(assignment) for assignment in assignments]


def run_serial(names, quiet, *, shard=0, shards=1, selected=None):
    """Keep ordinary module suites and their discovery hooks together."""
    started = time.perf_counter()
    suite = load_suite(names)
    if selected is not None:
        items = work_items(suite)
        missing = selected - items.keys()
        if missing:
            raise RuntimeError(f"Test discovery changed after scheduling: {sorted(missing)}")
        suite = TimingSuite(group for label, group in items.items() if label in selected)
    elif shards > 1:
        suite = TimingSuite(list(suite)[shard::shards])
    else:
        suite = TimingSuite(work_items(suite).values())
    discovery_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result = unittest.TextTestRunner(
        verbosity=0 if quiet else 2, resultclass=TimingResult).run(suite)
    execution_seconds = time.perf_counter() - started
    return result, discovery_seconds, execution_seconds


RESULT_LISTS = ("failures", "errors", "skipped", "expectedFailures", "unexpectedSuccesses",
                "test_times", "group_times", "work_times")


def run_worker(names, quiet, shard, shards, selected=None):
    """Return printable results without sending game objects between processes."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        result, discovery, execution = run_serial(names, quiet, shard=shard, shards=shards, selected=selected)
    data = {"testsRun": result.testsRun, "discovery": discovery, "execution": execution,
            "output": output.getvalue()}
    for field in RESULT_LISTS:
        values = getattr(result, field)
        if field in ("test_times", "group_times", "work_times"):
            data[field] = values
        elif field == "unexpectedSuccesses":
            data[field] = [str(test) for test in values]
        else:
            data[field] = [(str(test), detail) for test, detail in values]
    return data


def run_parallel(names, quiet, jobs):
    """Use fresh interpreters so workers cannot share patches or SDL state."""
    result = TimingResult(io.StringIO(), False, 0)
    started = time.perf_counter()
    assignments = balance_work(work_items(load_suite(names)), jobs, read_work_times())
    discovery_seconds = time.perf_counter() - started
    execution_seconds = 0.0
    # Spawn isolates native libraries. A process must not execute two shards,
    # even when one shard finishes before all processes have started.
    with ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn"),
                             max_tasks_per_child=1) as pool:
        futures = {pool.submit(run_worker, names, quiet, shard, jobs, selected): shard + 1
                   for shard, selected in enumerate(assignments)}
        for future in as_completed(futures):
            number = futures[future]
            try:
                data = future.result()
            except (BrokenProcessPool, RuntimeError) as exc:
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
                        help="Worker processes; default: up to eight for full runs, one for focused runs.")
    args = parser.parse_args(argv)
    if args.durations < 0:
        parser.error("--durations must be zero or greater")
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be one or greater")
    jobs = args.jobs if args.jobs is not None else (1 if args.tests else min(8, os.cpu_count() or 1))
    started = time.perf_counter()
    if jobs == 1:
        result, discovery_seconds, execution_seconds = run_serial(args.tests, args.quiet)
    else:
        result, discovery_seconds, execution_seconds = run_parallel(args.tests, args.quiet, jobs)
    save_work_times(result.work_times)

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
