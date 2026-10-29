"""Shared research cases for content, controls, and multiplayer validation."""

from data import queries


# These names and dates are explicit content requirements.
NEW_INDUSTRY_MILESTONES = (
    ("metal_shaper", "Metal Shaper", 1835),
    ("steam_hammer", "Steam Hammer", 1840),
    ("machine_tools", "Machine Tools", 1935),
    ("industrial_robot", "Industrial Robot", 1955),
    ("stanford_arm", "Stanford Arm", 1965),
    ("asea_irb_6", "ASEA IRB 6", 1975),
    ("3d_printing", "3D Printing", 1995),
    ("industry_4_0", "Industry 4.0", 2015),
    ("industry_5_0", "Industry 5.0", 2025),
)


def factory_research_cases(tree):
    """Return candidate, locked progress, and valid progress from the active prerequisites."""
    cases = []
    targets = [(key, 1) for key, data in tree.items()
               if data["category"] == "INDUSTRY" and data["max_lvl"] == 1 and data.get("req")]
    targets.extend(("factory", level) for level in
                   [1, *sorted(int(level) for level in tree["factory"].get("level_reqs", {}))])
    for key, level in targets:
        unlocked = queries.edited_research_levels({}, key, level, True, tree)
        unlocked[key] = level - 1
        locked = dict(unlocked)
        # Remove all prerequisites for this step, including alternative branches.
        requirements = queries.get_tech_requirements(tree[key], level)
        for dependency, _required in queries.walk_tech_requirements(requirements):
            locked[dependency] = 0
        cases.append((key, locked, unlocked))
    return cases
