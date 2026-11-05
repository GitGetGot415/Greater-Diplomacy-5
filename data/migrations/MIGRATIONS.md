# How Updating Works

This file explains how a newer game opens data from an older Greater Diplomacy 5 (GD5) release.
"Migration" means this conversion.
This file is the primary guide. It has the full rules, the list of current conversion rules, and the procedure to add a rule.

For update checklists, see [the AI guide](update_ai.md) or [the human release guide](update_human.md).

Imports from Greater Diplomacy 4 (GD4) and Greater Diplomacy Hex Edition are not migrations.
Those are separate games. Their translation modules are in `map_logic/imports/`.

## The Goal

An older save must load and be playable in any later game.
Example: a v20 save opens in v40 and in every version after it.
Exact older values are less important. Statistics can change, and data that cannot convert can be dropped.

## Never Use Version Steps or a Chain

**Do not add version-numbered conversion steps. Do not make a chain of steps.**

A chain has one step for each release, such as `v47.py`, `v48.py`, and `v49.py`.
Each step converts data from the release before it. The version stamp selects the steps that run.
A save from many releases ago must then go through every step since its release.

This project does not use a chain, for these reasons:

- The project did not need one before. Older saves loaded because the loader converted older shapes when it found them.
- Each step expects the output of the step before it. One broken step stops every older save from loading.
- Each step uses the current game's helpers. A later change to a helper can break an old step without a change to the step.
  Shape-based rules also use current helpers, so the rules still need regression coverage.
- A chain grows with every release, and each release needs a new file and a new entry in a list.

Do not write per-version files. Do not add step lists such as `SAVE_STEPS` or `MOVE_STEPS`.

## Ownership

Keep all conversion of older GD5 data in the `data/migrations/` package. Its `__init__.py` lists each file.
Callers import names from the package: `from data import migrations`.

| File | Contents |
| --- | --- |
| `__init__.py` | The names that callers import. |
| `versions.py` | The version stamp, `upgrade_save`, and `upgrade_move`. |
| `conversions.py` | Every conversion rule for older saves and moves. |
| `validation.py` | Shared readers for known saved fields, including research containers. |
| `released_content.py` | Generated released names and historical equipment meanings used by runtime aliases and tests. |
| `research.py` | Research conversion by year, research level clamps, and the prerequisite grant. |
| `units.py` | Older unit names, categories, and metadata. |
| `settings.py` | Older settings names and mouse-button controls. |
| `repairs.py` | Load repairs for buildings, production orders, and faction rosters. |
| `tournament.py` | Older tournament projections and encrypted-file payloads. |
| `snapshot_moves.py` | The reader for snapshot moves, from v46 and every earlier release. See [Snapshot Moves](#snapshot-moves). |

Other modules own related data:

- Keep GD4 conversion rules in `map_logic/imports/gd4_translation.py`.
- Keep Greater Diplomacy Hex Edition conversion rules in `map_logic/imports/gdhex_translation.py`.
- Keep current settings fields, coercion, and serialization in `data/io/settings_schema.py`. Missing-setting defaults come from `data/json/starting_defaults.json`.
- Keep editable distribution preferences in `data/json/starting_defaults.json`. See `documentation/general_info.txt`, SETTINGS LOADING.
- Keep current gameplay rules and validation in their shared rule modules.
- Keep saved-file access, compression formats, and storage synchronization in their input and output modules.
- The `armies.py`, `units.py`, `saves.py`, and `air.py` modules in `data/queries/` own unit identities, unit statistics, province overlays, air order repair, and spawned-territory repair.
- `map_logic/diplomacy/diplomacy_lifecycle.py` owns request, response, and treaty identities.
- `map_logic/diplomacy/faction_records.py` owns faction record validation.
- `map_logic/diplomacy/deal.py` reads old peace text, old trade fields, and AI prose as deals.

## How Conversion Works

`conversions.py` holds every conversion rule for older formats.
Every rule runs on every load, whatever version wrote the file.

Each rule finds an older shape in the data and converts it to the current format.
Examples:

- A province has `deployment_queue`. The rule moves its entries into `unit_queue` and `building_queue`.
- A production entry has `days_remaining`. The rule replaces it with `turns_remaining`.
- A unit has an older name, such as `Infantry Type 1917`. The rule changes it to the current stage name.

A rule must do nothing to current data.
Then it is safe to run on every load, on a save from any version.
The rules run in one fixed order. A rule that uses the result of another rule comes after it.

`migrations.upgrade_save` refuses a newer save, runs `convert_save`, and stamps `GAME_VERSION`.
`convert_save` converts `meta.json` and `map_data.json`.

### One Rule Replaces Version Numbers

**Never reuse a saved field or identifier with a new meaning.**

A rule can only see the data. It cannot see which version wrote the data.
If a field keeps its name but changes its meaning, no rule can tell older data from current data.
Give the new meaning a new name. Or save the data that is necessary to read the older meaning.

`research_years` is an example.
Each save stores the stage years of the research tree that wrote it.
The loader compares these years with the active tree, so research converts without a version number.

## Current Conversion Rules

These rules convert formats from released versions up to v46.
They also keep support for older save formats that v46 accepted.

- Country records lose the obsolete `allied_with` field. Factions and subjects do not change.
- Country records lose `ai_commitments` and `summit_log`, which AI summits wrote until summits were removed.
  Relation modifiers that those commitments added stay until they expire.
  Country conversion and research repairs skip the `FACTION_WAR_MAPS` bookkeeping record.
- `deployment_queue` entries move into `unit_queue` and `building_queue`.
- Research projects without `points_remaining` receive points from their day countdown.
- Production entries with `days_remaining` receive `turns_remaining`. The day field has priority.
- Unnumbered recruitable units become level I in units, transports, queues, upgrade targets, custom production, and Spawn Unit actions.
- Older aircraft Trucks unpack on land or become Convoys at sea. Identity and health fraction do not change.
- Scripted events receive condition and action lists from their single fields.
- Inbox messages without `message_id` receive one.
- Release requests without `release_type` use Integrated.
- Older `ACCEPT_` and `REJECT_` entries move from `pending_diplomacy` to `diplo_responses`.
- Completed real-time saves without `offline_view` open as spectator replays.
- Older infantry, vehicle infantry, cavalry, militia, and artillery identifiers become named equipment stages.
- Unnumbered named equipment stages become level I, including vehicle infantry and heavy artillery.
- Units select the latest stage at or before their older equipment year.
- Transport names, aircraft cargo, production queues, upgrade targets, custom production lists, and scripted spawns use the same conversion.
- Map overlays, a selected history snapshot, and tournament move intents receive these conversions.
- Older tournament move formats convert to the snapshot move shape. See [Move Conversion Rules](#move-conversion-rules).
- Duplicate custom production entries combine when their older units become the same stage.

## What the Version Stamp Does

The game version is the save version.
`GAME_VERSION` in `data/constants.py` holds the version in development.
Set it to the new version when work on that version starts.
Then update the list of released names. See [Released Names](#released-names).

`version.txt` holds the last released version. Players download it to check for updates.
Only the owner changes `version.txt`, at release. Never change it during development.

Saves, tournament files, and move files record the version that wrote them:

| File | Field | Since |
| --- | --- | --- |
| Save (`meta.json`) | `version` | v15 |
| Tournament move | `game_version` | After v46 |

The stamp has three uses:

1. The game refuses a file from a newer version. The error tells the player to update the game.
   The load screen and the tournament loader show this error. The map loader also refuses the file.
2. Real-time messages carry `game_version`. Every player must have the host's version.
   The host tells a guest with a different version why the connection closed.
3. A tournament host approves a move whose stamp differs from the host's version, or has no stamp.

The stamp never selects conversion rules.

## Three Kinds of Conversion

| Kind | When it runs | What it fixes | Examples |
| --- | --- | --- | --- |
| Conversion rule | On every load, before the libraries are selected | An older shape: a field that changed meaning, moved, or changed shape | `conversions.py` |
| Library conversion | On every load, after the scenario selects its libraries | Saved data that does not agree with the active unit and research libraries | `migrate_infantry_research`, `clamp_research_levels`, `grant_research_prerequisites`, `queries.refresh_unit_stats` |
| Load repair | On every load | Current data that is not valid | `clamp_building_level`, `repair_faction_rosters` |

### Recovery and Input Validation

Getting an older save into a playable state takes priority over retaining every damaged value.
`validation.py` shares the readers used by conversion and research repairs.
For local saves and selected history, unreadable optional containers become empty containers.
Readable list entries, unknown extension fields, valid unit identities, paid orders, and their progress remain intact.
Numeric text is recovered when possible. Unreadable individual entries are dropped, invalid orders are canceled,
and missing production countdowns default to one remaining turn.
An order with no readable production target is dropped; conversion does not invent a refund for an unidentified order.
Repairs are logged and do not rewrite the original save files.

For example, `research_progress: null` becomes an empty mapping instead of preventing a load.
`current_research: null` and `default_research: null` remain valid empty states.
Local unit identity repair still replaces malformed or duplicate IDs.
Equipment levels and year lists retain the specific recovery rules below.
Unreadable world-file roots and files from newer game versions retain their existing errors.

Tournament commands are input from another player. Structural readers reject malformed submitted choices
before the host changes state; normal authentication, ownership, legality, session, turn, and duplicate checks remain mandatory.
A bad move produces a rejection and does not stop the importer from processing the next file.
Programming exceptions are not caught as input errors.
History remains lazy: research conversion repairs historical research fields, while ordinary snapshot fields convert only when selected.

### Library Conversions

A library conversion compares saved data with the active libraries.
A library edit changes its result. A library edit needs no new conversion rule.
A scenario can select different libraries. This conversion uses the libraries that the scenario selects.

- `migrate_infantry_research` compares saved research years with the active research tree.
  It converts every history snapshot too. See [History Snapshots](#history-snapshots).
- `clamp_research_levels` lowers a research level above the active maximum. The equipment tracks keep their levels.
  It removes queued projects, progress, and current research for a technology that the new maximum completes.
  This includes a saved level already equal to the active maximum.
- `grant_research_prerequisites` gives countries the prerequisite levels of technologies they already have.
  Older saves have technologies whose prerequisites were added later.
  Without them a country cannot research further levels of what it owns.
  The grant uses the active research tree. It covers live countries, default research, and snapshot moves.
  Equipment tracks are not changed, and no prerequisite uses them.
- `queries.refresh_unit_stats` copies unit statistics from the active unit library.

`clamp_research_levels` and `grant_research_prerequisites` change only live state.
They run after a selected history turn becomes live state.

Unit statistics are an example.
Each load copies attack, defense, speed, and maximum health from the active unit library.
Health keeps its fraction of maximum health.
Example: a unit has 50 of 100 health. The library now gives 120 maximum health. The unit gets 60 health.

### Load Repairs

A load repair fixes data that the current rules do not allow. Load repairs are not migrations.
The clamps in `repairs.py` and `research.py` are load repairs. They share the package but are not conversion rules.
Example: a building level outside its family's range moves to the nearest level in the active library.

No load repair removes a unit whose type is not in the unit library.
That unit stays, and it keeps its saved statistics. Only units of disabled families are removed.
Thus a conversion rule must give each released unit name a current name.

## Research and Units by Year

The equipment tracks are infantry, cavalry, militia, and artillery.
Their stages have years. Conversion uses these years, not stage numbers.

### Research

Equipment research saves include `research_years` for the four tracks.
`data/queries/saves.py` copies these public year lists from the active research library when it builds a save.

On load, `migrate_infantry_research` does these steps for each track:

1. Find the year of the last completed stage in the saved `research_years`.
2. Count the stages in the active tree at or before that year.
3. Set that count as the new level.

Example with artificial years:
the active tree has stages for 1914 and 1918.
A country completed a 1917 stage in an older release.
The country now has the 1914 stage.
A country that completed a 1918 stage now has the 1918 stage.

History, default research, paused projects, and active project points keep their meaning.
Unfinished research points apply to the next stage.
A queued project is removed when its track is already complete.
An older unfinished first project receives its earlier equipment stages before that project continues.
An unresearched track without a pending project stays unresearched.
A save without `research_years` uses `LEGACY_INFANTRY_RESEARCH_YEARS` in `research.py`.

Tournament snapshots, older move projections, real-time snapshots, and imports use the same research-year representation.

### Units

A conversion rule changes older unit names to current stage names.
Example: `Infantry Type 1917` becomes the latest infantry stage at or before 1917.
`equipment_stage_aliases` in `units.py` makes this table from the default unit library.
Conversion runs before the scenario selects its libraries, so it cannot use the active library.

The rule converts units, transport cargo, production queues, upgrade targets, custom production lists, and scripted spawns.
Held volunteer units use the same conversion.
Conversion follows these known fields in saves, selected history, and moves. It leaves unknown fields and their contents intact.
When a new saved location holds a unit reference, include that location in the conversion.
The stat refresh then gives each unit its new statistics. Health keeps its fraction.

`released_content.EQUIPMENT` records each released equipment identifier's family, research track, and year.
`scripts/data/write_released_content.py` derives these descriptions from committed release libraries.
Explicit metadata supplies the meaning; libraries without metadata use the supported older naming rules.
`equipment_stage_aliases` compares these recorded years with the current default library.
Newly recorded equipment names therefore need no hand-written year ranges or aliases when the family still exists.
The original v46 family/date rules remain as a supplement for names that older loaders accepted even when no release library listed them.
Non-year renames and missing or renamed families still need explicit compatibility rules.
The generator refuses conflicting historical equipment meanings instead of guessing.

Some renames do not use years. Examples are `Piston Fighter` and `WW1 Tank`.
`LEGACY_UNIT_NAMES` in `units.py` lists them.

### Older Family Names in Unit Metadata

Unit metadata keeps the family names of older releases.
`data/generators/recipes.py` writes them from the prefix of each equipment line.
Example: `Trench Infantry I` has `family` `Infantry Type` and `settings_family` `Infantry`.

Two parts of the game read these names:

- `equipment_stage_aliases` finds the stages of an older family through `family`.
  Example: it finds the current stages for `Infantry Type 1917` in the `Infantry Type` family.
- Scenario settings use `settings_family` as their key. `get_base_item_name` reads it.
  The keys are in `unit_disabled`, `unit_turn_overrides`, and `unit_range_overrides`.
  Buildings use their family as the key in `building_disabled` and `building_turn_overrides`.

No conversion rule changes these settings keys.
Do not rename `family` or `settings_family` to match a player-facing name.
If a rename is necessary, add a conversion rule for the settings keys.
Also keep each older family in `equipment_stage_aliases`.
`ReleasedContentTests` fails when a released family no longer selects content.

## Opening an Older Save

`load_map_assets` in `data/map/load_map.py` does these steps:

1. `read_save_files` reads `meta.json`, `map_data.json`, and the turn history.
2. `upgrade_save` refuses a newer save. It then runs every conversion rule on `meta.json` and `map_data.json`, and stamps the current version.
   `upgrade_history_turn` converts the selected history turn, if there is one.
3. Scenario settings select the active libraries.
4. `migrate_infantry_research` converts research levels to the active research tree, in all history too.
5. A selected history turn replaces the current country and province state.
   `clamp_research_levels` then lowers levels above the active maximum.
   `grant_research_prerequisites` then gives countries the prerequisites of technologies they have.
6. Country templates fill empty catalog records and missing fields.
7. Province repairs drop units of disabled families and buildings that the active library does not contain.
   A unit whose type is not in the library stays. See [Load Repairs](#load-repairs).
   A numbered building level outside its family range moves to the nearest level in the active library.
   Example: "Factory Lvl 50" becomes the highest Factory level. `migrations.clamp_building_level` does this.
   Queued building orders follow the same rule (`migrations.clamp_building_queue`). A paid order keeps its progress and refund.
   Gaps in the library's levels select the nearest existing level. Equal distances select the lower level.
   A snapshot move receives the same clamp, so its queue matches the host's queue.
   A building with no family in the library is still dropped.
8. `refresh_unit_stats` copies unit statistics from the active unit library. Health keeps its fraction of maximum health.
9. Faction roster repair removes members that cannot be in their faction.
   It occurs before faction pre-war maps are initialized.

Saves without a `factions` block convert their country faction fields through `repair_faction_rosters`.

### History Snapshots

The loader does not convert every history snapshot.
Only a selected history turn becomes live game state, so only that snapshot converts.
`migrations.upgrade_history_turn` converts that one snapshot when a player selects it.
The other snapshots stay in their saved format. The rules convert them if a player selects them later.
Do not convert every snapshot on load. On a large save with a long history, that adds several seconds to each load.

`migrate_infantry_research` is the exception. A save has one `research_years` list for all snapshots.
That function changes the list, so it must convert the levels in every snapshot at the same time.
If the list changed without the snapshots, their levels would be read against the wrong years.

### Broken Research Data

Equipment levels and year lists have specific recovery rules:

- An unreadable equipment level reads as the nearest whole level, or 0.
- A malformed year list cannot tell what its levels mean, so those levels stay as they are.
- A missing year list uses the original GD5 dates in `LEGACY_INFANTRY_RESEARCH_YEARS`.

Malformed local research objects and progress mappings become empty mappings.
Unreadable queued projects are dropped, while readable projects and paused progress are retained.
Research conversion and both research load repairs use the same recovery readers.

The loader does not write the save during conversion.
The next save writes the current format.
After the load, gameplay, user interface (UI), and AI code read only the current format.

## Older Identifiers and Fields

Settings accept `api_key` as `gemini_api_key` and `ollama_api_key` as `ollama_base_url`.
They accept `music_speed` and `sfx_speed` as `music_pitch` and `sfx_pitch`.
`LING` becomes `OPENROUTER`. `ling_api_key` and `ling_model` become `openrouter_api_key` and `openrouter_model`.
Writers use current names. Positional settings slots do not change.

Library loading converts `AEROSPACE` to `AIR` and `Aerospace` to `Air`.
Older unnumbered unit library keys convert to their canonical level-I identifiers.
Current keys take priority if a library contains both names. Unknown valid entry fields remain intact.
Research IDs stay unchanged in saves and multiplayer files.
Equipment unit IDs use stage names. Older IDs convert through the conversion rules.

## Scenario Information

`WorldState.scenario_metadata` owns optional Author and Description text.
The shared save builder writes `scenario_metadata` to `meta.json`, saves, and multiplayer snapshots.
The loader supplies empty text when an older file omits this optional field.
This additive field does not change an older field's meaning or require a conversion rule.
Scenario information remains the same when a selected history turn becomes live state.
Only local map editors can change it. Multiplayer commands cannot change it.

`SessionState.editor_scenario_name` is an editor draft. It is not saved in scenario data.
The loader derives the name from the selected folder.
`screens/editors/menus.py` owns save confirmation dialogs.
`data/map/save_map.py` validates folders and writes scenario files.

## Unit Event Report Compatibility

Each new damage entry can include `detail_parts` with text fragments and identified units' recorded owners.
Saves, tournament exports, and real-time snapshots retain these fragments.
`unit_events.normalize_log` validates the fragments and preserves the original details text.
Old reports without `detail_parts` keep plain text for other units until the next completed turn.
Their main unit still has its recorded owner's flag.
Existing Unknown unit entries cannot recover identities omitted by older recording rules.

## Unit Metadata

Unit libraries contain explicit identity and requirement metadata.
Queries read this metadata without parsing the unit identifier.
`legacy_unit_metadata` infers metadata from a name. It serves names that are not library entries and libraries without metadata.
Explicit metadata takes priority. Invalid explicit fields produce errors that identify the unit and field.
Unknown valid metadata fields remain intact.
`get_unit_unlock_requirement` retains its older three-field result as a compatibility adapter.
Runtime unlock checks use `get_unit_requirements` for explicit compound requirements.
Add new units in `data/generators/recipes.py`. The Tkinter unit editor changes only the statistics of existing units.
See `documentation/general_info.txt` for metadata ownership and cache invalidation.

## Diplomatic Record Identities

Requests remain in each country's `pending_diplomacy` channel.
Responses remain in `diplo_responses`. They do not gain request travel counters.

Each new request receives `request_id` without consuming gameplay randomness.
Responses refer to the request they answer.
`normalize_diplomatic_records` gives requests without `request_id` reproducible identities from their content and country pair.
It runs on load, on save, and during turn processing.
Repeat normalization preserves identity, timing, escrow, and unknown fields.
An unmatched older response retains its explicit `legacy_unmatched` marker.
Current network input cannot use that marker to establish authority.

Ratification rounds use `treaty_id`. Member answers refer to their current round.
Older active rounds receive reproducible identities. Human waiting periods and immediate AI answers remain unchanged.
Saves, history, tournament files, and real-time snapshots retain these fields in their existing country-owned channels.
Private real-time channels remain filtered before transmission.

All tournament production queues use shared legality, cost, and aggregate budget checks.
Missing queue fields receive defaults from the shared constructor.
Existing paid entries retain progress. Explicit timing and refund differences retain host review.
Authentication, session checks, turn checks, and duplicate checks apply before host state changes.

Diplomacy commands validate supplied response references against host-owned requests.
The input adapter binds omitted references to matching current requests.
An omitted reference cannot identify a replaced request. Explicit stale references remain invalid.
A client-supplied identity never proves ownership or permission.

## Faction Records and Runtime Rules

`WorldState` owns the optional `factions` mapping. Stable faction IDs are its keys.
Each record contains name, leader, ordered members, and `pre_war_borders`.
Unknown valid record fields survive loading and disk saves.
Country faction fields and `FACTION_WAR_MAPS` are derived compatibility projections.
Valid canonical records take precedence over those projections.
Malformed record structures produce validation errors. Existing leader repair still selects missing successors after loading territory.
Older data without `factions` uses `faction_records.canonical_records` after the roster-repair pass.
Legacy identity conversion is reproducible. New identities do not consume gameplay randomness.
World saves, history, and multiplayer snapshots retain these identities.
Selected historical turns replace faction records together with country data.
Real-time recipient projection removes unknown private faction fields.

`scenario_settings` remains the saved rule source. Runtime libraries and indexes are reconstructed instead of serialized.
No-context library access reads defaults. Active gameplay passes its explicit world context.

## Tournament Moves

Moves convert like saves. A move from any older release converts. No release is the oldest supported move.
Conversion uses the rules in `conversions.py`. No file converts one version to another.
Only a move from a newer version is refused.

### Two Move Formats

A move file has one of two formats:

- An **intent move** holds `player_intents`, a list of player choices.
  Examples are "give unit X this order" and "this province's unit queue holds these items".
  The host checks each choice against its own state.
  Health, resources, and research progress always come from the host.
  Releases after v46 write intent moves.
- A **snapshot move** has no `player_intents`. It holds a copy of the player's state at export.
  The copy has the country record, the queues of the player's provinces, and the player's ground units with their statistics.
  The host checks the copy against its own state. It then puts the copy in place of its records for that country.
  v46 and every earlier release wrote snapshot moves.

An intent move also holds the snapshot sections: `nation_data`, `provinces`, `aircraft_orders`, `air_transport`, and `release_subjects`.
The host only compares these sections with the intents. Only the intents change game state.

### How the Host Loads a Move

`load_move_files` in `data/multiplayer/tournament/files.py` does these steps:

1. `move_version` reads `game_version`. It refuses a move from a newer version.
   This rejection cannot be overridden. It tells the player to update the game.
2. A move whose stamp differs from the host's version, or has no stamp, stops with a "version" override.
   The rejection does not change host state.
3. The host selects Convert or Reject.
4. `upgrade_move` runs every conversion rule on the move, whatever version wrote it.
   Malformed containers encountered during conversion produce a normal rejection before host state changes.
5. The converted move passes every normal check, including session, turn, faction, permission, and duplicate checks.
6. An intent move goes through the shared validation in `PlayerActions`.
7. A snapshot move goes to `snapshot_moves.py`.
   When its statistics differ from the host's state, the host gets a "stats" override.

A move with the host's version needs no host question. The rules still run, and do nothing.

### Move Conversion Rules

`convert_move` in `conversions.py` converts moves.
Each rule finds an older shape and does nothing to current data. The version stamp never selects a rule.

These rules convert older move formats:

- A move without `nation_data`, `provinces`, and `player_intents` holds only a country record. The oldest moves have this shape.
  The rule moves the record into `nation_data` and adds empty `provinces`.
  The fields in `MOVE_FIELDS`, such as `tournament_turn`, stay at the top of the move.
- A move without `release_subjects` takes them from the country's `release_puppet_queue`.
  If the country record has no queue, the host keeps its own queue.
- A move without `aircraft_orders` holds whole aircraft records in its provinces.
  The rule copies only the order and the name of each aircraft. The host keeps its own aircraft statistics and positions.
- A move without `unit_snapshot` replaces the country's units only when it lists provinces. This keeps the earlier behavior.

`convert_move` also applies the country, province, and unit rules for saves to the move's records.
See [Current Conversion Rules](#current-conversion-rules).

Some older shapes need host state, so the snapshot reader converts them:

- A move without `tournament_session` or `tournament_turn` skips those checks. The summary counts it as `legacy`.
- A move without `faction_renames` can rename a faction through its leader's record.
  The host accepts this only when the country is still the faction leader.

### Why Moves Have a Separate Entry Point

Saves and moves use the same rules.
In `conversions.py`, `convert_save` and `convert_move` call the same country, province, and unit functions.
The entry points are different because the files are different:

- A save holds the whole world and its history. A move holds one country and the provinces that it changed.
- A move has no terrain data. Host validation checks each converted unit against the host's state.
- A save belongs to the player who opens it. A move is input from another player.
  The host must approve the conversion, and the move must pass all normal checks.

### Intent Moves

Intent moves use the shared real-time domain commands.
The host validates the complete draft before applying its choices.
Ground units use identity and order intents. Omitted unit records cannot create or destroy units through this path.
Unchanged paid orders preserve progress and payment. Combined production and repair costs use one affordability check.
Cancellation refunds become available before the combined payment is collected.
A complete intent draft is rejected when one of its choices is not valid.

`tournament_player_intents` in `tournament.py` compares the snapshot sections with the intents.
Conflicting unit, cargo, production, research, army, or appearance choices are rejected.

### Snapshot Moves

`data/migrations/snapshot_moves.py` reads every snapshot move.
It is the reader for a file format, not for one version.
The conversion rules bring every older snapshot to one shape before the reader gets it.
A later release does not need a new reader or a new file. It adds rules to `conversions.py`.

A snapshot cannot become a list of intents through a change of field names.
A snapshot holds results, such as unit statistics and paid queue entries.
The intent path matches paid queue entries exactly and ignores submitted statistics.
Thus snapshot moves keep their own reader and host review.

The reader does these steps:

1. It converts the move's research levels to the active research tree by year.
   It then applies `clamp_research_levels` and `grant_research_prerequisites`.
2. It clamps building queues as the host's own load did, so the queues match.
3. It gives the move's ground units the statistics of the active unit library, as the host's load did.
   Health keeps its fraction. Thus a library change gives no warning, and accepted units do not bring older statistics into the game.
4. It validates releases, administrative orders, production, aircraft orders, cargo, and units against host state.
   Differences in statistics, timing, or refunds become warnings for the "stats" override.
5. It drops a new production order that the current rules refuse. The drop is a warning for the same override.
   An older release can allow an order that the current rules refuse.
   The country record gets back the payment of each dropped order, as a cancellation does.
   A foreign order, or a move over its budget, is still rejected.
6. `legacy_player_country` in `tournament.py` prepares the country record.
   The host keeps its faction fields, policy timers, travelling requests, and treaty rounds.
   Invalid diplomatic drafts are discarded. Other choices in the move are kept.
7. It applies the move. It replaces the country record, applies faction renames, appearance, siphon, and cargo changes, and applies aircraft orders.
   When `unit_snapshot` is true, it replaces the country's ground units with the move's units.

Review acceptance re-reads and revalidates the file. Real-time clients cannot request these overrides.
Units without IDs are kept. They cannot be compared with host units, so they give no warnings.
Held volunteer units in the country record keep their statistics until the next load refreshes them.

### Removing Snapshot Support

Keep snapshot support while players can have snapshot moves. Remove it only when the user asks.
To remove it, do these steps:

1. Delete `snapshot_moves.py` and its branch in `load_move_files`.
   Make `load_move_files` refuse a move without `player_intents`.
2. Remove the snapshot sections from `export_move_file`, and the conflict checks from `tournament_player_intents`.
3. Remove the older move format rules from `convert_move`. Keep the country, province, and unit rules.

### Other Owners

The move adapters keep session checks, turn checks, duplicate detection, and submission replacement.
Tournament encryption, fog policy, file downloads, and storage synchronization stay with the tournament input and output module.
The real-time adapter keeps server authority, identity checks, recipient filtering, submission locks, and network limits.

## Released Names

A release is a version that players received. Only released data needs conversion rules.
`version.txt` names the last release. Its Git history gives each release.

### Find a Release

1. Run `git log --format="%h %s" -- version.txt`.
   The newest commit with a stamp, such as `v46`, is that release.
2. Ignore test edits. They have stamps above the current release, such as `v999`, or stamps such as `v15a`.
3. Read a release file with `git show <commit>:data/json/unit_data.json`.
4. To get a full copy of a release, use `git archive <commit>` into a separate folder.
   Do not use `git checkout` or `git stash`. See `AGENTS.md`.

### The List of Released Names

`data/migrations/released_content.py` lists the names that releases wrote into saves.
It holds unit and building identifiers, scenario-settings family keys, and historical equipment descriptions.
Runtime aliases and tests import this generated inventory directly.
`scripts/data/write_released_content.py` writes the inventory from every release in the `version.txt` history.
An unreadable, empty, or malformed release library stops generation before the existing list is overwritten.
Generation requires full Git history. On a shallow clone, run `git fetch --unshallow` first.
The generator also refuses missing releases, changed recorded release commits, and removal of any previously listed name or family.
It also refuses removal or changed meanings of recorded equipment descriptions.
It keeps the existing inventory when a check fails.

`ReleasedContentTests` in `tests/test_data_migrations.py` checks each name:

- Released units and buildings pass through save conversion and resolve to current library entries.
  Buildings also pass through the normal province repair.
- Released settings families pass through save conversion and still select units or buildings.
  Disabled families and their production and range overrides keep the same family key and values.
- The release in `version.txt` is in the list.

A rename, a removed unit, or a lower level count can make this test fail.
Do not remove the name from the list. Add an alias or a conversion rule.

When `GAME_VERSION` changes to the next version, do these steps:

1. Make sure that the release commit is committed. The script reads only committed history.
2. Run `python scripts/data/write_released_content.py`.
3. Run `ReleasedContentTests`. Add aliases for names that fail.

## Adding a Conversion Rule

### Which Kind of Change Do I Need?

Use these rules when a change affects data from a released version:

- An additive field with a default that keeps old behavior needs no rule.
- Statistics and costs need no rule. Library conversions and the stat refresh adapt to them.
  Research levels and stage years adapt through the saved research years and library clamps.
  Reducing unit levels or changing stage names can remove released unit identifiers.
  Add conversions for every removed released identifier; unknown unit types retain their saved statistics.
  Building level reductions use the existing clamp only while their family still exists.
- A renamed unit, building, or setting needs an alias in this package.
  A renamed unit family or settings family also needs this. See [Older Family Names in Unit Metadata](#older-family-names-in-unit-metadata).
- A field that changes meaning, moves, or changes shape needs a conversion rule in `conversions.py`.
  Give the changed field a new name.
- Invalid data that the rules now prevent needs a load repair.

Never add a version-numbered step, a per-version file, or a list of steps.
Include only identifiers and formats that existed in supported released data.
To find out if a name was released, see [Released Names](#released-names).
Do not add rules for content introduced and changed only during development of the next release.
Keep existing rules. Remove a rule only when the user asks to drop support for that older format.

### Procedure

1. Give a changed meaning a new field or identifier name. Do not reuse the older name.
2. Add the rule to `data/migrations/conversions.py`. Put it after any rule whose result it uses.
3. Make the rule find the older shape and do nothing to current data.
4. Convert country records, province records, and `meta.json` fields.
   Make `convert_history_turn` apply the rule to a selected history snapshot too.
   If move files contain the changed data, make `convert_move` apply the rule too.
5. Change gameplay code to read only the new format. Remove any read-time adapter for the old format.
6. Preserve unknown valid fields and references held by other modules.
7. Add the rule to [Current Conversion Rules](#current-conversion-rules) in this guide.
8. Test older data, current data, and a save/load round trip.
9. Test affected multiplayer validation and player modes.
10. Run `tests/test_data_migrations.py`. It loads every built-in map and checks that current saves do not change.
    It also checks that every released name still converts.
11. Optional: run `scripts/maps/upgrade_shipped_maps.py` to write the built-in maps in the current format.

## Tests and Tools

- `tests/test_data_migrations.py` tests the conversion rules.
  It also loads every built-in map and checks that the rules do not change a current save.
  The map loads use the default scenario settings, not the local `data/json/scenario_settings.json`.
  `ReleasedContentTests` checks the names in `data/migrations/released_content.py`.
  The pull request workflow runs this module together with the equipment and tournament migration tests.
- `scripts/data/write_released_content.py` writes `data/migrations/released_content.py`. See [Released Names](#released-names).
- Write test fixtures as Python modules, not JSON files.
  `.gitignore` ignores `*.json` outside a few folders, so a JSON fixture in `tests/` is not committed.
- `tests/test_tournament_moves.py` tests move conversion and host review.
- `tests/test_historical_infantry.py` tests the equipment tracks.
- Tests that replace `CURRENT_VERSION` replace it in `data.migrations.versions`.
- `scripts/maps/upgrade_shipped_maps.py` writes the built-in maps in the current format.
  This is optional. Built-in maps convert on every load.
