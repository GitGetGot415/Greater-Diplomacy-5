"""Whether a nation could actually get to a province, on its own.

A treaty could name any province on the map. Nothing anywhere asked whether the
nation receiving it had any way of reaching the place: a player at war with the
United Kingdom could demand Australia, and a trade could move a province between
two countries on opposite sides of the world.

The rule is the plain one. You can have it if you can get to it:

  * you are already standing on it -- it is yours, the treaty only says so;
  * it touches land you own;
  * it touches water that also touches land you own.

"On its own" is the whole point of the third word in the title. Only the
receiving nation's own provinces seed the search -- not its puppets', not its
allies', not its faction's. queries.is_nation_reachable, which answers a
different question for the AI's war planning, walks out of every friendly
capital at once and lets armies cross anybody who is not hostile; that is right
for "can this war be fought at all" and wrong for "is this mine to ask for".

Water is walked as connected bodies rather than tested with the `is_coastal`
flag, because a lake is water too. The 1941 map has one 469-tile ocean and
twenty-six separate lakes, so a nation on one shore of a lake reaches the far
shore of that lake and nothing else -- which is exactly what it should get, and
is not something a flag can express.

Stdlib and `data` only.
"""

import collections

import data.constants as c
from data import queries


class Reachability:
    """One sweep of the map, then a cheap answer per nation.

    Built once and reused: the two sweeps below are the expensive part and they
    do not depend on who is asking. AIWorld keeps one for the turn, the deal
    screen keeps one for as long as it is open, and prune builds one per treaty.
    """

    def __init__(self, map_data):
        self._by_id = {}
        self._body_of = {}          # water province id -> body id
        self._touches = {}          # land province id -> frozenset of body ids
        self._neighbours = {}       # land province id -> tuple of land neighbour ids
        self._seeds = {}            # nation -> (owned ids, bodies, neighbour ids)

        for prov in map_data.values():
            self._by_id[int(prov["id"])] = prov

        self._find_water_bodies()
        self._map_shores()

    # -- construction -------------------------------------------------- #

    def _find_water_bodies(self):
        water = {pid for pid, prov in self._by_id.items()
                 if queries.is_water_province(prov)}
        body = 0
        for start in water:
            if start in self._body_of:
                continue
            body += 1
            queue = collections.deque([start])
            self._body_of[start] = body
            while queue:
                current = queue.popleft()
                for n_id in self._by_id[current].get("neighbors", ()):
                    n_id = int(n_id)
                    if n_id in water and n_id not in self._body_of:
                        self._body_of[n_id] = body
                        queue.append(n_id)

    def _map_shores(self):
        for pid, prov in self._by_id.items():
            if pid in self._body_of:
                continue
            bodies, land = set(), []
            for n_id in prov.get("neighbors", ()):
                n_id = int(n_id)
                if n_id in self._body_of:
                    bodies.add(self._body_of[n_id])
                elif n_id in self._by_id:
                    land.append(n_id)
            self._touches[pid] = frozenset(bodies)
            self._neighbours[pid] = tuple(land)

    def _seeds_for(self, nation):
        """(what they hold, which waters they sit on, what they border)."""
        cached = self._seeds.get(nation)
        if cached is not None:
            return cached

        held = {pid for pid, prov in self._by_id.items()
                if prov.get("owner") == nation and pid not in self._body_of}
        bodies = set()
        border = set()
        for pid in held:
            bodies |= self._touches.get(pid, ())
            border.update(self._neighbours.get(pid, ()))

        cached = (held, bodies, border)
        self._seeds[nation] = cached
        return cached

    # -- the question -------------------------------------------------- #

    def reachable(self, nation, prov):
        """Whether `nation` could get to this province without anyone's help."""
        if not nation or nation in c.UNPLAYABLE_NATIONS:
            return False

        pid = int(prov["id"]) if isinstance(prov, dict) else int(prov)
        if pid in self._body_of:
            return False        # nobody is handed an ocean tile in a treaty

        held, bodies, border = self._seeds_for(nation)
        if pid in held or pid in border:
            return True
        return bool(bodies & self._touches.get(pid, frozenset()))

    def unreachable_ids(self, nation, prov_ids):
        """The subset of `prov_ids` this nation could not get to, in order."""
        out = []
        for pid in prov_ids:
            prov = self._by_id.get(int(pid))
            if prov is not None and not self.reachable(nation, prov):
                out.append(int(pid))
        return out


def index(map_data):
    """A Reachability for this map. Callers that ask more than once should
    hold on to it rather than calling this again."""
    return Reachability(map_data)
