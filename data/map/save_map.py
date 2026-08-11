import json
import pygame
import os
import asyncio
import traceback
from datetime import datetime
import data.constants as c
from data import queries
from data.map import history_io
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
        save_dict = queries.build_save_dict(self)
        self.save_progress_completed = 1
        await asyncio.sleep(0)

        # Actual map data. json.dump writes through the text layer in many
        # small chunks; one buffered write of the same bytes is several times
        # faster, and history.json is large enough that it dominated the save.
        with open(os.path.join(save_path, "meta.json"), "w") as f:
            f.write(history_io.dump_text(save_dict, indent=c.SAVE_INDENT))
        self.save_progress_completed = 2
        await asyncio.sleep(0)

        # Raw structural geometry (so this save is completely self-contained)
        with open(os.path.join(save_path, "map_data.json"), "w") as f:
            f.write(history_io.dump_text(self.raw_json_data, indent=c.SAVE_INDENT))
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

        # Visual states
        pygame.image.save(self.political_map, os.path.join(save_path, "political.png"))
        pygame.image.save(self.terrain_map, os.path.join(save_path, "terrain.png"))
        pygame.image.save(self.id_map, os.path.join(save_path, "id_map.png"))
        pygame.image.save(self.cores_map, os.path.join(save_path, "cores.png"))
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
