import pygame
import numpy as np
import data.constants as c
from data import queries
from ui.rendering import province_pixels

# Lakes and seas render the same color as oceans on political maps
VISUAL_WATER_MAPPING = {
    "ocean": "Ocean", 
    "coastal_sea": "Ocean", 
    "inland_sea": "Ocean", 
    "lakes": "Ocean"
}

# Brightness applied to each shading band, indexed by the level ids assigned in
# _shading_levels: 0 unshaded, then edge_1, edge_3, edge_4, interior.
_SHADE_FACTORS = (1.0, 0.7, 0.8, 0.6, 0.4)

# Pre-multiplying every possible channel value turns the shading pass into one
# gather instead of a masked read-multiply-write per band. Built with the same
# float expression the per-band version used, so the output is bit-identical.
_SHADE_LUT = np.stack([(np.arange(256) * f).astype(np.uint8) for f in _SHADE_FACTORS])

# The four one-pixel neighbors, as np.roll arguments. np.roll wraps at the map
# edge, and the shading has always wrapped with it.
_NEIGHBOR_SHIFTS = ((1, 1), (-1, 1), (1, 0), (-1, 0))

# How far a change of owner can reach through the shading. The gap fill makes
# two rounds of one-pixel copies in each direction, so a pixel's filled owner
# comes from at most 2 pixels away. Each of the four edge bands then looks one
# pixel further than the band before it.
_GAP_FILL_REACH = 2
_EDGE_BAND_REACH = 4


def _roll_into(array, shift, axis, out):
    """np.roll(array, shift, axis) for a one-pixel shift, written into out.

    The shading pass rolls whole-map arrays two dozen times; reusing one buffer
    instead of allocating a fresh copy each time is most of what makes it fast.
    """
    source = np.moveaxis(array, axis, 0)
    target = np.moveaxis(out, axis, 0)
    if shift == 1:
        target[1:] = source[:-1]
        target[:1] = source[-1:]
    else:
        target[:-1] = source[1:]
        target[-1:] = source[:1]
    return out


def _fill_gaps(slots, is_gap_slot, gap):
    """Bridge the black gaps between provinces so internal borders are ignored.

    Works on id-map slots rather than owners: a gap is a pixel whose color no
    province uses, and a pixel's filled owner is always the owner of the slot
    copied into it. So the fill depends only on the id map and which colors are
    provinces, and every layer that shares both can share one fill.
    """
    filled = np.where(is_gap_slot[slots], slots.dtype.type(gap), slots)
    shifted = np.empty_like(filled)
    is_gap = np.empty(filled.shape, dtype=bool)
    for _ in range(2):
        for shift, axis in _NEIGHBOR_SHIFTS:
            np.equal(filled, gap, out=is_gap)
            np.copyto(filled, _roll_into(filled, shift, axis, shifted), where=is_gap)
    return filled


def _shading_levels(owner_2d, is_land):
    """Works out which shading band every pixel falls in.

    owner_2d is each pixel's gap-filled owner. The bands depend only on how
    pixels are grouped by owner, never on the colors drawn on top -- which is
    what lets _build_map_surface reuse one result across the map modes that
    group tiles the same way. Water and unclaimed land are never shaded.
    """
    shifted = np.empty_like(owner_2d)
    differs = np.empty(owner_2d.shape, dtype=bool)
    edge_1 = np.zeros(owner_2d.shape, dtype=bool)
    for shift, axis in _NEIGHBOR_SHIFTS:
        np.not_equal(owner_2d, _roll_into(owner_2d, shift, axis, shifted), out=differs)
        edge_1 |= differs
    edge_1 &= is_land

    # Each later band is the land touching the band before it that no earlier
    # band has claimed, so the bands are mutually exclusive by construction.
    remaining = is_land & ~edge_1
    bands = [edge_1]
    touching = np.empty(owner_2d.shape, dtype=bool)
    for _ in range(3):
        touching.fill(False)
        for shift, axis in _NEIGHBOR_SHIFTS:
            touching |= _roll_into(bands[-1], shift, axis, differs)
        band = remaining & touching
        remaining &= ~band
        bands.append(band)
    edge_1, edge_2, edge_3, edge_4 = bands

    # Each pixel records the row of the brightness table it belongs to.
    # edge_2 keeps level 0 (100% brightness)
    level = np.zeros(owner_2d.shape, dtype=np.uint8)
    np.copyto(level, 1, where=edge_1)
    np.copyto(level, 2, where=edge_3)
    np.copyto(level, 3, where=edge_4)
    np.copyto(level, 4, where=remaining)
    return level


# Every layer over the same provinces shares one gap fill, so keep the last.
_FILLED = None


def _filled_slots(pixels, is_gap_slot):
    global _FILLED
    key = is_gap_slot.tobytes()
    if _FILLED is None or _FILLED[0] is not pixels or _FILLED[1] != key:
        _FILLED = (pixels, key, _fill_gaps(pixels.slots, is_gap_slot, pixels.slot_count))
    return _FILLED[2]


class _Layout:
    """One way of grouping provinces by owner, as a layer build resolved it.

    `owners` lists each input's owner, aligned with `color_keys`. Owners alone
    decide the shading: which pixels share an owner, and which owners are water
    or unclaimed. So two layouts over the same provinces differ in shading only
    near the provinces whose owner differs.
    """

    def __init__(self, pixels, inputs, slot_owner, slot_land):
        self.pixels = pixels
        self.color_keys = tuple(row[0] for row in inputs)
        self.owners = tuple(row[1] for row in inputs)
        self.slot_owner = slot_owner
        self.slot_land = slot_land
        self.is_gap_slot = slot_owner[:pixels.slot_count] == 0

    def filled(self):
        return _filled_slots(self.pixels, self.is_gap_slot)

    def full_levels(self):
        filled = self.filled()
        return _shading_levels(self.slot_owner[filled], self.slot_land[filled])

    def patched_levels(self, base):
        """These levels, recomputed only around provinces that changed owner.

        `base` is a cached (_Layout, levels) over the same provinces. Returns
        None when the changes cover too much of the map for a patch to save
        time. A pixel's level depends on owners within
        _GAP_FILL_REACH + _EDGE_BAND_REACH pixels, so only pixels that close to
        a changed province can change, and recomputing each of those windows
        with _EDGE_BAND_REACH pixels of margin reproduces the full pass exactly.
        """
        base_layout, base_levels = base
        width, height = base_levels.shape
        changed = (index for index, (old, new) in enumerate(zip(base_layout.owners, self.owners))
                   if old != new)
        reach = _GAP_FILL_REACH + _EDGE_BAND_REACH
        margin = reach + _EDGE_BAND_REACH
        windows = []
        area = 0
        for index in changed:
            slot = self.pixels.slot_for(self.color_keys[index])
            if slot is None:
                continue
            x0, x1, y0, y1 = self.pixels.bounds_of(slot)
            if x1 - x0 + 2 * margin > width or y1 - y0 + 2 * margin > height:
                return None
            windows.append((x0, x1, y0, y1))
            area += (x1 - x0 + 2 * margin) * (y1 - y0 + 2 * margin)
            if area > width * height * _PATCH_AREA_LIMIT:
                return None

        filled = self.filled()
        levels = base_levels.copy()
        trim = slice(_EDGE_BAND_REACH, -_EDGE_BAND_REACH)
        for x0, x1, y0, y1 in windows:
            # mode="wrap" matches the wrap-around of the full pass at map edges.
            xs = np.arange(x0 - margin, x1 + margin)
            ys = np.arange(y0 - margin, y1 + margin)
            window = filled.take(xs, axis=0, mode="wrap").take(ys, axis=1, mode="wrap")
            patch = _shading_levels(self.slot_owner[window], self.slot_land[window])
            levels[np.ix_(xs[trim] % width, ys[trim] % height)] = patch[trim, trim]
        return levels


# The edge sweep above is the most expensive part of a rebuild, and several map
# modes group tiles identically -- political, relations and factions all key off
# the raw province owner. Caching by that grouping runs the sweep once per
# distinct layout per turn instead of once per map mode. The key names every
# province's owner, so a cache hit cannot describe a different world.
#
# A miss is usually last turn's layout with a few provinces changed hands, so
# the cache keeps its oldest entries until it is full rather than clearing, and
# a miss patches the closest entry instead of sweeping the whole map again.
_LEVEL_CACHE = {}
_LEVEL_CACHE_PIXELS = None
# Political, cores and faction territories are each rebuilt every turn, and
# each must still find its previous turn's entry, with room for a preview.
_LEVEL_CACHE_LIMIT = 6
# Patching beyond this share of the map costs about as much as a full sweep.
_PATCH_AREA_LIMIT = 0.25


def _cached_shading_levels(layout, layout_key):
    global _LEVEL_CACHE_PIXELS
    if _LEVEL_CACHE_PIXELS is not layout.pixels:
        _LEVEL_CACHE.clear()
        _LEVEL_CACHE_PIXELS = layout.pixels

    entry = _LEVEL_CACHE.pop(layout_key, None)
    if entry is None:
        levels = None
        candidates = [cached for cached in _LEVEL_CACHE.values()
                      if cached[0].color_keys == layout.color_keys]
        if candidates:
            closest = min(candidates, key=lambda cached: sum(
                old != new for old, new in zip(cached[0].owners, layout.owners)))
            levels = layout.patched_levels(closest)
        if levels is None:
            levels = layout.full_levels()
        entry = (layout, levels)
        if len(_LEVEL_CACHE) >= _LEVEL_CACHE_LIMIT:
            del _LEVEL_CACHE[next(iter(_LEVEL_CACHE))]
    # Most recently used last, so eviction drops the least recently used.
    _LEVEL_CACHE[layout_key] = entry
    return entry[1]


def invalidate_map_surface_cache(map_screen, *attrs):
    """Invalidate incrementally painted layers, or force a complete rebuild.

    Incremental editor/capture painting mutates a cached surface's pixels, so
    input comparison alone cannot certify that surface on its next refresh.
    With no attrs this also drops geometry shading and the id map's pixel
    index for the manual Refresh Maps action, including externally edited map
    assets.
    """
    global _FILLED
    # Optional for editor/test screens that have not rendered a layer yet.
    cache = map_screen._map_surface_cache
    if cache is not None:
        if attrs:
            for attr in attrs:
                cache.pop(attr, None)
        else:
            cache.clear()
    if not attrs or "fog_map" in attrs:
        map_screen._fog_surface_cache = None
    if not attrs:
        _LEVEL_CACHE.clear()
        _FILLED = None
        province_pixels.clear()


def _map_surface_inputs(map_screen, get_owner_and_color):
    """Resolve the exact grouping and color inputs at a state boundary.

    Keys include province colors and iteration order as well as their resolved
    owners/colors. This follows each mode's real color rule, so changes to cores,
    leaders, relations, perspective or pre-war borders cannot miss invalidation.
    No rule queries or map sweeps are added to frame rendering.
    """
    inputs = []
    for color_key, data in map_screen.map_data.items():
        terrain_type = data.get("terrain", "plains")

        if terrain_type in VISUAL_WATER_MAPPING:
            owner = VISUAL_WATER_MAPPING[terrain_type]
            color = c.COLOR_CHROMA_PINK
        else:
            owner, color = get_owner_and_color(data)

            # THE FIX: Properly indent the colorkey collision check so it ONLY runs on land!
            if tuple(color) == c.COLOR_CHROMA_PINK:
                color = (254, 0, 255)

        inputs.append((color_key, owner, tuple(color)))
    return tuple(inputs)


def _build_map_surface(map_screen, get_owner_and_color, inputs=None):
    """Unified helper to build NumPy map surfaces to prevent array calculation duplication."""
    if inputs is None:
        inputs = _map_surface_inputs(map_screen, get_owner_and_color)
    pixels = province_pixels.for_id_map(map_screen.id_map)
    slot_count = pixels.slot_count

    # One entry per id-map color. Colors no province uses stay owner 0 and
    # black, and so does the extra last entry the gap fill uses as its marker.
    owner_to_int = {}
    owner_seq = []
    slot_owner = np.zeros(slot_count + 1, dtype=np.uint32)
    slot_color = np.zeros((slot_count, 3), dtype=np.uint8)
    for color_key, owner, color in inputs:
        if owner not in owner_to_int:
            owner_to_int[owner] = len(owner_to_int) + 1
        owner_seq.append(owner_to_int[owner])
        slot = pixels.slot_for(color_key)
        if slot is not None:
            slot_owner[slot] = owner_to_int[owner]
            slot_color[slot] = color

    # Process Shading
    water_ids = [owner_to_int.get("Ocean", -1), owner_to_int.get("Lakes", -1), owner_to_int.get("Unclaimed", -1)]
    owner_is_land = np.ones(len(owner_to_int) + 1, dtype=bool)
    owner_is_land[0] = False
    owner_is_land[[owner_id for owner_id in water_ids if owner_id > 0]] = False
    if len(owner_to_int) < np.iinfo(np.uint16).max:
        # Half the memory traffic for every comparison in the shading pass.
        slot_owner = slot_owner.astype(np.uint16)
    layout = _Layout(pixels, inputs, slot_owner, owner_is_land[slot_owner])
    layout_key = (tuple((row[0], owner) for row, owner in zip(inputs, owner_seq)),
                  tuple(water_ids))
    level = _cached_shading_levels(layout, layout_key)

    # Each slot's color at every brightness, as the screen's own pixel values,
    # read back with one lookup per pixel.
    new_surf = pygame.Surface(map_screen.id_map.get_size())
    shaded = _SHADE_LUT[:, slot_color].reshape(-1, 1, 3)
    mapped = pygame.surfarray.map_array(new_surf, shaded).ravel()
    index = level.astype(np.uint32)
    index *= slot_count
    index += pixels.slots
    pygame.surfarray.blit_array(new_surf, mapped[index])

    # Now that the water is actually (255, 0, 255), this will punch out the transparency mask.
    new_surf.set_colorkey(c.COLOR_CHROMA_PINK)

    return new_surf

#: Color for a tile nobody owns, in every map mode that draws one.
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
    inputs = _map_surface_inputs(map_screen, get_data)
    # Screen-local, bounded to one surface per mode. Lightweight screen doubles
    # and callers outside Map.__init__ can initialize this cache on first use.
    cache = map_screen._map_surface_cache
    if cache is None:
        cache = map_screen._map_surface_cache = {}
    cached = cache.get(attr)
    if (cached is not None and cached[0] is map_screen.id_map and cached[1] == inputs
            and getattr(map_screen, attr, None) is cached[2]):
        surface = cached[2]
    else:
        surface = _build_map_surface(map_screen, get_data, inputs=inputs)
        cache[attr] = (map_screen.id_map, inputs, surface)
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

#: The viewpoint country's own land on the relations map.
RELATIONS_VIEWPOINT_COLOR = (0, 0, 255)


def _relations_colors(map_screen, viewpoint):
    """get_data for the relations map: every country colored by its score toward viewpoint."""
    # The score depends only on who owns the tile, so score each owner once,
    # and all of them in one walk over the provinces.
    rated = {data.get("owner", "Unclaimed") for data in map_screen.map_data.values()
             if data.get("terrain", "plains") not in VISUAL_WATER_MAPPING}
    rated.difference_update(c.UNOWNED_LAND_OWNERS)
    rated.discard(viewpoint)
    scores = queries.get_relation_scores_toward(
        viewpoint, rated, map_screen.nation_data, map_screen.id_to_province)

    def get_data(data):
        owner = data.get("owner", "Unclaimed")
        if owner in c.UNOWNED_LAND_OWNERS:
            color = UNOWNED_COLOR
        elif owner == viewpoint:
            color = RELATIONS_VIEWPOINT_COLOR
        else:
            color = queries.get_relation_color(scores[owner])
        return owner, color
    return get_data


def refresh_relations_map(map_screen):
    """Rebuilds the relations map surface instantly using a NumPy LUT."""
    _refresh_mode(map_screen, "Relations", "relations_map", "RELATIONS",
                  _relations_colors(map_screen, map_screen.player_country))
    # A chosen country's view was built from the state before this refresh.
    # Rebuild it while that country still owns land and the same player is
    # looking; otherwise return to the player's own view.
    view = map_screen._relations_view
    map_screen._relations_view = None
    if view is not None and view[0] == map_screen.player_country:
        _show_relations_view(map_screen, view[1])


# Right-clicking a country in the Relations view shows the map as that country
# sees everyone, until the player right-clicks elsewhere or changes map layer.
# _relations_view holds (player who chose it, chosen country, surface).


def relations_viewpoint_for(map_screen, province):
    """The country a right-click on this province chooses, or None for the player's own view.

    Water, unowned land, unplayable owners, the player's own land and no
    province at all choose the player's view.
    """
    if province is None or queries.is_water_province(province):
        return None
    owner = province.get("owner", "Unclaimed")
    if (owner == map_screen.player_country or owner in c.UNOWNED_LAND_OWNERS
            or owner in c.UNPLAYABLE_NATIONS or owner not in map_screen.nation_data):
        return None
    return owner


def _show_relations_view(map_screen, viewpoint):
    owns_land = any(data.get("owner") == viewpoint for data in map_screen.map_data.values()
                    if data.get("terrain", "plains") not in VISUAL_WATER_MAPPING)
    if not owns_land:
        return
    surface = _build_map_surface(map_screen, _relations_colors(map_screen, viewpoint))
    map_screen._relations_view = (map_screen.player_country, viewpoint, surface)


def choose_relations_viewpoint(map_screen, province):
    """Shows the relations map from the right-clicked province's country.

    Called from input handling, never from drawing.
    """
    viewpoint = relations_viewpoint_for(map_screen, province)
    if viewpoint is None:
        map_screen._relations_view = None
    elif viewpoint != shown_relations_viewpoint(map_screen):
        _show_relations_view(map_screen, viewpoint)


def _showing_player_relations(map_screen):
    # Screens that swap another surface in for their own draw keep map_mode,
    # so check the surface itself.
    return (map_screen.map_mode == "RELATIONS"
            and map_screen.active_map is map_screen.relations_map)


def shown_relations_viewpoint(map_screen):
    """The other country whose relations view is on screen, or None for the player's."""
    if not _showing_player_relations(map_screen):
        return None
    view = map_screen._relations_view
    if view is None or view[0] != map_screen.player_country:
        return None
    return view[1]


def shown_base_map(map_screen):
    """The surface the renderer draws as the map: the active map, or a chosen relations view."""
    if shown_relations_viewpoint(map_screen) is None:
        return map_screen.active_map
    return map_screen._relations_view[2]

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
            # Membership cannot change while collecting this layer's inputs.
            # Resolve leaders once per faction, not once per province, even
            # when unchanged pixels let the whole surface be reused.
            if fac not in faction_colors:
                leader = queries.get_faction_leader(fac, map_screen.nation_data)
                faction_colors[fac] = (map_screen.nation_colors[leader]
                                      if leader and leader in map_screen.nation_colors
                                      else get_faction_color(fac))
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


def build_deal_preview_map(map_screen, parties, transfers, baseline=None):
    """The map as a treaty would leave it, with only its signatories colored in.

    Returns a surface; unlike its neighbours it is not cached on the map screen,
    because it belongs to one open screen and one particular set of terms.

    The projected map used to be blobs -- an ellipse drawn over the ordinary
    political map for each province that changed hands. On a world map that is a
    scattering of dots among two hundred countries painted exactly as they always
    are, which tells you where a treaty bites but nothing about who it is
    between. This is the Faction Territories treatment instead: the parties in
    their own colors, everyone else flattened to grey, and the provinces the
    treaty moves already painted in the color of whoever is about to own them.

    `transfers` is deal.tile_transfers -- the same dict deal_effects acts on --
    and `baseline` is deal.baseline_owners, the map underneath it if the treaty
    named no land at all. Together they are exactly what execution does, so the
    picture and the outcome cannot disagree. Drawn over the *live* map instead,
    a peace with no demands looked like the front line rather than like the
    pre-war borders it actually restores, which is the one thing a player needs
    to see before deciding what to demand.
    """
    parties = set(parties)

    def get_data(data):
        prov_id = int(data["id"])
        owner = transfers.get(prov_id)
        if owner is None and baseline is not None:
            owner = baseline.get(prov_id)
        if owner is None:
            owner = data.get("owner", "Unclaimed")

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
    if not queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, map_screen.scenario_settings) or map_screen.selection_mode:
        map_screen.fog_map = None
        map_screen.visible_provinces = None
        map_screen.partial_visible_provinces = None
        return

    # --- THE FIX: Blanket the entire map in fog during the AI viewing phase in multiplayer ---
    # Prevents hotseat players from seeing Player 1's vision before the next turn starts
    is_multiplayer = len(map_screen.active_players) > 1
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

    fog_strength = map_screen.scenario_settings.get("fog_of_war_strength", c.DEFAULT_FOG_OF_WAR_STRENGTH)
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

    # Vision above must still be evaluated and published at every boundary,
    # including hotseat handoffs and client projections. Only the unchanged
    # pixel surface is reused; visibility is never inferred from a cache hit.
    inputs = []
    for color_key, data in map_screen.map_data.items():
        p_id = data["id"]
        alpha = c.FOG_OF_WAR_ALPHA
        if p_id in map_screen.visible_provinces:
            alpha = 0 # 0 Alpha = Completely visible
        elif p_id in map_screen.partial_visible_provinces:
            alpha = c.FOG_OF_WAR_ALPHA // 2 # Slightly darker for radius 2
        else:
            if fog_strength == "lite":
                alpha = c.FOG_OF_WAR_ALPHA // 2
            elif fog_strength == "extreme" and p_id in extreme_hidden:
                alpha = 255
            # else remains c.FOG_OF_WAR_ALPHA
        inputs.append((color_key, alpha))

    inputs = tuple(inputs)
    # Optional for lightweight screen doubles; Map owns the live cache.
    cached = map_screen._fog_surface_cache
    if cached is not None and cached[0] is map_screen.id_map and cached[1] == inputs:
        map_screen.fog_map = cached[2]
        return

    # Colors no province uses stay fully fogged.
    pixels = province_pixels.for_id_map(map_screen.id_map)
    slot_alpha = np.full(pixels.slot_count, c.FOG_OF_WAR_ALPHA, dtype=np.uint8)
    for color_key, alpha in inputs:
        slot = pixels.slot_for(color_key)
        if slot is not None:
            slot_alpha[slot] = alpha
    alpha_2d = slot_alpha[pixels.slots]

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
    map_screen._fog_surface_cache = (map_screen.id_map, inputs, fog_surf)
    print(f"Fog map refreshed in {pygame.time.get_ticks() - timer} ms")
