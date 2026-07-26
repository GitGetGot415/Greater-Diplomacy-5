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
    player = map_screen.player_country
    for prov in map_screen.map_data.values():
        if prov.get("owner") == player:
            queue = prov.get("building_queue", [])
            for q in queue:
                # Refund cost
                b_type = q.get("building_type")
                if b_type:
                    cost = queries.get_building_library().get(b_type, {}).get("cost", 0)
                    map_screen.nation_data[player]["materials"] += cost
            prov["building_queue"] = []
            
            unit_queue = prov.get("unit_queue", [])
            for u in unit_queue:
                u_type = u.get("unit_type")
                if u_type:
                    stats = queries.get_unit_library().get(u_type, {})
                    map_screen.nation_data[player]["manpower"] += stats.get("cost_manpower", 0)
                    map_screen.nation_data[player]["materials"] += stats.get("cost_materials", 0)
                    map_screen.nation_data[player]["fuel"] += stats.get("cost_fuel", 0)
            prov["unit_queue"] = []

def clear_player_movement(map_screen):
    player = map_screen.player_country
    for prov in map_screen.map_data.values():
        for unit in prov.get("units", []):
            if unit.get("owner") == player:
                unit["order"] = {}

def clear_player_research(map_screen):
    player = map_screen.player_country
    player_data = map_screen.nation_data.get(player, {})
    queue = player_data.get("research_queue", [])
    progress_cache = player_data.setdefault("research_progress", {})
    for project in queue:
        tech_name = project.get("tech_name")
        if tech_name:
            progress_cache[tech_name] = project.get("points_remaining", 0)
    player_data["research_queue"] = []
