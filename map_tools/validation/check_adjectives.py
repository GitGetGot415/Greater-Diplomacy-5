import os
import json

def check_adjectives():
    """
    Utility script to ensure every playable country inside data/json/countries_data.json
    has an associated 'adjective' property set.
    """
    # Use relative paths assuming this is inside the map_tools/ folder
    countries_json = os.path.join(os.path.dirname(__file__), '..', 'data', 'json', 'countries_data.json')

    if not os.path.exists(countries_json):
        print(f"Error: File {countries_json} not found.")
        return

    with open(countries_json, "r", encoding="utf-8") as f:
        countries_data = json.load(f)

    missing_adjectives = []
    
    # Optional: Skip these non-countries
    ignored_entities = {"Ocean", "Lakes", "Unclaimed", "Spectator", "GLOBAL_EVENTS", "FACTION_WAR_MAPS", "None"}
    
    for country_name, stats in countries_data.items():
        if country_name in ignored_entities:
            continue
            
        # Also ignore non-playable map entities if you want, but for now we'll check any normal country
        # if not stats.get("is_playable", False):
        #     continue

        adjective = stats.get("adjective", "")
        if not adjective:
            missing_adjectives.append(country_name)

    print("--- Adjective Audit Report ---")
    if missing_adjectives:
        print(f"Found {len(missing_adjectives)} country(s) missing an adjective:")
        for country in missing_adjectives:
            print(f" [!] {country}")
    else:
        print("Success! All countries have an adjective set.")

if __name__ == "__main__":
    check_adjectives()
