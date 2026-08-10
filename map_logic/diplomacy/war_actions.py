"""War state mutations: declaring, joining, and ending wars, plus the shared
military-access helper the puppet/faction paths also reach for.

See map_logic/diplomacy/diplomacy_agreements.py for how this fits alongside
puppet_actions.py and faction_actions.py.
"""
from map_logic.turn_processing import edit_province_ownership
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


def _break_for_independence(map_data, nation_data, rebel, master, headline):
    """Cuts a puppet loose because the two of them went to war.

    Written out twice, once per direction, differing only in the headline: a
    puppet that attacks its master is rebelling, one that is attacked has
    independence forced on it. Either way the master keeps a claim on every
    province the rebel holds, which is what gives the war a wargoal.
    """
    from map_logic.diplomacy.puppet_actions import break_puppet_link
    break_puppet_link(nation_data, master, rebel)

    master_claims = nation_data.setdefault(master, {}).setdefault("claims", [])
    for prov in map_data.values():
        if prov.get("owner") == rebel and prov["id"] not in master_claims:
            master_claims.append(prov["id"])

    log_global_event(nation_data, headline)


def finalize_war(map_data, nation_data, a, b):
    from map_logic.diplomacy.faction_actions import finalize_faction_leave
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_war, pull_master_into_war

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
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_peace

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
