"""Declare diplomatic categories, legality, and existing execution phases."""

# Constants import these definitions during initialization. Load rule dependencies inside checks so definitions remain available during that import.


from types import SimpleNamespace


from dataclasses import dataclass


@dataclass(frozen=True)
class Availability:
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class ActionDefinition:
    category: str
    phase: str
    legality: object


def _check_existing(context, sender, target, action_type, nation_data, sender_data, target_data):
    # These actions retain their effect owner's checks and existing idempotent behavior.
    # This refactor adds no independent proposal restriction for them.
    return True, ""


def _check_subject_control(context, sender, target, action_type, nation_data, sender_data, target_data):
    if target_data.get("master") != sender:
        return False, "You can only issue this action for your own subject."
    return True, ""


def _check_faction_control(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    if not queries.is_faction_leader(sender, nation_data):
        return False, "Only a faction leader may issue this action."
    if action_type == "KICK_FACTION_MEMBER" and not queries.are_in_same_faction(sender, target, nation_data):
        return False, "That country is outside your faction."
    return True, ""


def _check_war_declaration(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if sender == target:
        return (False, 'a country cannot declare war on itself')
    if queries.are_at_war(sender, target, nation_data):
        return (False, 'the countries are already at war')
    sender_master = sender_data.get('master', '')
    target_master = target_data.get('master', '')
    sender_type = sender_data.get('puppet_type', '')
    target_type = target_data.get('puppet_type', '')
    if sender_master and sender_master != target:
        return (False, 'a puppet may only declare war on its master')
    if target_master and target_type == c.PUPPET_TYPE_INTEGRATED:
        return (False, 'integrated puppets cannot be declared on')
    subject_war = sender_master == target and sender_type == c.PUPPET_TYPE_AUTONOMOUS or (target_master == sender and target_type == c.PUPPET_TYPE_AUTONOMOUS)
    if queries.are_in_same_faction(sender, target, nation_data) and (not subject_war):
        return (False, 'the countries are in the same faction')
    if queries.has_active_truce(sender, target, nation_data):
        return (False, 'the countries have an active truce')
    return True, ""

def _check_ceasefire(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if not peace_scope.has_settleable_war(sender, target, nation_data):
        return (False, 'there is no war these countries may settle')
    return True, ""

def _check_faction_invite(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if queries.get_scenario_flag("disable_factions", c.DEFAULT_DISABLE_FACTIONS, getattr(world_state, "scenario_settings", {})):
        return (False, 'factions are disabled')
    leadership_error = queries.faction_request_leadership_error(sender, target, action_type, nation_data)
    if leadership_error:
        return (False, leadership_error)
    if not queries.can_choose_own_faction(target, nation_data):
        return (False, "a puppet follows its master's faction")
    if target_data.get('faction', ''):
        return (False, 'the target is already in a faction')
    return True, ""

def _check_join_faction_req(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if queries.get_scenario_flag("disable_factions", c.DEFAULT_DISABLE_FACTIONS, getattr(world_state, "scenario_settings", {})):
        return (False, 'factions are disabled')
    if not queries.can_choose_own_faction(sender, nation_data):
        return (False, "a puppet follows its master's faction")
    if sender_data.get('faction', ''):
        return (False, 'the sender is already in a faction')
    leadership_error = queries.faction_request_leadership_error(sender, target, action_type, nation_data)
    if leadership_error:
        return (False, leadership_error)
    if queries.are_at_war(sender, target, nation_data):
        return (False, 'the countries are at war')
    return True, ""

def _check_create_faction(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if queries.get_scenario_flag("disable_factions", c.DEFAULT_DISABLE_FACTIONS, getattr(world_state, "scenario_settings", {})):
        return (False, 'factions are disabled')
    if not queries.can_choose_own_faction(sender, nation_data) or not queries.can_choose_own_faction(target, nation_data):
        return (False, 'puppets cannot found factions independently')
    if sender_data.get('faction', '') or target_data.get('faction', ''):
        return (False, 'both founders must be outside factions')
    return True, ""

def _check_guarantee(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    legal, reason = guarantees.is_eligible(sender, target, nation_data)
    if not legal:
        return (False, reason)
    return True, ""

def _check_send_military_attache(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    legal, reason = military_attaches.is_eligible(sender, target, nation_data)
    if not legal:
        return (False, reason)
    return True, ""

def _check_req_military_access(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if sender == target:
        return (False, 'a country already has access to itself')
    if queries.are_at_war(sender, target, nation_data):
        return (False, 'enemies cannot request military access')
    if queries.has_military_access(sender, target, nation_data):
        return (False, 'military access is already granted')
    return True, ""

def _check_join_wars(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if not queries.are_in_same_faction(sender, target, nation_data):
        return (False, 'the countries are not in the same faction')
    if not war_calls.is_honest(action_type, sender, target, nation_data):
        return (False, 'there is no unshared war to join')
    return True, ""

def _check_leave_faction(context, sender, target, action_type, nation_data, sender_data, target_data):
    from data import queries
    import data.constants as c
    from data.state_access import world_for
    from map_logic.diplomacy import peace_scope, guarantees, military_attaches, war_calls
    world_state = world_for(context)
    if not sender_data.get("faction"):
        return False, "the sender is outside a faction"
    if not queries.can_choose_own_faction(sender, nation_data):
        return False, "a puppet follows its master's faction"
    return True, ""

ACTION_DEFINITIONS = {
    'WAR_DECLARATION': ActionDefinition('unilateral', 'send', _check_war_declaration),
    'BREAK_ALLIANCE': ActionDefinition('unilateral', 'send', _check_existing),
    'KICK_FACTION_MEMBER': ActionDefinition('unilateral', 'send', _check_faction_control),
    'LEAVE_FACTION': ActionDefinition('unilateral', 'send', _check_leave_faction),
    'DISBAND_FACTION': ActionDefinition('unilateral', 'send', _check_faction_control),
    'CLAIM_FACTION_LEADERSHIP': ActionDefinition('unilateral', 'send', _check_existing),
    'JUSTIFY_WARGOAL': ActionDefinition('unilateral', 'send', _check_existing),
    'ANNEX_PUPPET': ActionDefinition('unilateral', 'send', _check_subject_control),
    'RELEASE_PUPPET': ActionDefinition('unilateral', 'send', _check_subject_control),
    'TAKE_PUPPETS': ActionDefinition('unilateral', 'send', _check_subject_control),
    'CANCEL_MILITARY_ACCESS': ActionDefinition('unilateral', 'send', _check_existing),
    'REVOKE_MILITARY_ACCESS': ActionDefinition('unilateral', 'send', _check_existing),
    'FORWARD_MESSAGE': ActionDefinition('unilateral', 'send', _check_existing),
    'RECALL_VOLUNTEERS': ActionDefinition('unilateral', 'send', _check_existing),
    'SEND_HOME_VOLUNTEERS': ActionDefinition('unilateral', 'send', _check_existing),
    'GUARANTEE': ActionDefinition('unilateral', 'send', _check_guarantee),
    'REVOKE_GUARANTEE': ActionDefinition('unilateral', 'send', _check_existing),
    'WITHDRAW_MILITARY_ATTACHE': ActionDefinition('unilateral', 'send', _check_existing),
    'REVOKE_MILITARY_ATTACHE': ActionDefinition('unilateral', 'send', _check_existing),
    'JOIN_WARS': ActionDefinition('bilateral', 'reply', _check_join_wars),
    'FACTION_INVITE': ActionDefinition('bilateral', 'reply', _check_faction_invite),
    'JOIN_FACTION_REQ': ActionDefinition('bilateral', 'reply', _check_join_faction_req),
    'CEASEFIRE': ActionDefinition('bilateral', 'reply', _check_ceasefire),
    'CALL_TO_ARMS': ActionDefinition('bilateral', 'reply', _check_join_wars),
    'CREATE_FACTION': ActionDefinition('bilateral', 'reply', _check_create_faction),
    'PEACE_TREATY': ActionDefinition('bilateral', 'reply', _check_ceasefire),
    'TRADE': ActionDefinition('bilateral', 'reply', _check_existing),
    'REQ_MILITARY_ACCESS': ActionDefinition('bilateral', 'reply', _check_req_military_access),
    'SEND_MILITARY_ATTACHE': ActionDefinition('bilateral', 'reply', _check_send_military_attache),
    'SEND_VOLUNTEERS': ActionDefinition('bilateral', 'reply', _check_existing),
}

UNILATERAL_ACTIONS = [action for action, definition in ACTION_DEFINITIONS.items() if definition.category == "unilateral"]
BILATERAL_ACTIONS = [action for action, definition in ACTION_DEFINITIONS.items() if definition.category == "bilateral"]


def availability(context, sender, target, action, *, phase="draft"):
    """Check game rules independently of selection, player authority, and AI preference."""
    from data.state_access import world_for
    world = world_for(context)
    if isinstance(world, dict):
        # Public helpers also accept standalone country records at input boundaries.
        world = SimpleNamespace(nation_data=world, scenario_settings={})
        context = world
    nation_data = world.nation_data
    sender_data, target_data = nation_data.get(sender), nation_data.get(target)
    if not isinstance(sender_data, dict) or not isinstance(target_data, dict):
        return Availability(False, "one of the countries no longer exists")
    if not isinstance(action, str):
        return Availability(False, "invalid diplomatic action")
    if action.startswith("MSG:"):
        return Availability(True)
    definition = ACTION_DEFINITIONS.get(action)
    if definition is None:
        return Availability(False, "unknown diplomatic action")
    allowed, reason = definition.legality(context, sender, target, action, nation_data, sender_data, target_data)
    return Availability(allowed, reason)
