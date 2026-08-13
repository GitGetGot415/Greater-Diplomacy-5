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
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from ui_elements import Button, draw_text_box, process_text_input

#: Which side of the table a picked province belongs to.
TAKE = "TAKE"
GIVE = "GIVE"

_HIGHLIGHT_TAKE = (90, 220, 120)
_HIGHLIGHT_GIVE = (235, 110, 110)


class Deal_Screen(MapOverlayScreen):
    # Docked low and translucent so the map stays readable and clickable --
    # provinces are picked by clicking them, the same way claims always were.
    CENTER_PANEL = False
    overlay_alpha = 0
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_CONFIRM_OVER_MAP

    #: Which text attribute each of the four number boxes edits.
    FIELD_ATTRS = {
        "TAKE_MATS": "take_mats_str",
        "TAKE_FUEL": "take_fuel_str",
        "GIVE_MATS": "give_mats_str",
        "GIVE_FUEL": "give_fuel_str",
    }

    def __init__(self, map_screen, target_nation, kind=deal_mod.KIND_PEACE):
        super().__init__(map_screen, pygame.Rect(c.SCREEN_WIDTH // 2 - 420,
                                                 c.SCREEN_HEIGHT - 340, 840, 285))
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
            for giver, group in sorted(self._group_by_owner(ids).items()):
                clauses.append(deal_mod.tiles_clause(
                    giver, self._recipient_for(group, receiver_side), group))

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

    def _group_by_owner(self, ids):
        grouped = {}
        for prov_id in ids:
            prov = self.map_screen.id_to_province.get(int(prov_id))
            if prov:
                grouped.setdefault(prov.get("owner"), []).append(int(prov_id))
        return grouped

    def _recipient_for(self, ids, receiver_side):
        """Who on the receiving side actually gets these provinces.

        Land goes home where it can: a province that belonged to a bloc member
        before the war returns to that member rather than to whoever happened to
        be doing the negotiating. Everything else goes to the signatory.
        """
        prewar = war_score.prewar_index(self.map_screen.nation_data)
        anchor = self.player if receiver_side is self.my_side else self.target_nation

        owners = set()
        for prov_id in ids:
            prov = self.map_screen.id_to_province.get(int(prov_id))
            if prov:
                owners.add(war_score.original_owner(prov, prewar))

        candidates = [n for n in receiver_side if n in owners]
        return candidates[0] if len(candidates) == 1 else anchor

    # ------------------------------------------------------------------ #
    #                            PICKING                                  #
    # ------------------------------------------------------------------ #

    def set_picking(self, side):
        self.picking = None if self.picking == side else side
        self.active_input = None
        self.refresh_ui()

    def _pickable_owners(self, side):
        return self.their_side if side == TAKE else self.my_side

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
                text, status = process_text_input(event, getattr(self, attr),
                                                  validation_func=str.isdigit)
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

    def input_rects(self):
        left = self.panel_rect.x + 150
        right = self.panel_rect.centerx + 190
        top = self.panel_rect.y + 108
        return {
            "TAKE_MATS": pygame.Rect(left, top, 110, 26),
            "TAKE_FUEL": pygame.Rect(left, top + 32, 110, 26),
            "GIVE_MATS": pygame.Rect(right, top, 110, 26),
            "GIVE_FUEL": pygame.Rect(right, top + 32, 110, 26),
        }

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel",
                                self.exit_screen)]

        pick_y = self.panel_rect.y + 74
        self.elements.append(build_choice_button(
            self.panel_rect.x + 150, pick_y, "small",
            f"Pick ({len(self.take_ids)})", True, self.picking == TAKE,
            lambda: self.set_picking(TAKE), font_preset="small"))
        self.elements.append(build_choice_button(
            self.panel_rect.centerx + 190, pick_y, "small",
            f"Pick ({len(self.give_ids)})", True, self.picking == GIVE,
            lambda: self.set_picking(GIVE), font_preset="small"))

        self._build_clause_toggles()

        confirm = "Update Offer" if self.is_editing else "Send Proposal"
        self.elements.append(Button(self.panel_rect.centerx - 210, self.panel_rect.bottom - 44,
                                    "medium", "green", confirm, self.confirm))
        if self.is_editing:
            self.elements.append(Button(self.panel_rect.centerx + 20, self.panel_rect.bottom - 44,
                                        "medium", "red", "Cancel Offer", self.revoke_offer))

        self._refresh_readouts()

    def _build_clause_toggles(self):
        """The terms that are on or off rather than a number."""
        their_data = self.map_screen.nation_data.get(self.target_nation, {})
        my_data = self.map_screen.nation_data.get(self.player, {})
        can_vassalize = not (their_data.get("master") or my_data.get("master"))

        row_y = self.panel_rect.y + 182
        toggles = [("Vassalize Them", "vassalize", can_vassalize)]
        if self.is_peace:
            toggles.append(("Demilitarize Them", "demilitarize", True))
        toggles.append(("Take Military Access", "military_access", True))

        for i, (label, attr, enabled) in enumerate(toggles):
            self.elements.append(build_choice_button(
                self.panel_rect.x + 30 + i * 250, row_y, "medium", label, enabled,
                getattr(self, attr), lambda a=attr: self.toggle_clause(a),
                font_preset="small"))

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

        if self.target_nation in self.map_screen.active_players:
            self.verdict_text = "Another player decides this one for themselves."
            self.verdict_color = c.UI_TEXT_MUTED
        elif not self.is_peace:
            self.verdict_text = ""
            self.verdict_color = c.UI_TEXT_MUTED
        else:
            # The same call the engine makes when the answer comes back, which
            # is the whole point -- two implementations is how the old screen
            # ended up predicting the opposite of what happened.
            likely = ai_opinion.accepts_peace(self.world, self.target_nation, self.player,
                                              agreement, self.map_screen.scenario_settings)
            self.verdict_text = ("They are likely to ACCEPT these terms."
                                 if likely else "They are likely to REFUSE these terms.")
            self.verdict_color = c.COLOR_SUCCESS_GREEN if likely else (255, 110, 110)

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

        diplomacy_messages.set_pending(
            self.map_screen.nation_data, self.player, self.target_nation, action,
            parameters=agreement,
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
        if not self.is_peace:
            return f"Trade Agreement: {self.target_nation}"
        if peace_scope.binds_whole_bloc(self.role) and len(self.my_side) > 1:
            return f"Peace: {', '.join(self.my_side)}  vs  {', '.join(self.their_side)}"
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

    def _draw_leverage(self, surface):
        mine = self.leverage["a"]
        bar = pygame.Rect(self.panel_rect.x + 150, self.panel_rect.y + 46, 420, 14)

        pygame.draw.rect(surface, (70, 40, 40), bar, border_radius=3)
        won = pygame.Rect(bar.x, bar.y, int(bar.width * mine), bar.height)
        pygame.draw.rect(surface, (90, 170, 220), won, border_radius=3)
        pygame.draw.rect(surface, c.MODAL_BORDER, bar, 1, border_radius=3)

        small = fonts.get("small")
        surface.blit(small.render("LEVERAGE", True, c.COLOR_GOLD_HIGHLIGHT),
                     (self.panel_rect.x + 30, bar.y))
        surface.blit(small.render(f"You {int(round(mine * 100))}%   "
                                  f"Them {int(round(self.leverage['b'] * 100))}%",
                                  True, c.UI_TEXT_LIGHT), (bar.right + 12, bar.y))
        surface.blit(small.render(war_score.summary_line(self.leverage["parts"]["a"]),
                                  True, c.UI_TEXT_MUTED),
                     (self.panel_rect.x + 150, bar.bottom + 3))

    def _draw_columns(self, surface):
        heading = fonts.get("heading2")
        small = fonts.get("normal")
        top = self.panel_rect.y + 108

        surface.blit(heading.render("YOU RECEIVE", True, c.COLOR_SUCCESS_GREEN),
                     (self.panel_rect.x + 30, self.panel_rect.y + 74))
        surface.blit(heading.render("YOU GIVE", True, (235, 110, 110)),
                     (self.panel_rect.centerx + 70, self.panel_rect.y + 74))

        for x in (self.panel_rect.x + 30, self.panel_rect.centerx + 70):
            surface.blit(small.render("Provinces:", True, c.UI_TEXT_LIGHT), (x, self.panel_rect.y + 78))
            surface.blit(small.render("Materials:", True, c.UI_TEXT_LIGHT), (x, top + 4))
            surface.blit(small.render("Fuel:", True, c.UI_TEXT_LIGHT), (x, top + 36))

        for key, rect in self.input_rects().items():
            draw_text_box(surface, rect, getattr(self, self.FIELD_ATTRS[key]),
                          active=self.active_input == key, font=small, pad_x=5)

    def _draw_footer(self, surface):
        small = fonts.get("small")
        y = self.panel_rect.bottom - 68

        if self.picking:
            hint = (f"Click provinces on the map to "
                    f"{'demand' if self.picking == TAKE else 'offer'} them.")
            surface.blit(small.render(hint, True, c.COLOR_GOLD_HIGHLIGHT),
                         (self.panel_rect.x + 30, y))
        elif self.bound:
            surface.blit(small.render(f"Also bound: {', '.join(self.bound)} "
                                      f"(they may refuse and leave the faction)",
                                      True, c.UI_TEXT_MUTED),
                         (self.panel_rect.x + 30, y))

        if self.problems:
            surface.blit(small.render(self.problems[0], True, (255, 150, 90)),
                         (self.panel_rect.x + 30, y + 16))
        elif self.verdict_text:
            surface.blit(small.render(self.verdict_text, True, self.verdict_color),
                         (self.panel_rect.x + 30, y + 16))


def open_deal_menu(map_screen, target_nation, kind=deal_mod.KIND_PEACE):
    _run_pygame_sub_screen(map_screen, Deal_Screen(map_screen, target_nation, kind))


def open_peace_menu(map_screen, target_nation):
    open_deal_menu(map_screen, target_nation, deal_mod.KIND_PEACE)


def open_trade_menu(map_screen, target_nation):
    open_deal_menu(map_screen, target_nation, deal_mod.KIND_TRADE)
