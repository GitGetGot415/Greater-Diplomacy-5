# ==========================================
# FALLBACK / MANUAL AI RESPONSES
# ==========================================
# Every line the AI says when the model is not consulted. These used to be a
# fifty-entry dict compiled into this file, one string per situation, so the
# same war produced the same sentence every time and nobody could add a line
# without editing Python. They now live in data/json/ai_responses.json, read
# through the same cache as unit_data.json and the rest -- see resolve() for
# the shape, and the _README key in the file itself for the authoring notes.

import random

from data import queries


#: Bands for the `strength` condition, as a ratio of our military strength to
#: theirs. Anything between the two reads as an even match.
STRENGTH_WEAKER = 0.7
STRENGTH_STRONGER = 1.4

#: Bands for the `opinion` condition, on get_relation_score's scale.
OPINION_HOSTILE = -20
OPINION_WARM = 25


def _situation(sender, target, nation_data, world=None, map_data=None):
    """What is true of these two right now, in the terms a `when` block uses.

    Everything here is either a direct read or already memoised on the turn's
    snapshot, so describing the situation costs nothing worth measuring even
    when every nation on a large map wants a line in the same turn.
    """
    facts = {}
    if not sender or not target or nation_data is None:
        return facts

    facts["at_war"] = queries.are_at_war(sender, target, nation_data)
    facts["same_faction"] = queries.are_in_same_faction(sender, target, nation_data)

    score = queries.get_relation_score(sender, target, nation_data)
    facts["opinion"] = ("hostile" if score <= OPINION_HOSTILE
                        else "warm" if score >= OPINION_WARM else "cold")

    # get_military_strength counts units on the map, so it wants map_data --
    # handing it nation_data returns 0 for everybody and silently reads every
    # war as an even match.
    if world is not None:
        mine, theirs = world.military(sender), world.military(target)
    elif map_data is not None:
        mine = queries.get_military_strength(sender, map_data)
        theirs = queries.get_military_strength(target, map_data)
    else:
        # Nothing to compare with. Leaving the fact out means every group that
        # tests it is skipped and the catch-all answers, which is the honest
        # result -- better than guessing "even" and picking a line on it.
        return facts

    if theirs > 0:
        ratio = mine / theirs
    elif mine > 0:
        # An enemy with no army at all is not an even match, whatever the bands
        # happen to be set to.
        ratio = STRENGTH_STRONGER * 2
    else:
        ratio = 1.0
    facts["strength"] = ("weaker" if ratio < STRENGTH_WEAKER
                         else "stronger" if ratio > STRENGTH_STRONGER else "even")
    return facts


def _matches(condition, facts):
    """Whether one group's `when` block holds. A missing fact never matches, so
    an unanswerable condition falls through to the catch-all rather than firing
    on a guess."""
    for key, wanted in condition.items():
        if key not in facts:
            return False
        allowed = wanted if isinstance(wanted, list) else [wanted]
        if facts[key] not in allowed:
            return False
    return True


def _lines_for(entry, facts, rng):
    """One line out of whatever shape this key holds.

    A bare string is a key nobody has written variants for yet, and stays legal
    forever -- that is what lets the file be filled in a bit at a time, and what
    keeps a mod that trims it down to strings working.
    """
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, list):
        return None

    # Bare strings in the list are the simplest authoring shape and by far the
    # most common one in the shipped file: interchangeable lines, no conditions.
    # They gather into one implicit catch-all group rather than each being their
    # own, or only the first of them would ever be said.
    # They sit below every explicit group, so a file that mixes the two shapes
    # still lets a conditioned line win.
    plain = [g for g in entry if isinstance(g, str)]
    best, best_specificity = (plain or None), -1

    for group in entry:
        if not isinstance(group, dict):
            continue
        lines = group.get("lines")
        if isinstance(lines, str):
            lines = [lines]
        if not isinstance(lines, list) or not lines:
            continue
        condition = group.get("when") or {}
        if not isinstance(condition, dict) or not _matches(condition, facts):
            continue
        # The most specific group that holds wins; an unconditional one is the
        # catch-all and only wins when nothing else did.
        if len(condition) > best_specificity:
            best, best_specificity = lines, len(condition)

    if not best:
        return None
    return rng.choice(best)


def all_responses():
    """The whole table as loaded from disk."""
    return queries.get_ai_responses()


def lines_for(key):
    """Every line this key could ever produce, conditions ignored.

    For auditing and for tests: with variants in play "the line for X" is no
    longer a single string, so anything checking that a literal has not drifted
    from the table has to ask whether it is still one of them.
    """
    entry = all_responses().get(key)
    if isinstance(entry, str):
        return [entry]
    if not isinstance(entry, list):
        return []

    out = []
    for group in entry:
        if isinstance(group, str):
            out.append(group)
            continue
        if not isinstance(group, dict):
            continue
        lines = group.get("lines")
        if isinstance(lines, str):
            lines = [lines]
        if isinstance(lines, list):
            out.extend(line for line in lines if isinstance(line, str))
    return out


def resolve(key, sender=None, target=None, nation_data=None, world=None,
            map_data=None, default=None, rng=None, fmt=None):
    """The line this nation says for `key`, given who it is talking to.

    Groups whose conditions hold are filtered, the most specific wins, and one
    of its lines is picked at random -- so the same nation making the same
    proposal twice does not say the same words twice. Passing no sender leaves
    every condition unanswerable, which resolves to the unconditional group;
    that is what the forty-odd call sites that have no second party do.

    `fmt` is a dict rather than **kwargs because one of the placeholders this
    has to fill is literally called {target}, which would collide with the
    nation being addressed and silently swallow it.
    """
    entry = all_responses().get(key)
    if entry is None:
        return default

    facts = (_situation(sender, target, nation_data, world, map_data)
             if sender and target else {})
    line = _lines_for(entry, facts, rng or random)
    if line is None:
        return default
    return line.format(**fmt) if fmt else line


class _FallbackTable:
    """dict-alike over the JSON, so the call sites that predate it keep working.

    Forty-odd places index AI_FALLBACK_RESPONSES directly or call .get on it.
    Rewriting all of them to pass a sender and a target would be a large diff
    for no benefit at most of them -- a timeout message has no second party --
    so this stays, answering with the unconditional line, and the sites that do
    have both migrate to resolve() where the variation is worth having.
    """

    def _flat(self):
        return {k: _lines_for(v, {}, random)
                for k, v in all_responses().items() if not k.startswith("_")}

    def __getitem__(self, key):
        line = resolve(key)
        if line is None:
            raise KeyError(key)
        return line

    def get(self, key, default=None):
        line = resolve(key)
        return default if line is None else line

    def __contains__(self, key):
        return not key.startswith("_") and key in all_responses()

    def __iter__(self):
        return iter(k for k in all_responses() if not k.startswith("_"))

    def keys(self):
        return list(self)

    def items(self):
        return self._flat().items()

    def values(self):
        return self._flat().values()

    def __len__(self):
        # Counted straight from the file: going through keys() would make
        # list(table) recurse, since list() asks for a length hint first.
        return sum(1 for k in all_responses() if not k.startswith("_"))

    def __eq__(self, other):
        return self._flat() == other if isinstance(other, dict) else NotImplemented

    def __repr__(self):
        return repr(self._flat())


AI_FALLBACK_RESPONSES = _FallbackTable()


# ==========================================
# SYSTEM PROMPTS & CONTEXT GENERATORS
# ==========================================

def build_world_context(current_date, ai_nation, active_nations_str, manpower, materials,
                        politics_str, events_str, target_context_str, target_nation,
                        relations_str=""):
    """Assembles the world, economy and politics a nation is reasoning about.

    Everything true of the world regardless of who is asking comes first, and
    byte-for-byte identically for every nation in a turn's batch; only the tail
    knows whose turn it is.

    That ordering is the whole reason this is worth writing down. A local model
    re-reads the prompt from the first token that differs, and the world picture
    is around ninety percent of it -- so weaving each nation's own relation
    scores through the politics block, which is what this used to do, meant
    twelve nations paid the full cost twelve times. Measured against llama3 on
    a 12k-character prompt: 9.5s of prompt evaluation cold, 0.2s when the
    prefix matches the previous call. Nothing here is hidden from the model
    that was visible before; it is the same text in a different order.
    """
    # --- shared prefix: identical for every nation asked this turn ----------
    context = f"Current Date: {current_date}\n"
    context += f"CRITICAL RULE: The ONLY nations that currently exist in this world are: {active_nations_str}.\n"
    context += "Do NOT mention, reference, or interact with any country, empire, or nation not explicitly on this list.\n\n"
    # How war works, for a model deciding whether to start or end one. World
    # knowledge, identical for everyone asked this turn, so it costs nothing:
    # it sits in the shared prefix a local model evaluates once and reuses.
    context += "--- HOW BATTLES WORK ---\n"
    context += ("A contested tile splits into separate battles, one per pair of hostile sides, "
                "and damage never crosses between them. Allies fight as one side and share its "
                "front between them, so a small ally is never swallowed by a larger one but "
                "never hoards room it has no troops for either. Only a fixed number of units "
                "per side fight at once; the rest wait in reserve, untouched, and rotate in as "
                "the front rank dies, so numbers past that limit do not win a battle faster. "
                "You only ever exchange fire with nations you are actually at war with, even "
                "when fighting alongside allies who are at war with others. Artillery bombards "
                "from outside every battle and is the only way to reach a reserve.\n\n")
    context += "--- GLOBAL POLITICS ---\n"
    context += politics_str

    if events_str:
        context += "\n--- RECENT WORLD EVENTS ---\n"
        context += events_str

    # --- per-nation tail ---------------------------------------------------
    context += f"\n--- YOU ---\nYou are the leader of {ai_nation}.\n"
    context += f"Your economy: {manpower} Manpower, {materials} Materials.\n"
    if relations_str:
        context += ("How you regard the others (scale -200 to 200; anyone not "
                    "listed is neutral):\n" + relations_str)

    if target_nation:
        context += f"\n--- CURRENT TARGET ---\nYou are currently communicating with {target_nation}.\n"
        if target_context_str:
            context += "Recent message history:\n" + target_context_str

    return context

def get_proactive_action_context(action_type, target=None):
    # Returns the descriptive context for when an AI initiates a diplomatic move.
    if action_type == "CEASEFIRE":
        return "offering a ceasefire because our nations cannot physically reach each other"
    elif action_type == "CALL_TO_ARMS":
        return f"calling you to arms in our war against {target}"
    elif action_type == "JOIN_WARS":
        return f"mobilizing our forces to join your war against {target}"
    elif action_type == "WAR_DECLARATION":
        return f"declaring war on {target} to reclaim rightful core territory, you are not negotiating"
    elif action_type == "JOIN_FACTION_REQ":
        return "requesting to join your faction to stand against our mutual enemies"
    elif action_type == "CREATE_FACTION":
        return "proposing to create a new faction together to combat mutual threats"
    elif action_type == "REQ_MILITARY_ACCESS":
        return "requesting military access through your territory since we are both fighting a common enemy"
    elif action_type == "PEACE_TREATY":
        return "offering terms to end the war between us, which has gone badly for us"
    elif action_type == "FACTION_INVITE":
        return "inviting you into our faction, since we are on good terms and would both be stronger for it"
    elif action_type == "TRADE":
        return "proposing an exchange of resources, each of us sending what the other lacks"
    elif action_type.startswith("ACCEPT_"):
        return f"accepting the {action_type.replace('ACCEPT_', '').replace('_', ' ').lower()} proposal"
    elif action_type.startswith("REJECT_"):
        return f"rejecting the {action_type.replace('REJECT_', '').replace('_', ' ').lower()} proposal"
    elif action_type.startswith("MSG:"):
        return f"sending a diplomatic message: '{action_type[4:]}'"
    return "taking a diplomatic action"

def get_unilateral_receive_context(action_type, sender_nation, custom_msg=""):
    # Returns the context for when an AI receives an un-rejectable action (like War).
    context = ""
    if action_type == "WAR_DECLARATION":
        context = f"{sender_nation} has DECLARED WAR on us!"
    elif action_type == "LEAVE_FACTION":
        context = f"{sender_nation} has abandoned our faction!"
    elif action_type == "DISBAND_FACTION":
        context = f"{sender_nation} has disbanded our faction!"
    elif action_type == "JOIN_WARS":
        context = f"{sender_nation} has mobilized their forces to join our ongoing wars!"
    elif action_type == "BREAK_ALLIANCE":
        context = f"{sender_nation} has broken their alliance with us!"
    elif action_type == "KICK_FACTION_MEMBER":
        context = f"{sender_nation} has expelled us from the faction!"
        
    if custom_msg:
        context += f" They included this official message: '{custom_msg}'"
    return context

def get_bilateral_receive_context(action_type, sender_nation, custom_msg="", note=""):
    """What was proposed, and what its proposer said about it.

    Two different things, and they used to share one field. `custom_msg` is the
    terms -- for a trade it was literally rendered as "Terms: {custom_msg}", and
    the "official message" line below was skipped for trades on the strength of
    that. So a player could attach words to a treaty and have them read as terms,
    or attach them to a trade and have the model never see the terms at all.
    Terms are generated from the deal now; `note` is what the player wrote.
    """
    if action_type == "JOIN_WARS":
        context = f"{sender_nation} is offering to join YOUR ongoing wars."
    elif action_type == "CALL_TO_ARMS":
        context = f"{sender_nation} is calling YOU to arms to join THEIR ongoing wars."
    elif action_type == "FACTION_INVITE":
        context = f"{sender_nation} is inviting you to join THEIR faction."
    elif action_type == "JOIN_FACTION_REQ":
        context = f"{sender_nation} is requesting to join YOUR faction."
    elif action_type == "TRADE":
        context = f"{sender_nation} has proposed a Trade Agreement. Terms: {custom_msg}"
    elif action_type in ("PEACE_TREATY", "CEASEFIRE"):
        context = (f"{sender_nation} has proposed terms to end the war. "
                   f"Terms: {custom_msg}")
    elif action_type == "REQ_MILITARY_ACCESS":
        context = f"{sender_nation} is requesting military access to move their troops through your territory."
    else:
        context = f"{sender_nation} has proposed a {action_type.replace('_', ' ').title()}."

    if custom_msg and action_type not in ("TRADE", "PEACE_TREATY", "CEASEFIRE"):
        context += f" They included this official message: '{custom_msg}'"
    if note:
        context += f" Their government adds: '{note}'"

    return context

#: How the message is to be written, as opposed to what it has to contain.
#:
#: Nothing said this before. Every prompt named the nation ("You are the leader
#: of X") and left the voice to be inferred, which a strong model does and a
#: small one does not: llama3 wrote "Switzerland accepts your offer" into a
#: message already labelled as being from Switzerland. Stated once here, since
#: all three long prompts end with action_rules_and_schema.
VOICE_RULE = (
    "VOICE: write the 'message' as your own government addressing theirs, in the "
    "first person plural -- 'we', 'our', 'us'. Never refer to your own nation in "
    "the third person or by name, and never narrate what it does from outside.\n"
)


def reads_as_third_person(message, nation, nation_data=None):
    """Whether a reply talks about its own sender rather than speaking as them.

    Deliberately narrow: only an opening that names the nation or its adjective,
    which is the failure small models actually produce and the one that reads
    worst next to a sender label. A nation named mid-sentence is ordinary prose
    ("our claim on Poland stands") and is left alone. No second request is made
    to fix it -- the canned line is used instead, because a retry at ABSOLUTE
    costs one call per nation per turn.
    """
    if not message or not nation:
        return False

    names = {nation}
    data = (nation_data or {}).get(nation) or {}
    for key in ("name", "adjective"):
        if data.get(key):
            names.add(data[key])

    opening = message.lstrip().lstrip("\"'*").lower()
    for name in names:
        name = name.strip().lower()
        if not name or not opening.startswith(name):
            continue
        rest = opening[len(name):]
        # "Switzerland accepts" is third person; "Switzerland! We accept" and
        # "Switzerland's terms are these" are somebody's own voice.
        if rest[:1] in ("", " ") and not rest.lstrip().startswith(("we ", "we'", "our ")):
            return True
    return False


def action_rules_and_schema(subject, message_hint):
    """The tail every long system prompt ends with: the action list, the rules
    for using them, and the JSON schema to reply in.

    These eleven lines were written out three times, once per prompt, which
    meant adding a valid action or a rule meant editing all three and the
    copies had already begun to drift. Only two things genuinely differ:

    - `subject`: what to call the thing being reacted to ("event", "proposal",
      "message"), used in the opinion_change instruction.
    - `message_hint`: the placeholder inside the JSON schema. The model reads
      it, so the three stay distinct verbatim rather than being generalised.
    """
    return (
        VOICE_RULE +
        "Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', 'JOIN_FACTION_REQ', 'CEASEFIRE', 'CALL_TO_ARMS', 'CREATE_FACTION', 'KICK_FACTION_MEMBER', 'DISBAND_FACTION' or 'NONE'.\n"
        "RULES FOR ACTIONS:\n"
        "- You MUST specify the target country for your action in 'action_target' (e.g., 'Germany', 'Russia', or the sender's name).\n"
        "- Do NOT output 'JOIN_FACTION_REQ' if you are already in a faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'LEAVE_FACTION' while you are fighting a war alongside your faction. You do not abandon allies mid-war, and the request will be refused.\n"
        "- Do NOT output 'WAR_DECLARATION' against a member of your own faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'JOIN_WARS' if you're trying to join the war of someone not in your faction, instead just type 'WAR_DECLARATION' against the target country.\n"
        "- If your plan requires two steps (like proposing a ceasefire this turn and a full peace next turn), "
        "put your immediate move in 'action'/'action_target' and your next move in 'follow_up_action'/'follow_up_target'.\n"
        "- If you declare war on your master, put 'Independence' in the 'message' field. If you declare war on your puppet, put 'Preemptive'. Puppets and masters automatically leave shared factions upon war. A puppet cannot make peace or sign a ceasefire on its own authority, only with its own master.\n"
        f"- You MUST specify an 'opinion_change' integer between -20 and 20 indicating how much this {subject} improved or worsened your general opinion of the sender.\n"
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "' + message_hint + '", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0}'
    )

def get_unilateral_system_prompt(action_context):
    return (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"You have just received the following unilateral declaration: {action_context} "
        "There is no proposal to accept or reject. You must send a reply to the country that sent you this declaration in character. "
        "You may also take a diplomatic action in retaliation or response.\n"
        + action_rules_and_schema("event", "In-character dialogue reacting to the event in english")
    )

def get_bilateral_system_prompt(accepted, allow_override=False, reason="", confidence=1.0):
    """The prompt for answering a proposal.

    When the staff are certain -- a structural rule, not a judgement -- the
    decision is stated as settled and the model only phrases it, which is both
    correct and cheaper to generate. When the call is genuinely marginal the
    recommendation is offered with its reasoning and the leader may overrule it.

    Every proposal used to take the first form: "you have already decided to
    strongly ACCEPT", with no reasoning attached and no way to disagree.
    """
    decision_str = 'ACCEPT' if accepted else 'REJECT'

    if not allow_override:
        return (
            "You are an AI playing a grand strategy game. You act as the leader of your nation. "
            f"You have already decided to strongly {decision_str} the diplomatic proposal. "
            "The details are already finalized, don't ask for further clarification, and don't ask to discuss it further. "
            "You may also take a diplomatic action in response to this proposal.\n"
            + action_rules_and_schema("proposal", "In-character dialogue responding to the proposal in english")
        )

    strength = "low" if confidence < 0.4 else "moderate"
    reasoning = f" Their reasoning: {reason}." if reason else ""
    return (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"Your ministers recommend that you {decision_str} the diplomatic proposal.{reasoning} "
        f"Their confidence in that recommendation is {strength}. "
        "You may follow it, or overrule it if your own judgement differs -- say which in 'accepted'. "
        "You may also take a diplomatic action in response to this proposal.\n"
        "- Set 'accepted' to true to agree to the proposal, or false to refuse it.\n"
        + action_rules_and_schema("proposal", "In-character dialogue responding to the proposal in english")
        + ', "accepted": ' + ('true' if accepted else 'false')
    )

def get_custom_message_system_prompt():
    return (
        "You are an AI leader in a grand strategy game. Respond to the incoming diplomatic message in character. "
        "Keep your response under 2 sentences. "
        #"For reasons unbenownst to the other country, your goals actually align exactly with what they think they have to convince you to do. "
        #"It's also in your best interest to make it seem like they had to convince you, so your actions don't seem too spontaneous. "
        "CRITICAL: Use the 'Relations' score provided in the context to determine your tone. "
        "- Relations < -50: Be hostile, dismissive, or threatening.\n"
        "- Relations 0 to 50: Be neutral, transactional, and cautious.\n"
        "- Relations > 50: Be warm, brotherly, and highly cooperative.\n"
        "If you are at war, do not agree to anything friendly unless it's a 'CEASEFIRE'. "
        "You may also take a diplomatic action if the sender's reasoning is convincing or offensive. "
        + action_rules_and_schema("message", "Your in-character response here")
    )

def get_proactive_system_prompt(ai_nation, target_nation, action_context):
    return (
        f"You are the leader of {ai_nation}. Write a single, brief sentence to {target_nation} "
        f"about {action_context}. Do not include quotes. Reply strictly with a JSON object: "
        '{"message": "Your text here"}'
    )