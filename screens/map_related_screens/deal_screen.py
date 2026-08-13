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
"""

import pygame

import data.constants as c
from gameState import MapOverlayScreen
from map_logic.ai import ai_opinion, ai_world
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import diplomacy_messages, peace_scope, war_score
from map_logic.rendering import overlay_renderer
from map_logic.rendering.font_manager import fonts
from screens.map_related_screens.diplomacy_screen_widgets import build_choice_button
from ui import text_utils
from ui.screen_runner import _run_pygame_sub_screen
from ui_elements import Button, draw_text_box, process_text_input

#: Which side of the table a picked province belongs to.
TAKE = "TAKE"
GIVE = "GIVE"

_HIGHLIGHT_TAKE = (90, 220, 120)
_HIGHLIGHT_GIVE = (235, 110, 110)


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

    # --- Layout ---------------------------------------------------------
    # Every offset below is from the panel's own top-left, and no two of them
    # overlap. The panel used to be 285px tall and they did, badly: the 28px
    # column headings were blitted four pixels above the 18px row labels at the
    # same x, so "YOU RECEIVE" and "Provinces:" were printed on top of each
    # other; the hint line landed inside the first toggle button; the verdict
    # clipped the Send button; and the Send button itself hung six pixels below
    # the panel. Anything with a variable length -- a bloc roster, a verdict
    # sentence -- is now passed through text_utils rather than trusted to fit.
    WIDTH, HEIGHT = 920, 364
    PAD = 30                #: left margin inside the panel
    COL_W = 300             #: the RECEIVE and GIVE columns
    LABEL_W = 120           #: room for "Provinces:" before its control
    Y_BAR = 56              #: leverage bar
    Y_BREAKDOWN = 76        #: its component line, which also names bound members
    Y_HEADINGS = 96
    Y_PROVINCES = 130       #: pick buttons; their labels sit 4px lower
    Y_MATERIALS = 176
    Y_FUEL = 206
    Y_NOTICE = 236          #: "take everything I occupy", and what would revert
    Y_NOTE = 276
    Y_VERDICT = 312
    Y_BUTTONS = 306
    ROW_H = 26              #: a text box
    TOGGLE_H = 30

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

        self.take_ids = set()
        self.give_ids = set()
        self.take_mats_str = "0"
        self.take_fuel_str = "0"
        self.give_mats_str = "0"
        self.give_fuel_str = "0"
        self.vassalize = False
        self.demilitarize = False
        self.military_access = False
        self.note = ""

        self.picking = None       # TAKE / GIVE while the map is being clicked
        self.active_input = None

        self._load_existing_offer()
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                             STATE                                   #
    # ------------------------------------------------------------------ #

    @property
    def is_peace(self):
        return self.kind == deal_mod.KIND_PEACE

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
                bucket = self.take_ids if clause.get("to") in self.my_side else self.give_ids
                bucket.update(int(i) for i in clause.get("ids", []))
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

    def _amount(self, attr):
        try:
            return max(0, int(getattr(self, attr) or 0))
        except ValueError:
            return 0

    def build_deal(self):
        """The deal as currently assembled.

        Rebuilt from scratch every time rather than edited in place -- deals are
        immutable once queued (see deal.py), and treating the one on screen the
        same way means there is no second set of rules to get wrong.
        """
        clauses = []
        if self.is_peace:
            clauses.append(deal_mod.white_peace())

        for ids, receiver_side in ((self.take_ids, self.my_side),
                                   (self.give_ids, self.their_side)):
            for (giver, receiver), group in sorted(self._group_transfers(ids, receiver_side).items()):
                clauses.append(deal_mod.tiles_clause(giver, receiver, group))

        for resource, take_attr, give_attr in (
                ("materials", "take_mats_str", "give_mats_str"),
                ("fuel", "take_fuel_str", "give_fuel_str")):
            taken = self._amount(take_attr)
            given = self._amount(give_attr)
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

    def _group_transfers(self, ids, receiver_side):
        """{(giver, receiver): [province id, ...]} for the provinces picked.

        One clause per giver *and* recipient. Grouping by giver alone and then
        picking one recipient for the whole batch is what this used to do, and it
        read the batch as a set: if any single province in it had belonged to a
        bloc member before the war, and no other member had a claim on any of the
        others, that one province decided where all of them went. Twenty-two
        British provinces would be handed to the Netherlands because one of them
        was Dutch once. Each province is routed on its own history now.
        """
        prewar = war_score.prewar_index(self.map_screen.nation_data)
        anchor = self.player if receiver_side is self.my_side else self.target_nation

        grouped = {}
        for prov_id in ids:
            prov = self.map_screen.id_to_province.get(int(prov_id))
            if not prov:
                continue
            # Land goes home where it can: a province that belonged to a member
            # of the receiving side before the war returns to that member rather
            # than to whoever happened to be doing the negotiating.
            was = war_score.original_owner(prov, prewar)
            receiver = was if was in receiver_side else anchor
            grouped.setdefault((prov.get("owner"), receiver), []).append(int(prov_id))
        return grouped

    # ------------------------------------------------------------------ #
    #                            PICKING                                  #
    # ------------------------------------------------------------------ #

    def set_picking(self, side):
        self.picking = None if self.picking == side else side
        self.active_input = None
        self.refresh_ui()

    def _pickable_owners(self, side):
        return self.their_side if side == TAKE else self.my_side

    def occupied_of_theirs(self):
        """Provinces we hold that were theirs before the war.

        The set that a peace treaty has to *name* to keep, now that anything
        occupied and unmentioned goes home when the fighting stops.
        """
        if not self.is_peace:
            return set()

        prewar = war_score.prewar_index(self.map_screen.nation_data)
        ours, theirs = set(self.my_side), set(self.their_side)
        return {prov["id"] for prov in self.map_screen.map_data.values()
                if prov.get("owner") in ours
                and war_score.original_owner(prov, prewar) in theirs}

    def take_everything_occupied(self):
        """Puts every province we are standing on into the demand, in one click.

        Without this the new rule is a trap: the treaty decides the map, so a
        player who conquers forty provinces and forgets to list them signs them
        all away. Forty clicks is not a decision, it is a chore.
        """
        occupied = self.occupied_of_theirs()
        self.take_ids = set() if occupied <= self.take_ids else (self.take_ids | occupied)
        self.refresh_ui()

    def additional_events(self, event):
        super().additional_events(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hit = next((key for key, rect in self.input_rects().items()
                        if rect.collidepoint(event.pos)), None)
            if hit:
                self.active_input = hit
                return
            if self.is_over_ui():
                self.active_input = None
                return
            if self.picking:
                self.toggle_province(self.get_clicked_province(event.pos))
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
                setattr(self, attr, text)
                if status == "CANCEL":
                    self.active_input = None
                self.refresh_ui()

    def toggle_province(self, prov):
        """Adds or removes a province from whichever column is being picked."""
        if not prov:
            return

        owner = prov.get("owner")
        allowed = self._pickable_owners(self.picking)
        if owner not in allowed:
            self.map_screen.show_feedback(
                f"Pick territory belonging to {' or '.join(allowed)}.")
            return

        bucket = self.take_ids if self.picking == TAKE else self.give_ids
        bucket.symmetric_difference_update({prov["id"]})
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
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel",
                                self.exit_screen)]

        for side, ids in ((TAKE, self.take_ids), (GIVE, self.give_ids)):
            self.elements.append(build_choice_button(
                self._col_x(side) + self.LABEL_W, self.panel_rect.y + self.Y_PROVINCES,
                "small", f"Pick ({len(ids)})", True, self.picking == side,
                lambda s=side: self.set_picking(s), font_preset="small"))

        occupied = self.occupied_of_theirs()
        if occupied:
            taken_all = occupied <= self.take_ids
            self.elements.append(build_choice_button(
                self.panel_rect.x + self.PAD, self.panel_rect.y + self.Y_NOTICE,
                "diplomatic", f"Demand all {len(occupied)} I hold", True, taken_all,
                self.take_everything_occupied, font_preset="small"))

        self._build_clause_toggles()

        confirm = "Update Offer" if self.is_editing else "Send Proposal"
        buttons_y = self.panel_rect.y + self.Y_BUTTONS
        self.elements.append(Button(self.panel_rect.right - 220, buttons_y,
                                    "medium", "green", confirm, self.confirm))
        if self.is_editing:
            self.elements.append(Button(self.panel_rect.right - 440, buttons_y,
                                        "medium", "red", "Cancel Offer", self.revoke_offer))

        self._refresh_readouts()

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
                x, self.panel_rect.y + self.Y_PROVINCES + i * (self.TOGGLE_H + 4),
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

        agreement = self.build_deal()
        self.problems = deal_mod.validate(agreement, self.map_screen.map_data,
                                          self.map_screen.nation_data)
        self.bound = peace_scope.bound_members(self.my_side, self.player)
        self.reverting = len(self.occupied_of_theirs() - self.take_ids)

        # A verdict is read out in five steps rather than two. The old line said
        # ACCEPT or REFUSE and nothing else, which made the whole negotiation a
        # lock to be picked: nudge a number until the word changes, then send.
        # The dots say how much room there is either side of the line, and the
        # sentence says which term is deciding it.
        self.verdict_dots = None
        self.verdict_accepted = None
        self.verdict_slack = None
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

        filled, total, headline = ai_opinion.verdict_band(verdict.slack)
        self.verdict_dots = (filled, total)
        self.verdict_accepted = verdict.accepted
        self.verdict_slack = verdict.slack
        self.verdict_text = f"{headline} -- {verdict.reason}."
        self.verdict_color = (c.COLOR_SUCCESS_GREEN if verdict.accepted
                              else (255, 110, 110))

    # ------------------------------------------------------------------ #
    #                            ACTIONS                                  #
    # ------------------------------------------------------------------ #

    def confirm(self):
        agreement = self.build_deal()
        problems = deal_mod.validate(agreement, self.map_screen.map_data,
                                     self.map_screen.nation_data)
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

        self.map_screen.show_feedback("Offer Updated!" if self.is_editing else "Offer Sent!")
        self.done = True

    def revoke_offer(self):
        diplomacy_messages.clear_pending(
            self.map_screen.nation_data, self.player, self.target_nation,
            only_actions=["PEACE_TREATY", "CEASEFIRE", "TRADE"])
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

    def draw_content(self, surface):
        self._draw_picked_provinces(surface)
        self.draw_panel(surface)

        if self.leverage:
            self._draw_leverage(surface)
        self._draw_columns(surface)
        self._draw_footer(surface)

    def _draw_picked_provinces(self, surface):
        for prov_id in self.take_ids:
            overlay_renderer.draw_map_highlight(surface, self.map_screen, prov_id,
                                                _HIGHLIGHT_TAKE, base_radius=8)
        for prov_id in self.give_ids:
            overlay_renderer.draw_map_highlight(surface, self.map_screen, prov_id,
                                                _HIGHLIGHT_GIVE, base_radius=8)

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

            for text, row in (("Provinces:", self.Y_PROVINCES + 10),
                              ("Materials:", self.Y_MATERIALS + 3),
                              ("Fuel:", self.Y_FUEL + 3)):
                self._line(surface, text, x, self.panel_rect.y + row, c.UI_TEXT_LIGHT,
                           font=label)

        for key in ("TAKE_MATS", "TAKE_FUEL", "GIVE_MATS", "GIVE_FUEL"):
            draw_text_box(surface, rects[key], getattr(self, self.FIELD_ATTRS[key]),
                          active=self.active_input == key, font=label, pad_x=5)

    def _draw_footer(self, surface):
        left = self.panel_rect.x + self.PAD
        width = self._verdict_width()

        # --- what the map will do, in the row beside the "demand all" button ---
        notice_x = left + (220 if self.occupied_of_theirs() else 0)
        notice_y = self.panel_rect.y + self.Y_NOTICE + 7
        if self.picking:
            self._line(surface, f"Click provinces on the map to "
                                f"{'demand' if self.picking == TAKE else 'offer'} them.",
                       notice_x, notice_y, c.COLOR_GOLD_HIGHLIGHT,
                       width=self.panel_rect.right - self.PAD - notice_x)
        elif self.reverting:
            self._line(surface, f"{self.reverting} occupied "
                                f"{'province' if self.reverting == 1 else 'provinces'} "
                                f"not demanded here will return to their pre-war owners.",
                       notice_x, notice_y, (235, 180, 90),
                       width=self.panel_rect.right - self.PAD - notice_x)

        # --- the note that travels with the offer ---
        self._line(surface, "Note to them:", left, self.panel_rect.y + self.Y_NOTE + 4,
                   c.UI_TEXT_LIGHT)
        draw_text_box(surface, self.input_rects()["NOTE"], self.note,
                      active=self.active_input == "NOTE", font=fonts.get("normal"),
                      placeholder="optional -- their leader will read it", pad_x=5)

        # --- the verdict ---
        y = self.panel_rect.y + self.Y_VERDICT
        if self.problems:
            self._line(surface, self.problems[0], left, y, (255, 150, 90), width=width)
            return

        text_x = left
        if self.verdict_dots:
            text_x = self._draw_dots(surface, left, y + 8, *self.verdict_dots)
        if self.verdict_text:
            self._line(surface, self.verdict_text, text_x, y, self.verdict_color,
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


def open_deal_menu(map_screen, target_nation, kind=deal_mod.KIND_PEACE):
    _run_pygame_sub_screen(map_screen, Deal_Screen(map_screen, target_nation, kind))


def open_peace_menu(map_screen, target_nation):
    open_deal_menu(map_screen, target_nation, deal_mod.KIND_PEACE)


def open_trade_menu(map_screen, target_nation):
    open_deal_menu(map_screen, target_nation, deal_mod.KIND_TRADE)
