# Recipe tables

This guide applies to recipe tables in `recipes.py`.

## Requirements

- Keep each recipe row on one line.
- Keep tuple values in the same order as the table's column mapping.
- Put each comma directly after its value. Add spaces after commas to align the next column.
- Do not use commas as visual separators in table header comments. Use spaces and align each label with its data column.
- Keep the header labels in the same order as the tuple fields.
- When a field is added or removed, update every row and its column mapping together.
- Keep row formatting changes separate from gameplay or tuning changes.

## Unit and building rows

Each row starts with its first year and name. Its base statistics follow the matching column mapping.
The `UPGRADES` tuple contains `(levels, years between levels, per-level statistic increases)`.
The level count includes the first entry. Omitted statistics keep their base values.
Use full JSON field names in the increases dictionary.

`EQUIPMENT_STAGES` contains the named infantry equipment stages.
`LAND_UNIT_RECIPES`, `NAVAL_UNIT_RECIPES`, and `AIR_UNIT_RECIPES` contain the other unit stages.
`BUILDING_RECIPES` groups the stages of each building chain.
Read current tuning in these tables and the generated libraries. The example below uses artificial values.

## Unit example

```python
#YR    NAME            HP   ATK DEF SPD MAT MAN FUEL TIME BOMB UPGRADES                     OPTIONS
(1900, "Example Ship", 100, 20, 3,  1,  40, 50, 0,   2,   None, (3, 5, {"health": 10}), {})
```

This row produces three Roman-numbered unit tiers. Each later tier adds the specified health increase.
Research uses the same first year, interval, and level count.

Every recruitable unit has a numbered identifier, including a family with one level.
Older identifiers convert through the shared save and move migrations.
Generated `metadata.display_name` omits the suffix when the family has only one level.
Use `queries.get_unit_display_name` for labels. Use `queries.unit_picker_items` when a picker returns a unit identifier.

Use an inline `piecewise(...)` base value when a statistic has different growth segments.
Do not also put that statistic in the increases dictionary.
Aircraft use the same base columns, followed by their aircraft fields.

## Building chains

Each inner list in `BUILDING_RECIPES` is one building chain.
Rows remain in construction order. Each entry requires the previous building in that chain.
The `numbered: False` option emits an unnumbered base building.
The `req` option sets a row's first prerequisite. Later levels still require the previous building.

Keep the literal `"null"` string distinct from `None` where existing data requires it.

The level count includes every numbered entry in that row.
A numbered first building appears once. It does not need a separate base recipe.
A `None` year marks a building without its own research track.

## Research rows

The first column of `RESEARCH_RECIPES` contains research dates.
`equipment_years`, `unit_years`, and `building_years` read those dates from their owning stage rows.
Do not repeat these dates or level counts in research rows.
Technologies without unit or building stages keep their dates directly in `RESEARCH_RECIPES`.
The generator derives each research level count from its dates.
Each generated unit tier has a matching research level.

Research categories, costs, prerequisites, names, level gates, and output bonuses remain in `RESEARCH_RECIPES`.
Shared vehicle infantry and heavy artillery rules still derive their variants from regular equipment stages.

## Regenerate the libraries

1. Edit the owning stage row or research-only row.
2. Run `python data/generators/generate_data.py`.
3. Run `python data/generators/generate_data.py --check` to check agreement.

The game reads the generated files in `data/json/`. It does not read these recipe tables during play.
During a refactor, compare all three generated libraries with their previous contents.
Report each intended gameplay change separately.
