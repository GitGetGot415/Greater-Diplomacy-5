"""Map editor paint regions, bulk setup changes, and undo/redo state."""

import copy
import data.constants as c
from data.state_access import world_for, session_for
from data import queries
from data.queries.unit_info import get_base_unit_name, units_with_air_cargo
from data.queries.units import apply_library_stats
from data.queries.saves import normalized_scenario_metadata
from data.queries.files import validated_scenario_name


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


def _get_current_map_state(context):
    world_state = world_for(context)
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


def _apply_map_state(context, state):
    world_state = world_for(context)
    for color_key, saved_prov in state.items():
        prov = world_state.map_data.get(color_key)
        if prov:
            prov["owner"] = saved_prov["owner"]
            prov["cores"] = copy.deepcopy(saved_prov["cores"])
            prov["buildings"] = copy.deepcopy(saved_prov["buildings"])
            prov["resources"] = copy.deepcopy(saved_prov["resources"])
            prov["units"] = copy.deepcopy(saved_prov["units"])
            
    # Apply the changes visually
    context.refresh_all_maps()


def save_editor_state(context):
    """Snapshots the current map data for the undo feature, clearing redo history."""
    # Any new physical edit destroys the active redo-timeline
    context.editor_redo_history = []
        
    context.editor_history.append(_get_current_map_state(context))
    
    if len(context.editor_history) > c.MAX_EDITOR_HISTORY:
        context.editor_history.pop(0)


def restore_editor_state(context):
    """Restores the last map state from the editor history (Undo)."""
    if not context.editor_history:
        context.show_feedback("Nothing to undo!")
        return
        
    # Save the current state to the redo stack before replacing it
    context.editor_redo_history.append(_get_current_map_state(context))
        
    last_state = context.editor_history.pop()
    _apply_map_state(context, last_state)
    context.show_feedback("Undo Successful")


def redo_editor_state(context):
    """Restores the next map state from the redo history (Redo)."""
    if not context.editor_redo_history:
        context.show_feedback("Nothing to redo!")
        return
        
    # Save the current state to the undo stack before replacing it
    context.editor_history.append(_get_current_map_state(context))
        
    next_state = context.editor_redo_history.pop()
    _apply_map_state(context, next_state)
    context.show_feedback("Redo Successful")


def can_bulk_edit_map(context):
    """Allow bulk setup changes only in an idle local map editor."""
    session = session_for(context)
    return bool(session.is_editor and not session.tactical_mode
                and not session.multiplayer_mode and not session.realtime_multiplayer
                and not session.ai_is_thinking and not session.viewing_ai_moves
                and not session.is_refreshing and not session.is_saving)


def set_editor_metadata(context, name, author, description):
    """Apply scenario information only in an idle local editor."""
    if not can_bulk_edit_map(context):
        raise ValueError("Metadata changes require an idle local map editor.")
    name = validated_scenario_name(name)
    metadata = normalized_scenario_metadata({"author": author, "description": description})
    world_for(context).scenario_metadata.update(metadata)
    session_for(context).editor_scenario_name = name


EDITOR_BUILDING_GROUPS = {
    "industry": "Factories",
    "recruitment": "Recruitment Centers",
    "fortification": "Forts",
}


def editor_building_targets(context, group):
    """Return one building group's active types in library order."""
    if group not in EDITOR_BUILDING_GROUPS:
        raise ValueError("Select factories, recruitment centers, or forts.")
    return [name for name, stats in queries.get_building_library(context).items()
            if stats.get("group") == group]


def set_editor_buildings(context, group, target):
    """Replace existing buildings in one group. Do not add buildings to other tiles."""
    if not can_bulk_edit_map(context):
        raise ValueError("Bulk changes require an idle local map editor.")
    building_types = set(editor_building_targets(context, group))
    if target not in building_types:
        raise ValueError("Select a building from the chosen group in the active building library.")
    changes = []
    for province in world_for(context).map_data.values():
        buildings = province.get("buildings", [])
        changes.extend((buildings, index) for index, name in enumerate(buildings)
                       if name in building_types and name != target)
    if changes:
        save_editor_state(context)
        for buildings, index in changes:
            buildings[index] = target
        context.queue_editor_visual_refresh()
    return len(changes)


def editor_unit_targets(context, mode, value):
    """Choose family equipment by year or one-based family level."""
    if mode not in ("year", "level") or type(value) is not int or value < 1:
        raise ValueError("Enter a positive whole year or family level.")
    library = queries.get_unit_library(context)
    tree = queries.get_tech_tree(context)
    families = {}
    for name in library:
        metadata = queries.get_unit_metadata(name, library, context=context)
        requirements = [metadata["research"]] + metadata["requirements"]
        years = []
        for requirement in requirements:
            if "year" in requirement or "minimum_year" in requirement:
                years.append(requirement.get("year", requirement.get("minimum_year")))
            else:
                timeline = tree.get(requirement["tech"], {}).get("years", [])
                level = requirement["level"]
                if 0 < level <= len(timeline):
                    years.append(timeline[level - 1])
        families.setdefault(metadata["family"], []).append(
            (metadata["tier_order"], name, max(years) if years else None))
    targets = {}
    for family, tiers in families.items():
        tiers.sort(key=lambda item: item[0])
        if mode == "level":
            targets[family] = tiers[min(value, len(tiers)) - 1][1]
        else:
            eligible = [item for item in tiers if item[2] is not None and item[2] <= value]
            if eligible:
                targets[family] = eligible[-1][1]
    return targets


def set_editor_units(context, mode, value):
    """Change placed equipment, including cargo, without changing unit identity."""
    if not can_bulk_edit_map(context):
        raise ValueError("Bulk changes require an idle local map editor.")
    library = queries.get_unit_library(context)
    targets = editor_unit_targets(context, mode, value)
    changes = []
    skipped = 0
    for province in world_for(context).map_data.values():
        for unit in units_with_air_cargo(province.get("units", [])):
            current = unit.get("original_type", unit.get("type"))
            if current not in library:
                skipped += 1
                continue
            family = get_base_unit_name(current, library, context=context)
            target = targets.get(family)
            if target is None:
                skipped += 1
            elif target != current:
                changes.append((unit, target))
    if changes:
        save_editor_state(context)
        for unit, target in changes:
            if "original_type" in unit:
                transport = unit["type"].split(" (", 1)[0]
                unit["original_type"] = target
                unit["type"] = f"{transport} ({target})"
            else:
                unit["type"] = target
            apply_library_stats(unit, library)
            unit["order"] = {}
        context.queue_editor_visual_refresh()
    return len(changes), skipped


def reset_editor_diplomacy(context):
    """Clear live diplomatic setup. Preserve territory, cores, and historical messages."""
    if not can_bulk_edit_map(context):
        raise ValueError("Bulk changes require an idle local map editor.")
    # Diplomacy imports queries during startup. Resolve its owners after initialization.
    from map_logic.diplomacy import diplomacy_lifecycle

    diplomacy_lifecycle.reset_editor_setup(context)
    # Map-only undo cannot restore diplomatic state or off-map volunteer placement.
    session_for(context).editor_history.clear()
    session_for(context).editor_redo_history.clear()
    context.refresh_diplomacy_maps()
