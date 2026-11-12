# TODO

## Uncategorized

- make it so that in tactical mode you can get other units to make simmilar movement orders to you to coordinate attacks n such
- you can bring allies when declaring independence
- expand tactical battles so as to allow naval and air battles

## Check First

- check why refreshing country data can show countries that don't exist anymore
- check why AI countries refuse to become vassals and whether their replies explain the real reason
- check which historical scenarios use the wrong Germany tag `(oh right german reich vs regular ol germany, historical leaders use the germany tag not the german reich tag)`
- only show active countries under "Claims On You," and decide what to do with governments in exile
- add a way to reset a country's appearance to its defaults
- find specific examples of bad or predictable AI decisions
- measure which parts of the game are slow before looking into C++ or vectorization
- check whether saving during tournament move entry is allowed
- check whether sending military access and then declaring war while the request is pending works
- check whether snapshot_moves.py can be deleted `(maybe sometime in the future)`
- check whether low-health units should deal less damage `(lane targeting already spreads damage across the front rank, and the AI already rotates badly damaged units out)`
- check whether overkill can kill a unit before the rest of the damage is applied
- check the maximum country-data length `(search for max_length)`
- check whether all current tests are needed `(visual menu tests may not be useful)`
- review the old TODOs

## Audio

- make music pitch work with regular audio files on macOS and web, not just json
- look into another audio backend if the current options can't do what's needed
- use different selection sounds for different unit types `(like HOI4)`
- make UltraBox mod channels play on desktop. Desktop playback never calls the synth's `play()`, so `isPlayingSong` stays false and UltraBox skips its mod channels. Vibrato, pan, and other automation stay at their starting values. Web playback runs them correctly.

## Diplomacy and Countries

- add non-aggression pacts for players and rule-based AI
- think about whether countries with conflicting cores should be able to join the same faction
- let countries surrender and give up claims to avoid war
- let countries betray their faction right away without having to leave it first
- let countries declare rivals, making relations worse and giving them a free reason to start a humiliation war, with limits based on country power
- let players release a country and then play as it
- let players release nations or puppets from spectator mode `(i think this was already added?)`
- stop a country from giving up land in a peace deal unless it controls that land or the controller agrees
- let countries leave or rejoin factions correctly after annexation
- add custom country names, and make them work for subjects
- add diplomatic plays from Victoria 3  `(ACTUAL DIPLOMACY??? IN GREATER DIPLOMACY 5???)`
- check whether Integrated and Autonomous subjects give useful choices compared with annexing them
- let much stronger neighboring countries demand cores or submission through ultimatums
- let nearby countries react to ultimatums by backing opposing factions
- think about adding world tension `(what would that even do though)`
- figure out which diplomacy rules from the board game would be useful `(as a seperate game mode)`

## Puppets and Factories

- let AI countries create Integrated subjects when it's useful
- let masters build factories in their subjects' territory
- decide whether building cost uses the owner's factories or only factories on core land
- let AI masters take resources from Integrated subjects
- let subjects get captured land where they have cores
- stop subjects from getting unwanted borders
- decide whether a country with only subjects should form a faction
- decide what Integrated subjects can trade to their master, including land with different cores
- decide whether Integrated subjects should accept every trade from their master
- decide whether trades with Integrated subjects need a different interface
- stop overlapping subject creation from making unwanted countries in the same area

## Economy and Production

- make fuel shortages affect normal movement or combat
- decide whether resources need storage limits
- let players change how much units cost to produce
- let players save and load unit-cost presets
- add more resources for tanks, factories, and other production `(please god no don't make things more complicated than they have to be)`
- let disbanding refund a little `(idk about this one)`
- let countries nationalize factories, which should hurt diplomacy `(yoink! your factories are MINE)`
- combine the tank production buttons like the infantry and artillery buttons
- add a separate naval production queue
- add ports that make naval units faster to build
- always show oil cost and defense on production rows, even when they're zero
- show production info in a table
- let countries control another country's factories temporarily or permanently
- let countries rent factories through trade
- let countries take over foreign-owned factories at a diplomatic cost
- figure out what political power would be used for before adding it

## Combat and Units

- let infantry variants turn back into regular infantry
- rework aircraft carriers so they can carry a certain amount of air units
- add guerrilla units as faster militia `(it's like cavalry but worse!)`
- add armored trains with their own role `(wouldn't this need railways first)`
- add entrenchment
- decide whether artillery should pierce defense, do percentage damage, or use whichever does more damage `(guohhhhhhhhh)`
- show separate buttons for convoying, unconvoying, trucking, and untrucking `(idk is this really worth it)`
- add more ways to support naval invasions besides the existing shore bombardment `(are you not satisfied)`
- decide whether combat-width research would make combat better
- decide whether connecting tiles should affect combat width
- decide whether allies should use the highest combat-width research level on their side `(COMBAT WIDTH RESEARCH ISNT EVEN A THING YET)`
- move unused combat width between lanes during the same turn
- measure AI_LINE_SPEND_RATIO again with the current lane rules
- figure out specific ways to improve the combat zone display `(VAAAAAAAAGUE)`

## Movement and Map Display

- let allies see active movement arrows
- let players queue movement across oceans, including getting units on and off ships
- add straits and land bridges
- add railroads `(choo choo)`
- add an option to group units when zoomed out
- add filters to the country list
- add country filters on the world map
- add settings for how country names show up on the map

## AI and scripted events

- add an AI difficulty setting and make it clear what it changes
- add an option to make AI countries never accept peace proposals `(oh my god why)`
- add an option to stop cores from being removed `(in game you can do this, not scripted events tho)`
- add a separate option to stop core removal from causing revolts
- let players edit AI prompts in settings `(if someone wants to have an ai larp as monika from doki doki literature club for some reason yeah sure let them do that)`
- add newspaper events that country actions can trigger
- add a separate screen for setting up newspaper events
- add more causes for rebellions besides core removal
- add focus trees `(im sure scenario creators would love this)`
- add rules for devastation and recovery `(see greater diplomacy 4 for more context on this)`

## Scenarios and Maps

- add the Backrooms as a map `(haha no)`
- figure out which controls are missing for historical country names, scenario maps, and resource maps `(huh?????)`
- add sliders for minimum and maximum resource values in random scenarios `(not the resource spawn % im talking about the pure RAW values)`
- make scenarios and saves use less space
- make the JSON for saves and scenarios human-readable so changes are easy to diff, as long as the exported zip doesn't get much bigger
- let scenarios use custom unit_data.json files `(AAAAAAAAAAAAAAA)`
- let players export a timelapse from saved game history `(oh this might be fun)`

## UI and tools

- add a way to inspect all data associated with a country
- use the operating system's folder picker where possible `(actually the current built in folder picker seems alright enough, is this thing really nessecary?)`
- add missing statistics and history views `(more statistics besides just global economy, like CHARTS and stuff)`
- figure out specific ways to better organize Hanskolmer's art `(vague, seriously what do you mean "organize better")`

## Insane dedication required for these ones

- add a historical campaign from 1910 to 1940 `(this is INSANELY ambitious how the HELL are you going to railroad that) (maybe increasing the days per turn could help)`
- think about continuous real-time gameplay `(ohhhhhhhh my god real time HOI4 multiplayer)`

## Custom Map Terrain Maker not just Painter

- let players import an image and turn it into a map `(and not like a custom terrain map i mean they should be able to import something like trollface.png and have that turned into a terrain map)`
- let players change the map's shape without losing countries or scenario data
- keep province data when splitting provinces without copying units or resources into both
- keep needed data and sort out ownership when merging provinces