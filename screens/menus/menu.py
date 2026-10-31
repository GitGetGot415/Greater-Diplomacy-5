import time
import math
from functools import lru_cache

import pygame
import webbrowser
import threading
import urllib.request
import urllib.error
import ssl
from ui.widgets import ui_elements
from ui.bars import ui_bars
from ui.navigation.game_state import GameState
from ui.widgets.ui_elements import Button
import data.constants as c
from data import queries
from ui.dialogs import pickers
from data.platform import IS_WEB
from ui.rendering.font_manager import fonts

from ui.dialogs.character_select_screen import CHARACTERS_DIR
from ui import dialogs

MENU_WATERLINE_RATIO = 0.605
MENU_SKY_STEPPED = False  # False gives a smooth gradient. Restart after editing.
MENU_SKY_DITHERING = False
MENU_SKY_BANDS = 12
MENU_WATER_STEPPED = False
MENU_WATER_DITHERING = False
MENU_WATER_BANDS = 12

# Edit these RGB colors, then restart the game.
MENU_SKY_START_COLOR = (24, 28, 65)
MENU_SKY_END_COLOR = (220, 120, 140)

# Fade
MENU_SKY_FADE_ENABLED = True
MENU_SKY_START_FADE_COLOR = (24, 28, 65)
MENU_SKY_END_FADE_COLOR = (180, 80, 100)
MENU_SKY_FADE_CYCLE_SECONDS = 8.0  # Full cycle: original colors to targets and back.
# Options: "linear", "ease_in", "ease_out", "ease_in_out".
MENU_SKY_FADE_IN_EASING = "ease_in_out"  # Original colors to target colors.
MENU_SKY_FADE_OUT_EASING = "ease_in_out"  # Target colors back to original colors.

MENU_WATER_START_COLOR = (30, 62, 100)
MENU_WATER_END_COLOR = (10, 25, 55)
MENU_CHECKERBOARD_COLOR = (60, 30, 90)
MENU_CHECKERBOARD_OPACITY = 50  # 0 hides the overlay; 255 makes it opaque.


@lru_cache(maxsize=4)
def _menu_background(size, sky_start_color=MENU_SKY_START_COLOR, sky_end_color=MENU_SKY_END_COLOR):
    """Cache the sky and water by viewport size and current sky endpoint colors."""
    width, height = size
    background = pygame.Surface(size)
    sky_height = round(height * MENU_WATERLINE_RATIO)
    colors = (sky_start_color, sky_end_color)
    ui_elements.draw_color_gradient(
        background, pygame.Rect(0, 0, width, sky_height), colors,
        stepped=MENU_SKY_STEPPED, bands=MENU_SKY_BANDS, dithering=MENU_SKY_DITHERING)
    ui_elements.draw_color_gradient(
        background, pygame.Rect(0, sky_height, width, height - sky_height),
        (MENU_WATER_START_COLOR, MENU_WATER_END_COLOR),
        stepped=MENU_WATER_STEPPED, bands=MENU_WATER_BANDS, dithering=MENU_WATER_DITHERING)
    return background


def _menu_fade_progress(progress, easing):
    """Apply the selected speed curve to one direction of the sky fade."""
    if easing == "linear":
        return progress
    if easing == "ease_in":
        return progress * progress
    if easing == "ease_out":
        return 1.0 - (1.0 - progress) ** 2
    if easing == "ease_in_out":
        return (1.0 - math.cos(math.pi * progress)) / 2.0
    raise ValueError(
        f"Unknown sky fade easing {easing!r}. "
        "Use linear, ease_in, ease_out, or ease_in_out in MENU_SKY_FADE_IN_EASING and MENU_SKY_FADE_OUT_EASING.")


def _menu_sky_colors():
    """Fade both sky endpoints to their targets and back with the selected easing."""
    if not MENU_SKY_FADE_ENABLED:
        return MENU_SKY_START_COLOR, MENU_SKY_END_COLOR
    if MENU_SKY_FADE_CYCLE_SECONDS <= 0:
        raise ValueError("MENU_SKY_FADE_CYCLE_SECONDS must be greater than zero.")
    phase = (pygame.time.get_ticks() / (1000.0 * MENU_SKY_FADE_CYCLE_SECONDS)) % 1.0
    if phase < 0.5:
        blend = _menu_fade_progress(phase * 2.0, MENU_SKY_FADE_IN_EASING)
    else:
        blend = 1.0 - _menu_fade_progress((phase - 0.5) * 2.0, MENU_SKY_FADE_OUT_EASING)
    return (queries.lerp_color(MENU_SKY_START_COLOR, MENU_SKY_START_FADE_COLOR, blend),
            queries.lerp_color(MENU_SKY_END_COLOR, MENU_SKY_END_FADE_COLOR, blend))


@lru_cache(maxsize=1)
def _menu_checkerboard_overlay(tile, opacity):
    """Cache a transparent copy without changing the shared checkerboard tile."""
    overlay = tile.copy()
    overlay.set_alpha(opacity)
    return overlay


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
    INTRO_SLIDE_START_MARGIN = 40
    EXIT_INTRO_START_MARGIN = 2000
    GROUND_INTRO_START_MARGIN = 1600
    SIGN_INTRO_START_MARGIN = 200
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

        try:
            raw_image = pygame.image.load("assets/images/The Sign.png").convert_alpha()
            
            # --- EDIT THIS NUMBER TO CHANGE THE SIZE ---
            # 1.0 is normal size. 0.5 is half size. 2.0 is double size.
            scale_factor = 2
            
            new_size = (int(raw_image.get_width() * scale_factor), int(raw_image.get_height() * scale_factor))
            self.sign_image = pygame.transform.scale(raw_image, new_size)
            # Keep the sign attached to one fixed bottom-right point, just as
            # the portrait is attached to its bottom-left point. The values
            # preserve the sign's previous resting location while making its
            # placement independent of the asset's height.
            sign_anchor_x = c.SCREEN_WIDTH - 50
            sign_anchor_y = 480
            self._sign_anchor_bottomright = (sign_anchor_x, sign_anchor_y)
            self.sign_rect = self.sign_image.get_rect(bottomright=self._sign_anchor_bottomright)
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
        (self.hildehrand_gradient, self.hildehrand_gradient_strength,
         self.hildehrand_gradient_stepped,
         self.hildehrand_gradient_bands) = queries.get_hildehrand_gradient()
        self.hildehrand_gradient_dithering = queries.get_hildehrand_dithering()
        try:
            self._hildehrand_plain_image = _load_scaled_image(
                f"{CHARACTERS_DIR}/{self.hildehrand_choice}", self.HILDEHRAND_SCALE)
        except Exception as e:
            print(f"Failed to load the Hildehrand image: {e}")
            self._hildehrand_plain_image = None
        self._refresh_hildehrand_image()

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
        # to this timestamp. Start horizontally animated art off-screen even
        # before the first update() tick, so it cannot flash at its resting
        # position for one frame.
        self.intro_start_ticks = pygame.time.get_ticks()
        self._title_draw_pos = self.title_rect.topleft if self.title_rect else (0, 0)
        self._sign_draw_pos = (
            c.SCREEN_WIDTH + self.sign_rect.width + self.SIGN_INTRO_START_MARGIN,
            self.sign_rect.y,
        ) if self.sign_rect else (0, 0)
        self._right_ground_draw_pos = (
            c.SCREEN_WIDTH + self.GROUND_INTRO_START_MARGIN,
            self.right_ground_rect.y,
        ) if self.right_ground_rect else (0, 0)
        self._left_ground_draw_pos = (
            -self.left_ground_rect.width - self.GROUND_INTRO_START_MARGIN,
            self.left_ground_rect.y,
        ) if self.left_ground_rect else (0, 0)

        # (y offset from centre, label, color, icon, destination state) — one row
        # per centred menu entry, so adding a screen is a single line here.
        # Both menu button groups are generated from separate table settings.
        self.elements = []

        # The primary New Game action is standalone so its position, size, and
        # text size can be edited independently from the other menu buttons.
        new_game_button_size = (200, 100)
        new_game_text_size = 28
        self.new_game_btn = Button(
            460,
            220,
            new_game_button_size,
            "green",
            "New Game",
            lambda: self.go_to("NEW_GAME"),
            image=ui_elements.UI_ICONS.get("new_game"),
            font_size=new_game_text_size,
        )
        self.elements.append(self.new_game_btn)

        main_button_size = (200, 45)
        main_table_x, main_table_y = (460, 330)
        main_button_w, main_button_h = main_button_size
        main_columns = 1
        for index, button_data in enumerate(c.MENU_MAIN_BUTTON_TABLE):
            row, column = divmod(index, main_columns)
            button = Button(
                main_table_x + column * (main_button_w + 10),
                main_table_y + row * (main_button_h + 10),
                main_button_size,
                button_data["color"],
                button_data["text"],
                lambda state=button_data["state"]: self.go_to(state),
                image=ui_elements.UI_ICONS.get(button_data.get("image")),
                font_size=button_data.get("text_size"),
            )
            setattr(self, button_data["attribute"], button)
            self.elements.append(button)

        button_size = (130, 40)
        table_x, table_y = 670, 220
        button_w, button_h = button_size
        columns = 1
        for index, button_data in enumerate(c.MENU_BUTTON_TABLE):
            row, column = divmod(index, columns)
            button = Button(
                table_x + column * (button_w + 10),
                table_y + row * (button_h + 5),
                button_size,
                button_data["color"],
                button_data["text"],
                lambda state=button_data["state"]: self.go_to(state),
                image=ui_elements.UI_ICONS.get(button_data.get("image")),
                font_size=button_data.get("text_size"),
            )
            setattr(self, button_data["attribute"], button)
            self.elements.append(button)
        
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

        # Small button beneath Hildehrand that opens the portrait editor: the
        # picker for any portrait under assets/characters/ plus the gradient.
        # Positioned off a fixed spot, not the image itself, so it never moves
        # when a taller or shorter portrait gets picked.
        self.edit_portrait_btn = Button(
            50,
            500,
            "edit_portrait",
            "purple",
            "Edit Portrait",
            lambda: self.go_to("EDIT_PORTRAIT"),
            font_preset="small",
        )
        self.elements.append(self.edit_portrait_btn)

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

        # These controls skip the rise-from-bottom cascade below and instead
        # slide in horizontally: the refresh and exit buttons from the right,
        # alongside the sign and in the top corner respectively, and the
        # portrait edit button from the left, alongside Hildehrand.
        right_intro_buttons = [self.refresh_btn]
        if self.exit_btn:
            right_intro_buttons.append(self.exit_btn)
        for button in right_intro_buttons:
            button._intro_from_right = True
        if self.exit_btn:
            self.exit_btn._intro_start_margin = self.EXIT_INTRO_START_MARGIN
        self.edit_portrait_btn._intro_from_left = True

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

    def confirm_exit(self):

        dialogs.ask_yes_no(
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

    def set_hildehrand_choice(self, rel_path):
        try:
            image = _load_scaled_image(f"{CHARACTERS_DIR}/{rel_path}", self.HILDEHRAND_SCALE)
        except Exception as e:
            print(f"Failed to load the Hildehrand image: {e}")
            return
        self.hildehrand_choice = rel_path
        self._hildehrand_plain_image = image
        self._refresh_hildehrand_image()
        self.save_hildehrand_settings()

    def toggle_hildehrand_gradient(self):
        self.hildehrand_gradient = not self.hildehrand_gradient
        self._refresh_hildehrand_image()
        self.save_hildehrand_settings()

    def toggle_hildehrand_gradient_stepped(self):
        self.hildehrand_gradient_stepped = not self.hildehrand_gradient_stepped
        self._refresh_hildehrand_image()
        self.save_hildehrand_settings()

    def toggle_hildehrand_gradient_dithering(self):
        if not (self.hildehrand_gradient and self.hildehrand_gradient_stepped):
            return
        self.hildehrand_gradient_dithering = not self.hildehrand_gradient_dithering
        self._refresh_hildehrand_image()
        self.save_hildehrand_settings()

    def set_hildehrand_gradient_bands(self, bands):
        """Live slider update. The caller saves once the drag ends."""
        self.hildehrand_gradient_bands = bands
        self._refresh_hildehrand_image()

    def set_hildehrand_gradient_strength(self, strength):
        """Live slider update. The caller saves once the drag ends."""
        self.hildehrand_gradient_strength = strength
        self._refresh_hildehrand_image()

    def save_hildehrand_settings(self):
        queries.save_hildehrand_portrait(self.hildehrand_choice, self.hildehrand_gradient,
                                         self.hildehrand_gradient_strength,
                                         self.hildehrand_gradient_stepped,
                                         self.hildehrand_gradient_bands,
                                         gradient_dithering=self.hildehrand_gradient_dithering)

    def _refresh_hildehrand_image(self):
        """Builds the drawn portrait from the plain one, shaded when the gradient is on.
        The anchor is the bottom-left corner, so the image size never moves the feet."""
        plain = self._hildehrand_plain_image
        if plain and self.hildehrand_gradient:
            self.hildehrand_image = ui_elements.apply_button_gradient(
                plain, self.hildehrand_gradient_strength, self.hildehrand_gradient_stepped,
                self.hildehrand_gradient_bands, dithering=self.hildehrand_gradient_dithering)
        else:
            self.hildehrand_image = plain

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

            # FORCE TEXT:
            # self.version_status = "Version: v30 (Up to date)"
            # self.version_color = c.COLOR_SUCCESS_GREEN
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
                    pickers.play_click_sound()

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
            start_x = c.SCREEN_WIDTH + self.sign_rect.width + self.SIGN_INTRO_START_MARGIN
            self._sign_draw_pos = (int(_lerp(start_x, self.sign_rect.x, t)), self.sign_rect.y)

            if self.right_ground_rect:
                ground_start_x = c.SCREEN_WIDTH + self.GROUND_INTRO_START_MARGIN
                self._right_ground_draw_pos = (int(_lerp(ground_start_x, self.right_ground_rect.x, t)), self.right_ground_rect.y)

        if self.left_ground_rect:
            t = _ease_out_expo(elapsed / self.SIGN_INTRO_MS)
            ground_start_x = -self.left_ground_rect.width - self.GROUND_INTRO_START_MARGIN
            self._left_ground_draw_pos = (int(_lerp(ground_start_x, self.left_ground_rect.x, t)), self.left_ground_rect.y)

        if self.hildehrand_image:
            rest_rect = self.hildehrand_image.get_rect(bottomleft=self._hildehrand_anchor_bottomleft)
            local_elapsed = elapsed - self.HILDEHRAND_INTRO_DELAY_MS
            t = _ease_out_expo(local_elapsed / self.SIGN_INTRO_MS) if local_elapsed > 0 else 0.0
            start_x = -rest_rect.width - self.INTRO_SLIDE_START_MARGIN
            self._hildehrand_draw_pos = (int(_lerp(start_x, rest_rect.x, t)), rest_rect.y)

        rise_start_y = c.SCREEN_HEIGHT + self.BUTTON_INTRO_START_MARGIN
        slide_start_x_right = c.SCREEN_WIDTH + self.INTRO_SLIDE_START_MARGIN

        for btn in self.elements:
            local_elapsed = elapsed - btn._intro_delay
            t = _ease_out_expo(local_elapsed / self.BUTTON_INTRO_DURATION_MS) if local_elapsed > 0 else 0.0
            if getattr(btn, "_intro_from_right", False):
                start_margin = getattr(btn, "_intro_start_margin", self.INTRO_SLIDE_START_MARGIN)
                btn.rect.x = int(_lerp(c.SCREEN_WIDTH + start_margin, btn._intro_target_x, t))
            elif getattr(btn, "_intro_from_left", False):
                slide_start_x_left = -btn.rect.width - self.INTRO_SLIDE_START_MARGIN
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

    def draw_background(self, surface):
        sky_start, sky_end = _menu_sky_colors()
        surface.blit(_menu_background(surface.get_size(), sky_start, sky_end), (0, 0))
        if MENU_CHECKERBOARD_OPACITY > 0:
            tile = ui_bars.get_checkerboard_tile(MENU_CHECKERBOARD_COLOR)
            overlay = _menu_checkerboard_overlay(tile, MENU_CHECKERBOARD_OPACITY)
            sky_rect = pygame.Rect(0, 0, surface.get_width(),
                                   round(surface.get_height() * MENU_WATERLINE_RATIO))
            old_clip = surface.get_clip()
            surface.set_clip(old_clip.clip(sky_rect))
            try:
                self.draw_checkerboard_background(surface, MENU_CHECKERBOARD_COLOR, tile=overlay)
            finally:
                surface.set_clip(old_clip)

    def additional_draw(self, surface):
        if self.title_image:
            surface.blit(self.title_image, self._title_draw_pos)

        if self.right_ground_image:
            surface.blit(self.right_ground_image, self._right_ground_draw_pos)

        if self.left_ground_image:
            surface.blit(self.left_ground_image, self._left_ground_draw_pos)

        if self.sign_image:
            surface.blit(self.sign_image, self._sign_draw_pos)

        if self.hildehrand_image:
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
