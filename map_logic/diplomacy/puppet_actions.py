"""Puppet-hierarchy mutations: assigning, releasing, annexing, and cascading
diplomatic state (wars, peace, factions) down a master's puppet tree.

See map_logic/diplomacy/diplomacy_agreements.py for how this fits alongside
war_actions.py and faction_actions.py.
"""
import copy
from map_logic.turn_processing import edit_province_ownership
from data import queries
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.diplomacy.war_actions import sever_military_access, link_war, remove_enemy, finalize_neutral
import data.constants as c

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
    if p_data.get("is_faction_leader", False):
        fac = p_data.get("faction", "")
        p_data["is_faction_leader"] = False
        if fac:
            m_data["faction"] = fac
            m_data["is_faction_leader"] = True

    # Auto-pull puppet into master's faction
    master_fac = m_data.get("faction", "")
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
            if c.TRUCE_TURNS > 0:
                truces[other] = c.TRUCE_TURNS
            else:
                truces.pop(other, None)
    apply_to_puppets_recursively(master, nation_data, _remove_war)

def pull_puppets_into_faction(master, fac, map_data, nation_data):
    from map_logic.diplomacy.faction_actions import settle_with_faction

    def _set_fac(p):
        nation_data[p]["faction"] = fac
        nation_data[p]["is_faction_leader"] = False
        settle_with_faction(nation_data, p, fac)

    apply_to_puppets_recursively(master, nation_data, _set_fac)

def pull_puppets_out_of_faction(master, nation_data):
    def _clear_fac(p):
        nation_data[p]["faction"] = ""
        nation_data[p]["is_faction_leader"] = False
    apply_to_puppets_recursively(master, nation_data, _clear_fac)

def finalize_annexation(map_data, nation_data, master, puppet, map_screen, *, force=False):
    if force and (not queries.can_use_spectator_country_actions(map_screen)
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
            edit_province_ownership.conquer_province(
                map_screen, prov, master, refresh_visuals=not force,
                check_landless=not force, apply_capture_rules=not force)
        for unit in prov.get("units", []):
            if unit.get("owner") == puppet:
                queries.set_unit_owner(unit, master)

    # Every province above went through conquer_province, which retires the
    # loser once its last one changes hands -- but a puppet that already held
    # nothing never enters that loop, and used to stay on its faction's roster
    # for the rest of the game.
    from map_logic.turn_processing.edit_province_ownership import retire_landless_nation
    retire_landless_nation(map_screen, puppet, force=force)

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
    list_fields = ("at_war_with", "allied_with", "puppets", "guarantees", "military_attaches",
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
    for field in ("FACTION_WAR_MAPS", "WAR_PRE_MAPS"):
        maps = nation_data.get(field, {})
        maps.pop(country, None)
        for borders in maps.values():
            # Older shared records can also contain ordinary country defaults.
            if not isinstance(borders, dict):
                continue
            for province_id, owner in list(borders.items()):
                if owner == country:
                    del borders[province_id]


def finalize_spectator_country_removal(map_screen, country, annexer=None):
    """Annex a country immediately, or delete its live state and preserve history."""
    nation_data, map_data = map_screen.nation_data, map_screen.map_data
    if (not queries.can_use_spectator_country_actions(map_screen)
            or not queries.is_playable(country, nation_data)):
        return False
    if annexer is not None and (annexer == country or not queries.is_playable(annexer, nation_data)
                               or annexer not in queries.get_living_nations(map_data)):
        return False
    from map_logic.diplomacy import volunteers, faction_actions, faction_leadership
    country_name = queries.get_country_display_name(country, nation_data)
    volunteers.end_country_missions(map_screen, country, annexer)
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
        finalize_annexation(map_data, nation_data, annexer, country, map_screen, force=True)
    else:
        for province in map_data.values():
            if province.get("owner") == country:
                edit_province_ownership.conquer_province(
                    map_screen, province, "Unclaimed", refresh_visuals=False,
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
        faction_leadership.promote(map_screen, faction)
        if hasattr(map_screen, "nation_colors"):
            map_screen.nation_colors.pop(country, None)
    for province in map_data.values():
        survivors = []
        for unit in province.get("units", []):
            if unit.get("owner") == country:
                if annexer is None:
                    continue
                queries.set_unit_owner(unit, annexer)
            if "air_cargo" in unit:
                unit["air_cargo"] = [cargo for cargo in unit["air_cargo"]
                                      if annexer is not None or cargo.get("owner") != country]
            for member in queries.units_with_air_cargo([unit]):
                if member.get("owner") == country and annexer is not None:
                    queries.set_unit_owner(member, annexer)
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
        data.update(master="", puppet_type="", puppets=[], faction="", is_faction_leader=False,
                    at_war_with=[], allied_with=[], pending_diplomacy={}, diplo_responses={},
                    volunteer_missions={}, scripted_events=[], armies=[], claim_queue=[],
                    revoke_queue=[], return_queue=[], release_puppet_queue=[])
    queries.normalize_armies(nation_data, map_data)
    map_screen.centers_need_update = True
    return True

def finalize_release(map_data, nation_data, master, puppet, map_screen):
    break_puppet_link(nation_data, master, puppet)

    log_global_event(nation_data, f"{master} has released {puppet} as an independent nation.")

def finalize_take_puppets(map_data, nation_data, master, target_puppet):
    puppets_to_take = nation_data.get(target_puppet, {}).get("puppets", []).copy()
    for p in puppets_to_take:
        p_type = nation_data.get(p, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
        assign_puppet(map_data, nation_data, master, p, p_type)

def canonical_puppet_release_queue(map_data, nation_data, master, entries, old_queue=()):
    """Validate release choices. Preserve host countdowns and legacy Integrated releases."""
    if master not in nation_data or master in c.UNPLAYABLE_NATIONS or not isinstance(entries, list):
        raise ValueError("Invalid releasing country or release queue.")
    previous = {entry["core_nation"]: entry for entry in old_queue}
    result, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid nation release entry.")
        subject = entry.get("core_nation")
        keep_cores = entry.get("keep_cores", False)
        # Older saves and move files did not store a release type.
        release_type = entry.get("release_type", c.PUPPET_TYPE_INTEGRATED)
        if (not isinstance(subject, str) or subject == master or subject in c.UNPLAYABLE_NATIONS
                or subject in seen or not isinstance(keep_cores, bool)
                or not isinstance(release_type, str) or release_type not in c.PUPPET_RELEASE_TYPES):
            raise ValueError("Invalid nation release choice.")
        old = previous.get(subject)
        if old:
            if (old.get("keep_cores", False) != keep_cores
                    or old.get("release_type", c.PUPPET_TYPE_INTEGRATED) != release_type):
                raise ValueError("Cancel the existing release before changing its options.")
        elif not queries.get_puppet_release_provinces(master, subject, map_data, keep_cores, result):
            raise ValueError("That country has no eligible core territory to release.")
        result.append({"core_nation": subject, "keep_cores": keep_cores, "release_type": release_type,
                       "turns_left": old.get("turns_left", 1) if old else 1})
        seen.add(subject)
    return result


def finalize_create_integrated_puppet(map_data, nation_data, master, core_nation, map_screen, keep_cores=False):
    """Compatibility entry point for an Integrated release."""
    return finalize_create_puppet(map_data, nation_data, master, core_nation, map_screen, keep_cores)


def finalize_create_puppet(map_data, nation_data, master, core_nation, map_screen,
                         keep_cores=False, release_type=c.PUPPET_TYPE_INTEGRATED):
    """Release eligible core land as an Integrated, Autonomous, or Independent country."""
    if release_type not in c.PUPPET_RELEASE_TYPES or master not in nation_data:
        return None
    territory = queries.get_puppet_release_provinces(master, core_nation, map_data, keep_cores)
    if not territory:
        return None
    territory_ids = {province["id"] for province in territory}
    master_data = nation_data.get(master, {})
    master_name = master_data.get("name", master)
    master_adjective = master_data.get("adjective", "")
    integrated = release_type == c.PUPPET_TYPE_INTEGRATED
    from data.io import country_io

    # Load from active data or from disk if dead
    if core_nation in nation_data:
        base_data = nation_data[core_nation].copy()
    else:
        base_data = country_io.get_country_stats(core_nation).copy()

    core_name = base_data.get("name", core_nation)
    if not integrated:
        base_str = core_name
    elif master_adjective:
        base_str = f"{master_adjective} {core_name}"
    else:
        base_str = f"{master_name}'s Protectorate of {core_name}"

    new_id = base_str
    new_name = base_str

    # Check collision to avoid overwriting existing subjects
    suffix = 1
    while new_id in nation_data or any(d.get("name") == new_name for d in nation_data.values()):
        suffix += 1
        new_id = f"{base_str} {suffix}"
        new_name = f"{base_str} {suffix}"

    new_data = copy.deepcopy(base_data)
    new_data["name"] = new_name

    # Only Integrated releases use the master's appearance.
    # Older country records may omit color. Use the shared country default.
    release_color = (master_data.get("color", [255, 255, 255]) if integrated
                     else base_data.get("color", country_io.DEFAULT_NATION_COLOR))
    new_data["color"] = list(release_color)

    # Update map_screen's color cache so the white default bug doesn't happen ---
    if hasattr(map_screen, 'nation_colors'):
        map_screen.nation_colors[new_id] = tuple(release_color)

    # Inherit Master's Research exactly
    master_research = nation_data.get(master, {}).get("research", {})
    new_data["research"] = copy.deepcopy(master_research)

    new_data["is_playable"] = True
    new_data.pop("is_created_integrated_puppet", None)
    if release_type == c.PUPPET_TYPE_INTEGRATED:
        new_data["is_created_integrated_puppet"] = True
    new_data["at_war_with"] = []
    new_data["allied_with"] = []
    new_data["pending_diplomacy"] = {}
    new_data["claims"] = []
    new_data["claim_queue"] = []
    new_data["revoke_queue"] = []
    new_data["return_queue"] = []
    new_data["release_puppet_queue"] = []
    new_data["puppets"] = []
    new_data["master"] = ""
    new_data["puppet_type"] = ""
    new_data["faction"] = ""
    new_data["is_faction_leader"] = False
    new_data["spawned_territories"] = []

    nation_data[new_id] = new_data

    # Independent releases do not inherit the master's faction or wars.
    if release_type != c.PUPPET_RELEASE_INDEPENDENT:
        assign_puppet(map_data, nation_data, master, new_id, release_type)

    # Transfer tiles
    for prov in map_data.values():
        if core_nation in prov.get("cores", []):
            if new_id not in prov.get("cores", []):
                prov.setdefault("cores", []).append(new_id)

            if prov["id"] in territory_ids:
                nation_data[new_id]["spawned_territories"].append(prov["id"])
                edit_province_ownership.conquer_province(map_screen, prov, new_id)

    log_global_event(nation_data, f"{master_name} has formed {new_name}.")
    return new_id
