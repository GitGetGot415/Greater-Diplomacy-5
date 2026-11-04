"""Convert saved research levels to the active technology tree."""

import math

import data.constants as c


# Original GD5 equipment dates. These describe older saved level numbers.
LEGACY_INFANTRY_RESEARCH_YEARS = {
    "infantry_type": list(range(1910, 2051)),
    "cavalry": list(range(1910, 1927, 4)),
    "militia": list(range(1910, 2051, 5)),
    "artillery": list(range(1910, 2051, 5)),
}


def _valid_years(years):
    return (isinstance(years, list) and bool(years)
            and all(type(year) is int for year in years) and years == sorted(set(years)))


def _saved_level(level):
    """Read a saved equipment level as a nonnegative whole number. Unreadable levels read as 0."""
    if type(level) is int:
        return max(0, level)
    if isinstance(level, float) and math.isfinite(level):
        return max(0, round(level))
    return 0


def migrate_infantry_research(saved, tech_tree, history=None):
    """Map completed equipment years to the active stages. Keep unfinished points.

    It converts every history snapshot too. All snapshots share the save's research_years.
    Broken saved data does not stop a load. An unreadable level reads as the nearest whole
    level, or 0. A malformed year list cannot tell what its levels mean, so those levels stay.
    """
    saved_years = saved.get("research_years", LEGACY_INFANTRY_RESEARCH_YEARS)
    targets = {key: list(tech_tree[key]["years"])
               for key in c.DATED_UNIT_RESEARCH_TRACKS if key in tech_tree}
    sources = {}
    if isinstance(saved_years, dict):
        sources = {key: saved_years[key] if _valid_years(saved_years[key]) else target
                   for key, target in targets.items() if key in saved_years}

    def convert(research, pending=()):
        if not isinstance(research, dict):
            return
        for key, target in targets.items():
            if key not in research:
                continue
            level = research[key] = _saved_level(research[key])
            source = sources.get(key)
            if source is None or source == target:
                continue
            if level:
                # Retain levels beyond an older content cap instead of discarding them.
                year = source[min(level, len(source)) - 1]
                research[key] = sum(value <= year for value in target) + max(0, level - len(source))
            elif key in pending:
                research[key] = sum(value < source[0] for value in target)

    def convert_countries(countries):
        if not isinstance(countries, dict):
            return
        for name, country in countries.items():
            if name == "FACTION_WAR_MAPS" or not isinstance(country, dict):
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


def clamp_research_levels(saved, tech_tree):
    """Lower research levels above the active maximum. Drop projects the new maximum completes.

    It changes only the live state. A selected history turn becomes live state first.
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
                    and type(level) is int and level >= tech_tree[key]["max_lvl"]):
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
            for name, country in countries.items():
                if name != "FACTION_WAR_MAPS" and isinstance(country, dict):
                    clamp(country)

    if isinstance(saved.get("default_research"), dict):
        clamp({"research": saved["default_research"]})
    clamp_countries(saved.get("nation_data"))
    return saved


def grant_research_prerequisites(saved, tech_tree):
    """Grant the prerequisite levels of technologies that a country already has.

    Without them a country cannot research further levels of what it owns. Older saves
    have technologies whose prerequisites were added later. The grant uses the active
    research tree. The equipment tracks are not changed, and no prerequisite uses them.
    It changes only the live state. A selected history turn becomes live state first.
    """
    from data import queries

    def grant(research):
        if not isinstance(research, dict):
            return
        for tech, level in list(research.items()):
            if (tech not in tech_tree or tech in c.DATED_UNIT_RESEARCH_TRACKS
                    or type(level) is not int or level < 1):
                continue
            level = min(level, tech_tree[tech]["max_lvl"])
            if queries.check_tech_requirements(
                    research, queries.get_tech_requirements(tech_tree[tech], level), level):
                continue
            try:
                research.update(queries.edited_research_levels(research, tech, level, True, tech_tree))
            except ValueError:
                # A prerequisite the active tree cannot supply. Keep the saved levels.
                continue

    def grant_countries(countries):
        if isinstance(countries, dict):
            for name, country in countries.items():
                if name != "FACTION_WAR_MAPS" and isinstance(country, dict):
                    grant(country.get("research"))

    grant(saved.get("default_research"))
    grant_countries(saved.get("nation_data"))
    return saved
