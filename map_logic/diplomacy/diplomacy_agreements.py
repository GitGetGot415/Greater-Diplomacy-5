"""Facade module to maintain backwards compatibility with existing imports across the project.

The diplomatic state-mutation functions used to all live here in one file
mixing war, puppet, and faction concerns. They're now split by concern into
war_actions.py, puppet_actions.py, and faction_actions.py (which cross-import
each other where the concerns interact -- e.g. finalize_war pulling puppets
in, or a faction join settling puppet wars); this module re-exports all of
them under the name every existing caller and diplomacy_logic.py already uses.
"""

from map_logic.diplomacy.war_actions import (
    sever_military_access,
    add_enemy,
    remove_enemy,
    link_war,
    clear_war_call_cooldowns,
    finalize_war,
    finalize_neutral,
    execute_peace_treaty,
)

from map_logic.diplomacy.puppet_actions import (
    break_puppet_link,
    apply_to_puppets_recursively,
    pull_master_into_war,
    assign_puppet,
    pull_puppets_into_war,
    pull_puppets_into_peace,
    pull_puppets_into_faction,
    pull_puppets_out_of_faction,
    finalize_annexation,
    finalize_release,
    finalize_take_puppets,
    finalize_create_integrated_puppet,
)

from map_logic.diplomacy.faction_actions import (
    settle_with_faction,
    leave_faction,
    resent_departure,
    finalize_create_faction,
    finalize_disband_faction,
    finalize_faction_join,
    finalize_faction_leave,
    join_faction_wars,
    finalize_faction_kick,
)
