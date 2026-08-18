"""Assembling an itemized deal: the screen that replaced three buttons.

The peace screen offered Surrender / Demand Claims / Ceasefire and nothing else,
and which provinces moved was decided for you by whatever you happened to have
claimed. The trade screen offered four number boxes. Between them that was the
whole vocabulary of the diplomacy: you could not cede one province, or ask for
reparations, or trade a border town for fuel, or say "keep your capital, give me
the coast".

One screen builds both now, because a peace treaty and a trade are the same
document -- a list of terms and two sides -- and only peace adds that the war
ends. What you assemble here is exactly what map_logic/diplomacy/deal.py
executes, and the acceptance line under it asks the same function the engine
will ask when the answer comes back. That last part is not a nicety: the old
screen called queries.will_ai_accept_peace while the engine called
ai_opinion.accepts_peace, so it could tell you "the AI will REJECT this" and
then watch the AI accept it.

Everything on it is measured against `deal.baseline_owners` -- the map this
treaty starts from, which for a peace is the pre-war border rather than the
front line, because unnamed occupied land goes home when the fighting stops.
That rule used to live only in deal_effects, so this screen priced, drew and
explained a different treaty from the one the engine carried out.
"""

import pygame

import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from map_logic.ai import ai_opinion, ai_world
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import diplomacy_messages, peace_scope, reach, war_score
from map_logic.rendering import overlay_renderer, refresh_map
from map_logic.rendering.font_manager import fonts
from screens.map_related_screens.diplomacy_screen_widgets import build_choice_button
from ui import text_utils
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from ui_elements import Button, draw_text_box, process_text_input

#: Which side of the table a picked province belongs to.
TAKE = "TAKE"
GIVE = "GIVE"

_HIGHLIGHT_TAKE = (90, 220, 120)
_HIGHLIGHT_GIVE = (235, 110, 110)
#: A pick that changes nothing -- the baseline already hands it to the nation it
#: is assigned to. Drawn muted rather than hidden, so "why is this not counting"
#: has an answer on screen.
_HIGHLIGHT_MOOT = (140, 140, 140)

#: What the recipient control says when nobody has been chosen for a column.
AUTO = "Auto (pre-war owner)"


def _digits(text):
    """An amount as it should be shown while it is being typed.

    Only the leading zeros come off, one keystroke at a time, so this never
    fights the typist: "0" then "9" gives "9", and an emptied box reads as zero
    through _amount rather than snapping back to a "0" the next digit would sit
    behind. The field accepted digits and tidied nothing, so a box starting at
    "0" turned into "0999" the moment anybody typed a number into it.
    """
    trimmed = text.lstrip("0")
    return trimmed if trimmed or not text else "0"


def _thousands(number):
    return f"{int(number):,}"


def _bloc_name(nation_data, side):
    """What to call a side: its faction if it has one, otherwise its leader."""
    for member in side:
        faction = nation_data.get(member, {}).get("faction", "")
        if faction:
            return faction
    return side[0] if side else "?"


class Deal_Screen(MapOverlayScreen):
    # Docked low and translucent so the map stays readable and clickable --
    # provinces are picked by clicking them, the same way claims always were.
    CENTER_PANEL = False
    overlay_alpha = 0
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_CONFIRM_OVER_MAP

    #: Which text attribute each editable box writes to, and what it will accept.
    FIELD_ATTRS = {
        "TAKE_MATS": "take_mats_str",
        "TAKE_FUEL": "take_fuel_str",
        "GIVE_MATS": "give_mats_str",
        "GIVE_FUEL": "give_fuel_str",
        "NOTE": "note",
    }

    #: The four of those that hold a quantity, and what quantity: (column,
    #: resource). Which column a box is in decides who pays out of it, and
    #: therefore whose output caps it.
    AMOUNT_FIELDS = {
        "TAKE_MATS": (TAKE, "materials"),
        "TAKE_FUEL": (TAKE, "fuel"),
        "GIVE_MATS": (GIVE, "materials"),
        "GIVE_FUEL": (GIVE, "fuel"),
    }

    # --- Layout ---------------------------------------------------------
    # Every offset below is from the panel's own top-left, and no two of them
    # overlap. The panel used to be 285px tall and they did, badly: the 28px
    # column headings were blitted four pixels above the 18px row labels at the
    # same x, so "YOU RECEIVE" and "Provinces:" were printed on top of each
    # other; the hint line landed inside the first toggle button; the verdict
    # clipped the Send button; and the Send button itself hung six pixels below
    # the panel. Anything with a variable length -- a bloc roster, a verdict
    # sentence -- is passed through text_utils rather than trusted to fit, and
    # LayoutTests fails on any two controls sharing ground.
    WIDTH, HEIGHT = 920, 392
    PAD = 30                #: left margin inside the panel
    COL_W = 300             #: the RECEIVE and GIVE columns
    LABEL_W = 120           #: room for "Provinces:" before its control
    Y_BAR = 56              #: leverage bar
    Y_BREAKDOWN = 76        #: its component line, which also names bound members
    Y_HEADINGS = 98
    Y_RECIPIENT = 128       #: who each column's provinces actually go to
    Y_PROVINCES = 162       #: pick buttons; their labels sit 10px lower
    Y_MATERIALS = 208
    Y_FUEL = 238
    Y_NOTICE = 270          #: "demand all I hold", what would revert, "clear"
    Y_NOTE = 304
    Y_BUTTONS = 336
    Y_VERDICT = 334
    VERDICT_LINES = 2       #: the sentence is long and worth reading in full
    VERDICT_LINE_H = 17
    ROW_H = 26              #: a text box
    TOGGLE_H = 30

    #: The recipient popup. It sits *above* the panel, in the map strip, so it
    #: cannot land on any of the controls it is opened from.
    LIST_W = 230
    LIST_ROW_H = 26
    LIST_ROWS = 7           #: shown at once; the wheel moves the window a row
    HINT_H = 16             #: the "N more" line under them, when there are more

    def __init__(self, map_screen, target_nation, kind=deal_mod.KIND_PEACE):
        super().__init__(map_screen, pygame.Rect(
            c.SCREEN_WIDTH // 2 - self.WIDTH // 2,
            c.SCREEN_HEIGHT - c.BOT_UI_HEIGHT - self.HEIGHT,
            self.WIDTH, self.HEIGHT))
        self.target_nation = target_nation
        self.kind = kind

        self.role = peace_scope.negotiation_role(self.player, target_nation,
                                                 map_screen.nation_data)
        self.my_side, self.their_side = peace_scope.deal_sides(
            self.player, target_nation, map_screen.nation_data, self.role)

        # One snapshot for the whole session. The map cannot change while this
        # screen is open, and building one per keystroke to re-price the deal
        # would mean a full sweep of every province on every click.
        self.world = ai_world.for_screen(map_screen)
        # Same reasoning, and the same lifetime: who can get where is a fact
        # about the map, and the map does not move while this screen is up.
        self.reach = reach.index(map_screen.map_data)
        self._baseline = None

        # {province id: the nation the player chose for it, or None for Auto}.
        # A set until territory could be routed anywhere but the obvious place.
        self.take_ids = {}
        self.give_ids = {}
        self.take_mats_str = "0"
        self.take_fuel_str = "0"
        self.give_mats_str = "0"
        self.give_fuel_str = "0"
        self.vassalize = False
        self.demilitarize = False
        self.military_access = False
        self.note = ""
        self.recipients = {TAKE: None, GIVE: None}

        self.picking = None       # TAKE / GIVE while the map is being clicked
        self.active_input = None
        self.list_open = None     # TAKE / GIVE while the recipient list shows
        self.list_scroll = 0
        self._preview = None

        self._load_existing_offer()
        self._load_draft()
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                             STATE                                   #
    # ------------------------------------------------------------------ #

    @property
    def is_peace(self):
        return self.kind == deal_mod.KIND_PEACE

    def baseline_owners(self):
        """Who holds each province if this deal names no land at all.

        For a peace that is the pre-war map between the two sides, because
        unnamed occupied land goes home when the fighting stops. Cached for the
        session: the map cannot change while this screen is open, and this is
        read on every click.
        """
        if self._baseline is None:
            self._baseline = deal_mod.baseline_owners(
                deal_mod.new(self.kind, self.my_side, self.their_side, []),
                self.map_screen.map_data, self.map_screen.nation_data)
        return self._baseline

    def _load_existing_offer(self):
        """Reopens an offer already queued, so editing it starts from its terms."""
        pending = diplomacy_messages.get_pending(self.map_screen.nation_data,
                                                 self.player, self.target_nation)
        self.is_editing = pending.get("action") in ("PEACE_TREATY", "CEASEFIRE", "TRADE")
        if not self.is_editing:
            return

        self.note = pending.get("note", "") or ""

        existing = pending.get("parameters")
        if not deal_mod.is_deal(existing):
            return

        for clause in deal_mod.clauses(existing):
            kind = clause.get("type")
            if kind == deal_mod.TILES:
                receiver = clause.get("to")
                bucket = self.take_ids if receiver in self.my_side else self.give_ids
                for prov_id in clause.get("ids", []):
                    bucket[int(prov_id)] = receiver
            elif kind == deal_mod.RESOURCES:
                side = "take" if clause.get("to") in self.my_side else "give"
                short = "mats" if clause.get("resource") == "materials" else "fuel"
                setattr(self, f"{side}_{short}_str", str(int(clause.get("amount", 0))))
            elif kind == deal_mod.VASSALIZE:
                self.vassalize = clause.get("master") == self.player
            elif kind == deal_mod.DEMILITARIZE:
                self.demilitarize = True
            elif kind == deal_mod.MILITARY_ACCESS:
                self.military_access = True

    # --- the draft, kept between openings ------------------------------
    # Assembling a bloc peace is not one sitting: you go and look at the front,
    # count what you are holding, come back. Closing the screen threw all of it
    # away, so checking the map cost you the terms. A draft survives until the
    # turn ends, and no longer -- once the armies have moved the picked
    # provinces are about somebody else's map.

    #: Everything a draft carries. Kept as one list so saving and loading cannot
    #: drift apart and quietly lose a field.
    DRAFT_FIELDS = ("take_ids", "give_ids", "take_mats_str", "take_fuel_str",
                    "give_mats_str", "give_fuel_str", "vassalize", "demilitarize",
                    "military_access", "note", "recipients")

    def _draft_key(self):
        return (self.target_nation, self.kind)

    def _drafts(self):
        drafts = getattr(self.map_screen, "deal_drafts", None)
        if drafts is None:
            drafts = {}
            self.map_screen.deal_drafts = drafts
        return drafts

    def _turn(self):
        return queries.get_total_turns(self.map_screen.time_manager)

    def _save_draft(self):
        """Written on every change rather than on the way out, so it survives
        however the screen is closed."""
        draft = {field: getattr(self, field) for field in self.DRAFT_FIELDS}
        draft["turn"] = self._turn()
        self._drafts()[self._draft_key()] = draft

    def _load_draft(self):
        draft = self._drafts().get(self._draft_key())
        if not draft or draft.get("turn") != self._turn():
            self._drafts().pop(self._draft_key(), None)
            return
        for field in self.DRAFT_FIELDS:
            if field in draft:
                value = draft[field]
                setattr(self, field, dict(value) if isinstance(value, dict) else value)

    def _clear_draft(self):
        self._drafts().pop(self._draft_key(), None)

    def _amount(self, attr):
        try:
            return max(0, int(getattr(self, attr) or 0))
        except ValueError:
            return 0

    def payer_of(self, side):
        """Who actually hands over the goods in that column."""
        return self.player if side == GIVE else self.target_nation

    def cap_for(self, side, resource):
        """The most that column may move: one turn of the payer's output.

        world.economies is the same snapshot the AI prices against, computed
        once and held for the session -- calculate_all_economies is a sweep of
        every province on the map and this is read on every keystroke.
        """
        return deal_mod.resource_cap(self.payer_of(side), resource,
                                     self.world.economies)

    def over_cap(self):
        """Every amount typed past what its payer could deliver.

        [(side, resource, typed, ceiling)]. Shown rather than clamped as you
        type: rewriting "5000" to "400" the moment the fourth digit lands is a
        box that fights back. build_deal sends the ceiling, so what is priced
        and what is sent already agree -- this is only the sentence that says so.
        """
        out = []
        for side, resource, attr in self._amount_fields():
            typed = self._amount(attr)
            ceiling = self.cap_for(side, resource)
            if ceiling is not None and typed > ceiling:
                out.append((side, resource, typed, ceiling))
        return out

    def _amount_fields(self):
        for side, prefix in ((TAKE, "take"), (GIVE, "give")):
            for resource, short in (("materials", "mats"), ("fuel", "fuel")):
                yield side, resource, f"{prefix}_{short}_str"

    def build_deal(self):
        """The deal as currently assembled.

        Rebuilt from scratch every time rather than edited in place -- deals are
        immutable once queued (see deal.py), and treating the one on screen the
        same way means there is no second set of rules to get wrong.
        """
        clauses = []
        if self.is_peace:
            clauses.append(deal_mod.white_peace())

        for picks, receiver_side in ((self.take_ids, self.my_side),
                                     (self.give_ids, self.their_side)):
            for (giver, receiver), group in sorted(
                    self._group_transfers(picks, receiver_side).items()):
                if giver == receiver:
                    continue  # the baseline already does this; it is not a term
                clauses.append(deal_mod.tiles_clause(giver, receiver, group))

        # Trimmed to what the payer produces in a turn, so the deal that is
        # priced here is the deal that will be paid. A promise used to be worth
        # whatever it said and collected at whatever was in the bank.
        for resource, take_attr, give_attr in (
                ("materials", "take_mats_str", "give_mats_str"),
                ("fuel", "take_fuel_str", "give_fuel_str")):
            taken = deal_mod.capped(self._amount(take_attr), self.target_nation,
                                    resource, self.world.economies)
            given = deal_mod.capped(self._amount(give_attr), self.player,
                                    resource, self.world.economies)
            if taken:
                clauses.append(deal_mod.resources_clause(
                    self.target_nation, self.player, resource, taken))
            if given:
                clauses.append(deal_mod.resources_clause(
                    self.player, self.target_nation, resource, given))

        if self.vassalize:
            clauses.append({"type": deal_mod.VASSALIZE, "master": self.player,
                            "subject": self.target_nation,
                            "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        if self.demilitarize:
            clauses.append({"type": deal_mod.DEMILITARIZE, "nation": self.target_nation,
                            "turns": c.DEAL_DEMILITARIZE_TURNS})
        if self.military_access:
            clauses.append({"type": deal_mod.MILITARY_ACCESS,
                            "grantor": self.target_nation, "grantee": self.player})

        # A member settling behind its bloc's back leaves the bloc. Shown as a
        # term rather than sprung on them at signing -- treaty_effects adds it
        # regardless, so the screen had better say so.
        if peace_scope.costs_membership(self.role):
            clauses.append({"type": deal_mod.FACTION_EXIT, "nation": self.player})

        return deal_mod.new(self.kind, self.my_side, self.their_side, clauses)

    def would_receive(self, prov, side):
        """Who this province would actually go to if it were picked for `side`.

        The same routing _group_transfers does, for one province, so the reach
        check below asks about the nation that would really end up with it --
        which with the recipient set to Auto is often not the player at all.
        """
        receiver_side = self.my_side if side == TAKE else self.their_side
        anchor = self.player if side == TAKE else self.target_nation
        chosen = self.recipients[side]
        if chosen in receiver_side:
            return chosen
        was = self.baseline_owners().get(int(prov["id"]), prov.get("owner"))
        return was if was in receiver_side else anchor

    def _group_transfers(self, picks, receiver_side):
        """{(giver, receiver): [province id, ...]} for the provinces picked.

        `picks` is {province id: chosen recipient or None}. One clause per giver
        *and* recipient. Grouping by giver alone and then picking one recipient
        for the whole batch is what this used to do, and it read the batch as a
        set: if any single province in it had belonged to a bloc member before
        the war, and no other member had a claim on any of the others, that one
        province decided where all of them went. Twenty-two British provinces
        would be handed to the Netherlands because one of them was Dutch once.
        Each province is routed on its own history now, or on the recipient the
        player named for it.

        The giver is read off the deal's *baseline* -- who holds the province if
        the treaty names no land at all. Naming the current occupier is how
        demanding land you already stand on came out as {from: You, to: You}: a
        term the other side was not party to, worth nothing in their ledger, and
        so worth nothing to their answer.
        """
        baseline = self.baseline_owners()
        anchor = self.player if receiver_side is self.my_side else self.target_nation

        grouped = {}
        for prov_id, chosen in picks.items():
            prov = self.map_screen.id_to_province.get(int(prov_id))
            if not prov:
                continue
            # Land goes home where it can: a province that belonged to a member
            # of the receiving side before the war returns to that member rather
            # than to whoever happened to be doing the negotiating. A recipient
            # the player named outranks that.
            was = baseline.get(int(prov_id), prov.get("owner"))
            if chosen in receiver_side:
                receiver = chosen
            else:
                receiver = was if was in receiver_side else anchor
            grouped.setdefault((was, receiver), []).append(int(prov_id))
        return grouped

    def moot_picks(self):
        """Picked provinces whose term would move nothing.

        Handing a province back to the nation it already belongs to is what a
        peace does anyway, so naming it is not a concession -- and scoring it as
        one was an exploit: fill the give column with the land you are about to
        lose regardless and the AI reads it as generosity.
        """
        moot = set()
        for picks, receiver_side in ((self.take_ids, self.my_side),
                                     (self.give_ids, self.their_side)):
            for (giver, receiver), group in self._group_transfers(picks, receiver_side).items():
                if giver == receiver:
                    moot.update(group)
        return moot

    # ------------------------------------------------------------------ #
    #                            PICKING                                  #
    # ------------------------------------------------------------------ #

    def set_picking(self, side):
        self.picking = None if self.picking == side else side
        self.active_input = None
        self.list_open = None
        self.refresh_ui()

    def can_pick(self, prov, side):
        """Whether this province belongs in that column at all.

        TAKE used to accept only land the other side currently owns, which
        excluded every province you had actually conquered -- the ones a treaty
        most needs to name, now that unnamed occupied land goes home. They could
        only be added by the all-or-nothing "demand everything" button, so the
        choice was forty provinces or none of them.
        """
        owner = prov.get("owner")
        if side == GIVE:
            return owner in self.my_side
        if owner in self.their_side:
            return True
        return (owner in self.my_side
                and self.baseline_owners().get(int(prov["id"])) in self.their_side)

    def occupied_of_theirs(self):
        """Provinces we hold that were theirs before the war.

        The set that a peace treaty has to *name* to keep, now that anything
        occupied and unmentioned goes home when the fighting stops.
        """
        if not self.is_peace:
            return set()

        ours, theirs = set(self.my_side), set(self.their_side)
        baseline = self.baseline_owners()
        return {prov["id"] for prov in self.map_screen.map_data.values()
                if prov.get("owner") in ours
                and baseline.get(int(prov["id"])) in theirs}

    def take_everything_occupied(self):
        """Puts every province we are standing on into the demand, in one click.

        Without this the new rule is a trap: the treaty decides the map, so a
        player who conquers forty provinces and forgets to list them signs them
        all away. Forty clicks is not a decision, it is a chore -- but they are
        forty separate clicks when you want them to be, which they were not.
        """
        occupied = self.occupied_of_theirs()
        if occupied <= set(self.take_ids):
            for prov_id in occupied:
                self.take_ids.pop(prov_id, None)
        else:
            # Whatever a co-belligerent took and we cannot get to is left out
            # rather than added and then refused at the verdict -- the point of
            # this button is that it produces a deal you can actually send.
            for prov_id in occupied:
                prov = self.map_screen.id_to_province.get(int(prov_id))
                if prov and not self.reach.reachable(self.would_receive(prov, TAKE), prov):
                    continue
                self.take_ids.setdefault(prov_id, self.recipients[TAKE])
        self.refresh_ui()

    def clear_terms(self):
        """Back to a bare white peace, or an empty trade."""
        self.take_ids = {}
        self.give_ids = {}
        self.take_mats_str = self.take_fuel_str = "0"
        self.give_mats_str = self.give_fuel_str = "0"
        self.vassalize = self.demilitarize = self.military_access = False
        self.picking = None
        self.list_open = None
        self.refresh_ui()

    def additional_events(self, event):
        super().additional_events(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = next((key for key, rect in self.input_rects().items()
                        if rect.collidepoint(event.pos)), None)
            if hit:
                self.active_input = hit
                self.list_open = None
                self.refresh_ui()
                return
            if self.is_over_ui(event.pos):
                self.active_input = None
                return
            if self.list_open:
                # A click anywhere else closes the list rather than picking a
                # province through it.
                self.list_open = None
                self.refresh_ui()
                return
            if self.picking:
                self.toggle_province(self.get_clicked_province(event.pos))
            return

        if event.type == pygame.MOUSEWHEEL and self.list_open:
            self.list_scroll = max(0, min(self._max_list_scroll(),
                                          self.list_scroll - event.y))
            self._rebuild_elements()
            return

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                self.active_input = None
            elif self.active_input:
                attr = self.FIELD_ATTRS[self.active_input]
                # The note takes prose; the four amounts take digits.
                is_note = self.active_input == "NOTE"
                text, status = process_text_input(
                    event, getattr(self, attr),
                    max_length=c.DEAL_NOTE_MAX_LEN if is_note else None,
                    validation_func=None if is_note else str.isdigit)
                if not is_note:
                    text = _digits(text)
                setattr(self, attr, text)
                if status == "CANCEL":
                    self.active_input = None
                self.refresh_ui()

    def is_over_ui(self, pos=None):
        """The recipient list counts as UI, or a click on it would fall through
        to the map underneath and pick a province."""
        if super().is_over_ui(pos):
            return True
        if not self.list_open:
            return False
        pos = pos or pygame.mouse.get_pos()
        return self.list_rect().collidepoint(pos)

    def picks_for(self, side):
        return self.take_ids if side == TAKE else self.give_ids

    def pick(self, side, prov_id, recipient=None):
        """Puts one province in a column, optionally naming who gets it.

        The columns are {province id: recipient} rather than sets of ids, so
        that a demand can be split between allies -- and so a conquest can be
        handed to a particular enemy nation rather than to whoever happens to be
        leading the other bloc.
        """
        self.picks_for(side)[int(prov_id)] = recipient

    def toggle_province(self, prov):
        """Adds or removes a province from whichever column is being picked."""
        if not prov:
            return

        if not self.can_pick(prov, self.picking):
            allowed = self.their_side if self.picking == TAKE else self.my_side
            self.map_screen.show_feedback(
                f"Pick territory belonging to {' or '.join(allowed)}.")
            return

        # Land nobody on the receiving end can get to is not land that can
        # change hands. Refused at the click rather than at the verdict, so the
        # answer arrives while the player is still looking at the province --
        # and named on the nation that would actually receive it, which with
        # Auto is frequently an ally rather than the player.
        receiver = self.would_receive(prov, self.picking)
        if (prov["id"] not in self.picks_for(self.picking)
                and not self.reach.reachable(receiver, prov)):
            whose = "your" if receiver == self.player else f"{receiver}'s"
            self.map_screen.show_feedback(
                f"Out of reach: it borders none of {whose} land and no water {whose} coast is on.")
            return

        bucket = self.take_ids if self.picking == TAKE else self.give_ids
        if prov["id"] in bucket:
            del bucket[prov["id"]]
        else:
            bucket[prov["id"]] = self.recipients[self.picking]
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                         RECIPIENT LIST                              #
    # ------------------------------------------------------------------ #

    def recipient_options(self, side):
        """Auto, then everyone on the side that would be receiving."""
        members = self.my_side if side == TAKE else self.their_side
        return [None] + sorted(members)

    def _max_list_scroll(self):
        return max(0, len(self.recipient_options(self.list_open)) - self.LIST_ROWS)

    def list_rect(self):
        """Where the recipient list sits: above the panel, in the map strip.

        Deliberately not inside the panel. Every control there is placed by hand
        against a fixed offset and checked by LayoutTests for collisions; a popup
        that covered half of them would either break that test or have to be
        exempted from it, and an exemption is how the five original overlaps went
        unnoticed for a release.
        """
        options = len(self.recipient_options(self.list_open or TAKE))
        rows = min(self.LIST_ROWS, options)
        # Room for the "N more" line under the last row, or it is drawn inside it.
        height = rows * self.LIST_ROW_H + 12 + (self.HINT_H if options > rows else 0)
        x = self._col_x(self.list_open or TAKE) + self.LABEL_W
        return pygame.Rect(x, max(c.TOP_UI_HEIGHT, self.panel_rect.y - height - 8),
                           self.LIST_W, height)

    def open_recipient_list(self, side):
        self.list_open = None if self.list_open == side else side
        self.list_scroll = 0
        self.picking = None
        self.active_input = None
        self.refresh_ui()

    def choose_recipient(self, side, nation):
        """Sets the column's recipient, and re-targets everything already picked.

        Re-targeting rather than applying only to the next click: a player who
        picks fourteen provinces and then decides they should go to an ally means
        those fourteen, not the fifteenth.
        """
        self.recipients[side] = nation
        picks = self.take_ids if side == TAKE else self.give_ids
        for prov_id in picks:
            picks[prov_id] = nation
        self.list_open = None
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              UI                                     #
    # ------------------------------------------------------------------ #

    def _col_x(self, side):
        """Left edge of the RECEIVE or the GIVE column."""
        return self.panel_rect.x + self.PAD + (0 if side == TAKE else self.COL_W)

    def _terms_x(self):
        """Left edge of the third column, where the on/off terms live.

        They used to sit in a full-width row underneath everything, which is
        what the footer text then had to be drawn on top of. Standing them up
        beside the two number columns uses the width the panel already had.
        """
        return self.panel_rect.right - 230

    def input_rects(self):
        rects = {}
        for side, take in ((TAKE, True), (GIVE, False)):
            x = self._col_x(side) + self.LABEL_W
            for key, y in ((("TAKE_MATS" if take else "GIVE_MATS"), self.Y_MATERIALS),
                           (("TAKE_FUEL" if take else "GIVE_FUEL"), self.Y_FUEL)):
                rects[key] = pygame.Rect(x, self.panel_rect.y + y, 130, self.ROW_H)

        note_x = self.panel_rect.x + self.PAD + 110
        rects["NOTE"] = pygame.Rect(note_x, self.panel_rect.y + self.Y_NOTE,
                                    self._verdict_width() - 110, self.ROW_H)
        return rects

    def _verdict_width(self):
        """How much room the left-hand text has before the buttons start."""
        return max(120, self.panel_rect.right - 250 - (self.panel_rect.x + self.PAD))

    def refresh_ui(self):
        self._rebuild_elements()
        self._refresh_readouts()
        self._save_draft()

    def _rebuild_elements(self):
        """Just the buttons. Split from refresh_ui because scrolling the
        recipient list has to re-place its rows without re-pricing the deal."""
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel",
                                self.exit_screen)]

        for side, picks in ((TAKE, self.take_ids), (GIVE, self.give_ids)):
            self.elements.append(build_choice_button(
                self._col_x(side) + self.LABEL_W, self.panel_rect.y + self.Y_RECIPIENT,
                "thin", f"To: {self._recipient_label(side)}", True,
                self.list_open == side,
                lambda s=side: self.open_recipient_list(s), font_preset="small"))
            self.elements.append(build_choice_button(
                self._col_x(side) + self.LABEL_W, self.panel_rect.y + self.Y_PROVINCES,
                "small", f"Pick ({len(picks)})", True, self.picking == side,
                lambda s=side: self.set_picking(s), font_preset="small"))

        occupied = self.occupied_of_theirs()
        if occupied:
            taken_all = occupied <= set(self.take_ids)
            self.elements.append(build_choice_button(
                self.panel_rect.x + self.PAD, self.panel_rect.y + self.Y_NOTICE,
                "diplomatic", f"Demand all {len(occupied)} I hold", True, taken_all,
                self.take_everything_occupied, font_preset="small"))

        self._build_clause_toggles()

        self.elements.append(Button(self._terms_x(), self.panel_rect.y + self.Y_NOTICE,
                                    "diplomatic", "grey", "Clear Terms",
                                    self.clear_terms, font_preset="small"))

        confirm = "Update Offer" if self.is_editing else "Send Proposal"
        buttons_y = self.panel_rect.y + self.Y_BUTTONS
        self.elements.append(Button(self.panel_rect.right - 220, buttons_y,
                                    "medium", "green", confirm, self.confirm))
        if self.is_editing:
            self.elements.append(Button(self.panel_rect.right - 440, buttons_y,
                                        "medium", "red", "Cancel Offer", self.revoke_offer))

        self._build_recipient_rows()

    def _recipient_label(self, side):
        chosen = self.recipients[side]
        if chosen is None:
            return "Auto"
        return text_utils.fit_text(chosen, fonts.get("small"), 90)

    def _build_recipient_rows(self):
        if not self.list_open:
            return

        options = self.recipient_options(self.list_open)
        box = self.list_rect()
        window = options[self.list_scroll:self.list_scroll + self.LIST_ROWS]
        for i, nation in enumerate(window):
            self.elements.append(build_choice_button(
                box.x + 6, box.y + 6 + i * self.LIST_ROW_H, "automation_option",
                AUTO if nation is None else nation, True,
                self.recipients[self.list_open] == nation,
                lambda n=nation, s=self.list_open: self.choose_recipient(s, n),
                font_preset="small"))

    def _build_clause_toggles(self):
        """The terms that are on or off rather than a number."""
        their_data = self.map_screen.nation_data.get(self.target_nation, {})
        my_data = self.map_screen.nation_data.get(self.player, {})
        can_vassalize = not (their_data.get("master") or my_data.get("master"))

        toggles = [("Vassalize Them", "vassalize", can_vassalize)]
        if self.is_peace:
            toggles.append(("Demilitarize Them", "demilitarize", True))
        toggles.append(("Military Access", "military_access", True))

        x = self._terms_x()
        for i, (label, attr, enabled) in enumerate(toggles):
            self.elements.append(build_choice_button(
                x, self.panel_rect.y + self.Y_RECIPIENT + i * (self.TOGGLE_H + 4),
                "diplomatic", label, enabled, getattr(self, attr),
                lambda a=attr: self.toggle_clause(a), font_preset="small"))

    def toggle_clause(self, attr):
        setattr(self, attr, not getattr(self, attr))
        self.refresh_ui()

    def _refresh_readouts(self):
        """Recomputes the leverage bar and the acceptance line.

        Here rather than in draw_content so it happens on a change, not sixty
        times a second -- accepts_peace prices every clause against every
        province the deal names.
        """
        self.leverage = None
        if self.is_peace:
            self.leverage = war_score.leverage(self.map_screen, self.my_side,
                                               self.their_side, self.world)

        self.balance_terms = ""
        self.balance_reading = ""

        agreement = self.build_deal()
        self.problems = deal_mod.validate(agreement, self.map_screen.map_data,
                                          self.map_screen.nation_data,
                                          reach_index=self.reach)
        self.bound = peace_scope.bound_members(self.my_side, self.player)
        self.moot = self.moot_picks()
        self.reverting = len(self.occupied_of_theirs() - set(self.take_ids))
        self.transfers = deal_mod.tile_transfers(agreement, self.map_screen.map_data,
                                                 self.map_screen.nation_data)

        # A verdict is read out in five steps rather than two. The old line said
        # ACCEPT or REFUSE and nothing else, which made the whole negotiation a
        # lock to be picked: nudge a number until the word changes, then send.
        # The dots say how much room there is either side of the line, and the
        # sentence says which term is deciding it.
        self.verdict_dots = None
        self.verdict_accepted = None
        self.verdict_slack = None
        if not self.is_peace:
            self.balance_terms = self._balance_terms(agreement)
        if self.target_nation in self.map_screen.active_players:
            self.verdict_text = "Another player decides this one for themselves."
            self.verdict_color = c.UI_TEXT_MUTED
            return

        # The same call the engine makes when the answer comes back, which is
        # the whole point -- two implementations is how the old screen ended up
        # predicting the opposite of what happened.
        judge = ai_opinion.peace_verdict if self.is_peace else ai_opinion.trade_verdict
        verdict = judge(self.world, self.target_nation, self.player, agreement,
                        self.map_screen.scenario_settings)

        if not self.is_peace:
            self.balance_reading = self._balance_reading(agreement)

        filled, total, headline = ai_opinion.verdict_band(verdict.slack)
        self.verdict_dots = (filled, total)
        self.verdict_accepted = verdict.accepted
        self.verdict_slack = verdict.slack
        # Told about them, not spoken by them. verdict.reason is the nation's own
        # words about its own position -- right for the model's system prompt,
        # and printed here verbatim it put "59% of the leverage is ours" directly
        # under a bar reading "You 41%  Them 59%".
        self.verdict_text = f"{headline} -- {ai_opinion.reason_about(verdict)}."
        self.verdict_color = (c.COLOR_SUCCESS_GREEN if verdict.accepted
                              else (255, 110, 110))

    def _balance_terms(self, agreement):
        """"You give: 3 provinces, 5,000 materials   You receive: 1,200 fuel".

        Read off the assembled deal rather than off the boxes, so what it lists
        is what would actually be sent -- an amount trimmed to its ceiling shows
        trimmed, and a province that changes nothing does not show at all.
        """
        def side(receiver):
            items = []
            tiles = sum(len(cl.get("ids", [])) for cl in deal_mod.clauses(agreement)
                        if cl.get("type") == deal_mod.TILES and cl.get("to") == receiver)
            if tiles:
                items.append(f"{tiles} province{'' if tiles == 1 else 's'}")
            for clause in deal_mod.clauses(agreement):
                if (clause.get("type") == deal_mod.RESOURCES
                        and clause.get("to") == receiver):
                    items.append(f"{_thousands(clause.get('amount', 0))} "
                                 f"{clause.get('resource')}")
            return ", ".join(items) or "nothing"

        return (f"You give: {side(self.target_nation)}"
                f"      You receive: {side(self.player)}")

    def _balance_reading(self, agreement):
        """What the other side makes of that exchange, as a ratio.

        The same numbers trade_verdict decides on -- one arithmetic, two
        readers, because a screen that prices a deal differently from the engine
        is how the old peace screen came to predict the opposite of what
        happened.
        """
        gained, lost = ai_opinion.trade_balance(
            self.world, self.target_nation, self.player, agreement,
            self.map_screen.scenario_settings)

        if gained <= 0 and lost <= 0:
            return "Nothing is on the table yet."
        if lost <= 0:
            return f"{self.target_nation} is being asked for nothing in return."
        if gained <= 0:
            return f"{self.target_nation} is being offered nothing for it."
        return (f"{self.target_nation} rates what you offer at "
                f"{ai_opinion.times_phrase(gained / lost)} what it would give up.")

    # ------------------------------------------------------------------ #
    #                            ACTIONS                                  #
    # ------------------------------------------------------------------ #

    def confirm(self):
        agreement = self.build_deal()
        problems = deal_mod.validate(agreement, self.map_screen.map_data,
                                     self.map_screen.nation_data,
                                     reach_index=self.reach)
        if problems:
            self.map_screen.show_feedback(problems[0])
            return

        action = "TRADE" if not self.is_peace else (
            "CEASEFIRE" if deal_mod.is_white_peace(agreement) else "PEACE_TREATY")

        # The itemized terms and the covering note are two different things and
        # travel in two different fields. `message` is generated from the deal so
        # the inbox thread always describes what was actually offered; `note` is
        # whatever the player wrote, and is what the model is shown as their
        # government's own words.
        diplomacy_messages.set_pending(
            self.map_screen.nation_data, self.player, self.target_nation, action,
            parameters=agreement, note=self.note.strip(),
            message="\n".join(deal_mod.describe(agreement, viewer=self.player,
                                                nation_data=self.map_screen.nation_data)))

        self._clear_draft()
        self.map_screen.show_feedback("Offer Updated!" if self.is_editing else "Offer Sent!")
        self.done = True

    def revoke_offer(self):
        diplomacy_messages.clear_pending(
            self.map_screen.nation_data, self.player, self.target_nation,
            only_actions=["PEACE_TREATY", "CEASEFIRE", "TRADE"])
        self._clear_draft()
        self.map_screen.show_feedback("Offer Cancelled.")
        self.done = True

    # ------------------------------------------------------------------ #
    #                            DRAWING                                  #
    # ------------------------------------------------------------------ #

    def get_panel_title(self):
        """One line, and one that fits.

        This used to join both bloc rosters in full and hand the result to
        draw_centered_title, which centres on the screen with no wrap, no
        truncation and no clip -- so a fourteen-nation peace ran off both edges
        of the window at once. The rosters are named under the leverage bar
        instead, where there is room and where a long list can be trimmed.
        """
        if not self.is_peace:
            return f"Trade Agreement: {self.target_nation}"
        if peace_scope.binds_whole_bloc(self.role) and len(self.my_side) > 1:
            mine = _bloc_name(self.map_screen.nation_data, self.my_side)
            theirs = _bloc_name(self.map_screen.nation_data, self.their_side)
            count = len(self.my_side) + len(self.their_side)
            return f"Peace: {mine} vs {theirs} ({count} nations)"
        if peace_scope.costs_membership(self.role):
            return f"Separate Peace: {self.target_nation} (leaves your faction)"
        return f"Peace Terms: {self.target_nation}"

    def preview_map(self):
        """The map this deal starts from: the parties in colour, the rest grey.

        The *baseline* only, not the baseline plus the current picks. Both would
        be more literal, and it would cost a full sweep of the province-id map --
        145ms measured on the 1939 scenario -- on every province clicked. The
        picks are drawn over the top as highlights instead, which also reads
        better: a ring in demand-green says which way a province is moving, where
        repainting it in its new owner's colour only says it became a different
        shade of blue.

        Built on first draw rather than in _refresh_readouts, so a keystroke
        never pays for one and a test that never draws never builds one. The
        baseline cannot change while the screen is open, so it is built once.
        """
        if self._preview is None:
            self._preview = refresh_map.build_deal_preview_map(
                self.map_screen, self.my_side + self.their_side, {},
                self.baseline_owners())
        return self._preview

    def draw_content(self, surface):
        self._draw_preview_map(surface)
        self._draw_picked_provinces(surface)
        self.draw_panel(surface)

        if self.leverage:
            self._draw_leverage(surface)
        else:
            self._draw_balance(surface)
        self._draw_columns(surface)
        self._draw_footer(surface)
        self._draw_recipient_list(surface)

    def _draw_preview_map(self, surface):
        """Paints the parties in their colours and everyone else grey, on the
        map this treaty starts from.

        The builder drew the ordinary political map with coloured blobs on the
        picked provinces, so a peace with no demands looked like the front line
        -- when what it actually restores is the pre-war border. The one thing a
        player needs before deciding what to demand is what happens if they
        demand nothing.
        """
        preview = self.preview_map()
        if preview is None:
            return

        previous_layer = self.map_screen.base_layer
        previous_map = self.map_screen.active_map
        try:
            self.map_screen.base_layer = "POLITICAL"
            self.map_screen.active_map = preview
            self.map_screen.draw_clean_map_background(surface)
        finally:
            self.map_screen.base_layer = previous_layer
            self.map_screen.active_map = previous_map

    def _draw_picked_provinces(self, surface):
        for picks, color in ((self.take_ids, _HIGHLIGHT_TAKE),
                             (self.give_ids, _HIGHLIGHT_GIVE)):
            for prov_id in picks:
                overlay_renderer.draw_map_highlight(
                    surface, self.map_screen, prov_id,
                    _HIGHLIGHT_MOOT if prov_id in self.moot else color, base_radius=8)

    def _line(self, surface, text, x, y, color, font=None, width=None):
        """One line of text, trimmed to fit rather than allowed to run off.

        Nothing on this screen did this. Every string was blitted raw, so
        anything whose length depended on the size of a faction -- the title,
        the bound-member list, the verdict sentence -- simply left the panel and
        then the window.
        """
        font = font or fonts.get("small")
        if width:
            text = text_utils.fit_text(text, font, width)
        surface.blit(font.render(text, True, color), (x, y))

    def _draw_leverage(self, surface):
        mine = self.leverage["a"]
        left = self.panel_rect.x + self.PAD
        bar = pygame.Rect(left + self.LABEL_W, self.panel_rect.y + self.Y_BAR, 420, 14)

        pygame.draw.rect(surface, (70, 40, 40), bar, border_radius=3)
        won = pygame.Rect(bar.x, bar.y, int(bar.width * mine), bar.height)
        pygame.draw.rect(surface, (90, 170, 220), won, border_radius=3)
        pygame.draw.rect(surface, c.MODAL_BORDER, bar, 1, border_radius=3)

        self._line(surface, "LEVERAGE", left, bar.y, c.COLOR_GOLD_HIGHLIGHT)
        self._line(surface, f"You {int(round(mine * 100))}%   "
                            f"Them {int(round(self.leverage['b'] * 100))}%",
                   bar.right + 12, bar.y, c.UI_TEXT_LIGHT)

        # The rosters live here, where a long one can be trimmed, rather than in
        # the title, where one could not.
        line = war_score.summary_line(self.leverage["parts"]["a"])
        if self.bound:
            line += f"   also binds {deal_mod.roster(self.bound)}"
        self._line(surface, line, bar.x, self.panel_rect.y + self.Y_BREAKDOWN,
                   c.UI_TEXT_MUTED, width=self.panel_rect.right - self.PAD - bar.x)

    def _draw_columns(self, surface):
        heading = fonts.get("heading2")
        label = fonts.get("normal")
        rects = self.input_rects()

        for side, title, color in ((TAKE, "YOU RECEIVE", c.COLOR_SUCCESS_GREEN),
                                   (GIVE, "YOU GIVE", (235, 110, 110))):
            x = self._col_x(side)
            self._line(surface, title, x, self.panel_rect.y + self.Y_HEADINGS, color,
                       font=heading, width=self.COL_W - 10)

            for text, row in (("Goes to:", self.Y_RECIPIENT + 5),
                              ("Provinces:", self.Y_PROVINCES + 10),
                              ("Materials:", self.Y_MATERIALS + 3),
                              ("Fuel:", self.Y_FUEL + 3)):
                self._line(surface, text, x, self.panel_rect.y + row, c.UI_TEXT_LIGHT,
                           font=label)

        for key in ("TAKE_MATS", "TAKE_FUEL", "GIVE_MATS", "GIVE_FUEL"):
            draw_text_box(surface, rects[key], getattr(self, self.FIELD_ATTRS[key]),
                          active=self.active_input == key, font=label, pad_x=5)

    def _notice(self):
        """(sentence, colour) for the one-line status row, or None.

        Ordered by how much it matters that the player reads it: a number that
        will not be sent as typed first, then whatever they are in the middle of
        doing, then the two standing facts about the map. Only one row exists, so
        they take turns rather than share it.
        """
        over = self.over_cap()
        if over:
            _side, resource, typed, ceiling = over[0]
            return (f"{_thousands(typed)} {resource} trimmed to "
                    f"{_thousands(ceiling)} -- one turn's output is the most "
                    f"anyone can hand over.", (255, 150, 90))

        if self.picking:
            return (f"Click provinces on the map to "
                    f"{'demand' if self.picking == TAKE else 'offer'} them.",
                    c.COLOR_GOLD_HIGHLIGHT)

        if self.active_input in self.AMOUNT_FIELDS:
            side, resource = self.AMOUNT_FIELDS[self.active_input]
            ceiling = self.cap_for(side, resource)
            if ceiling is not None:
                return (f"{self.payer_of(side)} produces {_thousands(ceiling)} "
                        f"{resource} a turn, and cannot hand over more than that.",
                        c.UI_TEXT_MUTED)

        if self.moot:
            return (f"{len(self.moot)} picked "
                    f"{'province goes' if len(self.moot) == 1 else 'provinces go'} "
                    f"there anyway.", _HIGHLIGHT_MOOT)

        if self.reverting:
            return (f"{self.reverting} occupied "
                    f"{'province reverts' if self.reverting == 1 else 'provinces revert'} "
                    f"unless demanded.", (235, 180, 90))
        return None

    def _draw_balance(self, surface):
        """What each side is putting up, and what they make of it.

        A trade has no leverage bar, so these two rows were empty -- while the
        only reading of the deal anywhere on the screen was a single sentence at
        the bottom which, for a land-for-cash offer, used to say "they are asking
        nothing of them". The figures are ai_opinion's own, in its own currency,
        so this line and the verdict under it cannot come apart.
        """
        left = self.panel_rect.x + self.PAD
        width = self.panel_rect.right - self.PAD - (left + self.LABEL_W)

        self._line(surface, "BALANCE", left, self.panel_rect.y + self.Y_BAR,
                   c.COLOR_GOLD_HIGHLIGHT)
        self._line(surface, self.balance_terms, left + self.LABEL_W,
                   self.panel_rect.y + self.Y_BAR, c.UI_TEXT_LIGHT, width=width)
        self._line(surface, self.balance_reading, left + self.LABEL_W,
                   self.panel_rect.y + self.Y_BREAKDOWN, c.UI_TEXT_MUTED, width=width)

    def _draw_footer(self, surface):
        left = self.panel_rect.x + self.PAD
        width = self._verdict_width()

        # --- what the map will do, in the row beside the "demand all" button ---
        notice_x = left + (220 if self.occupied_of_theirs() else 0)
        notice_y = self.panel_rect.y + self.Y_NOTICE + 7
        notice_w = self._terms_x() - 10 - notice_x
        notice = self._notice()
        if notice:
            text, color = notice
            self._line(surface, text, notice_x, notice_y, color, width=notice_w)

        # --- the note that travels with the offer ---
        self._line(surface, "Note to them:", left, self.panel_rect.y + self.Y_NOTE + 4,
                   c.UI_TEXT_LIGHT)
        draw_text_box(surface, self.input_rects()["NOTE"], self.note,
                      active=self.active_input == "NOTE", font=fonts.get("normal"),
                      placeholder="optional -- their leader will read it", pad_x=5)

        # --- the verdict ---
        # Two lines, wrapped. It is the most informative sentence on the screen
        # and the longest -- "They will refuse outright -- you hold 100% of their
        # land and are asking for 45% of their country" is about 760px of small
        # text in the 640 the row has -- so on one line it lost the half that
        # says what to change.
        y = self.panel_rect.y + self.Y_VERDICT
        if self.problems:
            self._line(surface, self.problems[0], left, y, (255, 150, 90), width=width)
            return

        text_x = left
        if self.verdict_dots:
            text_x = self._draw_dots(surface, left, y + 8, *self.verdict_dots)
        if self.verdict_text:
            font = fonts.get("small")
            lines = text_utils.wrap_text(self.verdict_text, font,
                                         width - (text_x - left))
            for i, line in enumerate(lines[:self.VERDICT_LINES]):
                last = i == self.VERDICT_LINES - 1 and len(lines) > self.VERDICT_LINES
                self._line(surface, line + ("..." if last else ""), text_x,
                           y + i * self.VERDICT_LINE_H, self.verdict_color,
                           width=width - (text_x - left))

    def _draw_dots(self, surface, x, cy, filled, total):
        """The five-step reading of how likely they are to sign. Returns where
        the sentence after it should start."""
        radius, step = 4, 13
        for i in range(total):
            centre = (x + radius + i * step, cy)
            if i < filled:
                pygame.draw.circle(surface, self.verdict_color, centre, radius)
            else:
                pygame.draw.circle(surface, c.UI_TEXT_MUTED, centre, radius, 1)
        return x + total * step + 8

    def _draw_recipient_list(self, surface):
        """The box behind the rows. The rows themselves are buttons, drawn after
        draw_content by draw_elements, so they land on top of this."""
        if not self.list_open:
            return

        box = self.list_rect()
        ui_bars.draw_translucent_panel(surface, box, (*c.HUD_PANEL_BG, 240),
                                       border_color=c.MODAL_BORDER)

        hidden = len(self.recipient_options(self.list_open)) - self.LIST_ROWS
        if hidden > 0:
            self._line(surface, f"scroll -- {hidden} more", box.x + 8,
                       box.bottom - self.HINT_H, c.UI_TEXT_MUTED, width=box.width - 16)


def open_deal_menu(map_screen, target_nation, kind=deal_mod.KIND_PEACE):
    _run_pygame_sub_screen(map_screen, Deal_Screen(map_screen, target_nation, kind))


def open_peace_menu(map_screen, target_nation):
    open_deal_menu(map_screen, target_nation, deal_mod.KIND_PEACE)


def open_trade_menu(map_screen, target_nation):
    open_deal_menu(map_screen, target_nation, deal_mod.KIND_TRADE)
