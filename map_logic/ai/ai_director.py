"""Lets the model decide which of a nation's legal options it actually takes.

Until now the model wrote prose. Every decision -- accept or reject, declare war
or not, who to ally with -- was made in Python before it was ever called, and
the prompt then told it what had been decided so it could phrase it. The one
lever it had was a follow-up action applied afterwards, which bypassed the war
prerequisites entirely (see the note in diplomacy_processor).

Here it chooses. The heuristic layer builds the menu -- scored, with reasons,
and every entry already checked against cooldowns, truces, wargoals and puppet
status -- and the model picks from it. It cannot invent an action, name a
country that does not exist, or start a war the rules forbid, because those
never make it onto the menu. That invariant is what makes this safe to hand to a
language model at all, and tests/test_ai_candidates.py guards it.

One call per nation per turn, not one per action. And because the same reply
carries the wording, this call replaces the whole separate proactive-text batch
that used to run afterwards: strictly fewer requests per turn than before, while
doing considerably more.
"""

import json

import data.constants as c


def top_scored(candidates, limit):
    """What the heuristic layer would do on its own. Every fallback lands here."""
    return list(candidates[:limit])


def should_consult(candidates):
    """Whether this nation's choice is worth a request.

    Nothing to choose between means nothing to ask about. On a large map this is
    most nations most turns, and skipping them is the cheapest lever there is on
    what ABSOLUTE mode costs.
    """
    return len(candidates) > 1


def build_prompt(world, nation, candidates, limit, personality_note=""):
    """The menu, as the leader's staff would put it."""
    from map_logic.ai import ai_candidates

    lines = []
    for cand in candidates:
        lines.append(f"  [{cand.cid}] {ai_candidates.describe(cand)}")
    lines.append(f"  [{c.AI_DIRECTOR_NONE_CID}] do nothing this turn")

    system = (
        f"You are the leader of {nation} in a grand strategy game. "
        f"Your staff has prepared the options below. All of them are legal and "
        f"ready to execute this turn, and the staff rating is their own estimate "
        f"of how well each serves the nation.\n"
        f"{personality_note}"
        f"Choose at most {limit}. You may follow the ratings or overrule them, "
        f"but you may only choose from this list.\n\n"
        "Reply ONLY with a valid JSON object of this shape:\n"
        '{"picks": [0], "reason": "one sentence of why", '
        '"messages": {"0": "In-character text of the message that action sends"}}\n'
        "Every index in \"picks\" must appear in \"messages\"."
    )
    user = "Your options:\n" + "\n".join(lines) + "\n\nChoose."
    return system, user


def validate(reply, candidates, limit):
    """Turns a model reply into actual candidates, dropping anything it made up.

    Anything unrecognised, duplicated, or past the limit is discarded rather
    than argued with; an empty or unusable reply falls back to the heuristic's
    own order. There is deliberately no path here that produces an action the
    caller did not already offer.
    """
    if not isinstance(reply, dict):
        return top_scored(candidates, limit)

    by_cid = {cand.cid: cand for cand in candidates}
    picks = reply.get("picks")
    if isinstance(picks, (str, int)):
        picks = [picks]
    if not isinstance(picks, list):
        return top_scored(candidates, limit)

    chosen = []
    for raw in picks:
        cand = by_cid.get(str(raw).strip())
        if cand is not None and cand not in chosen:
            chosen.append(cand)
        if len(chosen) >= limit:
            break

    # An explicit "do nothing" is a real answer and must not be overridden by
    # the fallback -- otherwise the model can never decline to act.
    if not chosen and _declined(picks):
        return []

    return chosen or top_scored(candidates, limit)


def _declined(picks):
    return any(str(raw).strip() == c.AI_DIRECTOR_NONE_CID for raw in picks)


def messages_from(reply):
    """The in-character text per chosen index, if the model supplied any."""
    if not isinstance(reply, dict):
        return {}
    messages = reply.get("messages")
    if not isinstance(messages, dict):
        return {}
    return {str(k): str(v) for k, v in messages.items() if isinstance(v, str) and v.strip()}


def parse(raw_reply, candidates, limit):
    """(chosen candidates, {cid: message}) from one provider reply."""
    reply = raw_reply
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except (ValueError, TypeError):
            reply = None
    return validate(reply, candidates, limit), messages_from(reply)
