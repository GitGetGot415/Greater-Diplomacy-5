import json
import os

files_to_fix = [
    "data/json/countries_data.json"
]

new_research_block = {
    "infantry_type": 1, "cavalry": 1, "civilian_car": 0, "ww1_armored_car": 0, "ww1_tank": 0, 
    "armored_car": 0, "light_tank": 0, "medium_tank": 0, "heavy_tank": 0, "main_battle_tank": 0, 
    "dreadnought": 0, "destroyer": 0, 
    "aircraft_carrier": 0, "basic_factory": 0, "factory": 0, "bergius_process": 0, 
    "fuel_refining": 0,
    "general_recruitment": 0,
    "militia": 0,
    "motorized_infantry": 0,
    "mechanized_infantry": 0,
    "battleship": 0,
    "basic_recruitment": 0,
    "recruitment_buildings": 0
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