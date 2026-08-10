"""Native pygame replacement for the map editor's global diplomacy/factions
tkinter tool window -- see screens/editor_screens/__init__.py."""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, TextField, make_back_button
from ui.bars import ui_bars
from ui.scroll_panes import ScrollPanes
from ui.table_screen import truncate
from map_logic.rendering.font_manager import fonts
from map_logic.diplomacy.diplomacy_agreements import assign_puppet

# ==========================================
# GLOBAL DIPLOMACY & FACTIONS EDITOR
# ==========================================

class Diplomacy_Editor_Screen(ScrollPanes, MapOverlayScreen):
    """Wars, factions and puppets for the whole map on a single screen.

    Keeps the shape of the tkinter original: nations down the left, and the
    selected nation's relations laid out live to the right. Picking a nation
    only swaps what the right-hand side is editing -- and, like the original,
    reloads from nation_data, so switching away drops unsaved edits. Saving
    leaves the screen open so several nations can be edited in a row.
    """
    pans_camera = False
    overlay_alpha = 220

    ROW_HEIGHT = 30
    NAT_W = 260
    COL_W = 296
    COL_GAP = 10
    LIST_VIEW_H = 390
    # Each scrollable region keeps its own offset/track attributes so the four
    # lists on screen scroll independently.
    REGIONS = ("nations", "wars", "members", "master")
    PUPPET_TYPES = (c.PUPPET_TYPE_AUTONOMOUS, c.PUPPET_TYPE_INTEGRATED)

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 1240, 660))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"

        self.countries = sorted(queries.get_living_nations(map_screen.map_data))
        self.target = None
        self.others = []
        self.wars = set()
        self.members = set()
        self.is_leader = False
        self.master = "None"
        self.puppet_type = c.PUPPET_TYPE_AUTONOMOUS

        for name in self.REGIONS:
            setattr(self, f"_scroll_{name}", 0)

        self.faction_field = TextField(0, 0, 300, 36, "", label="Faction Name:")
        self._layout()

        if self.countries:
            self.select_nation(self.countries[0])
        else:
            self.refresh_ui()

    def _layout(self):
        p = self.panel_rect
        self.nat_x = p.x + 16
        self.nations_top = p.y + 108
        self.nations_view_h = p.bottom - 16 - self.nations_top

        self.cols_x = self.nat_x + self.NAT_W + 20
        self.lists_top = p.y + 132
        self.row_a_y = self.lists_top + self.LIST_VIEW_H + 20
        self.row_b_y = self.row_a_y + 56

        self.regions = {"nations": pygame.Rect(self.nat_x, self.nations_top, self.NAT_W, self.nations_view_h)}
        for i, name in enumerate(("wars", "members", "master")):
            self.regions[name] = pygame.Rect(self._col_x(i), self.lists_top, self.COL_W, self.LIST_VIEW_H)

        # Published per-region so scroll_attrs's content_rect_attr can point
        # handle_content_drag/draw_elements at each region's own rect by name.
        for name, rect in self.regions.items():
            setattr(self, f"_content_{name}", rect)

    def _col_x(self, index):
        return self.cols_x + index * (self.COL_W + self.COL_GAP)

    @property
    def listening_for(self):
        """Keeps the global BACK keybind from closing the editor mid-edit."""
        return self.faction_field.active

    # ------------------------------------------------------------------ #
    #                             SELECTION                              #
    # ------------------------------------------------------------------ #

    def select_nation(self, cid):
        """Loads a nation into the right-hand side, discarding unsaved edits."""
        data = self.map_screen.nation_data.get(cid, {})
        self.target = cid
        self.others = [n for n in self.countries if n != cid]

        self.wars = {n for n in data.get("at_war_with", []) if n in self.others}
        self.is_leader = bool(data.get("is_faction_leader", False))
        self.master = data.get("master", "") or "None"
        self.puppet_type = data.get("puppet_type", "") or c.PUPPET_TYPE_AUTONOMOUS

        faction = data.get("faction", "")
        self.faction_field.text = faction
        self.faction_field.active = False
        self.members = {n for n in self.others
                        if faction and self.map_screen.nation_data.get(n, {}).get("faction", "") == faction}

        for name in ("wars", "members", "master"):
            setattr(self, f"_scroll_{name}", 0)
        self.refresh_ui()

    def toggle_membership(self, group, name):
        group.symmetric_difference_update({name})
        self.refresh_ui()

    def set_master(self, name):
        self.master = name
        self.refresh_ui()

    def toggle_leader(self):
        self.is_leader = not self.is_leader
        self.refresh_ui()

    def cycle_puppet_type(self):
        i = self.PUPPET_TYPES.index(self.puppet_type) if self.puppet_type in self.PUPPET_TYPES else 0
        self.puppet_type = self.PUPPET_TYPES[(i + 1) % len(self.PUPPET_TYPES)]
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                               SAVING                               #
    # ------------------------------------------------------------------ #

    def save(self):
        if not self.target:
            return

        nation_data = self.map_screen.nation_data
        target = self.target
        data = nation_data.get(target, {})

        # 1. Wars, kept bidirectional -- drop target from everyone, then re-add the picks.
        for name in self.countries:
            if target in nation_data[name].get("at_war_with", []):
                nation_data[name]["at_war_with"].remove(target)
        data["at_war_with"] = sorted(self.wars)
        for enemy in self.wars:
            if target not in nation_data[enemy].get("at_war_with", []):
                nation_data[enemy].setdefault("at_war_with", []).append(target)

        # 2. Faction membership.
        new_faction = self.faction_field.text.strip()
        data["faction"] = new_faction
        data["is_faction_leader"] = self.is_leader

        for name in self.others:
            if name in self.members:
                nation_data[name]["faction"] = new_faction
                if new_faction:
                    nation_data[name]["is_faction_leader"] = False
            elif new_faction and nation_data[name].get("faction", "") == new_faction:
                nation_data[name]["faction"] = ""
                nation_data[name]["is_faction_leader"] = False

        # 3. Puppet state.
        old_master = data.get("master", "")
        if old_master and old_master != "None" and old_master in nation_data:
            if target in nation_data[old_master].get("puppets", []):
                nation_data[old_master]["puppets"].remove(target)

        if self.master and self.master != "None" and self.master != target:
            assign_puppet(self.map_screen.map_data, nation_data, self.master, target, self.puppet_type)
        else:
            data["master"] = ""
            data["puppet_type"] = ""

        self.map_screen.refresh_diplomacy_maps()
        self.map_screen.show_feedback(f"Diplomacy saved for {target}")
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def _row(self, x, y, width, color, text, callback):
        btn = Button(x, y, "list_row", color, text, callback, font_preset="button_small")
        btn.rect.width = width
        return btn

    def _columns(self):
        """(region, header, rows, is_checked, on_click) for the three right-hand lists."""
        return [
            ("wars", "At War With", self.others,
             lambda n: n in self.wars, lambda n: self.toggle_membership(self.wars, n)),
            ("members", "Faction Members", self.others,
             lambda n: n in self.members, lambda n: self.toggle_membership(self.members, n)),
            ("master", "Master Nation", ["None"] + self.others,
             lambda n: n == self.master, self.set_master),
        ]

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [make_back_button(self.exit_screen, pos=(self.nat_x, p.y + 10))]

        for i, y in self.pane_rows("nations", len(self.countries), self.nations_top, self.nations_view_h):
            cid = self.countries[i]
            btn = self._row(self.nat_x, y, self.NAT_W - 24, "blue", truncate(cid, 26),
                            lambda cc=cid: self.select_nation(cc))
            btn.is_selected = cid == self.target
            btn.pane = "nations"
            btn.click_guard = self._guard_nations
            self.elements.append(btn)

        if not self.target:
            return

        for idx, (region, _header, rows, is_checked, on_click) in enumerate(self._columns()):
            col_x = self._col_x(idx)
            single = region == "master"
            for i, y in self.pane_rows(region, len(rows), self.lists_top, self.LIST_VIEW_H):
                name = rows[i]
                checked = is_checked(name)
                label = truncate(name, 28) if single else f"{'[X]' if checked else '[  ]'} {truncate(name, 24)}"
                btn = self._row(col_x, y, self.COL_W - 24, "green" if checked else "blue", label,
                                lambda n=name, cb=on_click: cb(n))
                btn.is_selected = checked
                btn.pane = region
                btn.click_guard = getattr(self, f"_guard_{region}")
                self.elements.append(btn)

        self.faction_field.rect.topleft = (self.cols_x + 130, self.row_a_y)
        self.elements.append(self.faction_field)

        leader_btn = Button(self.cols_x + 470, self.row_a_y - 2, "editor_ui",
                            "green" if self.is_leader else "grey",
                            f"Faction Leader: {'Yes' if self.is_leader else 'No'}",
                            self.toggle_leader, font_preset="button_small")
        leader_btn.is_selected = self.is_leader
        self.elements.append(leader_btn)

        self.elements.append(Button(self.cols_x, self.row_b_y, "editor_ui", "blue",
                                    f"Puppet Type: {self.puppet_type}", self.cycle_puppet_type,
                                    font_preset="button_small"))
        self.elements.append(Button(self.cols_x + 470, self.row_b_y - 5, "medium", "green",
                                    "Save Changes", self.save))

    def pane_rects(self):
        return self.regions

    def additional_events(self, event):
        self.route_pane_scroll(event)

    def draw_elements(self, surface):
        """Four independent scrolling regions: nations plus the three columns."""
        self.draw_panes(surface)

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(33, 150, 243), border_width=2)
        ui_bars.draw_centered_title(surface, "Global Diplomacy & Factions", p.y + 14, "heading2")

        small = fonts.get("small")
        surface.blit(small.render("Nations:", True, c.UI_TEXT_DIM), (self.nat_x, self.nations_top - 20))
        pygame.draw.line(surface, (70, 70, 95), (self.cols_x - 10, p.y + 60),
                         (self.cols_x - 10, p.bottom - 16), 1)

        if not self.target:
            msg = fonts.get("heading2").render("Select a nation...", True, c.UI_TEXT_LIGHT)
            surface.blit(msg, msg.get_rect(center=(self.cols_x + 450, p.centery)))
            return

        heading = fonts.get("heading2").render(f"Editing: {self.target}", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(heading, (self.cols_x, p.y + 66))

        for idx, (region, header, rows, _is_checked, _on_click) in enumerate(self._columns()):
            col_x = self._col_x(idx)
            surface.blit(small.render(header, True, c.UI_TEXT_DIM), (col_x, self.lists_top - 20))
            if not rows:
                surface.blit(small.render("None available.", True, c.UI_TEXT_MUTED),
                             (col_x + 4, self.lists_top + 6))
            self.draw_list_scrollbar(surface, col_x + self.COL_W - 18, self.lists_top, self.LIST_VIEW_H,
                                     **self.scroll_attrs(region))

        self.draw_list_scrollbar(surface, self.nat_x + self.NAT_W - 18, self.nations_top,
                                 self.nations_view_h, **self.scroll_attrs("nations"))
