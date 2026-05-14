import pygame
import os
from data import queries
import ui_elements 
from gameState import GameState
from ui_elements import Button, Slider, process_text_input
from map_logic.rendering.font_manager import fonts
import data.constants as c

song_y = 32

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
        pygame.draw.rect(surface, (25, 25, 30), (c.MUSIC_LEFT_PANE_W, 0, c.SCREEN_WIDTH - c.MUSIC_LEFT_PANE_W, 140))
        
        # Re-draw the divider line over the header
        pygame.draw.line(surface, (100, 100, 100), (c.MUSIC_LEFT_PANE_W, 0), (c.MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT), 2)
        
        font_title = fonts.get("heading1")
        font_norm = fonts.get("normal")
        surface.blit(font_title.render("ALBUMS", True, (255, 255, 255)), (20, 80))
        
        np_text = f"Now Playing: {os.path.basename(self.controller.now_playing)}" if self.controller.now_playing != "None" else "Now Playing: Nothing"
        surface.blit(font_norm.render(np_text, True, (255, 215, 0)), (c.MUSIC_LEFT_PANE_W + 20, 30))

class Music_Player(GameState):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (25, 25, 30)
        self.return_state = "MENU"
        
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
        track_y = 140 + self.track_scroll_y
        track_content_h = 0
        
        for track_path in self.controller.playlist:
            track_name = os.path.basename(track_path)
            is_playing = (self.controller.now_playing == track_path)
            color = "orange" if is_playing else "grey"
            
            # Conditionally fire the callback ONLY if the mouse is below the clipping header!
            track_cb = lambda p=track_path: self.play_track(p) if pygame.mouse.get_pos()[1] >= 140 else None
            
            self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, track_y, "song", color, track_name, track_cb))
            track_y += song_y
            track_content_h += song_y

        # Calculate max boundary for Track scrolling
        self.max_track_scroll = min(0, c.SCREEN_HEIGHT - 140 - track_content_h - 20)

        # --- 3. Top Layer: Fixed Overlay & Buttons ---
        self.elements.append(TopBarOverlay(self.controller))
        
        self.elements.append(Button(20, 20, "small", "red", "Back", self.handle_back_key))
        # Anchored relative to the UI so it never scrolls away!
        self.elements.append(Button(c.MUSIC_LEFT_PANE_W + 20, 80, "medium", "green", "Skip / Random Song", self.play_track))
        
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
        if track_path:
            self.controller.play_specific_song(track_path)
        else:
            self.controller.play_random_song()
        self.refresh_ui()

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
            if getattr(ui_elements, 'pygame_click_sound', None):
                ui_elements.pygame_click_sound.set_volume(val)
            if getattr(ui_elements, 'pygame_slider_sound', None):
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
            # Shifted from 0.5 + (val * 1.5) to a clean 0.5 + val mapping
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
        view_h = c.SCREEN_HEIGHT - 120
        handle_h = max(30, int(view_h * (view_h / (view_h - self.max_album_scroll))))
        rel_y = my - 120 - (handle_h / 2)
        max_y = view_h - handle_h
        ratio = max(0.0, min(1.0, rel_y / max(1, max_y)))
        self.album_scroll_y = ratio * self.max_album_scroll
        self.refresh_ui()

    def _snap_track_scroll(self, my):
        view_h = c.SCREEN_HEIGHT - 140
        handle_h = max(30, int(view_h * (view_h / (view_h - self.max_track_scroll))))
        rel_y = my - 140 - (handle_h / 2)
        max_y = view_h - handle_h
        ratio = max(0.0, min(1.0, rel_y / max(1, max_y)))
        self.track_scroll_y = ratio * self.max_track_scroll
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
            if getattr(self, 'album_dragging', False):
                self._snap_album_scroll(my)
            elif getattr(self, 'track_dragging', False):
                self._snap_track_scroll(my)

    def additional_draw(self, surface):
        # Left Pane Background (Drawn underneath everything)
        left_pane = pygame.Rect(0, 0, c.MUSIC_LEFT_PANE_W, c.SCREEN_HEIGHT)
        pygame.draw.rect(surface, (35, 35, 45), left_pane)

        # --- DYNAMIC SCROLLBAR RENDERING ---
        
        # 1. Album Scrollbar
        album_view_h = c.SCREEN_HEIGHT - 120
        if self.max_album_scroll < 0:
            track_bg = pygame.Rect(c.MUSIC_LEFT_PANE_W - 15, 120, 10, album_view_h)
            pygame.draw.rect(surface, (50, 50, 60), track_bg)
            
            ratio = self.album_scroll_y / self.max_album_scroll
            handle_h = max(30, int(album_view_h * (album_view_h / (album_view_h - self.max_album_scroll))))
            handle_y = 120 + ratio * (album_view_h - handle_h)
            
            handle_rect = pygame.Rect(c.MUSIC_LEFT_PANE_W - 15, handle_y, 10, handle_h)
            pygame.draw.rect(surface, (150, 150, 150), handle_rect, border_radius=5)
            
            self.album_track_rect = track_bg
            self.album_handle_rect = handle_rect
        else:
            self.album_track_rect = None
            self.album_handle_rect = None

        # 2. Track Scrollbar
        track_view_h = c.SCREEN_HEIGHT - 140
        if self.max_track_scroll < 0:
            track_bg = pygame.Rect(c.SCREEN_WIDTH - 280, 140, 10, track_view_h)
            pygame.draw.rect(surface, (50, 50, 60), track_bg)
            
            ratio = self.track_scroll_y / self.max_track_scroll
            handle_h = max(30, int(track_view_h * (track_view_h / (track_view_h - self.max_track_scroll))))
            handle_y = 140 + ratio * (track_view_h - handle_h)
            
            handle_rect = pygame.Rect(c.SCREEN_WIDTH - 280, handle_y, 10, handle_h)
            pygame.draw.rect(surface, (150, 150, 150), handle_rect, border_radius=5)
            
            self.track_track_rect = track_bg
            self.track_handle_rect = handle_rect
        else:
            self.track_track_rect = None
            self.track_handle_rect = None

    def handle_back_key(self):
        self.next_state = getattr(self, 'return_state', 'MENU')
        self.done = True