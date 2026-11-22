"""Evaluate and perform scenario scripted events. The event editor reads its choices from this module."""

from dataclasses import dataclass
from functools import partial
from typing import Callable
import operator
import random

import data.constants as c
from data import queries
from data.state_access import world_for, session_for
from map_logic.ai import ai_handler, ai_prompts
from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
from map_logic.diplomacy import diplomacy_messages, global_rules, guarantees, military_attaches, volunteers
from map_logic.diplomacy.diplomacy_processor import action_is_legal
from map_logic.territory import ownership


@dataclass(frozen=True)
class EventRun:
    """State shared by every condition and action in one pass over the scripted events."""
    context: object
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
    return _numeric_condition(volunteers.committed_count(run.context, nation),
                              condition.get("operator", "=="), condition.get("value", ""), _int_value)


def _volunteer_capacity(run, nation, condition):
    return _numeric_condition(volunteers.remaining_capacity(run.context, nation),
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
def _all_targets(rule):
    """Require a matching result for every country in the list."""
    def evaluate(run, nation, condition):
        targets = [target.strip() for target in str(condition.get("value", "")).split(",") if target.strip()]
        return bool(targets) and all(rule(run, nation, target) for target in targets)
    return evaluate


def _target_or_self(rule):
    """Use the event owner when the country field is blank."""
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


@dataclass(frozen=True)
class Condition:
    evaluate: Callable
    field: str
    help_text: str


CONDITIONS = {
    'Turn Number': Condition(_turn_number, 'turn', 'Turn Number: Checks if the current game turn matches the specified value'),
    'Variable': Condition(_variable, 'variable', 'Variable: Compares a selected global variable against a static value (supports math operators for numerical variables)'),
    'At War With': Condition(_all_targets(_living(_nation_rule(queries.are_at_war))), 'countries', 'At War With: Checks if the nation is at war with the specified target(s) (comma-separated)'),
    'Is At War': Condition(_target_or_self(lambda run, target: len(queries.get_enemies(target, run.world.nation_data)) > 0), 'country_or_self', 'Is At War: Checks if the target nation (or self if blank) is currently in any war'),
    'In Faction With': Condition(_all_targets(_living(_nation_rule(queries.are_in_same_faction))), 'countries', 'In Faction With: Checks if the nation shares a faction with the target(s)'),
    'Not In Faction With': Condition(_all_targets(_living(_negated(_nation_rule(queries.are_in_same_faction)))), 'countries', 'Not In Faction With: Checks if the nation does NOT share a faction with the target(s)'),
    'Is In Faction': Condition(_target_or_self(lambda run, target: queries.get_country_faction(target, run.world.nation_data) != ""), 'country_or_self', 'Is In Faction: Checks if the target nation (or self if blank) is currently in any faction'),
    'Not In Faction': Condition(_target_or_self(lambda run, target: (target in run.active_nations and queries.get_country_faction(target, run.world.nation_data) == "")), 'country_or_self', 'Not In Faction: Checks if the target nation (or self if blank) is currently outside every faction'),
    'Is Faction Leader': Condition(_target_or_self(lambda run, target: bool(queries.is_faction_leader(target, run.world.nation_data))), 'country_or_self', 'Is Faction Leader: Checks if the target nation (or self if blank) is the leader of their faction'),
    'Has Truce With': Condition(_all_targets(_living(_nation_rule(queries.has_active_truce))), 'countries', 'Has Truce With: Checks if the nation has an active truce with the specified target(s) (comma-separated)'),
    'At Peace With': Condition(_all_targets(_living(_negated(_nation_rule(queries.are_at_war)))), 'countries', 'At Peace With: Checks if the nation is explicitly NOT at war with the target(s)'),
    'Is At Peace': Condition(_target_or_self(lambda run, target: len(queries.get_enemies(target, run.world.nation_data)) == 0), 'country_or_self', 'Is At Peace: Checks if the target nation (or self if blank) is in ZERO wars'),
    'Random (0.00 - 1.00)': Condition(_random_value, 'random', 'Random (0.00 - 1.00): Returns a random value between 0.0 and 1.0'),
    'Received Action': Condition(_received_action, 'received_action', 'Received Action: Checks if a specific diplomatic action is pending from a specific sender'),
    'Country Exists': Condition(_all_targets(lambda run, _nation, target: target in run.active_nations), 'countries', 'Country Exists: Checks if the target(s) currently hold territory on the map'),
    "Country Doesn't Exist": Condition(_all_targets(lambda run, _nation, target: target not in run.active_nations), 'countries', "Country Doesn't Exist: Checks if the target(s) are completely wiped off the map"),
    'Occupying Core Of': Condition(_occupying_core_of, 'country', 'Occupying Core Of: Checks if the nation occupies any core of the target'),
    'Occupying All Cores Of': Condition(lambda run, nation, condition: queries.is_occupying_all_cores(nation, condition.get("value", ""), run.world.map_data), 'compare_countries', 'Occupying All Cores Of: Checks if the nation occupies EVERY core of the target'),
    'Occupying Claims Of': Condition(_all_targets(lambda run, nation, target: any(_owner_of(run, province_id) == nation for province_id in _claims_of(run, target))), 'countries', 'Occupying Claims Of: Checks if the nation occupies any claim of the target'),
    'Occupying All Claims': Condition(_all_targets(_occupying_all_claims), 'countries', 'Occupying All Claims: Checks if the nation occupies EVERY claim of the target'),
    'Occupying Tile': Condition(lambda run, nation, condition: queries.is_occupying_tiles(nation, condition.get("value", ""), run.world.id_to_province), 'compare_tiles', 'Occupying Tile: Checks if the nation occupies specific province IDs (comma-separated)'),
    'Is AI Controlled': Condition(_target_or_self(lambda run, target: target not in run.human_players and target in run.active_nations), 'country_or_self', 'Is AI Controlled: Checks if the target nation (or self if blank) is controlled by AI'),
    'Is Player Controlled': Condition(_target_or_self(lambda run, target: target in run.human_players and target in run.active_nations), 'country_or_self', 'Is Player Controlled: Checks if the target nation (or self if blank) is controlled by a human'),
    'Bordering': Condition(_borders, 'country', 'Bordering / Not Bordering: Checks physical adjacency to the target'),
    'Not Bordering': Condition(lambda run, nation, condition: not _borders(run, nation, condition), 'country', ''),
    'Guaranteeing': Condition(_all_targets(_living(_is_guaranteeing)), 'countries', 'Guaranteeing / Not Guaranteeing: Checks whether this country guarantees each target country'),
    'Not Guaranteeing': Condition(_all_targets(_living(_negated(_is_guaranteeing))), 'countries', ''),
    'Has Military Attaché': Condition(_all_targets(_living(_has_attache_in)), 'countries', "Has / Doesn't Have Military Attaché: Checks whether this country has an attaché at each target country"),
    "Doesn't Have Military Attaché": Condition(_all_targets(_living(_negated(_has_attache_in))), 'countries', ''),
    'Has Military Access Through': Condition(_all_targets(_living(_has_access_through)), 'countries', "Has / Doesn't Have Military Access Through: Checks whether this country can move through each target country's territory"),
    "Doesn't Have Military Access Through": Condition(_all_targets(_living(_negated(_has_access_through))), 'countries', ''),
    'Grants Military Access To': Condition(_all_targets(_living(_grants_access_to)), 'countries', "Grants / Doesn't Grant Military Access To: Checks whether each target country can move through this country's territory"),
    "Doesn't Grant Military Access To": Condition(_all_targets(_living(_negated(_grants_access_to))), 'countries', ''),
    'Volunteer Divisions Sent': Condition(_volunteers_sent, 'count', "Volunteer Divisions Sent: Compares this country's volunteer divisions currently reserved, travelling, or deployed"),
    'Volunteer Capacity Remaining': Condition(_volunteer_capacity, 'count', 'Volunteer Capacity Remaining: Compares how many more volunteer divisions this country may currently send'),
    'True': Condition(lambda _run, _nation, _condition: True, 'none', ''),
    'False': Condition(lambda _run, _nation, _condition: False, 'none', ''),
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
        definition = CONDITIONS.get(condition.get("type"))
        result = definition.evaluate(run, nation, condition) if definition else False
        met = result if index == 0 else _chain_condition_result(met, result, condition.get("chain", "AND"))
    return met


# --- Actions ---------------------------------------------------------------------------------

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


def _edit_field(_run, _nation, data, _pending, act, *, field):
    value = act.get("message", "")
    if value:
        data[field] = value


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
        if hasattr(run.context, "nation_colors"):
            run.context.nation_colors[nation] = color
        run.context.centers_need_update = True


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
        ownership.conquer_province(run.context, province, target)


def _spawn_unit(run, nation, _data, _pending, act):
    library = queries.get_unit_library(run.context)
    unit_type = act.get("unit_type") or queries.get_unit_for_family_year(
        library, "Infantry Type", c.DEFAULT_EQUIPMENT_YEAR, context=run.context)
    for target, province in _target_provinces(run, nation, act):
        province.setdefault("units", []).append(
            queries.create_unit_dict(unit_type, target, library, world_for(run.context).nation_data))


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
        # Global rules read the scripted mark when the answer is settled.
        diplomacy_messages.set_response(run.world.nation_data, nation, target, verdict, expected_action,
                                        message=act.get("message", ""), parameters=request.get("parameters"),
                                        scripted=True)


def _answer_proposal(run, nation, target, act, verdict):
    # Answering a proposal is its own channel, not a pending action.
    pending_action, pending_turns = queries.get_diplomatic_status(target, nation, run.world.nation_data)
    if pending_turns > 0 and pending_action in c.BILATERAL_ACTIONS:
        _answer_request(run, nation, target, act, pending_action, verdict)


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
        count = min(count, volunteers.remaining_capacity(run.context, nation))
    chosen = volunteers.available_units(run.context, nation)[:count]
    details, error = volunteers.create_offer(run.context, nation, target, chosen)
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
    legal, reason = action_is_legal(run.context, nation, target, action, scripted=True)
    if not legal:
        print(f"[SCRIPTED EVENT] Skipping {action} from {nation} to {target}: {reason}.")
        return
    custom_message = act.get("message", "")
    # Global rules read the scripted mark again when the request is sent.
    lifecycle.put_request(run.world.nation_data, nation, target, **{
        "action": action,
        "turns": 0,
        "timer": 0,
        "message": custom_message,
        "scripted": True,
    })
    if act.get("ai_generate", False):
        # Generated here rather than queued. Scripted events run *after* the LLM
        # pass, so anything appended to its task list is never picked up. There
        # are only ever a handful of these in a turn, so an inline call costs
        # little and makes the option real.
        generated = ai_handler.generate_proactive_text(
            run.world.nation_data, run.active_nations, nation, target,
            ai_prompts.get_proactive_action_context(action, target),
            run.human_players, ai_handler.CURRENT_TURN_ID,
            current_date=run.world.time_manager.get_date_string())
        pending[target]["message"] = generated or custom_message or "We have sent a diplomatic missive."


@dataclass(frozen=True)
class Action:
    run: Callable
    field: str
    help_text: str = ""
    response: tuple | None = None
    edits_identity: bool = False


def _for_each_target(handler):
    def perform(run, nation, _data, pending, act):
        for target in _action_targets(act):
            if target != "None":
                handler(run, nation, pending, target, act)
    return perform


def _request(action, *, field="message", help_text=""):
    def send(run, nation, pending, target, act):
        _send_request(run, nation, pending, target, act, action)
    return Action(_for_each_target(send), field, help_text)


def _response(action, verdict, *, help_text=""):
    def answer(run, nation, _pending, target, act):
        if action is None:
            _answer_proposal(run, nation, target, act, verdict)
        else:
            _answer_request(run, nation, target, act, action, verdict)
    field = "message" if action is None else "target"
    return Action(_for_each_target(answer), field, help_text, (action, verdict))


def _send_custom_message(run, nation, pending, target, act):
    _send_request(run, nation, pending, target, act, f"MSG:{act.get('message', '')}")


def _edit(key, field, *, help_text=""):
    return Action(partial(_edit_field, field=key), field, help_text, edits_identity=True)


ACTIONS = {
    'Declare War': _request("WAR_DECLARATION", help_text='Declare War: Declares war on the target'),
    'Join Faction': _request("JOIN_FACTION_REQ", help_text='Join Faction / Create Faction / Invite to Faction: Modifies faction alignments'),
    'Create Faction': _request("CREATE_FACTION"),
    'Invite to Faction': _request("FACTION_INVITE"),
    'Accept Proposal': _response(None, diplomacy_messages.RESPONSE_ACCEPT, help_text='Accept / Reject Proposal: Responds to a pending diplomatic request'),
    'Reject Proposal': _response(None, diplomacy_messages.RESPONSE_REJECT),
    'Send Ceasefire': _request("CEASEFIRE", help_text='Send Ceasefire: Offers peace to the target'),
    'Send Custom Message': Action(_for_each_target(_send_custom_message), "message", help_text='Send Custom Message: Sends a text message to the target'),
    'Queue Claims': Action(_queue_claims, 'text', help_text='Queue Claims: Begins fabricating claims on the specified Province IDs (comma-separated)'),
    'Revoke Claims': Action(_revoke_claims, 'text', help_text='Revoke Claims: Removes claims on the specified Province IDs (comma-separated)'),
    'Revoke All Claims': Action(_revoke_all_claims, 'target', help_text='Revoke All Claims: Removes ALL claims held by the target nation'),
    'Give Territory': Action(_give_territory, 'territory', help_text="Give Territory: Transfers the specified Province IDs (comma-separated) to the target nation. Check 'Must Control' if they must currently control the tiles to transfer them."),
    'Spawn Unit': Action(_spawn_unit, 'unit', help_text="Spawn Unit: Spawns the specified unit type for the target nation on the specified Province IDs (comma-separated). Check 'Must Control' if they must currently control the tiles to spawn the unit on them."),
    'Set Variable': Action(_set_variable, 'variable', help_text='Set Variable: Modifies a selected global variable by setting, adding, subtracting, multiplying, or dividing it by a static value.'),
    'Guarantee Independence': _request("GUARANTEE", field="target", help_text="Guarantee Independence: Queues a unilateral guarantee of the selected country's independence."),
    'Send Military Attaché': _request("SEND_MILITARY_ATTACHE", help_text='Send Military Attaché / Request Military Access: Sends the normal diplomatic request to the selected country.'),
    'Request Military Access': _request("REQ_MILITARY_ACCESS"),
    'Offer Volunteer Divisions': Action(_for_each_target(_offer_volunteers), "volunteers", help_text="Offer Volunteer Divisions: Sends the selected country the number of available land divisions entered in the message box (default: 1). Enable 'Use Available Capacity' to send fewer if the requested number exceeds the remaining cap. The host must accept the offer."),
    'Accept Military Attaché': _response("SEND_MILITARY_ATTACHE", diplomacy_messages.RESPONSE_ACCEPT, help_text='Accept / Reject Military Attaché, Military Access, or Volunteer Divisions: Responds only to that matching pending request from the selected country.'),
    'Reject Military Attaché': _response("SEND_MILITARY_ATTACHE", diplomacy_messages.RESPONSE_REJECT),
    'Accept Military Access': _response("REQ_MILITARY_ACCESS", diplomacy_messages.RESPONSE_ACCEPT),
    'Reject Military Access': _response("REQ_MILITARY_ACCESS", diplomacy_messages.RESPONSE_REJECT),
    'Accept Volunteer Divisions': _response("SEND_VOLUNTEERS", diplomacy_messages.RESPONSE_ACCEPT),
    'Reject Volunteer Divisions': _response("SEND_VOLUNTEERS", diplomacy_messages.RESPONSE_REJECT),
    'Edit Name': _edit("name", 'text', help_text='Edit Name / Leader / Title: Changes cosmetic names for the event owner'),
    'Edit Leader Name': _edit("leader_name", 'text'),
    'Edit Leader Title': _edit("leader_title", 'text'),
    'Edit Color': Action(_edit_color, 'color', help_text='Edit Color / Flag / Portrait: Modifies cosmetic visual aspects', edits_identity=True),
    'Edit Flag': _edit("flag_data", 'flag'),
    'Edit Portrait': _edit("portrait_data", 'portrait'),
}

CHAIN_OPS = ["AND", "OR", "XOR", "NOR", "NAND"]
NUMERIC_OPS = ["==", "!=", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]
TURN_OPS = ["==", ">", "<", ">=", "<=", "BETWEEN (INC)", "BETWEEN (EXC)"]
VAR_MATH_OPS = list(_VARIABLE_MATH)


# --- Event processing ------------------------------------------------------------------------

def _scripted_event_response(actions, sender_nation, request_action):
    """Return the last scripted answer matching this hypothetical request."""
    response = None
    matched = False
    for action in actions:
        definition = ACTIONS.get(action.get("type"))
        if definition is None or definition.response is None:
            continue
        expected_action, verdict = definition.response
        if expected_action is None:
            if request_action not in c.BILATERAL_ACTIONS:
                continue
            expected_action = request_action
        if expected_action != request_action:
            continue
        if sender_nation in _action_targets(action):
            response = verdict
            matched = True
    return matched, response


def scripted_event_response_preview(context, nation, sender, action):
    """Predict a scripted response without mutating state or consuming RNG."""
    if (action == "TRADE" and nation not in session_for(context).active_players
            and queries.are_at_war(nation, sender, world_for(context).nation_data)):
        return "NO"
    response = process_scripted_events(context, preview_request=(nation, sender, action))
    # An accepting event cannot break a global rule that binds scripted events.
    choice = global_rules.Choice(global_rules.is_ai_controlled(context, nation), accepting=True, scripted=True)
    if response in ("YES", "MAYBE") and global_rules.forbidden_reason(context, sender, nation, action,
                                                                      choices=(choice,)):
        return "NO"
    return response


def _event_can_fire(event, index, fired_events, nation, human_players):
    if index in fired_events and event.get("fire_once", True):
        return False
    trigger = event.get("trigger_type", "AI Only")
    if trigger == "AI Only" and nation in human_players:
        return False
    if trigger == "Player Only" and nation not in human_players:
        return False
    return bool(event.get("conditions", []))


def process_scripted_events(context, preview_request=None):
    """Processes scenario-specific scripted events for AI nations."""
    world_state = world_for(context)
    session_state = session_for(context)
    if not queries.get_scenario_flag("use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS, world_state.scenario_settings):
        return None

    run = EventRun(context, world_state, set(queries.get_living_nations(world_state.map_data)),
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
                    definition = ACTIONS.get(act.get("type"))
                    if definition is not None:
                        definition.run(run, nation, data, pending, act)
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
