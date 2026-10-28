# Import Greater Diplomacy 4 saves

Greater Diplomacy 5 (GD5) imports standard Greater Diplomacy 4 (GD4) saves.
Use **Translate Maps ? Greater Diplomacy 4**.

The importer creates a new folder under `saves/` without overwriting an existing folder.
It does not change the GD4 source file.
Open the new save from **Load Game**.

## Supported inputs

The importer accepts two TurboWarp save formats:

- LZ-String `Base64` text.
- The same save decompressed to text.

It checks the GD4 divider (`?`, U+239A) and the standard map structure.
That structure has 458 countries and 564 provinces.
Older saves with fewer than 65 sections or shorter lists can load with conversion notes.
Missing fields use neutral country or province data.
A missing date uses GD5's default start year.

The importer rejects non-GD4 text and malformed required JSON.
Custom-map records convert only when they match the standard GD4 ordering.

## Map conversion

Each import starts from GD5's bundled `GD4` base map.
`map_logic/gd4_translation.py` owns the country-code and province mapping tables.
They map 547 Earth province indices.
GD5 does not represent GD4's 17 moon records.
The normal loader rebuilds the political overlay when the new save opens.

Some GD4 provinces cover several GD5 tiles.
Ownership and a core also copy to these companion tiles:

| GD5 mapped tile | GD5 companion tiles |
| --- | --- |
| 746 | 756, 761 |
| 704 | 728 |
| 611 | 617 |
| 57 | 7 |

Companion tiles keep their own buildings, resources, and units unless they also have a direct GD4 mapping.
Direct mappings take priority.
GD4 province 132 maps to GD5 tile 7.
GD4 province 283 maps to GD5 tile 45.

## Country and province data

The importer preserves supported country names, leader names and titles, ownership, factories, and forts.
It converts Iron, Coal, Oil, and Wheat.
Multiply each GD4 resource amount by 50 and round it to an integer.
Forts become `Fort Lvl N`.
Valid wars become two-way GD5 wars.

GD4 friendship data does not convert.
Imports start without GD5 alliances, factions, subjects, or shared map visibility.

Countries with a GD5 equivalent keep their established GD5-map colors.
Other countries use an RGB conversion of their GD4 color-wheel value and brightness.
The source ranges are 0?200 for color and -100?100 for brightness.

GD4 uses `TRO` for territory owned by The Rot.
If The Rot's separate country record exists, those tiles import as The Rot instead of Unclaimed.

Factory levels represent both industry and recruitment capacity:

| GD4 level | GD5 buildings |
| --- | --- |
| 0 | None |
| 1 | Basic Factory |
| 2 | Basic Factory and Basic Recruitment Center |
| 3 | Basic Factory and Recruitment Building Lvl 1 |
| 4?8 | Factory Lvl `level - 3` and Recruitment Building Lvl `level - 2` |

## Date, player, research, and troops

GD4 stores time as `year * 12 + zero-based month`.
The imported date uses the 15th of that month.
It starts with `total_turns` at 0 and 30-day turns.
Dates before GD5's start year become January 15 of that year, with a conversion note.
Later dates keep their month.

GD5 applies research appropriate to the imported year.
Partial GD4 research does not convert.

The selected GD4 country becomes the GD5 player country.
`Spectator` saves remain Spectator saves.
If an older save has no valid selected country, it becomes a Spectator save.

Troops convert to `Infantry Type <imported year>`.
The troop-to-unit conversion factor determines complete units and the health fraction of any remaining unit.
See the conversion logic in `map_logic/gd4_translation.py` for that factor.
If the exact infantry year is unavailable, the importer uses the nearest supported year.

## Data that does not convert

The importer omits:

- Money and partial research.
- Passive-income, fort, and naval research.
- Friendship and alliance state.
- Naval units and connections.
- Devastation and production queues.
- Artillery targets and mail.
- Flags, portraits, and GD4 color effects.
- Moon records and unsupported provinces.

Destination country colors and base-map resource balances come from GD5's existing GD4 map.

## Maintain the importer

The decoder and save-data builder do not depend on the UI.
Tests can run without opening the game.

If the standard TurboWarp map changes:

1. Update `GD4_COUNTRY_CODES` and `GD4_PROVINCE_TO_GD5` from the new source data.
2. Update the related tests.
3. Keep country and province count checks consistent with those tables.

Do not accept an arbitrary custom map as the standard map.
Its indices could refer to different territories.
