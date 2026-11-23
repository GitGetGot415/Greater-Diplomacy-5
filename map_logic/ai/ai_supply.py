"""Supply information and projected assignments for one country's order pass."""

from collections import defaultdict, deque

import data.constants as c
from data import queries
from map_logic.ai import ai_tuning
from map_logic.system32 import combat_rules


def _articulation_tiles(neighbors, areas):
    """Find provinces whose loss splits a route, including alternate sea routes."""
    depth = {}
    low = {}
    cuts = set()
    for root in areas:
        if root in depth:
            continue
        depth[root] = low[root] = 0
        stack = [(root, None, iter(neighbors[root]))]
        children = 0
        while stack:
            tile, parent, edges = stack[-1]
            neighbor = next(edges, None)
            if neighbor is None:
                stack.pop()
                if parent is not None:
                    low[parent] = min(low[parent], low[tile])
                    if parent != root and low[tile] >= depth[parent]:
                        cuts.add(parent)
                continue
            if neighbor == parent or areas.get(neighbor) != areas[tile]:
                continue
            if neighbor in depth:
                low[tile] = min(low[tile], depth[neighbor])
                continue
            if tile == root:
                children += 1
            depth[neighbor] = low[neighbor] = depth[tile] + 1
            stack.append((neighbor, tile, iter(neighbors[neighbor])))
        if children > 1:
            cuts.add(root)
    return cuts


class SupplyPlanner:
    def __init__(self, actual, known, country):
        self.actual = actual
        self.known = known
        self.country = country
        self.network = known.for_country(country) if country in known.land_units else queries.SupplyNetwork()
        self.demand = {key: area.demand.copy() for key, area in self.network.areas.items()}
        self.projections = {}
        self.incoming = defaultdict(list)
        self.enemies = set(queries.get_enemies(country, known.nations))
        self.critical = self._critical_corridors() if self.enemies else set()

    def status(self, unit):
        if unit.get("owner") == self.country:
            return self.actual.status(unit)
        if self.known.visible_provinces is None:
            return self.known.status(unit)
        # Unknown enemy production and force size make foreign supply uncertain.
        return None

    def current(self, unit):
        return self._conditions(unit, self.status(unit))

    def _conditions(self, unit, status):
        speed = unit.get("speed", c.DEFAULT_UNIT_SPD)
        if status is None:
            return 1.0, speed
        return status.readiness, queries.fuel_movement_speed(speed, status.fractions[2])

    def _unit(self, unit):
        return self.known.unit_data.get(queries.supply_unit_key(unit))

    def _area(self, unit):
        return self.network.unit_area.get(queries.supply_unit_key(unit))

    def _critical_corridors(self):
        areas = self.network.province_area
        neighbors = self.known.neighbors
        threats = {tile for tile in areas.keys() - self.known.water
                   if any(self.known.provinces[near].get("owner") in self.enemies
                          or self.known.occupants.get(near, set()) & self.enemies for near in neighbors[tile])}
        if not threats:
            return set()
        cuts = _articulation_tiles(neighbors, areas) & threats
        critical = set()
        units = [(self.known.unit_data[identity], area_id) for identity, area_id in self.network.unit_area.items()]
        for tile in cuts:
            area_id = areas[tile]
            exposed = [data.unit for data, area in units if area == area_id and data.province != tile]
            if not exposed:
                continue
            projected = self.known.land_projection(self.country, tile)
            if any(any(new < old for new, old in zip(self.known.fractions(unit, network=projected),
                                                    self.known.fractions(unit, network=self.network))) for unit in exposed):
                critical.add(tile)
        return critical

    def _projected_demand(self, area=None, origin=None, upkeep=None):
        key = (area, origin, tuple(upkeep.values()) if upkeep else ())
        if key not in self.projections:
            demand = self.demand.copy()
            if upkeep is not None and area != origin:
                for area_id, direction in ((origin, -1), (area, 1)):
                    if area_id is not None:
                        demand[area_id] = {resource: amount + direction * upkeep[resource]
                                           for resource, amount in self.demand[area_id].items()}
            self.projections[key] = self.known.demand_projection(self.country, demand)
        return self.projections[key]

    def destination_area(self, unit, tile, connected=None):
        own_area = self._area(unit)
        area = self.network.province_area.get(tile)
        if area is not None:
            return area
        choices = self.known.neighboring_areas(self.network, tile)
        if connected is not None:
            choices.add(connected)
        return max(sorted(choices), key=lambda choice: self._quality(unit, choice, own_area), default=None)

    def _quality(self, unit, area, origin=None):
        data = self._unit(unit)
        if data is None:
            return self._conditions(unit, None)
        demand = data.demand
        if area is None:
            fractions = tuple(0.0 if demand[key] else 1.0 for key in c.ECON_RESOURCE_KEYS)
        else:
            projected = self._projected_demand(area, origin, demand)
            fractions = queries.supply_fractions(projected.available(area), projected.areas[area].demand, demand)
        return self._conditions(unit, queries.SupplyStatus.from_fractions(fractions, demand))

    def quality(self, unit, tile):
        origin = self._area(unit)
        destination = self.destination_area(unit, tile)
        return self.current(unit) if destination == origin else self._quality(unit, destination, origin)

    def advance(self, unit, path):
        """Trim an advance where a visible fight can stop the corridor opening."""
        area = self._area(unit)
        result = []
        vulnerable = False
        for tile in path:
            next_area = self.destination_area(unit, tile, area)
            exposed = (tile not in self.network.province_area and len(self.known.neighboring_areas(self.network, tile)) <= 1
                       and any(self.known.occupants.get(near, set()) & self.enemies
                               for near in self.known.neighbors.get(tile, ())))
            if result and (self._quality(unit, next_area, self._area(unit)) < self.current(unit) or vulnerable and exposed):
                break
            result.append(tile)
            if self.known.occupants.get(tile, set()) & self.enemies:
                break
            area = next_area
            vulnerable |= exposed
        return result

    def relief_targets(self, tiles):
        targets = set()
        for tile in tiles:
            if tile in self.network.province_area or tile in self.known.water:
                continue
            areas = self.known.neighboring_areas(self.network, tile)
            if len(areas) < 2:
                continue
            projected = self._projected_demand()
            for key in areas:
                available = projected.available(key)
                if any(available[resource] < projected.areas[key].demand[resource] for resource in c.ECON_RESOURCE_KEYS):
                    targets.add(tile)
                    break
        return targets

    def _naval_shortlist(self, country, tiles, network):
        """Prefer sea approaches close to forces that could lose supply."""
        if not tiles:
            return []
        pending = deque(sorted(self.known.land_units[country]))
        seen = set(pending)
        ranked = []
        while pending and len(ranked) < ai_tuning.AI_SUPPLY_SEA_CANDIDATES:
            here = pending.popleft()
            if here in tiles:
                ranked.append(here)
            for near in self.known.neighbors[here]:
                if near not in seen and (near in self.known.sea or near in network.province_area):
                    seen.add(near)
                    pending.append(near)
        return ranked

    def _naval_impact(self, country, before, after):
        """Measure the change in effective health and movement of observed forces."""
        impact = 0.0
        for group in self.known.land_units[country].values():
            for identity in group:
                unit = self.known.unit_data[identity].unit
                readiness_before, speed_before = self._conditions(unit, self.known.status(unit, network=before))
                readiness_after, speed_after = self._conditions(unit, self.known.status(unit, network=after))
                impact += unit["health"] * (readiness_after - readiness_before
                                           + (speed_after - speed_before) / max(1, unit.get("speed", c.DEFAULT_UNIT_SPD)))
        return impact

    def naval_supply_objectives(self, reachable, enemy_reach, vacating_ships, stations, available_ships):
        """Score sea occupations and clearances with the actual supply network rules.

        A two-tile blockade is one objective: a partial assignment is worth
        nothing if it leaves the other route open.
        """
        sea = self.known.sea & reachable
        if not self.enemies or not sea:
            return []
        objectives = []
        visible_blockers = {tile for tile in sea if self.known.occupants.get(tile, set()) & self.enemies}
        if self.country in self.known.land_units:
            home = self.known.sea_projection(self.country)
            for tile in self._naval_shortlist(self.country, visible_blockers, home):
                opened = self.known.sea_projection(self.country, reopen=(tile,))
                gain = self._naval_impact(self.country, home, opened)
                if gain > 0:
                    objectives.append(("relief", gain, (tile,), self.country))
            unexplained = any(self.current(self.known.unit_data[identity].unit)
                              < self._conditions(self.known.unit_data[identity].unit,
                                                 self.known.status(self.known.unit_data[identity].unit, network=home))
                              for group in self.known.land_units[self.country].values() for identity in group)
            if unexplained or enemy_reach:
                candidates = sea & home.province_area.keys()
                if not unexplained:
                    candidates &= enemy_reach.keys()
                quiet = []
                for tile in self._naval_shortlist(self.country, candidates, home):
                    closed = self.known.sea_projection(self.country, block=(tile,))
                    loss = -self._naval_impact(self.country, home, closed)
                    if loss > 0:
                        kind = "guard" if tile in enemy_reach else "scout"
                        objectives.append((kind, loss, (tile,), self.country))
                    elif unexplained or tile in enemy_reach:
                        quiet.append(tile)

                # One guarded or scouted opening can be useful when the
                # garrison can draw through either of two threatened routes.
                for index, first in enumerate(quiet):
                    for second in quiet[index + 1:]:
                        threaten_both = any(a is not b for _, a in enemy_reach.get(first, ()) for _, b in enemy_reach.get(second, ()))
                        if not unexplained and not threaten_both:
                            continue
                        closed = self.known.sea_projection(self.country, block=(first, second))
                        loss = -self._naval_impact(self.country, home, closed)
                        if loss > 0:
                            if threaten_both:
                                objectives.append(("guard_one", loss, (first, second), self.country))
                            else:
                                objectives.extend(("scout", loss, (tile,), self.country) for tile in (first, second))

        for enemy in sorted(self.enemies & self.known.land_units.keys()):
            # Ships available for reassignment can leave their starting tile.
            # Count a blockade by those ships only if they are assigned to hold it.
            base = self.known.sea_projection(enemy, block=stations, blocker=self.country, departing=vacating_ships)
            candidates = self._naval_shortlist(enemy, sea & base.province_area.keys(), base)
            if not candidates:
                continue
            quiet = []
            for tile in candidates:
                cut = (tile,)
                after = self.known.sea_projection(enemy, block=stations | {tile}, blocker=self.country, departing=vacating_ships)
                loss = -self._naval_impact(enemy, base, after)
                if loss > 0:
                    objectives.append(("blockade", loss, cut, enemy))
                else:
                    quiet.append(tile)

            if available_ships < 2:
                continue
            for index, first in enumerate(quiet):
                for second in quiet[index + 1:]:
                    cut = (first, second)
                    after = self.known.sea_projection(enemy, block=stations | set(cut), blocker=self.country, departing=vacating_ships)
                    loss = -self._naval_impact(enemy, base, after)
                    if loss > 0:
                        objectives.append(("blockade", loss, cut, enemy))
        return objectives

    def book(self, unit, path):
        data = self._unit(unit)
        if data is None or not path:
            return
        start = self._area(unit)
        end = start
        for tile in path:
            end = self.destination_area(unit, tile, end)
        if end != start:
            for resource, amount in data.demand.items():
                if start is not None:
                    self.demand[start][resource] -= amount
                if end is not None:
                    self.demand[end][resource] += amount
            self.projections.clear()
        self.incoming[path[-1]].append(unit)

    def improves_reinforcement(self, unit, province):
        """Compare projected combat exchanges if extra demand weakens the front."""
        data = self._unit(unit)
        area = self.destination_area(unit, province["id"])
        if data is None or area is None or area == self._area(unit):
            return True
        current = self._projected_demand()
        projected = self._projected_demand(area, self._area(unit), data.demand)
        production, extra = projected.available(area), projected.areas[area].demand
        if all(extra[key] <= production[key] or data.demand[key] == 0 for key in extra):
            return True
        friends = list(self.incoming[province["id"]])
        enemies = []
        for other in province.get("units", ()):
            if other is unit:
                continue
            owner = queries.get_unit_combat_owner(other)
            if owner == self.country:
                friends.append(other)
            elif (owner in self.enemies and owner in self.known.occupants.get(province["id"], ())
                  and queries.is_unit_visible_to(other, self.country, province, self.known.nations)):
                enemies.append(other)
        if not friends or not enemies:
            return True

        def exchange(participants, production, totals):
            profiles = []
            for participant in participants:
                row = self._unit(participant)
                profile = queries.supply_combat_profile(participant)
                if row is not None:
                    fractions = queries.supply_fractions(production, totals, row.demand)
                    profile["_supply_multiplier"] = queries.supply_fraction(fractions, row.demand)
                elif (status := self.status(participant)) is not None:
                    profile["_supply_multiplier"] = status.readiness
                profiles.append(profile)
            battle = combat_rules.build_battle([profiles, enemies], self.known.nations,
                                               terrain=province.get("terrain"), tiles=(province, province))
            incoming = combat_rules.projected_incoming_damage(battle, self.known.nations)
            return (sum(min(enemy["health"], incoming.get(id(enemy), 0.0)) for enemy in enemies)
                    - sum(min(friend["health"], incoming.get(id(friend), 0.0)) for friend in profiles))

        return exchange([*friends, unit], production, extra) > exchange(friends, current.available(area), current.areas[area].demand)
