import random
import data.constants as c
from data import queries
from map_logic.ai import ai_unit_eval, ai_world


def _unit_costs(unit_library, unit_name):
    """(stats, materials, manpower, fuel) for one unit type.

    The purchase loop below re-reads these every time it changes its mind about
    what to build, which it does up to three times per nation per turn.
    """
    stats = unit_library.get(unit_name, {})
    return (stats, stats.get("cost_materials", 0),
            stats.get("cost_manpower", 0), stats.get("cost_fuel", 0))


# ============================================================================ #
#              process_ai_economy_decisions PHASE HELPERS                      #
# ============================================================================ #
# One nation's economy pass runs a fixed pipeline: work out its upkeep ratios
# and army-composition targets, tally what it already has (disbanding or
# panic-building along the way), spend down its budget on units, then spend
# whatever's left on cores and buildings. Several of these phases share
# mutable running totals (upkeep, role counts, the unit valuation) that later phases
# both read and adjust, so they're threaded through as a single `state` dict
# rather than a long, easy-to-misorder parameter list.

def _deficit_list(upkeep, income, targets):
    """Which of the three resources this nation is overspending on.

    `targets` is keyed the same way `upkeep` and `income` are, and the answer
    comes back keyed by the unit stat that costs the resource, since every
    caller wants to ask "does this unit cost something I am short of".
    """
    stat_for = {"manpower": "cost_manpower", "materials": "cost_materials",
                "fuel": "cost_fuel"}
    over = []
    for res, stat in stat_for.items():
        inc = income.get(res, 0)
        ratio = upkeep.get(res, 0) / inc if inc > 0 else 1.0
        if ratio > targets[res]:
            over.append(stat)
    return over


def _disband_peacetime_militia(ai_name, my_provs, at_war):
    """Militia are for wars. At peace, stand them down.

    Runs after the purchase loop rather than before it, and skips any type on
    order, because the purchase loop is name-blind and buys militia whenever its
    own valuation rates them worth buying -- so from the other side of the pass
    this rule was scrapping militia the nation had just paid for. Reading the
    queue beforehand would have read last turn's.
    """
    if at_war:
        return
    on_order = {q.get("unit_type") for prov in my_provs
                for q in prov.get("unit_queue", []) if q.get("unit_type")}
    for prov in my_provs:
        for u in prov.get("units", []):
            if (u.get("owner") == ai_name
                    and queries.get_base_unit_name(u.get("type", "")) == "Militia"
                    and u.get("type", "") not in on_order
                    and u.get("order", {}).get("type") != "DISBAND"):
                u["order"] = {"type": "DISBAND", "turns_left": 1}


def _compute_economy_ratios(map_screen, ai_name, data, my_provs, econ, unit_library):
    """Section 1: upkeep-vs-income ratios (including the pending build queue,
    so the AI doesn't bankrupt itself on units that haven't spawned yet) and
    which resources are in deficit."""
    at_war = len(data.get("at_war_with", [])) > 0
    war_mult = c.AI_WAR_UPKEEP_MULTIPLIER if at_war else 1.0

    target_man = c.AI_UPKEEP_TARGETS["manpower"] * war_mult
    target_mat = c.AI_UPKEEP_TARGETS["materials"] * war_mult
    target_fuel = c.AI_UPKEEP_TARGETS["fuel"] * war_mult

    inc_mat = econ["total_inc"]["materials"]
    upk_mat = econ["upkeep"]["materials"]
    inc_man = econ["total_inc"]["manpower"]
    upk_man = econ["upkeep"]["manpower"]
    inc_fuel = econ["total_inc"]["fuel"]
    upk_fuel = econ["upkeep"]["fuel"]

    income = {"manpower": inc_man, "materials": inc_mat, "fuel": inc_fuel}
    targets = {"manpower": target_man, "materials": target_mat, "fuel": target_fuel}

    # What the army standing on the map costs today, before anything on order.
    # The disband decision keys off this and only this: counting the queue there
    # made a nation delete real units to fund units that had not arrived yet,
    # and then delete those too once they did.
    standing_deficits = _deficit_list(
        {"manpower": upk_man, "materials": upk_mat, "fuel": upk_fuel}, income, targets)

    # --- THE FIX: Include Pending Queue in Upkeep Projections ---
    # Prevents the AI from bankupting itself on units that haven't spawned yet
    for prov in my_provs:
        for q in prov.get("unit_queue", []):
            q_type = q.get("unit_type")
            if q_type:
                q_upkeep = queries.get_unit_upkeep(unit_library.get(q_type, {}))
                upk_man += q_upkeep["manpower"]
                upk_mat += q_upkeep["materials"]
                upk_fuel += q_upkeep["fuel"]
    # ------------------------------------------------------------

    ratio_man = upk_man / inc_man if inc_man > 0 else 1.0
    ratio_mat = upk_mat / inc_mat if inc_mat > 0 else 1.0
    ratio_fuel = upk_fuel / inc_fuel if inc_fuel > 0 else 1.0

    deficits = _deficit_list(
        {"manpower": upk_man, "materials": upk_mat, "fuel": upk_fuel}, income, targets)

    return {
        "at_war": at_war,
        "target_man": target_man, "target_mat": target_mat, "target_fuel": target_fuel,
        "inc_man": inc_man, "inc_mat": inc_mat, "inc_fuel": inc_fuel,
        "upk_man": upk_man, "upk_mat": upk_mat, "upk_fuel": upk_fuel,
        "ratio_man": ratio_man, "ratio_mat": ratio_mat, "ratio_fuel": ratio_fuel,
        "deficits": deficits,
        "standing_deficits": standing_deficits,
    }


def _update_conscription_slider(data, state):
    """If AI has excess manpower but needs materials, convert manpower to
    materials. 1.0 = keep all, 0.0 = convert all.

    The first branch used to be "save up for a tank we are below quota on".
    There is no quota any more -- the purchase loop buys what is worth the most
    and stops when it stops being worth it -- so the slider keys purely off the
    upkeep ratios, which is what the remaining branches always did.
    """
    ratio_mat, target_mat = state["ratio_mat"], state["target_mat"]
    ratio_man, target_man = state["ratio_man"], state["target_man"]

    if ratio_mat > target_mat and ratio_man < target_man and data.get("manpower", 0) > c.AI_CONSCRIPTION_MIN_MANPOWER:
        data["conscription_slider"] = 0.5 # Convert 50%
    elif (data.get("manpower", 0) > c.AI_CONSCRIPTION_PANIC_MANPOWER and data.get("materials", 0) < c.AI_CONSCRIPTION_PANIC_MATERIALS) or data.get("manpower", 0) > c.AI_CONSCRIPTION_EMERGENCY_MANPOWER:
        data["conscription_slider"] = 0.25 # Emergency: Convert 75%
    else:
        data["conscription_slider"] = 1.0 # Normal (keep 100%)


def _update_fuel_conversion_slider(data, state):
    """Fetches this AI's legal maximum materials->fuel conversion and decides
    how much of it to actually use this turn.

    The tank-quota branch is gone with the quota; what is left is the ratio
    logic, which now pairs naturally with unit pricing -- converting materials
    into fuel makes fuel cheaper, which makes fuel-burning units score better
    on the next pass without either side knowing about the other.
    """
    ratio_fuel, target_fuel = state["ratio_fuel"], state["target_fuel"]
    ratio_mat, target_mat = state["ratio_mat"], state["target_mat"]

    max_conversion = queries.get_max_fuel_conversion(data)

    if max_conversion > 0:
        if ratio_fuel > target_fuel and ratio_mat < target_mat and data.get("materials", 0) > c.AI_CONVERSION_MIN_MATERIALS:
            data["mat_to_fuel_slider"] = max_conversion * 0.5 # Convert using 50% of their LEGAL MAXIMUM capability
        elif (data.get("materials", 0) > c.AI_CONVERSION_PANIC_MATERIALS and data.get("fuel", 0) < c.AI_CONVERSION_PANIC_FUEL) or data.get("materials", 0) > c.AI_CONVERSION_EMERGENCY_MATERIALS:
            data["mat_to_fuel_slider"] = max_conversion # Emergency: Maximize production safely
        else:
            data["mat_to_fuel_slider"] = 0.0
    else:
        data["mat_to_fuel_slider"] = 0.0


def _is_frontline(map_screen, ai_name, prov):
    """Whether a province is in combat or has an enemy standing next door.

    Same two questions the panic-militia pass asks, in the same order, since
    "somewhere the war is" is one idea and not two.
    """
    if queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data):
        return True
    for n_id in prov.get("neighbors", []):
        n_prov = map_screen.id_to_province.get(n_id)
        if not n_prov:
            continue
        for u in n_prov.get("units", []):
            if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data):
                return True
    return False


def _disband_worst_unit_if_deficit(map_screen, data, my_provs, ai_name, deficits,
                                   unit_library, values=None):
    """If any resource is in deficit, gives up the one unit worth least to this
    nation that costs a resource it is short of.

    It used to rank by raw `attack`, which is not what the AI buys by: the
    purchase loop takes the argmax of ai_unit_eval's marginal score, so a nation
    would pay for the unit its evaluator rated best and then delete that same
    unit as its "worst" -- Japan, the German Reich and France were each buying
    and disbanding one type in the same turn. Selling by the valuation it buys
    with is the whole of the fix; obsolescence stays the first key, because that
    part was always right.

    Two things it will not do, both of which it used to:

      - touch a unit that is fighting or has an enemy next door. Nothing here
        ever looked at where a unit was standing, which is why they went missing
        off the front line. If every candidate is at the front, give up nothing:
        losing the war costs more than the deficit does.
      - delete a type this nation is currently producing. Whatever the scores
        say, paying for a unit and scrapping its twin in one turn is incoherent.
    """
    if not deficits:
        return

    values = values or {}
    on_order = {q.get("unit_type") for prov in my_provs
                for q in prov.get("unit_queue", []) if q.get("unit_type")}

    candidates = []
    for prov in my_provs:
        if _is_frontline(map_screen, ai_name, prov):
            continue
        for u in prov.get("units", []):
            if u.get("owner") != ai_name or u.get("order", {}).get("type") == "DISBAND":
                continue
            u_type = u.get("type", "")
            if u_type in on_order:
                continue
            stats = unit_library.get(u_type, {})
            if any(stats.get(res, 0) > 0 for res in deficits):
                candidates.append((u, u_type, stats))

    if not candidates:
        return

    res_levels = data.get("research", {})
    def sort_key(item):
        u, u_type, stats = item
        is_obs = queries.is_unit_obsolete(u_type, res_levels)
        value = values.get(u_type)
        # Outdated units (is_obs=True) have priority (0). Then the one the
        # nation's own valuation rates lowest. An unscored type sorts first
        # among its peers, being one the evaluator would never have bought.
        return (0 if is_obs else 1, value.score if value else 0.0, u_type)

    candidates.sort(key=sort_key)

    # Disband the worst unit
    worst_unit = candidates[0][0]
    worst_unit["order"] = {"type": "DISBAND", "turns_left": 1}


def _panic_militia_and_tally_forces(map_screen, ai_name, data, my_provs, unit_library, state, roles):
    """Section: per-province pass that clears losing tiles' build queues,
    panic-queues a Militia on any core threatened by an adjacent enemy, and
    tallies current + queued forces (by role) and land/sea border counts."""
    role_counts = {}
    land_border_count = 0
    sea_border_count = 0

    for prov in my_provs:
        in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)
        has_factory = queries.has_industry(prov)

        # 1. Clear queues on tiles in active combat if we are losing
        if in_combat:
            friendly_nations = queries.get_all_friendly_nations(ai_name, map_screen.nation_data)
            my_units = [u for u in prov.get("units", []) if u.get("owner") in friendly_nations]
            enemy_units = [u for u in prov.get("units", []) if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data)]

            my_str = sum(queries.calculate_unit_strength(u) for u in my_units)
            enemy_str = sum(queries.calculate_unit_strength(u) for u in enemy_units)

            if enemy_str > my_str:
                while prov.get("unit_queue"):
                    item = prov["unit_queue"].pop(0)
                    if "refund" in item: queries.refund_resources(data, item["refund"])
                while prov.get("building_queue"):
                    item = prov["building_queue"].pop(0)
                    if "refund" in item: queries.refund_resources(data, item["refund"])

            continue # Skip panic militia check since it's already in combat and can't build anyway

        # 2. Panic Militia
        if has_factory and queries.has_core(ai_name, prov):
            enemy_adjacent = False
            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if not n_prov: continue
                # Are there enemy units here?
                for u in n_prov.get("units", []):
                    if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data):
                        enemy_adjacent = True
                        break
                if enemy_adjacent: break

            if enemy_adjacent:
                queue = prov.get("unit_queue", [])
                safe_to_panic = True

                if queue:
                    first_item = queue[0]
                    u_type = first_item.get("unit_type", "")
                    is_naval = queries.is_naval_unit(u_type) if u_type else False
                    turns = first_item.get("turns_remaining", 999)

                    if not is_naval and turns <= 1:
                        safe_to_panic = False # Let the ground unit finish!

                militia_name = queries.get_best_preferred_unit(data.get("research", {}), unit_library, ["Militia"]) or "Militia I"
                militia_stats = unit_library.get(militia_name, {})
                militia_time = militia_stats.get("production_time", 1)

                if safe_to_panic and militia_time == 1 and (not queue or queries.get_base_unit_name(queue[0].get("unit_type", "")) != "Militia"):
                    # Cancel existing queue
                    while queue:
                        item = queue.pop(0)
                        if "refund" in item: queries.refund_resources(data, item["refund"])

                    # Queue Militia
                    c_mat = militia_stats.get("cost_materials", 0)
                    c_man = militia_stats.get("cost_manpower", 0)
                    c_fuel = militia_stats.get("cost_fuel", 0)

                    if data.get("materials", 0) >= c_mat and data.get("manpower", 0) >= c_man and data.get("fuel", 0) >= c_fuel:
                        data["materials"] -= c_mat
                        data["manpower"] -= c_man
                        data["fuel"] -= c_fuel

                        # Adjust upkeep tracking
                        militia_upkeep = queries.get_unit_upkeep(militia_stats)
                        state["upk_man"] += militia_upkeep["manpower"]
                        state["upk_mat"] += militia_upkeep["materials"]
                        state["upk_fuel"] += militia_upkeep["fuel"]
                        militia_role = roles.get(militia_name, ai_unit_eval.ROLE_LINE)
                        role_counts[militia_role] = role_counts.get(militia_role, 0) + 1

                        order = {
                            "unit_type": militia_name,
                            "turns_remaining": max(1, militia_stats.get("production_time", 1)),
                            "refund": {"cost_materials": c_mat, "cost_manpower": c_man, "cost_fuel": c_fuel}
                        }
                        prov.setdefault("unit_queue", []).append(order)

        # Count what we have and what is already on order, together --
        # the two loops applied the same rule and differed only in which
        # key holds the unit's name. Bucketed by the role the unit's own stats
        # put it in, rather than by ai_force_category's substring match on the
        # name, so a renamed or newly added unit counts as whatever it is.
        standing = [u.get("type", "") for u in prov.get("units", [])
                    if u.get("owner") == ai_name]
        ordered = [q.get("unit_type", "") for q in prov.get("unit_queue", [])]
        for u_type in standing + ordered:
            role = roles.get(u_type)
            if role:
                role_counts[role] = role_counts.get(role, 0) + 1

        # Check neighbors to determine land/sea ratios
        is_land_border = False
        is_coast = False
        for n_id in prov.get("neighbors", []):
            n_prov = map_screen.id_to_province.get(n_id)
            if n_prov:
                if n_prov.get("terrain") in c.OCEAN_TERRAINS:
                    is_coast = True
                elif n_prov.get("owner") != ai_name and n_prov.get("owner") not in c.WATER_NATIONS:
                    is_land_border = True

        if is_land_border:
            land_border_count += 1
        if is_coast:
            sea_border_count += 1

    return {
        "role_counts": role_counts,
        "land_border_count": land_border_count,
        "sea_border_count": sea_border_count,
    }


def _naval_need(land_border_count, sea_border_count):
    """How many warships this nation's coastline justifies.

    A count, where this used to be a percentage of the whole army. The
    percentage had to be enforced by buying ships first whenever the fleet was
    below quota; a count is just another role target, so ships compete on value
    against everything else through the same marginal loop -- and an island
    nation ends up with a fleet because its coastline is long, not because a
    ratio said so.

    The tiny-coast rule survives: two beach tiles and a land war on the other
    side is not a reason to build a navy.
    """
    if sea_border_count <= 0:
        return 0.0
    if sea_border_count < c.AI_MIN_COAST_FOR_NAVY and land_border_count > 0:
        return 0.0
    return float(sea_border_count) * c.AI_NAVY_PER_COAST_TILE


def _recruit_sites(map_screen, ai_name, my_provs):
    """Where each kind of unit can be built, worked out once for the whole turn.

    The same gates the Production screen applies to a player -- cored, not in
    combat, the right industry, and a coast for anything that floats -- but
    there are only three answers, not one per unit. Deriving them per candidate
    per iteration meant rescanning every province the nation owns up to six
    hundred times a turn, which was most of what this pass cost.
    """
    usable = [p for p in my_provs
              if queries.has_core(ai_name, p)
              and not queries.is_nation_in_combat_here(ai_name, p, map_screen.nation_data)]

    militia = [p for p in usable if queries.has_industry(p)]
    factory = [p for p in usable if queries.has_basic_factory(p)]
    naval = [p for p in factory if p.get("is_coastal", False)
             and queries.borders_ocean(p, map_screen.id_to_province)]
    return {"militia": militia, "factory": factory, "naval": naval}


def _sites_for(sites, unit_name):
    """Which of the three lists this unit is allowed to be built in."""
    if queries.is_naval_unit(unit_name):
        return sites["naval"]
    if queries.get_base_unit_name(unit_name) == "Militia":
        return sites["militia"]
    return sites["factory"]


def _affordable_within(stats, data, econ, turns):
    """Whether this nation's income closes the gap on this unit inside `turns`.

    The guard on saving up: a nation with no materials income must never sit on
    its hands waiting for a tank it will never be able to buy.
    """
    for res in ai_unit_eval.RESOURCES:
        shortfall = stats.get(f"cost_{res}", 0) - data.get(res, 0)
        if shortfall <= 0:
            continue
        income = econ.get("total_inc", {}).get(res, 0)
        if income <= 0 or shortfall / income > turns:
            return False
    return True


def _run_purchase_loop(map_screen, ai_name, data, my_provs, unit_library, tech_tree, state):
    """Spends this nation's budget on whatever is worth the most to it right now.

    Every purchase is the argmax of ai_unit_eval's marginal score over what the
    nation can currently afford and deploy, with prices recomputed as the
    stockpile drains. Nothing in here names a unit or a ratio.

    What this replaces, and why none of it is missed:
      - the force-tank quota (one tank per 2000 materials of income), including
        the branch where a nation below quota stopped buying anything at all and
        hoarded for a tank it could not afford
      - AI_INFANTRY_TO_TANK_RATIO, which resolved to 1:1 in almost every game
      - the naval ratio branch, so a navy now competes on merit against a target
        derived from actual coastline
      - the fuel_shortage boolean and both of its fallback branches, subsumed by
        pricing fuel against the nation's own income and reserves
    """
    target_man, target_mat = state["target_man"], state["target_mat"]
    target_fuel = state["target_fuel"]
    inc_man, inc_mat, inc_fuel = state["inc_man"], state["inc_mat"], state["inc_fuel"]
    upk_man, upk_mat, upk_fuel = state["upk_man"], state["upk_mat"], state["upk_fuel"]

    values = state["unit_values"]
    targets = state["role_targets"]
    have = dict(state["role_counts"])

    if not values:
        return

    best_overall = max((v.score for v in values.values()), default=0.0)
    floor = best_overall * c.AI_MARGINAL_FLOOR

    sites = _recruit_sites(map_screen, ai_name, my_provs)
    deployable = {name: _sites_for(sites, name) for name in values}
    values = {n: v for n, v in values.items() if deployable[n]}
    if not values:
        return

    failsafe = 0
    while failsafe < 50:
        failsafe += 1

        ratio_man = upk_man / inc_man if inc_man > 0 else 1.0
        ratio_mat = upk_mat / inc_mat if inc_mat > 0 else 1.0
        if ratio_mat >= target_mat or ratio_man >= target_man:
            break

        # Fuel was accumulated below and never once read, so the loop bought
        # tanks and ships until materials ran out no matter what they cost to
        # run -- and the disband pass then deleted a unit every turn to pay for
        # them. It cannot join the break above, though: most units burn no fuel
        # at all, and stopping outright would leave a nation unable to afford
        # armour and therefore unable to raise infantry either. So an army it
        # cannot fuel stops it buying more of what needs fuel, and nothing else.
        ratio_fuel = upk_fuel / inc_fuel if inc_fuel > 0 else 1.0
        out_of_fuel = ratio_fuel >= target_fuel

        # Of the units it can deploy, which can it pay for right now?
        affordable = {
            name for name, value in values.items()
            if data.get("materials", 0) >= value.stats.get("cost_materials", 0)
            and data.get("manpower", 0) >= value.stats.get("cost_manpower", 0)
            and data.get("fuel", 0) >= value.stats.get("cost_fuel", 0)
            and not (out_of_fuel and value.stats.get("cost_fuel", 0) > 0)
        }

        pick, marginal = ai_unit_eval.pick_next(values, have, targets, affordable=affordable)

        # Would something it cannot pay for today be markedly better? Then bank
        # the money instead of spending it on the cheapest thing available.
        #
        # The old loop got this right for the wrong reason: a hardcoded quota of
        # one tank per 2000 materials of income, which made it stop buying
        # entirely until the tank was paid for -- and hang forever if it never
        # could be. Without any equivalent the AI simply never bought anything
        # expensive, because there was always an affordable infantryman and the
        # budget was gone by the time armour came up. The rule here is general:
        # save only for something genuinely better, and only if income actually
        # closes the gap in a few turns.
        # Saving up for something it cannot run is the same mistake as buying
        # it, so a nation over its fuel target does not bank money for a tank.
        savable = {n: v for n, v in values.items()
                   if not (out_of_fuel and v.stats.get("cost_fuel", 0) > 0)}
        best_any, best_any_marginal = ai_unit_eval.pick_next(savable, have, targets)
        if (best_any and best_any_marginal >= floor
                and (not pick or marginal < best_any_marginal * c.AI_SAVE_UP_THRESHOLD)
                and _affordable_within(best_any.stats, data, state["econ"], c.AI_SAVE_UP_TURNS)):
            break

        if not pick or marginal < floor:
            break

        stats = pick.stats
        cost_mat = stats.get("cost_materials", 0)
        cost_man = stats.get("cost_manpower", 0)
        cost_fuel = stats.get("cost_fuel", 0)

        data["materials"] -= cost_mat
        data["manpower"] -= cost_man
        data["fuel"] -= cost_fuel

        upkeep = queries.get_unit_upkeep(stats)
        upk_man += upkeep["manpower"]
        upk_mat += upkeep["materials"]
        upk_fuel += upkeep["fuel"]
        have[pick.role] = have.get(pick.role, 0) + 1

        # Spread the load rather than stacking one province's queue.
        target_prov = min(deployable[pick.name], key=lambda p: len(p.get("unit_queue", [])))
        target_prov.setdefault("unit_queue", []).append({
            "unit_type": pick.name,
            "turns_remaining": max(1, stats.get("production_time", 1)),
            "refund": {"cost_materials": cost_mat, "cost_manpower": cost_man,
                       "cost_fuel": cost_fuel},
        })

        # The stockpile just shrank, so what is scarce may have changed. Only
        # the prices moved, so this rescores rather than re-deriving.
        values = ai_unit_eval.reprice(
            values, ai_unit_eval.resource_prices(state["econ"], data))

    state["upk_man"], state["upk_mat"], state["upk_fuel"] = upk_man, upk_mat, upk_fuel
    state["role_counts"] = have


def _apply_coring_priority(map_screen, ai_name, data, my_provs):
    """Section: AI CORING PRIORITY -- spends surplus manpower coring the best
    available uncored province (prioritizing ones with factories)."""
    # Nothing to core when cores are disabled -- every tile already counts
    # as cored, so skip straight past this without spending resources.
    surplus_manpower = c.AI_SURPLUS_MANPOWER_FOR_CORING
    if getattr(c, "DISABLE_CORES", False) or data.get("manpower", 0) <= surplus_manpower:
        return

    uncored_provs = [p for p in my_provs if ai_name not in p.get("cores", []) and not any(q.get("order_type") == "CORE" for q in p.get("building_queue", []))]
    if not uncored_provs:
        return

    valid_uncored = []
    has_any_core = any(ai_name in p.get("cores", []) for p in map_screen.map_data.values())
    for p in uncored_provs:
        can_core = False
        if not has_any_core:
            can_core = True
        elif p.get("is_coastal", False):
            can_core = True
        else:
            for n_id in p.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if n_prov and ai_name in n_prov.get("cores", []):
                    can_core = True
                    break
        if can_core:
            valid_uncored.append(p)

    if not valid_uncored:
        return

    # Prioritize territories with factories
    valid_uncored.sort(key=lambda p: (queries.has_industry(p), p.get("is_coastal", False)), reverse=True)
    target_core_prov = valid_uncored[0]
    core_data = queries.get_core_cost(ai_name, map_screen.map_data)
    if queries.can_afford(data, core_data):
        queries.deduct_resources(data, core_data)
        order = {
            "order_type": "CORE",
            "item_name": "Core Territory",
            "turns_remaining": max(1, core_data.get("time", 24)),
            "group": "administration",
            "refund": {"cost_materials": core_data.get("cost_materials", 0), "cost_manpower": core_data.get("cost_manpower", 0), "cost_fuel": core_data.get("cost_fuel", 0)}
        }
        target_core_prov.setdefault("building_queue", []).append(order)


def _apply_construction_logic(map_screen, ai_name, data, my_provs, building_library):
    """Section: EVALUATE CONSTRUCTION LOGIC -- if the AI has an excess hoard
    of materials, invests it back into the next industry/recruitment building
    tier it has the tech and a free build slot for, one per turn."""
    if data.get("materials", 0) <= c.AI_MIN_MATERIALS_FOR_CONSTRUCTION:
        return

    res_levels = data.get("research", {})

    # Fetch the dynamic lists
    industry_b_list = [b for b, d in building_library.items() if d.get("group") == "industry"]
    recruit_b_list = [b for b, d in building_library.items() if d.get("group") == "recruitment"]

    # Sort provinces by queue length to spread out construction
    my_provs.sort(key=lambda p: len(p.get("building_queue", [])))

    for prov in my_provs:
        # Ensure AI only builds in its core territories
        if not queries.has_core(ai_name, prov):
            continue

        current_buildings = prov.get("buildings", [])
        queue = prov.get("building_queue", [])

        # Double check the queue so it doesn't build two at once in the same province
        if any(q.get("group") in ["industry", "recruitment"] for q in queue):
            continue

        target_bldg = None
        has_factory = queries.has_basic_factory(prov)

        # Expand AI's building options dynamically based on the tile's current capacity
        groups_to_check = [industry_b_list]
        if has_factory:
            groups_to_check.extend([recruit_b_list])

        random.shuffle(groups_to_check)

        for b_list in groups_to_check:
            if not b_list: continue
            group_id = building_library[b_list[0]].get("group")
            owned_in_group = [b for b in current_buildings if building_library.get(b, {}).get("group") == group_id]

            if not owned_in_group:
                target_bldg = b_list[0]
            else:
                for i, b_name in enumerate(b_list):
                    if b_name in owned_in_group:
                        if i + 1 < len(b_list):
                            target_bldg = b_list[i+1]

            if target_bldg:
                # Check if the AI actually has the research required for this next tier
                req_tech, req_lvl = queries.get_building_required_tech(target_bldg)
                if req_tech and res_levels.get(req_tech, 0) < req_lvl:
                    target_bldg = None # Lacks the research, clear and check the next group
                    continue
                break # Found a valid, fully-researched building!

        if target_bldg:
            # We have the tech and the physical foundation, now check dynamic costs
            b_stats = queries.get_building_cost(target_bldg, ai_name, map_screen.map_data, building_library)
            c_mat = b_stats.get("cost_materials", 0)
            c_fuel = b_stats.get("cost_fuel", 0)

            if data.get("materials", 0) >= c_mat and data.get("fuel", 0) >= c_fuel:
                data["materials"] -= c_mat
                data["fuel"] -= c_fuel

                order = {
                    "order_type": "BUILDING",
                    "item_name": target_bldg,
                    "turns_remaining": max(1, b_stats.get("time", 1)),
                    "group": b_stats["group"],
                    "refund": {"cost_materials": c_mat, "cost_manpower": 0, "cost_fuel": c_fuel}
                }
                prov.setdefault("building_queue", []).append(order)

                # Successfully queued a building. Break out of the loop so it only queues one per turn
                # to avoid instantly draining its treasury on 30 workshops at once.
                break


def process_ai_economy_decisions(map_screen):
    """Handles AI unit recruitment and building construction based on economy."""
    unit_library = queries.get_unit_library()
    building_library = queries.get_building_library()

    tech_tree = queries.get_tech_tree()

    all_econ = queries.calculate_all_economies(map_screen.map_data, map_screen.nation_data)

    # Border and coast counts, and the enemy stacks each nation is facing, all
    # come off this turn's snapshot rather than being re-derived per nation.
    world = ai_world.for_screen(map_screen)

    # Pre-group provinces by owner for efficiency
    nation_provs = {}
    for prov in map_screen.map_data.values():
        owner = prov.get("owner")
        # Prevent AI from treating bugged water tiles as valid build sites
        if owner and not queries.is_water_province(prov):
            nation_provs.setdefault(owner, []).append(prov)

    ai_nations = queries.get_active_ai_nations(map_screen)

    for ai_name in ai_nations:
        data = map_screen.nation_data[ai_name]
        econ = all_econ.get(ai_name)
        if not econ: continue

        my_provs = nation_provs.get(ai_name, [])
        if not my_provs: continue

        # --- NEW: Randomize Tile Selection ---
        # By shuffling the array before doing any queue length sorting,
        # the AI will organically distribute its buildings and units to random valid tiles
        # instead of always hard-focusing the first province id it owns.
        random.shuffle(my_provs)

        # --- 1. EVALUATE RECRUITMENT RATIOS ---
        state = _compute_economy_ratios(map_screen, ai_name, data, my_provs, econ, unit_library)

        # --- 1b. VALUE EVERY UNIT THIS NATION COULD FIELD ---
        # Scored against the war it is actually in: what its fronts are being
        # hit with, and how well armoured the things it is shooting at are.
        # Existing unit types are valued alongside the buildable ones purely so
        # the tally below can bucket them by the same rule; only the buildable
        # set is ever purchased from.
        candidates = ai_unit_eval.buildable_units(data.get("research", {}), unit_library)
        owned_types = {u.get("type", "") for p in my_provs for u in p.get("units", [])
                       if u.get("owner") == ai_name}
        owned_types |= {q.get("unit_type", "") for p in my_provs
                        for q in p.get("unit_queue", [])}

        volley, enemy_def, enemy_stack = ai_unit_eval.threat_profile(
            world, ai_name, unit_library, candidates)
        frontline = len(world.land_border_tiles.get(ai_name, ())) if world else len(my_provs)
        coast = len(world.coast_tiles.get(ai_name, ())) if world else 0

        unit_prices = ai_unit_eval.resource_prices(econ, data)
        unit_ctx = ai_unit_eval.context(
            unit_prices,
            volley=volley, stack=max(1.0, c.MAX_COMBAT_ATTACKERS),
            enemy_def=enemy_def, enemy_stack=enemy_stack,
            frontline=max(1, frontline), coast=coast,
            budget=ai_unit_eval.spending_budget(econ, data, unit_prices))

        all_values = ai_unit_eval.evaluate(
            sorted(set(candidates) | {t for t in owned_types if t}), unit_library, unit_ctx)
        roles = {name: value.role for name, value in all_values.items()}
        buildable_values = {n: v for n, v in all_values.items() if n in set(candidates)}

        # Sliders no longer have a tank quota to save up for; they key off the
        # same upkeep ratios they always did.
        _update_conscription_slider(data, state)
        _update_fuel_conversion_slider(data, state)

        _disband_worst_unit_if_deficit(map_screen, data, my_provs, ai_name,
                                       state["standing_deficits"], unit_library, all_values)

        # --- NEW: Panic Militia & Combat Queue Clearing ---
        force_tally = _panic_militia_and_tally_forces(
            map_screen, ai_name, data, my_provs, unit_library, state, roles)

        state.update(force_tally)
        state["econ"] = econ
        state["unit_values"] = buildable_values
        state["unit_context"] = unit_ctx
        state["role_targets"] = ai_unit_eval.role_targets(
            unit_ctx,
            naval_need=_naval_need(force_tally["land_border_count"],
                                   force_tally["sea_border_count"]),
            values=buildable_values)

        # Allow the AI to purchase multiple units per turn until its budget maxes out
        _run_purchase_loop(map_screen, ai_name, data, my_provs, unit_library, tech_tree, state)

        # After the purchases, so it can see what was actually ordered.
        _disband_peacetime_militia(ai_name, my_provs, state["at_war"])

        # --- AI CORING PRIORITY ---
        _apply_coring_priority(map_screen, ai_name, data, my_provs)

        # --- 2. EVALUATE CONSTRUCTION LOGIC ---
        _apply_construction_logic(map_screen, ai_name, data, my_provs, building_library)
