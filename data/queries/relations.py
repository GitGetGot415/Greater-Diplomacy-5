"""Relation scores, temporary modifiers, reachability, and the AI checks for war and peace."""

import collections
import data.constants as c
from data.queries.geometry import is_water_province
from data.queries.diplomacy import are_at_war, get_enemies
from data.queries.factions import are_in_same_faction, get_faction_members
from data.queries.strength import (
    get_alliance_military_strength,
    get_border_strength,
    get_combined_enemy_strength,
    get_economic_power,
)
from data import queries


def get_relation_score(nation_a, nation_b, nation_data, id_to_province=None):
    """Calculates dynamic relations based on flat state modifiers and temporary modifiers."""
    if nation_a == nation_b:
        return 0
        
    score = 0
    if are_at_war(nation_a, nation_b, nation_data):
        score += c.REL_MOD_AT_WAR
    elif are_in_same_faction(nation_a, nation_b, nation_data):
        score += c.REL_MOD_IN_FACTION
        
    # Common Enemy Bonus
    enemies_a = set(get_enemies(nation_a, nation_data))
    enemies_b = set(get_enemies(nation_b, nation_data))
    
    # If the intersection contains anything, they share at least one enemy.
    # The flat bonus is applied once, capping the effect.
    if enemies_a & enemies_b:
        score += c.REL_MOD_COMMON_ENEMY
        
    # master and puppet mechanics
    master_a = nation_data.get(nation_a, {}).get("master", "")
    master_b = nation_data.get(nation_b, {}).get("master", "")
    if master_b == nation_a:
        score += c.REL_MOD_MASTER_OF
    elif master_a == nation_b:
        score += c.REL_MOD_PUPPET_OF
                
    # Apply all decaying temporary modifiers
    temp_mods = nation_data.get(nation_a, {}).get("temp_modifiers", {}).get(nation_b, {})
    for entry in temp_mods.values():
        score += modifier_value(entry)
        
    if id_to_province:
        claims_a = nation_data.get(nation_a, {}).get("claims", [])
        claims_b = nation_data.get(nation_b, {}).get("claims", [])
        
        a_claims_b = 0
        b_claims_a = 0
        
        for prov in id_to_province.values():
            owner = prov.get("owner")
            if owner == nation_b:
                if nation_a in prov.get("cores", []) or prov["id"] in claims_a:
                    a_claims_b += 1
            elif owner == nation_a:
                if nation_b in prov.get("cores", []) or prov["id"] in claims_b:
                    b_claims_a += 1
        
        penalty_per_claim = abs(c.REL_MOD_PER_CLAIM)
        max_penalty = abs(c.REL_MOD_MAX_CLAIM_PENALTY)
        
        claim_penalty = min(max_penalty, (a_claims_b + b_claims_a) * penalty_per_claim)
        score -= claim_penalty
        
    return score


# A relation modifier is stored either as a bare int -- every modifier written
# before this existed, and every one in an old save -- or as a dict carrying how
# fast it fades and how long it lasts:
#
#     -40                                              decays 1/turn, as always
#     {"value": -40, "decay": 0, "turns": 60, ...}     durable: 60 turns, no fade
#
# Nothing migrates in place. An int keeps behaving exactly as it always has, for
# as long as it exists, and a mixed dict is fine. Grudges that actually last are
# what make a betrayal cost something later.
def modifier_value(entry):
    """The score contribution of a modifier, in either storage form."""
    if isinstance(entry, dict):
        try:
            return int(entry.get("value", 0))
        except (TypeError, ValueError):
            return 0
    try:
        return int(entry)
    except (TypeError, ValueError):
        return 0


def modifier_decay(entry):
    """How much this modifier fades toward zero per turn. 0 means never."""
    if isinstance(entry, dict):
        try:
            return max(0, int(entry.get("decay", 1)))
        except (TypeError, ValueError):
            return 1
    return 1


def modifier_turns(entry):
    """Turns left before it expires outright, or None for no expiry."""
    if isinstance(entry, dict) and entry.get("turns") is not None:
        try:
            return int(entry["turns"])
        except (TypeError, ValueError):
            return None
    return None


def add_temporary_modifier(nation_a, nation_b, mod_name, value, nation_data,
                           decay=1, turns=None, reason=""):
    """Adds or updates a temporary relation modifier. General opinions stack.

    decay/turns/reason are keyword arguments with the old behaviour as their
    defaults, so every existing call site is unchanged.
    """
    if nation_a not in nation_data: return
    mods = nation_data.setdefault(nation_a, {}).setdefault("temp_modifiers", {}).setdefault(nation_b, {})

    if mod_name == "general":
        value = modifier_value(mods.get("general", 0)) + value

    if decay == 1 and turns is None and not reason:
        # Plain form for a plain modifier, so saves stay readable and old builds
        # can still make sense of the common case.
        mods[mod_name] = value
    else:
        mods[mod_name] = {"value": value, "decay": decay, "turns": turns, "reason": reason}


def lerp_color(c1, c2, t):
    """Linearly interpolates between two RGB color tuples by factor t (0.0-1.0)."""
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))


def get_relation_color(score):
    """Returns a dynamic color mapped to the relation score (-200 to 200)."""
    score = max(-200, min(200, score))

    if score > 100:
        return lerp_color(c.COLOR_REL_POS, c.COLOR_REL_MAX_POS, (score - 100) / 100.0)
    elif score > 0:
        return lerp_color(c.COLOR_REL_NEU, c.COLOR_REL_POS, score / 100.0)
    elif score < -100:
        return lerp_color(c.COLOR_REL_NEG, c.COLOR_REL_MAX_NEG, (-score - 100) / 100.0)
    elif score < 0:
        return lerp_color(c.COLOR_REL_NEU, c.COLOR_REL_NEG, -score / 100.0)
        
    return c.COLOR_REL_NEU


def build_national_border_graph(map_data, id_to_province):
    """Builds the world adjacency graph is_nation_reachable walks.

    Nodes are nation names, plus one "WATER_<id>" node per sea tile. Derived
    purely from tile ownership and terrain, so a caller asking about several
    nations in a row should build this once and pass it to every call rather
    than paying for a full map sweep each time.
    """
    borders = {}

    def add_edge(u, v):
        if u not in borders: borders[u] = set()
        if v not in borders: borders[v] = set()
        borders[u].add(v)
        borders[v].add(u)

    for prov_id, prov in map_data.items():
        is_water = is_water_province(prov)
        owner = prov.get("owner")

        node_u = f"WATER_{prov_id}" if is_water else owner
        if not node_u: continue

        for n_id in prov.get("neighbors", []):
            n_prov = id_to_province.get(n_id)
            if not n_prov: continue

            n_is_water = is_water_province(n_prov)
            n_owner = n_prov.get("owner")

            node_v = f"WATER_{n_id}" if n_is_water else n_owner
            if not node_v: continue

            if node_u != node_v:
                add_edge(node_u, node_v)

    return borders


def is_nation_reachable(nation_a, target_nation, map_data, id_to_province, nation_data, borders=None):
    """Determines if a nation can physically reach another via land borders (including passable nations) or connected water."""
    friendly_a = queries.get_all_friendly_nations(nation_a, nation_data)
    at_war_a = set(get_enemies(nation_a, nation_data))

    friendly_b = queries.get_all_friendly_nations(target_nation, nation_data)
    at_war_b = set(get_enemies(target_nation, nation_data))

    target_faction = nation_data.get(target_nation, {}).get("faction", "")
    enemy_nations = {target_nation}
    if target_faction:
        enemy_nations.update(get_faction_members(target_faction, nation_data))

    passable_nations = set(friendly_a) | at_war_a | set(friendly_b) | at_war_b | enemy_nations

    if borders is None:
        borders = build_national_border_graph(map_data, id_to_province)

    visited = set(friendly_a)
    queue = collections.deque(friendly_a)

    while queue:
        curr = queue.popleft()

        if curr in enemy_nations:
            return True

        for neighbor in borders.get(curr, ()):
            if neighbor not in visited:
                is_water_node = str(neighbor).startswith("WATER_")
                if neighbor in enemy_nations:
                    return True
                if is_water_node or neighbor in passable_nations:
                    visited.add(neighbor)
                    queue.append(neighbor)

    return False


def is_ai_diplo_on_cooldown(sender, target, action, nation_data):
    """Checks if a specific proactive diplomatic action is on cooldown."""
    cooldowns = nation_data.get(sender, {}).get("diplo_cooldowns", {})
    target_cooldowns = cooldowns.get(target, {})
    return target_cooldowns.get(action, 0) != 0


def set_ai_diplo_cooldown(sender, target, action, nation_data, duration=None):
    """Sets a cooldown for a proactive diplomatic action to prevent spamming."""
    if duration is None:
        # Check if this is a war declaration to use the specific override
        if action == "WAR_DECLARATION":
            duration = c.AI_WAR_COOLDOWN
        else:
            duration = c.AI_DIPLO_COOLDOWN
    
    cooldowns = nation_data.setdefault(sender, {}).setdefault("diplo_cooldowns", {})
    target_cooldowns = cooldowns.setdefault(target, {})
    target_cooldowns[action] = duration


def get_valid_claim_targets(nation, target_nation, map_data):
    """Returns a list of province dicts owned by target_nation that can be claimed."""
    targets = []
    for prov in map_data.values():
        if prov.get("owner") == target_nation:
            targets.append(prov)
    return targets


def has_wargoal(nation, target_nation, nation_data, map_data=None):
    """Returns True if the nation has active claims on the target, or a justified wargoal."""
    if map_data:
        claims = nation_data.get(nation, {}).get("claims", [])
        for prov in map_data.values():
            # If target owns the tile, and the attacker either claimed it or has a core on it
            if prov.get("owner") == target_nation and (prov["id"] in claims or nation in prov.get("cores", [])):
                return True
    return target_nation in nation_data.get(nation, {}).get("wargoals", {})


def power_ratio(ai_nation, target_nation, map_data, nation_data, id_to_province=None):
    """(border_ratio, global_ratio) between two nations.

    The two quantities ai_thinks_it_can_win compares against its thresholds,
    exposed as numbers so a caller can reason in degrees instead of a yes/no --
    which is what lets a bold nation gamble on odds a careful one turns down.
    ai_thinks_it_can_win is written in terms of this so the two cannot drift.
    """
    if not id_to_province:
        id_to_province = {prov["id"]: prov for prov in map_data.values()}

    my_border_str, target_border_str = get_border_strength(ai_nation, target_nation, map_data, id_to_province, nation_data)

    # Prevent division by zero if they have literally no troops on the border
    target_border_str = max(1, target_border_str)

    # Consider total alliance strength, economy, and distractions
    my_alliance_str = get_alliance_military_strength(ai_nation, map_data, nation_data)
    target_alliance_str = get_alliance_military_strength(target_nation, map_data, nation_data)

    my_econ_power = get_economic_power(ai_nation, nation_data) / 100.0
    target_econ_power = get_economic_power(target_nation, nation_data) / 100.0

    # Factor in how distracted the target is by their existing wars
    target_distraction_str = get_combined_enemy_strength(target_nation, map_data, nation_data) * (c.AI_ENEMY_DISTRACTION_WEIGHT)

    # Add the target's distraction to our perceived power
    my_total_power = my_alliance_str + my_econ_power + target_distraction_str
    target_total_power = max(1.0, target_alliance_str + target_econ_power)

    return my_border_str / target_border_str, my_total_power / target_total_power


def ai_thinks_it_can_win(ai_nation, target_nation, map_data, nation_data, id_to_province=None):
    """Calculates if the AI believes it is strong enough to defeat the target (CTW)."""
    border_ratio, global_ratio = power_ratio(ai_nation, target_nation, map_data, nation_data, id_to_province)

    # AI needs local border superiority AND overall global viability
    return border_ratio >= c.AI_WAR_STRENGTH_THRESHOLD and global_ratio >= c.AI_GLOBAL_STRENGTH_THRESHOLD


def is_weaker_neighbor(ai_nation, target_nation, map_data, nation_data):
    """Returns True if the target nation's total power is significantly lower than the AI's."""
    my_alliance_str = get_alliance_military_strength(ai_nation, map_data, nation_data)
    my_econ_power = get_economic_power(ai_nation, nation_data) / 100.0
    my_total_power = my_alliance_str + my_econ_power
    
    target_alliance_str = get_alliance_military_strength(target_nation, map_data, nation_data)
    target_econ_power = get_economic_power(target_nation, nation_data) / 100.0
    target_total_power = max(1.0, target_alliance_str + target_econ_power)
    
    return target_total_power < (my_total_power * c.AI_WEAK_NEIGHBOR_STRENGTH_RATIO)


def will_ai_accept_peace(target_nation, proposer_nation, peace_type, map_data, nation_data):
    """DEPRECATED. Forwards to ai_opinion.accepts_peace, which is the real rule.

    This function's own logic refused any demand for claims unconditionally, so
    no AI war ever ended with territory changing hands -- and because the peace
    screen called this while the engine called accepts_peace, the screen could
    tell a player "the AI will REJECT this" and then watch the AI accept it. The
    body is gone rather than fixed: two implementations of one judgement is what
    caused the disagreement, and a second one would only drift again.

    Kept, with its signature untouched, because a mod may be calling it -- see
    the note in map_logic/ai/ai_world.py about mods shadowing this whole file.
    """
    from map_logic.ai import ai_opinion, ai_world

    world = ai_world.AIWorld(map_data or {}, nation_data,
                             {prov["id"]: prov for prov in (map_data or {}).values()})
    return ai_opinion.accepts_peace(world, target_nation, proposer_nation, peace_type)
