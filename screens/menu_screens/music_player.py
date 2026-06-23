import pygame
import os
from data import queries
import ui_elements 
from gameState import GameState
from ui_elements import Button, Slider, process_text_input
from map_logic.rendering.font_manager import fonts
import data.constants as c
from ui.bars import ui_bars

song_y = 32

# ==========================================
# PYGAME MIXER PAUSE BUG PATCH
# Pygame 2+ returns False for get_busy() when music is paused.
# This makes standard game loops auto-skip to the next song. 
# We monkey-patch it here so the controller respects the pause!
# ==========================================
if not hasattr(pygame.mixer.music, '_original_get_busy'):
    pygame.mixer.music._original_get_busy = pygame.mixer.music.get_busy
    def _patched_get_busy():
        if pygame.mixer.music._custom_is_paused:
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
        pygame.draw.rect(surface, (35, 35, 45), (0, 0, c.MUSIC_LEFT_PANE_W, 120))
        pygame.draw.rect(surface, (25, 25, 30), (c.MUSIC_LEFT_PANE_W, 0, c.SCREEN_WIDTH - c.MUSIC_LEFT_PANE_W, 200)) # Height for scrubber
        
        # Re-draw the divider line over the header
        pygame.draw.line(surface, (100, 100, 100), (c.MUSIC_LEFT_PANE_W, 0), (c.MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)
        
        font_title = fonts.get("heading1")
        font_norm = fonts.get("normal")
        surface.blit(font_title.render("ALBUMS", True, (255, 255, 255)), (20, 80))
        
        np_text = f"Now Playing: {os.path.basename(self.controller.now_playing)}" if self.controller.now_playing != "None" else "Now Playing: Nothing"
        surface.blit(font_norm.render(np_text, True, (255, 215, 0)), (c.MUSIC_LEFT_PANE_W + 20, 30))


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


class Music_Player(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.return_state = "MENU"
        
        # Track auto-plays so UI syncs when a song naturally ends.
        # FIX: Explicitly set to None on boot so the UI forcefully syncs 
        # to the audio engine the very first time the menu is opened.
        self._last_playing_track = None
        self._awaiting_seek_confirm = False
        
        # Ensure directories and files exist
        if not os.path.exists(c.MUSIC_DIR):
            os.makedirs(c.MUSIC_DIR)
        
        self.album_scroll_y = 0
        self.track_scroll_y = 0
        self.max_album_scroll = 0
        self.max_track_scroll = 0
        
        # Drag state trackers for scrollbars
        self.album_dragging = False
        self.track_dragging = False
        self.album_track_rect = None
        self.album_handle_rect = None
        self.track_track_rect = None
        self.track_handle_rect = None
        
        # Scrubbing state
        self._track_lengths = {}
        
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        
        # --- 1. Left Column: Albums (Scrolling) ---
        y_offset = 120 + self.album_scroll_y
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
            
            # Conditionally fire the callback ONLY if the mouse is below the clipping header!
            album_cb = lambda a=album: self.toggle_album(a) if pygame.mouse.get_pos()[1] >= 120 else None

            if icon_img:
                self.elements.append(Button(20, y_offset, "album_square", color, album, 
                                            album_cb, image=icon_img, show_text=True, layout="vertical"))
                y_offset += 210 # 200 height + 10 padding
                album_content_h += 210
            else:
                self.elements.append(Button(20, y_offset, "medium", color, album, album_cb))
                y_offset += 60
                album_content_h += 60

        # Calculate max boundary for Album scrolling
        self.max_album_scroll = min(0, c.SCREEN_HEIGHT - 120 - album_content_h - 20)

        # --- 2. Right Column: Tracks (Scrolling) ---
        track_y = 200 + self.track_scroll_y # Adjusted to start below new scrubber
        track_content_h = 0
        
        for track_path in self.controller.playlist:
            track_name = os.path.basename(track_path)
            is_playing = (self.controller.now_playing == track_path)
            color = "orange" if is_playing else "grey"
            
            # Conditionally fire the callback ONLY if the mouse is below the clipping header!
            track_cb = lambda p=track_path: self.play_track(p) if pygame.mouse.get_pos()[1] >= 200 else None
            
            self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "song", color, track_name, track_cb))
            track_y += song_y
            track_content_h += song_y

        # Calculate max boundary for Track scrolling
        self.max_track_scroll = min(0, c.SCREEN_HEIGHT - 200 - track_content_h - 20)

        # --- 3. Top Layer: Fixed Overlay & Buttons ---
        self.elements.append(TopBarOverlay(self.controller))
        
        self.elements.append(Button(20, 20, "small", "red", "Back", self.handle_back_key))
        # Anchored relative to the UI so it never scrolls away!
        self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, 80, "medium", "green", "Skip / Random Song", self.play_track))
        
        # Add Pause Button
        pause_text = "Play" if getattr(self.controller, 'is_paused', False) else "Pause"
        self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 240, 80, "medium", "orange", pause_text, self.toggle_pause))
        
        # Add Progress Slider (Custom MusicScrubber)
        self.progress_slider = MusicScrubber(c.MUSIC_LEFT_PANE_W + 20, 155, 400, 15, self.scrub_music)
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
                self.controller.soloud.seek(self.controller.music_handle, target_time)
                # Pure UI tracking: ignore SoLoud's internal clock completely
                self.controller._frozen_time = target_time
                self._last_ticks = pygame.time.get_ticks()
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
            try:
                sound = pygame.mixer.Sound(track)
                self._track_lengths[track] = sound.get_length()
            except Exception:
                self._track_lengths[track] = 0
                
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
        # SOLOUD: Uses Pure Wall-Clock Integrator
        # ----------------------------------------------------
        else:
            if self.controller.is_paused or self.controller.music_handle is None:
                self._last_ticks = pygame.time.get_ticks() # Prevent jumping when unpaused
                return self.controller._frozen_time

            # Measure real time passed since last frame
            current_ticks = pygame.time.get_ticks()
            wall_delta = (current_ticks - self._last_ticks) / 1000.0
            self._last_ticks = current_ticks

            # FIX: If delta is huge (e.g. user was on Map screen), sync directly with SoLoud's backend!
            if wall_delta > 0.5:
                try:
                    if hasattr(self.controller.soloud, 'get_stream_position'):
                        current = self.controller.soloud.get_stream_position(self.controller.music_handle)
                        self.controller._frozen_time = current
                        return current
                    elif hasattr(self.controller.soloud, 'get_stream_time'):
                        current = self.controller.soloud.get_stream_time(self.controller.music_handle)
                        self.controller._frozen_time = current
                        return current
                except Exception:
                    pass
                wall_delta = 0.0 # Fallback if backend query fails
            elif wall_delta < 0:
                wall_delta = 0.0

            # Scale only the pure time delta by the pitch
            speed_mult = 0.5 + self.controller.music_pitch
            
            current = self.controller._frozen_time
            current += (wall_delta * speed_mult)
            
            # Prevent the visual bar from bleeding past the end
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
                    elif hasattr(self.controller.soloud, 'get_stream_time'):
                        actual_pos = self.controller.soloud.get_stream_time(self.controller.music_handle)
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
        ui_elements.global_sfx_volume = val    
        
        if not c.USE_SOLOUD:
            if ui_elements.pygame_click_sound:
                ui_elements.pygame_click_sound.set_volume(val)
            if ui_elements.pygame_slider_sound:
                ui_elements.pygame_slider_sound.set_volume(val)
                
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

    # --- PLAYLIST ACTIONS ---
    def toggle_album(self, album):
        if album in self.controller.active_albums:
            self.controller.active_albums.remove(album)
        else:
            self.controller.active_albums.append(album)
            
        self.controller.save_active_albums()
        self.controller.build_playlist()
        self.refresh_ui()

    # --- SCROLL BAR SNAPPING HELPERS ---
    def _snap_album_scroll(self, my):
        self.album_scroll_y = ui_bars.calculate_scroll_snap(my, self.max_album_scroll, 120, c.SCREEN_HEIGHT - 120)
        self.refresh_ui()

    def _snap_track_scroll(self, my):
        self.track_scroll_y = ui_bars.calculate_scroll_snap(my, self.max_track_scroll, 200, c.SCREEN_HEIGHT - 200)
        self.refresh_ui()

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        mx, my = pygame.mouse.get_pos()
        
        # 1. Standard Mouse Wheel Scrolling
        if event.type == pygame.MOUSEWHEEL:
            if mx < c.MUSIC_LEFT_PANE_W:
                self.album_scroll_y += event.y * 40
                self.album_scroll_y = max(self.max_album_scroll, min(0, self.album_scroll_y))
            else:
                self.track_scroll_y += event.y * 40
                self.track_scroll_y = max(self.max_track_scroll, min(0, self.track_scroll_y))
            self.refresh_ui()
            
        # 2. Scrollbar Drag Start
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Album Scrollbar
            if self.album_handle_rect and self.album_handle_rect.collidepoint(mx, my):
                self.album_dragging = True
            elif self.album_track_rect and self.album_track_rect.collidepoint(mx, my):
                self.album_dragging = True
                self._snap_album_scroll(my)
                
            # Track Scrollbar
            elif self.track_handle_rect and self.track_handle_rect.collidepoint(mx, my):
                self.track_dragging = True
            elif self.track_track_rect and self.track_track_rect.collidepoint(mx, my):
                self.track_dragging = True
                self._snap_track_scroll(my)
                
        # 3. Scrollbar Drag Release
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.album_dragging = False
            self.track_dragging = False
            
        # 4. Scrollbar Drag Motion
        elif event.type == pygame.MOUSEMOTION:
            if self.album_dragging:
                self._snap_album_scroll(my)
            elif self.track_dragging:
                self._snap_track_scroll(my)

    def additional_draw(self, surface):
        # Left Pane Background (Drawn underneath everything)
        left_pane = pygame.Rect(0, 0, c.MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, (35, 35, 45), left_pane)

        # --- DYNAMIC SCROLLBAR RENDERING ---
        self.album_track_rect, self.album_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, self.album_scroll_y, self.max_album_scroll, c.MUSIC_LEFT_PANE_W - 15, 120, c.SCREEN_HEIGHT - 120, width=10
        )
        
        self.track_track_rect, self.track_handle_rect = ui_bars.draw_standard_scrollbar(
            surface, self.track_scroll_y, self.max_track_scroll, c.SCREEN_WIDTH - 280, 200, c.SCREEN_HEIGHT - 200, width=10
        )

    def handle_back_key(self):
        self.next_state = self.return_state
        self.done = True