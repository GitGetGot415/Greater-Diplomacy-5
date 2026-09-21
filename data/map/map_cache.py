"""Names and cleanup helpers for map layers derived from saved map state."""

import os


OPTIONAL_LAYER_FILES = {
    "political": "political.png",
    "cores": "cores.png",
}


def remove_optional_layer_files(map_path):
    """Remove cached overlays that are regenerated when a map is loaded."""
    for filename in OPTIONAL_LAYER_FILES.values():
        try:
            os.remove(os.path.join(map_path, filename))
        except FileNotFoundError:
            pass
