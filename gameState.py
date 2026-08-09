import os
import shutil
import pygame
import data.constants as c
from data import queries
from data.platform import sync_persisted_dir
from ui.bars import ui_bars

def resolve_keybind(state, action, default):
    """Resolves a rebindable action's pygame key code.

    Delegates to the persisted settings rather than state.controller -- most
    screens never get a controller reference wired up, so that chain was
    silently falling back to `default` almost everywhere.
    """
    return queries.get_keybind(action, default)

def dispatch_global_keys(state, event):
    """Routes BACK/ORDERS presses to a state's handlers.

    Shared by the main loop and the blocking sub-screen loop so no individual
    screen has to re-resolve the keybinds itself.
    """
    if event.type != pygame.KEYDOWN or getattr(state, "listening_for", None):
        return
    if event.key == resolve_keybind(state, "BACK", pygame.K_ESCAPE):
        state.handle_back_key()
    elif event.key == resolve_keybind(state, "ORDERS", pygame.K_q):
        if hasattr(state, "handle_orders_key"):
            state.handle_orders_key()

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

class GameState:
    # Screens layered over the map set this; it drives feedback text and keybind lookup.
    map_screen = None
    # Where exit_screen() sends the state machine. None just closes the screen.
    back_state = None
    # Pixels per wheel notch: panels layered on the map, and full-screen menu lists.
    scroll_speed = 30
    list_scroll_speed = 40

    # Centred header drawn under the buttons. Set `title` for a fixed string or
    # override get_title() for one that changes with the screen's sub-state.
    title = None
    title_y = 40
    title_preset = "heading1"
    title_shadow = False

    # Scroll state for the standard vertical list. Declared here so no screen
    # has to re-initialise the same five attributes; scroll_by/handle_list_scroll
    # write instance values over these class defaults on first use.
    scroll_y = 0
    max_scroll = 0
    is_dragging_scrollbar = False
    scroll_track_rect = None
    scroll_handle_rect = None

    # Content click-and-drag state (see handle_content_drag) and the rect/guard
    # a scrollable list publishes for it -- kept separate from the scrollbar's
    # own drag state above since both gestures can be live on the same list.
    scroll_content_rect = None
    content_drag_state = None
    scroll_click_guard = None

    def __init__(self):
        self.done = False
        self.next_state = None
        self.elements = []
        self.bg_image_path = None # Added support for generic background images

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        pass

    def go_to(self, state):
        """Hands the state machine off to another screen and closes this one."""
        self.next_state = state
        self.done = True

    def exit_screen(self):
        """Closes this screen, handing off to back_state when one is declared."""
        if self.back_state:
            self.next_state = self.back_state
        self.done = True

    def handle_back_key(self):
        self.exit_screen()

    def content_drag_attr_name(self, attr="scroll_y"):
        """Name of the per-pane content-drag state attribute for a given scroll
        attr. Content-drag state must be keyed per-pane (not a single shared
        `content_drag_state`) so a screen with multiple independent scrolling
        panes -- e.g. the music player's album/track columns, or view_assets'
        folder/file/preview columns -- doesn't have a drag armed in one pane's
        content area picked up by a different pane on the next MOUSEMOTION."""
        return f"_content_drag_state_{attr}"

    def is_content_dragging(self, attr="scroll_y"):
        """Whether a content-drag (see handle_content_drag) is currently armed
        for the given pane's scroll attr. Callers that gate MOUSEMOTION routing
        on drag state (rather than going through handle_list_scroll every frame)
        should use this instead of reading `content_drag_state` directly."""
        return getattr(self, self.content_drag_attr_name(attr), None) is not None

    def scroll_by(self, event, attr="scroll_y", limit_attr="max_scroll", speed=None):
        """Applies a wheel event to a negative-range scroll offset and clamps it."""
        step = event.y * (self.scroll_speed if speed is None else speed)
        limit = getattr(self, limit_attr, 0)
        setattr(self, attr, max(limit, min(0, getattr(self, attr, 0) + step)))
        self.refresh_ui()

    def snap_scroll(self, mouse_y, track_y, view_h, attr="scroll_y", limit_attr="max_scroll"):
        """Jumps a scroll offset to wherever the scrollbar handle was dragged."""
        setattr(self, attr, ui_bars.calculate_scroll_snap(mouse_y, getattr(self, limit_attr, 0), track_y, view_h))
        self.refresh_ui()

    def handle_list_scroll(self, event, speed=None, attr="scroll_y", limit_attr="max_scroll",
                           track_attr="scroll_track_rect", handle_attr="scroll_handle_rect",
                           drag_attr="is_dragging_scrollbar", content_rect_attr=None):
        """Drives a scrollable list: wheel, scrollbar grab, drag and release.

        Track geometry is read off the rect the screen published when it drew
        its scrollbar, so there is nothing to keep in sync by hand. Returns True
        when the event was consumed, so callers can skip their own handling.

        Pass `content_rect_attr` (the same rect the list clips to) to also let
        the user grab the list body itself and drag it -- see handle_content_drag.
        """
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_by(event, attr, limit_attr, self.list_scroll_speed if speed is None else speed)
            return True

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            # A grab on the handle/track and a content-drag can both arm on the
            # same mouse-down when the content rect overlaps the scrollbar (the
            # usual case). Clear the handle/track flag here, unconditionally,
            # before the content-drag branch below can return early and skip it
            # -- otherwise it's left stuck True and the handle free-follows the
            # mouse on every later motion until another drag happens to mask it.
            setattr(self, drag_attr, False)

        track = getattr(self, track_attr, None)
        handle = getattr(self, handle_attr, None)
        grabbing_scrollbar = (event.type == pygame.MOUSEBUTTONDOWN and track
                              and ((handle and handle.collidepoint(event.pos))
                                   or track.collidepoint(event.pos)))

        # invert=True here because this list also has a real scrollbar (below):
        # handle_content_drag defaults to touch-pan feel (drag down reveals
        # earlier rows), but the scrollbar/wheel on the same scroll_y move the
        # opposite way (down reveals later rows). Grabbing the list body has to
        # agree with dragging its own scrollbar, not fight it.
        #
        # But a click that lands on the scrollbar itself must never be allowed
        # to arm (or keep driving) the content-drag: content-drag moves scroll_y
        # 1:1 with mouse pixels in *content* space, while the handle is supposed
        # to snap to the mouse's ratio *along the track*. Since the content is
        # usually much taller than the track, letting content-drag win once it
        # crosses its arm threshold makes the handle crawl far slower than the
        # mouse instead of tracking it -- so it visibly falls behind the longer
        # you drag. Clearing content_drag_state here keeps the two gestures from
        # fighting over the same motion events.
        #
        # Keyed off `attr` (unique per pane) rather than a single shared
        # "content_drag_state" -- a screen with more than one scrolling pane
        # (e.g. the music player's album/track columns) would otherwise have
        # every pane's content-drag arm/read the *same* attribute, so a drag
        # started in one pane's content area gets picked up by whichever pane
        # happens to be checked first on the next MOUSEMOTION, moving a
        # completely different scrollbar than the one under the mouse.
        content_drag_attr = self.content_drag_attr_name(attr)
        if grabbing_scrollbar or getattr(self, drag_attr, False):
            setattr(self, content_drag_attr, None)
        elif content_rect_attr and self.handle_content_drag(event, attr, limit_attr, content_rect_attr,
                                                             drag_attr=content_drag_attr, invert=True):
            return True

        if not track:
            return False

        def snap_to(mouse_y):
            self.snap_scroll(mouse_y, track.top, track.height, attr, limit_attr)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if handle and handle.collidepoint(event.pos):
                setattr(self, drag_attr, True) # Grabbing the handle drags from where it sits
                return True
            if track.collidepoint(event.pos):
                setattr(self, drag_attr, True) # Clicking the bare track jumps to that spot
                snap_to(event.pos[1])
                return True
        elif event.type == pygame.MOUSEMOTION and getattr(self, drag_attr, False):
            snap_to(event.pos[1])
            return True

        return False

    def _cancel_pressed_elements(self):
        """Un-arms any button caught mid-press once a drag is confirmed, so the
        eventual mouse-up doesn't also fire its click."""
        for el in self.elements:
            if getattr(el, "is_pressed", False):
                el.is_pressed = False

    def handle_content_drag(self, event, attr="scroll_y", limit_attr="max_scroll",
                            rect_attr="scroll_content_rect", drag_attr="content_drag_state",
                            lo=None, hi=None, threshold=6, invert=False, refresh=True, axis="y"):
        """Lets the user grab a scrollable region's own content and drag it,
        alongside whatever wheel/scrollbar-handle scrolling it already has.

        A small pixel threshold has to be crossed before a press is treated as
        a drag (and any button pressed under the cursor gets un-armed), so an
        ordinary click on a button inside the list still registers normally.
        Content tracks the mouse 1:1 via `event.rel`, like a touch/trackpad pan.
        `axis="x"` drags horizontally (a timeline) instead of the usual vertical list.

        `lo`/`hi` bound the resulting value; by default `hi` is 0 and `lo` is
        the list's own `max_scroll`-style limit (the mixin's usual negative-range
        convention where the offset is added to a row's y). Pass explicit bounds
        for screens using a 0..max convention instead -- and if that convention
        *subtracts* the offset from content's y (as the map HUD panels do), pass
        `invert=True` so dragging down still pulls content down, not up.
        Pass `refresh=False` for a screen whose `update()` already repositions
        scrolled elements every frame off `attr` alone (e.g. a base_y + scroll_y
        offset), so a full refresh_ui() rebuild isn't needed on every drag pixel.
        Returns True when the event was consumed as a drag.
        """
        rect = getattr(self, rect_attr, None)
        if not rect:
            return False

        idx = 0 if axis == "x" else 1
        state = getattr(self, drag_attr, None)  # None, or [origin, armed]

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and rect.collidepoint(event.pos):
            setattr(self, drag_attr, [event.pos[idx], False])
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and state is not None:
            setattr(self, drag_attr, None)
            return state[1]
        if event.type == pygame.MOUSEMOTION and state is not None:
            origin, armed = state
            if not armed:
                if abs(event.pos[idx] - origin) < threshold:
                    return False
                armed = state[1] = True
                self._cancel_pressed_elements()
            limit = getattr(self, limit_attr, 0)
            low = limit if lo is None else lo
            high = 0 if hi is None else hi
            delta = -event.rel[idx] if invert else event.rel[idx]
            setattr(self, attr, max(low, min(high, getattr(self, attr, 0) + delta)))
            if refresh:
                self.refresh_ui()
            return True

        return False

    def refresh_ui(self):
        pass

    # ---------------------------------------------------------------- #
    #                     STANDARD VERTICAL LISTS                      #
    # ---------------------------------------------------------------- #

    def layout_list_rows(self, count, row_h, top, view_h=None, pad=0,
                         cull_top=100, cull_bottom=None,
                         attr="scroll_y", limit_attr="max_scroll",
                         guard_attr="scroll_click_guard"):
        """Sets the scroll limit for a list and yields (index, y) for visible rows.

        Every folder/scenario list in the menus is built this way: derive the
        scroll floor from the total content height, then walk the rows applying
        the offset. A row is included as soon as any part of it overlaps
        [cull_top, cull_bottom], not just its top corner, so pair this with
        `ui_bars.clip_scroll_region` (or a manual set_clip at the same bounds)
        around wherever the row actually gets drawn -- otherwise a row that's
        only partially in view will render uncropped past the boundary.

        Also publishes `guard_attr`: a callable a scrolled button/field can set
        as its `click_guard` so a click landing in that cropped sliver (still
        inside the row's own rect, but outside the visible boundary) doesn't
        fire.
        """
        if cull_bottom is None:
            cull_bottom = c.SCREEN_HEIGHT - 50
        if view_h is None:
            # Derived from where rows actually get culled, not a magic constant --
            # keeps max_scroll in lockstep with wherever the caller's clip rect
            # ends, so the last row can always be scrolled fully into view instead
            # of stopping short of the boundary it's drawn against.
            view_h = cull_bottom - top

        setattr(self, limit_attr, min(0, view_h - (count * row_h) - pad))
        scroll = getattr(self, attr, 0)
        setattr(self, guard_attr, lambda: cull_top <= pygame.mouse.get_pos()[1] <= cull_bottom)

        for i in range(count):
            y = top + (i * row_h) + scroll
            if y + row_h > cull_top and y < cull_bottom:
                yield i, y

    def draw_list_scrollbar(self, surface, track_x, track_y, view_h, width=15,
                            attr="scroll_y", limit_attr="max_scroll",
                            track_attr="scroll_track_rect", handle_attr="scroll_handle_rect",
                            drag_attr=None, content_rect_attr=None):
        """Draws the list scrollbar and publishes its rects for handle_list_scroll.

        Accepts (and ignores) drag_attr/content_rect_attr so a screen can keep
        one dict of attribute names and hand it to both this and handle_list_scroll.
        """
        track, handle = ui_bars.draw_standard_scrollbar(
            surface, getattr(self, attr, 0), getattr(self, limit_attr, 0),
            track_x, track_y, view_h, width
        )
        setattr(self, track_attr, track)
        setattr(self, handle_attr, handle)
        return track, handle

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
            self.draw_checkerboard_background(surface, getattr(self, 'bg_color', c.DEFAULT_BG_COLOR))

    def draw_checkerboard_background(self, surface, base_color):
        # Draw the tile in a grid slightly larger than the screen, offset by a
        # time-based amount that grows down and to the right. Since the tile
        # is seamless, wrapping the offset back to 0 every tile-length makes
        # the motion loop forever with no seam.
        tile = ui_bars.get_checkerboard_tile(base_color)
        tile_w, tile_h = tile.get_size()

        elapsed = pygame.time.get_ticks() / 1000.0
        offset_x = int((elapsed * c.CHECKERBOARD_SCROLL_SPEED) % tile_w)
        offset_y = int((elapsed * c.CHECKERBOARD_SCROLL_SPEED) % tile_h)

        start_x = -offset_x - tile_w
        start_y = -offset_y - tile_h
        for y in range(start_y, surface.get_height() + tile_h, tile_h):
            for x in range(start_x, surface.get_width() + tile_w, tile_w):
                surface.blit(tile, (x, y))

    def draw(self, surface):
        # 1. Fill background or draw background image
        self.draw_background(surface)

        # 2. Centred header, then the specific screen content (Map, UI Bars)
        # Keeping both BEFORE elements fixes the layering
        self.draw_title(surface)
        self.additional_draw(surface)

        # 3. Draw UI buttons on the very top. Anything a screen marked
        # is_scrollable (built inside a layout_list_rows loop) is cropped to
        # scroll_content_rect and drawn last, so it's cleanly cut off at that
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

        if not scrollable:
            return

        if self.scroll_content_rect:
            with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                            draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
                for el in scrollable:
                    el.draw(surface)
        else:
            for el in scrollable:
                el.draw(surface)

    def draw_feedback(self, surface):
        if self.map_screen:
            from ui.information import feedback_text
            feedback_text.draw_feedback(self.map_screen, surface)

    def additional_draw(self, surface):
        pass

    def update(self):
        pass

class FolderListState(GameState):
    """Base for the menus that list folders on disk (saves, custom maps).

    Subclasses point `managed_dir` at a directory and get the inline rename
    box, the delete confirmation prompt and their keyboard handling for free.
    Both were previously reimplemented per screen with the same layout and the
    same Enter/Escape contract, just different attribute names.
    """
    # Geometry of the rename box, relative to the row being renamed.
    rename_box_size = (300, 50)
    # Size of the centred "Delete X?" confirmation popup.
    delete_popup_size = (500, 200)

    def __init__(self):
        super().__init__()
        self.renaming_item = None
        self.deleting_item = None
        self.new_name_text = ""

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

    def start_rename(self, name):
        self.renaming_item = name
        self.new_name_text = name
        self.refresh_ui()

    def finish_rename(self):
        name = self.new_name_text.strip()
        if name and name != self.renaming_item:
            old_path = os.path.join(self.managed_dir, self.renaming_item)
            new_path = os.path.join(self.managed_dir, name)
            if not os.path.exists(new_path):
                os.rename(old_path, new_path)
                sync_persisted_dir(self.managed_dir)
        self.cancel_rename()

    def cancel_rename(self):
        self.renaming_item = None
        self.refresh_ui()

    def start_delete(self, name):
        self.deleting_item = name
        self.refresh_ui()

    def confirm_delete(self):
        if self.deleting_item:
            path = os.path.join(self.managed_dir, self.deleting_item)
            if os.path.exists(path):
                shutil.rmtree(path)
                sync_persisted_dir(self.managed_dir)
        self.cancel_delete()

    def cancel_delete(self):
        self.deleting_item = None
        self.refresh_ui()

    def handle_name_prompt_event(self, event):
        """Feeds an event to whichever prompt is open. True means it was consumed."""
        if self.renaming_item:
            from ui_elements import process_text_input
            is_valid_char = lambda ch: ch.isalnum() or ch in " _-"
            self.new_name_text, status = process_text_input(event, self.new_name_text,
                                                           validation_func=is_valid_char)
            if status == "SUBMIT":
                self.finish_rename()
            elif status == "CANCEL":
                self.cancel_rename()
            return True

        if self.deleting_item:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.confirm_delete()
                elif event.key == resolve_keybind(self, "BACK", pygame.K_ESCAPE):
                    self.cancel_delete()
            return True

        return False

    def is_row_hidden(self, name):
        """True while a row is replaced by the rename box or the delete prompt."""
        return name in (self.renaming_item, self.deleting_item)

    # ---------------------------------------------------------------- #
    #                            RENDERING                             #
    # ---------------------------------------------------------------- #

    def draw_rename_box(self, surface, x, y):
        """Draws the inline name-entry box in place of the row being renamed."""
        from map_logic.rendering.font_manager import fonts
        input_rect = pygame.Rect(x, y, *self.rename_box_size)
        pygame.draw.rect(surface, (100, 100, 100), input_rect)
        pygame.draw.rect(surface, (255, 255, 255), input_rect, 2)

        txt_surf = fonts.get("heading2").render(self.new_name_text + "|", True, (255, 255, 255))
        surface.blit(txt_surf, (input_rect.x + 10, input_rect.y + 10))

        instr = fonts.get("normal").render("Enter: Save | Esc: Cancel", True, c.UI_TEXT_LIGHT)
        surface.blit(instr, (input_rect.x, input_rect.y - 25))

    def draw_delete_confirm(self, surface, center=None):
        """Dims the screen and asks for Enter/Escape on the pending deletion."""
        from map_logic.rendering.font_manager import fonts
        ui_bars.draw_fullscreen_overlay(surface, 180)

        pop_rect = pygame.Rect((0, 0), self.delete_popup_size)
        pop_rect.center = center or (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        ui_bars.draw_modal_box(surface, pop_rect, bg_color=(60, 20, 20),
                               border_color=(255, 50, 50), border_width=3)

        msg = fonts.get("heading2").render(f"Delete '{self.deleting_item}'?", True, (255, 255, 255))
        surface.blit(msg, msg.get_rect(center=(pop_rect.centerx, pop_rect.centery - 25)))

        sub_msg = fonts.get("normal").render("Press Enter to Confirm or Esc to Cancel", True, c.UI_TEXT_LIGHT)
        surface.blit(sub_msg, sub_msg.get_rect(center=(pop_rect.centerx, pop_rect.centery + 25)))

class MapOverlayScreen(GameState):
    """Base for screens drawn on top of the live map (claims, peace, trade, puppets...).

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

    def __init__(self, map_screen, panel_rect=None):
        super().__init__()
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.panel_rect = panel_rect
        self.scroll_y = 0
        self.max_scroll = 0

    def is_over_ui(self, pos=None):
        """True when the cursor sits on a panel or the top bar rather than the map."""
        pos = pos or pygame.mouse.get_pos()
        rects = (self.panel_rect, getattr(self.map_screen, "top_bar_rect", None))
        return any(r and r.collidepoint(pos) for r in rects)

    def additional_events(self, event):
        # Scrollbar grab/drag/release always takes priority over camera panning,
        # so click-to-scroll works the same way it does on the standalone menu screens.
        # content_rect_attr also lets the panel's own content be grabbed and dragged.
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and event.button == 1:
            if self.handle_list_scroll(event, content_rect_attr="scroll_content_rect"):
                return

        if event.type not in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
            return

        if event.type == pygame.MOUSEMOTION and (getattr(self, "is_dragging_scrollbar", False)
                                                  or self.is_content_dragging()):
            self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")
            return

        on_ui = self.is_over_ui()
        if event.type == pygame.MOUSEWHEEL and (on_ui or self.scroll_anywhere):
            self.scroll_by(event)
        elif self.pans_camera:
            self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

    def get_clicked_province(self, mouse_pos):
        return queries.get_clicked_province(mouse_pos, self.map_screen)

    def update(self):
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def draw(self, surface):
        # Map_Screen.draw_background recomputes its own bg_color from the live
        # camera zoom (see map.py), so this stays color-responsive while
        # zooming even though Map_Screen.update() doesn't run behind a modal.
        self.map_screen.draw_background(surface)
        self.map_screen.draw_clean_map_background(surface)
        if self.overlay_alpha:
            ui_bars.draw_fullscreen_overlay(surface, self.overlay_alpha)

        self.draw_content(surface)

        self.draw_elements(surface)
        self.draw_feedback(surface)

    def draw_content(self, surface):
        """Hook for highlights and panels drawn between the map and the buttons."""
        pass
