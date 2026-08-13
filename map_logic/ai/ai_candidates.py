"""The legal diplomatic moves a nation could make this turn, each with a price.

The proactive pass used to write straight into pending_diplomacy, which holds
one action per target. Eight sections ran in a fixed order competing for that
slot, so a Call to Arms queued by section 2 silently starved the war
declaration section 4 wanted to send to the same nation -- the earliest-numbered
section won, not the most important one, and nothing anywhere compared them.

Sections now emit candidates and an arbiter picks. With the model switched off
that arbiter is `sorted(by score)`, which on its own fixes the starvation. With
it on (phase 4) the same list becomes the menu the model chooses from -- and
because every candidate was built by the ordinary rules, complete with its
cooldowns, truces and wargoal checks, there is nothing illegal on it for the
model to pick. That invariant is what makes handing a language model the
diplomacy of a whole map safe.

Stdlib and `data` only.
"""

import collections
import hashlib

import data.constants as c
from data import queries

#: One legal, executable action.
#:
#: cid       -- index within this nation's list; what the model answers with,
#:              so it cannot name an action or a country that does not exist
#: score     -- 0..1 desirability, from ai_opinion where there is a real
#:              appetite to measure
#: rationale -- one sentence of why, for the prompt and the event log
#: payload   -- everything _queue_proactive_proposal needs: context_target for
#:              the wording, parameters for trades and peace terms
Candidate = collections.namedtuple(
    "Candidate", "cid action target score rationale payload")


def make(action, target, score, rationale, **payload):
    """A candidate with its index left blank; the collector assigns those."""
    return Candidate(cid="", action=action, target=target,
                     score=max(0.0, min(1.0, float(score))),
                     rationale=rationale, payload=payload)


class Collector:
    """Gathers one nation's options for the turn.

    Deliberately dumb about legality: a section decides whether an action is
    allowed, exactly as it always did, and this only refuses to hold two
    proposals aimed at the same nation.
    """

    def __init__(self, nation, pending):
        self.nation = nation
        self.pending = pending
        self._by_target = {}

    def add(self, candidate):
        """Offers a candidate. The better of two aimed at the same target wins."""
        if candidate is None:
            return False
        if not self._target_is_free(candidate.target):
            return False

        existing = self._by_target.get(candidate.target)
        if existing is not None and existing.score >= candidate.score:
            return False

        self._by_target[candidate.target] = candidate
        return True

    def _target_is_free(self, target):
        """pending_diplomacy holds one action per target, and a proposal already
        travelling must not be overwritten under the recipient."""
        existing = self.pending.get(target)
        if existing is None:
            return True
        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
        return turns == 0

    def ranked(self, limit=None):
        """Best first, indexed. Ties break on target name so runs agree."""
        ordered = sorted(self._by_target.values(),
                         key=lambda cand: (-cand.score, cand.action, cand.target))
        if limit is not None:
            ordered = ordered[:limit]
        return [cand._replace(cid=str(i)) for i, cand in enumerate(ordered)]

    def __len__(self):
        return len(self._by_target)


def describe(candidate):
    """One line for a prompt or a log entry."""
    verb = c.AI_ACTION_PHRASES.get(candidate.action, candidate.action.replace("_", " ").lower())
    return f"{verb} {candidate.target} -- staff rating {candidate.score:.2f} -- {candidate.rationale}"


def _haggle(nation, partner, turn, spread=c.AI_TRADE_JITTER):
    """A stable per-pair, per-turn wobble in 1±spread.

    Not `random`: the same save re-run has to make the same offers, and
    ai_personality already establishes hashing the names as how this codebase
    gets determinism it can reproduce. Without it every nation on the map sizes
    its offer with the same arithmetic and arrives at the same round number,
    which is what made the AI's proposals read as one copy-pasted message.
    """
    digest = hashlib.sha256(f"{nation}|{partner}|{turn}".encode("utf-8")).digest()
    unit_interval = int.from_bytes(digest[:4], "big") / float(0xFFFFFFFF)
    return 1.0 + spread * (unit_interval * 2.0 - 1.0)


def _negotiators_number(amount):
    """Rounds to something a person would say. 1,175 is a spreadsheet; 1,200 is
    an offer."""
    if amount <= 0:
        return 0
    step = c.AI_TRADE_ROUNDING
    while step > 1 and amount < step * 4:
        step //= 2
    return max(step, int(round(amount / float(step)) * step))


def resource_offer(world, nation, partner, scenario_settings=None):
    """A trade worth proposing, or None.

    Looks for a genuine complementarity: something we have spare that they are
    short of, against something they have spare that we are short of.

    The asking price used to be `int(their_surplus * 0.5)` -- computed entirely
    from the *recipient's* economy with a flat constant and no variation of any
    kind. Every nation on the map therefore asked the same player for the
    identical number, and it only moved when the player's own income did, so a
    dozen different countries would open with a request for exactly 3,140 fuel.

    What a nation asks for is now what it is short of, scaled by how pushy it is
    and how much it likes you, wobbled per pair and rounded to a number somebody
    would actually say out loud.
    """
    from map_logic.ai import ai_personality

    econ_a = world.economies.get(nation, {})
    econ_b = world.economies.get(partner, {})
    if not econ_a or not econ_b:
        return None

    stock_a = world.nation_data.get(nation, {})
    stock_b = world.nation_data.get(partner, {})

    def surplus(econ, stock, resource):
        income = float(econ.get("total_inc", {}).get(resource, 0))
        upkeep = float(econ.get("upkeep", {}).get(resource, 0))
        return (income - upkeep) + float(stock.get(resource, 0)) / c.AI_TRADE_STOCK_TURNS

    tradeable = ("materials", "fuel")
    mine = {r: surplus(econ_a, stock_a, r) for r in tradeable}
    theirs = {r: surplus(econ_b, stock_b, r) for r in tradeable}

    # What I can spare against what I am shortest of -- NOT my best surplus
    # against theirs. Nearly every nation is longest on materials and shortest
    # on fuel, so comparing the two bests picked the same resource on both sides
    # and the function returned None for every pair on the map.
    give = max(tradeable, key=lambda r: (mine[r], r))
    take = min(tradeable, key=lambda r: (mine[r], r))
    if give == take or mine[give] <= 0 or theirs[take] <= 0:
        return None

    person = ai_personality.get(world.nation_data, nation, scenario_settings)
    turn = getattr(world, "total_turns", 0)

    # How hard this particular nation pushes this particular partner, this turn.
    # An ambitious one asks for more, one that likes you asks for less, one that
    # is genuinely short asks harder. None of that existed: a warm neighbour and
    # a cold one made you the same offer, in the same words, every time.
    goodwill = max(-1.0, min(1.0, world.relation(nation, partner) / 200.0))
    share = (c.AI_TRADE_ASK_BASE_SHARE
             + c.AI_TRADE_ASK_AMBITION * (person.get("ambition", 0.5) - 0.5)
             - c.AI_TRADE_ASK_GOODWILL * goodwill)

    deficit = max(0.0, -mine[take])
    if deficit > 0:
        share += c.AI_TRADE_ASK_NEED * min(1.0, deficit / theirs[take])

    share = max(c.AI_TRADE_ASK_MIN_SHARE,
                min(c.AI_TRADE_MAX_SHARE, share * _haggle(nation, partner, turn)))

    # Sized to what each side can spare rather than matched one for one:
    # materials and fuel are nothing like the same value, and an even swap by
    # volume would be an absurd offer. Whether it is a fair deal is the
    # recipient's judgement, and trade_appetite prices it properly.
    give_amount = _negotiators_number(
        mine[give] * c.AI_TRADE_OFFER_FRACTION * _haggle(partner, nation, turn))
    take_amount = _negotiators_number(theirs[take] * share)
    if give_amount < c.AI_TRADE_MIN_AMOUNT or take_amount <= 0:
        return None

    # Read from the sender's point of view, as the diplomacy screen's parameters
    # are: we "give" what they receive.
    return {f"give_{give}": give_amount, f"take_{take}": take_amount}


def sole_target_of(nation_data, nation, action):
    """Whether this nation already has a proposal of `action` out to anyone.

    Some actions only make sense one at a time -- asking three separate leaders
    to let you into their faction reads as desperation and used to happen.
    """
    for info in (nation_data.get(nation, {}).get("pending_diplomacy") or {}).values():
        if isinstance(info, dict) and info.get("action") == action:
            return True
    return False


def not_on_cooldown(nation_data, nation, target, action):
    return not queries.is_ai_diplo_on_cooldown(nation, target, action, nation_data)
