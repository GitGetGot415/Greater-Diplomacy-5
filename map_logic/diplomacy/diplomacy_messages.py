
import data.constants as c

# ==========================================
# PENDING DIPLOMACY ACCESS
# ==========================================
# One set of accessors for the nation_data["pending_diplomacy"] dict, so
# callers never have to repeat the nested .get() chains or remember that an
# entry may be a bare action string from an older save rather than a dict.

def get_pending_map(nation_data, player_name, writable=False):
    """The player's whole outgoing-diplomacy dict. writable=True creates it."""
    if writable:
        return nation_data.setdefault(player_name, {}).setdefault("pending_diplomacy", {})
    return nation_data.get(player_name, {}).get("pending_diplomacy", {})

def get_pending(nation_data, player_name, target_name):
    """The pending entry aimed at target_name, always as a dict ({} if none)."""
    info = get_pending_map(nation_data, player_name).get(target_name)
    return info if isinstance(info, dict) else {}

def get_pending_action(nation_data, player_name, target_name):
    pending = get_pending_map(nation_data, player_name)
    info = pending.get(target_name)
    if isinstance(info, dict):
        return info.get("action")
    return info

def set_pending(nation_data, player_name, target_name, action, **extra):
    """Overwrites the pending action aimed at target_name.

    Deliberately an overwrite, not a toggle: the player-facing screens replace
    a queued declaration/offer outright rather than cancelling it.
    """
    entry = {"action": action, "turns": 0, "timer": 0}
    entry.update(extra)
    get_pending_map(nation_data, player_name, writable=True)[target_name] = entry
    return entry

def clear_pending(nation_data, player_name, target_name, only_actions=None):
    """Removes a queued action. `only_actions` limits it to matching actions.

    Returns True when something was actually removed.
    """
    pending = get_pending_map(nation_data, player_name)
    if target_name not in pending:
        return False
    if only_actions is not None:
        action = get_pending_action(nation_data, player_name, target_name)
        if action not in only_actions:
            return False
    del pending[target_name]
    return True

# ==========================================
# DIPLOMATIC RESPONSE ACCESS
# ==========================================
# Answers to incoming proposals live in their own dict rather than in
# pending_diplomacy. The two are genuinely independent: a nation can have an
# offer travelling towards someone while also answering an offer travelling the
# other way, and neither may quietly overwrite the other.
#
#   nation_data[me]["diplo_responses"][sender] = {
#       "verdict": "ACCEPT" | "REJECT",
#       "action": "<the action being answered>",
#       "message": "<reply text>",
#       "parameters": {...},   # copied from their request (trades, peace terms)
#   }
#
# Responses carry no "turns": they resolve on the turn they are queued.

RESPONSE_ACCEPT = "ACCEPT"
RESPONSE_REJECT = "REJECT"

def get_response_map(nation_data, player_name, writable=False):
    """The player's whole queued-response dict. writable=True creates it."""
    if writable:
        return nation_data.setdefault(player_name, {}).setdefault("diplo_responses", {})
    return nation_data.get(player_name, {}).get("diplo_responses", {})

def get_response(nation_data, player_name, sender_name):
    """The response queued for sender_name, always as a dict ({} if none)."""
    info = get_response_map(nation_data, player_name).get(sender_name)
    return info if isinstance(info, dict) else {}

def get_response_status(nation_data, player_name, sender_name):
    """Unpacks a queued response. Returns (verdict, action), both "" if none."""
    info = get_response(nation_data, player_name, sender_name)
    return info.get("verdict", ""), info.get("action", "")

def set_response(nation_data, player_name, sender_name, verdict, action, **extra):
    """Queues an answer to sender_name's proposal. Overwrites any earlier answer."""
    entry = {"verdict": verdict, "action": action, "message": ""}
    entry.update(extra)
    get_response_map(nation_data, player_name, writable=True)[sender_name] = entry
    return entry

def clear_response(nation_data, player_name, sender_name):
    """Removes a queued response. Returns True when something was removed."""
    responses = get_response_map(nation_data, player_name)
    if sender_name not in responses:
        return False
    del responses[sender_name]
    return True

def queue_text_message(nation_data, player_name, target_name, content):
    if player_name not in nation_data:
        return "Cannot send messages as this entity."
        
    p_data = nation_data[player_name]
    pending = get_pending_map(nation_data, player_name, writable=True)
    draft_lists = p_data.setdefault("draft_lists", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    cur_list = draft_lists.setdefault(target_name, [])
    if content and content not in cur_list:
        cur_list.append(content)
        
    if current_action is not None and not current_action.startswith("MSG:"):
        return "Message draft saved alongside formal action."
        
    combined = "\n".join(cur_list) if cur_list else content
    pending[target_name] = {"action": f"MSG:{combined}", "turns": 0, "message": combined}
    return "Message draft saved. Will send at end of turn."

def cancel_text_message(nation_data, player_name, target_name):
    """Safely clears a drafted text message if it hasn't been sent yet."""
    if player_name not in nation_data:
        return "No drafted message to clear."
        
    current_action = get_pending_action(nation_data, player_name, target_name)

    if current_action and current_action.startswith("MSG:"):
        if get_pending(nation_data, player_name, target_name).get("turns", 0) > 0:
            return "Cannot undo! Message is already in transit."

        clear_pending(nation_data, player_name, target_name)
        return "Draft cleared."
    return "No drafted message to clear."

def _deliver(nation_data, owner, entry):
    """Puts one message at the top of a nation's inbox, oldest trimmed off.

    Inboxes are serialized wholesale into the save with the rest of
    nation_data and nothing ever pruned them, so a long game grew them without
    bound. Newest-first, so the tail is what falls off the end.
    """
    data = nation_data.get(owner)
    if not data:
        return

    inbox = data.setdefault("inbox", [])
    inbox.insert(0, entry)
    if len(inbox) > c.INBOX_MAX_MESSAGES:
        del inbox[c.INBOX_MAX_MESSAGES:]


def send_message(map_screen, sender, receiver, content, msg_type="TEXT"):
    nation_data = map_screen.nation_data
    date_str = map_screen.time_manager.get_date_string()

    # 1. Deliver the message to the receiver
    _deliver(nation_data, receiver, {
        "sender": sender, "content": content, "type": msg_type,
        "read": False, "spectator_read": False, "date": date_str
    })

    # 2. Save a "Sent" copy to the sender's inbox
    _deliver(nation_data, sender, {
        "sender": f"To: {receiver}", "content": content, "type": msg_type,
        "read": True, "spectator_read": True, "date": date_str
    })

# ==========================================
# OUTGOING ANNOUNCEMENTS
# ==========================================

#: What an outgoing action says when its sender wrote nothing of their own.
#:
#: A tuple means "look this key up in ai_prompts.AI_FALLBACK_RESPONSES, and use
#: the second element only if it isn't there". Those five actions already read
#: that table, but with no default at all, so a mod that trimmed an entry sent
#: a message with `None` for content. The plain strings are actions that have
#: never read the table and are left alone.
DEFAULT_ANNOUNCEMENTS = {
    "CALL_TO_ARMS": "We request your aid in our ongoing conflicts!",
    "CANCEL_MILITARY_ACCESS": "We no longer require military access through your territory.",
    "REVOKE_MILITARY_ACCESS": "Your military access through our territory has been revoked.",
    "FACTION_INVITE": "We invite your nation to join our faction.",
    "JOIN_FACTION_REQ": "We formally request to join your faction.",
    "REQ_MILITARY_ACCESS": "We formally request military access to move our troops through your territory.",
    "CEASEFIRE": "We offer terms for a ceasefire.",
    "CREATE_FACTION": "We propose establishing a new faction together.",
    "TRADE": "We propose a trade agreement.",
    "JOIN_WARS": ("REQUEST_JOIN_WARS", "We request permission to join your ongoing wars."),
    "BREAK_ALLIANCE": ("BREAK_ALLIANCE", "We have broken our alliance."),
    "DISBAND_FACTION": ("FACTION_DISBANDED", "It is a shame to see our alliance broken."),
    "KICK_FACTION_MEMBER": ("KICKED_FROM_FACTION", "We will not forget being expelled from the alliance."),
    "LEAVE_FACTION": ("FACTION_ABANDONED", "We will not forget your abandonment."),
}


def announcement_for(action, custom_msg=""):
    """The line an outgoing action announces itself with.

    Fifteen branches of the outgoing-diplomacy pass wrote out
    `custom_msg if custom_msg else "<literal>"` by hand, and several of those
    literals were a stale copy of an AI_FALLBACK_RESPONSES entry saying the
    same thing in slightly different words.
    """
    if custom_msg:
        return custom_msg

    default = DEFAULT_ANNOUNCEMENTS.get(action)
    if default is None:
        # An action added to constants.py without an entry here still reaches
        # the other side's inbox rather than arriving blank.
        return f"We propose {action.replace('_', ' ').lower()}."
    if isinstance(default, tuple):
        from map_logic.ai import ai_prompts
        return ai_prompts.AI_FALLBACK_RESPONSES.get(default[0], default[1])
    return default


def send_treaty_message(map_screen, sender, receiver, action, custom_msg=""):
    """Announces an outgoing diplomatic action to its recipient."""
    send_message(map_screen, sender, receiver, announcement_for(action, custom_msg), "DIPLOMACY")
