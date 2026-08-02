import os
import subprocess
import shutil
import sys
import data.constants as c

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

    # saves/ ships empty, same as windows_compilation.py (pygbag's virtual FS persists
    # in-session writes to IndexedDB, so an empty starting folder is all that's needed)
    os.makedirs(os.path.join(STAGE_DIR, "saves"), exist_ok=True)

    # Reset runtime-state JSON to defaults, identical to windows_compilation.py, so the
    # web build doesn't carry over whatever local settings the dev machine had
    for rel, content in [
        (os.path.join("data", "json", "active_albums.json"), "[]"),
        (os.path.join("data", "json", "scenario_settings.json"), "{}"),
        (os.path.join("data", "json", "settings_config.json"), "{}"),
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
        # The official soundtrack ships as .mp3; pygbag's asset scanner flags that as a
        # "commonly unsupported" browser format and refuses to build otherwise. Modern
        # browsers do decode mp3 fine, but this hasn't been verified against Pyodide's
        # bundled SDL2_mixer yet -- if music doesn't actually play in a real browser test,
        # transcoding assets/music/Greater Diplomacy */*.mp3 to .ogg is the fix.
        "--disable-sound-format-error",
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
