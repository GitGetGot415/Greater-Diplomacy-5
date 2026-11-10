"""Check Android staging and device targeting without requiring an SDK or emulator."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from compilation_scripts import build_manifest as manifest, build_support
from compilation_scripts import android_tools, test_android_build as launcher


ROOT = Path(__file__).resolve().parent.parent


class AndroidPackagingTests(unittest.TestCase):
    def test_staging_refreshes_web_assets_and_retains_incremental_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in manifest.ANDROID_PROJECT_FILES:
                target = root / manifest.ANDROID_PROJECT_DIR / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / manifest.ANDROID_PROJECT_DIR / name).read_bytes())
            icon = root / manifest.ANDROID_ICON
            icon.parent.mkdir(parents=True)
            icon.write_bytes((ROOT / manifest.ANDROID_ICON).read_bytes())
            web = root / "browser-output"
            web.mkdir()
            (web / "index.html").write_text("current game: game.tar.gz")
            (web / "game.tar.gz").write_bytes(b"game archive")
            (web / "game.apk").write_bytes(b"redundant web ZIP archive")
            destination = root / "wrapper-output"
            build_support.stage_android_project(root, web, destination)
            assets = destination / "app/src/main/assets/www"
            (assets / "removed-asset.dat").write_bytes(b"old")
            (assets / "game.apk").write_bytes(b"left over from an older Android build")
            (destination / "compile-cache.dat").write_bytes(b"keep")
            (web / "index.html").write_text("updated game: game.tar.gz")
            build_support.stage_android_project(root, web, destination)
            self.assertEqual((assets / "index.html").read_text(), "updated game: game.tar.gz.bin")
            self.assertEqual((assets / "game.tar.gz.bin").read_bytes(), b"game archive")
            self.assertEqual((web / "index.html").read_text(), "updated game: game.tar.gz")
            self.assertEqual((web / "game.tar.gz").read_bytes(), b"game archive")
            self.assertFalse((assets / "game.apk").exists())
            self.assertEqual((web / "game.apk").read_bytes(), b"redundant web ZIP archive")
            self.assertFalse((assets / "removed-asset.dat").exists())
            self.assertEqual((destination / "compile-cache.dat").read_bytes(), b"keep")
            self.assertTrue((destination / "app/src/main/res/drawable/icon.png").is_file())

    def test_staging_rejects_output_outside_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary, "workspace")
            root.mkdir()
            with self.assertRaises(ValueError):
                build_support.stage_android_project(root, root, root.parent / "elsewhere")

    def test_sdk_environment_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = Path(temporary, "custom-sdk")
            (sdk / "platform-tools").mkdir(parents=True)
            with patch.dict("os.environ", {"ANDROID_HOME": str(sdk)}, clear=True):
                self.assertEqual(android_tools.android_sdk(), sdk.resolve())


class AndroidLauncherTests(unittest.TestCase):
    def test_multiple_devices_require_an_explicit_target(self):
        with patch.object(launcher, "connected_devices", return_value=[
                ("emulator-5554", "device"), ("phone", "device")]), \
                patch.object(android_tools, "sdk_tool", return_value="adb"), \
                patch.object(launcher.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "Several Android devices"):
                launcher.select_device(Path("sdk"), {})
            spawn.assert_not_called()
            self.assertEqual(launcher.select_device(Path("sdk"), {}, serial="phone"), ("adb", "phone"))

    def test_unauthorized_device_does_not_wait_or_install(self):
        with patch.object(launcher, "connected_devices", return_value=[("phone", "unauthorized")]), \
                patch.object(launcher.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "approve"):
                launcher.wait_for_boot("adb", {}, "phone")
            sleep.assert_not_called()

    def test_install_failure_does_not_launch_old_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            apk = Path(temporary, "game.apk")
            apk.write_bytes(b"fixture")
            with patch.object(android_tools, "android_sdk", return_value=Path("sdk")), \
                    patch.object(launcher, "select_device", return_value=("adb", "phone")), \
                    patch.object(launcher, "wait_for_boot"), \
                    patch.object(launcher, "adb_run", side_effect=subprocess.CalledProcessError(
                        1, ["adb", "install"], stderr="INSTALL_FAILED_UPDATE_INCOMPATIBLE")) as run:
                self.assertEqual(launcher.main(["--apk", str(apk), "--no-logs"]), 1)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[2:5], ("-s", "phone", "install"))

    def test_missing_apk_does_not_start_an_emulator(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(launcher, "select_device") as select:
            self.assertEqual(launcher.main(["--apk", str(Path(temporary, "missing.apk"))]), 1)
            select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
