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

async def save_map_data(self, save_name=None):
    """Saves logical data and visual state. Runs as a background coroutine (see
    data.platform.run_background) so a 'Saving...' screen can be shown instead
    of freezing the window while a large history.json/images are written."""
    try:
        queries.scrub_default_images(self.nation_data)

        if not save_name:
            save_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # --- CONDITIONAL PATH LOGIC ---
        if self.is_editor:
            # Standardize Map Editor Exports to the custom scenarios directory
            save_path = os.path.join(c.SCENARIOS_CUSTOM_DIR, f"MapExport_{save_name}")
        else:
            # Standard Game Save
            save_path = os.path.join(c.SAVES_DIR, save_name)

        if not os.path.exists(save_path):
            os.makedirs(save_path)

        # 1. Consolidated Data Structure
        # map_data.json now carries the full current province state. Keep the
        # separate meta.json province block only in multiplayer snapshots.
        save_dict = queries.build_save_dict(self, include_provinces=False)
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

        if not self.is_editor:
            # Web only: mirror the new save into IndexedDB so it survives closing
            # the tab (pygbag's in-memory FS otherwise loses it). No-op on desktop.
            sync_persisted_dir(c.SAVES_DIR)

        self.show_feedback(f"Exported: {save_name} to {save_path}" if self.is_editor else f"Saved: {save_name} to {save_path}")
    except Exception as e:
        print(f"SAVE FAILED:\n{traceback.format_exc()}")
        self.show_feedback(f"Save failed: {e}")
    finally:
        self.is_saving = False
