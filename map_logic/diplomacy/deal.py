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

def validate(deal, map_data=None, nation_data=None, reach_index=None):
    """Everything wrong with this deal, as sentences. Empty list means good.

    Called when a deal is built and again when it is about to execute -- the
    world moves between the two, and a province promised three turns ago may
    have changed hands since.

    `reach_index` is a reach.Reachability; one is built from `map_data` if the
    caller has not got one already. A caller that validates repeatedly -- the
    deal screen does, on every click -- should hold one and pass it in.
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
                # The giving side needs *title*, not possession. This demanded
                # the named giver still hold the ground, which is exactly wrong
                # for the commonest term there is -- a demand for land the
                # demander's army is already standing on. deal_effects.prune was
                # fixed to the three-way test below and this was left behind, so
                # the two halves of the same question disagreed: prune honoured
                # a term that validate would not let you send.
                giver = clause.get("from")
                giving_side = set(deal["sides"].get(side_of(deal, giver) or "a") or [])
                receiving_side = set(deal["sides"].get(side_of(deal, clause.get("to")) or "b") or [])
                by_id = {prov["id"]: prov for prov in map_data.values()}
                prewar = prewar_index(nation_data) if nation_data else {}

                for prov_id in clause.get("ids", []):
                    prov = by_id.get(int(prov_id))
                    if prov is None:
                        problems.append(f"Province {prov_id} no longer exists.")
                        continue
                    owner = prov.get("owner")
                    if owner in giving_side:
                        continue
                    if (owner in receiving_side
                            and original_owner(prov, prewar) in giving_side):
                        continue  # ours by force already; the treaty makes it ours by right
                    problems.append(f"{giver} no longer holds province {prov_id}.")

                problems.extend(_out_of_reach(clause, map_data, reach_index))
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


def _out_of_reach(clause, map_data, reach_index=None):
    """Complaints about provinces the receiver has no way of getting to.

    Land you cannot reach is not land you can be given. A demand used to be
    bounded only by who was at war with whom, so a treaty with the United
    Kingdom could name Australia, and a trade could move a province between two
    countries on opposite sides of the world.

    Judged on the *receiver* of each term rather than on whoever drafted the
    deal, which is what closes the obvious way round it: handing unreachable
    land to a puppet or an ally is that nation's reach to satisfy, not yours.
    """
    from map_logic.diplomacy import reach as reach_mod

    receiver = clause.get("to")
    ids = clause.get("ids") or ()
    if not receiver or not ids:
        return []

    index = reach_index or reach_mod.index(map_data)
    return [f"{receiver} cannot reach province {prov_id} -- it borders none of "
            f"their land and no water they sit on."
            for prov_id in index.unreachable_ids(receiver, ids)]


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


#: Whose books a province is being valued on. A deal has two sides and they do
#: not price the same tile the same way, which is the whole reason this argument
#: exists -- see the occupation note in tile_value_between.
GIVER = "giver"
RECEIVER = "receiver"


def tile_value_between(prov, giver, receiver, nation_data, perspective=RECEIVER):
    """What this province is worth in a deal, on `perspective`'s books.

    Their own core land hurts to lose; land the receiver has long claimed is
    cheaper to give up, which is now the whole job claims do at the peace table.

    The third modifier, "the receiver's army is already standing on it", applies
    only to the *receiver*. It is a real discount on what taking the tile is
    worth -- you already have it, the treaty only makes it official -- and it was
    nonsense on the giver's side: having your province occupied does not make you
    value it less, and pretending it does is double-counting, because occupation
    is already what decides how much can be demanded of you at all.

    Left in, the two discounts compounded: a core the receiver claimed and
    occupied came out at 2.0 x 0.5 x 0.6 = 0.6, cheaper than a bare tile the
    giver did not even core. Worse, nation_total_value -- the denominator every
    demand is measured against -- has no receiver to apply them for, so the same
    land was priced high as part of the country and low as part of the demand.
    That gap is a large part of why the United Kingdom agreed to hand over the
    British Isles.
    """
    value = tile_value(prov)

    if giver and giver in prov.get("cores", []):
        value *= c.DEAL_VALUE_CORE_MULT

    if receiver:
        claims = nation_data.get(receiver, {}).get("claims", []) if nation_data else []
        if prov["id"] in claims or receiver in prov.get("cores", []):
            value *= c.DEAL_VALUE_CLAIM_MULT
        if perspective == RECEIVER and any(
                unit.get("owner") == receiver for unit in prov.get("units", [])):
            value *= c.DEAL_VALUE_OCCUPIED_MULT

    return value


def prewar_index(nation_data):
    """{province id (as str): owner when the war began}, across every snapshot.

    Two sources, neither overlapping the other: save_faction_pre_war_map records
    a faction's own members' provinces when it goes to war, and WAR_PRE_MAPS does
    the same one nation at a time for belligerents with no faction to snapshot
    them -- see war_actions.finalize_war.

    Lives here rather than in war_score because valuation needs it too and
    war_score already imports this module; the other direction would be a cycle.
    war_score re-exports both of these for its own callers.
    """
    merged = {}
    for key in ("FACTION_WAR_MAPS", "WAR_PRE_MAPS"):
        for snapshot in (nation_data.get(key) or {}).values():
            if isinstance(snapshot, dict):
                merged.update(snapshot)
    return merged


def original_owner(prov, prewar):
    """Who this province belonged to before the shooting started.

    The inverse of queries.was_original_owner, which answers the same question
    one nation at a time; asking it per nation per province would be a sweep per
    belligerent. Same two rules in the same order: the pre-war snapshot if there
    is one, otherwise cores. A province with several cores resolves to the first,
    which load_map treats as the primary one.
    """
    owner = prewar.get(str(prov["id"]))
    if owner:
        return owner
    cores = prov.get("cores") or []
    return cores[0] if cores else prov.get("owner")


def baseline_owners(deal, map_data, nation_data, prewar=None):
    """{province id: who owns it if this deal is signed with none of its tile terms}.

    The map a treaty is measured against. For a peace that is the pre-war map
    between the two sides, because unnamed occupied land goes home when the
    fighting stops -- see deal_effects.restore_occupied, which is where that rule
    was written and, until this function existed, the only place it was known.

    Everything else on the screen was still measuring against the *current* map,
    and the gap between the two is not cosmetic. deal_screen named the current
    holder as a term's giver, so demanding land you already occupy emitted
    {from: You, to: You}: a clause the other side is not party to, worth nothing
    in their ledger, leaving the verdict bit-identical to a white peace. The
    mirror of it was worse -- handing back a province that was reverting anyway
    scored as a gift, so a player could fill the give column with land they were
    losing regardless and have it read as generosity.

    Only land taken from the other side of *this* war moves. A conquest from a
    third party is not this treaty's business and stands, and a trade ends no
    war, so its baseline is simply the map as it is.

    Keyed by int province id, to match tile_transfers and the clause id lists.
    """
    live = {int(prov["id"]): prov.get("owner") for prov in map_data.values()}
    if not is_deal(deal) or not ends_war(deal):
        return live

    if prewar is None:
        prewar = prewar_index(nation_data)

    a = set(deal["sides"].get("a") or [])
    b = set(deal["sides"].get("b") or [])

    for prov in map_data.values():
        holder = prov.get("owner")
        other = b if holder in a else (a if holder in b else None)
        if other is None:
            continue
        was = original_owner(prov, prewar)
        if was != holder and was in other:
            live[int(prov["id"])] = was
    return live


def nation_total_value(nation, map_data, nation_data, prewar=None):
    """What a nation amounts to, for measuring how much of itself a deal costs it.

    Land only, and priced the way *losing* it would be priced -- core multiplier
    and all. Three deliberate choices:

    Stockpiles are not counted. A nation is its territory; its treasury is
    recoverable and, at the prices above, a full warchest can outweigh a core
    province, which made giving one up read as a quarter of the country rather
    than a third of it.

    The core multiplier is applied here as well as in tile_value_between so the
    two sides of the fraction are measured the same way. Without it a demand for
    two core provinces comes out as a larger share of the nation than the nation
    is worth to itself, and every serious demand rounds to total.

    A nation is worth its *homeland* -- what it holds now, plus what has been
    taken from it in the war -- and not merely what it still holds. Counting only
    current holdings made a country worth less the worse the war went for it, so
    the same province read as a third of a nation that had lost nothing and as
    all of one that was down to its last two, and every demand looked more
    outrageous the more justified it had become. It also put this figure in a
    different currency from war_score.occupation, which has always measured the
    pre-war homeland -- and the AI compares the two directly.

    Never zero: a nation reduced to one province still has to be able to say that
    giving up that province would be everything.
    """
    if prewar is None:
        prewar = prewar_index(nation_data)

    total = 0.0
    for prov in map_data.values():
        if prov.get("owner") == nation or original_owner(prov, prewar) == nation:
            total += tile_value_between(prov, nation, None, nation_data)

    return max(total, c.DEAL_VALUE_TILE_BASE)


def tile_moves(clause, map_data, nation_data, baseline=None):
    """Every province a TILES term actually moves, as (loser, taker, prov).

    Who loses a province is a fact about the map, not about what the clause
    calls itself. It was read straight off clause["from"], which is only right
    when the giver still holds the ground -- and a demand is usually for ground
    the *demander* is standing on, which is what winning a war looks like. The
    screen named the occupier, so the term read as a nation giving a province to
    itself, and the side it was actually taken from never saw it in their books.

    Provinces the baseline already hands to the receiver are not moves at all
    and are left out.
    """
    from data import queries

    giver, receiver = clause.get("from"), clause.get("to")
    wanted = {int(i) for i in clause.get("ids", [])}
    recover_homeland = clause.get("plus_originals", False)

    for prov in map_data.values():
        if not (prov["id"] in wanted or (
                recover_homeland and prov.get("owner") == giver
                and queries.was_original_owner(prov, receiver, nation_data))):
            continue

        loser = giver if baseline is None else baseline.get(int(prov["id"]),
                                                            prov.get("owner"))
        if loser == receiver:
            continue
        yield loser, receiver, prov


def clause_value(clause, map_data, nation_data, perspective=RECEIVER, baseline=None):
    """What this clause is worth, on `perspective`'s books.

    RECEIVER prices a gain, GIVER prices a loss. Only TILES actually differs
    between the two; everything else is worth the same to both.

    `baseline` is baseline_owners() -- who holds each province if this deal is
    signed with none of its tile terms. Given one, a TILES term is priced as the
    difference it makes to *that* map rather than to the live one: a province
    already going to the receiver anyway is worth nothing, and one that is not
    costs whoever it is being taken from, whether or not their army is still
    standing on it. Optional, and absent it falls back to the live map, so a
    caller from before this argument existed gets the old answer.
    """
    kind = clause.get("type")

    if kind == TILES:
        return sum(tile_value_between(prov, loser, taker, nation_data, perspective)
                   for loser, taker, prov
                   in tile_moves(clause, map_data, nation_data, baseline))

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


#: Clause types that move territory rather than goods. A vassal is a country,
#: not a payment, so vassalage is counted here -- the point of the distinction is
#: that a stockpile can be rebuilt and a province cannot.
_LAND_CLAUSES = (TILES, VASSALIZE)


def ledger(deal, nation, map_data, nation_data, whole_side=True):
    """Everything this deal moves for `nation`, kept in four separate columns.

    {"given_land", "given_other", "got_land", "got_other"}, all non-negative.

    net_value collapses these into one number, which is right for "did we come
    out ahead" and wrong for everything else -- it let one material of positive
    value stand in for the whole question of whether to stop fighting, and it let
    a big enough payment stand in for a province. Kept apart, a caller can price
    land as land and cash as cash.

    Territory is booked province by province against the deal's baseline, so a
    term is worth what it changes rather than what it claims to be.
    """
    side = side_of(deal, nation)
    mine = set(deal["sides"][side]) if (whole_side and side) else {nation}
    baseline = baseline_owners(deal, map_data, nation_data)

    book = {"given_land": 0.0, "given_other": 0.0, "got_land": 0.0, "got_other": 0.0}
    for clause in clauses(deal):
        if clause.get("type") == TILES:
            for loser, taker, prov in tile_moves(clause, map_data, nation_data, baseline):
                if taker in mine:
                    book["got_land"] += tile_value_between(prov, loser, taker,
                                                           nation_data, RECEIVER)
                if loser in mine:
                    book["given_land"] += tile_value_between(prov, loser, taker,
                                                             nation_data, GIVER)
            continue

        column = "land" if clause.get("type") in _LAND_CLAUSES else "other"
        if _clause_receiver(clause) in mine:
            book["got_" + column] += clause_value(clause, map_data, nation_data, RECEIVER)
        if _clause_giver(clause) in mine:
            book["given_" + column] += clause_value(clause, map_data, nation_data, GIVER)
    return book


def resource_flows(deal, nation):
    """({resource: amount} coming to `nation`, {resource: amount} leaving it).

    Both dicts always carry every tradeable resource, so a caller can price them
    without worrying about which keys happen to be present.
    """
    receive = {resource: 0 for resource in c.TRADE_RESOURCE_KEYS}
    give = dict(receive)

    for clause in clauses(deal):
        if clause.get("type") != RESOURCES:
            continue
        resource = clause.get("resource")
        if resource not in receive:
            continue
        amount = float(clause.get("amount", 0) or 0)
        if clause.get("to") == nation:
            receive[resource] += amount
        if clause.get("from") == nation:
            give[resource] += amount
    return receive, give


def resource_cap(nation, resource, economies):
    """The most `nation` may move in one deal: DEAL_MAX_RESOURCE_TURNS of output.

    A term is only real if the nation can actually deliver it, and one turn's
    production is the honest measure of that. Without a ceiling the number in the
    box was pure theatre: a player could promise 99,999,999 materials, have the
    offer priced on the promise, and then pay whatever happened to be in the bank
    -- because both halves of paying clamped to the stockpile. The cap and that
    clamp are two sides of one rule, and the clamp is the half that is going.

    Raw output, not output minus upkeep: a nation running a deficit can still
    sell what it digs up this turn. `economies` is what
    queries.calculate_all_economies returns, which every caller already has --
    the screen and the AI both read world.economies, computed once per turn --
    because recomputing it here would be a sweep of every province on the map.

    No economies, no ceiling: a caller without one gets the amount unchanged
    rather than a silent zero.
    """
    if not economies:
        return None
    income = (economies.get(nation) or {}).get("total_inc") or {}
    return max(0, int(float(income.get(resource, 0) or 0) * c.DEAL_MAX_RESOURCE_TURNS))


def capped(amount, nation, resource, economies):
    """`amount`, trimmed to what resource_cap allows. See it for why."""
    ceiling = resource_cap(nation, resource, economies)
    return int(amount) if ceiling is None else max(0, min(int(amount), ceiling))


def vassalizes(deal, nation):
    """Whether any clause hands `nation` over to somebody as a subject."""
    return any(clause.get("type") == VASSALIZE and clause.get("subject") == nation
               for clause in clauses(deal))


def side_worth(deal, nation, map_data, nation_data, whole_side=True):
    """What the nation -- or its whole side -- amounts to. Never zero."""
    side = side_of(deal, nation)
    bloc = deal["sides"][side] if (whole_side and side) else [nation]
    return max(1.0, sum(nation_total_value(member, map_data, nation_data)
                        for member in bloc))


def net_value(deal, nation, map_data, nation_data, whole_side=True):
    """What the deal is worth to `nation`. Positive means it comes out ahead.

    `whole_side=True` counts what the nation's allies gain and lose too, which
    is what a faction leader weighing a bloc treaty cares about; a member being
    asked to ratify wants only its own column, so it passes False.
    """
    book = ledger(deal, nation, map_data, nation_data, whole_side)
    return (book["got_land"] + book["got_other"]
            - book["given_land"] - book["given_other"])


def losses(deal, nation, map_data, nation_data, baseline=None):
    """Every province this deal takes off `nation`, as province dicts.

    The same book ledger keeps, without the prices -- who loses what is decided
    by tile_moves against the deal's baseline, so a term is read for the change
    it makes rather than for the nation its `from` field happens to name.
    """
    if baseline is None:
        baseline = baseline_owners(deal, map_data, nation_data)

    for clause in clauses(deal):
        if clause.get("type") != TILES:
            continue
        for loser, _taker, prov in tile_moves(clause, map_data, nation_data, baseline):
            if loser == nation:
                yield prov


def is_home_ground(nation, prov):
    """Whether this province is `nation`'s own country rather than a holding.

    Its core, or a province it is part-way through coring -- ground it has
    already paid to make permanently its own. A conquest it has not started
    coring is a holding, and a holding can be traded like one.

    Reads the cores list directly rather than through queries.has_core, as the
    rest of this module's valuation does: under the Disable Cores scenario rule
    has_core answers True for every owned tile, which would make every nation's
    entire territory unsellable in a game that has no cores in it at all.
    """
    if nation in prov.get("cores", []):
        return True
    return any(order.get("order_type") == "CORE"
               for order in prov.get("building_queue", []) or [])


def homeland_losses(deal, nation, map_data, nation_data, baseline=None):
    """The provinces this deal takes off `nation` that are its own country.

    What a nation will not sell in peacetime, however good the price. A peace
    treaty is a different matter and does not ask this: losing core land is what
    losing a war means.
    """
    return [prov for prov in losses(deal, nation, map_data, nation_data, baseline)
            if is_home_ground(nation, prov)]


def occupied_fraction(deal, nation, map_data, nation_data, whole_side=True):
    """How much of `nation` -- or its whole side -- the other side is standing on.

    Priced exactly the way demand_fraction prices a loss, because the two get
    compared directly: what may be demanded of a nation is capped by how much of
    it the demander actually holds.

    That comparison used to be made against war_score.between's occupation
    figure, which is a different measurement in a different currency with a
    different denominator -- it resolves the whole coalition on each side and
    prices tiles bare, without the core multiplier. On the save this was found
    in, Germany's grip on twenty-two British provinces came out as 7% (of the
    entire Allied homeland, bare) and was tested against a demand of 36% (of the
    United Kingdom, cored). Demanding two provinces out of the twenty-two it was
    already holding was refused outright.
    """
    side = side_of(deal, nation)
    if side is None:
        return 0.0
    mine = set(deal["sides"][side]) if whole_side else {nation}
    theirs = set(deal["sides"]["b" if side == "a" else "a"])
    prewar = prewar_index(nation_data)

    held = 0.0
    for prov in map_data.values():
        was = original_owner(prov, prewar)
        if was in mine and prov.get("owner") in theirs:
            held += tile_value_between(prov, was, None, nation_data)

    worth = side_worth(deal, nation, map_data, nation_data, whole_side)
    return max(0.0, min(1.0, held / worth))


def demand_fraction(deal, nation, map_data, nation_data, whole_side=True):
    """How much of itself this deal asks `nation` to give up, 0..1.

    Zero when the deal is neutral or favourable. This is the number the AI
    weighs its leverage against.
    """
    net = net_value(deal, nation, map_data, nation_data, whole_side)
    if net >= 0:
        return 0.0

    worth = side_worth(deal, nation, map_data, nation_data, whole_side)
    return max(0.0, min(1.0, -net / worth))


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
            # It said "the map stands", which stopped being true when unnamed
            # occupied land started going home -- and it is the one line a player
            # reads before signing away every conquest they made.
            lines.append("White peace: the fighting stops and the pre-war "
                         "borders are restored.")
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

    # One line per side rather than one line naming everybody. A treaty between
    # two coalitions can bind thirty nations, and this used to join all of them
    # into a single string that the treaty viewer then blitted into a 460-pixel
    # box with no wrapping and no clip.
    for key, label in (("a", "Signed by"), ("b", "Against")):
        members = [n for n in deal["sides"].get(key, []) if n != viewer]
        if len(members) > 1:
            lines.append(f"{label}: {roster(members, tail='and {n} others')}.")

    return lines


def roster(members, limit=c.DEAL_NAMES_SHOWN, tail="+{n} more"):
    """A list of nations as a phrase, with a count once it stops being readable.

    Lives here rather than at either caller because a treaty between blocs is
    read in two places -- the builder's status line and the treaty viewer's
    prose -- and the two disagreeing about how many names is too many is how a
    roster ends up fitting one screen and running off the other. `tail` is the
    only thing that differs: a status line has no room for "and eleven others".
    """
    members = list(members)
    if len(members) <= limit:
        return ", ".join(members)
    return f"{', '.join(members[:limit])} {tail.format(n=len(members) - limit)}"


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

        # "SENDER", "NONE" and "RECEIVER" are the three the old trade screen
        # wrote. Anything else is read as a vassalage term all the same, in the
        # sender's favour: the check it replaced was `!= "NONE"`, so an
        # unrecognised value was refused rather than waved through, and a value
        # this does not understand is the last thing that should quietly become
        # no clause at all.
        puppet_state = params.get("puppet_state") or "NONE"
        if puppet_state == "RECEIVER":
            deal = add_clause(deal, {"type": VASSALIZE, "master": target, "subject": proposer,
                                     "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        elif puppet_state != "NONE":
            deal = add_clause(deal, {"type": VASSALIZE, "master": proposer, "subject": target,
                                     "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        return deal

    return from_legacy_string(params, proposer, target)
