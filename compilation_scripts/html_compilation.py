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
from compilation_scripts.build_support import include_asset, is_git_ignored, stage_release, verified_build_path

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


def main():
    os.chdir(REPO_ROOT)
    stage_path = verified_build_path(REPO_ROOT, STAGE_DIR)
    if os.path.exists(stage_path):
        print("Cleaning web_stage folder...")
        shutil.rmtree(stage_path)
    stage_release(REPO_ROOT, stage_path, "web")
    if not os.path.isfile(os.path.join(stage_path, "libdragoman.so")):
        raise FileNotFoundError("Web staging requires libdragoman.so")

    # 2b. Transcode remaining soundtrack MP3s to OGG for the web bundle only.
    # Confirmed via real browser testing: this pygame-ce/SDL_mixer WASM build cannot
    # decode MP3 at all ("Unrecognized audio format"), matching pygame-web's own docs
    # (https://pygame-web.github.io/wiki/pygbag/ -- only WAV/OGG are reliably
    # supported). Matching BeepBox tracks are played from their JSON instead. Desktop
    # builds are untouched; only the staged copy is converted.
    music_dir = os.path.join(STAGE_DIR, "assets", "music")
    if os.path.exists(music_dir):
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            print("Warning: imageio-ffmpeg not installed (pip install imageio-ffmpeg) -- "
                  "skipping MP3->OGG transcode. Non-BeepBox MP3 music will not play "
                  "in the web build.")
            ffmpeg_exe = None

        if ffmpeg_exe:
            print("Transcoding non-BeepBox soundtrack MP3s to OGG for the web build...")
            for dirpath, _, filenames in os.walk(music_dir):
                for fname in filenames:
                    if not fname.lower().endswith(".mp3"):
                        continue
                    src_path = os.path.join(dirpath, fname)
                    dst_path = os.path.splitext(src_path)[0] + ".ogg"
                    result = subprocess.run(
                        [ffmpeg_exe, "-y", "-i", src_path, "-c:a", "libvorbis", "-q:a", "4", dst_path],
                        capture_output=True,
                    )
                    if result.returncode != 0:
                        print(f"  Failed to transcode {src_path}: {result.stderr.decode(errors='replace')}")
                        continue
                    os.remove(src_path)

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
        # Remaining soundtrack MP3s are transcoded to OGG above (confirmed required --
        # this WASM build can't decode MP3 at all). This flag just covers any other stray
        # .mp3 that isn't under assets/music (e.g. an unused leftover asset file) so
        # the build doesn't fail outright over something that was never played anyway.
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

    # 4. Rename pygbag's own web.zip to match the "GD5 <PLATFORM> <version>.zip" convention
    zip_name = f"GD5 WEB {c.GAME_VERSION}"
    src_zip = os.path.join(STAGE_DIR, "build", "web.zip")
    dst_zip = os.path.join(STAGE_DIR, "build", f"{zip_name}.zip")
    if os.path.exists(src_zip):
        if os.path.exists(dst_zip):
            os.remove(dst_zip)
        shutil.move(src_zip, dst_zip)
        print(f"Zip ready at {dst_zip}. Upload it directly to itch.io, or unzip {build_web_dir}/ and serve it from any static host.")
    else:
        print(f"Warning: expected pygbag archive not found at {src_zip}; check {build_web_dir}/ directly.")


if __name__ == "__main__":
    main()
