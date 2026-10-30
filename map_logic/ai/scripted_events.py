"""Evaluate and perform scenario scripted events. The event editor reads its choices from this module."""

from dataclasses import dataclass
import operator
import random

import data.constants as c
from data import queries
from data.state_access import world_for, session_for
from map_logic.ai import ai_handler, ai_prompts
from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
from map_logic.diplomacy import diplomacy_messages, guarantees, military_attaches, volunteers
from map_logic.diplomacy.diplomacy_processor import action_is_legal
from map_logic.territory import ownership


@dataclass(frozen=True)
class EventRun:
    """State shared by every condition and action in one pass over the scripted events."""
    map_screen: object
    world: object
    active_nations: set
    human_players: list
    current_turn: int
    preview_request: tuple | None


# --- Conditions ------------------------------------------------------------------------------

_ORDER_COMPARISONS = {"==": operator.eq, ">": operator.gt, "<": operator.lt,
                      ">=": operator.ge, "<=": operator.le}
# Turn Number and Random conditions do not support "!=". The editor does not offer it for them.
_ALL_COMPARISONS = {**_ORDER_COMPARISONS, "!=": operator.ne}


def _int_value(text):
    return int(float(text))


def _numeric_condition(current, op, value, parse, comparisons=_ALL_COMPARISONS):
    """Compare a number to a single value or a comma-separated BETWEEN range."""
    text = str(value)
    try:
        if "BETWEEN" in op:
            parts = text.split(",")
            if len(parts) < 2:
                return False
            low, high = parse(parts[0].strip()), parse(parts[1].strip())
            return low <= current <= high if op == "BETWEEN (INC)" else low < current < high
        target = parse(text.strip())
    except ValueError:
        return False
    compare = comparisons.get(op)
    return compare(current, target) if compare else False


def _turn_number(run, _nation, condition):
    return _numeric_condition(run.current_turn, condition.get("operator", "=="), condition.get("value", ""),
                              int, _ORDER_COMPARISONS)


def _random_value(run, _nation, condition):
    # A preview must not consume random numbers, so its result is unknown.
    if run.preview_request is not None:
        return None
    return _numeric_condition(random.random(), condition.get("operator", "=="), condition.get("value", ""),
                              float, _ORDER_COMPARISONS)


def _variable(run, _nation, condition):
    op, value = condition.get("operator", "=="), condition.get("value", "")
    name = condition.get("variable", "")
    record = next((item for item in run.world.script_variables if item["name"] == name), None)
    kind, current = (record["type"], record["value"]) if record else ("string", "0")
    if kind not in ("int", "double"):
        return {"==": str(current) == str(value), "!=": str(current) != str(value)}.get(op, False)
    parse = _int_value if kind == "int" else float  # An int variable truncates when compared.
    try:
        current = parse(current)
        # Existing behavior: the whole value must be one number, even for BETWEEN.
        # A range such as "1,5" fails this parse, so numeric-variable BETWEEN is always false.
        parse(str(value).strip())
    except ValueError:
        return False
    return _numeric_condition(current, op, value, parse)


def _volunteers_sent(run, nation, condition):
    # This count follows the volunteer picker. A division in an outstanding
    # offer, travelling, or deployed is committed capacity.
    return _numeric_condition(volunteers.committed_count(run.map_screen, nation),
                              condition.get("operator", "=="), condition.get("value", ""), _int_value)


def _volunteer_capacity(run, nation, condition):
    return _numeric_condition(volunteers.remaining_capacity(run.map_screen, nation),
                              condition.get("operator", "=="), condition.get("value", ""), _int_value)


def _claims_of(run, target):
    return run.world.nation_data.get(target, {}).get("claims", [])


def _owner_of(run, province_id):
    return run.world.id_to_province.get(province_id, {}).get("owner")


def _occupying_all_claims(run, nation, target):
    claims = _claims_of(run, target)
    return bool(claims) and all(_owner_of(run, province_id) == nation for province_id in claims)


def _living(condition):
    """Require a living target country and a true result for it."""
    return lambda run, nation, target: target in run.active_nations and condition(run, nation, target)


def _nation_rule(rule):
    """Adapt a query that takes (nation, target, nation_data)."""
    return lambda run, nation, target: rule(nation, target, run.world.nation_data)


def _is_guaranteeing(run, nation, target):
    return target in guarantees.guaranteed_targets(nation, run.world.nation_data)


def _has_attache_in(run, nation, target):
    return target in military_attaches.hosts_for(nation, run.world.nation_data)


def _has_access_through(run, nation, target):
    return queries.has_military_access(nation, target, run.world.nation_data)


def _grants_access_to(run, nation, target):
    return queries.has_military_access(target, nation, run.world.nation_data)


def _negated(condition):
    return lambda run, nation, target: not condition(run, nation, target)


# These conditions take a comma-separated list of country IDs. Every country must pass.
TARGET_LIST_CONDITIONS = {
    "At War With": _living(_nation_rule(lambda *args: queries.are_at_war(*args))),
    "In Faction With": _living(_nation_rule(lambda *args: queries.are_in_same_faction(*args))),
    "Not In Faction With": _living(_negated(_nation_rule(lambda *args: queries.are_in_same_faction(*args)))),
    "Has Truce With": _living(_nation_rule(lambda *args: queries.has_active_truce(*args))),
    "At Peace With": _living(_negated(_nation_rule(lambda *args: queries.are_at_war(*args)))),
    "Country Exists": lambda run, _nation, target: target in run.active_nations,
    "Country Doesn't Exist": lambda run, _nation, target: target not in run.active_nations,
    "Occupying Claims Of": lambda run, nation, target: any(
        _owner_of(run, province_id) == nation for province_id in _claims_of(run, target)),
    "Occupying All Claims": _occupying_all_claims,
    "Guaranteeing": _living(_is_guaranteeing),
    "Not Guaranteeing": _living(_negated(_is_guaranteeing)),
    "Has Military Attaché": _living(_has_attache_in),
    "Doesn't Have Military Attaché": _living(_negated(_has_attache_in)),
    "Has Military Access Through": _living(_has_access_through),
    "Doesn't Have Military Access Through": _living(_negated(_has_access_through)),
    "Grants Military Access To": _living(_grants_access_to),
    "Doesn't Grant Military Access To": _living(_negated(_grants_access_to)),
}

# These conditions take one country ID. A blank value means the country that owns the event.
SELF_OR_TARGET_CONDITIONS = {
    "Is AI Controlled": lambda run, target: target not in run.human_players and target in run.active_nations,
    "Is Player Controlled": lambda run, target: target in run.human_players and target in run.active_nations,
    "Is At War": lambda run, target: len(queries.get_enemies(target, run.world.nation_data)) > 0,
    "Is At Peace": lambda run, target: len(queries.get_enemies(target, run.world.nation_data)) == 0,
    "Is In Faction": lambda run, target: run.world.nation_data.get(target, {}).get("faction", "") != "",
    "Not In Faction": lambda run, target: (target in run.active_nations and
                                           run.world.nation_data.get(target, {}).get("faction", "") == ""),
    "Is Faction Leader": lambda run, target: bool(queries.is_faction_leader(target, run.world.nation_data)),
}

# These quantities always describe the country that owns the event.
SELF_NUMERIC_CONDITIONS = {"Volunteer Divisions Sent": _volunteers_sent,
                           "Volunteer Capacity Remaining": _volunteer_capacity}


def _target_list_condition(condition_type):
    rule = TARGET_LIST_CONDITIONS[condition_type]

    def evaluate(run, nation, condition):
        targets = [target.strip() for target in str(condition.get("value", "")).split(",") if target.strip()]
        return bool(targets) and all(rule(run, nation, target) for target in targets)
    return evaluate


def _self_or_target_condition(condition_type):
    rule = SELF_OR_TARGET_CONDITIONS[condition_type]
    return lambda run, nation, condition: rule(run, condition.get("value", "") or nation)


def _received_action(run, nation, condition):
    op, value = condition.get("operator", "=="), condition.get("value", "")
    if run.preview_request is not None and value == run.preview_request[1]:
        return op == run.preview_request[2]
    pending_action, pending_turns = queries.get_diplomatic_status(value, nation, run.world.nation_data)
    return pending_action == op and pending_turns > 0


def _occupying_core_of(run, nation, condition):
    value = condition.get("value", "")
    return any(province.get("owner") == nation and value in province.get("cores", [])
               for province in run.world.map_data.values())


def _borders(run, nation, condition):
    return condition.get("value", "") in queries.get_neighboring_nations(
        nation, run.world.map_data, run.world.id_to_province)


CONDITIONS = {
    "Turn Number": _turn_number,
    "Variable": _variable,
    "Random (0.00 - 1.00)": _random_value,
    "Received Action": _received_action,
    "Occupying Core Of": _occupying_core_of,
    "Occupying All Cores Of": lambda run, nation, condition: queries.is_occupying_all_cores(
        nation, condition.get("value", ""), run.world.map_data),
    "Occupying Tile": lambda run, nation, condition: queries.is_occupying_tiles(
        nation, condition.get("value", ""), run.world.id_to_province),
    "Bordering": _borders,
    "Not Bordering": lambda run, nation, condition: not _borders(run, nation, condition),
    "True": lambda _run, _nation, _condition: True,
    "False": lambda _run, _nation, _condition: False,
    **SELF_NUMERIC_CONDITIONS,
    **{name: _target_list_condition(name) for name in TARGET_LIST_CONDITIONS},
    **{name: _self_or_target_condition(name) for name in SELF_OR_TARGET_CONDITIONS},
}


def _chain_condition_result(previous, current, chain):
    """Combine conditions with three-valued support for random previews."""
    if chain in ("AND", "NAND"):
        if previous is False or current is False:
            result = False
        elif previous is True and current is True:
            result = True
        else:
            result = None
        return not result if chain == "NAND" and result is not None else result
    if chain in ("OR", "NOR"):
        if previous is True or current is True:
            result = True
        elif previous is False and current is False:
            result = False
        else:
            result = None
        return not result if chain == "NOR" and result is not None else result
    if chain == "XOR":
        return (previous ^ current
                if previous is not None and current is not None else None)
    return previous


def _conditions_met(run, nation, conditions):
    """Evaluate every condition. Do not stop early: each Random condition must draw its number."""
    met = False
    for index, condition in enumerate(conditions):
        evaluate = CONDITIONS.get(condition.get("type"))
        result = evaluate(run, nation, condition) if evaluate else False
        met = result if index == 0 else _chain_condition_result(met, result, condition.get("chain", "AND"))
    return met


# --- Actions ---------------------------------------------------------------------------------

_EDIT_FIELDS = {"Edit Name": "name", "Edit Leader Name": "leader_name", "Edit Leader Title": "leader_title",
                "Edit Flag": "flag_data", "Edit Portrait": "portrait_data"}
_SCRIPTED_REQUEST_ACTIONS = {
    "Declare War": "WAR_DECLARATION", "Join Faction": "JOIN_FACTION_REQ", "Create Faction": "CREATE_FACTION",
    "Invite to Faction": "FACTION_INVITE", "Send Ceasefire": "CEASEFIRE", "Guarantee Independence": "GUARANTEE",
    "Send Military Attaché": "SEND_MILITARY_ATTACHE", "Request Military Access": "REQ_MILITARY_ACCESS",
}
_SCRIPTED_RESPONSE_ACTIONS = {
    "Accept Military Attaché": ("SEND_MILITARY_ATTACHE", diplomacy_messages.RESPONSE_ACCEPT),
    "Reject Military Attaché": ("SEND_MILITARY_ATTACHE", diplomacy_messages.RESPONSE_REJECT),
    "Accept Military Access": ("REQ_MILITARY_ACCESS", diplomacy_messages.RESPONSE_ACCEPT),
    "Reject Military Access": ("REQ_MILITARY_ACCESS", diplomacy_messages.RESPONSE_REJECT),
    "Accept Volunteer Divisions": ("SEND_VOLUNTEERS", diplomacy_messages.RESPONSE_ACCEPT),
    "Reject Volunteer Divisions": ("SEND_VOLUNTEERS", diplomacy_messages.RESPONSE_REJECT),
}
_GENERIC_RESPONSE_VERDICTS = {"Accept Proposal": diplomacy_messages.RESPONSE_ACCEPT,
                              "Reject Proposal": diplomacy_messages.RESPONSE_REJECT}
_VARIABLE_MATH = {
    "Set": lambda _current, change: change,
    "Add": operator.add,
    "Subtract": operator.sub,
    "Multiply": operator.mul,
    "Divide": lambda current, change: current / change if change != 0 else current,
}


def _action_targets(act):
    return [target.strip() for target in str(act.get("target", "None")).split(",") if target.strip()]


def _message_province_ids(act):
    return [int(part.strip()) for part in str(act.get("message", "")).split(",") if part.strip().isdigit()]


def _edit_field(_run, _nation, data, _pending, act):
    value = act.get("message", "")
    if value:
        data[_EDIT_FIELDS[act.get("type")]] = value


def _edit_color(run, nation, data, _pending, act):
    value = act.get("message", "")
    if not value:
        return
    try:
        color = tuple(map(int, value.replace(" ", "").split(",")))
    except (ValueError, AttributeError):
        return
    if len(color) == 3:
        data["color"] = list(color)
        if hasattr(run.map_screen, "nation_colors"):
            run.map_screen.nation_colors[nation] = color
        run.map_screen.centers_need_update = True


def _queue_claims(run, _nation, data, _pending, act):
    for province_id in _message_province_ids(act):
        if province_id not in run.world.id_to_province:
            continue
        queue = data.setdefault("claim_queue", [])
        if not any(item["prov_id"] == province_id for item in queue) and province_id not in data.get("claims", []):
            queue.append({"prov_id": province_id, "turns_left": c.CLAIM_TURN_NON_CORE})


def _revoke_claims(_run, _nation, data, _pending, act):
    province_ids = _message_province_ids(act)
    queue = data.setdefault("revoke_queue", [])
    for province_id in province_ids:
        if not any(item["prov_id"] == province_id for item in queue) and province_id in data.get("claims", []):
            queue.append({"prov_id": province_id, "turns_left": 1})


def _revoke_all_claims(run, _nation, _data, _pending, act):
    for target in _action_targets(act):
        if target == "None":
            continue
        target_data = run.world.nation_data.get(target, {})
        queue = target_data.setdefault("revoke_queue", [])
        for province_id in target_data.get("claims", []):
            if not any(item["prov_id"] == province_id for item in queue):
                queue.append({"prov_id": province_id, "turns_left": 1})


def _target_provinces(run, nation, act):
    """Yield each living target with each listed province the event may use for it."""
    tiles = [tile.strip() for tile in str(act.get("message", "")).split(",") if tile.strip()]
    must_control = act.get("ai_generate", False)
    for target in _action_targets(act):
        if target not in run.active_nations:
            continue
        for tile in tiles:
            if not tile.isdigit():
                continue
            province = run.world.id_to_province.get(int(tile))
            if province and not (must_control and province.get("owner") != nation):
                yield target, province


def _give_territory(run, nation, _data, _pending, act):
    for target, province in _target_provinces(run, nation, act):
        ownership.conquer_province(run.map_screen, province, target)


def _spawn_unit(run, nation, _data, _pending, act):
    library = queries.get_unit_library(run.map_screen)
    unit_type = act.get("unit_type") or queries.get_unit_for_family_year(
        library, "Infantry Type", c.DEFAULT_EQUIPMENT_YEAR, context=run.map_screen)
    for target, province in _target_provinces(run, nation, act):
        province.setdefault("units", []).append(queries.create_unit_dict(unit_type, target, library))


def _set_variable(run, _nation, _data, _pending, act):
    name, op, value = act.get("target"), act.get("unit_type", "Set"), act.get("message", "0")
    record = next((item for item in run.world.script_variables if item["name"] == name), None)
    if record is None:
        return
    if record["type"] not in ("int", "double"):
        if op == "Set":
            record["value"] = str(value)
        return
    try:
        current = float(record["value"])
        change = float(value)
        math = _VARIABLE_MATH.get(op)
        if math:
            current = math(current, change)
        record["value"] = str(int(current)) if record["type"] == "int" else str(current)
    except ValueError:
        pass


def _answer_request(run, nation, target, act, expected_action, verdict):
    pending_action, pending_turns = queries.get_diplomatic_status(target, nation, run.world.nation_data)
    if pending_turns > 0 and pending_action == expected_action:
        request = diplomacy_messages.get_pending(run.world.nation_data, target, nation)
        diplomacy_messages.set_response(run.world.nation_data, nation, target, verdict, expected_action,
                                        message=act.get("message", ""), parameters=request.get("parameters"))


def _answer_proposal(run, nation, target, act):
    # Answering a proposal is its own channel, not a pending action.
    pending_action, pending_turns = queries.get_diplomatic_status(target, nation, run.world.nation_data)
    if pending_turns > 0 and pending_action in c.BILATERAL_ACTIONS:
        _answer_request(run, nation, target, act, pending_action, _GENERIC_RESPONSE_VERDICTS[act.get("type")])


def _offer_volunteers(run, nation, pending, target, act):
    # Scripted events cannot open the player's unit picker. Instead, reserve the
    # requested number of eligible divisions in the stable map order. This creates
    # the same reversible offer and travel state as the normal picker.
    if target in pending:
        return
    try:
        count = int(str(act.get("message", "1")).strip() or "1")
    except ValueError:
        count = 1
    count = max(1, count)
    if act.get("send_up_to", False):
        count = min(count, volunteers.remaining_capacity(run.map_screen, nation))
    chosen = volunteers.available_units(run.map_screen, nation)[:count]
    details, error = volunteers.create_offer(run.map_screen, nation, target, chosen)
    if not error:
        lifecycle.put_request(run.world.nation_data, nation, target, **{
            "action": volunteers.ACTION,
            "turns": 0,
            "timer": 0,
            "message": (f"We offer {details['count']} volunteer "
                        f"{'division' if details['count'] == 1 else 'divisions'}."),
            "parameters": details,
        })


def _send_request(run, nation, pending, target, act, action):
    if target in pending and isinstance(pending[target], dict) and pending[target].get("action") == action:
        return
    # Scripted events bypass the player UI, so they must ask the shared diplomacy
    # guard before entering pending_diplomacy. This keeps an authored event from
    # starting an illegal war, faction change, or diplomatic request merely
    # because the board changed since it was made.
    legal, reason = action_is_legal(run.map_screen, nation, target, action)
    if not legal:
        print(f"[SCRIPTED EVENT] Skipping {action} from {nation} to {target}: {reason}.")
        return
    custom_message = act.get("message", "")
    lifecycle.put_request(run.world.nation_data, nation, target, **{
        "action": action,
        "turns": 0,
        "timer": 0,
        "message": custom_message,
    })
    if act.get("ai_generate", False):
        # Generated here rather than queued. Scripted events run *after* the LLM
        # pass, so anything appended to its task list is never picked up. There
        # are only ever a handful of these in a turn, so an inline call costs
        # little and makes the option real.
        generated = ai_handler.generate_proactive_text(
            run.world.nation_data, run.active_nations, nation, target,
            ai_prompts.get_proactive_action_context(action, target),
            run.human_players, ai_handler.CURRENT_TURN_ID)
        pending[target]["message"] = generated or custom_message or "We have sent a diplomatic missive."


def _diplomatic_action(run, nation, _data, pending, act):
    """Perform a diplomatic action for each comma-separated target."""
    action_type = act.get("type")
    for target in _action_targets(act):
        if target == "None":
            continue
        if action_type in _GENERIC_RESPONSE_VERDICTS:
            _answer_proposal(run, nation, target, act)
        elif action_type in _SCRIPTED_RESPONSE_ACTIONS:
            # Specific answers make a scenario's intent visible at a glance, while
            # the generic accept and reject actions remain for old scenarios and
            # broad event logic. They can never answer the wrong offer.
            _answer_request(run, nation, target, act, *_SCRIPTED_RESPONSE_ACTIONS[action_type])
        elif action_type == "Offer Volunteer Divisions":
            _offer_volunteers(run, nation, pending, target, act)
        elif action_type == "Send Custom Message":
            _send_request(run, nation, pending, target, act, f"MSG:{act.get('message', '')}")
        elif action_type in _SCRIPTED_REQUEST_ACTIONS:
            _send_request(run, nation, pending, target, act, _SCRIPTED_REQUEST_ACTIONS[action_type])


ACTIONS = {
    **{name: _edit_field for name in _EDIT_FIELDS},
    "Edit Color": _edit_color,
    "Queue Claims": _queue_claims,
    "Revoke Claims": _revoke_claims,
    "Revoke All Claims": _revoke_all_claims,
    "Give Territory": _give_territory,
    "Spawn Unit": _spawn_unit,
    "Set Variable": _set_variable,
}

# --- Editor choices --------------------------------------------------------------------------

COND_TYPES = [
    "Turn Number", "Variable", "At War With", "Is At War", "In Faction With",
    "Not In Faction With", "Is In Faction", "Not In Faction", "Is Faction Leader", "Has Truce With",
    "At Peace With", "Is At Peace", "Random (0.00 - 1.00)", "Received Action",
    "Country Exists", "Country Doesn't Exist", "Occupying Core Of",
    "Occupying All Cores Of", "Occupying Claims Of", "Occupying All Claims",
    "Occupying Tile", "Is AI Controlled", "Is Player Controlled", "Bordering",
    "Not Bordering", "Guaranteeing", "Not Guaranteeing", "Has Military Attaché",
    "Doesn't Have Military Attaché", "Has Military Access Through",
    "Doesn't Have Military Access Through", "Grants Military Access To",
    "Doesn't Grant Military Access To", "Volunteer Divisions Sent",
    "Volunteer Capacity Remaining", "True", "False",
]
CHAIN_OPS = ["AND", "OR", "XOR", "NOR", "NAND"]
NUMERIC_OPS = ["==", "!=", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]
TURN_OPS = ["==", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]
TARGET_LIST_TYPES = list(TARGET_LIST_CONDITIONS)
SELF_NUMERIC_CONDITION_TYPES = list(SELF_NUMERIC_CONDITIONS)
SELF_OR_TARGET_TYPES = list(SELF_OR_TARGET_CONDITIONS)
EDIT_ACTIONS = ["Edit Name", "Edit Leader Name", "Edit Leader Title",
                "Edit Color", "Edit Flag", "Edit Portrait"]
ACT_TYPES = ["Declare War", "Join Faction", "Create Faction", "Invite to Faction",
             "Accept Proposal", "Reject Proposal", "Send Ceasefire", "Send Custom Message",
             "Queue Claims", "Revoke Claims", "Revoke All Claims", "Give Territory",
             "Spawn Unit", "Set Variable", "Guarantee Independence",
             "Send Military Attaché", "Request Military Access",
             "Offer Volunteer Divisions", "Accept Military Attaché",
             "Reject Military Attaché", "Accept Military Access",
             "Reject Military Access", "Accept Volunteer Divisions",
             "Reject Volunteer Divisions"] + EDIT_ACTIONS
VAR_MATH_OPS = list(_VARIABLE_MATH)


# --- Event processing ------------------------------------------------------------------------

def _scripted_event_response(actions, sender_nation, request_action):
    """Return the last scripted answer matching this hypothetical request."""
    response = None
    matched = False
    for action in actions:
        action_type = action.get("type")
        if action_type in _GENERIC_RESPONSE_VERDICTS:
            expected_action = request_action
            verdict = _GENERIC_RESPONSE_VERDICTS[action_type]
            if request_action not in c.BILATERAL_ACTIONS:
                continue
        else:
            expected_action, verdict = _SCRIPTED_RESPONSE_ACTIONS.get(action_type, (None, None))
        if expected_action != request_action:
            continue
        if sender_nation in _action_targets(action):
            response = verdict
            matched = True
    return matched, response


def scripted_event_response_preview(map_screen, nation, sender, action):
    """Predict a scripted response without mutating state or consuming RNG."""
    return process_scripted_events(map_screen, preview_request=(nation, sender, action))


def _event_can_fire(event, index, fired_events, nation, human_players):
    if index in fired_events and event.get("fire_once", True):
        return False
    trigger = event.get("trigger_type", "AI Only")
    if trigger == "AI Only" and nation in human_players:
        return False
    if trigger == "Player Only" and nation not in human_players:
        return False
    return bool(event.get("conditions", []))


def process_scripted_events(map_screen, preview_request=None):
    """Processes scenario-specific scripted events for AI nations."""
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    if not queries.get_scenario_flag("use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS, world_state.scenario_settings):
        return None

    run = EventRun(map_screen, world_state, set(queries.get_living_nations(world_state.map_data)),
                   session_state.active_players, queries.get_total_turns(world_state.time_manager), preview_request)
    preview_response = None
    preview_unknown = False

    for nation in run.active_nations:
        if preview_request is not None and nation != preview_request[0]:
            continue
        data = world_state.nation_data.get(nation, {})
        events = data.get("scripted_events", [])
        if not events:
            continue
        fired_events = (data.get("fired_scripted_events", [])
                        if preview_request is not None
                        else data.setdefault("fired_scripted_events", []))

        for index, event in enumerate(events):
            if not _event_can_fire(event, index, fired_events, nation, run.human_players):
                continue
            met = _conditions_met(run, nation, event["conditions"])

            if preview_request is not None:
                matched, response = _scripted_event_response(
                    event.get("actions", []), preview_request[1], preview_request[2])
                if matched and met is None:
                    preview_response = None
                    preview_unknown = True
                elif matched and met:
                    preview_response = response
                    preview_unknown = False
                continue

            if met:
                pending = data.setdefault("pending_diplomacy", {})
                for act in event.get("actions", []):
                    ACTIONS.get(act.get("type"), _diplomatic_action)(run, nation, data, pending, act)
                if event.get("fire_once", True) and index not in fired_events:
                    fired_events.append(index)

    if preview_request is not None:
        if preview_unknown:
            return "MAYBE"
        if preview_response == diplomacy_messages.RESPONSE_ACCEPT:
            return "YES"
        if preview_response == diplomacy_messages.RESPONSE_REJECT:
            return "NO"
    return None
