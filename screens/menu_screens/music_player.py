import pygame
import os
from data import queries
import ui_elements 
from gameState import GameState
from ui.bars import ui_bars
from ui.scroll_panes import ScrollPanes
from ui_elements import Button, Slider, make_back_button
from map_logic.rendering.font_manager import fonts
import data.constants as c

# ==========================================
# LAYOUT
# ==========================================

MUSIC_LEFT_PANE_W = 250
song_y = 32

# ==========================================
# PYGAME MIXER PAUSE BUG PATCH
# Pygame 2+ returns False for get_busy() when music is paused.
# This makes standard game loops auto-skip to the next song. 
# We monkey-patch it here so the controller respects the pause!
# ==========================================
if not hasattr(pygame.mixer.music, '_original_get_busy'):
    pygame.mixer.music._original_get_busy = pygame.mixer.music.get_busy
    
    # 1. Initialize the attribute immediately so it always exists
    pygame.mixer.music._custom_is_paused = False 
    
    def _patched_get_busy():
        # 2. Use getattr() with a default fallback to be completely bulletproof
        if getattr(pygame.mixer.music, '_custom_is_paused', False):
            return True
        return pygame.mixer.music._original_get_busy()
        
    pygame.mixer.music.get_busy = _patched_get_busy


class TopBarOverlay:
    """A custom UI element injected to act as a solid header, clipping scrolled items."""
    def __init__(self, controller):
        self.controller = controller
        self.visible = True
        
    def handle_event(self, event): 
        pass
        
    def draw(self, surface):
        # Draw solid backgrounds over the scrolling area
        pygame.draw.rect(surface, (35, 35, 45), (0, 0, MUSIC_LEFT_PANE_W, 120))
        pygame.draw.rect(surface, (25, 25, 30), (MUSIC_LEFT_PANE_W, 0, c.SCREEN_WIDTH - MUSIC_LEFT_PANE_W, 200)) # Height for scrubber
        
        # Re-draw the divider line over the header
        pygame.draw.line(surface, (100, 100, 100), (MUSIC_LEFT_PANE_W, 0), (MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)
        
        font_title = fonts.get("heading1")
        font_norm = fonts.get("normal")
        surface.blit(font_title.render("ALBUMS", True, (255, 255, 255)), (20, 80))
        
        np_text = f"Now Playing: {os.path.basename(self.controller.now_playing)}" if self.controller.now_playing != "None" else "Now Playing: Nothing"
        surface.blit(font_norm.render(np_text, True, c.COLOR_GOLD_HIGHLIGHT), (MUSIC_LEFT_PANE_W + 20, 30))


class StartingSongOverlay:
    """Fixed HUD label showing which track (if any) is pinned to play on boot."""
    def __init__(self, controller):
        self.controller = controller
        self.visible = True

    def handle_event(self, event):
        pass

    def draw(self, surface):
        font = fonts.get("normal")
        name = os.path.basename(self.controller.starting_song) if self.controller.starting_song else "None (Random)"
        text = f"Starting Song: {name}"
        surface.blit(font.render(text, True, c.COLOR_GOLD_HIGHLIGHT), (c.SCREEN_WIDTH - 250, c.SCREEN_HEIGHT - 150))


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
        
        # Draw track background
        pygame.draw.rect(surface, (50, 50, 60), self.rect, border_radius=5)
        
        # Draw filled progress
        fill_width = int(self.value * self.rect.width)
        if fill_width > 0:
            fill_rect = pygame.Rect(self.rect.x, self.rect.y, fill_width, self.rect.height)
            pygame.draw.rect(surface, (255, 150, 50), fill_rect, border_radius=5)
            
        # Draw draggable handle
        handle_x = self.rect.x + fill_width
        handle_rect = pygame.Rect(handle_x - 5, self.rect.y - 5, 10, self.rect.height + 10)
        pygame.draw.rect(surface, (200, 200, 200), handle_rect, border_radius=3)
        
        # Draw outline
        pygame.draw.rect(surface, (100, 100, 100), self.rect, 2, border_radius=5)


class Music_Player(ScrollPanes, GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.back_state = "MENU"
        
        # Track auto-plays so UI syncs when a song naturally ends.
        # FIX: Explicitly set to None on boot so the UI forcefully syncs 
        # to the audio engine the very first time the menu is opened.
        self._last_playing_track = None
        self._awaiting_seek_confirm = False
        
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
        
        # Scrubbing state
        self._track_lengths = {}
        
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []

        self._content_album = pygame.Rect(0, 120, MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT - 120)
        self._content_track = pygame.Rect(MUSIC_LEFT_PANE_W, 200, c.SCREEN_WIDTH - MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT - 200)

        # --- 1. Left Column: Albums (Scrolling) ---
        y_offset = 120 + self._scroll_album
        album_content_h = 0
        
        for album in sorted(self.controller.all_albums.keys()):
            is_active = album in self.controller.active_albums
            color = "green" if is_active else "grey"
            
            # --- IMPROVED COVER ART SEARCH ---
            album_dir = os.path.join(c.MUSIC_DIR, album)
            icon_img = None
            
            if os.path.exists(album_dir):
                # Search the album folder for ANY valid image file to use as the cover art
                for file in os.listdir(album_dir):
                    if file.lower().endswith(('.png', '.jpg', '.jpeg')):
                        try:
                            icon_path = os.path.join(album_dir, file)
                            raw_img = pygame.image.load(icon_path).convert_alpha()
                            icon_img = pygame.transform.smoothscale(raw_img, (180, 160))
                            break # Found an image, stop searching
                        except Exception as e:
                            print(f"Error loading icon {file} for {album}: {e}")
            
            # Only registers a click (sound included) when below the clipping header!
            album_cb = lambda a=album: self.toggle_album(a)
            album_guard = lambda: pygame.mouse.get_pos()[1] >= 120

            if icon_img:
                btn = Button(20, y_offset, "album_square", color, album,
                             album_cb, image=icon_img, show_text=True, layout="vertical")
                y_offset += 210 # 200 height + 10 padding
                album_content_h += 210
            else:
                btn = Button(20, y_offset, "medium", color, album, album_cb)
                y_offset += 60
                album_content_h += 60
            btn.click_guard = album_guard
            btn.pane = "album"
            self.elements.append(btn)

        # Calculate max boundary for Album scrolling
        self._max_album = min(0, c.SCREEN_HEIGHT - 120 - album_content_h - 20)

        # --- 2. Right Column: Tracks (Scrolling) ---
        track_y = 200 + self._scroll_track # Adjusted to start below new scrubber
        track_content_h = 0
        
        for track_path in self.controller.playlist:
            track_name = os.path.basename(track_path)
            is_playing = (self.controller.now_playing == track_path)
            color = "orange" if is_playing else "grey"
            
            # Only registers a click (sound included) when below the clipping header!
            track_cb = lambda p=track_path: self.play_track(p)

            track_btn = Button(MUSIC_LEFT_PANE_W + 20, track_y, "song", color, track_name, track_cb)
            track_btn.click_guard = lambda: pygame.mouse.get_pos()[1] >= 200
            track_btn.pane = "track"
            self.elements.append(track_btn)
            track_y += song_y
            track_content_h += song_y

        # Calculate max boundary for Track scrolling
        self._max_track = min(0, c.SCREEN_HEIGHT - 200 - track_content_h - 20)

        # --- 3. Top Layer: Fixed Overlay & Buttons ---
        self.elements.append(TopBarOverlay(self.controller))
        
        self.elements.append(make_back_button(self.handle_back_key))
        # Anchored relative to the UI so it never scrolls away!
        self.elements.append(Button(MUSIC_LEFT_PANE_W + 20, 80, "medium", "green", "Skip / Random Song", self.play_track))
        
        # Add Pause Button
        pause_text = "Play" if getattr(self.controller, 'is_paused', False) else "Pause"
        self.elements.append(Button(MUSIC_LEFT_PANE_W + 240, 80, "medium", "orange", pause_text, self.toggle_pause))
        
        # Add Progress Slider (Custom MusicScrubber)
        self.progress_slider = MusicScrubber(MUSIC_LEFT_PANE_W + 20, 155, 400, 15, self.scrub_music)
        self.elements.append(self.progress_slider)
        
        # --- 4. Top Layer: Audio Sliders ---
        slider_x = c.SCREEN_WIDTH - 250
        
        self.elements.append(Slider(slider_x, 40, 200, "SFX Vol", self.controller.sfx_volume, self.set_sfx_volume))
        if c.USE_SOLOUD:
            self.elements.append(Slider(slider_x, 100, 200, "SFX Pitch", self.controller.sfx_pitch, self.set_sfx_pitch))

        self.elements.append(Slider(slider_x, 180, 200, "Music Vol", self.controller.music_volume, self.set_music_volume))
        if c.USE_SOLOUD:
            self.elements.append(Slider(slider_x, 240, 200, "Music Pitch", self.controller.music_pitch, self.set_music_pitch))

        # --- 5. Reset Audio Button ---
        reset_y = 300 if c.USE_SOLOUD else 240
        self.elements.append(Button(slider_x, reset_y, "medium", "red", "Reset to Default", self.reset_audio_defaults))

        # --- 6. Starting Song Selector (Bottom Right) ---
        # Pins whichever track is currently playing so it always opens the
        # game, independent of which albums happen to be toggled active.
        self.elements.append(StartingSongOverlay(self.controller))

        set_start_btn = Button(slider_x, c.SCREEN_HEIGHT - 130, "medium", "blue",
                                "Set as Starting Song", self.set_starting_song)
        set_start_btn.disabled = (self.controller.now_playing == "None")
        self.elements.append(set_start_btn)

        reset_start_btn = Button(slider_x, c.SCREEN_HEIGHT - 70, "medium", "red",
                                  "Reset Starting Song", self.reset_starting_song)
        reset_start_btn.disabled = not self.controller.starting_song
        self.elements.append(reset_start_btn)

    def play_track(self, track_path=None):
        """Helper to play a track and instantly update the UI colors."""
        self.controller._playback_offset = 0.0
        self.controller._scrub_base_pos = 0.0
        self.controller._frozen_time = 0.0
        self._last_ticks = pygame.time.get_ticks() # Setup pure wall-clock for SoLoud
        pygame.mixer.music._custom_is_paused = False
        
        if track_path:
            self.controller.play_specific_song(track_path)
        else:
            self.controller.play_random_song()
            
        self._last_playing_track = self.controller.now_playing
        
        self.controller.is_paused = False
        self._awaiting_seek_confirm = True # Restored for Pygame compatibility
        self.refresh_ui()

    def toggle_pause(self):
        if not hasattr(self.controller, 'is_paused'):
            self.controller.is_paused = False
            
        self.controller.is_paused = not self.controller.is_paused
        
        if c.USE_SOLOUD:
            if self.controller.music_handle is not None:
                self.controller.soloud.set_pause(self.controller.music_handle, self.controller.is_paused)
        else:
            if self.controller.is_paused:
                pygame.mixer.music._custom_is_paused = True
                pygame.mixer.music.pause()
            else:
                pygame.mixer.music._custom_is_paused = False
                pygame.mixer.music.unpause()
        
        self.refresh_ui()

    def scrub_music(self, val):
        if not self.controller.now_playing or self.controller.now_playing == "None":
            return
            
        length = self.get_current_track_length()
        if length <= 0: return
        
        # Clamp slightly to prevent End-of-File crashes
        safe_length = max(0, length - 0.5)
        target_time = val * safe_length
        
        if c.USE_SOLOUD:
            if self.controller.music_handle is not None:
                was_paused = getattr(self.controller, 'is_paused', False)
                
                # WORKAROUND: This SoLoud DLL's seek() has a bug where it
                # resets mStreamPosition to 0 before the skip loop, so after
                # seeking, mStreamPosition = skip_distance (not absolute target).
                # On repeated seeks the audio decoder overshoots the intended
                # position, eventually running past the end of the stream.
                #
                # Fix: stop → reload → play paused → seek from 0 → unpause.
                # When seeking from position 0, skip_distance == target, so
                # mStreamPosition ends up correct.
                self.controller.soloud.stop(self.controller.music_handle)
                self.controller._load_soloud_stream_unicode_safe(self.controller.now_playing)
                self.controller.music_handle = self.controller.soloud.play(
                    self.controller.music_stream, aPaused=1
                )
                
                # Reapply volume to the new handle
                self.controller.soloud.set_volume(
                    self.controller.music_handle, self.controller.music_volume
                )
                
                # Seek from position 0 BEFORE setting speed — the seek skip
                # loop internally uses getAudio() which consumes samples at
                # the current play speed. At 1.5x it would overshoot; at
                # 0.75x it would undershoot. Seeking at default 1.0x is exact.
                self.controller.soloud.seek(self.controller.music_handle, target_time)
                
                # NOW apply pitch/speed after the seek is complete
                speed_mult = 0.5 + self.controller.music_pitch
                self.controller.soloud.set_relative_play_speed(
                    self.controller.music_handle, speed_mult
                )
                
                # Unpause (unless the user had the music paused)
                if not was_paused:
                    self.controller.soloud.set_pause(self.controller.music_handle, False)
                
                self.controller._frozen_time = target_time
                self._last_ticks = pygame.time.get_ticks()
            # DEBUG: Show what SoLoud reports right after seeking
            try:
                pos_after = self.controller.soloud.get_stream_position(self.controller.music_handle)
                print(f"[SCRUB DEBUG] val={val:.3f}, length={length:.2f}, target={target_time:.2f}, soloud_pos_after_seek={pos_after:.2f}")
            except Exception as e:
                print(f"[SCRUB DEBUG] get_stream_position failed: {e}")
        else:
            # Original Pygame logic restored
            if pygame.mixer.music._custom_is_paused:
                pygame.mixer.music._custom_is_paused = False
                self.controller.is_paused = False
                pygame.mixer.music.unpause()
                self.refresh_ui()
                
            try:
                pygame.mixer.music.set_pos(target_time)
            except pygame.error:
                try:
                    pygame.mixer.music.play(start=target_time)
                except Exception as e:
                    print(f"Cannot scrub format: {e}")
                    
            self.controller._playback_offset = target_time
            self.controller._frozen_time = target_time
            self._awaiting_seek_confirm = True

    def get_current_track_length(self):
        track = self.controller.now_playing
        if not track or track == "None": return 0
        
        if track not in self._track_lengths:
            length = 0
            # Use SoLoud's own length when available — pygame.mixer.Sound
            # can report a different duration for compressed formats (MP3/OGG),
            # which causes the scrubber to seek past SoLoud's actual stream end.
            if c.USE_SOLOUD and hasattr(self.controller, 'music_stream'):
                try:
                    length = self.controller.music_stream.get_length()
                except Exception:
                    pass
            
            # Fallback to pygame if SoLoud length is unavailable or zero
            if length <= 0:
                try:
                    sound = pygame.mixer.Sound(track)
                    length = sound.get_length()
                except Exception:
                    pass
            
            self._track_lengths[track] = length
                
        return self._track_lengths[track]

    def get_current_track_pos(self):
        # ----------------------------------------------------
        # PYGAME: Uses original offset logic
        # ----------------------------------------------------
        if not c.USE_SOLOUD:
            if self._awaiting_seek_confirm:
                return self.controller._frozen_time
                
            if pygame.mixer.music._custom_is_paused:
                return self.controller._frozen_time
                
            raw_pos = pygame.mixer.music.get_pos() / 1000.0
            if raw_pos < 0: raw_pos = 0.0
            offset = self.controller._playback_offset
            base_pos = self.controller._scrub_base_pos
            
            current = offset + (raw_pos - base_pos)
            self.controller._frozen_time = current
            return current

        # ----------------------------------------------------
        # SOLOUD: Query backend directly; wall-clock fallback
        # ----------------------------------------------------
        else:
            if self.controller.is_paused or self.controller.music_handle is None:
                self._last_ticks = pygame.time.get_ticks() # Prevent jumping when unpaused
                return self.controller._frozen_time

            # If the scrubber is being dragged, freeze — don't advance position
            if hasattr(self, 'progress_slider') and self.progress_slider.is_dragging:
                self._last_ticks = pygame.time.get_ticks()
                return self.controller._frozen_time

            # PRIMARY: Query SoLoud directly for the actual stream position.
            # The wall-clock integrator drifts after seeks because SoLoud's
            # internal position and our accumulated delta diverge.
            try:
                if hasattr(self.controller.soloud, 'get_stream_position'):
                    current = self.controller.soloud.get_stream_position(self.controller.music_handle)
                    self.controller._frozen_time = current
                    self._last_ticks = pygame.time.get_ticks()
                    return current
            except Exception:
                pass
            
            # NOTE: Intentionally NOT using get_stream_time as a fallback.
            # get_stream_time returns total elapsed play-time (a monotonic clock),
            # NOT the actual position in the stream. After seeks it keeps counting
            # from where it left off, which causes the slider to show wrong values.

            # FALLBACK: Wall-clock integrator (only if backend queries fail)
            current_ticks = pygame.time.get_ticks()
            wall_delta = (current_ticks - self._last_ticks) / 1000.0
            self._last_ticks = current_ticks

            if wall_delta > 0.5 or wall_delta < 0:
                wall_delta = 0.0

            speed_mult = 0.5 + self.controller.music_pitch
            
            current = self.controller._frozen_time
            current += (wall_delta * speed_mult)
            
            max_len = self.get_current_track_length()
            if max_len > 0:
                current = min(current, max_len)

            self.controller._frozen_time = current
            return current

    def update(self):
        super().update()
        
        # Sync UI if track auto-plays/changes externally or upon first opening the menu
        current_track = self.controller.now_playing
        if self._last_playing_track != current_track:
            self._last_playing_track = current_track
            
            # Retrieve actual elapsed time from backend so scrubber doesn't start at 0:00
            actual_pos = 0.0
            if c.USE_SOLOUD and self.controller.music_handle is not None:
                try:
                    if hasattr(self.controller.soloud, 'get_stream_position'):
                        actual_pos = self.controller.soloud.get_stream_position(self.controller.music_handle)
                except Exception:
                    pass
            elif not c.USE_SOLOUD:
                try:
                    actual_pos = pygame.mixer.music.get_pos() / 1000.0
                    if actual_pos < 0: actual_pos = 0.0
                except Exception:
                    pass

            self.controller._playback_offset = actual_pos
            self.controller._scrub_base_pos = actual_pos
            self.controller._frozen_time = actual_pos
            self._last_ticks = pygame.time.get_ticks()
            
            self._awaiting_seek_confirm = False # FIX: Do not await seek on natural track change
            pygame.mixer.music._custom_is_paused = False
            self.controller.is_paused = False
            self.refresh_ui()
            
        # Capture Pygame's raw stream position one frame after seeking
        if self._awaiting_seek_confirm and not c.USE_SOLOUD:
            self._awaiting_seek_confirm = False
            self.controller._scrub_base_pos = pygame.mixer.music.get_pos() / 1000.0
            
        # Continuously sync the scrubber visual and text with actual audio progress
        if hasattr(self, 'progress_slider'):
            length = self.get_current_track_length()
            pos = self.get_current_track_pos()
            self.progress_slider.update_progress(pos, length)

    # --- AUDIO MODIFICATION HANDLERS ---
    def reset_audio_defaults(self):
        """Resets sliders to 100% Volume, and 50% Pitch (1.0x multiplier)"""
        self.set_sfx_volume(1.0)
        self.set_music_volume(1.0)
        if c.USE_SOLOUD:
            self.set_sfx_pitch(0.5)
            self.set_music_pitch(0.5)
        self.refresh_ui()

    def set_sfx_volume(self, val):
        self.controller.sfx_volume = val
        ui_elements.set_sfx_volume(val)
        self.save_audio_settings()

    def set_music_volume(self, val):
        self.controller.music_volume = val
        if c.USE_SOLOUD:
            if self.controller.music_handle is not None:
                self.controller.soloud.set_volume(self.controller.music_handle, val)
        else:
            pygame.mixer.music.set_volume(val)
        self.save_audio_settings()

    def set_music_pitch(self, val):
        self.controller.music_pitch = val
        if self.controller.music_handle is not None:
            speed_mult = 0.5 + val 
            self.controller.soloud.set_relative_play_speed(self.controller.music_handle, speed_mult)
        self.save_audio_settings()
        
    def set_sfx_pitch(self, val):
        self.controller.sfx_pitch = val
        ui_elements.global_sfx_pitch = val
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

    # --- PLAYLIST ACTIONS ---
    def toggle_album(self, album):
        if album in self.controller.active_albums:
            self.controller.active_albums.remove(album)
        else:
            self.controller.active_albums.append(album)
            
        self.controller.save_active_albums()
        self.controller.build_playlist()
        self.refresh_ui()

    # The two panes are ordinary scrollable lists, so they both go through
    # GameState.handle_list_scroll / draw_list_scrollbar with their own attrs.
    def pane_rects(self):
        return {"album": self._content_album, "track": self._content_track}

    def additional_events(self, event):
        self.route_pane_scroll(event)

    def draw_elements(self, surface):
        """Two independent scrolling panes, each cropped to its own rect."""
        self.draw_panes(surface)

    def additional_draw(self, surface):
        # Left Pane Background (Drawn underneath everything)
        left_pane = pygame.Rect(0, 0, MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, (35, 35, 45), left_pane)

        # --- DYNAMIC SCROLLBAR RENDERING ---
        self.draw_pane_scrollbar(surface, "album", MUSIC_LEFT_PANE_W - 15, 120,
                                 c.SCREEN_HEIGHT - 120, width=10)
        self.draw_pane_scrollbar(surface, "track", c.SCREEN_WIDTH - 280, 200,
                                 c.SCREEN_HEIGHT - 200, width=10)

