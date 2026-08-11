"""Summits: two AI nations talk to each other and come away with obligations.

Everything else in this branch is one nation reasoning on its own. This is the
piece where two of them work something out between themselves -- and where, if
you turn ABSOLUTE on and are patient, the world starts running on agreements you
were never part of and can read about afterwards.

The transcript is not the point. The point is what the transcript is turned
into: whitelisted, validated terms that become commitments the ordinary
heuristic layer then honours or betrays, at a price it remembers. Nothing here
is trusted for state -- the model can say anything it likes, and only terms that
survive validation change the game.

Cost is bounded by construction. Pairs are capped, each pair is a single job in
the batch with its exchanges sequential inside it, and a pair that has just met
will not meet again for several turns. Off entirely unless both nations are
model-driven, so FULL and below pay nothing.
"""

import data.constants as c
from data import queries
from data.platform import IS_WEB
from map_logic.ai import ai_commitments, ai_personality


def enabled():
    """Summits are desktop-only, like every other networked part of the AI."""
    return not IS_WEB


def pressure(world, a, b, scenario_settings=None):
    """How much these two have to talk about, 0..1.

    Pairs with a reason to reach an understanding, roughly in the order a
    historian would expect: co-belligerents who have not formalised anything,
    exhausted enemies, friends without a bloc, and neighbours with a grievance
    that has not yet become a war.
    """
    from map_logic.ai import ai_opinion

    nation_data = world.nation_data
    score = 0.0

    a_enemies = set(queries.get_enemies(a, nation_data))
    b_enemies = set(queries.get_enemies(b, nation_data))

    if a_enemies & b_enemies and not queries.are_in_same_faction(a, b, nation_data):
        score += c.AI_PRESSURE_COMMON_ENEMY

    if b in a_enemies:
        weariness = min(ai_opinion.war_weariness(world, a, b),
                        ai_opinion.war_weariness(world, b, a))
        score += c.AI_PRESSURE_WEARY_WAR * weariness
    else:
        relation = world.relation(a, b)
        if relation > 0 and not nation_data.get(a, {}).get("faction"):
            score += c.AI_PRESSURE_FRIENDLY * min(1.0, relation / 100.0)

        contested = (world.claim_pressure.get((b, a), 0) + world.claim_pressure.get((a, b), 0))
        if contested and relation > c.AI_PRESSURE_SALVAGEABLE_RELATION:
            score += c.AI_PRESSURE_CONTESTED

        if b in world.neighbors.get(a, ()):
            score += c.AI_PRESSURE_NEIGHBOUR

    # Nobody wants a pact with a nation that does not keep them.
    score *= (0.5 + 0.5 * ai_commitments.reputation(nation_data, b))
    return max(0.0, min(1.0, score))


def select_pairs(world, ai_nations, is_model_driven, total_turns, limit=None):
    """The pairs worth convening this turn, best first.

    Both sides must be model-driven -- a summit is a conversation, and half a
    conversation is nothing. One meeting per nation per turn, so a great power
    does not spend its whole turn in summits.
    """
    limit = c.AI_NEGOTIATION_MAX_PAIRS if limit is None else limit
    eligible = sorted(n for n in ai_nations if is_model_driven(n))

    scored = []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            if _on_cooldown(world.nation_data, a, b, total_turns):
                continue
            value = pressure(world, a, b)
            if value >= c.AI_NEGOTIATION_MIN_PRESSURE:
                scored.append((value, a, b))

    scored.sort(key=lambda row: (-row[0], row[1], row[2]))

    taken, pairs = set(), []
    for value, a, b in scored:
        if a in taken or b in taken:
            continue
        taken.update((a, b))
        pairs.append({"a": a, "b": b, "pressure": value, "transcript": [], "terms": []})
        if len(pairs) >= limit:
            break
    return pairs


def _on_cooldown(nation_data, a, b, total_turns):
    log = nation_data.get(a, {}).get("summit_log") or {}
    last = log.get(b)
    return last is not None and (total_turns - last) < c.AI_NEGOTIATION_COOLDOWN


def record_summit(nation_data, a, b, total_turns):
    for owner, partner in ((a, b), (b, a)):
        nation_data.setdefault(owner, {}).setdefault("summit_log", {})[partner] = total_turns


# ----------------------------------------------------------------------------
# Turning what was said into what is true
# ----------------------------------------------------------------------------

def validate_terms(world, a, b, raw_terms):
    """Keeps only the terms these two could actually agree to.

    The model is not trusted for state. An unknown type, a country that does not
    exist, a promise about somebody's own territory -- all dropped, silently and
    individually, so one bad clause does not void an otherwise sound agreement.
    """
    if not isinstance(raw_terms, list):
        return []

    nation_data = world.nation_data
    out = []
    for raw in raw_terms[:c.AI_NEGOTIATION_MAX_TERMS]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type", "")).upper().strip()
        if kind not in ai_commitments.TYPES:
            continue

        target = raw.get("target")
        target = str(target).strip() if target else None
        if kind in ai_commitments.NEEDS_TARGET:
            if not target or target not in nation_data or target in (a, b):
                continue
            if kind == ai_commitments.JOINT_WAR and queries.are_in_same_faction(a, target, nation_data):
                continue
        else:
            target = None

        if kind == ai_commitments.NON_AGGRESSION and queries.are_at_war(a, b, nation_data):
            # Stopping a war is a ceasefire, which is a different instrument.
            continue

        try:
            turns = int(raw.get("turns", c.AI_NEGOTIATION_DEFAULT_TURNS))
        except (TypeError, ValueError):
            turns = c.AI_NEGOTIATION_DEFAULT_TURNS
        turns = max(1, min(c.AI_NEGOTIATION_MAX_TERM_TURNS, turns))

        params = {}
        if kind == ai_commitments.RESOURCE_TRANSFER:
            resource = str(raw.get("resource", "")).lower()
            if resource not in ("materials", "fuel"):
                continue
            try:
                amount = int(raw.get("amount", 0))
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            giver = str(raw.get("from", a)).strip()
            if giver not in (a, b):
                giver = a
            params = {"resource": resource, "amount": amount, "from": giver}

        out.append({"type": kind, "target": target, "turns": turns, "params": params})
    return out


def apply_terms(map_screen, a, b, terms, total_turns):
    """Turns validated terms into commitments, and returns what was agreed."""
    made = []
    for term in terms:
        entry = ai_commitments.make(
            map_screen.nation_data, a, b, term["type"], target=term.get("target"),
            turns=term["turns"], params=term.get("params"), made_turn=total_turns)
        if entry:
            made.append(term)
    return made


def describe_terms(terms):
    """The agreement in a line, for the log and for the player's dispatch."""
    parts = []
    for term in terms:
        kind = term["type"].replace("_", " ").lower()
        if term.get("target"):
            parts.append(f"{kind} against {term['target']} ({term['turns']} turns)")
        elif term["type"] == ai_commitments.RESOURCE_TRANSFER:
            p = term["params"]
            parts.append(f"{p['from']} to send {p['amount']} {p['resource']}")
        else:
            parts.append(f"{kind} ({term['turns']} turns)")
    return "; ".join(parts)


# ----------------------------------------------------------------------------
# Prompts
# ----------------------------------------------------------------------------

def opening_prompt(world, speaker, listener, scenario_settings=None):
    temperament = ai_personality.describe(world.nation_data, speaker, scenario_settings)
    return (
        f"You are the leader of {speaker}, meeting the leader of {listener} in private. "
        f"Your temperament: {temperament}. "
        "Say what you want from them and what you are prepared to offer, in two sentences at most. "
        "Speak in character. Reply ONLY with JSON: "
        '{"message": "what you say"}'
    )


def reply_prompt(world, speaker, listener, scenario_settings=None):
    temperament = ai_personality.describe(world.nation_data, speaker, scenario_settings)
    return (
        f"You are the leader of {speaker}, in private talks with {listener}. "
        f"Your temperament: {temperament}. "
        "Answer them in two sentences at most, in character. Reply ONLY with JSON: "
        '{"message": "what you say"}'
    )


def closing_prompt(world, speaker, listener, scenario_settings=None):
    """The one call that can change the world, so it is the strictest."""
    return (
        f"You are the leader of {speaker}, closing private talks with {listener}. "
        "State what, if anything, the two of you actually agreed. Promise only what you mean to keep: "
        "breaking an agreement will be remembered against you for a long time.\n"
        "Valid term types: 'NON_AGGRESSION' (no target), 'JOINT_WAR' (target = the country you will "
        "fight together), 'RESOURCE_TRANSFER' (resource = 'materials' or 'fuel', amount, from = which "
        "of you sends it), 'SPHERE' (target = a country the other of you will leave alone), "
        "'MILITARY_ACCESS' (no target).\n"
        "If you agreed nothing, say so with an empty terms list -- that is a normal outcome.\n"
        "Reply ONLY with JSON: "
        '{"agreed": true, "terms": [{"type": "NON_AGGRESSION", "turns": 20}], '
        '"message": "your closing words"}'
    )
