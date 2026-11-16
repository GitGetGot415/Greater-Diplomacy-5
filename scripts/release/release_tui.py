"""Walk through a release in order: check, tag, build, then announce.

Usage:
    python scripts/release/release_tui.py
    python scripts/release/release_tui.py --dry-run

A text wizard. Every step prints what the step will run before running anything,
and nothing runs without a typed answer. --dry-run prints the commands and runs
none of them.

WHY A WIZARD AND NOT A SCRIPT THAT DOES EVERYTHING

A release has one ordering rule, stated in release_state.py: version.txt is the
announcement every running copy of the game reads, so version.txt is written
last, after a tag exists and after the build for that tag has finished and been
attached to the release. The steps in between are a push and a wait on a build
that takes several minutes and can fail.

One command that did all of it would have to either stop in the middle, leaving
the person who ran the command to work out which half happened, or wait on the
build and announce whatever came out of the build. The wizard shows which steps
are done and which step is next, so a release interrupted at any point can be
resumed by running the wizard again, and the state it prints comes from Git and
from the repository files rather than from anything remembered between runs.

NO CURSES, NO NEW DEPENDENCY

The screen is printed text and the input is a line at a time. Python's curses
module is not available on Windows, the Windows build is the most common one,
and the game's requirements.txt gains nothing from a terminal library used by
one script at release time.
"""

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.release import release_state as state

RULE = "-" * 72
REMOTE = "origin"
RUNS_URL = "https://github.com/GitGetGot415/Greater-Diplomacy-5/actions"


def run(command, dry_run):
    """Print one command and run the command unless this is a dry run."""
    print(f"    $ {' '.join(command)}")
    if dry_run:
        return True
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"    FAILED with exit code {result.returncode}")
        return False
    return True


def ask(question, default=False):
    """Ask one yes or no question. An empty answer takes the default."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except EOFError:
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def have_github_cli():
    return shutil.which("gh") is not None


def release_assets(version):
    """Return the asset names attached to the release for one version.

    Return None when the GitHub CLI is missing or cannot answer, which is not
    the same answer as an empty list: an empty list means the release exists
    and carries no files.
    """
    if not have_github_cli():
        return None
    result = subprocess.run(
        ["gh", "release", "view", version, "--json", "assets",
         "--jq", ".assets[].name"],
        cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.split() if line]


def step_check(version, dry_run):
    problems = state.problems()
    if not problems:
        print("  Every check passes.")
        return True
    print(f"  {len(problems)} thing(s) to settle first:")
    for problem in problems:
        print(f"    - {problem}")
    return False


def step_tag(version, dry_run):
    notes = state.release_notes()
    print(f"  Tag {version} at the current commit, with {len(notes)} commit(s) in the message.")
    for line in notes[:10]:
        print(f"    {line}")
    if len(notes) > 10:
        print(f"    ... and {len(notes) - 10} more")
    if not ask(f"  Create the tag {version}?"):
        return False
    message = f"{version}\n\n" + "\n".join(notes)
    return run(["git", "tag", "-a", version, "-m", message], dry_run)


def step_push_tag(version, dry_run):
    print(f"  Push {version} to {REMOTE}. Pushing the tag starts the release build:")
    print("  the test suite, then a real Windows, macOS, Linux and web build, then a")
    print("  DRAFT release with those files attached. Nothing is public yet.")
    if not ask(f"  Push the tag {version} to {REMOTE}?"):
        return False
    return run(["git", "push", REMOTE, version], dry_run)


def step_build(version, dry_run):
    assets = release_assets(version)
    if assets is None:
        print("  The GitHub CLI cannot answer, so the build cannot be confirmed from here.")
        print(f"  Open {RUNS_URL} and check the run for {version}.")
        return ask(f"  Has the build for {version} finished, with files attached to the release?")
    if not assets:
        print(f"  A release for {version} exists and carries no files yet.")
        print(f"  Watch the run at {RUNS_URL}.")
        return False
    print(f"  {len(assets)} file(s) attached to the release for {version}:")
    for name in assets:
        print(f"    {name}")
    return True


def step_announce(version, dry_run):
    print(f"  Write {version} into version.txt, commit, and push to {REMOTE} main.")
    print("  Every running copy of the game downloads version.txt and compares the")
    print("  contents with its own version, so from the push onwards every player on")
    print("  an older version is told an update exists. The files they will look for")
    print("  are the ones listed above.")
    if not ask("  Announce the release?"):
        return False
    if not dry_run:
        with open(state.VERSION_FILE, "w", encoding="utf-8") as handle:
            handle.write(version)
        print(f"    wrote {version} to version.txt")
    else:
        print(f"    (dry run) would write {version} to version.txt")
    return (run(["git", "add", "version.txt"], dry_run)
            and run(["git", "commit", "-m", f"{version} released"], dry_run)
            and run(["git", "push", REMOTE, "HEAD:main"], dry_run))


# Each step is a name, the function that performs the step, and whether the step
# is already done. "Done" is read from Git and the repository files every time
# the wizard draws, so the wizard never has to be told where a release got to.
STEPS = (
    ("Checks", step_check, lambda version: not state.problems()),
    ("Tag", step_tag, lambda version: state.tag_exists(version)),
    ("Push the tag", step_push_tag, lambda version: state.remote_tag_exists(version) is True),
    ("Build and attach", step_build, lambda version: bool(release_assets(version))),
    ("Announce", step_announce,
     lambda version: state.version_number(state.published_version()) == state.version_number(version)),
)


def draw(version):
    """Print the state and the checklist. Return the index of the first unfinished step."""
    print()
    print(RULE)
    print(f"  Greater Diplomacy 5 release  {version}")
    print(RULE)
    width = max(len(label) for label, _ in state.summary())
    for label, value in state.summary():
        print(f"  {label.ljust(width)}  {value}")
    print()
    next_step = None
    for index, (name, _, done) in enumerate(STEPS):
        # Stop asking once the first unfinished step is found. Two of these
        # questions reach the network, and a step after an unfinished one
        # cannot be done anyway.
        if next_step is not None:
            mark = ""
        elif done(version):
            mark = "done"
        else:
            next_step, mark = index, "next"
        print(f"  {index + 1}. [{mark.center(4)}] {name}")
    print(RULE)
    return next_step


def main():
    parser = argparse.ArgumentParser(description="Walk through a release in order.")
    parser.add_argument("--dry-run", action="store_true",
                        help="print every command and run none of them")
    arguments = parser.parse_args()

    version = state.built_version()
    while True:
        next_step = draw(version)
        if next_step is None:
            print(f"  {version} is released and announced. Raise GAME_VERSION in")
            print("  data/constants.py when work on the next version starts.")
            return 0
        name, action, _ = STEPS[next_step]
        print(f"\nStep {next_step + 1}: {name}")
        if not action(version, arguments.dry_run):
            print("\nStopped. Run this wizard again to carry on from here.")
            return 1


if __name__ == "__main__":
    sys.exit(main())
