## Greater Diplomacy 5

Greater Diplomacy 5 is an open source grand strategy game which has a timeline that spans 1910 - 2010

what makes it unique is that ai controlled countries can be made to use an llm to process diplomacy, making interactions with them very immersive

feel free to look around, fork it, clone it, etc

## Maintaining Raw Source
if you have decided to download the raw source from here (Code > Download ZIP > extract it), this section covers how to maintain it.

**Pros:** you get every update as they are uploaded rather than getting full versions every now and then on itch.io.

**Cons:** its harder to setup (requiring git installed), although i've tried to make it as simple as it can be for you in this guide.

first, install git from https://git-scm.com/install/. the installer has a lot of options just click "next" through them, they aren't necessary.
*(p.s dont choose to download any of the extra apps & gui, just the base.)*

second, now go into your downloaded gd5 folder and run `pip install -r requirements.txt` to install all dependencies.

third, whenever you want to check if there's an update, run `git pull`. if it says "Already up to date.", you are at the latest version. If not it will
automatically upd everything to latest version on github.

## For MacOS Users
When installing Greater Diplomacy 5, and double clicking "main" artifact that is extracted from packaged on itch.io zip it might display this popup

"“main” is damaged and can’t be opened. You should move it to the Bin." with no option to start anyways.

The fix:

For every instalation Greater Diplomacy 5, this command needs to be ran:
xattr -dr com.apple.quarantine /path/to/the/GD5/main.app

## Real Time Multiplayer

desktop real-time multiplayer hosts use TLS. Source and packaging environments need the `cryptography` Python package (`pip install cryptography`); the Windows and macOS build recipes bundle it automatically. Browser builds intentionally show real-time multiplayer as desktop-only.
## Benchmarking with Objective Judge Horizon

[Objective Judge Horizon](https://github.com/Pr1nted/objective-judge-horizon) compares turn-based strategy games on the same machine. `map_tools/ojh_benchmark.py` lets it measure Greater Diplomacy 5 through the game's own code rather than an outside driver:

```bash
python map_tools/ojh_benchmark.py turns --turns 250 --scenario scenarios/historical/1939
python map_tools/ojh_benchmark.py fps --seconds 5 --late-turns 20 --scenario scenarios/historical/1939
```

`turns` plays every nation as AI with no window and times each whole turn through `turn_manager` (AI preparation, resolution and the map refresh passes). `fps` opens the real window with no frame cap and times the menu, the map (start, zoomed out, zoomed in, scrolling, late game), the research screen and the map while a turn resolves. Model-driven diplomacy is skipped, as with Force Skip. Results are printed as `OJH ...` lines on stdout; the tool's docstring lists them.
