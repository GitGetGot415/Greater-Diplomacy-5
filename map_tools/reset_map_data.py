import json
import os
import sys

# Add the parent directory (project root) to the Python path so the picker's imports resolve
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from ui.file_browser_screen import run_file_browser

# Ask the user which base map to reset
target_dir = run_file_browser("Select Map to Reset", "base_maps", mode="select_folder")

if not target_dir:
    print("No folder selected. Exiting.")
    exit()

filename = os.path.join(target_dir, 'map_data.json')
print(f"Resetting: {filename}")

# 1. Load existing data
with open(filename, 'r') as f:
    data = json.load(f)
    print(f"Loaded {len(data)} items from map data.")

# 2. Iterate through and reset owner fields
for key in data:
    if "owner" in data[key]:
        data[key]["owner"] = "Unclaimed" # Unclaimed is cleaner for your engine than ""

# 3. Save the result
with open(filename, 'w') as f:
    json.dump(data, f, indent=4)

print("Owner fields cleared successfully!")