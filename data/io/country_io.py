from data import queries

def load_all_country_data():
    """Returns the full dictionary of country objects from cache."""
    return queries.get_country_data()

def get_nation_colors():
    """Returns {Name: (R, G, B)} for Pygame rendering."""
    data = load_all_country_data()
    # FIX: Use .get() with a fallback color (Grey) to prevent KeyErrors on utility entities
    return {name: tuple(stats.get("color", [150, 150, 150])) for name, stats in data.items()}

def get_country_stats(name):
    """Returns the dictionary for a specific country"""
    data = load_all_country_data()
    return data.get(name, {"color": [80,80,80]})