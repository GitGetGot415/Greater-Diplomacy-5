import data.constants as c
from data.io import country_io
from map_logic.rendering import map_utils

def conquer_province(map_screen, province, new_owner):
    """Annexes a specific province to a specific country and updates visuals."""
    if province:
        # --- NEW: Integrated Puppet Capture Reroute ---
        if new_owner in map_screen.nation_data:
            nd = map_screen.nation_data[new_owner]
            if nd.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
                if province["id"] not in nd.get("spawned_territories", []):
                    master = nd.get("master")
                    if master and master in map_screen.nation_data:
                        new_owner = master

        # --- NEW: If you ever lose a territory, you immediately get a claim on it ---
        old_owner = province.get("owner", "Unclaimed")
        if old_owner not in c.UNPLAYABLE_NATIONS and old_owner != new_owner and not map_screen.is_editor:
            add_claim(map_screen, province, old_owner)

        # 1. Logic Update
        province["owner"] = new_owner
        
        # --- BUGFIX: Clear coring progress on capture ---
        if "building_queue" in province:
            province["building_queue"] = [q for q in province["building_queue"] if q.get("order_type") != "CORE"]
        
        # 2. Visual Update
        if not map_screen.viewing_ai_moves and not map_screen.ai_is_thinking:
            nations_dict = country_io.get_nation_colors()
            new_color = list(nations_dict.get(new_owner, (255, 255, 255))) # Fallback to white if unclaimed
            
            new_color = map_utils.avoid_chroma(new_color)
            
            map_utils.update_single_province_surface(
                map_screen.political_map, 
                map_screen.id_map, 
                province["map_color"], 
                new_color
            )
            
            # 3. Sync the active view
            if map_screen.map_mode == "POLITICAL":
                map_screen.active_map = map_screen.political_map
                
        # 4. UPDATE COUNTRY CENTER FOR TEXT RENDERING
        # Flag this for an update later rather than doing the heavy math instantly
        map_screen.centers_need_update = True

        if not map_screen.is_editor:
            if not province.get("cores"):
                province["cores"] = [new_owner]

        # --- A nation that just lost its last province leaves the world stage ---
        if old_owner != new_owner and old_owner in map_screen.nation_data:
            landless = not any(p.get("owner") == old_owner
                               for p in map_screen.map_data.values())
            if landless:
                retire_landless_nation(map_screen, old_owner)


def retire_landless_nation(map_screen, nation):
    """Takes a nation that holds no territory out of everyone else's business.

    Two jobs used to be one, behind a gate that only opened for a puppet the
    player had created or a rebellion put down mid-war. Everything else -- an
    ordinary conquest, or annexing a puppet the scenario shipped with -- left a
    landless nation sitting on its faction's roster forever: saves/Tannu Tuva
    Gone but not forgotten had three of them, only one of which was a puppet.

    So the diplomatic tidy-up now runs for anyone who runs out of land, and only
    the harder half -- erasing cores and the nation itself -- stays behind the
    original gate. That is the distinction the two kinds of integrated puppet
    are meant to have: one the scenario authored keeps its cores when you annex
    it, one you created and re-annexed does not.
    """
    data = map_screen.nation_data.get(nation)
    if data is None:
        return

    # --- Always: nobody is still allied with, at war with, or in a bloc with
    # a nation that no longer holds any ground. ---
    from map_logic.diplomacy.faction_actions import leave_faction
    fac = data.get("faction", "")
    if fac:
        leave_faction(map_screen.nation_data, nation)

    master = data.get("master", "")
    if master and master in map_screen.nation_data:
        if nation in map_screen.nation_data[master].get("puppets", []):
            map_screen.nation_data[master]["puppets"].remove(nation)

    for n_id, n_data in list(map_screen.nation_data.items()):
        if not isinstance(n_data, dict) or n_id == nation:
            continue
        if nation in n_data.get("at_war_with", []):
            n_data["at_war_with"].remove(nation)
        if nation in n_data.get("allied_with", []):
            n_data["allied_with"].remove(nation)
        for dict_key in ["pending_diplomacy", "diplo_responses", "diplo_cooldowns",
                         "truces", "draft_lists"]:
            if nation in n_data.get(dict_key, {}):
                del n_data[dict_key][nation]

    if fac and "FACTION_WAR_MAPS" in map_screen.nation_data:
        war_maps = map_screen.nation_data["FACTION_WAR_MAPS"]
        if fac in war_maps and nation in war_maps[fac]:
            del war_maps[fac][nation]

    # --- Only for a puppet the player created, or a rebellion put down while
    # the war was still running: erase the cores and the nation with them. ---
    should_delete = bool(data.get("is_created_integrated_puppet", False))
    if data.get("is_rebellion", False) and data.get("at_war_with", []):
        should_delete = True
    if not should_delete:
        return

    for p in map_screen.map_data.values():
        if nation in p.get("cores", []):
            p["cores"].remove(nation)
            refresh_core_tint(map_screen, p, p["cores"])

    for n_id, n_data in list(map_screen.nation_data.items()):
        if not isinstance(n_data, dict):
            continue
        if nation in n_data.get("puppets", []):
            n_data["puppets"].remove(nation)
        if n_data.get("master") == nation:
            n_data["master"] = ""
            n_data["puppet_type"] = ""
        for dict_key in ["relations", "wargoals"]:
            if nation in n_data.get(dict_key, {}):
                del n_data[dict_key][nation]
        # Remove messages sent by the dead entity to avoid ghost notifications
        if "inbox" in n_data:
            n_data["inbox"] = [msg for msg in n_data["inbox"]
                               if msg.get("sender") != nation]

    del map_screen.nation_data[nation]

def get_mixed_core_color(cores):
    """Helper function to average the colors of all cores on a tile."""
    nations_dict = country_io.get_nation_colors() 
    if not cores:
        return (255, 255, 255)
    if len(cores) == 1:
        return map_utils.avoid_chroma(nations_dict.get(cores[0], (255, 255, 255)))
        
    r = g = b = valid = 0
    for core in cores:
        col = nations_dict.get(core)
        if col:
            r += col[0]; g += col[1]; b += col[2]
            valid += 1
            
    color = (r // valid, g // valid, b // valid) if valid > 0 else (255, 255, 255)
    return map_utils.avoid_chroma(color)

def refresh_core_tint(map_screen, province, cores=None):
    """Repaints one tile on the cores overlay after its core list changed.

    Four callers -- add, remove, clear, and wiping a dead nation's cores -- each
    carried this same three-line ritual, including the "don't repaint while the
    AI is moving" guard that keeps the overlay from flickering mid-turn.
    Pass cores=None to paint the blank tile the eraser leaves behind.
    """
    if map_screen.viewing_ai_moves or map_screen.ai_is_thinking:
        return
    color = get_mixed_core_color(cores) if cores is not None else (255, 255, 255)
    map_utils.update_single_province_surface(
        map_screen.cores_map, map_screen.id_map, province["map_color"], color)
    if map_screen.map_mode == "CORES":
        map_screen.active_map = map_screen.cores_map


def add_core(map_screen, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation not in cores:
            cores.insert(0, nation) # Insert at front as primary
        
        refresh_core_tint(map_screen, province, cores)

def remove_core(map_screen, province, nation):
    if province and nation:
        cores = province.setdefault("cores", [])
        if nation in cores:
            cores.remove(nation)
        
        refresh_core_tint(map_screen, province, cores)

def clear_cores(map_screen, province):
    """Wipes all cores from the tile for the Unclaimed Eraser brush."""
    if province:
        province["cores"] = []
        
        refresh_core_tint(map_screen, province)

def add_claim(map_screen, province, nation):
    if province and nation:
        prov_id = province["id"]
        claims = map_screen.nation_data.setdefault(nation, {}).setdefault("claims", [])
        if prov_id not in claims:
            claims.append(prov_id)
        # Force a label text realignment
        map_screen.centers_need_update = True

def remove_claim(map_screen, province, nation):
    if province and nation:
        prov_id = province["id"]
        claims = map_screen.nation_data.get(nation, {}).get("claims", [])
        if prov_id in claims:
            claims.remove(prov_id)
        map_screen.centers_need_update = True

def clear_claims(map_screen, province):
    if province:
        prov_id = province["id"]
        for n_data in map_screen.nation_data.values():
            claims = n_data.get("claims", [])
            if prov_id in claims:
                claims.remove(prov_id)
        map_screen.centers_need_update = True