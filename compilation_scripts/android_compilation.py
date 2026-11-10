"""Build the current web distribution into a locally signed Android debug APK."""

from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if __name__ == "__main__" and str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compilation_scripts import android_tools, build_manifest as manifest
from compilation_scripts.build_support import stage_android_project


def build_apk(skip_web_build=False):
    sdk = android_tools.android_sdk()
    java = android_tools.java_home()
    for required in ("platforms/android-37.0/android.jar", "build-tools/36.0.0"):
        if not (sdk / required).exists():
            raise FileNotFoundError(
                f"Missing {sdk / required}. In Android Studio's SDK Manager, install "
                "Android SDK Platform 37.0 and Android SDK Build-Tools 36.0.0.")
    environment = android_tools.tool_environment(sdk)
    environment["JAVA_HOME"] = str(java)
    environment["PATH"] = str(java / "bin") + os.pathsep + environment.get("PATH", "")
    environment.setdefault("GRADLE_USER_HOME", str(REPO_ROOT / "build/android/gradle-home"))
    if not skip_web_build:
        subprocess.run([sys.executable, str(REPO_ROOT / "compilation_scripts/html_compilation.py")],
                       cwd=REPO_ROOT, check=True)
    stage_android_project(REPO_ROOT, REPO_ROOT / manifest.WEB_CONTENT_DIR, android_tools.PROJECT_DIR)

    # Defer game/content imports so --help and missing-tool errors work without pygame.
    from data.constants import GAME_VERSION

    wrapper = android_tools.PROJECT_DIR / ("gradlew.bat" if os.name == "nt" else "gradlew")
    print(f"Building Android APK with {java}...", flush=True)
    subprocess.run([str(wrapper), "--no-daemon", "--console=plain", ":app:assembleDebug",
                    f"-Pgd5ApplicationId={manifest.ANDROID_APPLICATION_ID}",
                    f"-Pgd5VersionName={GAME_VERSION}"],
                   cwd=android_tools.PROJECT_DIR, env=environment, check=True)
    source = android_tools.PROJECT_DIR / "app/build/outputs/apk/debug/app-debug.apk"
    destination = REPO_ROOT / manifest.ANDROID_APK
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after successful compilation; a failed build leaves the previous APK intact.
    temporary = destination.with_suffix(".apk.tmp")
    shutil.copy2(source, temporary)
    temporary.replace(destination)
    print(f"APK ready: {destination}", flush=True)
    print("This debug APK needs internet access for Pygbag's runtime downloads.", flush=True)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-web-build", action="store_true",
                        help="Reuse the existing web output when changing only the Android wrapper.")
    args = parser.parse_args(argv)
    try:
        build_apk(args.skip_web_build)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Android build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
