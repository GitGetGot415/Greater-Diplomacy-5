"""Modal grid picker for choosing any portrait under assets/characters/.

Originally the main menu's Hildehrand button just toggled between two
hardcoded images (assets/images/Hildehrand F.png / M.png). This replaces that
with a picker over every portrait in assets/characters/ (Aamari, Hildehrand's
F and M subfolders, Pierre, Rachel, Yasmine, ...), so it stays useful as more
characters/variants are added without any code change.
"""
import os
import re

import pygame

import data.constants as c
from ui import text_utils
from ui.modal_screen import ModalScreen
from ui_elements import Button
from map_logic.rendering.font_manager import fonts

CHARACTERS_DIR = "assets/characters"

#: Fallback portrait -- the game's original default look.
DEFAULT_PORTRAIT = "Hildehrand/F/2.png"

_DIGIT_RE = re.compile(r"(\d+)")


def _natural_key(path):
    """Sorts "Hildehrand/F/2.png" before "Hildehrand/F/10.png" -- plain string
    sorting would put "10" before "2"."""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGIT_RE.split(path)]


def discover_character_images():
    """Every .png under assets/characters/, recursively, as forward-slash
    paths relative to CHARACTERS_DIR (e.g. "Hildehrand/F/2.png")."""
    results = []
    if not os.path.isdir(CHARACTERS_DIR):
        return results
    for dirpath, _dirs, files in os.walk(CHARACTERS_DIR):
        for name in files:
            if name.lower().endswith(".png"):
                rel = os.path.relpath(os.path.join(dirpath, name), CHARACTERS_DIR)
                results.append(rel.replace(os.sep, "/"))
    results.sort(key=_natural_key)
    return results


def _label_for(rel_path):
    parts = rel_path.split("/")
    parts[-1] = os.path.splitext(parts[-1])[0]
    return " ".join(parts)


def _load_thumbnail(path, max_w, max_h):
    raw = pygame.image.load(path).convert_alpha()
    w, h = raw.get_size()
    if w <= 0 or h <= 0:
        return raw
    scale = min(max_w / w, max_h / h)
    size = (max(1, int(w * scale)), max(1, int(h * scale)))
    # Matches view_assets.py's rule: smoothscale only when shrinking, since
    # nearest-neighbour keeps pixel art crisp when enlarging.
    if scale >= 1.0:
        return pygame.transform.scale(raw, size)
    return pygame.transform.smoothscale(raw, size)


class CharacterSelectScreen(ModalScreen):
    """Click-to-pick grid of every portrait under assets/characters/, styled
    after ColorPickerScreen/ListSelectScreen: a dimmed freeze-frame behind a
    bordered panel, Cancel top-left, closes itself on a pick."""

    PANEL_SIZE = (900, 640)
    COLUMNS = 4
    TILE_GAP = 18
    THUMB_MAX = (120, 110)
    GRID_TOP = 90
    LABEL_MAX_WIDTH = 170

    def __init__(self, game_state, current_path, on_confirm):
        super().__init__(game_state, "Choose a Portrait")
        self.on_confirm = on_confirm
        self.current_path = current_path
        self.images = discover_character_images()
        self._thumbnails = {}
        self.refresh_ui()

    def select(self, rel_path):
        self.on_confirm(rel_path)
        self.exit_screen()

    def _thumbnail(self, rel_path):
        thumb = self._thumbnails.get(rel_path)
        if rel_path not in self._thumbnails:
            try:
                thumb = _load_thumbnail(f"{CHARACTERS_DIR}/{rel_path}", *self.THUMB_MAX)
            except Exception:
                thumb = None
            self._thumbnails[rel_path] = thumb
        return thumb

    def refresh_ui(self):
        self.elements = [Button(self.panel_rect.x + 20, self.panel_rect.y + 20, "small", "red",
                                "Cancel", self.exit_screen)]

        tile_w, tile_h = c.SIZES["character_portrait_tile"]
        cols = self.COLUMNS
        grid_w = cols * tile_w + (cols - 1) * self.TILE_GAP
        grid_x = self.panel_rect.centerx - grid_w // 2
        grid_top = self.panel_rect.y + self.GRID_TOP

        rows = max(1, (len(self.images) + cols - 1) // cols)
        row_h = tile_h + self.TILE_GAP
        cull_top, cull_bottom = grid_top, self.panel_rect.bottom - 20
        view_h = cull_bottom - grid_top
        self.scroll_content_rect = pygame.Rect(self.panel_rect.x, cull_top, self.panel_rect.width,
                                               cull_bottom - cull_top)

        font = fonts.get("small")
        for row, y in self.layout_list_rows(rows, row_h, grid_top, view_h=view_h,
                                            cull_top=cull_top, cull_bottom=cull_bottom):
            for col in range(cols):
                idx = row * cols + col
                if idx >= len(self.images):
                    break
                rel_path = self.images[idx]
                x = grid_x + col * (tile_w + self.TILE_GAP)
                label = text_utils.fit_text(_label_for(rel_path), font, self.LABEL_MAX_WIDTH)
                btn = Button(x, y, "character_portrait_tile", "blue", label,
                            lambda p=rel_path: self.select(p), image=self._thumbnail(rel_path),
                            show_text=True, layout="vertical", font_preset="small")
                btn.is_selected = (rel_path == self.current_path)
                btn.is_scrollable = True
                btn.click_guard = self.scroll_click_guard
                self.elements.append(btn)

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw_body(self, surface):
        if not self.images:
            msg = fonts.get("normal").render("No character portraits found.", True, c.UI_TEXT_LIGHT)
            surface.blit(msg, msg.get_rect(center=self.panel_rect.center))

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 30, self.panel_rect.y + self.GRID_TOP,
                                 self.panel_rect.height - self.GRID_TOP - 20)
