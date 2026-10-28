"""Own request identity, channel writes, and permitted timing transitions.

The existing turns field remains the canonical request age. State is derived
from that age and the action. Responses have no travelling request age.
"""

import copy
from enum import Enum
import json
import uuid

import data.constants as c


class RequestState(Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    AWAITING_REPLY = "awaiting_reply"
    AWAITING_REACTION = "awaiting_reaction"
    EXPIRED = "expired"


def request_state(record):
    age = record.get("turns", 0)
    if age == 0:
        return RequestState.SCHEDULED if record.get("timer", 0) > 0 else RequestState.DRAFT
    if record.get("action") in c.BILATERAL_ACTIONS:
        return RequestState.AWAITING_REPLY if age == 1 else RequestState.EXPIRED
    return RequestState.AWAITING_REACTION


def put_request(nation_data, sender, target, action, **extra):
    """Replace one outgoing channel with a fresh identity, independent of replies."""
    channel = nation_data.setdefault(sender, {}).setdefault("pending_diplomacy", {})
    return put_request_in_channel(channel, target, action, **extra)


def put_request_in_channel(channel, target, action, **extra):
    """Support callers which already hold the canonical outgoing channel."""
    record = {"action": action, "turns": 0, "timer": 0, "request_id": uuid.uuid4().hex}
    record.update(extra)
    channel[target] = record
    return record


def remove_request(pending, target, *, request_id=None):
    record = pending.get(target)
    if target not in pending:
        return False
    if request_id is not None and (not isinstance(record, dict) or record.get("request_id") != request_id):
        return False
    del pending[target]
    return True


def advance_request(record):
    """Advance at the existing pass boundary without changing processing order."""
    if record.get("timer", 0) > 0:
        raise ValueError("A scheduled request must finish its timer before delivery.")
    record["turns"] = record.get("turns", 0) + 1
    return request_state(record)


def tick_schedule(record):
    """Return true on the existing scheduled execution turn."""
    if record.get("timer", 0) <= 0:
        return True
    record["timer"] -= 1
    return record["timer"] <= 0


def put_response(nation_data, recipient, sender, verdict, action, **extra):
    """Bind an answer to the current request without creating a travelling reply."""
    request = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(recipient, {})
    record = {"verdict": verdict, "action": action, "message": "",
              "request_id": request.get("request_id") if isinstance(request, dict) else None}
    record.update(extra)
    nation_data.setdefault(recipient, {}).setdefault("diplo_responses", {})[sender] = record
    return record


def remove_response(responses, sender):
    if sender not in responses:
        return False
    del responses[sender]
    return True


def response_matches_request(response, request):
    """A cancelled request's response cannot resolve its replacement."""
    reference = response.get("request_id")
    if reference is None:
        # Only the older-data adapter supplies this marker. Network input strips it.
        return response.get("legacy_unmatched", False)
    return (isinstance(request, dict) and reference == request.get("request_id")
            and response.get("action") == request.get("action"))


def canonical_response_reference(nation_data, recipient, sender, response):
    """Adapt supported older input and check references against host-owned requests."""
    return normalize_response_reference(nation_data, recipient, sender, response)


def apply_draft(nation_data, sender, pending, responses, draft_lists):
    """Install validated intent while retaining server-owned travelling requests."""
    normalize_diplomatic_records(nation_data)
    country = nation_data[sender]
    current = country.setdefault("pending_diplomacy", {})
    in_flight = {target: record for target, record in current.items()
                 if isinstance(record, dict) and record.get("turns", 0) > 0}
    for target, intent in pending.items():
        if target in in_flight:
            # Executed unilateral actions can be replaced, as in local play.
            if (in_flight[target].get("action") not in c.UNILATERAL_ACTIONS
                    or intent.get("turns", 0) > 0):
                continue
        old = current.get(target)
        record = copy.deepcopy(intent)
        # Keep the host identity of an unchanged unsent draft. Client identities
        # are references and cannot establish a new authoritative identity.
        comparable = lambda entry: {key: value for key, value in entry.items() if key != "request_id"}
        identity = (old.get("request_id") if isinstance(old, dict)
                    and comparable(old) == comparable(record) else None)
        record.pop("request_id", None)
        action = record.pop("action")
        if identity:
            record["request_id"] = identity
        in_flight[target] = put_request(nation_data, sender, target, action, **record)
    current.clear()
    current.update(in_flight)
    answer_map = country.setdefault("diplo_responses", {})
    answer_map.clear()
    for target, response in responses.items():
        record = copy.deepcopy(response)
        verdict, action = record.pop("verdict"), record.pop("action")
        put_response(nation_data, sender, target, verdict, action, **record)
    country["draft_lists"] = copy.deepcopy(draft_lists)


def answer_ratification(nation_data, member, verdict, *, treaty_id=None):
    request = nation_data.get(member, {}).get("pending_ratification")
    if not isinstance(request, dict):
        return False
    if treaty_id is not None and treaty_id != request.get("treaty_id"):
        raise ValueError("That ratification refers to an expired treaty.")
    if verdict is None:
        request.pop("verdict", None)
    else:
        request["verdict"] = verdict
    return True


def normalize_response_reference(nation_data, recipient, sender, response):
    """Bind omitted older references and validate supplied references against host state."""
    request = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(recipient)
    if request is not None:
        request = normalize_diplomatic_request(copy.deepcopy(request), sender, recipient)
    reference = response.get("request_id")
    if reference is not None:
        if (not isinstance(reference, str) or not isinstance(request, dict)
                or reference != request.get("request_id") or response.get("action") != request.get("action")):
            raise ValueError("That response refers to an expired diplomatic request.")
        return {"request_id": reference}
    existing = nation_data.get(recipient, {}).get("diplo_responses", {}).get(sender)
    if isinstance(existing, dict) and existing.get("legacy_unmatched") and response == existing:
        return {"legacy_unmatched": True}
    if isinstance(request, dict) and response.get("action") == request.get("action"):
        return {"request_id": request["request_id"]}
    # Older files can contain standalone responses with copied treaty terms.
    return {"legacy_unmatched": True}


def normalize_diplomatic_request(entry, sender, target):
    """Give older requests reproducible identities without gameplay randomness."""
    if isinstance(entry, str):
        entry = {"action": entry, "turns": 1, "timer": 0}
    if not isinstance(entry, dict):
        raise ValueError("A diplomatic request must be an action or a record.")
    identity = entry.get("request_id")
    if identity is None:
        payload = json.dumps([sender, target, entry], sort_keys=True, separators=(",", ":"))
        entry["request_id"] = uuid.uuid5(uuid.NAMESPACE_URL, "gd5:diplomacy:" + payload).hex
    elif not isinstance(identity, str) or not identity or len(identity) > 128:
        raise ValueError("A diplomatic request_id must be a nonempty string of at most 128 characters.")
    return entry


def normalize_diplomatic_records(nation_data):
    """Normalize both channels after loading requests, preserving unknown fields."""
    for sender, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        pending = country.get("pending_diplomacy", {})
        for target, entry in list(pending.items()):
            pending[target] = normalize_diplomatic_request(entry, sender, target)
    for recipient, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        for sender, response in country.get("diplo_responses", {}).items():
            if not isinstance(response, dict) or "request_id" in response:
                continue
            request = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(recipient, {})
            if isinstance(request, dict) and request.get("action") == response.get("action"):
                response["request_id"] = request["request_id"]
            else:
                # Older saves could contain standalone responses with copied terms.
                response["legacy_unmatched"] = True
    for signatory, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        treaty = country.get("pending_treaty")
        if not isinstance(treaty, dict):
            continue
        if not treaty.get("treaty_id"):
            payload = json.dumps([signatory, treaty], sort_keys=True, separators=(",", ":"))
            treaty["treaty_id"] = uuid.uuid5(uuid.NAMESPACE_URL, "gd5:ratification:" + payload).hex
        for member in treaty.get("awaiting", []):
            request = nation_data.get(member, {}).get("pending_ratification")
            if isinstance(request, dict):
                request.setdefault("treaty_id", treaty["treaty_id"])
    return nation_data


def normalize_diplomacy_channels(nation_data):
    """Give every country its diplomatic channels and identify their records."""
    for country in nation_data.values():
        country.setdefault("at_war_with", [])
        country.setdefault("guarantees", [])
        country.setdefault("military_attaches", [])
        country.setdefault("pending_diplomacy", {})
        country.setdefault("diplo_responses", {})
    return normalize_diplomatic_records(nation_data)
