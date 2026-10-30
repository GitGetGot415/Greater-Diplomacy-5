"""Shared research cases for content, controls, and multiplayer validation."""

from data import queries


def research_lock_cases(tree, category="INDUSTRY"):
    """Return tech, locked progress, and valid progress for each gated step in the active tree."""
    cases = []
    for key, data in tree.items():
        if data["category"] != category:
            continue
        for level in (1, *sorted(int(level) for level in data.get("level_reqs", {}))):
            requirements = queries.get_tech_requirements(data, level)
            if not requirements:
                continue
            unlocked = queries.edited_research_levels({}, key, level, True, tree)
            unlocked[key] = level - 1
            locked = dict(unlocked)
            # Remove all prerequisites for this step, including alternative branches.
            for dependency, _required in queries.walk_tech_requirements(requirements):
                locked[dependency] = 0
            cases.append((key, locked, unlocked))
    return cases


def fixture_metadata(*, family="Fixture", tier=1, level=1):
    return {"family": family, "tier_order": tier,
            "research": {"tech": "fixture_track", "level": level},
            "requirements": [{"tech": "fixture_track", "level": level}],
            "recruitment": {"industry": "none", "coastal": False}}
