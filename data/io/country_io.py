import data.constants as c
from data import queries

def load_all_country_data():
    """Returns the full dictionary of country objects from cache."""
    return queries.get_country_data()

def get_nation_colors():
    """Returns {Name: (R, G, B)} for Pygame rendering."""
    data = load_all_country_data()
    return {name: tuple(stats["color"]) for name, stats in data.items()}

def get_country_stats(name):
    """Returns the dictionary for a specific country"""
    data = load_all_country_data()
    return data.get(name, {"color": [80,80,80]})