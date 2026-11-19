"""Province geometry and map/screen coordinate helpers."""

import data.constants as c
from data.state_access import world_for


# Sample a narrow seam in native map pixels, independent of zoom and tilt.
_COUNTRY_GAP_REACH = 2
_COUNTRY_GAP_AXES = ((1, 0), (0, 1), (1, 1), (1, -1))


def get_average_province_center(provinces, loop_map=False, map_width=None):
    """Return the geographic centre of provinces, including across a map seam."""
    centers = [province["center"] for province in provinces if province.get("center")]
    if not centers:
        return None
    average_y = sum(center[1] for center in centers) / len(centers)
    if not loop_map or not map_width:
        return (sum(center[0] for center in centers) / len(centers), average_y)

    anchor_x = centers[0][0]
    unwrapped_xs = []
    for center_x, _center_y in centers:
        delta_x = center_x - anchor_x
        if delta_x > map_width / 2:
            delta_x -= map_width
        elif delta_x < -map_width / 2:
            delta_x += map_width
        unwrapped_xs.append(anchor_x + delta_x)
    return (sum(unwrapped_xs) / len(unwrapped_xs) % map_width, average_y)


def get_country_map_center(country_id, map_data, loop_map=False, map_width=None):
    """Return a country's focus point, preferring its core territory.

    A country's geographic center is the average of the centers of every tile
    that lists it as a core.  Countries without core data fall back to their
    currently owned tiles.  On a looping map, calculate the horizontal average
    in the nearest wrapped space so territory on both map edges stays together.
    """
    core_tiles = [province for province in map_data.values()
                  if country_id in province.get("cores", []) and province.get("center")]
    tiles = core_tiles or [province for province in map_data.values()
                           if province.get("owner") == country_id and province.get("center")]
    return get_average_province_center(tiles, loop_map, map_width)


def is_water_province(province):
    """Shorthand to check if a province is a water tile."""
    return province.get("terrain") in c.WATER_TERRAINS


def borders_ocean(province, id_to_province):
    """Returns True if the province borders at least one non-lake water tile."""
    for n_id in province.get("neighbors", []):
        n_prov = id_to_province.get(n_id)
        if n_prov and n_prov.get("terrain") in c.OCEAN_TERRAINS:
            return True
    return False


def get_wrapped_x(x1, x2, map_w, loop_map):
    """Returns the modified x2 to account for shortest map wrap distance."""
    if loop_map:
        dx = x2 - x1
        if dx > map_w / 2: return x2 - map_w
        elif dx < -map_w / 2: return x2 + map_w
    return x2


def _province_at_pixel(id_map, map_data, x, y):
    color = id_map.get_at((x, y))
    return map_data.get((color.r, color.g, color.b))


def _province_along_gap(id_map, world_state, x, y, dx, dy, reach):
    for distance in range(1, reach + 1):
        sample_x, sample_y = x + dx * distance, y + dy * distance
        if world_state.loop_map:
            sample_x %= world_state.map_w
        if not (0 <= sample_x < world_state.map_w and 0 <= sample_y < world_state.map_h):
            break
        province = _province_at_pixel(id_map, world_state.map_data, sample_x, sample_y)
        if province is not None:
            return province
    return None


def _country_gap_province(id_map, world_state, x, y, is_visible):
    """Find a province for a gap bracketed by inspectable provinces of one country."""
    # Try adjacent pixels first. A nearby coast or border should not veto a
    # seam already bracketed by matching provinces on its immediate sides.
    for reach in range(1, _COUNTRY_GAP_REACH + 1):
        owner = anchor = None
        for dx, dy in _COUNTRY_GAP_AXES:
            before = _province_along_gap(id_map, world_state, x, y, -dx, -dy, reach)
            after = _province_along_gap(id_map, world_state, x, y, dx, dy, reach)
            for province in (before, after):
                if province is None:
                    continue
                candidate = province.get("owner")
                if (not candidate or candidate in c.OWNERLESS_OWNERS or is_water_province(province)
                        or (owner is not None and owner != candidate) or not is_visible(province)):
                    return None
                owner = candidate
            if anchor is None and before is not None and after is not None and before is not after:
                anchor = before
        if anchor is not None:
            return anchor
    return None


def get_clicked_province(mouse_pos, context, *, country_gap_is_visible=None):
    """Resolve a screen position, with a seam fallback for country targets that opt in."""
    world_state = world_for(context)
    mx, my = mouse_pos
    cam = context.camera
    wx = (mx / cam.zoom) + cam.pos.x
    if world_state.loop_map:
        wx %= world_state.map_w
    wy = ((my - context.top_ui_height) / (cam.zoom * cam.tilt_factor)) + cam.pos.y
    
    if 0 <= wy < world_state.map_h:
        safe_x = max(0, min(int(wx), world_state.map_w - 1))
        safe_y = max(0, min(int(wy), world_state.map_h - 1))
        province = _province_at_pixel(context.id_map, world_state.map_data, safe_x, safe_y)
        if province is None and country_gap_is_visible is not None and 0 <= wx < world_state.map_w:
            return _country_gap_province(context.id_map, world_state, safe_x, safe_y, country_gap_is_visible)
        return province
    return None


def world_to_screen(world_pos, context, offset=0):
    """Converts world map coordinates to screen pixel coordinates."""
    cam = context.camera
    sx = (world_pos[0] + offset - cam.pos.x) * cam.zoom
    sy = (world_pos[1] - cam.pos.y) * cam.zoom * cam.tilt_factor + context.top_ui_height
    return sx, sy
