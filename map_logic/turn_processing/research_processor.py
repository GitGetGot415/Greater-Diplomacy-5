import data.constants as c
from data import queries
from map_logic import politics

def process_national_research(map_screen):
    # Load template to know costs (REPLACED WITH CACHE)
    template = queries.get_tech_tree()
    
    # Uses the new constant
    days_per_turn = queries.get_days_per_turn(map_screen.scenario_settings)
    base_points_per_turn = c.BASE_RESEARCH_POINTS_PER_DAY * days_per_turn

    current_exact_year = queries.get_exact_year(map_screen.time_manager)

    for country_name, country_data in map_screen.nation_data.items():
        queue = country_data.get("research_queue", [])
        if not queue: continue

        # We iterate backwards through the queue so we can safely remove items
        for i in range(len(queue) - 1, -1, -1):
            project = queue[i]
            tech_key = project["tech_name"]
            
            # --- AHEAD OF TIME PENALTY LOGIC ---
            # Figure out what level is currently being researched
            current_level = country_data.get("research", {}).get(tech_key, 0)
            tech_data = template.get(tech_key, {})
            years_array = tech_data.get("years", [1850])
            
            # Cap the index to prevent out-of-bounds if a nation somehow researches past max_lvl
            target_index = min(current_level, len(years_array) - 1)
            target_year = years_array[target_index]
            
            multiplier = queries.get_research_multiplier(current_exact_year, target_year)
            # A libertarian nation researches faster and an authoritarian one
            # slower -- at the far end, not at all, which is a stalled project
            # rather than a guarded division.
            effective_points = (base_points_per_turn * multiplier
                                * politics.research_multiplier(map_screen.nation_data, country_name))
            # -----------------------------------
            
            # Use 'points_remaining' instead of 'days_remaining'
            # (First time initialization if coming from an old save)
            if "points_remaining" not in project:
                project["points_remaining"] = project.get("days_remaining", 30) * 10
            
            project["points_remaining"] -= effective_points

            if project["points_remaining"] <= 0:
                country_data["research"][tech_key] = country_data["research"].get(tech_key, 0) + 1
                
                # CLEANUP: Remove from progress cache if it was there
                if "research_progress" in country_data:
                    country_data["research_progress"].pop(tech_key, None)
                
                if country_name == map_screen.player_country:
                    map_screen.show_feedback(f"TECH FINISHED: {tech_key.replace('_', ' ').title()}")
                
                # Remove completed tech from queue
                queue.pop(i)