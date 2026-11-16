"""Answer where a release stands: the built version, the published version, and the tag.

Usage:
    python scripts/release/release_state.py
    python scripts/release/release_state.py --notes

This module holds no interactive code and runs no release step. The wizard in
release_tui.py reads the answers from here, and tests/test_release_state.py
checks the answers against the repository's own files, so the wizard and the
tests cannot disagree about what a release is.

THREE VERSIONS, AND THE ORDER THEY MOVE IN

  GAME_VERSION in data/constants.py   What a build of the current source calls itself.
  version.txt                         What the public repository says the newest release is.
  A Git tag                           Which commit a release was built from.

Every running copy of the game downloads version.txt, compares the contents with
its own GAME_VERSION, and tells the player "Outdated!" when version.txt is
higher. version.txt is therefore the announcement, not a record: the moment
version.txt changes on the public repository, every player is told an update
exists. If no build has been produced and attached to a release by then, every
player is told to download something that is not there.

So version.txt is written LAST, after a tag exists and after the build for that
tag has finished and been attached. That order is the only thing these scripts
enforce. Nothing here can publish, and nothing here edits version.txt.

A repository with no tags at all still has a history of releases, because every
release changed version.txt. The commit that last changed version.txt is where
the previous release was announced, and release_notes() falls back to that commit
when the tag for the previous version does not exist.
"""

import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONSTANTS_PATH = os.path.join(ROOT, "data", "constants.py")
VERSION_FILE = os.path.join(ROOT, "version.txt")
VERSION_PATTERN = re.compile(r"^v(\d+)$")


def git(*arguments, check=True):
    """Run one Git command in the repository and return the stripped output."""
    result = subprocess.run(["git"] + list(arguments), cwd=ROOT,
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def version_number(version):
    """Return the integer in a version such as "v50", or None when the text is not one."""
    match = VERSION_PATTERN.match((version or "").strip())
    return int(match.group(1)) if match else None


def built_version():
    """Return GAME_VERSION from data/constants.py.

    Read as text rather than imported: data/constants.py pulls in game modules,
    which initialize pygame, and a release check must run on a machine with no
    display and no audio device.
    """
    with open(CONSTANTS_PATH, encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r'^GAME_VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise RuntimeError(f"No GAME_VERSION assignment in {CONSTANTS_PATH}")
    return match.group(1)


def published_version():
    """Return the contents of version.txt, which is what players compare against."""
    with open(VERSION_FILE, encoding="utf-8") as handle:
        return handle.read().strip()


def tag_exists(version):
    return bool(git("tag", "--list", version))


def remote_tag_exists(version, remote="origin"):
    """Report whether the remote already has the tag. Return None when the remote is unreachable."""
    result = subprocess.run(["git", "ls-remote", "--tags", remote, f"refs/tags/{version}"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def previous_release_ref():
    """Return the commit or tag the previous release was announced at, or None.

    The tag for the published version is preferred. A repository that tagged no
    releases still changed version.txt for each one, so the commit that last
    changed version.txt is the fallback.
    """
    published = published_version()
    if version_number(published) is not None and tag_exists(published):
        return published
    commit = git("log", "-1", "--format=%H", "--", "version.txt")
    return commit or None


def release_notes(ref=None):
    """Return one line per commit since the previous release, newest first."""
    ref = ref or previous_release_ref()
    if not ref:
        return []
    lines = git("log", "--no-merges", "--format=%h %s", f"{ref}..HEAD")
    return [line for line in lines.splitlines() if line]


def working_tree_changes():
    """Return the porcelain lines for a dirty tree, which is empty when the tree is clean."""
    return [line for line in git("status", "--porcelain").splitlines() if line]


def current_branch():
    return git("rev-parse", "--abbrev-ref", "HEAD")


def problems():
    """Return the reasons the repository is not ready to tag a release.

    Each reason is a sentence naming the file or the Git state to correct. An
    empty list means a tag can be created, not that a release can be published:
    publishing also needs the build for the tag to have finished.
    """
    found = []
    built = built_version()
    published = published_version()
    built_number, published_number = version_number(built), version_number(published)

    if built_number is None:
        found.append(f'GAME_VERSION in data/constants.py is "{built}", which is not a version '
                     f'of the form v1. The game compares version numbers, and a version it '
                     f'cannot parse reads as an error in every player\'s main menu.')
    if published_number is None:
        found.append(f'version.txt holds "{published}", which is not a version of the form v1.')
    if built_number is not None and published_number is not None:
        if built_number == published_number:
            found.append(f"version.txt already says {published}, so {built} is published "
                         f"already. Raise GAME_VERSION in data/constants.py before releasing again.")
        elif built_number < published_number:
            found.append(f"version.txt says {published} but this source builds {built}, which "
                         f"is older. Every player would be told to downgrade.")

    if tag_exists(built):
        found.append(f"The tag {built} exists already. Delete the tag, or raise GAME_VERSION.")

    changes = working_tree_changes()
    if changes:
        found.append(f"{len(changes)} uncommitted change(s) in the working tree. A tag names a "
                     f"commit, so anything uncommitted is not in the release.")

    branch = current_branch()
    if branch != "main":
        found.append(f"The current branch is {branch}, not main.")

    return found


def summary():
    """Return the state as label and value pairs, for printing."""
    built = built_version()
    return [
        ("This source builds", built),
        ("version.txt announces", published_version()),
        ("Local tag for this version", "yes" if tag_exists(built) else "no"),
        ("Current branch", current_branch()),
        ("Uncommitted changes", str(len(working_tree_changes()))),
        ("Commits since the last release", str(len(release_notes()))),
    ]


def main():
    parser = argparse.ArgumentParser(description="Print where a release stands.")
    parser.add_argument("--notes", action="store_true",
                        help="list the commits since the previous release")
    arguments = parser.parse_args()

    width = max(len(label) for label, _ in summary())
    for label, value in summary():
        print(f"{label.ljust(width)}  {value}")

    if arguments.notes:
        print()
        notes = release_notes()
        print(f"{len(notes)} commit(s) since {previous_release_ref() or 'the first commit'}:")
        for line in notes:
            print(f"  {line}")

    found = problems()
    print()
    if not found:
        print("Ready to tag.")
        return 0
    print(f"{len(found)} thing(s) to settle before tagging:")
    for problem in found:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
