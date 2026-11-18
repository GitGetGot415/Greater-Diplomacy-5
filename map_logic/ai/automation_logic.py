from data.state_access import world_for, session_for
import data.queries as queries
from map_logic.ai import ai_construction, ai_movement, ai_research

# --- AUTOMATE THIS TURN ---

def automate_player_construction(context):
    ai_construction.process_ai_economy_decisions(context, countries=[session_for(context).player_country])

def automate_player_movement(context):
    ai_movement.process_ai_unit_orders(context, countries=[session_for(context).player_country])

def automate_player_research(context):
    ai_research.process_ai_research(context, countries=[session_for(context).player_country])


def run_enabled_automation(context):
    """Prepare the next turn for one country's enabled automation options."""
    country = session_for(context).player_country
    if not country or country == "Spectator":
        return
    automation = world_for(context).nation_data.get(country, {}).get("automation", {})
    if not isinstance(automation, dict):
        return
    if automation.get("construction"):
        automate_player_construction(context)
    if automation.get("movement"):
        automate_player_movement(context)
    if automation.get("research"):
        automate_player_research(context)


# --- CLEAR ---

def clear_player_construction(context):
    """Empties the player's build and recruit queues, refunding what was paid.

    Both queues go through the same refund rule the Production screen's Cancel
    button uses, which honours the "refund" each entry recorded at purchase.
    """
    world_state = world_for(context)
    session_state = session_for(context)
    player = session_state.player_country
    player_data = world_state.nation_data[player]

    for prov in world_state.map_data.values():
        if prov.get("owner") != player:
            continue
        for queue_key in ("building_queue", "unit_queue"):
            for item in prov.get(queue_key, []):
                queries.refund_queue_item(player_data, item, player, world_state.map_data, context=context)
            prov[queue_key] = []

def clear_player_movement(context):
    world_state = world_for(context)
    session_state = session_for(context)
    player = session_state.player_country
    for prov in world_state.map_data.values():
        for unit in prov.get("units", []):
            if unit.get("owner") == player:
                unit["order"] = {}

def clear_player_research(context):
    world_state = world_for(context)
    session_state = session_for(context)
    player = session_state.player_country
    player_data = world_state.nation_data.get(player, {})
    queue = player_data.get("research_queue", [])
    progress_cache = player_data.setdefault("research_progress", {})
    for project in queue:
        tech_name = project.get("tech_name")
        if tech_name:
            progress_cache[tech_name] = project.get("points_remaining", 0)
    player_data["research_queue"] = []
