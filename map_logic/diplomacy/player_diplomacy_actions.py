from data import queries
from map_logic.diplomacy import diplomacy_logic
import data.constants as c


def _queue_and_report(map_screen, target, action_type, custom_msg):
    """Hands a validated action to the engine and reports what it said.

    Closing the mail box and echoing the engine's message is the tail of every
    "queue this offer" path, so it lives here rather than at each caller.
    """
    msg = diplomacy_logic.toggle_diplomacy_action(
        map_screen.nation_data, map_screen.player_country, target, action_type, custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)


def handle_declare_war(map_screen):
    player = map_screen.player_country
    target = map_screen.selected_province.get("owner")
    
    p_data = map_screen.nation_data.get(player, {})
    t_data = map_screen.nation_data.get(target, {})
    
    my_master = p_data.get("master", "")
    my_type = p_data.get("puppet_type", "")
    
    t_master = t_data.get("master", "")
    t_type = t_data.get("puppet_type", "")
    
    # 1 & 2. Puppets (Integrated and Autonomous) can ONLY declare independence wars
    if my_master and target != my_master:
        map_screen.show_feedback("Puppets can only declare war on their master!")
        return
        
    # 3. Cannot declare war ON an integrated puppet
    if t_master and t_type == c.PUPPET_TYPE_INTEGRATED:
        if t_master == player:
            map_screen.show_feedback("Cannot declare war on your own integrated puppet! (You can just annex them)")
        else:
            map_screen.show_feedback(f"Integrated puppets cannot be declared war on! Declare on {t_master} instead.")
        return

    if target in map_screen.nation_data.get(player, {}).get("puppets", []):
        if t_type == c.PUPPET_TYPE_INTEGRATED:
            map_screen.show_feedback("Cannot declare war on your own integrated puppet!")
            return
        
    at_war = queries.are_at_war(player, target, map_screen.nation_data)
    
    if at_war:
        handle_ceasefire(map_screen)
        return

    # Prevent declaring war on your own faction
    if queries.are_in_same_faction(player, target, map_screen.nation_data):
        is_rebellion = (my_master == target and my_type == c.PUPPET_TYPE_AUTONOMOUS)
        is_preemptive = (t_master == player and t_type == c.PUPPET_TYPE_AUTONOMOUS)
        if not (is_rebellion or is_preemptive):
            map_screen.show_feedback("Cannot declare war on a faction member!")
            return

    # Prevent declaring war with active truce
    if queries.has_active_truce(player, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot declare war while a truce is active!")
        return

    # Direct import to bypass __init__.py namespace issues
    from ui.player_diplomacy_menus import open_wargoal_selection_menu
    open_wargoal_selection_menu(map_screen, target)

def open_claims_menu(map_screen):
    from ui.player_diplomacy_menus import open_claims_menu
    open_claims_menu(map_screen)

def handle_ceasefire(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # Guard check: Prevent modifying or opening a peace offer if it has already been sent (turns > 0)
    pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, target, map_screen.nation_data)
    if pending_action in ["PEACE_TREATY", "CEASEFIRE"] and pending_turns > 0:
        map_screen.show_feedback("You must wait for their response to your peace offer!")
        return
        
    # Direct import to bypass __init__.py namespace issues
    from ui.player_diplomacy_menus import open_peace_menu
    open_peace_menu(map_screen, target)

def open_puppets_menu(map_screen):
    from ui.player_diplomacy_menus import open_puppets_menu
    open_puppets_menu(map_screen)

def handle_specific_action(map_screen, action_type):
    """A clean, generic handler replacing the overloaded faction button logic."""
    target = map_screen.selected_province.get("owner")
        
    custom_msg = map_screen.mail_draft_text.strip()
    
    # Block puppets from creating/joining factions independently
    if action_type in ["CREATE_FACTION", "JOIN_FACTION_REQ", "FACTION_INVITE", "LEAVE_FACTION", "DISBAND_FACTION", "KICK_FACTION_MEMBER"]:
        if map_screen.nation_data.get(map_screen.player_country, {}).get("master"):
            map_screen.show_feedback("Puppets cannot handle faction diplomacy independently!")
            return

    # Pre-flight Check: Ensure we don't accidentally leave/disband while an invite is pending
    if action_type in ["LEAVE_FACTION", "DISBAND_FACTION"]:
        player_pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {})
        has_blocking_action = False
        invites_to_cancel = []
        
        # Scan through the pending diplomacy dict safely
        for other_nation, info in list(player_pending.items()):
            act = info.get("action", "") if isinstance(info, dict) else info
            tns = info.get("turns", 0) if isinstance(info, dict) else 0
            
            if act == "FACTION_INVITE":
                if tns > 0:
                    has_blocking_action = True
                else:
                    invites_to_cancel.append(other_nation)
            elif act in ["JOIN_WARS", "CALL_TO_ARMS"]:
                has_blocking_action = True
        
        # Block the action entirely if an invite is en route or military action is pending
        if has_blocking_action:
            map_screen.show_feedback("Cannot leave with pending invites or military actions!")
            return
        
        # Silently cancel any unsent invites and proceed
        if invites_to_cancel:
            for n in invites_to_cancel:
                del player_pending[n]

    # Pass the validated action down to the engine
    _queue_and_report(map_screen, target, action_type, custom_msg)

def _answer_incoming_request(map_screen, target, verdict, custom_msg):
    """Shared plumbing for the Accept / Reject buttons.

    Answers live in their own channel, so queueing one never disturbs an offer we
    already have travelling towards the same nation.
    """
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)
    if incoming_turns <= 0 or action not in c.BILATERAL_ACTIONS:
        return None

    # Re-clicking the same verdict is an undo, handled inside the toggle.
    queued_verdict, queued_action = diplomacy_logic.get_response_status(
        map_screen.nation_data, map_screen.player_country, target)
    is_undo = (queued_verdict == verdict and queued_action == action)

    if custom_msg is None:
        custom_msg = map_screen.mail_draft_text.strip()

    # The terms belong to their offer -- carry them so nothing is lost.
    their_pending = map_screen.nation_data.get(target, {}).get("pending_diplomacy", {}).get(map_screen.player_country, {})
    params = their_pending.get("parameters") if isinstance(their_pending, dict) else None

    msg = diplomacy_logic.toggle_diplomatic_response(
        map_screen.nation_data, map_screen.player_country, target,
        verdict, action, custom_msg, parameters=params)

    if not is_undo:
        map_screen.mail_draft_text = ""
        map_screen.mail_input_active = False
    map_screen.refresh_diplomacy_maps()
    map_screen.show_feedback(msg)
    return msg


def handle_accept_req(map_screen, target=None, custom_msg=None):
    """Processes the execution of accepting an incoming proposal."""
    if not target:
        target = map_screen.selected_province.get("owner")

    action, _turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    # Undoing an acceptance needs no eligibility check -- it only removes a queued answer.
    queued_verdict, queued_action = diplomacy_logic.get_response_status(
        map_screen.nation_data, map_screen.player_country, target)
    if not (queued_verdict == diplomacy_logic.RESPONSE_ACCEPT and queued_action == action):
        my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")

        if action == "FACTION_INVITE":
            if my_faction:
                map_screen.show_feedback("Must leave your current faction first!")
                return
        elif action == "JOIN_FACTION_REQ":
            # They are joining OUR faction, so having one is a requirement, not a blocker.
            if not queries.is_faction_leader(map_screen.player_country, map_screen.nation_data):
                map_screen.show_feedback("You are no longer the leader, cannot accept!")
                return
        elif action == "CREATE_FACTION":
            if my_faction:
                map_screen.show_feedback("Must leave your current faction first!")
                return
        elif action in ["JOIN_WARS", "CALL_TO_ARMS"]:
            if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
                map_screen.show_feedback("You must be in the same faction to do this!")
                return

    _answer_incoming_request(map_screen, target, diplomacy_logic.RESPONSE_ACCEPT, custom_msg)


def handle_reject_req(map_screen, target=None, custom_msg=None):
    """Processes the execution of rejecting an incoming proposal."""
    if not target:
        target = map_screen.selected_province.get("owner")

    _answer_incoming_request(map_screen, target, diplomacy_logic.RESPONSE_REJECT, custom_msg)

def _handle_faction_assist(map_screen, action, at_war_msg, not_allied_msg, leaving_msg):
    """Queues one of the two "help a faction partner fight" requests.

    Join Wars and Call to Arms ran the same three gates in the same order and
    differed only in the action string and the wording of each refusal, so the
    wording is now the parameter and the gates are written once.
    """
    target = map_screen.selected_province.get("owner")
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback(at_war_msg)
        return
    if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback(not_allied_msg)
        return

    # A nation on its way out of the faction cannot commit it to anything.
    self_action, self_turns = queries.get_diplomatic_status(map_screen.player_country, map_screen.player_country, map_screen.nation_data)
    if self_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
        map_screen.show_feedback(leaving_msg)
        return

    _queue_and_report(map_screen, target, action, map_screen.mail_draft_text.strip())

def handle_join_wars(map_screen):
    _handle_faction_assist(map_screen, "JOIN_WARS",
                           "You cannot join the wars of an enemy!",
                           "You must be in the same faction to assist them!",
                           "Cannot join wars while leaving the faction!")

def handle_call_to_arms(map_screen):
    _handle_faction_assist(map_screen, "CALL_TO_ARMS",
                           "Cannot call enemies to arms!",
                           "You must be in the same faction to call them to arms!",
                           "Cannot call to arms while leaving the faction!")