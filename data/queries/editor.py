"""Map editor paint regions and undo/redo state."""

import copy
import data.constants as c
from data.state_access import world_for


def get_editor_paint_region(province, id_to_province, mode):
    """Return connected land with the same owner or core set as the clicked tile."""
    if mode not in ("NATION", "CORE") or province.get("owner") in c.WATER_NATIONS:
        return []

    def tile_type(tile):
        return tile.get("owner") if mode == "NATION" else frozenset(tile.get("cores", []))

    source_type = tile_type(province)
    pending = [province]
    visited = {province["id"]}
    region = []
    while pending:
        current = pending.pop()
        region.append(current)
        for neighbor_id in current.get("neighbors", []):
            if neighbor_id in visited:
                continue
            visited.add(neighbor_id)
            neighbor = id_to_province.get(neighbor_id)
            if (neighbor is not None and neighbor.get("owner") not in c.WATER_NATIONS
                    and tile_type(neighbor) == source_type):
                pending.append(neighbor)
    return region


def _get_current_map_state(map_screen):
    world_state = world_for(map_screen)
    state = {}
    for color_key, prov in world_state.map_data.items():
        state[color_key] = {
            "owner": prov.get("owner"),
            "cores": copy.deepcopy(prov.get("cores", [])),
            "buildings": copy.deepcopy(prov.get("buildings", [])),
            "resources": copy.deepcopy(prov.get("resources", {})),
            "units": copy.deepcopy(prov.get("units", []))
        }
    return state


def _apply_map_state(map_screen, state):
    world_state = world_for(map_screen)
    for color_key, saved_prov in state.items():
        prov = world_state.map_data.get(color_key)
        if prov:
            prov["owner"] = saved_prov["owner"]
            prov["cores"] = copy.deepcopy(saved_prov["cores"])
            prov["buildings"] = copy.deepcopy(saved_prov["buildings"])
            prov["resources"] = copy.deepcopy(saved_prov["resources"])
            prov["units"] = copy.deepcopy(saved_prov["units"])
            
    # Apply the changes visually
    map_screen.refresh_all_maps()


def save_editor_state(map_screen):
    """Snapshots the current map data for the undo feature, clearing redo history."""
    # Any new physical edit destroys the active redo-timeline
    map_screen.editor_redo_history = []
        
    map_screen.editor_history.append(_get_current_map_state(map_screen))
    
    if len(map_screen.editor_history) > c.MAX_EDITOR_HISTORY:
        map_screen.editor_history.pop(0)


def restore_editor_state(map_screen):
    """Restores the last map state from the editor history (Undo)."""
    if not map_screen.editor_history:
        map_screen.show_feedback("Nothing to undo!")
        return
        
    # Save the current state to the redo stack before replacing it
    map_screen.editor_redo_history.append(_get_current_map_state(map_screen))
        
    last_state = map_screen.editor_history.pop()
    _apply_map_state(map_screen, last_state)
    map_screen.show_feedback("Undo Successful")


def redo_editor_state(map_screen):
    """Restores the next map state from the redo history (Redo)."""
    if not map_screen.editor_redo_history:
        map_screen.show_feedback("Nothing to redo!")
        return
        
    # Save the current state to the undo stack before replacing it
    map_screen.editor_history.append(_get_current_map_state(map_screen))
        
    next_state = map_screen.editor_redo_history.pop()
    _apply_map_state(map_screen, next_state)
    map_screen.show_feedback("Redo Successful")
