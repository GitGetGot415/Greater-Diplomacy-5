import data.constants as c
from data import queries

def process_national_research(self):
    # Load template to know costs (REPLACED WITH CACHE)
    template = queries.get_tech_tree()
    
    # Uses the new constant
    base_points_per_turn = c.BASE_RESEARCH_POINTS_PER_DAY * c.DAYS_PER_TURN

    current_exact_year = queries.get_exact_year(self.time_manager)

    for country_name, country_data in self.nation_data.items():
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
            effective_points = base_points_per_turn * multiplier
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
                
                if country_name == self.player_country:
                    self.show_feedback(f"TECH FINISHED: {tech_key.replace('_', ' ').title()}")
                
                # Remove completed tech from queue
                queue.pop(i)