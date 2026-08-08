"""Historical Leaders Editor: a dated timeline of name/adjective/color/flag/
portrait/leader_name/leader_title per country, saved to
data/json/historical_leaders.json.

Left column is the working roster of countries being tracked; the right
column -- much wider, since each row holds several fields -- lists the active
country's timeline as editable cards, one per dated entry. An entry applies
from its own date onward until a later entry supersedes it, field by field
independently (see queries.apply_historical_leader_timeline). Flag and
portrait, like color, start unset (None) on every entry -- a country with no
override anywhere in its timeline just keeps using its normal flag/portrait.

Saving here doesn't touch any scenario file directly: data/map/load_map.py
re-applies the saved timeline to every scenario under scenarios/historical
at load time, keyed off that scenario's own date, so edits made here always
take effect the next time a historical scenario is opened.
"""
import copy
import json
import pygame
from gameState import GameState
import data.constants as c
from data import queries
from ui import confirm_dialog
from ui.bars import ui_bars
from ui.table_screen import truncate
from ui_elements import Button, TextField
from map_logic.rendering.font_manager import fonts

PAD = 20
TOP_Y = 100
ROSTER_W = 300
ROSTER_ROW_H = 36
ENTRY_ROW_H = 150
FIELD_H = 32
COLOR_SWATCH_SIZE = 34
IMAGE_SWATCH_SIZE = 34
# Thumbnail sizes the flag/portrait swatches render their preview at --
# smaller than the game's actual c.FLAG_SIZE/c.PORTRAIT_SIZE, just enough
# to sit inside an IMAGE_SWATCH_SIZE square button.
FLAG_PREVIEW_SIZE = (30, 20)
PORTRAIT_PREVIEW_SIZE = (30, 30)
# Vertical offsets of each entry card's two field rows, relative to the
# card's own top -- kept well apart so the date/name/adjective/color row
# reads as clearly separate from the leader row below it.
ROW1_Y_OFFSET = 26
ROW2_Y_OFFSET = 92

# Display convention: month is shown/edited as 1-12, matching how the rest of
# the editors (e.g. ui/editor_screens.py's Editor_Date_Screen) present dates
# to a human. Storage (both the in-memory working buffer here and the saved
# JSON) keeps that same 1-12 value -- only queries.apply_historical_leader_timeline
# converts down to TimeHandler's 0-based month_index when it compares against
# a scenario's live date.


def _new_entry(year=c.START_YEAR):
    return {"year": year, "month": 1, "day": 1,
            "name": "", "adjective": "", "leader_name": "", "leader_title": ""}


def _date_key(entry):
    def as_int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    return (as_int(entry.get("year", 0)), as_int(entry.get("month", 0)), as_int(entry.get("day", 0)))


class Historical_Leaders_Editor(GameState):
    back_state = "NEW_GAME"
    title = "Historical Leaders & Names"

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 35, 20)

        self._load_from_disk()

        self._scroll_roster = 0
        self._scroll_timeline = 0
        self._max_roster = 0
        self._max_timeline = 0
        self._entry_layout = []

        self.refresh_ui()

    def _load_from_disk(self):
        """(Re)builds self.data/roster/active_country from whatever's
        currently saved in historical_leaders.json -- shared by __init__,
        Import and Reset, which all need to throw away in-memory state and
        start over from the file on disk."""
        raw = queries.get_historical_leader_timeline()
        self.data = {country: sorted((dict(e) for e in entries), key=_date_key)
                    for country, entries in copy.deepcopy(raw).items()}
        self.roster = sorted(self.data.keys())
        self.active_country = self.roster[0] if self.roster else None

    @property
    def listening_for(self):
        """Keeps the global BACK keybind from closing the editor mid-edit."""
        return any(getattr(el, "active", False) for el in self.elements)

    # ------------------------------------------------------------------ #
    #                               LAYOUT                                #
    # ------------------------------------------------------------------ #

    def _layout(self):
        bottom = c.SCREEN_HEIGHT - PAD - 70
        self.roster_rect = pygame.Rect(PAD, TOP_Y, ROSTER_W, bottom - TOP_Y)

        timeline_x = PAD + ROSTER_W + 30
        self.timeline_rect = pygame.Rect(timeline_x, TOP_Y, c.SCREEN_WIDTH - timeline_x - PAD, bottom - TOP_Y)

        self.regions = {"roster": self.roster_rect, "timeline": self.timeline_rect}
        for name, rect in self.regions.items():
            setattr(self, f"_content_{name}", rect)

        tx = self.timeline_rect.x + 12
        self.field_x = {
            "year": tx, "month": tx + 62, "day": tx + 116,
            "name": tx + 172, "adjective": tx + 334, "color": tx + 506,
            "leader_name": tx, "leader_title": tx + 300,
            "flag": tx + 588, "portrait": tx + 706,
        }

    def _scroll_attrs(self, name):
        return {"attr": f"_scroll_{name}", "limit_attr": f"_max_{name}",
                "track_attr": f"_track_{name}", "handle_attr": f"_handle_{name}",
                "drag_attr": f"_drag_{name}", "content_rect_attr": f"_content_{name}"}

    def _rows_of(self, name, count, top, view_h, row_h):
        # view_h is NOT forwarded to layout_list_rows: passing it explicitly
        # would let it compute max_scroll against the full (taller) view_h
        # while cull_bottom -- which actually gates clicks -- is shorter by
        # row_h-2, leaving the last row a permanent sliver short of being
        # clickable once fully scrolled into view. Omitting it makes the
        # function derive its own view_h from cull_bottom instead, so the
        # scroll limit and the clickable boundary always agree (see the
        # matching comment in ui/turn_editor.py's refresh_ui).
        attrs = self._scroll_attrs(name)
        return self.layout_list_rows(count, row_h, top,
                                     cull_top=top - 1, cull_bottom=top + view_h - row_h + 2,
                                     attr=attrs["attr"], limit_attr=attrs["limit_attr"],
                                     guard_attr=f"_guard_{name}")

    # ------------------------------------------------------------------ #
    #                          FIELD <-> DATA SYNC                       #
    # ------------------------------------------------------------------ #

    def _sync_entries(self):
        """Pulls live text out of on-screen fields before they get rebuilt or saved."""
        for el in self.elements:
            entry = getattr(el, "entry_ref", None)
            if entry is not None:
                entry[el.entry_key] = el.text

    # ------------------------------------------------------------------ #
    #                               ACTIONS                               #
    # ------------------------------------------------------------------ #

    def select_country(self, country):
        self._sync_entries()
        self.active_country = country
        self._scroll_timeline = 0
        self.refresh_ui()

    def add_country(self):
        self._sync_entries()
        all_playable = sorted(name for name, stats in queries.get_country_data().items()
                              if stats.get("is_playable") and name not in c.UNPLAYABLE_NATIONS)
        available = [n for n in all_playable if n not in self.data]
        if not available:
            confirm_dialog.show_info("Add Country", "Every playable country is already being tracked.")
            return

        def on_pick(country):
            self.data[country] = []
            self.roster = sorted(self.data.keys())
            self.active_country = country
            self._scroll_roster = 0
            self._scroll_timeline = 0
            self.refresh_ui()

        queries.open_listbox_selector(self, "Add Country", "Choose a country to track:", available, on_pick)

    def remove_country(self, country):
        def on_confirm(ok):
            if not ok:
                return
            self.data.pop(country, None)
            self.roster = sorted(self.data.keys())
            if self.active_country == country:
                self.active_country = self.roster[0] if self.roster else None
            self.refresh_ui()

        count = len(self.data.get(country, []))
        confirm_dialog.ask_yes_no(
            "Remove Country",
            f"Stop tracking {country} and discard its {count} timeline entr{'y' if count == 1 else 'ies'}?\n"
            f"This isn't written to disk until you Save Timeline.",
            on_confirm)

    def add_entry(self):
        if not self.active_country:
            return
        self._sync_entries()
        entries = self.data[self.active_country]

        if entries:
            last = entries[-1]
            entry = {k: last.get(k, "") for k in
                     ("year", "month", "day", "name", "adjective", "leader_name", "leader_title")}
            entry["color"] = last.get("color")
            entry["flag_data"] = last.get("flag_data")
            entry["portrait_data"] = last.get("portrait_data")
        else:
            base = queries.get_country_data().get(self.active_country, {})
            entry = _new_entry()
            entry["name"] = base.get("name", self.active_country)
            entry["adjective"] = base.get("adjective", "")
            # Colour/flag/portrait all start unset (None) rather than
            # pre-filled from the country's current appearance -- existing
            # countries keep whatever they already have until someone
            # deliberately opens the swatch and picks something for this entry.
            entry["color"] = None
            entry["flag_data"] = None
            entry["portrait_data"] = None

        entries.append(entry)
        self.refresh_ui()

    def delete_entry(self, entry):
        self._sync_entries()
        entries = self.data.get(self.active_country, [])
        entries[:] = [e for e in entries if e is not entry]
        self.refresh_ui()

    def pick_color(self, entry):
        self._sync_entries()
        current = entry.get("color") or queries.get_country_data().get(
            self.active_country, {}).get("color", [150, 150, 150])

        def on_pick(rgb):
            entry["color"] = list(rgb)
            self.refresh_ui()

        queries.open_color_picker(self, f"{self.active_country} Color", current, on_pick)

    def clear_color(self, entry):
        self._sync_entries()
        entry["color"] = None
        self.refresh_ui()

    def _pick_image(self, entry, field, browse_dir, size, label):
        """Shared flag/portrait file-import flow: browse, scale to the game's
        fixed flag/portrait dimensions, and stash it Base64-encoded on the
        entry -- same storage format country_data already uses, so a set
        entry overrides the country's normal appearance and a cleared one
        (None) just falls back to whatever the country already has."""
        self._sync_entries()

        def on_picked(file_path):
            if not file_path:
                return
            try:
                img = pygame.image.load(file_path).convert_alpha()
                scaled = pygame.transform.scale(img, size)
            except Exception:
                confirm_dialog.show_error(f"Import Failed", f"Could not load that image as a {label.lower()}.")
                return
            entry[field] = queries.encode_surf_to_b64(scaled)
            self.refresh_ui()

        queries.open_file_browser(self, f"{self.active_country} {label}", browse_dir,
                                  extensions=[".png", ".jpg", ".jpeg", ".bmp"], on_result=on_picked)

    def pick_flag(self, entry):
        self._pick_image(entry, "flag_data", c.FLAGS_DIR, c.FLAG_SIZE, "Flag")

    def clear_flag(self, entry):
        self._sync_entries()
        entry["flag_data"] = None
        self.refresh_ui()

    def pick_portrait(self, entry):
        self._pick_image(entry, "portrait_data", c.PORTRAITS_DIR, c.PORTRAIT_SIZE, "Portrait")

    def clear_portrait(self, entry):
        self._sync_entries()
        entry["portrait_data"] = None
        self.refresh_ui()

    def save(self):
        self._sync_entries()
        cleaned = {}
        for country, entries in self.data.items():
            parsed = []
            for e in entries:
                try:
                    year = int(e.get("year") or 0)
                    month = int(e.get("month") or 0)
                    day = int(e.get("day") or 0)
                except (TypeError, ValueError):
                    confirm_dialog.show_error(
                        "Invalid Date", f"{country} has a non-numeric date in its timeline -- fix it before saving.")
                    return
                color = e.get("color")
                if isinstance(color, (list, tuple)) and len(color) == 3:
                    try:
                        color = [max(0, min(255, int(v))) for v in color]
                    except (TypeError, ValueError):
                        color = None
                else:
                    color = None

                flag_data = e.get("flag_data")
                if not isinstance(flag_data, str) or not flag_data:
                    flag_data = None
                portrait_data = e.get("portrait_data")
                if not isinstance(portrait_data, str) or not portrait_data:
                    portrait_data = None

                parsed.append({
                    "year": year,
                    "month": max(1, min(12, month)),
                    "day": max(1, min(30, day)),
                    "name": str(e.get("name", "")).strip(),
                    "adjective": str(e.get("adjective", "")).strip(),
                    "color": color,
                    "flag_data": flag_data,
                    "portrait_data": portrait_data,
                    "leader_name": str(e.get("leader_name", "")).strip(),
                    "leader_title": str(e.get("leader_title", "")).strip(),
                })
            parsed.sort(key=_date_key)
            if parsed:
                cleaned[country] = parsed

        queries.save_historical_leader_timeline(cleaned)
        self.data = cleaned
        self.roster = sorted(self.data.keys())
        if self.active_country not in self.data:
            self.active_country = self.roster[0] if self.roster else None

        confirm_dialog.show_success(
            "Saved",
            "Historical timeline saved. Every historical scenario will now show these names, "
            "adjectives and leaders automatically, based on each scenario's own date.")
        self.refresh_ui()

    def export_timeline(self):
        """Sends the on-disk historical_leaders.json to Downloads as-is --
        exports the last saved state, not unsaved edits still sitting in the
        on-screen fields (same "Save is its own separate step" split the rest
        of this editor already uses)."""
        queries.export_json_file(c.HISTORICAL_LEADERS_PATH, "historical_leaders.json")

    @staticmethod
    def _is_valid_timeline(data):
        """A historical_leaders.json is {country: [ {year, month, day, ...}, ... ]}
        -- rejects anything else before it gets anywhere near disk or self.data,
        since a malformed shape here would only surface later as a confusing
        crash in _date_key or the scenario loader."""
        if not isinstance(data, dict):
            return False
        for entries in data.values():
            if not isinstance(entries, list):
                return False
            if any(not isinstance(e, dict) or "year" not in e for e in entries):
                return False
        return True

    def import_timeline(self):
        def on_loaded(data):
            if not self._is_valid_timeline(data):
                confirm_dialog.show_error(
                    "Import Error", "That file doesn't look like a historical leaders timeline.")
                return

            def on_confirm(ok):
                if not ok:
                    return
                queries.save_historical_leader_timeline(data)
                self._load_from_disk()
                self._scroll_roster = 0
                self._scroll_timeline = 0
                confirm_dialog.show_success("Import Success", "Historical leaders timeline imported.")
                self.refresh_ui()

            confirm_dialog.ask_yes_no(
                "Import Timeline?",
                "This replaces your current historical leaders timeline, including any unsaved "
                "edits, with the imported file. This can't be undone.", on_confirm)

        queries.import_json_file(self, "Select historical_leaders.json", on_loaded)

    def reset_timeline(self):
        def on_confirm(ok):
            if not ok:
                return
            try:
                with open(c.HISTORICAL_LEADERS_DEFAULT_PATH, "r", encoding="utf-8") as f:
                    default_data = json.load(f)
            except Exception as e:
                confirm_dialog.show_error("Reset Error", str(e))
                return
            queries.save_historical_leader_timeline(default_data)
            self._load_from_disk()
            self._scroll_roster = 0
            self._scroll_timeline = 0
            confirm_dialog.show_success("Reset", "Historical leaders timeline reset to the game's defaults.")
            self.refresh_ui()

        confirm_dialog.ask_yes_no(
            "Reset to Defaults?",
            "This overwrites historical_leaders.json with the game's built-in defaults, discarding "
            "every custom entry and any unsaved edits. This can't be undone.", on_confirm)

    # ------------------------------------------------------------------ #
    #                              BUILD UI                               #
    # ------------------------------------------------------------------ #

    def _effective_field(self, entries, entry, field):
        """Resolves what this entry will actually render as once applied in
        play, mirroring queries.apply_historical_leader_timeline: the entry's
        own value if it set one, else the latest earlier entry's value, else
        None -- same fall-through so the swatch preview never lies about
        what a blank field on this entry actually means."""
        value = None
        for e in sorted(entries, key=_date_key):
            v = e.get(field)
            if v:
                value = v
            if e is entry:
                break
        return value

    def _preview_surf(self, b64_data, size, is_portrait, target_size):
        """Decodes a flag/portrait entry (None falls back to the country's
        normal appearance, same as an unset field does in play) and scales
        it down to fit inside a swatch button."""
        full = queries.decode_b64_to_surf(b64_data or "DEFAULT", size, is_portrait=is_portrait,
                                          country_name=self.active_country)
        return pygame.transform.smoothscale(full, target_size)

    def _build_entry_row(self, entry, y, entries):
        fx = self.field_x
        row1_y = y + ROW1_Y_OFFSET
        row2_y = y + ROW2_Y_OFFSET

        def mk(key, x, y_pos, w, numeric=False):
            field = TextField(x, y_pos, w, FIELD_H, str(entry.get(key, "")), numeric=numeric)
            field.entry_ref = entry
            field.entry_key = key
            field.pane = "timeline"
            field.click_guard = self._guard_timeline
            return field

        self.elements.append(mk("year", fx["year"], row1_y, 52, True))
        self.elements.append(mk("month", fx["month"], row1_y, 44, True))
        self.elements.append(mk("day", fx["day"], row1_y, 44, True))
        self.elements.append(mk("name", fx["name"], row1_y, 152, False))
        self.elements.append(mk("adjective", fx["adjective"], row1_y, 152, False))
        self.elements.append(mk("leader_name", fx["leader_name"], row2_y, 280, False))
        self.elements.append(mk("leader_title", fx["leader_title"], row2_y, 280, False))

        color = entry.get("color")
        swatch = Button(fx["color"], row1_y - 1, "tiny_square", "grey", "",
                        lambda e=entry: self.pick_color(e), show_text=False)
        swatch.rect.size = (COLOR_SWATCH_SIZE, COLOR_SWATCH_SIZE)
        swatch.set_colors(tuple(color) if color else (55, 60, 65))
        swatch.pane = "timeline"
        swatch.click_guard = self._guard_timeline
        self.elements.append(swatch)

        clear_btn = Button(fx["color"] + COLOR_SWATCH_SIZE + 8, row1_y - 1, "tiny_square", "orange", "Clear",
                           lambda e=entry: self.clear_color(e), font_preset="button_small")
        clear_btn.rect.size = (60, COLOR_SWATCH_SIZE)
        if not color:
            clear_btn.apply_state(enabled=False)
        clear_btn.pane = "timeline"
        clear_btn.click_guard = self._guard_timeline
        self.elements.append(clear_btn)

        for key, size, is_portrait, preview_size, pick_cb, clear_cb in (
            ("flag", c.FLAG_SIZE, False, FLAG_PREVIEW_SIZE, self.pick_flag, self.clear_flag),
            ("portrait", c.PORTRAIT_SIZE, True, PORTRAIT_PREVIEW_SIZE, self.pick_portrait, self.clear_portrait),
        ):
            has_override = bool(entry.get(f"{key}_data"))
            effective = self._effective_field(entries, entry, f"{key}_data")
            preview = self._preview_surf(effective, size, is_portrait, preview_size)

            img_btn = Button(fx[key], row2_y - 1, "tiny_square", "grey", "",
                             lambda e=entry, cb=pick_cb: cb(e), image=preview, show_text=False)
            img_btn.rect.size = (IMAGE_SWATCH_SIZE, IMAGE_SWATCH_SIZE)
            img_btn.pane = "timeline"
            img_btn.click_guard = self._guard_timeline
            self.elements.append(img_btn)

            img_clear_btn = Button(fx[key] + IMAGE_SWATCH_SIZE + 8, row2_y - 1, "tiny_square", "orange", "Clear",
                                   lambda e=entry, cb=clear_cb: cb(e), font_preset="button_small")
            img_clear_btn.rect.size = (60, IMAGE_SWATCH_SIZE)
            if not has_override:
                img_clear_btn.apply_state(enabled=False)
            img_clear_btn.pane = "timeline"
            img_clear_btn.click_guard = self._guard_timeline
            self.elements.append(img_clear_btn)

        # Kept well clear of the card's own right edge (timeline_rect.right - 20,
        # see the card_rect built in draw_elements) and the scrollbar track
        # beside it -- previously this sat past the card's edge entirely.
        del_btn = Button(self.timeline_rect.right - 65, row1_y - 4, "tiny_square", "red", "X",
                         lambda e=entry: self.delete_entry(e), font_preset="button_small")
        del_btn.pane = "timeline"
        del_btn.click_guard = self._guard_timeline
        self.elements.append(del_btn)

    def refresh_ui(self):
        self._layout()

        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
            Button(self.roster_rect.x, self.roster_rect.y - 40, "editor_ui", "green",
                  "+ Add Country", self.add_country),
            Button(700, c.SCREEN_HEIGHT - 60, "small", "blue", "Export", self.export_timeline),
            Button(810, c.SCREEN_HEIGHT - 60, "small", "purple", "Import", self.import_timeline),
            Button(920, c.SCREEN_HEIGHT - 60, "small", "orange", "Reset", self.reset_timeline),
            Button(c.SCREEN_WIDTH - 240, c.SCREEN_HEIGHT - 60, "medium", "green",
                  "Save Timeline", self.save),
        ]

        for i, y in self._rows_of("roster", len(self.roster), self.roster_rect.y,
                                  self.roster_rect.height, ROSTER_ROW_H):
            country = self.roster[i]
            label = f"{country} ({len(self.data.get(country, []))})"
            btn = Button(self.roster_rect.x, y, "list_row", "green" if country == self.active_country else "blue",
                        truncate(label, 28), lambda cc=country: self.select_country(cc), font_preset="button_small")
            btn.rect.width = self.roster_rect.width - 50
            btn.is_selected = country == self.active_country
            btn.pane = "roster"
            btn.click_guard = self._guard_roster
            self.elements.append(btn)

            rm_btn = Button(self.roster_rect.right - 44, y + 3, "tiny_square", "red", "x",
                            lambda cc=country: self.remove_country(cc), font_preset="button_small")
            rm_btn.pane = "roster"
            rm_btn.click_guard = self._guard_roster
            self.elements.append(rm_btn)

        if self.active_country:
            # "editor_ui" is 300px wide -- anchored off timeline_rect.right so
            # the whole button stays on screen instead of running past it.
            self.elements.append(Button(self.timeline_rect.right - 310, self.timeline_rect.y - 40,
                                        "editor_ui", "green", "+ Add Entry", self.add_entry))

        entries = self.data.get(self.active_country, []) if self.active_country else []
        self._entry_layout = []
        for i, y in self._rows_of("timeline", len(entries), self.timeline_rect.y,
                                  self.timeline_rect.height, ENTRY_ROW_H):
            entry = entries[i]
            self._entry_layout.append((entry, y))
            self._build_entry_row(entry, y, entries)

    # ------------------------------------------------------------------ #
    #                             EVENTS                                  #
    # ------------------------------------------------------------------ #

    def additional_events(self, event):
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            for name, rect in self.regions.items():
                if rect.collidepoint(pos):
                    self.handle_list_scroll(event, **self._scroll_attrs(name))
                    return
            return

        for name in ("roster", "timeline"):
            if self.handle_list_scroll(event, **self._scroll_attrs(name)):
                return

    # ------------------------------------------------------------------ #
    #                             RENDERING                               #
    # ------------------------------------------------------------------ #

    def draw_elements(self, surface):
        fixed = [el for el in self.elements if not getattr(el, "pane", None)]

        roster_scroll, roster_limit = getattr(self, "_scroll_roster", 0), getattr(self, "_max_roster", 0)
        with ui_bars.clip_scroll_region(surface, self.roster_rect,
                                        draw_top=roster_scroll != 0, draw_bottom=roster_scroll > roster_limit):
            for el in self.elements:
                if getattr(el, "pane", None) == "roster":
                    el.draw(surface)

        tl_scroll, tl_limit = getattr(self, "_scroll_timeline", 0), getattr(self, "_max_timeline", 0)
        with ui_bars.clip_scroll_region(surface, self.timeline_rect,
                                        draw_top=tl_scroll != 0, draw_bottom=tl_scroll > tl_limit):
            tiny = fonts.get("tiny")
            fx = self.field_x
            for entry, y in self._entry_layout:
                card_rect = pygame.Rect(self.timeline_rect.x, y, self.timeline_rect.width - 20, ENTRY_ROW_H - 10)
                pygame.draw.rect(surface, (35, 45, 35), card_rect, border_radius=4)
                pygame.draw.rect(surface, (80, 110, 80), card_rect, 1, border_radius=4)

                row1_y, row2_y = y + ROW1_Y_OFFSET, y + ROW2_Y_OFFSET
                for key, label in (("year", "Year"), ("month", "Mon"), ("day", "Day"),
                                   ("name", "Name"), ("adjective", "Adjective"), ("color", "Color")):
                    cap = tiny.render(label, True, (150, 190, 150))
                    surface.blit(cap, (fx[key], row1_y - 15))
                for key, label in (("leader_name", "Leader Name"), ("leader_title", "Leader Title"),
                                   ("flag", "Flag"), ("portrait", "Portrait")):
                    cap = tiny.render(label, True, (150, 190, 150))
                    surface.blit(cap, (fx[key], row2_y - 15))

            for el in self.elements:
                if getattr(el, "pane", None) == "timeline":
                    el.draw(surface)

        for el in fixed:
            el.draw(surface)

    def additional_draw(self, surface):
        p = self.roster_rect
        small = fonts.get("small")
        surface.blit(small.render(f"Countries Tracked ({len(self.roster)})", True, (170, 210, 170)),
                    (p.x, p.y - 20))

        if not self.roster:
            msg = fonts.get("normal").render("Add a country to begin.", True, (200, 200, 200))
            surface.blit(msg, (p.x + 4, p.y + 6))

        pygame.draw.line(surface, (70, 95, 70), (self.timeline_rect.x - 15, TOP_Y),
                         (self.timeline_rect.x - 15, self.roster_rect.bottom), 1)

        header = fonts.get("heading2").render(
            f"Timeline: {self.active_country}" if self.active_country else "Select a country",
            True, c.COLOR_GOLD_HIGHLIGHT if self.active_country else (200, 200, 200))
        surface.blit(header, (self.timeline_rect.x, self.timeline_rect.y - 40))

        if self.active_country and not self.data.get(self.active_country):
            msg = fonts.get("normal").render(
                "No entries yet -- Add Entry sets when this country's name/adjective/leader take effect.",
                True, (200, 200, 200))
            surface.blit(msg, (self.timeline_rect.x + 4, self.timeline_rect.y + 6))

        hint_line1 = fonts.get("small").render(
            "Each entry applies from its date onward until a later entry overrides that field.",
            True, (170, 170, 170))
        hint_line2 = fonts.get("small").render(
            "Blank fields keep whatever the previous entry set.", True, (170, 170, 170))
        surface.blit(hint_line1, (PAD, c.SCREEN_HEIGHT - 40))
        surface.blit(hint_line2, (PAD, c.SCREEN_HEIGHT - 24))

        self.draw_list_scrollbar(surface, self.roster_rect.right - 8, self.roster_rect.y,
                                 self.roster_rect.height, **self._scroll_attrs("roster"))
        self.draw_list_scrollbar(surface, self.timeline_rect.right - 8, self.timeline_rect.y,
                                 self.timeline_rect.height, **self._scroll_attrs("timeline"))


def open_historical_leaders_editor(on_done=None):
    from ui.screen_runner import run_screen
    run_screen(Historical_Leaders_Editor, on_done=on_done, caption="Historical Leaders & Names")
