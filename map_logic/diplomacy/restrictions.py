"""Limits a treaty can impose on a nation, and the two questions they answer.

So far there is one: a demilitarization clause bars the signatory from raising
new units for a number of turns. It is stored as a countdown rather than an end
date because that is what the rest of the diplomacy state does -- truces,
war_durations and temp_modifiers all tick down in _decay_modifiers_and_truces,
and a save that skips a turn should not silently expire a clause early.

    nation_data[n]["restrictions"] = {"demilitarized": turns_left}

Deliberately not in data/queries.py: a mod may ship its own copy of that file
and shadow it wholesale, which would take a brand new function with it. See the
note in map_logic/ai/ai_world.py.
"""


def get(nation, nation_data):
    """This nation's restriction block, or an empty one. Never creates it."""
    entry = nation_data.get(nation, {}).get("restrictions")
    return entry if isinstance(entry, dict) else {}


def turns_left(nation, nation_data, restriction):
    return int(get(nation, nation_data).get(restriction, 0) or 0)


def can_raise_units(nation, nation_data):
    """Whether this nation may put anything new in a unit queue."""
    return turns_left(nation, nation_data, "demilitarized") <= 0


def is_demilitarized(nation, nation_data):
    return not can_raise_units(nation, nation_data)


def tick(data):
    """Ages one nation's restrictions down a turn, clearing the spent ones.

    Takes the nation's own dict rather than the whole map, to sit alongside the
    truce and modifier decay in diplomacy_processor that does the same.
    """
    entry = data.get("restrictions")
    if not isinstance(entry, dict):
        return
    for name in list(entry.keys()):
        entry[name] = int(entry[name] or 0) - 1
        if entry[name] <= 0:
            del entry[name]
    if not entry:
        data.pop("restrictions", None)
