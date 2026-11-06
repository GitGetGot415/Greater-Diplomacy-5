import pygame
import os
import asyncio
import traceback
from datetime import datetime
import data.constants as c
from data import queries
from data.map import history_io
from data.map.map_cache import remove_optional_layer_files
from data.platform import sync_persisted_dir
from data.state_access import session_for


def editor_save_path(name):
    """Resolve a scenario folder inside the configured custom scenario directory."""
    name = queries.validated_scenario_name(name)
    if not name:
        raise ValueError("Choose a scenario name before resolving its folder.")
    root = os.path.realpath(c.SCENARIOS_CUSTOM_DIR)
    path = os.path.join(root, name)
    if os.path.commonpath((root, os.path.realpath(path))) != root:
        raise ValueError("The scenario folder must be inside the custom scenarios directory.")
    return path


async def save_map_data(self, save_name=None, *, overwrite=False, save_path=None):
    """Saves logical data and visual state. Runs as a background coroutine (see
    data.platform.run_background) so a 'Saving...' screen can be shown instead
    of freezing the window while a large history.json/images are written."""
    try:
        # --- CONDITIONAL PATH LOGIC ---
        if save_path is not None:
            # Only the UI's explicit destination choice bypasses the default roots.
            save_path = os.path.abspath(save_path)
            save_name = os.path.basename(save_path)
            if self.is_editor:
                queries.validated_scenario_name(save_name)
            os.makedirs(save_path, exist_ok=overwrite)
        elif self.is_editor:
            if not save_name:
                save_name = session_for(self).editor_scenario_name or (
                    "MapExport_" + datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
            save_path = editor_save_path(save_name)
            # Creating the directory here also rejects a collision after the UI check.
            os.makedirs(save_path, exist_ok=overwrite)
        else:
            # Standard Game Save
            if not save_name:
                save_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            save_path = os.path.join(c.SAVES_DIR, save_name)
            os.makedirs(save_path, exist_ok=True)

        queries.scrub_default_images(self.nation_data)

        # 1. Consolidated Data Structure
        # map_data.json now carries the full current province state. Keep the
        # separate meta.json province block only in multiplayer snapshots.
        save_dict = queries.build_save_dict(
            self, include_provinces=False, compact_nations=True, include_local_preferences=True)
        self.save_progress_completed = 1
        await asyncio.sleep(0)

        # Pretty JSON makes saves and scenario exports easy to inspect and diff.
        # The export path compresses these files with ZIP_DEFLATED, so the
        # whitespace has only a small effect on the exported archive size.
        with open(os.path.join(save_path, "meta.json"), "w") as f:
            f.write(history_io.dump_text(save_dict, indent=c.SAVE_INDENT))
        self.save_progress_completed = 2
        await asyncio.sleep(0)

        # Structural map and current province state, so the save is self-contained.
        with open(os.path.join(save_path, "map_data.json"), "w") as f:
            f.write(history_io.dump_text(
                queries.build_map_data_save(self), indent=c.SAVE_INDENT))
        self.save_progress_completed = 3
        await asyncio.sleep(0)

        # History
        if hasattr(self, 'history'):
            # Scrub images from history snapshots before writing (they were
            # skipped at snapshot time for speed). Each snapshot is scrubbed
            # once and flagged: the work is identical every time, and redoing
            # it for all 130 turns on every save was most of the save's cost.
            for turn_snap in self.history.values():
                nd = turn_snap.get("nation_data")
                if nd and not turn_snap.get(c.HISTORY_SCRUBBED_KEY):
                    queries.scrub_default_images(nd)
                    turn_snap[c.HISTORY_SCRUBBED_KEY] = True
            history_io.write(save_path, self.history)
        self.save_progress_completed = 4
        await asyncio.sleep(0)

        # Political and cores surfaces are derived from map/province data and
        # regenerated during Map initialization. Remove stale cache files when
        # overwriting an older save, and persist only the required map images.
        remove_optional_layer_files(save_path)
        pygame.image.save(self.terrain_map, os.path.join(save_path, "terrain.png"))
        pygame.image.save(self.id_map, os.path.join(save_path, "id_map.png"))
        self.save_progress_completed = 5

        # Web builds restore both saved games and custom scenarios at startup.
        sync_persisted_dir(c.SCENARIOS_CUSTOM_DIR if self.is_editor else c.SAVES_DIR)
        if self.is_editor:
            session_for(self).editor_scenario_name = os.path.basename(save_path)

        self.show_feedback(f"Exported: {save_name} to {save_path}" if self.is_editor else f"Saved: {save_name} to {save_path}")
        return save_path
    except Exception as e:
        print(f"SAVE FAILED:\n{traceback.format_exc()}")
        self.show_feedback(f"Save failed: {e}")
    finally:
        self.is_saving = False
