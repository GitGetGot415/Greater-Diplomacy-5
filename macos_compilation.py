import os
import subprocess
import shutil
import sys
import time
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
    cmd = "python3 setup.py py2app"
    
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
    for settings_file in ("scenario_settings.json", "settings_config.json"):
        settings_path = os.path.join(resources_json_dir, settings_file)
        if os.path.exists(resources_json_dir):
            with open(settings_path, "w") as f:
                f.write("{}")

    # 3. Zipping the app
    zip_name = f"GD5 MACOS {c.GAME_VERSION}"
    print(f"Zipping {dist_dir} into {zip_name}.zip...")
    
    # Zip the contents of dist (which is main.app)
    shutil.make_archive(zip_name, 'zip', dist_dir)
    
    zip_filename = f"{zip_name}.zip"
    dst_zip_path = os.path.join(dist_dir, zip_filename)
    
    # If there's an existing zip in dist, remove it before moving the new one
    if os.path.exists(dst_zip_path):
        os.remove(dst_zip_path)
        
    # Move the zip into the dist directory
    shutil.move(zip_filename, dst_zip_path)
    print(f"Moved {zip_filename} into {dist_dir}/.")
    
    print("\nCompilation and zipping finished successfully.")
    print("To test the application, you can run the following command in terminal:")
    print("    ./dist/main.app/Contents/MacOS/main\n")

if __name__ == "__main__":
    main()
