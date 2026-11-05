
#: How many events each list keeps. The log feeds every LLM prompt, so a longer
#: one costs tokens on every request.
GLOBAL_EVENT_LIMIT = 15


def log_global_event(nation_data, event_message):
    """Stores world events so the AI can react to them on the next turn."""
    if "GLOBAL_EVENTS" not in nation_data:
        nation_data["GLOBAL_EVENTS"] = {"is_playable": False, "log": [], "news_flash": []}

    # Newest first.
    log = nation_data["GLOBAL_EVENTS"].setdefault("log", [])
    log.insert(0, event_message)
    del log[GLOBAL_EVENT_LIMIT:]

    # Oldest first. Nothing reads this list yet, but it is saved with the game,
    # so it has the same limit as the log. A longer list from an older save
    # becomes short again at the next event.
    news = nation_data["GLOBAL_EVENTS"].setdefault("news_flash", [])
    news.append(event_message)
    del news[:-GLOBAL_EVENT_LIMIT]


def clear_global_events(nation_data):
    """Empties both event lists, for a game that is just starting.

    The log is what happened in one game. A scenario file can still hold
    events from a game its author played, or notes its load repairs wrote, and
    every LLM prompt reads the log as current news. Other GLOBAL_EVENTS fields,
    such as deleted_countries, are not events and stay.
    """
    record = nation_data.get("GLOBAL_EVENTS")
    if isinstance(record, dict):
        record["log"] = []
        record["news_flash"] = []