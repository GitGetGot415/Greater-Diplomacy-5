# Tactical mode

This guide owns the campaign rules for the player's tactical division, including control, movement,
encounters, retreat, and results. AI means artificial intelligence.
Shared battlefield controls, combat mechanics, and custom battles are documented in
[tactical_battles.md](tactical_battles.md). Shared campaign combat rules are in
[non_llm_ai.txt](non_llm_ai.txt).

## Your division

The player commands one land division while the parent country remains AI-controlled.
After confirming a division for a new tactical game, the map camera centers on that division's tile.
Choosing a tile or stack offers only land units eligible for tactical battles, excluding aircraft, ships, and artillery.
A tile or stack holding only ineligible units offers no division and does not spawn a replacement.
Tactical battles in tournament and real-time multiplayer remain unavailable.

Tactical Orders commands only the tactical division. Other units on the opened tile are read-only.
Tactical Orders has no selection, batch, army, or clear-all controls.
The AI leaves the tactical division's orders under player control.

Tactical play has no resource pool. The tactical division moves without fuel, and repairs are free.
Neither the player nor the parent country pays for those repairs.
The resource strip is hidden and Economy is disabled.
Declare Independence starts the new country with `c.TACTICAL_INDEPENDENCE_STOCKPILE`.

## Movement and pinning

Normal tile access, speed, and pinning rules apply to the tactical division.
See Movement and pinning in [non_llm_ai.txt](non_llm_ai.txt) for the shared movement-step and withdrawal rules.
Those rules check incoming hostile units regardless of tile ownership and consider attack steps after a friendly
first step within the same turn. Pinning is checked again from the current positions on each movement step.
A route that stays in friendly territory this turn can withdraw even when the destination holds enemies.
The division joins combat on arrival; fighting on friendly land does not make the withdrawal an attack route.

If the tactical division and hostile land forces attempt to cross the same border in opposite directions,
the tactical division wins the movement clash only when no incoming hostile unit from another tile pins the division.
Otherwise the tactical division stays on its current tile and fights the arriving enemies there.
If the incoming attacker dies or is stopped before arriving, the division continues its original route with no movement lost to the failed pin.
When crossing priority applies, the opponents stay on the destination tile and the tactical division enters that tile,
where the encounter takes place. This applies at turn start and on later movement steps.
The crossing deals no automatic combat damage and does not award victory in the tactical battle.

The map's crossing preview points toward the tactical division's destination when both orders are visible
and the shared pinning check allows the crossing. A pinned crossing has no advance marker.
Other clashes keep the normal movement and combat rules.

## Encounters and artillery

The flow is **campaign encounter → preview → actual battle → campaign**.
After each turn resolves, once per turn, the game opens preview when the player's land unit shares a tile
with hostile land units that can fight a tactical battle. Preview starts with the player's division controlled.
The friendly army is that division followed by friendly land units on the tile, and the enemy army is the hostile
land units there, each up to the deployment limit. Each deployed unit enters with its current health.
The limit controls battlefield deployment; units beyond the limit still belong to their side's final result.

An eligible ground encounter involving the tactical division is recognized before any automatic charge-survival
projection or ground-combat calculation, whether the division attacks or defends.
Even an apparently doomed attacker reaches the tactical battle alive.
Ground combat, capture ranking, and capture bounces wait for the tactical result.
Convoys caught on land unload without an automatic combat calculation.
Simultaneous hostile arrivals stop on their shared tile before either unit takes another movement step.

Naval and air units do not take part in the tactical battle.
Grounded aircraft and warships caught in land combat retain their destruction rules.
Separate air missions and bombardments retain their own resolution rules.

Artillery-type units on the tile sit the battle out. When the battle ends, the losing side's artillery on the tile
is destroyed and the winning side's artillery is untouched; mutual destruction counts as a friendly loss.
When hostile artillery is the only hostile land force on the tile, the player wins at once without a battle:
no preview opens, campaign combat skips the tile, and that artillery is destroyed.
The player's side is untouched, and the tile is then captured as after any campaign combat.

Tactical play has no editing view and no route for adding, removing, randomly generating, or replacing units.
Preview can reorder the friendly army, which sets where each division deploys;
each unit's result still returns to that unit.

## Retreat

**Retreat** opens the map with the tiles the unit can fall back to marked: neighboring tiles the unit may enter
that are not hostile land and hold no hostile units, the same rule the rule-based AI uses to retreat.
Choose a marked tile to give the division a move order there and return to the map.
The mouse wheel zooms and the pan buttons move the map. **Back** returns to preview.
**Retreat** is available even when no tile is marked, so the player can look and go back.

## Battle results and loss of control

Actual battle has no **Exit** button in tactical play. When the battle ends, **Continue** returns to the map.
The player directly controls the middle sub-unit of the division's line. The division's other sub-units fight
automatically. If the controlled sub-unit dies, the player spectates the rest of the battle without switching units.

If every sub-unit of the controlled division was destroyed, even in a won battle, the division is removed,
tactical mode ends, and the game continues in spectator mode.
While any of the division's sub-units survives, the player keeps the division, even when the controlled sub-unit
was destroyed and the player spectated the rest of the battle.

Every surviving participating unit keeps its sub-units' remaining share of its full health in the campaign.
Winning a tactical battle leaves zero enemy units on the tile. The entire defeated side is destroyed and removed,
including divisions beyond the deployment limit, artillery, and any other enemy units that did not deploy.
Incoming enemies that moved onto the tile are included in the defeat; those units do not return to their origin tiles.
The same rule clears the player's side after a defeat. Winning reserves and neutral bystanders are preserved;
volunteer units belong to the side of their host country. Automatic victories against hostile artillery also clear
all enemy units from the tile. Unit rosters, capture checks, and battle-marker caches refresh after the result.
The tile is then captured as after any campaign combat: if only enemies remain, those enemies take the tile.
Everything else waits for the next turn.

Saving during tactical play records the controlled division's persistent unit ID in `tactical_player_unit_id`.
Loading binds control to that same living division on the loaded map and leaves the host country AI-controlled.
The save stores no duplicate unit. If the saved division is missing, dead, ineligible for tactical battles, or no longer belongs to the player,
the game opens in spectator mode. Editors, new scenarios, tournament games, and real-time games do not restore
tactical control. Older saves without the reference keep their existing country-control behavior.
New history snapshots record the reference too, so selecting a recorded turn restores that turn's tactical control.

## State and implementation owners

`queries.get_active_ai_nations` removes the human-country exclusion while `tactical_mode` is active.
`map_screen.player_unit` can remain after independence ends tactical mode.
Check `tactical_mode` instead of inferring the mode from that attribute.
`diplomatic_popups.spawn_popups_for_player` marks suppressed host messages as shown during tactical play,
preventing old host messages from appearing after independence.

[tactical_orders.py](../screens/game/tactical_orders.py) owns Tactical Orders (`TACTICAL_ORDERS`).
`map_input.orders_state` names the screen for every route into Orders, including battle panels.
Both Orders screens share unit rows, commands, and map targeting through
[unit_commands.py](../ui/panels/unit_commands.py).
[unit_actions.py](../map_logic/actions/unit_actions.py) owns command permissions;
`unit_actions.repair_costs` makes tactical repairs free.

[movement.py](../data/queries/movement.py) owns shared movement and pinning queries.
[combat_processor.py](../map_logic/system32/combat_processor.py) and
[movement_processor.py](../map_logic/system32/movement_processor.py) apply those rules during turn resolution.
[custom_battle.py](../map_logic/custom_battle.py) identifies tactical encounters and applies battle results.
`Map.open_tactical_battle` starts an encounter; [tactical_retreat.py](../screens/game/tactical_retreat.py)
owns the retreat map. See [tactical_battles.md](tactical_battles.md#rules-and-implementation-owners)
for the shared battlefield simulation and tuning owners.
