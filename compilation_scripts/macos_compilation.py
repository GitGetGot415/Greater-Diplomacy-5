import os
import subprocess
import shutil
import sys
import time

# This script lives in compilation_scripts/ but every relative path below (build_dir,
# dist_dir, etc.) is meant to resolve against the actual project root, so hop up one
# level and put the root on sys.path before importing first-party packages.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

import data.constants as c

def remove_dir_safely(dir_path, retries=5, delay=0.2):
    """Safely remove a directory tree, handling macOS APFS/Finder file lock race conditions."""
    if not os.path.exists(dir_path):
        return
    for i in range(retries):
        try:
            shutil.rmtree(dir_path)
            return
        except OSError:
            if i == retries - 1:
                shutil.rmtree(dir_path, ignore_errors=True)
            else:
                time.sleep(delay)

def main():
    build_dir = "build"
    dist_dir = "dist"

    # 1. Clean old build
    if os.path.exists(build_dir):
        print(f"Cleaning {build_dir} folder...")
        remove_dir_safely(build_dir)
        
    if os.path.exists(dist_dir):
        print(f"Cleaning {dist_dir} folder...")
        remove_dir_safely(dist_dir)
    
    # 2. Rebuild
    print("Running py2app...")
    # setup.py lives alongside this script in compilation_scripts/, but py2app resolves
    # its DATA_FILES (assets, base_maps, etc.) relative to the CWD it's invoked from --
    # which is REPO_ROOT thanks to the os.chdir() above, so this still lands dist/build
    # at the project root exactly like before.
    cmd = "python3 compilation_scripts/setup.py py2app"
    
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        print("py2app failed.")
        sys.exit(result.returncode)
        
    print("py2app finished successfully.")
    
    # Overwrite active_albums.json with [] so the build doesn't carry over local settings
    active_albums_path = os.path.join(dist_dir, "main.app", "Contents", "Resources", "data", "json", "active_albums.json")
    if os.path.exists(os.path.dirname(active_albums_path)):
        with open(active_albums_path, "w") as f:
            f.write("[]")

    # Reset scenario/global settings to {} so the build falls back to the game's
    # built-in defaults instead of carrying over whatever the dev machine had set
    resources_json_dir = os.path.join(dist_dir, "main.app", "Contents", "Resources", "data", "json")
    for settings_file in ("scenario_settings.json", "settings_config.json", "starting_song.json", "hildehrand_choice.json"):
        settings_path = os.path.join(resources_json_dir, settings_file)
        if os.path.exists(resources_json_dir):
            with open(settings_path, "w") as f:
                f.write("{}")

    # 3. Zipping the app
    zip_name = f"GD5 MACOS {c.GAME_VERSION}"
    zip_filename = f"{zip_name}.zip"
    print(f"Zipping {dist_dir} into {zip_filename}...")

    dst_zip_path = os.path.join(dist_dir, zip_filename)

    # If there's an existing zip in dist, remove it before creating the new one
    if os.path.exists(dst_zip_path):
        os.remove(dst_zip_path)

    # Use ditto, not shutil.make_archive (Python's zipfile module), to zip main.app.
    # zipfile flattens the symlinks inside the .app bundle (e.g. Python.framework's
    # Versions/Current) into plain file copies, which invalidates py2app's ad-hoc code
    # signature. A downloaded/re-extracted app with a broken signature is exactly what
    # makes Gatekeeper report "main is damaged and can't be opened" with no bypass
    # option, instead of the normal "unidentified developer" prompt.
    app_path = os.path.join(dist_dir, "main.app")
    result = subprocess.run(["ditto", "-c", "-k", "--keepParent", app_path, dst_zip_path])
    if result.returncode != 0:
        print("ditto zipping failed.")
        sys.exit(result.returncode)
    print(f"Created {zip_filename} in {dist_dir}/.")
    
    print("\nCompilation and zipping finished successfully.")
    print("To test the application, you can run the following command in terminal:")
    print("    ./dist/main.app/Contents/MacOS/main\n")

if __name__ == "__main__":
    main()
