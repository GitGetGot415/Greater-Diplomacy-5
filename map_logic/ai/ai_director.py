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
import re

import data.constants as c

from map_logic.ai import ai_candidates, ai_prompts
from map_logic.diplomacy import diplomacy_messages


def top_scored(candidates, limit):
    """What the heuristic layer would do on its own. Every fallback lands here.

    A leader's own initiatives are left out: no staff rule asked for them, so
    the staff never take one on the leader's behalf.
    """
    return [cand for cand in candidates if not ai_candidates.is_initiative(cand)][:limit]


def _clashes(candidate, chosen):
    """Whether this pick cannot go out beside the ones already chosen.

    pending_diplomacy holds one proposal per country, and a country may have
    only one faction request pending, as for a player.
    """
    for other in chosen:
        if other.target == candidate.target:
            return True
        if (candidate.action in c.FACTION_REQUEST_ACTIONS
                and other.action in c.FACTION_REQUEST_ACTIONS):
            return True
    return False


def should_consult(candidates, wants_prose=False):
    """Whether this nation is worth a request.

    Nothing to choose between means nothing to ask about, and on a large map
    that is most nations most turns -- the cheapest lever there is on what
    ABSOLUTE mode costs.

    But the same reply carries the wording, so this was quietly deciding two
    things at once. A nation with exactly one legal option sent its canned line
    at every immersion level, including ABSOLUTE, whose entire purpose is that
    the world writes its own diplomacy: saves/generic message despite absolute
    ai is almost nothing but "We accept your proposal." Where the level would
    have written prose for this nation anyway, ask -- the choice is a formality
    and the wording is the point.
    """
    return len(candidates) > 1 or (wants_prose and len(candidates) > 0)


def _terms(candidate, nation, nation_data):
    """A trade's or treaty's terms as this country's own offer, or "".

    Without them the model wrote its message to an offer it could not see:
    "our surplus of [insert resource] for their surplus of [insert resource]".
    Labelled only "terms", they read as terms someone had sent: Switzerland
    answered its own trade offer with "We are interested in your proposal".
    """
    params = candidate.payload.get("parameters")
    lines = diplomacy_messages.describe_trade(params, viewer_is_proposer=True, viewer=nation,
                                              nation_data=nation_data) if params else []
    return f" -- your offer: {'; '.join(lines)}" if lines else ""


#: Words that answer a proposal. A director message always makes one, so these
#: mean the model thought the other country had offered first.
_ANSWERING_TEXT = re.compile(r"\byour (proposal|offer|terms)\b", re.IGNORECASE)


def reads_as_answer(message):
    """Whether a proposal's message answers a proposal nobody made."""
    return bool(message) and bool(_ANSWERING_TEXT.search(message))


#: An option's reason shorter than this is too generic to count as copied.
_MENU_COPY_MIN_LENGTH = 12


def copies_menu(message, candidates):
    """Whether a message quotes the menu it was chosen from.

    Italy sent "We request military access through Germany -- your own
    initiative, not a staff proposal -- passage through their territory": its
    option line, word for word. The check compares against the exact text the
    model was shown: the own-initiative note and every option's reason.
    """
    text = (message or "").lower()
    if not text:
        return False
    if any(part in text for part in ("own initiative", "staff proposal")):
        return True
    return any(len(note) >= _MENU_COPY_MIN_LENGTH and note.lower() in text
               for cand in candidates
               for note in (cand.rationale, ai_candidates.effect(cand)) if note)


#: Words of friendship or a deal, which no declaration of war says. The Soviet
#: Union declared war on Latvia with "we propose a peaceful transfer of the
#: territory", and the German Reich declared war on the Soviet Union with its
#: notebook's plans for Slovakia: "a joint venture ... mutually beneficial ...
#: exploring opportunities for cooperation".
_FRIENDLY_TEXT = re.compile(
    r"\b(propos\w*|offer\w*|cooperat\w*|co-operat\w*|mutual(ly)? benefi\w*|partnership\w*"
    r"|joint ventures?|explor\w* (the )?(opportunit\w*|possibilit\w*|ways)|open to discuss\w*"
    r"|friendship|strengthen\w* our (ties|bonds?|relations\w*|alliance|partnership))\b",
    re.IGNORECASE)


def reads_as_friendly(message):
    """Whether a message offers something, or speaks of friendship or a deal."""
    return bool(message) and bool(_FRIENDLY_TEXT.search(message))


def build_prompt(world, nation, candidates, limit, personality_note="", nation_data=None):
    """The menu, as the leader's staff would put it.

    The system half deliberately names nobody. ai_handler._combined_prompt now
    sends it after the world context, but when it went first, a single "You
    are the leader of X" at the top made every nation's prompt differ from its
    first line and cost a local model a full re-read of the whole world --
    around 13 of the 15 seconds a call takes. Who is being addressed is
    established in the context's own per-nation tail instead, which sits after
    everything the nations share.
    """

    lines = []
    for cand in candidates:
        lines.append(f"  [{cand.cid}] {ai_candidates.describe(cand)}"
                     f"{_terms(cand, nation, nation_data)}")
    lines.append(f"  [{c.AI_DIRECTOR_NONE_CID}] do nothing this turn")

    system = (
        f"You are the leader of a nation in a grand strategy game, named below. "
        f"Your staff has prepared the options at the end. All of them are legal and "
        f"ready to execute this turn, and the staff rating is their own estimate "
        f"of how well each serves the nation. Options marked as your own initiative "
        f"are proposals to countries you have been writing to that your staff did "
        f"not recommend; take one when your letters or your notebook give you a "
        f"reason to.\n"
        f"Choose at most {limit}, at most one per country. You may follow the "
        f"ratings or overrule them, but you may only choose from this list. "
        f"Doing nothing is a normal choice: most leaders make no proposal most turns.\n"
        f"Every option is your own move. Nobody has offered it to you, "
        f"so do not write as if you were answering one. "
        f"Each message is sent to the country its option names, and is about that "
        f"option's action and nothing else. Write to that "
        f"government directly, as 'you'. Where an option lists your offer, the message "
        f"must state those terms. A declaration of war declares the war: it proposes "
        f"and offers nothing. The staff ratings and notes are for you alone: "
        f"never quote them.\n\n"
        + ai_prompts.VOICE_RULE + ai_prompts.CONDUCT_RULE +
        "\nReply ONLY with a valid JSON object of this shape:\n"
        '{"picks": [0], "reason": "one sentence of why", '
        '"messages": {"0": "the message you send to that option\'s country"}}\n'
        "Every index in \"picks\" must appear in \"messages\"."
    )
    user = (f"{personality_note}You are the leader of {nation}.\n"
            "Your options:\n" + "\n".join(lines) + "\n\nChoose.")
    return system, user


def reply_schema(candidates, limit):
    """The JSON schema of build_prompt's reply.

    Ollama enforces it while it generates (see ai_handler.call_ollama). A pick
    can only be one of this nation's option IDs or "do nothing", so a pick
    always names an option on the menu. At least one pick is required, which
    makes "do nothing" an explicit choice. Each message is optional and can be
    keyed only by an option ID.
    """
    cids = [cand.cid for cand in candidates]
    return {
        "type": "object",
        "properties": {
            "picks": {"type": "array", "minItems": 1, "maxItems": limit,
                      "items": {"type": "string", "enum": cids + [c.AI_DIRECTOR_NONE_CID]}},
            "reason": {"type": "string"},
            "messages": {"type": "object", "additionalProperties": False,
                         "properties": {cid: {"type": "string"} for cid in cids}},
        },
        "required": ["picks", "reason", "messages"],
        "additionalProperties": False,
    }


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
        if cand is not None and cand not in chosen and not _clashes(cand, chosen):
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


def messages_from(reply, nation=None, nation_data=None, candidates=()):
    """The in-character text per chosen index, if the model supplied any.

    A line that talks about its own sender in the third person, or names the
    country it is sent to, is dropped rather than sent, and the proposal falls
    back to its canned line. Small models write
    "Switzerland accepts your offer" into a message already labelled as being
    from Switzerland; a dropped line costs one piece of flavour, a kept one
    reads as a bug. A line with placeholder or menu text is dropped the same way,
    and so is one that answers a proposal nobody made (reads_as_answer), one
    that quotes `candidates`, the menu it was chosen from (copies_menu), or a
    war declaration's that sounds friendly (reads_as_friendly).
    """

    if not isinstance(reply, dict):
        return {}
    messages = reply.get("messages")
    if not isinstance(messages, dict):
        return {}
    wars = {cand.cid for cand in candidates if cand.action == "WAR_DECLARATION"}
    targets = {cand.cid: cand.target for cand in candidates}
    return {str(k): str(v) for k, v in messages.items()
            if isinstance(v, str) and v.strip()
            and not ai_prompts.unusable_message(v, nation, nation_data,
                                                recipient=targets.get(str(k)))
            and not reads_as_answer(v)
            and not copies_menu(v, candidates)
            and not (str(k) in wars and reads_as_friendly(v))}


def parse(raw_reply, candidates, limit, nation=None, nation_data=None):
    """(chosen candidates, {cid: message}) from one provider reply."""
    reply = raw_reply
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except (ValueError, TypeError):
            reply = None
    return (validate(reply, candidates, limit),
            messages_from(reply, nation, nation_data, candidates))
