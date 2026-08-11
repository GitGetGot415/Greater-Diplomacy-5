import random
from collections import namedtuple
from map_logic.ai import ai_handler, ai_llm_runner, ai_opinion, ai_prompts, ai_world
from map_logic.diplomacy import diplomacy_messages, diplomacy_events
from data import queries
import data.constants as c

def _attach_generated_message(nation_data, task, final_msg):
    """Writes an LLM-generated line onto the action the task was queued for.

    The action is only updated if it is still the one this task generated text
    for, so a declaration the AI changed its mind about isn't overwritten.
    """
    target_info = diplomacy_messages.get_pending(nation_data, task["sender"], task["target"])
    if target_info.get("action") == task["action_type"]:
        target_info["message"] = final_msg


def process_proactive_llm_tasks(map_screen):
    """Processes all queued proactive diplomacy texts in a background ThreadPoolExecutor."""
    tasks = map_screen.proactive_llm_tasks
    
    if not tasks:
        map_screen.proactive_llm_tasks_total = 0
        map_screen.proactive_llm_tasks_completed = 0
        return
        
    human_players = map_screen.active_players
    current_ai_mode = ai_handler.get_ai_mode()
    immersion = ai_handler.get_ai_immersion_level()
    
    # --- DYNAMIC LOADING BAR CALCULATION ---
    task_count = 0
    if current_ai_mode != "OFF":
        if immersion == "ABSOLUTE":
            # In Absolute mode, every single proactive task calls the LLM
            task_count = len(tasks)
        elif immersion == "FULL":
            # In Full mode, only tasks targeting human players call the LLM
            task_count = sum(1 for t in tasks if t["target"] in human_players)
        # In Lite mode, proactive tasks return None immediately, so count remains 0
        
    map_screen.proactive_llm_tasks_total = task_count
    map_screen.proactive_llm_tasks_completed = 0
    
    max_threads = queries.get_ai_threads()
    
    map_screen.loading_status_text = f"Drafting Proactive Responses (0/{map_screen.proactive_llm_tasks_total})..."
    
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    my_turn_id = ai_handler.CURRENT_TURN_ID

    def call(task):
        return ai_handler.generate_proactive_text(
            map_screen.nation_data, active_nations, task["sender"], task["target"],
            task["context"], human_players, my_turn_id)

    def record(task, llm_msg):
        # An empty answer is the same as no answer here.
        _attach_generated_message(map_screen.nation_data, task,
                                  llm_msg if llm_msg else task["fallback"])

    def record_fallback(task):
        _attach_generated_message(map_screen.nation_data, task, task["fallback"])

    def count(task):
        """Only the tasks the loading bar was sized for tick it along."""
        if current_ai_mode == "OFF":
            return
        if immersion == "ABSOLUTE" or (immersion == "FULL" and task["target"] in human_players):
            map_screen.proactive_llm_tasks_completed += 1
            map_screen.loading_status_text = f"Drafting Proactive Responses ({map_screen.proactive_llm_tasks_completed}/{map_screen.proactive_llm_tasks_total})..."

    ai_llm_runner.run_llm_batch(
        tasks, call, record, record_fallback,
        on_progress=count,
        should_abort=lambda: map_screen.force_skip_llm,
        max_workers=max_threads,
        deadline=ai_llm_runner.turn_deadline())

def process_basic_proactive_ai(map_screen):
    """Hardcoded basic logic for AI to declare war for cores and join faction wars."""
    # This pass queues diplomacy and revokes lapsed military access, but never
    # moves a nation between factions, alliances or imperial families -- so the
    # membership half of the diplomatic picture can be resolved once up front.
    # Access itself stays live, since section 0.5 below revokes it as it goes.
    with queries.diplomacy_snapshot(freeze_access=False):
        _run_basic_proactive_ai(map_screen)


#: One row per proposal the AI opens on its own initiative.
#: fallback_key  -- entry in ai_prompts.AI_FALLBACK_RESPONSES
#: fallback      -- the same line again, so a mod that trims that table gets a
#:                  sensible message instead of a KeyError. Two of the seven
#:                  sections used to index the table directly and would crash.
#: queued_message-- overrides what is stored on the queued action itself; only
#:                  a war declaration uses it, to name the wargoal
#: cooldown      -- whether queueing also starts a cooldown against the target
ProactiveProposal = namedtuple("ProactiveProposal",
                               "fallback_key fallback queued_message cooldown")

PROACTIVE_PROPOSALS = {
    "CEASEFIRE": ProactiveProposal(
        "PROACTIVE_CEASEFIRE", "We offer terms for a ceasefire.", None, False),
    "JOIN_FACTION_REQ": ProactiveProposal(
        "PROACTIVE_JOIN_FACTION",
        "Our enemies are aligned, let us join your faction to stand against them.",
        None, False),
    "CREATE_FACTION": ProactiveProposal(
        "PROACTIVE_CREATE_FACTION", "We propose establishing a new faction together.",
        None, False),
    "CALL_TO_ARMS": ProactiveProposal(
        "PROACTIVE_CALL_TO_ARMS", "We request your aid in our ongoing conflicts!",
        None, False),
    "REQ_MILITARY_ACCESS": ProactiveProposal(
        "PROACTIVE_REQ_MILITARY_ACCESS",
        "As we both fight against a common foe, we request military access through your territory.",
        None, False),
    "JOIN_WARS": ProactiveProposal(
        "PROACTIVE_JOIN_WAR", "May we join you in your war?", None, False),
    "WAR_DECLARATION": ProactiveProposal(
        "PROACTIVE_DECLARE_WAR", "Your occupation of our rightful territory ends now!",
        c.WARGOAL_TAKE_CLAIMS, True),
}


def _queue_proactive_proposal(map_screen, pending, ai_name, target, action, context_target=None):
    """Queues one AI-initiated proposal and books the job that writes its text.

    Seven sections of the proactive pass build the same three things -- the
    prompt context, the entry in pending_diplomacy, and the proactive_llm_tasks
    job -- and every difference between them that actually matters is a column
    of PROACTIVE_PROPOSALS. The sections keep their own gating: who is a valid
    target, and whether to stop after one, is genuinely per-section.
    """
    spec = PROACTIVE_PROPOSALS[action]
    fallback = ai_prompts.AI_FALLBACK_RESPONSES.get(spec.fallback_key, spec.fallback)

    pending[target] = {
        "action": action,
        "turns": 0,
        "message": spec.queued_message or fallback,
    }
    if spec.cooldown:
        queries.set_ai_diplo_cooldown(ai_name, target, action, map_screen.nation_data)

    map_screen.proactive_llm_tasks.append({
        "sender": ai_name,
        "target": target,
        "context": ai_prompts.get_proactive_action_context(action, context_target),
        "fallback": fallback,
        "action_type": action,
    })


def _claim_slot(pending, queued_this_pass, target):
    """Reserves this nation's one outgoing-proposal slot for `target`.

    pending_diplomacy holds a single action per target, so the sections below
    compete for the same slot. Without this, a Call to Arms queued by section 2
    would be silently overwritten by section 3's Join Wars later in the very same
    pass, and the player would never see the request at all. First section to ask
    for a target wins it; the rest wait for a future turn.
    """
    if target in queued_this_pass:
        return False

    existing = pending.get(target)
    if existing is not None:
        # Never overwrite a proposal that is already travelling
        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
        if turns != 0:
            return False

    queued_this_pass.add(target)
    return True


def _decrement_diplo_cooldowns(data):
    """Section 0: ages down (and cleans up) this nation's per-target action cooldowns."""
    if "diplo_cooldowns" in data:
        for target, actions in list(data["diplo_cooldowns"].items()):
            for act, cd in list(actions.items()):
                if cd > 0:
                    actions[act] -= 1
                elif cd == 0:
                    # Clean up finished cooldowns
                    del actions[act]
            if not actions:
                del data["diplo_cooldowns"][target]


def _auto_revoke_war_based_access(map_screen, ai_name, data, my_enemies):
    """Section 0.5: access granted purely because we shared an enemy lapses
    once that shared enemy is no longer common to both of us (peace, ceasefire, etc)."""
    access_reasons = data.get("military_access_reasons", {})
    if not access_reasons:
        return

    my_access = data.get("military_access", [])
    for grantee in list(access_reasons.keys()):
        if access_reasons[grantee] != "war":
            continue
        grantee_enemies = set(queries.get_enemies(grantee, map_screen.nation_data))
        if set(my_enemies) & grantee_enemies:
            continue  # still fighting a common enemy, access stands

        if grantee in my_access:
            my_access.remove(grantee)
        del access_reasons[grantee]

        diplomacy_events.log_global_event(map_screen.nation_data, f"{ai_name} revoked {grantee}'s military access as their shared war has ended.")
        diplomacy_messages.send_message(map_screen, ai_name, grantee, "Our common war has ended; your military access through our territory has been revoked.", "DIPLOMACY")


def _seek_ceasefire_if_unreachable(map_screen, ai_name, pending, queued_this_pass, my_enemies, active_nations, world):
    """Section 1: offers a ceasefire to any enemy we can no longer physically reach."""
    for enemy in my_enemies:
        if enemy not in active_nations: continue
        if not world.reachable(ai_name, enemy):
            if not queries.is_ai_diplo_on_cooldown(ai_name, enemy, "CEASEFIRE", map_screen.nation_data):
                if _claim_slot(pending, queued_this_pass, enemy):
                    _queue_proactive_proposal(map_screen, pending, ai_name, enemy, "CEASEFIRE")
                    break # Act once per turn to avoid conflicts


def _seek_defensive_faction(map_screen, ai_name, pending, queued_this_pass, my_enemies, active_nations):
    """Section 1.5: an unaligned nation at war looks for a faction to join, or
    else another unaligned co-belligerent to found one with."""
    # Prevent sending multiple faction requests
    has_pending_faction_req = False
    for target_nation, info in pending.items():
        if isinstance(info, dict) and info.get("action") in ["CREATE_FACTION", "JOIN_FACTION_REQ"]:
            has_pending_faction_req = True
            break

    if has_pending_faction_req:
        return

    potential_leaders = []
    for enemy in my_enemies:
        # Find nations also at war with our enemy
        enemy_wars = queries.get_enemies(enemy, map_screen.nation_data)
        for mutual_combatant in enemy_wars:
            if mutual_combatant == ai_name or mutual_combatant not in active_nations:
                continue
            # If they have a faction, we want to talk to the leader
            fac = map_screen.nation_data.get(mutual_combatant, {}).get("faction", "")
            if fac:
                fac_leader = queries.get_faction_leader(fac, map_screen.nation_data)
                if fac_leader and fac_leader not in potential_leaders and fac_leader in active_nations:
                    potential_leaders.append(fac_leader)

    if potential_leaders:
        # Just ask the first valid leader we found
        target_leader = potential_leaders[0]
        if not queries.is_ai_diplo_on_cooldown(ai_name, target_leader, "JOIN_FACTION_REQ", map_screen.nation_data):
            if _claim_slot(pending, queued_this_pass, target_leader):
                _queue_proactive_proposal(map_screen, pending, ai_name, target_leader, "JOIN_FACTION_REQ")
        return

    # Find nations also at war with our enemy who aren't in a faction to form a new one with
    potential_partners = []
    for enemy in my_enemies:
        enemy_wars = queries.get_enemies(enemy, map_screen.nation_data)
        for mutual_combatant in enemy_wars:
            if mutual_combatant == ai_name or mutual_combatant not in active_nations:
                continue
            fac = map_screen.nation_data.get(mutual_combatant, {}).get("faction", "")
            if not fac and mutual_combatant not in potential_partners:
                potential_partners.append(mutual_combatant)

    if potential_partners:
        target_partner = potential_partners[0]
        if not queries.is_ai_diplo_on_cooldown(ai_name, target_partner, "CREATE_FACTION", map_screen.nation_data):
            if _claim_slot(pending, queued_this_pass, target_partner):
                _queue_proactive_proposal(map_screen, pending, ai_name, target_partner, "CREATE_FACTION")


def _call_faction_to_arms(map_screen, ai_name, pending, queued_this_pass, my_faction, my_enemies, active_nations):
    """Section 2: asks a faction-mate to join a war of ours they aren't already in."""
    faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
    for member in faction_members:
        if member == ai_name or member not in active_nations: continue

        member_enemies = map_screen.nation_data[member].get("at_war_with", [])

        unshared_wars = [e for e in my_enemies if e not in member_enemies and e in active_nations and not queries.has_active_truce(member, e, map_screen.nation_data)]

        if unshared_wars:
            if not queries.is_ai_diplo_on_cooldown(ai_name, member, "CALL_TO_ARMS", map_screen.nation_data):
                if _claim_slot(pending, queued_this_pass, member):
                    _queue_proactive_proposal(map_screen, pending, ai_name, member, "CALL_TO_ARMS",
                                              context_target=unshared_wars[0])


def _request_access_from_co_belligerents(map_screen, ai_name, pending, queued_this_pass, my_enemies, active_nations):
    """Section 2.5: even nations in different factions ask each other for
    passage if they're both fighting the same enemy, so allied fronts can
    actually link up."""
    co_belligerents = []
    for enemy in my_enemies:
        if enemy not in active_nations: continue
        for co in queries.get_enemies(enemy, map_screen.nation_data):
            if co == ai_name or co not in active_nations: continue
            if co in co_belligerents: continue
            if co in my_enemies: continue
            if not queries.needs_military_access_request(ai_name, co, map_screen.nation_data): continue
            co_belligerents.append(co)

    for co in co_belligerents:
        if queries.is_ai_diplo_on_cooldown(ai_name, co, "REQ_MILITARY_ACCESS", map_screen.nation_data):
            continue

        if _claim_slot(pending, queued_this_pass, co):
            _queue_proactive_proposal(map_screen, pending, ai_name, co, "REQ_MILITARY_ACCESS")
            break  # Act once per turn to avoid conflicts


def _join_faction_wars_proactively(map_screen, ai_name, pending, queued_this_pass, my_faction, my_enemies, active_nations):
    """Section 3: offers to join a faction-mate's war we aren't already in."""
    faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
    for member in faction_members:
        if member == ai_name:
            continue

        member_enemies = map_screen.nation_data[member].get("at_war_with", [])

        unshared_wars = [e for e in member_enemies if e not in my_enemies and e in active_nations and not queries.has_active_truce(ai_name, e, map_screen.nation_data)]

        if unshared_wars:
            target_enemy = unshared_wars[0]
            if not queries.is_ai_diplo_on_cooldown(ai_name, member, "JOIN_WARS", map_screen.nation_data):
                if _claim_slot(pending, queued_this_pass, member):
                    _queue_proactive_proposal(map_screen, pending, ai_name, member, "JOIN_WARS",
                                              context_target=target_enemy)


def _declare_war_for_cores_and_claims(map_screen, ai_name, pending, queued_this_pass, my_enemies, my_master, my_type, is_already_at_war, active_nations, world):
    """Section 4: declares war on a bordering nation holding our cores/claims
    once we think we can win, or fabricates a claim on them first if we lack a wargoal."""
    if my_master and my_type == c.PUPPET_TYPE_INTEGRATED:
        return

    current_turn = queries.get_total_turns(map_screen.time_manager)
    turns_to_wait = int(map_screen.scenario_settings.get("turns_to_wait_before_war", c.TURNS_TO_WAIT_BEFORE_WAR))
    if current_turn < turns_to_wait:
        return

    valid_war_targets = world.core_claim_targets(ai_name)
    if not valid_war_targets:
        return

    # ONLY look at nations we actually share a physical border with.
    # Sorted because the loop below takes the first candidate that passes and
    # breaks: iterating the raw set meant which neighbour got invaded came down
    # to string hash order, which is randomised per process, so the same save
    # could start a different war on different launches. Alphabetical is a
    # placeholder for the desirability score Phase 3 sorts by.
    my_neighbors = world.neighbors[ai_name]
    valid_border_targets = sorted(t for t in valid_war_targets if t in my_neighbors)

    for target in valid_border_targets:
        if target not in active_nations: continue
        if target in my_enemies: continue
        if queries.are_in_same_faction(ai_name, target, map_screen.nation_data): continue
        if queries.has_active_truce(ai_name, target, map_screen.nation_data): continue

        # --- NEW: Skip Integrated Puppets ---
        t_master = map_screen.nation_data.get(target, {}).get("master", "")
        t_type = map_screen.nation_data.get(target, {}).get("puppet_type", "")
        if t_master and t_type == c.PUPPET_TYPE_INTEGRATED:
            continue

        # Avoid arbitrary attacks on masters
        if my_master and my_type == c.PUPPET_TYPE_AUTONOMOUS and target != my_master:
            continue

        # Border superiority, alliance/economic power and how distracted
        # the target already is all live inside ai_thinks_it_can_win; this
        # block used to recompute every one of them and throw the result
        # away, which cost several full map scans per candidate target.
        # Not "could I win" but "do I want this": the odds still dominate, but a
        # nation we are on good terms with, a promise we made, and the two wars
        # we are already losing all count now -- and an aggressive nation will
        # gamble on odds a cautious one turns down.
        if ai_opinion.wants_war(world, ai_name, target, map_screen.scenario_settings):

            # Random chance to actually declare war
            war_chance = float(map_screen.scenario_settings.get("ai_war_declaration_chance", c.AI_WAR_DECLARATION_CHANCE))
            if random.random() <= war_chance:
                has_wargoal = queries.has_wargoal(ai_name, target, map_screen.nation_data, map_screen.map_data)
                if has_wargoal:
                    if not queries.is_ai_diplo_on_cooldown(ai_name, target, "WAR_DECLARATION", map_screen.nation_data):
                        if _claim_slot(pending, queued_this_pass, target):
                            _queue_proactive_proposal(map_screen, pending, ai_name, target,
                                                      "WAR_DECLARATION", context_target=target)
                            break
                else:
                    # Make a claim! (assuming no war is happening)
                    if not is_already_at_war and not queries.is_ai_diplo_on_cooldown(ai_name, target, "MAKE_CLAIM", map_screen.nation_data):
                        core_ids = []
                        for prov in map_screen.map_data.values():
                            if prov.get("owner") == target and ai_name in prov.get("cores", []):
                                core_ids.append(prov["id"])

                        if core_ids:
                            queue = map_screen.nation_data[ai_name].setdefault("claim_queue", [])
                            claims = map_screen.nation_data[ai_name].setdefault("claims", [])
                            for cid in core_ids:
                                if cid not in claims and not any(q["prov_id"] == cid for q in queue):
                                    queue.append({"prov_id": cid, "turns_left": c.CLAIM_TURN_CORE})

                            queries.set_ai_diplo_cooldown(ai_name, target, "MAKE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)
                            break


def _fabricate_claims_during_war(map_screen, ai_name, data, my_enemies, active_nations):
    """Section 4.5: while at war and with no claim queued, picks one enemy
    province (preferring one bordering territory we already hold or claim) to fabricate a claim on."""
    claim_queue = data.get("claim_queue", [])
    if claim_queue:
        return

    my_claims = set(data.get("claims", []))
    owned_and_claimed = set(my_claims)
    for prov in map_screen.map_data.values():
        if prov.get("owner") == ai_name:
            owned_and_claimed.add(prov["id"])

    potential_targets_adjacent = []
    potential_targets_any = []

    for enemy in my_enemies:
        if enemy not in active_nations: continue
        if queries.is_ai_diplo_on_cooldown(ai_name, enemy, "FABRICATE_CLAIM", map_screen.nation_data):
            continue

        for prov in map_screen.map_data.values():
            if prov.get("owner") == enemy and prov["id"] not in my_claims:
                potential_targets_any.append((enemy, prov))
                if any(n_id in owned_and_claimed for n_id in prov.get("neighbors", [])):
                    potential_targets_adjacent.append((enemy, prov))

    chosen_target = None
    if potential_targets_adjacent:
        chosen_target = random.choice(potential_targets_adjacent)
    elif potential_targets_any:
        chosen_target = random.choice(potential_targets_any)

    if chosen_target:
        target_enemy, target_prov = chosen_target
        data.setdefault("claim_queue", []).append({"prov_id": target_prov["id"], "turns_left": c.CLAIM_TURN_NON_CORE})
        queries.set_ai_diplo_cooldown(ai_name, target_enemy, "FABRICATE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)


def _fabricate_claims_on_weaker_neighbors(map_screen, ai_name, data, my_master, my_enemies, active_nations, world):
    """Section 5: while at peace, fabricates a claim on a weaker bordering
    neighbor we don't already have a wargoal or claim against."""
    current_turn = queries.get_total_turns(map_screen.time_manager)
    turns_to_wait = int(map_screen.scenario_settings.get("turns_to_wait_before_war", c.TURNS_TO_WAIT_BEFORE_WAR))
    if current_turn < turns_to_wait:
        return

    # Sorted for the same reason as the war-target loop above: this one also
    # breaks after the first neighbour it successfully queues a claim against.
    my_neighbors = sorted(world.neighbors[ai_name])

    for neighbor in my_neighbors:
        if neighbor not in active_nations: continue
        if neighbor in my_enemies: continue
        if queries.are_in_same_faction(ai_name, neighbor, map_screen.nation_data): continue
        if queries.has_active_truce(ai_name, neighbor, map_screen.nation_data): continue

        # Avoid attacking masters or puppets
        n_master = map_screen.nation_data.get(neighbor, {}).get("master", "")
        if my_master and my_master == neighbor: continue
        if n_master and n_master == ai_name: continue

        # Check if we already have claims on them or an active wargoal
        has_wg = queries.has_wargoal(ai_name, neighbor, map_screen.nation_data, map_screen.map_data)
        claims = data.get("claims", [])
        has_claims_on_them = any(map_screen.id_to_province.get(cid, {}).get("owner") == neighbor for cid in claims)

        if not has_wg and not has_claims_on_them:
            # Fabricating a claim is how a war becomes legal later, so it wants
            # the same appetite the war itself will need -- minus the wargoal
            # requirement it exists to satisfy. An unambitious nation on good
            # terms with a weak neighbour now simply leaves them alone.
            if (world.is_weaker_neighbor(ai_name, neighbor)
                    and ai_opinion.war_desire(world, ai_name, neighbor,
                                              map_screen.scenario_settings)
                    >= c.AI_CLAIM_DESIRE_THRESHOLD):
                if not queries.is_ai_diplo_on_cooldown(ai_name, neighbor, "FABRICATE_CLAIM", map_screen.nation_data):

                    valid_targets = queries.get_valid_claim_targets(ai_name, neighbor, map_screen.map_data)
                    if valid_targets:
                        target_prov = random.choice(valid_targets)
                        queue = data.setdefault("claim_queue", [])

                        # Ensure it's not already in the queue
                        if not any(q["prov_id"] == target_prov["id"] for q in queue):
                            queue.append({"prov_id": target_prov["id"], "turns_left": c.CLAIM_TURN_NON_CORE})
                            queries.set_ai_diplo_cooldown(ai_name, neighbor, "FABRICATE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)
                            break  # Limit to queueing one claim per cycle


def _run_basic_proactive_ai(map_screen):
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    ai_nations = queries.get_active_ai_nations(map_screen)

    # --- Trigger the UI Progress Bar ---
    map_screen.proactive_tasks_total = len(ai_nations)
    map_screen.proactive_tasks_completed = 0
    map_screen.loading_status_text = "Evaluating AI Grand Strategy..."

    # Nothing below redraws the map, so every border, strength and relation
    # this pass asks about is the same for every nation in it. The snapshot
    # holds the reachability graph that used to be built here, plus the
    # per-pair answers each section below would otherwise sweep the map for.
    world = ai_world.for_screen(map_screen)

    for ai_name in ai_nations:
        if ai_name not in active_nations:
            map_screen.proactive_tasks_completed += 1
            continue

        data = map_screen.nation_data[ai_name]
        pending = data.setdefault("pending_diplomacy", {})
        # Targets already spoken for by an earlier section this turn
        queued_this_pass = set()
        my_faction = data.get("faction", "")
        my_enemies = data.get("at_war_with", [])
        my_master = data.get("master", "")
        my_type = data.get("puppet_type", "")

        _decrement_diplo_cooldowns(data)
        _auto_revoke_war_based_access(map_screen, ai_name, data, my_enemies)

        # Battle Royale has no diplomacy to run, but the cooldown/access
        # upkeep above still applies to every nation -- this used to `return`
        # from inside the loop, which skipped that upkeep for every nation
        # after the first and left the loading bar stuck below its total.
        if c.BATTLE_ROYALE_MODE:
            map_screen.proactive_tasks_completed += 1
            continue

        is_already_at_war = len(my_enemies) > 0

        if is_already_at_war:
            _seek_ceasefire_if_unreachable(map_screen, ai_name, pending, queued_this_pass, my_enemies, active_nations, world)

        if is_already_at_war and not my_faction and not getattr(c, "DISABLE_FACTIONS", False):
            _seek_defensive_faction(map_screen, ai_name, pending, queued_this_pass, my_enemies, active_nations)

        if is_already_at_war and my_faction:
            _call_faction_to_arms(map_screen, ai_name, pending, queued_this_pass, my_faction, my_enemies, active_nations)

        if is_already_at_war:
            _request_access_from_co_belligerents(map_screen, ai_name, pending, queued_this_pass, my_enemies, active_nations)

        if my_faction:
            _join_faction_wars_proactively(map_screen, ai_name, pending, queued_this_pass, my_faction, my_enemies, active_nations)

        _declare_war_for_cores_and_claims(map_screen, ai_name, pending, queued_this_pass, my_enemies, my_master, my_type, is_already_at_war, active_nations, world)

        if is_already_at_war and not (my_master and my_type == c.PUPPET_TYPE_INTEGRATED):
            _fabricate_claims_during_war(map_screen, ai_name, data, my_enemies, active_nations)

        if not is_already_at_war and not (my_master and my_type == c.PUPPET_TYPE_INTEGRATED):
            _fabricate_claims_on_weaker_neighbors(map_screen, ai_name, data, my_master, my_enemies, active_nations, world)

        # --- Update Progress Bar ---
        map_screen.proactive_tasks_completed += 1
        map_screen.loading_status_text = f"Evaluating AI Grand Strategy ({map_screen.proactive_tasks_completed}/{map_screen.proactive_tasks_total})..."

def process_scripted_events(map_screen):
    """Processes scenario-specific scripted events for AI nations."""
    if not queries.get_scenario_flag("use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS, map_screen.scenario_settings):
        return
        
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    human_players = map_screen.active_players
    current_turn = queries.get_total_turns(map_screen.time_manager)
    
    for nation_name in active_nations:
        data = map_screen.nation_data.get(nation_name, {})
        events = data.get("scripted_events", [])
        if not events:
            continue
            
        fired_events = data.setdefault("fired_scripted_events", [])
        
        for i, evt in enumerate(events):
            if i in fired_events and evt.get("fire_once", True):
                continue
                
            # --- NEW: TRIGGER TYPE CHECK ---
            trigger_type = evt.get("trigger_type", "AI Only")
            if trigger_type == "AI Only" and nation_name in human_players:
                continue
            if trigger_type == "Player Only" and nation_name not in human_players:
                continue
            
            # Backwards compatibility parser
            if "conditions" not in evt:
                evt["conditions"] = [{
                    "type": evt.get("condition_type", "Turn Number"),
                    "operator": "==",
                    "value": evt.get("condition_val", ""),
                    "chain": "AND"
                }]
                evt["fire_once"] = True

            conditions = evt.get("conditions", [])
            if not conditions:
                continue

            overall_met = False

            for c_idx, cond in enumerate(conditions):
                c_type = cond.get("type")
                c_op = cond.get("operator", "==")
                c_val = cond.get("value", "")
                chain = cond.get("chain", "AND")
                
                res = False
                
                if c_type == "Turn Number":
                    try:
                        if "BETWEEN" in c_op:
                            parts = c_val.split(",")
                            if len(parts) >= 2:
                                v1, v2 = int(parts[0].strip()), int(parts[1].strip())
                                if c_op == "BETWEEN (INC)":
                                    res = (v1 <= current_turn <= v2)
                                else:
                                    res = (v1 < current_turn < v2)
                        else:
                            v = int(c_val.strip())
                            if c_op == "==": res = (current_turn == v)
                            elif c_op == ">": res = (current_turn > v)
                            elif c_op == "<": res = (current_turn < v)
                            elif c_op == ">=": res = (current_turn >= v)
                            elif c_op == "<=": res = (current_turn <= v)
                    except ValueError:
                        pass
                
                # Random Generation
                elif c_type == "Random (0.00 - 1.00)":
                    rand_val = random.random()
                    try:
                        if "BETWEEN" in c_op:
                            parts = c_val.split(",")
                            if len(parts) >= 2:
                                v1, v2 = float(parts[0].strip()), float(parts[1].strip())
                                if c_op == "BETWEEN (INC)":
                                    res = (v1 <= rand_val <= v2)
                                else:
                                    res = (v1 < rand_val < v2)
                        else:
                            v = float(c_val.strip())
                            if c_op == "==": res = (rand_val == v)
                            elif c_op == ">": res = (rand_val > v)
                            elif c_op == "<": res = (rand_val < v)
                            elif c_op == ">=": res = (rand_val >= v)
                            elif c_op == "<=": res = (rand_val <= v)
                    except ValueError:
                        pass
                        
                elif c_type == "Variable":
                    var_name = cond.get("variable", "")
                    var_type = "string"
                    var_val = "0"
                    for v in getattr(map_screen, "script_variables", []):
                        if v["name"] == var_name:
                            var_type = v["type"]
                            var_val = v["value"]
                            break
                            
                    if var_type in ["int", "double"]:
                        try:
                            # Int truncates internally for execution
                            current_v = int(float(var_val)) if var_type == "int" else float(var_val)
                            check_v = int(float(c_val.strip())) if var_type == "int" else float(c_val.strip())
                            
                            if "BETWEEN" in c_op:
                                parts = c_val.split(",")
                                if len(parts) >= 2:
                                    v1 = int(float(parts[0].strip())) if var_type == "int" else float(parts[0].strip())
                                    v2 = int(float(parts[1].strip())) if var_type == "int" else float(parts[1].strip())
                                    if c_op == "BETWEEN (INC)":
                                        res = (v1 <= current_v <= v2)
                                    else:
                                        res = (v1 < current_v < v2)
                            else:
                                if c_op == "==": res = (current_v == check_v)
                                elif c_op == "!=": res = (current_v != check_v)
                                elif c_op == ">": res = (current_v > check_v)
                                elif c_op == "<": res = (current_v < check_v)
                                elif c_op == ">=": res = (current_v >= check_v)
                                elif c_op == "<=": res = (current_v <= check_v)
                        except ValueError:
                            res = False
                    else:
                        if c_op == "==": res = (str(var_val) == str(c_val))
                        elif c_op == "!=": res = (str(var_val) != str(c_val))
                        
                elif c_type in ["At War With", "In Faction With", "Not In Faction With", "Has Truce With", "At Peace With", "Country Exists", "Country Doesn't Exist", "Occupying Claims Of", "Occupying All Claims"]:
                    targets = [t.strip() for t in str(c_val).split(",") if t.strip()]
                    if not targets:
                        res = False
                    elif c_type == "At War With":
                        res = all(t in active_nations and queries.are_at_war(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "In Faction With":
                        res = all(t in active_nations and queries.are_in_same_faction(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "Not In Faction With":
                        res = all(t in active_nations and not queries.are_in_same_faction(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "Has Truce With":
                        res = all(t in active_nations and queries.has_active_truce(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "At Peace With":
                        res = all(t in active_nations and not queries.are_at_war(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "Country Exists":
                        res = all(t in active_nations for t in targets)
                    elif c_type == "Country Doesn't Exist":
                        res = all(t not in active_nations for t in targets)
                    elif c_type == "Occupying Claims Of":
                        res = all(any(map_screen.id_to_province.get(pid, {}).get("owner") == nation_name for pid in map_screen.nation_data.get(t, {}).get("claims", [])) for t in targets)
                    elif c_type == "Occupying All Claims":
                        res = all(map_screen.nation_data.get(t, {}).get("claims") and all(map_screen.id_to_province.get(pid, {}).get("owner") == nation_name for pid in map_screen.nation_data.get(t, {}).get("claims", [])) for t in targets)
                elif c_type == "True":
                    res = True
                elif c_type == "False":
                    res = False
                elif c_type == "Received Action":
                    pend_act, pend_turns = queries.get_diplomatic_status(c_val, nation_name, map_screen.nation_data)
                    res = (pend_act == c_op and pend_turns > 0)
                elif c_type == "Occupying All Cores Of":
                    res = queries.is_occupying_all_cores(nation_name, c_val, map_screen.map_data)
                elif c_type == "Occupying Tile":
                    res = queries.is_occupying_tiles(nation_name, c_val, map_screen.id_to_province)
                elif c_type == "Is AI Controlled":
                    target_check = c_val if c_val else nation_name
                    res = (target_check not in human_players and target_check in active_nations)
                elif c_type == "Is Player Controlled":
                    target_check = c_val if c_val else nation_name
                    res = (target_check in human_players and target_check in active_nations)
                elif c_type == "Occupying Core Of":
                    res = any(p.get("owner") == nation_name and c_val in p.get("cores", []) for p in map_screen.map_data.values())
                elif c_type == "Bordering":
                    res = c_val in queries.get_neighboring_nations(nation_name, map_screen.map_data, map_screen.id_to_province)
                elif c_type == "Not Bordering":
                    res = c_val not in queries.get_neighboring_nations(nation_name, map_screen.map_data, map_screen.id_to_province)
                elif c_type == "Is At War":
                    target_check = c_val if c_val else nation_name
                    res = len(queries.get_enemies(target_check, map_screen.nation_data)) > 0
                elif c_type == "Is At Peace":
                    target_check = c_val if c_val else nation_name
                    res = len(queries.get_enemies(target_check, map_screen.nation_data)) == 0
                elif c_type == "Is In Faction":
                    target_check = c_val if c_val else nation_name
                    res = map_screen.nation_data.get(target_check, {}).get("faction", "") != ""
                elif c_type == "Is Faction Leader":
                    target_check = c_val if c_val else nation_name
                    res = queries.is_faction_leader(target_check, map_screen.nation_data)
                    
                if c_idx == 0:
                    overall_met = res
                else:
                    if chain == "AND": overall_met = overall_met and res
                    elif chain == "OR": overall_met = overall_met or res
                    elif chain == "XOR": overall_met = overall_met ^ res
                    elif chain == "NOR": overall_met = not (overall_met or res)
                    elif chain == "NAND": overall_met = not (overall_met and res)
                    
            if overall_met:
                actions = evt.get("actions", [])
                if not actions and "action_type" in evt:
                    actions = [{"type": evt["action_type"], "target": evt.get("action_target", "None")}]
                
                pending = data.setdefault("pending_diplomacy", {})
                
                for act in actions:
                    a_type = act.get("type")
                    raw_targets = act.get("target", "None")
                    
                    if a_type in ["Edit Name", "Edit Leader Name", "Edit Leader Title", "Edit Color", "Edit Flag", "Edit Portrait"]:
                        val = act.get("message", "")
                        if not val: continue
                        
                        if a_type == "Edit Name":
                            data["name"] = val
                        elif a_type == "Edit Leader Name":
                            data["leader_name"] = val
                        elif a_type == "Edit Leader Title":
                            data["leader_title"] = val
                        elif a_type == "Edit Flag":
                            data["flag_data"] = val
                        elif a_type == "Edit Portrait":
                            data["portrait_data"] = val
                        elif a_type == "Edit Color":
                            try:
                                new_col = tuple(map(int, val.replace(" ", "").split(',')))
                                if len(new_col) == 3:
                                    data["color"] = list(new_col)
                                    if hasattr(map_screen, 'nation_colors'):
                                        map_screen.nation_colors[nation_name] = new_col
                                    map_screen.centers_need_update = True
                            except Exception:
                                pass
                        continue

                    if a_type == "Queue Claims":
                        prov_ids = [int(p.strip()) for p in str(act.get("message", "")).split(",") if p.strip().isdigit()]
                        for pid in prov_ids:
                            queue = data.setdefault("claim_queue", [])
                            if not any(q["prov_id"] == pid for q in queue) and pid not in data.get("claims", []):
                                queue.append({"prov_id": pid, "turns_left": c.CLAIM_TURN_NON_CORE})
                        continue

                    if a_type == "Revoke Claims":
                        prov_ids = [int(p.strip()) for p in str(act.get("message", "")).split(",") if p.strip().isdigit()]
                        revoke_queue = data.setdefault("revoke_queue", [])
                        for pid in prov_ids:
                            if not any(rq["prov_id"] == pid for rq in revoke_queue) and pid in data.get("claims", []):
                                revoke_queue.append({"prov_id": pid, "turns_left": 1})
                        continue

                    if a_type == "Revoke All Claims":
                        target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                        for a_target in target_list:
                            if a_target == "None": continue
                            t_data = map_screen.nation_data.get(a_target, {})
                            revoke_queue = t_data.setdefault("revoke_queue", [])
                            for pid in t_data.get("claims", []):
                                if not any(rq["prov_id"] == pid for rq in revoke_queue):
                                    revoke_queue.append({"prov_id": pid, "turns_left": 1})
                        continue

                    if a_type == "Give Territory":
                        target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                        tiles = [t.strip() for t in str(act.get("message", "")).split(",") if t.strip()]
                        must_control = act.get("ai_generate", False)
                        from map_logic.turn_processing import edit_province_ownership
                        for a_target in target_list:
                            if a_target == "None": continue
                            for tile_id in tiles:
                                if not tile_id.isdigit(): continue
                                prov = map_screen.id_to_province.get(int(tile_id))
                                if prov:
                                    if must_control and prov.get("owner") != nation_name:
                                        continue
                                    edit_province_ownership.conquer_province(map_screen, prov, a_target)
                        continue

                    if a_type == "Spawn Unit":
                        target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                        unit_type = act.get("unit_type", "Infantry Type 1910")
                        tiles = [t.strip() for t in str(act.get("message", "")).split(",") if t.strip()]
                        must_control = act.get("ai_generate", False)
                        for a_target in target_list:
                            if a_target == "None": continue
                            for tile_id in tiles:
                                if not tile_id.isdigit(): continue
                                prov = map_screen.id_to_province.get(int(tile_id))
                                if prov:
                                    if must_control and prov.get("owner") != nation_name:
                                        continue
                                    new_unit = queries.create_unit_dict(unit_type, a_target, queries.get_unit_library())
                                    prov.setdefault("units", []).append(new_unit)
                        continue
                    
                    if a_type == "Set Variable":
                        var_name = act.get("target")
                        op = act.get("unit_type", "Set")
                        msg_val = act.get("message", "0")
                        
                        for v in getattr(map_screen, "script_variables", []):
                            if v["name"] == var_name:
                                var_type = v["type"]
                                if var_type in ["int", "double"]:
                                    try:
                                        current_v = float(v["value"])
                                        change_v = float(msg_val)
                                        
                                        if op == "Set":
                                            current_v = change_v
                                        elif op == "Add":
                                            current_v += change_v
                                        elif op == "Subtract":
                                            current_v -= change_v
                                        elif op == "Multiply":
                                            current_v *= change_v
                                        elif op == "Divide" and change_v != 0:
                                            current_v /= change_v
                                            
                                        if var_type == "int":
                                            v["value"] = str(int(current_v))
                                        else:
                                            v["value"] = str(current_v)
                                    except ValueError:
                                        pass
                                else:
                                    if op == "Set":
                                        v["value"] = str(msg_val)
                                break
                        continue
                    
                    # Supports comma-separated targets for simultaneous multi-country actions
                    target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                    
                    for a_target in target_list:
                        if a_target == "None": continue

                        # Answering a proposal is its own channel, not a pending action
                        if a_type in ("Accept Proposal", "Reject Proposal"):
                            pend_act, pend_turns = queries.get_diplomatic_status(a_target, nation_name, map_screen.nation_data)
                            if pend_turns > 0 and pend_act in c.BILATERAL_ACTIONS:
                                verdict = diplomacy_messages.RESPONSE_ACCEPT if a_type == "Accept Proposal" else diplomacy_messages.RESPONSE_REJECT
                                their_req = diplomacy_messages.get_pending(map_screen.nation_data, a_target, nation_name)
                                diplomacy_messages.set_response(
                                    map_screen.nation_data, nation_name, a_target, verdict, pend_act,
                                    message=act.get("message", ""), parameters=their_req.get("parameters"))
                            continue

                        eng_action = ""
                        if a_type == "Declare War": eng_action = "WAR_DECLARATION"
                        elif a_type == "Join Faction": eng_action = "JOIN_FACTION_REQ"
                        elif a_type == "Create Faction": eng_action = "CREATE_FACTION"
                        elif a_type == "Invite to Faction": eng_action = "FACTION_INVITE"
                        elif a_type == "Send Ceasefire": eng_action = "CEASEFIRE"
                        elif a_type == "Send Custom Message": eng_action = f"MSG:{act.get('message', '')}"

                        if eng_action:
                            already_queued = (a_target in pending and isinstance(pending[a_target], dict) and pending[a_target].get("action") == eng_action)
                            if not already_queued:
                                custom_msg = act.get("message", "")
                                ai_generate = act.get("ai_generate", False)

                                pending[a_target] = {
                                    "action": eng_action,
                                    "turns": 0,
                                    "timer": 0,
                                    "message": custom_msg
                                }

                                if ai_generate:
                                    action_context = ai_prompts.get_proactive_action_context(eng_action, a_target)

                                    fallback = custom_msg if custom_msg else "We have sent a diplomatic missive."
                                    map_screen.proactive_llm_tasks.append({
                                        "sender": nation_name,
                                        "target": a_target,
                                        "context": action_context,
                                        "fallback": fallback,
                                        "action_type": eng_action
                                    })
                            
                if evt.get("fire_once", True) and i not in fired_events:
                    fired_events.append(i)