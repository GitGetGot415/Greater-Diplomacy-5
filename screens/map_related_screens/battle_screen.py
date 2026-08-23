"""Managing one tile's battle: which duel each of your units fights, and who
waits in reserve.

The province sidebar shows the same fight, but read-only and squeezed into 370
pixels. This is where the two decisions the lane model actually gives a player
live:

  - which enemy a unit faces, when more than one is standing here. The default
    is the heaviest front first, which is usually right and occasionally very
    wrong -- a nation that would rather finish off a weak neighbour than trade
    with the strong one has no other way to say so.
  - where a unit stands in the queue for the front rank. Holding a damaged unit
    back lets a fresh one take its slot, and a reserve takes no damage and
    recovers morale while the front bleeds. It is a preference, not a veto: a
    held unit still fills a slot nobody else can, because an empty slot is worse
    for the side than a hurt unit standing in it. Hold four of six men and the
    other two do not inherit four idle slots -- all four are still fielded.

Both are written straight onto the unit dict, where combat_rules.build_battle is
the only thing that reads them back. That is deliberate: a second store for
"who is fighting whom" is how the four callers of the old firing_lines drifted
apart in the first place.

A ModalScreen rather than a registered state, because it is an inspector rather
than a mode -- see the class docstring. It is launched by the map button that
replaces Give Orders while a tile is fighting, and carries a button back to the
Orders screen so bombardment and retreat stay reachable mid-battle.
"""

import pygame

import data.constants as c
from data import queries
from map_logic.turn_processing import combat_rules
from map_logic.rendering.font_manager import fonts
from ui import flag_icons
from ui.bars import ui_bars, view_mode_buttons
from ui.modal_screen import ModalScreen
from ui_elements import draw_combat_stats, draw_bombardment_stats

#: Panes, left to right. Lane list, then the selected lane's three columns.
PANE_LANES = "lanes"
PANE_FRONT = "front"
PANE_ENEMY = "enemy"
PANE_RESERVE = "reserve"

LANE_COL_W = 250
#: Two lines: the unit and its flag, then its stats. The sidebar shows the same
#: stats on the same icons, and a lane manager that showed less than the panel
#: it opens from would be the wrong way round.
ROW_H = 42
HEADER_H = 26
#: Flags a lane row shows per side before it gives up and counts the rest.
LANE_FLAGS_SHOWN = 3

#: Room reserved at the very bottom of the panel for the shared view-mode
#: button row (Resources/Blank/Units/Economy), which is drawn at the same
#: screen-fixed y as every other screen's copy of it -- see refresh_ui and
#: _layout, which both shrink to make room for it instead of drawing under it.
VIEW_MODE_ROW_RESERVE = 40


def side_name(side):
    """A side in words, for anywhere a flag will not fit."""
    return " + ".join(side.nations)


class Battle_Screen(ModalScreen):
    """A tile's lanes, and the player's units in them.

    Not a registered state like Orders_Screen: that would need an entry in
    main.py's state table, a handoff branch in flip_state and a row in the test
    harness's MAP_HANDOFFS, which is three files of state-machine wiring for a
    screen that inspects one province and closes. ModalScreen gives the dimmed
    freeze-frame, the panel chrome and the multi-pane scrolling for free.
    """

    PANEL_SIZE = (1240, 680)
    ROW_HEIGHT = ROW_H
    PAD = 16
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_DANGER

    def __init__(self, map_screen, province, origin_screen=None):
        self.province = province
        # Both set before super(), because ModalScreen.__init__ asks for the
        # title and the title depends on whether any of these units are ours.
        self.map_screen = map_screen
        self.player = map_screen.player_country
        # Whichever screen this battle was pushed over (Map, Orders or
        # Production) -- see close_and_navigate.
        self.origin_screen = origin_screen or map_screen
        super().__init__(map_screen, self.get_panel_title())
        # Hotseat and fog of war: the same rule the sidebar uses. A province you
        # cannot see is not one whose order of battle you get to read.
        self.visible = queries.is_province_visible(map_screen, province["id"])
        self.selected_lane = 0
        self.regions = {}
        # {pane: [(rect, payload)]}, filled by refresh_ui and read by the
        # foreground painters. Safe to cache because GameState.scroll_by calls
        # refresh_ui on every wheel notch, so the rects never go stale.
        self.row_paint = {}
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              THE FIGHT                             #
    # ------------------------------------------------------------------ #

    def rebuild(self):
        """Re-reads the battle. Called after every change, so slot counts and
        lane membership update as the player edits rather than on close."""
        self.battle = combat_rules.build_battle(
            [self.province.get("units", [])], self.map_screen.nation_data)
        if self.selected_lane >= len(self.battle.lanes):
            self.selected_lane = 0

    def my_lanes(self):
        """The lanes this player holds a side in, which are the editable ones."""
        return [lane for lane in self.battle.lanes
                if self.player in lane.a.nations or self.player in lane.b.nations]

    def current(self):
        """(lane, near, far) for the selected lane, or (None, None, None).

        `near` is the player's side when they hold one, so their own units are
        always in the same column. Otherwise it is simply lane.a: a battle you
        are not in is still worth watching, and both halves of it are shown --
        read-only, since you command nobody in either.
        """
        if not self.battle.lanes:
            return None, None, None
        lane = self.battle.lanes[min(self.selected_lane, len(self.battle.lanes) - 1)]
        return (lane,) + self.near_far(lane)

    def is_mine(self, side):
        return side is not None and self.player in side.nations

    def near_far(self, lane):
        """A lane's two sides, the player's first when they hold one.

        Every reading of a lane orders it this way -- the row in the list, the
        summary line, the two columns -- so a player never has to work out which
        half of "6 v 3" is theirs.
        """
        if self.player in lane.b.nations:
            return lane.b, lane.a
        return lane.a, lane.b

    def my_units(self):
        """The units on this tile the player may actually give orders to.

        In tactical mode a player commands one division, not a country, so the
        lane manager has to narrow to it the same way the Orders screen does --
        otherwise the one screen you open in the middle of a battle is the one
        that hands you the whole army back.
        """
        mine = [u for u in self.province.get("units", [])
                if u.get("owner") == self.player]
        if self.map_screen.tactical_mode:
            return [u for u in mine if u is self.map_screen.player_unit]
        return mine

    def can_command(self, unit):
        """Whether this particular unit takes orders from the player."""
        return any(u is unit for u in self.my_units())

    def seated(self):
        """ids of every unit holding a front slot in any lane on this tile."""
        return {id(u) for lane in self.battle.lanes
                for side in (lane.a, lane.b) for u in side.front}

    def bench(self):
        """Our units in no front rank anywhere -- the pool a lane draws from."""
        seated = self.seated()
        return [u for u in self.my_units() if id(u) not in seated]

    def side_bench(self, side):
        """The whole side's reserves: ours first, then everyone else's here.

        An ally's reserves are not the player's to move, and their rows say so
        by being dead. They are still the most important thing on the column:
        they are what steps into the front rank as it dies, so a side that looks
        outnumbered three to six may be nothing of the kind. Showing only our
        own made every fight look like we were holding it alone.

        "Everyone else" includes our own nation's other divisions in tactical
        mode, where the player commands one of them and the rest are the host's
        -- the same units the front column already lists without giving away.
        """
        seated = self.seated()
        mine = self.bench()
        commanded = {id(u) for u in mine}

        rest = [u for u in self.province.get("units", [])
                if u.get("owner") in side.nations
                and id(u) not in seated and id(u) not in commanded]
        # Grouped by nation so the flags read as blocks; sorted() is stable, so
        # within a nation they keep the order they stand in on the tile.
        rest.sort(key=lambda u: side.nations.index(u.get("owner")))
        return mine + rest

    # ------------------------------------------------------------------ #
    #                              COMMANDS                              #
    # ------------------------------------------------------------------ #

    def send_to_lane(self, unit, lane):
        """Pins a unit to the duel against whoever is on the other side."""
        far = lane.b if self.player in lane.a.nations else lane.a
        # A pin names an enemy nation; build_battle resolves it back to whichever
        # lane has that nation on the other side.
        unit["lane_target"] = far.nations[0]
        unit.pop("combat_stance", None)
        self.refresh_ui()

    def toggle_stance(self, unit):
        """Moves a unit to the back of its nation's queue for the front rank.

        Not out of the fight: combat_rules._availability reorders on this flag
        rather than filtering on it, so a held unit is seated once every unheld
        one has a slot. Which is why a held unit can still show up in the front
        pane -- it says [Release] there rather than [Hold].
        """
        if unit.get("combat_stance") == "RESERVE":
            unit.pop("combat_stance", None)
        else:
            unit["combat_stance"] = "RESERVE"
        self.refresh_ui()

    def clear_orders(self):
        for unit in self.my_units():
            unit.pop("lane_target", None)
            unit.pop("combat_stance", None)
        self.refresh_ui()

    def go_to_orders(self):
        """Bombard and retreat live in Orders, and both matter mid-battle."""
        if c.MAP_NAVIGATION_MODE == "CLASSIC":
            # Classic: Orders is reached only through Map.change_state, not
            # through navigate_view_mode/origin_screen -- see
            # ui.event_handler.navigate_view_mode. Flagging the map screen here
            # is how Orders_Screen.start_with_province learns Back should
            # reopen this battle instead of landing on the plain province menu
            # -- see its exit_screen.
            self.map_screen.pending_battle_return = True
            self.done = True
            self.map_screen.change_state("ORDERS")
        else:
            self.close_and_navigate("ORDERS")

    def exit_screen(self):
        """Closing the battle inspector -- the Close button, or Back/Esc.

        Classic: just pops the modal. Battle is only ever opened here while
        Map is the active state (either directly, or because Orders handed off
        to MAP before reopening it -- see go_to_orders), so popping reveals Map
        with the tile still selected, i.e. the plain province menu -- matching
        what Back does from Orders/Production in Classic.

        Preemptive: always lands on the bare map with the tile deselected,
        matching what Back does from Orders/Production there. Popping the
        modal with the base implementation would just resume whichever screen
        was underneath (Production or Orders, if this battle was reached via
        their own copy of the view-mode row) with the tile still selected;
        deselecting here directly, rather than relying on origin_screen's own
        exit_screen (see close_and_navigate, which forwards via go_to, not
        exit_screen), covers every origin in one place, including Map itself.
        """
        if c.MAP_NAVIGATION_MODE == "CLASSIC":
            self.done = True
            return
        if self.map_screen:
            self.map_screen.deselect_province()
        self.close_and_navigate("MAP")

    def go_to(self, state_name):
        """Overridden so ui.event_handler.navigate_view_mode's generic
        `origin.go_to(state_name)` (used for the shared view-mode button row
        this screen now also carries) closes this modal and forwards on
        correctly instead of just setting next_state, which nothing would
        ever read -- see close_and_navigate.
        """
        self.close_and_navigate(state_name)

    def close_and_navigate(self, state_name):
        """Closes this modal and hands off to `state_name` on whichever screen
        it was opened over -- Map by default, but Production or Orders when
        this battle was reached from their own copy of the view-mode row.
        Popping the modal alone would just resume that screen unchanged, which
        is wrong for anything other than Map (already showing beneath), so the
        request is forwarded on to it explicitly.
        """
        self.done = True
        if not (self.origin_screen is self.map_screen and state_name == "MAP"):
            self.origin_screen.go_to(state_name)

    # ------------------------------------------------------------------ #
    #                              LAYOUT                                #
    # ------------------------------------------------------------------ #

    def _layout(self):
        p = self.panel_rect
        top = p.y + 64
        view_h = p.bottom - 66 - VIEW_MODE_ROW_RESERVE - top
        col_w = (p.width - 2 * self.PAD - LANE_COL_W - 3 * 10) // 3

        x = p.x + self.PAD
        self.regions = {PANE_LANES: pygame.Rect(x, top, LANE_COL_W, view_h)}
        x += LANE_COL_W + 10
        for name in (PANE_FRONT, PANE_ENEMY, PANE_RESERVE):
            self.regions[name] = pygame.Rect(x, top + HEADER_H, col_w, view_h - HEADER_H)
            x += col_w + 10
        self.list_top = top
        self.view_h = view_h

    def pane_rects(self):
        return self.regions

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.rebuild()
        self._layout()
        self.elements = []
        self.row_paint = {}
        p = self.panel_rect

        btn_y = p.bottom - 52 - VIEW_MODE_ROW_RESERVE
        self.elements.append(
            self.button(p.x + self.PAD, btn_y, 150, "blue", "Unit Orders", self.go_to_orders))
        # Nothing to clear on a tile you command nothing on.
        if self.my_units():
            self.elements.append(
                self.button(p.x + self.PAD + 160, btn_y, 150, "orange", "Clear Lane Orders",
                            self.clear_orders))
        self.elements.append(
            self.button(p.right - self.PAD - 110, btn_y, 110, "red", "Close", self.exit_screen))

        # Deferred import: ui.event_handler imports this module at load time
        # to open battles, so importing it back at module scope here would close
        # a cycle.
        from ui import event_handler
        self.view_mode_buttons = view_mode_buttons.build(
            lambda mode: event_handler.navigate_view_mode(self.map_screen, mode, origin=self))
        view_mode_buttons.sync_highlight(self.view_mode_buttons, self.map_screen.secondary_mode)
        self.elements.extend(self.view_mode_buttons)

        if not self.visible or not self.battle.lanes:
            return

        self._lane_rows()
        lane, near, far = self.current()
        self._unit_rows(PANE_FRONT, near.front, lane, editable=self.is_mine(near))
        self._unit_rows(PANE_ENEMY, far.front, lane, editable=False)

        # The reserve column is our side's bench when we are in this fight --
        # ours to move, our allies' to count -- and both sides' when we are only
        # watching.
        if self.is_mine(near):
            self._unit_rows(PANE_RESERVE, self.side_bench(near), lane,
                            editable=True, is_bench=True)
        elif self.is_mine(far):
            self._unit_rows(PANE_RESERVE, self.side_bench(far), lane,
                            editable=True, is_bench=True)
        else:
            self._unit_rows(PANE_RESERVE, list(near.reserve) + list(far.reserve),
                            lane, editable=False)

    def _lane_rows(self):
        """One row per lane: the two sides' flags, and how the fight stands.

        Buttons carry no text -- _paint_lanes draws over them. A Button renders
        one string and a side is a row of flags, so the label was the wrong
        shape for it well before the names stopped fitting in the column.
        """
        rect = self.regions[PANE_LANES]
        # Every lane is selectable; the player's are picked out in colour so a
        # crowded tile still reads at a glance.
        mine = {id(lane) for lane in self.my_lanes()}
        self.row_paint[PANE_LANES] = []
        for i, y in self.pane_rows(PANE_LANES, len(self.battle.lanes), rect.y, rect.height):
            lane = self.battle.lanes[i]
            colour = "blue" if id(lane) in mine else "grey"
            btn = self.button(rect.x, y, LANE_COL_W, colour, "",
                              lambda idx=i: self._select(idx))
            btn.is_selected = (i == self.selected_lane)
            self.add_pane_row(PANE_LANES, btn)
            self.row_paint[PANE_LANES].append((btn.rect, lane))

    def _unit_rows(self, pane, unit_list, lane, editable, is_bench=False):
        rect = self.regions[pane]
        self.row_paint[pane] = []
        for i, y in self.pane_rows(pane, len(unit_list), rect.y, rect.height):
            unit = unit_list[i]
            held = unit.get("combat_stance") == "RESERVE"
            can_edit = editable and self.can_command(unit)

            if not can_edit:
                btn = self.button(rect.x, y, rect.width, "grey", "", lambda: None)
                btn.disabled = True
                note = ""
            elif is_bench:
                btn = self.button(rect.x, y, rect.width, "orange" if held else "green", "",
                                  lambda u=unit, l=lane: self.send_to_lane(u, l))
                note = f"{'HELD  ' if held else ''}->  lane {lane.index + 1}"
            else:
                btn = self.button(rect.x, y, rect.width, "blue", "",
                                  lambda u=unit: self.toggle_stance(u))
                # A held unit reaches the front rank whenever nobody else can
                # take the slot, so this pane has to be able to say so -- an
                # honest [Hold] on a unit that is already held reads as if the
                # flag had not stuck.
                note = "[Release]" if held else "[Hold]"
            self.add_pane_row(pane, btn)
            self.row_paint[pane].append((btn.rect, (unit, note)))

    # -- painting -------------------------------------------------------- #

    def _paint_lanes(self, surface):
        """`1.  [flag][flag]  v  [flag][flag]      6 v 3`"""
        small = fonts.get("small")
        for rect, lane in self.row_paint.get(PANE_LANES, ()):
            x = rect.x + 8
            top = rect.y + (rect.height - small.get_height()) // 2

            number = small.render(f"{lane.index + 1}.", True, c.UI_TEXT_LIGHT)
            surface.blit(number, (x, top))
            x += number.get_width() + 6

            near, far = self.near_far(lane)
            for n, side in enumerate((near, far)):
                if n:
                    versus = small.render("v", True, c.UI_TEXT_MUTED)
                    surface.blit(versus, (x, top))
                    x += versus.get_width() + 6
                x = self._paint_side_flags(surface, side, x, rect, small)

            tally = small.render(f"{len(near.front)} v {len(far.front)}",
                                 True, c.UI_TEXT_MUTED)
            surface.blit(tally, (rect.right - 10 - tally.get_width(), top))

    def _paint_side_flags(self, surface, side, x, rect, font):
        """A side's flags in a row, counting the overflow rather than truncating.

        A coalition of six will not fit in the column, and a truncated list of
        flags is worse than a short one with a number: it looks like the whole
        side is two nations.
        """
        for nation in side.nations[:LANE_FLAGS_SHOWN]:
            x = flag_icons.draw_flag_centered(surface, nation, self.map_screen.nation_data,
                                              x, rect.y, rect.height)
        extra = len(side.nations) - LANE_FLAGS_SHOWN
        if extra > 0:
            more = font.render(f"+{extra}", True, c.UI_TEXT_MUTED)
            surface.blit(more, (x, rect.y + (rect.height - font.get_height()) // 2))
            x += more.get_width() + 6
        return x

    def _paint_units(self, pane):
        """The stat block the sidebar shows, on the row it belongs to.

        Same helpers at labeled=False, so the two readings of a unit cannot
        drift. Bombardment goes on the end of the stat line rather than a third
        line of its own: pane_rows lays out one height for every row in a pane,
        and a gunner is not worth making every infantry row taller for.
        """
        def paint(surface):
            small = fonts.get("small")
            library = queries.get_unit_library()
            for rect, (unit, note) in self.row_paint.get(pane, ()):
                owner = unit.get("owner", "?")
                x = flag_icons.draw_flag_centered(surface, owner, self.map_screen.nation_data,
                                                  rect.x + 6, rect.y + 2, small.get_height())

                dim = owner != self.player or not self.can_command(unit)
                name = queries.get_condensed_unit_name(unit.get("type", "Unit"))
                name_surf = small.render(name, True,
                                         c.UI_TEXT_MUTED if dim else c.UI_TEXT_LIGHT)
                surface.blit(name_surf, (x, rect.y + 2))
                hp_surf = small.render(queries.format_health_percent(unit), True, c.UI_TEXT_MUTED)
                surface.blit(hp_surf, (x + name_surf.get_width() + 4, rect.y + 2))

                if note:
                    note_surf = small.render(note, True, c.UI_TEXT_LIGHT)
                    surface.blit(note_surf, (rect.right - 8 - note_surf.get_width(), rect.y + 2))

                stat_y = rect.y + 2 + small.get_height() + 2
                # Politics included: this row is a promise about what the unit
                # will actually do this turn, and the resolver scales its shot
                # by exactly this.
                dmg_mult = combat_rules.effective_damage_multiplier(
                    unit, self.map_screen.nation_data)
                def_mult = combat_rules.health_defense_multiplier(unit)
                end_x = draw_combat_stats(
                    surface, small, "", unit.get("attack", 0) * dmg_mult, unit.get("defense", 0) * def_mult,
                    int(unit.get("health", 0)), unit.get("speed", 0),
                    rect.x + 10, stat_y, (200, 200, 200), labeled=False)

                stats = library.get(unit.get("type", ""), {})
                if "bombard_attack" in stats:
                    draw_bombardment_stats(
                        surface, small,
                        unit.get("bombard_attack", stats.get("bombard_attack", 0)) * dmg_mult,
                        unit.get("bombard_range", stats.get("bombard_range", 0)),
                        end_x, stat_y, (200, 200, 200), base_text="", labeled=False)
        return paint

    def draw_elements(self, surface):
        """Rows crop to their own pane, and their decoration crops with them.

        Without this the screen leaned on GameState.draw_elements, which clips
        to a single content rect -- there are four here, so nothing was clipped
        at all and a long roster painted straight over the footer buttons.
        """
        self.draw_panes(surface, foregrounds={
            PANE_LANES: self._paint_lanes,
            PANE_FRONT: self._paint_units(PANE_FRONT),
            PANE_ENEMY: self._paint_units(PANE_ENEMY),
            PANE_RESERVE: self._paint_units(PANE_RESERVE),
        })

    def _select(self, index):
        self.selected_lane = index
        self.refresh_ui()

    def _composition(self, side):
        """`Vichy France 5 · German Reich 1` -- a side's members and their width."""
        return "  +  ".join(f"{m.nation} {len(m.front)}/{m.slots}" for m in side.members)

    def get_panel_title(self):
        owner = self.province.get("owner", "Unclaimed")
        verb = "Manage" if self.my_units() else "View"
        return f"{verb} Battle - Province {self.province.get('id')} ({owner})"

    def draw_body(self, surface):
        p = self.panel_rect

        if not self.visible:
            self.label(surface, "This province is hidden by fog of war.",
                       (p.x + self.PAD, self.list_top), preset="normal")
            return

        if not self.battle.lanes:
            self.label(surface, "No lanes here -- nobody on this tile is fighting anybody.",
                       (p.x + self.PAD, self.list_top), preset="normal")
            return

        lane, near, far = self.current()
        summary = (f"Combat width {self.battle.width} of {c.COMBAT_WIDTH}   |   "
                   f"{len(self.battle.lanes)} lane(s)   |   {lane.slots} slots per side")
        if not (self.is_mine(near) or self.is_mine(far)):
            summary += "   |   OBSERVING - you have no units in this duel"
        self.label(surface, summary, (p.x + self.PAD, p.y + 30))

        # Who is on each side and what width they were given. A side is a
        # coalition and the split between its members is the thing a player has
        # no other way to find out -- it is why their nine units field five.
        self.label(surface, f"{self._composition(near)}   v   {self._composition(far)}",
                   (p.x + self.PAD, p.y + 48))

        near_label = "YOUR SIDE" if self.is_mine(near) else side_name(near).upper()
        far_label = "ENEMY SIDE" if self.is_mine(near) else side_name(far).upper()
        if self.map_screen.tactical_mode and self.is_mine(near):
            near_label = "YOUR SIDE (tactical: one division is yours)"
        our_side = near if self.is_mine(near) else (far if self.is_mine(far) else None)
        if our_side is None:
            reserve_label = f"RESERVES ({len(near.reserve) + len(far.reserve)})"
        else:
            ours = len(self.bench())
            allied = len(self.side_bench(our_side)) - ours
            reserve_label = f"YOUR RESERVE ({ours})"
            if allied:
                reserve_label = f"SIDE RESERVE ({ours} yours / {allied} allied)"

        headings = (
            (PANE_FRONT, f"{near_label} ({len(near.front)}/{lane.slots})"),
            (PANE_ENEMY, f"{far_label} ({len(far.front)}/{lane.slots})"),
            (PANE_RESERVE, reserve_label),
        )
        for pane, text in headings:
            rect = self.regions[pane]
            self.label(surface, text, (rect.x, rect.y - HEADER_H + 4))

        ui_bars.draw_translucent_panel(
            surface, self.regions[PANE_LANES], (0, 0, 0, 60),
            border_color=c.UI_TEXT_MUTED, border_width=1)

    def draw_foreground(self, surface):
        for pane in (PANE_LANES, PANE_FRONT, PANE_ENEMY, PANE_RESERVE):
            rect = self.regions.get(pane)
            if rect and self.pane_scroll_limit(pane) > 0:
                self.draw_pane_scrollbar(surface, pane, rect.right - 15, rect.y, rect.height)

    def additional_events(self, event):
        self.route_pane_scroll(event)


def open_battle_screen(map_screen, origin_screen=None):
    """Opens the lane manager for the selected province."""
    from ui.screen_runner import _run_pygame_sub_screen

    province = map_screen.selected_province
    if not province:
        return
    _run_pygame_sub_screen(map_screen, Battle_Screen(map_screen, province, origin_screen=origin_screen))
