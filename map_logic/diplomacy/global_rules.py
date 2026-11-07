"""Scenario rules that forbid one diplomatic outcome between two countries for a whole game.

The Scripted Events editor writes these rules to WorldState.global_rules. Each rule is

    {"country": "<country ID>", "rule": "<one of RULE_TYPES>", "target": "<country ID>"}

and reads as "<country> may never <rule> <target>", for example
"German Reich may never Make Peace With Soviet Union".

Rules apply only while the scenario's scripted events are enabled. They bind players, the
rule-based AI, the LLM, and scripted events alike, because two shared gates read them:

  * action_definitions.availability refuses to draft or send a forbidden action.
  * treaty_effects.apply_treaty_effect refuses to settle a forbidden agreement. An offer
    waits a turn for its answer, and factions and wars can change while it waits.

A rule judges every country an action binds, not only the two that exchange it. A faction
leader's peace binds its members. A faction join brings in the joiner's subjects. A call
to arms puts the country that answers it at war with each of the caller's enemies.
"""

from data import queries
import data.constants as c
from data.state_access import world_for
from map_logic.diplomacy import peace_scope, war_calls
from map_logic.diplomacy.puppet_actions import apply_to_puppets_recursively

DECLARE_WAR = "Declare War On"
MAKE_PEACE = "Make Peace With"
SHARE_FACTION = "Be In Faction With"
GUARANTEE = "Guarantee Independence Of"
TRADE = "Trade With"
GRANT_ACCESS = "Grant Military Access To"

RULE_TYPES = [DECLARE_WAR, MAKE_PEACE, SHARE_FACTION, GUARANTEE, TRADE, GRANT_ACCESS]
# The two countries in these rules are equal partners, so each rule also covers the reverse order.
MUTUAL_RULES = {MAKE_PEACE, SHARE_FACTION, TRADE}


def _pair(sender, target, _nation_data):
    return [sender], [target]


def _granter_pair(sender, target, _nation_data):
    # The target of a military access request grants passage to its sender.
    return [target], [sender]


def _join_wars_sides(sender, target, nation_data):
    # The sender joins the target's wars.
    return [sender], war_calls.unshared_wars(target, sender, nation_data)


def _call_to_arms_sides(sender, target, nation_data):
    # The target answers by joining the sender's wars.
    return [target], war_calls.unshared_wars(sender, target, nation_data)


def _with_subjects(nation, nation_data):
    """A country and every subject that follows it into a faction."""
    family = [nation]
    apply_to_puppets_recursively(nation, nation_data, family.append)
    return family


def _faction_of(host, nation_data):
    faction = nation_data.get(host, {}).get("faction", "")
    return queries.get_faction_members(faction, nation_data) if faction else [host]


def _invite_sides(sender, target, nation_data):
    return _with_subjects(target, nation_data), _faction_of(sender, nation_data)


def _join_request_sides(sender, target, nation_data):
    return _with_subjects(sender, nation_data), _faction_of(target, nation_data)


def _create_faction_sides(sender, target, nation_data):
    return _with_subjects(sender, nation_data), _with_subjects(target, nation_data)


# Each action lists the rule types it can break and the two sides each rule compares.
# A rule's country must be on the first side and its target on the second, unless the rule is mutual.
# Joining a faction also ends every war between the joiner and the faction's members.
_ACTION_CHECKS = {
    "WAR_DECLARATION": ((DECLARE_WAR, _pair),),
    "JOIN_WARS": ((DECLARE_WAR, _join_wars_sides),),
    "CALL_TO_ARMS": ((DECLARE_WAR, _call_to_arms_sides),),
    "CEASEFIRE": ((MAKE_PEACE, peace_scope.deal_sides),),
    "PEACE_TREATY": ((MAKE_PEACE, peace_scope.deal_sides),),
    "FACTION_INVITE": ((SHARE_FACTION, _invite_sides), (MAKE_PEACE, _invite_sides)),
    "JOIN_FACTION_REQ": ((SHARE_FACTION, _join_request_sides), (MAKE_PEACE, _join_request_sides)),
    "CREATE_FACTION": ((SHARE_FACTION, _create_faction_sides), (MAKE_PEACE, _create_faction_sides)),
    "GUARANTEE": ((GUARANTEE, _pair),),
    "TRADE": ((TRADE, _pair),),
    "REQ_MILITARY_ACCESS": ((GRANT_ACCESS, _granter_pair),),
}


def active_rules(context):
    """The rules in force for this game. Disabling scripted events disables them too."""
    world = world_for(context)
    if not queries.get_scenario_flag("use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS,
                                     world.scenario_settings):
        return []
    return world.global_rules


def names(rule, country, target):
    """Whether the rule names these two countries in this order, or in either order when mutual."""
    pair = (rule["country"], rule["target"])
    return pair == (country, target) or (rule["rule"] in MUTUAL_RULES and pair == (target, country))


def find_rule(rules, rule_type, country, target):
    """The existing rule of this type that names these two countries, or None."""
    return next((rule for rule in rules
                 if rule["rule"] == rule_type and names(rule, country, target)), None)


def describe(rule, nation_data):
    country = queries.get_country_display_name(rule["country"], nation_data)
    target = queries.get_country_display_name(rule["target"], nation_data)
    return f"{country} may never {rule['rule'].lower()} {target}"


def _breaks(rule, side_a, side_b, nation_data):
    # A peace rule only matters while its two countries are at war.
    return any(names(rule, a, b) and (rule["rule"] != MAKE_PEACE or queries.are_at_war(a, b, nation_data))
               for a in side_a for b in side_b)


def forbidden_reason(context, sender, target, action):
    """Why a global rule forbids this action from sender to target, or "" when none does."""
    rules = active_rules(context)
    checks = _ACTION_CHECKS.get(action)
    if not rules or not checks:
        return ""
    nation_data = world_for(context).nation_data
    for rule_type, sides in checks:
        side_a, side_b = sides(sender, target, nation_data)
        for rule in rules:
            if rule["rule"] == rule_type and _breaks(rule, side_a, side_b, nation_data):
                return f"a scenario rule says {describe(rule, nation_data)}"
    return ""
