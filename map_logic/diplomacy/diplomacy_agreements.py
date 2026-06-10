import re
from map_logic.system32 import edit_province_ownership
from data import queries
import data.constants as c

# --- RECURSIVE PUPPET HELPERS ---
def assign_puppet(map_data, nation_data, master, puppet, puppet_type=c.PUPPET_TYPE_AUTONOMOUS):
    p_data = nation_data.get(puppet, {})
    m_data = nation_data.get(master, {})

    p_data["master"] = master
    p_data["puppet_type"] = puppet_type
    
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
        
    # Force peace between them if they were at war
    if puppet in m_data.get("at_war_with", []):
        finalize_neutral(nation_data, master, puppet)

def pull_puppets_into_war(master, target, map_data, nation_data):
    for puppet in nation_data.get(master, {}).get("puppets", []):
        if target not in nation_data.get(puppet, {}).get("at_war_with", []):
            nation_data.setdefault(puppet, {}).setdefault("at_war_with", []).append(target)
        if puppet not in nation_data.get(target, {}).get("at_war_with", []):
            nation_data.setdefault(target, {}).setdefault("at_war_with", []).append(puppet)
        pull_puppets_into_war(puppet, target, map_data, nation_data)

def pull_puppets_into_peace(master, target, nation_data):
    for puppet in nation_data.get(master, {}).get("puppets", []):
        if target in nation_data.get(puppet, {}).get("at_war_with", []):
            nation_data[puppet]["at_war_with"].remove(target)
        if puppet in nation_data.get(target, {}).get("at_war_with", []):
            nation_data[target]["at_war_with"].remove(puppet)
        nation_data[puppet].setdefault("relations", {})[target] = 0
        nation_data[puppet].setdefault("truces", {})[target] = c.TRUCE_TURNS
        pull_puppets_into_peace(puppet, target, nation_data)

def pull_puppets_into_faction(master, fac, map_data, nation_data):
    for puppet in nation_data.get(master, {}).get("puppets", []):
        nation_data[puppet]["faction"] = fac
        nation_data[puppet]["is_faction_leader"] = False
        pull_puppets_into_faction(puppet, fac, map_data, nation_data)

def pull_puppets_out_of_faction(master, nation_data):
    for puppet in nation_data.get(master, {}).get("puppets", []):
        nation_data[puppet]["faction"] = ""
        nation_data[puppet]["is_faction_leader"] = False
        pull_puppets_out_of_faction(puppet, nation_data)

def finalize_annexation(map_data, nation_data, master, puppet, map_screen):
    if puppet in nation_data.get(master, {}).get("puppets", []):
        nation_data[master]["puppets"].remove(puppet)
    nation_data.get(puppet, {})["master"] = ""
    nation_data.get(puppet, {})["puppet_type"] = ""
    
    # Transfer all territory and units
    from map_logic.system32 import edit_province_ownership
    for prov in map_data.values():
        if prov.get("owner") == puppet:
            edit_province_ownership.conquer_province(map_screen, prov, master)
        for unit in prov.get("units", []):
            if unit.get("owner") == puppet:
                unit["owner"] = master
                
    from map_logic.diplomacy.diplomacy_events import log_global_event
    log_global_event(nation_data, f"{master} has fully annexed {puppet}.")

def finalize_release(map_data, nation_data, master, puppet, map_screen):
    if puppet in nation_data.get(master, {}).get("puppets", []):
        nation_data[master]["puppets"].remove(puppet)
    nation_data.get(puppet, {})["master"] = ""
    nation_data.get(puppet, {})["puppet_type"] = ""
    
    from map_logic.diplomacy.diplomacy_events import log_global_event
    log_global_event(nation_data, f"{master} has released {puppet} as an independent nation.")
# ---------------------------------

def finalize_war(map_data, nation_data, a, b):
    # GUARDRAIL: If they are in the same faction, the aggressor (a) leaves automatically
    if queries.are_in_same_faction(a, b, nation_data):
        finalize_faction_leave(nation_data, a)

    fac_a = nation_data.get(a, {}).get("faction", "")
    fac_b = nation_data.get(b, {}).get("faction", "")

    if fac_a and not queries.is_faction_at_war(fac_a, nation_data):
        queries.save_faction_pre_war_map(fac_a, map_data, nation_data)
    if fac_b and not queries.is_faction_at_war(fac_b, nation_data):
        queries.save_faction_pre_war_map(fac_b, map_data, nation_data)

    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].append(other)

        # Clear faction war cooldowns so allies can be called in
        faction = nation_data[country].get("faction", "")
        if faction:
            members = queries.get_faction_members(faction, nation_data)
            for member in members:
                if "diplo_cooldowns" in nation_data[country] and member in nation_data[country]["diplo_cooldowns"]:
                    nation_data[country]["diplo_cooldowns"][member].pop("CALL_TO_ARMS", None)
                    nation_data[country]["diplo_cooldowns"][member].pop("JOIN_WARS", None)

    # Pull subjects into the fray
    pull_puppets_into_war(a, b, map_data, nation_data)
    pull_puppets_into_war(b, a, map_data, nation_data)

def finalize_neutral(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)
            
        # Reset relations to 0 upon ceasefire
        nation_data[country].setdefault("relations", {})[other] = 0
        
        # Apply Temporary Post-War Modifier
        queries.add_temporary_modifier(country, other, "recent_war", c.REL_MOD_RECENT_WAR, nation_data)

        # Apply Non-Aggression Pact
        nation_data[country].setdefault("truces", {})[other] = c.TRUCE_TURNS

    # Subdue puppets 
    pull_puppets_into_peace(a, b, nation_data)
    pull_puppets_into_peace(b, a, nation_data)

    fac_a = nation_data.get(a, {}).get("faction", "")
    fac_b = nation_data.get(b, {}).get("faction", "")

    if fac_a: queries.clear_faction_pre_war_map_if_peace(fac_a, nation_data)
    if fac_b: queries.clear_faction_pre_war_map_if_peace(fac_b, nation_data)

def execute_peace_treaty(map_data, nation_data, proposer, target, peace_type, map_screen):
    """Executes the specific terms of a peace deal based on its type."""
    import re

    # Helper to check original ownership (Uses the pre-war border snapshot if available)
    def was_original_owner(prov, nation):
        fac = nation_data.get(nation, {}).get("faction", "")
        if fac and "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
            pre_war = nation_data["FACTION_WAR_MAPS"][fac]
            if str(prov["id"]) in pre_war:
                return pre_war[str(prov["id"])] == nation
        # Fallback to cores if the war snapshot doesn't exist
        return nation in prov.get("cores", [])

    # Extract frozen IDs using regex
    frozen_ids = []
    
    # THE FIX: Removed the space before the + so it correctly matches the list of numbers
    match = re.search(r'\(Territories (?:demanded|surrendered): ([\d, ]+)', peace_type)
    
    if match:
        frozen_ids = [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]

    if peace_type.startswith(c.PEACE_WHITE_PEACE):
        # Status Quo: Nothing changes
        pass

    elif peace_type.startswith(c.PEACE_DEMAND_CLAIMS):
        # Proposer wins. Target is Loser.
        for prov in map_data.values():
            # 1. Proposer gets the explicitly frozen claims
            if prov["id"] in frozen_ids and prov.get("owner") == target:
                edit_province_ownership.conquer_province(map_screen, prov, proposer)
            # 2. Loser (Target) must return any of Proposer's territory they occupied
            elif prov.get("owner") == target and was_original_owner(prov, proposer):
                edit_province_ownership.conquer_province(map_screen, prov, proposer)
            # Proposer keeps anything they currently occupy, so no action needed.

    elif peace_type.startswith(c.PEACE_SURRENDER):
        # Target wins. Proposer is Loser.
        for prov in map_data.values():
            # 1. Target gets the explicitly frozen claims
            if prov["id"] in frozen_ids and prov.get("owner") == proposer:
                edit_province_ownership.conquer_province(map_screen, prov, target)
            # 2. Loser (Proposer) must return any of Target's territory they occupied
            elif prov.get("owner") == proposer and was_original_owner(prov, target):
                edit_province_ownership.conquer_province(map_screen, prov, target)
            # Target keeps anything they currently occupy, so no action needed.

    # Clear wargoals between the two
    if proposer in nation_data.get(target, {}).get("wargoals", {}):
        del nation_data[target]["wargoals"][proposer]
    if target in nation_data.get(proposer, {}).get("wargoals", {}):
        del nation_data[proposer]["wargoals"][target]

    finalize_neutral(nation_data, proposer, target)

def finalize_create_faction(map_data, nation_data, creator):
    fac = f"The {nation_data[creator].get('name', creator)} Pact"
    nation_data[creator]["faction"] = fac
    nation_data[creator]["is_faction_leader"] = True

    if queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)
        
    pull_puppets_into_faction(creator, fac, map_data, nation_data)

def finalize_disband_faction(nation_data, leader):
    fac = nation_data[leader].get("faction", "")
    if not fac: return
    
    if "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
        del nation_data["FACTION_WAR_MAPS"][fac]
        
    for n, d in nation_data.items():
        if d.get("faction") == fac:
            d["faction"] = ""
            d["is_faction_leader"] = False
            
    pull_puppets_out_of_faction(leader, nation_data)

def finalize_faction_join(map_data, nation_data, host, joiner):
    fac = nation_data[host].get("faction", "")
    if fac:
        nation_data[joiner]["faction"] = fac
        nation_data[joiner]["is_faction_leader"] = False
        
        # Set relations to 100 with all faction members
        members = queries.get_faction_members(fac, nation_data)
        for member in members:
            if member != joiner:
                nation_data[joiner].setdefault("relations", {})[member] = 100
                nation_data[member].setdefault("relations", {})[joiner] = 100

        if queries.is_faction_at_war(fac, nation_data):
            queries.add_member_to_pre_war_map(joiner, fac, map_data, nation_data)
            
        pull_puppets_into_faction(joiner, fac, map_data, nation_data)

def finalize_faction_leave(nation_data, leaver):
    fac = nation_data[leaver].get("faction", "")
    members = queries.get_faction_members(fac, nation_data)
    
    if fac:
        queries.remove_member_from_pre_war_map(leaver, fac, nation_data)
        
    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False
    
    pull_puppets_out_of_faction(leaver, nation_data)
    
    # Apply Temporary Faction Desertion Modifier
    for m in members:
        if m != leaver:
            queries.add_temporary_modifier(leaver, m, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)
            queries.add_temporary_modifier(m, leaver, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)

def join_faction_wars(map_data, nation_data, joiner, faction_member):
    """Pulls the joining nation into all active wars of the target faction member."""
    fac = nation_data[faction_member].get("faction", "")
    if fac and not queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)

    wars = nation_data[faction_member].get("at_war_with", [])
    for enemy in wars:
        if enemy not in nation_data[joiner]["at_war_with"]:
            nation_data[joiner]["at_war_with"].append(enemy)
        if joiner not in nation_data[enemy]["at_war_with"]:
            nation_data[enemy]["at_war_with"].append(joiner)
            
        # Recursive puppet pull logic for new wars joined
        pull_puppets_into_war(joiner, enemy, map_data, nation_data)

    # Clear the cooldowns between these two so they can interact in future wars
    for a, b in [(joiner, faction_member), (faction_member, joiner)]:
        if "diplo_cooldowns" in nation_data[a] and b in nation_data[a]["diplo_cooldowns"]:
            nation_data[a]["diplo_cooldowns"][b].pop("CALL_TO_ARMS", None)
            nation_data[a]["diplo_cooldowns"][b].pop("JOIN_WARS", None)

def finalize_faction_kick(nation_data, leader, member):
    fac = nation_data[member].get("faction", "")
    if fac:
        queries.remove_member_from_pre_war_map(member, fac, nation_data)
        
    nation_data[member]["faction"] = ""
    nation_data[member]["is_faction_leader"] = False
    
    pull_puppets_out_of_faction(member, nation_data)
    
    # Temporary Faction Desertion Modifier
    queries.add_temporary_modifier(leader, member, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)
    queries.add_temporary_modifier(member, leader, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)