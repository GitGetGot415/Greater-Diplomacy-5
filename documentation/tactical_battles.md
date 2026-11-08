# Tactical battles

This guide owns the tactical battle terminology, custom-battle controls, and intended tactical-mode flow.
AI means artificial intelligence.

## Current status

The playable land-combat prototype is available through **Custom Battle** in the main menu.
Custom battles run separately from the campaign. They spend no resources, change no campaign units, and are not saved, exported, or used in multiplayer.

Connecting the preview and actual battle to campaign tactical mode is planned.
The intended campaign flow described below is not yet implemented.
The existing campaign battle editor for front-line and reserve orders has its own rules in [non_llm_ai.txt](non_llm_ai.txt).

## The three views

| Term | Screen name | Purpose | Availability |
| --- | --- | --- | --- |
| Editing | Edit Battle | Build the armies, reorder units, and choose a controlled unit. | Custom battles only. |
| Preview | Preview Battle | Review the participating units in read-only roster panels before combat starts. | Custom battles now; intended for campaign tactical mode. |
| Actual | Actual Battle | Fight on the battlefield. | Custom battles now; intended for campaign tactical mode. |

**Editing should only be viewable when making a custom battle.**
Playing tactical mode should use preview and actual battle, with participants supplied by the campaign encounter.

### Editing: Edit Battle

Choose **Custom Battle** to open editing.
**Add Friendly** and **Add Enemy** open the searchable land-unit picker. Each selection adds one unit at the chosen library level.
**Cancel** closes the picker and keeps units already added.

Select a roster card and choose **Remove** to remove that entry.
Drag cards within an army to change deployment order. Scroll long rosters with the wheel, scrollbar, or by dragging the roster background.
Each army has a size limit. Both armies need at least one unit before **Simulate** becomes available.

**Random** replaces both armies with independently chosen groups of three to five units.
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
The sound sequence is **Open Music**, **Cancel Orders** when the bars meet, then
**Open Music** as the bars start moving apart. The bars have their own styling,
similar to the Messages panels, and can be changed independently.

Edit `PREVIEW_SLIDE_IN_SECONDS`, `PREVIEW_HOLD_SECONDS`, and
`PREVIEW_SLIDE_OUT_SECONDS` near the top of
[screens/game/custom_battle.py](../screens/game/custom_battle.py) to change the timing.
Slide durations must be positive; the hold can be zero. Restart after changing them.
The configured Back key cancels the transition and returns to editing.
Other preview controls become available when the transition finishes.

Preview uses the same friendly and enemy roster panels as editing.
The rosters can be scrolled, but units cannot be added, removed, reordered, or reassigned to player control.
Editing buttons, **Random**, **Simulate**, and the **Year** slider are absent.

Preview shows the units involved in the encounter. It shows no battlefield.
Combat time stays still, units do not move, and no shots are fired.

The Music screen can assign a tactical battle song. The song begins in preview
and continues through actual battle without restarting at Start. Editing uses
normal playlist music. Leaving preview or actual battle, including reaching the
result view, stops the tactical song and uses normal playlist selection.
See MUSIC PLAYBACK in [general_info.txt](general_info.txt) for selection and persistence.

**Start** is available only in preview. Choosing **Start** opens actual battle with the prepared forces.
In a custom battle, **Exit** returns to editing while preserving the army setup.

### Actual: Actual Battle

Actual battle is the fighting on the grass battlefield.
Tanks and vehicles use rectangles, artillery uses thin rectangles, infantry and militia use circles, and cavalry uses ovals.
Health bars show remaining strength, and projectiles show shots in flight.
The controlled unit has a yellow outline and an arrow pointing along its facing direction.

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
**Edit Armies** returns to editing. **Exit** from preview, actual battle, or the result view also returns to editing.
**Exit** from editing returns to the main menu. These routes back to editing belong to the custom-battle prototype.

## Intended tactical-mode flow

During campaign tactical play, the player commands one land division while the parent country remains AI-controlled.
The intended encounter flow is **campaign encounter → preview → actual battle → campaign result**.

The campaign should supply the participating units and the player's controlled division.
Preview should allow the player to inspect those units and start the encounter.
Tactical play should expose no editing view and no route for adding, removing, randomly generating, or replacing the encounter's units.

Actual battle should resolve the encounter to a win or loss: destroy all hostile units on the tile or lose the controlled division.
The campaign would then apply the encounter's consequences and continue turn processing.
The intended tactical division has no resource-management costs, including repair costs, and does not charge the parent country for those actions.
Selecting naval or air units for this tactical combat and multiplayer integration remain outside the current scope.

## Rules and implementation owners

[screens/game/custom_battle.py](../screens/game/custom_battle.py) owns the three views, roster controls, navigation, and keyboard input.
[map_logic/custom_battle.py](../map_logic/custom_battle.py) owns unit generation, deployment, movement, projectiles, cooldowns, and results.

Unit statistics and capabilities come from [unit_data.json](../data/json/unit_data.json).
Research dates come from [research_template.json](../data/json/research_template.json) through the shared [unit queries](../data/queries/unit_info.py).
Read those sources for current tuning values.

The prototype converts movement and range to battlefield pixels and uses shared health-scaled combat damage.
Positive damage rounds up to whole health points so weakening armies can finish a battle.
The shared campaign combat rules remain documented in [non_llm_ai.txt](non_llm_ai.txt).
