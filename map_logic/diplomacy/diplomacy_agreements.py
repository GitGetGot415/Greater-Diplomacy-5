import copy
from map_logic.system32 import edit_province_ownership
from data import queries
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.diplomacy.diplomacy_messages import clear_pending
import data.constants as c

# --- SHARED STATE EDITS ---
# The small, repeated edits to a nation's diplomatic bookkeeping. Each was
# written out three or four times below with a different guard style, and the
# odd one out was the one that could raise.

def sever_military_access(nation_data, a, b):
    """Drops any granted or requested passage between two nations.

    Done when a nation is puppeted, when it joins a faction, and when a puppet
    is dragged into its master's faction: in all three cases the two now move
    through each other's territory by right, so a standing grant is redundant
    and a pending request is moot.
    """
    for country, other in ((a, b), (b, a)):
        access = nation_data.get(country, {}).get("military_access", [])
        if other in access:
            access.remove(other)
        clear_pending(nation_data, country, other, only_actions=["REQ_MILITARY_ACCESS"])


def add_enemy(nation_data, country, other):
    """Puts `other` on `country`'s war list. True when it wasn't already there."""
    enemies = nation_data.setdefault(country, {}).setdefault("at_war_with", [])
    if other in enemies:
        return False
    enemies.append(other)
    return True


def remove_enemy(nation_data, country, other):
    """Takes `other` off `country`'s war list. True when it was on it.

    The mirror of add_enemy, and written out in two different styles by the
    peace paths -- one indexing nation_data directly, one going through .get().
    """
    enemies = nation_data.get(country, {}).get("at_war_with")
    if not enemies or other not in enemies:
        return False
    enemies.remove(other)
    return True


def link_war(nation_data, a, b):
    """Puts two nations on each other's war list.

    Four call sites wrote this out; one of them indexed nation_data directly
    and raised KeyError for a nation that had never been given the key.
    """
    for country, other in ((a, b), (b, a)):
        add_enemy(nation_data, country, other)


def clear_war_call_cooldowns(nation_data, country, other):
    """Lets `country` ask `other` for help again immediately.

    Both a new war and a newly joined war reset these, so an ally who was
    turned down last turn can be asked again now the situation has changed.
    Deliberately one-directional: a new war clears only the belligerent's own
    cooldowns, while joining a war clears both sides'.
    """
    cooldowns = nation_data.get(country, {}).get("diplo_cooldowns", {}).get(other)
    if cooldowns:
        cooldowns.pop("CALL_TO_ARMS", None)
        cooldowns.pop("JOIN_WARS", None)


def settle_with_faction(nation_data, joiner, fac):
    """Makes peace with everyone already in `fac` and drops passage rights.

    A faction cannot contain two nations at war with each other, so joining one
    ends any such war. Written out twice: once for a nation joining directly,
    once for its puppets being pulled in behind it.
    """
    for member in queries.get_faction_members(fac, nation_data):
        if member == joiner:
            continue
        if queries.are_at_war(joiner, member, nation_data) or queries.are_at_war(member, joiner, nation_data):
            finalize_neutral(nation_data, joiner, member)
        sever_military_access(nation_data, joiner, member)


def leave_faction(nation_data, leaver):
    """Strips a nation's faction membership and takes its puppets with it.

    The shared body of leaving voluntarily and being kicked out. What differs
    is only who resents whom afterwards, which stays with the two callers.
    """
    fac = nation_data[leaver].get("faction", "")
    if fac:
        queries.remove_member_from_pre_war_map(leaver, fac, nation_data)

    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False
    pull_puppets_out_of_faction(leaver, nation_data)
    return fac


def _break_for_independence(map_data, nation_data, rebel, master, headline):
    """Cuts a puppet loose because the two of them went to war.

    Written out twice, once per direction, differing only in the headline: a
    puppet that attacks its master is rebelling, one that is attacked has
    independence forced on it. Either way the master keeps a claim on every
    province the rebel holds, which is what gives the war a wargoal.
    """
    break_puppet_link(nation_data, master, rebel)

    master_claims = nation_data.setdefault(master, {}).setdefault("claims", [])
    for prov in map_data.values():
        if prov.get("owner") == rebel and prov["id"] not in master_claims:
            master_claims.append(prov["id"])

    log_global_event(nation_data, headline)


def resent_departure(nation_data, a, b):
    """Applies the mutual "they walked out on us" relations hit."""
    queries.add_temporary_modifier(a, b, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)
    queries.add_temporary_modifier(b, a, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)


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
    from map_logic.system32 import edit_province_ownership
    for prov in map_data.values():
        if prov.get("owner") == puppet:
            edit_province_ownership.conquer_province(map_screen, prov, master)
        for unit in prov.get("units", []):
            if unit.get("owner") == puppet:
                unit["owner"] = master
                
    break_puppet_link(nation_data, master, puppet)
    
    from map_logic.diplomacy.diplomacy_events import log_global_event
    log_global_event(nation_data, f"{master} has fully annexed {puppet}.")

def finalize_release(map_data, nation_data, master, puppet, map_screen):
    break_puppet_link(nation_data, master, puppet)
    
    from map_logic.diplomacy.diplomacy_events import log_global_event
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

# ---------------------------------

def finalize_war(map_data, nation_data, a, b):
    master_a = nation_data.get(a, {}).get("master", "")
    master_b = nation_data.get(b, {}).get("master", "")

    # GUARDRAIL: If they are in the same faction, the aggressor (a) leaves automatically
    # UNLESS it's a preemptive war against a puppet, then the puppet leaves
    if queries.are_in_same_faction(a, b, nation_data):
        if master_b == a:
            finalize_faction_leave(nation_data, b)
        else:
            finalize_faction_leave(nation_data, a)
        
    # If they are master and puppet, break the bond and declare independence
    if master_a == b:
        _break_for_independence(map_data, nation_data, rebel=a, master=b,
                                headline=f"{a} has declared a war of independence against {b}!")
    elif master_b == a:
        _break_for_independence(map_data, nation_data, rebel=b, master=a,
                                headline=f"{b} has achieved independence after being attacked by {a}!")

    fac_a = nation_data.get(a, {}).get("faction", "")
    fac_b = nation_data.get(b, {}).get("faction", "")

    if fac_a and not queries.is_faction_at_war(fac_a, nation_data):
        queries.save_faction_pre_war_map(fac_a, map_data, nation_data)
    if fac_b and not queries.is_faction_at_war(fac_b, nation_data):
        queries.save_faction_pre_war_map(fac_b, map_data, nation_data)

    for country, other in [(a, b), (b, a)]:
        if add_enemy(nation_data, country, other):
            # NEW: Track war duration for ceasefire cooldowns
            nation_data[country].setdefault("war_durations", {})[other] = 0

        # Clear military access when going to war
        access = nation_data[country].get("military_access", [])
        if other in access:
            access.remove(other)

        # Clear faction war cooldowns so allies can be called in
        faction = nation_data[country].get("faction", "")
        if faction:
            for member in queries.get_faction_members(faction, nation_data):
                clear_war_call_cooldowns(nation_data, country, member)

    # Pull subjects into the fray
    pull_puppets_into_war(a, b, map_data, nation_data)
    pull_puppets_into_war(b, a, map_data, nation_data)
    
    # Pull masters into the fray (which cascades to their other puppets)
    pull_master_into_war(a, b, map_data, nation_data)
    pull_master_into_war(b, a, map_data, nation_data)

def finalize_neutral(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        remove_enemy(nation_data, country, other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)
            
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
    # Frozen-id parsing and the pre-war ownership rule live in queries, so the
    # projected-peace map the player is shown is driven by the exact same logic
    # that runs here when they accept.
    frozen_ids = queries.parse_peace_frozen_ids(peace_type)

    # A white peace is pure status quo, so only the two territory-transferring
    # treaty types actually touch the map.
    if peace_type.startswith(c.PEACE_DEMAND_CLAIMS) or peace_type.startswith(c.PEACE_SURRENDER):
        winner, loser = queries.get_peace_winner_loser(peace_type, proposer, target)
        for prov in map_data.values():
            if prov.get("owner") != loser:
                # The winner keeps anything they currently occupy, so no action needed.
                continue
            # The loser hands over the explicitly frozen claims, plus any of the
            # winner's own pre-war territory they are sitting on.
            if prov["id"] in frozen_ids or queries.was_original_owner(prov, winner, nation_data):
                edit_province_ownership.conquer_province(map_screen, prov, winner)

    # Clear wargoals between the two
    if proposer in nation_data.get(target, {}).get("wargoals", {}):
        del nation_data[target]["wargoals"][proposer]
    if target in nation_data.get(proposer, {}).get("wargoals", {}):
        del nation_data[proposer]["wargoals"][target]

    finalize_neutral(nation_data, proposer, target)

def finalize_create_faction(map_data, nation_data, creator):
    import data.constants as c
    if getattr(c, "DISABLE_FACTIONS", False):
        return

    master = nation_data.get(creator, {}).get("master", "")
    leader = master if master else creator
    
    fac = f"The {nation_data[leader].get('name', leader)} Pact"
    nation_data[leader]["faction"] = fac
    nation_data[leader]["is_faction_leader"] = True
    
    if master:
        nation_data[creator]["faction"] = fac
        nation_data[creator]["is_faction_leader"] = False

    if queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)
        
    pull_puppets_into_faction(leader, fac, map_data, nation_data)

def finalize_disband_faction(nation_data, leader):
    fac = nation_data[leader].get("faction", "")
    if not fac: return
    
    if "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
        del nation_data["FACTION_WAR_MAPS"][fac]
        
    for n, d in list(nation_data.items()):
        if d.get("faction") == fac:
            d["faction"] = ""
            d["is_faction_leader"] = False
            
    pull_puppets_out_of_faction(leader, nation_data)

def finalize_faction_join(map_data, nation_data, host, joiner):
    fac = nation_data[host].get("faction", "")
    if fac:
        nation_data[joiner]["faction"] = fac
        nation_data[joiner]["is_faction_leader"] = False
        
        settle_with_faction(nation_data, joiner, fac)

        if queries.is_faction_at_war(fac, nation_data):
            queries.add_member_to_pre_war_map(joiner, fac, map_data, nation_data)
            
        pull_puppets_into_faction(joiner, fac, map_data, nation_data)

def finalize_faction_leave(nation_data, leaver):
    """A nation walks out of its faction. Everyone left behind resents it."""
    # Read the roster before the membership is stripped.
    members = queries.get_faction_members(nation_data[leaver].get("faction", ""), nation_data)

    fac = leave_faction(nation_data, leaver)

    for m in members:
        if m != leaver:
            resent_departure(nation_data, leaver, m)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)

def join_faction_wars(map_data, nation_data, joiner, faction_member):
    """Pulls the joining nation into all active wars of the target faction member."""
    fac = nation_data[faction_member].get("faction", "")
    if fac and not queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)

    wars = nation_data[faction_member].get("at_war_with", [])
    for enemy in wars:
        link_war(nation_data, joiner, enemy)

        # Recursive puppet pull logic for new wars joined
        pull_puppets_into_war(joiner, enemy, map_data, nation_data)

    # Clear the cooldowns between these two so they can interact in future wars
    clear_war_call_cooldowns(nation_data, joiner, faction_member)
    clear_war_call_cooldowns(nation_data, faction_member, joiner)

def finalize_faction_kick(nation_data, leader, member):
    """The leader throws a member out. Only the two of them fall out over it,
    unlike leaving voluntarily, which the whole faction takes personally."""
    fac = leave_faction(nation_data, member)

    resent_departure(nation_data, leader, member)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)