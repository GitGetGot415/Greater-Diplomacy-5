"""One domestic axis: libertarian at one end, authoritarian at the other.

A country trades how hard its armies hit against how fast it researches, and it
cannot do it quickly -- picking a direction moves the value one step per
processed turn, so either extreme is ten turns away from the centre. Everyone
starts centrist; the map editor can author a different starting position.

Damage means every point of damage a nation's units deal, attacking or
defending, plus bombardment. A lane fight is a simultaneous exchange with no
designated attacker, so "your armies deal more damage" can only sensibly be a
property of the army rather than of who moved first.

Stdlib and `data.constants` only, so it imports under Pyodide and can be
imported at module level from combat_rules without joining the queries cycle.
"""

import data.constants as c

#: Where the two scalars live on nation_data[name]. Flat and defaulted, never
#: written at country-creation time: build_save_dict dumps nation_data verbatim
#: and snapshot_history copies scalars by value, so persistence costs nothing,
#: and reading through the accessors below covers every nation the base-template
#: merge in load_map never sees -- rebellions, splinter states, generated maps.
VALUE_KEY = "political_value"
DRIFT_KEY = "political_drift"


def clamp(value):
    """A political value forced onto the axis, as an int."""
    try:
        return max(c.POLITICS_MIN, min(c.POLITICS_MAX, int(round(float(value)))))
    except (TypeError, ValueError):
        return c.POLITICS_START


def value(nation_data, nation):
    """Where this nation sits, POLITICS_MIN..POLITICS_MAX. Centre by default."""
    if not nation_data:
        return c.POLITICS_START
    return clamp(nation_data.get(nation, {}).get(VALUE_KEY, c.POLITICS_START))


def drift(nation_data, nation):
    """Which way it is heading: -1 libertarian, 0 holding, +1 authoritarian.

    A direction persists until something changes it -- the player reopening the
    tab, the AI reconsidering, or `tick` hitting the end of the axis.
    """
    if not nation_data:
        return 0
    try:
        raw = int(nation_data.get(nation, {}).get(DRIFT_KEY, 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(-1, min(1, raw))


def set_value(nation_data, nation, new_value):
    """Pins a nation's position outright. The map editor's starting value."""
    nation_data.setdefault(nation, {})[VALUE_KEY] = clamp(new_value)


def set_drift(nation_data, nation, direction):
    """Points a nation at one end of the axis, or stops it."""
    nation_data.setdefault(nation, {})[DRIFT_KEY] = max(-1, min(1, int(direction)))


def _fraction(nation_data, nation):
    """Position as -1.0..+1.0, which is what both multipliers are linear in."""
    return value(nation_data, nation) / float(c.POLITICS_MAX)


def damage_multiplier(nation_data, nation):
    """What this nation's units multiply their damage by. 0.7x .. 1.3x."""
    return 1.0 + c.POLITICS_DAMAGE_SPAN * _fraction(nation_data, nation)


def research_multiplier(nation_data, nation):
    """What this nation multiplies its research points by. 2.0x .. 0.0x.

    Zero at the authoritarian end is deliberate and not a floor to guard
    against: points_remaining simply stops falling, which is what "research is
    frozen" has to look like.
    """
    return 1.0 - c.POLITICS_RESEARCH_SPAN * _fraction(nation_data, nation)


#: The axis carved into five named bands, libertarian first. Each entry is
#: (highest value in the band, what to call it, its c.UI_COLORS palette name).
#:
#: One table rather than two, because the word and the colour are the same
#: statement made twice: a screen that called a nation "Statist" and painted it
#: red would be telling the reader two different things about one number. The
#: centre band is yellow, so a map nobody has authored yet opens all one colour.
BANDS = (
    (-7, "Libertarian", "light_blue"),
    (-3, "Liberal", "green"),
    (2, "Centrist", "yellow"),
    (6, "Statist", "orange"),
    (c.POLITICS_MAX, "Authoritarian", "red"),
)


def band(political_value):
    """The (bound, label, palette) entry a value falls in."""
    v = clamp(political_value)
    for entry in BANDS:
        if v <= entry[0]:
            return entry
    return BANDS[-1]


def label(political_value):
    """A short word for a position, for screens and tooltips."""
    return band(political_value)[1]


def palette(political_value):
    """The c.UI_COLORS name a position is drawn in.

    Runs light blue -> green -> yellow -> orange -> red across the axis, so the
    editor's country list reads as a heat map of who has centralised.
    """
    return band(political_value)[2]


def at_limit(political_value):
    """Whether a value has run out of axis to move along."""
    v = clamp(political_value)
    return v <= c.POLITICS_MIN or v >= c.POLITICS_MAX


def tick(map_screen):
    """One processed turn of drift, for every nation that has picked a direction.

    Reaching either end clears the direction rather than leaving it pressed
    against the wall: "stop at the maximum" and "stop because the player chose
    to" then become the same state, which is what the map button's arrow badge
    reads and what keeps the AI from re-deciding a move it cannot make.
    """
    for name, stats in map_screen.nation_data.items():
        if name == "GLOBAL_EVENTS" or name in c.UNPLAYABLE_NATIONS:
            continue

        direction = drift(map_screen.nation_data, name)
        if not direction:
            continue

        new_value = clamp(value(map_screen.nation_data, name) + direction * c.POLITICS_STEP)
        stats[VALUE_KEY] = new_value
        if at_limit(new_value):
            stats[DRIFT_KEY] = 0
