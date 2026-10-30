"""ZIP extraction, research-project construction, and country appearance helpers."""

import copy
import data.constants as c
import os
import shutil
import zipfile
from data.queries.tech import get_tech_requirements
from data import queries


def extract_and_flatten_zip(zip_path, extract_target_dir):
    """
    Extracts a zip file and flattens it if the archiver created a redundant root directory.
    This fixes the issue where importing a map/mod creates folder/folder/data.json.
    """
    # Ensure the target directory exists before unpacking
    os.makedirs(extract_target_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_target_dir)

    # Remove macOS junk folder which often breaks the single directory check
    macosx_path = os.path.join(extract_target_dir, "__MACOSX")
    if os.path.exists(macosx_path):
        shutil.rmtree(macosx_path)

    # Filter out OS junk files (like .DS_Store on Mac) to see if there's only one REAL item
    valid_items = [item for item in os.listdir(extract_target_dir) if not item.startswith('.')]

    # If the only valid item extracted is a single directory, it's been nested. Let's flatten it.
    if len(valid_items) == 1:
        single_folder_path = os.path.join(extract_target_dir, valid_items[0])
        
        if os.path.isdir(single_folder_path):
            # Move all internal contents up one level into the target directory
            for item in os.listdir(single_folder_path):
                shutil.move(os.path.join(single_folder_path, item), extract_target_dir)
            
            # Clean up the now-empty redundant folder
            try:
                os.rmdir(single_folder_path)
            except OSError:
                shutil.rmtree(single_folder_path)
    else:
        # Fallback: If there are multiple items but map_data.json is hiding inside a subdirectory
        if not os.path.exists(os.path.join(extract_target_dir, "map_data.json")):
            for item in valid_items:
                potential_path = os.path.join(extract_target_dir, item)
                if os.path.isdir(potential_path) and os.path.exists(os.path.join(potential_path, "map_data.json")):
                    # Found the true map folder, flatten it!
                    for sub_item in os.listdir(potential_path):
                        shutil.move(os.path.join(potential_path, sub_item), extract_target_dir)
                    
                    try:
                        os.rmdir(potential_path)
                    except OSError:
                        shutil.rmtree(potential_path) # Fallback if hidden files got left behind
                    break


MAX_UNIT_ORDER_PATH = 200


def build_research_project(tech_name, points_remaining):
    """Construct the current project schema without changing progress policy."""
    return {"tech_name": tech_name, "points_remaining": points_remaining}


def canonical_research_selection(country_data, requested, tech_tree=None, *, context=None):
    """Preview an ordered selection using authoritative progress and prerequisites."""
    if (not isinstance(requested, list) or len(requested) > c.RESEARCH_SLOTS or
            any(not isinstance(tech, str) for tech in requested) or
            len(set(requested)) != len(requested)):
        raise ValueError("Invalid research selection.")
    if not isinstance(country_data, dict):
        raise ValueError("Unknown country research selection.")
    tech_tree = queries.get_tech_tree(context) if tech_tree is None else tech_tree
    research = country_data.get("research", {})
    if not isinstance(research, dict):
        raise ValueError("Invalid authoritative research data.")
    current_queue = country_data.get("research_queue", [])
    if not isinstance(current_queue, list):
        raise ValueError("Invalid authoritative research queue.")
    running = {project.get("tech_name"): project for project in current_queue
               if isinstance(project, dict) and isinstance(project.get("tech_name"), str)}
    progress = copy.deepcopy(country_data.get("research_progress", {}))
    if not isinstance(progress, dict):
        progress = {}

    # Paused projects retain the authoritative remaining point total.
    for tech_name, project in running.items():
        if tech_name not in requested:
            remaining = project.get("points_remaining", tech_tree.get(tech_name, {}).get("cost", 0))
            if isinstance(remaining, (int, float)) and remaining >= 0:
                progress[tech_name] = remaining

    canonical_projects = []
    for tech_name in requested:
        tech = tech_tree.get(tech_name)
        if not isinstance(tech, dict):
            raise ValueError("Unknown research technology.")
        if tech_name in running:
            # Keep the server's project object and progress, never the
            # similarly shaped value supplied by a client.
            project = copy.deepcopy(running[tech_name])
        else:
            current_level = research.get(tech_name, 0)
            if not isinstance(current_level, int) or current_level < 0:
                raise ValueError("Invalid research level.")
            if current_level >= tech.get("max_lvl", 0):
                raise ValueError("That research is already complete.")
            if not queries.check_tech_requirements(research, get_tech_requirements(tech, current_level + 1), current_level + 1):
                raise ValueError("Research requirements are not met.")
            cost = tech.get("cost")
            if not isinstance(cost, (int, float)) or cost <= 0:
                raise ValueError("Invalid research technology.")
            remaining = progress.pop(tech_name, cost)
            if not isinstance(remaining, (int, float)) or remaining < 0:
                remaining = cost
            project = build_research_project(tech_name, remaining)
        progress.pop(tech_name, None)
        canonical_projects.append(project)
    return {"projects": canonical_projects,
            "research_progress": progress}


def apply_country_appearance(nation_data, country_id, appearance):
    """Apply identity fields after the caller validates its mode and authority."""
    if country_id not in nation_data or not isinstance(appearance, dict):
        raise ValueError("Invalid country appearance target or data.")
    if set(appearance) - set(c.COUNTRY_APPEARANCE_FIELDS):
        raise ValueError("Country appearance cannot change gameplay fields.")
    country = nation_data[country_id]
    changed = tuple(key for key, value in appearance.items() if country.get(key) != value)
    country.update(copy.deepcopy(appearance))
    return changed
