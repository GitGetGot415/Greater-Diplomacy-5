"""Technology and research queries, unit unlock lookups, and research-edit previews."""

import copy
import data.constants as c
from data.state_access import world_for, session_for
from data.queries.content import get_time_appropriate_research
from data.queries.unit_info import (
    get_base_unit_name,
    get_infantry_family_year,
    get_unit_research_requirement,
    get_unit_tier,
    is_unit_unlocked,
)
from data.queries.air import get_air_unit_traits
from data import queries


def apply_time_appropriate_research_to_map(map_screen, year):
    """Overwrites the map default and every living nation's research with the
    time-appropriate levels for `year`.

    Shared by the research editor's manual toggle and the date editor's
    auto-recompute (when "force_time_appropriate_research" is on), so the two
    can't drift into computing this differently.
    """
    world_state = world_for(map_screen)
    time_app_res = get_time_appropriate_research(year, context=map_screen)
    world_state.default_research = time_app_res.copy()
    for cid in queries.get_living_nations(world_state.map_data):
        world_state.nation_data[cid]["research"] = time_app_res.copy()
    return time_app_res


def get_total_turns(time_manager):
    """Calculates the total number of turns elapsed since the start of the scenario."""
    return time_manager.total_turns


def get_building_required_tech(b_name):
    """Maps building names to their respective research tree requirements."""
    if "Basic Factory" in b_name:
        return "basic_factory", 1
    if "Factory Lvl" in b_name:
        return "factory", int(b_name.split()[-1])
    if "Synthetic Refinery" in b_name:
        return "fuel_refining", int(b_name.split()[-1])
    if "Basic Recruitment" in b_name:
        return "basic_recruitment", 1
    if "Recruitment Building Lvl" in b_name:
        return "recruitment_buildings", int(b_name.split()[-1])
    return None, 0


def get_tech_display_name(tech_key, *, context=None):
    """Keep research labels independent of stable save/protocol IDs."""
    return queries.get_tech_tree(context).get(tech_key, {}).get("display_name", tech_key.replace("_", " ").title())


def get_tech_unlocks(tech_key, level, *, context=None):
    """Returns a list of strings detailing what this tech unlocks."""
    unlocks = []
    for target_key, target_level in get_tech_level_gate_unlocks(tech_key, level, context=context):
        name = get_tech_display_name(target_key, context=context)
        unlocks.append(f"Research prerequisite: {name}, level {target_level}")
    for bonus in queries.get_tech_tree(context).get(tech_key, {}).get("building_output_bonuses", []):
        targets = list(bonus.get("building_families", []))
        targets.extend(group.replace("_", " ").title() for group in bonus.get("building_groups", []))
        for resource, amount in bonus.get("outputs", {}).items():
            increase = ((1.0 + amount) ** level - 1.0) * 100
            unlocks.append(f"+{increase:g}% {resource.title()} Output: {', '.join(targets)}")
        for resource, amount in bonus.get("flat_outputs", {}).items():
            unlocks.append(f"+{amount * level:g} {resource.title()} Output: {', '.join(targets)}")
    bldg_lib = queries.get_building_library(context)
    for b_name in bldg_lib.keys():
        req_tech, req_lvl = queries.get_building_required_tech(b_name)
        if req_tech == tech_key and req_lvl == level:
            unlocks.append(b_name)
            
    # Hardcoded logic bonuses
    if tech_key == "bergius_process" and level == 1:
        unlocks.append(f"+{c.BERGIUS_FUEL_BONUS} Base Fuel/Turn")
    elif tech_key == "fuel_refining":
        limit = int(level * c.FUEL_REFINING_CONVERSION_PER_LVL * 100)
        unlocks.append(f"Max Mat-to-Fuel Conversion: {limit}%")
        
    if tech_key == "general_recruitment":
        bonus = c.GENERAL_RECRUITMENT_BONUS
        unlocks.append(f"+{bonus} Base Manpower/Tile")

    if tech_key == "resource_refining":
        mult = 1.0 + level * c.RESOURCE_REFINING_BONUS_PER_LVL
        unlocks.append(f"Resource Income x{mult:.1f}")

    if tech_key == "trucks" and level == 1:
        unlocks.append("Motorized Infantry (buildable up to your current Infantry tech)")
        unlocks.append("Naval units can now be loaded into Trucks")

    if tech_key == "armored_personnel_carriers" and level == 1:
        unlocks.append("Mechanized Infantry (buildable up to your current Infantry tech)")

    if tech_key == "infantry_fighting_vehicle" and level == 1:
        unlocks.append("Infantry Fighting Vehicle (buildable up to your current Infantry tech)")

    if tech_key == "submarine":
        unlocks.append("Invisible to neutral/enemy nations unless engaged in active combat")

    for name, stats in queries.get_unit_library(context).items():
        if (tech_key in c.DATED_UNIT_RESEARCH_TRACKS
                and get_unit_research_requirement(name, context=context) == (tech_key, level)):
            unlocks.append(name)
        if stats.get("air_role") and get_unit_research_requirement(name, context=context) == (tech_key, level):
            unlocks.extend(get_air_unit_traits(name, context=context))

    return unlocks


def get_upgrade_target(unit_type, player_research, unit_library, tech_tree, *, context=None):
    """Return the researched equipment stage or tier within the current family."""
    current = queries.get_unit_metadata(unit_type, unit_library, context=context)
    if current["tier_order"] <= 0:
        return None
    track = current["research"]["tech"]
    yearly = ("year" in current["research"] or
              any("minimum_year" in requirement for requirement in current["requirements"]))
    target = (get_infantry_family_year(track, player_research, tech_tree) if yearly
              else player_research.get(track, 0))
    if target is None or target <= 0:
        return None
    for name in unit_library:
        metadata = queries.get_unit_metadata(name, unit_library, context=context)
        if metadata["family"] != current["family"] or metadata["tier_order"] <= current["tier_order"]:
            continue
        level = metadata["tier_order"] if yearly else metadata["research"].get("level", 1)
        if level == target:
            return name
    return None


def get_best_preferred_unit(player_research, unit_library, preference_list, *, context=None):
    """Find the highest available tier in the existing family preference order."""
    for family in reversed(preference_list):
        candidates = [name for name in unit_library
                      if get_base_unit_name(name, unit_library, context=context) == family
                      and is_unit_unlocked(name, player_research, unit_library, context=context)]
        if candidates:
            return max(candidates, key=lambda name: get_unit_tier(name, unit_library, context=context))
    return None


def _best_unit_for_role(player_research, unit_library, role, preference_list, *, context=None):
    """Highest-scoring unlocked unit filling a role, by stats rather than by name.

    These two used to walk a hand-written list in constants.py backwards, so the
    last entry won: Main Battle Tanks and Destroyers the moment either was
    researched, whatever they cost, and Heavy Tanks, Artillery, Submarines and
    Carriers never. They keep their signatures because the random map generator
    seeds starting armies with them and mods may call them, but the answer now
    comes from map_logic.ai.ai_unit_eval like every other unit decision.

    The old preference list survives as the fallback for a caller with no
    research at all, where there is nothing to score.
    """
    from map_logic.ai import ai_unit_eval

    candidates = ai_unit_eval.buildable_units(player_research, unit_library)
    if candidates:
        prices = {res: 1.0 for res in ai_unit_eval.RESOURCES}
        ctx = ai_unit_eval.context(prices, volley=1000.0, stack=c.LANE_SLOTS_TYPICAL)
        best = ai_unit_eval.best_by_role(
            ai_unit_eval.evaluate(candidates, unit_library, ctx), role)
        if best:
            return best
    return get_best_preferred_unit(player_research, unit_library, preference_list, context=context)


def get_best_offensive_unit(player_research, unit_library, *, context=None):
    """Finds the best offensive unit the nation has unlocked."""
    from map_logic.ai import ai_unit_eval
    return _best_unit_for_role(player_research, unit_library,
                               ai_unit_eval.ROLE_ASSAULT, c.AI_OFFENSIVE_UNIT_PREFERENCE, context=context)


def get_best_naval_unit(player_research, unit_library, *, context=None):
    """Finds the best naval unit the nation has unlocked."""
    from map_logic.ai import ai_unit_eval
    return _best_unit_for_role(player_research, unit_library,
                               ai_unit_eval.ROLE_NAVAL, c.AI_NAVAL_UNIT_PREFERENCE, context=context)


REQ_GROUP_KEYS = ("OR", "AND")


def get_tech_level_gate_unlocks(tech_key, level, *, context=None):
    """Return first research levels and added level gates that name this technology level."""
    unlocks = []
    for key, data in queries.get_tech_tree(context).items():
        gates = [(1, data.get("req", {}))]
        gates.extend((int(target), reqs) for target, reqs in data.get("level_reqs", {}).items())
        for target, requirements in gates:
            if ((key, target) not in unlocks
                    and any(dependency == tech_key and tech_requirement_level(required, target) == level
                            for dependency, required in queries.walk_tech_requirements(requirements))):
                unlocks.append((key, target))
    return unlocks


def get_tech_requirements(tech_data, target_level=1):
    """Combine base requirements with gates at or below the target level."""
    requirements = [tech_data.get("req", {})]
    requirements.extend(reqs for level, reqs in tech_data.get("level_reqs", {}).items()
                        if int(level) <= target_level)
    requirements = [reqs for reqs in requirements if reqs]
    if not requirements:
        return {}
    return requirements[0] if len(requirements) == 1 else {"AND": requirements}


def tech_requirement_level(value, target_level):
    """Resolve a fixed prerequisite level or a MATCH_LEVEL expression."""
    if isinstance(value, str) and value.startswith("MATCH_LEVEL"):
        offset = value[len("MATCH_LEVEL"):]
        return target_level + (int(offset) if offset else 0)
    return value


def check_tech_requirements(res_levels, reqs, target_lvl=1):
    """Centralized tech requirement checker.

    A plain {tech: lvl, ...} mapping means every entry has to be met. "OR" and
    "AND" each take a LIST of such mappings and may be nested inside each other:
        {"AND": [{"heavy_tank": 4}, {"OR": [{"light_tank": 1}, {"armored_car": 1}]}]}
    Anything that is not a group key is read as a tech name.
    """
    if not reqs: return True

    if "OR" in reqs:
        return any(check_tech_requirements(res_levels, sub, target_lvl) for sub in reqs["OR"])
    if "AND" in reqs:
        return all(check_tech_requirements(res_levels, sub, target_lvl) for sub in reqs["AND"])
    return all(res_levels.get(k, 0) >= tech_requirement_level(v, target_lvl) for k, v in reqs.items())


def edited_research_levels(research, tech_key, level, researched, tech_tree=None, *, context=None):
    """Grant prerequisites or remove dependent levels without changing the input."""
    tree = queries.get_tech_tree(context) if tech_tree is None else tech_tree
    if not isinstance(tech_key, str) or tech_key not in tree:
        raise ValueError("This technology is not available in this map.")
    if isinstance(level, bool) or not isinstance(level, int) or not 1 <= level <= tree[tech_key]["max_lvl"]:
        raise ValueError("Choose a technology level within this map's research tree.")
    if researched is None:
        researched = research.get(tech_key, 0) < level
    result = dict(research)

    def grant(key, required, state, visiting, verified):
        if required <= 0 or verified.get(key, 0) >= required:
            return
        if key not in tree or required > tree[key]["max_lvl"]:
            raise ValueError("A research prerequisite is unavailable in this map.")
        if key in visiting:
            raise ValueError("Research prerequisites contain a cycle.")
        for target in range(verified.get(key, 0) + 1, required + 1):
            satisfy(get_tech_requirements(tree[key], target), target, state, visiting | {key}, verified)
            state[key] = max(state.get(key, 0), target)
            verified[key] = target

    def satisfy(requirements, target, state, visiting, verified):
        if "OR" in requirements:
            candidates = []
            for branch in requirements["OR"]:
                candidate = dict(state)
                candidate_verified = dict(verified)
                try:
                    satisfy(branch, target, candidate, visiting, candidate_verified)
                except ValueError:
                    continue
                added = sum(max(0, value - state.get(key, 0)) for key, value in candidate.items())
                candidates.append((added, candidate, candidate_verified))
            if not candidates:
                raise ValueError("No research prerequisite branch is available in this map.")
            _, chosen, chosen_verified = min(candidates, key=lambda item: item[0])
            state.update(chosen)
            verified.update(chosen_verified)
        elif "AND" in requirements:
            for branch in requirements["AND"]:
                satisfy(branch, target, state, visiting, verified)
        else:
            for key, value in requirements.items():
                grant(key, tech_requirement_level(value, target), state, visiting, verified)

    if researched:
        grant(tech_key, level, result, set(), {})
    else:
        result[tech_key] = min(result.get(tech_key, 0), level - 1)
        affected = {tech_key}
        while True:
            changed = False
            for key, data in tree.items():
                requirements = get_tech_requirements(data, data["max_lvl"])
                if not any(dependency in affected for dependency, _ in queries.walk_tech_requirements(requirements)):
                    continue
                current = result.get(key, 0)
                for target in range(1, current + 1):
                    if not queries.check_tech_requirements(result, get_tech_requirements(data, target), target):
                        result[key] = target - 1
                        affected.add(key)
                        changed = True
                        break
            if not changed:
                break
    return result


def can_edit_starting_research(map_screen, country_id):
    """Starting research edits belong to a local map editor and a living country."""
    return bool(getattr(session_for(map_screen), "is_editor", False)
                and can_edit_country_research(map_screen, country_id))


def can_edit_country_research(map_screen, country_id):
    """Allow direct research changes in a local editor or permitted spectator game."""
    world_state = world_for(map_screen)
    # Optional mode flags support lightweight editor maps and older callers.
    return bool((getattr(session_for(map_screen), "is_editor", False)
                 or (getattr(session_for(map_screen), "player_country", None) == "Spectator"
                     and c.SPECTATOR_CAN_EDIT_RESEARCH))
                and not getattr(session_for(map_screen), "tactical_mode", False)
                and not getattr(session_for(map_screen), "multiplayer_mode", False)
                and not getattr(session_for(map_screen), "realtime_multiplayer", False)
                and isinstance(country_id, str)
                and country_id in world_state.nation_data
                and country_id in queries.get_living_nations(world_state.map_data))


def toggle_starting_research(map_screen, country_id, tech_key, level):
    """Apply a map editor click through the shared country research editor."""
    if not can_edit_starting_research(map_screen, country_id):
        raise ValueError("Starting research can only be changed for a country in the local map editor.")
    return toggle_country_research(map_screen, country_id, tech_key, level)


def toggle_country_research(map_screen, country_id, tech_key, level):
    """Apply a permitted click and clear projects invalidated by changed research."""
    world_state = world_for(map_screen)
    if not can_edit_country_research(map_screen, country_id):
        raise ValueError("Research editing requires a local map editor or permitted spectator.")
    country = world_state.nation_data[country_id]
    state, _ = preview_country_research_edit(country, tech_key, level, context=map_screen)
    changed = {key for key, value in state["research"].items() if value != country.get("research", {}).get(key, 0)}
    _apply_country_research_state(country, state)
    return changed


RESEARCH_EDIT_FIELDS = ("research", "research_queue", "research_progress", "current_research")


def country_research_edit_state(country):
    """Copy research fields without retaining references to the live country."""
    return {key: copy.deepcopy(country[key]) for key in RESEARCH_EDIT_FIELDS if key in country}


def preview_country_research_edit(country, tech_key, level, *, context=None):
    """Return changed research fields and the projects whose progress is discarded."""
    country = country_research_edit_state(country)
    research = country.get("research", {})
    tree = queries.get_tech_tree(context)
    result = edited_research_levels(research, tech_key, level, None, tree, context=context)
    changed = {key for key in result if result[key] != research.get(key, 0)}
    research = country.setdefault("research", {})
    research.update(result)
    invalidated = set(changed)
    pending = {project["tech_name"] for project in country.get("research_queue", [])}
    pending.update(country.get("research_progress", {}))
    current_research = country.get("current_research")
    if isinstance(current_research, str):
        pending.add(current_research)
    for key in pending:
        if key in tree and (research.get(key, 0) >= tree[key]["max_lvl"]
                           or not queries.check_tech_requirements(research, get_tech_requirements(tree[key], research.get(key, 0) + 1),
                                                          research.get(key, 0) + 1)):
            invalidated.add(key)
    if "research_queue" in country:
        country["research_queue"][:] = [project for project in country["research_queue"]
                                        if project["tech_name"] not in invalidated]
    for key in invalidated:
        country.get("research_progress", {}).pop(key, None)
    if isinstance(current_research, str) and current_research in invalidated:
        country["current_research"] = None
    return country, invalidated & pending


def _apply_country_research_state(country, state):
    """Apply research fields while preserving existing dictionary and list references."""
    for key in RESEARCH_EDIT_FIELDS:
        if key not in state:
            continue
        value = copy.deepcopy(state[key])
        current = country.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            current.clear()
            current.update(value)
        elif isinstance(current, list) and isinstance(value, list):
            current[:] = value
        else:
            country[key] = value


def confirm_country_research_edit(map_screen, country_id, original, draft):
    """Save a permitted spectator draft only if the live research is unchanged."""
    world_state = world_for(map_screen)
    if (getattr(session_for(map_screen), "player_country", None) != "Spectator"
            or getattr(session_for(map_screen), "is_editor", False)
            or not can_edit_country_research(map_screen, country_id)):
        raise ValueError("Research editing requires a permitted local spectator.")
    country = world_state.nation_data[country_id]
    if country_research_edit_state(country) != original:
        raise ValueError("Country research changed while editing. Cancel and reopen this country's research.")
    _apply_country_research_state(country, draft)


def walk_tech_requirements(reqs):
    """Yields every (tech_name, required_level) leaf in a req block, at any nesting depth."""
    for key, val in (reqs or {}).items():
        if key in REQ_GROUP_KEYS:
            for sub in val:
                yield from walk_tech_requirements(sub)
        else:
            yield key, val


def strip_disabled_tech_requirements(reqs, disabled_techs):
    """Rebuilds a req block with every leaf naming a disabled tech bypassed
    (treated as already satisfied), so a scenario that disables a unit/building
    never leaves some other tech permanently unresearchable behind it.

    Mirrors the OR/AND walk in check_tech_requirements/walk_tech_requirements,
    but returns a smaller req tree instead of a bool: a satisfied AND clause is
    dropped, and an OR satisfied by one clause collapses the whole group.
    """
    if not reqs or not disabled_techs:
        return reqs or {}

    if "OR" in reqs:
        subs = [strip_disabled_tech_requirements(sub, disabled_techs) for sub in reqs["OR"]]
        if any(not sub for sub in subs):
            return {}
        return {"OR": subs}

    if "AND" in reqs:
        subs = [strip_disabled_tech_requirements(sub, disabled_techs) for sub in reqs["AND"]]
        subs = [sub for sub in subs if sub]
        if not subs:
            return {}
        if len(subs) == 1:
            return subs[0]
        return {"AND": subs}

    return {k: v for k, v in reqs.items() if k not in disabled_techs}


def get_exact_year(time_manager):
    """Calculates the exact fractional year based on the game's 360-day calendar."""
    return time_manager.year + (time_manager.month_index / 12.0) + (time_manager.day / 360.0)


def get_research_multiplier(current_exact_year, target_year):
    """Calculates the ahead-of-time penalty multiplier."""
    years_ahead = target_year - current_exact_year
    if years_ahead > 0:
        return 0.5 ** years_ahead
    return 1.0


def has_free_research_slots(nation, nation_data):
    """Returns True if the nation is researching fewer than c.RESEARCH_SLOTS techs."""
    # Prevent the research notification from popping up for the Spectator or Ocean
    if nation in c.UNPLAYABLE_NATIONS:
        return False

    queue = nation_data.get(nation, {}).get("research_queue", [])
    return len(queue) < c.RESEARCH_SLOTS
