"""Shared state queries, rule helpers, caches, and the save-dictionary builder.

This package replaces the former single module `data/queries.py`. It re-exports the public names
of each submodule, so callers keep writing `queries.get_unit_library(...)`.
A new public name needs no entry here. Do not use a public name in two submodules.
Add a private name below only when a caller outside its submodule reads it through this package.
The submodules are layered. A module imports only from modules earlier in this list:

    content         Cached game content and settings: JSON cache, libraries, scenario flags, settings, keybinds, music choices, and historical leader timelines.
    geometry        Province geometry and map/screen coordinate helpers.
    diplomacy       Diplomatic status: wars, military access, truces, and pending message state.
    factions        Faction and alliance membership, leadership, friendly-nation lookups, and pre-war snapshots.
    countries       Which countries exist, who plays them, and what a viewer can see of them.
    unit_info       What a unit type is: names, groups, research requirements, tiers, and aircraft classification.
    combat_state    Where combat is taking place and which units a nation can see.
    movement_access Whether a unit class may enter a tile, before path-finding.
    units           Unit instances: stats refresh, owner changes, health loss, bombardment, and view filters.
    air             Aircraft rules: missions, ranges, transport cargo, air drops, and ground-combat interaction.
    tech            Technology and research queries, unit unlock lookups, and research-edit previews.
    economy         Resources, costs, production output, administrative actions, and economy projections.
    forts           Fort levels, fort defense bonuses, and fort damage.
    movement        Unit move steps, path-finding, tactical speed and fuel, and air move orders.
    strength        Military and economic strength, attacker ranking, and combat predictions.
    armies          Army groups, army symbols, defense-area orders, unit creation, and air-drop recovery.
    relations       Relation scores, temporary modifiers, reachability, and the AI checks for war and peace.
    nation_summary  Per-country summaries and shared-economy views.
    saves           Save-dictionary builders and country-record compaction.
    images          Flag and portrait image encoding, decoding, and caching.
    files           ZIP extraction, research-project construction, and country appearance helpers.
    editor          Map editor paint regions and undo/redo state.

Patch seams: tests and a few callers rebind a name on this package, for example
`mock.patch.object(queries, "get_unit_library", ...)`. A submodule must see that rebind,
so it reads those names as `queries.NAME` instead of importing them.
Add a name to that rule when a new test patches it on `queries` and another query calls it.

UI, AI, and rule modules import queries. Load those callers inside helpers to avoid cycles and screen
initialization. NumPy stays local to pixel-geometry helpers, which backend state can omit.
"""

from data.state_access import world_for
import os
import random
import subprocess
import sys
from data.platform import IS_WEB
from data.platform import downloads_dir
from data.platform import sync_persisted_dir
from data.platform import download_file
from datetime import datetime
import pygame
from data.migrations import normalize_cached_json_names
from data.migrations import normalize_air_category

from data.queries.content import *
from data.queries.geometry import *
from data.queries.diplomacy import *
from data.queries.factions import *
from data.queries.countries import *
from data.queries.unit_info import *
from data.queries.combat_state import *
from data.queries.movement_access import *
from data.queries.units import *
from data.queries.air import *
from data.queries.tech import *
from data.queries.economy import *
from data.queries.forts import *
from data.queries.movement import *
from data.queries.strength import *
from data.queries.armies import *
from data.queries.relations import *
from data.queries.nation_summary import *
from data.queries.saves import *
from data.queries.images import *
from data.queries.files import *
from data.queries.editor import *

# Star imports omit private names.
from data.queries.content import _JSON_CACHE, _load_cached_json
