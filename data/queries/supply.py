"""Connected province production and land division supply."""

from collections import defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import data.constants as c
from data import queries
from data.state_access import session_for, world_for


_COMBAT_SUPPLY = ContextVar("combat_supply", default=None)
_ATTRITION_RATE = 0.10


def _resources():
    return dict.fromkeys(c.ECON_RESOURCE_KEYS, 0.0)


def _add_resources(total, amounts, scale=1):
    for resource in c.ECON_RESOURCE_KEYS:
        total[resource] += amounts[resource] * scale


def supply_fractions(production, demand, unit_demand):
    return tuple(min(1.0, max(0.0, production[resource] / demand[resource]))
                 if unit_demand[resource] > 0 and demand[resource] > 0 else 1.0
                 for resource in c.ECON_RESOURCE_KEYS)


def supply_fraction(fractions):
    return sum(fractions) / len(c.ECON_RESOURCE_KEYS)


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
        self.visible_provinces = visible_provinces
        if source is None:
            self.provinces = {province["id"]: province for province in world.map_data.values() if "id" in province}
            self.water = {key for key, province in self.provinces.items() if queries.is_water_province(province)}
            self.sea = {key for key in self.water if self.provinces[key].get("terrain") in c.OCEAN_TERRAINS}
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
            self.neighbors = source.neighbors
            self.occupied = source.occupied
            self.yields = source.yields
            self.production = source.production
        self.occupants = {}
        self.land_units = defaultdict(lambda: defaultdict(list))
        self.unit_data = {}
        self.networks = {}
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
                unit_type = unit.get("type", "")
                stats = library.get(unit_type, {})
                base_stats = library.get(queries.get_base_unit_type(unit), stats)
                if (owner not in self.nations or key in self.water or stats.get("air_role")
                        or base_stats.get("air_role") or base_stats.get("naval_unit") or unit.get("naval_unit")
                        or unit_type.startswith("Convoy")):
                    continue
                identity = supply_unit_key(unit)
                existing = source.unit_data.get(identity) if source is not None else None
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
        permitted = {country} | set(queries.friendly_nations_view(country, self.nations))
        permitted.update(owner for owner in self.nations if queries.has_military_access(country, owner, self.nations))
        enemies = set(queries.get_enemies(country, self.nations))
        permitted.difference_update(enemies, c.OWNERLESS_OWNERS)
        blocked = {key for key, occupants in self.occupants.items() if enemies & occupants}
        land = {key for key, province in self.provinces.items() if key not in self.water and province.get("owner") in permitted}
        return (land | self.sea) - blocked

    def for_country(self, country):
        if country not in self.networks:
            self.networks[country] = self._build_network(country)
        return self.networks[country]

    def _build_network(self, country):
        network = SupplyNetwork()
        accessible = self._traversable(country)
        land_units = self.land_units.get(country, {})
        # Traverse each component once. A deterministic tile ID names the component.
        for start in sorted(accessible - self.sea):
            if start in network.province_area:
                continue
            area = network.areas[start] = SupplyArea()
            network.province_area[start] = start
            queue = deque([start])
            while queue:
                key = queue.popleft()
                if key not in self.water and self.provinces[key].get("owner") == country:
                    _add_resources(area.production, self.province_output(key))
                for identity in land_units.get(key, ()):
                    network.unit_area[identity] = start
                    _add_resources(area.demand, self.unit_data[identity].demand)
                for neighbor in self.neighbors[key]:
                    if neighbor in accessible and neighbor not in network.province_area:
                        network.province_area[neighbor] = start
                        queue.append(neighbor)

        # A contested group may draw from a neighboring area without joining
        # distinct networks through a hostile or contested tile.
        for key in sorted(land_units):
            if key in network.province_area:
                continue
            choices = {network.province_area[neighbor] for neighbor in self.neighbors[key]
                       if neighbor not in self.water and neighbor in network.province_area}
            if not choices:
                continue
            group = land_units[key]
            extra = _resources()
            for identity in group:
                _add_resources(extra, self.unit_data[identity].demand)

            def score(area_id):
                area = network.areas[area_id]
                demand = {resource: area.demand[resource] + extra[resource] for resource in c.ECON_RESOURCE_KEYS}
                return sum(supply_fraction(supply_fractions(area.production, demand, self.unit_data[identity].demand))
                           for identity in group)

            best = max(sorted(choices), key=score)
            _add_resources(network.areas[best].demand, extra)
            network.unit_area.update(dict.fromkeys(group, best))
        return network

    def fractions(self, unit):
        identity = supply_unit_key(unit)
        data = self.unit_data.get(identity)
        if data is None:
            return None
        demand = data.demand
        network = self.for_country(data.country)
        area = network.areas.get(network.unit_area.get(identity))
        return supply_fractions(area.production, area.demand, demand) if area else tuple(
            0.0 if demand[resource] else 1.0 for resource in c.ECON_RESOURCE_KEYS)

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
    fractions = unit_supply_details(supply, unit) if supply is not None else None
    return supply_fraction(fractions) if fractions is not None else 1.0


def supply_combat_profile(unit):
    return dict(unit, _supply_multiplier=unit_supply_multiplier(unit))


def freeze_combat_supply(context):
    snapshot = SupplySnapshot(context)
    return {identity: snapshot.fractions(data.unit) for identity, data in snapshot.unit_data.items()}


def apply_supply_attrition(context):
    snapshot = SupplySnapshot(context)
    # Resolve all rates before changing upkeep demand through HP loss.
    losses = [(data, data.unit["health"] * _ATTRITION_RATE * (1.0 - supply_fraction(snapshot.fractions(data.unit))))
              for data in snapshot.unit_data.values()]
    for data, loss in losses:
        if loss > 0:
            queries.apply_unit_health_loss(data.unit, loss, tile=data.province)


def prepare_presentation_supply(context):
    """Resolve supply at a presentation boundary so drawing only reads values."""
    projection = getattr(context, "player_supply_projection", None)
    if projection is not None or getattr(context, "is_editor", False):
        return
    snapshot = SupplySnapshot(context)
    player = session_for(context).player_country
    scenario = world_for(context).scenario_settings
    can_see_all = (player not in snapshot.nations and player != c.TOURNAMENT_SPECTATOR
                   or not queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, scenario))
    context._supply_presentation = {
        identity: snapshot.fractions(data.unit)
        for identity, data in snapshot.unit_data.items() if data.owner == player or can_see_all
    }


def presentation_supply(context):
    """The cached local view, or the host's private player projection."""
    projection = getattr(context, "player_supply_projection", None)
    return projection if projection is not None else getattr(context, "_supply_presentation", None) or {}


def unit_supply_details(supply, unit):
    return supply.get(supply_unit_key(unit)) if isinstance(supply, dict) else supply.fractions(unit)


def normalize_supply_projection(value):
    """Read only complete unit ratios from a player snapshot."""
    if not isinstance(value, dict):
        return {}
    return {identity: tuple(ratios) for identity, ratios in value.items()
            if isinstance(identity, str) and isinstance(ratios, (list, tuple))
            and len(ratios) == len(c.ECON_RESOURCE_KEYS)
            and all(isinstance(ratio, (float, int)) and 0 <= ratio <= 1 for ratio in ratios)}
