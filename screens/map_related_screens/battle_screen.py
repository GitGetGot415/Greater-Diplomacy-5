"""Managing one tile's battle: which duel each of your units fights, and who
waits in reserve.

The province sidebar shows the same fight, but read-only and squeezed into 370
pixels. This is where the two decisions the lane model actually gives a player
live:

  - which enemy a unit faces, when more than one is standing here. The default
    is the heaviest front first, which is usually right and occasionally very
    wrong -- a nation that would rather finish off a weak neighbour than trade
    with the strong one has no other way to say so.
  - whether a unit is in the front rank at all. Holding a damaged unit back lets
    a fresh one take its slot, and a reserve takes no damage and recovers morale
    while the front bleeds.

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
from ui import text_utils
from ui.bars import ui_bars
from ui.modal_screen import ModalScreen

#: Panes, left to right. Lane list, then the selected lane's three columns.
PANE_LANES = "lanes"
PANE_FRONT = "front"
PANE_ENEMY = "enemy"
PANE_RESERVE = "reserve"

LANE_COL_W = 210


def side_name(side):
    """A side in words, for anywhere a flag will not fit."""
    return " + ".join(side.nations)
ROW_H = 30
HEADER_H = 26


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

    def __init__(self, map_screen, province):
        self.province = province
        # Both set before super(), because ModalScreen.__init__ asks for the
        # title and the title depends on whether any of these units are ours.
        self.map_screen = map_screen
        self.player = map_screen.player_country
        super().__init__(map_screen, self.get_panel_title())
        # Hotseat and fog of war: the same rule the sidebar uses. A province you
        # cannot see is not one whose order of battle you get to read.
        self.visible = queries.is_province_visible(map_screen, province["id"])
        self.selected_lane = 0
        self.regions = {}
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
        if self.player in lane.b.nations:
            return lane, lane.b, lane.a
        return lane, lane.a, lane.b

    def is_mine(self, side):
        return side is not None and self.player in side.nations

    def my_units(self):
        return [u for u in self.province.get("units", [])
                if u.get("owner") == self.player]

    def bench(self):
        """Our units in no front rank anywhere -- the pool a lane draws from."""
        seated = {id(u) for lane in self.battle.lanes
                  for side in (lane.a, lane.b) for u in side.front}
        return [u for u in self.my_units() if id(u) not in seated]

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
        self.done = True
        self.map_screen.change_state("ORDERS")

    # ------------------------------------------------------------------ #
    #                              LAYOUT                                #
    # ------------------------------------------------------------------ #

    def _layout(self):
        p = self.panel_rect
        top = p.y + 64
        view_h = p.bottom - 66 - top
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
        p = self.panel_rect

        btn_y = p.bottom - 52
        self.elements.append(
            self.button(p.x + self.PAD, btn_y, 150, "blue", "Unit Orders", self.go_to_orders))
        # Nothing to clear on a tile you command nothing on.
        if self.my_units():
            self.elements.append(
                self.button(p.x + self.PAD + 160, btn_y, 150, "orange", "Clear Lane Orders",
                            self.clear_orders))
        self.elements.append(
            self.button(p.right - self.PAD - 110, btn_y, 110, "red", "Close", self.exit_screen))

        if not self.visible or not self.battle.lanes:
            return

        self._lane_rows()
        lane, near, far = self.current()
        self._unit_rows(PANE_FRONT, near.front, lane, editable=self.is_mine(near))
        self._unit_rows(PANE_ENEMY, far.front, lane, editable=False)

        # The reserve column is the player's own bench when they are in this
        # fight, and both sides' reserves when they are only watching.
        if self.is_mine(near) or self.is_mine(far):
            self._unit_rows(PANE_RESERVE, self.bench(), lane, editable=True, is_bench=True)
        else:
            self._unit_rows(PANE_RESERVE, list(near.reserve) + list(far.reserve),
                            lane, editable=False)

    def _lane_rows(self):
        rect = self.regions[PANE_LANES]
        # Every lane is selectable; the player's are picked out in colour so a
        # crowded tile still reads at a glance.
        mine = {id(lane) for lane in self.my_lanes()}
        for i, y in self.pane_rows(PANE_LANES, len(self.battle.lanes), rect.y, rect.height):
            lane = self.battle.lanes[i]
            # Truncate each name rather than the joined string, so the second
            # nation is never the half that disappears -- "Soviet Union v ..."
            # names one side of a duel and is useless for picking between two.
            room = max(4, ((LANE_COL_W - 14) // 9 - 6) // 2)
            label = (f"{i + 1}. {text_utils.truncate_chars(side_name(lane.a), room)}"
                     f" v {text_utils.truncate_chars(side_name(lane.b), room)}")
            colour = "blue" if id(lane) in mine else "grey"
            btn = self.button(rect.x, y, LANE_COL_W, colour, label,
                              lambda idx=i: self._select(idx))
            btn.is_selected = (i == self.selected_lane)
            self.add_pane_row(PANE_LANES, btn)

    def _unit_rows(self, pane, unit_list, lane, editable, is_bench=False):
        rect = self.regions[pane]
        for i, y in self.pane_rows(pane, len(unit_list), rect.y, rect.height):
            unit = unit_list[i]
            name = queries.get_condensed_unit_name(unit.get("type", "Unit"))
            held = unit.get("combat_stance") == "RESERVE"

            if not editable:
                label = f"{name}  {int(unit.get('health', 0))}hp"
                if unit.get("owner") != self.player:
                    label = f"[{unit.get('owner', '?')[:3].upper()}] " + label
                btn = self.button(rect.x, y, rect.width, "grey",
                                  text_utils.truncate_chars(label, (rect.width - 14) // 9),
                                  lambda: None)
                btn.disabled = True
            elif is_bench:
                label = f"{'HELD ' if held else ''}{name}  ->  lane {lane.index + 1}"
                btn = self.button(rect.x, y, rect.width, "orange" if held else "green",
                                  text_utils.truncate_chars(label, (rect.width - 14) // 9),
                                  lambda u=unit, l=lane: self.send_to_lane(u, l))
            else:
                label = f"{name}  {int(unit.get('health', 0))}hp  [Hold]"
                btn = self.button(rect.x, y, rect.width, "blue",
                                  text_utils.truncate_chars(label, (rect.width - 14) // 9),
                                  lambda u=unit: self.toggle_stance(u))
            self.add_pane_row(pane, btn)

    def _select(self, index):
        self.selected_lane = index
        self.refresh_ui()

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
        self.label(surface, summary, (p.x + self.PAD, p.y + 44))

        near_label = "YOUR SIDE" if self.is_mine(near) else side_name(near).upper()
        far_label = "ENEMY SIDE" if self.is_mine(near) else side_name(far).upper()
        if self.is_mine(near) or self.is_mine(far):
            reserve_label = f"YOUR RESERVE ({len(self.bench())})"
        else:
            reserve_label = f"RESERVES ({len(near.reserve) + len(far.reserve)})"

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


def open_battle_screen(map_screen):
    """Opens the lane manager for the selected province."""
    from ui.screen_runner import _run_pygame_sub_screen

    province = map_screen.selected_province
    if not province:
        return
    _run_pygame_sub_screen(map_screen, Battle_Screen(map_screen, province))
