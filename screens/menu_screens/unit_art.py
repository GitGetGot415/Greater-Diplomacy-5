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
GALLERY_TOP = 110
GALLERY_BOTTOM = c.SCREEN_HEIGHT - 20

ROW_H = 100
ROW_PAD_X = 24
ICON_BOX = 76
ICON_ZOOM = 6.0  # Feeds symbol_loader's zoom*0.5*custom_scale sizing; the icon
                 # is then fit down to ICON_BOX regardless, so this just needs
                 # to be big enough that even the smallest icons (Infantry at
                 # 22px) don't come out blurry when scaled back down.

STYLE_LABELS = {"classic": "Classic", "hanskolmer": "Hanskolmer"}

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


def build_gallery_rows(style):
    """One row per distinct piece of unit art `style` would actually show
    (falling back to classic per the same rule symbol_loader.get_symbol
    uses), in family order, with a header wherever the Infantry/Tanks/Navy
    group changes. Every unit in data/json/unit_data.json is covered -- a
    family with a hundred yearly tiers collapses to as many rows as it has
    distinct pictures, not a hundred near-identical ones.
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
        if group != last_group:
            rows.append({"kind": "header", "label": group})
            last_group = group

        resolved = [symbol_loader.resolve(n, style) for n in names]
        for _key, run in itertools.groupby(zip(names, resolved), key=lambda t: t[1]):
            run_names = [n for n, _r in run]
            first, last = run_names[0], run_names[-1]
            rows.append({"kind": "unit", "group": group,
                        "label": _merge_label(first, last), "resolve_name": first})
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
        self.rows = build_gallery_rows(self.style)
        self._visible_rows = []
        self.scroll_content_rect = None
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              STYLE                                 #
    # ------------------------------------------------------------------ #

    def set_style(self, style):
        if style == self.style:
            return
        self.style = style
        c.apply_runtime_settings({"unit_art_style": style})
        self.controller.unit_art_style = style
        queries.save_global_settings(self.controller)

        self.rows = build_gallery_rows(style)
        self.scroll_y = 0
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                                UI                                  #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]

        y = 100
        for style in c.UNIT_ART_STYLES:
            btn = Button(20, y, "medium", "green" if style == self.style else "grey",
                        STYLE_LABELS.get(style, style.title()), lambda s=style: self.set_style(s))
            btn.is_selected = (style == self.style)
            self.elements.append(btn)
            y += 60

        self.scroll_content_rect = pygame.Rect(GALLERY_X, GALLERY_TOP, GALLERY_W,
                                               GALLERY_BOTTOM - GALLERY_TOP)
        self._visible_rows = [(self.rows[i], row_y) for i, row_y in
                              self.layout_list_rows(len(self.rows), ROW_H, GALLERY_TOP,
                                                    cull_bottom=GALLERY_BOTTOM)]

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
        surface.blit(fonts.get("heading2").render(f"{style_label} Preview", True, (255, 255, 255)),
                    (GALLERY_X + ROW_PAD_X, 70))

        clip = surface.get_clip()
        surface.set_clip(self.scroll_content_rect)
        for row, y in self._visible_rows:
            self._draw_row(surface, row, y)
        surface.set_clip(clip)

        self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 25, GALLERY_TOP, GALLERY_BOTTOM - GALLERY_TOP)

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

        icon = symbol_loader.get_symbol(row["resolve_name"], ICON_ZOOM, style=self.style)
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
