"""Domestic politics: political and economic drift and timed national policies.

The vertical axis trades army damage against core province manpower. The
horizontal axis trades factory output against research speed. Each axis moves
by ``POLITICS_STEP`` per processed turn while a direction is selected. Map
authors can set a country's starting coordinates. National policies have their
own activation and cancellation durations.

Damage means every point of damage a nation's units deal, attacking or
defending, plus bombardment. A lane fight is a simultaneous exchange with no
designated attacker, so "your armies deal more damage" can only sensibly be a
property of the army rather than of who moved first.

Stdlib and `data.constants` only, so it imports under Pyodide and can be
imported at module level from combat_rules without joining the queries cycle.
"""

from operator import gt, lt

from data.state_access import world_for, session_for
import data.constants as c

#: Position and drift live on nation_data[name]. Flat and defaulted, never
#: written at country-creation time: build_save_dict dumps nation_data verbatim
#: and snapshot_history copies scalars by value, so persistence costs nothing,
#: and reading through the accessors below covers every nation the base-template
#: merge in load_map never sees -- rebellions, splinter states, generated maps.
VALUE_KEY = "political_value"
DRIFT_KEY = "political_drift"
ECONOMIC_VALUE_KEY = "economic_value"
ECONOMIC_DRIFT_KEY = "economic_drift"
MIXED_BAND_LIMIT = 2

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
        "min_economy": MIXED_BAND_LIMIT,
        "effects": {"research": 1.50, "manpower": 0.80, "materials": 0.90, "fuel": 0.90},
        "effect_lines": ("Research +50%", "Manpower -20%", "Materials -10%", "Fuel -10%"),
    },
    {
        "id": "prioritize_civilian_needs",
        "name": "Prioritize Civilian Needs",
        "min_economy": -MIXED_BAND_LIMIT - 1,
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
    """Constrain a compass coordinate to the shared integer range."""
    try:
        return max(c.POLITICS_MIN, min(c.POLITICS_MAX, int(round(float(value)))))
    except (TypeError, ValueError, OverflowError):
        return c.POLITICS_START


def _read_value(nation_data, nation, key):
    return clamp(nation_data.get(nation, {}).get(key, c.POLITICS_START))


def value(nation_data, nation):
    """Where this nation sits, POLITICS_MIN..POLITICS_MAX. Centre by default."""
    return _read_value(nation_data or {}, nation, VALUE_KEY)


def economic_value(nation_data, nation):
    """Where the economy sits, from planned to market. Mixed by default."""
    return _read_value(nation_data or {}, nation, ECONOMIC_VALUE_KEY)


def _read_drift(nation_data, nation, key):
    try:
        raw = int(nation_data.get(nation, {}).get(key, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(-1, min(1, raw))


def drift(nation_data, nation):
    """Which way it is heading: -1 libertarian, 0 holding, +1 authoritarian.

    A direction persists until the player or AI changes it or the axis reaches
    an end.
    """
    return _read_drift(nation_data or {}, nation, DRIFT_KEY)


def economic_drift(nation_data, nation):
    """Read the economic direction: -1 planned, 0 hold, +1 market."""
    return _read_drift(nation_data or {}, nation, ECONOMIC_DRIFT_KEY)


def set_value(nation_data, nation, new_value):
    """Pins a nation's position outright. The map editor's starting value."""
    nation_data.setdefault(nation, {})[VALUE_KEY] = clamp(new_value)


def set_drift(nation_data, nation, direction):
    """Points a nation at one end of the axis, or stops it."""
    nation_data.setdefault(nation, {})[DRIFT_KEY] = max(-1, min(1, int(direction)))


def set_economic_value(nation_data, nation, new_value):
    """Set a scenario's starting economic position."""
    nation_data.setdefault(nation, {})[ECONOMIC_VALUE_KEY] = clamp(new_value)


def set_economic_drift(nation_data, nation, direction):
    """Point a nation toward a planned or market economy, or hold."""
    nation_data.setdefault(nation, {})[ECONOMIC_DRIFT_KEY] = max(-1, min(1, int(direction)))


def advance(position, direction):
    """Calculate the next position on either axis."""
    return clamp(position + direction * c.POLITICS_STEP)


def can_shift(position, direction):
    """Allow holding anywhere and moving only when there is space."""
    return direction == 0 or advance(position, direction) != position


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


_POLICY_REQUIREMENTS = (
    ("max_politics", "politics", "<", value, lt),
    ("min_politics", "politics", ">", value, gt),
    ("max_economy", "economy", "<", economic_value, lt),
    ("min_economy", "economy", ">", economic_value, gt),
)


def requirements_met(nation_data, nation, policy_id):
    """Whether a policy can be activated at the country's current position."""
    definition = policy(policy_id)
    if definition is None:
        return False
    return all(compare(read(nation_data, nation), definition[key])
               for key, _axis, _symbol, read, compare in _POLICY_REQUIREMENTS if key in definition)


def requirement_text(policy_id):
    """A short, exact explanation of a policy's compass requirements."""
    definition = policy(policy_id)
    if definition is None:
        return "Unavailable"
    bounds = [f"{axis} {symbol} {definition[key]:+d}"
              for key, axis, symbol, _read, _compare in _POLICY_REQUIREMENTS if key in definition]
    return "Requires " + " and ".join(bounds) if bounds else "No compass requirement"


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
    """Immediately remove every policy whose compass requirement was lost."""
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


def _axis_strength(position):
    return position / float(c.POLITICS_MAX)


def axis_damage_multiplier(position):
    return 1.0 + c.POLITICS_DAMAGE_SPAN * _axis_strength(position)


def axis_core_manpower_multiplier(position):
    return 1.0 - c.POLITICS_CORE_MANPOWER_SPAN * _axis_strength(position)


def axis_factory_multiplier(position):
    return 1.0 - c.ECONOMICS_FACTORY_SPAN * _axis_strength(position)


def factory_output_multiplier(nation_data, nation):
    return axis_factory_multiplier(economic_value(nation_data, nation))


def axis_research_multiplier(position):
    return 1.0 + c.ECONOMICS_RESEARCH_SPAN * _axis_strength(position)


def damage_multiplier(nation_data, nation):
    """What this nation's units multiply their damage by, including policy."""
    axis_multiplier = axis_damage_multiplier(value(nation_data, nation))
    return axis_multiplier * effect_multiplier(nation_data, nation, "damage")


def research_multiplier(nation_data, nation):
    """What this nation multiplies its research points by, including policy.

    Zero at the fully planned end is deliberate and not a floor to guard
    against: points_remaining simply stops falling, which is what "research is
    frozen" has to look like.
    """
    axis_multiplier = axis_research_multiplier(economic_value(nation_data, nation))
    return axis_multiplier * effect_multiplier(nation_data, nation, "research")


def resource_multiplier(nation_data, nation, resource):
    """What this nation multiplies one resource's produced income by."""
    return effect_multiplier(nation_data, nation, resource)


#: Both axes share the same five score ranges. Each row contains the upper
#: bound, political label, political palette, and economic label. The political
#: label and palette describe the same band, with yellow for the centre.
_COMPASS_BANDS = (
    (-7, "Libertarian", "light_blue", "Planned"),
    (-3, "Liberal", "green", "Planned-leaning"),
    (MIXED_BAND_LIMIT, "Centrist", "yellow", "Mixed"),
    (6, "Statist", "orange", "Market-leaning"),
    (c.POLITICS_MAX, "Authoritarian", "red", "Market"),
)
BANDS = tuple(row[:3] for row in _COMPASS_BANDS)


def _band_index(position):
    position = clamp(position)
    for index, row in enumerate(_COMPASS_BANDS):
        if position <= row[0]:
            return index
    return len(_COMPASS_BANDS) - 1


def band(political_value):
    """The (bound, label, palette) entry a value falls in."""
    return BANDS[_band_index(political_value)]


def label(political_value):
    """A short word for a position, for screens and tooltips."""
    return band(political_value)[1]


def economic_label(position):
    """Return the economic label for the position's compass band."""
    return _COMPASS_BANDS[_band_index(position)][3]


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


def tick(context):
    """Advance each axis and clear its direction when it reaches an end."""
    world_state = world_for(context)
    for name, stats in world_state.nation_data.items():
        if name in c.UNPLAYABLE_NATIONS:
            continue

        for value_key, drift_key in ((VALUE_KEY, DRIFT_KEY), (ECONOMIC_VALUE_KEY, ECONOMIC_DRIFT_KEY)):
            direction = _read_drift(world_state.nation_data, name, drift_key)
            if direction:
                position = advance(_read_value(world_state.nation_data, name, value_key), direction)
                stats[value_key] = position
                if at_limit(position):
                    stats[drift_key] = 0

    # Do this after political drift, before combat/economy/research resolve.
    # An activated policy becomes effective on the third processed turn; a
    # cancellation completes on the next one.  Losing eligibility is immediate
    # and removes the effects before any phase of that turn can use them.
    for name, stats in world_state.nation_data.items():
        if name == "GLOBAL_EVENTS" or name in c.UNPLAYABLE_NATIONS:
            continue
        reconcile_policy(world_state.nation_data, name)
        for policy_id, state in tuple(policy_states(world_state.nation_data, name).items()):
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
