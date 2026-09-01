import os
import itertools
import pygame

from gameState import GameState
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import symbol_loader
from data import queries
import data.constants as c

# ==========================================
# LAYOUT
# ==========================================

STYLE_PANE_W = 260
GALLERY_X = STYLE_PANE_W
GALLERY_W = c.SCREEN_WIDTH - GALLERY_X
GALLERY_BOTTOM = c.SCREEN_HEIGHT - 20

ROW_H = 100
ROW_PAD_X = 24
ICON_BOX = 76
ICON_ZOOM = 6.0  # Feeds symbol_loader's zoom*0.5*custom_scale sizing; the icon
                 # is then fit down to ICON_BOX regardless, so this just needs
                 # to be big enough that even the smallest icons (Infantry at
                 # 22px) don't come out blurry when scaled back down.

# --- Per-family row: one label on the left, then every distinct picture the
# family has (a tier, an era range, ...) as its own icon cell running to the
# right of it, wrapping onto further ROW_H-tall lines within the same row
# when they don't all fit one line (same idea as the tab-wrapping below). ---
CELL_GAP_X = 16
CELL_LABEL_FONT = "small"
CELL_LABEL_H = ROW_H - ICON_BOX  # band reserved above the icon for its tier/era label

STYLE_LABELS = {"classic": "Classic", "hanskolmer": "Hanskolmer"}

# --- Country tab bar, across the top of the gallery pane ---
GENERIC_TAB_LABEL = "Generic"
TABS_TOP = 96
TAB_H = 32
TAB_ROW_GAP = 6
TAB_GAP_X = 8
TAB_PAD_X = 14
TAB_FONT = "small"
GALLERY_TOP_MARGIN = 16

GROUP_ACCENT = {
    "Infantry": (90, 140, 200),
    "Tanks": (200, 130, 60),
    "Navy": (60, 170, 160),
}

# --- Level-display toggle: top-right corner of the gallery pane, picking how
# a cell's tier/era label reads (see _level_label). ---
LEVEL_DISPLAY_MODES = ("default", "years", "numbers")
LEVEL_DISPLAY_LABELS = {"default": "Default", "years": "Years", "numbers": "Numbers"}
LEVEL_TOGGLE_Y = 50
LEVEL_TOGGLE_H = 30
LEVEL_TOGGLE_GAP_X = 8
LEVEL_TOGGLE_PAD_X = 12
LEVEL_TOGGLE_FONT = "small"

# --- "Show All Art" toggle, directly above the level-display row. ---
SHOW_ALL_ART_LABEL = "Show All Art"
SHOW_ALL_ART_Y = 12
SHOW_ALL_ART_H = 30
SHOW_ALL_ART_PAD_X = 12
SHOW_ALL_ART_FONT = "small"


def _merge_label(first, last):
    """first and last are the endpoints of a run of unit names that all
    resolve to the same piece of art. Collapses their shared prefix so a
    hundred-year run of identical Infantry art reads as one row -- 'Infantry
    Type 1910-2010' -- instead of repeating the whole name twice."""
    if first == last:
        return first
    common = os.path.commonprefix([first, last])
    cut = common.rfind(" ")
    if cut == -1:
        return f"{first} - {last}"
    prefix = first[:cut + 1]
    return f"{prefix}{first[cut + 1:]}-{last[cut + 1:]}"


def _family_display_name(base):
    """The label shown once per family row. 'Type' is a connector word before
    the era suffix, already dropped everywhere else a unit name is condensed
    for space (see queries.CONDENSED_UNIT_NAME_WORDS) -- so 'Infantry Type'
    (get_base_unit_name's result for 'Infantry Type 1940') reads as plain
    'Infantry' here too."""
    suffix = " Type"
    return base[:-len(suffix)] if base.endswith(suffix) else base


def _family_kind(base, first_name):
    """Whether a family's tiers are suffixed with a roman numeral ('Light
    Tank I'), a calendar year ('Infantry Type 1910'), or nothing at all (a
    single-tier family like 'Railgun') -- drives how "years"/"numbers"
    display mode reads a tier's level in _level_label. `first_name` is any
    member of the family (its own suffix shape is the same for all of
    them)."""
    suffix = first_name[len(base):].strip()
    if not suffix:
        return "single"
    if suffix.isdigit() and len(suffix) == 4:
        return "year"
    if all(ch in "IVXLCDM" for ch in suffix.upper()):
        return "roman"
    return "other"


def _level_label(mode, base, kind, years_list, idx_by_name, first, last, default_label):
    """The text shown above a cell's icon, per the level-display mode the
    player picked on the Unit Art screen (Unit_Art.set_level_display):

    - "default": whatever the art boundaries already produced (default_label
      -- unchanged).
    - "numbers": the cell's 1-based position among the family's own tiers,
      e.g. Light Tank's 10th tier ('Light Tank X') reads '10' and Infantry's
      1st ('Infantry Type 1910') reads '1' -- the same rule whether the tier
      happens to be roman-numeral- or year-suffixed, since both are already
      in tier order in `idx_by_name`.
    - "years": the calendar years this tier is the current one -- from its
      own research year (data/json/research_template.json) up to just
      before the next tier's research year, open-ended ('1918+') for a
      family's final tier. A "year"-kind family already shows this under
      "default" (its own name suffix IS the year), so this mode leaves those
      untouched. Falls back to default_label wherever there's no usable data
      -- an unrecognised suffix shape, or a family with no matching entry in
      the tech tree (e.g. Heavy Artillery, which has no research years of
      its own).
    """
    if mode == "default" or kind == "other":
        return default_label

    if mode == "numbers":
        i1, i2 = idx_by_name[first], idx_by_name[last]
        return str(i1) if i1 == i2 else f"{i1}-{i2}"

    # mode == "years"
    if kind == "year":
        return default_label  # the name's own suffix already is the year
    if not years_list:
        return default_label  # no research_template.json entry for this family

    lvl1 = 1 if kind == "single" else queries.roman_to_int(first[len(base):].strip())
    lvl2 = 1 if kind == "single" else queries.roman_to_int(last[len(base):].strip())
    if lvl1 < 1 or lvl1 > len(years_list):
        return default_label

    start_year = years_list[lvl1 - 1]
    end_year = years_list[lvl2] - 1 if lvl2 < len(years_list) else None
    return f"{start_year}-{end_year}" if end_year is not None else f"{start_year}+"


def build_gallery_rows(style, country=None, level_display="default", show_all_art=False):
    """One row per unit family, each holding every distinct piece of art
    `style` would actually show `country` for that family (falling back to
    classic per the same rule symbol_loader.get_symbol uses -- and within a
    style, falling back further to whatever art applies to every country when
    none of it is scoped to this one), in family order, with a header
    wherever the Infantry/Tanks/Navy group changes.

    A family with several distinct pictures -- different tiers (Light Tank
    IV/V/VI) or different filename-defined eras (Infantry 1914/1916/...) --
    gets one cell per picture instead of one row per picture, so the whole family
    reads left-to-right as one line (the gallery wraps a family onto further
    lines itself if its cells don't all fit the width -- see
    Unit_Art._wrap_cells).

    `country` is a country id (a key of data/json/countries_data.json, e.g.
    "Germany") or None for "nobody in particular", which only ever sees
    unrestricted art -- the same view every country without its own
    dedicated pictures gets. Two countries can produce different cell counts
    for the same family: a family collapses to as many cells as it has
    distinct pictures *for that country*, so a family with nation-specific
    eras only gains extra cells for the nations that have them.

    A non-classic style only lists what it actually draws differently: a run
    that resolves all the way through to classic (nothing in `style` covers
    it, for this country or any other) is dropped rather than shown as a
    picture the style never contributes -- unless `show_all_art` is True, in
    which case it's kept and shows the classic fallback it would actually
    draw in-game instead of being hidden. Picking "Classic" itself still
    lists everything either way, since there classic *is* the style being
    browsed. A family with nothing surviving loses its header too, so
    switching to a country with one specialised unit and show_all_art off
    shows just that unit, not every empty section.

    `level_display` ("default"/"years"/"numbers") picks what each cell's
    label reads as -- see _level_label for exactly what each mode shows.
    """
    unit_library = queries.get_unit_library()

    families = {}       # base name -> [unit names, in file order]
    family_group = {}   # base name -> "Infantry"/"Tanks"/"Navy"
    for name, stats in unit_library.items():
        base = queries.get_base_unit_name(name)
        families.setdefault(base, []).append(name)
        family_group[base] = queries.classify_unit_group(base, stats)

    rows = []
    last_group = None
    for base, names in families.items():
        group = family_group[base]
        resolved = [symbol_loader.resolve(n, style, country) for n in names]

        kind = _family_kind(base, names[0])
        years_list = None
        if level_display == "years" and kind in ("single", "roman"):
            tech_key = queries.get_unit_tech_key(base)
            years_list = queries.get_tech_tree().get(tech_key, {}).get("years")
        idx_by_name = {name: i + 1 for i, name in enumerate(names)} if level_display == "numbers" else None

        cells = []
        prefix = base + " "
        for res_key, run in itertools.groupby(zip(names, resolved), key=lambda t: t[1]):
            if not show_all_art and style != "classic" and res_key is not None and res_key[0] == "classic":
                continue  # this style contributes nothing here -- not worth a cell
            run_names = [n for n, _r in run]
            first, last = run_names[0], run_names[-1]
            full_label = _merge_label(first, last)
            # The family name is already shown once on the row, on the left --
            # a cell only needs the part that actually varies (a tier, an era).
            default_sublabel = full_label[len(prefix):] if full_label.startswith(prefix) else ""
            sublabel = _level_label(level_display, base, kind, years_list, idx_by_name,
                                    first, last, default_sublabel)
            cells.append({"label": sublabel, "resolve_name": first})

        if not cells:
            continue  # nothing of this family survived -- its header would be empty
        if group != last_group:
            rows.append({"kind": "header", "label": group})
            last_group = group
        # One word per line (see Unit_Art._draw_row) so a long name like
        # "Landkreuzer P.1000 Ratte" stacks tall instead of wide, leaving more
        # of the row's width for cells.
        display_name = _family_display_name(base)
        rows.append({"kind": "family", "group": group, "label": display_name,
                     "label_words": display_name.split(" "), "cells": cells})
    return rows


class Unit_Art(GameState):
    """Settings sub-screen: pick a unit art style on the left, browse every
    unit it would draw on the right. Picking a style applies it immediately
    (same as every other toggle on the Settings screen) and persists it."""

    back_state = "SETTINGS"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.style = getattr(controller, "unit_art_style", c.UNIT_ART_STYLE)
        self.country = None  # None = the leftmost "Generic" tab; otherwise a
                              # culture's representative country id (see
                              # symbol_loader.culture_representative)
        self.available_cultures = []
        self.tab_labels = {None: GENERIC_TAB_LABEL}  # self.country value -> the tab label it was picked under
        self.level_display = "default"  # see LEVEL_DISPLAY_MODES / _level_label
        self.show_all_art = False  # see toggle_show_all_art
        self.rows = []
        self._visible_rows = []
        self.gallery_top = TABS_TOP
        self.scroll_content_rect = None
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                          STYLE / COUNTRY                           #
    # ------------------------------------------------------------------ #

    def set_style(self, style):
        if style == self.style:
            return
        self.style = style
        c.apply_runtime_settings({"unit_art_style": style})
        self.controller.unit_art_style = style
        queries.save_global_settings(self.controller)

        # A style's set of countries with dedicated art is its own -- the
        # country picked under the old style may not mean anything (or may
        # mean something different) under the new one, so fall back to the
        # generic tab rather than carry a stale selection across.
        self.country = None
        self.scroll_y = 0
        self.refresh_ui()

    def set_country_filter(self, country):
        if country == self.country:
            return
        self.country = country
        self.scroll_y = 0
        self.refresh_ui()

    def set_level_display(self, mode):
        if mode == self.level_display:
            return
        self.level_display = mode
        # Unlike switching style/country (which can change which families and
        # cells even exist), this only changes label text -- same rows, same
        # cells, just possibly wrapped differently -- so keep the player's
        # scroll position instead of jumping back to the top. refresh_ui's
        # own scroll clamp handles the rare case where the new labels' wrap
        # shrank the content past where the old scroll position pointed.
        self.refresh_ui()

    def toggle_show_all_art(self):
        self.show_all_art = not self.show_all_art
        # This adds/removes cells (units the active style falls back to
        # classic for) rather than just changing label text, but the rows
        # above the toggled content don't move -- keep the player's scroll
        # position instead of jumping back to the top. refresh_ui's own
        # scroll clamp (in _layout_gallery_rows) handles it if turning this
        # off shrank the content past where the old position pointed.
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                                UI                                  #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.available_cultures = symbol_loader.style_cultures(self.style)
        self.rows = build_gallery_rows(self.style, self.country, self.level_display, self.show_all_art)

        # Width of the left-hand family-name column, sized to whatever's
        # actually on screen right now rather than a guessed constant -- a
        # style/country with only short family names (e.g. "Infantry") gets
        # more room for cells than one that also lists "Motorized Infantry".
        # Sized by the single widest WORD, not the widest whole name, since a
        # multi-word name wraps one word per line (see _draw_row) rather than
        # running wide across the row.
        label_font = fonts.get("normal")
        self.family_label_w = max((label_font.size(word)[0]
                                   for row in self.rows if row["kind"] == "family"
                                   for word in row["label_words"]),
                                  default=0) + ROW_PAD_X

        self.elements = [make_back_button(self.exit_screen)]

        y = 100
        for style in c.UNIT_ART_STYLES:
            btn = Button(20, y, "medium", "green" if style == self.style else "grey",
                        STYLE_LABELS.get(style, style.title()), lambda s=style: self.set_style(s))
            btn.is_selected = (style == self.style)
            self.elements.append(btn)
            y += 60

        self.elements.extend(self._build_country_tabs())
        self.elements.append(self._build_show_all_art_toggle())
        self.elements.extend(self._build_level_display_toggle())

        self.scroll_content_rect = pygame.Rect(GALLERY_X, self.gallery_top, GALLERY_W,
                                               GALLERY_BOTTOM - self.gallery_top)
        self._visible_rows = self._layout_gallery_rows()

    def _layout_gallery_rows(self):
        """Positions every row top-to-bottom and returns the ones currently in
        view as (row, lines, y, height) -- lines is the _wrap_cells() output
        for a "family" row, or None for a "header" row.

        Stands in for the generic layout_list_rows (used by every other
        scrollable list in the menus) because that helper assumes one fixed
        row_h for everything it lays out: here a family's row is ROW_H tall
        per wrapped line of cells (or taller still if its label needs more
        vertical space than that -- a one-cell family with a three-word name
        stacks three lines of text next to a single line of icons), so two
        rows can have completely different heights. This still sets
        self.max_scroll the same way (min(0, view_h - total_content_height))
        so handle_list_scroll, draw_list_scrollbar and friends work
        unmodified.
        """
        cell_font = fonts.get(CELL_LABEL_FONT)
        label_line_h = fonts.get("normal").get_linesize()
        cells_x0 = GALLERY_X + ROW_PAD_X + self.family_label_w
        cells_right = c.SCREEN_WIDTH - 30

        laid_out = []  # (row, lines_or_None, height)
        for row in self.rows:
            if row["kind"] == "header":
                laid_out.append((row, None, ROW_H))
            else:
                lines = self._wrap_cells(row["cells"], cells_x0, cells_right, cell_font)
                cells_h = len(lines) * ROW_H
                label_h = len(row["label_words"]) * label_line_h
                laid_out.append((row, lines, max(cells_h, label_h)))

        view_h = GALLERY_BOTTOM - self.gallery_top
        total_h = sum(height for _row, _lines, height in laid_out)
        self.max_scroll = min(0, view_h - total_h)
        # A mode switch keeps whatever scroll position the player was at (see
        # set_level_display), but its wrapping can shrink the content below
        # that point -- clamp back within range instead of leaving a gap of
        # blank space or an out-of-bounds scrollbar handle.
        self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))

        visible = []
        y = self.gallery_top + self.scroll_y
        for row, lines, height in laid_out:
            if y + height > self.gallery_top and y < GALLERY_BOTTOM:
                visible.append((row, lines, y, height))
            y += height
        return visible

    @staticmethod
    def _wrap_cells(cells, x0, right, font):
        """Packs a family's cells left-to-right starting at x0, wrapping onto
        a new ROW_H-tall line (like _build_country_tabs wraps tabs) whenever
        the next one would cross `right`. A cell is at least ICON_BOX wide,
        or as wide as its own label if that label doesn't fit under a bare
        icon (e.g. a filename-defined Infantry era label).

        Returns a list of lines, each a list of (cell, x, width) ready to
        draw -- computed once per refresh_ui rather than re-measured on
        every frame.
        """
        lines, current, x = [], [], x0
        for cell in cells:
            w = max(ICON_BOX, font.size(cell["label"])[0]) if cell["label"] else ICON_BOX
            if x + w > right and current:
                lines.append(current)
                current, x = [], x0
            current.append((cell, x, w))
            x += w + CELL_GAP_X
        if current:
            lines.append(current)
        return lines

    def _build_country_tabs(self):
        """The tab row: 'Generic' (country=None) first, then one tab per
        culture group this style has dedicated art for -- countries in the
        same culture always share identical art (a restricted entry names
        the whole culture, never an individual country), so e.g. Germany,
        German Reich and German Empire collapse into one "Germanic" tab
        instead of three identical ones. Selecting a culture tab resolves
        and draws art using that culture's representative country id (see
        symbol_loader.culture_representative). Always shown, even when a
        style has no culture-specific art of its own, so Generic is always
        reachable. Wraps onto further rows if the tabs don't fit one line,
        and grows self.gallery_top to match so the row list below never
        overlaps them.
        """
        font = fonts.get(TAB_FONT)
        self.tab_labels = {None: GENERIC_TAB_LABEL}
        tabs = [(GENERIC_TAB_LABEL, None)]
        for culture in self.available_cultures:
            representative = symbol_loader.culture_representative(self.style, culture)
            label = culture.title()
            tabs.append((label, representative))
            self.tab_labels[representative] = label

        buttons = []
        x = GALLERY_X + ROW_PAD_X
        y = TABS_TOP
        for label, value in tabs:
            w = font.size(label)[0] + TAB_PAD_X * 2
            if x + w > c.SCREEN_WIDTH - 30 and x > GALLERY_X + ROW_PAD_X:
                x = GALLERY_X + ROW_PAD_X
                y += TAB_H + TAB_ROW_GAP

            btn = Button(x, y, "asset_folder", "green" if value == self.country else "grey",
                        label, lambda v=value: self.set_country_filter(v), font_preset=TAB_FONT)
            btn.rect.width = w
            btn.rect.height = TAB_H
            btn.is_selected = (value == self.country)
            buttons.append(btn)
            x += w + TAB_GAP_X

        self.gallery_top = y + TAB_H + GALLERY_TOP_MARGIN
        return buttons

    def _build_show_all_art_toggle(self):
        """The 'Show All Art' switch, directly above the level-display row in
        the gallery pane's top-right corner. Off (the default) is today's
        behaviour: a non-classic style only lists units it actually draws
        differently. On, a unit the active style falls back to classic for
        is shown anyway, with that classic fallback picture, instead of
        being left out entirely (see build_gallery_rows's show_all_art
        param)."""
        font = fonts.get(SHOW_ALL_ART_FONT)
        w = font.size(SHOW_ALL_ART_LABEL)[0] + SHOW_ALL_ART_PAD_X * 2
        x = c.SCREEN_WIDTH - 30 - w

        btn = Button(x, SHOW_ALL_ART_Y, "asset_folder", "green" if self.show_all_art else "grey",
                    SHOW_ALL_ART_LABEL, self.toggle_show_all_art, font_preset=SHOW_ALL_ART_FONT)
        btn.rect.width = w
        btn.rect.height = SHOW_ALL_ART_H
        btn.is_selected = self.show_all_art
        return btn

    def _build_level_display_toggle(self):
        """The Default/Years/Numbers toggle in the gallery pane's top-right
        corner, controlling how every cell's tier/era label reads (see
        _level_label) independently of the style/country filters above.
        Laid out right-to-left from the pane's right edge so it always sits
        flush in the corner regardless of how wide "Numbers" vs "Default"
        render.
        """
        font = fonts.get(LEVEL_TOGGLE_FONT)
        buttons = []
        x = c.SCREEN_WIDTH - 30
        for mode in reversed(LEVEL_DISPLAY_MODES):
            label = LEVEL_DISPLAY_LABELS[mode]
            w = font.size(label)[0] + LEVEL_TOGGLE_PAD_X * 2
            x -= w

            btn = Button(x, LEVEL_TOGGLE_Y, "asset_folder", "green" if mode == self.level_display else "grey",
                        label, lambda m=mode: self.set_level_display(m), font_preset=LEVEL_TOGGLE_FONT)
            btn.rect.width = w
            btn.rect.height = LEVEL_TOGGLE_H
            btn.is_selected = (mode == self.level_display)
            buttons.append(btn)
            x -= LEVEL_TOGGLE_GAP_X
        return buttons

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def additional_draw(self, surface):
        pygame.draw.rect(surface, (32, 32, 40), (0, 0, STYLE_PANE_W, c.SCREEN_HEIGHT))
        pygame.draw.rect(surface, (22, 22, 28), (GALLERY_X, 0, GALLERY_W, c.SCREEN_HEIGHT))
        pygame.draw.line(surface, (90, 90, 90), (STYLE_PANE_W, 0), (STYLE_PANE_W, c.SCREEN_HEIGHT), 2)

        surface.blit(fonts.get("heading2").render("UNIT ART", True, (255, 255, 255)), (20, 70))
        style_label = STYLE_LABELS.get(self.style, self.style.title())
        subject = self.tab_labels.get(self.country, GENERIC_TAB_LABEL)
        surface.blit(fonts.get("heading2").render(f"{style_label} Preview - {subject}", True, (255, 255, 255)),
                    (GALLERY_X + ROW_PAD_X, 55))

        clip = surface.get_clip()
        surface.set_clip(self.scroll_content_rect)
        for row, lines, y, height in self._visible_rows:
            self._draw_row(surface, row, lines, y, height)
        surface.set_clip(clip)

        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 25, self.gallery_top, GALLERY_BOTTOM - self.gallery_top)

    def _draw_row(self, surface, row, lines, y, height):
        x = GALLERY_X + ROW_PAD_X

        if row["kind"] == "header":
            line_y = y + ROW_H - 28
            pygame.draw.line(surface, (80, 80, 80), (x, line_y), (c.SCREEN_WIDTH - 30, line_y), 1)
            text = fonts.get("heading2").render(row["label"].upper(), True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(text, (x, y + (ROW_H - 28) // 2 - text.get_height() // 2))
            return

        accent = GROUP_ACCENT.get(row["group"], (120, 120, 120))

        # One word per line -- see build_gallery_rows -- stacked and centred
        # as a block against the row's full height (which already grew to
        # fit this if a multi-word name needs more room than its cells do).
        family_font = fonts.get("normal")
        label_line_h = family_font.get_linesize()
        words = row["label_words"]
        label_y = y + (height - len(words) * label_line_h) // 2
        for word in words:
            text = family_font.render(word, True, c.UI_TEXT_BRIGHT)
            surface.blit(text, (x, label_y))
            label_y += label_line_h

        # The cell block is only as tall as its own wrapped lines need --
        # centre it too, in case the label above made the row taller still.
        cell_block_top = y + (height - len(lines) * ROW_H) // 2

        cell_font = fonts.get(CELL_LABEL_FONT)
        for li, cell_line in enumerate(lines):
            line_top = cell_block_top + li * ROW_H
            icon_top = line_top + CELL_LABEL_H
            for cell, cell_x, cell_w in cell_line:
                icon_box = pygame.Rect(cell_x + (cell_w - ICON_BOX) // 2, icon_top, ICON_BOX, ICON_BOX)
                pygame.draw.rect(surface, (45, 45, 55), icon_box, border_radius=6)
                pygame.draw.rect(surface, accent, icon_box, 2, border_radius=6)

                icon = symbol_loader.get_symbol(cell["resolve_name"], ICON_ZOOM,
                                                style=self.style, country=self.country)
                if icon:
                    icon = self._fit_icon(icon, ICON_BOX - 12, ICON_BOX - 12)
                    surface.blit(icon, icon.get_rect(center=icon_box.center))
                else:
                    miss = fonts.get("small").render("No Art", True, (150, 150, 150))
                    surface.blit(miss, miss.get_rect(center=icon_box.center))

                if cell["label"]:
                    cell_label = cell_font.render(cell["label"], True, c.UI_TEXT_BRIGHT)
                    lx = cell_x + (cell_w - cell_label.get_width()) // 2
                    ly = line_top + (CELL_LABEL_H - cell_label.get_height()) // 2
                    surface.blit(cell_label, (lx, ly))

    @staticmethod
    def _fit_icon(surf, max_w, max_h):
        w, h = surf.get_size()
        if w <= max_w and h <= max_h:
            return surf
        scale = min(max_w / w, max_h / h)
        size = (max(1, int(w * scale)), max(1, int(h * scale)))
        return pygame.transform.smoothscale(surf, size) if scale < 1.0 else pygame.transform.scale(surf, size)

    def handle_back_key(self):
        self.exit_screen()
