import pygame
import numpy as np
import data.constants as c
from data import queries

# Brightness applied to each shading band, indexed by the level ids assigned in
# apply_border_shading: 0 unshaded, then edge_1, edge_3, edge_4, interior.
_SHADE_FACTORS = (1.0, 0.7, 0.8, 0.6, 0.4)

# Pre-multiplying every possible channel value turns the shading pass into one
# gather instead of a masked read-multiply-write per band. Built with the same
# float expression the per-band version used, so the output is bit-identical.
_SHADE_LUT = np.stack([(np.arange(256) * f).astype(np.uint8) for f in _SHADE_FACTORS])


def compute_shading_levels(owner_2d, water_ids):
    """Works out which shading band every pixel falls in.

    Depends only on how tiles are grouped by owner, never on the colours drawn
    on top -- which is what lets _build_map_surface reuse one result across the
    map modes that group tiles the same way.
    """
    # Bridge the black gaps on the OWNER array so internal province borders are ignored.
    filled_owner = np.copy(owner_2d)
    for _ in range(2): 
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, 1, axis=1)[is_gap]
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, -1, axis=1)[is_gap]
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, 1, axis=0)[is_gap]
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, -1, axis=0)[is_gap]

    # Identify water IDs and unclaimed IDs to exclude them from shading
    is_land = ~np.isin(filled_owner, water_ids) & (filled_owner != 0)

    # Shift arrays to look at neighboring owners
    shift_u = np.roll(filled_owner, 1, axis=1)
    shift_d = np.roll(filled_owner, -1, axis=1)
    shift_l = np.roll(filled_owner, 1, axis=0)
    shift_r = np.roll(filled_owner, -1, axis=0)

    # Calculate Edge Depths
    edge_1 = is_land & ((filled_owner != shift_u) | (filled_owner != shift_d) | \
                        (filled_owner != shift_l) | (filled_owner != shift_r))
    edge_2 = is_land & ~edge_1 & (np.roll(edge_1, 1, axis=1) | np.roll(edge_1, -1, axis=1) | \
                                  np.roll(edge_1, 1, axis=0) | np.roll(edge_1, -1, axis=0))
    edge_3 = is_land & ~edge_1 & ~edge_2 & (np.roll(edge_2, 1, axis=1) | np.roll(edge_2, -1, axis=1) | \
                                            np.roll(edge_2, 1, axis=0) | np.roll(edge_2, -1, axis=0))
    edge_4 = is_land & ~edge_1 & ~edge_2 & ~edge_3 & (np.roll(edge_3, 1, axis=1) | np.roll(edge_3, -1, axis=1) | \
                                                      np.roll(edge_3, 1, axis=0) | np.roll(edge_3, -1, axis=0))

    interior = is_land & ~edge_1 & ~edge_2 & ~edge_3 & ~edge_4

    # The bands are mutually exclusive by construction, so each pixel just
    # records the row of the brightness table it belongs to.
    # edge_2 keeps level 0 (100% brightness)
    level = np.zeros(owner_2d.shape, dtype=np.uint8)
    level[edge_1] = 1
    level[edge_3] = 2
    level[edge_4] = 3
    level[interior] = 4
    return level


def apply_border_shading(out_2d, owner_2d, id_array, water_ids):
    """
    Helper function that applies HoI4-style inner borders and gradient shading.
    Used by Political, Relations, and Cores maps.
    """
    return shade_packed_colors(out_2d, id_array.shape, compute_shading_levels(owner_2d, water_ids))


def shade_packed_colors(out_2d, shape_3d, level):
    """Unpacks packed RGB into channels and applies the shading band brightness."""
    out_3d = np.empty(shape_3d, dtype=np.uint8)
    out_3d[:, :, 0] = (out_2d >> 16) & 0xFF
    out_3d[:, :, 1] = (out_2d >> 8) & 0xFF
    out_3d[:, :, 2] = out_2d & 0xFF
    return _SHADE_LUT[level[:, :, None], out_3d]


# The edge sweep above is the most expensive part of a rebuild, and several map
# modes group tiles identically -- political, relations and factions all key off
# the raw province owner. Caching by that grouping runs the sweep once per
# distinct layout per turn instead of once per map mode. The key names every
# province's owner, so a cache hit cannot describe a different world.
_LEVEL_CACHE = {}
_LEVEL_CACHE_MAP = None
_LEVEL_CACHE_LIMIT = 4


def _cached_shading_levels(id_map, layout_key, build_owner_2d, water_ids):
    global _LEVEL_CACHE_MAP
    if _LEVEL_CACHE_MAP is not id_map:
        _LEVEL_CACHE.clear()
        _LEVEL_CACHE_MAP = id_map

    level = _LEVEL_CACHE.get(layout_key)
    if level is None:
        if len(_LEVEL_CACHE) >= _LEVEL_CACHE_LIMIT:
            _LEVEL_CACHE.clear()
        level = compute_shading_levels(build_owner_2d(), water_ids)
        _LEVEL_CACHE[layout_key] = level
    return level


def get_id_2d_array(id_map):
    """Helper to avoid duplicating the 3D-to-2D bitwise array extraction."""
    id_array = pygame.surfarray.pixels3d(id_map)
    id_2d = (id_array[:, :, 0].astype(np.uint32) << 16) | \
            (id_array[:, :, 1].astype(np.uint32) << 8) | \
             id_array[:, :, 2].astype(np.uint32)
    return id_array, id_2d


def _build_map_surface(map_screen, get_owner_and_color):
    """Unified helper to build NumPy map surfaces to prevent array calculation duplication."""
    id_array, id_2d = get_id_2d_array(map_screen.id_map)
    shape_3d = id_array.shape
    lut = np.zeros(16777216, dtype=np.uint32)
    owner_lut = np.zeros(16777216, dtype=np.uint32)
    owner_to_int = {}
    next_owner_id = 1
    owner_seq = []

    for color_key, data in map_screen.map_data.items():
        terrain_type = data.get("terrain", "plains")

        if terrain_type in c.VISUAL_WATER_MAPPING:
            owner = c.VISUAL_WATER_MAPPING[terrain_type]
            color = c.COLOR_CHROMA_PINK
        else:
            owner, color = get_owner_and_color(data)

            # THE FIX: Properly indent the colorkey collision check so it ONLY runs on land!
            if tuple(color) == c.COLOR_CHROMA_PINK:
                color = (254, 0, 255)

        if owner not in owner_to_int:
            owner_to_int[owner] = next_owner_id
            next_owner_id += 1

        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]

        lut[packed_key] = packed_color
        owner_lut[packed_key] = owner_to_int[owner]
        owner_seq.append(owner_to_int[owner])

    out_2d = lut[id_2d]

    # Process Shading
    water_ids = [owner_to_int.get("Ocean", -1), owner_to_int.get("Lakes", -1), owner_to_int.get("Unclaimed", -1)]
    layout_key = (tuple(owner_seq), tuple(water_ids))
    level = _cached_shading_levels(map_screen.id_map, layout_key, lambda: owner_lut[id_2d], water_ids)
    out_3d = shade_packed_colors(out_2d, shape_3d, level)

    new_surf = pygame.Surface(map_screen.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_surf, out_3d)
    
    # Now that the water is actually (255, 0, 255), this will punch out the transparency mask.
    new_surf.set_colorkey(c.COLOR_CHROMA_PINK) 
    
    return new_surf

#: Colour for a tile nobody owns, in every map mode that draws one.
UNOWNED_COLOR = (255, 255, 255)


def _refresh_mode(map_screen, label, attr, mode, get_data):
    """Builds one map-mode surface, stores it, and swaps it in if it's showing.

    Every refresh_*_map function below wrapped its own get_data in this same
    four steps -- time it, build it, `if map_screen.map_mode == "...":
    active_map = ...`, print the timing -- with only the attribute and the mode
    string changing, so adding a mode meant copying the wrapper again and
    remembering to change both strings.
    """
    timer = pygame.time.get_ticks()
    surface = _build_map_surface(map_screen, get_data)
    setattr(map_screen, attr, surface)
    if map_screen.map_mode == mode:
        map_screen.active_map = surface
    print(f"{label} map refreshed in {pygame.time.get_ticks() - timer} ms")
    return surface


def refresh_political_map(map_screen):
    """Rebuilds the entire political map surface instantly using a NumPy LUT."""
    def get_data(data):
        owner = data.get("owner", "Unclaimed")
        return owner, map_screen.nation_colors.get(owner, UNOWNED_COLOR)

    _refresh_mode(map_screen, "Political", "political_map", "POLITICAL", get_data)

def refresh_relations_map(map_screen):
    """Rebuilds the relations map surface instantly using a NumPy LUT."""
    # Scoring a pair walks every province to tally claims, and the answer only
    # depends on who owns the tile -- so resolve it once per nation, not once
    # per tile.
    color_by_owner = {}

    def get_data(data):
        owner = data.get("owner", "Unclaimed")
        color = color_by_owner.get(owner)
        if color is None:
            if owner in c.UNOWNED_LAND_OWNERS:
                color = UNOWNED_COLOR
            elif owner == map_screen.player_country:
                color = (0, 0, 255)
            else:
                relation = queries.get_relation_score(owner, map_screen.player_country, map_screen.nation_data, map_screen.id_to_province)
                color = queries.get_relation_color(relation)
            color_by_owner[owner] = color
        return owner, color

    _refresh_mode(map_screen, "Relations", "relations_map", "RELATIONS", get_data)

def refresh_cores_map(map_screen):
    """Rebuilds the cores map surface instantly using a NumPy LUT."""
    def get_data(data):
        cores = data.get("cores", [])
        if not cores:
            owner = "Unclaimed"
            color = map_screen.nation_colors.get(owner, UNOWNED_COLOR)
        elif len(cores) == 1:
            owner = cores[0]
            color = map_screen.nation_colors.get(owner, UNOWNED_COLOR)
        else:
            owner = ",".join(sorted(cores)) 
            r = g = b = valid = 0
            for core_name in cores:
                c_color = map_screen.nation_colors.get(core_name)
                if c_color:
                    r += c_color[0]; g += c_color[1]; b += c_color[2]; valid += 1
            color = (r // valid, g // valid, b // valid) if valid > 0 else UNOWNED_COLOR
        return owner, color

    _refresh_mode(map_screen, "Cores", "cores_map", "CORES", get_data)

def refresh_factions_map(map_screen):
    """Rebuilds the factions map surface instantly using a NumPy LUT."""
    faction_colors = {}
    
    def get_faction_color(fac_name):
        h = sum(ord(c) * (i+1) for i, c in enumerate(fac_name))
        return ((h * 123) % 200 + 55, (h * 321) % 200 + 55, (h * 213) % 200 + 55)
        
    def get_data(data):
        owner = data.get("owner", "Unclaimed")
        fac = map_screen.nation_data.get(owner, {}).get("faction", "")
        
        if owner in c.UNOWNED_LAND_OWNERS:
            color = UNOWNED_COLOR
        elif not fac:
            color = (150, 150, 150) # Neutral grey for non-faction countries
        else:
            leader = queries.get_faction_leader(fac, map_screen.nation_data)
            if leader and leader in map_screen.nation_colors:
                faction_colors[fac] = map_screen.nation_colors[leader]
            elif fac not in faction_colors:
                faction_colors[fac] = get_faction_color(fac)
            color = faction_colors[fac]
        return owner, color
        
    _refresh_mode(map_screen, "Factions", "factions_map", "FACTIONS", get_data)

def refresh_faction_territories_map(map_screen):
    """Rebuilds the map showing pre-war faction borders, or current borders if at peace."""
    player_fac = map_screen.nation_data.get(map_screen.player_country, {}).get("faction", "")
    members = queries.get_faction_members(player_fac, map_screen.nation_data) if player_fac else []
    pre_war_map = map_screen.nation_data.get("FACTION_WAR_MAPS", {}).get(player_fac, {})
    is_at_war = bool(pre_war_map)
    
    def get_data(data):
        curr_owner = data.get("owner", "Unclaimed")
        
        if is_at_war:
            if str(data["id"]) in pre_war_map:
                owner = pre_war_map[str(data["id"])]
                color = map_screen.nation_colors.get(owner, UNOWNED_COLOR)
            else:
                if curr_owner in members:
                    possible_cores = [c for c in data.get("cores", []) if c not in members]
                    owner = possible_cores[0] if possible_cores else "Unclaimed"
                else:
                    owner = curr_owner
                color = UNOWNED_COLOR if owner in c.UNOWNED_LAND_OWNERS else (100, 100, 100)
        else:
            owner = curr_owner
            if owner in members:
                color = map_screen.nation_colors.get(owner, UNOWNED_COLOR)
            else:
                color = UNOWNED_COLOR if owner in c.UNOWNED_LAND_OWNERS else (100, 100, 100)

        return owner, color

    _refresh_mode(map_screen, "Faction Territories", "faction_territories_map",
                  "FACTION_TERRITORIES", get_data)

#: Everyone who is not party to the deal being previewed.
BYSTANDER_COLOR = (100, 100, 100)


def build_deal_preview_map(map_screen, parties, transfers):
    """The map as a treaty would leave it, with only its signatories coloured in.

    Returns a surface; unlike its neighbours it is not cached on the map screen,
    because it belongs to one open screen and one particular set of terms.

    The projected map used to be blobs -- an ellipse drawn over the ordinary
    political map for each province that changed hands. On a world map that is a
    scattering of dots among two hundred countries painted exactly as they always
    are, which tells you where a treaty bites but nothing about who it is
    between. This is the Faction Territories treatment instead: the parties in
    their own colours, everyone else flattened to grey, and the provinces the
    treaty moves already painted in the colour of whoever is about to own them.

    `transfers` is deal.tile_transfers -- the same dict deal_effects acts on, so
    the picture and the outcome cannot disagree.
    """
    parties = set(parties)

    def get_data(data):
        owner = transfers.get(int(data["id"])) or data.get("owner", "Unclaimed")
        if owner in parties:
            return owner, map_screen.nation_colors.get(owner, UNOWNED_COLOR)
        if owner in c.UNOWNED_LAND_OWNERS:
            return owner, UNOWNED_COLOR
        return owner, BYSTANDER_COLOR

    return _build_map_surface(map_screen, get_data)


def refresh_fog_map(map_screen):
    """Builds a semi-transparent fog surface to darken unseen provinces."""
    timer = pygame.time.get_ticks()
    
    # Turn off the fog entirely if disabled in constants OR if the player is currently selecting a country
    if not c.USE_FOG_OF_WAR or map_screen.selection_mode:
        map_screen.fog_map = None
        map_screen.visible_provinces = None
        map_screen.partial_visible_provinces = None
        return

    # --- THE FIX: Blanket the entire map in fog during the AI viewing phase in multiplayer ---
    # Prevents hotseat players from seeing Player 1's vision before the next turn starts
    is_multiplayer = hasattr(map_screen, 'active_players') and len(map_screen.active_players) > 1
    if map_screen.viewing_ai_moves and is_multiplayer:
        map_screen.visible_provinces = set() # Return an empty set so nothing is visible
        map_screen.partial_visible_provinces = set()
    else:
    # Dynamically fetch get_visible_provinces from queries
        vis_result = queries.get_visible_provinces(map_screen)
        if vis_result[0] is None:
            map_screen.fog_map = None
            map_screen.visible_provinces = None
            map_screen.partial_visible_provinces = None
            return
            
        map_screen.visible_provinces, map_screen.partial_visible_provinces = vis_result

    fog_strength = map_screen.scenario_settings.get("fog_of_war_strength", "normal") if hasattr(map_screen, 'scenario_settings') else "normal"
    extreme_hidden = set()
    
    if fog_strength == "extreme":
        for p_id, p_data in map_screen.id_to_province.items():
            if p_id not in map_screen.visible_provinces and p_id not in map_screen.partial_visible_provinces:
                # check neighbors
                neighbors = p_data.get("neighbors", [])
                is_extreme = True
                for n in neighbors:
                    if n in map_screen.visible_provinces or n in map_screen.partial_visible_provinces:
                        is_extreme = False
                        break
                if is_extreme:
                    extreme_hidden.add(p_id)
    map_screen.extreme_hidden_provinces = extreme_hidden

    id_array, id_2d = get_id_2d_array(map_screen.id_map)
    lut = np.full(16777216, c.FOG_OF_WAR_ALPHA, dtype=np.uint8)

    for color_key, data in map_screen.map_data.items():
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        p_id = data["id"]
        
        if p_id in map_screen.visible_provinces:
            lut[packed_key] = 0 # 0 Alpha = Completely visible
        elif p_id in map_screen.partial_visible_provinces:
            lut[packed_key] = c.FOG_OF_WAR_ALPHA // 2 # Slightly darker for radius 2
        else:
            if fog_strength == "lite":
                lut[packed_key] = c.FOG_OF_WAR_ALPHA // 2
            elif fog_strength == "extreme" and p_id in extreme_hidden:
                lut[packed_key] = 255
            # else remains c.FOG_OF_WAR_ALPHA
            
    alpha_2d = lut[id_2d]

    fog_surf = pygame.Surface(map_screen.id_map.get_size(), pygame.SRCALPHA)
    fog_surf.fill((0, 0, 0, 0)) # Base transparent layer
    
    # Lock alpha array to write NumPy output to it directly
    alpha_array = pygame.surfarray.pixels_alpha(fog_surf)
    np.copyto(alpha_array, alpha_2d)
    del alpha_array
    
    # Force RGB to black (so it applies a dark shadow instead of a white one)
    rgb_array = pygame.surfarray.pixels3d(fog_surf)
    rgb_array[...] = 0
    del rgb_array

    map_screen.fog_map = fog_surf
    print(f"Fog map refreshed in {pygame.time.get_ticks() - timer} ms")