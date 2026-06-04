from map_logic.system32 import edit_province_ownership
from data import queries
import data.constants as c

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

    fac_a = nation_data.get(a, {}).get("faction", "")
    fac_b = nation_data.get(b, {}).get("faction", "")

    if fac_a: queries.clear_faction_pre_war_map_if_peace(fac_a, nation_data)
    if fac_b: queries.clear_faction_pre_war_map_if_peace(fac_b, nation_data)

def execute_peace_treaty(map_data, nation_data, proposer, target, peace_type, map_screen):
    """Executes the specific terms of a peace deal based on its type."""

    if peace_type == c.PEACE_WHITE_PEACE:
        pass # Just regular finalize_neutral happens at the end

    elif peace_type == c.PEACE_DEMAND_CLAIMS:
        # Proposer demands claims from target
        claims = nation_data.get(proposer, {}).get("claims", [])
        for prov in map_data.values():
            if prov["id"] in claims and prov.get("owner") == target:
                edit_province_ownership.conquer_province(map_screen, prov, proposer)

    elif peace_type == c.PEACE_SURRENDER:
        # Target gets their claims.
        claims = nation_data.get(target, {}).get("claims", [])
        for prov in map_data.values():
            if prov["id"] in claims and prov.get("owner") == proposer:
                edit_province_ownership.conquer_province(map_screen, prov, target)

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

def finalize_disband_faction(nation_data, leader):
    fac = nation_data[leader].get("faction", "")
    if not fac: return
    
    if "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
        del nation_data["FACTION_WAR_MAPS"][fac]
        
    for n, d in nation_data.items():
        if d.get("faction") == fac:
            d["faction"] = ""
            d["is_faction_leader"] = False

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

def finalize_faction_leave(nation_data, leaver):
    fac = nation_data[leaver].get("faction", "")
    members = queries.get_faction_members(fac, nation_data)
    
    if fac:
        queries.remove_member_from_pre_war_map(leaver, fac, nation_data)
        
    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False
    
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
    
    # Temporary Faction Desertion Modifier
    queries.add_temporary_modifier(leader, member, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)
    queries.add_temporary_modifier(member, leader, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)