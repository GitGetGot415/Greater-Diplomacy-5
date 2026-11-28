"""Puppet-hierarchy mutations: assigning, releasing, annexing, and cascading
diplomatic state (wars, peace, factions) down a master's puppet tree.

Works alongside war_actions.py and faction_actions.py. These modules import
each other where the concerns interact.
"""

# Faction actions call subject actions. Keep imports of faction mutations local to avoid that reciprocal dependency.

import copy
from dataclasses import dataclass
import uuid

from data.state_access import world_for, session_for
from map_logic.territory import ownership
from data import queries
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.diplomacy.war_actions import sever_military_access, link_war, remove_enemy, finalize_neutral
import data.constants as c

from data.io import country_io
from map_logic.territory.ownership import retire_landless_nation
from map_logic.diplomacy import volunteers, faction_leadership, faction_records


# --- RECURSIVE PUPPET HELPERS ---
def break_puppet_link(nation_data, master, puppet):
    if puppet in nation_data.get(master, {}).get("puppets", []):
        nation_data[master]["puppets"].remove(puppet)
    if puppet in nation_data:
        nation_data[puppet]["master"] = ""
        nation_data[puppet]["puppet_type"] = ""
        if "is_created_integrated_puppet" in nation_data[puppet]:
            del nation_data[puppet]["is_created_integrated_puppet"]

def apply_to_puppets_recursively(master, nation_data, action_func):
    """Apply a diplomatic state down a puppet tree, visiting each country once.

    The editor and old saves can contain malformed cycles. An iterative walk
    prevents both repeated visits and recursion-depth crashes on long trees.
    """
    visited = {master}
    pending = list(reversed(nation_data.get(master, {}).get("puppets", [])))
    while pending:
        puppet = pending.pop()
        if puppet in visited:
            continue
        visited.add(puppet)
        action_func(puppet)
        children = nation_data.get(puppet, {}).get("puppets", [])
        pending.extend(reversed(children))


def would_create_puppet_cycle(master, puppet, nation_data):
    """Return whether assigning ``puppet`` beneath ``master`` creates a cycle."""
    if master == puppet:
        return True

    # Check the child links used by hierarchy propagation. The visited set
    # also makes this safe when the existing hierarchy is already malformed.
    visited = set()
    pending = [puppet]
    while pending:
        country = pending.pop()
        if country == master:
            return True
        if country in visited:
            continue
        visited.add(country)
        pending.extend(nation_data.get(country, {}).get("puppets", []))
    return False

def pull_master_into_war(puppet, target, map_data, nation_data):
    master = nation_data.get(puppet, {}).get("master", "")
    if master and master != target:
        if queries.are_in_same_faction(master, target, nation_data):
            return

        link_war(nation_data, master, target)

        # Recursively pull the master's OTHER puppets into the war too!
        pull_puppets_into_war(master, target, map_data, nation_data)

        log_global_event(nation_data, f"{master} has joined the war on the side of {puppet}!")

def assign_puppet(map_data, nation_data, master, puppet, puppet_type=c.PUPPET_TYPE_AUTONOMOUS):
    if would_create_puppet_cycle(master, puppet, nation_data):
        return False

    p_data = nation_data.get(puppet, {})
    m_data = nation_data.get(master, {})

    # Remove from old master if exists so they don't have dual loyalties
    old_master = p_data.get("master", "")
    if old_master and old_master in nation_data:
        if puppet in nation_data[old_master].get("puppets", []):
            nation_data[old_master]["puppets"].remove(puppet)

    p_data["master"] = master
    p_data["puppet_type"] = puppet_type

    if puppet_type == c.PUPPET_TYPE_INTEGRATED:
        if "spawned_territories" not in p_data:
            p_data["spawned_territories"] = []
            for prov in map_data.values():
                if prov.get("owner") == puppet:
                    p_data["spawned_territories"].append(prov["id"])

    if puppet not in m_data.get("puppets", []):
        m_data.setdefault("puppets", []).append(puppet)

    # Transfer leadership if puppet was a leader
    if queries.is_faction_leader(puppet, nation_data):
        fac = queries.get_country_faction(puppet, nation_data)
        queries.set_faction_leadership(nation_data, puppet, False)
        if fac:
            queries.set_country_faction(nation_data, master, fac)
            queries.set_faction_leadership(nation_data, master, True)

    # Auto-pull puppet into master's faction
    master_fac = queries.get_country_faction(master, nation_data)
    if master_fac:
        pull_puppets_into_faction(master, master_fac, map_data, nation_data)

    # Auto-pull puppet into master's wars
    for enemy in m_data.get("at_war_with", []):
        pull_puppets_into_war(master, enemy, map_data, nation_data)

    # Force peace between them if they were at war
    if queries.are_at_war(master, puppet, nation_data) or queries.are_at_war(puppet, master, nation_data):
        finalize_neutral(nation_data, master, puppet)

    # Puppet and master already have free passage, so any grant or request is moot.
    sever_military_access(nation_data, master, puppet)
    return True

def pull_puppets_into_war(master, target, map_data, nation_data):
    def _add_war(p):
        if queries.are_in_same_faction(p, target, nation_data):
            return
        link_war(nation_data, p, target)
    apply_to_puppets_recursively(master, nation_data, _add_war)

def pull_puppets_into_peace(master, target, nation_data):
    """A master's peace settles its puppets' half of the same war.

    The truce is written both ways, like the war it replaces. Writing it only on
    the puppet's side left the other party with no record of a peace it had just
    agreed to, so anything that reads a truce to decide whether a war may start
    -- a call to arms, an AI declaration -- saw nothing standing in its way.
    """
    def _remove_war(p):
        remove_enemy(nation_data, p, target)
        remove_enemy(nation_data, target, p)
        for country, other in ((p, target), (target, p)):
            truces = nation_data.setdefault(country, {}).setdefault("truces", {})
            if queries.world_truce_turns(nation_data) > 0:
                truces[other] = queries.world_truce_turns(nation_data)
            else:
                truces.pop(other, None)
    apply_to_puppets_recursively(master, nation_data, _remove_war)

def pull_puppets_into_faction(master, fac, map_data, nation_data):
    from map_logic.diplomacy.faction_actions import settle_with_faction

    def _set_fac(p):
        queries.set_country_faction(nation_data, p, fac)
        queries.set_faction_leadership(nation_data, p, False)
        settle_with_faction(nation_data, p, fac)

    apply_to_puppets_recursively(master, nation_data, _set_fac)

def pull_puppets_out_of_faction(master, nation_data):
    def _clear_fac(p):
        queries.set_country_faction(nation_data, p, "")
        queries.set_faction_leadership(nation_data, p, False)
    apply_to_puppets_recursively(master, nation_data, _clear_fac)

def finalize_annexation(map_data, nation_data, master, puppet, context, *, force=False):
    if force and (not queries.can_use_spectator_country_actions(context)
                  or master == puppet or not queries.is_playable(master, nation_data)
                  or not queries.is_playable(puppet, nation_data)):
        return False
    puppets_to_transfer = nation_data.get(puppet, {}).get("puppets", []).copy()
    for child in puppets_to_transfer:
        p_type = nation_data.get(child, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
        assign_puppet(map_data, nation_data, master, child, p_type)

    # Transfer all territory and units
    for prov in map_data.values():
        if prov.get("owner") == puppet:
            ownership.conquer_province(
                context, prov, master, refresh_visuals=not force,
                check_landless=not force, apply_capture_rules=not force)
        for unit in prov.get("units", []):
            if unit.get("owner") == puppet:
                queries.set_unit_owner(unit, master, context=context)

    # Every province above went through conquer_province, which retires the
    # loser once its last one changes hands -- but a puppet that already held
    # nothing never enters that loop, and used to stay on its faction's roster
    # for the rest of the game.
    retire_landless_nation(context, puppet, force=force)

    break_puppet_link(nation_data, master, puppet)

    log_global_event(nation_data, f"{master} has fully annexed {puppet}.")


def _references_country(value, country):
    """Check structured orders and diplomacy for a country ID."""
    if isinstance(value, dict):
        return country in value or any(_references_country(item, country) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_references_country(item, country) for item in value)
    return value == country


def _clear_country_relationships(nation_data, country):
    """Remove live relations and pending actions. Preserve historical world events."""
    list_fields = ("at_war_with", "puppets", "guarantees", "military_attaches",
                   "military_access", "pending_military_attache_revocations", "pending_volunteer_send_homes")
    table_fields = ("relations", "wargoals", "temp_modifiers", "pending_diplomacy", "diplo_responses",
                    "diplo_cooldowns", "truces", "draft_lists", "war_durations", "volunteer_missions")
    queue_fields = ("return_queue", "release_puppet_queue", "inbox", "outbox")
    for country_id, record in nation_data.items():
        if country_id in ("GLOBAL_EVENTS", "FACTION_WAR_MAPS", "WAR_PRE_MAPS"):
            continue
        if record.get("master") == country:
            record["master"] = ""
            record["puppet_type"] = ""
            record.pop("is_created_integrated_puppet", None)
        for field in list_fields + queue_fields:
            if field in record:
                record[field] = [item for item in record[field] if not _references_country(item, country)]
        for field in table_fields:
            if field in record:
                table = record[field]
                for key, value in list(table.items()):
                    if key == country or _references_country(value, country):
                        del table[key]
    faction_records.set_pre_war_map(nation_data, country, None)
    individual_maps = nation_data.get("WAR_PRE_MAPS", {})
    individual_maps.pop(country, None)
    for maps in (faction_records.pre_war_maps(nation_data), individual_maps):
        for borders in maps.values():
            # Older shared records can also contain ordinary country defaults.
            if not isinstance(borders, dict):
                continue
            for province_id, owner in list(borders.items()):
                if owner == country:
                    del borders[province_id]


def finalize_spectator_country_removal(context, country, annexer=None):
    """Annex a country immediately, or delete its live state and preserve history."""
    world_state = world_for(context)
    nation_data, map_data = world_state.nation_data, world_state.map_data
    if (not queries.can_use_spectator_country_actions(context)
            or not queries.is_playable(country, nation_data)):
        return False
    if annexer is not None and (annexer == country or not queries.is_playable(annexer, nation_data)
                               or annexer not in queries.get_living_nations(map_data)):
        return False
    from map_logic.diplomacy import faction_actions
    country_name = queries.get_country_display_name(country, nation_data)
    volunteers.end_country_missions(context, country, annexer)
    for province in map_data.values():
        for unit in queries.units_with_air_cargo(province.get("units", [])):
            if unit.get("owner") == country:
                unit.pop("volunteer_host", None)
                unit.pop("volunteer_origin_id", None)
    if annexer is not None:
        # A subject can annex its own ancestor without creating a puppet cycle.
        if would_create_puppet_cycle(annexer, country, nation_data):
            break_puppet_link(nation_data, nation_data[annexer].get("master", ""), annexer)
        if nation_data[annexer].get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
            spawned = nation_data[annexer].setdefault("spawned_territories", [])
            spawned.extend(p["id"] for p in map_data.values()
                           if p.get("owner") == country and p["id"] not in spawned)
        finalize_annexation(map_data, nation_data, annexer, country, context, force=True)
    else:
        for province in map_data.values():
            if province.get("owner") == country:
                ownership.conquer_province(
                    context, province, "Unclaimed", refresh_visuals=False,
                    check_landless=False, apply_capture_rules=False)
                province["unit_queue"] = []
                province["building_queue"] = []
                province["orders"] = []
            province["cores"] = [core for core in province.get("cores", []) if core != country]
        faction = faction_actions.leave_faction(nation_data, country)
        del nation_data[country]
        # The loader must not restore a deleted catalog country from its template.
        log_global_event(nation_data, f"{country_name} was deleted by the spectator.")
        deleted = nation_data["GLOBAL_EVENTS"].setdefault("deleted_countries", [])
        if country not in deleted:
            deleted.append(country)
        faction_leadership.promote(context, faction)
        if hasattr(context, "nation_colors"):
            context.nation_colors.pop(country, None)
    for province in map_data.values():
        survivors = []
        for unit in province.get("units", []):
            if unit.get("owner") == country:
                if annexer is None:
                    continue
                queries.set_unit_owner(unit, annexer, context=context)
            if "air_cargo" in unit:
                unit["air_cargo"] = [cargo for cargo in unit["air_cargo"]
                                      if annexer is not None or cargo.get("owner") != country]
            for member in queries.units_with_air_cargo([unit]):
                if member.get("owner") == country and annexer is not None:
                    queries.set_unit_owner(member, annexer, context=context)
                if member.get("volunteer_host") == country:
                    member.pop("volunteer_host", None)
                    member.pop("volunteer_origin_id", None)
            survivors.append(unit)
        province["units"] = survivors
        for field in ("unit_queue", "building_queue", "orders"):
            if field in province:
                province[field] = [entry for entry in province[field]
                                    if not _references_country(entry, country)]
    _clear_country_relationships(nation_data, country)
    if country in nation_data:
        data = nation_data[country]
        queries.set_country_faction(nation_data, country, "")
        data.update(master="", puppet_type="", puppets=[], faction="", is_faction_leader=False,
                    at_war_with=[], pending_diplomacy={}, diplo_responses={},
                    volunteer_missions={}, scripted_events=[], armies=[], claim_queue=[],
                    revoke_queue=[], return_queue=[], release_puppet_queue=[])
    queries.normalize_armies(nation_data, map_data)
    context.centers_need_update = True
    return True

def finalize_release(map_data, nation_data, master, puppet, context):
    break_puppet_link(nation_data, master, puppet)

    log_global_event(nation_data, f"{master} has released {puppet} as an independent nation.")

def finalize_take_puppets(map_data, nation_data, master, target_puppet):
    puppets_to_take = nation_data.get(target_puppet, {}).get("puppets", []).copy()
    for p in puppets_to_take:
        p_type = nation_data.get(p, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
        assign_puppet(map_data, nation_data, master, p, p_type)


RELEASE_RESTORE = "restore"
RELEASE_ADD_LAND = "add_land"
RELEASE_RETURN_LAND = "return_land"
RELEASE_CREATE = "create"
RELEASE_ACTIONS = (RELEASE_RESTORE, RELEASE_ADD_LAND, RELEASE_RETURN_LAND, RELEASE_CREATE)


@dataclass
class PuppetReleasePlan:
    action: str | None
    country: str | None
    provinces: list[dict]
    reason: str = ""
    matching_subjects: tuple[str, ...] = ()
    blocked_action: str | None = None

    def destination(self):
        return {"action": self.action, "country": self.country}

    def separate_destination(self):
        if self.provinces and self.action != RELEASE_RESTORE:
            return {"action": RELEASE_CREATE, "country": None}
        return None


def plan_puppet_release(map_data, nation_data, master, core_nation, release_type, keep_cores=False,
                        *, reserved=(), destination=None):
    """Resolve a release's recipient and eligible provinces. Never change world state."""
    if (release_type not in c.PUPPET_RELEASE_TYPES or master not in nation_data
            or master == core_nation or core_nation in c.UNPLAYABLE_NATIONS or master in c.UNPLAYABLE_NATIONS):
        return PuppetReleasePlan(None, None, [], "Invalid nation release.")
    provinces = [province for province in queries.get_puppet_release_provinces(
        master, core_nation, map_data, keep_cores, nation_data=nation_data) if province["id"] not in reserved]

    source = nation_data.get(core_nation, {})
    active = bool(queries.get_country_faction(core_nation, nation_data)) or any(
        province.get("owner") == core_nation for province in map_data.values())
    subjects = [subject for subject in nation_data[master].get("puppets", [])
                if nation_data.get(subject, {}).get("master") == master and queries.is_playable(subject, nation_data)
                and (subject == core_nation or nation_data[subject].get("release_source") == core_nation)]
    matching = tuple(subject for subject in subjects if nation_data[subject].get("puppet_type") == release_type)
    plan = PuppetReleasePlan(None, None, provinces, matching_subjects=matching)
    if matching:
        plan.action, plan.country = RELEASE_ADD_LAND, matching[0]
    elif subjects and (release_type != c.PUPPET_RELEASE_INDEPENDENT or core_nation in subjects):
        subject = subjects[0]
        name = queries.get_country_display_name(subject, nation_data)
        plan.blocked_action = RELEASE_ADD_LAND
        plan.reason = f"{name} is {nation_data[subject]['puppet_type']}."
    elif active and release_type == c.PUPPET_RELEASE_INDEPENDENT and source.get("is_playable"):
        plan.action, plan.country = RELEASE_RETURN_LAND, core_nation
    elif active:
        name = queries.get_country_display_name(core_nation, nation_data)
        plan.blocked_action = RELEASE_RETURN_LAND
        plan.reason = f"{name} still exists."
    elif release_type != c.PUPPET_RELEASE_INDEPENDENT and would_create_puppet_cycle(master, core_nation, nation_data):
        plan.blocked_action = RELEASE_RESTORE
        plan.reason = "Restoring this country as a subject would create a subject cycle."
    else:
        plan.action, plan.country = RELEASE_RESTORE, core_nation

    if not provinces:
        return PuppetReleasePlan(None, plan.country, [], "No eligible provinces.",
                                 blocked_action=plan.action or plan.blocked_action)
    if destination is None:
        return plan
    if destination == plan.separate_destination():
        return PuppetReleasePlan(RELEASE_CREATE, None, provinces)
    if isinstance(destination, dict) and destination.get("action") == RELEASE_ADD_LAND and destination.get("country") in matching:
        plan.country = destination["country"]
    if not plan.action or destination != plan.destination():
        return PuppetReleasePlan(None, None, [], "The planned destination has changed.")
    return plan


def queued_puppet_release_plans(map_data, nation_data, master, queue):
    """Preview all entries in the order that they first become due."""
    plans, reserved = {}, set()
    for entry in sorted(queue, key=lambda item: max(1, item.get("turns_left", 1))):
        core_nation = entry["core_nation"]
        plan = plan_puppet_release(map_data, nation_data, master, core_nation, entry["release_type"],
                                   entry.get("keep_cores", False), reserved=reserved, destination=entry.get("destination"))
        plans[core_nation] = plan
        if plan.action:
            reserved.update(province["id"] for province in plan.provinces)
    return plans, reserved


def canonical_puppet_release_queue(map_data, nation_data, master, entries, old_queue=()):
    """Validate player choices, keep existing countdowns and bind new orders to their destinations."""
    if master not in nation_data or master in c.UNPLAYABLE_NATIONS or not isinstance(entries, list):
        raise ValueError("Invalid source country or nation release queue.")
    previous = {entry["core_nation"]: entry for entry in old_queue}
    result, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid nation release entry.")
        subject = entry.get("core_nation")
        keep_cores = entry.get("keep_cores", False)
        release_type = entry.get("release_type", c.PUPPET_TYPE_INTEGRATED)
        destination = entry.get("destination")
        if (not isinstance(subject, str) or subject == master or subject in c.UNPLAYABLE_NATIONS
                or subject in seen or not isinstance(keep_cores, bool)
                or release_type not in c.PUPPET_RELEASE_TYPES
                or ("destination" in entry and (not isinstance(destination, dict)
                    or set(destination) != {"action", "country"} or destination["action"] not in RELEASE_ACTIONS
                    or (destination["country"] is not None and not isinstance(destination["country"], str))))):
            raise ValueError("Invalid nation release choice.")
        old = previous.get(subject)
        order = {"core_nation": subject, "keep_cores": keep_cores, "release_type": release_type,
                 "turns_left": old.get("turns_left", 1) if old else 1}
        if old:
            if (old.get("keep_cores", False) != keep_cores or old["release_type"] != release_type
                    or (destination is not None and destination != old.get("destination"))):
                raise ValueError("Cancel the existing nation release before changing its options.")
            if "destination" in old:
                order["destination"] = copy.deepcopy(old["destination"])
        elif destination is not None:
            order["destination"] = destination.copy()
        result.append(order)
        seen.add(subject)

    plans, _ = queued_puppet_release_plans(map_data, nation_data, master, result)
    for order in result:
        subject = order["core_nation"]
        if subject not in previous:
            plan = plans[subject]
            if not plan.action:
                raise ValueError(plan.reason)
            order["destination"] = plan.destination()
    return result


def _prepare_released_country(nation_data, master, core_nation, release_type, *, separate):
    source = nation_data.get(core_nation)
    template = country_io.get_country_stats(core_nation)
    appearance = source if source is not None else template
    master_data = nation_data[master]
    integrated = release_type == c.PUPPET_TYPE_INTEGRATED
    name = appearance.get("name", core_nation)

    if separate:
        if integrated:
            adjective = master_data.get("adjective")
            master_name = queries.get_country_display_name(master, nation_data)
            name = f"{adjective} {name}" if adjective else f"{master_name}'s Protectorate of {name}"
        base_name, suffix = name, 1
        names = {data.get("name", country) for country, data in nation_data.items()}
        while name in names:
            suffix += 1
            name = f"{base_name} {suffix}"
        country = "country-" + uuid.uuid4().hex
    else:
        country = core_nation

    if not separate and source is not None:
        break_puppet_link(nation_data, source.get("master", ""), country)
        data = source
    else:
        data = {key: copy.deepcopy(appearance[key]) for key in c.COUNTRY_APPEARANCE_FIELDS if key in appearance}
        data.update({key: template.get(key, 0) for key in c.ECON_RESOURCE_KEYS})
        data.update(puppets=[], faction="", is_faction_leader=False, inbox=[])
        if separate:
            data["release_source"] = core_nation
            if integrated:
                data["is_created_integrated_puppet"] = True

    # A split country needs its own copy of images resolved by the source ID.
    if separate and data.get("flag_data") in (None, "", "DEFAULT"):
        flag = queries.decode_b64_to_surf("DEFAULT", c.FLAG_SIZE, country_name=core_nation)
        data["flag_data"] = queries.encode_surf_to_b64(flag)
    if separate and data.get("portrait_data") in (None, "", "DEFAULT"):
        portrait = queries.decode_b64_to_surf("DEFAULT", c.PORTRAIT_SIZE, is_portrait=True, country_name=core_nation)
        data["portrait_data"] = queries.encode_surf_to_b64(portrait)
    data.setdefault("flag_data", "DEFAULT")
    color = (master_data.get("color", country_io.DEFAULT_NATION_COLOR) if integrated
             else appearance.get("color", country_io.DEFAULT_NATION_COLOR))
    data.update(name=name, color=list(color), research=copy.deepcopy(master_data.get("research", {})),
                is_playable=True, at_war_with=[], pending_diplomacy={}, diplo_responses={}, draft_lists={},
                claim_queue=[], revoke_queue=[], return_queue=[], release_puppet_queue=[],
                master="", puppet_type="", spawned_territories=[])
    nation_data[country] = data
    return country


def apply_puppet_release(map_data, nation_data, master, core_nation, context, release_type, plan):
    """Apply a plan calculated against the current turn's world state."""
    country = plan.country
    if plan.action in (RELEASE_RESTORE, RELEASE_CREATE):
        country = _prepare_released_country(nation_data, master, core_nation, release_type,
                                            separate=plan.action == RELEASE_CREATE)
        if release_type != c.PUPPET_RELEASE_INDEPENDENT:
            assign_puppet(map_data, nation_data, master, country, release_type)
        if hasattr(context, "nation_colors"):
            context.nation_colors[country] = tuple(nation_data[country]["color"])

    recipient = nation_data[country]
    if plan.action == RELEASE_CREATE:
        for province in map_data.values():
            cores = province.get("cores", [])
            if core_nation in cores and country not in cores:
                cores.append(country)
    if recipient.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
        spawned = recipient.setdefault("spawned_territories", [])
        spawned.extend(province["id"] for province in plan.provinces if province["id"] not in spawned)
    for province in plan.provinces:
        if country not in province.get("cores", []) and plan.action == RELEASE_ADD_LAND:
            province.setdefault("cores", []).append(country)
        ownership.conquer_province(context, province, country)

    master_name = queries.get_country_display_name(master, nation_data)
    name = queries.get_country_display_name(country, nation_data)
    event = {
        RELEASE_RESTORE: f"{master_name} has restored {name}.",
        RELEASE_ADD_LAND: f"{master_name} has transferred territory to its subject {name}.",
        RELEASE_RETURN_LAND: f"{master_name} has returned territory to {name}.",
        RELEASE_CREATE: f"{master_name} has formed {name}.",
    }
    log_global_event(nation_data, event[plan.action])
    return country


def finalize_create_puppet(map_data, nation_data, master, core_nation, context,
                         keep_cores=False, release_type=c.PUPPET_TYPE_INTEGRATED, *, destination=None):
    """Resolve a release immediately for callers outside the turn queue."""
    plan = plan_puppet_release(map_data, nation_data, master, core_nation, release_type, keep_cores,
                               destination=destination)
    if plan.action:
        return apply_puppet_release(map_data, nation_data, master, core_nation, context, release_type, plan)
    return None
