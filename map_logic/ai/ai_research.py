import json
import os
import data.constants as c
from data import queries

def process_ai_research(map_screen):
    """Automates research queueing for AI nations."""
    # REPLACED DISK I/O WITH CACHED QUERIES
    tech_tree = queries.get_tech_tree()
    if not tech_tree: 
        return

    ai_nations = queries.get_active_ai_nations(map_screen)

    for ai_name in ai_nations:
        data = map_screen.nation_data[ai_name]

        queue = data.setdefault("research_queue", [])
        
        # AI can only research 2 things at a time
        if len(queue) >= 2:
            continue

        res_levels = data.setdefault("research", {})

        available_techs = []
        for tech_key, t_data in tech_tree.items():
            cur_lvl = res_levels.get(tech_key, 0)
            max_lvl = t_data["max_lvl"]
            
            # Skip if fully researched
            if cur_lvl >= max_lvl:
                continue
            
            # Skip if already in queue
            is_researching = any(q["tech_name"] == tech_key for q in queue)
            if is_researching:
                continue

            lvl_to_research = cur_lvl + 1
            
            # --- THE FIX: Use the centralized query that knows how to do math ---
            reqs = t_data.get("req", {})
            if not queries.check_tech_requirements(res_levels, reqs, lvl_to_research):
                continue

            # Fetch the historical year to avoid massive ahead-of-time penalties
            years = t_data.get("years", [1900] * max_lvl)
            target_year = years[min(lvl_to_research - 1, len(years)-1)]
            
            available_techs.append((tech_key, target_year, t_data.get("cost", 300)))

        # Sort by year (prioritize techs that are on-time or older), then by cost
        current_year = map_screen.time_manager.year
        available_techs.sort(key=lambda x: (max(0, x[1] - current_year), x[2]))

        # Fill the queue
        while len(queue) < 2 and available_techs:
            best_tech = available_techs.pop(0)
            queue.append({
                "tech_name": best_tech[0],
                "points_remaining": best_tech[2]
            })