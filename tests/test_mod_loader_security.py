"""Regression tests for the mod sandbox.

Each case builds a throwaway game folder, drops in one mod that tries a
documented bypass, and checks whether the mod managed to touch the disk.
The side effect -- did a file appear? -- is the assertion, rather than
which exception came out, because that is the property the sandbox is
actually for.

Every case runs in its OWN interpreter. sys.addaudithook cannot be
removed once installed, so two cases in one process would contaminate
each other.

    python3 tests/test_mod_loader_security.py
    python3 tests/test_mod_loader_security.py --loader /path/to/other.py

--loader points the suite at a different mod_loader.py. Run it against
the pre-fix loader and the bypass cases are expected to FAIL: a suite
that passes against the vulnerable file is not testing anything.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOADER = os.path.join(os.path.dirname(HERE), "mod_loader.py")

# A game function that touches the filesystem, for the hop-through case.
IO_HELPER = (
    'def read_file(path):\n'
    '    with open(path, "r", encoding="utf-8") as f:\n'
    '        return f.read()\n'
    '\n'
    'def write_file(path, text):\n'
    '    with open(path, "w", encoding="utf-8") as f:\n'
    '        f.write(text)\n'
)


def build(workdir, loader, mod_source, state):
    os.makedirs(os.path.join(workdir, "data"), exist_ok=True)
    os.makedirs(os.path.join(workdir, "mods"), exist_ok=True)
    shutil.copyfile(loader, os.path.join(workdir, "mod_loader.py"))
    for rel, text in (
        ("main.py", "BOOT = True\n"),
        ("data/queries.py", 'VALUE = "real"\n'),
        ("data/platform.py", "WINDOW = None\n"),
        ("data/io_helpers.py", IO_HELPER),
    ):
        with open(os.path.join(workdir, rel), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(workdir, "mods", "probe.py"), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(mod_source).lstrip("\n"))
    with open(os.path.join(workdir, "mods", "enabled_mods.json"), "w", encoding="utf-8") as f:
        f.write(state)


RUNNER = r'''
import sys
sys.path.insert(0, ".")
import mod_loader
mod_loader.install()
try:
    import data.queries
    print("VALUE=%s" % getattr(data.queries, "VALUE", "?"))
except Exception as e:
    print("RAISED=%s: %s" % (type(e).__name__, e))
print("DESCRIBE=%s" % (mod_loader.describe_mod("probe.py"),))
'''


def run_case(loader, mod_source, state='{"probe.py": {"enabled": true, "sandboxed": true}}', *, runner=RUNNER):
    """(touched_disk, stdout) for one mod in a fresh interpreter."""
    workdir = tempfile.mkdtemp(prefix="gd5sbx-")
    try:
        build(workdir, loader, mod_source, state)
        proc = subprocess.run([sys.executable, "-c", runner], cwd=workdir,
                              capture_output=True, text=True, timeout=60)
        out = proc.stdout + proc.stderr
        return os.path.exists(os.path.join(workdir, "TOUCHED")), out
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# Written by a mod to prove it reached the filesystem. Relative to the game
# folder, which is the cwd of the child interpreter.
TOUCH = 'open("TOUCHED", "w").close()'

CASES = []


def case(name, detail):
    def wrap(fn):
        CASES.append((name, detail, fn))
        return fn
    return wrap


@case("plain open()", "a sandboxed mod calling open() directly is blocked")
def _plain(loader):
    touched, out = run_case(loader, f'''
        #data/queries.py
        {TOUCH}
        VALUE = "modded"
    ''')
    return not touched, out


@case("marker delete", "popping the sandbox marker out of the mod's own globals does not disarm it")
def _marker(loader):
    touched, out = run_case(loader, f'''
        #data/queries.py
        globals().pop("__gd5_mod_sandbox__", None)
        {TOUCH}
        VALUE = "modded"
    ''')
    return not touched, out


@case("hop through a game function", "calling a game function that does the I/O is still blocked")
def _hop(loader):
    # The game function does the writing. A direct open() here would be
    # blocked even by the frame-1-only sandbox, so the case would pass
    # against the very design it is meant to catch.
    touched, out = run_case(loader, '''
        #data/queries.py
        import data.io_helpers
        try:
            data.io_helpers.write_file("TOUCHED", "hopped")
        except PermissionError:
            pass
        VALUE = "modded"
    ''')
    return not touched, out


@case("exec with fresh globals", "exec()ing into a brand new globals dict is still blocked")
def _exec(loader):
    touched, out = run_case(loader, '''
        #data/queries.py
        exec('open("TOUCHED", "w").close()', {})
        VALUE = "modded"
    ''')
    return not touched, out


@case("scheduled mod callback", "a timer callback retains its mod's sandbox setting after import")
def _scheduled_callback(loader):
    source = '''
        # mod: target=data/queries.py sandbox=auto
        import threading

        def write_from_timer():
            print("CALLBACK_RAN")
            try:
                open("TOUCHED", "w").close()
            except PermissionError:
                print("CALLBACK_BLOCKED")

        timer = threading.Timer(0, write_from_timer)
        VALUE = "modded"
    '''
    # Start after import returns. The callback has no top-level mod frame
    # below it, but its own frame still uses the registered module globals.
    runner = RUNNER + '\ndata.queries.timer.start()\ndata.queries.timer.join()\n'
    touched, blocked_out = run_case(loader, source, runner=runner)
    sandboxed_ok = (not touched and "VALUE=modded" in blocked_out
                    and "CALLBACK_RAN" in blocked_out and "CALLBACK_BLOCKED" in blocked_out)
    touched, allowed_out = run_case(
        loader, source, state='{"probe.py": {"enabled": true, "sandboxed": false}}', runner=runner)
    unsandboxed_ok = (touched and "VALUE=modded" in allowed_out
                      and "CALLBACK_RAN" in allowed_out and "CALLBACK_BLOCKED" not in allowed_out)
    return sandboxed_ok and unsandboxed_ok, blocked_out + allowed_out


@case("defang the blocked-event table", "reassigning mod_loader._SANDBOX_BLOCKED_EVENTS has no effect")
def _defang(loader):
    touched, out = run_case(loader, f'''
        #data/queries.py
        import mod_loader
        mod_loader._SANDBOX_BLOCKED_EVENTS = set()
        mod_loader._SANDBOX_BLOCKED_PREFIXES = ()
        {TOUCH}
        VALUE = "modded"
    ''')
    return not touched, out


@case("reserved targets", "mods targeting mod_loader / main / data.platform are refused")
def _reserved(loader):
    ok, log = True, []
    for target in ("mod_loader.py", "main.py", "data/platform.py"):
        _touched, out = run_case(loader, f'''
            #{target}
            VALUE = "modded"
        ''')
        refused = "'valid': False" in out or '"valid": false' in out.lower()
        reserved = "reserved" in out.lower()
        ok = ok and refused and reserved
        log.append(f"  {target}: refused={refused} says-reserved={reserved}")
    return ok, "\n".join(log)


@case("unsandboxed still works", "the sandbox is not blocking a mod the user allowed")
def _unsandboxed(loader):
    touched, out = run_case(loader, f'''
        #data/queries.py
        {TOUCH}
        VALUE = "modded"
    ''', state='{"probe.py": {"enabled": true, "sandboxed": false}}')
    return touched, out


@case("legacy header still loads", "a '#path' mod loads and says it is deprecated")
def _legacy(loader):
    _touched, out = run_case(loader, '''
        #data/queries.py
        VALUE = "modded"
    ''', state='{"probe.py": {"enabled": true, "sandboxed": false}}')
    return "VALUE=modded" in out and "legacy" in out.lower(), out


@case("manifest sandbox=on wins", "a mod declaring sandbox=on is sandboxed even if the user untoggled it")
def _manifest(loader):
    touched, out = run_case(loader, f'''
        # mod: target=data/queries.py sandbox=on
        {TOUCH}
        VALUE = "modded"
    ''', state='{"probe.py": {"enabled": true, "sandboxed": false}}')
    # "not touched" alone is not enough: a loader that cannot parse a
    # manifest header refuses the mod outright and touches nothing either.
    # The mod has to have been accepted AND then held to sandbox=on.
    # A loader that cannot parse a manifest header refuses the mod outright
    # and touches nothing either, so "not touched" alone proves nothing. The
    # header has to have been UNDERSTOOD -- the target resolved to a real
    # module -- and the mod then held to sandbox=on despite the user toggle.
    # (valid is False afterwards: a mod blocked mid-load is recorded as
    # failed, which is correct, if an odd thing for the Mods screen to show.)
    understood = "'module': 'data.queries'" in out
    return (not touched) and understood, out


class ModLoaderSecurityTests(unittest.TestCase):
    """Run each sandbox case in its own interpreter during normal discovery."""

    def test_sandbox_cases(self):
        for name, _detail, check in CASES:
            with self.subTest(case=name):
                ok, output = check(DEFAULT_LOADER)
                self.assertTrue(ok, output)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loader", default=DEFAULT_LOADER)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    loader = os.path.abspath(args.loader)
    if not os.path.isfile(loader):
        print(f"no mod_loader at {loader}")
        return 2
    print(f"mod_loader under test: {loader}\n")

    failed = 0
    for name, detail, fn in CASES:
        ok, out = fn(loader)
        print(f"[{'PASS' if ok else 'FAIL'}] {name} -- {detail}")
        if not ok:
            failed += 1
        if args.verbose or not ok:
            for line in out.strip().splitlines():
                print(f"       {line[:150]}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
