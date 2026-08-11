"""Everything the AI passes need to know about this turn, computed once.

The strategy AI asks the same few questions over and over: how strong are these
two nations along the border they share, who borders whom, who is holding land
we have a claim on. Every one of those was a full sweep of map_data, and
`ai_thinks_it_can_win` alone is three of them plus one per friendly and one per
enemy nation. On a large map `_run_basic_proactive_ai` was paying for those
thousands of times a turn, which is why the AI could not afford to think any
harder than it did.

AIWorld does the sweeps once and answers from the result. The answers are
identical to the `queries` functions they stand in for -- tests/test_ai_world.py
asserts that pairwise, and that parity is the whole contract. Nothing here is a
better heuristic; it is the same heuristic, affordable.

Why the cached versions live here rather than as `world=` arguments on
data/queries.py: mod_loader replaces whole files by path, so a mod shipping its
own copy of queries.py would break the moment core code passed it an argument
its version had never heard of. The UI keeps calling queries.* exactly as
before; only the AI knows AIWorld exists.

Validity: one turn, and only for the AI phases. Those queue actions into
pending_diplomacy rather than moving units or transferring provinces, so
nothing cached here can go stale underneath them. process_scripted_events,
which *can* hand territory around, runs after every AI phase. The one thing
that does change mid-pass is relation modifiers, so call invalidate_relations()
after writing any.

Stdlib and `data` only -- no requests, no google.genai -- so it imports under
Pyodide alongside the rest of the heuristic AI.
"""

import collections
import random

import data.constants as c
from data import queries


class AIWorld:
    """Per-turn snapshot of the map, with memoised strength/relation queries."""

    def __init__(self, map_data, nation_data, id_to_province, total_turns=0):
        self.map_data = map_data
        self.nation_data = nation_data
        self.id_to_province = id_to_province
        self.total_turns = total_turns

        # Deterministic per-turn randomness for AI decisions. Module-level
        # `random` stays where it is -- get_active_ai_nations shuffles with it
        # and other callers depend on that -- so this only covers choices made
        # through the world.
        self.rng = random.Random(total_turns * 2654435761 + 1013904223)

        #: nation -> [province]. Every province with a truthy owner, including
        #: the unplayable pseudo-owners; callers filter as their query does.
        self.provs_by_owner = collections.defaultdict(list)
        #: nation -> set of bordering nations, unplayable owners excluded
        #: (get_neighboring_nations drops them, so this must too).
        self.neighbors = collections.defaultdict(set)
        #: frozenset({a, b}) -> set of province ids forming their shared front.
        #: Both sides of the border, matching get_border_strength's zone.
        self.border_tiles = collections.defaultdict(set)
        #: (holder, claimant) -> how many of holder's provinces claimant cores
        #: or claims. Unfiltered: get_relation_score's claim penalty counts
        #: every owner, while core_claim_targets drops the unplayable ones.
        self.claim_pressure = collections.Counter()
        #: nation -> province ids that touch water / touch another nation
        self.coast_tiles = collections.defaultdict(set)
        self.land_border_tiles = collections.defaultdict(set)
        #: province ids where mutually hostile units are stacked
        self.combat_tiles = set()

        # Memo tables. _military is filled by the sweep itself rather than on
        # demand -- every nation's total costs the same one pass -- so it has
        # to exist before _sweep runs; the rest fill in lazily.
        self._military = {}
        self._alliance = {}
        self._econ_power = {}
        self._distraction = {}
        self._border_strength = {}
        self._relation = {}
        self._reachable = {}
        self._core_claim_targets = {}
        self._economies = None

        self._sweep()
        self.border_graph = queries.build_national_border_graph(map_data, id_to_province)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _sweep(self):
        """The one pass over map_data that fills every index above."""
        nation_data = self.nation_data
        id_to_province = self.id_to_province

        for prov in self.map_data.values():
            owner = prov.get("owner")
            prov_id = prov["id"]

            for u in prov.get("units", []):
                u_owner = u.get("owner")
                if u_owner:
                    self._military[u_owner] = (self._military.get(u_owner, 0)
                                               + queries.calculate_unit_strength(u))

            if queries.is_province_in_active_combat(prov, nation_data):
                self.combat_tiles.add(prov_id)

            for cored_by in prov.get("cores", []):
                if owner and cored_by != owner:
                    self.claim_pressure[(owner, cored_by)] += 1

            if not owner:
                continue

            self.provs_by_owner[owner].append(prov)

            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if not n_prov:
                    continue

                if queries.is_water_province(n_prov):
                    self.coast_tiles[owner].add(prov_id)
                    continue

                n_owner = n_prov.get("owner")
                if not n_owner or n_owner == owner:
                    continue

                self.land_border_tiles[owner].add(prov_id)
                # Both sides of the adjacency, matching get_border_strength's
                # zone. Adding the far tile is redundant while neighbour lists
                # are symmetric -- the sweep reaches it from its own side too --
                # but it is what keeps the front complete if one ever isn't,
                # and it is how the original builds the zone from one side.
                pair = frozenset((owner, n_owner))
                self.border_tiles[pair].add(prov_id)
                self.border_tiles[pair].add(n_id)

                if n_owner not in c.UNPLAYABLE_NATIONS:
                    self.neighbors[owner].add(n_owner)

        # Claims are stored per nation as province id lists, so they are
        # cheaper to fold in from the other direction than to look up per tile.
        for nation, data in nation_data.items():
            if not isinstance(data, dict):
                continue
            for prov_id in data.get("claims", []):
                prov = id_to_province.get(prov_id)
                if not prov:
                    continue
                owner = prov.get("owner")
                # A core on the same tile already counted this pair, and
                # get_relation_score counts a tile once however it qualifies.
                if owner and owner != nation and nation not in prov.get("cores", []):
                    self.claim_pressure[(owner, nation)] += 1

    # ------------------------------------------------------------------
    # Strength
    # ------------------------------------------------------------------

    def military(self, nation):
        """queries.get_military_strength, totalled for every nation in one sweep.

        The query scans the whole map per nation asked about, and
        alliance_strength asks about every friendly nation in turn, so a single
        can-we-win check used to cost a sweep per member of both alliances.
        Summing per owner as the sweep goes makes all of them one pass.
        """
        return self._military.get(nation, 0)

    def alliance_strength(self, nation):
        """queries.get_alliance_military_strength."""
        cached = self._alliance.get(nation)
        if cached is None:
            cached = sum(self.military(member)
                         for member in queries.get_all_friendly_nations(nation, self.nation_data))
            self._alliance[nation] = cached
        return cached

    def econ_power(self, nation):
        """queries.get_economic_power (stockpile-weighted, not income)."""
        cached = self._econ_power.get(nation)
        if cached is None:
            cached = queries.get_economic_power(nation, self.nation_data)
            self._econ_power[nation] = cached
        return cached

    def enemy_distraction(self, nation):
        """queries.get_combined_enemy_strength -- how busy this nation already is."""
        cached = self._distraction.get(nation)
        if cached is None:
            cached = sum(self.military(enemy)
                         for enemy in queries.get_enemies(nation, self.nation_data)
                         if enemy in self.nation_data and enemy not in c.UNPLAYABLE_NATIONS)
            self._distraction[nation] = cached
        return cached

    def border_strength(self, nation_a, nation_b):
        """queries.get_border_strength -- (a's strength, b's strength) on their shared front.

        Both sides are measured over the same tile set, friendlies included,
        capped at combat width per tile, with anyone already fighting a third
        party counting for less.
        """
        key = (nation_a, nation_b)
        cached = self._border_strength.get(key)
        if cached is not None:
            return cached

        tiles = self.border_tiles.get(frozenset((nation_a, nation_b)), ())
        result = (self._front_strength(tiles, nation_a, nation_b),
                  self._front_strength(tiles, nation_b, nation_a))
        self._border_strength[key] = result
        self._border_strength[(nation_b, nation_a)] = (result[1], result[0])
        return result

    def _front_strength(self, prov_ids, evaluating_nation, opposing_nation):
        nation_data = self.nation_data
        friendly = queries.get_all_friendly_nations(evaluating_nation, nation_data)
        strength = 0

        for prov_id in prov_ids:
            prov = self.id_to_province.get(prov_id)
            if not prov:
                continue

            units = prov.get("units", [])
            friendly_units = [u for u in units if u.get("owner") in friendly]
            top_units = sorted(friendly_units, key=queries.calculate_unit_strength,
                               reverse=True)[:c.MAX_COMBAT_ATTACKERS]

            for u in top_units:
                base_str = queries.calculate_unit_strength(u)
                owner = u.get("owner")
                for other_u in units:
                    other_owner = other_u.get("owner")
                    if other_owner != opposing_nation and queries.are_at_war(owner, other_owner, nation_data):
                        base_str *= c.AI_BORDER_DISTRACTION_MULTIPLIER
                        break
                strength += base_str

        return strength

    def power_ratio(self, ai_nation, target_nation):
        """The two quantities ai_thinks_it_can_win thresholds, as numbers.

        Returns (border_ratio, global_ratio). The booleans that gate war today
        are just these two against AI_WAR_STRENGTH_THRESHOLD and
        AI_GLOBAL_STRENGTH_THRESHOLD; exposing the ratios lets a caller reason
        in degrees instead of a yes/no. Phase 3's war_desire is the first
        caller that needs that.
        """
        my_border, target_border = self.border_strength(ai_nation, target_nation)
        target_border = max(1, target_border)

        my_total = (self.alliance_strength(ai_nation)
                    + self.econ_power(ai_nation) / 100.0
                    + self.enemy_distraction(target_nation) * c.AI_ENEMY_DISTRACTION_WEIGHT)
        target_total = max(1.0, self.alliance_strength(target_nation)
                           + self.econ_power(target_nation) / 100.0)

        return my_border / target_border, my_total / target_total

    def thinks_it_can_win(self, ai_nation, target_nation):
        """queries.ai_thinks_it_can_win, from the cached ratios."""
        border_ratio, global_ratio = self.power_ratio(ai_nation, target_nation)
        return (border_ratio >= c.AI_WAR_STRENGTH_THRESHOLD
                and global_ratio >= c.AI_GLOBAL_STRENGTH_THRESHOLD)

    def is_weaker_neighbor(self, ai_nation, target_nation):
        """queries.is_weaker_neighbor -- note this one ignores the border and distraction."""
        my_total = self.alliance_strength(ai_nation) + self.econ_power(ai_nation) / 100.0
        target_total = max(1.0, self.alliance_strength(target_nation)
                           + self.econ_power(target_nation) / 100.0)
        return target_total < (my_total * c.AI_WEAK_NEIGHBOR_STRENGTH_RATIO)

    # ------------------------------------------------------------------
    # Diplomacy
    # ------------------------------------------------------------------

    def relation(self, nation_a, nation_b):
        """queries.get_relation_score, claim penalty always included.

        The AI's one relation-driven decision today calls the query without
        id_to_province, which silently skips the claim penalty. Here the count
        is already indexed, so the full score costs nothing and there is no
        reason to ever compute the partial one.
        """
        if nation_a == nation_b:
            return 0

        key = (nation_a, nation_b)
        cached = self._relation.get(key)
        if cached is not None:
            return cached

        nation_data = self.nation_data
        score = 0
        if queries.are_at_war(nation_a, nation_b, nation_data):
            score += c.REL_MOD_AT_WAR
        elif queries.are_in_same_faction(nation_a, nation_b, nation_data):
            score += c.REL_MOD_IN_FACTION

        if set(queries.get_enemies(nation_a, nation_data)) & set(queries.get_enemies(nation_b, nation_data)):
            score += c.REL_MOD_COMMON_ENEMY

        master_a = nation_data.get(nation_a, {}).get("master", "")
        master_b = nation_data.get(nation_b, {}).get("master", "")
        if master_b == nation_a:
            score += c.REL_MOD_MASTER_OF
        elif master_a == nation_b:
            score += c.REL_MOD_PUPPET_OF

        for entry in nation_data.get(nation_a, {}).get("temp_modifiers", {}).get(nation_b, {}).values():
            score += queries.modifier_value(entry)

        contested = self.claim_pressure[(nation_b, nation_a)] + self.claim_pressure[(nation_a, nation_b)]
        score -= min(abs(c.REL_MOD_MAX_CLAIM_PENALTY), contested * abs(c.REL_MOD_PER_CLAIM))

        self._relation[key] = score
        return score

    def invalidate_relations(self):
        """Drops memoised relation scores after a pass writes temp_modifiers."""
        self._relation.clear()

    def core_claim_targets(self, nation):
        """queries.get_nations_holding_our_cores_or_claims."""
        cached = self._core_claim_targets.get(nation)
        if cached is None:
            cached = {holder for (holder, claimant), count in self.claim_pressure.items()
                      if claimant == nation and count > 0
                      and holder != nation and holder not in c.UNPLAYABLE_NATIONS}
            self._core_claim_targets[nation] = cached
        return cached

    def reachable(self, nation_a, target_nation):
        """queries.is_nation_reachable, reusing the prebuilt border graph."""
        key = (nation_a, target_nation)
        cached = self._reachable.get(key)
        if cached is None:
            cached = queries.is_nation_reachable(nation_a, target_nation, self.map_data,
                                                 self.id_to_province, self.nation_data,
                                                 borders=self.border_graph)
            self._reachable[key] = cached
        return cached

    # ------------------------------------------------------------------
    # Economy
    # ------------------------------------------------------------------

    @property
    def economies(self):
        """queries.calculate_all_economies, computed on first ask.

        Lazy because the diplomacy passes never look at it and it is the most
        expensive single thing in here; Phase 2's unit pricing is what makes it
        worth caching at all.
        """
        if self._economies is None:
            self._economies = queries.calculate_all_economies(self.map_data, self.nation_data)
        return self._economies


def build(map_screen):
    """Snapshots the map for this turn's AI passes."""
    total_turns = 0
    time_manager = getattr(map_screen, "time_manager", None)
    if time_manager is not None:
        total_turns = queries.get_total_turns(time_manager)

    return AIWorld(map_screen.map_data, map_screen.nation_data,
                   map_screen.id_to_province, total_turns)


def for_screen(map_screen):
    """This turn's snapshot, or a throwaway one if the caller is outside a turn.

    prepare_turn builds the shared snapshot and clears it again afterwards, so
    an AI pass invoked from anywhere else -- Automate This Turn runs three of
    them straight off a button -- would otherwise find nothing there. Building
    one on the spot costs a sweep, which is still what the code did before the
    cache existed, and keeps every AI entry point callable on its own.
    """
    world = getattr(map_screen, "ai_world", None)
    return world if world is not None else build(map_screen)
