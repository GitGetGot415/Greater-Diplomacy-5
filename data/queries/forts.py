"""Fort levels, fort defense bonuses, and fort damage."""

import data.constants as c
import re
from data.queries.factions import are_in_same_faction
from data.queries.combat_state import (
    COMBAT_LOCATION_DEFENSE,
    COMBAT_LOCATION_GENERIC,
    COMBAT_LOCATION_OFFENSE,
)
from data.queries.economy import refund_queue_item
from data import queries


def get_fort_level(province):
    """Returns the highest completed fort level on a province, if any."""
    level = 0
    for b_name in province.get("buildings", []):
        match = re.fullmatch(r"Fort Lvl (\d+)", b_name)
        if match:
            level = max(level, int(match.group(1)))
    return level


def is_fort_defended_territory(province, nation, nation_data):
    """Whether ``nation`` would receive a fort's defense on this province.

    This does not require a fort or active combat.  It answers the durable
    territory rule shared by fort bonuses, combat presentation, and any future
    defense-side mechanics: a province protects its owner and faction members.
    """
    owner = province.get("owner")
    return bool(owner and nation and
                (nation == owner or are_in_same_faction(owner, nation, nation_data)))


def get_combat_location_category(province, perspective_nation, nation_data,
                                 battle_units=None):
    """Classify a battle from the viewer's aligned side.

    A viewer who is not engaged on either side gets the generic shape. This
    includes spectators, editors, and countries merely observing a battle.
    The battle units are required to tell an aligned viewer which side is
    engaged and whether that side is defending the current land owner.
    """
    if (not battle_units or perspective_nation is None
            or perspective_nation in ("Spectator", "Editor")):
        return COMBAT_LOCATION_GENERIC

    from map_logic.system32 import combat_rules

    battle = combat_rules.build_battle(
        [battle_units], nation_data, terrain=province.get("terrain"))
    if not battle.lanes:
        return COMBAT_LOCATION_GENERIC

    friendly_nations = queries.get_all_friendly_nations(
        perspective_nation, nation_data)
    owner = province.get("owner")

    def side_matches_viewer(side):
        return (any(nation in friendly_nations for nation in side.nations)
                or any(unit.get("owner") in friendly_nations
                       for unit in side.front + side.reserve))

    def side_defends_tile(side):
        if not owner:
            return False
        return any(
            nation == owner or are_in_same_faction(owner, nation, nation_data)
            for nation in side.nations)

    for lane in battle.lanes:
        for side in (lane.a, lane.b):
            if side_matches_viewer(side):
                return (COMBAT_LOCATION_DEFENSE
                        if side_defends_tile(side)
                        else COMBAT_LOCATION_OFFENSE)

    return COMBAT_LOCATION_GENERIC


def damage_fort(province, nation_data, map_data=None, *, context=None):
    """Removes one fort level and cancels/refunds queued fort upgrades.

    The queue belongs to the province, while its construction cost was paid by
    the current tile owner.  Queue entries record the exact amount paid, so
    using ``refund_queue_item`` also keeps old saves and any applicable cost
    modifiers correct.

    Returns the new fort level, or ``None`` when the province had no fort.
    """
    if context is None:
        context = nation_data
    current_level = get_fort_level(province)
    if current_level <= 0:
        return None

    province["buildings"] = [
        b_name for b_name in province.get("buildings", [])
        if not re.fullmatch(r"Fort Lvl (\d+)", b_name)
    ]
    if current_level > 1:
        province["buildings"].append(f"Fort Lvl {current_level - 1}")

    queue = province.get("building_queue", [])
    if queue:
        owner = province.get("owner")
        owner_data = nation_data.get(owner, {}) if owner else {}
        kept_queue = []
        cancelled = False
        for item in queue:
            if (item.get("order_type") == "BUILDING"
                    and re.fullmatch(r"Fort Lvl (\d+)", item.get("item_name", ""))):
                refund_queue_item(owner_data, item, owner, map_data, context=context)
                cancelled = True
            else:
                kept_queue.append(item)
        if cancelled:
            province["building_queue"] = kept_queue

    return current_level - 1


def get_fort_defense_bonus(province, unit, nation_data, combat_active=None):
    """Returns the fort defense bonus for a unit defending this province.

    Forts protect the province owner and nations in the owner's faction.  The
    bonus only exists while the tile is under attack; callers such as
    bombardment can pass ``combat_active=True`` because the attacker is not
    physically present in the province.
    """
    level = get_fort_level(province)
    if level <= 0:
        return 0

    if combat_active is None:
        combat_active = queries.is_province_in_active_combat(province, nation_data)
    if not combat_active:
        return 0

    if not is_fort_defended_territory(province, unit.get("owner"), nation_data):
        return 0
    return level * c.FORT_DEFENSE_PER_LEVEL
