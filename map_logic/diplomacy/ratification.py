"""The veto a faction member gets over terms its leader signed for it.

A leader negotiates for the whole bloc and may put a member's own provinces on
the table. Binding a nation to that without a word would be the worst version of
faction peace, so every member with something to lose in the deal gets one
chance to refuse -- and refusing means leaving the faction and fighting on
alone, which is a real price rather than a free veto.

AI members answer on the spot. Only a human being asked needs a round trip, so
in an ordinary single-player game a bloc treaty still settles the turn it is
accepted, and the extra turn appears exactly when somebody has to read
something. That is why this does not use pending_diplomacy: that dict holds one
entry per target, and a leader asking four members at once would clobber four
unrelated offers. Its own channel cannot collide with anything.

    nation_data[member]["pending_ratification"]  -- the ask, and the answer
    nation_data[signatory]["pending_treaty"]     -- the deal, waiting on replies
"""

import data.constants as c
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import deal_effects
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.diplomacy.diplomacy_messages import send_message

RATIFY = "RATIFY"
REFUSE = "REFUSE"


def _members_with_something_to_lose(deal, signatory):
    """Everyone on the signatory's side the deal takes something from."""
    ours = set(deal["sides"][deal_mod.side_of(deal, signatory) or "a"])
    return [n for n in deal_mod.affected_nations(deal)
            if n in ours and n != signatory]


def _ai_ratifies(map_screen, member, deal):
    from map_logic.ai import ai_opinion, ai_world

    world = map_screen.ai_world or ai_world.for_screen(map_screen)
    return ai_opinion.ratifies(world, member, deal, map_screen.map_data,
                               map_screen.scenario_settings)


def open_round(map_screen, signatory, opponent, deal, escrow=None):
    """Puts a bloc treaty to the members it binds.

    Returns True when the treaty settled immediately -- nobody had to be asked,
    or everyone who did was an AI. Returns False when a human member still owes
    an answer, in which case the deal waits in `pending_treaty` and
    process_ratifications finishes it.
    """
    nation_data = map_screen.nation_data
    bound = _members_with_something_to_lose(deal, signatory)

    refused, awaiting = [], []
    for member in bound:
        if member in map_screen.active_players:
            nation_data.setdefault(member, {})["pending_ratification"] = {
                "signatory": signatory, "opponent": opponent, "deal": deal, "turns": 0}
            send_message(map_screen, signatory, member,
                         _ask_text(signatory, opponent), "DIPLOMACY",
                         extra={"action": "RATIFY_TREATY", "parameters": deal})
            awaiting.append(member)
        elif not _ai_ratifies(map_screen, member, deal):
            refused.append(member)

    if awaiting:
        nation_data.setdefault(signatory, {})["pending_treaty"] = {
            "deal": deal, "opponent": opponent, "escrow": escrow,
            "awaiting": awaiting, "refused": refused, "turns": 0}
        return False

    settle(map_screen, signatory, deal, opponent, refused, escrow)
    return True


def _ask_text(signatory, opponent):
    return (f"{signatory} has agreed terms with {opponent} on our bloc's behalf. "
            f"These terms bind you. Refusing them means leaving the faction and "
            f"fighting on alone.")


def answer(nation_data, member, verdict):
    """Records a human member's reply. Returns what to tell them, or ""."""
    entry = nation_data.get(member, {}).get("pending_ratification")
    if not isinstance(entry, dict):
        return ""
    entry["verdict"] = verdict
    return ("Terms ratified." if verdict == RATIFY
            else "Terms refused -- you will leave the faction and fight on alone.")


def pending_for(nation_data, member):
    """The treaty `member` has been asked to ratify, as a dict ({} if none)."""
    entry = nation_data.get(member, {}).get("pending_ratification")
    return entry if isinstance(entry, dict) else {}


def process_ratifications(map_screen):
    """Collects replies and settles any treaty that has all of them.

    A human member that says nothing is taken to consent after
    RATIFICATION_TURNS: a leader's authority is the whole point of bloc peace,
    and silence should not be able to hold a settlement open forever.
    """
    nation_data = map_screen.nation_data

    for signatory, data in list(nation_data.items()):
        if not isinstance(data, dict):
            continue
        treaty = data.get("pending_treaty")
        if not isinstance(treaty, dict):
            continue

        treaty["turns"] = treaty.get("turns", 0) + 1
        still_waiting = []

        for member in list(treaty.get("awaiting", [])):
            entry = pending_for(nation_data, member)
            verdict = entry.get("verdict")

            if verdict is None and treaty["turns"] <= c.RATIFICATION_TURNS:
                still_waiting.append(member)
                continue

            if verdict == REFUSE:
                treaty.setdefault("refused", []).append(member)
            nation_data.get(member, {}).pop("pending_ratification", None)

        treaty["awaiting"] = still_waiting
        if still_waiting:
            continue

        del data["pending_treaty"]
        settle(map_screen, signatory, treaty["deal"], treaty.get("opponent", ""),
               treaty.get("refused", []), treaty.get("escrow"))


def settle(map_screen, signatory, deal, opponent, refused, escrow=None):
    """Executes a bloc treaty, minus whoever would not sign it.

    A refusing member's terms come out of the deal and it comes off the roster,
    so finalize_neutral never runs for it: it keeps its land, loses its faction,
    and is still at war with the other side in the morning.
    """
    from map_logic.diplomacy.faction_actions import finalize_faction_leave

    nation_data = map_screen.nation_data

    for member in refused or []:
        deal = deal_mod.without_nation(deal, member)
        if nation_data.get(member, {}).get("faction", ""):
            finalize_faction_leave(nation_data, member)
        log_global_event(nation_data,
                         f"{member} refused the terms {signatory} agreed with {opponent}, "
                         f"broke with the faction, and fights on.")
        send_message(map_screen, member, signatory,
                     "We will not be signed away. We leave your faction and fight on.",
                     "DIPLOMACY")

    dropped = deal_effects.execute(map_screen, deal,
                                   escrowed={signatory: escrow} if escrow else None)
    deal_effects.announce(map_screen, deal, dropped)
    return deal
