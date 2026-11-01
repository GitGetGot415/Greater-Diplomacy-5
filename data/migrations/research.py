"""Convert saved research levels to the active technology tree."""

import data.constants as c


# Original GD5 equipment dates. These describe older saved level numbers.
LEGACY_INFANTRY_RESEARCH_YEARS = {
    "infantry_type": list(range(1910, 2051)),
    "cavalry": list(range(1910, 1927, 4)),
    "militia": list(range(1910, 2051, 5)),
    "artillery": list(range(1910, 2051, 5)),
}


def migrate_infantry_research(saved, tech_tree, history=None):
    """Map completed equipment years to the active stages. Keep unfinished points."""
    sources = saved.get("research_years", LEGACY_INFANTRY_RESEARCH_YEARS)
    if not isinstance(sources, dict):
        raise ValueError("Saved research_years must contain technology year lists.")
    targets = {key: list(tech_tree[key]["years"])
               for key in c.DATED_UNIT_RESEARCH_TRACKS if key in tech_tree}

    def convert(research, pending=()):
        if not isinstance(research, dict):
            return
        for key, target in targets.items():
            if key not in sources or key not in research:
                continue
            source = sources[key]
            if source == target:
                continue
            if (not isinstance(source, list) or not source
                    or any(type(year) is not int for year in source)
                    or source != sorted(set(source))):
                raise ValueError(f"Saved research years for {key} must be increasing integers.")
            level = research[key]
            if type(level) is not int or level < 0:
                raise ValueError(f"Saved research level for {key} must be a nonnegative integer.")
            if level:
                # Retain levels beyond an older content cap instead of discarding them.
                year = source[min(level, len(source)) - 1]
                research[key] = sum(value <= year for value in target) + max(0, level - len(source))
            elif key in pending:
                research[key] = sum(value < source[0] for value in target)

    def convert_countries(countries):
        if not isinstance(countries, dict):
            return
        for country in countries.values():
            if not isinstance(country, dict):
                continue
            pending = set(country.get("research_progress", {}))
            pending.update(project.get("tech_name") for project in country.get("research_queue", []))
            if isinstance(country.get("current_research"), str):
                pending.add(country["current_research"])
            convert(country.get("research"), pending)
            # A shorter stage list can finish a track while older work is still queued.
            completed = {key for key, years in targets.items()
                         if sources.get(key) != years
                         and country.get("research", {}).get(key, 0) >= len(years)}
            if "research_queue" in country:
                country["research_queue"][:] = [project for project in country["research_queue"]
                                                if project.get("tech_name") not in completed]
            for key in completed:
                country.get("research_progress", {}).pop(key, None)
            if isinstance(country.get("current_research"), str) and country["current_research"] in completed:
                country["current_research"] = None

    convert(saved.get("default_research"))
    convert_countries(saved.get("nation_data"))
    for snapshot in (history or {}).values():
        if isinstance(snapshot, dict):
            convert_countries(snapshot.get("nation_data"))
    saved["research_years"] = targets
    return saved


def clamp_research_levels(saved, tech_tree, history=None):
    """Lower research levels above the active maximum. Drop projects the new maximum completes.

    The equipment tracks keep their levels. migrate_infantry_research retains levels
    beyond a content cap on purpose.
    """
    def clamp(country):
        research = country.get("research")
        if not isinstance(research, dict):
            return
        done = set()
        for key, level in research.items():
            if (key in tech_tree and key not in c.DATED_UNIT_RESEARCH_TRACKS
                    and type(level) is int and level > tech_tree[key]["max_lvl"]):
                research[key] = tech_tree[key]["max_lvl"]
                done.add(key)
        if "research_queue" in country:
            country["research_queue"][:] = [project for project in country["research_queue"]
                                            if project.get("tech_name") not in done]
        for key in done:
            country.get("research_progress", {}).pop(key, None)
        if country.get("current_research") in done:
            country["current_research"] = None

    def clamp_countries(countries):
        if isinstance(countries, dict):
            for country in countries.values():
                if isinstance(country, dict):
                    clamp(country)

    if isinstance(saved.get("default_research"), dict):
        clamp({"research": saved["default_research"]})
    clamp_countries(saved.get("nation_data"))
    for snapshot in (history or {}).values():
        if isinstance(snapshot, dict):
            clamp_countries(snapshot.get("nation_data"))
    return saved
