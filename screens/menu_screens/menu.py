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
from data import queries
from data.platform import IS_WEB
from map_logic.rendering.font_manager import fonts

def _ease_out_expo(t):
    """Fast start that eases into the resting position: 1 - 2^-10t."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return 1 - pow(2, -10 * t)

def _lerp(a, b, t):
    return a + (b - a) * t

def _load_scaled_image(path, factor):
    """Loads a PNG and scales it by `factor` with nearest-neighbour scaling,
    which keeps pixel art crisp instead of the blur smoothscale would add."""
    raw = pygame.image.load(path).convert_alpha()
    size = (int(raw.get_width() * factor), int(raw.get_height() * factor))
    return pygame.transform.scale(raw, size)

class Menu(GameState):
    # Intro animation timings, in ms. Title drops from above, sign slides in
    # from the right. Buttons/text rise straight up from below the screen;
    # BUTTON_INTRO_CASCADE_MS is spread across them by vertical position, so
    # rows nearer the top start sooner and lower rows start later, then each
    # takes BUTTON_INTRO_DURATION_MS to arrive.
    TITLE_INTRO_MS = 900
    SIGN_INTRO_MS = 900
    # Hildehrand slides in from the left, just slightly after the sign starts
    # sliding in from the right, so the two don't read as one flat block
    # arriving together.
    HILDEHRAND_INTRO_DELAY_MS = 150
    # Nearest-neighbour upscale applied to whichever character portrait is picked.
    HILDEHRAND_SCALE = 2
    BUTTON_INTRO_DURATION_MS = 500
    BUTTON_INTRO_CASCADE_MS = 650
    # How far below the screen bottom rows start from, so they're fully
    # hidden (not just off their mark) until their delay elapses.
    BUTTON_INTRO_START_MARGIN = 60

    @staticmethod
    def _stagger_by_y(target_ys, cascade_ms):
        """Maps each y position to a start delay: smaller y (higher on
        screen) gets a smaller delay, larger y gets a larger delay."""
        min_y, max_y = min(target_ys), max(target_ys)
        spread = max_y - min_y
        if spread <= 0:
            return lambda y: 0.0
        return lambda y: (y - min_y) / spread * cascade_ms

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 80) # Blue
        # GameState.draw_background falls back to a checkerboard tinted to bg_color

        try:
            raw_image = pygame.image.load("assets/images/The Sign.png").convert_alpha()
            
            # --- EDIT THIS NUMBER TO CHANGE THE SIZE ---
            # 1.0 is normal size. 0.5 is half size. 2.0 is double size.
            scale_factor = 2
            
            new_size = (int(raw_image.get_width() * scale_factor), int(raw_image.get_height() * scale_factor))
            self.sign_image = pygame.transform.scale(raw_image, new_size)
            self.sign_rect = self.sign_image.get_rect()
            self.sign_rect.right = c.SCREEN_WIDTH - 50
            self.sign_rect.centery = (c.SCREEN_HEIGHT // 2) + 25
        except Exception as e:
            print(f"Failed to load the sign image: {e}")
            self.sign_image = None
            self.sign_rect = None

        # The right ground sits directly beneath the sign's post, scaled the
        # same as the sign so the pixel art matches, and rides along with the
        # sign's slide-in as a single unit rather than animating on its own.
        try:
            raw_ground = pygame.image.load("assets/images/Right Ground.png").convert_alpha()
            ground_size = (int(raw_ground.get_width() * scale_factor), int(raw_ground.get_height() * scale_factor))
            self.right_ground_image = pygame.transform.scale(raw_ground, ground_size)
            self.right_ground_rect = self.right_ground_image.get_rect()
            self.right_ground_rect.left = 900
            self.right_ground_rect.top = 460
        except Exception as e:
            print(f"Failed to load the right ground image: {e}")
            self.right_ground_image = None
            self.right_ground_rect = None

        # The left ground is the same prop mirrored onto the left side of the
        # screen, sliding in from the left independently of the sign. Mirrored
        # off the right ground's own left-edge distance so the two sit
        # symmetrically either side of the screen's centre.
        try:
            raw_left_ground = pygame.image.load("assets/images/Left Ground.png").convert_alpha()
            left_ground_size = (int(raw_left_ground.get_width() * scale_factor),
                                int(raw_left_ground.get_height() * scale_factor))
            self.left_ground_image = pygame.transform.scale(raw_left_ground, left_ground_size)
            self.left_ground_rect = self.left_ground_image.get_rect()
            self.left_ground_rect.right = c.SCREEN_WIDTH - 900
            self.left_ground_rect.top = 460
        except Exception as e:
            print(f"Failed to load the left ground image: {e}")
            self.left_ground_image = None
            self.left_ground_rect = None

        # Hildehrand stands near the left edge of the screen, scaled the same
        # nearest-neighbour way as The Sign.png (not smoothscale) so the
        # pixel art stays crisp instead of blurring. The portrait is anchored
        # by its BOTTOM-LEFT corner rather than its center: every portrait
        # grows up-and-right from this one fixed point, so a short/narrow
        # image never looks like it's floating above the ground, and a
        # tall/wide one never sinks through the floor or gets cut off past
        # the edge of the screen.
        #
        # --- EDIT THESE TWO NUMBERS TO MOVE HILDEHRAND ---
        hildehrand_anchor_x = 25   # distance from the left edge of the screen
        hildehrand_anchor_y = (c.SCREEN_HEIGHT // 2) + 120   # the "floor" line the feet rest on
        self._hildehrand_anchor_bottomleft = (hildehrand_anchor_x, hildehrand_anchor_y)

        self.hildehrand_choice = queries.get_hildehrand_choice()
        try:
            from ui.character_select_screen import CHARACTERS_DIR

            self.hildehrand_image = _load_scaled_image(f"{CHARACTERS_DIR}/{self.hildehrand_choice}",
                                                        self.HILDEHRAND_SCALE)
        except Exception as e:
            print(f"Failed to load the Hildehrand image: {e}")
            self.hildehrand_image = None

        self._hildehrand_draw_pos = (
            self.hildehrand_image.get_rect(bottomleft=self._hildehrand_anchor_bottomleft).topleft
            if self.hildehrand_image else self._hildehrand_anchor_bottomleft
        )

        try:
            raw_title = pygame.image.load("assets/backgrounds/Title.png").convert_alpha()
            title_width = min(raw_title.get_width(), c.SCREEN_WIDTH - 80)
            title_scale = title_width / raw_title.get_width()
            title_size = (title_width, int(raw_title.get_height() * title_scale))
            self.title_image = pygame.transform.smoothscale(raw_title, title_size)
            self.title_rect = self.title_image.get_rect()
            self.title_rect.left = 20
            self.title_rect.top = 20
        except Exception as e:
            print(f"Failed to load the title image: {e}")
            self.title_image = None
            self.title_rect = None

        # Intro animation clock; title/sign/buttons/text all ease in relative
        # to this timestamp. Draw positions default to the resting spot until
        # the first update() tick moves them off-screen to start the intro.
        self.intro_start_ticks = pygame.time.get_ticks()
        self._title_draw_pos = self.title_rect.topleft if self.title_rect else (0, 0)
        self._sign_draw_pos = self.sign_rect.topleft if self.sign_rect else (0, 0)
        self._right_ground_draw_pos = self.right_ground_rect.topleft if self.right_ground_rect else (0, 0)
        self._left_ground_draw_pos = self.left_ground_rect.topleft if self.left_ground_rect else (0, 0)

        # (y offset from centre, label, color, icon, destination state) — one row
        # per centred menu entry, so adding a screen is a single line here.
        # Credits is positioned separately below, above the GitHub/Discord links.
        menu_items = [
            ("- 200", "New Game",     "green",  "new_game",   "NEW_GAME"),
            ("- 150",  "Load Game",   "yellow", "load_game",  "LOAD_GAME"),
            ("- 100", "Tournaments",  "red",    "mail",       "MULTIPLAYER_HUB"),
            ("- 50",  "Map Editor",   "orange", "map_editor", "SELECT_BASE_MAP"),
            ("+ 0", "Settings",       "grey",   "settings",   "SETTINGS"),
            ("+ 50", "Music Player",  "blue",   "music",      "MUSIC_PLAYER"),
            ("+ 100", "Translate",    "white",  "export",     "TRANSLATE"),
        ]
        self.elements = [
            Button("centered", f"centered {offset}", "menu", color, label,
                   lambda s=state: self.go_to(s), image=ui_elements.UI_ICONS.get(icon))
            for offset, label, color, icon, state in menu_items
        ]

        # Keep Credits out of the centred cascade. It shares the lower-left
        # column with the two link rows, but sits above them without changing
        # any of the other menu buttons' positions.
        credits_y = (c.MENU_BOTTOM_TEXT_START_Y + c.MENU_BOTTOM_TEXT_STEP_Y
                     - c.SIZES["credit"][1] - 10)
        self.credits_btn = Button(
            c.MENU_BOTTOM_TEXT_START_X, credits_y, "credit", "purple", "Credits",
            lambda: self.go_to("CREDITS"), image=ui_elements.UI_ICONS.get("credits"))
        self.elements.append(self.credits_btn)

        row_button_gap = 10
        self.assets_btn = Button(
            self.credits_btn.rect.right + row_button_gap, credits_y, "credit", "pink", "Assets",
            lambda: self.go_to("VIEW_ASSETS"), image=ui_elements.UI_ICONS.get("brush"))
        self.elements.append(self.assets_btn)

        mods_x = 300
        self.mods_btn = Button(
            mods_x, credits_y, "credit", "light_blue", "Mods",
            lambda: self.go_to("MODS"), image=ui_elements.UI_ICONS.get("mods"))
        self.elements.append(self.mods_btn)
        
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
                "main_rect": main_rect,
                "_intro_target_main_y": main_rect.y,
                "_intro_target_link_y": link_rect.y,
            })
            current_y += c.MENU_BOTTOM_TEXT_STEP_Y

        self.version_status = "Checking version..." if not IS_WEB else "Version check unavailable"
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

        # Small button beneath Hildehrand that opens a picker for any portrait
        # under assets/characters/, not just Hildehrand's own F/M variants.
        # Positioned off the fixed anchor point, not the image itself, so it
        # never moves when a taller or shorter portrait gets picked.
        swap_btn_width = c.SIZES["swap_hildehrand"][0]
        hildehrand_anchor_x, hildehrand_anchor_y = self._hildehrand_anchor_bottomleft
        self.swap_hildehrand_btn = Button(
            50,
            500,
            "swap_hildehrand",
            "purple",
            "Choose Portrait",
            self.open_hildehrand_picker,
            font_preset="small",
        )
        self.elements.append(self.swap_hildehrand_btn)

        # Exit lives in the top-right corner on desktop builds and uses the
        # shared modal dialog so the game is never closed accidentally by a
        # single click. Browsers cannot close their own tab, so omit this
        # control from the web build entirely.
        self.exit_btn = None
        if not IS_WEB:
            self.exit_btn = Button(
                c.SCREEN_WIDTH - 120,
                20,
                "small",
                "red",
                "Exit",
                self.confirm_exit,
                font_preset="button",
            )
            self.elements.append(self.exit_btn)

        # These two skip the rise-from-bottom cascade below and instead slide
        # in horizontally: the refresh button from the right, alongside the
        # sign, the exit button from the right in the top corner, and the
        # portrait swap button from the left, alongside Hildehrand.
        self.refresh_btn._intro_from_right = True
        if self.exit_btn:
            self.exit_btn._intro_from_right = True
        self.swap_hildehrand_btn._intro_from_left = True

        # Cascade the rise-in by vertical position: rows near the top of the
        # screen start first, rows near the bottom start last.
        all_target_ys = [btn.rect.y for btn in self.elements] + \
                         [item["_intro_target_main_y"] for item in self.bottom_texts]
        delay_for_y = self._stagger_by_y(all_target_ys, self.BUTTON_INTRO_CASCADE_MS)

        for btn in self.elements:
            btn._intro_target_y = btn.rect.y
            btn._intro_target_x = btn.rect.x
            btn._intro_delay = delay_for_y(btn.rect.y)

        for item in self.bottom_texts:
            item["_intro_delay"] = delay_for_y(item["_intro_target_main_y"])

        # The version text isn't a Button, so it rides the same right-edge
        # slide-in as the refresh button just above it, sharing its delay.
        self._version_text_intro_delay = self.refresh_btn._intro_delay
        self._version_draw_pos = (0, 0)

        # Start version check in background so it doesn't freeze the menu.
        # Skipped entirely on web: no real OS threads under Pyodide, and the
        # blocking urllib call it makes has no browser-safe path either, so
        # there's nothing useful to do here even synchronously.
        if not IS_WEB:
            threading.Thread(target=self.check_version, daemon=True).start()

    def open_hildehrand_picker(self):
        queries.open_character_picker(self, self.hildehrand_choice, self._set_hildehrand_choice)

    def confirm_exit(self):
        from ui import confirm_dialog

        confirm_dialog.ask_yes_no(
            "Exit Game",
            "Are you sure you want to exit the game?",
            self._exit_game,
            yes_label="Exit",
            no_label="Cancel",
        )

    @staticmethod
    def _exit_game(confirmed):
        if confirmed:
            # Let the main loop handle cleanup and platform-specific shutdown.
            pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _set_hildehrand_choice(self, rel_path):
        from ui.character_select_screen import CHARACTERS_DIR
        try:
            image = _load_scaled_image(f"{CHARACTERS_DIR}/{rel_path}", self.HILDEHRAND_SCALE)
        except Exception as e:
            print(f"Failed to load the Hildehrand image: {e}")
            return
        self.hildehrand_choice = rel_path
        self.hildehrand_image = image
        queries.save_cached_json("hildehrand_choice", {"variant": rel_path})

    def trigger_version_check(self):
        if IS_WEB:
            return
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

    def update(self):
        # Drives the whole intro: title drops from above, the sign slides in
        # from the right, and every button/text row rises straight up from
        # below the screen (hidden until its delay elapses), eased with
        # _ease_out_expo so each arrives fast then settles.
        elapsed = pygame.time.get_ticks() - self.intro_start_ticks

        if self.title_rect:
            t = _ease_out_expo(elapsed / self.TITLE_INTRO_MS)
            start_y = -self.title_rect.height
            self._title_draw_pos = (self.title_rect.x, int(_lerp(start_y, self.title_rect.y, t)))

        if self.sign_rect:
            t = _ease_out_expo(elapsed / self.SIGN_INTRO_MS)
            start_x = c.SCREEN_WIDTH + 40
            self._sign_draw_pos = (int(_lerp(start_x, self.sign_rect.x, t)), self.sign_rect.y)

            if self.right_ground_rect:
                self._right_ground_draw_pos = (int(_lerp(start_x, self.right_ground_rect.x, t)), self.right_ground_rect.y)

        if self.left_ground_rect:
            t = _ease_out_expo(elapsed / self.SIGN_INTRO_MS)
            start_x = -self.left_ground_rect.width - 40
            self._left_ground_draw_pos = (int(_lerp(start_x, self.left_ground_rect.x, t)), self.left_ground_rect.y)

        if getattr(self, "hildehrand_image", None):
            rest_rect = self.hildehrand_image.get_rect(bottomleft=self._hildehrand_anchor_bottomleft)
            local_elapsed = elapsed - self.HILDEHRAND_INTRO_DELAY_MS
            t = _ease_out_expo(local_elapsed / self.SIGN_INTRO_MS) if local_elapsed > 0 else 0.0
            start_x = -rest_rect.width - 40
            self._hildehrand_draw_pos = (int(_lerp(start_x, rest_rect.x, t)), rest_rect.y)

        rise_start_y = c.SCREEN_HEIGHT + self.BUTTON_INTRO_START_MARGIN
        slide_start_x_right = c.SCREEN_WIDTH + 40

        for btn in self.elements:
            local_elapsed = elapsed - btn._intro_delay
            t = _ease_out_expo(local_elapsed / self.BUTTON_INTRO_DURATION_MS) if local_elapsed > 0 else 0.0
            if getattr(btn, "_intro_from_right", False):
                btn.rect.x = int(_lerp(slide_start_x_right, btn._intro_target_x, t))
            elif getattr(btn, "_intro_from_left", False):
                slide_start_x_left = -btn.rect.width - 40
                btn.rect.x = int(_lerp(slide_start_x_left, btn._intro_target_x, t))
            else:
                btn.rect.y = int(_lerp(rise_start_y, btn._intro_target_y, t))

        version_font = fonts.get("heading2")
        v_width = version_font.size(self.version_status)[0]
        target_v_x = c.SCREEN_WIDTH - v_width - 20
        v_y = c.SCREEN_HEIGHT - version_font.get_height() - 10
        local_elapsed = elapsed - self._version_text_intro_delay
        t = _ease_out_expo(local_elapsed / self.BUTTON_INTRO_DURATION_MS) if local_elapsed > 0 else 0.0
        self._version_draw_pos = (int(_lerp(slide_start_x_right, target_v_x, t)), v_y)

        for item in self.bottom_texts:
            local_elapsed = elapsed - item["_intro_delay"]
            t = _ease_out_expo(local_elapsed / self.BUTTON_INTRO_DURATION_MS) if local_elapsed > 0 else 0.0
            item["main_rect"].y = int(_lerp(rise_start_y, item["_intro_target_main_y"], t))
            item["link_rect"].y = int(_lerp(rise_start_y, item["_intro_target_link_y"], t))

    def additional_draw(self, surface):
        if getattr(self, "title_image", None):
            surface.blit(self.title_image, self._title_draw_pos)

        if getattr(self, "right_ground_image", None):
            surface.blit(self.right_ground_image, self._right_ground_draw_pos)

        if getattr(self, "left_ground_image", None):
            surface.blit(self.left_ground_image, self._left_ground_draw_pos)

        if getattr(self, "sign_image", None):
            surface.blit(self.sign_image, self._sign_draw_pos)

        if getattr(self, "hildehrand_image", None):
            surface.blit(self.hildehrand_image, self._hildehrand_draw_pos)

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
        v_x, v_y = self._version_draw_pos
        fonts.draw_text_with_shadow(surface, self.version_status, v_x, v_y, "heading2", self.version_color)
