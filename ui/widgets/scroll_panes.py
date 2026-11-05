"""Mixin for screens that show several independently scrolling lists at once.

Five screens -- the diplomacy editor, the historical-leaders editor, the
scripted-events editor, the asset viewer and the music player -- each grew their
own copy of the same four pieces: a table of per-pane scroll attribute names, a
row-layout wrapper, a wheel router, and a draw_elements that clips each pane to
its own rect. Three of the copies were byte-identical.

Row layout, clipping and click guards share the full pane height, so partially
visible rows slide behind its edges. Wheel routing hit-tests pane rects rather
than a column boundary, so a notch over a gutter cannot scroll the wrong list.

Kept dependency-free apart from pygame and data.constants so it stays a leaf in
the import graph -- it is a mixin rather than a Screen subclass precisely so
it doesn't have to import game_state and can be combined with anything.
"""

import pygame


from ui.bars import ui_bars


class ScrollPanes:
    """Adds multi-pane scrolling to any Screen subclass.

    A screen supplies pane_rects(); everything else is derived. Buttons are
    tagged with `el.pane = "<name>"` to bind them to a pane, and anything
    untagged is treated as fixed chrome drawn on top.
    """

    regions = {}

    #: Default row height for pane_rows(), overridable per screen.
    ROW_HEIGHT = 34

    def pane_rects(self):
        """{pane_name: rect} for every scrolling region currently on screen.

        Screens with a fixed layout can just return a dict literal; the editors
        rebuild theirs in refresh_ui and return that.
        """
        return self.regions

    def scroll_attrs(self, name):
        """The per-pane scroll state attribute names.

        Underscore-prefixed so a pane can never shadow a method: a pane called
        "events" would otherwise publish its scrollbar handle as
        self.handle_events and overwrite Screen.handle_events.
        """
        return {"attr": f"_scroll_{name}", "limit_attr": f"_max_{name}",
                "track_attr": f"_track_{name}", "handle_attr": f"_handle_{name}",
                "drag_attr": f"_drag_{name}", "content_rect_attr": f"_content_{name}"}

    def pane_scroll(self, name):
        return getattr(self, f"_scroll_{name}", 0)

    def pane_scroll_limit(self, name):
        return getattr(self, f"_max_{name}", 0)

    def pane_scroll_axis(self, name):
        """Screens can opt individual panes into horizontal scrolling."""
        return "y"

    def pane_rows(self, name, count, top, view_h, row_h=None):
        """Yields (index, y) for the rows of `name` that are worth drawing.

        Use the full clipping region for row inclusion, clicks and the scroll
        limit. Subtracting a row height here makes rows pop out before they
        have finished sliding behind the bottom edge.
        """
        row_h = row_h or self.ROW_HEIGHT
        attrs = self.scroll_attrs(name)
        return self.layout_list_rows(count, row_h, top, view_h=view_h,
                                     cull_top=top, cull_bottom=top + view_h,
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
                    self.handle_list_scroll(event, axis=self.pane_scroll_axis(name),
                                            **self.scroll_attrs(name))
                    return True
            return False

        for name in rects:
            if self.handle_list_scroll(event, axis=self.pane_scroll_axis(name),
                                       **self.scroll_attrs(name)):
                return True
        return False

    def draw_panes(self, surface, rects=None, backdrops=None, foregrounds=None):
        """Draws each pane's rows clipped to its own rect, then the fixed chrome.

        `backdrops` is an optional {pane_name: callable(surface)} drawn inside
        the clip region but *underneath* that pane's elements -- row striping,
        card frames and the like, which have to crop with the widgets sitting on
        them but must not paint over them.

        `foregrounds` is the mirror of it, drawn inside the same clip region but
        *over* the elements. That is what a row made of more than a text label
        needs -- a flag, a line of stat icons -- since a Button can only render
        one string and the decoration has to crop with the row it belongs to.
        """
        # ui_bars owns clipping and scroll indicators for every pane.

        rects = self.pane_rects() if rects is None else rects
        for name, rect in rects.items():
            if not rect:
                continue
            scroll, limit = self.pane_scroll(name), self.pane_scroll_limit(name)
            with ui_bars.clip_scroll_region(surface, rect,
                                            draw_top=scroll != 0, draw_bottom=scroll > limit):
                if backdrops and name in backdrops:
                    backdrops[name](surface)
                for el in self.elements:
                    if getattr(el, "pane", None) == name:
                        el.draw(surface)
                if foregrounds and name in foregrounds:
                    foregrounds[name](surface)

        for el in self.elements:
            if not getattr(el, "pane", None):
                el.draw(surface)

    def draw_pane_scrollbar(self, surface, name, track_x, track_y, view_h, width=15):
        """Scrollbar for one pane, wired to the same attributes as its rows."""
        return self.draw_list_scrollbar(surface, track_x, track_y, view_h, width=width,
                                        axis=self.pane_scroll_axis(name),
                                        **self.scroll_attrs(name))
