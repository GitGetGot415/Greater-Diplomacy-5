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

        # --- NEW: Check if old owner was a created integrated puppet and lost all territory ---
        if old_owner != new_owner and old_owner in map_screen.nation_data:
            should_delete = False
            
            if map_screen.nation_data[old_owner].get("is_created_integrated_puppet", False):
                should_delete = not any(p.get("owner") == old_owner for p in map_screen.map_data.values())
            
            # Rebellion killed before peace deal: still at war means defeated in combat, not via treaty
            if map_screen.nation_data[old_owner].get("is_rebellion", False):
                if not any(p.get("owner") == old_owner for p in map_screen.map_data.values()):
                    if map_screen.nation_data[old_owner].get("at_war_with", []):
                        should_delete = True
            
            if should_delete:
                # Remove all cores of this country from the map
                for p in map_screen.map_data.values():
                    if old_owner in p.get("cores", []):
                        p["cores"].remove(old_owner)
                        refresh_core_tint(map_screen, p, p["cores"])
                            
                # --- Completely remove from the game ---
                # 1. Break puppet link from master
                master = map_screen.nation_data[old_owner].get("master", "")
                if master and master in map_screen.nation_data:
                    if old_owner in map_screen.nation_data[master].get("puppets", []):
                        map_screen.nation_data[master]["puppets"].remove(old_owner)
                        
                # 2. Cleanup references in other nations
                for n_id, n_data in list(map_screen.nation_data.items()):
                    if old_owner in n_data.get("at_war_with", []):
                        n_data["at_war_with"].remove(old_owner)
                    if old_owner in n_data.get("allied_with", []):
                        n_data["allied_with"].remove(old_owner)
                    if old_owner in n_data.get("puppets", []):
                        n_data["puppets"].remove(old_owner)
                    if n_data.get("master") == old_owner:
                        n_data["master"] = ""
                        n_data["puppet_type"] = ""
                        
                    for dict_key in ["relations", "truces", "diplo_cooldowns", "wargoals", "pending_diplomacy", "draft_lists", "diplo_responses"]:
                        if old_owner in n_data.get(dict_key, {}):
                            del n_data[dict_key][old_owner]
                            
                    # Remove messages sent by the dead entity to avoid ghost notifications
                    if "inbox" in n_data:
                        n_data["inbox"] = [msg for msg in n_data["inbox"] if msg.get("sender") != old_owner]
                            
                # Cleanup faction maps
                fac = map_screen.nation_data[old_owner].get("faction", "")
                if fac and "FACTION_WAR_MAPS" in map_screen.nation_data:
                    if fac in map_screen.nation_data["FACTION_WAR_MAPS"]:
                        if old_owner in map_screen.nation_data["FACTION_WAR_MAPS"][fac]:
                            del map_screen.nation_data["FACTION_WAR_MAPS"][fac][old_owner]
                            
                # 3. Finally delete from nation_data
                del map_screen.nation_data[old_owner]

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