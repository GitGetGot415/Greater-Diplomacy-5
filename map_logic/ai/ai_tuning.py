"""AI tuning: weights, thresholds, and limits that only map_logic/ai/ reads.

AI values that other systems also read stay in data/constants.py.
"""

# ==========================================
# STARTING GAME RULES & TIMING
# ==========================================
AI_RESEARCH_FUNDING_RATE = 0.10

# ==========================================
# WAR SCORE (LEVERAGE)
# ==========================================
# What the AI weighs a demand against: its opponent's leverage, plus its own
# appetite for getting out. Leverage takes this share and appetite the rest. A
# cautious nation wants a bigger cushion before it signs, which is what the
# margin scales with.
AI_PEACE_LEVERAGE_SHARE = 0.6
AI_PEACE_MARGIN_BASE = 0.08
AI_PEACE_MARGIN_CAUTION = 0.12

#: What a nation still expects to win by fighting on, as a share of its own
#: leverage. This is the price of *stopping*, and it did not exist: peace itself
#: was free, so a nation overrunning its enemy would sign a white peace for one
#: material and call it a gain. A winner now has to be offered more than the war
#: is still worth to it.
#:
#: At 0.5 a clear winner refused almost everything: on saves/same peace deals the
#: German Reich, at 90% leverage, turned down 65 provinces from the Soviet Union.
#: This is honestly a pretty reasonable stance, given that if you're winnning, you
#: might not feel the need to make a peace deal with someone you know you can get
#: more out of.
#: At 0.15 a winner takes a small concession of land but still refuses a white
#: peace or a token offer. At 0 it would take a white peace, which is the free
#: peace this term exists to prevent.
#: 0.5 seems more realistic
AI_PEACE_PRIZE_W = 0.5

#: The hard ceiling on a demand: you may ask for at most this multiple of the
#: share of their homeland you actually occupy. Slightly over 1 so that having
#: overrun a country lets you annex a little more of it than you are literally
#: standing on -- that margin is what surrendering costs.
#:
#: This is the rule that stops an army that has not landed in Britain being
#: handed Britain, and it is read off raw occupation rather than off the
#: leverage bar, because the bar is a *share* and two sides who have taken
#: nothing from each other still read 0.5 each.
AI_PEACE_LAND_ALLOWANCE = 1.25
#: Floor, so a nation who is not winning can still ask for a token indemnity.
AI_PEACE_MIN_ALLOWANCE = 0.03

#: How much of a territorial demand a payment is allowed to buy off. Materials
#: and provinces are both priced in the same currency above, which means that
#: without a cap a large enough warchest simply purchases a country. The prices
#: themselves now say that land outlasts goods; this says that even at the right
#: price, land is not straightforwardly for sale.
AI_PEACE_CASH_OFFSET_CAP = 0.15

#: How the slack either side of the accept/refuse line is read back to the
#: player. Each row is (slack at or above which this applies, filled dots, text).
#: Ordered best first. Anything below the last row is the last row.
AI_VERDICT_BANDS = (
    (0.20, 5, "They will almost certainly accept"),
    (0.05, 4, "They would probably accept"),
    (-0.05, 3, "This could go either way"),
    (-0.20, 2, "They would probably refuse"),
    (-99.0, 1, "They will refuse outright"),
)

# How willing a bound faction member is to swallow terms its leader signed on
# its behalf. Above 1.0 it wants to be keener on peace than the deal costs it;
# below, it gives its leader the benefit of the doubt. Refusing means leaving
# the faction and fighting on alone, so the bar is not high.
AI_RATIFY_STRICTNESS = 0.8

#: Leverage a nation needs before it asks for land rather than the status quo.
#: Below this an army that has taken a few tiles offers a white peace instead of
#: a demand it would only be refused for.
#:
#: Lower than it was. A white peace used to be free for the winner -- the map
#: stood as the armies had left it -- so holding out for one cost nothing. Now
#: that unnamed occupied land returns to its pre-war owner, an army that signs a
#: white peace hands back everything it took, so anyone actually holding enemy
#: ground should be asking to keep it.
AI_PEACE_DEMAND_LEVERAGE = 0.55

# ==========================================
# AI CONFIGURATION
# ==========================================
# --- NEW: Expeditionary Force Weight ---
# A higher number means the AI prefers defending its own borders over helping allies.
# 5 means it will secure its own borders with at least 5 units before sending units away.
AI_EXPEDITION_WEIGHT = 5

# ==========================================
# AI PERSONALITY (map_logic/ai/ai_personality.py)
# ==========================================
# What counts as a trait worth mentioning when describing a nation: at least
# this far from the average of 0.5, in either direction.
AI_TRAIT_NOTABLE_MARGIN = 0.18

AI_RELATION_FACTION_THRESHOLD = 50

AI_CLAIM_COOLDOWN = 12 # How many turns the AI waits before trying to fabricate another claim

# ==========================================
# AI DESIRE WEIGHTS (map_logic/ai/ai_opinion.py)
# ==========================================
# War used to be two thresholds and nothing else. These turn the same
# quantities into degrees, and add the things the old logic had no way to say:
# that we like them, that we are already fighting two wars, that we promised not
# to. The odds terms and the appetite terms each sum to 1.0, so a nation with
# perfect odds and maximum appetite sits at 2.0 before restraint pulls it back.

# How the two halves of the decision trade off. They are averaged rather than
# added -- see the note in war_desire -- so odds take this share and appetite the rest.
AI_WAR_ODDS_SHARE = 0.55    # can we win, against do we want to

AI_WAR_BORDER_SHARE = 0.6   # local superiority on the shared front; overall alliance and economic weight takes the rest
AI_ODDS_STEEPNESS = 6.0     # how sharply confidence turns over around the crossover

AI_W_CLAIM = 0.45           # how much of their land we already claim
AI_W_AGGRO = 0.35           # temperament, independent of the odds
AI_W_AMBITION = 0.20        # appetite for land we have no claim on yet

AI_W_RELATION = 0.55        # good relations suppress war. Previously: nothing did.
AI_W_OVEREXTENSION = 0.45   # every war already being fought makes the next one less appealing
# A guarantee is a credible extra enemy, even where that guarantor does not
# share the target's border. ai_opinion scales this by the guarantor's power.
AI_GUARANTEE_RESTRAINT = 0.55

# Measured over 20 turns of the 1939 scenario against the old boolean, which
# declared 33 wars and ended 8. This gives 23 declared and 7 ended: a
# noticeably less trigger-happy world where a larger share of wars actually
# resolve, without making it inert. 0.62 gives 16/6 and 0.70 gives 11/7, both
# too quiet for a scenario that should catch fire.
AI_WAR_DESIRE_THRESHOLD = 0.55
# Lower than the war bar: fabricating a claim is a step toward a war, taken
# before the odds are settled, and it is how a war becomes legal at all.
AI_CLAIM_DESIRE_THRESHOLD = 0.45
AI_WAR_LOAD_SATURATION = 3.0    # wars at which a nation counts as fully committed

# Peace. Losing and cautious push toward the table.
#
# There used to be a third term, war weariness: a counter of how many turns a
# war had run, which by itself pushed any war older than twenty-five turns
# toward a settlement whoever was winning it. Nobody asked for the mechanic and
# it was doing real damage -- at 0.35 it was the second-heaviest weight here,
# so a nation overrunning its enemy would sue for peace on the strength of the
# calendar. Its weight is redistributed rather than replaced: a nation wants out
# of a war because it is losing one, not because it is bored of it.
AI_PEACE_LOSING_SHARE = 0.8  # losing takes this share of peace appetite; caution takes the rest
# How strongly losing its homeland pushes a nation toward peace, on top of
# losing the military balance. The two combine as independent pressures --
# losing = 1 - (1 - military) * (1 - AI_W_PEACE_OCCUPIED * occupied) -- so a
# nation with its land intact judges by its army exactly as before, while one
# whose heartland is overrun wants out even with an army still in the field.
# `occupied` is war_score's value-weighted share of the pre-war homeland the
# enemy side holds, the same figure under the war-score bar.
AI_W_PEACE_OCCUPIED = 1.0
# Peace decisions read each country's own view of the war (see
# ai_world.AIWorld.perceived_military). Under fog of war a country guesses the
# armies it cannot see, and its temperament bends the guess: the estimate is
# scaled by 1 + AI_PERCEPTION_SKEW * (caution - aggression), so a cautious
# country fears hidden armies and an aggressive one discounts them. This is
# what lets two countries at war read the same war differently.
AI_PERCEPTION_SKEW = 0.5
#
# AI_PEACE_CEASEFIRE_THRESHOLD, the bar appetite had to clear before a bare
# ceasefire was agreed, is gone with the shortcut that read it. A white peace is
# weighed like any other terms now -- against what the war is still worth to the
# side being asked -- so there is nothing left for a second threshold to decide.
# Removed rather than left sitting here: AI_PEACE_CEDE_LAND_THRESHOLD spent a
# release defined, commented, and wired to nothing at all.

# Trade. How much a good relationship discounts what we hand over.
AI_TRADE_GOODWILL_DISCOUNT = 0.5

# Alliances and faction invitations. Relations, scaled by trust, take this share;
# a shared enemy takes the rest.
AI_ALLY_RELATION_SHARE = 0.5
AI_ALLIANCE_DESIRE_THRESHOLD = 0.55

# How many proposals one nation may have in flight at once. The pass used to
# allow exactly one per target with no comparison between them, so whichever
# section ran first won the slot.
AI_MAX_ACTIONS_PER_TURN = 3

# Proposing a trade. Stock counts toward what a nation can spare, spread over
# this many turns, so a full warehouse is tradeable but not all at once.
AI_TRADE_STOCK_TURNS = 20.0
AI_TRADE_OFFER_FRACTION = 0.5
#: Below this an offer is too small to be worth sending. A *value*, priced in
#: the proposer's own materials, not a count of units: 250 fuel and 250 materials
#: are nothing like the same offer, and reading it as a count quietly barred
#: fuel-rich nations from proposing anything at all.
AI_TRADE_MIN_AMOUNT = 250

# How big an ask is, as a share of what the other side can spare -- and how much
# that share varies. It used to be the flat AI_TRADE_OFFER_FRACTION with nothing
# else in it, so every AI on the map requested the identical amount of the same
# player and the offers read as one copy-pasted message.
AI_TRADE_ASK_BASE_SHARE = 0.35  # a reasonable opening ask
# How far each pressure moves the ask: a pushy nation asks for more (ambition,
# centred on 0.5), a nation that likes you asks for less, and a nation
# genuinely short of the resource pushes harder.
AI_TRADE_ASK_SWING = 0.30
AI_TRADE_ASK_MIN_SHARE = 0.05
AI_TRADE_MAX_SHARE = 0.60       # never ask for more of their surplus than this
AI_TRADE_JITTER = 0.25
#: What the AI is willing to pay, as a multiple of what it is getting, priced in
#: its own scarcity terms. Base 1.0 is a straight swap of value for value; a
#: nation genuinely short of something will pay over the odds for it, up to the
#: ceiling.
#:
#: Nothing capped this before, and nothing even compared the two halves: the
#: amount offered was sized from the proposer's own surplus and the amount asked
#: for from the partner's, so a great power with materials in the tens of
#: thousands would offer all of them for whatever trickle of fuel its neighbour
#: could spare. 12,000 materials for 40 fuel is a real offer from a real save.
#: The rate tops out at base plus the full need premium, so the haggling
#: wobble (stable per pair per turn) never pays more than a nation in full need.
AI_TRADE_EXCHANGE_BASE = 1.0
AI_TRADE_EXCHANGE_NEED = 0.35
# Offers are round numbers, not spreadsheet output. Largest step the amount can
# carry wins, so a big offer lands on hundreds and a small one still survives.
AI_TRADE_ROUNDING_LADDER = (1000, 500, 100, 50, 25, 10, 5)

# ==========================================
# POLITICS (map_logic/politics.py, map_logic/ai/ai_politics.py)
# ==========================================
# --- What the AI aims for (map_logic/ai/ai_politics.py) ---
# The AI picks a target position on each axis and walks toward it, rather than
# picking a direction and running to the wall. Two nations in the same war end
# up in different places, and a nation that has arrived stops.

# Political: fully authoritarian, for fast and cheap coring, once this share of
# its land is uncored. Less uncored land leaves it proportionally nearer the
# libertarian end, where research is fastest.
POLITICS_AI_UNCORED_SHARE_FOR_AUTHORITY = 0.5

# Economic: fully planned, where non-core land stays productive, once this
# share of its land is non-core. Less leaves it proportionally nearer market.
POLITICS_AI_UNCORED_SHARE_FOR_PLANNING = 0.5

# Quality: how much of `danger` is "this war is going badly"; "there are several
# of them" takes the rest.
POLITICS_AI_LOSING_SHARE = 0.65

# Strategy: fully defensive once enemies hold this share of its cores.
POLITICS_AI_OCCUPIED_SHARE_FOR_DEFENSE = 0.25

# ==========================================
# LLM DIRECTOR (map_logic/ai/ai_director.py)
# ==========================================
# Per-country override of whether a nation is model-driven, stored on
# nation_data so it saves with everything else. AUTO defers to the global
# immersion level.
AI_TIER_AUTO = "AUTO"
AI_TIER_ALWAYS = "ALWAYS"
AI_TIER_NEVER = "NEVER"

# Who counts as a major power: the strongest handful, plus everyone whose doings
# a player would see anyway.
AI_MAJOR_POWER_FRACTION = 0.15
AI_MAJOR_POWER_MIN = 6
AI_MAJOR_POWER_MAX = 12
AI_MAJOR_POWER_PROVINCE_WEIGHT = 5.0   # size counts, but an army counts more

# The index the model answers with to decline to act. Must not collide with a
# candidate index, so it is not a number.
AI_DIRECTOR_NONE_CID = "none"

# A verdict at or above this confidence is stated to the model as settled and
# cannot be overruled -- those are structural rules, not judgement calls. Below
# it the recommendation is offered with its reasoning and the leader may differ.
AI_VERDICT_OVERRIDE_MAX_CONFIDENCE = 0.85

AI_REQUEST_LIFETIME = 3          # turns a filed request stays worth acting on

# How much the leader having asked for it counts. Enough to break a tie, not
# enough to carry a war the nation has no appetite for.
AI_LLM_REQUEST_BONUS = 0.25

# Countries with no mail waiting that still sit down to write in a turn,
# longest-waiting first. Countries with mail waiting always do.
AI_LETTER_WRITERS_PER_TURN = 6
AI_LETTERS_PER_CALL = 2          # letters one country may send from one sitting
AI_LETTER_LENGTH = 1200          # characters kept of one letter
AI_LETTER_THREAD_SHOWN = 6       # earlier letters shown per correspondent
AI_NOTEBOOK_LENGTH = 1500        # characters kept of a country's private notebook
# Countries whose recent letters give the director proposals of the country's
# own initiative, newest correspondence first.
AI_CORRESPONDENTS_MAX = 4

# How each action reads in a prompt or an event log.
AI_ACTION_PHRASES = {
    "WAR_DECLARATION": "declare war on",
    "CEASEFIRE": "offer a ceasefire to",
    "PEACE_TREATY": "offer peace terms to",
    "JOIN_FACTION_REQ": "ask to join the faction of",
    "CREATE_FACTION": "propose founding a faction with",
    "FACTION_INVITE": "invite into our faction",
    "CALL_TO_ARMS": "call to arms",
    "JOIN_WARS": "offer to join the wars of",
    "REQ_MILITARY_ACCESS": "request military access through",
    "SEND_MILITARY_ATTACHE": "send a military attaché to",
    "TRADE": "propose a trade with",
    "BREAK_ALLIANCE": "break our alliance with",
}

#: What each action does, said on the director's menu next to it. "call to
#: arms Italy" alone told the model nothing, and the Reich wrote its call to
#: arms as a "joint training exercise". {enemy} is the war the option is about.
#:
#: No pronoun stands for the recipient: the model copies these into its
#: message, and "cross their territory" became "military access through France
#: to let our troops cross their territory", written to France.
AI_ACTION_EFFECTS = {
    "WAR_DECLARATION": "this message announces the war; it is not an offer and cannot be refused",
    "CALL_TO_ARMS": "a request to join your war against {enemy}",
    "JOIN_WARS": "an offer to declare war on {enemy} too",
    "REQ_MILITARY_ACCESS": "a request for passage for your troops to reach {enemy}",
}

#: {enemy} in AI_ACTION_EFFECTS when an option names no particular war.
AI_ACTION_EFFECT_ENEMY = {
    "CALL_TO_ARMS": "your enemies",
    "JOIN_WARS": "the same enemies",
    "REQ_MILITARY_ACCESS": "your enemies",
}

#: Proposals that mirror one another. A nation is not offered one to a country
#: whose mirror of it is already waiting for its answer (see
#: ai_candidates.mirrors_waiting_proposal): it answers that one instead.
AI_MIRRORED_PROPOSALS = {
    "REQ_MILITARY_ACCESS": ("REQ_MILITARY_ACCESS",),
    "CALL_TO_ARMS": ("JOIN_WARS",),
    "JOIN_WARS": ("CALL_TO_ARMS",),
    # Spain refused the German Reich's invitation into the Axis and asked to
    # join the Axis in the same turn.
    "FACTION_INVITE": ("JOIN_FACTION_REQ",),
    "JOIN_FACTION_REQ": ("FACTION_INVITE",),
    "CREATE_FACTION": ("CREATE_FACTION",),
    # A country holding the enemy's peace terms answers them rather than
    # writing its own back across the table in the same turn.
    "PEACE_TREATY": ("PEACE_TREATY", "CEASEFIRE"),
    "CEASEFIRE": ("CEASEFIRE", "PEACE_TREATY"),
}

# Baseline desirability for actions with no appetite function of their own.
# Access is cheap to ask for and often the difference between being able to
# fight a shared war at all -- but it is a tactical convenience, and loses to
# anything that changes who a nation's friends are.
AI_SCORE_MILITARY_ACCESS = 0.55

# A nation at war with no allies at all wants that fixed more than it wants
# anything else, whatever it happens to think of the only bloc on offer.
AI_SCORE_DEFENSIVE_FACTION = 0.78
AI_SCORE_CALL_TO_ARMS = 0.50
AI_SCORE_JOIN_WARS = 0.45
AI_SCORE_CEASEFIRE_UNREACHABLE = 0.80   # a war we physically cannot fight is pure cost
AI_SCORE_TRADE = 0.40                   # useful, rarely urgent
AI_SCORE_CLAIM_LEADERSHIP = 0.70        # six turns in the making; do not sit on it

# How badly a war must be going before the AI sues for peace. Below the bar at
# which it would accept a ceasefire offered to it: asking costs standing, so it
# waits a little longer than it would to say yes.
AI_PEACE_OFFER_THRESHOLD = 0.62

MIN_TURNS_FOR_CEASEFIRE = 6 # Turns that must occur before the ai allows ceasefires

# ==========================================
# FACTION LEADERSHIP
# ==========================================
#: How ambitious an AI has to be to take the chair when it could. A content
#: nation stays a follower even at the head of the strongest army in the bloc.
AI_CLAIM_LEADERSHIP_AMBITION = 0.45

# ==========================================
# AI UNIT VALUATION (map_logic/ai/ai_unit_eval.py)
# ==========================================
# Same "wounded" line, spent on repairing instead of rotating: below this share
# of health and out of combat, the AI sends a unit to repair -- see
# ai_movement._assign_maintenance_orders. Matches AI_ROTATE_HEALTH_FRACTION by
# default since it is the same judgement (a unit this hurt deals reduced
# damage -- see combat_rules.health_damage_multiplier -- and is worth less in a
# fight than it would be back at full health), kept as its own constant so the
# two can be tuned apart.
AI_REPAIR_HEALTH_FRACTION = 0.4

# The same judgement made for a unit that is already standing somewhere it can
# be repaired. Walking a division home costs it several turns of marching, so
# that needs a badly hurt unit to be worth it; sitting on the factory already,
# the turn costs nothing but the turn. Anything short of full health was
# arguably right here, but a unit at 95% is not worth a turn out of the line.
AI_REPAIR_ON_SITE_FRACTION = 0.8

# Share of a nation's ground and naval units that may be on a repair trip at
# once (at least one). The repair trip is the only order in the AI that
# deliberately moves a unit AWAY from the war, so it is capped rather than
# trusted: without this a bad turn at the front would rout an entire army into
# the rear as a maintenance decision. A share rather than a count, because a
# fixed two let a hundred-division army fix two divisions at a time.
AI_MAX_REPAIR_TRIP_SHARE = 0.15

# How many exchanges ahead the AI looks when deciding a battle is lost (see
# ai_movement._tile_is_lost). The forecast is the shared one Manage Battle
# shows. Longer sees a slow defeat sooner but also gives up fights a
# reinforcement could still have turned.
AI_RETREAT_FORECAST_TURNS = 3

# What a unit contributes, given how combat actually resolves:
#  - only a lane's front rank deals damage -- LANE_SLOTS_TYPICAL of them in an
#    ordinary one-enemy fight -- so offence is raw attack
#  - incoming damage is split across the enemy front IN THAT LANE, then each
#    subtracts its own defense flat, so a cheap high-defense body is worth far
#    more than its stats suggest
# Offense and durability each count once, measured against the mean of the
# units on offer. The weights below are relative to that.
AI_W_TRANSPORT = 1.0  # Cargo capacity and flight reach determine transport utility.
# Flat, not scaled by health: damage is divided by the number of defenders in the
# lane, so every body in the front rank thins the volley for that rank by the
# same amount whatever it is made of. A body PAST the front thins nothing at all
# -- that is what AI_RESERVE_DEPTH is for, and why this is no longer a reason to
# buy bodies without limit. Its real effect is to make cheap units better value
# per point of pain, up to the depth the tile can use.
AI_W_SOAK = 0.35
AI_W_BOMBARD = 0.6      # bombardment sits outside every lane and takes no return fire

# Floor on the damage a unit takes, as a fraction of its share of the volley.
# Without it, defense >= share divides by zero and an unkillable unit scores
# infinitely; with it, stacking defense has strong but finite returns.
AI_MIN_DAMAGE_FRACTION = 0.10

# A unit that takes ten turns to build is worth less than the same value
# arriving now. 0.5 = value scales with the square root of build time.
AI_TIME_EXPONENT = 0.5

# Turns of upkeep counted against a unit's purchase price.
AI_UPKEEP_HORIZON = 20

# Floor on how scarce a resource can get, so pricing saturates instead of
# dividing by zero when a nation has no income and no stockpile of something.
AI_MIN_RESOURCE_SLACK = 0.05

# Army composition. Targets are per frontline tile; a role at its target is
# multiplied by AI_ROLE_DIMINISH, so roles trade off against each other instead
# of being bought to a hardcoded ratio.
AI_ROLE_DIMINISH = 0.35

# How much to spend on depth versus firepower, as a ratio of resources -- NOT of
# unit counts. Only a lane's front rank fires, so the assault target is a count
# the combat rules hand us directly; bodies then get a comparable share of the
# budget, which at 1.0 means "about as much again".
#
# It has to be expressed as spend rather than as a number of units, because a
# heavy tank costs seventeen infantry. A count-based depth target quietly
# committed 90% of the budget to armour and produced an army that lost to every
# mixed composition in a round-robin under the real combat rules.
#
# 2.0 was picked by measurement under the model the lane system replaced, where
# an extra body always thinned somebody's volley and depth therefore had
# unbounded if diminishing value. It does not any more: useful line bodies are
# LANE_SLOTS_TYPICAL x frontline x (AI_RESERVE_DEPTH - 1), which at depth 2.0 is
# the same count as the assault target, and a 1:1 spend split is what that
# implies. That is a derivation, not a measurement -- the harness the old number
# came from was run offline and does not exist in tests/.
AI_LINE_SPEND_RATIO = 1.0
# Guns went from support to the only thing that reaches a reserve, and deep
# reserve stacks are the formation the lane model encourages.
AI_BOMBARD_SPEND_RATIO = 0.25
AI_AIR_SPEND_RATIO = 0.25
AI_TRANSPORT_SPEND_RATIO = 0.05
AI_MIN_ROLE_TARGET = 2.0    # even a landlocked one-province nation wants a couple of each

# A unit is ASSAULT when this much of its combat value comes from attack rather
# than from staying alive and taking up space; everything else on land is a LINE
# body. Below 0.5 on purpose: a unit that does most of its work shooting still
# has to survive to do it, so the best attackers are never pure offence.
AI_ASSAULT_OFFENSE_SHARE = 0.45
# Front-slot quality: an assault unit's score is multiplied by its combat value
# relative to the assault mean, raised to this power, and it fills its role by
# that relative combat. A battle tile seats only a few units a side, so the
# unit in the slot matters more than its price per point suggests. At 0, cost
# per point decides alone and cheap infantry wins every slot. Tuned over ten
# turns on a copy of saves/runv3: the purchase loop's ground buys went from
# under 1% armor at 0 to 17% at 1.0, 20% here and 22% at 1.5, where fuel
# rather than the score becomes the limit.
AI_SLOT_QUALITY_EXPONENT = 1.25

# Stop buying when the best remaining option is worth less than this fraction of
# the best option overall -- the AI has better uses for the resources.
AI_MARGINAL_FLOOR = 0.15

# Saving up. If the best unit the nation cannot yet afford is worth more than
# this much more than the best it can, it banks the turn's budget instead --
# but only when income actually closes the gap inside AI_SAVE_UP_TURNS, so a
# nation with no industry never sits waiting for a tank it will never afford.
AI_SAVE_UP_THRESHOLD = 0.6
AI_SAVE_UP_TURNS = 4

# Fallback for how hard the enemy hits when a nation is at peace and has no
# frontline to measure, expressed as a multiple of the mean buildable attack.
AI_PEACETIME_THREAT_MULTIPLIER = 3.0

# How few turns of stockpile a resource must be down to before the AI will give
# up a unit over it. AI_UPKEEP_TARGETS is a ratio of upkeep to income, which
# says nothing about whether a nation can actually pay -- and a nation losing a
# war fails it by definition, because the income is what the enemy is taking.
# France in saves/"france disbanding their tanks despite losing" was 36% over
# its materials target with 20,526 materials banked, about 25 turns of reserve,
# and scrapped a unit every turn of the invasion. Ratio says overspending;
# runway says running out. Only the second one is worth an army for.
AI_DISBAND_RUNWAY_TURNS = 8

AI_WAR_UPKEEP_MULTIPLIER = 1.5

AI_NAVY_PER_COAST_TILE = 0.5 # Warships wanted per coastal tile, as a role target
AI_CONVOY_ESCORT_WEIGHT = 1 # Negative weight to pull pathing warships towards convoys
AI_CONVOY_COMBAT_WEIGHT = 50 # MASSIVE priority to escort convoys actively being attacked
AI_CONVOY_DANGER_SHIP_WEIGHT = 25 # Priority for convoys near enemy ships
AI_CONVOY_DANGER_COAST_WEIGHT = 10 # Priority for convoys near enemy borders/coasts

AI_SEA_PATH_PENALTY_MULTIPLIER = 2.0 # Land troops prefer land routes unless sea is this much faster (2.0 = 2x faster)

AI_REINFORCE_COMBAT_WEIGHT = 20 # Pulls eligible units toward active battles
AI_REAR_GUARD_PENALTY = 50 # Pushes units off a quiet border once one is standing there
AI_COAST_GARRISON_TURNS = 3  # Stage a guard from this many turns away by land.
AI_SUPPLY_SEA_CANDIDATES = 12  # Limit alternate-route projections per country and order pass.

AI_MIN_COAST_FOR_NAVY = 8 # Tiles needed to justify building a navy

AI_MIN_MATERIALS_FOR_CONSTRUCTION = 15000

AI_SURPLUS_MANPOWER_FOR_CORING = 2000 # Manpower above this triggers AI to prioritize coring uncored provinces

# Stock thresholds for the AI's two economy conversions, conscription (manpower into
# materials) and fuel conversion (materials into fuel). A conversion is wanted when the
# product is short, the source is spare, and the source stock exceeds "min". It is an
# emergency when the source stock exceeds "panic" while the product stock is below
# "panic_product", or when the source stock exceeds "emergency" on its own.
AI_RESOURCE_CONVERSIONS = {
    "conscription": {"source": "manpower", "product": "materials", "min": 5000, "panic": 10000, "panic_product": 1000, "emergency": 50000},
    "fuel": {"source": "materials", "product": "fuel", "min": 500, "panic": 5000, "panic_product": 500, "emergency": 50000},
}

# How much an economic tech's per-turn yield counts against a military tech's
# one-off improvement to the units on offer. The two are in different units --
# income per turn versus a better division -- so this is the exchange rate
# between them, and raising it makes the AI build its economy before its army.
AI_TECH_ECONOMY_WEIGHT = 1.0

# How many of the RESEARCH_SLOTS are held for a tech that unlocks a unit.
# Economic techs are repeatable and compound, so on value alone they take every
# slot forever -- true enough about this economy, and a terrible way to fight a
# war. Which military tech fills the slot still comes from the valuation.
AI_RESEARCH_MILITARY_SLOTS = 1

# How many turns of extra income an economic tech is credited with. Longer means
# more willingness to invest in industry before army.
AI_TECH_ECONOMY_HORIZON = 30.0

# How hard a tech the world has already had pulls at an AI that has not got it.
#
# get_research_multiplier only ever punished being EARLY -- it returns a flat 1.0
# for anything historical, so a family a nation is a decade behind on scored
# exactly like one it was on schedule for, and nothing anywhere pulled it back
# towards the rest of the world. Combined with repeatable economic and infantry
# lines winning on raw value forever, that is how saves/AI IS FAR BEHIND ON
# RESEARCH ends 1920 with France on infantry_type 12 and resource_refining 11
# while its factory and tank lines sit at zero.
#
# One multiplier per year overdue, so a family at level 0 -- which takes its
# distance from level 1's year and is therefore the most overdue thing on the
# board -- gets the biggest pull, and breadth follows without a separate rule
# for it. The cap stops a 1900 tech in 2010 drowning out everything else.
AI_TECH_OVERDUE_WEIGHT = 0.15
AI_TECH_OVERDUE_CAP = 20

# How many years early a tech may be and still be treated as a real option.
# Progress halves per year early, so at eight the thing already costs 256 times
# its sticker price and a nation would not finish it inside the scenario. Past
# this it sorts behind everything reachable rather than being removed, because a
# nation with nothing else available should still pick it -- but it must never
# beat an on-schedule tech, which it could when the on-schedule one happened to
# be worth exactly zero and this one was worth an epsilon.
AI_TECH_EARLY_HORIZON = 8

# How long a BUILDING gets to earn back what it cost to put up. A separate
# number from the one above, which they used to share: that one scales an
# income stream against an army, while this one is a payback period, and a
# building keeps producing long after the thirty turns a division is costed
# against. At thirty every building in the game -- including the first Basic
# Factory -- read as a loss, which is the opposite of the error it was meant
# to correct. Sixty turns is roughly when a factory upgrade breaks even.
AI_BUILDING_PAYBACK_TURNS = 60.0

# How many building levels the AI will research ahead of what it has actually
# constructed. A province can only ever queue the next item in its chain, so
# research further ahead than this buys nothing it can act on for many turns.
# One spare level keeps the pipeline full without letting it run away.
AI_MAX_BUILDING_RESEARCH_LEAD = 1
