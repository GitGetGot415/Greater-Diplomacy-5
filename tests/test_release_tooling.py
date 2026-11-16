"""Check the release tooling against the repository's own files.

The rules under test, each stated where it is implemented:

  * compilation_scripts/build_manifest.py names the platforms a release
    attaches a download for. The release build workflow must build every one of
    them, or a release quietly ships without a platform.
  * The Linux build is the Windows build with two differences and no others:
    where the output goes, and the separator PyInstaller wants in --add-binary.
  * scripts/release/release_state.py refuses to tag when the three versions
    disagree, so a release cannot announce a version older than the published
    one or announce a version twice.
"""

import os
import re
import unittest
from unittest import mock

from compilation_scripts import build_manifest as manifest, build_support as support, multi_compilation
from scripts.release import release_state as state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def workflow(name):
    return read(".github", "workflows", name)


class ReleasePlatformTests(unittest.TestCase):
    def test_every_release_platform_has_a_build_script(self):
        for platform in manifest.RELEASE_PLATFORMS:
            self.assertIn(platform, multi_compilation.PLATFORM_SCRIPTS)
            script = multi_compilation.PLATFORM_SCRIPTS[platform]
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "compilation_scripts", script)),
                            f"{platform} names {script}, which does not exist")

    def test_the_build_workflow_builds_every_release_platform(self):
        """A platform a release attaches must be built by the workflow a release calls."""
        text = workflow("build.yml")
        for platform in manifest.RELEASE_PLATFORMS:
            script = multi_compilation.PLATFORM_SCRIPTS[platform]
            self.assertIn(script, text,
                          f"build.yml never runs {script}, so a release would carry no "
                          f"{platform} download")

    def test_the_release_workflow_calls_the_build_workflow(self):
        """One copy of the build steps. A release builds what a manual build builds."""
        self.assertIn("workflow_call", workflow("build.yml"))
        self.assertIn("./.github/workflows/build.yml", workflow("release.yml"))

    def test_the_release_workflow_runs_the_whole_suite(self):
        self.assertIn("run_tests.py", workflow("release.yml"))

    def test_the_gates_read_the_release_state_module(self):
        """The workflows and the wizard answer from one module, not from copied rules."""
        for name in ("release.yml",):
            self.assertIn("scripts/release/release_state.py", workflow(name))


class LinuxBuildTests(unittest.TestCase):
    def test_linux_arguments_differ_from_windows_only_where_they_must(self):
        windows = manifest.windows_arguments()
        linux = manifest.linux_arguments()
        self.assertEqual(len(windows), len(linux))
        differences = [(left, right) for left, right in zip(windows, linux) if left != right]
        expected = [(manifest.WINDOWS_DIST_DIR, manifest.LINUX_DIST_DIR)]
        expected += [(binary + ";.", binary + ":.") for binary in manifest.NATIVE_BINARIES]
        self.assertEqual(differences, expected)

    def test_linux_ships_the_same_inventory_as_windows(self):
        linux = [str(relative) for _, relative in support.distributed_files(ROOT, "linux")]
        windows = [str(relative) for _, relative in support.distributed_files(ROOT, "windows")]
        self.assertEqual(linux, windows)

    def test_the_linux_archive_is_not_a_zip(self):
        """ZIP has no permission bits every extractor restores, so the game would not start."""
        text = read("compilation_scripts", "linux_compilation.py")
        self.assertIn('"gztar"', text)
        self.assertNotIn("'zip'", text)
        self.assertNotIn('"zip"', text)

    def test_the_linux_audio_library_is_a_distributed_binary(self):
        """soloud.py selects this file on Linux, so the build has to carry the file."""
        self.assertIn("lin64-libsoloud.so", manifest.NATIVE_BINARIES)
        self.assertIn("lin64-libsoloud.so:.", manifest.linux_arguments())


class ReleaseStateTests(unittest.TestCase):
    def test_version_number_reads_the_games_own_format(self):
        self.assertEqual(state.version_number("v50"), 50)
        self.assertIsNone(state.version_number("50"))
        self.assertIsNone(state.version_number("v50b"))
        self.assertIsNone(state.version_number(""))

    def test_the_built_version_is_the_constant_the_game_shows(self):
        """Read as text, because data/constants.py imports game modules."""
        text = read("data", "constants.py")
        expected = re.search(r'^GAME_VERSION\s*=\s*"([^"]+)"', text, re.M).group(1)
        self.assertEqual(state.built_version(), expected)

    def reasons(self, built, published, tagged=False, changes=(), branch="main"):
        with mock.patch.object(state, "built_version", return_value=built), \
                mock.patch.object(state, "published_version", return_value=published), \
                mock.patch.object(state, "tag_exists", return_value=tagged), \
                mock.patch.object(state, "working_tree_changes", return_value=list(changes)), \
                mock.patch.object(state, "current_branch", return_value=branch):
            return state.problems()

    def test_a_clean_release_has_nothing_to_settle(self):
        self.assertEqual(self.reasons("v51", "v50"), [])

    def test_announcing_the_published_version_again_is_refused(self):
        self.assertTrue(any("already" in reason for reason in self.reasons("v50", "v50")))

    def test_announcing_an_older_version_is_refused(self):
        self.assertTrue(any("older" in reason for reason in self.reasons("v49", "v50")))

    def test_an_unparsable_version_is_refused(self):
        self.assertTrue(any("data/constants.py" in reason
                            for reason in self.reasons("fifty", "v50")))

    def test_an_existing_tag_is_refused(self):
        self.assertTrue(any("exists already" in reason
                            for reason in self.reasons("v51", "v50", tagged=True)))

    def test_uncommitted_work_and_the_wrong_branch_are_refused(self):
        reasons = self.reasons("v51", "v50", changes=[" M main.py"], branch="feature")
        self.assertTrue(any("uncommitted" in reason for reason in reasons))
        self.assertTrue(any("not main" in reason for reason in reasons))

    def test_the_repository_state_is_readable(self):
        """Every label the wizard prints comes back with a value."""
        for label, value in state.summary():
            self.assertTrue(label)
            self.assertTrue(value)


if __name__ == "__main__":
    unittest.main()
