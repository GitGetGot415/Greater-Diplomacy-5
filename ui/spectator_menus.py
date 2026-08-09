from collections import namedtuple

import data.constants as c
from data import queries

def force_war_menu(map_screen): 
    open_spectator_action_menu(map_screen, "WAR")

def force_peace_menu(map_screen): 
    open_spectator_action_menu(map_screen, "PEACE")

def _spec_faction_action(map_screen, finalizer, verb, wants_map_data=False):
    """Applies a one-shot faction change to the selected province's owner.

    Create / leave / disband were three copies of the same six lines, differing
    only in which diplomacy_logic function they called, whether it wanted
    map_data, and the past-tense verb in the feedback line.
    """
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    from map_logic.diplomacy import diplomacy_logic
    fn = getattr(diplomacy_logic, finalizer)
    if wants_map_data:
        fn(map_screen.map_data, map_screen.nation_data, source_nation)
    else:
        fn(map_screen.nation_data, source_nation)
    map_screen.show_feedback(f"{verb} Faction: {source_nation}")
    map_screen.refresh_diplomacy_maps()

def spec_create_faction(map_screen):
    _spec_faction_action(map_screen, "finalize_create_faction", "Created", wants_map_data=True)

def spec_leave_faction(map_screen):
    _spec_faction_action(map_screen, "finalize_faction_leave", "Left")

def spec_disband_faction(map_screen):
    _spec_faction_action(map_screen, "finalize_disband_faction", "Disbanded")

def spec_join_faction(map_screen):
    open_spectator_action_menu(map_screen, "JOIN_FACTION")

def spec_invite_faction(map_screen):
    open_spectator_action_menu(map_screen, "INVITE_FACTION")

#: One row per spectator force-action. `candidates` picks who may be targeted,
#: `apply` performs it, `feedback` is the confirmation line. Both used to be
#: written as separate if/elif ladders over the same action_type, which is how
#: the two got to disagree about what "playable" meant.
SpectatorAction = namedtuple("SpectatorAction", "candidates apply feedback")


def _enemies_of(map_screen, nation):
    return map_screen.nation_data[nation].get("at_war_with", [])


SPECTATOR_ACTIONS = {
    "WAR": SpectatorAction(
        lambda ms, src, living: sorted(
            n for n, d in ms.nation_data.items()
            if d.get("is_playable") and n != src and n in living
            and n not in _enemies_of(ms, src)),
        lambda dl, ms, src, tgt: dl.finalize_war(ms.map_data, ms.nation_data, src, tgt),
        "Forced War: {src} vs {tgt}"),
    "PEACE": SpectatorAction(
        lambda ms, src, living: sorted(n for n in _enemies_of(ms, src) if n in living),
        lambda dl, ms, src, tgt: dl.finalize_neutral(ms.nation_data, src, tgt),
        "Forced Peace: {src} & {tgt}"),
    "JOIN_FACTION": SpectatorAction(
        lambda ms, src, living: sorted(
            n for n, d in ms.nation_data.items()
            if d.get("is_faction_leader") and n != src),
        lambda dl, ms, src, tgt: dl.finalize_faction_join(ms.map_data, ms.nation_data, tgt, src),
        "Forced Join: {src} joined {tgt}"),
    "INVITE_FACTION": SpectatorAction(
        lambda ms, src, living: sorted(
            n for n, d in ms.nation_data.items()
            if d.get("is_playable") and not d.get("faction") and n != src),
        lambda dl, ms, src, tgt: dl.finalize_faction_join(ms.map_data, ms.nation_data, src, tgt),
        "Forced Invite: {tgt} joined {src}"),
}

#: An unrecognised action still opens the picker but does nothing on confirm,
#: which is what the old ladders' `else` branch amounted to.
_UNKNOWN_ACTION = SpectatorAction(
    lambda ms, src, living: sorted(
        n for n, d in ms.nation_data.items() if d.get("is_playable") and n != src),
    None, None)


def open_spectator_action_menu(map_screen, action_type):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    if source_nation in c.UNPLAYABLE_NATIONS: return

    action = SPECTATOR_ACTIONS.get(action_type, _UNKNOWN_ACTION)
    living_nations = queries.get_living_nations(map_screen.map_data)
    items = action.candidates(map_screen, source_nation, living_nations)

    def cb(target_nation):
        if action.apply:
            from map_logic.diplomacy import diplomacy_logic
            action.apply(diplomacy_logic, map_screen, source_nation, target_nation)
            map_screen.show_feedback(action.feedback.format(src=source_nation, tgt=target_nation))
        map_screen.refresh_diplomacy_maps()

    queries.open_listbox_selector(map_screen, f"{action_type} for {source_nation}", f"Select Target for {action_type}:", items, cb)