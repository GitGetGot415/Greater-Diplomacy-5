"""Save-dictionary builders and country-record compaction."""

import copy
import data.constants as c
from types import SimpleNamespace
from data.state_access import session_for, world_for
from map_logic.diplomacy import faction_records, diplomacy_lifecycle
from data.queries.content import get_research_years
from data.queries.nation_summary import get_shared_country_economy_summaries
from data import queries


def merge_country_templates(nation_data):
    """Restore catalog countries and add missing fields in place.

    Empty save records are references to the shared country catalog. Filling
    them in place preserves the saved iteration order, including custom IDs,
    and keeps catalog countries available unless a spectator explicitly deleted them.
    Copies keep live edits from changing the process-wide template cache.
    """
    deleted = nation_data.get("GLOBAL_EVENTS", {}).get("deleted_countries", [])
    for country in deleted:
        nation_data.pop(country, None)
    for country, template in queries.get_country_data().items():
        if country in deleted:
            continue
        if country not in nation_data:
            nation_data[country] = copy.deepcopy(template)
            continue
        current = nation_data[country]
        # SYNC FIX: Merge missing top-level and research keys from the base
        # template so old saves immediately get new fields and tech keys.
        for key, value in template.items():
            if key not in current:
                current[key] = copy.deepcopy(value)
        if "research" in template:
            research = current.setdefault("research", {})
            for key, value in template["research"].items():
                if key not in research:
                    research[key] = copy.deepcopy(value)
    return nation_data


def overlay_saved_province_data(map_data, saved_provinces):
    """Apply legacy or history province overlays to their map-data records."""
    malformed_resources = 0
    for json_key, saved_province in saved_provinces.items():
        province = map_data.get(json_key)
        if province is not None and saved_province:
            if not isinstance(saved_province, dict):
                continue
            # A pre-fix history snapshot could contain resource names as a
            # list: snapshot_history used a list copier on the resources dict.
            # Do not replace a valid current resource mapping with that known
            # malformed value.  There is no amount data to recover from it,
            # but preserving the current mapping avoids silent resource loss.
            overlay = copy.deepcopy(saved_province)
            resources = overlay.get("resources")
            if "resources" in overlay and not isinstance(resources, dict):
                malformed_resources += 1
                del overlay["resources"]
            province.update(overlay)
    if malformed_resources:
        print(f"[WARN] Ignored malformed saved resources in {malformed_resources} province overlay(s).")


def build_saved_province_data(data):
    """Build the mutable province fields shared by map and save serializers."""
    return {
        "owner": data["owner"],
        "cores": data.get("cores", []),
        "is_coastal": data.get("is_coastal", False),
        "units": data.get("units", []),
        "building_queue": data.get("building_queue", []),
        "unit_queue": data.get("unit_queue", []),
        "orders": data.get("orders", []),
        "resources": data.get("resources", {}),
        "buildings": data.get("buildings", []),
    }


def build_map_data_save(map_screen):
    """Return a self-contained map snapshot with current province state.

    Province state is stored in map_data.json for new saves. This makes the
    separate meta.json province overlay unnecessary while retaining the
    structural and unknown fields already attached to each live province.
    """
    world_state = world_for(map_screen)
    return {
        data["json_key"]: copy.deepcopy(data)
        for data in world_state.map_data.values()
    }


def build_map_geometry_save(raw_map_data, saved_provinces):
    """Keep map geometry without fields already stored in the province snapshot.

    Preserve unknown fields and provinces without a matching state record.
    The loader restores current state through overlay_saved_province_data.
    """
    return {
        key: {field: copy.deepcopy(value) for field, value in province.items()
              if field not in saved_provinces.get(key, {})}
        for key, province in raw_map_data.items()
    }


def map_data_with_saved_provinces(map_data, saved_provinces):
    """Return map geometry with a legacy province snapshot embedded in it."""
    result = copy.deepcopy(map_data)
    overlay_saved_province_data(result, saved_provinces)
    return result


# These optional bookkeeping fields have empty defaults at their readers.
# Do not generalize this to arbitrary empty values: an empty custom field may
# be an intentional override and must survive a save.
_EMPTY_COUNTRY_SAVE_FIELDS = {
    "pending_diplomacy": {},
    "relations": {},
    "diplo_responses": {},
    "military_attaches": [],
    "armies": [],
    "war_durations": {},
}


def _country_uses_only_template_defaults(country, template):
    """Whether restoring this record loses no authored or gameplay state."""
    if not isinstance(country, dict):
        return False
    for key, value in country.items():
        if key == "research" and isinstance(value, dict):
            # The loader already fills missing research keys. Preserve any
            # override or unknown technology, including an explicitly zero level.
            baseline = template.get(key, {})
            if any(tech not in baseline or level != baseline[tech]
                   for tech, level in value.items()):
                return False
        elif (key in ("flag_data", "portrait_data")
              and not template.get(key) and value in ("", "DEFAULT")):
            # _load_default_images resolves both to the same local/default asset.
            continue
        elif key in template:
            if value != template[key]:
                return False
        elif key not in _EMPTY_COUNTRY_SAVE_FIELDS or value != _EMPTY_COUNTRY_SAVE_FIELDS[key]:
            return False
    return True


def compact_nation_data(nation_data, *reference_blocks):
    """Replace unused, unmodified catalog records with empty template references.

    Keep every custom/modified record and the transitive country references in
    retained state, province data and metadata. Scanning dictionary keys too
    protects diplomacy tables and pre-war ownership maps. Unknown state is
    retained conservatively. Empty placeholders preserve iteration order (and
    thus AI/random/diplomacy ordering) without duplicating hundreds of templates.
    Live state and shared templates are never mutated.
    """
    templates = queries.get_country_data()
    candidates = {
        name for name, country in nation_data.items()
        if name in templates and name not in c.UNPLAYABLE_NATIONS
        and _country_uses_only_template_defaults(country, templates[name])
    }
    required = set(nation_data) - candidates
    pending = [nation_data[name] for name in required]
    pending.extend(reference_blocks)
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set)):
            pending.extend(value)
        elif isinstance(value, str) and value in nation_data and value not in required:
            required.add(value)
            pending.append(nation_data[value])
    return {name: country if name in required else {}
            for name, country in nation_data.items()}


def compact_save_nation_data(save_dict, map_data):
    """Compact a disk metadata payload, protecting all other saved fields."""
    references = {key: value for key, value in save_dict.items() if key != "nation_data"}
    save_dict["nation_data"] = compact_nation_data(
        save_dict["nation_data"], map_data, references)
    return save_dict


def build_save_dict(map_screen, *, include_provinces=True, compact_nations=False):
    """Standardize save state; only disk saves opt into country compaction.

    Network snapshots keep complete records for projection and authentication;
    they do not rely on the recipient having an identical country catalog.
    """
    world_state = world_for(map_screen)
    if hasattr(world_state, "factions"):
        faction_records.records_for(world_state)
    session_state = session_for(map_screen)
    from map_logic.system32 import unit_events
    diplomacy_lifecycle.normalize_diplomatic_records(world_state.nation_data)
    scenario_settings = world_state.scenario_settings or {}
    # Keep this setting explicit in every new save. Older base maps omit it,
    # but their effective default is OFF and that default should survive the
    # editor's copy/save path instead of disappearing from meta.json.
    scenario_settings.setdefault(
        "force_time_appropriate_research",
        c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH,
    )

    save_dict = {
        "version": c.GAME_VERSION,
        "generated_at": queries.datetime.now().isoformat(),
        "date": {
            "day": world_state.time_manager.day,
            "month": world_state.time_manager.month_index,
            "year": world_state.time_manager.year,
            "total_turns": world_state.time_manager.total_turns
        },
        "loop_map": world_state.loop_map,
        "player_country": session_state.player_country,
        "active_players": session_state.active_players,
        "current_player_index": session_state.current_player_index,
        "scenario_settings": scenario_settings,
        "script_variables": world_state.script_variables,
        "default_research": world_state.default_research,
        "research_years": get_research_years(context=map_screen),
        "nation_data": world_state.nation_data,
        "factions": copy.deepcopy(world_state.factions) if hasattr(world_state, "factions")
                    else faction_records.canonical_records(world_state.nation_data),
        "unit_event_log": unit_events.saved_log(map_screen),
        "unit_event_read_turns": unit_events.saved_reads(map_screen),
    }
    if include_provinces:
        save_dict["provinces"] = {}
    realtime_metadata = map_screen.realtime_match_metadata
    if isinstance(realtime_metadata, dict):
        # Additive metadata keeps the normal save/load format compatible with
        # old single-player and tournament files.
        save_dict["realtime_match"] = realtime_metadata
    
    if include_provinces:
        for data in world_state.map_data.values():
            save_dict["provinces"][data["json_key"]] = build_saved_province_data(data)
    if compact_nations:
        compact_save_nation_data(save_dict, world_state.map_data)
    return save_dict


def player_snapshot_projection(map_screen, snapshot, country_id):
    """Filter a network save before transmission, including raw map geometry."""
    world_state = world_for(map_screen)
    result = copy.deepcopy(snapshot)
    from map_logic.system32 import unit_events
    report = unit_events.normalize_log(result.get("unit_event_log"),
                                      result.get("date", {}).get("total_turns", 0))
    report["events"] = [row for row in report["events"] if row["owner"] == country_id]
    result["unit_event_log"] = report
    result["unit_event_read_turns"] = {
        owner: turn for owner, turn in result.get("unit_event_read_turns", {}).items()
        if owner == country_id and turn == report["turn"]}
    view = SimpleNamespace(player_country=country_id, map_data=world_state.map_data,
        nation_data=world_state.nation_data,
        id_to_province={p["id"]: p for p in world_state.map_data.values()},
        tactical_mode=False, player_unit=None)
    visible, _partial = queries.get_visible_provinces(view) if country_id in world_state.nation_data else (set(), set())
    fog = queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR,
                            world_state.scenario_settings)
    result["country_economy_summaries"] = get_shared_country_economy_summaries(
        country_id, world_state.map_data, world_state.nation_data, context=map_screen)
    private_fields = ("production_queue", "current_research", "research_queue", "research_progress",
        "research", "inbox", "pending_diplomacy", "diplo_responses", "diplo_draft_lists",
        "queued_ai_actions", "orders", "armies", "automation", "materials", "manpower", "fuel",
        "manpower_pool", "materials_pool", "fuel_pool")
    # New record fields must not bypass the established country visibility policy.
    result["factions"] = {
        identity: {key: copy.deepcopy(record[key])
                   for key in ("name", "leader", "members", "pre_war_borders") if key in record}
        for identity, record in result.get("factions", {}).items()}
    for cid, country in result.get("nation_data", {}).items():
        if cid != country_id and isinstance(country, dict):
            for field in private_fields:
                country.pop(field, None)
    by_key = {p["json_key"]: p for p in world_state.map_data.values()}
    for key, province in result.get("provinces", {}).items():
        original = by_key.get(key)
        if original is None:
            continue
        can_see = not fog or visible is None or original["id"] in visible
        province["units"] = [unit for unit in province.get("units", [])
            if unit.get("owner") == country_id or can_see and queries.is_unit_visible_to(
                unit, country_id, original, world_state.nation_data)]
        for unit in province["units"]:
            if unit.get("owner") != country_id:
                for field in ("order", "combat_stance", "lane_target", "repair_trip", "air_cargo"):
                    unit.pop(field, None)
        if original.get("owner") != country_id:
            for field in ("building_queue", "unit_queue", "orders"):
                province[field] = []
        if not can_see:
            province["resources"] = {}
            province["buildings"] = []
    for key, raw in result.get("_raw_map_data", {}).items():
        projected = result.get("provinces", {}).get(key)
        if projected is not None:
            for field in ("units", "building_queue", "unit_queue", "orders", "resources", "buildings"):
                raw[field] = copy.deepcopy(projected.get(field, []))
        else:
            raw["units"] = []
            raw["building_queue"] = raw["unit_queue"] = raw["orders"] = []
    result["player_country"] = country_id
    return result
