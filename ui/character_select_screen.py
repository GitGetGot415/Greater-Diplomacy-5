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

#: Portraits imported via the "+ Add New" tile live here, one level under
#: CHARACTERS_DIR, so discover_character_images() picks them up for free.
CUSTOM_SUBDIR = "Custom"

#: Fallback portrait -- the game's original default look.
DEFAULT_PORTRAIT = "Hildehrand/F/2.png"

#: Extensions accepted both when scanning assets/characters/ and when
#: importing a new custom portrait. Broader than the curated set's plain
#: .png so a photo dragged in from Downloads doesn't need converting first.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

_DIGIT_RE = re.compile(r"(\d+)")
# Lower-cased for the comparison in is_custom_portrait() below: Windows'
# filesystem is case-insensitive, so os.walk() can (and, on at least one
# real machine, does) hand back the on-disk folder as "custom" even though
# it was created by writing to a path spelled "Custom" -- a case-sensitive
# prefix check against CUSTOM_SUBDIR would then silently fail to recognise
# a real custom portrait as custom at all.
_CUSTOM_PREFIX_LOWER = f"{CUSTOM_SUBDIR.lower()}/"


def _natural_key(path):
    """Sorts "Hildehrand/F/2.png" before "Hildehrand/F/10.png" -- plain string
    sorting would put "10" before "2"."""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGIT_RE.split(path)]


def is_custom_portrait(rel_path):
    """True for anything imported via the "+ Add New" tile (assets/characters/Custom/...).

    Compares case-insensitively -- see the _CUSTOM_PREFIX_LOWER comment above."""
    return rel_path.replace(os.sep, "/").lower().startswith(_CUSTOM_PREFIX_LOWER)


def discover_character_images():
    """Every image under assets/characters/, recursively, as forward-slash
    paths relative to CHARACTERS_DIR (e.g. "Hildehrand/F/2.png").

    Custom (user-imported) portraits are sorted first among themselves, ahead
    of the curated set, so a newly-added photo doesn't get lost several pages
    into an alphabetical scan."""
    results = []
    if not os.path.isdir(CHARACTERS_DIR):
        return results
    for dirpath, _dirs, files in os.walk(CHARACTERS_DIR):
        for name in files:
            if name.lower().endswith(IMAGE_EXTENSIONS):
                rel = os.path.relpath(os.path.join(dirpath, name), CHARACTERS_DIR)
                results.append(rel.replace(os.sep, "/"))
    custom = sorted((p for p in results if is_custom_portrait(p)), key=_natural_key)
    curated = sorted((p for p in results if not is_custom_portrait(p)), key=_natural_key)
    return custom + curated


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
        #: rel_path of the custom portrait pending a delete confirmation, if any.
        self.deleting_item = None
        self.refresh_ui()

    def select(self, rel_path):
        self.on_confirm(rel_path)
        self.exit_screen()

    def add_custom_portrait(self):
        """Opens a file picker (starting in Downloads) and copies whatever
        image is chosen into assets/characters/custom/, then refreshes the
        grid so it shows up right away -- no confirm dialog, since unlike a
        mod import this can't run any code, it's just a picture."""
        from data import queries
        queries.import_character_portrait(self, on_success=self._on_custom_imported)

    def _on_custom_imported(self, rel_path):
        self.images = discover_character_images()
        self.refresh_ui()

    def start_delete_custom(self, rel_path):
        self.deleting_item = rel_path
        # The X sits inside scroll_content_rect, so this very click can arm a
        # content-drag on mouse-down. additional_events then blocks mouse
        # events -- including the matching mouse-up -- while the confirm
        # popup is open, so without this the drag is left stuck armed and the
        # next mouse move free-scrolls the grid with no button held. Same
        # fix GameState.cancel_active_drags() exists for: a covering screen
        # stealing that mouse-up.
        self.cancel_active_drags()
        self.refresh_ui()

    def cancel_delete_custom(self):
        self.deleting_item = None
        self.refresh_ui()

    def confirm_delete_custom(self):
        rel_path = self.deleting_item
        if rel_path:
            path = os.path.join(CHARACTERS_DIR, rel_path)
            if os.path.exists(path):
                os.remove(path)
                from data.platform import sync_persisted_dir
                sync_persisted_dir(os.path.join(CHARACTERS_DIR, CUSTOM_SUBDIR))
            # Deleting the portrait currently in use elsewhere would leave that
            # screen holding a path that no longer resolves on the next load --
            # fall back to the default rather than leaving a dangling reference.
            if self.current_path == rel_path:
                self.current_path = DEFAULT_PORTRAIT
                self.on_confirm(DEFAULT_PORTRAIT)
            self.images = discover_character_images()
        self.cancel_delete_custom()

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

        # Slot 0 is the "+ Add New" tile; every image follows it, so the grid
        # has one more slot than there are images.
        total_slots = 1 + len(self.images)
        rows = max(1, (total_slots + cols - 1) // cols)
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
                if idx >= total_slots:
                    break
                x = grid_x + col * (tile_w + self.TILE_GAP)
                if idx == 0:
                    self._add_tile(x, y)
                    continue
                rel_path = self.images[idx - 1]
                # Replaced by the centred confirm popup while its own delete is pending.
                if rel_path == self.deleting_item:
                    continue
                self._portrait_tile(rel_path, x, y, font)

    def _add_tile(self, x, y):
        btn = Button(x, y, "character_portrait_tile", "green", "+ Add New",
                    self.add_custom_portrait, show_text=True, font_preset="small")
        btn.is_scrollable = True
        btn.click_guard = self.scroll_click_guard
        self.elements.append(btn)

    def _portrait_tile(self, rel_path, x, y, font):
        tile_w, _tile_h = c.SIZES["character_portrait_tile"]
        label = text_utils.fit_text(_label_for(rel_path), font, self.LABEL_MAX_WIDTH)
        btn = Button(x, y, "character_portrait_tile", "blue", label,
                    lambda p=rel_path: self.select(p), image=self._thumbnail(rel_path),
                    show_text=True, layout="vertical", font_preset="small")
        btn.is_selected = (rel_path == self.current_path)
        btn.is_scrollable = True

        if is_custom_portrait(rel_path):
            # Sits flush in the tile's top-right corner, on top of it in both
            # z-order (appended after) and click priority (the tile's own
            # guard below refuses clicks landing inside the X's rect).
            del_btn = Button(x + tile_w - 30, y, "tiny_square", "red", "X",
                             lambda p=rel_path: self.start_delete_custom(p))
            del_btn.is_scrollable = True
            del_btn.click_guard = self.scroll_click_guard

            scroll_guard = self.scroll_click_guard
            def tile_guard(dbtn=del_btn, sg=scroll_guard):
                return not dbtn.rect.collidepoint(pygame.mouse.get_pos()) and sg()
            btn.click_guard = tile_guard

            self.elements.append(btn)
            self.elements.append(del_btn)
        else:
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

    def additional_events(self, event):
        if self.deleting_item:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.confirm_delete_custom()
                elif event.key == pygame.K_ESCAPE:
                    self.cancel_delete_custom()
            return
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def draw_body(self, surface):
        if not self.images:
            msg = fonts.get("normal").render("No character portraits found.", True, c.UI_TEXT_LIGHT)
            surface.blit(msg, msg.get_rect(center=self.panel_rect.center))

    def draw_foreground(self, surface):
        self.draw_list_scrollbar(surface, self.panel_rect.right - 30, self.panel_rect.y + self.GRID_TOP,
                                 self.panel_rect.height - self.GRID_TOP - 20)
        if self.deleting_item:
            self._draw_delete_confirm(surface)

    def _draw_delete_confirm(self, surface):
        """Dims the panel and asks for Enter/Escape -- same shape as
        gameState.FolderListState.draw_delete_confirm, hand-rolled here since
        this screen isn't (and doesn't otherwise need to be) a FolderListState."""
        from ui.bars import ui_bars

        ui_bars.draw_fullscreen_overlay(surface, 180)

        pop_rect = pygame.Rect(0, 0, 500, 200)
        pop_rect.center = self.panel_rect.center
        bg, border, border_width = c.PANEL_THEME_DANGER
        ui_bars.draw_modal_box(surface, pop_rect, bg_color=bg, border_color=border,
                               border_width=border_width)

        name = _label_for(self.deleting_item)
        msg = fonts.get("heading2").render(f"Delete '{name}'?", True, (255, 255, 255))
        surface.blit(msg, msg.get_rect(center=(pop_rect.centerx, pop_rect.centery - 25)))

        sub_msg = fonts.get("normal").render("Press Enter to Confirm or Esc to Cancel", True, c.UI_TEXT_LIGHT)
        surface.blit(sub_msg, sub_msg.get_rect(center=(pop_rect.centerx, pop_rect.centery + 25)))
