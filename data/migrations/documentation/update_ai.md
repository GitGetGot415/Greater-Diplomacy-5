Updating the Game: AI Guide
==========================

Use this checklist when implementing an update. The full migration rules and
ownership are in data/migrations/MIGRATIONS.md. The release checklist for the
human maintainer is in data/migrations/update_human.md.
Run commands from the repository root.

Before Editing
--------------

1. Read AGENTS.md and documentation/writing_style.md. Check git status and
   preserve unrelated changes.
2. Read the affected code, tests, and the relevant sections of MIGRATIONS.md.
   Find every reader, writer, saved reference, and multiplayer representation
   of the data before changing its name, meaning, or shape.
3. Check Released Names in MIGRATIONS.md and data/migrations/released_content.py.
   Compatibility rules cover released data, including formats older releases
   accepted. Do not invent legacy cases for changes made only in development.

Starting a Version
------------------

1. Change GAME_VERSION in data/constants.py when work on a new version starts.
   Do not increment it for each task within that version.
2. Never edit version.txt. Only the human maintainer changes it at release.
   Players download that file; changing it early makes them see "Outdated"
   before a release is available.
3. After the previous release is committed, run:
   python scripts/data/write_released_content.py
   This refreshes data/migrations/released_content.py from committed release history,
   not from the new development content. The generator requires full Git
   history and refuses to discard recorded releases or names.
   Do not commit, stage, or create a branch without explicit user approval.

Deciding Whether Data Needs Conversion
-------------------------------------

- An optional new field needs an owner, writer, loader, and an old-save default
  that preserves old behavior. It needs no conversion rule if that default is
  enough. Verify old-save loading and a new-data round trip.
- A released field that moves, changes shape, or changes meaning needs a rule
  in data/migrations/conversions.py. Give a changed meaning a new field name.
- A renamed or removed released unit, building, or settings key needs a
  conversion or alias in the migrations package. Check queues, cargo, orders,
  scripts, scenario settings, and other saved references too.
- Statistics, costs, and research-year changes normally use existing library
  conversions and load repairs. Research uses saved research_years and the
  active tree; unit stat refresh preserves the fraction of health remaining.
  If a library edit removes a released identifier, that identifier still needs
  a conversion. Unknown unit types otherwise keep their saved statistics.
- Invalid current data needs a load repair with its existing shared owner.
  See Three Kinds of Conversion in MIGRATIONS.md for the distinction.

Implementing a Conversion
-------------------------

1. Extend the shared conversion rule or alias. Each rule detects the older
   data itself and does nothing to current data. Running conversion again
   must leave the result unchanged. Preserve unknown valid fields and saved
   references. Keep existing compatibility rules unless the user asks to
   remove support.
2. Every format-conversion rule runs on every load, regardless of the saved
   version. Keep dependency order, but never add per-version files, a chain
   of release steps, or another format version. The version stamp refuses
   newer files, matches real-time players, and requests tournament host review;
   the stamp never selects conversion rules.
3. Apply the rule through convert_save, convert_history_turn, and convert_move
   wherever the affected data occurs. Convert history only when a turn is
   selected. Research-year conversion is the exception because all snapshots
   share research_years. Keep gameplay, UI, and AI reading the current format.
4. Check tournament and real-time multiplayer separately. Tournament moves
   contain partial player data. A different or missing version stamp requires
   host approval; conversion still passes normal authentication, permission,
   session, turn, and duplicate checks. Keep snapshot_moves.py for moves
   without player_intents. Real-time players must match the host's version;
   the server owns state and filters snapshots for each recipient.
5. Use the shared readers in validation.py before traversing known saved fields.
   Prioritize a playable local save: recover readable values, default unreadable
   optional containers, and drop only broken entries. Preserve valid paid orders
   and progress. Player commands still require permission and legality checks;
   malformed submissions produce ValueError with their field path. Do not catch
   programming exceptions as malformed input. Preserve lazy history conversion.
6. Document the rule in MIGRATIONS.md and update affected readers and guides.
   Do not duplicate the full migration reference in this checklist.

Verification and Handoff
------------------------

For migration changes, cover older data, unchanged current data, repeat
conversion, unknown valid fields, and save/load round trips. Include selected
history and affected move formats. Check valid, unauthorized, malformed, and
stale multiplayer input when applicable. Use committed fixtures, not ignored
files. Do not remove released names from the inventory to make a check pass.

Run the relevant migration checks when changing compatibility behavior:
    python -m unittest tests.test_data_migrations

Include these modules when equipment research or tournament moves are affected:
    python -m unittest tests.test_historical_infantry tests.test_tournament_moves

Do not run tests for unrelated documentation edits. Follow AGENTS.md for other
required checks when adding runtime material or changing tests that read tuning
data. Build with the appropriate scripts in compilation_scripts/ when needed.

Built-in maps convert on load. Rewriting their files is optional and adds data
changes, so do it only when those changes are in scope. Preview first:
    python scripts/maps/upgrade_shipped_maps.py
Apply the preview with:
    python scripts/maps/upgrade_shipped_maps.py --write
The tool applies format conversions, not the full load-time library refresh.

Report changed files, compatibility decisions, verification, and any changes
beyond the request. State that version.txt was not touched. Leave release
publication and the version.txt update to the human maintainer.
