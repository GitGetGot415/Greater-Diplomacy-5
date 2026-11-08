# Tactical battles

This guide owns the tactical battle terminology, custom-battle controls, and intended tactical-mode flow.
AI means artificial intelligence.

## Current status

The playable land-combat prototype is available through **Custom Battle** in the main menu.
Custom battles run separately from the campaign. They spend no resources, change no campaign units, and are not saved, exported, or used in multiplayer.

Campaign tactical mode uses the same preview and actual battle. See [Tactical-mode flow](#tactical-mode-flow).
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
**Add Friendly** and **Add Enemy** open the searchable land-unit picker. Each selection adds one unit at the chosen library level.
**Cancel** closes the picker and keeps units already added.

Select a roster card and choose **Remove** to remove that entry.
Drag cards within an army to change deployment order. Scroll long rosters with the wheel, scrollbar, or by dragging the roster background.
Each army has a size limit. Both armies need at least one unit before **Simulate** becomes available.

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

Editing cards show the unit name, symbols for health, health-adjusted attack, and defense
(including zero defense), and a health bar along the bottom with the nationality's flag to its right.
The bar is shaded in dithered bands and blends from green to yellow at half health to red at zero.
Drag along the bar to set that unit's starting HP; on a card in a selected group, it sets the whole group.
Preview cards omit the unit name. They show a larger icon, a health bar
with the nationality's flag to its right, and the same stat symbols.
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
The rosters can be scrolled, but units cannot be added, removed, reordered, or reassigned to player control.
Nationality and starting HP are read-only in preview; gear buttons are absent.
Editing buttons, **Random**, **Simulate**, and the **Year** slider are absent.

Preview shows the units involved in the encounter. It shows no battlefield.
Combat time stays still, units do not move, and no shots are fired.

The Music screen can assign a tactical battle song. The song begins in preview
and continues through actual battle without restarting at Start. Editing uses
normal playlist music. Leaving preview or actual battle, including reaching the
result view, stops the tactical song and uses normal playlist selection.
See MUSIC PLAYBACK in [general_info.txt](general_info.txt) for selection and persistence.

**Start** is available only in preview. Choosing **Start** opens actual battle with the prepared forces.
In a custom battle, **Retreat** returns to editing while preserving the army setup.

### Actual: Actual Battle

Actual battle is the fighting on the grass battlefield.
Tanks and vehicles use rectangles, artillery uses thin rectangles, infantry and militia use circles, and cavalry uses ovals.
Health bars show remaining strength, with the unit's nationality flag beside each bar, and projectiles show shots in flight.
The controlled unit has a yellow outline and an arrow pointing along its facing direction.
Each hit is reduced by the target's full defense stat, down to zero damage.
Tactical defense stays constant as health falls; campaign combat scales defense with health.

| Control | Action |
| --- | --- |
| W | Move forward along the unit's facing direction. |
| S | Reverse along the unit's facing direction. |
| A | Turn left. |
| D | Turn right. |
| Space | Fire straight ahead. |

Movement follows the unit's facing direction. A and D rotate the unit rather than moving it sideways.
Firing uses a cooldown shared with AI units. Holding Space fires again only after the cooldown expires.
Other friendly units and all enemy units move and fire automatically.
When no unit is controlled, both armies fight automatically.

**Pause** freezes combat, and **Resume** continues it. The configured Back key toggles pause during actual battle.
Losing window focus also pauses combat. Pausing or leaving combat clears held movement and fire controls.

The custom battle is won when the enemy army is destroyed and lost when the friendly army is destroyed.
Mutual destruction counts as a loss. If the controlled unit is destroyed while friendly units remain, those friendly units continue fighting under AI control.

**Run Again** opens preview with fresh armies from the same setup.
**Edit Armies** returns to editing. **Exit** from actual battle or the result view also returns to editing.
**Exit** from editing returns to the main menu. These routes back to editing belong to the custom-battle prototype.

## Tactical-mode flow

During campaign tactical play, the player commands one land division while the parent country remains AI-controlled.
The flow is **campaign encounter → preview → actual battle → campaign**.

After each turn resolves, once per turn, the game opens preview at once when the player's land unit shares a tile
with hostile land units. Preview starts with that unit controlled. The friendly army is that unit followed by friendly
land units on the tile, and the enemy army is the hostile land units there, each up to the army size limit.
Each unit enters with its current health. Campaign combat deals no damage on that tile during turn resolution,
so the battle is where the damage happens. Naval and air units do not take part.
Tactical play has no editing view and no route for adding, removing, randomly generating, or replacing units.

**Retreat** opens the map with the tiles the unit can fall back to marked: neighboring tiles it may enter
that are not hostile land and hold no hostile units, the same rule the rule-based AI uses to retreat. Choose a marked tile to give the unit a move order there and return to the map.
The mouse wheel zooms and the pan buttons move the map. **Back** returns to the preview. **Retreat** is available even when no tile is marked, so the player can look and go back.

Actual battle has no **Exit** button in tactical play. When it ends, **Continue** returns to the map.
If the controlled unit was destroyed, even in a won battle, it is removed, tactical mode ends,
and the game continues in spectator mode.
When the battle ends, every unit that took part keeps its remaining fraction of health in the campaign, and destroyed units, friendly or enemy, are removed from the tile.
The tile is then captured as after any campaign combat: if only enemies remain, they take it. Everything else waits for the next turn.
The tactical division has no resource-management costs, including repair costs, and does not charge the parent country for those actions.
Tactical battles in multiplayer remain unavailable.

## Rules and implementation owners

[screens/game/custom_battle.py](../screens/game/custom_battle.py) owns the three views, roster controls, navigation, and keyboard input.
[screens/game/tactical_retreat.py](../screens/game/tactical_retreat.py) owns the retreat map. `Map.open_tactical_battle` starts an encounter.
[map_logic/custom_battle.py](../map_logic/custom_battle.py) owns unit generation, deployment, movement, projectiles, cooldowns, and results.

Unit statistics and capabilities come from [unit_data.json](../data/json/unit_data.json).
Research dates come from [research_template.json](../data/json/research_template.json) through the shared [unit queries](../data/queries/unit_info.py).
Read those sources for current tuning values.

The prototype converts movement and range to battlefield pixels and uses shared health-scaled attack.
Positive damage rounds up to whole health points so weakening armies can finish a battle.
The shared campaign combat rules remain documented in [non_llm_ai.txt](non_llm_ai.txt).
