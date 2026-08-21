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


def build_gallery_rows(style, country=None):
    """One row per distinct piece of unit art `style` would actually show
    `country` (falling back to classic per the same rule symbol_loader.get_symbol
    uses -- and within a style, falling back further to whatever art applies
    to every country when none of it is scoped to this one), in family order,
    with a header wherever the Infantry/Tanks/Navy group changes.

    `country` is a country id (a key of data/json/countries_data.json, e.g.
    "Germany") or None for "nobody in particular", which only ever sees
    unrestricted art -- the same view every country without its own
    dedicated pictures gets. Two countries can produce different row counts
    for the same family: a family collapses to as many rows as it has
    distinct pictures *for that country*, so a family with nation-specific
    eras only splits into extra rows for the nations that have them.

    A non-classic style only lists what it actually draws differently: a run
    that resolves all the way through to classic (nothing in `style` covers
    it, for this country or any other) is dropped rather than shown as a
    picture the style never contributes. Picking "Classic" itself still lists
    everything, since there classic *is* the style being browsed. A family
    with nothing surviving loses its header too, so switching to a country
    with one specialised unit shows just that unit, not every empty section.
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

        family_rows = []
        for res_key, run in itertools.groupby(zip(names, resolved), key=lambda t: t[1]):
            if style != "classic" and res_key is not None and res_key[0] == "classic":
                continue  # this style contributes nothing here -- not worth a row
            run_names = [n for n, _r in run]
            first, last = run_names[0], run_names[-1]
            family_rows.append({"kind": "unit", "group": group,
                                "label": _merge_label(first, last), "resolve_name": first})

        if not family_rows:
            continue  # nothing of this family survived -- its header would be empty
        if group != last_group:
            rows.append({"kind": "header", "label": group})
            last_group = group
        rows.extend(family_rows)
    return rows


class Unit_Art(GameState):
    """Settings sub-screen: pick a unit art style on the left, browse every
    unit it would draw on the right. Picking a style applies it immediately
    (same as every other toggle on the Settings screen) and persists it."""

    back_state = "SETTINGS"
    ROW_HEIGHT = ROW_H

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

    # ------------------------------------------------------------------ #
    #                                UI                                  #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.available_cultures = symbol_loader.style_cultures(self.style)
        self.rows = build_gallery_rows(self.style, self.country)

        self.elements = [make_back_button(self.exit_screen)]

        y = 100
        for style in c.UNIT_ART_STYLES:
            btn = Button(20, y, "medium", "green" if style == self.style else "grey",
                        STYLE_LABELS.get(style, style.title()), lambda s=style: self.set_style(s))
            btn.is_selected = (style == self.style)
            self.elements.append(btn)
            y += 60

        self.elements.extend(self._build_country_tabs())

        self.scroll_content_rect = pygame.Rect(GALLERY_X, self.gallery_top, GALLERY_W,
                                               GALLERY_BOTTOM - self.gallery_top)
        self._visible_rows = [(self.rows[i], row_y) for i, row_y in
                              self.layout_list_rows(len(self.rows), ROW_H, self.gallery_top,
                                                    cull_bottom=GALLERY_BOTTOM)]

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
        for row, y in self._visible_rows:
            self._draw_row(surface, row, y)
        surface.set_clip(clip)

        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 25, self.gallery_top, GALLERY_BOTTOM - self.gallery_top)

    def _draw_row(self, surface, row, y):
        x = GALLERY_X + ROW_PAD_X

        if row["kind"] == "header":
            line_y = y + ROW_H - 28
            pygame.draw.line(surface, (80, 80, 80), (x, line_y), (c.SCREEN_WIDTH - 30, line_y), 1)
            text = fonts.get("heading2").render(row["label"].upper(), True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(text, (x, y + (ROW_H - 28) // 2 - text.get_height() // 2))
            return

        accent = GROUP_ACCENT.get(row["group"], (120, 120, 120))
        icon_box = pygame.Rect(x, y + (ROW_H - ICON_BOX) // 2, ICON_BOX, ICON_BOX)
        pygame.draw.rect(surface, (45, 45, 55), icon_box, border_radius=6)
        pygame.draw.rect(surface, accent, icon_box, 2, border_radius=6)

        icon = symbol_loader.get_symbol(row["resolve_name"], ICON_ZOOM, style=self.style, country=self.country)
        if icon:
            icon = self._fit_icon(icon, ICON_BOX - 12, ICON_BOX - 12)
            surface.blit(icon, icon.get_rect(center=icon_box.center))
        else:
            miss = fonts.get("small").render("No Art", True, (150, 150, 150))
            surface.blit(miss, miss.get_rect(center=icon_box.center))

        label_x = x + ICON_BOX + 24
        label = fonts.get("normal").render(row["label"], True, c.UI_TEXT_BRIGHT)
        surface.blit(label, (label_x, y + ROW_H // 2 - label.get_height() // 2))

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
