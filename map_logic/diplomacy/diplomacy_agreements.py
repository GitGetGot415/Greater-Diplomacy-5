from data import queries

def finalize_war(nation_data, a, b):
    # GUARDRAIL: If they are in the same faction, the aggressor (a) leaves automatically
    if queries.are_in_same_faction(a, b, nation_data):
        finalize_faction_leave(nation_data, a)

    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].append(other)
            
        # Snap relations to rock bottom
        nation_data[country].setdefault("relations", {})[other] = -100

        # --- FIX: Clear faction war cooldowns so allies can be called in ---
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

def finalize_create_faction(nation_data, creator):
    fac = f"The {nation_data[creator].get('name', creator)} Pact"
    nation_data[creator]["faction"] = fac
    nation_data[creator]["is_faction_leader"] = True

def finalize_disband_faction(nation_data, leader):
    fac = nation_data[leader].get("faction", "")
    if not fac: return
    for n, d in nation_data.items():
        if d.get("faction") == fac:
            d["faction"] = ""
            d["is_faction_leader"] = False

def finalize_faction_join(nation_data, host, joiner):
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

def finalize_faction_leave(nation_data, leaver):
    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False

def join_faction_wars(nation_data, joiner, faction_member):
    """Pulls the joining nation into all active wars of the target faction member."""
    wars = nation_data[faction_member].get("at_war_with", [])
    for enemy in wars:
        if enemy not in nation_data[joiner]["at_war_with"]:
            nation_data[joiner]["at_war_with"].append(enemy)
        if joiner not in nation_data[enemy]["at_war_with"]:
            nation_data[enemy]["at_war_with"].append(joiner)
            
        # Instantly drop relations to -100 upon joining a war
        nation_data[joiner].setdefault("relations", {})[enemy] = -100
        nation_data[enemy].setdefault("relations", {})[joiner] = -100

    # --- FIX: Clear the cooldowns between these two so they can interact in future wars ---
    for a, b in [(joiner, faction_member), (faction_member, joiner)]:
        if "diplo_cooldowns" in nation_data[a] and b in nation_data[a]["diplo_cooldowns"]:
            nation_data[a]["diplo_cooldowns"][b].pop("CALL_TO_ARMS", None)
            nation_data[a]["diplo_cooldowns"][b].pop("JOIN_WARS", None)

def finalize_faction_kick(nation_data, leader, member):
    nation_data[member]["faction"] = ""
    nation_data[member]["is_faction_leader"] = False
    
    # Sour relations instantly upon being kicked
    nation_data[leader].setdefault("relations", {})[member] = -50
    nation_data[member].setdefault("relations", {})[leader] = -50