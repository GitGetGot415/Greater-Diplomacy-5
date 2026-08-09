import pygame
try:
    # Not available in pygame-ce's WASM build; clipboard calls elsewhere already
    # guard against pygame.scrap being missing with their own try/except.
    import pygame.scrap
except Exception:
    pass
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import symbol_loader

soloud_engine = None
click_sound = None
slider_sound = None
pygame_click_sound = None
pygame_slider_sound = None
global_sfx_volume = 0.5
global_sfx_pitch = 0.5

UI_ICONS = {}

def parse_pos(val, limit, size):
    if isinstance(val, str):
        if "centered" in val:
            base = (limit / 2) - (size / 2)
            if "+" in val:
                return base + int(val.split("+")[-1])
            if "-" in val:
                return base - int(val.split("-")[-1])
            return base
    return val

def play_ui_sound(kind="click"):
    """Plays a UI sfx through whichever audio backend is active.

    Single entry point for every click/slider blip in the game, so the SoLoud
    vs. pygame.mixer branch and the volume/pitch maths live in exactly one place.
    """
    if global_sfx_volume <= 0:
        return

    if c.USE_SOLOUD:
        sound = click_sound if kind == "click" else slider_sound
        if sound and soloud_engine:
            handle = soloud_engine.play(sound)
            soloud_engine.set_volume(handle, global_sfx_volume)
            # Centres the speed variance directly on a 0.5 pitch input
            soloud_engine.set_relative_play_speed(handle, 0.5 + global_sfx_pitch)
    else:
        sound = pygame_click_sound if kind == "click" else pygame_slider_sound
        if sound:
            sound.set_volume(global_sfx_volume)
            sound.play()

def set_sfx_volume(val):
    """Applies a new sfx volume to the shared state and both audio backends."""
    global global_sfx_volume
    global_sfx_volume = val
    if not c.USE_SOLOUD:
        for sound in (pygame_click_sound, pygame_slider_sound):
            if sound:
                sound.set_volume(val)

def scale_icon(icon_name, size):
    """Fetches a symbol and scales it to a square of `size`, or None if missing."""
    icon_surf = symbol_loader.SYMBOLS.get(icon_name)
    if not icon_surf:
        return None
    return pygame.transform.smoothscale(icon_surf, (size, size))

def draw_notification_badge(surface, rect, text, color=None):
    """Draws the small red circle + text badge used to flag a button (unread
    counts, "you have a free research slot", "this scenario setting isn't at
    its default", ...). Single shared implementation so every badge in the
    game looks and behaves the same.
    """
    color = color or c.MSG_NOTIFICATION_COLOR
    bx, by = rect.right - 10, rect.top + 10
    radius = max(12, 9 + 3 * (len(text) - 1))
    pygame.draw.circle(surface, color, (bx, by), radius)
    pygame.draw.circle(surface, (255, 255, 255), (bx, by), radius, 1)

    font = fonts.get("tiny")
    txt_surf = font.render(text, True, (255, 255, 255))
    surface.blit(txt_surf, txt_surf.get_rect(center=(bx, by)))

class Button:
    # UPDATED: Added font_preset parameter defaulting to "button"
    def __init__(self, x, y, size_preset, color_preset, text, callback, image=None, show_text=True, layout="horizontal", font_preset="button"):
        self.width, self.height = c.SIZES.get(size_preset, (200, 50))
        final_x = parse_pos(x, c.SCREEN_WIDTH, self.width)
        final_y = parse_pos(y, c.SCREEN_HEIGHT, self.height)
        self.rect = pygame.Rect(final_x, final_y, self.width, self.height)

        self.set_palette(color_preset)

        self.text = text
        self.callback = callback
        self.image = image 
        self.show_text = show_text
        self.layout = layout

        # Pull the requested font preset from the FontManager
        self.font = fonts.get(font_preset)

        self.visible = True
        self.is_pressed = False

        self.is_selected = False
        self.disabled = False
        self.text_align = "center"
        self.notification_count = 0
        # Overrides notification_count's digit text with an arbitrary string
        # (e.g. "!"). Same badge, just not a count.
        self.notification_text = None

        # Optional callable: when set, a click only registers (sound + callback)
        # if it returns True. Lets a button stay visible/clickable-looking while
        # scrolled behind a fixed overlay without the click sfx sneaking through.
        self.click_guard = None

    # ------------------------------------------------------------------ #
    #                         APPEARANCE HELPERS                         #
    # ------------------------------------------------------------------ #

    def set_palette(self, color_preset):
        """Recolours the button from a c.UI_COLORS preset name.

        Always the way to change a button's colour: it keeps base, hover and
        pressed shades in step, which hand-assigning `.color`/`.hover_color`
        at the call site did not.
        """
        base, hover = c.UI_COLORS.get(color_preset, c.UI_COLORS["grey"])
        self.set_colors(base, hover)

    def set_colors(self, base, hover=None):
        """Recolours the button from raw RGB values (palette swatches, etc.)."""
        self.color = base
        self.hover_color = base if hover is None else hover
        self.pressed_color = tuple(max(0, ch - 40) for ch in base[:3])

    def apply_state(self, visible=None, enabled=None, text=None, color=None):
        """Updates the per-frame dynamic bits of a button in one call.

        Passing `enabled=False` greys the button out, which is why colour and
        enabled-ness are set together rather than by separate assignments.
        """
        if visible is not None:
            self.visible = visible
        if text is not None:
            self.text = text
        if enabled is not None:
            self.disabled = not enabled
        if color is not None or enabled is not None:
            self.set_palette("grey" if self.disabled else (color or "green"))

    def draw_label(self, surface, text, **anchor):
        """Blits the button's text with its standard 1px drop shadow.

        `anchor` takes any pygame rect keyword (center=, midleft=, midtop=...),
        which is what lets every layout branch below share one blit path.
        """
        text_surf = self.font.render(text, True, (255, 255, 255))
        text_rect = text_surf.get_rect(**anchor)
        surface.blit(self.font.render(text, True, (0, 0, 0)), (text_rect.x + 1, text_rect.y + 1))
        surface.blit(text_surf, text_rect)
        return text_rect

    def draw(self, surface):
        if not self.visible: return

        mouse_pos = pygame.mouse.get_pos()
        is_hovered = self.rect.collidepoint(mouse_pos)
        
        current_color = self.color
        if self.disabled: current_color = c.UI_COLORS["grey"][0]
        elif self.is_pressed and is_hovered: current_color = self.pressed_color
        elif is_hovered: current_color = self.hover_color
        
        if getattr(self, 'shading', True):
            self.draw_gradient_rect(surface, current_color, self.rect)
        else:
            pygame.draw.rect(surface, current_color, self.rect)
        
        if self.is_selected:
            border_color = c.COLOR_GOLD_HIGHLIGHT
            border_thickness = 3
        else:
            if self.disabled:
                border_color = c.COLOR_DIM_BORDER
            else:
                border_color = (255, 255, 255) if is_hovered else (20, 20, 20)
            border_thickness = 2
            
        pygame.draw.rect(surface, border_color, self.rect, border_thickness)

        labelled = bool(self.image and self.text and self.show_text)

        if self.image:
            if not labelled:
                img_anchor = {"center": self.rect.center}
            elif getattr(self, 'layout', 'horizontal') == 'vertical':
                # Shifted down slightly to make room for the text above it
                img_anchor = {"center": (self.rect.centerx, self.rect.centery + 10)}
            else:
                img_anchor = {"midleft": (self.rect.x + 10, self.rect.centery)}
            img_rect = self.image.get_rect(**img_anchor)
            surface.blit(self.image, img_rect)

        if labelled:
            if getattr(self, 'layout', 'horizontal') == 'vertical':
                self.draw_label(surface, self.text, midtop=(self.rect.centerx, self.rect.y + 5))
            else:
                self.draw_label(surface, self.text, midleft=(img_rect.right + 10, self.rect.centery))
        elif self.text and not self.image:
            if self.text_align == "left":
                self.draw_label(surface, self.text, midleft=(self.rect.x + 10, self.rect.centery))
            else:
                self.draw_label(surface, self.text, center=self.rect.center)

        badge_text = getattr(self, 'notification_text', None)
        if not badge_text and getattr(self, 'notification_count', 0) > 0:
            badge_text = str(self.notification_count)
        if badge_text:
            draw_notification_badge(surface, self.rect, badge_text)

    def draw_gradient_rect(self, surface, color, rect):
        hi = 30
        low = 50
        c1 = (min(255, color[0] + hi), min(255, color[1] + hi), min(255, color[2] + hi))
        c2 = (max(0, color[0] - low), max(0, color[1] - low), max(0, color[2] - low))
        
        for i in range(rect.height):
            lerp = i / rect.height
            r, g, b = queries.lerp_color(c1, c2, lerp)
            pygame.draw.line(surface, (r, g, b), (rect.x, rect.y + i), (rect.right - 1, rect.y + i))

    def handle_event(self, event):
        if not self.visible or getattr(self, 'disabled', False): return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos) and (self.click_guard is None or self.click_guard()):
                self.is_pressed = True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.is_pressed:
                self.is_pressed = False
                if self.rect.collidepoint(event.pos) and (self.click_guard is None or self.click_guard()):
                    play_ui_sound("click")
                    self.callback()

#: Where a back button sits, by the kind of screen it is on.
BACK_BTN_STYLES = {
    # Full-screen menus and editors draw their own title, so the button tucks
    # into the top-left corner.
    "menu": c.BACK_BTN_TOPLEFT,
    # Screens layered over the map have to clear the top bar, so they sit lower
    # and slightly further in.
    "map": c.BACK_BTN_MAP_CENTER,
}


def make_back_button(on_click, style="menu", pos=None, label="Back", color="red"):
    """The one way to build a screen's back button.

    There were ~40 of these written out by hand in four different position
    conventions, and one file (faction.py) used two of them for the same
    button on two of its screens. The two dominant conventions are kept as two
    named styles rather than merged: collapsing them would move the button on
    every menu screen or on every map-layered screen, for no benefit.

    Pass `pos` to place the button relative to a panel; it wins over `style`.
    """
    x, y = pos if pos is not None else BACK_BTN_STYLES.get(style, c.BACK_BTN_TOPLEFT)
    return Button(x, y, "small", color, label, on_click)


class Slider:
    def __init__(self, x, y, width, text, initial_val, callback, visual_max=1.0, allowed_max=1.0):
        self.rect = pygame.Rect(x, y, width, 20)
        self.visual_max = visual_max
        self.allowed_max = allowed_max
        
        self.value = max(0.0, min(initial_val, self.allowed_max))
        ratio = self.value / self.visual_max if self.visual_max > 0 else 0
        
        self.handle_rect = pygame.Rect(x + (width * ratio) - 10, y - 5, 20, 30)
        self.text = text
        self.callback = callback
        self.dragging = False
        self.visible = True
        self.click_guard = None

        # --- COMBINED TRACKERS ---
        self.last_display_string = self.get_display_string()
        self.last_sound_tick = 0

    def get_display_string(self):
        """
        Determines the exact text to render. 
        """
        if ":" in self.text:
            return self.text
        else:
            return f"{self.text}: {int(self.value * 100)}%"

    def draw(self, surface):
        if not self.visible: return
        
        pygame.draw.rect(surface, c.COLOR_SLIDER_TRACK, self.rect)
        
        # Draw restricted track if applicable
        if self.allowed_max < self.visual_max and self.visual_max > 0:
            allowed_ratio = self.allowed_max / self.visual_max
            restricted_x = self.rect.x + int(self.rect.width * allowed_ratio)
            restricted_w = self.rect.width - int(self.rect.width * allowed_ratio)
            restricted_rect = pygame.Rect(restricted_x, self.rect.y, restricted_w, self.rect.height)
            pygame.draw.rect(surface, (60, 40, 40), restricted_rect) # A dark reddish-grey for locked part
            
        pygame.draw.rect(surface, c.COLOR_SLIDER_HANDLE, self.handle_rect)
        
        slider_font = fonts.get("normal")
        
        display_text = self.get_display_string()
        txt = slider_font.render(display_text, True, (255, 255, 255))
            
        surface.blit(txt, (self.rect.x, self.rect.y - 25))

    def handle_event(self, event):
        if not self.visible: return 
        
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.handle_rect.collidepoint(event.pos):
            if self.click_guard is not None and not self.click_guard():
                return
            self.dragging = True
            self.last_display_string = self.get_display_string()

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False

        elif event.type == pygame.MOUSEMOTION and self.dragging:
            if not pygame.mouse.get_pressed()[0]:
                # The button-up event was missed (e.g. a focus hiccup) -- don't
                # let the handle keep free-following the cursor forever.
                self.dragging = False
                return
            raw_x = max(self.rect.left, min(event.pos[0], self.rect.right))
            raw_ratio = (raw_x - self.rect.left) / self.rect.width
            max_ratio = self.allowed_max / self.visual_max if self.visual_max > 0 else 1.0
            
            clamped_ratio = min(raw_ratio, max_ratio)
            
            self.handle_rect.centerx = self.rect.left + int(self.rect.width * clamped_ratio)
            self.value = clamped_ratio * self.visual_max
            
            self.callback(self.value)
            
            current_display = self.get_display_string()
            
            # 1. Did the visual number actually change?
            if current_display != self.last_display_string:
                self.last_display_string = current_display 
                
                # 2. Has it been at least 100ms since the last click?
                current_time = pygame.time.get_ticks()
                if current_time - self.last_sound_tick > 50:
                    play_ui_sound("slider")
                    self.last_sound_tick = current_time # Reset the throttle

def draw_text_box(surface, rect, text, active=False, font=None, placeholder=None,
                  pad_x=10, show_caret=True):
    """Draws one single-line text entry box: fill, border, text, caret.

    Nine screens carried their own copy of these four steps, between them using
    six different fills and four different borders for the same widget. The
    colours come from the shared palette now. `font` stays a parameter because
    the boxes genuinely differ in size, from the unit-rename strip to the
    faction title bar.

    The clip is intersected with whatever is already set rather than replacing
    it, so a box drawn inside a scrolling pane still gets cut off at the pane's
    edge instead of escaping it.
    """
    font = font or fonts.get("normal")

    pygame.draw.rect(surface, c.INPUT_BG_ACTIVE if active else c.INPUT_BG, rect)
    pygame.draw.rect(surface, c.INPUT_BORDER_ACTIVE if active else c.INPUT_BORDER, rect, 2)

    if not text and placeholder:
        text_surf = font.render(placeholder, True, c.UI_TEXT_MUTED)
    else:
        text_surf = font.render(text + ("|" if active and show_caret else ""), True, (255, 255, 255))

    old_clip = surface.get_clip()
    inner = rect.inflate(-6, -4)
    surface.set_clip(inner.clip(old_clip) if old_clip else inner)
    surface.blit(text_surf, text_surf.get_rect(midleft=(rect.x + pad_x, rect.centery)))
    surface.set_clip(old_clip)


class TextField:
    """A single-line text entry box with the same duck-typed interface as Button
    (.rect, .visible, .handle_event(event), .draw(surface)) so it can sit in a
    screen's `self.elements` list and get events/drawing for free.

    Click to focus; typing while focused edits `.text`. Enter calls on_submit
    (if given) and unfocuses; Escape just unfocuses. Screens that need Tab-like
    behaviour between fields should defocus other fields themselves on click.
    """
    def __init__(self, x, y, width, height, initial_text="", numeric=False,
                max_length=None, on_submit=None, label=None):
        self.rect = pygame.Rect(x, y, width, height)
        self.text = str(initial_text)
        self.numeric = numeric
        self.max_length = max_length
        self.on_submit = on_submit
        self.label = label
        self.active = False
        self.visible = True
        self.click_guard = None

    def _valid_char(self, ch):
        if self.numeric:
            return ch.isdigit() or (ch == "-" and not self.text)
        return ch.isprintable()

    def get_int(self, default=0):
        try:
            return int(self.text)
        except ValueError:
            return default

    def handle_event(self, event):
        if not self.visible:
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos) and (self.click_guard is None or self.click_guard()):
                self.active = True
            else:
                self.active = False
            return

        if not self.active or event.type != pygame.KEYDOWN:
            return

        self.text, status = process_text_input(event, self.text, max_length=self.max_length,
                                                validation_func=self._valid_char)
        if status == "SUBMIT":
            self.active = False
            if self.on_submit:
                self.on_submit()
        elif status == "CANCEL":
            self.active = False

    def draw(self, surface):
        if not self.visible:
            return

        if self.label:
            label_font = fonts.get("normal")
            label_surf = label_font.render(self.label, True, c.UI_TEXT_BRIGHT)
            surface.blit(label_surf, label_surf.get_rect(midright=(self.rect.x - 10, self.rect.centery)))

        draw_text_box(surface, self.rect, self.text, active=self.active, pad_x=8)

def process_text_input(event, current_text, max_length=None, validation_func=None):
    if event.type != pygame.KEYDOWN:
        return current_text, "TYPING"

    if event.key == pygame.K_BACKSPACE:
        return current_text[:-1], "TYPING"
    elif event.key == pygame.K_RETURN:
        return current_text, "SUBMIT"
    elif event.key == pygame.K_ESCAPE:
        return current_text, "CANCEL"
    elif event.key == pygame.K_v and (pygame.key.get_mods() & pygame.KMOD_CTRL or pygame.key.get_mods() & pygame.KMOD_GUI):
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            clip_bytes = pygame.scrap.get(pygame.SCRAP_TEXT)
            if clip_bytes:
                clip_str = clip_bytes.decode('utf-8', errors='ignore').replace('\x00', '')
                for char in clip_str:
                    if max_length is not None and len(current_text) >= max_length:
                        break
                        
                    if validation_func:
                        if validation_func(char):
                            current_text += char
                    elif char.isprintable():
                        current_text += char
        except Exception as e:
            print(f"Paste Error: {e}")
        return current_text, "TYPING"
    else:
        if max_length is not None and len(current_text) >= max_length:
            return current_text, "TYPING"

        char = event.unicode
        
        if validation_func:
            if not validation_func(char):
                return current_text, "TYPING"
        elif not char.isprintable():
            return current_text, "TYPING"

        return current_text + char, "TYPING"

def draw_icon_row(surface, font, base_text, entries, x, y, color,
                  icon_size=None, icon_gap=4, empty_text=None):
    """Draws "<label>  [icon] value  [icon] value ..." on one line.

    Every stat line in the game (costs, yields, combat, bombardment) is this
    same shape, so they all funnel through here; the callers below only differ
    in which icons they pick and how the values are formatted.

    `entries` is a sequence of (icon_name, display_text) pairs, already
    filtered and formatted by the caller. `icon_size` defaults to the font
    height so icons line up with the text; pass a number to pin it.

    Returns the x position just past the last thing drawn, so callers can
    chain multiple colored segments onto the same line.
    """
    base_surf = font.render(base_text, True, color)
    surface.blit(base_surf, (x, y))
    curr_x = x + base_surf.get_width()

    size = max(16, font.get_height()) if icon_size is None else icon_size

    for icon_name, display_text in entries:
        icon_surf = scale_icon(icon_name, size)
        if icon_surf:
            surface.blit(icon_surf, (curr_x, y + 2))
            curr_x += size + icon_gap

        val_surf = font.render(f"{display_text}   ", True, color)
        surface.blit(val_surf, (curr_x, y))
        curr_x += val_surf.get_width()

    if not entries and empty_text:
        empty_surf = font.render(empty_text, True, color)
        surface.blit(empty_surf, (curr_x, y))
        curr_x += empty_surf.get_width()

    return curr_x

def draw_resource_string(surface, font, base_text, mat, man, fuel, x, y, color, is_yield=False):
    """Material/manpower/fuel row. Zero-valued resources are left out entirely."""
    entries = []
    for icon_name, val in (("Iron", mat), ("Infantry", man), ("Oil", fuel)):
        try:
            numeric = float(val)
        except (ValueError, TypeError):
            continue
        if numeric == 0:
            continue

        display_val = queries.format_number(val)
        if is_yield and numeric > 0 and not display_val.startswith("+"):
            display_val = f"+{display_val}"
        entries.append((icon_name, display_val))

    # 16px icons and a 20px step, rather than the font-height sizing the stat
    # rows use, keeps the resource glyphs at their long-standing HUD size.
    return draw_icon_row(surface, font, base_text, entries, x, y, color,
                          icon_size=16, icon_gap=4,
                          empty_text="None" if is_yield else "Free")

def draw_combat_stats(surface, font, base_text, atk, df, hp, spd, x, y, color, labeled=True):
    """Attack/defense/health/speed row.

    Defense is hidden entirely when 0, the same way a free resource cost is
    hidden in draw_resource_string, rather than showing "DEF: 0" noise.
    `labeled=False` drops the "ATK:"-style prefixes and shows bare numbers
    next to each icon, for compact single-line layouts.
    """
    if labeled:
        stats = [
            (c.ICON_ATTACK, f"ATK: {queries.format_number(atk)}"),
            (c.ICON_DEFENSE, f"DEF: {queries.format_number(df)}"),
            (c.ICON_HEALTH, f"HP: {queries.format_number(hp)}"),
            (c.ICON_SPEED, f"SPD: {queries.format_number(spd)}"),
        ]
    else:
        stats = [
            (c.ICON_ATTACK, queries.format_number(atk)),
            (c.ICON_DEFENSE, queries.format_number(df)),
            (c.ICON_HEALTH, queries.format_number(hp)),
            (c.ICON_SPEED, queries.format_number(spd)),
        ]
    if not df:
        stats.pop(1)
    return draw_icon_row(surface, font, base_text, stats, x, y, color)

def draw_bombardment_stats(surface, font, dmg, rng, x, y, color, base_text="Bombardment:   ", labeled=True):
    """Bombardment damage/range row.
    Caller is responsible for only calling this for units that can bombard."""
    if labeled:
        entries = [(c.ICON_BOMBARDMENT, f"DMG: {queries.format_number(dmg)}"), (c.ICON_BOMBARD_RANGE, f"RNG: {queries.format_number(rng)}")]
    else:
        entries = [(c.ICON_BOMBARDMENT, queries.format_number(dmg)), (c.ICON_BOMBARD_RANGE, queries.format_number(rng))]
    return draw_icon_row(surface, font, base_text, entries, x, y, color)

def draw_time_stat(surface, font, turns, x, y, color, icon_name="Clock"):
    """Single 'clock icon + turn count' stat, used where a full "Build Time:
    N turns" label would take up too much space (e.g. compact list rows)."""
    return draw_icon_row(surface, font, "", [(icon_name, str(turns))], x, y, color,
                          icon_size=16, icon_gap=4)

def draw_stat_separator(surface, font, x, y, color=(130, 130, 130)):
    """Draws a '| ' divider between differently-colored stat segments packed
    onto the same line, and returns the x position just past it."""
    sep_surf = font.render("| ", True, color)
    surface.blit(sep_surf, (x, y))
    return x + sep_surf.get_width()