import pygame
import data.constants as c
from data import queries
from ui.bars import ui_bars

def resolve_keybind(state, action, default):
    """Finds a keybind by checking the state, then its map_screen, for a controller."""
    for host in (state, getattr(state, "map_screen", None)):
        controller = getattr(host, "controller", None)
        if controller:
            return controller.keybinds.get(action, default)
    return default

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

class GameState:
    # Screens layered over the map set this; it drives feedback text and keybind lookup.
    map_screen = None
    # Where exit_screen() sends the state machine. None just closes the screen.
    back_state = None
    # Pixels per wheel notch: panels layered on the map, and full-screen menu lists.
    scroll_speed = 30
    list_scroll_speed = 40

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

    def exit_screen(self):
        """Closes this screen, handing off to back_state when one is declared."""
        if self.back_state:
            self.next_state = self.back_state
        self.done = True

    def handle_back_key(self):
        self.exit_screen()

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
                           drag_attr="is_dragging_scrollbar"):
        """Drives a scrollable list: wheel, scrollbar grab, drag and release.

        Track geometry is read off the rect the screen published when it drew
        its scrollbar, so there is nothing to keep in sync by hand. Returns True
        when the event was consumed, so callers can skip their own handling.
        """
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_by(event, attr, limit_attr, self.list_scroll_speed if speed is None else speed)
            return True

        track = getattr(self, track_attr, None)
        if not track:
            return False

        def snap_to(mouse_y):
            self.snap_scroll(mouse_y, track.top, track.height, attr, limit_attr)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            handle = getattr(self, handle_attr, None)
            if handle and handle.collidepoint(event.pos):
                setattr(self, drag_attr, True) # Grabbing the handle drags from where it sits
                return True
            if track.collidepoint(event.pos):
                setattr(self, drag_attr, True) # Clicking the bare track jumps to that spot
                snap_to(event.pos[1])
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            setattr(self, drag_attr, False)
        elif event.type == pygame.MOUSEMOTION and getattr(self, drag_attr, False):
            snap_to(event.pos[1])
            return True

        return False

    def refresh_ui(self):
        pass

    def draw(self, surface):
        # 1. Fill background or draw background image
        if self.bg_image_path:
            bg_img = ui_bars.get_ui_image(self.bg_image_path, directory=c.BACKGROUNDS_DIR)
            if bg_img.get_size() != surface.get_size():
                bg_img = pygame.transform.scale(bg_img, surface.get_size())
            surface.blit(bg_img, (0, 0))
        else:
            # Pull from constants instead of hardcoding
            surface.fill(getattr(self, 'bg_color', c.DEFAULT_BG_COLOR))

        # 2. Draw the specific screen content (Map, UI Bars)
        # Moving this BEFORE elements fixes the layering
        self.additional_draw(surface)

        # 3. Draw UI buttons on the very top
        for el in self.elements:
            el.draw(surface)

        # 4. Green status text, for every screen that hangs off the map
        self.draw_feedback(surface)

    def draw_feedback(self, surface):
        if self.map_screen:
            from ui.information import feedback_text
            feedback_text.draw_feedback(self.map_screen, surface)

    def additional_draw(self, surface):
        pass

    def update(self):
        pass

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
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and event.button == 1:
            if self.handle_list_scroll(event):
                return

        if event.type not in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
            return

        if event.type == pygame.MOUSEMOTION and getattr(self, "is_dragging_scrollbar", False):
            self.handle_list_scroll(event)
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
        surface.fill(self.map_screen.bg_color)
        self.map_screen.draw_clean_map_background(surface)
        if self.overlay_alpha:
            ui_bars.draw_fullscreen_overlay(surface, self.overlay_alpha)

        self.draw_content(surface)

        for el in self.elements:
            if el.visible:
                el.draw(surface)
        self.draw_feedback(surface)

    def draw_content(self, surface):
        """Hook for highlights and panels drawn between the map and the buttons."""
        pass
