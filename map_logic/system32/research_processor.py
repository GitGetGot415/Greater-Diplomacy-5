import copy

import data.constants as c
from data.state_access import world_for, session_for
from data import queries


def process_national_research(context, *, economies=None):
    world_state = world_for(context)
    session_state = session_for(context)
    template = queries.get_tech_tree(context)
    days_per_turn = queries.get_days_per_turn(world_state.scenario_settings)
    current_exact_year = queries.get_exact_year(world_state.time_manager)

    for country_name, country_data in world_state.nation_data.items():
        queue = country_data.get("research_queue", [])
        if not queue: continue

        normal = queries.get_normal_research_progress(world_state.nation_data, country_name, template, days_per_turn, current_exact_year)
        bonus = {}
        if economies and country_name in economies and country_name not in c.UNPLAYABLE_NATIONS and country_name != "GLOBAL_EVENTS":
            surplus = min(country_data["materials"], queries.get_net_materials_income(economies[country_name]))
            diverted, bonus = queries.calculate_research_funding(country_data, surplus, normal)
            if diverted:
                country_data["materials"] -= diverted

        # We iterate backwards through the queue so we can safely remove items
        for i in range(len(queue) - 1, -1, -1):
            project = queue[i]
            tech_key = project["tech_name"]
            project["points_remaining"] -= normal[tech_key]
            project["points_remaining"] -= bonus.get(tech_key, 0)

            if project["points_remaining"] <= 0:
                country_data["research"][tech_key] = country_data["research"].get(tech_key, 0) + 1
                
                # CLEANUP: Remove from progress cache if it was there
                if "research_progress" in country_data:
                    country_data["research_progress"].pop(tech_key, None)
                
                if country_name == session_state.player_country:
                    context.show_feedback(f"TECH FINISHED: {queries.get_tech_display_name(tech_key, context=context)}")
                
                # Remove completed tech from queue
                queue.pop(i)


def apply_research_selection(country, result):
    """Apply a canonical queue projection after its adapter validates authority."""
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
