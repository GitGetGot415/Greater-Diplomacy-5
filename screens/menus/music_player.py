import pygame
import os
from data import queries
from data.io import settings_schema
from ui.widgets import ui_elements
from ui.navigation.screen import Screen, ScreenLayer
from ui.bars import ui_bars
from ui.background_styles import MUSIC_PANEL_STYLES
from ui.widgets.scroll_panes import ScrollPanes
from ui.widgets.text_utils import fit_text
from ui.widgets.ui_elements import Button, Slider, make_back_button, make_choice_button, make_info_button
from ui.rendering.font_manager import fonts
import data.constants as c
from beepbox_audio import source_seconds_from_timeline, timeline_seconds_from_source

from ui import dialogs
from ui.dialogs import pickers
from data.platform import downloads_dir
# ==========================================
# LAYOUT
# ==========================================

MUSIC_SCROLLBAR_WIDTH = 20
# Albums sit in a grid of ALBUM_COLUMNS tiles; the left pane is sized to hold it.
ALBUM_COLUMNS = 2
# Album folder names shown first, in this order. Names with no matching folder
# are skipped. Every other album follows, sorted A to Z.
ALBUM_ORDER = ["Greater Diplomacy 5", "Greater Diplomacy 4", "Greater Diplomacy 3", "Greater Diplomacy 2", "Greater Diplomacy 1", "Experimental"]
# The tile that makes a new album is always the last tile, after every album.
NEW_ALBUM_LABEL = "+ New Album"
ALBUM_DELETE_BUTTON_SIZE = (22, 22)
# How far the delete button sticks out past the tile's top-right corner.
ALBUM_DELETE_OVERHANG = 6
ALBUM_MARGIN = 20
ADD_SONG_LABEL = "+ Add Song"
# Sits inside the top-right corner of a song button. Songs are only 2px apart,
# so unlike the album button it cannot stick out.
SONG_DELETE_BUTTON_SIZE = (18, 18)
SONG_FILE_EXTENSIONS = list(c.MUSIC_AUDIO_EXTENSIONS) + [".json"]
ALBUM_GAP = 10
ALBUM_TILE_SIZE = (140, 170)
ALBUM_TEXT_TILE_SIZE = (140, 50)
# Tiles without a cover stack up to this many per slot.
ALBUM_MAX_TEXT_STACK = 3
# Every cover is stretched to this size so all tiles look alike.
ALBUM_COVER_SIZE = (120, 120)
ALBUM_COVER_BOTTOM_MARGIN = 10
MUSIC_LEFT_PANE_W = (ALBUM_MARGIN + ALBUM_COLUMNS * ALBUM_TILE_SIZE[0] + (ALBUM_COLUMNS - 1) * ALBUM_GAP
                     + ALBUM_GAP + MUSIC_SCROLLBAR_WIDTH + 5)
song_y = 32
TRACK_SHUFFLE_TOGGLE_SIZE = (26, 26)
TRACK_SHUFFLE_TOGGLE_GAP = 4
TRACK_ALBUM_HEADER_HEIGHT = 32
TRACK_ALBUM_LABEL_GAP = 10
TRACK_ADD_SONG_DIVIDER_HEIGHT = 12
TRACK_ADD_SONG_DIVIDER_TOP_GAP = 8
TRACK_ADD_SONG_GAP = 8
# The right pane holds audio sliders and pinned song controls.
MUSIC_RIGHT_PANE_W = 260
MUSIC_RIGHT_PANE_X = c.SCREEN_WIDTH - MUSIC_RIGHT_PANE_W
MUSIC_RIGHT_CONTROL_W = 200
MUSIC_RIGHT_CONTROL_X = MUSIC_RIGHT_PANE_X + (MUSIC_RIGHT_PANE_W - MUSIC_RIGHT_CONTROL_W) // 2
MUSIC_STARTING_SONG_Y = 390
MUSIC_PIN_BUTTON_SIZE = (MUSIC_RIGHT_CONTROL_W, 32)
MUSIC_PIN_LABEL_GAP = 28
MUSIC_PIN_BUTTON_GAP = 8
MUSIC_TACTICAL_SONG_Y = (MUSIC_STARTING_SONG_Y + MUSIC_PIN_LABEL_GAP
                         + 2 * (MUSIC_PIN_BUTTON_SIZE[1] + MUSIC_PIN_BUTTON_GAP) + 24)
MUSIC_PROGRESS_X = MUSIC_LEFT_PANE_W + 20
MUSIC_PROGRESS_Y = 155
MUSIC_PROGRESS_SIZE = (400, 15)
MUSIC_TIMELINE_BUTTON_SIZE = (70, 40)
MUSIC_TIMELINE_BUTTON_GAP = 10
MUSIC_TIMELINE_BUTTON_X = MUSIC_PROGRESS_X + MUSIC_PROGRESS_SIZE[0] + 20
MUSIC_TIMELINE_BUTTON_Y = MUSIC_PROGRESS_Y - (MUSIC_TIMELINE_BUTTON_SIZE[1] - MUSIC_PROGRESS_SIZE[1]) // 2
MUSIC_TIMELINE_HELP_BUTTON_X = (
    MUSIC_TIMELINE_BUTTON_X + (2 * MUSIC_TIMELINE_BUTTON_SIZE[0])
    + MUSIC_TIMELINE_BUTTON_GAP + MUSIC_TIMELINE_BUTTON_GAP
)
MUSIC_TIMELINE_HELP_BUTTON_Y = (
    MUSIC_TIMELINE_BUTTON_Y
    + (MUSIC_TIMELINE_BUTTON_SIZE[1] - c.SIZES["scenario_setting_info"][1]) // 2
)

class MusicScrubber:
    """A dedicated interactive UI slider specifically for scrubbing music playback."""
    def __init__(self, x, y, width, height, callback):
        self.rect = pygame.Rect(x, y, width, height)
        self.callback = callback
        self.value = 0.0  # Range: 0.0 to 1.0
        self.is_dragging = False
        self.visible = True
        self.current_time_str = "00:00"
        self.total_time_str = "00:00"

    def _format_time(self, seconds):
        s = int(max(0, seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    def update_progress(self, current_sec, total_sec):
        if total_sec > 0:
            self.total_time_str = self._format_time(total_sec)
            
            if self.is_dragging:
                # Show projected time while dragging
                scrub_time = self.value * total_sec
                self.current_time_str = self._format_time(scrub_time)
            else:
                # Sync exactly with playback if not dragging
                self.current_time_str = self._format_time(current_sec)
                self.value = max(0.0, min(1.0, current_sec / total_sec))
        else:
            self.total_time_str = "00:00"
            self.current_time_str = "00:00"
            if not self.is_dragging:
                self.value = 0.0

    def handle_event(self, event):
        if not self.visible: return
        
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Expand hitbox slightly vertically to make it easier to grab
            hitbox = self.rect.inflate(0, 10)
            if hitbox.collidepoint(event.pos):
                self.is_dragging = True
                self._update_value_from_mouse(event.pos[0])
                
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_dragging:
                self.is_dragging = False
                if self.callback:
                    self.callback(self.value)
                    
        elif event.type == pygame.MOUSEMOTION:
            if self.is_dragging:
                self._update_value_from_mouse(event.pos[0])

    def _update_value_from_mouse(self, mouse_x):
        rel_x = max(0, min(mouse_x - self.rect.x, self.rect.width))
        self.value = rel_x / self.rect.width

    def draw(self, surface):
        if not self.visible: return
        
        # Draw text above the track
        font = fonts.get("tiny")
        text_str = f"Progress:  {self.current_time_str} / {self.total_time_str}"
        text_surf = font.render(text_str, True, (255, 255, 255))
        text_rect = text_surf.get_rect(topleft=(self.rect.x, self.rect.y - 20))
        surface.blit(text_surf, text_rect)
        
        fill_width = int(self.value * self.rect.width)
        handle_x = self.rect.x + fill_width
        handle_rect = pygame.Rect(handle_x - 5, self.rect.y - 5, 10, self.rect.height + 10)
        ui_elements.draw_slider(surface, self.rect, handle_rect,
                                dragging=self.is_dragging, progress_ratio=self.value)


class Music_Player(ScrollPanes, Screen):
    progress_slider = None

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.back_state = "MENU"
        
        # Track auto-plays so UI syncs when a song naturally ends.
        # FIX: Explicitly set to None on boot so the UI forcefully syncs 
        # to the audio engine the very first time the menu is opened.
        self._last_playing_track = None
        
        # Ensure directories and files exist
        if not os.path.exists(c.MUSIC_DIR):
            os.makedirs(c.MUSIC_DIR)
        
        self._scroll_album = 0
        self._scroll_track = 0
        self._max_album = 0
        self._max_track = 0
        
        # Drag state trackers for scrollbars
        self._drag_album = False
        self._drag_track = False
        self._track_album = None
        self._handle_album = None
        self._track_track = None
        self._handle_track = None
        
        
        self.refresh_ui()

    def on_enter(self, app, previous):
        self.return_to_previous_context(app, previous)

    def refresh_ui(self):
        self.elements = []

        self._content_album = pygame.Rect(0, 120, MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT - 120)
        self._content_track = pygame.Rect(MUSIC_LEFT_PANE_W, 200, MUSIC_RIGHT_PANE_X - MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT - 200)

        # --- 1. Left Column: Albums (Scrolling) ---
        # Room above the first row so the delete buttons are not cut off.
        y_offset = 120 + ALBUM_DELETE_OVERHANG + self._scroll_album
        album_content_h = ALBUM_DELETE_OVERHANG
        
        albums = self.album_display_order()
        # A row has ALBUM_COLUMNS slots. Each slot holds one cover tile, or a
        # stack of up to ALBUM_MAX_TEXT_STACK tiles without a cover.
        slot_heights = [0] * ALBUM_COLUMNS
        column = -1
        text_stack = 0
        slot_buttons = [[] for _ in range(ALBUM_COLUMNS)]
        # None stands for the new-album tile, which always comes last.
        tiles = albums + [None]
        for album in tiles:
            is_active = album is not None and album in self.controller.active_albums
            color = "green" if is_active else "grey"
            
            # --- IMPROVED COVER ART SEARCH ---
            icon_img = None
            album_dir = None if album is None else os.path.join(c.MUSIC_DIR, album)
            
            if album_dir is not None and os.path.exists(album_dir):
                # Search the album folder for ANY valid image file to use as the cover art
                for file in os.listdir(album_dir):
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        try:
                            icon_path = os.path.join(album_dir, file)
                            raw_img = pygame.image.load(icon_path).convert_alpha()
                            icon_img = pygame.transform.smoothscale(raw_img, ALBUM_COVER_SIZE)
                            break # Found an image, stop searching
                        except Exception as e:
                            print(f"Error loading icon {file} for {album}: {e}")
            
            # Only registers a click (sound included) when below the clipping header!
            album_cb = self.start_new_album if album is None else (lambda a=album: self.toggle_album(a))
            album_guard = lambda: pygame.mouse.get_pos()[1] >= 120

            if icon_img is None and text_stack and text_stack < ALBUM_MAX_TEXT_STACK:
                # Directly under the previous tile, which has no cover either.
                text_stack += 1
            else:
                column += 1
                if column == ALBUM_COLUMNS:
                    y_offset += max(slot_heights)
                    album_content_h += max(slot_heights)
                    slot_heights = [0] * ALBUM_COLUMNS
                    slot_buttons = [[] for _ in range(ALBUM_COLUMNS)]
                    column = 0
                text_stack = 0 if icon_img else 1
            tile_x = ALBUM_MARGIN + column * (ALBUM_TILE_SIZE[0] + ALBUM_GAP)
            tile_y = y_offset + slot_heights[column]
            if icon_img:
                btn = Button(tile_x, tile_y, ALBUM_TILE_SIZE, color, album,
                             album_cb, image=icon_img, show_text=True, layout="vertical")
            elif album is None:
                btn = Button(tile_x, tile_y, ALBUM_TEXT_TILE_SIZE, "blue", NEW_ALBUM_LABEL, album_cb)
            else:
                btn = Button(tile_x, tile_y, ALBUM_TEXT_TILE_SIZE, color, album, album_cb)
            slot_heights[column] += btn.height + ALBUM_GAP
            btn.click_guard = album_guard
            btn.fit_text = True
            btn.image_bottom_margin = ALBUM_COVER_BOTTOM_MARGIN
            btn.sound_kind = "select_category"
            btn.pane = "album"
            self.elements.append(btn)
            slot_buttons[column].append(btn)

            if album is not None and queries.is_deletable_album(album):
                # Sticks out of the tile's top-right corner, on top of it in z-order
                # (appended after) and in click priority (the tile's guard
                # refuses clicks that land inside the X).
                delete_btn = Button(btn.rect.right - ALBUM_DELETE_BUTTON_SIZE[0] + ALBUM_DELETE_OVERHANG,
                                    btn.rect.y - ALBUM_DELETE_OVERHANG,
                                    ALBUM_DELETE_BUTTON_SIZE, "red", "X",
                                    lambda a=album: self.start_delete_album(a), font_preset="tiny")
                delete_btn.click_guard = album_guard
                delete_btn.pane = "album"
                self.elements.append(delete_btn)
                btn.hover_blocker = delete_btn
                btn.click_guard = lambda dbtn=delete_btn: (
                    not dbtn.rect.collidepoint(pygame.mouse.get_pos()) and album_guard())

        # Fill the last row's trailing text slots left to right before stacking.
        # New Album follows every album in that same visual order.
        first_text_column = 0
        for index, buttons in enumerate(slot_buttons):
            if buttons and buttons[0].image is not None:
                first_text_column = index + 1
        text_buttons = [btn for buttons in slot_buttons[first_text_column:] for btn in buttons]
        stack_columns = min(ALBUM_COLUMNS - first_text_column, len(text_buttons))
        if stack_columns > 1:
            for target_column in range(first_text_column, first_text_column + stack_columns):
                slot_heights[target_column] = 0
            for index, btn in enumerate(text_buttons):
                target_column = first_text_column + index % stack_columns
                tile_x = ALBUM_MARGIN + target_column * (ALBUM_TILE_SIZE[0] + ALBUM_GAP)
                tile_y = y_offset + slot_heights[target_column]
                if btn.hover_blocker is not None:
                    btn.hover_blocker.rect.move_ip(tile_x - btn.rect.x, tile_y - btn.rect.y)
                btn.rect.topleft = (tile_x, tile_y)
                slot_heights[target_column] += btn.height + ALBUM_GAP

        album_content_h += max(slot_heights)
        # Calculate max boundary for Album scrolling
        self._max_album = min(0, c.SCREEN_HEIGHT - 120 - album_content_h - 20)

        # --- 2. Right Column: Tracks (Scrolling) ---
        track_y = 200 + self._scroll_track # Adjusted to start below new scrubber
        track_content_h = 0
        self._track_dividers = []
        previous_album = None
        header_width = c.SIZES["song"][0] + TRACK_SHUFFLE_TOGGLE_GAP + TRACK_SHUFFLE_TOGGLE_SIZE[0]
        header_font = fonts.get("small")
        
        for track_path in self.controller.playlist:
            album = os.path.basename(os.path.dirname(track_path.replace("\\", "/")))
            if album != previous_album:
                header = pygame.Surface((header_width, TRACK_ALBUM_HEADER_HEIGHT), pygame.SRCALPHA)
                label = header_font.render(
                    fit_text(album, header_font, header_width - 4 * TRACK_ALBUM_LABEL_GAP),
                    True, c.UI_TEXT_DIM)
                label_rect = label.get_rect(center=header.get_rect().center)
                pygame.draw.line(header, c.UI_TEXT_DIM, (0, label_rect.centery),
                                 (label_rect.left - TRACK_ALBUM_LABEL_GAP, label_rect.centery))
                pygame.draw.line(header, c.UI_TEXT_DIM,
                                 (label_rect.right + TRACK_ALBUM_LABEL_GAP, label_rect.centery),
                                 (header_width - 1, label_rect.centery))
                header.blit(label, label_rect)
                self._track_dividers.append((
                    header, header.get_rect(topleft=(MUSIC_LEFT_PANE_W + 20, track_y))))
                track_y += TRACK_ALBUM_HEADER_HEIGHT
                track_content_h += TRACK_ALBUM_HEADER_HEIGHT
                previous_album = album
            track_name = os.path.basename(track_path)
            is_playing = (self.controller.now_playing == track_path)
            excluded_from_shuffle = self.controller.is_shuffle_disabled(track_path)
            color = "orange" if is_playing else "grey"
            
            # Only registers a click (sound included) when below the clipping header!
            track_cb = lambda p=track_path: self.play_track(p)

            # Excluding a track only removes it from automatic random
            # selection; it must remain available for deliberate playback.
            track_btn = Button(MUSIC_LEFT_PANE_W + 20, track_y, "song", color, track_name, track_cb)
            track_btn.click_guard = lambda: pygame.mouse.get_pos()[1] >= 200
            track_btn.fit_text = True
            track_btn.fit_single_line = True
            track_btn.sound_kind = "select_sub_category"
            track_btn.pane = "track"
            self.elements.append(track_btn)

            # Keep the shuffle toggle separate from the manual playback button.
            shuffle_toggle = Button(
                track_btn.rect.right + TRACK_SHUFFLE_TOGGLE_GAP,
                track_y + (song_y - TRACK_SHUFFLE_TOGGLE_SIZE[1]) // 2,
                TRACK_SHUFFLE_TOGGLE_SIZE,
                "grey" if excluded_from_shuffle else "green",
                "S",
                lambda p=track_path: self.toggle_shuffle_exclusion(p),
                font_preset="tiny",
            )
            shuffle_toggle.click_guard = lambda: pygame.mouse.get_pos()[1] >= 200
            shuffle_toggle.pane = "track"
            self.elements.append(shuffle_toggle)

            if queries.is_deletable_song(track_path):
                song_guard = track_btn.click_guard
                delete_btn = Button(track_btn.rect.right - SONG_DELETE_BUTTON_SIZE[0], track_btn.rect.y,
                                    SONG_DELETE_BUTTON_SIZE, "red", "X",
                                    lambda p=track_path: self.start_delete_song(p), font_preset="tiny")
                delete_btn.click_guard = song_guard
                delete_btn.pane = "track"
                self.elements.append(delete_btn)
                track_btn.hover_blocker = delete_btn
                track_btn.click_guard = lambda dbtn=delete_btn, guard=song_guard: (
                    not dbtn.rect.collidepoint(pygame.mouse.get_pos()) and guard())
            track_y += song_y
            track_content_h += song_y

        if self.controller.playlist:
            track_y += TRACK_ADD_SONG_DIVIDER_TOP_GAP
            track_content_h += TRACK_ADD_SONG_DIVIDER_TOP_GAP
            divider = pygame.Surface((header_width, TRACK_ADD_SONG_DIVIDER_HEIGHT), pygame.SRCALPHA)
            pygame.draw.line(divider, c.UI_TEXT_DIM,
                             (0, TRACK_ADD_SONG_DIVIDER_HEIGHT // 2),
                             (header_width - 1, TRACK_ADD_SONG_DIVIDER_HEIGHT // 2))
            self._track_dividers.append((
                divider, divider.get_rect(topleft=(MUSIC_LEFT_PANE_W + 20, track_y))))
            track_y += TRACK_ADD_SONG_DIVIDER_HEIGHT + TRACK_ADD_SONG_GAP
            track_content_h += TRACK_ADD_SONG_DIVIDER_HEIGHT + TRACK_ADD_SONG_GAP

        # Always the last row of the song list.
        add_song_btn = Button(MUSIC_LEFT_PANE_W + 20, track_y, "song", "blue", ADD_SONG_LABEL,
                              self.start_add_song, sound_kind=None)
        add_song_btn.click_guard = lambda: pygame.mouse.get_pos()[1] >= 200
        add_song_btn.pane = "track"
        self.elements.append(add_song_btn)
        track_content_h += song_y

        # Calculate max boundary for Track scrolling
        self._max_track = min(0, c.SCREEN_HEIGHT - 200 - track_content_h - 20)

        # --- 3. Top Layer: Fixed Overlay & Buttons ---
        self.elements.append(ScreenLayer(self, "draw_top_bar"))
        
        self.elements.append(make_back_button(self.handle_back_key))
        # Anchored relative to the UI so it never scrolls away!
        self.elements.append(Button(MUSIC_LEFT_PANE_W + 20, 80, "medium", "green", "Skip / Random Song",
                                    self.play_track, sound_kind="skip_song"))
        
        # Add Pause Button
        pause_text = "Play" if self.is_paused() else "Pause"
        self.elements.append(Button(MUSIC_LEFT_PANE_W + 240, 80, "medium", "orange", pause_text,
                                    self.toggle_pause, sound_kind="toggle_pause"))
        
        # Add Progress Slider (Custom MusicScrubber)
        self.progress_slider = MusicScrubber(
            MUSIC_PROGRESS_X, MUSIC_PROGRESS_Y, *MUSIC_PROGRESS_SIZE,
            self.scrub_music,
        )
        self.elements.append(self.progress_slider)
        timeline_mode = self.controller.music_pitch_timeline
        self.elements.append(make_choice_button(
            MUSIC_TIMELINE_BUTTON_X, MUSIC_TIMELINE_BUTTON_Y, MUSIC_TIMELINE_BUTTON_SIZE, "Static",
            timeline_mode == c.MUSIC_PITCH_TIMELINE_STATIC, self.set_static_pitch_timeline,
            idle_color="grey", font_preset="tiny",
        ))
        self.elements.append(make_choice_button(
            MUSIC_TIMELINE_BUTTON_X + MUSIC_TIMELINE_BUTTON_SIZE[0] + MUSIC_TIMELINE_BUTTON_GAP,
            MUSIC_TIMELINE_BUTTON_Y, MUSIC_TIMELINE_BUTTON_SIZE, "Dynamic",
            timeline_mode == c.MUSIC_PITCH_TIMELINE_DYNAMIC, self.set_dynamic_pitch_timeline,
            idle_color="grey", font_preset="tiny",
        ))
        self.elements.append(make_info_button(
            MUSIC_TIMELINE_HELP_BUTTON_X,
            MUSIC_TIMELINE_HELP_BUTTON_Y,
            self.show_timeline_and_queue_help,
        ))
        
        # --- 4. Top Layer: Audio Sliders ---
        slider_x = MUSIC_RIGHT_CONTROL_X
        
        self.elements.append(Slider(slider_x, 40, 200, "SFX Vol", self.controller.sfx_volume, self.set_sfx_volume))
        self.elements.append(Slider(slider_x, 100, 200, "SFX Pitch", self.controller.sfx_pitch, self.set_sfx_pitch))

        self.elements.append(Slider(slider_x, 180, 200, "Music Vol", self.controller.music_volume, self.set_music_volume))
        # BeepBox supports pitch in both desktop and web builds, independent
        # of whether native SoLoud happens to power other audio formats.
        self.elements.append(Slider(slider_x, 240, 200, "Music Pitch", self.controller.music_pitch, self.set_music_pitch))

        # --- 5. Reset Audio Button ---
        reset_y = 300
        self.elements.append(Button(slider_x, reset_y, "medium", "red", "Reset to Default", self.reset_audio_defaults))

        # Pinned songs are independent of active albums and shuffle exclusions.
        for label_y, draw_method, set_text, set_action, clear_text, clear_action, selected in (
                (MUSIC_STARTING_SONG_Y, "draw_starting_song_label", "Set as Starting Song",
                 self.set_starting_song, "Clear Starting Song", self.reset_starting_song,
                 self.controller.starting_song),
                (MUSIC_TACTICAL_SONG_Y, "draw_tactical_song_label", "Set Tactical Song",
                 self.set_tactical_song, "Clear Tactical Song", self.reset_tactical_song,
                 self.controller.tactical_battle_song)):
            self.elements.append(ScreenLayer(self, draw_method))
            set_y = label_y + MUSIC_PIN_LABEL_GAP
            set_button = Button(slider_x, set_y, MUSIC_PIN_BUTTON_SIZE, "blue", set_text,
                                set_action, font_size=18)
            set_button.apply_state(enabled=bool(self.controller.now_playing)
                                   and self.controller.now_playing != "None", color="blue")
            clear_button = Button(slider_x, set_y + MUSIC_PIN_BUTTON_SIZE[1] + MUSIC_PIN_BUTTON_GAP,
                                  MUSIC_PIN_BUTTON_SIZE, "red", clear_text, clear_action, font_size=18)
            clear_button.apply_state(enabled=bool(selected), color="red")
            self.elements.extend((set_button, clear_button))

    def is_paused(self):
        music = self.controller.music
        return music is not None and music.paused

    def play_track(self, track_path=None):
        """Helper to play a track and instantly update the UI colors."""
        self.controller._frozen_time = 0.0
        if track_path:
            self.controller.play_specific_song(track_path)
        else:
            self.controller.play_random_song()
        self._last_playing_track = self.controller.now_playing
        self.refresh_ui()

    def toggle_pause(self):
        music = self.controller.music
        if music is not None:
            music.pause(not music.paused)
        self.refresh_ui()

    def scrub_music(self, val):
        music = self.controller.music
        if music is None or not self.controller.now_playing or self.controller.now_playing == "None":
            return

        length = self.get_current_track_length()
        if length <= 0: return

        # Clamp slightly to prevent End-of-File crashes
        safe_length = max(0, length - 0.5)
        target_time = val * safe_length
        was_paused = music.paused
        music.seek(source_seconds_from_timeline(
            target_time, music.speed, self.controller.music_pitch_timeline,
        ))
        self.controller._frozen_time = target_time
        # Pygame Mixer resumes a paused track when it seeks.
        if music.paused != was_paused:
            self.refresh_ui()

    def get_current_track_length(self):
        track = self.controller.now_playing
        music = self.controller.music
        if not track or track == "None" or music is None:
            return 0
        return timeline_seconds_from_source(
            music.source_length(), music.speed, self.controller.music_pitch_timeline,
        )

    def get_current_track_pos(self):
        """The playback position on the selected timeline, or the last known one."""
        music = self.controller.music
        source_position = music.source_position() if music is not None else None
        if source_position is not None:
            self.controller._frozen_time = timeline_seconds_from_source(
                source_position, music.speed, self.controller.music_pitch_timeline,
            )
        return self.controller._frozen_time

    def update(self):
        super().update()

        # Sync UI if track auto-plays/changes externally or upon first opening the menu
        current_track = self.controller.now_playing
        if self._last_playing_track != current_track:
            self._last_playing_track = current_track
            # Read the elapsed time from the backend so the scrubber does not start at 0:00.
            self.controller._frozen_time = 0.0
            self.get_current_track_pos()
            self.refresh_ui()

        # Continuously sync the scrubber visual and text with actual audio progress
        if self.progress_slider is not None:
            length = self.get_current_track_length()
            pos = self.get_current_track_pos()
            self.progress_slider.update_progress(pos, length)

    # --- AUDIO MODIFICATION HANDLERS ---
    def reset_audio_defaults(self):
        """Restore the configured starting volume, pitch, and timeline settings."""
        defaults = settings_schema.defaults()
        self.set_sfx_volume(defaults["sfx_volume"])
        self.set_music_volume(defaults["music_volume"])
        self.set_sfx_pitch(defaults["sfx_pitch"])
        self.set_music_pitch(defaults["music_pitch"])
        self.set_music_pitch_timeline(defaults["music_pitch_timeline"])
        self.refresh_ui()

    def set_sfx_volume(self, val):
        self.controller.sfx_volume = val
        ui_elements.set_sfx_volume(val)
        self.save_audio_settings()

    def set_music_volume(self, val):
        self.controller.music_volume = val
        if self.controller.music is not None:
            self.controller.music.set_volume(val)
        self.save_audio_settings()

    def set_music_pitch(self, val):
        music = self.controller.music
        if music is not None:
            # Keep the musical position while the speed changes.
            source_position = music.source_position()
            music.set_speed(0.5 + val)
            if source_position is not None:
                self.controller._frozen_time = timeline_seconds_from_source(
                    source_position, music.speed, self.controller.music_pitch_timeline,
                )
        self.controller.music_pitch = val
        self.save_audio_settings()

    def set_static_pitch_timeline(self):
        self.set_music_pitch_timeline(c.MUSIC_PITCH_TIMELINE_STATIC)

    def set_dynamic_pitch_timeline(self):
        self.set_music_pitch_timeline(c.MUSIC_PITCH_TIMELINE_DYNAMIC)

    def show_timeline_and_queue_help(self):
        """Explain pitch timeline options and random-song exclusions."""

        dialogs.show_info(
            "Music Player Help",
            "Static keeps the displayed song length and your current progress "
            "position unchanged when you adjust pitch. Higher pitch moves the "
            "progress slider faster; lower pitch moves it slower.\n\n"
            "Dynamic changes the displayed song length with the pitch. Higher "
            "pitch shortens the displayed duration and lower pitch lengthens it.\n\n"
            "The S beside a song sets whether Skip / Random Song can pick it. "
            "A green S means the song can be picked. A grey S means the song "
            "is skipped; click it again to put the song back in the random queue.",
        )

    def set_music_pitch_timeline(self, timeline_mode):
        """Choose whether the scrubber shows source or elapsed playback time."""
        if timeline_mode not in (
                c.MUSIC_PITCH_TIMELINE_STATIC, c.MUSIC_PITCH_TIMELINE_DYNAMIC):
            return
        self.controller.music_pitch_timeline = timeline_mode
        if self.controller.now_playing != "None":
            self.controller._frozen_time = self.get_current_track_pos()
        self.save_audio_settings()
        self.refresh_ui()
        
    def set_sfx_pitch(self, val):
        self.controller.sfx_pitch = val
        ui_elements.set_sfx_pitch(val)
        self.save_audio_settings()
        
    def save_audio_settings(self):
        queries.save_global_settings(self.controller)

    # --- STARTING SONG ACTIONS ---
    def set_starting_song(self):
        if self.controller.now_playing and self.controller.now_playing != "None":
            self.controller.starting_song = self.controller.now_playing
            self.controller.save_starting_song()
            self.refresh_ui()

    def reset_starting_song(self):
        self.controller.starting_song = None
        self.controller.save_starting_song()
        self.refresh_ui()

    def set_tactical_song(self):
        if self.controller.now_playing and self.controller.now_playing != "None":
            self.controller.tactical_battle_song = self.controller.now_playing
            self.controller.save_tactical_battle_song()
            self.refresh_ui()

    def reset_tactical_song(self):
        self.controller.tactical_battle_song = ""
        self.controller.save_tactical_battle_song()
        self.refresh_ui()

    # --- PLAYLIST ACTIONS ---
    def album_display_order(self):
        """Album names in screen order: ALBUM_ORDER first, then the rest A to Z."""
        pinned = [album for album in ALBUM_ORDER if album in self.controller.all_albums]
        return pinned + sorted(album for album in self.controller.all_albums if album not in pinned)

    def deletable_albums(self):
        """The albums that accept new songs: every album not in UNDELETABLE_ALBUMS."""
        return [album for album in self.album_display_order() if queries.is_deletable_album(album)]

    def start_add_song(self):
        albums = self.deletable_albums()
        if not albums:
            dialogs.show_info("Add Song", "Create an album before adding a song.")
            return
        ui_elements.play_ui_sound("click")
        pickers.open_listbox_selector(self, "Add Song", "Which album should the song go in?",
                                      albums, self.pick_song_file)

    def pick_song_file(self, album):
        pickers.open_file_browser(self, f"Select a Song for {album}", downloads_dir(),
                                  extensions=SONG_FILE_EXTENSIONS,
                                  on_result=lambda path: self.add_song(album, path))

    def add_song(self, album, path):
        if not path:
            return
        try:
            queries.add_song_to_album(path, album)
        except ValueError as error:
            dialogs.show_error("Add Song", str(error))
            return
        self.controller.load_music_data()
        self.refresh_ui()

    def start_delete_song(self, track_path):
        dialogs.ask_yes_no(
            "Delete Song", f"Delete {os.path.basename(track_path)}? This cannot be undone.",
            lambda confirmed, p=track_path: self.delete_song(p) if confirmed else None)

    def delete_song(self, track_path):
        if self.controller.now_playing.replace("\\", "/") == track_path.replace("\\", "/"):
            # The playing file stays open, which blocks deleting it.
            dialogs.show_error("Delete Song", "This song is playing. Play another song first.")
            return
        try:
            queries.delete_song(track_path)
        except ValueError as error:
            dialogs.show_error("Delete Song", str(error))
            return
        self.controller.load_music_data()
        self.refresh_ui()
        # The shorter list can leave the pane scrolled past its new end.
        if self._scroll_track < self._max_track:
            self._scroll_track = self._max_track
            self.refresh_ui()

    def start_new_album(self):
        dialogs.ask_string("New Album", "Album name:", self.create_album, allow_empty=False)

    def create_album(self, name):
        if name is None:
            return
        try:
            queries.create_album(name)
        except ValueError as error:
            dialogs.show_error("New Album", str(error))
            return
        self.controller.load_music_data()
        self.refresh_ui()

    def start_delete_album(self, album):
        dialogs.ask_yes_no(
            "Delete Album", f"Delete {album} and every file in it? This cannot be undone.",
            lambda confirmed, a=album: self.delete_album(a) if confirmed else None)

    def delete_album(self, album):
        album_prefix = f"{c.MUSIC_DIR}/{album}/"
        if self.controller.now_playing.replace("\\", "/").startswith(album_prefix):
            # The playing file stays open, which blocks deleting its folder.
            dialogs.show_error("Delete Album", f"A song from {album} is playing. Play a song from another album first.")
            return
        try:
            queries.delete_album(album)
        except ValueError as error:
            dialogs.show_error("Delete Album", str(error))
            return
        self.controller.load_music_data()
        self.refresh_ui()
        # The shorter list can leave the pane scrolled past its new end.
        if self._scroll_album < self._max_album:
            self._scroll_album = self._max_album
            self.refresh_ui()

    def toggle_album(self, album):
        if album in self.controller.active_albums:
            self.controller.active_albums.remove(album)
        else:
            self.controller.active_albums.append(album)
            
        self.controller.save_active_albums()
        self.controller.build_playlist()
        self.refresh_ui()

    def toggle_shuffle_exclusion(self, track_path):
        self.controller.toggle_shuffle_disabled_track(track_path)
        self.refresh_ui()

    # The two panes are ordinary scrollable lists, so they both go through
    # Screen.handle_list_scroll / draw_list_scrollbar with their own attrs.
    def pane_rects(self):
        return {"album": self._content_album, "track": self._content_track}

    def additional_events(self, event):
        self.route_pane_scroll(event)

    def draw_top_bar(self, surface):
        """Fixed chrome painted over the two independently scrolling panes."""
        clip = surface.get_clip()
        try:
            surface.set_clip(clip.clip(pygame.Rect(0, 0, MUSIC_LEFT_PANE_W, 120)))
            # Use the full pane's gradient so the fixed header has no color seam.
            self.draw_album_background(surface)
        finally:
            surface.set_clip(clip)
        header = pygame.Rect(MUSIC_LEFT_PANE_W, 0, MUSIC_RIGHT_PANE_X - MUSIC_LEFT_PANE_W, 200)
        ui_elements.draw_pixel_background(surface, header, MUSIC_PANEL_STYLES["header"])
        right_pane = pygame.Rect(MUSIC_RIGHT_PANE_X, 0, MUSIC_RIGHT_PANE_W, c.SCREEN_HEIGHT)
        ui_elements.draw_pixel_background(surface, right_pane, MUSIC_PANEL_STYLES["controls"])
        for divider_x in (MUSIC_LEFT_PANE_W, MUSIC_RIGHT_PANE_X):
            pygame.draw.line(surface, (100, 100, 100),
                             (divider_x, 0), (divider_x, c.SCREEN_HEIGHT), 2)

        font_title = fonts.get("heading1")
        font_norm = fonts.get("normal")
        surface.blit(font_title.render("ALBUMS", True, (255, 255, 255)), (20, 80))
        now_playing = (f"Now Playing: {os.path.basename(self.controller.now_playing)}"
                       if self.controller.now_playing != "None" else "Now Playing: Nothing")
        surface.blit(font_norm.render(now_playing, True, c.COLOR_GOLD_HIGHLIGHT),
                     (MUSIC_LEFT_PANE_W + 20, 30))

    def draw_starting_song_label(self, surface):
        """Fixed HUD label showing which track, if any, starts on boot."""
        self._draw_pinned_song_label(surface, "Starting Song", self.controller.starting_song,
                                     MUSIC_STARTING_SONG_Y, "None (Random)")

    def draw_tactical_song_label(self, surface):
        self._draw_pinned_song_label(surface, "Tactical Song", self.controller.tactical_battle_song,
                                     MUSIC_TACTICAL_SONG_Y, "None (Playlist)")

    @staticmethod
    def _draw_pinned_song_label(surface, caption, track, y, empty_label):
        font = fonts.get("normal")
        name = os.path.basename(track) if track else empty_label
        label = fit_text(f"{caption}: {name}", font, MUSIC_RIGHT_CONTROL_W)
        surface.blit(font.render(label, True, c.COLOR_GOLD_HIGHLIGHT),
                     (MUSIC_RIGHT_CONTROL_X, y))

    def draw_elements(self, surface):
        """Two independent scrolling panes, each cropped to its own rect."""
        self.draw_panes(surface, foregrounds={"track": self.draw_track_dividers})

    def draw_track_dividers(self, surface):
        """Draw cached dividers inside the song pane's clip region."""
        for divider, rect in self._track_dividers:
            surface.blit(divider, rect)

    def draw_album_background(self, surface):
        left_pane = pygame.Rect(0, 0, MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT)
        ui_elements.draw_pixel_background(surface, left_pane, MUSIC_PANEL_STYLES["albums"])

    def additional_draw(self, surface):
        # Left pane background, drawn underneath the album buttons.
        self.draw_album_background(surface)

        # --- DYNAMIC SCROLLBAR RENDERING ---
        self.draw_pane_scrollbar(surface, "album", MUSIC_LEFT_PANE_W - MUSIC_SCROLLBAR_WIDTH - 5, 120,
                                 c.SCREEN_HEIGHT - 120, width=MUSIC_SCROLLBAR_WIDTH)
        self.draw_pane_scrollbar(surface, "track", MUSIC_RIGHT_PANE_X - MUSIC_SCROLLBAR_WIDTH - 5, 200,
                                 c.SCREEN_HEIGHT - 200, width=MUSIC_SCROLLBAR_WIDTH)
