"""Connected province production and land division supply."""

from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

import data.constants as c
from data import queries
from data.state_access import session_for, world_for


_COMBAT_SUPPLY = ContextVar("combat_supply", default=None)
_ATTRITION_RATE = 0.10
_ROUTE_PROJECTION_LIMIT = 24


def _resources():
    return dict.fromkeys(c.ECON_RESOURCE_KEYS, 0.0)


def _add_resources(total, amounts, scale=1):
    for resource in c.ECON_RESOURCE_KEYS:
        total[resource] += amounts[resource] * scale


def supply_fractions(production, demand, unit_demand):
    return tuple(min(1.0, max(0.0, production[resource] / demand[resource]))
                 if unit_demand[resource] > 0 and demand[resource] > 0 else 1.0
                 for resource in c.ECON_RESOURCE_KEYS)


def supply_fraction(fractions, unit_demand):
    """Share of the unit's Manpower and Materials upkeep covered by supply."""
    manpower, materials, _fuel = fractions
    manpower_demand = unit_demand["manpower"]
    materials_demand = unit_demand["materials"]
    total = manpower_demand + materials_demand
    return (manpower * manpower_demand + materials * materials_demand) / total if total else 1.0


@dataclass(frozen=True)
class SupplyStatus:
    fractions: tuple
    readiness: float

    @classmethod
    def from_fractions(cls, fractions, unit_demand):
        return cls(fractions, supply_fraction(fractions, unit_demand))


def fuel_movement_speed(speed, fuel):
    """Partial fuel unlocks higher speeds only above each exact threshold."""
    if speed <= 1 or fuel >= 1.0:
        return speed
    return 1 + sum(fuel > step / (speed - 1) for step in range(1, speed - 1))


def supply_unit_key(unit):
    return unit.get("unit_id") or id(unit)


@dataclass
class SupplyArea:
    production: dict = field(default_factory=_resources)
    demand: dict = field(default_factory=_resources)


@dataclass
class SupplyNetwork:
    province_area: dict = field(default_factory=dict)
    unit_area: dict = field(default_factory=dict)
    areas: dict = field(default_factory=dict)
    production_tiles: dict = field(default_factory=dict)
    contested: dict = field(default_factory=dict)
    allied_supply: dict = field(default_factory=dict)

    def available(self, area_id):
        production = self.areas[area_id].production
        support = self.allied_supply.get(area_id)
        return ({resource: production[resource] + support[resource] for resource in c.ECON_RESOURCE_KEYS}
                if support else production)


def _divide_surplus(pools, remaining):
    """Allocate one resource by unmet demand, redirecting any excess offers."""
    capacity = pools
    assigned = defaultdict(dict)
    received = defaultdict(float)
    while pools:
        offers = []
        totals = defaultdict(float)
        for recipients, stock in pools.items():
            demand = sum(remaining[recipient] for recipient in recipients)
            if not demand:
                continue
            budget = min(stock, demand)
            amounts = {recipient: amount for recipient in recipients if (amount := budget * (remaining[recipient] / demand)) > 0}
            for recipient, amount in amounts.items():
                totals[recipient] += amount
            offers.append((recipients, stock, demand, amounts))
        if not totals:
            break
        acceptance = {recipient: min(1.0, remaining[recipient] / amount) for recipient, amount in totals.items()}
        pools = {}
        for recipients, stock, demand, amounts in offers:
            capped = any(acceptance[recipient] < 1.0 for recipient in amounts)
            for recipient, amount in amounts.items():
                used = amount * acceptance[recipient]
                assigned[recipients][recipient] = assigned[recipients].get(recipient, 0.0) + used
            if capped or stock > demand:
                leftover = stock - sum(amount * acceptance[recipient] for recipient, amount in amounts.items())
                if leftover > 0:
                    pools[recipients] = leftover
        for recipient, amount in totals.items():
            used = min(amount, remaining[recipient])
            received[recipient] += used
            remaining[recipient] -= used
    if any(remaining.values()):
        _use_remaining_surplus(capacity, assigned, remaining, received)
    return received


def _use_remaining_surplus(capacity, assigned, remaining, received):
    """Swap equivalent deliveries if a flexible donor can cover another pocket."""
    donors = defaultdict(list)
    for pool in capacity:
        for recipient in pool:
            donors[recipient].append(pool)
    for start, stock in capacity.items():
        free = stock - sum(assigned[start].values())
        while free > 0:
            previous = {start: ()}
            pending = deque([start])
            destination = None
            while pending and destination is None:
                pool = pending.popleft()
                for recipient in pool:
                    if remaining[recipient] > 0:
                        destination = pool, recipient
                        break
                    for donor in donors[recipient]:
                        used = assigned[donor].get(recipient, 0)
                        if used > 0 and donor not in previous:
                            previous[donor] = pool, recipient, used
                            pending.append(donor)
            if destination is None:
                break
            pool, recipient = destination
            swaps = []
            amount = min(free, remaining[recipient])
            while pool != start:
                earlier, exchange, used = previous[pool]
                swaps.append((earlier, exchange, pool, used))
                amount = min(amount, used)
                pool = earlier
            pool, recipient = destination
            assigned[pool][recipient] = assigned[pool].get(recipient, 0.0) + amount
            received[recipient] += amount
            remaining[recipient] -= amount
            free -= amount
            for earlier, exchange, later, used in swaps:
                assigned[earlier][exchange] = assigned[earlier].get(exchange, 0.0) + amount
                assigned[later][exchange] = used - amount


@dataclass
class SupplyUnit:
    unit: dict
    country: str
    owner: str
    province: int
    demand: dict


class SupplySnapshot:
    """Lazy country networks sharing one indexed view of a phase's world."""

    def __init__(self, context, *, visible_to=None, visible_provinces=None, source=None):
        world = world_for(context)
        self.nations = world.nation_data
        self.visible_to = visible_to
        self.visible_provinces = visible_provinces
        if source is None:
            self.provinces = {province["id"]: province for province in world.map_data.values() if "id" in province}
            self.water = {key for key, province in self.provinces.items() if queries.is_water_province(province)}
            self.sea = {key for key in self.water if self.provinces[key].get("terrain") in c.OCEAN_TERRAINS}
            self.owned_land = defaultdict(list)
            for key, province in self.provinces.items():
                if key not in self.water:
                    self.owned_land[province.get("owner")].append(key)
            self.neighbors = {
                key: tuple(neighbor for neighbor in province.get("neighbors", ()) if neighbor in self.provinces
                           and ((key in self.water) == (neighbor in self.water)
                                or self.provinces[neighbor if key in self.water else key].get("is_coastal", False)))
                for key, province in self.provinces.items()
            }
            self.occupied = tuple(key for key, province in self.provinces.items() if province.get("units"))
            self.yields = {}
            self.production = queries.ProvinceProduction(self.nations, context)
        else:
            self.provinces = source.provinces
            self.water = source.water
            self.sea = source.sea
            self.owned_land = source.owned_land
            self.neighbors = source.neighbors
            self.occupied = source.occupied
            self.yields = source.yields
            self.production = source.production
        self.occupants = {}
        self.visible_units = {}
        self.estimated_output = {}
        self.estimated_production = None
        self.land_units = defaultdict(lambda: defaultdict(list))
        self.unit_data = {}
        self.networks = {}
        self.domestic_networks = {}
        self.accessible = {}
        self.country_enemies = {}
        self.allies = {}
        self.members = {}
        self.share_sources = {}
        self.route_projections = {}
        self.topologies = {}
        library = queries.get_unit_library(context)
        player_unit = getattr(session_for(context), "player_unit", None)
        for key in self.occupied:
            province = self.provinces[key]
            occupants = set()
            for unit in province.get("units", ()):
                if unit.get("health", 0) <= 0:
                    continue
                owner = queries.get_unit_combat_owner(unit)
                display_owner = unit.get("owner")
                if owner == "TACTICAL_HIDDEN" and unit is player_unit:
                    owner = display_owner = session_for(context).player_country
                if display_owner != visible_to and visible_to is not None:
                    if visible_provinces is not None and key not in visible_provinces:
                        continue
                    if not queries.is_unit_visible_to(unit, visible_to, province, self.nations):
                        continue
                occupants.add(owner)
                self.visible_units.setdefault(key, []).append(unit)
                unit_type = unit.get("type", "")
                stats = library.get(unit_type, {})
                base_stats = library.get(queries.get_base_unit_type(unit), stats)
                if (owner not in self.nations or key in self.water or stats.get("air_role")
                        or base_stats.get("air_role") or base_stats.get("naval_unit") or unit.get("naval_unit")
                        or unit_type.startswith("Convoy")):
                    continue
                identity = supply_unit_key(unit)
                existing = source.unit_data.get(identity) if source is not None else None
                if visible_provinces is not None and display_owner != visible_to:
                    demand = queries.get_unit_upkeep(base_stats, unit=unit)
                else:
                    demand = existing.demand if existing else queries.get_live_unit_upkeep(unit, library, self.nations)
                self.land_units[owner][key].append(identity)
                self.unit_data[identity] = SupplyUnit(unit, owner, display_owner, key, demand)
            if occupants:
                self.occupants[key] = occupants

    def province_output(self, key):
        if key not in self.yields:
            output = _resources()
            for amounts in self.production.breakdown(self.provinces[key]).values():
                _add_resources(output, amounts)
            self.yields[key] = output
        return self.yields[key]

    def _traversable(self, country):
        if country in self.accessible:
            return self.accessible[country]
        permitted = {country} | set(queries.friendly_nations_view(country, self.nations))
        permitted.update(owner for owner in self.nations if queries.has_military_access(country, owner, self.nations))
        enemies = self._enemies(country)
        permitted.difference_update(enemies, c.OWNERLESS_OWNERS)
        blocked = {key for key, occupants in self.occupants.items() if enemies & occupants}
        land = {key for owner in permitted for key in self.owned_land.get(owner, ())}
        self.accessible[country] = frozenset((land | self.sea) - blocked)
        return self.accessible[country]

    def _enemies(self, country):
        if country not in self.country_enemies:
            self.country_enemies[country] = set(queries.get_enemies(country, self.nations))
        return self.country_enemies[country]

    def _sharing_members(self, country):
        if not self.allies:
            links = {member: set() for member in self.nations}
            for recipient in self.nations:
                friendly = queries.friendly_nations_view(recipient, self.nations) & self.nations.keys()
                donors = {donor for donor in friendly - self._enemies(recipient) - {recipient}
                          if recipient not in self._enemies(donor)}
                self.allies[recipient] = donors
                for donor in donors:
                    links[recipient].add(donor)
                    links[donor].add(recipient)
            for start in links:
                if start in self.members:
                    continue
                group = {start}
                pending = [start]
                while pending:
                    new = links[pending.pop()] - group
                    group.update(new)
                    pending.extend(new)
                for member in group:
                    self.members[member] = tuple(sorted(group))
        return self.members.get(country, (country,))

    def _domestic_network(self, country):
        if country not in self.domestic_networks:
            self.domestic_networks[country] = self._build_network(country)
        return self.domestic_networks[country]

    def for_country(self, country):
        if country not in self.networks:
            members = self._sharing_members(country)
            networks = {member: self._domestic_network(member) for member in members}
            if len(members) > 1:
                self.share_sources[members] = self._sharing_sources(networks)
                networks = self._settle_supply(networks, self.share_sources[members])
            self.networks.update(networks)
        return self.networks[country]

    def _sharing_sources(self, networks):
        """Group donor output by the areas that can reach its producing tiles."""
        if len(networks) < 2:
            return {}
        sources = defaultdict(_resources)
        for donor, network in networks.items():
            recipients = [(member, recipient.province_area) for member, recipient in networks.items()
                          if donor in self.allies[member]]
            if not recipients:
                continue
            for tile, output in network.production_tiles.items():
                reachable = tuple((member, areas[tile]) for member, areas in recipients if tile in areas)
                if reachable:
                    _add_resources(sources[donor, network.province_area[tile], reachable], output)
        return sources

    def _allocate_allied_supply(self, networks, sources):
        additions = {member: defaultdict(_resources) for member in networks}
        for resource in c.ECON_RESOURCE_KEYS:
            remaining = {(member, area_id): area.demand[resource] - area.production[resource]
                         for member, network in networks.items() for area_id, area in network.areas.items()
                         if area.demand[resource] > area.production[resource]}
            if not remaining:
                continue
            pools = defaultdict(float)
            for (donor, area_id, reachable), output in sources.items():
                area = networks[donor].areas[area_id]
                gross = area.production[resource]
                spare = gross - area.demand[resource]
                if spare > 0 and output[resource] > 0:
                    recipients = tuple(recipient for recipient in reachable if recipient in remaining)
                    if recipients:
                        # Domestic upkeep reserves the same share of production at each source.
                        pools[recipients] += spare * (output[resource] / gross)
            for (member, area_id), amount in _divide_surplus(pools, remaining).items():
                additions[member][area_id][resource] = amount
        return {member: replace(network, allied_supply=additions[member]) for member, network in networks.items()}

    def _settle_supply(self, networks, sources):
        if not sources:
            return networks
        settled = self._allocate_allied_supply(networks, sources)
        receiving = {recipient for _, _, recipients in sources for recipient in recipients}
        for member, network in networks.items():
            for group, choices in network.contested.values():
                if not any((member, area_id) in receiving for area_id in choices):
                    continue
                current = settled[member]
                origin = current.unit_area[group[0]]
                best = settled
                best_score = self._group_supply_score(group, current.available(origin), current.areas[origin].demand)
                for destination in choices:
                    if destination == origin:
                        continue
                    moved = self._move_supply_group(current, group, origin, destination)
                    candidate = self._allocate_allied_supply({**settled, member: moved}, sources)
                    projected = candidate[member]
                    score = self._group_supply_score(group, projected.available(destination), projected.areas[destination].demand)
                    if score > best_score:
                        best = candidate
                        best_score = score
                settled = best
        return settled

    def _move_supply_group(self, network, group, origin, destination):
        areas = network.areas.copy()
        for area_id, direction in ((origin, -1), (destination, 1)):
            area = areas[area_id]
            demand = area.demand.copy()
            for identity in group:
                _add_resources(demand, self.unit_data[identity].demand, direction)
            areas[area_id] = replace(area, demand=demand)
        return replace(network, areas=areas, unit_area={**network.unit_area, **dict.fromkeys(group, destination)})

    def demand_projection(self, country, demand):
        """Forecast booked demand changes with the same allied allocation as the live network."""
        network = self.for_country(country)
        if all(area.demand == demand[area_id] for area_id, area in network.areas.items()):
            return network
        areas = {area_id: replace(area, demand=demand[area_id]) if area.demand != demand[area_id] else area
                 for area_id, area in network.areas.items()}
        members = self._sharing_members(country)
        sources = self.share_sources.get(members)
        if not sources:
            return replace(network, areas=areas)
        networks = {member: self.networks[member] for member in members}
        networks[country] = replace(network, areas=areas)
        return self._allocate_allied_supply(networks, sources)[country]

    def _route_projection(self, country, closed, opened):
        members = self._sharing_members(country)
        changes = {}
        for member in members:
            accessible = self._traversable(member)
            unavailable = closed.get(member, set())
            removed = unavailable & accessible
            added = opened.get(member, set()) - accessible - unavailable
            if removed or added:
                changes[member] = frozenset(removed), frozenset(added)
        if not changes:
            return self.for_country(country)
        key = members, tuple(changes.items())
        if key not in self.route_projections:
            networks = {member: self._domestic_network(member) for member in members}
            for member, (removed, added) in changes.items():
                networks[member] = self._build_network(member, (self._traversable(member) | added) - removed)
            settled = self._settle_supply(networks, self._sharing_sources(networks))
            if len(self.route_projections) >= _ROUTE_PROJECTION_LIMIT:
                del self.route_projections[next(iter(self.route_projections))]
            self.route_projections[key] = settled
        return self.route_projections[key][country]

    def land_projection(self, country, tile):
        return self._route_projection(country, {country: {tile}}, {})

    def sea_projection(self, country, *, block=(), reopen=(), blocker=None, departing=None):
        """Recalculate supply under hypothetical sea occupations or clearances."""
        blocked = self.sea.intersection(block)
        cleared = self.sea.intersection(reopen)
        if not blocked and not cleared and not departing:
            return self.for_country(country)
        members = self._sharing_members(country)
        closed = {country: blocked}
        opened = defaultdict(set)
        departing = departing or {}
        changes = cleared | (self.sea & departing.keys())
        enemies = self._enemies(country)
        for tile in changes:
            leaving = departing.get(tile, ())
            remaining = {queries.get_unit_combat_owner(unit) for unit in self.visible_units.get(tile, ()) if id(unit) not in leaving}
            if tile in cleared:
                remaining.difference_update(enemies)
            for member in members:
                if not remaining & self._enemies(member):
                    opened[member].add(tile)
        if blocker is not None:
            for member in members:
                if blocker in self._enemies(member):
                    closed[member] = closed[country]
        return self._route_projection(country, closed, opened)

    def _estimate_province_output(self, key):
        if key not in self.visible_provinces:
            return c.BASE_YIELDS
        if key not in self.estimated_output:
            if self.estimated_production is None:
                # Use visible province contents and default national multipliers.
                self.estimated_production = queries.ProvinceProduction({owner: {} for owner in self.nations}, self.production.context)
            output = _resources()
            for amounts in self.estimated_production.breakdown(self.provinces[key]).values():
                _add_resources(output, amounts)
            self.estimated_output[key] = output
        return self.estimated_output[key]

    def neighboring_areas(self, network, tile):
        """Supply areas reachable by one land or sea edge."""
        return {network.province_area[neighbor] for neighbor in self.neighbors.get(tile, ()) if neighbor in network.province_area}

    def _province_areas(self, accessible):
        if accessible in self.topologies:
            return self.topologies[accessible]
        province_area = {}
        anchors = []
        # Traverse each component once. A deterministic tile ID names the component.
        for start in sorted(accessible - self.sea):
            if start in province_area:
                continue
            anchors.append(start)
            province_area[start] = start
            queue = deque([start])
            while queue:
                key = queue.popleft()
                for neighbor in self.neighbors[key]:
                    if neighbor in accessible and neighbor not in province_area:
                        province_area[neighbor] = start
                        queue.append(neighbor)
        if len(self.topologies) >= _ROUTE_PROJECTION_LIMIT:
            del self.topologies[next(iter(self.topologies))]
        self.topologies[accessible] = province_area, anchors
        return province_area, anchors

    def _build_network(self, country, accessible=None):
        if accessible is None:
            accessible = self._traversable(country)
        province_area, anchors = self._province_areas(accessible)
        network = SupplyNetwork(province_area=province_area, areas={key: SupplyArea() for key in anchors})
        output = self._estimate_province_output if self.visible_provinces is not None and country != self.visible_to else self.province_output
        land_units = self.land_units.get(country, {})
        for key in self.owned_land.get(country, ()):
            if (area_id := province_area.get(key)) is not None:
                production = network.production_tiles[key] = output(key)
                _add_resources(network.areas[area_id].production, production)
        for key, identities in land_units.items():
            if (area_id := province_area.get(key)) is not None:
                for identity in identities:
                    network.unit_area[identity] = area_id
                    _add_resources(network.areas[area_id].demand, self.unit_data[identity].demand)

        # A contested group may draw from a neighboring area without joining
        # distinct networks through a hostile or contested tile.
        for key in sorted(land_units):
            if key in network.province_area:
                continue
            choices = self.neighboring_areas(network, key)
            if not choices:
                continue
            group = land_units[key]
            if len(choices) > 1:
                network.contested[key] = group, tuple(sorted(choices))
            extra = _resources()
            for identity in group:
                _add_resources(extra, self.unit_data[identity].demand)

            def score(area_id):
                area = network.areas[area_id]
                demand = {resource: area.demand[resource] + extra[resource] for resource in c.ECON_RESOURCE_KEYS}
                return self._group_supply_score(group, area.production, demand)

            best = max(sorted(choices), key=score)
            _add_resources(network.areas[best].demand, extra)
            network.unit_area.update(dict.fromkeys(group, best))
        return network

    def _group_supply_score(self, group, production, demand):
        readiness = 0.0
        speed = 0
        for identity in group:
            data = self.unit_data[identity]
            fractions = supply_fractions(production, demand, data.demand)
            readiness += supply_fraction(fractions, data.demand)
            speed += fuel_movement_speed(data.unit.get("speed", 1), fractions[2])
        return readiness, speed

    def fractions(self, unit, *, network=None):
        identity = supply_unit_key(unit)
        data = self.unit_data.get(identity)
        if data is None:
            return None
        demand = data.demand
        if network is None:
            network = self.for_country(data.country)
        area_id = network.unit_area.get(identity)
        return supply_fractions(network.available(area_id), network.areas[area_id].demand, demand) if area_id is not None else tuple(
            0.0 if demand[resource] else 1.0 for resource in c.ECON_RESOURCE_KEYS)

    def status(self, unit, *, network=None):
        fractions = self.fractions(unit, network=network)
        if fractions is None:
            return None
        return SupplyStatus.from_fractions(fractions, self.unit_data[supply_unit_key(unit)].demand)

    def player_summary(self, player):
        return {identity: self.fractions(data.unit) for identity, data in self.unit_data.items()
                if data.owner == player and isinstance(identity, str)}


@contextmanager
def combat_supply(supply):
    """Keep each phase's supply inputs scoped to that combat or forecast."""
    token = _COMBAT_SUPPLY.set(supply)
    try:
        yield
    finally:
        _COMBAT_SUPPLY.reset(token)


def unit_supply_multiplier(unit):
    # Tactical sub-units and simulated combat copies carry their parent's value.
    if "_supply_multiplier" in unit:
        return unit["_supply_multiplier"]
    supply = _COMBAT_SUPPLY.get()
    status = unit_supply_status(supply, unit)
    return status.readiness if status is not None else 1.0


def unit_movement_speed(unit, *, supply=None):
    """Campaign movement allowance from the same supply ratios as combat."""
    speed = unit.get("speed", c.DEFAULT_UNIT_SPD)
    if speed <= 1:
        return speed
    if supply is None:
        supply = _COMBAT_SUPPLY.get()
    status = unit_supply_status(supply, unit)
    return fuel_movement_speed(speed, status.fractions[2]) if status is not None else speed


def supply_combat_profile(unit):
    return dict(unit, _supply_multiplier=unit_supply_multiplier(unit))


def freeze_combat_supply(context):
    snapshot = SupplySnapshot(context)
    return {identity: snapshot.status(data.unit) for identity, data in snapshot.unit_data.items()}


def apply_supply_attrition(context):
    snapshot = SupplySnapshot(context)
    # Resolve all rates before changing upkeep demand through HP loss.
    losses = [(data, data.unit["health"] * _ATTRITION_RATE * (1.0 - snapshot.status(data.unit).readiness))
              for data in snapshot.unit_data.values()]
    for data, loss in losses:
        if loss > 0:
            queries.apply_unit_health_loss(data.unit, loss, tile=data.province)


def prepare_presentation_supply(context):
    """Resolve supply at a presentation boundary so drawing only reads values."""
    projection = getattr(context, "player_supply_projection", None)
    context._supply_presentation = {}
    context._movement_speed_presentation = {}
    if getattr(context, "is_editor", False):
        return
    if projection is not None:
        # The host sends per-resource coverage. The local upkeep rules supply the weights.
        world = world_for(context)
        library = queries.get_unit_library(context)
        units = {identity: unit for province in world.map_data.values() for unit in province.get("units", ())
                 if (identity := supply_unit_key(unit)) in projection}
        statuses = {identity: SupplyStatus.from_fractions(projection[identity], queries.get_live_unit_upkeep(unit, library, world.nation_data))
                    for identity, unit in units.items()}
    else:
        snapshot = SupplySnapshot(context)
        player = session_for(context).player_country
        scenario = world_for(context).scenario_settings
        can_see_all = (player not in snapshot.nations and player != c.TOURNAMENT_SPECTATOR
                       or not queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, scenario))
        statuses = {
            identity: snapshot.status(data.unit)
            for identity, data in snapshot.unit_data.items() if data.owner == player or can_see_all
        }
        units = {identity: snapshot.unit_data[identity].unit for identity in statuses}
    context._supply_presentation = statuses
    context._movement_speed_presentation = {identity: unit_movement_speed(unit, supply=statuses) for identity, unit in units.items()}


def presentation_supply(context):
    """The cached local view, or the host's private player projection."""
    return getattr(context, "_supply_presentation", None) or {}


def presentation_move_speed(context, unit):
    speeds = getattr(context, "_movement_speed_presentation", {})
    return speeds.get(supply_unit_key(unit), unit.get("speed", c.DEFAULT_UNIT_SPD))


def unit_supply_status(supply, unit):
    if supply is None:
        return None
    return supply.get(supply_unit_key(unit)) if isinstance(supply, dict) else supply.status(unit)


def normalize_supply_projection(value):
    """Read only complete unit ratios from a player snapshot."""
    if not isinstance(value, dict):
        return {}
    return {identity: tuple(ratios) for identity, ratios in value.items()
            if isinstance(identity, str) and isinstance(ratios, (list, tuple))
            and len(ratios) == len(c.ECON_RESOURCE_KEYS)
            and all(isinstance(ratio, (float, int)) and 0 <= ratio <= 1 for ratio in ratios)}
