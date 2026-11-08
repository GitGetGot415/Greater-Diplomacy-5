"""Managing one tile's battle: which duel each of your units fights, and who
waits in reserve.

The Orders screen owns a compact unit-command panel on the left and this lane
manager fills the clear space beside it when opened. This is where the two
decisions the lane model gives a player are edited on a separate drag-and-drop
screen opened by the overview's Edit button (labeled View, and read-only, for a
player with no units here):

  - which enemy a unit faces, when more than one is standing here. The default
    is the heaviest front first, which is usually right and occasionally very
    wrong -- a nation that would rather finish off a weak neighbour than trade
    with the strong one has no other way to say so.
  - where a unit stands in the queue for the front rank. Holding a damaged unit
    back lets a fresh one take its slot, and a reserve takes no damage while
    the front bleeds. It is a preference, not a veto: a
    held unit still fills a slot nobody else can, because an empty slot is worse
    for the side than a hurt unit standing in it. Hold four of six men and the
    other two do not inherit four idle slots -- all four are still fielded.

Both are written straight onto the unit dict, where combat_rules.build_battle is
the only thing that reads them back. That is deliberate: a second store for
"who is fighting whom" is how the four callers of the old firing_lines drifted
apart in the first place. The screen is opened from Orders and closes back to
that Orders screen so battle inspection never strands the order controls.

A ModalScreen rather than a registered state, because it is an inspector rather
than a mode -- see the class docstring. It is launched from the Orders screen,
whose controls remain one step away so bombardment and retreat stay reachable
mid-battle.
"""

import pygame

import data.constants as c
from data import queries
from map_logic.system32 import combat_rules
from map_logic.actions import unit_actions
from ui.rendering.font_manager import fonts
from ui.widgets import flag_icons
from ui.panels import sidebar_info
from ui.bars import ui_bars, view_mode_buttons
from ui.navigation.modal_screen import ModalScreen
from ui.background_styles import BATTLE_CARD_COLORS, COMBAT_PANEL_STYLES, battle_card_color
from ui import dialogs
from ui.widgets.ui_elements import (
    draw_pixel_panel, draw_wrapped_icon_row, get_combat_stat_entries,
    get_bombardment_stat_entries, make_info_button,
)
from ui.widgets.text_utils import wrap_text

from ui.rendering import overlay_renderer, symbol_loader


#: Lane list and the selected lane's two combined side rosters.
PANE_LANES = "lanes"
PANE_FRONT = "front"
PANE_ENEMY = "enemy"
PANE_RESERVE = "reserve"
UNIT_PANES = (PANE_FRONT, PANE_ENEMY)

# Keep the original lane column beside the two opposing rosters.
LANE_COL_W = 200
LANE_ROW_H = 42
CARD_COLUMNS = 3
CARD_H = 86
CARD_GAP = 4
CARD_ICON_SIZE = 24
CARD_PADDING = 4
CARD_STAT_H = 16
ROW_H = CARD_H + CARD_GAP
COL_GAP = 10
HEADER_H = 26
SCROLLBAR_W = 15
SCROLLBAR_GAP = 4
UNIT_ICON_GAP = 4
UNIT_ICON_PADDING = 6
UNIT_ICON_SIZE = 48
COLOR_HELP_BUTTON_TOP = 8
#: Flags a lane row shows per side before it gives up and counts the rest. Two
#: keeps the compact lane button's flags and combat tally inside its width.
LANE_FLAGS_SHOWN = 2

#: Room reserved at the very bottom of the panel for the shared view-mode
#: button row (Resources/Blank/Units/Economy), which is drawn at the same
#: screen-fixed y as every other screen's copy of it -- see refresh_ui and
#: _layout, which both shrink to make room for it instead of drawing under it.
VIEW_MODE_ROW_RESERVE = 40

# The selected lane's projected winner lives below the scrolling panes and
# above the fixed footer controls. Keeping it outside the panes means it stays
# visible while a roster is scrolled, and changing the selected lane can replace
# the one-line forecast without making a second list compete for that space.
OUTCOME_H = 48
OUTCOME_GAP = 8


# The embedded inspector sits close under its title to leave room for the lanes.
EMBEDDED_TITLE_Y_OFFSET = 8


class Battle_Screen(ModalScreen):
    """A tile's lanes, and the player's units in them.

    Not a registered state like Orders_Screen: that would need an entry in
    main.py's state table, an on_enter hook and a row in the test harness's
    MAP_LAYERED_STATES, which is three files of state-machine wiring for a
    screen that inspects one province and closes. It normally runs as a panel
    owned by Orders_Screen; ModalScreen remains available for legacy direct
    callers and gives that fallback the dimmed freeze-frame and chrome.
    """

    PANEL_SIZE = (1240, 680)
    ROW_HEIGHT = ROW_H
    PAD = 16
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_DANGER
    PANEL_STYLE = COMBAT_PANEL_STYLES["main"]

    def __init__(self, map_screen, province, origin_screen=None, embedded_rect=None):
        self.province = province
        # Both set before super(), because ModalScreen.__init__ asks for the
        # title and the title depends on whether any of these units are ours.
        self.map_screen = map_screen
        self.player = map_screen.player_country
        # The screen this battle was pushed over, normally Orders -- see
        # close_and_navigate.
        self.origin_screen = origin_screen or map_screen
        self.embedded = embedded_rect is not None
        panel_size = embedded_rect.size if embedded_rect is not None else None
        super().__init__(map_screen, self.get_panel_title(), panel_size=panel_size)
        if embedded_rect is not None:
            self.panel_rect = pygame.Rect(embedded_rect)
            self.TITLE_Y_OFFSET = EMBEDDED_TITLE_Y_OFFSET
        # Hotseat and fog of war: the same rule the Orders panel uses. A province you
        # cannot see is not one whose order of battle you get to read.
        self.visible = queries.is_province_visible(map_screen, province["id"])
        self.selected_lane = 0
        self.regions = {}
        self.lane_outcome = None
        # {pane: [(rect, payload)]}, filled by refresh_ui and read by the
        # foreground painters. Safe to cache because Screen.scroll_by calls
        # refresh_ui on every wheel notch, so the rects never go stale.
        self.row_paint = {}
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              THE FIGHT                             #
    # ------------------------------------------------------------------ #

    def rebuild(self, *, unit_icon_size=(UNIT_ICON_SIZE, UNIT_ICON_SIZE)):
        """Re-reads the battle. Called after every change, so slot counts and
        lane membership update as the player edits rather than on close."""
        self.combat_width = combat_rules.combat_width_for_terrain(
            self.province.get("terrain"))
        self.battle = combat_rules.build_battle(
            [self.province.get("units", [])], self.map_screen.nation_data,
            width=self.combat_width, terrain=self.province.get("terrain"))
        self.combat_row_data = {}
        for unit in self.province.get("units", []):
            profile = self.battle.profiles.get(id(unit), unit)
            row = sidebar_info.unit_roster_row(profile, self.province, self.map_screen.nation_data, True)
            combat_owner = queries.get_unit_combat_owner(unit)
            row["unit_icon"] = symbol_loader.get_symbol(
                unit["type"], zoom=1, country=combat_owner,
                color=self.map_screen.nation_colors.get(combat_owner, c.UI_TEXT_LIGHT),
                fit_size=unit_icon_size)
            row["entries"] = get_combat_stat_entries(
                row["attack"], row["defense"], int(profile.get("health", 0)),
                profile.get("speed", 0), labeled=False, defense_bonus=row["fort"])
            if row["bombard"] is not None:
                row["entries"].extend(get_bombardment_stat_entries(*row["bombard"], labeled=False))
            self.combat_row_data[id(unit)] = row
        if self.selected_lane >= len(self.battle.lanes):
            self.selected_lane = 0

    def my_lanes(self):
        """The lanes this player holds a side in, which are the editable ones."""
        return [lane for lane in self.battle.lanes
                if self.is_mine(lane.a) or self.is_mine(lane.b)]

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
        return side is not None and any(
            unit.get("owner") == self.player
            for unit in side.front + side.reserve)

    def near_far(self, lane):
        """A lane's two sides, the player's first when they hold one.

        Every reading of a lane orders it this way -- the row in the list, the
        summary line, the two columns -- so a player never has to work out which
        half of "6 v 3" is theirs.
        """
        if self.is_mine(lane.b):
            return lane.b, lane.a
        return lane.a, lane.b

    @staticmethod
    def side_units(side):
        """All units visually contributing to a combat side.

        `side.nations` is intentionally the effective military allegiance, so
        a volunteer is listed under its host there.  The battle UI instead
        uses actual owners for its flags and roster identity.
        """
        return list(getattr(side, "front", ())) + list(getattr(side, "reserve", ()))

    def side_display_nations(self, side):
        """Actual owners in stable order for a side's visual presentation."""
        nations = []
        for unit in self.side_units(side):
            owner = unit.get("owner")
            if owner and owner not in nations:
                nations.append(owner)
        # Lightweight callers and a few UI layout tests provide only the
        # nation list. It is also a sensible fallback for an empty side.
        return nations or list(side.nations)

    def my_units(self):
        """The units on this tile the player may actually give orders to.

        In tactical mode a player commands one division, not a country, so the
        lane manager has to narrow to it the same way the Orders screen does --
        otherwise the one screen you open in the middle of a battle is the one
        that hands you the whole army back.
        """
        mine = [u for u in self.province.get("units", [])
                if u.get("owner") == self.player and not queries.unit_is_air_drop_recovering(u)]
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

        An ally's reserves are not the player's to move. They are still
        important to show in the side's column:
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

        side_unit_ids = {id(unit) for unit in self.side_units(side)}
        rest = [u for u in self.province.get("units", [])
                if id(u) in side_unit_ids
                and id(u) not in seated and id(u) not in commanded]
        # Grouped by nation so the flags read as blocks; sorted() is stable, so
        # within a nation they keep the order they stand in on the tile.
        display_nations = self.side_display_nations(side)
        rest.sort(key=lambda u: display_nations.index(u.get("owner")))
        return mine + rest

    # ------------------------------------------------------------------ #
    #                              COMMANDS                              #
    # ------------------------------------------------------------------ #

    def can_edit_realtime(self):
        return queries.require_realtime_turn_open(self.map_screen, "battle orders")

    def send_to_lane(self, unit, lane):
        """Pins a unit to the duel against whoever is on the other side."""
        if not self.can_command(unit) or not self.can_edit_realtime():
            return
        nation = queries.get_unit_combat_owner(unit)
        far = lane.b if nation in lane.a.nations else lane.a
        # A pin names an enemy nation; build_battle resolves it back to whichever
        # lane has that nation on the other side.
        target = next((enemy for enemy in far.nations
                       if queries.are_at_war(nation, enemy, self.map_screen.nation_data)), None)
        if target is None:
            return
        unit_actions.apply_battle_orders(
            self.map_screen, self.player, self.province, [(unit, target, False)])
        self.map_screen.invalidate_map_presentation_cache()
        self.refresh_ui()

    def toggle_stance(self, unit):
        """Moves a unit to the back of its nation's queue for the front rank.

        Not out of the fight: combat_rules._availability reorders on this flag
        rather than filtering on it, so a held unit is seated once every unheld
        one has a slot. A held unit can therefore still appear in the front
        column, with its reserve preference shown as HELD.
        """
        if not self.can_command(unit) or not self.can_edit_realtime():
            return
        unit_actions.apply_battle_orders(
            self.map_screen, self.player, self.province,
            [(unit, None, unit.get("combat_stance") != "RESERVE")])
        self.map_screen.invalidate_map_presentation_cache()
        self.refresh_ui()

    def clear_orders(self):
        if not self.can_edit_realtime():
            return
        unit_actions.apply_battle_orders(
            self.map_screen, self.player, self.province,
            [(unit, None, False) for unit in self.my_units()])
        self.map_screen.invalidate_map_presentation_cache()
        self.refresh_ui()

    def open_editor(self):
        """Opens the battle editor; a player with no units here opens it read-only."""
        if not self.visible:
            return
        if self.my_units() and (not self.map_screen.can_select_map_units()
                                or not self.can_edit_realtime()):
            return
        self.origin_screen.battle_editor_overview = self
        self.origin_screen.go_to("BATTLE_EDITOR")
        if not self.embedded:
            # Legacy modal callers must release the modal stack before the
            # controller can switch the underlying registered screen.
            self.done = True

    def _editor_closed(self):
        self.province = self.map_screen.id_to_province.get(self.province["id"], self.province)
        self.visible = queries.is_province_visible(self.map_screen, self.province["id"])
        self.refresh_ui()

    def _orders_state(self):
        # Deferred import: screens.game.map_input imports this module at load
        # time to open battles.
        from screens.game import map_input
        return map_input.orders_state(self.map_screen)

    def go_to_orders(self):
        """Bombard and retreat live in Orders, and both matter mid-battle."""
        if self.embedded:
            self.exit_screen()
            return
        # When the inspector is embedded in Orders, closing it simply removes
        # the child pane. Keep the handoff for legacy/direct modal opens too,
        # so every route still reaches Orders before anything else.
        if self.origin_screen is not self.map_screen:
            self.done = True
        else:
            self.close_and_navigate(self._orders_state())

    def exit_screen(self):
        """Closing the battle inspector -- the Close button, or Back/Esc.

        The battle inspector is normally embedded in Orders, where this removes
        only the right-hand pane and preserves the left panel. A legacy direct
        map opener is still forwarded into Orders.
        """
        if self.embedded:
            self.done = True
            close_panel = getattr(self.origin_screen, "close_battle_panel", None)
            if close_panel:
                close_panel(self)
            return
        if self.origin_screen is not self.map_screen:
            self.done = True
            return
        self.close_and_navigate(self._orders_state())

    def go_to(self, state_name):
        """Overridden so screens.game.map_input.navigate_view_mode's generic
        `origin.go_to(state_name)` (used for the shared view-mode button row
        this screen now also carries) closes this modal and forwards on
        correctly instead of just setting next_state, which nothing would
        ever read -- see close_and_navigate.
        """
        self.close_and_navigate(state_name)

    def close_and_navigate(self, state_name):
        """Closes this modal and hands off to `state_name` on whichever screen
        it was opened over. The ordinary battle-close path only marks this
        modal done, so Orders can resume unchanged; explicit view-mode changes
        use this forwarding path to switch the underlying screen as requested.
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
        view_mode_reserve = 0 if self.embedded else VIEW_MODE_ROW_RESERVE
        footer_top = p.bottom - 66 - view_mode_reserve
        self.outcome_rect = pygame.Rect(
            p.x + self.PAD, footer_top - OUTCOME_H,
            max(1, p.width - 2 * self.PAD), OUTCOME_H)
        view_h = max(HEADER_H + 1,
                     self.outcome_rect.top - OUTCOME_GAP - top)
        x = p.x + self.PAD
        self.regions = {PANE_LANES: pygame.Rect(
            x, top, LANE_COL_W, view_h)}
        x += LANE_COL_W + COL_GAP
        col_w = (p.width - 2 * self.PAD - LANE_COL_W - 2 * COL_GAP) // 2
        for pane in UNIT_PANES:
            self.regions[pane] = pygame.Rect(
                x, top + HEADER_H, col_w, view_h - HEADER_H)
            x += col_w + COL_GAP
        self.list_top = top
        self.view_h = view_h

    def pane_rects(self):
        return self.regions

    def show_color_help(self):
        dialogs.show_info(
            "Battle Card Colors",
            f"{BATTLE_CARD_COLORS['frontline'].capitalize()}: Frontline units.\n"
            f"{BATTLE_CARD_COLORS['reserve'].capitalize()}: Available reserves.\n"
            f"{BATTLE_CARD_COLORS['held'].capitalize()}: Held reserves.\n\n"
            "Muted, grayer cards: Units you cannot control.")

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def _build_footer(self, btn_y):
        p = self.panel_rect
        viewing = not self.my_units()
        edit = self.button(p.x + self.PAD, btn_y, 130, "blue",
                           "View" if viewing else "Edit", self.open_editor)
        edit.disabled = not (self.visible and (viewing or self.map_screen.can_select_map_units()))
        self.elements.append(edit)
        if self.embedded:
            self.elements.append(
                self.button(p.right - self.PAD - 130, btn_y, 130,
                            "red", "Close Battle", self.exit_screen, sound_kind="back"))
        else:
            self.elements.append(
                self.button(p.x + self.PAD + 140, btn_y, 150,
                            "blue", "Unit Orders", self.go_to_orders))
            self.elements.append(
                self.button(p.right - self.PAD - 110, btn_y, 110,
                            "red", "Close", self.exit_screen, sound_kind="back"))

    def refresh_ui(self):
        self.rebuild()
        self._layout()
        self.elements = []
        self.row_paint = {}
        self.card_surfaces = {}
        self.side_counts = {}
        self.lane_outcome = None
        p = self.panel_rect

        view_mode_reserve = 0 if self.embedded else VIEW_MODE_ROW_RESERVE
        btn_y = p.bottom - 52 - view_mode_reserve
        self._build_footer(btn_y)
        color_help = make_info_button(0, p.y + COLOR_HELP_BUTTON_TOP, self.show_color_help)
        color_help.rect.right = p.right - self.PAD
        self.elements.append(color_help)

        if self.embedded:
            self.view_mode_buttons = []
        else:
            # Deferred import: screens.game.map_input imports this module at load time
            # to open battles, so importing it back at module scope here would close
            # a cycle.
            from screens.game import map_input 
            self.view_mode_buttons = view_mode_buttons.build(
                lambda mode: map_input.navigate_view_mode(self.map_screen, mode, origin=self))
            view_mode_buttons.sync_highlight(self.view_mode_buttons, self.map_screen.secondary_mode)
            self.elements.extend(self.view_mode_buttons)

        if not self.visible or not self.battle.lanes:
            return

        self._lane_rows()
        lane, near, far = self.current()
        self.lane_outcome = self._estimate_lane_outcome(lane)
        for side, pane in ((near, PANE_FRONT), (far, PANE_ENEMY)):
            # Keep the player's whole available bench, including allied units,
            # while showing the opposing lane's own reserves in its column.
            reserves = self.side_bench(side) if self.is_mine(side) else side.reserve
            # Display available reserves before held units without changing
            # combat priority or separating the continuous roster into sections.
            reserves = sorted(reserves, key=lambda unit: unit.get("combat_stance") == "RESERVE")
            units = list(side.front) + list(reserves)
            self.side_counts[pane] = len(units)
            self._unit_cards(pane, units, reserve_ids={id(unit) for unit in reserves})

    def _lane_rows(self):
        """One row per lane: the two sides' flags, and how the fight stands.

        Buttons carry no text -- _paint_lanes draws over them. A Button renders
        one string and a side is a row of flags, so the label was the wrong
        shape for it well before the names stopped fitting in the column.
        """
        rect = self.regions[PANE_LANES]
        # Every lane is selectable; the player's are picked out in color so a
        # crowded tile still reads at a glance.
        mine = {id(lane) for lane in self.my_lanes()}
        self.row_paint[PANE_LANES] = []
        for i, y in self.pane_rows(PANE_LANES, len(self.battle.lanes), rect.y,
                                   rect.height, row_h=LANE_ROW_H):
            lane = self.battle.lanes[i]
            color = "blue" if id(lane) in mine else "grey"
            btn = self.button(rect.x, y, rect.width - SCROLLBAR_W - SCROLLBAR_GAP,
                              color, "", lambda idx=i: self._select(idx))
            btn.rect.height = LANE_ROW_H
            btn.height = LANE_ROW_H
            btn.is_selected = (i == self.selected_lane)
            self.add_pane_row(PANE_LANES, btn)
            self.row_paint[PANE_LANES].append((btn.rect, lane))

    def _unit_cards(self, pane, unit_list, *, reserve_ids):
        """Passive, cached cards; only lane rows and footer actions are buttons."""
        rect = self.regions[pane]
        card_w = (rect.width - SCROLLBAR_W - SCROLLBAR_GAP
                  - (CARD_COLUMNS - 1) * CARD_GAP) // CARD_COLUMNS
        self.row_paint[pane] = []
        rows = (len(unit_list) + CARD_COLUMNS - 1) // CARD_COLUMNS
        # A different lane can have fewer cards than the previously scrolled one.
        attrs = self.scroll_attrs(pane)
        limit = min(0, rect.height - rows * self.ROW_HEIGHT)
        setattr(self, attrs["attr"], max(limit, min(0, self.pane_scroll(pane))))
        for grid_row, y in self.pane_rows(pane, rows, rect.y, rect.height):
            for column in range(CARD_COLUMNS):
                index = grid_row * CARD_COLUMNS + column
                if index >= len(unit_list):
                    break
                unit = unit_list[index]
                card_rect = pygame.Rect(
                    rect.x + column * (card_w + CARD_GAP), y, card_w, CARD_H)
                self.row_paint[pane].append((card_rect, (unit, "")))
                self.card_surfaces[pane, id(unit)] = self._card_surface(
                    unit, card_rect.size, id(unit) in reserve_ids)

    def _card_surface(self, unit, size, is_reserve):
        surface = pygame.Surface(size, pygame.SRCALPHA)
        held = unit.get("combat_stance") == "RESERVE"
        color = battle_card_color(
            frontline=not is_reserve, held=held, controllable=self.can_command(unit))
        draw_pixel_panel(surface, surface.get_rect(), color,
                         self.PANEL_BORDER)
        row = self.combat_row_data[id(unit)]
        icon = row["unit_icon"]
        if icon is not None:
            icon = pygame.transform.scale_by(icon, CARD_ICON_SIZE / max(icon.get_size()))
            surface.blit(icon, icon.get_rect(
                center=(size[0] // 2, CARD_PADDING + CARD_ICON_SIZE // 2)))
        # Use the same stat entries as Orders and the editor, including the
        # separate fort bonus. Always show defense, including zero.
        entries = dict(row["entries"])
        entries.setdefault(c.ICON_DEFENSE, queries.format_number(row["defense"]))
        for index, key in enumerate((c.ICON_ATTACK, c.ICON_HEALTH, c.ICON_DEFENSE)):
            draw_wrapped_icon_row(
                surface, fonts.get("small"), [(key, entries[key])],
                CARD_PADDING, CARD_PADDING * 2 + CARD_ICON_SIZE + index * CARD_STAT_H,
                c.UI_TEXT_LIGHT, max(1, size[0] - CARD_PADDING * 2), icon_size=16)
        return surface

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

    def _paint_side_flags(self, surface, side, x, rect, font,
                          max_flags=LANE_FLAGS_SHOWN):
        """A side's flags in a row, counting the overflow rather than truncating.

        A coalition of six will not fit in the column, and a truncated list of
        flags is worse than a short one with a number: it looks like the whole
        side is two nations.
        """
        display_nations = self.side_display_nations(side)
        for nation in display_nations[:max_flags]:
            x = flag_icons.draw_flag_centered(surface, nation, self.map_screen.nation_data,
                                              x, rect.y, rect.height)
        extra = len(display_nations) - max_flags
        if extra > 0:
            more = font.render(f"+{extra}", True, c.UI_TEXT_MUTED)
            surface.blit(more, (x, rect.y + (rect.height - font.get_height()) // 2))
            x += more.get_width() + 6
        return x

    def _paint_side_heading(self, surface, rect, side, count_text):
        """Paints a side's flags and roster count above its unit column."""
        header_rect = pygame.Rect(rect.x, rect.y - HEADER_H, rect.width, HEADER_H)
        small = fonts.get("small")
        count_surf = small.render(count_text, True, c.UI_TEXT_DIM)
        available_width = max(1, header_rect.width - count_surf.get_width() - 8)
        flag_step = flag_icons.ROW_FLAG_SIZE[0] + 6
        display_nations = self.side_display_nations(side)
        max_flags = len(display_nations)
        while max_flags > 1:
            extra = len(display_nations) - max_flags
            extra_width = small.size(f"+{extra}")[0] + 6 if extra else 0
            if max_flags * flag_step + extra_width <= available_width:
                break
            max_flags -= 1
        self._paint_side_flags(
            surface, side, header_rect.x, header_rect, small,
            max_flags=max(1, max_flags))
        surface.blit(
            count_surf,
            count_surf.get_rect(midright=(header_rect.right, header_rect.centery)))

    def _estimate_lane_outcome(self, lane):
        """Project this lane independently, including its waiting reserves."""
        # Use the same combat projection as the map renderer.

        sides = [
            list(lane.a.front) + list(lane.a.reserve),
            list(lane.b.front) + list(lane.b.reserve),
        ]
        return overlay_renderer.estimated_combat_outcome(
            sides, self.map_screen.nation_data, province=self.province)

    def _paint_outcome(self, surface, lane, *, rect=None, outcome=None):
        """Shared outlook display for the overview and editor's narrow column."""
        rect = self.outcome_rect if rect is None else rect
        ui_bars.draw_translucent_panel(
            surface, rect, (0, 0, 0, 90),
            border_color=c.UI_TEXT_MUTED, border_width=1)

        small = fonts.get("small")
        heading = small.render(f"LANE {lane.index + 1} OUTLOOK", True, c.UI_TEXT_DIM)
        surface.blit(heading, (rect.x + 8, rect.y + 4))

        outcome = (self.lane_outcome if outcome is None else outcome) or {}
        winner_index = outcome.get("winner_side")
        if winner_index is None:
            for index, line in enumerate(wrap_text("No clear winner expected", small, rect.width - 16)):
                surface.blit(small.render(line, True, c.UI_TEXT_MUTED),
                             (rect.x + 8, rect.y + 24 + index * small.get_height()))
            return

        side = (lane.a, lane.b)[winner_index]
        turns = outcome.get("turns")
        if turns is None:
            turns_text = "time unknown"
        elif turns == 0:
            turns_text = "already winning"
        elif turns == 1:
            turns_text = "in 1 turn"
        else:
            turns_text = f"in {turns} turns"

        line_y = rect.y + 24
        prefix = small.render("Expected winner:", True, c.UI_TEXT_LIGHT)
        surface.blit(prefix, (rect.x + 8, line_y))
        x = rect.x + 8 + prefix.get_width() + 8
        turn_surf = small.render(turns_text, True, c.UI_TEXT_LIGHT)
        turn_x = rect.right - 8 - turn_surf.get_width()
        available_width = max(1, turn_x - x - 8)
        turn_y = line_y
        if available_width < flag_icons.ROW_FLAG_SIZE[0]:
            # Stack the same winner, flags and duration inside narrow panels.
            x = rect.x + 8
            line_y += small.get_height() + 4
            available_width = max(1, rect.width - 16)
            turn_x = x
            turn_y = line_y + small.get_height() + 4

        # Show as many coalition flags as fit, retaining a +N marker for any
        # remaining members using the same convention as the lane list.
        flag_step = flag_icons.ROW_FLAG_SIZE[0] + 6
        display_nations = self.side_display_nations(side)
        max_flags = len(display_nations)
        while max_flags > 1:
            extra = len(display_nations) - max_flags
            extra_width = small.size(f"+{extra}")[0] + 6 if extra else 0
            if max_flags * flag_step + extra_width <= available_width:
                break
            max_flags -= 1
        line_rect = pygame.Rect(x, line_y, max(1, available_width), small.get_height())
        self._paint_side_flags(surface, side, x, line_rect, small,
                               max_flags=max(1, max_flags))
        surface.blit(turn_surf, (turn_x, turn_y))

    def _paint_units(self, pane):
        """Blit cached cards without hover states or gameplay queries."""
        def paint(surface):
            for rect, (unit, _note) in self.row_paint.get(pane, ()):
                surface.blit(self.card_surfaces[pane, id(unit)], rect)
        return paint

    def draw_elements(self, surface):
        """Rows crop to their own pane, and their decoration crops with them.

        Each side has one clip region shared by its front and reserve cards.
        """
        self.draw_panes(surface, foregrounds={
            PANE_LANES: self._paint_lanes,
            **{pane: self._paint_units(pane) for pane in UNIT_PANES},
        })

    def _select(self, index):
        self.selected_lane = index
        self.refresh_ui()

    def _composition(self, side):
        """`Vichy France 5 Â· German Reich 1` -- a side's members and their width."""
        counts = {}
        for unit in self.side_units(side):
            owner = unit.get("owner", "?")
            counts[owner] = counts.get(owner, 0) + 1
        return "  +  ".join(
            f"{queries.get_country_display_name(nation, self.map_screen.nation_data)} {count}"
            for nation, count in counts.items())

    def get_panel_title(self):
        owner = self.province.get("owner", "Unclaimed")
        verb = "Manage" if self.my_units() else "View"
        owner_name = queries.get_country_display_name(owner, self.map_screen.nation_data)
        return f"{verb} Battle - Province {self.province.get('id')} ({owner_name})"

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
        summary = (f"Combat width {self.battle.width} of {self.combat_width}   |   "
                   f"{len(self.battle.lanes)} lane(s)   |   {lane.slots} slots per side")
        if not (self.is_mine(near) or self.is_mine(far)):
            summary += "   |   OBSERVING - you have no units in this duel"
        self.label(surface, summary, (p.x + self.PAD, p.y + 30))

        # Who is on each side and what width they were given. A side is a
        # coalition and the split between its members is the thing a player has
        # no other way to find out -- it is why their nine units field five.
        self.label(surface, f"{self._composition(near)}   v   {self._composition(far)}",
                   (p.x + self.PAD, p.y + 48))

        for side, pane in ((near, PANE_FRONT), (far, PANE_ENEMY)):
            self._paint_side_heading(
                surface, self.regions[pane], side,
                f"{self.side_counts[pane]} units")

        ui_bars.draw_translucent_panel(
            surface, self.regions[PANE_LANES], (0, 0, 0, 60),
            border_color=c.UI_TEXT_MUTED, border_width=1)
        self._paint_outcome(surface, lane)

    def draw_embedded(self, surface):
        """Paints the battle inspector into the right side of Orders.

        Unlike ModalScreen.draw(), this does not repaint the captured map or
        dim the whole display. Orders has already drawn its live map and owns
        the neighboring left panel; this method paints only this panel's
        frame, contents, controls, and scrollbars.
        """
        if not self.embedded:
            self.draw(surface)
            return

        ui_bars.draw_screen_panel(surface, self, self.get_panel_title())
        self.draw_body(surface)
        self.draw_elements(surface)
        self.draw_foreground(surface)

    def draw_foreground(self, surface):
        for pane in (PANE_LANES, *UNIT_PANES):
            rect = self.regions.get(pane)
            if rect:
                # Rows are clipped above this fixed edge as they scroll into
                # the footer, instead of disappearing a whole row early.
                pygame.draw.line(surface, c.UI_TEXT_MUTED,
                                 (rect.left, rect.bottom), (rect.right - 1, rect.bottom))
                # The shared helper shows negative scroll ranges and clears
                # stale hitboxes when a pane no longer needs a scrollbar.
                self.draw_pane_scrollbar(
                    surface, pane, rect.right - SCROLLBAR_W, rect.y, rect.height,
                    width=SCROLLBAR_W)

    def additional_events(self, event):
        self.route_pane_scroll(event)

