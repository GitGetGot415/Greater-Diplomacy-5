"""Unilateral guarantees of independence.

The promise belongs to the guarantor: ``nation_data[guarantor]["guarantees"]``
is the list of countries it will defend. Keeping only that one authoritative
copy avoids the two directions drifting apart; the protected country's
"guaranteed by" list is derived when it is displayed or when war starts.
"""

from data import queries


ACTION = "GUARANTEE"
REVOKE_ACTION = "REVOKE_GUARANTEE"


def is_eligible(guarantor, target, nation_data):
    """Whether ``guarantor`` may newly guarantee ``target``, with a reason."""
    if guarantor == target:
        return False, "A country cannot guarantee itself."
    if guarantor not in nation_data or target not in nation_data:
        return False, "That country no longer exists."

    target_data = nation_data.get(target, {})
    if target_data.get("faction", ""):
        return False, "A country in a faction cannot be guaranteed."
    if queries.get_enemies(target, nation_data):
        return False, "A country at war cannot be guaranteed."
    return True, ""


def guaranteed_targets(guarantor, nation_data):
    """The countries currently promised protection by ``guarantor``."""
    guarantees = nation_data.get(guarantor, {}).get("guarantees", [])
    if not isinstance(guarantees, list):
        return []
    return list(dict.fromkeys(target for target in guarantees
                              if target in nation_data and target != guarantor))


def guarantors_of(target, nation_data):
    """Countries with an active promise to defend ``target``."""
    return [nation for nation in nation_data
            if target in guaranteed_targets(nation, nation_data)]


def grant(guarantor, target, nation_data):
    """Create a guarantee. Returns ``(changed, reason)``."""
    eligible, reason = is_eligible(guarantor, target, nation_data)
    if not eligible:
        return False, reason

    promises = nation_data[guarantor].setdefault("guarantees", [])
    if not isinstance(promises, list):
        promises = nation_data[guarantor]["guarantees"] = []
    if target in promises:
        return False, "You already guarantee that country."
    promises.append(target)
    return True, ""


def revoke(guarantor, target, nation_data):
    """Remove one promise, returning whether anything changed."""
    promises = nation_data.get(guarantor, {}).get("guarantees", [])
    if not isinstance(promises, list) or target not in promises:
        return False
    promises.remove(target)
    if not promises:
        nation_data[guarantor].pop("guarantees", None)
    return True


def reconcile(nation_data):
    """Drop guarantees whose target is now at war or in a faction.

    ``finalize_war`` calls defensive_guarantors before this runs, so a protected
    defender is still called in before the new war invalidates its guarantee.
    """
    removed = []
    for guarantor, data in list(nation_data.items()):
        if not isinstance(data, dict):
            continue
        promises = data.get("guarantees", [])
        if not isinstance(promises, list):
            data["guarantees"] = []
            continue
        kept = []
        for target in promises:
            eligible, _reason = is_eligible(guarantor, target, nation_data)
            if eligible:
                kept.append(target)
            else:
                removed.append((guarantor, target))
        if kept:
            data["guarantees"] = kept
        else:
            data.pop("guarantees", None)
    return removed


def defensive_guarantors(defender, attacker, nation_data):
    """Countries that must join ``defender`` against ``attacker``."""
    return [guarantor for guarantor in guarantors_of(defender, nation_data)
            if guarantor != attacker
            and not queries.are_at_war(guarantor, attacker, nation_data)]
