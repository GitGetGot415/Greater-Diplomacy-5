from data.state_access import world_for, session_for
import data.constants as c
from data import queries
from map_logic import politics

def process_national_research(map_screen):
    # Load template to know costs (REPLACED WITH CACHE)
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    template = queries.get_tech_tree(map_screen)
    
    # Uses the new constant
    days_per_turn = queries.get_days_per_turn(world_state.scenario_settings)
    base_points_per_turn = c.BASE_RESEARCH_POINTS_PER_DAY * days_per_turn

    current_exact_year = queries.get_exact_year(world_state.time_manager)

    for country_name, country_data in world_state.nation_data.items():
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
            faction_bonus = queries.get_faction_research_bonus(
                country_name, tech_key, current_level + 1, world_state.nation_data)
            effective_points = (base_points_per_turn * multiplier
                                * politics.research_multiplier(world_state.nation_data, country_name)
                                * (1.0 + faction_bonus))
            # -----------------------------------
            
            project["points_remaining"] -= effective_points

            if project["points_remaining"] <= 0:
                country_data["research"][tech_key] = country_data["research"].get(tech_key, 0) + 1
                
                # CLEANUP: Remove from progress cache if it was there
                if "research_progress" in country_data:
                    country_data["research_progress"].pop(tech_key, None)
                
                if country_name == session_state.player_country:
                    map_screen.show_feedback(f"TECH FINISHED: {queries.get_tech_display_name(tech_key, context=map_screen)}")
                
                # Remove completed tech from queue
                queue.pop(i)


def apply_research_selection(country, result):
    """Apply a canonical queue projection after its adapter validates authority."""
    import copy
    country["research_queue"] = copy.deepcopy(result["projects"])
    country["research_progress"] = copy.deepcopy(result["research_progress"])


def select_research(country, requested, tech_tree=None):
    result = queries.canonical_research_selection(country, requested, tech_tree)
    apply_research_selection(country, result)
    return result


def enqueue_research(queue, tech_name, points_remaining):
    """Keep AI restart costs explicit after its existing selection pass."""
    project = queries.build_research_project(tech_name, points_remaining)
    queue.append(project)
    return project
