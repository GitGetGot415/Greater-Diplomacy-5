"""Promises nations make to each other, and what happens when they break them.

This is the half of AI-to-AI diplomacy that has to exist for the other half to
mean anything. A summit that produces a transcript and nothing else is chat; a
summit that produces an obligation the heuristic layer then honours -- or
betrays, at a price it remembers for sixty turns -- is diplomacy.

Nothing here needs a model. Commitments are ordinary data on nation_data, so
they serialize with everything else, and the rules that read them are the same
ones that decide wars and answer proposals. ai_negotiation is one way to create
them; it is not the only way one could.

Stdlib and `data` only.
"""

import data.constants as c
from data import queries
from map_logic.ai import ai_personality

#: What two nations can promise each other. Anything not on this list is
#: discarded when a transcript is turned into state -- the model proposes,
#: the whitelist disposes.
NON_AGGRESSION = "NON_AGGRESSION"
JOINT_WAR = "JOINT_WAR"
RESOURCE_TRANSFER = "RESOURCE_TRANSFER"
SPHERE = "SPHERE"
MILITARY_ACCESS = "MILITARY_ACCESS"

TYPES = (NON_AGGRESSION, JOINT_WAR, RESOURCE_TRANSFER, SPHERE, MILITARY_ACCESS)

#: Which types need a third country named, and which do not.
NEEDS_TARGET = (JOINT_WAR, SPHERE)

ACTIVE, HONORED, BROKEN = "ACTIVE", "HONORED", "BROKEN"


def all_for(nation_data, nation):
    return nation_data.get(nation, {}).get("ai_commitments") or []


def active_with(nation_data, nation, partner, kind=None):
    """Live commitments between two nations, optionally of one kind."""
    return [entry for entry in all_for(nation_data, nation)
            if entry.get("status") == ACTIVE
            and entry.get("with") == partner
            and (kind is None or entry.get("type") == kind)]


def has_non_aggression(nation_data, nation, partner):
    return bool(active_with(nation_data, nation, partner, NON_AGGRESSION))


def joint_war_target(nation_data, nation, partner):
    """The enemy these two agreed to fight together, if they did."""
    for entry in active_with(nation_data, nation, partner, JOINT_WAR):
        if entry.get("target"):
            return entry["target"]
    return None


def is_sphered(nation_data, nation, other):
    """Whether `nation` agreed to keep its hands off somebody `other` claims."""
    return {entry.get("target") for entry in active_with(nation_data, nation, other, SPHERE)}


def make(nation_data, a, b, kind, target=None, turns=20, params=None, made_turn=0):
    """Records a promise on both sides. Returns the entry, or None if invalid.

    Mirrored deliberately: a commitment only one party remembers is not a
    promise, and the wronged side has to be able to notice it was broken.
    """
    if kind not in TYPES or a == b:
        return None
    if a not in nation_data or b not in nation_data:
        return None
    if kind in NEEDS_TARGET and (not target or target not in nation_data):
        return None

    turns = max(1, int(turns))
    entry_id = f"{a}|{b}|{kind}|{made_turn}"

    for owner, partner in ((a, b), (b, a)):
        entry = {
            "id": entry_id, "with": partner, "type": kind, "target": target,
            "params": dict(params or {}), "turns_left": turns,
            "made_turn": made_turn, "status": ACTIVE,
        }
        # Replace rather than stack: agreeing the same thing twice is one promise.
        existing = nation_data[owner].setdefault("ai_commitments", [])
        existing[:] = [e for e in existing
                       if not (e.get("with") == partner and e.get("type") == kind
                               and e.get("target") == target and e.get("status") == ACTIVE)]
        existing.append(entry)

    return nation_data[a]["ai_commitments"][-1]


def war_restraint(nation_data, nation, target, scenario_settings=None):
    """How much a promise not to attack actually holds this nation back, 0..1.

    Scaled by loyalty, so a faithless country will break a pact when the prize
    is big enough and a loyal one very nearly will not. A pact that binds
    everyone identically would just be a rule; this is a temperament.
    """
    if not has_non_aggression(nation_data, nation, target):
        return 0.0
    loyalty = ai_personality.trait(nation_data, nation, "loyalty", scenario_settings)
    return c.AI_COMMITMENT_WEIGHT * (c.AI_COMMITMENT_MIN_HOLD + (1.0 - c.AI_COMMITMENT_MIN_HOLD) * loyalty)


def reputation(nation_data, nation):
    """Share of this nation's settled promises that it actually kept, 0..1.

    Read by everyone else's willingness to deal with it, so a serial betrayer
    ends up isolated without any rule saying so. A nation with no record yet is
    given the benefit of the doubt.
    """
    settled = [e for e in all_for(nation_data, nation) if e.get("status") in (HONORED, BROKEN)]
    if not settled:
        return c.AI_DEFAULT_REPUTATION
    kept = sum(1 for e in settled if e["status"] == HONORED)
    return kept / float(len(settled))


def _settle(nation_data, nation, entry, status):
    entry["status"] = status
    entry["turns_left"] = 0


def _find_mirror(nation_data, partner, entry_id):
    for other in all_for(nation_data, partner):
        if other.get("id") == entry_id:
            return other
    return None


def tick(map_screen):
    """Ages every commitment a turn, settling the ones that ended.

    A promise kept to its end earns goodwill from both sides. A promise broken
    costs the breaker a grudge that does not fade -- REL_MOD_BROKEN_COMMITMENT
    is stored with decay 0 precisely so this still stings in fifty turns, which
    is what makes keeping one worth anything.
    """
    from map_logic.diplomacy.diplomacy_events import log_global_event

    nation_data = map_screen.nation_data
    handled = set()

    for nation in list(nation_data):
        data = nation_data.get(nation)
        if not isinstance(data, dict):
            continue

        for entry in list(data.get("ai_commitments") or []):
            if entry.get("status") != ACTIVE:
                continue
            partner = entry.get("with")
            entry_id = entry.get("id")
            if entry_id in handled:
                continue

            violated, broken_by = _violation(nation_data, map_screen.map_data,
                                             nation, partner, entry)
            if violated:
                handled.add(entry_id)
                wronged = partner if broken_by == nation else nation
                _break(map_screen, nation_data, entry, broken_by, wronged, log_global_event)
                continue

            entry["turns_left"] = int(entry.get("turns_left", 0)) - 1
            if entry["turns_left"] <= 0:
                handled.add(entry_id)
                _honor(nation_data, nation, partner, entry)

    _clip_history(nation_data)


def _violation(nation_data, map_data, nation, partner, entry):
    """(was it violated, by whom). Only checks what is actually checkable.

    The war lists do not record who declared, so the aggressor is taken to be
    whichever side holds a wargoal against the other -- which needs the real
    map, since a wargoal is a claim on a province. Passing an empty map here
    made every betrayal look like the victim's fault and put the grudge on the
    wrong nation.

    If neither side has one, the pact is void but nobody is blamed: a war with
    no casus belli on either side is not evidence about who broke faith.
    """
    if entry.get("type") != NON_AGGRESSION:
        return False, None
    if not queries.are_at_war(nation, partner, nation_data):
        return False, None

    if queries.has_wargoal(nation, partner, nation_data, map_data):
        return True, nation
    if queries.has_wargoal(partner, nation, nation_data, map_data):
        return True, partner
    return True, None


def _break(map_screen, nation_data, entry, breaker, wronged, log_global_event):
    for owner in {entry.get("_owner"), breaker, wronged} - {None}:
        mirror = _find_mirror(nation_data, owner, entry.get("id"))
        if mirror:
            _settle(nation_data, owner, mirror, BROKEN)
            mirror["broken_by"] = breaker
    _settle(nation_data, breaker, entry, BROKEN)

    if not breaker:
        log_global_event(
            nation_data,
            f"COLLAPSE: the understanding between {entry.get('with')} and its partner has lapsed into war.")
        return

    queries.add_temporary_modifier(
        wronged, breaker, f"broken_{entry.get('type', '').lower()}",
        c.REL_MOD_BROKEN_COMMITMENT, nation_data,
        decay=0, turns=c.REL_MOD_BROKEN_COMMITMENT_TURNS,
        reason=f"broke a {entry.get('type', 'promise').replace('_', ' ').lower()}")

    log_global_event(
        nation_data,
        f"BETRAYAL: {breaker} has broken its {entry.get('type', 'agreement').replace('_', ' ').lower()} with {wronged}.")


def _honor(nation_data, nation, partner, entry):
    for owner, other in ((nation, partner), (partner, nation)):
        mirror = _find_mirror(nation_data, owner, entry.get("id")) or entry
        _settle(nation_data, owner, mirror, HONORED)
        queries.add_temporary_modifier(owner, other, "kept_word",
                                       c.REL_MOD_HONORED_COMMITMENT, nation_data)


def _clip_history(nation_data):
    """Keeps the settled record bounded; it lives in the save file."""
    for data in nation_data.values():
        if not isinstance(data, dict):
            continue
        entries = data.get("ai_commitments")
        if not entries or len(entries) <= c.AI_COMMITMENT_HISTORY_MAX:
            continue
        active = [e for e in entries if e.get("status") == ACTIVE]
        settled = [e for e in entries if e.get("status") != ACTIVE]
        keep = c.AI_COMMITMENT_HISTORY_MAX - len(active)
        data["ai_commitments"] = active + settled[-max(0, keep):]
