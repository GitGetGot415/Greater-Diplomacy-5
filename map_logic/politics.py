"""Domestic politics: drift on four axes and timed national policies.

Two Civilian axes (Political, Economic) and two Military axes (Quality,
Strategy) each move by ``POLITICS_STEP`` per processed turn while a direction
is selected. Every axis effect is a row of ``c.POLITICS_AXIS_EFFECTS``; the
systems that own each number read it through ``axis_effect``. Map authors can
set a country's starting coordinates. National policies have their own
activation and cancellation durations.

Damage means every point of damage a nation's units deal, attacking or
defending, plus bombardment. A lane fight is a simultaneous exchange with no
designated attacker, so "your armies deal more damage" can only sensibly be a
property of the army rather than of who moved first.

Stdlib and `data.constants` only, so it imports under Pyodide and can be
imported at module level from combat_rules without joining the queries cycle.
"""

from data.state_access import world_for, session_for
import data.constants as c

POLITICAL = "political"
ECONOMIC = "economic"
QUALITY = "quality"
STRATEGY = "strategy"
CIVILIAN = "civilian"
MILITARY = "military"

#: Position and drift live on nation_data[name]. Flat and defaulted, never
#: written at country-creation time: build_save_dict dumps nation_data verbatim
#: and snapshot_history copies scalars by value, so persistence costs nothing,
#: and reading through the accessors below covers every nation the base-template
#: merge in load_map never sees -- rebellions, splinter states, generated maps.
VALUE_KEY = "political_value"
DRIFT_KEY = "political_drift"
ECONOMIC_VALUE_KEY = "economic_value"
ECONOMIC_DRIFT_KEY = "economic_drift"
QUALITY_VALUE_KEY = "quality_value"
QUALITY_DRIFT_KEY = "quality_drift"
STRATEGY_VALUE_KEY = "strategy_value"
STRATEGY_DRIFT_KEY = "strategy_drift"

#: Every axis in screen order. ``ends`` names the POLITICS_MIN and
#: POLITICS_MAX ends; ``bands`` names the five compass bands from min to max.
AXES = (
    {"id": POLITICAL, "group": CIVILIAN, "name": "Political", "value_key": VALUE_KEY, "drift_key": DRIFT_KEY,
     "ends": ("Libertarian", "Authoritarian"),
     "bands": ("Libertarian", "Liberal", "Centrist", "Statist", "Authoritarian")},
    {"id": ECONOMIC, "group": CIVILIAN, "name": "Economic", "value_key": ECONOMIC_VALUE_KEY, "drift_key": ECONOMIC_DRIFT_KEY,
     "ends": ("Planned", "Market"),
     "bands": ("Planned", "Planned-leaning", "Mixed", "Market-leaning", "Market")},
    {"id": QUALITY, "group": MILITARY, "name": "Quality", "value_key": QUALITY_VALUE_KEY, "drift_key": QUALITY_DRIFT_KEY,
     "ends": ("Professional", "Numerous"),
     "bands": ("Professional", "Professional-leaning", "Balanced", "Numerous-leaning", "Numerous")},
    {"id": STRATEGY, "group": MILITARY, "name": "Strategy", "value_key": STRATEGY_VALUE_KEY, "drift_key": STRATEGY_DRIFT_KEY,
     "ends": ("Offensive", "Defensive"),
     "bands": ("Offensive", "Offensive-leaning", "Balanced", "Defensive-leaning", "Defensive")},
)
AXES_BY_ID = {axis["id"]: axis for axis in AXES}
DRIFT_KEYS = tuple(axis["drift_key"] for axis in AXES)
VALUE_KEYS = tuple(axis["value_key"] for axis in AXES)
#: Effect name -> the axis that owns it.
EFFECT_AXES = {effect: axis for axis, effects in c.POLITICS_AXIS_EFFECTS.items() for effect in effects}

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
    """Constrain a compass coordinate to the shared integer range."""
    try:
        return max(c.POLITICS_MIN, min(c.POLITICS_MAX, int(round(float(value)))))
    except (TypeError, ValueError, OverflowError):
        return c.POLITICS_START


def _read_value(nation_data, nation, key):
    return clamp(nation_data.get(nation, {}).get(key, c.POLITICS_START))


def axis_value(nation_data, nation, axis):
    """Where this nation sits on one axis, POLITICS_MIN..POLITICS_MAX. Centre by default."""
    return _read_value(nation_data or {}, nation, AXES_BY_ID[axis]["value_key"])


def value(nation_data, nation):
    """Where this nation sits on the political axis."""
    return axis_value(nation_data, nation, POLITICAL)


def economic_value(nation_data, nation):
    """Where the economy sits, from planned to market. Mixed by default."""
    return axis_value(nation_data, nation, ECONOMIC)


def _read_drift(nation_data, nation, key):
    try:
        raw = int(nation_data.get(nation, {}).get(key, 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(-1, min(1, raw))


def axis_drift(nation_data, nation, axis):
    """Which way one axis is heading: -1 toward POLITICS_MIN, 0 holding, +1 toward POLITICS_MAX.

    A direction persists until the player or AI changes it or the axis reaches
    an end.
    """
    return _read_drift(nation_data or {}, nation, AXES_BY_ID[axis]["drift_key"])


def drift(nation_data, nation):
    """Which way the political axis is heading: -1 libertarian, 0 holding, +1 authoritarian."""
    return axis_drift(nation_data, nation, POLITICAL)


def economic_drift(nation_data, nation):
    """Read the economic direction: -1 planned, 0 hold, +1 market."""
    return axis_drift(nation_data, nation, ECONOMIC)


def set_axis_value(nation_data, nation, axis, new_value):
    """Pins a nation's position on one axis outright. The map editor's starting value."""
    nation_data.setdefault(nation, {})[AXES_BY_ID[axis]["value_key"]] = clamp(new_value)


def set_axis_drift(nation_data, nation, axis, direction):
    """Points one axis toward an end, or stops it."""
    nation_data.setdefault(nation, {})[AXES_BY_ID[axis]["drift_key"]] = max(-1, min(1, int(direction)))


def set_value(nation_data, nation, new_value):
    """Pins a nation's political position outright. The map editor's starting value."""
    set_axis_value(nation_data, nation, POLITICAL, new_value)


def set_drift(nation_data, nation, direction):
    """Points a nation at one end of the political axis, or stops it."""
    set_axis_drift(nation_data, nation, POLITICAL, direction)


def set_economic_value(nation_data, nation, new_value):
    """Set a scenario's starting economic position."""
    set_axis_value(nation_data, nation, ECONOMIC, new_value)


def set_economic_drift(nation_data, nation, direction):
    """Point a nation toward a planned or market economy, or hold."""
    set_axis_drift(nation_data, nation, ECONOMIC, direction)


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


def requirements_met(nation_data, nation, policy_id, *, political_value=None):
    """Whether a policy meets its requirement at the current or projected position."""
    definition = policy(policy_id)
    if definition is None:
        return False
    if political_value is None:
        political_value = value(nation_data, nation)
    return (("max_politics" not in definition or political_value < definition["max_politics"])
            and ("min_politics" not in definition or political_value > definition["min_politics"]))


def requirement_text(policy_id, *, compact=False):
    """A short, exact explanation of a policy's political requirement."""
    definition = policy(policy_id)
    if definition is None:
        return "Unavailable"
    prefix = "Politics" if compact else "Requires politics"
    if "max_politics" in definition:
        return f"{prefix} < {definition['max_politics']:+d}"
    if "min_politics" in definition:
        return f"{prefix} > {definition['min_politics']:+d}"
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
    """Immediately remove every policy whose political requirement was lost."""
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


def effect_at(effect, position):
    """An axis effect's value at a position, interpolated between the axis ends.

    Previews use this for a projected position; ``axis_effect`` reads a
    country's current one.
    """
    low, high = c.POLITICS_AXIS_EFFECTS[EFFECT_AXES[effect]][effect]
    fraction = (clamp(position) - c.POLITICS_MIN) / float(c.POLITICS_MAX - c.POLITICS_MIN)
    return low * (1.0 - fraction) + high * fraction


def axis_effect(nation_data, nation, effect):
    """One axis effect at this nation's current position."""
    return effect_at(effect, axis_value(nation_data, nation, EFFECT_AXES[effect]))


def territory_damage_multiplier(nation_data, nation, province):
    """Strategy's damage modifier for this nation's units fighting on one tile.

    Core territory is a tile the nation has cored, whoever holds it now, so a
    country retaking its own land keeps its core modifier. Sea, unowned and
    enemy tiles are non-core. Under the Disable Cores rule, every tile the
    nation owns counts as core.
    """
    if c.DISABLE_CORES:
        is_core = province.get("owner") == nation
    else:
        is_core = nation in province.get("cores", ())
    return axis_effect(nation_data, nation, "core_territory_damage" if is_core else "non_core_territory_damage")


def factory_output_multiplier(nation_data, nation):
    return axis_effect(nation_data, nation, "factory_output")


def damage_multiplier(nation_data, nation):
    """What this nation's units multiply their damage by: Quality, then policy."""
    return axis_effect(nation_data, nation, "damage") * effect_multiplier(nation_data, nation, "damage")


def research_multiplier(nation_data, nation):
    """Normal research multiplier, including policy.

    Fully authoritarian countries pause normal research. Funded research points
    bypass this multiplier.
    """
    return axis_effect(nation_data, nation, "research") * effect_multiplier(nation_data, nation, "research")


def resource_multiplier(nation_data, nation, resource):
    """What this nation's policies multiply one resource's produced income by."""
    return effect_multiplier(nation_data, nation, resource)


#: Every axis shares the same five score ranges: each band's upper bound and
#: the c.UI_COLORS palette it is drawn in, with yellow for the centre. Labels
#: come from each axis's ``bands``.
_BAND_BOUNDS = (-7, -3, 2, 6, c.POLITICS_MAX)
_BAND_PALETTES = ("light_blue", "green", "yellow", "orange", "red")
#: The political axis's (bound, label, palette) rows.
BANDS = tuple(zip(_BAND_BOUNDS, AXES_BY_ID[POLITICAL]["bands"], _BAND_PALETTES))


def _band_index(position):
    position = clamp(position)
    for index, bound in enumerate(_BAND_BOUNDS):
        if position <= bound:
            return index
    return len(_BAND_BOUNDS) - 1


def band(political_value):
    """The (bound, label, palette) entry a political value falls in."""
    return BANDS[_band_index(political_value)]


def axis_label(axis, position):
    """A short word for a position on one axis, for screens and tooltips."""
    return AXES_BY_ID[axis]["bands"][_band_index(position)]


def label(political_value):
    """A short word for a political position."""
    return axis_label(POLITICAL, political_value)


def economic_label(position):
    """Return the economic label for the position's compass band."""
    return axis_label(ECONOMIC, position)


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
    """Advance each axis and clear its direction when it reaches an end.

    Returns the countries whose Quality position moved, whose units' maximum
    health the turn then rescales.
    """
    world_state = world_for(context)
    quality_moved = set()
    for name, stats in world_state.nation_data.items():
        if name in c.UNPLAYABLE_NATIONS:
            continue

        for axis in AXES:
            direction = _read_drift(world_state.nation_data, name, axis["drift_key"])
            if direction:
                before = _read_value(world_state.nation_data, name, axis["value_key"])
                position = advance(before, direction)
                stats[axis["value_key"]] = position
                if axis["id"] == QUALITY and position != before:
                    quality_moved.add(name)
                if at_limit(position):
                    stats[axis["drift_key"]] = 0

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
    return quality_moved
