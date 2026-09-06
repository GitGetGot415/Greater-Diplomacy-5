"""Military attachés: temporary, host-approved intelligence sharing."""

from data import queries


ACTION = "SEND_MILITARY_ATTACHE"
WITHDRAW_ACTION = "WITHDRAW_MILITARY_ATTACHE"


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
