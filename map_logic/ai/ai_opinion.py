"""How much a nation wants a thing, rather than whether it is merely allowed.

The AI's grand strategy ran on two booleans. `ai_thinks_it_can_win` returned
true when border strength was 1.2x and global power 0.8x, and that was the whole
of its reasoning about war; `will_ai_accept_peace` flipped on the same function.
Relations were computed, displayed on the map, and consulted by exactly one
branch of one function -- which OR'd them with a shared-enemy check that usually
bypassed them anyway. A nation you had been friendly with for a hundred turns
was exactly as likely to be invaded as a sworn enemy.

Everything here is a degree instead of a threshold, so the same position can
produce different choices from different nations, and relations and temperament
both count. It works with the LLM off; Phase 4 layers a model on top of these
numbers rather than replacing them.

Stdlib and `data` only.
"""

import collections
import math

import data.constants as c
from data import queries
from map_logic.ai import ai_commitments, ai_personality


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _sigmoid(value, midpoint, steepness):
    """0..1, crossing 0.5 at `midpoint`. The soft version of a threshold."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))
    except OverflowError:
        return 0.0 if value < midpoint else 1.0


def traits(world, nation, scenario_settings=None):
    return ai_personality.get(world.nation_data, nation, scenario_settings)


def war_load(world, nation):
    """How stretched this nation already is, 0..1.

    A nation at war with three neighbours should be markedly less keen on a
    fourth, which nothing in the old logic expressed -- it evaluated every
    target in isolation.
    """
    enemies = [e for e in queries.get_enemies(nation, world.nation_data)
               if e in world.nation_data]
    if not enemies:
        return 0.0
    return _clamp01(len(enemies) / float(c.AI_WAR_LOAD_SATURATION))


def target_value(world, nation, target):
    """How much this nation stands to gain from taking the target's land, 0..1."""
    contested = world.claim_pressure.get((target, nation), 0)
    owned = max(1, len(world.provs_by_owner.get(target, ())))
    return _clamp01(contested / float(owned))


def war_desire(world, nation, target, scenario_settings=None):
    """How much `nation` wants a war with `target`, 0..1.

    The two power terms are the same quantities ai_thinks_it_can_win compares,
    but read as degrees rather than as a pass/fail -- with the crossover moved
    by how cautious this nation is, so a bold country gambles on odds a careful
    one turns down. The remaining terms are what the old logic had no way to
    say at all: that we like them, that we promised not to, that we are already
    fighting two wars.
    """
    person = traits(world, nation, scenario_settings)
    caution = person.get("caution", 0.5)

    border_ratio, global_ratio = world.power_ratio(nation, target)

    # Each of these is 0..1 in its own right and they are *averaged*, not added.
    # Summing them saturated the clamp at the top of the range -- any nation
    # with decent odds came out at 1.0 whatever it thought of the target -- and
    # in a full run that produced almost twice as many wars as the old boolean
    # it was supposed to be a more considered version of.
    odds = (c.AI_W_BORDER * _sigmoid(border_ratio,
                                     c.AI_WAR_STRENGTH_THRESHOLD * (0.7 + 0.6 * caution),
                                     c.AI_ODDS_STEEPNESS)
            + c.AI_W_GLOBAL * _sigmoid(global_ratio,
                                       c.AI_GLOBAL_STRENGTH_THRESHOLD * (0.7 + 0.6 * caution),
                                       c.AI_ODDS_STEEPNESS))

    appetite = (c.AI_W_CLAIM * target_value(world, nation, target)
                + c.AI_W_AGGRO * person.get("aggression", 0.5)
                + c.AI_W_AMBITION * person.get("ambition", 0.5))

    core = c.AI_W_ODDS * odds + c.AI_W_APPETITE * appetite

    # Relations now suppress war, which they have never done. Measured from
    # neutral upward only: being disliked does not by itself make a nation
    # attack you, that is what aggression is for, but being genuinely friendly
    # holds it back.
    goodwill = _clamp01(max(0.0, world.relation(nation, target)) / 200.0)
    restraint = (c.AI_W_RELATION * goodwill
                 + c.AI_W_OVEREXTENSION * war_load(world, nation))

    # A promise not to attack, weighted by how much this nation's word is worth
    # to it. A faithless country will still break a pact when the prize is big
    # enough -- which is the interesting outcome, not a bug -- and pay for it.
    restraint += ai_commitments.war_restraint(world.nation_data, nation, target,
                                              scenario_settings)

    # Nobody wants to be the third front for a nation that already spheres this
    # target away from us by agreement.
    if target in ai_commitments.is_sphered(world.nation_data, nation, target):
        restraint += c.AI_COMMITMENT_WEIGHT

    return _clamp01(core - restraint)


def wants_war(world, nation, target, scenario_settings=None):
    """Whether desire clears the bar. The single yes/no the pass still needs."""
    return war_desire(world, nation, target, scenario_settings) >= c.AI_WAR_DESIRE_THRESHOLD


def peace_appetite(world, nation, enemy, scenario_settings=None):
    """How much this nation wants out of its war with `enemy`, 0..1.

    Losing and cautious push toward the table. There was a third term, war
    weariness -- how many turns the war had run, over a fixed twenty-five -- and
    it is gone. It was the second-heaviest weight here, which meant a nation
    winning a long war would sue for peace because of the calendar rather than
    because of anything happening on the map, and the same counter was reading
    as "leverage" on the war-score bar besides. What a nation wants out of a war
    is now decided by how the war is going.
    """
    person = traits(world, nation, scenario_settings)
    border_ratio, global_ratio = world.power_ratio(nation, enemy)
    losing = 1.0 - _sigmoid((border_ratio + global_ratio) / 2.0, 1.0, c.AI_ODDS_STEEPNESS)

    return _clamp01(c.AI_W_PEACE_LOSING * losing
                    + c.AI_W_PEACE_CAUTION * person.get("caution", 0.5))


#: What peace_verdict answers with. `slack` is how far past the line the offer
#: landed -- positive accepted, negative refused, and the size of it is how
#: comfortably. `reason` names whichever constraint actually decided it, in the
#: second person, for the line under the leverage bar.
#: A verdict, and the sentence explaining it twice over.
#:
#: `reason` is what it has always been -- the nation's own words about its own
#: position, which is right for ai_evaluation, where it goes into the model's
#: system prompt as that leader's private reasoning.
#:
#: `detail` is the same sentence as a template, so the same facts can be said to
#: somebody else about them. The builder screen printed `reason` verbatim under a
#: leverage bar labelled "You 41% / Them 59%", so the player read "we are winning
#: this war; 59% of the leverage is ours" and took the 59% for their own. The
#: numbers agreed all along; only the pronouns did not.
#: `detail` defaults to empty so anything that built a three-field Peace -- a
#: test, a mod -- still can, and reason_about falls back to `reason` for it.
Peace = collections.namedtuple("Peace", "accepted slack reason detail",
                               defaults=("",))

#: The two ways of saying a reason. Only pronouns vary: every figure is already
#: formatted into the template, and nations take plural verbs in both voices, so
#: "we hold" and "they hold" are both correct with no conjugation table.
VOICE_SELF = {"we": "we", "us": "us", "our": "our", "ours": "ours"}
VOICE_OTHER = {"we": "they", "us": "them", "our": "their", "ours": "theirs"}


def _verdict(accepted, slack, detail):
    """A verdict from one reason template, said both ways."""
    return Peace(accepted, slack, detail.format(**VOICE_SELF), detail)


def reason_about(verdict):
    """The verdict's reason told to a third party about the nation that holds it.

    What a screen wants: "you hold 7% of their land and are asking for 36% of
    their country", rather than that same sentence in the first person, printed
    to the one person in the conversation who is not its author.
    """
    detail = getattr(verdict, "detail", "")
    return detail.format(**VOICE_OTHER) if detail else verdict.reason


def peace_verdict(world, nation, proposer, agreement, scenario_settings=None):
    """What this nation makes of the offered terms, and by how much.

    It reads the terms rather than the first two words of the sentence they were
    written in -- the version before the rework tested `peace_type.startswith`
    against three constants and fell through to `return True`, so every AI peace
    was agreed unconditionally. That is long fixed. What this rewrite adds is a
    price on *stopping*.

    Four quantities, all as fractions of what this nation is worth to itself:

      demand      what the deal takes from us
      sweetener   what it hands us, with cash capped (see AI_PEACE_CASH_OFFSET_CAP)
      willingness their leverage plus how badly we want out
      war_prize   what we still expect to win by fighting on

    accept  <=>  the war is old enough
            and  demand fits inside what their occupation entitles them to ask
            and  willingness + sweetener >= demand + war_prize + margin

    The two gates in the middle are the ones that were missing, and each maps to
    a save that went wrong. Without `war_prize`, peace was free: a nation being
    handed anything at all -- one material, in `ITS THAT SIMPLE` -- came out
    ahead by arithmetic and signed, one turn into a war it was winning, because
    the old shortcut read `demand <= 0` and returned `gain > 0`. Without the
    occupation ceiling, a demand was weighed only against a *share* of leverage,
    which never approaches zero, so Germany could be handed the British Isles
    without a soldier on them.

    The ceiling is _land_cap_breach, and both sides of its comparison are shares
    of the same nation priced the same way. They were not, which made it far too
    strict in exactly the situation it was written for -- see the note there.
    """
    from map_logic.diplomacy import deal as deal_mod
    from map_logic.diplomacy import war_score

    if not deal_mod.is_deal(agreement):
        agreement = deal_mod.coerce(agreement, proposer, nation, kind=deal_mod.KIND_PEACE)

    nation_data = world.nation_data
    map_data = getattr(world, "map_data", {}) or {}
    duration = nation_data.get(nation, {}).get("war_durations", {}).get(proposer, 0)

    # Stopping a war we have barely started is its own decision. This used to be
    # waived for anyone offering us something, which is precisely how a war two
    # turns old was settled for a single material.
    if duration < c.MIN_TURNS_FOR_CEASEFIRE:
        return _verdict(False, _REFUSED_FLAT,
                        f"{{we}} have been at war {duration} "
                        f"{'turn' if duration == 1 else 'turns'}; "
                        f"there is nothing to settle yet")

    book = deal_mod.ledger(agreement, nation, map_data, nation_data)
    worth = deal_mod.side_worth(agreement, nation, map_data, nation_data)

    # A bloc leader may put a member's territory on the table, so a treaty costs
    # whichever is worse: what the coalition gives up as a share of the
    # coalition, or what its hardest-hit member gives up as a share of itself.
    # Only the first of those existed, and "a fraction of the Allies" is exactly
    # how handing over the whole United Kingdom read as a modest request.
    bloc_demand = (book["given_land"] + book["given_other"]) / worth
    demand = max(bloc_demand, _worst_hit_member(agreement, nation, map_data, nation_data))
    sweetener = book["got_land"] / worth
    cash = book["got_other"] / worth
    # Goods may soften a territorial demand but never buy one outright.
    sweetener += min(cash, demand * c.AI_PEACE_CASH_OFFSET_CAP) if demand > 0 else cash

    # The coalition's own demand here, not `demand` -- that is the worse of two
    # figures on two different scales, and pairing it with the coalition's
    # occupation reintroduces exactly the mismatch _land_cap_breach exists to
    # avoid: a member-sized loss weighed against a bloc-sized grip. Each level
    # is checked against itself inside.
    breach = _land_cap_breach(agreement, nation, map_data, nation_data,
                              max(0.0, bloc_demand - sweetener))
    if breach:
        whose, asked, occupied = breach
        land = "{our} land" if whose is None else f"{whose}'s land"
        country = "{our} country" if whose is None else "it"
        return _verdict(False, _REFUSED_FLAT,
                        f"you hold {_pct(occupied)} of {land} and are asking "
                        f"for {_pct(asked)} of {country}")

    scores = war_score.between(_host(world), nation, proposer, world)
    occupied = deal_mod.occupied_fraction(agreement, nation, map_data, nation_data)
    appetite = peace_appetite(world, nation, proposer, scenario_settings)
    willingness = (c.AI_PEACE_LEVERAGE_W * scores["theirs"]
                   + c.AI_PEACE_APPETITE_W * appetite)
    war_prize = c.AI_PEACE_PRIZE_W * scores["mine"]

    caution = traits(world, nation, scenario_settings).get("caution", 0.5)
    margin = c.AI_PEACE_MARGIN_BASE + c.AI_PEACE_MARGIN_CAUTION * caution

    slack = (willingness + sweetener) - (demand + war_prize + margin)
    return _verdict(slack >= 0, slack,
                    _peace_reason(slack, demand, war_prize, scores, occupied))


#: Slack reported for a refusal that no amount of sweetening fixes -- the war is
#: too young, or the demand is past what occupation entitles them to. Well below
#: the worst verdict band so it always reads as flat refusal.
_REFUSED_FLAT = -1.0


def _pct(fraction):
    return f"{int(round(max(0.0, min(1.0, fraction)) * 100))}%"


def _worst_hit_member(deal, nation, map_data, nation_data):
    """The heaviest loss any one nation on our side is being asked to take."""
    from map_logic.diplomacy import deal as deal_mod

    side = deal_mod.side_of(deal, nation)
    if not side:
        return 0.0
    return max((deal_mod.demand_fraction(deal, member, map_data, nation_data,
                                         whole_side=False)
                for member in deal["sides"][side]), default=0.0)


def _land_cap_breach(deal, nation, map_data, nation_data, net_demand):
    """The worst place this deal asks for more land than occupation entitles.

    Returns (whose, asked, occupied) or None. `whose` is None for the coalition
    as a whole and a member's name otherwise.

    The rule -- you may demand at most AI_PEACE_LAND_ALLOWANCE times the share of
    a country you are actually holding -- is the one that stops an army which has
    not landed in Britain being handed Britain. Both halves have to be shares of
    the *same* thing for that comparison to mean anything, and they were not:
    the demand was measured against the hardest-hit member, and the occupation
    against the whole coalition in a different price table. Twenty-two British
    provinces read as 7% of the Allied homeland against a demand of 36% of the
    United Kingdom, so asking for two of the twenty-two was refused outright.

    Checked at both levels, each against itself: a coalition cannot be stripped
    beyond what is held of it, and neither can any one member of it.
    """
    from map_logic.diplomacy import deal as deal_mod

    side = deal_mod.side_of(deal, nation)
    if not side:
        return None

    def over(subject, asked, whole_side):
        occupied = deal_mod.occupied_fraction(deal, subject, map_data, nation_data,
                                              whole_side=whole_side)
        allowance = max(c.AI_PEACE_MIN_ALLOWANCE,
                        min(1.0, occupied * c.AI_PEACE_LAND_ALLOWANCE))
        return (asked, occupied) if asked > allowance else None

    worst = None
    coalition = over(nation, net_demand, True)
    if coalition:
        worst = (None, *coalition)

    for member in deal["sides"][side]:
        asked = deal_mod.demand_fraction(deal, member, map_data, nation_data,
                                         whole_side=False)
        hit = over(member, asked, False)
        if hit and (worst is None or hit[0] - hit[1] > worst[1] - worst[2]):
            worst = (None if member == nation else member, *hit)
    return worst


def _peace_reason(slack, demand, war_prize, scores, occupied):
    """One sentence naming whichever term is actually driving the answer.

    A template over VOICE_SELF / VOICE_OTHER -- see the note on Peace. Every
    figure is formatted in here; only the pronouns are left to the reader.
    """
    if slack >= 0:
        if demand <= 0:
            return "the fighting has gone on long enough"
        return f"{_pct(demand)} of {{our}} country is a price {{we}} can live with"
    if war_prize > demand + 0.05:
        return (f"{{we}} are winning this war; {_pct(scores['mine'])} "
                f"of the leverage is {{ours}}")
    if demand > 0:
        return (f"you hold {_pct(occupied)} of {{our}} land and are asking for "
                f"{_pct(demand)} of {{our}} country")
    return "{we} are not ready to stop"


def accepts_peace(world, nation, proposer, agreement, scenario_settings=None):
    """Whether this nation takes the offered terms.

    The yes/no half of peace_verdict, kept because it is what the engine, the
    screens and any mod already call.
    """
    return peace_verdict(world, nation, proposer, agreement, scenario_settings).accepted


def verdict_band(slack):
    """(filled dots, out of, sentence) for a slack figure. See AI_VERDICT_BANDS."""
    total = len(c.AI_VERDICT_BANDS)
    for threshold, dots, text in c.AI_VERDICT_BANDS:
        if slack >= threshold:
            return dots, total, text
    _threshold, dots, text = c.AI_VERDICT_BANDS[-1]
    return dots, total, text


class _host:
    """The two attributes war_score reads, borrowed off an AIWorld.

    AIWorld carries map_data and nation_data already; this only spells out that
    those two are all war_score wants, so it works equally off the map screen.
    """

    def __init__(self, world):
        self.map_data = getattr(world, "map_data", {}) or {}
        self.nation_data = world.nation_data


def ratifies(world, member, deal, map_data, scenario_settings=None):
    """Whether a bound faction member swallows terms its leader signed for it.

    A leader negotiates for the whole bloc and may put a member's own territory
    on the table. The member's only recourse is to refuse -- which leaves the
    faction and leaves it at war alone -- so this weighs exactly what the deal
    costs *it*, not what the bloc as a whole came out with.
    """
    from map_logic.diplomacy import deal as deal_mod

    loss = deal_mod.demand_fraction(deal, member, map_data, world.nation_data,
                                    whole_side=False)
    if loss <= 0:
        return True

    enemies = deal_mod.opponents_of(deal, member)
    appetite = max((peace_appetite(world, member, enemy, scenario_settings)
                    for enemy in enemies), default=0.0)

    return appetite >= loss * c.AI_RATIFY_STRICTNESS


def trade_appetite(world, nation, sender, receive, give, prices, scenario_settings=None):
    """What this nation makes of a trade, as a net value in its own price terms.

    `receive` and `give` are {resource: amount}. Priced by scarcity, so a
    fuel-starved nation will genuinely overpay for fuel, and shaded by how much
    it likes the other side -- a friend gets a better rate, an enemy does not
    get one at all. The old rule accepted a trade only if the AI gave literally
    nothing, which is why no AI ever agreed to a deal a player would call fair.
    """
    person = traits(world, nation, scenario_settings)
    gained = sum(prices.get(res, 1.0) * float(amount) for res, amount in receive.items())
    lost = sum(prices.get(res, 1.0) * float(amount) for res, amount in give.items())

    goodwill = (world.relation(nation, sender) / 200.0) * person.get("trust", 0.5)
    return gained - lost * (1.0 - c.AI_TRADE_GOODWILL_DISCOUNT * goodwill)


def trade_verdict(world, nation, sender, agreement, scenario_settings=None):
    """What this nation makes of a proposed trade, in the same shape as peace.

    One function so the line under the player's offer and the answer the engine
    gives come from the same arithmetic -- and so a trade gets a graded reading
    at all. The screen showed nothing whatsoever for a trade, and the engine's
    own answer was a bare `net > 0`, which is a coin-flip presented as a fact
    when the net is one material either way.
    """
    from map_logic.ai import ai_unit_eval
    from map_logic.diplomacy import deal as deal_mod

    if not deal_mod.is_deal(agreement):
        agreement = deal_mod.coerce(agreement, sender, nation, kind=deal_mod.KIND_TRADE)

    if deal_mod.vassalizes(agreement, nation):
        return _verdict(False, _REFUSED_FLAT, "the terms are not {ours} to agree to")

    receive, give = deal_mod.resource_flows(agreement, nation)
    prices = ai_unit_eval.resource_prices(world.economies.get(nation, {}),
                                          world.nation_data.get(nation, {}))
    net = trade_appetite(world, nation, sender, receive, give, prices, scenario_settings)

    # Scaled against the size of the exchange, so "a hundred materials to the
    # good" reads as decisive on a small trade and marginal on a huge one.
    scale = max(1.0, abs(net) + prices.get("materials", 1.0) * c.AI_TRADE_MIN_AMOUNT)
    slack = max(-1.0, min(1.0, net / scale))

    if not any(give.values()):
        reason = "they are asking nothing of {us}"
    elif net > 0:
        reason = "the exchange favours {us}"
    else:
        reason = "{we} give up more than {we} gain"
    return _verdict(net > 0, slack, reason)


def alliance_appetite(world, nation, other, scenario_settings=None):
    """How much this nation wants a formal bloc with `other`, 0..1."""
    person = traits(world, nation, scenario_settings)
    relation = _clamp01((world.relation(nation, other) + 200.0) / 400.0)

    mine = set(queries.get_enemies(nation, world.nation_data))
    theirs = set(queries.get_enemies(other, world.nation_data))
    shared = 1.0 if (mine & theirs) else 0.0

    return _clamp01(c.AI_W_ALLY_RELATION * relation * (0.5 + person.get("trust", 0.5))
                    + c.AI_W_ALLY_SHARED_ENEMY * shared
                    + c.AI_W_ALLY_WEAKNESS * (1.0 - _clamp01(
                        world.power_ratio(nation, other)[1])))
