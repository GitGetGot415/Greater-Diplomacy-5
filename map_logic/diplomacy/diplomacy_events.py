import data.constants as c

def log_global_event(nation_data, event_message):
    """Stores world events so the AI can react to them on the next turn."""
    if "GLOBAL_EVENTS" not in nation_data:
        nation_data["GLOBAL_EVENTS"] = {"is_playable": False, "log": [], "news_flash": []}
        
    log = nation_data["GLOBAL_EVENTS"].setdefault("log", [])
    log.insert(0, event_message)
    
    # NEW: Add to news flash for instant AI reactions
    news = nation_data["GLOBAL_EVENTS"].setdefault("news_flash", [])
    news.append(event_message)
    
    # Keep only the last 15 events to prevent the context window from exploding
    if len(log) > 15:
        log.pop()