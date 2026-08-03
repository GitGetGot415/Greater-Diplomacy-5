import os
import subprocess
import shutil
import sys

# This script lives in compilation_scripts/ but every relative path below (STAGE_DIR,
# DATA_DIRS, etc.) is meant to resolve against the actual project root, so hop up one
# level and put the root on sys.path before importing first-party packages.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

import data.constants as c

# Build-time only tools (not needed to run the game itself, so not in requirements.txt,
# same convention as PyInstaller/py2app for the other two platform builds):
#   pip install pygbag imageio-ffmpeg

STAGE_DIR = "web_stage"

# main.py ships source (not a frozen binary) into the browser's virtual FS, so unlike
# windows_compilation.py/macos_compilation.py this script also has to stage the first-party
# Python packages themselves, not just data directories.
SOURCE_FILES = ["main.py", "gameState.py", "ui_elements.py"]
SOURCE_PACKAGES = ["data", "ui", "screens", "map_logic"]
DATA_DIRS = ["assets", "base_maps", "scenarios", "tournament_saves"]


def main():
    if os.path.exists(STAGE_DIR):
        print("Cleaning web_stage folder...")
        shutil.rmtree(STAGE_DIR)
    os.makedirs(STAGE_DIR)

    # 1. Copy first-party source. data/editors (tkinter dev tools) is excluded since it's
    # never imported by main.py's runtime import graph; map_tools/ (standalone dev tools)
    # and soloud.py/native SoLoud binaries (only imported when USE_SOLOUD, which is always
    # False on web) are deliberately not staged at all.
    def pycache_ignore(dir_name, contents):
        return [e for e in contents if e == "__pycache__"]

    def data_pkg_ignore(dir_name, contents):
        if os.path.normpath(dir_name).endswith(os.path.join("data", "editors")):
            return contents
        return pycache_ignore(dir_name, contents)

    print("Copying first-party source...")
    for f in SOURCE_FILES:
        shutil.copy2(f, os.path.join(STAGE_DIR, f))

    for pkg in SOURCE_PACKAGES:
        dst = os.path.join(STAGE_DIR, pkg)
        ignore_fn = data_pkg_ignore if pkg == "data" else pycache_ignore
        shutil.copytree(pkg, dst, ignore=ignore_fn)

    # 2. Copy asset/data dirs, reusing the same git-ignore-based filtering
    # windows_compilation.py uses so the web bundle's music/scenario footprint matches
    # the desktop builds (gitignored local-only OSTs, etc. aren't shipped).
    def assets_ignore_func(dir_name, contents):
        ignored = []
        for entry in contents:
            path = os.path.join(dir_name, entry)
            try:
                # git check-ignore returns 0 if ignored, 1 if not ignored
                res = subprocess.run(["git", "check-ignore", "-q", path])
                if res.returncode == 0:
                    ignored.append(entry)
            except Exception as e:
                print(f"Error checking git ignore for {path}: {e}")
        return ignored

    def scenarios_ignore_func(dir_name, contents):
        parts = os.path.normpath(dir_name).split(os.sep)
        if "map_editor" in parts:
            return contents
        return []

    for d in DATA_DIRS:
        src = d
        dst = os.path.join(STAGE_DIR, d)

        if not os.path.exists(src):
            if d == "tournament_saves":
                os.makedirs(dst, exist_ok=True)
            else:
                print(f"Source directory {src} does not exist, skipping.")
            continue

        print(f"Copying {src} to {dst}...")
        if d == "assets":
            shutil.copytree(src, dst, ignore=assets_ignore_func)
        elif d == "scenarios":
            shutil.copytree(src, dst, ignore=scenarios_ignore_func)
        elif d == "tournament_saves":
            shutil.copytree(src, dst, ignore=lambda dn, c: c)
        else:
            shutil.copytree(src, dst)

    # 2b. Transcode the official soundtrack from MP3 to OGG for the web bundle only.
    # Confirmed via real browser testing: this pygame-ce/SDL_mixer WASM build cannot
    # decode MP3 at all ("Unrecognized audio format"), matching pygame-web's own docs
    # (https://pygame-web.github.io/wiki/pygbag/ -- only WAV/OGG are reliably
    # supported). Desktop builds are untouched; only the staged copy is converted.
    music_dir = os.path.join(STAGE_DIR, "assets", "music")
    if os.path.exists(music_dir):
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            print("Warning: imageio-ffmpeg not installed (pip install imageio-ffmpeg) -- "
                  "skipping MP3->OGG transcode. Music will not play in the web build.")
            ffmpeg_exe = None

        if ffmpeg_exe:
            print("Transcoding soundtrack from MP3 to OGG for the web build...")
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

    # saves/ ships empty, same as windows_compilation.py. Saves made in the browser
    # build persist across reloads via data/platform.py's own IndexedDB mirroring
    # (restored/synced from main.py, save_map.py, gameState.py, queries.py) -- not
    # anything pygbag provides automatically; its bundled WASM runtime only links
    # MEMFS in, so without that, an empty starting folder would stay empty forever.
    os.makedirs(os.path.join(STAGE_DIR, "saves"), exist_ok=True)

    # Reset runtime-state JSON to defaults, identical to windows_compilation.py, so the
    # web build doesn't carry over whatever local settings the dev machine had
    for rel, content in [
        (os.path.join("data", "json", "active_albums.json"), "[]"),
        (os.path.join("data", "json", "scenario_settings.json"), "{}"),
        (os.path.join("data", "json", "settings_config.json"), "{}"),
        (os.path.join("data", "json", "starting_song.json"), "{}"),
        (os.path.join("data", "json", "hildehrand_choice.json"), "{}"),
    ]:
        path = os.path.join(STAGE_DIR, rel)
        if os.path.exists(os.path.dirname(path)):
            with open(path, "w") as f:
                f.write(content)

    print("Copying finished successfully.")

    # 3. Invoke pygbag in build-only (non-interactive) mode against the staged dir.
    # pygbag writes its output to <STAGE_DIR>/build/web/, and can zip it directly via --archive.
    icon_path = os.path.join(STAGE_DIR, "assets", "icon", "icon.png")
    print("Running pygbag...")
    cmd = [
        sys.executable, "-m", "pygbag",
        "--build",
        "--archive",
        "--app_name", "Greater Diplomacy 5",
        # The soundtrack itself is transcoded to OGG above (confirmed required -- this
        # WASM build can't decode MP3 at all). This flag just covers any other stray
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
