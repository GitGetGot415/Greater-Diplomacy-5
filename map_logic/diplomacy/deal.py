"""An itemized diplomatic agreement: what each side hands the other.

Peace terms used to be a *sentence*. The three buttons on the peace screen
produced strings like

    "Demand Claims (Territories demanded: 12, 44, 91 + cores)"

which were stored in pending_diplomacy, shown to the player, matched with
`str.startswith` to decide who had won, and finally read back with a regex in
queries.parse_peace_frozen_ids to find out which provinces were meant. Three
separate places had to agree about how to read that sentence and they did not:
the projected-peace map tested `prov["id"] in claims` where the execution tested
`was_original_owner`, and an AI's peace offer -- which carried prose rather than
one of the three magic prefixes -- matched none of the branches at all, so it
was accepted unconditionally and then executed as a white peace.

A deal is data now. The same shape carries a peace treaty and a trade, because
"you give me these two provinces and I give you four thousand tons of fuel" is
the same sentence either way; the only thing peace adds is that the war ends.

    {"v": 1,
     "kind": "PEACE" | "TRADE",
     "sides": {"a": [nation, ...], "b": [nation, ...]},   # a proposed it
     "clauses": [{"type": ..., ...}, ...]}

Clauses are flat dicts -- no nesting below the clause itself. That is not
tidiness: queries.build_save_dict dumps nation_data wholesale, and
turn_processor.snapshot_history copies it only two levels deep, so anything
deeper than a clause would be *aliased* between the live game and every history
snapshot. For the same reason a queued deal is treated as immutable: `add_clause`
and `without_nation` return new deals rather than mutating in place. Editing an
offer replaces it outright.

Stdlib and `data` only, so the AI layers and the screens can both import it.
"""

import data.constants as c

VERSION = 1

KIND_PEACE = "PEACE"
KIND_TRADE = "TRADE"

# --- clause types ---
WHITE_PEACE = "WHITE_PEACE"          # status quo; the war simply ends
TILES = "TILES"                      # provinces change hands
RESOURCES = "RESOURCES"              # one-off stockpile transfer (reparations)
VASSALIZE = "VASSALIZE"              # subject becomes master's puppet
DEMILITARIZE = "DEMILITARIZE"        # may not raise new units for N turns
MILITARY_ACCESS = "MILITARY_ACCESS"  # grantor opens their borders to grantee
FACTION_EXIT = "FACTION_EXIT"        # nation leaves whatever faction it is in
WAR_EXIT = "WAR_EXIT"                # nation drops out of a war with a third party

CLAUSE_TYPES = (WHITE_PEACE, TILES, RESOURCES, VASSALIZE, DEMILITARIZE,
                MILITARY_ACCESS, FACTION_EXIT, WAR_EXIT)

#: Which clauses only make sense inside a peace treaty.
_PEACE_ONLY = (WHITE_PEACE, DEMILITARIZE, WAR_EXIT)


# ==========================================
# CONSTRUCTION
# ==========================================

def new(kind, side_a, side_b, clauses=()):
    """A deal between two blocs. `side_a` is the proposer's side."""
    return {
        "v": VERSION,
        "kind": kind,
        "sides": {"a": list(side_a), "b": list(side_b)},
        "clauses": [dict(clause) for clause in clauses],
    }


def is_deal(obj):
    """Whether this is a deal rather than a legacy terms string or a trade dict."""
    return isinstance(obj, dict) and "clauses" in obj and "sides" in obj


def clauses(deal):
    return deal.get("clauses", []) if isinstance(deal, dict) else []


def with_clauses(deal, new_clauses):
    """A copy of `deal` carrying a different clause list. See the module note on
    why nothing here edits a deal in place."""
    replacement = dict(deal)
    replacement["sides"] = {"a": list(deal["sides"]["a"]), "b": list(deal["sides"]["b"])}
    replacement["clauses"] = [dict(clause) for clause in new_clauses]
    return replacement


def add_clause(deal, clause):
    return with_clauses(deal, list(clauses(deal)) + [clause])


def tiles_clause(giver, receiver, ids, plus_originals=False):
    """`plus_originals` reproduces the old treaties' unwritten rule that the
    winner also recovers any of its own pre-war land the loser is sitting on."""
    clause = {"type": TILES, "from": giver, "to": receiver,
              "ids": sorted({int(i) for i in ids})}
    if plus_originals:
        clause["plus_originals"] = True
    return clause


def resources_clause(giver, receiver, resource, amount):
    return {"type": RESOURCES, "from": giver, "to": receiver,
            "resource": resource, "amount": int(amount)}


def white_peace():
    return {"type": WHITE_PEACE}


def ceasefire_deal(proposer, target, side_a=None, side_b=None):
    """The commonest deal there is: both sides stop, nothing changes hands."""
    return new(KIND_PEACE, side_a or [proposer], side_b or [target], [white_peace()])


# ==========================================
# READING
# ==========================================

def parties(deal):
    """Every nation bound by the deal, proposer's side first."""
    sides = deal.get("sides", {})
    return list(sides.get("a", [])) + list(sides.get("b", []))


def side_of(deal, nation):
    """"a", "b", or None if this nation is not a party."""
    sides = deal.get("sides", {})
    if nation in sides.get("a", []):
        return "a"
    if nation in sides.get("b", []):
        return "b"
    return None


def opponents_of(deal, nation):
    side = side_of(deal, nation)
    if side is None:
        return []
    return list(deal["sides"]["b" if side == "a" else "a"])


def is_white_peace(deal):
    """No clause moves anything -- the war just stops."""
    return all(clause.get("type") == WHITE_PEACE for clause in clauses(deal))


def ends_war(deal):
    return deal.get("kind") == KIND_PEACE


def affected_nations(deal):
    """Nations that are *giving something up*, in deal order.

    These are the ones a faction leader can bind and who therefore get a say --
    see peace_scope's ratification round.
    """
    losers = []
    for clause in clauses(deal):
        for key in ("from", "subject", "nation", "grantor"):
            who = clause.get(key)
            if who and who not in losers:
                losers.append(who)
    return losers


def without_nation(deal, nation):
    """A copy with every clause that takes something from `nation` struck out.

    Used when a bound faction member refuses to ratify: the rest of the treaty
    still stands, that member's share of it does not.
    """
    kept = [clause for clause in clauses(deal)
            if nation not in (clause.get("from"), clause.get("subject"),
                              clause.get("nation"), clause.get("grantor"))]
    stripped = with_clauses(deal, kept)
    for key in ("a", "b"):
        if nation in stripped["sides"][key]:
            stripped["sides"][key].remove(nation)
    return stripped


def tile_transfers(deal, map_data=None, nation_data=None):
    """{prov_id: new_owner} for everything the deal moves.

    Drives both the projected-map preview and the execution, so the two cannot
    disagree the way the string-based versions did. `map_data`/`nation_data` are
    only needed to expand a legacy clause's `plus_originals`.
    """
    from data import queries

    transfers = {}
    for clause in clauses(deal):
        if clause.get("type") != TILES:
            continue
        receiver = clause.get("to")
        for prov_id in clause.get("ids", []):
            transfers[int(prov_id)] = receiver

        if clause.get("plus_originals") and map_data and nation_data:
            giver = clause.get("from")
            for prov in map_data.values():
                if prov.get("owner") == giver and queries.was_original_owner(prov, receiver, nation_data):
                    transfers[int(prov["id"])] = receiver
    return transfers


# ==========================================
# VALIDATION
# ==========================================

def validate(deal, map_data=None, nation_data=None):
    """Everything wrong with this deal, as sentences. Empty list means good.

    Called when a deal is built and again when it is about to execute -- the
    world moves between the two, and a province promised three turns ago may
    have changed hands since.
    """
    problems = []
    if not is_deal(deal):
        return ["Not a deal."]

    everyone = parties(deal)
    if not deal["sides"].get("a") or not deal["sides"].get("b"):
        problems.append("A deal needs a nation on both sides.")
    if set(deal["sides"]["a"]) & set(deal["sides"]["b"]):
        problems.append("A nation cannot be on both sides of a deal.")
    if not clauses(deal):
        problems.append("A deal with no terms is not a deal.")

    for clause in clauses(deal):
        kind = clause.get("type")
        if kind not in CLAUSE_TYPES:
            problems.append(f"Unknown term '{kind}'.")
            continue
        if kind in _PEACE_ONLY and deal.get("kind") != KIND_PEACE:
            problems.append(f"'{kind}' only belongs in a peace treaty.")

        for key in ("from", "to", "subject", "master", "nation", "grantor", "grantee"):
            who = clause.get(key)
            if who and who not in everyone:
                problems.append(f"{who} is named in the terms but is not party to the deal.")

        if kind == TILES:
            if not clause.get("ids") and not clause.get("plus_originals"):
                problems.append("A territory term with no provinces in it.")
            if map_data:
                giver = clause.get("from")
                by_id = {prov["id"]: prov for prov in map_data.values()}
                for prov_id in clause.get("ids", []):
                    prov = by_id.get(int(prov_id))
                    if prov is None:
                        problems.append(f"Province {prov_id} no longer exists.")
                    elif prov.get("owner") != giver:
                        problems.append(f"{giver} no longer holds province {prov_id}.")
        elif kind == RESOURCES:
            if clause.get("resource") not in c.ECON_RESOURCE_KEYS:
                problems.append(f"Cannot trade '{clause.get('resource')}'.")
            if int(clause.get("amount", 0)) <= 0:
                problems.append("A payment of nothing is not a term.")
        elif kind == VASSALIZE and nation_data:
            subject = clause.get("subject")
            if nation_data.get(subject, {}).get("master"):
                problems.append(f"{subject} is already a puppet.")

    return problems


# ==========================================
# VALUATION
# ==========================================
# One currency for provinces, stockpiles and subjugation, so the AI can weigh
# "six provinces plus vassalage" against how badly it is losing the war. The
# absolute scale means nothing; only the ratios do.

def tile_value(prov):
    """What a province is worth before anyone's feelings about it."""
    value = c.DEAL_VALUE_TILE_BASE
    value += len(prov.get("buildings", [])) * c.DEAL_VALUE_BUILDING

    resources = prov.get("resources")
    if isinstance(resources, dict):
        total = sum(int(resources.get(key, 0) or 0)
                    for key in ("Iron", "Coal", "Oil", "Wheat"))
        value += total * c.DEAL_VALUE_RESOURCE_UNIT
    return value


def tile_value_between(prov, giver, receiver, nation_data):
    """What losing this province costs `giver`, given who is taking it.

    Their own core land hurts to lose; land the receiver has long claimed is
    cheaper to give up, which is now the whole job claims do at the peace table;
    land the receiver's army is already standing on is half-lost already.
    """
    value = tile_value(prov)

    if giver and giver in prov.get("cores", []):
        value *= c.DEAL_VALUE_CORE_MULT

    if receiver:
        claims = nation_data.get(receiver, {}).get("claims", []) if nation_data else []
        if prov["id"] in claims or receiver in prov.get("cores", []):
            value *= c.DEAL_VALUE_CLAIM_MULT
        if any(unit.get("owner") == receiver for unit in prov.get("units", [])):
            value *= c.DEAL_VALUE_OCCUPIED_MULT

    return value


def nation_total_value(nation, map_data, nation_data):
    """Everything a nation has, in the same currency, for normalising demands.

    Never zero: a nation reduced to one province still has to be able to say
    that giving up that province would be total.
    """
    total = 0.0
    for prov in map_data.values():
        if prov.get("owner") == nation:
            total += tile_value(prov)

    stock = nation_data.get(nation, {})
    for resource, price in c.DEAL_VALUE_RESOURCE_PRICES.items():
        total += float(stock.get(resource, 0) or 0) * price

    return max(total, c.DEAL_VALUE_TILE_BASE)


def clause_value(clause, map_data, nation_data):
    """What this clause is worth to whoever receives it."""
    kind = clause.get("type")

    if kind == TILES:
        giver, receiver = clause.get("from"), clause.get("to")
        wanted = {int(i) for i in clause.get("ids", [])}
        total = 0.0
        for prov in map_data.values():
            if prov["id"] in wanted:
                total += tile_value_between(prov, giver, receiver, nation_data)
        return total

    if kind == RESOURCES:
        price = c.DEAL_VALUE_RESOURCE_PRICES.get(clause.get("resource"), 1.0)
        return float(clause.get("amount", 0)) * price

    if kind == VASSALIZE:
        subject = clause.get("subject")
        return nation_total_value(subject, map_data, nation_data) * c.DEAL_VALUE_VASSAL_FRACTION

    if kind == DEMILITARIZE:
        return float(clause.get("turns", 0)) * c.DEAL_VALUE_DEMILITARIZE_PER_TURN

    if kind == MILITARY_ACCESS:
        return c.DEAL_VALUE_MILITARY_ACCESS
    if kind == FACTION_EXIT:
        return c.DEAL_VALUE_FACTION_EXIT
    if kind == WAR_EXIT:
        return c.DEAL_VALUE_WAR_EXIT

    return 0.0  # WHITE_PEACE costs nobody anything


def _clause_receiver(clause):
    kind = clause.get("type")
    if kind in (TILES, RESOURCES):
        return clause.get("to")
    if kind == VASSALIZE:
        return clause.get("master")
    if kind == MILITARY_ACCESS:
        return clause.get("grantee")
    return None


def _clause_giver(clause):
    kind = clause.get("type")
    if kind in (TILES, RESOURCES):
        return clause.get("from")
    if kind == VASSALIZE:
        return clause.get("subject")
    if kind == MILITARY_ACCESS:
        return clause.get("grantor")
    if kind in (DEMILITARIZE, FACTION_EXIT, WAR_EXIT):
        return clause.get("nation")
    return None


def net_value(deal, nation, map_data, nation_data, whole_side=True):
    """What the deal is worth to `nation`. Positive means it comes out ahead.

    `whole_side=True` counts what the nation's allies gain and lose too, which
    is what a faction leader weighing a bloc treaty cares about; a member being
    asked to ratify wants only its own column, so it passes False.
    """
    side = side_of(deal, nation)
    mine = set(deal["sides"][side]) if (whole_side and side) else {nation}

    total = 0.0
    for clause in clauses(deal):
        value = clause_value(clause, map_data, nation_data)
        if _clause_receiver(clause) in mine:
            total += value
        if _clause_giver(clause) in mine:
            total -= value
    return total


def demand_fraction(deal, nation, map_data, nation_data, whole_side=True):
    """How much of itself this deal asks `nation` to give up, 0..1.

    Zero when the deal is neutral or favourable. This is the number the AI
    weighs its leverage against.
    """
    net = net_value(deal, nation, map_data, nation_data, whole_side)
    if net >= 0:
        return 0.0

    side = side_of(deal, nation)
    bloc = deal["sides"][side] if (whole_side and side) else [nation]
    worth = sum(nation_total_value(member, map_data, nation_data) for member in bloc)
    return max(0.0, min(1.0, -net / max(worth, 1.0)))


# ==========================================
# PRESENTATION
# ==========================================

def _tile_word(count):
    return "province" if count == 1 else "provinces"


def describe(deal, viewer=None, nation_data=None):
    """The terms in words, as a list of lines for a message thread or a panel.

    `viewer` is whose point of view to write from; without one the nations are
    named outright, which is what a spectator reading someone else's treaty
    needs -- "You receive" is a lie when the reader is neither party.
    """
    if not is_deal(deal):
        return []

    def name(nation):
        if viewer and nation == viewer:
            return "you"
        return nation

    lines = []
    for clause in clauses(deal):
        kind = clause.get("type")

        if kind == WHITE_PEACE:
            lines.append("White peace: the fighting stops, the map stands.")
        elif kind == TILES:
            count = len(clause.get("ids", []))
            what = f"{count} {_tile_word(count)}" if count else "territory"
            if clause.get("plus_originals"):
                what += " (plus any occupied homeland)"
            lines.append(f"{name(clause['from'])} cede {what} to {name(clause['to'])}.")
        elif kind == RESOURCES:
            lines.append(f"{name(clause['from'])} pay {int(clause.get('amount', 0))} "
                         f"{clause.get('resource', '').title()} to {name(clause['to'])}.")
        elif kind == VASSALIZE:
            lines.append(f"{name(clause['subject'])} become a puppet of {name(clause['master'])}.")
        elif kind == DEMILITARIZE:
            lines.append(f"{name(clause['nation'])} may raise no new units "
                         f"for {int(clause.get('turns', 0))} turns.")
        elif kind == MILITARY_ACCESS:
            lines.append(f"{name(clause['grantor'])} grant passage to {name(clause['grantee'])}.")
        elif kind == FACTION_EXIT:
            faction = (nation_data or {}).get(clause.get("nation"), {}).get("faction", "")
            lines.append(f"{name(clause['nation'])} leave {faction or 'their faction'}.")
        elif kind == WAR_EXIT:
            lines.append(f"{name(clause['nation'])} withdraw from the war "
                         f"against {name(clause.get('against', ''))}.")

    bound = [n for n in parties(deal) if n != viewer]
    if len(bound) > 1:
        lines.append(f"Bound by these terms: {', '.join(bound)}.")

    return lines


def headline(deal, viewer=None):
    """One line naming what kind of deal this is, for a button or a log entry."""
    if not is_deal(deal):
        return str(deal)
    if is_white_peace(deal):
        return c.PEACE_WHITE_PEACE
    if deal.get("kind") == KIND_TRADE:
        return "Trade Agreement"
    net_gain = any(_clause_receiver(clause) == viewer for clause in clauses(deal))
    return "Peace Terms" if net_gain else "Peace Settlement"


# ==========================================
# LEGACY SAVES
# ==========================================

def from_legacy_string(peace_type, proposer, target):
    """Turns one of the three old peace sentences into a deal.

    Saves made before the rework can have a peace offer in flight, and the AI's
    own offers carried free prose where the terms were supposed to be. Anything
    that is not recognisably a demand is read as a white peace, which is what
    those offers already did when they executed -- treaty_effects fell back to
    PEACE_WHITE_PEACE whenever the parameters were empty.
    """
    from data import queries

    terms = peace_type if isinstance(peace_type, str) else ""

    if not (terms.startswith(c.PEACE_DEMAND_CLAIMS) or terms.startswith(c.PEACE_SURRENDER)):
        return ceasefire_deal(proposer, target)

    winner, loser = queries.get_peace_winner_loser(terms, proposer, target)
    frozen = queries.parse_peace_frozen_ids(terms)
    return new(KIND_PEACE, [proposer], [target],
               [tiles_clause(loser, winner, frozen, plus_originals=True)])


def coerce(params, proposer, target, kind=None):
    """Whatever was stored on a pending action, as a deal.

    Three shapes reach this: a real deal, one of the old peace strings, and the
    old four-key trade dict {give_materials, take_fuel, puppet_state, ...}. Pass
    `kind` when the caller knows which it should be -- an AI peace offer carried
    free prose where the terms belonged, and reading that as a trade would be
    worse than reading it as the white peace it always executed as.
    """
    if is_deal(params):
        return params

    if kind == KIND_PEACE:
        return from_legacy_string(params if isinstance(params, str) else "", proposer, target)

    if isinstance(params, dict):
        deal = new(KIND_TRADE, [proposer], [target])
        for resource in c.TRADE_RESOURCE_KEYS:
            given = int(params.get(f"give_{resource}", 0) or 0)
            taken = int(params.get(f"take_{resource}", 0) or 0)
            if given > 0:
                deal = add_clause(deal, resources_clause(proposer, target, resource, given))
            if taken > 0:
                deal = add_clause(deal, resources_clause(target, proposer, resource, taken))

        puppet_state = params.get("puppet_state", "NONE")
        if puppet_state == "SENDER":
            deal = add_clause(deal, {"type": VASSALIZE, "master": proposer, "subject": target,
                                     "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        elif puppet_state == "RECEIVER":
            deal = add_clause(deal, {"type": VASSALIZE, "master": target, "subject": proposer,
                                     "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        return deal

    return from_legacy_string(params, proposer, target)
