import pygame
import os
from gameState import GameState
from ui_elements import Button
from map_logic.rendering.font_manager import fonts
import data.constants as c

# ==========================================
# LAYOUT
# ==========================================

FOLDER_PANE_W = 240
FILE_PANE_W = 300
PREVIEW_X = FOLDER_PANE_W + FILE_PANE_W
PREVIEW_W = c.SCREEN_WIDTH - PREVIEW_X
HEADER_H = 90

FOLDER_ROW_H = 40
FILE_ROW_H = 24
FILE_FONT_PRESET = "small"


def _truncate_text(text, font, max_width):
    """Shortens text with a trailing ellipsis so it fits max_width, for the
    handful of asset filenames (some flag jokes run 40+ chars) too long to
    ever fit the narrow file-name column."""
    if font.size(text)[0] <= max_width:
        return text

    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(text[:mid] + "...")[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + "...") if lo > 0 else "..."

# Folders that hold non-image assets and shouldn't show up as browsable albums.
EXCLUDED_ASSET_FOLDERS = {"music", "sounds", "fonts"}


class TopBarOverlay:
    """Fixed header drawn over the scrolling folder/file panes, mirroring the music screen."""
    def __init__(self, screen):
        self.screen = screen
        self.visible = True

    def handle_event(self, event):
        pass

    def draw(self, surface):
        pygame.draw.rect(surface, (35, 35, 45), (0, 0, FOLDER_PANE_W, HEADER_H))
        pygame.draw.rect(surface, (30, 30, 38), (FOLDER_PANE_W, 0, FILE_PANE_W, HEADER_H))
        pygame.draw.rect(surface, (20, 20, 25), (PREVIEW_X, 0, PREVIEW_W, HEADER_H))

        pygame.draw.line(surface, (100, 100, 100), (FOLDER_PANE_W, 0), (FOLDER_PANE_W, c.SCREEN_HEIGHT), 2)
        pygame.draw.line(surface, (100, 100, 100), (PREVIEW_X, 0), (PREVIEW_X, c.SCREEN_HEIGHT), 2)

        font_title = fonts.get("heading2")
        surface.blit(font_title.render("FOLDERS", True, (255, 255, 255)), (20, 55))

        folder_label = self.screen.current_folder.upper() if self.screen.current_folder else "FILES"
        surface.blit(font_title.render(folder_label, True, (255, 255, 255)), (FOLDER_PANE_W + 15, 55))

        name_text = self.screen.current_file or "No image selected"
        name_surf = fonts.get("normal").render(name_text, True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(name_surf, (PREVIEW_X + 20, 35))


class View_Assets(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (25, 25, 30)
        self.back_state = "MENU"

        self.current_folder = None
        self.current_file = None
        self.preview_surface = None
        self.preview_error = None

        self.folder_scroll_y = 0
        self.file_scroll_y = 0
        self.max_folder_scroll = 0
        self.max_file_scroll = 0

        self.folder_dragging = False
        self.file_dragging = False
        self.folder_track_rect = None
        self.folder_handle_rect = None
        self.file_track_rect = None
        self.file_handle_rect = None

        self.folders = self._list_folders()
        self.files = []

        if self.folders:
            self.select_folder(self.folders[0])
        else:
            self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              DATA                                  #
    # ------------------------------------------------------------------ #

    def _list_folders(self):
        if not os.path.exists(c.ASSETS_ROOT_DIR):
            return []
        names = []
        for name in sorted(os.listdir(c.ASSETS_ROOT_DIR), key=str.lower):
            full = os.path.join(c.ASSETS_ROOT_DIR, name)
            if os.path.isdir(full) and name.lower() not in EXCLUDED_ASSET_FOLDERS:
                names.append(name)
        return names

    def _list_png_files(self, folder):
        folder_path = os.path.join(c.ASSETS_ROOT_DIR, folder)
        if not os.path.isdir(folder_path):
            return []
        return sorted(
            (name for name in os.listdir(folder_path) if name.lower().endswith(".png")),
            key=str.lower,
        )

    def _scale_to_fit(self, img):
        avail_w = max(1, PREVIEW_W - 40)
        avail_h = max(1, c.SCREEN_HEIGHT - HEADER_H - 40)
        img_w, img_h = img.get_size()
        if img_w <= 0 or img_h <= 0:
            return img

        scale = min(avail_w / img_w, avail_h / img_h)
        new_size = (max(1, int(img_w * scale)), max(1, int(img_h * scale)))
        return pygame.transform.smoothscale(img, new_size)

    # ------------------------------------------------------------------ #
    #                            SELECTION                               #
    # ------------------------------------------------------------------ #

    def select_folder(self, folder):
        self.current_folder = folder
        self.file_scroll_y = 0
        self.files = self._list_png_files(folder)

        if self.files:
            self.select_file(self.files[0])
        else:
            self.current_file = None
            self.preview_surface = None
            self.preview_error = None
            self.refresh_ui()

    def select_file(self, name):
        self.current_file = name
        self.preview_error = None
        self.preview_surface = None

        path = os.path.join(c.ASSETS_ROOT_DIR, self.current_folder, name)
        try:
            raw_img = pygame.image.load(path).convert_alpha()
            self.preview_surface = self._scale_to_fit(raw_img)
        except Exception as e:
            self.preview_error = f"Failed to load {name}: {e}"

        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                               UI                                   #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.elements = []

        # --- Left: Folders (Scrolling) ---
        y = HEADER_H + self.folder_scroll_y
        folder_content_h = 0
        for folder in self.folders:
            is_active = folder == self.current_folder
            color = "green" if is_active else "grey"
            cb = lambda f=folder: self.select_folder(f)

            btn = Button(20, y, "asset_folder", color, folder, cb)
            btn.click_guard = lambda: pygame.mouse.get_pos()[1] >= HEADER_H
            self.elements.append(btn)
            y += FOLDER_ROW_H
            folder_content_h += FOLDER_ROW_H

        self.max_folder_scroll = min(0, c.SCREEN_HEIGHT - HEADER_H - folder_content_h - 20)

        # --- Middle: File names (Scrolling) ---
        file_font = fonts.get(FILE_FONT_PRESET)
        file_btn_w = c.SIZES["asset_file"][0]

        y = HEADER_H + self.file_scroll_y
        file_content_h = 0
        for name in self.files:
            is_active = name == self.current_file
            color = "orange" if is_active else "grey"
            cb = lambda n=name: self.select_file(n)
            label = _truncate_text(name, file_font, file_btn_w - 20)

            btn = Button(FOLDER_PANE_W + 15, y, "asset_file", color, label, cb, font_preset=FILE_FONT_PRESET)
            btn.click_guard = lambda: pygame.mouse.get_pos()[1] >= HEADER_H
            self.elements.append(btn)
            y += FILE_ROW_H
            file_content_h += FILE_ROW_H

        self.max_file_scroll = min(0, c.SCREEN_HEIGHT - HEADER_H - file_content_h - 20)

        # --- Fixed chrome on top ---
        self.elements.append(TopBarOverlay(self))
        self.elements.append(Button(20, 20, "small", "red", "Back", self.handle_back_key))

    # ------------------------------------------------------------------ #
    #                        SCROLL / EVENTS                             #
    # ------------------------------------------------------------------ #

    PANES = {
        "folder": dict(attr="folder_scroll_y", limit_attr="max_folder_scroll",
                        track_attr="folder_track_rect", handle_attr="folder_handle_rect",
                        drag_attr="folder_dragging"),
        "file": dict(attr="file_scroll_y", limit_attr="max_file_scroll",
                     track_attr="file_track_rect", handle_attr="file_handle_rect",
                     drag_attr="file_dragging"),
    }

    def additional_events(self, event):
        if event.type == pygame.MOUSEWHEEL:
            mouse_x = pygame.mouse.get_pos()[0]
            if mouse_x < FOLDER_PANE_W:
                self.handle_list_scroll(event, **self.PANES["folder"])
            elif mouse_x < PREVIEW_X:
                self.handle_list_scroll(event, **self.PANES["file"])
            return

        for pane in self.PANES.values():
            if self.handle_list_scroll(event, **pane):
                return

    def additional_draw(self, surface):
        # Pane backgrounds
        pygame.draw.rect(surface, (35, 35, 45), (0, 0, FOLDER_PANE_W, c.SCREEN_HEIGHT))
        pygame.draw.rect(surface, (30, 30, 38), (FOLDER_PANE_W, 0, FILE_PANE_W, c.SCREEN_HEIGHT))
        pygame.draw.rect(surface, (20, 20, 25), (PREVIEW_X, 0, PREVIEW_W, c.SCREEN_HEIGHT))

        # --- Preview image (majority of the screen, for high-quality viewing) ---
        center = (PREVIEW_X + PREVIEW_W // 2, HEADER_H + (c.SCREEN_HEIGHT - HEADER_H) // 2)
        if self.preview_surface:
            surface.blit(self.preview_surface, self.preview_surface.get_rect(center=center))
        else:
            msg = self.preview_error or "No image selected"
            color = (255, 100, 100) if self.preview_error else (150, 150, 150)
            text_surf = fonts.get("normal").render(msg, True, color)
            surface.blit(text_surf, text_surf.get_rect(center=center))

        # --- Scrollbars ---
        self.draw_list_scrollbar(surface, FOLDER_PANE_W - 15, HEADER_H, c.SCREEN_HEIGHT - HEADER_H,
                                 width=10, **self.PANES["folder"])
        self.draw_list_scrollbar(surface, PREVIEW_X - 15, HEADER_H, c.SCREEN_HEIGHT - HEADER_H,
                                 width=10, **self.PANES["file"])
