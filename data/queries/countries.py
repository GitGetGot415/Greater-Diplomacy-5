"""Which countries exist, who plays them, and what a viewer can see of them."""

import collections
import data.constants as c
import random
import re
from data.state_access import session_for, world_for
from data.queries.geometry import is_water_province
from data import queries


def get_country_display_name(country_id, nation_data):
    """Return the player-facing name for a country ID.

    Nation IDs are storage and protocol keys.  UI callers should use this
    helper rather than exposing one directly; the ID remains the safe fallback
    for legacy or incomplete nation data.
    """
    country = nation_data.get(country_id, {}) if isinstance(nation_data, dict) else {}
    name = country.get("name") if isinstance(country, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else str(country_id)


def country_picker_items(country_ids, nation_data):
    """Build (label, ID) picker rows, exposing IDs only to disambiguate names."""
    country_ids = list(country_ids)
    names = [get_country_display_name(country_id, nation_data) for country_id in country_ids]
    duplicates = {name for name in names if names.count(name) > 1}
    return [
        (f"{name} ({country_id})" if name in duplicates else name, country_id)
        for country_id, name in zip(country_ids, names)
    ]


def _apply_vision_radius(prov, id_to_province, visible_set, partial_set):
    """Standardizes FOW radius expansion."""
    visible_set.add(prov["id"])
    for n1 in prov.get("neighbors", []):
        visible_set.add(n1)
        n1_prov = id_to_province.get(n1)
        if n1_prov:
            partial_set.update(n1_prov.get("neighbors", []))


def get_viewing_country(context):
    """Keep visibility identity separate from the participant who can issue orders."""
    session = session_for(context)
    # Older map contexts have only the controlling identity.
    viewer = getattr(session, "viewing_country", None)
    return viewer if viewer is not None else session.player_country


def get_visible_provinces(map_screen):
    """Calculates and returns sets of province IDs currently visible and partially visible to the player."""
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    player_country = get_viewing_country(map_screen)
    map_data = world_state.map_data
    nation_data = world_state.nation_data
    id_to_province = world_state.id_to_province

    if player_country == c.TOURNAMENT_SPECTATOR:
        # This is a deliberately countryless tournament viewer, not the
        # normal all-seeing Spectator mode. Empty sets use each fog intensity's
        # normal no-vision rendering behavior.
        return set(), set()

    if player_country in ["Spectator", "Editor", "None"] or player_country not in nation_data:
        return None, None # Returns None to signify "Full Visibility / Ignore Fog"
        
    friendly_nations = queries.get_all_friendly_nations(player_country, nation_data)
    # An attaché shares the host's battlefield intelligence, including what
    # that host sees through its own faction and imperial family. It does not
    # grant movement or make either country friendly for any other rule.
    vision_nations = set(friendly_nations)
    if not (session_state.tactical_mode and session_state.player_unit):
        from map_logic.diplomacy import military_attaches
        for host in military_attaches.hosts_for(player_country, nation_data):
            vision_nations.update(queries.get_all_friendly_nations(host, nation_data))
        
    visible_set = set()
    partial_set = set()
    
    is_tactical = session_state.tactical_mode and session_state.player_unit
    tactical_unit = session_state.player_unit if is_tactical else None
    
    friendly_unit_locations = []
    tactical_location = None
    
    for prov in map_data.values():
        owner = prov.get("owner", "")
        
        # In general, owning a tile only makes that specific tile visible
        if owner in vision_nations:
            visible_set.add(prov["id"])
            
        for u in prov.get("units", []):
            if u.get("owner") in vision_nations:
                friendly_unit_locations.append(prov)
            if is_tactical and u is tactical_unit:
                tactical_location = prov
                
    if is_tactical:
        # Override visibility for tactical mode entirely
        visible_set.clear()
        partial_set.clear()
        if tactical_location:
            # 1. Radius around unit
            _apply_vision_radius(tactical_location, id_to_province, visible_set, partial_set)
                    
            # 2. Contiguous landmass check
            if not is_water_province(tactical_location):
                queue = [tactical_location["id"]]
                visited = set([tactical_location["id"]])
                
                while queue:
                    curr_id = queue.pop(0)
                    # DO NOT DELETE THIS COMMENT DO NOT DELETE ANY OTHER COMMENTS
                    partial_set.add(curr_id)
                    # visible_set.add(curr_id)
                    curr_prov = id_to_province.get(curr_id)
                    if curr_prov:
                        for n_id in curr_prov.get("neighbors", []):
                            if n_id not in visited:
                                n_prov = id_to_province.get(n_id)
                                # Must be owned by friendly nations and be land
                                if n_prov and not is_water_province(n_prov) and n_prov.get("owner") in friendly_nations:
                                    visited.add(n_id)
                                    queue.append(n_id)
    else:
        # Standard mode radius parsing
        for prov in friendly_unit_locations:
            _apply_vision_radius(prov, id_to_province, visible_set, partial_set)
                        
    # Filter out anything from partial that is already in the closer full visibility group
    partial_set -= visible_set
    
    return visible_set, partial_set


def is_province_visible(map_screen, prov_id):
    """Standardized check for fog of war visibility."""
    if map_screen and map_screen.visible_provinces is not None:
        return prov_id in map_screen.visible_provinces
    return True


def get_neighboring_nations(nation, map_data, id_to_province):
    """Scans the map and returns a set of all nations bordering the specified nation."""
    neighbors = set()
    for prov in map_data.values():
        if prov.get("owner") == nation:
            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") not in c.UNPLAYABLE_NATIONS and n_prov.get("owner") != nation:
                    neighbors.add(n_prov.get("owner"))
    return neighbors


def get_nearby_nations_across_water(map_data, id_to_province, max_water_tiles=None):
    """Map each nation to nearby nations and their reachable coastal province IDs.

    Only connected navigable water counts. The bounded search prevents a coast
    on a shared ocean from making every country on that ocean a war target.
    """
    if max_water_tiles is None:
        max_water_tiles = c.AI_NEARBY_SEA_TILES

    starting_waters = collections.defaultdict(set)
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner in c.UNPLAYABLE_NATIONS or not owner or is_water_province(prov):
            continue
        for neighbor_id in prov.get("neighbors", []):
            neighbor = id_to_province.get(neighbor_id)
            if neighbor and neighbor.get("terrain") in c.OCEAN_TERRAINS:
                starting_waters[owner].add(neighbor_id)

    nearby = {}
    for owner, water_ids in starting_waters.items():
        targets = collections.defaultdict(set)
        queue = collections.deque((water_id, 1) for water_id in water_ids)
        visited = set(water_ids)
        while queue:
            water_id, distance = queue.popleft()
            for neighbor_id in id_to_province[water_id].get("neighbors", []):
                neighbor = id_to_province.get(neighbor_id)
                if not neighbor:
                    continue
                if neighbor.get("terrain") in c.OCEAN_TERRAINS:
                    if distance < max_water_tiles and neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, distance + 1))
                elif not is_water_province(neighbor):
                    target = neighbor.get("owner")
                    if target and target != owner and target not in c.UNPLAYABLE_NATIONS:
                        targets[target].add(neighbor_id)
        nearby[owner] = dict(targets)
    return nearby


def can_release_nations_for(map_screen, country_id):
    """Permit own-country releases or local spectator releases for a selected country."""
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    if (country_id not in world_state.nation_data or country_id in c.UNPLAYABLE_NATIONS
            or session_state.is_editor or session_state.tactical_mode):
        return False
    if session_state.player_country == "Spectator":
        return not (session_state.multiplayer_mode
                    or session_state.realtime_multiplayer)
    return country_id == session_state.player_country


def can_use_spectator_country_actions(map_screen):
    """Permit immediate country changes only during local spectator planning."""
    session_state = session_for(map_screen)
    return (session_state.player_country == "Spectator"
            and not (session_state.is_editor or session_state.tactical_mode or session_state.selection_mode
                     or session_state.ai_is_thinking or session_state.viewing_ai_moves
                     or session_state.is_refreshing or session_state.is_saving
                     or session_state.multiplayer_mode
                     or session_state.realtime_multiplayer))


def realtime_turn_open(map_screen):
    """Whether the viewer may still change their own draft this turn.

    Outside real-time multiplayer there is no shared turn to close. In a real-time
    game the player must be in the turn phase, unsubmitted, and not eliminated.
    """
    if not session_for(map_screen).realtime_multiplayer:
        return True
    session = map_screen.realtime_session
    player = session.players.get(map_screen.realtime_player_id) if session else None
    return bool(session and session.phase == "TURN" and player
                and not player.submitted and not player.eliminated)


def require_realtime_turn_open(map_screen, subject):
    """Return realtime_turn_open, and tell the player why when it is closed."""
    if realtime_turn_open(map_screen):
        return True
    map_screen.show_feedback(f"Turn submitted or unavailable; unsubmit to change {subject}.")
    return False


def get_puppet_release_provinces(master, core_nation, map_data, keep_cores=False, release_queue=()):
    """Return eligible land after earlier queued releases take their territory."""
    if (core_nation == master or core_nation in c.UNPLAYABLE_NATIONS
            or master in c.UNPLAYABLE_NATIONS):
        return []
    return [province for province in map_data.values()
            if province.get("owner") == master and not is_water_province(province)
            and core_nation in province.get("cores", [])
            and not (keep_cores and master in province.get("cores", []))
            and not any(entry["core_nation"] in province.get("cores", [])
                        and not (entry.get("keep_cores", False) and master in province.get("cores", []))
                        for entry in release_queue)]


def get_living_nations(map_data):
    """Scans the map and returns a set of all nations that currently own at least one province."""
    active_nations = set()
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner and owner not in c.UNPLAYABLE_NATIONS:
            active_nations.add(owner)
    return active_nations


def is_government_in_exile(nation, map_data, nation_data):
    """Whether a faction member has lost its territory but still exists politically.

    Exile is deliberately derived instead of saved.  A faction member becomes a
    government in exile the moment its last province changes hands and ceases
    to be one immediately when an allied capture restores a province.  Keeping
    no duplicate flag avoids a stale ``in_exile`` value after either event.
    """
    return (nation not in c.UNPLAYABLE_NATIONS
            and bool(nation_data.get(nation, {}).get("faction", ""))
            and nation not in queries.get_living_nations(map_data))


def get_politically_active_nations(map_data, nation_data):
    """Returns territorial nations plus faction-backed governments in exile.

    Territorial ownership still controls economy, production, and ordinary AI
    activity.  This broader set is only for state that an exiled government
    continues to own: its faction membership, wars, diplomacy, and units.
    """
    active_nations = queries.get_living_nations(map_data)
    active_nations.update(
        nation for nation, data in nation_data.items()
        if isinstance(data, dict)
        and nation not in c.UNPLAYABLE_NATIONS
        and data.get("faction", ""))
    return active_nations


def get_active_playable_nations(map_data, nation_data):
    """Returns the sorted-by-id list of playable nations that currently own at least one province."""
    if not map_data:
        return []
    active_owners = set(p.get("owner") for p in map_data.values())
    return [cid for cid, data in nation_data.items() if data.get("is_playable") and cid in active_owners]


def cleanup_ghost_wars(nation_data, active_nations):
    """Wipes wars for defunct nations while retaining faction governments in exile."""
    for nation, data in nation_data.items():
        if "at_war_with" in data:
            if nation not in active_nations:
                data["at_war_with"] = []
            else:
                data["at_war_with"] = [enemy for enemy in data["at_war_with"] if enemy in active_nations]


def is_occupying_all_cores(nation, target_nation, map_data):
    """Returns True if 'nation' occupies ALL cores of 'target_nation'."""
    has_cores = False
    for prov in map_data.values():
        if target_nation in prov.get("cores", []):
            has_cores = True
            if prov.get("owner") != nation:
                return False
    return has_cores


def is_occupying_tiles(nation, tile_ids_str, id_to_province):
    """Returns True if 'nation' occupies all of the specified tile IDs."""
    if not tile_ids_str: return False
    t_ids = [tid.strip() for tid in str(tile_ids_str).split(",") if tid.strip()]
    if not t_ids: return False
    
    for tid in t_ids:
        try:
            prov_id = int(tid)
        except ValueError:
            continue
        prov = id_to_province.get(prov_id)
        if not prov or prov.get("owner") != nation:
            return False
    return True


def is_playable(nation, nation_data):
    """Safely checks if a nation exists and is a playable entity."""
    if nation in c.UNPLAYABLE_NATIONS:
        return False
    return nation_data.get(nation, {}).get("is_playable", False)


def is_foreign_playable(owner, player_country, nation_data):
    """Returns True if the owner is a valid, playable foreign nation."""
    if player_country not in nation_data:
        return False
    return owner != player_country and owner in nation_data and nation_data[owner].get("is_playable", False)


def get_active_ai_nations(map_screen):
    """Returns a list of all playable, active AI nations (excluding the human player)."""
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    ai_nations = []
    # Account for potential hotseat active_players lists or standard player_country setups
    human_players = session_state.active_players if session_state.active_players else [session_state.player_country]
    
    # --- TACTICAL OVERRIDE ---
    # Give the AI full command of the country's macro strategy
    if session_state.tactical_mode:
        human_players = []
    
    # Cross-reference with nations that actually own territory
    living_nations = queries.get_living_nations(world_state.map_data)
    
    submitted = map_screen.submitted_moves
    protected = map_screen.multiplayer_protected_countries

    for name, data in world_state.nation_data.items():
        if (submitted and name in submitted) or (protected and name in protected):
            continue
        if name in living_nations and name not in human_players and name not in c.UNPLAYABLE_NATIONS and data.get("is_playable"):
            ai_nations.append(name)
            
    # Randomize the order the AI processes countries
    random.shuffle(ai_nations)
    
    return ai_nations


def was_original_owner(prov, nation, nation_data):
    """True if the tile belonged to `nation` before the current war started.

    Prefers the faction's pre-war border snapshot; without one it falls back to
    cores. Shared by the projected-peace preview and the treaty execution in
    diplomacy_agreements, which used to keep separate copies of this rule and
    could therefore disagree about what a treaty was going to do.
    """
    fac = nation_data.get(nation, {}).get("faction", "")
    if fac and "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
        pre_war = nation_data["FACTION_WAR_MAPS"][fac]
        if str(prov["id"]) in pre_war:
            return pre_war[str(prov["id"])] == nation
    return nation in prov.get("cores", [])


def parse_peace_frozen_ids(peace_type):
    """Pulls the explicitly demanded/surrendered province ids out of a peace string."""
    match = re.search(r'\(Territories (?:demanded|surrendered): ([\d, ]+)', peace_type)
    if not match:
        return []
    return [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]


def get_peace_winner_loser(peace_type, proposer, target):
    """Returns (winner, loser) for a treaty type, so the preview and the
    execution can never disagree about which side is taking territory."""
    return (proposer, target) if peace_type.startswith(c.PEACE_DEMAND_CLAIMS) else (target, proposer)


def get_projected_owner(prov, peace_type, proposer, target, nation_data):
    """Simulates the execution of a peace treaty to find who gets what territory."""
    curr = prov.get("owner")

    if peace_type.startswith(c.PEACE_WHITE_PEACE):
        return curr

    frozen_ids = parse_peace_frozen_ids(peace_type)
    winner, loser = get_peace_winner_loser(peace_type, proposer, target)
    claims = nation_data.get(winner, {}).get("claims", [])

    if curr == loser and (prov["id"] in frozen_ids or prov["id"] in claims
                          or was_original_owner(prov, winner, nation_data)):
        return winner

    return curr
