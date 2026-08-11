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


def economy_gain(tech_key, level, prices, building_library, income):
    """Per-turn economic value of a tech that unlocks a building or a flat bonus.

    Priced with the same scarcity vector as units, so a refinery is worth more
    to a nation that has run dry than to one sitting on a fuel mountain.
    """
    flat = FLAT_ECONOMY_TECHS.get(tech_key)
    if flat:
        resource, amount = flat
        return prices[resource] * amount

    if tech_key == "resource_refining":
        # A percentage multiplier, so its worth scales with what is already
        # coming in rather than being a fixed amount.
        return c.RESOURCE_REFINING_BONUS_PER_LVL * sum(
            prices[res] * max(0.0, float(income.get(res, 0))) for res in ai_unit_eval.RESOURCES)

    best = 0.0
    for name in buildings_unlocked_by(tech_key, level, building_library):
        stats = building_library.get(name, {})
        # Net of what it costs to put up, spread over the horizon an economic
        # tech is credited over rather than the shorter one unit upkeep uses --
        # a factory pays for itself across the rest of the game, not inside the
        # twenty turns a division is costed against.
        build_cost = sum(prices[res] * float(stats.get(f"cost_{res}", 0))
                         for res in ai_unit_eval.RESOURCES)
        best = max(best, _yield_value(stats, prices) - build_cost / c.AI_TECH_ECONOMY_HORIZON)
    return max(0.0, best)


def rank_available(available, research, unit_library, building_library, ctx,
                   current_names, current_year, income):
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
        economic = (economy_gain(tech_key, level, ctx.prices, building_library, income)
                    * buy_rate * horizon * c.AI_TECH_ECONOMY_WEIGHT)

        pace = queries.get_research_multiplier(current_year, target_year)
        return ((military + economic) * pace) / max(1.0, float(cost))

    # Sorted by name first so equal-value techs resolve the same way every run
    # rather than by dict order.
    return sorted(sorted(available, key=lambda e: e[0]), key=priority, reverse=True)
