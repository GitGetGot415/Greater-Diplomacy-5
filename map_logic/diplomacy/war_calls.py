"""Who may ask whom into a war, and which of the two ways round it is.

There are exactly two of these messages and they are mirror images:

    CALL_TO_ARMS   "come and fight in a war of ours"     -- the caller is at war
    JOIN_WARS      "let us fight in a war of yours"      -- the target is at war

Which one is correct is not a matter of taste, it is a fact about the two
nations' war lists, and until now nothing checked it. The proactive AI pass
worked it out properly (ai_diplomacy._call_faction_to_arms and
_join_faction_wars_proactively each look for wars the other side is missing),
but the branch that queues a *model's* chosen action did not: JOIN_WARS,
CEASEFIRE and JOIN_FACTION_REQ each got a guard and CALL_TO_ARMS got a single
unguarded line. `ai_prompts` states the rule in prose to the model and hopes.

So a nation in no faction, at war with nobody, could call the player to arms --
which is what `Hungary left and then asked to join in a faction war what` is a
save of:

    Hungary: faction = ""  at_war_with = []
             pending_diplomacy = {"German Reich": {"action": "CALL_TO_ARMS", ...}}

and an autonomous puppet, whose wars are by definition its master's already,
could call its own master to arms in them. It had picked the wrong one of the
pair: what it meant was "let us join you", and the fix is to send that instead
of the reverse of it.

Deliberately its own module rather than an addition to data/queries.py -- a mod
may ship its own copy of that file and shadow it wholesale, taking a new
function down with it. Same reasoning as map_logic/diplomacy/restrictions.py.
"""

from data import queries

CALL_TO_ARMS = "CALL_TO_ARMS"
JOIN_WARS = "JOIN_WARS"


def are_pledged(caller, target, nation_data):
    """Whether these two owe each other help at all.

    A faction is the ordinary answer. A master and its subject are the other
    one: a puppet is not always in its overlord's faction, and the two of them
    are bound more tightly than any pact -- pull_puppets_into_war drags a subject
    into its master's wars without asking.
    """
    if caller == target:
        return False
    if queries.are_in_same_faction(caller, target, nation_data):
        return True

    mine = nation_data.get(caller, {})
    theirs = nation_data.get(target, {})
    return mine.get("master") == target or theirs.get("master") == caller


def unshared_wars(nation, other, nation_data):
    """Wars `nation` is fighting that `other` is not, and could still join.

    A truce is a signed peace, and being called to arms is not a reason to tear
    one up -- join_faction_wars already refuses to, so a call naming only truced
    enemies would be answered by doing nothing at all.
    """
    theirs = set(queries.get_enemies(other, nation_data))
    return [enemy for enemy in queries.get_enemies(nation, nation_data)
            if enemy not in theirs
            and enemy != other
            and not queries.has_active_truce(other, enemy, nation_data)
            and not queries.has_active_truce(enemy, other, nation_data)]


def intended_action(caller, target, nation_data):
    """Which of the two messages these two nations' war lists actually support.

    CALL_TO_ARMS when the caller has a war to be helped in, JOIN_WARS when it is
    the target who does, and None when neither has anything to offer the other --
    which is the case the unguarded branch used to queue as a call to arms
    anyway.

    Checked in that order: a nation with a war of its own to fight is asking for
    help, even if the target also has one it could be pulled into.
    """
    if not are_pledged(caller, target, nation_data):
        return None
    if unshared_wars(caller, target, nation_data):
        return CALL_TO_ARMS
    if unshared_wars(target, caller, nation_data):
        return JOIN_WARS
    return None


def is_honest(action, caller, target, nation_data):
    """Whether this exact message is the one these two nations' wars support."""
    if action not in (CALL_TO_ARMS, JOIN_WARS):
        return True
    return action == intended_action(caller, target, nation_data)
