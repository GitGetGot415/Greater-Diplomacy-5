"""Military attachés: temporary, host-approved intelligence sharing."""

from data import queries


ACTION = "SEND_MILITARY_ATTACHE"
WITHDRAW_ACTION = "WITHDRAW_MILITARY_ATTACHE"
REVOKE_ACTION = "REVOKE_MILITARY_ATTACHE"
PENDING_REVOKE_KEY = "pending_military_attache_revocations"


def is_eligible(sender, host, nation_data):
    """Whether ``sender`` may send an attaché to the at-war ``host``."""
    if sender == host:
        return False, "A country cannot send a military attaché to itself."
    if sender not in nation_data or host not in nation_data:
        return False, "That country no longer exists."
    if not queries.get_enemies(host, nation_data):
        return False, "Military attachés can only be sent to countries at war."
    if queries.are_at_war(sender, host, nation_data):
        return False, "You cannot send a military attaché to an enemy."
    return True, ""


def hosts_for(sender, nation_data):
    """Active attaché hosts for ``sender``; malformed old state is ignored."""
    hosts = nation_data.get(sender, {}).get("military_attaches", [])
    if not isinstance(hosts, list):
        return []
    return list(dict.fromkeys(host for host in hosts
                              if is_eligible(sender, host, nation_data)[0]))


def attaches_from(host, nation_data):
    """Countries currently seeing through a military attaché at ``host``."""
    return [sender for sender in nation_data if host in hosts_for(sender, nation_data)]


def supports_an_enemy(sender, host, nation_data, observed_hosts=None):
    """Whether ``sender`` is aiding a country currently fighting ``host``.

    An attaché is an intelligence privilege, not a way to observe both sides of
    the same war.  A pending volunteer offer counts as aid here too: an AI host
    should not grant its battlefield information while that offer is waiting to
    be answered.
    """
    enemies = set(queries.get_enemies(host, nation_data))
    if not enemies:
        return False

    sender_data = nation_data.get(sender, {})
    missions = sender_data.get("volunteer_missions", {})
    if isinstance(missions, dict):
        for enemy in enemies:
            mission = missions.get(enemy)
            if isinstance(mission, dict) and mission.get("state") != "RETURNING":
                return True

    if observed_hosts is None:
        observed_hosts = hosts_for(sender, nation_data)
    return any(enemy in observed_hosts for enemy in enemies)


def ai_can_accept(sender, host, nation_data):
    """AI-only acceptance rule for an attaché request."""
    legal, reason = is_eligible(sender, host, nation_data)
    if not legal:
        return False, reason
    if supports_an_enemy(sender, host, nation_data):
        return False, "You are supporting a country we are at war with."
    return True, ""


def send(sender, host, nation_data):
    """Record an accepted attaché request, returning ``(changed, reason)``."""
    legal, reason = is_eligible(sender, host, nation_data)
    if not legal:
        return False, reason
    hosts = nation_data[sender].setdefault("military_attaches", [])
    if not isinstance(hosts, list):
        hosts = nation_data[sender]["military_attaches"] = []
    if host in hosts:
        return False, "You already have a military attaché there."
    hosts.append(host)
    return True, ""


def withdraw(sender, host, nation_data):
    """Recall an attaché, returning whether there was one to recall."""
    hosts = nation_data.get(sender, {}).get("military_attaches", [])
    if not isinstance(hosts, list) or host not in hosts:
        return False
    hosts.remove(host)
    if not hosts:
        nation_data[sender].pop("military_attaches", None)
    return True


def revoke_by_host(host, sender, nation_data):
    """Remove ``sender``'s attaché from ``host`` at the host's discretion."""
    return withdraw(sender, host, nation_data)


def schedule_conflict_revocations_for_ai_hosts(nation_data, human_hosts=()):
    """Schedule revocation by AI hosts whose observers support an enemy.

    Every host makes this decision against the same attachment snapshot. This
    matters when an observer is attached to both sides of one war: each side
    learns about the other attachment at the same moment, so both grant access
    first and both subsequently schedule its removal. The withdrawal itself is
    deliberately deferred to the following turn: no country can react to an
    attaché before it has learned the request was accepted.
    """
    human_hosts = set(human_hosts)
    observed_hosts = {
        sender: hosts_for(sender, nation_data)
        for sender in nation_data
    }
    to_revoke = [
        (sender, host)
        for sender, hosts in observed_hosts.items()
        for host in hosts
        if host not in human_hosts
        and supports_an_enemy(sender, host, nation_data, observed_hosts=hosts)
    ]
    scheduled = []
    for sender, host in to_revoke:
        host_data = nation_data.get(host, {})
        pending = host_data.setdefault(PENDING_REVOKE_KEY, [])
        if not isinstance(pending, list):
            pending = host_data[PENDING_REVOKE_KEY] = []
        if sender not in pending:
            pending.append(sender)
            scheduled.append((sender, host))
    return scheduled


def process_scheduled_revocations(nation_data):
    """Carry out AI attaché revocations that were scheduled last turn."""
    revoked = []
    for host, host_data in nation_data.items():
        if not isinstance(host_data, dict):
            continue
        pending = host_data.pop(PENDING_REVOKE_KEY, [])
        if not isinstance(pending, list):
            continue
        for sender in dict.fromkeys(pending):
            if revoke_by_host(host, sender, nation_data):
                revoked.append((sender, host))
    return revoked


def reconcile(nation_data):
    """Immediately withdraw attachés whose host is no longer eligible."""
    withdrawn = []
    for sender, data in list(nation_data.items()):
        if not isinstance(data, dict):
            continue
        hosts = data.get("military_attaches", [])
        if not isinstance(hosts, list):
            data.pop("military_attaches", None)
            continue
        kept = []
        for host in hosts:
            if is_eligible(sender, host, nation_data)[0]:
                kept.append(host)
            else:
                withdrawn.append((sender, host))
        if kept:
            data["military_attaches"] = list(dict.fromkeys(kept))
        else:
            data.pop("military_attaches", None)
    return withdrawn
