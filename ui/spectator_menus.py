from collections import namedtuple

import data.constants as c
from data import queries

def force_war_menu(map_screen): 
    open_spectator_action_menu(map_screen, "WAR")

def force_peace_menu(map_screen): 
    open_spectator_action_menu(map_screen, "PEACE")


def _selected_country_for_removal(map_screen):
    if not queries.can_use_spectator_country_actions(map_screen):
        return None
    country = (map_screen.selected_province or {}).get("owner")
    return country if queries.is_playable(country, map_screen.nation_data) else None


def _refresh_country_removal(map_screen):
    map_screen.clear_map_unit_selection()
    map_screen.refresh_map_layers(*map_screen.ALL_MAP_LAYERS)
    map_screen.update_country_centers()
    from screens.menu_screens.map import update_button_states
    update_button_states(map_screen)


def spec_annex_country(map_screen):
    source = _selected_country_for_removal(map_screen)
    if source is None:
        return
    source_name = queries.get_country_display_name(source, map_screen.nation_data)
    candidates = sorted(country for country in queries.get_living_nations(map_screen.map_data)
                        if country != source and queries.is_playable(country, map_screen.nation_data))

    def selected(target):
        if (_selected_country_for_removal(map_screen) != source
                or target not in queries.get_living_nations(map_screen.map_data)):
            return
        from map_logic.diplomacy.puppet_actions import finalize_spectator_country_removal
        target_name = queries.get_country_display_name(target, map_screen.nation_data)
        if finalize_spectator_country_removal(map_screen, target, source):
            _refresh_country_removal(map_screen)
            map_screen.show_feedback(f"{source_name} annexed {target_name}.")

    queries.open_listbox_selector(
        map_screen, f"Annex for {source_name}", "Select a country to annex immediately:",
        queries.country_picker_items(candidates, map_screen.nation_data), selected)


def spec_delete_country(map_screen):
    country = _selected_country_for_removal(map_screen)
    if country is None:
        return
    name = queries.get_country_display_name(country, map_screen.nation_data)

    def confirmed(accepted):
        if not accepted or _selected_country_for_removal(map_screen) != country:
            return
        from map_logic.diplomacy.puppet_actions import finalize_spectator_country_removal
        if finalize_spectator_country_removal(map_screen, country):
            _refresh_country_removal(map_screen)
            map_screen.show_feedback(f"Deleted {name}.")

    from ui import confirm_dialog
    confirm_dialog.ask_yes_no(
        "Delete Country", f"Delete {name}? Its territory will become unclaimed. "
        "All its cores and units will be removed. History will remain unchanged.",
        on_result=confirmed, yes_label="Delete", no_label="Cancel")


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
    map_screen.show_feedback(f"{verb} Faction: " + queries.get_country_display_name(
        source_nation, map_screen.nation_data))
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

    if action_type == "INVITE_FACTION":
        leadership_error = queries.faction_request_leadership_error(
            source_nation, "", "FACTION_INVITE", map_screen.nation_data)
        if leadership_error:
            map_screen.show_feedback(leadership_error)
            return

    action = SPECTATOR_ACTIONS.get(action_type, _UNKNOWN_ACTION)
    living_nations = queries.get_living_nations(map_screen.map_data)
    items = action.candidates(map_screen, source_nation, living_nations)

    def cb(target_nation):
        if action_type == "INVITE_FACTION":
            leadership_error = queries.faction_request_leadership_error(
                source_nation, target_nation, "FACTION_INVITE", map_screen.nation_data)
            if leadership_error:
                map_screen.show_feedback(leadership_error)
                return
        if action.apply:
            from map_logic.diplomacy import diplomacy_logic
            action.apply(diplomacy_logic, map_screen, source_nation, target_nation)
            map_screen.show_feedback(action.feedback.format(
                src=queries.get_country_display_name(source_nation, map_screen.nation_data),
                tgt=queries.get_country_display_name(target_nation, map_screen.nation_data)))
        map_screen.refresh_diplomacy_maps()

    queries.open_listbox_selector(
        map_screen,
        f"{action_type} for " + queries.get_country_display_name(source_nation, map_screen.nation_data),
        f"Select Target for {action_type}:",
        queries.country_picker_items(items, map_screen.nation_data), cb)
