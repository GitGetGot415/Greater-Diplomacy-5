"""Diplomatic status: wars, military access, truces, and pending message state."""

import data.constants as c


def are_at_war(nation_a, nation_b, nation_data):
    """Returns True if nation_b is in nation_a's war list."""
    return nation_b in get_enemies(nation_a, nation_data)


def has_military_access(moving_nation, target_owner, nation_data):
    """Returns True if the target_owner has granted military access to the moving_nation."""
    return moving_nation in nation_data.get(target_owner, {}).get("military_access", [])


def get_military_access_granted_by(nation, nation_data):
    """Who this nation lets march through its territory."""
    return list(nation_data.get(nation, {}).get("military_access", []))


def get_military_access_granted_to(nation, nation_data):
    """Whose territory this nation may march through.

    Access is stored only on the granting side, so the reverse direction needs a
    sweep -- there is no index for it. Cheap enough for a panel that redraws on
    selection, but do not call it per frame on a large map.
    """
    return sorted(other for other, data in nation_data.items()
                  if isinstance(data, dict) and nation in (data.get("military_access") or ()))


def can_negotiate_peace(nation, other, nation_data):
    """Whether `nation` may settle a war with `other` on its own authority.

    A puppet's wars are its master's business. It may still make peace WITH its
    master, since that is how an independence war ends -- the mirror of the
    existing rule that a puppet may only declare war on its master.

    Nothing enforced this before: thirteen separate paths could initiate or
    accept a peace, and none of them looked at `master`, so a subject could sign
    its own treaty while its overlord was still fighting.
    """
    master = nation_data.get(nation, {}).get("master", "")
    return not master or master == other


def can_choose_own_faction(nation, nation_data):
    """Whether `nation` may join, be invited into, or leave a faction alone.

    A puppet's alignment is its master's, exactly as its wars are -- it follows
    its overlord in and out through pull_puppets_into_faction and its opposite,
    and has no say of its own. Nothing checked this either, so a subject could
    sit in a faction its master had never joined: in saves/Madagascar but not
    France, French Madagascar was in the Axis while Vichy France was in nothing.

    Founding a faction is deliberately not covered. finalize_create_faction
    already redirects to the master, so the puppet is not acting alone there.
    """
    return not nation_data.get(nation, {}).get("master", "")


def get_enemies(nation, nation_data):
    """Who a nation is at war with. The one place the key name is spelled out."""
    return nation_data.get(nation, {}).get("at_war_with", [])


def get_diplomatic_status(sender, target, nation_data):
    """Safely unpacks the pending diplomacy dictionary. Returns (action_string, turns_int)."""
    pending = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(target, {})
    
    action = pending.get("action", "")
    turns = pending.get("turns", 0)
    
    # Failsafe
    if isinstance(action, dict): 
        action = ""
        
    return action, turns


def get_message_draft(sender, target, nation_data):
    """Returns the draft text if one exists and hasn't been sent."""
    draft_list = nation_data.get(sender, {}).get("draft_lists", {}).get(target, [])
    if draft_list:
        return "\n".join(draft_list)

    pending = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(target, {})
    if isinstance(pending, dict) and pending.get("turns", 0) == 0:
        action = pending.get("action", "")
        if isinstance(action, str) and action.startswith("MSG:"):
            return action[4:]
        if not action and "message" in pending:
            return pending["message"]
    return ""


def is_diplomat_busy(sender, target, nation_data):
    """Returns True if the diplomat is currently traveling."""
    action, turns = get_diplomatic_status(sender, target, nation_data)
    is_unilateral = action in c.UNILATERAL_ACTIONS

    if is_unilateral and turns > 0:
        return False
        
    # Allow queueing new messages/actions if the current action is just a message in transit
    #if str(action).startswith("MSG:") and turns > 0:
    #   return False
        
    if turns > 0: 
        return True
    return False


def get_incoming_justifications_count(nation, nation_data, id_to_province):
    """Returns the number of active claim justifications against the given nation."""
    count = 0
    for other_nation, data in list(nation_data.items()):
        if other_nation == nation: continue
        queue = data.get("claim_queue", [])
        if queue:
            q = queue[0]  # Only check the active justification
            if q.get("turns_left", 0) < c.CLAIM_TURN_NON_CORE: # Hide if made this turn
                prov = id_to_province.get(q["prov_id"])
                if prov and prov.get("owner") == nation:
                    count += 1
    return count


def has_unanswered_request(nation, other_nation, nation_data):
    """True if other_nation has a live proposal waiting on nation's answer.

    The single source of truth for "this contact needs your attention" -- the map
    badge and the per-contact badge in the messages screen both read it, so they
    can never disagree about what is outstanding.
    """
    req = nation_data.get(other_nation, {}).get("pending_diplomacy", {}).get(nation)
    if not isinstance(req, dict):
        return False
    if req.get("turns", 0) <= 0 or req.get("action", "") not in c.BILATERAL_ACTIONS:
        return False

    # Already answered this turn -- the reply just hasn't been processed yet.
    my_response = nation_data.get(nation, {}).get("diplo_responses", {}).get(other_nation)
    if isinstance(my_response, dict) and my_response.get("verdict"):
        return False
    return True


def get_pending_request_senders(nation, nation_data):
    """Every nation currently waiting on an answer from `nation`.

    Iterates a snapshot of the keys: this runs from the badge-drawing path, which
    can land mid-turn while nation_data is still growing (faction war maps, newly
    released nations), and a live iterator would blow up there.
    """
    return [other for other in list(nation_data)
            if other != nation and has_unanswered_request(nation, other, nation_data)]


def get_unread_message_count(nation, nation_data):
    """Returns the total number of unread messages and unanswered requests for a nation."""
    # If the user is the spectator, count unread messages across ALL playable nations
    if nation == "Spectator":
        # Calling get_pending_request_senders() once per playable nation -- as this
        # used to -- reruns its full nation_data scan every time, which makes the
        # whole thing O(nations^2). Every pending request lives as one entry in its
        # sender's own pending_diplomacy dict, so a single pass building a
        # recipient -> count map does the exact same accounting in O(nations +
        # pending requests) instead, with identical results.
        pending_counts = {}
        for sender, sender_data in nation_data.items():
            for recipient, req in sender_data.get("pending_diplomacy", {}).items():
                if not isinstance(req, dict):
                    continue
                if req.get("turns", 0) <= 0 or req.get("action", "") not in c.BILATERAL_ACTIONS:
                    continue
                my_response = nation_data.get(recipient, {}).get("diplo_responses", {}).get(sender)
                if isinstance(my_response, dict) and my_response.get("verdict"):
                    continue
                pending_counts[recipient] = pending_counts.get(recipient, 0) + 1

        total_unread = 0
        for n_name, n_data in nation_data.items():
            if n_data.get("is_playable", False):
                inbox = n_data.get("inbox", [])
                total_unread += sum(1 for msg in inbox if not msg.get("spectator_read", False))
                total_unread += pending_counts.get(n_name, 0)
        return total_unread

    # Standard logic for normal players
    inbox = nation_data.get(nation, {}).get("inbox", [])
    # Ignore messages where the sender is the nation itself
    unread_count = sum(1 for msg in inbox if not msg.get("read", False) and msg.get("sender") != nation)
    unread_count += len(get_pending_request_senders(nation, nation_data))

    return unread_count


def has_active_truce(nation_a, nation_b, nation_data):
    """Returns True if there is an active non-aggression pact/truce between the two nations."""
    if nation_a not in nation_data: return False
    return nation_data[nation_a].get("truces", {}).get(nation_b, 0) > 0


def get_active_truces(nation, nation_data):
    """Nations this one currently holds a truce with, mapped to turns remaining."""
    truces = nation_data.get(nation, {}).get("truces", {})
    return {other: turns for other, turns in truces.items() if turns > 0}
