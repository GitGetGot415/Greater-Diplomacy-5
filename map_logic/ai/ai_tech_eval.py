"""What researching a tech is actually worth to a particular nation.

The AI used to order its research by `(years overdue, is it new, cost)`. Every
already-historical tech ties at zero on the first term, so in practice it
researched whichever brand-new tech was cheapest -- with no notion of whether
the thing it unlocked was any use. An island power researched armour, a nation
being overrun by tanks researched recruitment buildings, and neither ever
noticed.

Value here is what the tech changes about the choices the nation has:

  - a tech that unlocks a unit is worth how much better that unit is than the
    best thing already available for the same job, scored by ai_unit_eval and so
    priced against this nation's own scarcity and the war it is actually in
  - a tech that unlocks a building is worth the yield it adds, priced the same way
  - a flat economic tech is worth its bonus, priced the same way

Which means the answer moves with the situation: the same tech is worth more to
a nation whose fronts are collapsing than to one at peace, and armour research
is worth more when the enemy is armoured.

`get_tech_unlocks` in queries.py cannot be used for this -- it returns display
strings like "+100 Base Fuel/Turn" for the research screen.
"""

import collections

import data.constants as c
from data import queries
from map_logic.ai import ai_unit_eval


#: Techs whose whole effect is a flat economic bonus per level, mapped to the
#: resource and the per-level amount. Everything else earns its value by
#: unlocking a unit or a building.
FLAT_ECONOMY_TECHS = {
    "general_recruitment": ("manpower", float(c.GENERAL_RECRUITMENT_BONUS)),
    "bergius_process": ("fuel", float(c.BERGIUS_FUEL_BONUS)),
}

#: Memo for "which units does one more level of this tech unlock", which depends
#: only on the research -- not on prices, wars or geography. Nations in a
#: scenario overwhelmingly share a research state, so this is asked once for a
#: whole map rather than once per nation.
_UNLOCK_CACHE = {}
_UNLOCK_CACHE_LIBRARY = None


def _research_key(research):
    return tuple(sorted((tech, lvl) for tech, lvl in research.items() if lvl))


def units_unlocked_by(tech_key, research, unit_library):
    """The units one more level of `tech_key` would newly make buildable."""
    global _UNLOCK_CACHE, _UNLOCK_CACHE_LIBRARY

    # `!=`, not `is not` -- see the same note in ai_unit_eval.buildable_units.
    if _UNLOCK_CACHE_LIBRARY != id(unit_library):
        _UNLOCK_CACHE = {}
        _UNLOCK_CACHE_LIBRARY = id(unit_library)

    key = (_research_key(research), tech_key)
    cached = _UNLOCK_CACHE.get(key)
    if cached is not None:
        return cached

    before = set(ai_unit_eval.buildable_units(research, unit_library))
    ahead = dict(research)
    ahead[tech_key] = ahead.get(tech_key, 0) + 1
    after = set(ai_unit_eval.buildable_units(ahead, unit_library))

    # Anything newly available, plus anything whose tier improved -- both show up
    # as a name in `after` that was not in `before`.
    result = tuple(sorted(after - before))
    _UNLOCK_CACHE[key] = result
    return result


def buildings_unlocked_by(tech_key, level, building_library):
    """Buildings that one more level of `tech_key` would make available."""
    unlocked = []
    for name in building_library:
        req_tech, req_lvl = queries.get_building_required_tech(name)
        if req_tech == tech_key and req_lvl == level:
            unlocked.append(name)
    return unlocked


def _yield_value(stats, prices, key_prefix="prod_"):
    """Per-turn output of a building, in the same scarcity terms as unit cost."""
    return sum(prices[res] * float(stats.get(f"{key_prefix}{res}", 0))
               for res in ai_unit_eval.RESOURCES)


def _replaced_building(name, building_library):
    """The building in the same group this one supersedes, if any.

    Upgrading does not stack: economy_processor drops every other member of the
    group from the province before appending the new one, so a Factory Lvl 8
    province produces 8000/turn, not 1000+2000+...+8000. The `req` field names
    exactly what is being torn down.
    """
    req = (building_library.get(name) or {}).get("req")
    if not req or req == "null" or req not in building_library:
        return None
    return req


def _build_cost(name, stats, prices):
    """What putting this building up costs, in the same scarcity terms."""
    if name == "Basic Factory":
        # Its JSON costs are zeros standing in for a figure worked out per
        # nation by queries.get_building_cost, which scales with how many
        # factories the nation already has. Taken at face value it read as a
        # free +500/turn. Nothing here has map access, so the base is the
        # honest floor.
        base = float(c.BASIC_FACTORY_BASE_COST_X)
        costs = {"materials": base * 2, "manpower": base, "fuel": 0.0}
    else:
        costs = {res: float(stats.get(f"cost_{res}", 0)) for res in ai_unit_eval.RESOURCES}
    return sum(prices[res] * costs[res] for res in ai_unit_eval.RESOURCES)


def _conversion_gain(level, prices, income):
    """What one more level of fuel_refining is worth.

    It raises the ceiling on how much of a nation's materials income it may
    convert into fuel, at FUEL_CONVERSION_RATIO. So it is worth something only
    where fuel is scarcer than the ten materials it takes to make a unit of it
    -- which is precisely the trade the slider offers, and can be negative.

    No building carries this tech, so the building branch found nothing to score
    and a fifty-level tech was worth exactly zero to every AI in the game.
    """
    if level * c.FUEL_REFINING_CONVERSION_PER_LVL > c.MAX_CONVERSION_SLIDER_VAL:
        return 0.0   # Past the slider's ceiling; further levels do nothing.
    freed = max(0.0, float(income.get("materials", 0))) * c.FUEL_REFINING_CONVERSION_PER_LVL
    return prices["fuel"] * freed * c.FUEL_CONVERSION_RATIO - prices["materials"] * freed


class UnitGains:
    """Per-tech unit value, scored in one pass over every reachable unit.

    Every candidate tech has to be compared against the same baseline, so the
    whole set -- what the nation can build now, plus everything any candidate
    tech would newly unlock -- is valued once and each tech then reads its
    answer off it. Scoring per tech instead meant one full valuation per tech
    per nation, which on a 33-nation map came to three seconds a turn.
    """

    def __init__(self, tech_keys, research, unit_library, ctx, current_names):
        self._unlocks = {t: units_unlocked_by(t, research, unit_library) for t in tech_keys}

        reachable = set(current_names)
        for names in self._unlocks.values():
            reachable.update(names)

        self._values = ai_unit_eval.evaluate(sorted(reachable), unit_library, ctx)
        self._current = set(current_names)

        self._best_now = collections.defaultdict(float)
        for name, value in self._values.items():
            if name in self._current:
                self._best_now[value.role] = max(self._best_now[value.role], value.score)

    def best_score(self):
        """Combat per unit of resource pain from the best thing we can build.

        The exchange rate between resources and fighting power, which is what
        makes an economic tech comparable to a military one.
        """
        return max((v.score for n, v in self._values.items() if n in self._current),
                   default=0.0)

    def gain(self, tech_key):
        """How much better the best unit this tech unlocks is than what we field.

        Compared within the unit's own role, because a better tank does not make
        a better body redundant -- only a better tank does.

        When we have nothing in that role at all, the comparison falls back to
        the best unit we field of any kind. Otherwise the baseline is zero and
        every first-of-its-kind unlock scores a gain however bad it is: a
        one-attack, ten-health unit that costs a fortune counted as progress
        purely because it was the only thing in its column.
        """
        best = 0.0
        for name in self._unlocks.get(tech_key, ()):
            value = self._values.get(name)
            if not value:
                continue
            baseline = self._best_now.get(value.role) or self.best_score()
            best = max(best, value.score - baseline)
        return max(0.0, best)


def built_levels(provinces, building_library):
    """The highest level of each building chain this nation has actually put up.

    Researching a building level does not make it buildable: a province can only
    ever queue the next item in its chain, so a nation whose factories are all at
    Lvl 1 cannot touch Lvl 9 until it has built seven upgrades at twelve turns
    each. Without this, research runs off ahead of construction and never comes
    back -- which is how a nation ends up holding factory level 8 with nothing
    above Lvl 1 anywhere on the map.

    A chain nobody has started is simply absent, which reads as level 0 -- so
    the first level of a ladder is always allowed and the second is not until
    the first is standing somewhere.
    """
    best = {}
    for prov in provinces or ():
        for name in prov.get("buildings", ()):
            if name not in building_library:
                continue
            tech_key, level = queries.get_building_required_tech(name)
            if tech_key:
                best[tech_key] = max(best.get(tech_key, 0), level)
    return best


def economy_gain(tech_key, level, prices, building_library, income, built=None):
    """Per-turn economic value of a tech that unlocks a building or a flat bonus.

    Priced with the same scarcity vector as units, so a refinery is worth more
    to a nation that has run dry than to one sitting on a fuel mountain.

    Everything here is MARGINAL -- what this level adds over the one below it.
    The building branch used to credit the new building's whole output, which
    for a chain that replaces rather than stacks overstated it by a factor of
    the level: Factory Lvl 8 was scored at 8000 materials a turn when upgrading
    a Lvl 7 province to it actually gains 1000, against the same flat 30,000
    build cost every level charges. The error grew with the level, so the higher
    and less reachable the tier, the better a deal the AI thought it was.
    """
    flat = FLAT_ECONOMY_TECHS.get(tech_key)
    if flat:
        resource, amount = flat
        return max(0.0, prices[resource] * amount)

    if tech_key == "resource_refining":
        # A percentage multiplier, so its worth scales with what is already
        # coming in rather than being a fixed amount.
        return max(0.0, c.RESOURCE_REFINING_BONUS_PER_LVL * sum(
            prices[res] * max(0.0, float(income.get(res, 0))) for res in ai_unit_eval.RESOURCES))

    if tech_key == "fuel_refining":
        return max(0.0, _conversion_gain(level, prices, income))

    # A level the nation could not start building for decades is not worth
    # researching now, however good it would eventually be. This is what stops
    # research running away from construction -- the USA in the save that
    # prompted this held factory level 8 with nothing above Lvl 1 on the map,
    # seven twelve-turn upgrades away from being able to use any of it.
    if built is not None and level > built.get(tech_key, 0) + c.AI_MAX_BUILDING_RESEARCH_LEAD:
        return 0.0

    best = 0.0
    for name in buildings_unlocked_by(tech_key, level, building_library):
        stats = building_library.get(name, {})

        # What the province gains, net of what the level below it stops
        # producing the moment this one is built on top.
        gain = _yield_value(stats, prices)
        replaced = _replaced_building(name, building_library)
        if replaced:
            gain -= _yield_value(building_library[replaced], prices)

        # Net of what it costs to put up, spread over the period a building is
        # given to earn that back -- it keeps producing long after the twenty
        # turns a division is costed against.
        best = max(best, gain - _build_cost(name, stats, prices) / c.AI_BUILDING_PAYBACK_TURNS)
    return max(0.0, best)


def rank_available(available, research, unit_library, building_library, ctx,
                   current_names, current_year, income, built=None):
    """Orders candidate techs best-first.

    `available` is (tech_key, target_year, cost, is_new). Value per point of
    research, discounted by how far ahead of its historical year the tech is --
    research_processor halves progress for every year early, so an off-schedule
    tech genuinely costs several times its sticker price. That term used to be
    the primary sort key, which is why the AI's research order was essentially
    "whatever is cheapest and historical".
    """
    if not available:
        return available

    gains = UnitGains([entry[0] for entry in available], research, unit_library,
                      ctx, current_names)

    # Unit gain and economy gain are not natively comparable: one is an
    # improvement in combat-per-cost, the other is resources per turn. Bridging
    # them through the value of what those resources would buy puts both in the
    # same units -- combat this nation ends up fielding -- so the weight below
    # is a genuine preference dial rather than a number that silently makes one
    # side always win. Without this the economy side was larger by ~10^7 and no
    # military tech was ever researched by anyone.
    buy_rate = gains.best_score()          # combat per unit of resource pain
    horizon = float(c.AI_TECH_ECONOMY_HORIZON)

    def priority(entry):
        tech_key, target_year, cost, _is_new = entry
        level = research.get(tech_key, 0) + 1

        # Applied across the army this nation can afford, not to one unit.
        military = gains.gain(tech_key) * max(1.0, ctx.budget)
        economic = (economy_gain(tech_key, level, ctx.prices, building_library, income, built)
                    * buy_rate * horizon * c.AI_TECH_ECONOMY_WEIGHT)

        pace = queries.get_research_multiplier(current_year, target_year)
        return ((military + economic) * pace) / max(1.0, float(cost))

    # Sorted by name first so equal-value techs resolve the same way every run
    # rather than by dict order.
    return sorted(sorted(available, key=lambda e: e[0]), key=priority, reverse=True)
