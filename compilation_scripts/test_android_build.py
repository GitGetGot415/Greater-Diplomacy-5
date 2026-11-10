"""Install and launch GD5's APK on an Android emulator or connected device."""

from pathlib import Path
import argparse
import os
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parent.parent
if __name__ == "__main__" and str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compilation_scripts import android_tools, build_manifest as manifest
from compilation_scripts.android_compilation import build_apk


BOOT_TIMEOUT_SECONDS = 240


def adb_run(adb, environment, *arguments, timeout=30):
    return subprocess.run([adb, *arguments], env=environment, check=True,
                          capture_output=True, text=True, timeout=timeout).stdout.strip()


def connected_devices(adb, environment):
    output = adb_run(adb, environment, "devices")
    return [tuple(line.split()[:2]) for line in output.splitlines()
            if line.strip() and not line.startswith(("List of devices", "*"))]


def avd_serial(adb, environment, name):
    for serial, state in connected_devices(adb, environment):
        if serial.startswith("emulator-") and state == "device":
            current = adb_run(adb, environment, "-s", serial, "emu", "avd", "name")
            if current.splitlines()[0] == name:
                return serial
    return None


def select_device(sdk, environment, serial=None, avd=None):
    adb = android_tools.sdk_tool(sdk, "platform-tools", "adb")
    devices = connected_devices(adb, environment)
    if serial:
        if not any(device == serial for device, _ in devices):
            raise ValueError(f"Android device {serial} is not connected. Run adb devices to list devices.")
        return adb, serial
    if avd:
        running = avd_serial(adb, environment, avd)
        if running:
            return adb, running
    elif len(devices) == 1:
        return adb, devices[0][0]
    elif len(devices) > 1:
        raise ValueError("Several Android devices are connected. Choose one with --serial SERIAL or --avd NAME.")

    emulator = android_tools.sdk_tool(sdk, "emulator", "emulator")
    names = subprocess.run([emulator, "-list-avds"], env=environment, check=True,
                           capture_output=True, text=True, timeout=30).stdout.splitlines()
    names = [name.strip() for name in names if name.strip()]
    if avd and avd not in names:
        raise ValueError(f"Unknown virtual device {avd}. Available devices: {', '.join(names) or 'none'}.")
    if not avd:
        if not names:
            raise ValueError("No virtual device found. Create a phone or tablet in Android Studio's Device Manager.")
        if len(names) != 1:
            raise ValueError("Choose a virtual device with --avd NAME. Available devices: " + ", ".join(names))
        avd = names[0]
    logs = REPO_ROOT / "build/android/logs"
    logs.mkdir(parents=True, exist_ok=True)
    print(f"Starting Android virtual device {avd}...", flush=True)
    with (logs / "emulator.log").open("w", encoding="utf-8") as output:
        process = subprocess.Popen([emulator, "-avd", avd], env=environment,
                                   stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        serial = avd_serial(adb, environment, avd)
        if serial:
            return adb, serial
        if process.poll() is not None:
            raise RuntimeError(f"Emulator exited with code {process.returncode}. See {logs / 'emulator.log'}.")
        time.sleep(1)
    raise TimeoutError(f"Emulator did not connect. See {logs / 'emulator.log'}.")


def wait_for_boot(adb, environment, serial):
    print(f"Waiting for Android on {serial}...", flush=True)
    deadline = time.monotonic() + BOOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        devices = dict(connected_devices(adb, environment))
        state = devices.get(serial)
        if state == "unauthorized":
            raise RuntimeError("Unlock the Android device and approve this computer's USB debugging connection.")
        if state == "device":
            boot = adb_run(adb, environment, "-s", serial, "shell", "getprop", "sys.boot_completed")
            if boot == "1":
                return
        time.sleep(1)
    raise TimeoutError(f"Android on {serial} did not finish booting within {BOOT_TIMEOUT_SECONDS} seconds.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Rebuild the web game and APK before installing.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--avd", help="Android Studio virtual-device name.")
    selection.add_argument("--serial", help="Connected device serial from adb devices.")
    parser.add_argument("--apk", type=Path, help="Install a specific APK instead of the default output.")
    parser.add_argument("--no-logs", action="store_true", help="Return after launch instead of collecting logs.")
    args = parser.parse_args(argv)
    if args.build and args.apk:
        parser.error("--build and --apk cannot be combined.")
    try:
        apk = build_apk() if args.build else (args.apk or REPO_ROOT / manifest.ANDROID_APK).resolve()
        if not apk.is_file():
            raise FileNotFoundError(f"No APK at {apk}. Run android_compilation.py or use --build.")
        sdk = android_tools.android_sdk()
        environment = android_tools.tool_environment(sdk)
        adb, serial = select_device(sdk, environment, args.serial, args.avd)
        wait_for_boot(adb, environment, serial)
        print(f"Installing {apk.name}; existing app data will be preserved...", flush=True)
        print(adb_run(adb, environment, "-s", serial, "install", "-r", "-t", str(apk), timeout=180))
        output = adb_run(adb, environment, "-s", serial, "shell", "am", "start", "-W", "-S",
                         "-n", manifest.ANDROID_APPLICATION_ID + "/.MainActivity", timeout=60)
        if "Error:" in output or "Status: ok" not in output:
            raise RuntimeError(f"Android could not launch GD5: {output}")
        print("GD5 launched. Internet access is required for runtime downloads.", flush=True)
        if not args.no_logs:
            log = REPO_ROOT / "build/android/logs/game.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            print(f"Capturing GD5/WebView logs to {log}. Press Ctrl+C to stop logging; the app stays open.",
                  flush=True)
            with log.open("w", encoding="utf-8") as output:
                process = subprocess.Popen([adb, "-s", serial, "logcat", "-T", "1",
                                            "GD5WebView:I", "chromium:E", "AndroidRuntime:E", "*:S"],
                                           env=environment, stdout=output, stderr=subprocess.STDOUT)
                try:
                    code = process.wait()
                    if code:
                        raise RuntimeError(f"Android log capture stopped with code {code}. See {log}.")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Android test failed: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout or "", error.stderr or "", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
