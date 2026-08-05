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

    # Create empty saves/tournament_saves dirs in the bundle, mirroring the
    # Windows build: the app expects these to exist relative to its cwd, but
    # any saves already on this dev machine must NOT be bundled.
    resources_dir = os.path.join(dist_dir, "main.app", "Contents", "Resources")
    for d in ("saves", "tournament_saves"):
        os.makedirs(os.path.join(resources_dir, d), exist_ok=True)

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

    # Stage main.app alongside a README so both land as siblings at the zip's
    # top level (see the README.md notes on py2app's ad-hoc signature below).
    package_dir = os.path.join(dist_dir, "package")
    if os.path.exists(package_dir):
        remove_dir_safely(package_dir)
    os.makedirs(package_dir, exist_ok=True)
    shutil.move(os.path.join(dist_dir, "main.app"), os.path.join(package_dir, "main.app"))

    readme_path = os.path.join(package_dir, "README.txt")
    with open(readme_path, "w") as f:
        f.write(
            "Greater Diplomacy 5 - macOS Build\n\n"
            "When you double-click main.app, macOS may show:\n"
            '"main is damaged and can\'t be opened. You should move it to the Bin."\n'
            "with no option to open it anyway.\n\n"
            "This isn't actual corruption: the app isn't signed with a paid Apple\n"
            "Developer certificate, and macOS quarantines and blocks any downloaded,\n"
            "non-notarized app this way.\n\n"
            "The fix:\n"
            "  1. Open Terminal.\n"
            "  2. Type the following, including the trailing space, but do NOT press\n"
            "     Enter yet:\n"
            "         xattr -dr com.apple.quarantine \n"
            "  3. Drag main.app from Finder into the Terminal window. This inserts its\n"
            "     path for you - don't type a path in yourself.\n"
            "  4. Press Enter.\n"
            "  5. Double-click main.app as normal.\n"
        )

    # Use ditto, not shutil.make_archive (Python's zipfile module), to zip main.app.
    # zipfile flattens the symlinks inside the .app bundle (e.g. Python.framework's
    # Versions/Current) into plain file copies, which invalidates py2app's ad-hoc code
    # signature. A downloaded/re-extracted app with a broken signature is exactly what
    # makes Gatekeeper report "main is damaged and can't be opened" with no bypass
    # option, instead of the normal "unidentified developer" prompt (see README.txt
    # above, and the "For MacOS Users" section in the repo's README.md).
    #
    # package_dir (not app_path) is the ditto source, and --keepParent is omitted:
    # ditto archives a given directory's *contents* at the zip's root, so main.app
    # and README.txt end up as siblings at the top level exactly as before, instead
    # of nested inside an extra "package/" folder.
    result = subprocess.run(["ditto", "-c", "-k", package_dir, dst_zip_path])
    if result.returncode != 0:
        print("ditto zipping failed.")
        sys.exit(result.returncode)
    print(f"Created {zip_filename} in {dist_dir}/.")

    print("\nCompilation and zipping finished successfully.")
    print("To test the application, you can run the following command in terminal:")
    print("    ./dist/package/main.app/Contents/MacOS/main\n")

if __name__ == "__main__":
    main()
