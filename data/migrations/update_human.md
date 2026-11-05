# hi hello if you're a human read this

## step 1
change `GAME_VERSION` in constants.py

## step 2
compile

## step 3
publish compiled versions

## step 4
change `version.txt` to match `GAME_VERSION`

## step 5
once the previous release is committed, run:

    python scripts/data/write_released_content.py

## why step 5

`write_released_content.py` reads committed git history to find released versions and the unit, building, and settings names those releases used

this updates `data/migrations/released_content.py` with released names and equipment meanings, so the game can map older equipment by year and the checks can catch an old unit, building, or setting that no longer works

the script reads committed releases, and uncommitted release changes aren’t in that history yet, so the previous release needs to be committed

starting the next version is simply a convenient time to refresh the list so compatibility checks cover everything players just received