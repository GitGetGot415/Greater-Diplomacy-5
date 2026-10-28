# Import Greater Diplomacy Hex Edition saves

Greater Diplomacy 5 (GD5) imports plain-text Greater Diplomacy Hex Edition saves.
Use **Translate Maps ? Greater Diplomacy Hex Edition**.

The importer creates a new folder under `saves/` without overwriting an existing folder.
It does not change the selected source file.

## Generated map

Each save supplies its own width, height, hex records, and army records.
The supplied 40 by 26 example does not set a required map size.

Each hex becomes one GD5 province in a generated flat-top hex map.
The importer preserves six-way adjacency, land and water, ownership, and coastlines.
Land becomes plains. Water becomes ocean.
Hex Edition does not save land terrain types.

`P` becomes **Player**, and `E` becomes **Enemy**.
They start at war.
Owner token `0` becomes **Unclaimed** land without a core.

Hex Edition does not save country names, leaders, diplomacy, factions, or membership for these owners.
A built-in mapping identifies known numeric country codes:

Switzerland, Sweden, Turkey, Iran, Iraq, Afghanistan, Portugal, Italy,
Ireland, Belgium, the Netherlands, Germany, Poland, Denmark, Norway, Finland,
Estonia, Latvia, Lithuania, Belarus, Russia, Ukraine, Kazakhstan, Georgia,
Armenia, Azerbaijan, Saudi Arabia, Pakistan, Egypt, Libya, Tunisia, Algeria,
Morocco, Romania, Bulgaria, Greece, Yugoslavia, Austria, Czechia, Slovakia,
Hungary, the United Kingdom, France, Spain, Syria, Lebanon, Israel, Palestine,
Kuwait, Turkmenistan, and Uzbekistan.

Each other numeric owner gets a random unused playable GD5 country identity for that import.

## State conversion

- The source month counter becomes the 15th of the same month and year.
  Dates before `START_YEAR` become January 15 of that year.
- Player and Enemy Grain/Manpower, Oil, and Steel become manpower, fuel, and materials.
  Multiply stockpiles by 100.
- Per-hex Wheat, Oil, and Steel markers become Wheat, Oil, and Iron deposits of 100 each.
- Factory levels become matching `Factory Lvl <n>` buildings.
  Resource-bearing land without a source factory gets a `Basic Factory`.
  Fort levels are preserved.
- Infantry, cavalry, motorized infantry, mechanized infantry, armored cars, and main battle tanks use corresponding GD5 unit families.
  Each unit keeps its health percentage.
- Destroyers become `Destroyer I`.
  Cruisers become `Dreadnought`, because GD5 has no cruiser class.
  Naval units stay on their generated ocean hex.

GD5 applies research appropriate to the imported date.
Hex Edition does not save research progress.

Grid and army lists must each contain exactly `width ? height` records.
The importer rejects malformed saves.

## Data that does not convert

The importer omits AI settings, turn settings, capitals, dockyard markers, queues, and unknown unit codes.
The import screen reports skipped unit codes in its conversion notes.
