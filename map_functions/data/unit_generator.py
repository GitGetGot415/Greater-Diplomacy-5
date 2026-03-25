import json

def generate_unit_json(health, attack, defense, speed, cost):
    data_to_file = {
        "health": health,
        "attack": attack,
        "defense": defense,
        "speed": speed,
        "cost": cost,
        "order": {}
    }
    return data_to_file

data_to_file = {
    "Chadian Toyota Hilux": generate_unit_json(50, 10, 1, 3, 100),
    "Libyan T-55": generate_unit_json(100, 20, 10, 2, 100),
    "Militia": generate_unit_json(9, 6, 0, 1, 100),
    "Infantry": generate_unit_json(15, 9, 0, 1, 100),
    "Main Battle Tank": generate_unit_json(15, 9, 0, 2, 100)
}

# Define the filename
filename = 'map_functions/data/unit_data.json'

# Open the file in write mode ('w') and use json.dump() to write the data
# The 'indent' parameter makes the file human-readable
with open(filename, 'w') as json_file:
    json.dump(data_to_file, json_file, indent=4)

print(f"Successfully generated JSON data and saved to {filename}")
