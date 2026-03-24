def get_relation(nation_data, country_a, country_b):
    """Returns the status between two countries. Defaults to NEUTRAL."""
    if country_a == country_b:
        return "SELF"
    
    # Check country A's opinion of B
    relations = nation_data.get(country_a, {}).get("relations", {})
    return relations.get(country_b, "NEUTRAL")

def set_relation(nation_data, country_a, country_b, status):
    """Updates the relation for both parties (Symmetric)."""
    for a, b in [(country_a, country_b), (country_b, country_a)]:
        if "relations" not in nation_data[a]:
            nation_data[a]["relations"] = {}
        nation_data[a]["relations"][b] = status

def are_at_war(nation_data, country_a, country_b):
    return get_relation(nation_data, country_a, country_b) == "WAR"