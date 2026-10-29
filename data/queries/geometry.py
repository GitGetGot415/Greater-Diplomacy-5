"""Province geometry and map/screen coordinate helpers."""

import data.constants as c
from data.state_access import world_for


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


def get_clicked_province(mouse_pos, map_screen):
    """Resolves the province dictionary corresponding to a screen click."""
    world_state = world_for(map_screen)
    mx, my = mouse_pos
    cam = map_screen.camera
    wx = (mx / cam.zoom) + cam.pos.x
    if world_state.loop_map:
        wx %= world_state.map_w
    wy = ((my - map_screen.top_ui_height) / (cam.zoom * cam.tilt_factor)) + cam.pos.y
    
    if 0 <= wy < world_state.map_h:
        safe_x = max(0, min(int(wx), world_state.map_w - 1))
        safe_y = max(0, min(int(wy), world_state.map_h - 1))
        color = map_screen.id_map.get_at((safe_x, safe_y))
        return world_state.map_data.get((color.r, color.g, color.b))
    return None


def world_to_screen(world_pos, map_screen, offset=0):
    """Converts world map coordinates to screen pixel coordinates."""
    cam = map_screen.camera
    sx = (world_pos[0] + offset - cam.pos.x) * cam.zoom
    sy = (world_pos[1] - cam.pos.y) * cam.zoom * cam.tilt_factor + map_screen.top_ui_height
    return sx, sy
