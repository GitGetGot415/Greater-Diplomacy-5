"""Build several platforms in one run by calling each platform's build script in turn."""

from pathlib import Path
import subprocess
import sys


SCRIPTS_DIR = Path(__file__).resolve().parent

# Platforms built by this script, in order. Add or remove names from PLATFORM_SCRIPTS.
# Keep "web" before "android": Android then packages that web build instead of rebuilding it.
MULTI_BUILD_PLATFORMS = ["web", "android", "windows"]

# Every platform this script can build, and the build script that makes it.
# macOS builds only on a Mac because its script zips with ditto, and Linux
# builds only on Linux because PyInstaller does not cross-compile. Neither is
# in MULTI_BUILD_PLATFORMS above for that reason: name either one there when
# running this script on that operating system.
PLATFORM_SCRIPTS = {
    "windows": "windows_compilation.py",
    "linux": "linux_compilation.py",
    "web": "html_compilation.py",
    "android": "android_compilation.py",
    "macos": "macos_compilation.py",
}


def build_command(platform, built):
    command = [sys.executable, str(SCRIPTS_DIR / PLATFORM_SCRIPTS[platform])]
    if platform == "android" and "web" in built:
        command.append("--skip-web-build")
    return command


def main():
    unknown = [name for name in MULTI_BUILD_PLATFORMS if name not in PLATFORM_SCRIPTS]
    if unknown:
        print(f"Unknown platforms in MULTI_BUILD_PLATFORMS: {', '.join(unknown)}. "
              f"Choose from: {', '.join(PLATFORM_SCRIPTS)}.", file=sys.stderr)
        return 1
    built, failed = [], []
    for platform in MULTI_BUILD_PLATFORMS:
        print(f"\n===== Building {platform} =====", flush=True)
        # Each build runs in its own process; the scripts change directory and exit on failure.
        result = subprocess.run(build_command(platform, built), cwd=SCRIPTS_DIR.parent)
        (built if result.returncode == 0 else failed).append(platform)
    print("\n===== Multi-build summary =====")
    print(f"Built: {', '.join(built) or 'none'}")
    if failed:
        print(f"Failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
