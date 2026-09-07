# Greater Diplomacy Hex Edition to Greater Diplomacy 5 saves

GD5 imports a plain-text Greater Diplomacy Hex Edition save from **Translate
Maps → Greater Diplomacy Hex Edition**. It is a one-way import: GD5 creates a
new collision-safe folder under `saves/` and never changes the selected file.

## Generated maps

Hex Edition saves their own width, height, hex records, and army records. GD5
reads those dimensions from every save; the supplied 40 by 26 example is not a
required map size. Each saved hex becomes one GD5 province in a generated,
flat-top hex map. The importer preserves six-way adjacency, the land/water
layout, owner layout, and coastlines. Land becomes plains and water becomes
ocean because Hex Edition does not save land terrain types.

`P` becomes the playable **Player** nation and `E` becomes **Enemy**; they
start at war. Numeric nonzero owner colors become neutral countries named `Hex
Country <color>` and retain their source hue. The Hex Edition owner token `0`
becomes GD5's built-in **Unclaimed** land, with no core. Hex Edition does not
save country names, leaders, diplomacy, factions, or faction membership for
these owners.

## Converted state

- The source month counter becomes the 15th of the same GD5 month and year.
  Dates before GD5's configured `START_YEAR` are clamped to January 15 of
  that year (currently January 15, 1910).
- Player and Enemy Grain/Manpower, Oil, and Steel stockpiles become GD5
  manpower, fuel, and materials at 100 times their saved values.
- Per-hex Wheat, Oil, and Steel markers become GD5 Wheat, Oil, and Iron
  deposits at 100 each.
- Source factory levels become the matching GD5 `Factory Lvl <n>` building.
  Resource-bearing land with no source factory receives a `Basic Factory`, so
  it produces its converted resource immediately. Fort levels are preserved.
- Infantry, cavalry, motorized infantry, mechanized infantry, armored cars,
  and main battle tanks become their corresponding GD5 unit families. Current
  health percentage is retained.
- Destroyers become `Destroyer I`; Hex cruisers become `Dreadnought`, since
  GD5 has no cruiser class. Naval units remain on their generated ocean hex.

Time-appropriate GD5 research is assigned because Hex Edition does not save
research progress. The importer validates that the grid and army lists each
contain exactly `width × height` records and rejects malformed saves.

## Deliberately omitted data

Hex Edition AI and turn settings, capitals, dockyard markers, queues, and
unknown unit codes are not carried over. The import screen reports skipped
unsupported unit codes in its conversion notes.
