"""
Facade module to maintain backwards compatibility with existing imports across the project.
All underlying logic has been separated into modular files.
"""

from map_logic.diplomacy.diplomacy_events import log_global_event

from map_logic.diplomacy.diplomacy_messages import (
    get_pending_action,
    queue_text_message,
    cancel_text_message,
    send_message,
    get_response,
    get_response_status,
    set_response,
    clear_response,
    RESPONSE_ACCEPT,
    RESPONSE_REJECT
)

from map_logic.diplomacy.diplomacy_agreements import (
    finalize_war, 
    finalize_neutral, 
    execute_peace_treaty,
    finalize_create_faction,
    finalize_disband_faction, 
    finalize_faction_join, 
    finalize_faction_leave,
    join_faction_wars, 
    finalize_faction_kick,
    finalize_annexation,
    finalize_release,
    finalize_take_puppets
)

from map_logic.diplomacy.diplomacy_processor import (
    toggle_diplomacy_action,
    toggle_diplomatic_response,
    process_diplomacy_turn
)