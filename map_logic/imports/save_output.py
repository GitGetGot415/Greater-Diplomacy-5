"""Write the GD5 save folder produced by a legacy game import."""

import os
import shutil

import data.constants as c
from data import queries
from data.map import history_io
from data.platform import sync_persisted_dir


def write_imported_save(source_path, saves_dir, prefix, fallback_name, payload, raw_map, write_image):
    raw_map = queries.map_data_with_saved_provinces(raw_map, payload.pop("provinces"))
    queries.compact_save_nation_data(payload, raw_map)
    saves_dir = saves_dir or c.SAVES_DIR
    os.makedirs(saves_dir, exist_ok=True)
    destination = queries.import_destination_path(source_path, saves_dir, prefix, fallback_name)
    os.makedirs(destination)
    try:
        for name, data in (("meta.json", payload), ("map_data.json", raw_map)):
            with open(os.path.join(destination, name), "w", encoding="utf-8") as handle:
                handle.write(history_io.dump_compact_text(data))
        for name in ("terrain.png", "id_map.png"):
            write_image(name, os.path.join(destination, name))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    sync_persisted_dir(saves_dir)
    return destination
