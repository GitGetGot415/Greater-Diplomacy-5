"""Load repairs. They compare saved data with the active libraries and run on every load.

They are not conversion rules for older formats. A changed library changes their result.
"""

import copy
import re

from map_logic.diplomacy.diplomacy_events import log_global_event


_BUILDING_LEVEL_NAME = re.compile(r"(.+) Lvl (-?\d+)")


def clamp_building_level(name, building_library):
    """Return the building a saved name means in the active library, or None.

    A numbered building whose level is not in the library moves to the nearest
    existing level of its family. A name with no family in the library gives None.
    """
    if name in building_library:
        return name
    match = _BUILDING_LEVEL_NAME.fullmatch(name) if isinstance(name, str) else None
    if not match:
        return None
    family, level = match.group(1), int(match.group(2))
    levels = [int(other.group(2)) for other in map(_BUILDING_LEVEL_NAME.fullmatch, building_library)
              if other and other.group(1) == family]
    if not levels:
        return None
    return f"{family} Lvl {min(max(level, min(levels)), max(levels))}"


def clamp_building_queue(queue, building_library):
    """Move queued numbered buildings to the nearest level in the active library.

    Orders without a level, such as core orders, and names with no family stay as they are.
    """
    for entry in queue:
        if isinstance(entry, dict):
            clamped = clamp_building_level(entry.get("item_name"), building_library)
            if clamped:
                entry["item_name"] = clamped


def normalize_production_order(entry, expected):
    """Complete older queue entries without replacing explicit countdowns or payments."""
    result = copy.deepcopy(entry)
    for key, value in copy.deepcopy(expected).items():
        result.setdefault(key, value)
    return result


def repair_faction_rosters(nation_data, map_data):
    """Drops from every faction roster the members who should never have been on it.

    Two states the engine now prevents but older saves are already in, because
    nothing checked them:

      - a puppet in a faction its master is not in. A subject holds whatever its
        master holds; it does not sign its own pacts. saves/Madagascar but not
        France has French Madagascar in the Axis while Vichy France, its master,
        is in nothing at all.
      - two members of the same faction at war. This was possible when a master
        attacked its own puppet: the puppet became independent, but the normal
        faction-leave guard had refused to move it first.

    Membership is cleared; nothing else about the nation is touched, and no
    nation is deleted. Each repair is logged, so a roster changing between one
    session and the next is traceable rather than mysterious.
    """
    from data import queries

    for name, data in list(nation_data.items()):
        if not isinstance(data, dict) or not data.get("faction"):
            continue

        master = data.get("master", "")
        if master and nation_data.get(master, {}).get("faction", "") != data["faction"]:
            reason = f"its master {master} is not in it"
        else:
            continue

        log_global_event(nation_data,
                         f"{name} is no longer counted among {data['faction']}: {reason}.")
        data["faction"] = ""
        data["is_faction_leader"] = False

    # A repaired save can still contain a historical internal war. Keep the
    # war intact, but remove the least-established side from the faction so the
    # game never loads two allies as enemies. Prefer a non-leader and then a
    # puppet; the alphabetical tie-break makes this recovery deterministic.
    seen_pairs = set()
    for name, data in sorted(nation_data.items()):
        if not isinstance(data, dict):
            continue
        for enemy in data.get("at_war_with", []):
            if not isinstance(enemy, str) or enemy not in nation_data:
                continue
            pair = tuple(sorted((name, enemy)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            other = nation_data.get(enemy, {})
            if not (isinstance(other, dict)
                    and queries.are_in_same_faction(name, enemy, nation_data)):
                continue

            def removal_priority(member):
                member_data = nation_data[member]
                try:
                    tenure = int(member_data.get("faction_tenure", 0) or 0)
                except (TypeError, ValueError):
                    tenure = 0
                return (bool(member_data.get("is_faction_leader")),
                        not bool(member_data.get("master", "")), tenure, member)

            leaver = min((name, enemy), key=removal_priority)
            faction = nation_data[leaver]["faction"]
            log_global_event(
                nation_data,
                f"{leaver} is no longer counted among {faction}: it is at war with "
                f"fellow member {enemy if leaver == name else name}.")
            nation_data[leaver]["faction"] = ""
            nation_data[leaver]["is_faction_leader"] = False
