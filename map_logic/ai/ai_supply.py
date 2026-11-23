"""Supply information and projected assignments for one country's order pass."""

from collections import defaultdict

import data.constants as c
from data import queries
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
        self.incoming = defaultdict(list)
        self.enemies = set(queries.get_enemies(country, known.nations))
        self.critical = self._critical_corridors() if self.enemies else set()

    def fractions(self, unit):
        if unit.get("owner") == self.country:
            return self.actual.fractions(unit)
        if self.known.visible_provinces is None:
            return self.known.fractions(unit)
        # Unknown enemy production and force size make foreign supply uncertain.
        return None

    def current(self, unit):
        return self._conditions(unit, self.fractions(unit))

    def _conditions(self, unit, fractions):
        speed = unit.get("speed", c.DEFAULT_UNIT_SPD)
        if fractions is None:
            return 1.0, speed
        return queries.supply_fraction(fractions), queries.fuel_movement_speed(speed, fractions[2])

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
        for tile in cuts:
            area_id = areas[tile]
            before = self.network.areas[area_id]
            if not any(before.demand.values()):
                continue
            baseline = queries.supply_fractions(before.production, before.demand, before.demand)
            visited = {tile}
            for start in neighbors[tile]:
                if start in visited or areas.get(start) != area_id:
                    continue
                supply = queries.SupplyArea()
                pending = [start]
                visited.add(start)
                while pending:
                    here = pending.pop()
                    if here not in self.known.water and self.known.provinces[here].get("owner") == self.country:
                        for resource, amount in self.known.province_output(here).items():
                            supply.production[resource] += amount
                    for identity in self.known.land_units[self.country].get(here, ()):
                        for resource, amount in self.known.unit_data[identity].demand.items():
                            supply.demand[resource] += amount
                    for near in neighbors[here]:
                        if near not in visited and areas.get(near) == area_id:
                            visited.add(near)
                            pending.append(near)
                after = queries.supply_fractions(supply.production, supply.demand, supply.demand)
                if any(new < old for new, old in zip(after, baseline)):
                    critical.add(tile)
                    break
        return critical

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
            return self._conditions(unit, tuple(0.0 if demand[key] else 1.0 for key in c.ECON_RESOURCE_KEYS))
        added = {key: total + (demand[key] if area != origin else 0.0) for key, total in self.demand[area].items()}
        return self._conditions(unit, queries.supply_fractions(self.network.areas[area].production, added, demand))

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
            for key in areas:
                area = self.network.areas[key]
                if any(area.production[resource] < self.demand[key][resource] for resource in c.ECON_RESOURCE_KEYS):
                    targets.add(tile)
                    break
        return targets

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
        self.incoming[path[-1]].append(unit)

    def improves_reinforcement(self, unit, province):
        """Compare projected combat exchanges if extra demand weakens the front."""
        data = self._unit(unit)
        area = self.destination_area(unit, province["id"])
        if data is None or area is None or area == self._area(unit):
            return True
        production = self.network.areas[area].production
        demand = self.demand[area]
        extra = {key: demand[key] + data.demand[key] for key in c.ECON_RESOURCE_KEYS}
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

        def exchange(participants, totals):
            profiles = []
            for participant in participants:
                row = self._unit(participant)
                values = queries.supply_fractions(production, totals, row.demand) if row else self.fractions(participant)
                profile = queries.supply_combat_profile(participant)
                if values is not None:
                    profile["_supply_multiplier"] = queries.supply_fraction(values)
                profiles.append(profile)
            battle = combat_rules.build_battle([profiles, enemies], self.known.nations,
                                               terrain=province.get("terrain"), tiles=(province, province))
            incoming = combat_rules.projected_incoming_damage(battle, self.known.nations)
            return (sum(min(enemy["health"], incoming.get(id(enemy), 0.0)) for enemy in enemies)
                    - sum(min(friend["health"], incoming.get(id(friend), 0.0)) for friend in profiles))

        return exchange([*friends, unit], extra) > exchange(friends, demand)
