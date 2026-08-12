"""What a unit is worth to a particular nation right now, from its stats.

The AI used to pick units off two hand-written lists in constants.py, walked in
reverse so the last entry won. That meant Main Battle Tanks and Destroyers the
moment either was researched, at any price, and Heavy Tanks, Super Heavy Tanks,
Artillery, Submarines and Carriers never, because nobody had put them on a list.
Rebalancing unit_data.json changed nothing about how the AI played.

Everything here is derived instead, and it is derived from how combat actually
resolves rather than from a general notion of "good stats":

  - A tile splits into lanes -- one duel per pair of hostile powers on it --
    and only a lane's front rank deals damage. LANE_SLOTS_TYPICAL of them in an
    ordinary one-enemy fight (combat_rules.build_battle), so offence is raw
    attack and the unit after that contributes nothing. That is what the role
    targets below are for.
  - Incoming damage is divided across the enemy front rank IN THAT LANE and
    then each defender subtracts its own defense, flat, per hit
    (combat_processor.apply_group_damage). So defense is worth much more than
    its magnitude suggests. Bodies past the front absorb NOTHING -- they wait in
    reserve, untouchable, which is worth something as a queue of replacements
    and nothing at all as protection. Under the pot this replaced they thinned
    the volley for the whole stack, which is why AI_RESERVE_DEPTH now caps how
    many of them are worth buying.
  - Morale is decremented but never read back in combat, and terrain never
    affects it. Neither is scored, because neither does anything.

Cost is priced against the nation's own scarcity rather than in absolute
numbers, which is what replaces the old `fuel_shortage` boolean: a nation with
no fuel income prices fuel near the cap, so every fuel-burning unit falls to the
bottom on its own, and recovers on its own when the oil starts flowing.

Stdlib and `data` only, so it imports under Pyodide with the rest of the
heuristic AI.
"""

import collections
import re

import data.constants as c
from data import queries

RESOURCES = ("manpower", "materials", "fuel")

ROLE_ASSAULT = "ASSAULT"    # holds a front slot and does the killing
ROLE_LINE = "LINE"          # the relief rank: holds the tile, rotates into the front as it dies
ROLE_BOMBARD = "BOMBARD"    # shells from outside every lane, the only thing that reaches a reserve
ROLE_NAVAL = "NAVAL"

LAND_ROLES = (ROLE_ASSAULT, ROLE_LINE, ROLE_BOMBARD)
ALL_ROLES = LAND_ROLES + (ROLE_NAVAL,)

#: One unit's worth to one nation this turn.
#: `score` is value per unit of resource pain; `pain` is what it costs in those
#: terms, so a caller that has to check affordability separately still can.
UnitValue = collections.namedtuple(
    "UnitValue", "name role score combat offense durability soak pain stats naval")

#: What the valuation is relative to -- the war this nation is actually fighting.
#: prices      -- pain per point of each resource, from resource_prices()
#: volley      -- the attack this nation's stacks expect to eat in one exchange
#: stack       -- how many friendly units typically share that volley
#: enemy_def   -- mean defense of the units being shot at, which is subtracted
#:                flat from every hit and is what makes weak attacks worthless
#: enemy_stack -- how many enemy bodies a volley gets divided between
#: frontline   -- tiles that need holding, which caps how many hitters can fire
#: coast       -- coastal tiles, which sets the naval target
#: budget      -- total pain this nation can afford to commit, which is what the
#:                role targets actually divide up
Context = collections.namedtuple(
    "Context", "prices volley stack enemy_def enemy_stack frontline coast budget")


def context(prices, volley=1.0, stack=5.0, enemy_def=0.0, enemy_stack=5.0,
            frontline=1.0, coast=0.0, budget=0.0):
    """Context with defaults, so callers only name what they know."""
    return Context(prices=prices, volley=float(volley), stack=float(stack),
                   enemy_def=float(enemy_def), enemy_stack=float(enemy_stack),
                   frontline=float(frontline), coast=float(coast),
                   budget=float(budget))


def spending_budget(econ, stockpile, prices):
    """Total pain this nation could commit to new units before upkeep bites.

    Its stockpile plus the income it has spare under the upkeep targets, over
    the same horizon a unit's upkeep is charged against. Priced in the same
    scarcity terms as the units themselves so the two are comparable.
    """
    total = 0.0
    for res in RESOURCES:
        income = float(econ.get("total_inc", {}).get(res, 0))
        upkeep = float(econ.get("upkeep", {}).get(res, 0))
        spare = max(0.0, income * c.AI_UPKEEP_TARGETS[res] - upkeep)
        total += prices[res] * (float(stockpile.get(res, 0)) + spare * c.AI_UPKEEP_HORIZON)
    return total


def effective_attack(attack, ctx):
    """How much of a unit's attack actually lands, given who it is shooting at.

    apply_group_damage splits the front rank's total attack across the enemy
    front rank and then each defender subtracts its own defense, flat. So attack
    is not worth its face value: a unit whose share of the volley never exceeds
    the enemy's defense contributes literally nothing, however many of them there
    are, and no amount of cheapness fixes that.

    Evaluated for a full front rank of this unit (LANE_SLOTS_TYPICAL of them)
    rather than one in isolation, because one unit's attack alone almost never
    clears a defense value on its own, while a rank of them routinely does --
    scoring it solo would write off every light unit in the game.

    `ctx.enemy_stack` is a FRONT size, not a whole-tile headcount. Passing the
    stack would report each enemy eating a share of the volley that the lane
    never divides that far, and the error runs in the direction that makes deep
    enemy stacks look safe to attack.
    """
    group = attack * c.LANE_SLOTS_TYPICAL
    per_defender = group / max(1.0, ctx.enemy_stack)
    landed = max(0.0, per_defender - ctx.enemy_def) * max(1.0, ctx.enemy_stack)
    return landed / c.LANE_SLOTS_TYPICAL


# ----------------------------------------------------------------------------
# Pricing
# ----------------------------------------------------------------------------

def resource_prices(econ, stockpile):
    """Pain per point of each resource, for this nation, right now.

    Cheap when there is headroom under the upkeep target and a stockpile to draw
    on; expensive as either runs out. A nation with no fuel income and no fuel in
    the bank prices fuel at the cap, which is what makes every fuel-burning unit
    score near zero without a special case anywhere.
    """
    prices = {}
    for res in RESOURCES:
        income = float(econ.get("total_inc", {}).get(res, 0))
        upkeep = float(econ.get("upkeep", {}).get(res, 0))

        # Fraction of this nation's income still unspoken for. Zero income means
        # zero headroom -- measuring it as a fraction of a denominator clamped to
        # 1 instead reported a broke nation as having the full upkeep target
        # spare, which made fuel look cheap to a nation with no oil at all.
        if income > 0:
            headroom = max(0.0, income * c.AI_UPKEEP_TARGETS[res] - upkeep) / income
        else:
            headroom = 0.0

        # Turns of reserve in the bank, capped at ten so a hoard isn't infinite
        # slack. A nation with no income but a full warehouse is still fine today.
        buffer = min(10.0, max(0.0, float(stockpile.get(res, 0))) / max(1.0, income)) / 10.0

        slack = 0.5 * headroom + 0.5 * buffer
        prices[res] = 1.0 / max(c.AI_MIN_RESOURCE_SLACK, slack)
    return prices


def unit_pain(stats, prices):
    """What buying and then keeping this unit costs, in scarcity-weighted terms."""
    upkeep = queries.get_unit_upkeep(stats)
    build = sum(prices[res] * stats.get(f"cost_{res}", 0) for res in RESOURCES)
    running = sum(prices[res] * upkeep.get(res, 0) for res in RESOURCES) * c.AI_UPKEEP_HORIZON
    return build + running


# ----------------------------------------------------------------------------
# Candidate set
# ----------------------------------------------------------------------------

_ROMAN_TAIL = re.compile(r'\s+[IVXLCDM]+$')
_YEAR_TAIL = re.compile(r'\s+\d{4}$')


def _tier_of(unit_name):
    """Sort key for 'which tier of this family is this', years and numerals alike."""
    year = _YEAR_TAIL.search(unit_name)
    if year:
        return int(year.group().strip())
    roman = _ROMAN_TAIL.search(unit_name)
    if roman:
        return queries.roman_to_int(roman.group().strip())
    return 0


#: Memo for buildable_units, keyed on the research that produced the answer.
#: Scanning the 602-entry library is regex-heavy and was 89% of the whole
#: economy pass -- but most nations in a scenario start on identical research,
#: so a map of fifty countries usually asks only a handful of distinct
#: questions. Keyed on the library object too, so a mod swapping it invalidates.
_BUILDABLE_CACHE = {}
_BUILDABLE_CACHE_LIBRARY = None


def buildable_units(research, unit_library):
    """The best unlocked, non-obsolete tier of each unit family.

    The same set the production screen offers a player by default, for the same
    reason: within a family the higher tier is the researched one, and letting
    the AI reach for tiers a player cannot see would be its own kind of wrong.
    Keeping it to one entry per family also holds the valuation at ~25 units
    instead of the 602 in the library.
    """
    global _BUILDABLE_CACHE, _BUILDABLE_CACHE_LIBRARY

    # `!=`, not `is not`: id() returns a large int and Python only interns small
    # ones, so an identity test here is true even when the library is the same
    # object -- which cleared the cache on every single call and made the whole
    # thing a no-op.
    if _BUILDABLE_CACHE_LIBRARY != id(unit_library):
        _BUILDABLE_CACHE = {}
        _BUILDABLE_CACHE_LIBRARY = id(unit_library)

    key = tuple(sorted((tech, lvl) for tech, lvl in research.items() if lvl))
    cached = _BUILDABLE_CACHE.get(key)
    if cached is not None:
        return cached

    best = {}
    for name in unit_library:
        base = queries.get_base_unit_name(name)
        if queries.is_unit_obsolete(base, research):
            continue
        if not queries.is_unit_unlocked(name, research):
            continue
        tier = _tier_of(name)
        if base not in best or tier > best[base][0]:
            best[base] = (tier, name)

    result = sorted(name for _, name in best.values())
    _BUILDABLE_CACHE[key] = result
    return result


# ----------------------------------------------------------------------------
# Valuation
# ----------------------------------------------------------------------------

def _mean(values):
    values = list(values)
    return (sum(values) / len(values)) if values else 0.0


def bombard_range(name, stats):
    """How far this unit shells, from its own stats first.

    The stats-win-over-table rule now lives in queries.get_bombardment_range, so
    what the AI values and what the turn processor lets a unit do are the same
    number. They used to be derived separately, which meant a unit given a
    bombard_range by hand was priced for a barrage it could never fire.

    `stats` is still consulted first for callers holding a synthetic library the
    real one has never heard of -- which is every test in this module.
    """
    from_stats = stats.get("bombard_range")
    if from_stats:
        return int(from_stats)
    return queries.get_bombardment_range(name)


def evaluate(names, unit_library, ctx):
    """Scores each named unit for this nation, as {name: UnitValue}.

    Offence and staying power are normalised against the mean of this candidate
    set before being weighted together, so the weights in constants.py stay
    meaningful whatever scale unit_data.json is written on.
    """
    # One incoming hit's worth per defender. Depends only on the context, not on
    # the unit, so it is the same for every candidate.
    share = ctx.volley / max(1.0, ctx.stack)

    raw = {}
    for name in names:
        stats = unit_library.get(name)
        if not stats:
            continue

        attack = effective_attack(float(stats.get("attack", 0)), ctx)
        health = float(stats.get("health", 0))
        defense = float(stats.get("defense", 0))

        # apply_group_damage: each defender eats max(0, volley/N - defense).
        # The floor keeps a unit whose defense exceeds its share from scoring
        # infinitely -- strong returns on defense, not unbounded ones.
        bite = max(share * c.AI_MIN_DAMAGE_FRACTION, share - defense)
        durability = health / bite if bite > 0 else 0.0

        raw[name] = (stats, attack, durability, health, defense)

    if not raw:
        return {}

    mean_attack = _mean([v[1] for v in raw.values()]) or 1.0
    mean_durability = _mean([v[2] for v in raw.values()]) or 1.0

    values = {}
    for name, (stats, attack, durability, health, defense) in raw.items():
        offense = c.AI_W_OFFENSE * (attack / mean_attack)

        # An extra body is worth what it actually absorbs, which is its DEFENSE.
        # apply_group_damage deals sum(max(0, volley/N - defense_i)), so with
        # defense 0 that sum is exactly `volley` for any N -- splitting a stack
        # into more zero-defense bodies reduces incoming damage by nothing at
        # all. This term used to be flat, on the reasoning that dividing damage
        # across more defenders helps whatever the body is made of; the combat
        # model says otherwise, and the flat version is why a nation with cheap
        # manpower would fill its queues with militia. Scaled by health it would
        # count health twice, since durability above already has it; scaled by
        # what a body soaks, it does the one thing it should.
        soak_share = min(defense, share) / share if share > 0 else 0.0
        combat = (offense + c.AI_W_DURABILITY * (durability / mean_durability)
                  + c.AI_W_SOAK * soak_share)

        bomb_range = bombard_range(name, stats)
        if bomb_range:
            # Bombardment fires outside the combat-width cap and draws no return
            # fire, so it is added on top rather than replacing the melee value.
            bombard_attack = effective_attack(
                float(stats.get("bombard_attack", stats.get("attack", 0))), ctx)
            combat += c.AI_W_BOMBARD * (bombard_attack / mean_attack) * bomb_range

        naval = bool(stats.get("naval_unit", False))
        if bomb_range and not naval:
            role = ROLE_BOMBARD
        elif naval:
            role = ROLE_NAVAL
        elif combat > 0 and (offense / combat) >= c.AI_ASSAULT_OFFENSE_SHARE:
            role = ROLE_ASSAULT
        else:
            role = ROLE_LINE

        # A division that lands after the front has collapsed is worth less than
        # two that land now.
        timed = combat / max(1.0, float(stats.get("production_time", 1))) ** c.AI_TIME_EXPONENT
        pain = unit_pain(stats, ctx.prices)
        score = timed / pain if pain > 0 else 0.0

        values[name] = UnitValue(name=name, role=role, score=score, combat=combat,
                                 offense=offense, durability=durability, soak=health,
                                 pain=pain, stats=stats, naval=naval)
    return values


# ----------------------------------------------------------------------------
# Composition
# ----------------------------------------------------------------------------

def _cheapest_pain(values, role):
    """What the most affordable unit of this role costs, in pain.

    The cheapest rather than the mean, because the target is what the nation
    could buy if it spent this role's share on it, and it would spend that share
    on whatever was best value -- averaging in an expensive outlier shrinks the
    target for no reason.
    """
    pains = [v.pain for v in values.values() if v.role == role and v.pain > 0]
    return min(pains) if pains else 0.0


def reprice(values, prices):
    """Rescores an existing valuation after the stockpile moved.

    Only cost changes when a purchase drains the treasury -- what a unit does in
    a fight is the same as it was a moment ago. Re-running evaluate() per
    purchase instead re-derives and re-normalises the whole set, which was
    comfortably the most expensive thing this module added to a turn.
    """
    out = {}
    for name, value in values.items():
        pain = unit_pain(value.stats, prices)
        timed = value.combat / max(
            1.0, float(value.stats.get("production_time", 1))) ** c.AI_TIME_EXPONENT
        out[name] = value._replace(pain=pain, score=(timed / pain if pain > 0 else 0.0))
    return out


def role_targets(ctx, naval_need, values=None):
    """How many of each role this nation wants, from its budget and its geography.

    Targets are a division of what this nation can actually spend, not of the
    front it would like to hold. That distinction is the whole function:
    scaling them with frontline instead produced targets in the high hundreds
    for any large country, so no role ever saturated, the diminishing-returns
    term never bit, and the single best value-per-pain unit won every purchase
    for the rest of the game -- which is how the first version of this ended up
    building 83% infantry and not one tank.

    Within the budget:
      - assault is additionally capped by the combat rules, since only a lane's
        front rank fires and the unit after that contributes nothing
      - depth is capped too, which is new. Under the pot this replaced an extra
        body always thinned somebody's volley, so depth had unbounded if
        diminishing value; under lanes a body past the relief rank absorbs
        nothing at all, so it is pure waste and AI_LINE_SPEND_RATIO is no longer
        the only thing bounding it
      - depth and guns take their share by *spend*, because a heavy tank costs
        seventeen infantry and a count-based split silently commits the whole
        budget to armour

    `values` is optional only so targets can be asked for before a valuation
    exists; without one it falls back to plain counts.
    """
    frontline = max(1.0, float(ctx.frontline))
    width_cap = max(c.AI_MIN_ROLE_TARGET, c.LANE_SLOTS_TYPICAL * frontline)
    depth_cap = max(c.AI_MIN_ROLE_TARGET, width_cap * (c.AI_RESERVE_DEPTH - 1.0))

    if not values or ctx.budget <= 0:
        return {
            ROLE_ASSAULT: width_cap,
            ROLE_LINE: min(depth_cap,
                           max(c.AI_MIN_ROLE_TARGET, width_cap * c.AI_LINE_SPEND_RATIO)),
            ROLE_BOMBARD: max(c.AI_MIN_ROLE_TARGET, width_cap * c.AI_BOMBARD_SPEND_RATIO),
            ROLE_NAVAL: max(0.0, naval_need),
        }

    shares = {
        ROLE_ASSAULT: 1.0,
        ROLE_LINE: c.AI_LINE_SPEND_RATIO,
        ROLE_BOMBARD: c.AI_BOMBARD_SPEND_RATIO,
    }
    total_share = sum(shares.values())

    targets = {}
    for role, share in shares.items():
        pain = _cheapest_pain(values, role)
        if pain <= 0:
            targets[role] = c.AI_MIN_ROLE_TARGET
            continue
        count = (ctx.budget * share / total_share) / pain
        targets[role] = max(c.AI_MIN_ROLE_TARGET, count)

    targets[ROLE_ASSAULT] = min(targets[ROLE_ASSAULT], width_cap)
    targets[ROLE_LINE] = min(targets[ROLE_LINE], depth_cap)
    targets[ROLE_NAVAL] = max(0.0, naval_need)
    return targets


def marginal_score(value, have, targets):
    """A unit's score discounted by how saturated its role already is.

    Diminishing rather than capped, so a role past its target still wins if
    nothing else is worth buying -- which is what stops the AI hoarding, the way
    the old force-tank quota did when it could not afford the tank it was
    saving for.
    """
    target = targets.get(value.role, 0.0)
    if target <= 0:
        return 0.0
    saturation = have.get(value.role, 0) / target
    return value.score * (c.AI_ROLE_DIMINISH ** saturation)


def pick_next(values, have, targets, affordable=None):
    """The best unit to buy next, or None when nothing is worth it.

    `affordable` filters to what the nation can actually pay for right now, so
    the choice is always executable.
    """
    best, best_marginal = None, 0.0
    for value in values.values():
        if affordable is not None and value.name not in affordable:
            continue
        m = marginal_score(value, have, targets)
        if m > best_marginal:
            best, best_marginal = value, m
    return best, best_marginal


def best_by_role(values, role):
    """Highest-scoring unit filling a given role, ignoring what is already built."""
    candidates = [v for v in values.values() if v.role == role]
    if not candidates:
        return None
    return max(candidates, key=lambda v: (v.score, v.name)).name


def threat_profile(world, nation, unit_library, candidates):
    """What this nation is up against: (volley, enemy_defense, enemy_stack).

    Measured off the units actually standing on its fronts, so an AI facing
    heavy armour values armour-piercing attack while one facing militia does
    not. At peace there is no front to read, so it assumes an opponent fielding
    what it could field itself -- which keeps both terms meaningful instead of
    collapsing to zero and making every unit look immortal and every attack
    look devastating.
    """
    volleys, defenses, stacks = [], [], []

    if world is not None:
        for enemy in queries.get_enemies(nation, world.nation_data):
            for prov_id in world.border_tiles.get(frozenset((nation, enemy)), ()):
                prov = world.id_to_province.get(prov_id)
                if not prov:
                    continue
                hostile = [u for u in prov.get("units", []) if u.get("owner") == enemy]
                if not hostile:
                    continue
                volleys.append(queries.get_group_attack_sum(hostile))
                defenses.append(_mean(float(u.get("defense", 0)) for u in hostile))
                # A FRONT size, not a headcount: the volley is divided across
                # the enemy's front rank in one lane, and everything behind it
                # is out of reach. Handing the whole stack over reported each
                # body eating a share the lane never divides that far, which
                # made deep enemy stacks look safe to walk into.
                stacks.append(min(len(hostile), c.LANE_SLOTS_TYPICAL))

    if volleys:
        return (max(1.0, _mean(volleys)), max(0.0, _mean(defenses)), max(1.0, _mean(stacks)))

    peers = [unit_library[n] for n in candidates if n in unit_library]
    mean_attack = _mean(float(s.get("attack", 0)) for s in peers)
    mean_defense = _mean(float(s.get("defense", 0)) for s in peers)
    volley = max(1.0, mean_attack * c.LANE_SLOTS_TYPICAL * c.AI_PEACETIME_THREAT_MULTIPLIER)
    return volley, mean_defense, float(c.LANE_SLOTS_TYPICAL)
