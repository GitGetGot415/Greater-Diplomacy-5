import os
import shutil
import math
import pygame
import data.constants as c
from data import queries
from data.io import keybind_io
from data.platform import sync_persisted_dir
from ui.bars import ui_bars

from ui.information import feedback_text
from ui.panels import turn_progress
from map_logic.diplomacy import diplomacy_processor
from ui.widgets.scroll_state import ScrollPaneOwner
from ui.widgets.ui_elements import Button, make_back_button
from ui.sound_effects import play_ui_sound
from ui.rendering.font_manager import fonts

# Keybind actions which synthesize the matching physical mouse-button event.
# The keybind screen owns their player-facing labels and layout; this mapping
# is shared input behavior, so it belongs with the other global constants.
KEYBIND_MOUSE_BUTTONS = {
    "MOUSE_LEFT_CLICK": 1,
    "MOUSE_MIDDLE_CLICK": 2,
    "MOUSE_RIGHT_CLICK": 3,
}

DEFAULT_BG_COLOR = c.DEFAULT_BG_COLOR


def resolve_keybind(state, action, default):
    """Resolves a rebindable action's pygame key code.

    Delegates to the persisted settings rather than state.controller -- most
    screens never get a controller reference wired up, so that chain was
    silently falling back to `default` almost everywhere.
    """
    return queries.get_keybind(action, default)


def host_map_screen(screen):
    """The map a screen is layered over, or the opener when it has no map."""
    return getattr(screen, "map_screen", None) or screen


# Keys currently acting as held mouse buttons.  This suppresses repeated
# KEYDOWN events and lets a key release produce the matching mouse release
# even if its binding changes while it is held.
_MOUSE_KEYBIND_PRESSES = {}


def synthesize_keybind_mouse_events(events, keybinds=None, allow_keydown=True, reserved_keys=()):
    """Add normal mouse down/up events for configured keyboard mouse clicks.

    Physical mouse input remains in ``events`` unchanged.  Keybinds receive
    the cursor's current position and otherwise follow the same UI, map, and
    drag paths as their physical button counterparts. ``allow_keydown`` keeps
    focused text fields from receiving new synthetic clicks while still
    releasing a click that began before a screen change. ``reserved_keys`` lets
    gameplay controls keep their physical keys without generating extra clicks.
    """
    if keybinds is None:
        keybinds = {
            action: queries.get_keybind(action, None)
            for action in KEYBIND_MOUSE_BUTTONS
        }

    cursor_pos = pygame.mouse.get_pos()
    translated = []
    focus_lost = getattr(pygame, "WINDOWFOCUSLOST", None)
    for event in events:
        translated.append(event)
        if event.type == pygame.KEYDOWN and allow_keydown and event.key not in reserved_keys:
            if event.key in _MOUSE_KEYBIND_PRESSES:
                continue
            buttons = tuple(button for action, button in KEYBIND_MOUSE_BUTTONS.items()
                            if keybinds.get(action) == event.key)
            if buttons:
                _MOUSE_KEYBIND_PRESSES[event.key] = buttons
                translated.extend(
                    pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=cursor_pos,
                                       button=button, keybind_mouse=True)
                    for button in buttons)
        elif event.type == pygame.KEYUP:
            for button in _MOUSE_KEYBIND_PRESSES.pop(event.key, ()):
                translated.append(
                    pygame.event.Event(pygame.MOUSEBUTTONUP, pos=cursor_pos,
                                       button=button, keybind_mouse=True))
        elif focus_lost is not None and event.type == focus_lost:
            for buttons in _MOUSE_KEYBIND_PRESSES.values():
                translated.extend(
                    pygame.event.Event(pygame.MOUSEBUTTONUP, pos=cursor_pos,
                                       button=button, keybind_mouse=True)
                    for button in buttons)
            _MOUSE_KEYBIND_PRESSES.clear()
    return translated

def keyboard_input_is_captured(state):
    """Whether keyboard input belongs to an active text or key-capture field.

    Screens answer through Screen.text_input_active. The getattr is for
    modal-stack entries that are not Screens, such as the loading modal.
    """
    return bool(getattr(state, "text_input_active", False))


def dispatch_global_keys(state, event):
    """Routes rebindable key presses to a state's matching handlers.

    Shared by the main loop and the blocking sub-screen loop so no individual
    screen has to re-resolve the keybinds itself. Screen-specific actions are
    harmless elsewhere because their handler is optional.
    """
    # A focused text bar owns every key press, including a character that has
    # been rebound as a map command. ``keyboard_input_is_captured`` also
    # prevents those keys from synthesizing mouse clicks at the event boundary.
    typing_in_ui_bar = keyboard_input_is_captured(state)
    if event.type != pygame.KEYDOWN:
        return
    # Gameplay screens can own physical controls even when a menu action was
    # rebound to that key. Lightweight non-Screen callers need no reservation.
    if event.key in getattr(state, "reserved_keys", ()):
        return
    back_key = resolve_keybind(state, "BACK", keybind_io.default_keybind("BACK"))
    # Back remains available while editing so a field or screen can offer its
    # normal cancel behavior; the remaining rebindable actions stay reserved
    # for the text bar.
    if typing_in_ui_bar and event.key != back_key:
        return
    if event.key == back_key:
        state.handle_back_key()
    elif event.key == resolve_keybind(state, "ORDERS", keybind_io.default_keybind("ORDERS")):
        if hasattr(state, "handle_orders_key"):
            state.handle_orders_key()
    elif event.key == resolve_keybind(state, "ECONOMY", keybind_io.default_keybind("ECONOMY")):
        if hasattr(state, "handle_economy_key"):
            state.handle_economy_key()
    elif event.key == resolve_keybind(state, "CLEAR_ORDERS", keybind_io.default_keybind("CLEAR_ORDERS")):
        if hasattr(state, "handle_clear_orders_key"):
            state.handle_clear_orders_key()

class ScreenLayer:
    """A pseudo-element that defers its drawing to one of its screen's methods.

    Screens whose buttons scroll register these to pin fixed chrome above the
    scrolling content: draw() walks `elements` in order, so anything appended
    after the scrolling buttons lands on top of them. Register genuinely fixed
    buttons *after* the layer so the chrome doesn't paint over them in turn.
    """
    def __init__(self, screen, draw_method):
        self.screen = screen
        self.draw_method = draw_method
        self.visible = True

    def handle_event(self, event):
        pass

    def draw(self, surface):
        getattr(self.screen, self.draw_method)(surface)

class Screen(ScrollPaneOwner):
    bg_color = DEFAULT_BG_COLOR
    reserved_keys = ()

    # Screens layered over the map set this; it drives feedback text and keybind lookup.
    map_screen = None
    # Where exit_screen() sends the state machine. None just closes the screen.
    back_state = None
    # Truthy while a field must receive every key, BACK and FULLSCREEN included.
    # A screen sets it or overrides it with a property.
    listening_for = None
    # Pixels per wheel notch: panels layered on the map, and full-screen menu lists.
    scroll_speed = 30
    list_scroll_speed = 40

    # Centred header drawn under the buttons. Set `title` for a fixed string or
    # override get_title() for one that changes with the screen's sub-state.
    title = None
    title_y = 40
    title_preset = "heading1"
    title_shadow = False

    # Optional method taking the surface. It draws row striping and labels inside
    # the scroll clip, under the is_scrollable elements. A screen that defines it
    # gets the backdrop even on a frame with no scrollable elements.
    draw_scroll_backdrop = None

    def __init__(self):
        self.done = False
        self.next_state = None
        self.elements = []
        self.bg_image_path = None # Added support for generic background images

    @property
    def text_input_active(self):
        """Whether a text or key-capture field owns the keyboard.

        While it is true, rebindable keys other than BACK do not fire and do not
        synthesize mouse clicks. A screen with its own text state overrides this
        and includes super().text_input_active. The army-name editor on the host
        map counts for every screen layered over that map. A modal opened from a
        menu hosts on that menu, which has no army editor; hence the getattr.
        """
        return bool(self.listening_for or getattr(self.map_screen, "army_editor_state", None))

    def on_enter(self, app, previous):
        """Prepare this screen when the controller makes it the active screen."""

    def prepare_map(self, app):
        """Build the map before this screen opens MAP. Return False to stay on this screen."""
        return True

    def prepare_map_steps(self, app):
        """Return loading stages for a new map, or None when returning to a screen."""
        return None

    def return_to_previous_context(self, app, previous):
        """Set back_state for a screen that can open over a live game or lobby."""
        if previous == app.states["MAP"]:
            self.back_state = "MAP"
        elif previous == app.states["REALTIME_LOBBY"]:
            # These are convenience overlays while a host waits in the
            # lobby. Returning must preserve the live server/session.
            self.back_state = "REALTIME_LOBBY"
        elif previous == app.states["REALTIME_REMOTE_LOBBY"]:
            self.back_state = "REALTIME_REMOTE_LOBBY"
        elif previous is not None and previous == app.states.get("CUSTOM_BATTLE"):
            # A standalone game registers no CUSTOM_BATTLE screen.
            # Opened from a tactical battle preview or a running battle; return to that same view.
            self.back_state = "CUSTOM_BATTLE"
        # Returning from a Settings sub-screen (e.g. Unit Art, Keybinds)
        # isn't a fresh entry into Settings -- it must not overwrite the
        # MAP/MENU back_state Settings already picked up when it was
        # first opened, or Back from the sub-screen would dump the
        # player at the menu even when they opened Settings from a live game.
        elif previous not in (app.states.get("UNIT_ART"), app.states.get("KEYBINDS"),
                              app.states.get("MOUSE_SETTINGS")):
            self.back_state = "MENU"

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        pass

    def touch_map_at(self, position):
        """Return a map only where this screen exposes an interactive map workspace."""
        return None

    def has_secondary_action_at(self, position):
        """Whether holding here offers an action distinct from an ordinary click."""
        return False

    def cancel_pointer_input(self):
        """Release UI drag state when touch loses focus or its screen changes."""
        self.cancel_active_drags()
        self._cancel_pressed_elements()
        for element in self.elements:
            if hasattr(element, "dragging"):
                element.dragging = False

    def go_to(self, state):
        """Hands the state machine off to another screen and closes this one."""
        self.next_state = state
        self.done = True

    def set_sub_state(self, state):
        """Changes a screen's local view and resets its standard list scroll.

        Category/list screens use the same transition contract: switch the
        state, return to the first row, then rebuild controls. Screens with
        extra transient state can clear it before delegating here.
        """
        self.sub_state = state
        self.scroll.value = 0
        self.refresh_ui()

    def exit_screen(self):
        """Closes this screen, handing off to back_state when one is declared."""
        if self.back_state:
            self.next_state = self.back_state
        self.done = True

    def handle_back_key(self):
        self.go_back()

    def go_back(self):
        """Leaves this screen with the same sound as its Back button."""
        play_ui_sound("back")
        self.exit_screen()

    @property
    def scroll(self):
        """The screen's standard list pane."""
        return self.scroll_state("list")

    def is_content_dragging(self, scroll=None):
        """Whether a content drag (see handle_content_drag) is armed on this pane."""
        return (scroll or self.scroll).content_drag is not None

    def cancel_active_drags(self):
        """Releases every pane's scrollbar and content drag mid-gesture.

        Call this on a screen right before it gets covered by a pushed modal
        (see ui/modal_stack.push) -- the covering screen steals every event
        from then on, including the MOUSEBUTTONUP that would normally end the
        drag, so without this it's left stuck armed. Once the covering modal
        closes and this screen starts receiving events again, the very next
        MOUSEMOTION would otherwise be misread as an active drag with no
        button held, making the content appear to scroll on its own.
        """
        for scroll in self.scrolls.values():
            scroll.cancel()

    def scroll_by(self, event, scroll=None, speed=None):
        """Applies a wheel event to a pane and clamps it."""
        scroll = scroll or self.scroll
        delta = -event.x if scroll.axis == "x" and event.x else event.y
        scroll.scroll_by(delta * (self.scroll_speed if speed is None else speed))
        self.refresh_ui()

    def handle_list_scroll(self, event, scroll=None, speed=None, content=False):
        """Drives a scrollable pane: wheel, scrollbar grab, drag and release.

        Track geometry is read off the rects the pane kept when it drew its
        scrollbar, so there is nothing to keep in sync by hand. Returns True
        when the event was consumed, so callers can skip their own handling.

        Pass `content=True` to also let the user grab the pane's content_rect
        itself and drag it -- see handle_content_drag.
        """
        scroll = scroll or self.scroll
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_by(event, scroll, self.list_scroll_speed if speed is None else speed)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # A grab on the handle/track and a content-drag can both arm on the
            # same mouse-down when the content rect overlaps the scrollbar (the
            # usual case). Clear the scrollbar drag here, unconditionally,
            # before the content-drag branch below can return early and skip it
            # -- otherwise it's left stuck and the handle free-follows the
            # mouse on every later motion until another drag happens to mask it.
            scroll.bar_drag = False

        track, handle = scroll.track, scroll.handle
        grabbing_scrollbar = (event.type == pygame.MOUSEBUTTONDOWN and track
                              and ((handle and handle.collidepoint(event.pos))
                                   or track.collidepoint(event.pos)))

        # A click that lands on the scrollbar itself must never be allowed to
        # arm (or keep driving) the content-drag: content-drag moves the offset
        # 1:1 with mouse pixels in *content* space, while the handle follows the
        # mouse's ratio *along the track*. Since the content is usually much
        # taller than the track, letting content-drag win once it crosses its
        # arm threshold makes the handle crawl far slower than the mouse.
        # Clearing the content drag keeps the two gestures from fighting over
        # the same motion events.
        if grabbing_scrollbar or scroll.bar_drag:
            scroll.content_drag = None
        elif content and self.handle_content_drag(event, scroll):
            return True

        if not track:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            before = scroll.value
            if scroll.press_scrollbar(event.pos):
                if scroll.value != before:
                    self.refresh_ui()
                return True
        elif event.type == pygame.MOUSEMOTION and scroll.bar_drag:
            scroll.snap(event.pos)
            self.refresh_ui()
            return True

        return False

    def _cancel_pressed_elements(self):
        """Un-arms any button caught mid-press once a drag is confirmed, so the
        eventual mouse-up doesn't also fire its click."""
        for el in self.elements:
            if getattr(el, "is_pressed", False):
                el.is_pressed = False

    def handle_content_drag(self, event, scroll=None, lo=None, hi=None, threshold=6, invert=False, refresh=True):
        """Lets the user grab a pane's own content and drag it, alongside
        whatever wheel/scrollbar-handle scrolling it already has.

        The drag starts inside the pane's content_rect. A small pixel threshold
        has to be crossed before a press is treated as a drag (and any button
        pressed under the cursor gets un-armed), so an ordinary click on a
        button inside the list still registers normally. Dragging down pulls
        content down. Dragging right pulls horizontal content right.

        `lo`/`hi` bound the resulting value; by default `hi` is 0 and `lo` is
        the pane's own limit (the usual negative-range convention where the
        offset is added to a row's position). Pass explicit bounds for screens
        using a 0..max convention instead -- and if that convention *subtracts*
        the offset from content's position (as the map HUD panels do), pass
        `invert=True` so dragging down still pulls content down.
        Pass `refresh=False` for a screen whose `update()` already repositions
        scrolled elements every frame off the offset alone, so a full
        refresh_ui() rebuild isn't needed on every drag pixel.
        Returns True when the event was consumed as a drag.
        """
        scroll = scroll or self.scroll
        rect = scroll.content_rect
        if not rect:
            return False

        idx = scroll.index
        state = scroll.content_drag  # None, or [origin, armed]

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and rect.collidepoint(event.pos):
            scroll.content_drag = [event.pos[idx], False]
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and state is not None:
            scroll.content_drag = None
            return state[1]
        if event.type == pygame.MOUSEMOTION and state is not None:
            origin, armed = state
            if not armed:
                if abs(event.pos[idx] - origin) < threshold:
                    return False
                armed = state[1] = True
                self._cancel_pressed_elements()
            low = scroll.limit if lo is None else lo
            high = 0 if hi is None else hi
            delta = -event.rel[idx] if invert else event.rel[idx]
            scroll.value = max(low, min(high, scroll.value + delta))
            if refresh:
                self.refresh_ui()
            return True

        return False

    def refresh_ui(self):
        pass

    def sync_entries(self):
        """Pulls live text out of on-screen fields before they get rebuilt or saved.

        Two ways to tag a field, both read here so no screen has to write this
        loop again: `entry_ref` (the dict it edits) plus `entry_key` writes the
        text straight back, and `entry_apply` hands the text to a callable for
        anything whose storage isn't a plain dict slot.

        Four editors each had their own copy of this keyed on a different
        marker attribute -- entry_ref, tech_key, turn_key -- which meant a field
        tagged for one screen was silently invisible to the others.
        """
        for el in self.elements:
            apply = getattr(el, "entry_apply", None)
            if apply is not None:
                apply(el.text)
                continue
            entry = getattr(el, "entry_ref", None)
            if entry is not None:
                entry[el.entry_key] = el.text

    # ---------------------------------------------------------------- #
    #                     STANDARD VERTICAL LISTS                      #
    # ---------------------------------------------------------------- #

    def layout_list_rows(self, count, row_h, top, view_h=None, pad=0,
                         cull_top=100, cull_bottom=None, scroll=None):
        """Sets the scroll limit for a list and yields (index, y) for visible rows.

        Every folder/scenario list in the menus is built this way: derive the
        scroll floor from the total content height, then walk the rows applying
        the offset. A row is included as soon as any part of it overlaps
        [cull_top, cull_bottom), not just its top corner, so pair this with
        `ui_bars.clip_scroll_region` (or a manual set_clip at the same bounds)
        around wherever the row actually gets drawn -- otherwise a row that's
        only partially in view will render uncropped past the boundary.

        Also publishes the pane's `guard`: a callable a scrolled button/field
        can set as its `click_guard` so a click landing in that cropped sliver
        (still inside the row's own rect, but outside the visible boundary)
        doesn't fire.
        """
        scroll = scroll or self.scroll
        if cull_bottom is None:
            cull_bottom = c.SCREEN_HEIGHT - 50
        if view_h is None:
            # Derived from where rows actually get culled, not a magic constant --
            # keeps the limit in lockstep with wherever the caller's clip rect
            # ends, so the last row can always be scrolled fully into view instead
            # of stopping short of the boundary it's drawn against.
            view_h = cull_bottom - top

        scroll.limit = min(0, view_h - (count * row_h) - pad)
        offset = scroll.value
        scroll.guard = lambda: cull_top <= pygame.mouse.get_pos()[1] < cull_bottom

        for i in range(count):
            y = top + (i * row_h) + offset
            if y + row_h > cull_top and y < cull_bottom:
                yield i, y

    def add_list_row(self, element, scroll=None):
        """Registers an element built inside a layout_list_rows loop.

        Call this after layout_list_rows has published the pane's guard. The
        element is cropped to the pane's content_rect, and a click on its
        cropped part does not fire.
        """
        element.is_scrollable = True
        element.click_guard = (scroll or self.scroll).guard
        self.elements.append(element)
        return element

    def draw_scrolling_lines(self, surface, lines, font, x, top, view_h, line_h, clip_rect, color_for):
        """Draws one column of text lines that scrolls inside clip_rect.

        Sets the scroll limit from the line count. `color_for` takes a line and
        returns its text color.
        """
        scroll = self.scroll
        scroll.content_rect = clip_rect
        with ui_bars.clip_scroll_region(surface, clip_rect,
                                        draw_top=scroll.value != 0, draw_bottom=scroll.value > scroll.limit):
            for i, y in self.layout_list_rows(len(lines), line_h, top, view_h=view_h,
                                              cull_top=clip_rect.top, cull_bottom=clip_rect.bottom):
                surface.blit(font.render(lines[i], True, color_for(lines[i])), (x, y))

    def content_hover_guard(self, scroll=None):
        """A `click_guard` for rows a screen laid out by hand rather than through
        layout_list_rows: it keeps a click landing in a row's cropped sliver,
        outside the visible content rect, from firing.

        layout_list_rows publishes the same thing as the pane's guard; this is
        for the panels that place their own rows and only need the guard.
        """
        rect = (scroll or self.scroll).content_rect
        return lambda: bool(rect) and rect.collidepoint(pygame.mouse.get_pos())

    def draw_list_scrollbar(self, surface, track_x, track_y, view_h, width=15, scroll=None):
        """Draws the pane's scrollbar and keeps its rects for handle_list_scroll.

        For a horizontal pane, view_h is the track length and width is its height.
        """
        return (scroll or self.scroll).draw_scrollbar(surface, track_x, track_y, view_h, width)

    def get_title(self):
        """The centred header text, or None for no header."""
        return self.title

    def draw_title(self, surface):
        text = self.get_title()
        if text:
            ui_bars.draw_centered_title(surface, text, self.title_y,
                                        self.title_preset, shadow=self.title_shadow)

    def draw_background(self, surface):
        """Fills the screen behind everything else. Override for a custom look
        instead of duplicating draw()."""
        if self.bg_image_path:
            bg_img = ui_bars.get_ui_image(self.bg_image_path, directory=c.BACKGROUNDS_DIR)
            if bg_img.get_size() != surface.get_size():
                bg_img = pygame.transform.scale(bg_img, surface.get_size())
            surface.blit(bg_img, (0, 0))
        else:
            # Screens with no dedicated bg_image_path get an endlessly
            # scrolling checkerboard tinted to their own bg_color instead of
            # a flat fill -- see ui_bars.get_checkerboard_tile.
            self.draw_checkerboard_background(surface, self.bg_color)

    def draw_checkerboard_background(self, surface, base_color, *, tile=None, reflection_y=None,
                                     reflection_scale=1.0, reflection_shear=0.0, scroll_y_scale=1.0,
                                     scroll_x_scale=1.0, origin=(0, 0), tile_scale=(1.0, 1.0)):
        # Draw the tile in a grid slightly larger than the screen, offset by a
        # time-based amount that grows down and to the right. Since the tile
        # is seamless, wrapping the offset back to 0 every tile-length makes
        # the motion loop forever with no seam.
        if tile is None:
            tile = ui_bars.get_checkerboard_tile(base_color)
        tile_w, tile_h = tile.get_size()
        period_x = max(1.0, tile_w * tile_scale[0])
        period_y = max(1.0, tile_h * tile_scale[1])

        phase = ui_bars.checkerboard_scroll_offset()
        offset_x = (phase * scroll_x_scale) % period_x
        offset_y = (phase * scroll_y_scale) % period_y

        start_x = (origin[0] - offset_x) % period_x - period_x
        start_y = (origin[1] - offset_y) % period_y - period_y
        if reflection_y is not None:
            # Mirror and scale the original pattern about the waterline, including its movement.
            source_height = period_y / reflection_scale
            source_offset = (phase * scroll_y_scale) % source_height
            reflected_origin = reflection_y + reflection_scale * (reflection_y - origin[1] + source_offset)
            start_y = reflected_origin % period_y - period_y
            if reflection_shear:
                water_top = max(0, reflection_y, surface.get_clip().top)
                water_height = surface.get_clip().bottom - water_top
                if water_height <= 0:
                    return
                pattern = ui_bars.get_sheared_checkerboard(
                    tile, (surface.get_width(), water_height), reflection_shear)
                source_y = (water_top - start_y) % tile_h
                # Cancel the cached row offset at the horizon to keep the reflection aligned.
                source_x = (-start_x - reflection_shear * (water_top - reflection_y)
                            + reflection_shear * source_y) % tile_w
                ui_bars.draw_checkerboard_region(
                    surface, pattern, pygame.Rect(0, water_top, surface.get_width(), water_height),
                    (source_x, source_y), tile.get_alpha())
                return
        clip = surface.get_clip()
        if clip.width <= 0 or clip.height <= 0:
            return
        canvas = ui_bars.checkerboard_canvas(clip.size)
        opaque_tile = ui_bars.opaque_checkerboard_tile(tile)
        base_x, base_y = math.floor(start_x), math.floor(start_y)
        canvas_x, canvas_y = clip.left - 1, clip.top - 1
        # Keep the fractional translation separate from rounded tile boundaries.
        # Blend that translation once for the complete background layer.
        first_row = math.floor((canvas_y - base_y) / period_y)
        last_row = math.ceil((canvas_y + canvas.get_height() - base_y) / period_y)
        first_col = math.floor((canvas_x - base_x) / period_x)
        last_col = math.ceil((canvas_x + canvas.get_width() - base_x) / period_x)
        for row in range(first_row, last_row):
            top = base_y + round(row * period_y) - canvas_y
            bottom = base_y + round((row + 1) * period_y) - canvas_y
            for col in range(first_col, last_col):
                left = base_x + round(col * period_x) - canvas_x
                right = base_x + round((col + 1) * period_x) - canvas_x
                scaled = ui_bars.scaled_checkerboard_tile(opaque_tile, (right - left, bottom - top))
                canvas.blit(scaled, (left, top))
        ui_bars.draw_checkerboard_region(
            surface, canvas, clip, (1 - (start_x - base_x), 1 - (start_y - base_y)), tile.get_alpha())

    def draw(self, surface):
        # 1. Fill background or draw background image
        self.draw_background(surface)

        # 2. Centred header, then the specific screen content (Map, UI Bars)
        # Keeping both BEFORE elements fixes the layering
        self.draw_title(surface)
        self.additional_draw(surface)

        # 3. Draw UI buttons on the very top. Anything a screen marked
        # is_scrollable (built inside a layout_list_rows loop) is cropped to
        # the list pane's content_rect and drawn last, so it's cleanly cut off at that
        # boundary instead of popping in/out at an untracked pixel.
        self.draw_elements(surface)

        # 4. Green status text, for every screen that hangs off the map
        self.draw_feedback(surface)

    def draw_elements(self, surface):
        scrollable = []
        for el in self.elements:
            if getattr(el, "is_scrollable", False):
                scrollable.append(el)
            else:
                el.draw(surface)

        if not scrollable and self.draw_scroll_backdrop is None:
            return

        scroll = self.scroll
        if scroll.content_rect:
            with ui_bars.clip_scroll_region(surface, scroll.content_rect,
                                            draw_top=scroll.value != 0, draw_bottom=scroll.value > scroll.limit):
                if self.draw_scroll_backdrop is not None:
                    self.draw_scroll_backdrop(surface)
                for el in scrollable:
                    el.draw(surface)
        else:
            for el in scrollable:
                el.draw(surface)

    def draw_feedback(self, surface):
        if self.map_screen:
            feedback_text.draw_feedback(self.map_screen, surface)

    def queue_diplomacy_action(self, target, action, params=""):
        """Toggles a queued diplomatic action and rebuilds this screen.

        Every "queue this for next turn" button on a map-layered screen does
        the same three things -- toggle, report the returned message, refresh --
        and each one used to spell them out. They now use the same diplomacy owner.
        """
        msg = diplomacy_processor.toggle_diplomacy_action(
            self.map_screen.world.nation_data, self.map_screen.session.player_country,
            target, action, params)
        self.map_screen.show_feedback(msg)
        self.refresh_ui()

    def additional_draw(self, surface):
        pass

    def update(self):
        pass

class ButtonMenuScreen(Screen):
    """A title, an optional caption, one centered column of large buttons, and Back."""
    title_y = 100
    title_shadow = True
    caption = None

    CAPTION_Y = 165
    BUTTON_TOP = 220
    BUTTON_GAP = 110

    def __init__(self):
        super().__init__()
        self.refresh_ui()

    def menu_buttons(self):
        """Returns one (label, color, callback) row per button, with an optional fourth icon."""
        raise NotImplementedError

    @classmethod
    def build_menu_buttons(cls, rows):
        """Builds the centered column from (label, color, callback) rows, with an optional fourth icon."""
        return [Button("centered", cls.BUTTON_TOP + i * cls.BUTTON_GAP, "large", color, label,
                       callback, image=icon[0] if icon else None)
                for i, (label, color, callback, *icon) in enumerate(rows)]

    def refresh_ui(self):
        self.elements = self.build_menu_buttons(self.menu_buttons())
        self.elements.append(make_back_button(self.exit_screen))

    def additional_draw(self, surface):
        if self.caption:
            text = fonts.get("normal").render(self.caption, True, (220, 220, 220))
            surface.blit(text, text.get_rect(midtop=(c.SCREEN_WIDTH // 2, self.CAPTION_Y)))


class MenuListScreen(Screen):
    """A title, one centered scrolling list, and Back: the scenario and map pickers.

    The list stops above the buttons that some of these screens place along the
    bottom. A screen with other views overrides has_menu_list for those views.
    """
    MENU_LIST_ROW_HEIGHT = 60
    MENU_LIST_TOP = 150
    MENU_LIST_BOTTOM = c.SCREEN_HEIGHT - 120
    MENU_LIST_CLIP_TOP = 100
    MENU_LIST_PAD = 20

    def has_menu_list(self):
        return True

    def layout_menu_list(self, count):
        """Publishes the menu list's clip area and yields (index, y) for visible rows."""
        self.scroll.content_rect = pygame.Rect(0, self.MENU_LIST_CLIP_TOP, c.SCREEN_WIDTH,
                                               self.MENU_LIST_BOTTOM - self.MENU_LIST_CLIP_TOP)
        return self.layout_list_rows(count, self.MENU_LIST_ROW_HEIGHT, self.MENU_LIST_TOP,
                                     pad=self.MENU_LIST_PAD, cull_top=self.MENU_LIST_CLIP_TOP,
                                     cull_bottom=self.MENU_LIST_BOTTOM)

    def add_menu_list(self, rows, on_pick):
        """Builds a centered button for each (label, value) row. A click passes the value to on_pick."""
        for i, y in self.layout_menu_list(len(rows)):
            label, value = rows[i]
            self.add_list_row(Button("centered", y, "new_game", "blue", label, lambda v=value: on_pick(v),
                                     sound_kind="select_sub_category"))

    def additional_events(self, event):
        if self.has_menu_list():
            self.handle_list_scroll(event, content=True)

    def additional_draw(self, surface):
        if self.has_menu_list():
            self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 40, self.MENU_LIST_TOP,
                                     self.MENU_LIST_BOTTOM - self.MENU_LIST_TOP)


class RefreshingMenuListScreen(MenuListScreen):
    """A menu list that can show map_refresh's progress bar over itself.

    map_refresh.refresh_map_directories writes the four refresh values below.
    While it runs, the buttons are hidden and input is ignored.

    A view with no list is a page of ButtonMenuScreen.build_menu_buttons, so its
    title sits where ButtonMenuScreen places it.
    """
    is_refreshing = False
    refresh_total = 0
    refresh_completed = 0
    refresh_status = ""

    @property
    def title_y(self):
        return Screen.title_y if self.has_menu_list() else ButtonMenuScreen.title_y

    @property
    def title_shadow(self):
        return Screen.title_shadow if self.has_menu_list() else ButtonMenuScreen.title_shadow

    def update(self):
        super().update()
        for el in self.elements:
            el.visible = not self.is_refreshing

    def handle_events(self, events):
        if not self.is_refreshing:
            super().handle_events(events)

    def draw(self, surface):
        super().draw(surface)
        if self.is_refreshing:
            turn_progress.draw_simple_refresh_bar(surface, self.refresh_status,
                                                  self.refresh_completed, self.refresh_total)


class FolderListState(Screen):
    """Base for the menus that list folders on disk (saves, custom maps).

    Subclasses point `managed_dir` at a directory and get the rename and delete
    popups for free.
    """

    def __init__(self):
        super().__init__()

    # -- the directory being managed; a property so sub-state screens can swap it
    @property
    def managed_dir(self):
        raise NotImplementedError

    def list_folders(self, directory=None):
        """Lists a directory's entries, creating it first if it is missing."""
        directory = self.managed_dir if directory is None else directory
        if not os.path.exists(directory):
            os.makedirs(directory)
        return os.listdir(directory)

    # ---------------------------------------------------------------- #
    #                         RENAME / DELETE                          #
    # ---------------------------------------------------------------- #

    @staticmethod
    def is_valid_name_char(char):
        return char.isalnum() or char in " _-"

    def start_rename(self, name):
        """Opens the popup that asks for a new name."""
        # ui.dialogs imports this module, so this import must stay local.
        from ui import dialogs

        dialogs.ask_string("Rename", f"Enter a new name for '{name}':",
                           lambda new_name: self.finish_rename(name, new_name),
                           initial=name, is_valid_char=self.is_valid_name_char)

    def finish_rename(self, old_name, new_name):
        """Applies the popup's answer. Cancel gives None, which changes nothing."""
        name = (new_name or "").strip()
        if name and name != old_name:
            old_path = os.path.join(self.managed_dir, old_name)
            new_path = os.path.join(self.managed_dir, name)
            if not os.path.exists(new_path):
                os.rename(old_path, new_path)
                sync_persisted_dir(self.managed_dir)
        self.refresh_ui()

    def start_delete(self, name):
        """Opens the popup that asks the player to confirm the deletion."""
        # ui.dialogs imports this module, so this import must stay local.
        from ui import dialogs

        dialogs.ask_yes_no("Delete", f"Delete '{name}'? This cannot be undone.",
                           lambda confirmed: self.delete_item(name) if confirmed else None)

    def delete_item(self, name):
        path = os.path.join(self.managed_dir, name)
        if os.path.exists(path):
            shutil.rmtree(path)
            sync_persisted_dir(self.managed_dir)
        self.refresh_ui()


class MapOverlayScreen(Screen):
    """Base for screens drawn on top of the live map (claims, peace, trade, nation creation).

    Handles the camera pass-through, panel scrolling and the standard
    map-background sandwich; subclasses only supply draw_content().
    """
    # Alpha of the dimming layer over the map. 0 leaves the map fully visible.
    overlay_alpha = 180
    # Whether wheel/motion over the map feeds pan/zoom input to the camera.
    # The camera still settles each frame either way, so an in-flight zoom
    # finishes smoothly instead of freezing while the panel is open.
    pans_camera = True
    # Whether the wheel scrolls the panel even when the cursor is off it.
    scroll_anywhere = False

    # Panel chrome, the same contract ModalScreen declares -- unpack one of
    # constants' PANEL_THEME_* tuples into the first three. Every subclass used
    # to pass these to ui_bars.draw_modal_box by hand, and then draw its own
    # title underneath, so a panel's look lived in its draw_content body rather
    # than anywhere you could see all of them at once.
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_STYLE = None
    #: Header text drawn inside the panel. Override get_panel_title() instead
    #: for one that names a nation or otherwise changes with the screen.
    PANEL_TITLE = None
    TITLE_PRESET = "heading1"
    TITLE_Y_OFFSET = 15
    #: Whether __init__ centres panel_rect on the screen. False for the panels
    #: that place themselves (the diplomacy overlays sit off-centre so the map
    #: they are about stays visible beside them).
    CENTER_PANEL = True

    def __init__(self, map_screen, panel_rect=None):
        super().__init__()
        self.map_screen = map_screen
        self.player = map_screen.session.player_country
        self.panel_rect = panel_rect
        if panel_rect is not None and self.CENTER_PANEL:
            self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)

    def is_over_ui(self, pos=None):
        """True when the cursor sits on a panel or the top bar rather than the map."""
        pos = pos or pygame.mouse.get_pos()
        rects = (self.panel_rect, self.map_screen.top_bar_rect)
        return any(r and r.collidepoint(pos) for r in rects)

    def additional_events(self, event):
        # Scrollbar grab/drag/release always takes priority over camera panning,
        # so click-to-scroll works the same way it does on the standalone menu screens.
        # content=True also lets the panel's own content be grabbed and dragged.
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and event.button == 1:
            if self.handle_list_scroll(event, content=True):
                return

        if event.type not in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION, pygame.KEYDOWN):
            return

        if event.type == pygame.MOUSEMOTION and (self.scroll.bar_drag
                                                  or self.is_content_dragging()):
            self.handle_list_scroll(event, content=True)
            return

        on_ui = self.is_over_ui()
        if event.type == pygame.MOUSEWHEEL and (on_ui or self.scroll_anywhere):
            self.scroll_by(event)
        elif self.pans_camera:
            self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

    def get_clicked_province(self, mouse_pos):
        return queries.get_clicked_province(mouse_pos, self.map_screen)

    def centered_x(self, size_preset):
        """The x that centers a button of this size in the panel."""
        return self.panel_rect.centerx - c.SIZES[size_preset][0] // 2

    def get_panel_title(self):
        """The header drawn inside the panel, or None for a bare box."""
        return self.PANEL_TITLE

    def draw_panel(self, surface):
        """Draws the bordered panel and its title -- call this from draw_content.

        Wherever a screen draws other things first (the peace screen previews
        the post-treaty map underneath its panel), call this at the point the
        old draw_modal_box call sat, so the layering is unchanged.
        """
        ui_bars.draw_screen_panel(surface, self, self.get_panel_title())

    def update(self):
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def draw_overlay_map(self, surface):
        self.map_screen.draw_clean_map_background(surface)

    def draw(self, surface):
        # Map_Screen.draw_background recomputes its own bg_color from the live
        # camera zoom (see map.py), so this stays color-responsive while
        # zooming even though Map_Screen.update() doesn't run behind a modal.
        self.map_screen.draw_background(surface)
        self.draw_overlay_map(surface)
        if self.overlay_alpha:
            ui_bars.draw_fullscreen_overlay(surface, self.overlay_alpha)

        self.draw_content(surface)

        self.draw_elements(surface)
        self.draw_feedback(surface)

    def draw_content(self, surface):
        """Hook for highlights and panels drawn between the map and the buttons."""
        pass


class EditorOverlayScreen(MapOverlayScreen):
    """Settings shared by the map editor's tool windows.

    The map does not pan behind them, Back returns to the map, and they use the
    modal title style.
    """
    pans_camera = False
    back_state = "MAP"
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    def draw_content(self, surface):
        self.draw_panel(surface)


class EditorFormScreen(EditorOverlayScreen):
    """Editor tool window with one column of text fields and one action button.

    A subclass sets self.fields (a dict of TextField) before it calls refresh_ui
    and implements apply. The field column is placed from the panel center.
    """
    FIELD_CENTER_OFFSET = 0
    FIELD_TOP = 80
    FIELD_GAP = 70
    ACTION_LABEL = "Apply"
    ACTION_COLOR = "green"

    @property
    def listening_for(self):
        return any(field.active for field in self.fields.values())

    def apply(self):
        raise NotImplementedError

    def refresh_ui(self):
        p = self.panel_rect
        for row, field in enumerate(self.fields.values()):
            field.rect.topleft = (p.centerx + self.FIELD_CENTER_OFFSET, p.y + self.FIELD_TOP + row * self.FIELD_GAP)
        self.action_button = Button(self.centered_x("medium"), p.bottom - 55, "medium", self.ACTION_COLOR,
                                    self.ACTION_LABEL, self.apply)
        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            self.action_button,
        ] + list(self.fields.values())


class EditorSliderScreen(EditorOverlayScreen):
    """Editor tool window with labelled sliders, Reset, and Save.

    A subclass returns (slider, low label, high label) rows from slider_rows and
    implements reset and save. Each label sits at one end of its slider.
    """
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    SLIDER_X = 150
    SLIDER_W = 300
    POLE_LABEL_X = 30
    POLE_LABEL_GAP = 14
    POLE_LABEL_Y_OFFSET = -2
    FOOTER_Y_OFFSET = 55
    RESET_X = 30
    SAVE_RIGHT_OFFSET = 230
    RESET_LABEL = "Reset"

    def slider_rows(self):
        raise NotImplementedError

    def reset(self):
        raise NotImplementedError

    def save(self):
        raise NotImplementedError

    def refresh_ui(self):
        p = self.panel_rect
        self.rows = self.slider_rows()
        footer_y = p.bottom - self.FOOTER_Y_OFFSET
        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.x + self.RESET_X, footer_y, "medium", "grey", self.RESET_LABEL, self.reset),
            Button(p.right - self.SAVE_RIGHT_OFFSET, footer_y, "medium", "green", "Save", self.save),
        ] + [slider for slider, _low, _high in self.rows]

    def draw_content(self, surface):
        self.draw_panel(surface)
        small = fonts.get("small")
        for slider, low, high in self.rows:
            y = slider.rect.y + self.POLE_LABEL_Y_OFFSET
            surface.blit(small.render(low, True, c.UI_TEXT_MUTED), (self.panel_rect.x + self.POLE_LABEL_X, y))
            surface.blit(small.render(high, True, c.UI_TEXT_MUTED), (slider.rect.right + self.POLE_LABEL_GAP, y))


class NationListOverlayScreen(EditorOverlayScreen):
    """Standard scrollable picker for the living nations on an editor map.

    Starting economy, politics, AI personality, and research each had the same panel,
    scroll bounds, button wiring, and scrollbar contract. They now only say
    how to label/color one country, what opening it should perform, and any
    header content unique to that tool. Geometry remains class-local so a
    future editor can intentionally choose a different list shape.
    """
    scroll_anywhere = True

    LIST_PANEL_SIZE = (620, 560)
    LIST_ROW_HEIGHT = 40
    LIST_HEADER_HEIGHT = 90
    LIST_BOTTOM_MARGIN = 20
    LIST_SCROLLBAR_WIDTH = 15
    LIST_NOTE_POS = (24, 58)
    #: Explanatory text above the rows, or None for no note.
    LIST_NOTE = None
    #: The screen edit() opens, built as EDIT_SCREEN(map_screen, country_id).
    EDIT_SCREEN = None

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, *self.LIST_PANEL_SIZE))
        self.active_countries = sorted(queries.get_living_nations(map_screen.world.map_data))
        self.refresh_ui()

    def list_header_elements(self):
        """Fixed controls in the panel header, excluding the shared Back button."""
        return []

    def country_button(self, country_id, x, y):
        """Builds the one row that represents ``country_id`` in this tool."""
        raise NotImplementedError

    def edit(self, country_id):
        """Opens EDIT_SCREEN for one country and rebuilds the rows afterward."""
        # screen_runner imports this module, so this import must stay local.
        from ui.navigation.screen_runner import _run_pygame_sub_screen

        _run_pygame_sub_screen(self.map_screen, self.EDIT_SCREEN(self.map_screen, country_id),
                               on_done=self.refresh_ui)

    def draw_list_header(self, surface):
        """Draws LIST_NOTE above the scrolling rows."""
        if self.LIST_NOTE:
            note = fonts.get("small").render(self.LIST_NOTE, True, c.UI_TEXT_MUTED)
            surface.blit(note, (self.panel_rect.x + self.LIST_NOTE_POS[0],
                                self.panel_rect.y + self.LIST_NOTE_POS[1]))

    def refresh_ui(self):

        panel = self.panel_rect
        self.elements = [make_back_button(self.exit_screen, style="map")] + self.list_header_elements()

        row_top = panel.y + self.LIST_HEADER_HEIGHT
        view_h = panel.height - self.LIST_HEADER_HEIGHT - self.LIST_BOTTOM_MARGIN
        row_x = panel.centerx - (c.SIZES["list_row"][0] // 2)
        cull_top = panel.y + self.LIST_HEADER_HEIGHT - 10
        cull_bottom = panel.bottom - self.LIST_BOTTOM_MARGIN
        self.scroll.content_rect = pygame.Rect(panel.x, cull_top, panel.width, cull_bottom - cull_top)

        for index, y in self.layout_list_rows(len(self.active_countries), self.LIST_ROW_HEIGHT,
                                              row_top, view_h=view_h, cull_top=cull_top,
                                              cull_bottom=cull_bottom):
            button = self.country_button(self.active_countries[index], row_x, y)
            button.sound_kind = "select_category"
            self.add_list_row(button)

        self.list_view_h = view_h

    def draw_content(self, surface):
        self.draw_panel(surface)
        self.draw_list_scrollbar(surface, self.panel_rect.right - self.LIST_SCROLLBAR_WIDTH,
                                 self.panel_rect.y + self.LIST_HEADER_HEIGHT,
                                 self.list_view_h, width=self.LIST_SCROLLBAR_WIDTH)
        self.draw_list_header(surface)
