from data.state_access import world_for, session_for
import data.queries as queries
from map_logic.ai import ai_construction, ai_movement, ai_research

def _run_with_player_as_ai(map_screen, func):
    """
    Temporarily overrides get_active_ai_nations to only return the player,
    so that the standard AI logic processes their turn for them.
    """
    original_get_ai = queries.get_active_ai_nations
    try:
        queries.get_active_ai_nations = lambda ms: [ms.player_country]
        func(map_screen)
    finally:
        queries.get_active_ai_nations = original_get_ai


# --- AUTOMATE THIS TURN ---

def automate_player_construction(map_screen):
    _run_with_player_as_ai(map_screen, ai_construction.process_ai_economy_decisions)

def automate_player_movement(map_screen):
    _run_with_player_as_ai(map_screen, ai_movement.process_ai_unit_orders)

def automate_player_research(map_screen):
    _run_with_player_as_ai(map_screen, ai_research.process_ai_research)


# --- CLEAR ---

def clear_player_construction(map_screen):
    """Empties the player's build and recruit queues, refunding what was paid.

    Both queues go through the same refund rule the Production screen's Cancel
    button uses, which honours the "refund" each entry recorded at purchase.
    """
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    player = session_state.player_country
    player_data = world_state.nation_data[player]

    for prov in world_state.map_data.values():
        if prov.get("owner") != player:
            continue
        for queue_key in ("building_queue", "unit_queue"):
            for item in prov.get(queue_key, []):
                queries.refund_queue_item(player_data, item, player, world_state.map_data)
            prov[queue_key] = []

def clear_player_movement(map_screen):
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    player = session_state.player_country
    for prov in world_state.map_data.values():
        for unit in prov.get("units", []):
            if unit.get("owner") == player:
                unit["order"] = {}

def clear_player_research(map_screen):
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    player = session_state.player_country
    player_data = world_state.nation_data.get(player, {})
    queue = player_data.get("research_queue", [])
    progress_cache = player_data.setdefault("research_progress", {})
    for project in queue:
        tech_name = project.get("tech_name")
        if tech_name:
            progress_cache[tech_name] = project.get("points_remaining", 0)
    player_data["research_queue"] = []
