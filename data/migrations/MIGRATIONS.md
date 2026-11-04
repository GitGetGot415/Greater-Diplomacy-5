# How Updating Works

This file explains how a newer game opens data from an older Greater Diplomacy 5 (GD5) release.
"Migration" means this conversion.

`documentation/data_migrations.txt` is the primary guide.
It has the full rules, the list of current conversion rules, and the procedure to add a rule.
This file gives an overview of the process.

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
- A chain grows with every release, and each release needs a new file and a new entry in a list.

Do not write per-version files. Do not add step lists such as `SAVE_STEPS` or `MOVE_STEPS`.

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

### One Rule Replaces Version Numbers

**Never reuse a saved field or identifier with a new meaning.**

A rule can only see the data. It cannot see which version wrote the data.
If a field keeps its name but changes its meaning, no rule can tell older data from current data.
Give the new meaning a new name. Or save the data that is necessary to read the older meaning.

`research_years` is an example.
Each save stores the stage years of the research tree that wrote it.
The loader compares these years with the active tree, so research converts without a version number.

## What the Version Stamp Does

The game version is `GAME_VERSION` in `data/constants.py`.
Never edit `version.txt`. It names the last release, and players download it to check for updates.

Each file records the version that wrote it:

| File | Field |
| --- | --- |
| Save (`meta.json`) | `version` |
| Tournament move | `game_version` |

The stamp has three uses:

1. The game refuses a file from a newer version. The error tells the player to update the game.
2. Real-time players must have the host's version.
3. A tournament host approves a move whose stamp differs from the host's version, or has no stamp.

The stamp never selects conversion rules.

## Three Kinds of Conversion

| Kind | When it runs | What it fixes | Examples |
| --- | --- | --- | --- |
| Conversion rule | On every load, before the libraries are selected | An older shape: a field that changed meaning, moved, or changed shape | `conversions.py` |
| Library conversion | On every load, after the scenario selects its libraries | Saved data that does not agree with the active unit and research libraries | `migrate_infantry_research`, `clamp_research_levels`, `grant_research_prerequisites`, `queries.refresh_unit_stats` |
| Load repair | On every load | Current data that is not valid | `clamp_building_level`, `repair_faction_rosters` |

### Library Conversions

A library conversion compares saved data with the active libraries.
A library edit changes its result. A library edit needs no new conversion rule.
A scenario can select different libraries. This conversion uses the libraries that the scenario selects.

Unit statistics are an example.
Each load copies attack, defense, speed, and maximum health from the active unit library.
Health keeps its fraction of maximum health.
Example: a unit has 50 of 100 health. The library now gives 120 maximum health. The unit gets 60 health.

### Load Repairs

A load repair fixes data that the current rules do not allow.
Example: a building level outside its family's range moves to the nearest level in the active library.

## Research and Units by Year

The equipment tracks are infantry, cavalry, militia, and artillery.
Their stages have years. Conversion uses these years, not stage numbers.

### Research

On load, `migrate_infantry_research` does these steps for each track:

1. Find the year of the last completed stage in the saved `research_years`.
2. Count the stages in the active tree at or before that year.
3. Set that count as the new level.

Example with artificial years:
the active tree has stages for 1914 and 1918.
A country completed a 1917 stage in an older release.
The country now has the 1914 stage.
A country that completed a 1918 stage now has the 1918 stage.

Unfinished research points apply to the next stage.
A queued project is removed when its track is already complete.
A save without `research_years` uses `LEGACY_INFANTRY_RESEARCH_YEARS` in `research.py`.

### Units

A conversion rule changes older unit names to current stage names.
Example: `Infantry Type 1917` becomes the latest active infantry stage at or before 1917.
`equipment_stage_aliases` in `units.py` makes this table from the active unit library.

The rule converts units, transport cargo, production queues, upgrade targets, custom production lists, and scripted spawns.
The stat refresh then gives each unit its new statistics. Health keeps its fraction.

The list of older names in `equipment_stage_aliases` describes v46 names.
Saves do not record the year of each unit name.
Thus a later rename of stages needs new entries in that table.

Some renames do not use years. Examples are `Piston Fighter` and `WW1 Tank`.
`LEGACY_UNIT_NAMES` in `units.py` lists them.

## Opening an Older Save

`load_map_assets` in `data/map/load_map.py` does these steps:

1. `read_save_files` reads `meta.json`, `map_data.json`, and the turn history.
2. `upgrade_save` refuses a newer save. It then runs every conversion rule and stamps the current version.
   `upgrade_history_turn` converts the selected history turn, if there is one.
3. Scenario settings select the active libraries.
4. `migrate_infantry_research` converts research levels, in all history too.
5. A selected history turn replaces the current country and province state.
   `clamp_research_levels` and `grant_research_prerequisites` then repair the live research.
6. Country records load. Province repairs drop or clamp content that the active libraries do not contain.
7. `refresh_unit_stats` copies unit statistics from the active library.
8. Faction repair removes members that cannot be in their faction.

### History Snapshots

The loader does not convert every history snapshot.
Only a selected history turn becomes live game state, so only that snapshot converts.
The other snapshots stay in their saved format. The rules convert them if a player selects them later.
Conversion of every snapshot added several seconds to each load of a large save.

`migrate_infantry_research` is the exception. A save has one `research_years` list for all snapshots.
That function changes the list, so it must convert the levels in every snapshot at the same time.

### Broken Research Data

Broken research data does not stop a load:

- An unreadable equipment level reads as the nearest whole level, or 0.
- A malformed year list cannot tell what its levels mean, so those levels stay as they are.
- A missing year list uses the original GD5 dates in `LEGACY_INFANTRY_RESEARCH_YEARS`.

The loader does not write the save during conversion.
The next save writes the current format.
After the load, gameplay, user interface (UI), and AI code read only the current format.

## Opening an Older Tournament Move

`load_move_files` in `data/multiplayer/tournament/files.py` does these steps:

1. `move_version` reads `game_version`. It refuses a move from a newer version.
2. A move whose stamp differs from the host's version, or has no stamp, stops with a "version" override.
   Host state does not change.
3. The host selects Convert or Reject.
4. `upgrade_move` runs every conversion rule on the move. It refuses an unstamped move from before v46.
5. The converted move passes the normal session, turn, faction, and duplicate checks.
6. A move with `player_intents` goes through the shared validation in `PlayerActions`.
7. A v46 move has no `player_intents`. `v46_moves.py` reads it instead.
   When its statistics differ from the host's state, the host gets a "stats" override.

A move with the host's version needs no host question. The rules still run, and do nothing.

### Why Moves Have a Separate Entry Point

Saves and moves use the same rules.
In `conversions.py`, `convert_save` and `convert_move` call the same country, province, and unit functions.
The entry points are different because the files are different:

- A save holds the whole world and its history. A move holds one country and the provinces that it changed.
- A move has no terrain data. Host validation checks each converted unit against the host's state.
- A save belongs to the player who opens it. A move is input from another player.
  The host must approve the conversion, and the move must pass all normal checks.
- A save from any version converts. An unstamped move without the v46 sections is from before v46, and is refused.

`v46_moves.py` reads v46 moves.
A v46 move is a snapshot of the country's state. A current move is a list of commands.
A change of field names cannot make a snapshot into commands, so v46 moves need their own reader.
Keep this module while v46 moves convert. Remove it only when the user asks to stop v46 move support.

## Which Kind of Change Do I Need?

Use these rules when a change affects data from a released version:

- An additive field with a default that keeps old behavior needs no rule.
- A change to library content needs no rule. Library conversions and the stat refresh adapt to it.
  Examples are statistics, costs, level counts, and stage years.
- A renamed unit, building, or setting needs an alias in this package.
- A field that changes meaning, moves, or changes shape needs a conversion rule in `conversions.py`.
  Give the changed field a new name.
- Invalid data that the rules now prevent needs a load repair.

Include only identifiers and formats from released data.
Do not add rules for content that changed only during development of the next release.

To add a rule, follow `documentation/data_migrations.txt`, ADDING A CONVERSION RULE.

## Files

| File | Contents |
| --- | --- |
| `__init__.py` | The names that callers import. Callers use `from data import migrations`. |
| `versions.py` | The version stamp, `upgrade_save`, and `upgrade_move`. |
| `conversions.py` | Every conversion rule for older saves and moves. |
| `research.py` | Research conversion by year, research level clamps, and the prerequisite grant. |
| `units.py` | Older unit names, categories, and metadata. |
| `settings.py` | Older settings names and mouse-button controls. |
| `repairs.py` | Load repairs for buildings, production orders, and faction rosters. |
| `tournament.py` | Older tournament projections and encrypted-file payloads. |
| `v46_moves.py` | The reader for v46 move files. |

## Tests and Tools

- `tests/test_data_migrations.py` tests the conversion rules.
  It also loads every built-in map and checks that the rules do not change a current save.
- `tests/test_tournament_moves.py` tests move conversion and host review.
- `tests/test_historical_infantry.py` tests the equipment tracks.
- `scripts/maps/upgrade_shipped_maps.py` writes the built-in maps in the current format.
  This is optional. Built-in maps convert on every load.
