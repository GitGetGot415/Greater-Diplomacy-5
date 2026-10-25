"""Resolve scenario rules and active content for one world."""

import copy
from dataclasses import dataclass, field

import data.constants as c


class ActiveLibrary(dict):
    """Carry the explicit rule context through existing library-based interfaces."""

    def __init__(self, runtime):
        super().__init__()
        self.runtime_rules = runtime


@dataclass
class RuntimeRules:
    libraries: dict = field(default_factory=dict)
    disabled_tech_keys: set = field(default_factory=set)
    indexes: dict = field(default_factory=dict)
    revision: int = 0

    def rebuild(self, settings, defaults):
        """Replace derived content in place. Saved settings remain authoritative."""
        from data import queries

        active = {name: copy.deepcopy(dict(library)) for name, library in defaults.items()}
        units = active['unit_library']
        buildings = active['building_library']
        tree = active['tech_tree']
        queries.apply_unit_range_overrides(units, settings)
        for library, key, time_key in (
                (units, 'unit_turn_overrides', 'production_time'),
                (buildings, 'building_turn_overrides', 'time')):
            for name, stats in library.items():
                family = queries.get_base_item_name(name)
                if family in settings.get(key, {}):
                    stats[time_key] = settings[key][family]
        disabled = set()
        for library, key in ((units, 'unit_disabled'), (buildings, 'building_disabled')):
            for name in list(library):
                if queries.get_base_item_name(name) not in settings.get(key, []):
                    continue
                tech = (queries.get_unit_research_requirement(name, library)[0]
                        if library is units else queries.get_building_required_tech(name)[0])
                if tech:
                    disabled.add(tech)
                del library[name]
        for key in disabled:
            tree.pop(key, None)
        if disabled:
            for stats in tree.values():
                stats['req'] = queries.strip_disabled_tech_requirements(stats.get('req', {}), disabled)
        for name, library in active.items():
            destination = self.libraries.setdefault(name, ActiveLibrary(self))
            destination.clear()
            destination.update(library)
        self.disabled_tech_keys = disabled
        self.indexes.clear()
        self.revision += 1


def for_world(context):
    """Initialize world content lazily, including supported flat backend contexts."""
    from data import queries
    from data.state_access import world_for

    world = world_for(context)
    # Flat contexts predate WorldState and do not declare a runtime owner.
    runtime = getattr(world, 'runtime_rules', None)
    if runtime is None:
        runtime = RuntimeRules()
        world.runtime_rules = runtime
    if not runtime.libraries:
        runtime.rebuild(getattr(world, "scenario_settings", {}), {
            name: queries._load_cached_json(name)
            for name in ('unit_library', 'building_library', 'tech_tree')})
    return runtime


def rebuild(context, *, reload_defaults=False):
    """Reconstruct one world's content after loading, editing, or snapshot replacement."""
    from data import queries
    from data.state_access import world_for

    runtime = for_world(context)
    defaults = {name: queries._load_cached_json(name, reload=reload_defaults)
                for name in ('unit_library', 'building_library', 'tech_tree')}
    runtime.rebuild(world_for(context).scenario_settings, defaults)
    return runtime


def flag(context, name, default=False):
    from data import queries
    from data.state_access import world_for
    return queries.get_scenario_flag(name, default, world_for(context).scenario_settings)


def value(context, name, default, cast=float):
    from data.state_access import world_for
    raw = world_for(context).scenario_settings.get(name, default)
    try:
        return cast(raw)
    except (ValueError, TypeError):
        return default
