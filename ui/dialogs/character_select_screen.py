"""Modal grid picker for choosing any portrait under assets/characters/.

Originally the main menu's Hildehrand button just toggled between two
hardcoded images (assets/images/Hildehrand F.png / M.png). This replaces that
with a picker over every portrait in assets/characters/ (Aamari, Hildehrand's
F and M subfolders, Pierre, Rachel, Yasmine, ...), so it stays useful as more
characters/variants are added without any code change.
"""
import os

import pygame

import data.constants as c
from ui.widgets import text_utils
from ui.navigation.modal_screen import ModalScreen
from ui.widgets.ui_elements import Button
from ui.rendering.font_manager import fonts

from ui import dialogs
from ui.dialogs import file_exchange
from data.platform import CHARACTERS_DIR, CUSTOM_SUBDIR, sync_persisted_dir
from data.queries.content import DEFAULT_PORTRAIT, discover_character_images, is_custom_portrait


def _label_for(rel_path):
    parts = rel_path.split("/")
    # The "Custom" folder itself is just where imported portraits live, not
    # part of anyone's name -- drop it so a custom tile reads e.g. "Photo"
    # instead of "Custom Photo".
    if is_custom_portrait(rel_path):
        parts = parts[1:]
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
        self._center_current_on_open = True
        self.refresh_ui()

    def select(self, rel_path):
        self.on_confirm(rel_path)
        self.exit_screen()

    def add_custom_portrait(self):
        """Opens a file picker (starting in Downloads) and copies whatever
        image is chosen into assets/characters/custom/, then refreshes the
        grid so it shows up right away -- no confirm dialog, since unlike a
        mod import this can't run any code, it's just a picture."""
        file_exchange.import_character_portrait(self, on_success=self._on_custom_imported)

    def _on_custom_imported(self, rel_path):
        self.images = discover_character_images()
        self.refresh_ui()

    def start_delete_custom(self, rel_path):
        dialogs.ask_yes_no("Delete Portrait", f"Delete '{_label_for(rel_path)}'? This cannot be undone.",
                           lambda confirmed: self.delete_custom(rel_path) if confirmed else None)

    def delete_custom(self, rel_path):
        path = os.path.join(CHARACTERS_DIR, rel_path)
        if os.path.exists(path):
            os.remove(path)
            sync_persisted_dir(os.path.join(CHARACTERS_DIR, CUSTOM_SUBDIR))
        # Deleting the portrait currently in use elsewhere would leave that
        # screen holding a path that no longer resolves on the next load --
        # fall back to the default rather than leaving a dangling reference.
        if self.current_path == rel_path:
            self.current_path = DEFAULT_PORTRAIT
            self.on_confirm(DEFAULT_PORTRAIT)
        self.images = discover_character_images()
        self.refresh_ui()

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
                                "Cancel", self.exit_screen, sound_kind="back")]

        tile_w, tile_h = c.SIZES["character_portrait_tile"]
        cols = self.COLUMNS
        grid_w = cols * tile_w + (cols - 1) * self.TILE_GAP
        grid_x = self.panel_rect.centerx - grid_w // 2
        grid_top = self.panel_rect.y + self.GRID_TOP

        # Slot 0 is the "+ Add New" tile; every image follows it, so the grid
        # has one more slot than there are images.
        total_slots = 1 + len(self.images)
        rows = max(1, (total_slots + cols - 1) // cols)
        row_h = tile_h + self.TILE_GAP
        cull_top, cull_bottom = grid_top, self.panel_rect.bottom - 20
        view_h = cull_bottom - grid_top
        self.scroll_content_rect = pygame.Rect(self.panel_rect.x, cull_top, self.panel_rect.width,
                                               cull_bottom - cull_top)

        if self._center_current_on_open:
            self._center_current_on_open = False
            if self.current_path in self.images:
                row = (self.images.index(self.current_path) + 1) // cols
                desired = view_h // 2 - (row * row_h + tile_h // 2)
                self.scroll_y = max(min(0, view_h - rows * row_h), min(0, desired))

        font = fonts.get("small")
        for row, y in self.layout_list_rows(rows, row_h, grid_top, view_h=view_h,
                                            cull_top=cull_top, cull_bottom=cull_bottom):
            for col in range(cols):
                idx = row * cols + col
                if idx >= total_slots:
                    break
                x = grid_x + col * (tile_w + self.TILE_GAP)
                if idx == 0:
                    self._add_tile(x, y)
                    continue
                self._portrait_tile(self.images[idx - 1], x, y, font)

    def _add_tile(self, x, y):
        btn = Button(x, y, "character_portrait_tile", "green", "+ Add New",
                    self.add_custom_portrait, show_text=True, font_preset="small")
        self.add_list_row(btn)

    def _portrait_tile(self, rel_path, x, y, font):
        tile_w, _tile_h = c.SIZES["character_portrait_tile"]
        label = text_utils.fit_text(_label_for(rel_path), font, self.LABEL_MAX_WIDTH)
        tile_color = "purple" if is_custom_portrait(rel_path) else "blue"
        btn = Button(x, y, "character_portrait_tile", tile_color, label,
                    lambda p=rel_path: self.select(p), image=self._thumbnail(rel_path),
                    show_text=True, layout="vertical", font_preset="small", sound_kind="select_sub_category")
        btn.is_selected = (rel_path == self.current_path)
        self.add_list_row(btn)

        if is_custom_portrait(rel_path):
            # Sits flush in the tile's top-right corner, on top of it in both
            # z-order (appended after) and click priority (the tile's own
            # guard below refuses clicks landing inside the X's rect).
            del_btn = Button(x + tile_w - 30, y, "tiny_square", "red", "X",
                             lambda p=rel_path: self.start_delete_custom(p))

            scroll_guard = self.scroll_click_guard
            def tile_guard(dbtn=del_btn, sg=scroll_guard):
                return not dbtn.rect.collidepoint(pygame.mouse.get_pos()) and sg()
            btn.click_guard = tile_guard

            self.add_list_row(del_btn)

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw_body(self, surface):
        if not self.images:
            msg = fonts.get("normal").render("No character portraits found.", True, c.UI_TEXT_LIGHT)
            surface.blit(msg, msg.get_rect(center=self.panel_rect.center))

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 30, self.panel_rect.y + self.GRID_TOP,
                                 self.panel_rect.height - self.GRID_TOP - 20)
