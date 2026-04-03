import json
import os
import tkinter as tk
from tkinter import filedialog

# Ask the user which base map to reset
root = tk.Tk()
root.withdraw()
target_dir = filedialog.askdirectory(initialdir="base_maps", title="Select Map to Reset")
root.destroy()

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