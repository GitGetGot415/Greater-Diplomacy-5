import os
from data.io import multiplayer_io
from data import queries
import data.constants as c
from ui.checkbox_list_screen import CheckboxItem


def load_multiplayer_moves(map_ref, tk_parent=None):
    """Multi-select move import. Returns True when files were actually loaded."""
    files = queries.open_file_browser(map_ref, "Select Move Files", c.TOURNAMENT_SAVES_DIR,
                                      mode="open_files", extensions=[".gd5move"], tk_parent=tk_parent)
    if not files:
        return False

    multiplayer_io.load_move_files(map_ref, files, getattr(map_ref, 'multiplayer_keys_dict', {}))
    map_ref.show_feedback(f"Loaded {len(files)} move files.")
    return True

def export_next_turn(map_ref):
    turn = map_ref.time_manager.total_turns

    tour_dir = getattr(map_ref, 'multiplayer_tournament_dir', None)
    if not tour_dir and hasattr(map_ref, 'loaded_tournament_path') and map_ref.loaded_tournament_path:
        tour_dir = os.path.dirname(map_ref.loaded_tournament_path)
    if not tour_dir:
        tour_dir = c.TOURNAMENT_SAVES_DIR

    os.makedirs(tour_dir, exist_ok=True)
    export_path = os.path.join(tour_dir, f"Turn_{turn}_Host.gd5tour")
    master_key = getattr(map_ref, 'multiplayer_master_key', '')
    keys_dict = getattr(map_ref, 'multiplayer_keys_dict', {})

    if not master_key or not keys_dict:
        map_ref.show_feedback("Error: Host keys missing. Did you init multiplayer?")
        return

    multiplayer_io.export_tournament(map_ref, export_path, master_key, keys_dict)

    # Reset protected countries for next turn
    map_ref.multiplayer_protected_countries = set()
    map_ref.submitted_moves = set()
    map_ref.show_feedback(f"Tournament exported to {export_path}")

def _playable_countries(map_ref):
    """Every playable nation still on the map, ordered by display name."""
    countries = queries.get_active_playable_nations(getattr(map_ref, 'map_data', None), map_ref.nation_data)
    countries.sort(key=lambda cid: map_ref.nation_data[cid].get("name", cid))
    return countries

def manage_players_panel(map_ref):
    """Picks which countries skip the AI this turn, and loads their move files."""
    if not hasattr(map_ref, 'multiplayer_protected_countries'):
        map_ref.multiplayer_protected_countries = set()
    if not hasattr(map_ref, 'submitted_moves'):
        map_ref.submitted_moves = set()

    def build_rows():
        rows = []
        for cid in _playable_countries(map_ref):
            name = map_ref.nation_data[cid].get("name", cid)
            has_move = cid in map_ref.submitted_moves
            rows.append(CheckboxItem(cid, f"{name} ({cid})",
                                     checked=cid in map_ref.multiplayer_protected_countries,
                                     note="[SUBMITTED]" if has_move else "[WAITING]",
                                     note_color=(120, 230, 120) if has_move else (190, 190, 190)))
        return rows

    def on_load_moves(screen):
        if load_multiplayer_moves(map_ref):
            screen.set_items(build_rows())

    skipped = queries.open_checkbox_list(
        map_ref, "Manage Players & Moves",
        "Load player moves, and select countries to skip (skipped countries will have AI disabled):",
        build_rows(), extra_buttons=[("Load Moves", "light_blue", on_load_moves)])

    if skipped is None:
        return

    map_ref.multiplayer_protected_countries = set(skipped)
    skipped_ai_count = len(skipped)
    submitted_count = len(getattr(map_ref, 'submitted_moves', set()))

    if submitted_count > 0 and skipped_ai_count > 0:
        map_ref.show_feedback(f"{submitted_count} player move(s) loaded; {skipped_ai_count} country/countries set to skip AI.")
    elif skipped_ai_count > 0:
        map_ref.show_feedback(f"{skipped_ai_count} country/countries set to skip AI this turn.")
    elif submitted_count > 0:
        map_ref.show_feedback(f"{submitted_count} player move(s) loaded.")
    else:
        map_ref.show_feedback("All unsubmitted countries will be controlled by AI this turn.")

def manage_keys_panel(map_ref):
    """Queues which countries get a fresh player key on the next export."""
    if not hasattr(map_ref, 'multiplayer_pending_key_regen'):
        map_ref.multiplayer_pending_key_regen = set()

    rows = [CheckboxItem(cid, f"{map_ref.nation_data[cid].get('name', cid)} ({cid})",
                         checked=cid in map_ref.multiplayer_pending_key_regen)
            for cid in _playable_countries(map_ref)]

    queued = queries.open_checkbox_list(
        map_ref, "Regenerate Player Keys",
        "Select countries whose keys should be regenerated upon exporting the turn/map:",
        rows)

    if queued is None:
        return

    map_ref.multiplayer_pending_key_regen = set(queued)
    map_ref.show_feedback(f"{len(queued)} country key(s) queued for regeneration upon export.")
