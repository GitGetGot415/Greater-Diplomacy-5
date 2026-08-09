"""Mixin for screens that show several independently scrolling lists at once.

Five screens -- the diplomacy editor, the historical-leaders editor, the
scripted-events editor, the asset viewer and the music player -- each grew their
own copy of the same four pieces: a table of per-pane scroll attribute names, a
row-layout wrapper, a wheel router, and a draw_elements that clips each pane to
its own rect. Three of the copies were byte-identical.

They had also drifted in two ways worth naming, since this mixin settles both:

- Whether row layout forwards view_h to layout_list_rows. It must not; see
  pane_rows() below.
- How the wheel picks a pane. The editors hit-test the pane rects; the asset
  viewer and music player compared the mouse x against a hardcoded column
  boundary, which sends a notch over a pane's gutter to the wrong list.

Kept dependency-free apart from pygame and data.constants so it stays a leaf in
the import graph -- it is a mixin rather than a GameState subclass precisely so
it doesn't have to import gameState and can be combined with anything.
"""

import pygame

import data.constants as c


class ScrollPanes:
    """Adds multi-pane scrolling to any GameState subclass.

    A screen supplies pane_rects(); everything else is derived. Buttons are
    tagged with `el.pane = "<name>"` to bind them to a pane, and anything
    untagged is treated as fixed chrome drawn on top.
    """

    #: Default row height for pane_rows(), overridable per screen.
    ROW_HEIGHT = 34

    def pane_rects(self):
        """{pane_name: rect} for every scrolling region currently on screen.

        Screens with a fixed layout can just return a dict literal; the editors
        rebuild theirs in refresh_ui and return that.
        """
        return getattr(self, "regions", {})

    def scroll_attrs(self, name):
        """The per-pane scroll state attribute names.

        Underscore-prefixed so a pane can never shadow a method: a pane called
        "events" would otherwise publish its scrollbar handle as
        self.handle_events and overwrite GameState.handle_events.
        """
        return {"attr": f"_scroll_{name}", "limit_attr": f"_max_{name}",
                "track_attr": f"_track_{name}", "handle_attr": f"_handle_{name}",
                "drag_attr": f"_drag_{name}", "content_rect_attr": f"_content_{name}"}

    def pane_scroll(self, name):
        return getattr(self, f"_scroll_{name}", 0)

    def pane_scroll_limit(self, name):
        return getattr(self, f"_max_{name}", 0)

    def pane_rows(self, name, count, top, view_h, row_h=None):
        """Yields (index, y) for the rows of `name` that are worth drawing.

        view_h is deliberately NOT forwarded to layout_list_rows. Passing it
        would let layout_list_rows compute max_scroll against the full (taller)
        view_h while cull_bottom -- which is what actually gates clicks -- is
        shorter by row_h-2, leaving the last row a permanent sliver short of
        being clickable once fully scrolled into view. Omitting it makes the
        function derive its own view_h from cull_bottom instead, so the scroll
        limit and the clickable boundary always agree.
        """
        row_h = row_h or self.ROW_HEIGHT
        attrs = self.scroll_attrs(name)
        return self.layout_list_rows(count, row_h, top,
                                     cull_top=top - 1, cull_bottom=top + view_h - row_h + 2,
                                     attr=attrs["attr"], limit_attr=attrs["limit_attr"],
                                     guard_attr=f"_guard_{name}")

    def add_pane_row(self, name, element):
        """Tags an element as belonging to `name` and registers it."""
        element.pane = name
        element.is_scrollable = True
        element.click_guard = getattr(self, f"_guard_{name}", None)
        self.elements.append(element)
        return element

    def route_pane_scroll(self, event, rects=None):
        """Wheel goes to whichever pane the cursor is over; scrollbar presses and
        drags are offered to every pane, which each ignore what is not theirs.

        Returns True when the event was consumed.
        """
        rects = self.pane_rects() if rects is None else rects
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            for name, rect in rects.items():
                if rect and rect.collidepoint(pos):
                    self.handle_list_scroll(event, **self.scroll_attrs(name))
                    return True
            return False

        for name in rects:
            if self.handle_list_scroll(event, **self.scroll_attrs(name)):
                return True
        return False

    def draw_panes(self, surface, rects=None, extra_draw=None):
        """Draws each pane's rows clipped to its own rect, then the fixed chrome.

        `extra_draw` is an optional {pane_name: callable(surface)} for panes that
        render something other than plain buttons inside the same clip region --
        the leaders editor draws its timeline cards that way.
        """
        from ui.bars import ui_bars  # deferred: keeps this module a leaf

        rects = self.pane_rects() if rects is None else rects
        for name, rect in rects.items():
            if not rect:
                continue
            scroll, limit = self.pane_scroll(name), self.pane_scroll_limit(name)
            with ui_bars.clip_scroll_region(surface, rect,
                                            draw_top=scroll != 0, draw_bottom=scroll > limit):
                for el in self.elements:
                    if getattr(el, "pane", None) == name:
                        el.draw(surface)
                if extra_draw and name in extra_draw:
                    extra_draw[name](surface)

        for el in self.elements:
            if not getattr(el, "pane", None):
                el.draw(surface)

    def draw_pane_scrollbar(self, surface, name, track_x, track_y, view_h, width=15):
        """Scrollbar for one pane, wired to the same attributes as its rows."""
        return self.draw_list_scrollbar(surface, track_x, track_y, view_h, width=width,
                                        **self.scroll_attrs(name))

    def pane_wheel_step(self):
        return c.SCROLL_STEP
