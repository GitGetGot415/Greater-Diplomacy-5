"""Which province color every pixel of the id map shows, worked out once.

Every map layer, the fog and the one-province repaints used to start by reading
the whole id map again: pack each pixel's three channels into one 24-bit number,
then look that number up in a table with an entry for every possible color. The
id map never changes in place -- loaders and the map generator replace the
surface instead -- so all of that can be done once per surface. A layer build
then fills one small table entry per province color and reads it back with a
single lookup per pixel.

A "slot" is a province color's position in the id map's sorted list of
distinct colors. Slots are numbered from the image alone, not from map_data, so
pixels in a color that no province uses still get one.
"""
import numpy as np
import pygame

#: Every value a packed 24-bit color can take.
COLOR_SPACE = 1 << 24


def pack_color(color):
    """One integer for an (r, g, b) color, the form the id map is indexed by."""
    return (color[0] << 16) | (color[1] << 8) | color[2]


def packed_id_colors(id_map):
    """The id map as one packed 24-bit color per pixel, indexed [x, y]."""
    id_array = pygame.surfarray.pixels3d(id_map)
    packed = (id_array[:, :, 0].astype(np.uint32) << 16) | \
             (id_array[:, :, 1].astype(np.uint32) << 8) | \
              id_array[:, :, 2].astype(np.uint32)
    del id_array  # Unlocks the id map.
    return packed


class ProvincePixels:
    """The slot every pixel of one id map shows, plus each slot's pixels on demand."""

    def __init__(self, id_map):
        self.id_map = id_map
        packed = packed_id_colors(id_map)
        present = np.zeros(COLOR_SPACE, dtype=bool)
        present[packed] = True
        colors = np.flatnonzero(present)
        self.slot_count = len(colors)
        # One value past the last slot is free for callers that need a marker
        # for "no slot", such as the gap fill in refresh_map.
        self.dtype = np.uint16 if self.slot_count < np.iinfo(np.uint16).max else np.uint32
        slot_lut = np.zeros(COLOR_SPACE, dtype=self.dtype)
        slot_lut[colors] = np.arange(self.slot_count, dtype=self.dtype)
        #: [x, y] -> slot of that pixel's id color.
        self.slots = slot_lut[packed]
        self.slot_of_color = {int(color): slot for slot, color in enumerate(colors)}
        self._order = None
        self._starts = None
        self._bounds = None

    def slot_for(self, color):
        """The slot of an (r, g, b) id color, or None when no pixel shows it."""
        return self.slot_of_color.get(pack_color(color))

    def _group_pixels(self):
        # Sorting by slot lists every slot's pixels side by side. NumPy sorts
        # 16-bit keys with a radix sort, so this stays quick on large maps.
        flat = self.slots.ravel()
        self._order = np.argsort(flat, kind="stable").astype(np.int32)
        counts = np.bincount(flat, minlength=self.slot_count)
        self._starts = np.concatenate(([0], np.cumsum(counts))).astype(np.int64)

        height = self.slots.shape[1]
        xs = self._order // height
        ys = self._order % height
        starts = self._starts[:-1]
        # Every slot has at least one pixel, since slots come from the image.
        self._bounds = np.stack((np.minimum.reduceat(xs, starts),
                                 np.maximum.reduceat(xs, starts) + 1,
                                 np.minimum.reduceat(ys, starts),
                                 np.maximum.reduceat(ys, starts) + 1), axis=1)

    def pixels_of(self, slot):
        """(xs, ys) of every pixel that shows this slot's color."""
        if self._order is None:
            self._group_pixels()
        flat = self._order[self._starts[slot]:self._starts[slot + 1]]
        height = self.slots.shape[1]
        return flat // height, flat % height

    def bounds_of(self, slot):
        """(x0, x1, y0, y1) of the box around this slot's pixels, ends exclusive."""
        if self._bounds is None:
            self._group_pixels()
        return tuple(int(v) for v in self._bounds[slot])


# One id map is on screen at a time; the deal and peace previews use the live
# map's surface too. Holding the surface keeps `is` comparisons honest.
_CACHED = None


def for_id_map(id_map):
    """The ProvincePixels of this id map, built on first use."""
    global _CACHED
    if _CACHED is None or _CACHED.id_map is not id_map:
        _CACHED = ProvincePixels(id_map)
    return _CACHED


def clear():
    """Forget the cached id map, for the manual Refresh Maps action."""
    global _CACHED
    _CACHED = None
