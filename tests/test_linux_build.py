"""Check the Linux build against the Windows build it is based on.

The Linux build is the Windows build with two differences and no others:
where the output goes, and the separator PyInstaller wants in --add-binary.
"""

import os
import unittest

from compilation_scripts import build_manifest as manifest, build_support as support

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


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


if __name__ == "__main__":
    unittest.main()
