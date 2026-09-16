"""Domestic politics: an ideological axis and timed national policies.

A country trades how hard its armies hit against how fast it researches, and it
cannot do it quickly -- picking a direction moves it by ``POLITICS_STEP`` per
processed turn. Everyone starts at ``POLITICS_START``; the map editor can
author a different starting position. A country may additionally pursue
eligible policies. Their activation and cancellation durations are the
respective ``POLICY_*_TURNS`` values below.

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

# Policies remain a flat mapping within nation_data so saves and history
# snapshots need no schema migration.  Every card has its own lifecycle.
POLICY_KEY = "domestic_policies"
POLICY_ACTIVATING = "ACTIVATING"
POLICY_ACTIVE = "ACTIVE"
POLICY_CANCELLING = "CANCELLING"
POLICY_ACTIVATION_TURNS = 2
POLICY_CANCELLATION_TURNS = 1

# Ordered left-to-right exactly as the Politics panel presents the cards.
# Requirements are strict: e.g. max_politics=-2 means the country must be at
# -3 or further left.  Effects are multiplicative and apply only when ACTIVE.
POLICIES = (
    {
        "id": "research_subsidies",
        "name": "Research Subsidies",
        "max_politics": -2,
        "effects": {"research": 1.50, "manpower": 0.80, "materials": 0.90, "fuel": 0.90},
        "effect_lines": ("Research +50%", "Manpower -20%", "Materials -10%", "Fuel -10%"),
    },
    {
        "id": "prioritize_civilian_needs",
        "name": "Prioritize Civilian Needs",
        "max_politics": 3,
        "effects": {"research": 1.20, "manpower": 0.90},
        "effect_lines": ("Research +20%", "Manpower -10%"),
    },
    {
        "id": "prioritize_industrial_needs",
        "name": "Prioritize Industrial Needs",
        "effects": {"materials": 1.10, "fuel": 1.10, "research": 0.80, "manpower": 0.80},
        "effect_lines": ("Materials +10%", "Fuel +10%", "Research -20%", "Manpower -20%"),
    },
    {
        "id": "recruitment_propaganda",
        "name": "Recruitment Propaganda",
        "min_politics": -3,
        "effects": {"research": 0.80, "manpower": 1.10},
        "effect_lines": ("Research -20%", "Manpower +10%"),
    },
    {
        "id": "total_mobilisation",
        "name": "Total Mobilisation",
        "min_politics": 2,
        "effects": {"damage": 1.10, "research": 0.50, "manpower": 0.80, "materials": 0.80, "fuel": 0.80},
        "effect_lines": ("Army damage +10%", "Research -50%", "Manpower -20%", "Materials -20%", "Fuel -20%"),
    },

    # maybe more stuff related to conscription...
    # also maybe a description for each item
)
POLICIES_BY_ID = {policy["id"]: policy for policy in POLICIES}


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


def policy(policy_id):
    """Returns a policy definition, or None for an unknown saved value."""
    return POLICIES_BY_ID.get(policy_id)


def policy_states(nation_data, nation):
    """The country's valid policy states, keyed by policy id."""
    states = nation_data.get(nation, {}).get(POLICY_KEY, {}) if nation_data else {}
    if not isinstance(states, dict):
        return {}
    return {
        policy_id: state for policy_id, state in states.items()
        if (policy(policy_id) is not None and isinstance(state, dict)
            and state.get("status") in (POLICY_ACTIVATING, POLICY_ACTIVE, POLICY_CANCELLING))
    }


def policy_state(nation_data, nation, policy_id=None):
    """One policy's saved state, or the sole state for legacy-style callers."""
    states = policy_states(nation_data, nation)
    if policy_id is not None:
        return states.get(policy_id)
    return next(iter(states.values()), None) if len(states) == 1 else None


def requirements_met(nation_data, nation, policy_id):
    """Whether a policy can be activated at the country's current position."""
    definition = policy(policy_id)
    if definition is None:
        return False
    political_value = value(nation_data, nation)
    return (("max_politics" not in definition or political_value < definition["max_politics"])
            and ("min_politics" not in definition or political_value > definition["min_politics"]))


def requirement_text(policy_id):
    """A short, exact explanation of a policy's political-axis requirement."""
    definition = policy(policy_id)
    if definition is None:
        return "Unavailable"
    if "max_politics" in definition:
        return "Requires politics < %+d" % definition["max_politics"]
    if "min_politics" in definition:
        return "Requires politics > %+d" % definition["min_politics"]
    return "No political requirement"


def activate_or_cancel_policy(nation_data, nation, policy_id):
    """Starts a policy, requests its cancellation, or undoes that request.

    Cancelling records the prior state so clicking the same card before the
    next processed turn restores that policy's activation timer exactly where
    it was.
    """
    definition = policy(policy_id)
    if definition is None:
        return False
    stats = nation_data.setdefault(nation, {})
    states = stats.get(POLICY_KEY)
    if not isinstance(states, dict):
        states = stats[POLICY_KEY] = {}
    current = policy_state(nation_data, nation, policy_id)

    if current:
        # The activation has not consumed a processed turn yet, so cancelling
        # it is just withdrawing this turn's choice -- there is no programme
        # to wind down and no one-turn cancellation delay to show.
        if (current["status"] == POLICY_ACTIVATING
                and current.get("turns_remaining") == POLICY_ACTIVATION_TURNS):
            states.pop(policy_id, None)
            if not states:
                stats.pop(POLICY_KEY, None)
            return True
        if current["status"] == POLICY_CANCELLING:
            states[policy_id] = {
                "status": current.get("resume_status", POLICY_ACTIVE),
                "turns_remaining": current.get("resume_turns_remaining", 0),
            }
        else:
            states[policy_id] = {
                "status": POLICY_CANCELLING,
                "turns_remaining": POLICY_CANCELLATION_TURNS,
                "resume_status": current["status"],
                "resume_turns_remaining": current.get("turns_remaining", 0),
            }
        return True

    if not requirements_met(nation_data, nation, policy_id):
        return False
    states[policy_id] = {
        "status": POLICY_ACTIVATING,
        "turns_remaining": POLICY_ACTIVATION_TURNS,
    }
    return True


def policy_draft_projection(nation_data, nation):
    """The client-safe policy choices for a multiplayer turn draft.

    Timers are authoritative turn state, so a draft names only each policy's
    desired lifecycle status.  The host restores countdowns from its own map.
    """
    return {policy_id: {"status": state["status"]}
            for policy_id, state in policy_states(nation_data, nation).items()}


def canonicalize_policy_draft(nation_data, nation, requested):
    """Validate a multiplayer policy draft against authoritative state.

    The client may start a currently eligible policy, ask to cancel one, or
    undo a recorded cancellation.  It may never choose an ACTIVE state or a
    countdown directly.  Existing absent entries are retained: a normal UI
    cancellation is represented explicitly as CANCELLING, while this protects
    the server from a stale or forged omission deleting an active policy.
    """
    if not isinstance(requested, dict) or set(requested) - set(POLICIES_BY_ID):
        raise ValueError("Invalid policy draft.")

    for state in requested.values():
        if not isinstance(state, dict) or set(state) != {"status"}:
            raise ValueError("Invalid policy draft.")
        if state["status"] not in (POLICY_ACTIVATING, POLICY_ACTIVE, POLICY_CANCELLING):
            raise ValueError("Invalid policy draft.")

    existing = policy_states(nation_data, nation)
    canonical = {}
    for definition in POLICIES:
        policy_id = definition["id"]
        current = existing.get(policy_id)
        desired = requested.get(policy_id, {}).get("status")

        if current is None:
            if desired is None:
                continue
            if desired != POLICY_ACTIVATING or not requirements_met(nation_data, nation, policy_id):
                raise ValueError("Invalid policy transition.")
            canonical[policy_id] = {"status": POLICY_ACTIVATING,
                                    "turns_remaining": POLICY_ACTIVATION_TURNS}
            continue

        if desired is None or desired == current["status"]:
            canonical[policy_id] = dict(current)
        elif (current["status"] in (POLICY_ACTIVATING, POLICY_ACTIVE)
              and desired == POLICY_CANCELLING):
            if (current["status"] == POLICY_ACTIVATING
                    and current.get("turns_remaining") == POLICY_ACTIVATION_TURNS):
                continue
            canonical[policy_id] = {
                "status": POLICY_CANCELLING,
                "turns_remaining": POLICY_CANCELLATION_TURNS,
                "resume_status": current["status"],
                "resume_turns_remaining": current.get("turns_remaining", 0),
            }
        elif (current["status"] == POLICY_CANCELLING
              and desired == current.get("resume_status", POLICY_ACTIVE)):
            canonical[policy_id] = {
                "status": current.get("resume_status", POLICY_ACTIVE),
                "turns_remaining": current.get("resume_turns_remaining", 0),
            }
        else:
            raise ValueError("Invalid policy transition.")
    return canonical


def active_policies(nation_data, nation):
    """Fully activated, still-eligible policy definitions for one country."""
    return tuple(
        policy(policy_id) for policy_id, state in policy_states(nation_data, nation).items()
        if state["status"] == POLICY_ACTIVE and requirements_met(nation_data, nation, policy_id)
    )


def reconcile_policy(nation_data, nation):
    """Immediately removes every policy whose political requirement was lost."""
    stats = nation_data.get(nation, {})
    states = stats.get(POLICY_KEY, {})
    if not isinstance(states, dict):
        return False
    removed = False
    for policy_id in tuple(policy_states(nation_data, nation)):
        if not requirements_met(nation_data, nation, policy_id):
            states.pop(policy_id, None)
            removed = True
    if not states:
        stats.pop(POLICY_KEY, None)
    return removed


def effect_multiplier(nation_data, nation, effect):
    """Multiplier contributed by the country's fully activated policy."""
    result = 1.0
    for current in active_policies(nation_data, nation):
        result *= current.get("effects", {}).get(effect, 1.0)
    return result


def _fraction(nation_data, nation):
    """Position as -1.0..+1.0, which is what both multipliers are linear in."""
    return value(nation_data, nation) / float(c.POLITICS_MAX)


def damage_multiplier(nation_data, nation):
    """What this nation's units multiply their damage by, including policy."""
    axis_multiplier = 1.0 + c.POLITICS_DAMAGE_SPAN * _fraction(nation_data, nation)
    return axis_multiplier * effect_multiplier(nation_data, nation, "damage")


def research_multiplier(nation_data, nation):
    """What this nation multiplies its research points by, including policy.

    Zero at the authoritarian end is deliberate and not a floor to guard
    against: points_remaining simply stops falling, which is what "research is
    frozen" has to look like.
    """
    axis_multiplier = 1.0 - c.POLITICS_RESEARCH_SPAN * _fraction(nation_data, nation)
    return axis_multiplier * effect_multiplier(nation_data, nation, "research")


def resource_multiplier(nation_data, nation, resource):
    """What this nation multiplies one resource's produced income by."""
    return effect_multiplier(nation_data, nation, resource)


#: The axis carved into five named bands, libertarian first. Each entry is
#: (highest value in the band, what to call it, its c.UI_COLORS palette name).
#:
#: One table rather than two, because the word and the color are the same
#: statement made twice: a screen that called a nation "Statist" and painted it
#: red would be telling the reader two different things about one number. The
#: centre band is yellow, so a map nobody has authored yet opens all one color.
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

    # Do this after political drift, before combat/economy/research resolve.
    # An activated policy becomes effective on the third processed turn; a
    # cancellation completes on the next one.  Losing eligibility is immediate
    # and removes the effects before any phase of that turn can use them.
    for name, stats in map_screen.nation_data.items():
        if name == "GLOBAL_EVENTS" or name in c.UNPLAYABLE_NATIONS:
            continue
        reconcile_policy(map_screen.nation_data, name)
        for policy_id, state in tuple(policy_states(map_screen.nation_data, name).items()):
            if state["status"] == POLICY_ACTIVE:
                continue
            turns_left = max(0, int(state.get("turns_remaining", 0)) - 1)
            if state["status"] == POLICY_ACTIVATING and turns_left == 0:
                stats[POLICY_KEY][policy_id] = {"status": POLICY_ACTIVE, "turns_remaining": 0}
            elif state["status"] == POLICY_CANCELLING and turns_left == 0:
                stats[POLICY_KEY].pop(policy_id, None)
            else:
                stats[POLICY_KEY][policy_id]["turns_remaining"] = turns_left
        if not stats.get(POLICY_KEY):
            stats.pop(POLICY_KEY, None)
