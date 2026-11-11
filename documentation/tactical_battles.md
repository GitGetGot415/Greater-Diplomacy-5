# Tactical battles

This guide owns the shared battlefield mechanics, tactical battle terminology, and custom-battle controls.
AI means artificial intelligence.

## Current status

The playable land-combat prototype is available through **Custom Battle** in the main menu.
Custom battles run separately from the campaign. They spend no resources, change no campaign units, and are not saved, exported, or used in multiplayer.

Campaign tactical mode uses the same preview and actual battle. Its division rules are in [tactical_mode.md](tactical_mode.md).
The existing campaign battle editor for front-line and reserve orders has its own rules in [non_llm_ai.txt](non_llm_ai.txt).

## The three views

| Term | Screen name | Purpose | Availability |
| --- | --- | --- | --- |
| Editing | Edit Battle | Build the armies, reorder units, and choose a controlled unit. | Custom battles only. |
| Preview | Preview Battle | Review the participating units in read-only roster panels before combat starts. | Custom battles and campaign tactical mode. |
| Actual | Actual Battle | Fight on the battlefield. | Custom battles and campaign tactical mode. |

**Editing should only be viewable when making a custom battle.**
Playing tactical mode uses preview and actual battle, with participants supplied by the campaign encounter.

### Editing: Edit Battle

Choose **Custom Battle** to open editing.
The terrain button opens **Battle Terrain**. Choose Plains, Hills, Desert, Forest, Jungle, Mountains, or Swamp.
The choice belongs to this custom-battle setup; campaign encounters use the province's terrain.
**Add Friendly** and **Add Enemy** open the searchable land-unit picker. Each selection adds one unit at the chosen library level.
Artillery-type units (everything that can bombard: artillery, railroad guns, Landkreuzers, and the Railgun)
take no part in tactical battles, so the picker and **Random** never offer them.
**Cancel** closes the picker and keeps units already added.

Select a roster card and choose **Remove** to remove that entry.
Drag cards within an army to change deployment order: the leftmost card deploys in the front rank, closest to the
enemy, and each card to its right deploys one rank further back.
Scroll long rosters with the wheel, scrollbar, or by dragging the roster background.
`CUSTOM_BATTLE_MAX_UNITS_PER_SIDE` in [data/constants.py](../data/constants.py) limits each army's divisions
in custom battles and the deployed divisions in campaign tactical encounters. Campaign results clear the entire
defeated side from the tile, including units beyond that deployment limit; see [tactical_mode.md](tactical_mode.md#battle-results-and-loss-of-control).
Both armies need at least one unit before **Simulate** becomes available.

The gray gear button opens **Unit Settings** for that roster entry.
**Nationality** chooses a country from the base country library. **Starting HP** is a slider that sets
the unit's health as a percent of its full library HP, from 1% to 100%. **Done** closes the settings.
Each change applies immediately; canceling a picker keeps the current value.

To edit several units at once, press in empty space of a roster panel (not on the card
area, a button, or the scrollbar) and drag a square over the cards. All touched cards of
that army are selected, and the gear button on any selected card opens **Group Settings**
for all of them. A field shows **Mixed** when the selected units differ. Selecting one
card is an ordinary selection. Clicking empty panel space, reordering, removing, or
generating armies clears the group.
Units of the same type can have different nationalities and starting health.
Reordering preserves those choices, and replaying uses the configured starting HP.
New units start at full health. The two sides initially use the first two playable
countries by display name, or the same country when only one is available.

Editing cards show the unit name, symbols for health, deployed tactical attack, and defense
(including zero defense), and a health bar along the bottom with the nationality's flag to its right.
The bar is shaded in dithered bands and blends from green to yellow at half health to red at zero.
Drag along the bar to set that unit's starting HP; on a card in a selected group, it sets the whole group.
Preview cards omit the unit name. They show a larger icon, a health bar
with the nationality's flag to its right, and the same stat symbols.
Attack accounts for how many sub-units the division deploys and those sub-units' health under the tactical
wound setting. The attack stat is before target defense, hit rounding, range falloff, and tactical pacing.
Nationality selects the preview art's country variant where available; army sides
still determine friend and foe.

**Random** replaces both armies with independently chosen groups of three to five units.
Each generated unit also gets a random nationality from the playable countries.
The **Year** slider limits random generation to the highest available level of each land-unit family at or before the selected year, including additional research requirements.
Units researched five or more years before the selected year are excluded.
The mouse wheel over the slider adjusts the year one year at a time. Manual selection remains unrestricted by the slider.

Select a friendly roster card and choose **Control** to command that unit during actual battle.
**Release Control** restores an entirely automatic battle.
A yellow arrow identifies the controlled unit. Reordering preserves the chosen entry; removing that entry or generating new armies clears control.

When both armies have units, a line below the rosters forecasts how the same fight would end in the normal game:
which army wins and in how many turns, that both armies are destroyed, or that there is no clear winner.
It uses the normal game's own battle forecast (`combat_forecast.estimated_combat_outcome`, which the map's
battle bubbles and Manage Battle also use) with each army standing in for one of two countries at war.
Nationality, terrain width, forts, politics, and conscription therefore do not affect it.
It changes when unit types, order, or starting HP change, and it can differ from the result of actual battle.

**Simulate** opens preview. Editing has no **Start** button.

### Preview: Preview Battle

Entering preview first shows a black screen. Two blank bars slide linearly inward
from the top and bottom, meet, wait, then slide apart to reveal the roster preview.
The sound sequence is **Open Music**, **Select Unit Filter** when the bars meet, then
**Open Music** as the bars start moving apart. The bars have their own styling,
similar to the Messages panels, and can be changed independently.

Edit `PREVIEW_SLIDE_IN_SECONDS`, `PREVIEW_HOLD_SECONDS`, and
`PREVIEW_SLIDE_OUT_SECONDS` near the top of
[screens/game/custom_battle.py](../screens/game/custom_battle.py) to change the timing.
Slide durations must be positive; the hold can be zero. Restart after changing them.
Other preview controls become available when the transition finishes.
Preview has no **Exit** button. **Retreat** sits beside **Start**. In a custom battle it returns to editing,
as does the configured Back key. In a tactical encounter it opens the retreat map.

Preview uses the same friendly and enemy roster panels as editing.
Preview cards use the base game's unit art and symbols for health, attack, and defense.
The rosters can be scrolled. Drag friendly cards to change the friendly army's deployment order, the same way as in
editing; the leftmost card deploys in the front rank. The enemy army's order is fixed.
Units cannot be added, removed, or reassigned to player control.
Nationality and starting HP are read-only in preview; gear buttons are absent.
Editing buttons, **Random**, **Simulate**, and the **Year** slider are absent.

Preview shows the units involved in the encounter. It shows no battlefield.
Combat time stays still, units do not move, and no shots are fired.

The Music screen's Tactical Songs lists choose battle music. A battle where the
enemy has a tank plays the tank songs; any other battle plays the infantry songs.
Friendly tanks do not count.
The music begins in preview and continues through actual battle without restarting
at Start. Editing uses normal playlist music. Leaving preview or actual battle,
including reaching the result view, stops the tactical music and uses normal playlist selection.
Actual battle, including while paused, lowers music and battlefield sound effects with separate multipliers.
Edit `BATTLE_MUSIC_VOLUME` and `BATTLE_SFX_VOLUME` together near the top of
[screens/game/custom_battle.py](../screens/game/custom_battle.py), then restart the game.
Each multiplier is a share of the normal volume: `0.0` mutes, `0.5` halves, and `1.0` keeps normal volume.
The SFX multiplier applies to gunfire, flesh hits, and ricochets. Zooming out reduces music and battlefield
effects further in proportion to the zoom; zooming closer than the default does not increase either multiplier.
Preview and the result view use normal music volume. Interface sounds such as button clicks are not lowered.
See MUSIC PLAYBACK in [general_info.txt](general_info.txt) for selection and persistence.

Preview, actual battle, and results have square gear (Settings) and music (Music) icon buttons. Each opens its screen over the battle,
and Back returns to the same view with its simulation unchanged. Opening either screen
during actual battle pauses it, and it stays paused after Back until **Resume** is chosen. The tactical song keeps playing through both screens and after Back.

**Start** is available only in preview. Choosing **Start** opens actual battle with the prepared forces.
In a custom battle, **Retreat** returns to editing while preserving the army setup.

### Actual: Actual Battle

Actual battle is the fighting on the terrain battlefield.
The two armies deploy facing each other around the middle of the battlefield, their front ranks a fixed distance apart
(`SPAWN_FRONT_GAP` in [map_logic/custom_battle.py](../map_logic/custom_battle.py)) whatever their size.
Each division deploys as one vertical line of its sub-units, centered top to bottom, in its own rank.
Sub-units keep the same spacing along a line, so a division with fewer sub-units makes a shorter line.
Roster order runs front to back. The battlefield is square, with each side long enough to fit two full armies.
Armored cars, WW1 tanks, light tanks, medium tanks, heavy tanks, main battle tanks, and super heavy tanks use the chassis
and turret images in `assets/battles`. The chassis follows the hull heading, and the turret follows the gun's aim.
Infantry, cavalry, and militia use their chassis images from the same folder and share `turret/Infantry Gun.png`
for their aimed weapon. These troops use smaller sprites, with the gun offset toward the right shoulder as the body turns.
Motorized infantry, mechanized infantry, and infantry fighting vehicles use their chassis
images without a separate weapon layer. Other tanks and vehicles use rectangles.
Health bars show remaining strength, with the unit's nationality flag beside each bar, and projectiles show shots in flight.
Cannon and autocannon shells are bright orange and thicker than rifle and machine-gun shots.
Muzzle flashes, cannon recoil, and brief impact flashes distinguish firing and impacts.
Regular shots from AI units play a random Rifle Shot 1, Rifle Shot 2, or Rifle Shot 3 sound.
Regular shots from the player-controlled sub-unit play Heavy Gunshot instead.
Each shell plays a random Tank Shot 1, Tank Shot 2, or Tank Shot 3 sound.
The weapon determines the sound: a vehicle's machine gun uses regular firing sounds.
Both armies and player-controlled units follow the same sound rules.
Projectile hits on unarmored bodies play a random Flesh Wound 1, 2, or 3 sound.
Armored bodies play a random Bullet Ricochet sound when the HP actually lost to the hit is at most one percent
of the struck sub-unit's maximum HP, including hits that deal no damage. Remaining HP limits the loss used
for this comparison. Larger armored hits add no impact sound. Terrain hits and rams do not use these sounds.
Impact sounds use the same zoom scaling as gunfire and share the bounded rifle sound pool.
Firing sounds use the existing sound-effect volume and pitch settings and play when a projectile is fired.
Rifle and tank firing sounds have separate voice pools so rifle volleys cannot suppress quieter tank shots.
When a pool is full, the newest shot replaces the oldest sound tail in that pool.

#### Sub-units

Each roster entry is a division. On the battlefield a division becomes several sub-units, each with its own shape,
health bar, and flag. Infantry-type, cavalry, and troop-carrier divisions bring the most; tanks and armored cars
bring fewer. `SUBUNIT_COUNTS` in
[map_logic/custom_battle.py](../map_logic/custom_battle.py) sets each count.
A wounded division brings fewer sub-units: with fraction `f` of full health and `N` sub-units at full health,
it brings `ceil(f × N)` sub-units that share its health equally. For example, with 10 sub-units at full health,
70% brings 7 at full health, 63% brings 7 at 90%, and 60% brings 6 at full health.
Sub-units also divide the division's damage. Each hit is worked out with the sub-unit's wound-adjusted attack against the
target's full defense, then the damage that gets through is divided by the division's sub-unit count at full health.
Weapon profiles multiply the damage after defense and sharing. The full stats still decide who can hurt whom;
weapon timing and damage multipliers determine how that attack becomes sustained fire.

#### Combat

Each hit is reduced by the target's full defense stat, down to zero damage.
Tactical defense stays constant as health falls; campaign combat scales defense with health.
`TACTICAL_DAMAGE_AT_ZERO_HEALTH` near the top of `map_logic/custom_battle.py` controls attack lost to wounds.
Set the multiplier to `0.0` for attack directly proportional to a sub-unit's remaining HP, or `1.0` for no wound penalty.
Values between zero and one interpolate linearly between that attack floor and full attack at full HP.
Restart after editing the value. Shooting and ramming use the same setting, before defense and rounding.
Destroyed sub-units never attack. Losing sub-units also reduces a division's total firepower.
After defense and sub-unit damage sharing, positive damage rounds up before the tactical pacing multiplier applies.
The multiplier slows even small hits without making previously vulnerable targets immune.
Shooting and ramming share the base damage calculation and target capability rules.
Weapon damage multipliers apply only to shooting; ramming retains its separate impact multiplier.
Machine guns cannot damage armored battlefield shapes, even when the vehicle carrying the gun can.
A shot retains the shooter's attack statistics and weapon profile when fired and uses the rules for the unit it actually hits.
A shot already in flight still lands after its shooter is destroyed.

Every sub-unit has the same maximum weapon range. Weapon profiles set projectile speed, spread, damage contribution,
shot interval, magazine or burst length, and the reload after the final round. Early firearms fire individual shots;
later equipment uses magazines, faster individual shots, or bursts. Equipment stages select profiles in the generated unit metadata.
An infantry or militia division with support-weapon metadata and more than one deployed sub-unit assigns one sub-unit
the support weapon. The remaining sub-units keep their primary firearms. The middle sub-unit remains player-controlled.
Tanks and armored cars have independent main guns and machine guns. Infantry fighting vehicles have autocannons
and machine guns. Both guns follow the same turret aim, but each gun has its own cooldown and burst or magazine state.
The machine gun remains available while the main gun reloads.

Shots fly in a straight line. Rifle and machine-gun shots stop at the first body they cross, ally or enemy.
Shells have a penetration budget. Each crossed body consumes that body's penetration resistance and reduces the shell's
remaining damage. A body that consumes the remaining budget stops the shell. A shell can hit each body only once,
including across simulation ticks. Terrain still intercepts shells. Only the shooter is safe from its own shot.
Friendly fire uses the same damage rules as hits on enemies.
Each shot, the player's included, leaves at a random angle within its weapon's spread. Movement and hull rotation
increase spread. Shell weapons use a smaller spread multiplier, including the movement and turning penalties;
vehicle machine guns retain normal bullet spread. The same small error
carries a shot further off target over a longer distance, so long-range shots miss more often than close ones.
Shots also lose damage gradually after their full-damage distance, down to a positive minimum multiplier.
Falloff uses the distance the projectile actually travels to impact and applies after defense and sub-unit damage sharing.
Falloff does not affect ramming. Preferred fighting, cavalry charge, skirmishing, and withdrawal distances
are separate from maximum weapon range. Read tactical tuning in `map_logic/custom_battle.py`.

#### Terrain

Plains have a light green background and a few scattered trees that block movement and intercept shots.
Deserts have an orange background and no obstacles.
Hills have a yellow background and occasional traversable mounds. Additional contour bands indicate higher mounds.
Raised ground intercepts shots through a crest;
climbing toward the crest opens firing lines. Units and guns use the ground height at their position.
Mountains have a brown background, more mounds, impassable rocks, and occasional chasms.
Chasms block ground movement but allow shots across.
Forests have a green background and scattered trees. Jungle has a dark green background, more trees,
and a few marsh areas, fewer than swamps have.
Each tree has a trunk of size 1, 2, or 3, drawn by the `Trunk` images in `assets/battles/terrain`.
The trunk is the tree's hitbox. `TREE_TRUNK_RADII` in [map_logic/battle_terrain.py](../map_logic/battle_terrain.py)
sets each size's radius, and the trunk image is scaled to that radius.
Foliage is a green circle drawn without an image. Each tree's foliage radius is chosen uniformly at random
from `TREE_FOLIAGE_RADII`, independently of trunk size.
Foliage only draws, covering units and shots, while health bars, flags, and the player's controls stay on top.
Each tree's foliage is a slightly lighter or darker shade of `FOLIAGE_COLOR` (up to `FOLIAGE_GREEN_VARIATION`).
All foliage is partly transparent (`FOLIAGE_ALPHA` in
[screens/game/custom_battle.py](../screens/game/custom_battle.py)), so units and trunks show faintly beneath it.
Trunks block ground movement and intercept shots. Ordinary shots leave trees intact; cannon and autocannon shells remove a tree,
foliage included, and stop at that tree. Later shots and ground units can use the opening.
Swamps have a pink background, trees, and impassable marsh areas. Marsh areas allow shots across like chasms.

Trees are placed individually across the battlefield, including beside and behind the armies, while deployment areas stay clear.
All generated terrain features keep at least `TERRAIN_FEATURE_GAP` of open ground between their edges.
The same spacing rule applies between trees, hills, mountain rocks, chasms, and marshes, including different feature types.
Spacing uses tree trunks and the full radius of other features; foliage can overlap. Crowded placements are skipped.
The generated battlefield keeps ground routes connected. Terrain generation and
navigation belong to `map_logic/battle_terrain.py`; the screen draws cached artwork from those same features.
Battlefield shapes have different body sizes. Projectile hits, body contacts, movement, navigation, and terrain clearance
use each body's collision radius. Navigation caches distinguish different radii and invalidate when trees are removed.
AI units use ground routes around obstacles and seek accessible firing positions when terrain blocks their shots.
Tanks can fire to clear obstructing trees. Formations can loosen while following routes around terrain.
Friendly support must have an unobstructed ground approach, and terrain-blocked enemy fire does not count as
an immediate close-combat threat. Both armies use the same terrain, navigation, and combat rules.

#### Unit behavior

Infantry-type, cavalry, and troop-carrier sub-units fire only inside a cone in front of the hull.
Tanks and armored cars aim all the way around. Every gun turns toward its aim at its own speed,
so it cannot swing from one direction to another at once. Sub-units also speed up, slow down, and start and stop
turning gradually. These rules apply to AI sub-units and the controlled sub-unit alike.

AI sub-units move as loose divisions. Each division advances on the enemy nearest its center, and each of its
sub-units heads for a point beside that enemy matching its own place in the division's line, so a division arrives
spread out in its deployment order. Divisions use separate approach lanes instead of all aiming for the same line.
Friendly and enemy AI units use the same decision rules. Both sides advance into their preferred firing positions
and hold according to unit behavior and the battle situation. No side receives a unique combat behavior because
of its friendly or enemy status. Unit capabilities, health, position, support, threats, and individual temperaments
can produce different decisions under those shared rules.
A sub-unit that gets well ahead of its division slows down until the division
catches up. Each sub-unit also has its own temperament, drawn at deployment: how close it comes before it stops to
fight, its cruising speed, a short delay before it first moves, and a gentle weave from side to side while advancing.
Once it has stopped, a sub-unit faces the enemy it shoots at so its firing cone covers it.

Each weapon chooses whom to shoot from the enemies close to the sub-unit's nearest enemy. A wounded enemy counts as nearer than
its actual distance, and clear firing lines take priority over targets behind terrain or allies.
Target selection favors enemies the weapon can damage at the shooter's current health. Cannons favor nearby armored
threats; machine guns choose vulnerable targets. While the main gun reloads, the turret can aim the machine gun at its target.

AI sub-units also fight according to their type:

| Type | Behavior |
| --- | --- |
| Tanks | Flank: reach a position beside the enemy before settling into firing range. Entering range alone does not end the flank. |
| Cavalry | Charge in close, withdraw to its usual distance, then charge again. Charging cavalry does not wait for its division. |
| Armored cars | Skirmish: stop at long range and reverse away from close enemies while facing them. |
| Infantry, militia, and troop carriers | Advance steadily and hold at their preferred firing distance. |

Two reactions come before the type's behavior. A sub-unit below a set share of its health falls back while healthier
allies can cover the withdrawal. The last wounded troops keep fighting so depleted armies cannot both withdraw
indefinitely. Wounded units seek nearby cover when available and stop withdrawing once terrain protects them
from their target. Without cover, units withdraw to their separate withdrawal distance.
Vehicles reverse while facing the enemy in an open withdrawal; infantry and cavalry turn away to withdraw.
A fast AI sub-unit (library speed at least `DODGE_MIN_SPEED`)
sidesteps briefly, at right angles to a shot's path and away from it, when it is hit and survives, and also when
another sub-unit's shot, an ally's included, is about to pass close to it while it is not about to fire (its weapon
is reloading, its target is out of range, or an ally stands in its firing line). Slower sub-units never sidestep: they would spend the time turning away instead of aiming. Sub-units still
move only along their hull, so a sidestep starts with a turn. The player's sub-unit never reacts on its own.

Firing always shoots a projectile, including at point-blank range, and uses the normal gun reload.
There are no melee attacks.

Any sub-unit whose library movement speed meets `RAM_MIN_UNIT_SPEED` can ram another unit with a fast impact,
including infantry and cavalry. Units below that cutoff still collide and separate but cannot deal ram damage.
Closing speed along the contact direction determines impact strength, so stationary contact
and sideways brushing do not deal ram damage. Contact mass determines how much each body moves and slows down.
Heavier bodies displace lighter bodies more; similar head-on vehicles stop rather than bounce apart.
Ramming uses the same damage as a point-blank bullet, multiplied by `RAM_DAMAGE`, the closing-speed strength
(capped by `RAM_MAX_STRENGTH`), and the attacker's mass divided by the target's mass (capped at one).
Ramming still respects defense and target capability rules. Ramming needs no fire input and does not use the gun reload.
Contact between allies uses the same collision and separation rules, but ramming damages only enemies.
A pair must separate beyond `CONTACT_RELEASE_DISTANCE` before another ram can deal damage. Sustained pushing cannot
repeat the impact. Knockback decays quickly and never disables steering or firing.
AI units that meet the movement-speed cutoff attempt a ram only with enough impact speed, a mass advantage, adequate health, and a safe approach against
a nearby wounded or reloading enemy. The AI considers suitable nearby targets rather than only the nearest body.
The AI predicts an interception and checks clear ground, intervening units, available run-up,
closing speed, and whether the target can be caught before committing. Terrain cover can make a close approach safer, while
rocks, trees, marshes, and chasms can prevent a ram. The player can attempt any impact under the same contact and damage rules.
During the final approach, committed units stop sidestepping; earlier in the approach, dodging remains available.
Units abandon the approach when support or health no longer permits the ram.

Shots hurt allies, so AI sub-units keep out of each other's way. An AI sub-unit holds fire while an ally
could take its shot. It checks the line along its lead on the target, widened by the aim tolerance and shot spread,
with each ally where it will be when the shot passes. Penetrating guns also check allies beyond the intended target,
up to the shell's maximum reach, unless intervening terrain stops the shot. A loaded AI sub-unit blocked only by an
ally sidesteps away from that ally, whatever its speed, until the line clears. Firing positions chosen around terrain also avoid allies.
Ram-capable AI units brake so they never reach an ally in their path faster than a harmless bump.
The player's sub-unit gets no such help: its shots can hurt allies.

#### Control

| Control | Action |
| --- | --- |
| W | Speed up forward along the hull's facing direction. |
| S | Slow down, then reverse along the hull's facing direction. |
| A | Turn left. |
| D | Turn right. |
| Mouse | Aim. The gun turns toward the pointer, inside the firing cone if the unit has one. |
| Left mouse | Fire the primary weapon along the gun. |
| Right mouse | Fire the secondary weapon, when equipped. Hold both buttons to use both weapons. |
| Mouse wheel | Zoom in or out. |

Movement follows the hull's facing direction. A and D rotate the hull rather than moving it sideways, and turning
the hull carries the firing cone with it.
Human and AI units use the same weapon timing. Holding a fire control fires again only when that weapon is ready.
The primary and secondary weapons have separate reload readouts and progress rings.

Mobile controls use independent drive and aim pads. The drive pad controls forward/reverse throttle and hull steering.
The aim pad aims and fires while held outside its dead zone. Releasing the aim pad stops firing; releasing the drive
pad releases throttle and steering. A weapon selector offers Primary, Secondary, and Both for units with two guns.
The selection remains active until changed, and each gun still follows its own cooldown. Single-weapon units need no selector.
Both pads can be held together, and the selector can be used while a drive finger remains held.
The shared touch-input layer suppresses duplicate mouse events and clears held controls on focus loss or screen changes.

Only the controlled sub-unit shows its range and firing cone (a circle for units that aim all the way around)
and a line along its gun. Its yellow ring has an arrow along the hull that
lengthens with speed and points back while reversing. A second ring fills while the weapon reloads.
Other sub-units show none of these.
The player's heading, selection, and reload indicators keep a readable minimum size when zooming out.
A controlled unit also has a stats box showing signed forward speed in battlefield pixels per second,
body angle in degrees, and whether the gun is ready or how many seconds remain before reloading finishes.
Negative speed means reversing. The body angle runs clockwise from zero pointing right.
The stats stay visible while paused and disappear when the controlled sub-unit is destroyed.

Control covers the middle sub-unit of the controlled division's line. The division's other sub-units fight automatically.
If the controlled sub-unit is destroyed, the player controls no unit for the rest of the battle and spectates it.
Dragging the battlefield then moves the view.
Other friendly units and all enemy units move and fire automatically.
When no unit is controlled, both armies fight automatically.

Actual battle fills the whole screen; the title, status line, and buttons sit on top of the battlefield.
The battlefield has a faint checkerboard that moves only with the view.
It is larger than the screen. While a sub-unit is controlled, the view follows the unit with an offset toward the
mouse pointer, showing more ground in the aiming direction. Moving the pointer farther from the view center
increases the offset. The offset keeps the unit visible and respects the battlefield edges at every zoom level.
Otherwise, drag the battlefield with the left mouse button to move the view.
The mouse wheel zooms in and out around the pointer through fixed steps. Zoomed out past the battlefield's
edges, the whole battlefield is centered on a dark surround.
At distant zoom levels, simple team and unit-type silhouettes replace detailed artwork, and health bars keep a
minimum readable size. Zoom changes presentation without changing weapon reach or collision size.
While controlling a living sub-unit, zooming out stops at `CONTROLLED_MIN_ZOOM` in `screens/game/custom_battle.py`,
including while paused. Set the limit to one of that file's `ZOOM_LEVELS` values.
Spectating allows the full zoom range again.
While the player controls a living sub-unit, arrows mark off-screen enemy divisions and show the nearest distance
in battlefield units. Divisions in the same direction share an arrow with a division count.

**Pause** freezes combat, and **Resume** continues it. The configured Back key toggles pause during actual battle.
The Pause button remains visible but disabled after combat ends; Settings and Music remain available.
Losing window focus also pauses combat. Pausing or leaving combat clears held movement and fire controls.

The custom battle is won when the enemy army is destroyed and lost when the friendly army is destroyed.
Mutual destruction counts as a loss. If the controlled sub-unit is destroyed while friendly units remain, those friendly units continue fighting under AI control.
The status line counts the divisions on each side that still have a sub-unit.
The kill feed keeps the battle's sub-unit deaths, newest first, with each killer and victim represented by a flag
and the normal unit artwork for its nationality and selected art style. Unit names are omitted.
Team colors identify friendly fire; RAM identifies a ramming kill. Scroll with the mouse wheel, scrollbar,
or by dragging the feed to read older kills. Feed scrolling does not zoom or pan the battlefield.
New kills keep older entries in view when the feed has been scrolled away from the newest entry.
The hit that reduces the victim to zero health receives the kill, including shots whose shooter has already died.
The feed panel is visible from the start, including when empty, and remains visible while paused and after combat ends.
Starting another battle clears the entries and keeps the empty panel visible.
When combat ends, the final battlefield stays visible with the win or loss message and the usual result controls.
The battle stops advancing. Use the mouse wheel to zoom and drag the battlefield to look around, including
when the controlled sub-unit survived. Result buttons remain available. Campaign encounters use
the same result view, with **Continue** returning to the map.

**Run Again** opens preview with fresh armies and a fresh battlefield from the same setup.
Reordering the friendly army during preview preserves that preview's generated terrain.
**Edit Armies** returns to editing. **Exit** from actual battle or the result view also returns to editing.
**Exit** from editing returns to the main menu. These routes back to editing belong to the custom-battle prototype.

## Tactical-mode flow

Campaign division control, movement, pinning, encounters, artillery, retreat, and battle results
have their own guide: [Tactical mode](tactical_mode.md).

## Rules and implementation owners

[screens/game/custom_battle.py](../screens/game/custom_battle.py) owns the three views, roster controls, navigation, the camera, and desktop and mobile battle controls.
[ui/navigation/touch_input.py](../ui/navigation/touch_input.py) routes continuous touch pointers separately from ordinary tap and drag gestures.
Campaign encounter and retreat owners are listed in [tactical_mode.md](tactical_mode.md#state-and-implementation-owners).
[map_logic/custom_battle.py](../map_logic/custom_battle.py) owns unit generation, sub-units, deployment, movement, aiming, projectiles, cooldowns, and results.
The same simulation handles custom battles and campaign encounters. Contact state, AI commitments, and gun cooldowns
exist only during the encounter; campaign results still use the surviving health fraction of each division.
Its `SUBUNIT_COUNTS`, `MOBILITY`, and `AIM` tables set sub-unit counts, acceleration and turning, and firing cones and gun speeds for each battlefield shape.
`WEAPON_RANGE`, `RANK_GAP`, `SUBUNIT_SPACING`, and `SPAWN_FRONT_GAP` set range and deployment.
`TACTICAL_WEAPONS`, `TACTICAL_VEHICLE_WEAPONS`, and `TACTICAL_BODIES` in [data/constants.py](../data/constants.py)
own weapon profiles, vehicle loadouts, body dimensions, collision radii, and penetration resistance.
`EQUIPMENT_TACTICAL_WEAPONS` in [data/generators/recipes.py](../data/generators/recipes.py) assigns each equipment stage
a primary weapon and optional support weapon, emitted as `metadata.tactical_primary` and `metadata.tactical_support`.
The active library supplies those assignments when a battle deploys. Content without optional weapon metadata uses
the standard rifle profile for nonvehicle shapes. Gun state exists only inside the encounter and is never saved or exported.
No save conversion is needed: campaign saves, selected historical turns, and older moves keep their existing unit records.
`is_artillery` decides which units sit tactical battles out.
Each weapon's `spread`, the movement and turning spread constants, and `TACTICAL_SHELL_SPREAD_MULTIPLIER`
set how far shots can stray. The simulation's `on_kill` callback reports lethal shots and rams without changing
damage resolution. The screen caches the compact feed when a kill occurs; feed entries are not campaign save data.
The `AI_*` ranges set the temperaments, and `COHESION_SLACK` and
`COHESION_THROTTLE` set how far ahead a sub-unit may get and how much it slows. `BEHAVIORS` assigns each shape its
behavior; `FLANK_OFFSET`, `CHARGE_CLOSE`, `SKIRMISH_*`, `FALL_BACK_HEALTH`, `DODGE_*`, and
`TARGET_*` tune the behaviors, reactions, and target choice. `BattleSimulation(seed=...)`
fixes the random temperaments and shot spread so a battle can be replayed; the game leaves it unset, so every battle differs.
`DAMAGE_SCALE`, `RAM_*`, `CONTACT_MASS`, and `KNOCKBACK_*` own tactical pacing and contact impacts.
`APPROACH_LANE_GAP` and `FLANK_ARRIVAL_DISTANCE` tune the approach lanes and flank completion.
`LINE_SHIFT_SECONDS` and `ALLY_BUMP_SPEED` tune how AI sub-units keep out of their allies' way.

Unit statistics and capabilities come from [unit_data.json](../data/json/unit_data.json).
Research dates come from [research_template.json](../data/json/research_template.json) through the shared [unit queries](../data/queries/unit_info.py).
Read those sources for current tuning values.

The prototype converts movement and range to battlefield pixels and shares target capability rules with campaign combat.
Tactical attacks use their own configurable health floor; campaign combat retains its existing health-scaled attack.
The shared campaign combat rules remain documented in [non_llm_ai.txt](non_llm_ai.txt).
