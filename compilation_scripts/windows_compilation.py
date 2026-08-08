import os
import subprocess
import shutil
import sys

# This script lives in compilation_scripts/ but every relative path below (dist_dir,
# the data dirs to copy, etc.) is meant to resolve against the actual project root, so
# hop up one level and put the root on sys.path before importing first-party packages.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

import data.constants as c

def main():
    dist_dir = "dist"
    if os.path.exists(dist_dir):
        print("Cleaning dist folder...")
        shutil.rmtree(dist_dir)

    # 1. Run pyinstaller
    print("Running PyInstaller...")
    cmd = 'pyinstaller --clean --onefile --add-binary "win64-libsoloud.dll;." --add-binary "mac64-libsoloud.dylib;." --add-binary "lin64-libsoloud.so;." main.py'
    
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("PyInstaller failed.")
        sys.exit(result.returncode)
        
    print("PyInstaller finished successfully.")

    # Ensure dist exists
    os.makedirs(dist_dir, exist_ok=True)
    
    # 2. Copy directories
    # screens/map_logic/ui are added alongside data so the mod system has a real,
    # loose .py source tree to validate mod targets against and patch at import
    # time -- PyInstaller only embeds compiled bytecode inside the exe itself,
    # so without these the game folder next to main.exe has nothing on disk for
    # mod_loader._resolve_target() to find, and every dropped-in mod is silently
    # rejected as "target file not found".
    dirs_to_copy = ["assets", "base_maps", "data", "screens", "map_logic", "ui",
                     "saves", "scenarios", "tournament_saves"]

    def data_ignore_func(dir_name, contents):
        ignored = []
        for entry in contents:
            path = os.path.join(dir_name, entry)
            if entry == "__pycache__":
                ignored.append(entry)
            elif os.path.isfile(path) and not (entry.endswith('.json') or entry.endswith('.py')):
                ignored.append(entry)
        return ignored

    def py_ignore_func(dir_name, contents):
        ignored = []
        for entry in contents:
            path = os.path.join(dir_name, entry)
            if entry == "__pycache__":
                ignored.append(entry)
            elif os.path.isfile(path) and not entry.endswith('.py'):
                ignored.append(entry)
        return ignored

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

    def saves_ignore_func(dir_name, contents):
        return contents

    def scenarios_ignore_func(dir_name, contents):
        parts = os.path.normpath(dir_name).split(os.sep)
        if "map_editor" in parts:
            return contents
        return []

    for d in dirs_to_copy:
        src = d
        dst = os.path.join(dist_dir, d)
        
        if not os.path.exists(src):
            if d == "tournament_saves" or d == "saves":
                os.makedirs(dst, exist_ok=True)
            else:
                print(f"Source directory {src} does not exist, skipping.")
            continue
            
        print(f"Copying {src} to {dst}...")
        
        # Remove destination if it exists so copytree doesn't fail
        if os.path.exists(dst):
            shutil.rmtree(dst)
            
        if d == "data":
            shutil.copytree(src, dst, ignore=data_ignore_func)
            for dirpath, dirnames, filenames in os.walk(dst, topdown=False):
                if not os.listdir(dirpath) and dirpath != dst:
                    os.rmdir(dirpath)
        elif d == "assets":
            shutil.copytree(src, dst, ignore=assets_ignore_func)
        elif d == "saves" or d == "tournament_saves":
            shutil.copytree(src, dst, ignore=saves_ignore_func)
        elif d == "scenarios":
            shutil.copytree(src, dst, ignore=scenarios_ignore_func)
        elif d in ("screens", "map_logic", "ui"):
            shutil.copytree(src, dst, ignore=py_ignore_func)
        else:
            shutil.copytree(src, dst)

    # Standalone top-level modules, alongside the package dirs above, so
    # mod_loader can find and patch them too (e.g. a mod targeting
    # "gameState.py" or "ui_elements.py" directly).
    for py_file in ("main.py", "mod_loader.py", "gameState.py", "ui_elements.py", "soloud.py"):
        if os.path.isfile(py_file):
            shutil.copy2(py_file, os.path.join(dist_dir, py_file))

    # Empty mods/ folder next to main.exe: dropping a .py mod in here (see
    # mod_loader.py's docstring, or the in-game Mods screen) is how players
    # self-serve mods without a rebuild. Left empty on purpose -- the
    # example_*.py mods in the repo's mods/ dir are dev references, not
    # meant to ship enabled.
    os.makedirs(os.path.join(dist_dir, "mods"), exist_ok=True)

    # Overwrite active_albums.json with [] so the build doesn't carry over local settings
    active_albums_path = os.path.join(dist_dir, "data", "json", "active_albums.json")
    if os.path.exists(os.path.dirname(active_albums_path)):
        with open(active_albums_path, "w") as f:
            f.write("[]")

    # Reset scenario/global settings to {} so the build falls back to the game's
    # built-in defaults instead of carrying over whatever the dev machine had set
    for settings_file in ("scenario_settings.json", "settings_config.json", "starting_song.json", "hildehrand_choice.json"):
        settings_path = os.path.join(dist_dir, "data", "json", settings_file)
        if os.path.exists(os.path.dirname(settings_path)):
            with open(settings_path, "w") as f:
                f.write("{}")

    print("Compilation and copying finished successfully.")

    zip_name = f"GD5 WINDOWS {c.GAME_VERSION}"
    print(f"Zipping {dist_dir} into {zip_name}.zip...")
    shutil.make_archive(zip_name, 'zip', dist_dir)
    
    zip_filename = f"{zip_name}.zip"
    dst_zip_path = os.path.join(dist_dir, zip_filename)
    if os.path.exists(dst_zip_path):
        os.remove(dst_zip_path)
    shutil.move(zip_filename, dst_zip_path)
    print(f"Moved {zip_filename} into {dist_dir}/.")

if __name__ == "__main__":
    main()
