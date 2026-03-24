import json

filename = 'map_tools/map_data.json'
print(filename)

# 1. ReLoadad existing data
with open(filename, 'r') as f:
    data = json.load(f)
    print(f"Loaded {len(data)} items from map data.")

# 2. Iterate through and reset owner fields
for key in data:
    if "owner" in data[key]:
        data[key]["owner"] = ""
        # print(f"Reset owner for province ID: {key}")


# 3. Save the result
with open('map_tools/map_data.json', 'w') as f:
    json.dump(data, f, indent=4)

print("Owner fields cleared successfully!")