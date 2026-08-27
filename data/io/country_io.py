from data import queries

def load_all_country_data():
    """Returns the full dictionary of country objects from cache."""
    return queries.get_country_data()

#: What a nation with no color of its own is drawn in.
DEFAULT_NATION_COLOR = (150, 150, 150)


def nation_colors_from(nation_data):
    """{Name: (R, G, B)} for Pygame rendering, from an in-memory nation table.

    The fallback matters: utility entities (Ocean, Lakes, GLOBAL_EVENTS) carry
    no color, and indexing straight into them used to raise. data/map/load_map
    carried its own copy of this comprehension, twice.
    """
    return {name: tuple(stats.get("color", DEFAULT_NATION_COLOR))
            for name, stats in nation_data.items()}


def get_nation_colors():
    """The same mapping, for the countries as they ship on disk."""
    return nation_colors_from(load_all_country_data())

def get_country_stats(name):
    """Returns the dictionary for a specific country.

    The fallback is DEFAULT_NATION_COLOR rather than a grey of its own: this is
    the disk-side counterpart of nation_colors_from, and the two used to hand
    back different shades for the same missing nation, so a rebellion colored
    from here came out visibly darker than the same nation everywhere else.
    """
    data = load_all_country_data()
    return data.get(name, {"color": list(DEFAULT_NATION_COLOR)})
