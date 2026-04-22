from map_functions.logic import state_queries

def get_relation(nation_data, country_a, country_b):
    """Legacy helper. Please use nation_data lists directly or state_queries."""
    if country_a == country_b:
        return "SELF"
    
    if state_queries.are_at_war(country_a, country_b, nation_data):
        return "WAR"
    if state_queries.are_allied(country_a, country_b, nation_data):
        return "ALLIED"
        
    return "NEUTRAL"

def set_relation(nation_data, country_a, country_b, status):
    """Deprecated. Diplomacy logic now handles list updates."""
    pass

def are_at_war(nation_data, country_a, country_b):
    """Redirects to state queries."""
    return state_queries.are_at_war(country_a, country_b, nation_data)