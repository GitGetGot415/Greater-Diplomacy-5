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
    """Generic helper to recursively apply diplomatic states down a puppet hierarchy."""
    for puppet in nation_data.get(master, {}).get("puppets", []):
        action_func(puppet)
        apply_to_puppets_recursively(puppet, nation_data, action_func)

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

def pull_puppets_into_war(master, target, map_data, nation_data):
    def _add_war(p):
        if queries.are_in_same_faction(p, target, nation_data):
            return
        link_war(nation_data, p, target)
    apply_to_puppets_recursively(master, nation_data, _add_war)

def pull_puppets_into_peace(master, target, nation_data):
    def _remove_war(p):
        remove_enemy(nation_data, p, target)
        remove_enemy(nation_data, target, p)
        nation_data[p].setdefault("truces", {})[target] = c.TRUCE_TURNS
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

def finalize_annexation(map_data, nation_data, master, puppet, map_screen):
    puppets_to_transfer = nation_data.get(puppet, {}).get("puppets", []).copy()
    for child in puppets_to_transfer:
        p_type = nation_data.get(child, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
        assign_puppet(map_data, nation_data, master, child, p_type)

    # Transfer all territory and units
    for prov in map_data.values():
        if prov.get("owner") == puppet:
            edit_province_ownership.conquer_province(map_screen, prov, master)
        for unit in prov.get("units", []):
            if unit.get("owner") == puppet:
                unit["owner"] = master

    break_puppet_link(nation_data, master, puppet)

    log_global_event(nation_data, f"{master} has fully annexed {puppet}.")

def finalize_release(map_data, nation_data, master, puppet, map_screen):
    break_puppet_link(nation_data, master, puppet)

    log_global_event(nation_data, f"{master} has released {puppet} as an independent nation.")

def finalize_take_puppets(map_data, nation_data, master, target_puppet):
    puppets_to_take = nation_data.get(target_puppet, {}).get("puppets", []).copy()
    for p in puppets_to_take:
        p_type = nation_data.get(p, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
        assign_puppet(map_data, nation_data, master, p, p_type)

def finalize_create_integrated_puppet(map_data, nation_data, master, core_nation, map_screen, keep_cores=False):
    master_data = nation_data.get(master, {})
    master_name = master_data.get("name", master)
    master_adjective = master_data.get("adjective", "")

    core_name = nation_data.get(core_nation, {}).get("name", core_nation)

    # Load from active data or from disk if dead
    if core_nation in nation_data:
        base_data = nation_data[core_nation].copy()
    else:
        from data.io import country_io
        base_data = country_io.get_country_stats(core_nation).copy()

    if master_adjective:
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

    # Inherit Master's Color
    master_color = nation_data.get(master, {}).get("color", [255, 255, 255])
    new_data["color"] = list(master_color)

    # Update map_screen's color cache so the white default bug doesn't happen ---
    if hasattr(map_screen, 'nation_colors'):
        map_screen.nation_colors[new_id] = tuple(master_color)

    # Inherit Master's Research exactly
    master_research = nation_data.get(master, {}).get("research", {})
    new_data["research"] = copy.deepcopy(master_research)

    new_data["is_playable"] = True
    new_data["is_created_integrated_puppet"] = True
    new_data["at_war_with"] = []
    new_data["allied_with"] = []
    new_data["pending_diplomacy"] = {}
    new_data["claims"] = []
    new_data["claim_queue"] = []
    new_data["revoke_queue"] = []
    new_data["return_queue"] = []
    new_data["puppets"] = []
    new_data["master"] = ""
    new_data["puppet_type"] = ""
    new_data["faction"] = ""
    new_data["is_faction_leader"] = False
    new_data["spawned_territories"] = []

    nation_data[new_id] = new_data

    # Assign as puppet
    assign_puppet(map_data, nation_data, master, new_id, c.PUPPET_TYPE_INTEGRATED)

    # Transfer tiles
    for prov in map_data.values():
        if core_nation in prov.get("cores", []):
            if new_id not in prov.get("cores", []):
                prov.setdefault("cores", []).append(new_id)

            if prov.get("owner") == master:
                # --- NEW: Keep Cores Check ---
                if keep_cores and master in prov.get("cores", []):
                    continue
                nation_data[new_id]["spawned_territories"].append(prov["id"])
                edit_province_ownership.conquer_province(map_screen, prov, new_id)

    log_global_event(nation_data, f"{master_name} has formed {new_name}.")
