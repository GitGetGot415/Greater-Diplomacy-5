"""Scroll position, limits, scrollbar geometry, and drag state for one pane."""

from ui.bars import ui_bars


class ScrollState:
    """One scrolling pane on a screen.

    `value` runs from `limit` (zero or negative) up to 0 and is added to the
    content's position, so the content moves up as the value falls. `axis` is
    "y" for a vertical pane and "x" for a horizontal one. `track` and `handle`
    are the scrollbar rects from the last draw. `bar_drag` and `grab_offset`
    follow a scrollbar drag, and `content_drag` is None or [origin, armed] for a
    drag on the content itself. `content_rect` is where that content drag starts,
    and `guard` is the click guard for rows cropped by the pane's edge.

    A pane with its own range, such as a list measured up from its newest row,
    keeps `value` on that range and passes its bounds to the drag helpers.
    """

    def __init__(self, axis="y"):
        self.axis = axis
        self.value = 0
        self.limit = 0
        self.track = None
        self.handle = None
        self.content_rect = None
        self.guard = None
        self.bar_drag = False
        self.grab_offset = 0
        self.content_drag = None

    @property
    def index(self):
        """The position component this pane scrolls along."""
        return 0 if self.axis == "x" else 1

    def scroll_by(self, delta):
        """Move the offset and keep it inside the pane's range."""
        self.value = max(self.limit, min(0, self.value + delta))

    def cancel(self):
        """Release scrollbar and content drags."""
        self.bar_drag = False
        self.content_drag = None

    def snap(self, position):
        """Move the handle under the pointer, keeping the point where it was grabbed."""
        point = position[self.index] - self.grab_offset
        if self.axis == "x":
            self.value = -ui_bars.calculate_scroll_snap_horizontal(
                point, 0, -self.limit, self.track.left, self.track.width)
        else:
            self.value = ui_bars.calculate_scroll_snap(point, self.limit, self.track.top, self.track.height)

    def press_scrollbar(self, position):
        """Start a scrollbar drag. Returns True when the press hit the scrollbar.

        A press on the handle keeps the grab point, so the first motion does not
        jump. A press on the bare track centres the handle on the pointer.
        """
        if not self.track:
            return False
        if self.handle and self.handle.collidepoint(position):
            self.grab_offset = position[self.index] - self.handle.center[self.index]
            self.bar_drag = True
            return True
        if self.track.collidepoint(position):
            self.grab_offset = 0
            self.bar_drag = True
            self.snap(position)
            return True
        return False

    def draw_scrollbar(self, surface, x, y, length, width=15):
        """Draw the scrollbar and keep its rects for input. Returns (track, handle)."""
        if self.axis == "x":
            self.track, self.handle = ui_bars.draw_standard_scrollbar_horizontal(
                surface, -self.value, 0, -self.limit, x, y, length, width)
        else:
            self.track, self.handle = ui_bars.draw_standard_scrollbar(
                surface, self.value, self.limit, x, y, length, width)
        return self.track, self.handle


class ScrollPaneOwner:
    """Keeps an object's named ScrollStates. Screens and the map own their panes this way."""

    @property
    def scrolls(self):
        """Every scrolling pane, by name."""
        scrolls = self.__dict__.get("_scrolls")
        if scrolls is None:
            scrolls = self.__dict__["_scrolls"] = {}
        return scrolls

    def scroll_state(self, name, axis="y"):
        """The named pane's ScrollState, created on first use."""
        state = self.scrolls.get(name)
        if state is None:
            state = self.scrolls[name] = ScrollState(axis)
        return state
