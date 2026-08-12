import data.constants as c
from data import queries
from map_logic.ai import ai_tech_eval, ai_unit_eval, ai_world

def process_ai_research(map_screen):
    """Automates research queueing for AI nations."""
    # REPLACED DISK I/O WITH CACHED QUERIES
    tech_tree = queries.get_tech_tree()
    if not tech_tree:
        return

    unit_library = queries.get_unit_library()
    building_library = queries.get_building_library()
    all_econ = queries.calculate_all_economies(map_screen.map_data, map_screen.nation_data)
    world = ai_world.for_screen(map_screen)

    ai_nations = queries.get_active_ai_nations(map_screen)

    for ai_name in ai_nations:
        data = map_screen.nation_data[ai_name]

        queue = data.setdefault("research_queue", [])
        
        # AI can only research c.RESEARCH_SLOTS things at a time
        if len(queue) >= c.RESEARCH_SLOTS:
            continue

        res_levels = data.setdefault("research", {})

        available_techs = []
        for tech_key, t_data in tech_tree.items():
            cur_lvl = res_levels.get(tech_key, 0)
            max_lvl = t_data["max_lvl"]
            
            # Skip if fully researched
            if cur_lvl >= max_lvl:
                continue
            
            # Skip if already in queue
            is_researching = any(q["tech_name"] == tech_key for q in queue)
            if is_researching:
                continue

            lvl_to_research = cur_lvl + 1
            
            # --- THE FIX: Use the centralized query that knows how to do math ---
            reqs = t_data.get("req", {})
            if not queries.check_tech_requirements(res_levels, reqs, lvl_to_research):
                continue

            # Fetch the historical year to avoid massive ahead-of-time penalties
            years = t_data.get("years", [1900] * max_lvl)
            target_year = years[min(lvl_to_research - 1, len(years)-1)]
            
            is_new_tech = cur_lvl == 0

            available_techs.append((tech_key, target_year, t_data.get("cost", 300), is_new_tech))

        # Order by what each tech is actually worth to THIS nation right now --
        # how much better the unit it unlocks is than what we already field, or
        # what the building or bonus adds, priced against our own scarcity.
        #
        # The old sort was (years overdue, is it new, cost). Every already
        # historical tech ties at zero on the first term, so it came down to
        # "cheapest brand-new tech", with no notion of whether the thing it
        # unlocked was any use: an island power researched armour and a nation
        # being overrun researched recruitment buildings. The historical-pace
        # term survives, but as a multiplier on value rather than as the key.
        current_year = map_screen.time_manager.year
        econ = all_econ.get(ai_name, {})
        available_techs = _rank_for_nation(
            available_techs, ai_name, data, econ, world,
            unit_library, building_library, current_year)

        _fill_queue(queue, available_techs, data.get("research", {}),
                    unit_library, tech_tree)


def _fill_queue(queue, ranked, research, unit_library, tech_tree):
    """Takes the best techs, but never leaves the army entirely unresearched.

    Economic techs are repeatable and compound, so on raw value they win every
    slot for the whole game -- which is a defensible read of this economy and a
    terrible way to play a war. At least one slot is reserved for the best tech
    that actually unlocks a unit, so armies keep modernising while industry
    grows. Which military tech that is still comes from the valuation, so a
    nation facing armour and a nation facing militia make different choices.
    """
    reserved = c.AI_RESEARCH_MILITARY_SLOTS
    military_taken = any(
        ai_tech_eval.units_unlocked_by(q["tech_name"], research, unit_library)
        for q in queue)

    while len(queue) < c.RESEARCH_SLOTS and ranked:
        slots_left = c.RESEARCH_SLOTS - len(queue)
        need_military = (not military_taken) and slots_left <= reserved

        pick = None
        if need_military:
            pick = next((t for t in ranked
                         if ai_tech_eval.units_unlocked_by(t[0], research, unit_library)), None)
        if pick is None:
            pick = ranked[0]

        ranked.remove(pick)
        if ai_tech_eval.units_unlocked_by(pick[0], research, unit_library):
            military_taken = True

        queue.append({"tech_name": pick[0], "points_remaining": pick[2]})


def _rank_for_nation(available_techs, ai_name, data, econ, world,
                     unit_library, building_library, current_year):
    """Best-first order of the techs this nation could start next."""
    if not available_techs:
        return available_techs

    research = data.get("research", {})
    candidates = ai_unit_eval.buildable_units(research, unit_library)
    volley, enemy_def, enemy_stack = ai_unit_eval.threat_profile(
        world, ai_name, unit_library, candidates)
    prices = ai_unit_eval.resource_prices(econ, data)
    frontline = len(world.land_border_tiles.get(ai_name, ())) if world else 1

    ctx = ai_unit_eval.context(
        prices, volley=volley, stack=max(1.0, c.LANE_SLOTS_TYPICAL),
        enemy_def=enemy_def, enemy_stack=enemy_stack,
        frontline=max(1, frontline),
        coast=len(world.coast_tiles.get(ai_name, ())) if world else 0,
        budget=ai_unit_eval.spending_budget(econ, data, prices))

    built = ai_tech_eval.built_levels(
        world.provs_by_owner.get(ai_name, ()) if world else (), building_library)

    return ai_tech_eval.rank_available(
        available_techs, research, unit_library, building_library, ctx,
        set(candidates), current_year, econ.get("total_inc", {}), built)