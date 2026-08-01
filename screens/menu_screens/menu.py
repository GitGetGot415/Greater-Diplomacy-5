import pygame
import webbrowser
import threading
import urllib.request
import urllib.error
import ssl
import ui_elements
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Menu(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue
        self.bg_image_path = c.MENU_BG_FILE 

        try:
            raw_image = pygame.image.load("assets/images/The Sign.png").convert_alpha()
            
            # --- EDIT THIS NUMBER TO CHANGE THE SIZE ---
            # 1.0 is normal size. 0.5 is half size. 2.0 is double size.
            scale_factor = 2
            
            new_size = (int(raw_image.get_width() * scale_factor), int(raw_image.get_height() * scale_factor))
            self.sign_image = pygame.transform.scale(raw_image, new_size)
        except Exception as e:
            print(f"Failed to load the sign image: {e}")
            self.sign_image = None

        # (y offset from centre, label, colour, icon, destination state) — one row
        # per menu entry, so adding a screen is a single line here.
        menu_items = [
            ("- 125", "New Game",     "green",  "new_game",   "NEW_GAME"),
            ("- 75",  "Load Game",    "yellow", "load_game",  "LOAD_GAME"),
            ("- 25",  "Tournaments",  "red",    "mail",       "MULTIPLAYER_HUB"),
            ("+ 25",  "Map Editor",   "orange", "map_editor", "SELECT_BASE_MAP"),
            ("+ 75",  "Credits",      "purple", "credits",    "CREDITS"),
            ("+ 125", "Music Player", "blue",   "music",      "MUSIC_PLAYER"),
            ("+ 175", "Settings",     "grey",   "settings",   "SETTINGS"),
            ("+ 225", "View Assets",  "pink",   "brush",      "VIEW_ASSETS"),
        ]
        self.elements = [
            Button("centered", f"centered {offset}", "menu", color, label,
                   lambda s=state: self.go_to(s), image=ui_elements.UI_ICONS.get(icon))
            for offset, label, color, icon, state in menu_items
        ]
        
        self.bottom_texts = []
        font = fonts.get("heading2")
        
        current_y = c.MENU_BOTTOM_TEXT_START_Y
        for item in c.MENU_BOTTOM_TEXTS:
            link_text = item.get("link_text", "")
            main_text = item.get("main_text", "")
            url = item.get("url")
            
            # Fetch width of the main text to correctly offset the link text to its right
            main_w = font.size(main_text)[0] if main_text else 0
            
            # Setup dedicated rectangles for click masking and isolated drawing
            main_rect = pygame.Rect(c.MENU_BOTTOM_TEXT_START_X, current_y, main_w, font.get_height())
            link_rect = pygame.Rect(c.MENU_BOTTOM_TEXT_START_X + main_w, current_y, font.size(link_text)[0] if link_text else 0, font.get_height())
            
            self.bottom_texts.append({
                "link_text": link_text,
                "main_text": main_text,
                "url": url,
                "link_rect": link_rect,
                "main_rect": main_rect
            })
            current_y += c.MENU_BOTTOM_TEXT_STEP_Y

        self.version_status = "Checking version..."
        self.version_color = (150, 150, 150) # Grey

        # Add refresh button in bottom right, above the text status
        self.refresh_btn = Button(
            c.SCREEN_WIDTH - 120,
            c.SCREEN_HEIGHT - 90,
            "small",
            "grey",
            "Refresh",
            self.trigger_version_check,
            font_preset="small"
        )
        self.elements.append(self.refresh_btn)

        # Start version check in background so it doesn't freeze the menu
        threading.Thread(target=self.check_version, daemon=True).start()

    def trigger_version_check(self):
        if self.version_status != "Checking version...":
            self.version_status = "Checking version..."
            self.version_color = (150, 150, 150)
            threading.Thread(target=self.check_version, daemon=True).start()

    def check_version(self):
        try:
            # We use the GitHub API directly instead of the raw content URL because 
            # raw.githubusercontent.com aggressively caches files for 5 minutes via Fastly CDN,
            # and ignores query parameters. The API serves the exact real-time content.
            api_url = "https://api.github.com/repos/GitGetGot415/Greater-Diplomacy-5/contents/version.txt"
            req = urllib.request.Request(
                api_url, 
                headers={
                    'User-Agent': 'Greater-Diplomacy-5-Game',
                    'Accept': 'application/vnd.github.v3.raw',
                    'Cache-Control': 'no-cache'
                }
            )
            
            # Disable SSL verification for macOS (where root certificates may not be installed in Python)
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            try:
                response = urllib.request.urlopen(req, timeout=3, context=ctx)
            except urllib.error.HTTPError as e:
                # If we hit the GitHub API rate limit (60 requests/hr for unauthenticated),
                # fallback to the raw CDN URL which might be delayed but won't crash
                if e.code == 403 or e.code == 429:
                    import time
                    bust_url = f"{c.VERSION_CHECK_URL}?t={int(time.time())}"
                    req = urllib.request.Request(bust_url, headers={'User-Agent': 'Greater-Diplomacy-5-Game'})
                    response = urllib.request.urlopen(req, timeout=3, context=ctx)
                else:
                    raise e

            fetched_version = response.read().decode('utf-8').strip()
            
            if fetched_version == c.GAME_VERSION:
                self.version_status = f"Version: {c.GAME_VERSION} (Up to date)"
                self.version_color = c.COLOR_SUCCESS_GREEN # Green
            else:
                self.version_status = f"Outdated! Latest: {fetched_version} (Current: {c.GAME_VERSION})"
                self.version_color = (255, 100, 100) # Red
        except urllib.error.URLError:
            self.version_status = f"Version: {c.GAME_VERSION} (Offline)"
            self.version_color = (255, 200, 100) # Orange
        except Exception:
            self.version_status = f"Version: {c.GAME_VERSION} (Error checking)"
            self.version_color = (255, 100, 100) # Red

    def additional_events(self, event):
        # We hook into mouse clicks here to make the hyperlinks functional
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for item in self.bottom_texts:
                if item["url"] and item["link_text"] and item["link_rect"].collidepoint(event.pos):
                    webbrowser.open(item["url"])
                    
                    # Play the UI click sound for auditory feedback
                    from data import queries
                    queries.play_click_sound()

    def additional_draw(self, surface):
        if getattr(self, "sign_image", None):
            img_rect = self.sign_image.get_rect()
            img_rect.right = c.SCREEN_WIDTH - 40
            img_rect.centery = c.SCREEN_HEIGHT // 2
            surface.blit(self.sign_image, img_rect)

        font = fonts.get("heading2")
        mouse_pos = pygame.mouse.get_pos()
        
        for item in self.bottom_texts:
            is_hovered = item["url"] and item["link_text"] and item["link_rect"].collidepoint(mouse_pos)
            link_color = c.MENU_BOTTOM_TEXT_HOVER_COLOR if is_hovered else c.MENU_BOTTOM_TEXT_LINK_COLOR
            
            # --- Draw the Main Chunk (Now on the Left) ---
            if item["main_text"]:
                fonts.draw_text_with_shadow(surface, item["main_text"], item["main_rect"].x, item["main_rect"].y, "heading2", c.MENU_BOTTOM_TEXT_COLOR)

            # --- Draw the Link Chunk (Now on the Right) ---
            if item["link_text"]:
                fonts.draw_text_with_shadow(surface, item["link_text"], item["link_rect"].x, item["link_rect"].y, "heading2", link_color)
                
                # Dynamic Underline for hovered active links
                if is_hovered:
                    pygame.draw.line(surface, link_color, (item["link_rect"].left, item["link_rect"].bottom - 2), (item["link_rect"].right, item["link_rect"].bottom - 2), 2)

        # --- Draw Version Text (Bottom Right) ---
        version_font = fonts.get("heading2")
        v_width = version_font.size(self.version_status)[0]
        v_x = c.SCREEN_WIDTH - v_width - 20
        v_y = c.SCREEN_HEIGHT - version_font.get_height() - 10
        fonts.draw_text_with_shadow(surface, self.version_status, v_x, v_y, "heading2", self.version_color)
