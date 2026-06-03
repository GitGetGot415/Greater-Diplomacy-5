import os
import json

def check_flags():
    """
    Utility script to ensure every .png image in the assets/flags directory
    has an associated country entry inside data/json/countries_data.json.
    """
    # Use relative paths assuming this is inside the map_tools/ folder
    flags_dir = os.path.join(os.path.dirname(__file__), '..', 'assets', 'flags')
    countries_json = os.path.join(os.path.dirname(__file__), '..', 'data', 'json', 'countries_data.json')

    if not os.path.exists(flags_dir):
        print(f"Error: Directory {flags_dir} not found.")
        return

    if not os.path.exists(countries_json):
        print(f"Error: File {countries_json} not found.")
        return

    with open(countries_json, "r", encoding="utf-8") as f:
        countries_data = json.load(f)

    valid_countries = set(countries_data.keys())
    flag_files = [f for f in os.listdir(flags_dir) if f.lower().endswith(".png")]

    unassociated_flags = []
    
    for flag_file in flag_files:
        country_name = os.path.splitext(flag_file)[0]
        
        # Omit the default game-provided placeholder flag
        if country_name not in valid_countries and country_name != "default_flag":
            unassociated_flags.append(flag_file)

    print("--- Flag Audit Report ---")
    if unassociated_flags:
        print(f"Found {len(unassociated_flags)} orphaned flag(s):")
        for flag in unassociated_flags:
            print(f" [!] {flag}")
    else:
        print("Success! All flag PNGs are correctly associated with valid country entries.")

if __name__ == "__main__":
    check_flags()