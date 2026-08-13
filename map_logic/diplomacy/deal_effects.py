"""Carrying out an accepted deal, one clause at a time.

Every clause is executed by a primitive that already existed and is already
used by some other path -- conquer_province, assign_puppet, finalize_neutral,
finalize_faction_leave. Nothing here invents a new way to change the world; it
only decides in what order, and what to do about the terms that have gone stale
between the offer being sent and the answer coming back.

That staleness is real and used to be unhandled. A treaty travels for at least
a turn, and a province promised in it can be captured by a third party, or by
the other signatory, before the ink is dry. execute_peace_treaty simply skipped
any province whose owner had changed, silently; now the deal is re-validated and
the dropped terms are reported back so the players can be told.
"""

from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.turn_processing import edit_province_ownership


def _provinces_by_id(map_screen):
    if getattr(map_screen, "id_to_province", None):
        return map_screen.id_to_province
    return {prov["id"]: prov for prov in map_screen.map_data.values()}


def prune(deal, map_screen):
    """The deal minus any term the world has since made impossible.

    Returns (deal, dropped) where `dropped` is a list of sentences describing
    what fell away, for the message that reports the settlement.
    """
    by_id = _provinces_by_id(map_screen)
    nation_data = map_screen.nation_data

    kept, dropped = [], []
    for clause in deal_mod.clauses(deal):
        kind = clause.get("type")

        if kind == deal_mod.TILES:
            giver = clause.get("from")
            still_theirs = [pid for pid in clause.get("ids", [])
                            if by_id.get(int(pid), {}).get("owner") == giver]
            lost = len(clause.get("ids", [])) - len(still_theirs)
            if lost:
                dropped.append(f"{lost} promised {'province' if lost == 1 else 'provinces'} "
                               f"had already changed hands.")
            if still_theirs or clause.get("plus_originals"):
                kept.append(deal_mod.tiles_clause(giver, clause.get("to"), still_theirs,
                                                  plus_originals=clause.get("plus_originals", False)))
            continue

        if kind == deal_mod.VASSALIZE:
            subject = clause.get("subject")
            if nation_data.get(subject, {}).get("master"):
                dropped.append(f"{subject} is already a puppet of another power.")
                continue

        kept.append(dict(clause))

    return deal_mod.with_clauses(deal, kept), dropped


def execute(map_screen, deal, escrowed=None):
    """Applies an accepted deal. Returns the list of terms that had to be dropped.

    `escrowed` is {nation: {resource: amount}} already taken out of a payer's
    hands when the offer was sent -- those payments are settled from the held
    pool rather than charged again. Everyone else pays out of their live
    stockpile, clamped to what is in it.

    Territory and payments settle before the war ends, because finalize_neutral
    writes the truce and the post-war relations penalty and reads as the closing
    act of the treaty -- which is the order execute_peace_treaty used, and the
    order the message the players receive describes.
    """
    from map_logic.diplomacy.faction_actions import finalize_faction_leave
    from map_logic.diplomacy.puppet_actions import assign_puppet
    from map_logic.diplomacy.war_actions import finalize_neutral, remove_enemy

    if not deal_mod.is_deal(deal):
        return []

    deal, dropped = prune(deal, map_screen)
    nation_data = map_screen.nation_data
    by_id = _provinces_by_id(map_screen)

    # --- 1. Territory ---
    transfers = deal_mod.tile_transfers(deal, map_screen.map_data, nation_data)
    for prov_id, receiver in transfers.items():
        prov = by_id.get(int(prov_id))
        if prov is not None and prov.get("owner") != receiver:
            edit_province_ownership.conquer_province(map_screen, prov, receiver)

    # --- 2. Payments ---
    # A payer who escrowed when the offer went out has already been charged, so
    # their side is delivered out of the held pool; anyone else pays now,
    # clamped to what they actually have. A nation can promise more than it can
    # afford and may have spent the difference while the offer was in transit;
    # taking it into the negative would be worse than taking less.
    pools = {payer: dict(held) for payer, held in (escrowed or {}).items()}

    for clause in deal_mod.clauses(deal):
        if clause.get("type") != deal_mod.RESOURCES:
            continue
        resource = clause.get("resource")
        payer_name, wanted = clause["from"], int(clause.get("amount", 0))
        pool = pools.get(payer_name)

        if pool is not None:
            paid = min(wanted, pool.get(resource, 0))
            pool[resource] = pool.get(resource, 0) - paid
        else:
            payer = nation_data.setdefault(payer_name, {})
            paid = min(wanted, int(payer.get(resource, 0) or 0))
            payer[resource] = int(payer.get(resource, 0) or 0) - paid

        receiver = nation_data.setdefault(clause["to"], {})
        receiver[resource] = int(receiver.get(resource, 0) or 0) + paid

    # Escrow held for terms that were pruned away has no home; give it back.
    for payer_name, leftover in pools.items():
        release_escrow(nation_data, leftover, payer_name)

    # --- 3. Everything else the clauses say ---
    for clause in deal_mod.clauses(deal):
        kind = clause.get("type")

        if kind == deal_mod.VASSALIZE:
            assign_puppet(map_screen.map_data, nation_data,
                          clause["master"], clause["subject"])

        elif kind == deal_mod.DEMILITARIZE:
            restrictions = nation_data.setdefault(clause["nation"], {}).setdefault("restrictions", {})
            restrictions["demilitarized"] = max(int(restrictions.get("demilitarized", 0)),
                                                int(clause.get("turns", 0)))

        elif kind == deal_mod.MILITARY_ACCESS:
            granted = nation_data.setdefault(clause["grantor"], {}).setdefault("military_access", [])
            if clause["grantee"] not in granted:
                granted.append(clause["grantee"])

        elif kind == deal_mod.FACTION_EXIT:
            if nation_data.get(clause["nation"], {}).get("faction", ""):
                finalize_faction_leave(nation_data, clause["nation"])

        elif kind == deal_mod.WAR_EXIT:
            remove_enemy(nation_data, clause["nation"], clause["against"])
            remove_enemy(nation_data, clause["against"], clause["nation"])

    # --- 4. The war itself ---
    if deal_mod.ends_war(deal):
        for ours in deal["sides"]["a"]:
            for theirs in deal["sides"]["b"]:
                _clear_wargoals(nation_data, ours, theirs)
                finalize_neutral(nation_data, ours, theirs)

    return dropped


def _clear_wargoals(nation_data, a, b):
    for side, other in ((a, b), (b, a)):
        wargoals = nation_data.get(side, {}).get("wargoals", {})
        wargoals.pop(other, None)


def announce(map_screen, deal, dropped=()):
    """Files a settlement in the global log, so the world hears about it.

    Wars only. An ordinary trade is between the two of them and already produces
    a "diplomatic agreement reached" line in diplomacy_processor; announcing
    every exchange of fuel as world news would bury the wars that end.
    """
    if not deal_mod.ends_war(deal):
        return

    sides = deal.get("sides", {})
    a = ", ".join(sides.get("a", [])) or "?"
    b = ", ".join(sides.get("b", [])) or "?"

    if deal_mod.is_white_peace(deal):
        log_global_event(map_screen.nation_data, f"PEACE: {a} and {b} have agreed a white peace.")
    else:
        log_global_event(map_screen.nation_data, f"PEACE: {a} and {b} have signed a settlement.")

    for note in dropped:
        log_global_event(map_screen.nation_data, f"Treaty note: {note}")


# ==========================================
# ESCROW
# ==========================================
# What a proposer promises is taken out of their hands when the offer is *sent*
# and given back if it is refused or lapses. This used to live in the trade
# screen, which meant it applied to the player and to nobody else: an AI's offer
# cost it nothing, so an accepted AI trade created materials out of thin air,
# and cancel_trade_escrow then *refunded* the AI for a rejected offer it had
# never paid for. One place, both sides, no minting.

def escrow_holdings(deal, nation):
    """{resource: amount} this nation has promised away in `deal`."""
    holdings = {}
    for clause in deal_mod.clauses(deal):
        if clause.get("type") == deal_mod.RESOURCES and clause.get("from") == nation:
            resource = clause.get("resource")
            holdings[resource] = holdings.get(resource, 0) + int(clause.get("amount", 0))
    return holdings


def hold_escrow(nation_data, deal, nation):
    """Takes the promised resources out of circulation. Returns what was held.

    Clamps to what is actually there, so a promise larger than the stockpile
    escrows the stockpile rather than pushing it negative.
    """
    held = {}
    stock = nation_data.setdefault(nation, {})
    for resource, amount in escrow_holdings(deal, nation).items():
        taken = min(amount, int(stock.get(resource, 0) or 0))
        stock[resource] = int(stock.get(resource, 0) or 0) - taken
        held[resource] = taken
    return held


def release_escrow(nation_data, held, nation):
    """Gives back what hold_escrow took. Pass the dict it returned, not the deal --
    the deal says what was promised, this says what was actually taken."""
    stock = nation_data.setdefault(nation, {})
    for resource, amount in (held or {}).items():
        if int(amount) > 0:
            stock[resource] = int(stock.get(resource, 0) or 0) + int(amount)
