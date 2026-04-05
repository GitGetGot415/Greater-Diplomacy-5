import json
import os

files_to_fix = [
    "data/json/countries_data.json"
]

new_research_block = {
    "infantry_type": 1, "cavalry": 1, "civilian_car": 0, "ww1_armored_car": 0, "ww1_tank": 0, 
    "armored_car": 0, "light_tank": 0, "medium_tank": 0, "heavy_tank": 0, "main_battle_tank": 0, 
    "carrack": 1, "ironclad": 0, "pre-dreadnaught": 0, "dreadnaught": 0, "destroyer": 0, 
    "aircraft_carrier": 0, "workshop": 0, "basic_factory": 0, "factory": 0, "bergius_process": 0, 
    "synthetic_fuel_experiments": 0, "fuel_refining": 0
}

for path in files_to_fix:
    if os.path.exists(path):
        with open(path, "r") as f:
            data = json.load(f)
            
        for country, attributes in data.items():
            if "research" in attributes:
                attributes["research"] = new_research_block.copy()
                
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
            
print("Countries updated to discrete research blocks!")