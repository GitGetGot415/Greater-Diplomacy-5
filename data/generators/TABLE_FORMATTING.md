# Recipe table formatting

This guide applies to recipe tables in `recipes.py`.

## Requirements

- Keep each recipe row on one line.
- Keep tuple values in the same order as the table's column mapping.
- Put each comma directly after its value. Add spaces after commas to align the next column.
- Do not use commas as visual separators in table header comments. Use spaces and align each label with its data column.
- Keep the header labels in the same order as the tuple fields.
- When a field is added or removed, update every row and its column mapping together.
- Keep row formatting changes separate from gameplay or tuning changes.

## Example

```python
#NAME    TIERS      HP
("Tank", rs(4),     lin(100, 10)),
```

In this example each comma stays next to the preceding value. Spaces after commas align the next value with its column. The header has no comma separators.
