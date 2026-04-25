from map_logic.ai import ai_handler
from data import queries
from data.constants import UNPLAYABLE_NATIONS

THINKING_COOLDOWN = 0

def process_ai_grand_strategy(map_screen):
    """
    Scores all AI nations to determine who 'cares' enough about the current state of the world
    to warrant spending an LLM API call on them this turn.
    """
    active_nations = list(queries.get_living_nations(map_screen.map_data))
    
    # Map out neighbors for quick checking
    nation_neighbors = {n: set() for n in active_nations}
    for prov in map_screen.map_data.values():
        owner = prov.get("owner")
        if owner in active_nations:
            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") in active_nations and n_prov.get("owner") != owner:
                    nation_neighbors[owner].add(n_prov.get("owner"))

    ai_scores = {}
    
    global_event_data = map_screen.nation_data.get("GLOBAL_EVENTS", {})
    # FIX: Use the news_flash queue instead of the permanent log
    news_flashes = global_event_data.get("news_flash", [])
    
    hot_nations = set()
    for ev in news_flashes:
        for n in active_nations:
            if n in ev:
                hot_nations.add(n)
                
    # Clear the flashes so they aren't processed again next turn
    if isinstance(global_event_data, dict) and "news_flash" in global_event_data:
        global_event_data["news_flash"] = []

    # Get an absolute turn number for cooldown math
    tm = map_screen.time_manager
    current_absolute_turn = tm.year * 36 + tm.month_index * 3 + tm.day // 10

    for ai_name, data in map_screen.nation_data.items():
        # Skip players, dead nations, or unplayable entities
        if ai_name == map_screen.player_country or ai_name in UNPLAYABLE_NATIONS or not data.get("is_playable"):
            continue
        if ai_name not in active_nations:
            continue

        score = 0
        
        # 1. Economic / Superpower bias (Bigger nations act more often)
        total_eco = data.get("materials", 0) + data.get("manpower", 0)
        score += min(50, total_eco // 10000) 
        
        # 2. Are they currently at war? (Needs to negotiate or call allies)
        if len(data.get("at_war_with", [])) > 0:
            score += 40
            
        # 3. Direct involvement in breaking news
        if ai_name in hot_nations:
            score += 100
            
        # 4. Proximity to breaking news (Neighbors care if a war breaks out next door)
        if any(hot_nation in nation_neighbors.get(ai_name, set()) for hot_nation in hot_nations):
            score += 60
            
        # 5. Cooldown Penalty (Prevents the same large empires from hogging the LLM during peacetime)
        last_thought = data.get("last_thought_turn", -10)
        if current_absolute_turn - last_thought < THINKING_COOLDOWN:
            score -= 100

        ai_scores[ai_name] = score

    # Sort AIs by highest score
    sorted_ais = sorted(ai_scores.items(), key=lambda item: item[1], reverse=True)
    
    # Take the top 3 most relevant AIs to act this turn
    top_ais = [ai[0] for ai in sorted_ais[:3] if ai[1] > 20] # Must have at least some relevance
    
    if top_ais:
        print(f"[AI FILTER] Nations selected to execute Grand Strategy this turn: {', '.join(top_ais)}")
    else:
        print("[AI FILTER] No AI nations passed the relevance threshold this turn.")
    
    current_date = map_screen.time_manager.get_date_string()
    
    # Let the selected AIs think and apply their orders
    for ai_nation in top_ais:
        # Mark their cooldown
        map_screen.nation_data[ai_nation]["last_thought_turn"] = current_absolute_turn
        
        actions = ai_handler.decide_grand_strategy(map_screen.nation_data, active_nations, ai_nation, current_date)
        
        pending = map_screen.nation_data[ai_nation].setdefault("pending_diplomacy", {})
        
        for act in actions:
            action_type = act.get("action")
            target = act.get("target")
            
            if not action_type or not target: continue
            
            # Special handling for self-targeting actions
            if action_type in ["CREATE_FACTION", "LEAVE_FACTION", "DISBAND_FACTION"]:
                target = ai_nation 

            if target not in active_nations: continue

            # Apply to pending diplomacy queue exactly like the player does
            if action_type == "CUSTOM_MSG":
                content = act.get("content", "Greetings.")
                pending[target] = {"action": f"MSG:{content}", "turns": 0}
            else:
                # Don't overwrite existing diplomacy in transit
                if target not in pending or pending[target].get("turns", 0) == 0:
                    pending[target] = {"action": action_type, "turns": 0}