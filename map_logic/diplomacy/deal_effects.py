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

import data.constants as c
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.turn_processing import edit_province_ownership


def _hand_over_the_land_only(map_screen, prov, receiver):
    """Marches everyone else's army off a province that has just changed hands.

    A treaty moves ground. It does not move the men standing on it, and it never
    did -- conquer_province has never so much as read province["units"] -- but
    what happened instead was that they stayed put, owned by whoever they had
    always been owned by, until process_stranded_units swept the map at the end
    of the turn. Between those two moments a province could be bought and come
    with somebody else's garrison sitting on it, which is what a trade looks
    like from the outside whether or not any owner field changed.

    So the sweep happens here, for that tile, at the instant the land moves: the
    seller's armies go home the way an exiled army does, and nothing about who
    owns which unit is touched by a deal at all. Ships are left alone, as they
    are by the end-of-turn pass -- they answer to coastal access, not to who
    owns the shore.
    """
    from map_logic.turn_processing import movement_processor

    for unit in list(prov.get("units", ())):
        owner = unit.get("owner")
        if not owner or owner == receiver or owner in c.UNPLAYABLE_NATIONS:
            continue
        if not movement_processor.is_land_unit(unit):
            continue
        movement_processor.send_unit_home(map_screen, prov, unit)


def _provinces_by_id(map_screen):
    if getattr(map_screen, "id_to_province", None):
        return map_screen.id_to_province
    return {prov["id"]: prov for prov in map_screen.map_data.values()}


def economies_for(map_screen):
    """This turn's economy snapshot, for deal.resource_cap.

    Three sources in order of how much they cost. One already computed and
    hung on the screen wins; then the AI's per-turn cache, because prepare_turn
    has usually already built it and a treaty executes inside that same turn;
    then a fresh sweep, which is affordable here in a way it is not on the
    builder screen -- executing a deal happens once, re-pricing one happens per
    keystroke.

    None when there is nothing to read. resource_cap takes that as "no ceiling"
    rather than a ceiling of zero, so a caller that cannot know what a nation
    produces does not silently cancel every payment in the treaty.
    """
    from data import queries

    supplied = getattr(map_screen, "economies", None)
    if supplied:
        return supplied

    world = getattr(map_screen, "ai_world", None)
    if world is not None:
        return world.economies

    map_data = getattr(map_screen, "map_data", None)
    if not map_data:
        return None
    return queries.calculate_all_economies(map_data, map_screen.nation_data)


def _provinces(count):
    return "province" if count == 1 else "provinces"


def _side_containing(deal, nation):
    """Everyone fighting alongside `nation` in this deal, including itself."""
    sides = deal.get("sides", {})
    for members in (sides.get("a") or [], sides.get("b") or []):
        if nation in members:
            return set(members)
    return {nation}


def prune(deal, map_screen):
    """The deal minus any term the world has since made impossible.

    Returns (deal, dropped) where `dropped` is a list of sentences describing
    what fell away, for the message that reports the settlement.
    """
    from map_logic.diplomacy import reach as reach_mod

    by_id = _provinces_by_id(map_screen)
    nation_data = map_screen.nation_data
    prewar = deal_mod.prewar_index(nation_data)
    economies = economies_for(map_screen)
    # Every treaty in the game funnels through here on its way to executing, so
    # this is where the reach rule actually binds -- on the AI's offers and on
    # scripted ones as much as on anything a player built in the deal screen.
    # It is also the only place that can be right about it: a province within
    # reach when the offer was written can be a province on the far side of a
    # collapsed front by the time it lands, a turn later.
    reachable = reach_mod.index(map_screen.map_data)
    receiver_ids = deal_mod.receiver_ids_by_recipient(deal)

    kept, dropped = [], []
    for clause in deal_mod.clauses(deal):
        kind = clause.get("type")

        if kind == deal_mod.RESOURCES:
            # A promise is capped at one turn's output when it is made, and the
            # offer then travels for a turn -- long enough to lose the provinces
            # that were producing it. Trimmed here rather than in the payment
            # loop so that staleness is handled in the one place that handles
            # staleness, and so the shortfall is reported instead of the treaty
            # quietly delivering less than it says.
            payer, resource = clause.get("from"), clause.get("resource")
            written = int(clause.get("amount", 0))
            payable = deal_mod.capped(written, payer, resource, economies)
            if payable < written:
                dropped.append(f"{payer} could only deliver {payable} of the "
                               f"{written} {resource} promised.")
                clause = dict(clause, amount=payable)
            kept.append(dict(clause))
            continue

        if kind == deal_mod.TILES:
            # Who currently holds a promised province decides almost nothing.
            # The old rule -- the named giver must still own it, or the term is
            # struck -- was wrong in both directions:
            #
            #  * A demand is usually for ground the *demander* is already
            #    standing on. That is what winning a war looks like, and the
            #    treaty is what makes it permanent now that unnamed occupied land
            #    goes home. Struck, it would have been handed straight back.
            #  * Combat resolves in phase 2 and diplomacy in phase 1 of the turn
            #    after, so a round of captures always sits between an offer being
            #    written and it executing, and what usually happens in it is that
            #    a co-belligerent takes the tile. Struck, that ally kept it.
            #
            # What matters is whether the giving side still has title to give:
            # somebody on that side holds it, or it was theirs before the war.
            giver = clause.get("from")
            giving_side = _side_containing(deal, giver)
            receiving_side = _side_containing(deal, clause.get("to"))

            receiver = clause.get("to")
            pending = receiver_ids.get(receiver, ())
            honoured, moved, gone, adrift = [], 0, 0, 0
            for pid in clause.get("ids", []):
                prov = by_id.get(int(pid))
                owner = prov.get("owner") if prov else None

                if prov is not None and not reachable.reachable(receiver, prov, pending=pending):
                    adrift += 1
                    continue

                if owner == giver:
                    honoured.append(pid)
                elif owner in giving_side:
                    honoured.append(pid)
                    moved += 1
                elif owner in receiving_side and deal_mod.original_owner(prov, prewar) in giving_side:
                    # Already ours by force; the treaty makes it ours by right.
                    honoured.append(pid)
                else:
                    gone += 1

            if moved:
                dropped.append(f"{moved} promised {_provinces(moved)} had passed to "
                               f"{giver}'s co-belligerents, and were handed over by them.")
            if gone:
                dropped.append(f"{gone} promised {_provinces(gone)} had already "
                               f"changed hands and could not be given.")
            if adrift:
                dropped.append(f"{adrift} promised {_provinces(adrift)} lay beyond "
                               f"anything {receiver} could reach, and stayed where "
                               f"they were.")
            if honoured or clause.get("plus_originals"):
                kept.append(deal_mod.tiles_clause(giver, clause.get("to"), honoured,
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
    stockpile, in full, into the negative if that is what it takes.

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
            # The land, and only the land. See _hand_over_the_land_only.
            _hand_over_the_land_only(map_screen, prov, prov.get("owner"))

    # --- 2. Payments ---
    # A payer who escrowed when the offer went out has already been charged, so
    # their side is delivered out of the held pool; anyone else pays now, and
    # pays in full.
    #
    # Both of those used to clamp to what the payer happened to hold, and that
    # made every number in a deal a suggestion: a term was *priced* at what it
    # said and *collected* at whatever was in the bank, so anything on the map
    # could be bought with money that did not exist. What bounds a promise now
    # is deal.resource_cap -- one turn of output -- and what a nation cannot
    # cover out of stock it owes.
    #
    # The debt is safe to write because it is bounded on both sides. It can
    # never exceed the ceiling that allowed the term, and process_economy adds
    # next turn's income *before* it floors a stockpile at zero
    # (economy_processor.py), so the same figure that set the ceiling is the one
    # that clears the debt. A nation cannot be driven under by a treaty; it can
    # only be made to spend the year's production on one.
    pools = {payer: dict(held) for payer, held in (escrowed or {}).items()}

    for clause in deal_mod.clauses(deal):
        if clause.get("type") != deal_mod.RESOURCES:
            continue
        resource = clause.get("resource")
        payer_name = clause["from"]
        # As written -- prune has already trimmed it to what the payer can
        # deliver, and capping it a second time here would be a second answer to
        # the same question with nobody told about the difference.
        paid = int(clause.get("amount", 0))
        pool = pools.get(payer_name)

        if pool is not None:
            # Escrow holds the same capped figure, so the pool covers this in
            # the ordinary case; a shortfall means the offer was written before
            # the ceiling existed, and the rest is charged live like anyone else.
            from_pool = min(paid, pool.get(resource, 0))
            pool[resource] = pool.get(resource, 0) - from_pool
            shortfall = paid - from_pool
        else:
            shortfall = paid

        if shortfall:
            payer = nation_data.setdefault(payer_name, {})
            payer[resource] = int(payer.get(resource, 0) or 0) - shortfall

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
            # FACTION_EXIT is a separate-peace term.  The builder used to add
            # it to ordinary trades made by faction members, and malformed
            # offers can remain in saves written before that was fixed.
            if deal.get("kind") != deal_mod.KIND_PEACE:
                continue
            if nation_data.get(clause["nation"], {}).get("faction", ""):
                finalize_faction_leave(nation_data, clause["nation"])

        elif kind == deal_mod.WAR_EXIT:
            remove_enemy(nation_data, clause["nation"], clause["against"])
            remove_enemy(nation_data, clause["against"], clause["nation"])

    # --- 4. The war itself ---
    if deal_mod.ends_war(deal):
        dropped.extend(restore_occupied(map_screen, deal, set(transfers)))
        for ours in deal["sides"]["a"]:
            for theirs in deal["sides"]["b"]:
                _clear_wargoals(nation_data, ours, theirs)
                finalize_neutral(nation_data, ours, theirs)

    return dropped


def restore_occupied(map_screen, deal, ceded):
    """Hands back every province one side holds of the other's and did not win
    in the treaty. Returns notes for the settlement message.

    Peace used to leave the map exactly as the armies had left it, so a white
    peace -- which described itself as "the fighting stops, the map stands", and
    now says the pre-war borders are restored, because they are -- froze every
    conquest permanently and made the tile clauses in a treaty decorative: you
    kept what you held either way. It also made a treaty impossible to read.
    A player who took twenty-two British provinces at the table could not tell
    which of the changes on the map afterwards were the treaty's doing and which
    were the previous turn's fighting, and reasonably assumed the treaty had done
    something strange.

    Only land taken *from the other side of this war* goes home, and only to
    whoever held it when the war began. Conquests from a third party are not this
    treaty's business, and land the treaty names has just been transferred on
    purpose -- `ceded` is that set.

    That rule is deal.baseline_owners now rather than a second copy of itself
    here. It was written in this function and known nowhere else, so valuation,
    the builder screen and the preview map all went on measuring against the
    live map while execution measured against the pre-war one -- the game
    priced, drew and explained a different treaty from the one it carried out.
    """
    baseline = deal_mod.baseline_owners(deal, map_screen.map_data, map_screen.nation_data)

    returned = 0
    for prov in map_screen.map_data.values():
        if prov["id"] in ceded:
            continue
        was = baseline.get(int(prov["id"]))
        if was is None or was == prov.get("owner"):
            continue

        edit_province_ownership.conquer_province(map_screen, prov, was)
        returned += 1

    if returned:
        return [f"{returned} occupied {_provinces(returned)} not named in the treaty "
                f"returned to their pre-war owners."]
    return []


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

def escrow_holdings(deal, nation, economies=None):
    """{resource: amount} this nation has promised away in `deal`.

    Capped at what it produces, so what is escrowed, what is delivered and what
    the other side was told are one figure. See deal.resource_cap.
    """
    holdings = {}
    for clause in deal_mod.clauses(deal):
        if clause.get("type") == deal_mod.RESOURCES and clause.get("from") == nation:
            resource = clause.get("resource")
            amount = deal_mod.capped(int(clause.get("amount", 0)), nation, resource,
                                     economies)
            holdings[resource] = holdings.get(resource, 0) + amount
    return holdings


def hold_escrow(nation_data, deal, nation, economies=None):
    """Takes the promised resources out of circulation. Returns what was held.

    Takes the whole promise, into the negative if the stockpile does not cover
    it. It used to clamp, which sounds prudent and was the mechanism of the
    exploit: escrowing the stockpile against a promise of any size meant a
    nation could offer a number it had never had, be believed, and pay what was
    in the till. Promising is spending now, and what a nation may promise is
    bounded instead -- one turn's output, which is also the income that arrives
    to clear the debt.
    """
    held = {}
    stock = nation_data.setdefault(nation, {})
    for resource, amount in escrow_holdings(deal, nation, economies).items():
        stock[resource] = int(stock.get(resource, 0) or 0) - int(amount)
        held[resource] = int(amount)
    return held


def release_escrow(nation_data, held, nation):
    """Gives back what hold_escrow took. Pass the dict it returned, not the deal --
    the deal says what was promised, this says what was actually taken."""
    stock = nation_data.setdefault(nation, {})
    for resource, amount in (held or {}).items():
        if int(amount) > 0:
            stock[resource] = int(stock.get(resource, 0) or 0) + int(amount)
