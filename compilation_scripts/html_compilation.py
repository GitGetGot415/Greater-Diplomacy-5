import os
import subprocess
import shutil
import sys

# This script lives in compilation_scripts/ but every relative path below (STAGE_DIR,
# DATA_DIRS, etc.) is meant to resolve against the actual project root, so hop up one
# level and put the root on sys.path before importing first-party packages.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__" and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import data.constants as c
from compilation_scripts import build_manifest as manifest
from compilation_scripts.build_support import export_web_build, include_asset, is_git_ignored, stage_release, verified_build_path

# Build-time only tools (not needed to run the game itself, so not in requirements.txt,
# same convention as PyInstaller/py2app for the other two platform builds):
#   pip install pygbag imageio-ffmpeg

STAGE_DIR = "web_stage"

# Source is staged in the browser virtual filesystem. Native SoLoud stays desktop-only.
SOURCE_FILES = manifest.WEB_SOURCE_FILES
SOURCE_PACKAGES = manifest.SOURCE_PACKAGES
DATA_DIRS = manifest.DATA_DIRS

# Retain the existing build-filter import paths.
_is_git_ignored = is_git_ignored


def _ignore_web_asset(path):
    return not include_asset(path, "web")


def transcode_web_audio(stage_path):
    """Convert staged MP3 music and effects to the browser mixer's OGG format."""
    sources = []
    for directory, _, filenames in os.walk(os.path.join(stage_path, "assets")):
        sources.extend(os.path.join(directory, name) for name in filenames
                       if name.lower().endswith(".mp3"))
    if not sources:
        return
    try:
        # Build-only dependency; desktop and browser runtime imports do not need it.
        import imageio_ffmpeg
    except ImportError as error:
        raise RuntimeError(
            "Web audio conversion requires imageio-ffmpeg. "
            "Install it with: python -m pip install imageio-ffmpeg"
        ) from error

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    print("Transcoding staged MP3 music and sound effects to OGG...")
    for source in sources:
        destination = os.path.splitext(source)[0] + ".ogg"
        result = subprocess.run(
            [ffmpeg_exe, "-y", "-i", source, "-c:a", "libvorbis", "-q:a", "4", destination],
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Cannot convert web audio {source}: {result.stderr.decode(errors='replace')}"
            )
        os.remove(source)


def main():
    os.chdir(REPO_ROOT)
    stage_path = verified_build_path(REPO_ROOT, STAGE_DIR)
    if os.path.exists(stage_path):
        print("Cleaning web_stage folder...")
        shutil.rmtree(stage_path)
    stage_release(REPO_ROOT, stage_path, "web")
    if not os.path.isfile(os.path.join(stage_path, "libdragoman.so")):
        raise FileNotFoundError("Web staging requires libdragoman.so")

    # 2b. Transcode MP3s to OGG for the web bundle only.
    # Browser checks confirm that this SDL_mixer build cannot decode MP3.
    # Use the OGG format recommended by https://pygame-web.github.io/wiki/pygbag/.
    # Matching BeepBox tracks are played from their JSON instead. Desktop builds
    # are untouched; only the staged copy is converted.
    transcode_web_audio(stage_path)

    print("Copying finished successfully.")

    # 3. Invoke pygbag in build-only (non-interactive) mode against the staged dir.
    # pygbag writes its output to <STAGE_DIR>/build/web/, and can zip it directly via --archive.
    icon_path = os.path.join(STAGE_DIR, "assets", "icon", "icon.png")
    # Custom index.html template: pygbag's own default.tmpl stretches the canvas to fill
    # its container (width:100%; height:100%) with no aspect-ratio lock, and its resize JS
    # derives the aspect ratio from the canvas's width/height attributes, which start out
    # hardcoded to 1x1 and only get corrected once pygame.display.set_mode() runs -- a race
    # that can bake in a square canvas. web_index.tmpl forces the real 16:9 ratio via CSS
    # with !important so it wins regardless of that race. See web_index.tmpl for detail.
    template_path = os.path.join("compilation_scripts", "web_index.tmpl")
    print("Running pygbag...")
    cmd = [
        sys.executable, "-m", "pygbag",
        "--build",
        "--archive",
        "--template", template_path,
        "--app_name", "Greater Diplomacy 5",
        # MP3s are converted above. Keep WAV effects, which this runtime decodes
        # directly; pygbag's format check would otherwise reject those files too.
        "--disable-sound-format-error",
        # Default (1) blocks the whole app behind an audio-unlock probe that pygbag's
        # own code marks buggy for non-interactive scripts (our case) -- it never
        # resolves and the game never starts. Confirmed via real browser testing.
        "--ume_block", "0",
    ]
    if os.path.exists(icon_path):
        cmd += ["--icon", icon_path]
    cmd += [STAGE_DIR]

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("pygbag build failed.")
        sys.exit(result.returncode)

    build_web_dir = os.path.join(STAGE_DIR, "build", "web")
    print(f"pygbag build finished. Output in {build_web_dir}/")

    # 4. Export only this platform's distribution, retaining the versioned ZIP name.
    src_zip = os.path.join(STAGE_DIR, "build", "web.zip")
    content_dir, dst_zip = export_web_build(REPO_ROOT, build_web_dir, src_zip, f"GD5 WEB {c.GAME_VERSION}.zip")
    print(f"Zip ready at {dst_zip}. Upload it directly to itch.io, or serve {content_dir}/ from any static host.")


if __name__ == "__main__":
    main()
