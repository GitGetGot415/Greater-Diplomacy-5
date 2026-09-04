
import copy
import uuid

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

def describe_trade(params, viewer_is_proposer=False, subject=None, viewer=None,
                   nation_data=None):
    """An agreement's terms in words, from one side's point of view.

    `subject` names that side instead of calling it "You", which is what a
    spectator watching two other countries needs -- "You receive" is a lie when
    the reader is not either party.

    Itemized deals describe themselves (see map_logic/diplomacy/deal.py) and are
    handed straight through. What follows is the old four-key trade dict, which
    saves written before the rework still carry: the keys are stored from the
    PROPOSER's point of view -- `give_*` is what they hand over, `take_*` what
    they ask for -- so the receiving side sees them inverted, and getting that
    backwards would mislead a player into accepting the opposite of what they
    thought.

    Returns [] when there is nothing to say, so a caller can skip the bubble.
    """
    from map_logic.diplomacy import deal as deal_mod

    if deal_mod.is_deal(params):
        return deal_mod.describe(params, viewer=viewer, nation_data=nation_data)

    if not isinstance(params, dict):
        return []

    incoming = {res: params.get(f"give_{res}", 0) or 0 for res in c.TRADE_RESOURCE_KEYS}
    outgoing = {res: params.get(f"take_{res}", 0) or 0 for res in c.TRADE_RESOURCE_KEYS}
    if viewer_is_proposer:
        incoming, outgoing = outgoing, incoming

    def amounts(side):
        return ", ".join(f"{int(qty)} {res.title()}"
                         for res, qty in side.items() if qty > 0)

    given, wanted = amounts(incoming), amounts(outgoing)
    who = subject or "You"
    receives, gives = ("receives", "gives") if subject else ("receive", "give")
    lines = []
    lines.append(f"{who} {receives}: {given or 'nothing'}")
    lines.append(f"{who} {gives}: {wanted or 'nothing'}")

    puppet_state = params.get("puppet_state", "NONE")
    if puppet_state and puppet_state != "NONE":
        lines.append(f"Puppet terms: {puppet_state}")

    return lines


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


# ==========================================
# FORWARDED MESSAGE ACCESS
# ==========================================

FORWARD_ACTION = "FORWARD_MESSAGE"


def is_forwarded(msg):
    """Whether a message carries the engine's forwarding provenance stamp."""
    return isinstance(msg, dict) and msg.get("forwarded") is True


def forwarded_details(msg):
    """Returns the reader-facing provenance fields for a forwarded message.

    Old saves have no forwarding fields, so callers can use this helper without
    having to distinguish a missing field from a malformed forwarded record.
    """
    if not is_forwarded(msg):
        return None
    return {
        "original_sender": msg.get("original_sender") or "Unknown",
        "original_receiver": msg.get("original_receiver") or "Unknown",
        "original_date": msg.get("original_date") or "Unknown",
        "forwarded_by": msg.get("forwarded_by") or msg.get("sender") or "Unknown",
        "forwarded_at": msg.get("forwarded_at") or msg.get("date") or "Unknown",
        "forward_chain": msg.get("forward_chain", []),
    }


def queue_forwarded_message(nation_data, player_name, target_name, source_owner,
                            original_message):
    """Queues one authenticated forward for the end-of-turn message pass.

    The original record is copied into the pending entry. The sender cannot
    rewrite its provenance through the compose box, and the delivery pass later
    creates a fresh forwarding record with a new message/forward id.
    """
    if player_name not in nation_data:
        return "Cannot forward messages as this entity."
    if target_name not in nation_data or target_name == player_name:
        return "That country cannot receive this forwarded message."
    if not isinstance(original_message, dict) or not original_message.get("content", ""):
        return "This message cannot be forwarded."

    pending = get_pending_map(nation_data, player_name, writable=True)
    existing = pending.get(target_name)
    if existing is not None:
        existing_turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
        if existing_turns > 0:
            return "A diplomatic action is already in transit to this country."
        return "A diplomatic action is already pending with this country."

    pending[target_name] = {
        "action": FORWARD_ACTION,
        "turns": 0,
        "timer": 0,
        "message": original_message.get("content", ""),
        "forwarded_message": copy.deepcopy(original_message),
        "forwarded_source": source_owner,
    }
    return "Forward queued. It will be sent at the end of the turn."

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


def send_message(map_screen, sender, receiver, content, msg_type="TEXT", extra=None,
                 llm=False):
    """Delivers one message to the receiver and files a sent copy for the sender.

    `extra` is stamped onto both copies. It exists for the terms of a trade: the
    numbers live on the sender's pending_diplomacy entry, which is deleted the
    moment the offer resolves, so a player who accepted a trade had no way to
    see afterwards what they had agreed to. Recorded on the message itself it
    outlives the offer, and costs nothing to persist -- nation_data is
    serialized wholesale by build_save_dict. The action a message announced
    rides along the same way, for the same reason.

    `llm` records that a model wrote this line rather than the canned table
    picking one. The two used to be indistinguishable the moment they left
    ai_evaluation -- the fallback is substituted by dict.get's default and
    travels the identical path -- so there was no way to see which of the
    things a country said it had actually thought of.
    """
    nation_data = map_screen.nation_data
    date_str = map_screen.time_manager.get_date_string()

    # Delivery fields are owned by this function. In particular, an action or
    # forwarding stamp must not be able to replace the visible sender/date by
    # arriving through an arbitrary `extra` dict.
    protected = {"sender", "content", "type", "read", "spectator_read", "date",
                 "message_id"}
    stamp = {key: value for key, value in (extra or {}).items()
             if key not in protected}
    if llm:
        stamp["llm"] = True

    message_id = uuid.uuid4().hex

    # 1. Deliver the message to the receiver
    incoming = {
        "sender": sender, "content": content, "type": msg_type,
        "read": False, "spectator_read": False, "date": date_str,
        "message_id": message_id,
    }
    incoming.update(stamp)
    _deliver(nation_data, receiver, incoming)

    # 2. Save a "Sent" copy to the sender's inbox
    outgoing = {
        "sender": f"To: {receiver}", "content": content, "type": msg_type,
        "read": True, "spectator_read": True, "date": date_str,
        "message_id": message_id,
    }
    outgoing.update(stamp)
    _deliver(nation_data, sender, outgoing)
    return incoming


def forward_message(map_screen, sender, receiver, original_message, source_owner=None):
    """Delivers a forwarded copy with immutable, visible provenance metadata.

    `sender` is the country doing the forwarding, while `original_sender` is
    retained from the first message in the chain. Action/terms/LLM metadata are
    carried over so a forwarded war declaration or treaty remains machine-
    readable to the next country.
    """
    if not isinstance(original_message, dict):
        return None
    content = original_message.get("content", "")
    if not content:
        return None

    # Give a legacy message a stable reference the first time it is forwarded.
    source_message_id = original_message.get("message_id")
    if not source_message_id:
        source_message_id = uuid.uuid4().hex
        original_message["message_id"] = source_message_id

    was_forwarded = is_forwarded(original_message)
    original_sender = (original_message.get("original_sender")
                       if was_forwarded else original_message.get("sender")) or "Unknown"
    original_date = (original_message.get("original_date")
                     if was_forwarded else original_message.get("date")) or "Unknown"
    original_receiver = (original_message.get("original_receiver")
                         if was_forwarded else (source_owner or sender)) or "Unknown"

    forward_chain = copy.deepcopy(original_message.get("forward_chain", [])) if was_forwarded else []
    if not isinstance(forward_chain, list):
        forward_chain = []
    date_str = map_screen.time_manager.get_date_string()
    forward_chain.append({"country": sender, "date": date_str})

    extra = {
        "forwarded": True,
        "forward_id": uuid.uuid4().hex,
        "original_sender": original_sender,
        "original_receiver": original_receiver,
        "original_date": original_date,
        "forwarded_by": sender,
        "forwarded_at": date_str,
        "forwarded_from_message_id": source_message_id,
        "forward_chain": forward_chain,
    }
    for key in ("action", "parameters"):
        if key in original_message:
            extra[key] = copy.deepcopy(original_message[key])

    return send_message(map_screen, sender, receiver, content,
                        original_message.get("type", "TEXT"), extra=extra,
                        llm=bool(original_message.get("llm")))

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
    "PEACE_TREATY": "We propose terms to end this war.",
    "JOIN_WARS": ("REQUEST_JOIN_WARS", "We request permission to join your ongoing wars."),
    "SEND_VOLUNTEERS": "We offer volunteer divisions for your war.",
    "RECALL_VOLUNTEERS": "We are recalling our volunteer divisions.",
    "BREAK_ALLIANCE": ("BREAK_ALLIANCE", "We have broken our alliance."),
    "DISBAND_FACTION": ("FACTION_DISBANDED", "It is a shame to see our alliance broken."),
    "KICK_FACTION_MEMBER": ("KICKED_FROM_FACTION", "We will not forget being expelled from the alliance."),
    "LEAVE_FACTION": ("FACTION_ABANDONED", "We will not forget your abandonment."),
    "CLAIM_FACTION_LEADERSHIP": ("FACTION_LEADERSHIP_TAKEN",
                                 "The pact needs a stronger hand at its head. "
                                 "It will be ours."),
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


def send_treaty_message(map_screen, sender, receiver, action, custom_msg="", parameters=None,
                        llm=False, note=""):
    """Announces an outgoing diplomatic action to its recipient.

    A trade's `parameters` ride along on the message so its terms survive the
    offer being resolved and cleared -- see send_message. `action` rides along
    for the same reason: it lives on the sender's pending_diplomacy entry,
    which is deleted on resolution, so afterwards nothing recorded whether a
    message had been a trade offer or a declaration of war.

    `note` is whatever the sender wrote to go with the offer, as opposed to the
    itemized terms. It is quoted under them so the thread reads as one letter.
    """
    extra = {"action": action}
    if parameters:
        extra["parameters"] = parameters

    body = announcement_for(action, custom_msg)
    if note:
        body = f"{body}\n\n\"{note}\""
    send_message(map_screen, sender, receiver, body, "DIPLOMACY", extra=extra, llm=llm)


def message_category(msg):
    """The kind of act a message announced, for a reader scanning a list.

    Falls back to the message's own type, so a message from a save written
    before actions were recorded still reads DIPLOMACY or TEXT rather than
    going blank.
    """
    if not isinstance(msg, dict):
        return ""
    action = msg.get("action")
    if action:
        return c.MESSAGE_CATEGORIES.get(action, "DIPLOMACY")
    return msg.get("type", "TEXT")
