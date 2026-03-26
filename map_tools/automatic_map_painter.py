import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image
import json

# Configuration
TERRAIN_LOOKUP = {
    (139, 69, 19):   "mountain",    # #8B4513
    (255, 255, 0):   "hills",       # #FFFF00
    (255, 165, 0):   "desert",      # #FFA500
    (144, 238, 144): "plains",      # #90EE90
    (0, 191, 0):     "forest",      # #00BF00
    (0, 128, 0):     "jungle",      # #008000
    (255, 20, 147):  "swamp",       # #FF1493
    (211, 211, 211): "tundra",      # #D3D3D3
    (255, 255, 255): "frozen",      # #FFFFFF

    (0, 0, 255):     "ocean",       # #0000FF
    (0, 133, 255):   "coastal_sea", # #0085FF
    (0, 194, 255):   "inland_sea",  # #00C2FF
    (128, 255, 255): "lakes"        # #80FFFF
}

def get_neighbors(x, y, width, height):
    adj = []
    for dx, dy in [(0, 2), (0, -2), (2, 0), (-2, 0)]:
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            adj.append((nx, ny))
    return adj

def run_generator(progress_var, root):
    path = filedialog.askopenfilename(title="Select Terrain Map")
    if not path: return

    img = Image.open(path).convert("RGB")
    img.save("map_tools/terrain_map.png")
    width, height = img.size
    pixels = img.load()
    
    id_img = Image.new("RGB", (width, height), (0, 0, 0))
    id_pixels = id_img.load()

    visited = set()
    temp_registry = {}
    current_id = 1

    # Total pixels for progress bar
    total_steps = height
    
    for y in range(height):
        # Update Progress Bar every 10 rows
        if y % 10 == 0:
            progress_var.set((y / total_steps) * 50) # First 50% is for mapping
            root.update_idletasks()

        for x in range(width):
            color = pixels[x, y]
            if color in TERRAIN_LOOKUP and (x, y) not in visited:
                terrain_name = TERRAIN_LOOKUP[color]
                r = (current_id & 0x0000FF)
                g = (current_id & 0x00FF00) >> 8
                b = (current_id & 0xFF0000) >> 16
                id_color = (r, g, b)

                queue = [(x, y)]
                visited.add((x, y))
                province_pixels = []
                
                head = 0
                while head < len(queue):
                    cx, cy = queue[head]
                    head += 1
                    province_pixels.append((cx, cy))
                    id_pixels[cx, cy] = id_color
                    
                    for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            if pixels[nx, ny] == color and (nx, ny) not in visited:
                                visited.add((nx, ny))
                                queue.append((nx, ny))

                avg_x = sum(p[0] for p in province_pixels) // len(province_pixels)
                avg_y = sum(p[1] for p in province_pixels) // len(province_pixels)

                temp_registry[id_color] = {
                    "id": current_id,
                    "terrain": terrain_name,
                    "center": (avg_x, avg_y),
                    "pixel_list": province_pixels
                }
                current_id += 1

    # --- Adjacency Pass & Coastal Detection ---
    final_json = {}
    total_provinces = len(temp_registry)
    
    # Define what counts as water for coastal detection
    WATER_TYPES = ["ocean", "coastal_sea", "inland_sea", "lakes"]
    
    for i, (id_color, data) in enumerate(temp_registry.items()):
        if i % 50 == 0:
            progress_var.set(50 + (i / total_provinces) * 50)
            root.update_idletasks()

        neighbors = set()
        is_coastal = False
        current_terrain = data["terrain"]

        for px, py in data["pixel_list"]:
            for nx, ny in get_neighbors(px, py, width, height):
                other_id_color = id_pixels[nx, ny]
                
                # If the pixel belongs to a different province
                if other_id_color != (0, 0, 0) and other_id_color != id_color:
                    neighbor_data = temp_registry[other_id_color]
                    neighbors.add(neighbor_data["id"])
                    
                    # COASTAL CHECK: 
                    # If I am LAND and my neighbor is WATER, I am coastal.
                    if current_terrain not in WATER_TYPES:
                        if neighbor_data["terrain"] in WATER_TYPES:
                            is_coastal = True
        
        final_json[str(id_color)] = {
            "id": data["id"],
            "terrain": data["terrain"],
            "is_coastal": is_coastal,  # <--- New Field added here
            "center": data["center"],
            "neighbors": list(neighbors),
            "owner": "Unclaimed",
            "units": [],
            "deployment_queue": [],
            "orders": [],
            "buildings": [],
            "resources": []
        }

    id_img.save("map_tools/provinces_id_map.png")
    with open("map_tools/map_data.json", "w") as f:
        json.dump(final_json, f, indent=4)
    
    progress_var.set(100)
    messagebox.showinfo("Success", f"Done! Found {current_id-1} provinces.")
    root.destroy()

# --- GUI Setup ---
root = tk.Tk()
root.title("Terrain Map Processor")
root.geometry("400x250")

label = tk.Label(root, text="Map Data Generator", font=("Arial", 14))
label.pack(pady=20)

progress_var = tk.DoubleVar()
progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=100, length=300)
progress_bar.pack(pady=10)

btn = tk.Button(root, text="Select Map & Start", 
               command=lambda: run_generator(progress_var, root), 
               pady=10, padx=20)
btn.pack(pady=20)

root.mainloop()