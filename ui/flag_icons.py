"""Small inline national flags, for lists that name a nation on every row.

The garrison list, the combat roster and the lane manager all want the same
thing: a country identified in eighteen pixels rather than eighteen characters,
because "United Kingdom v Vichy France" does not fit in a column and
"[flag] v [flag]" does.

Two copies of the decode-scale-border sequence already existed in
ui/sidebar_info.py, and both re-ran pygame.transform.scale for every unit on
every frame. The scaled surface is cached here instead: flags do not change
during a game, and a busy province is thirty rows deep.

queries.decode_b64_to_surf caches the full-size decode, but only at c.FLAG_SIZE
-- the base64 payload is raw pixels at that size, so it cannot be asked for a
small one directly. This is the layer that turns it into a row icon.
"""

import pygame

import data.constants as c

#: Row-sized flag, matching the c.FLAG_SIZE aspect ratio.
ROW_FLAG_SIZE = (18, 12)

_cache = {}


def flag_surface(nation, nation_data, size=ROW_FLAG_SIZE):
    """The nation's flag scaled to `size`, cached.

    Keyed on the flag data rather than the nation name, so an editor changing a
    flag mid-session shows the new one instead of a stale cache entry.
    """
    flag_data = (nation_data.get(nation) or {}).get("flag_data", "DEFAULT")
    key = (nation, flag_data, size)
    if key not in _cache:
        from data import queries

        full = queries.decode_b64_to_surf(flag_data, c.FLAG_SIZE,
                                          is_portrait=False, country_name=nation)
        _cache[key] = pygame.transform.scale(full, size)
    return _cache[key]


def draw_flag(surface, nation, nation_data, x, y, size=ROW_FLAG_SIZE):
    """Blits the flag with the thin border every list draws around it.

    Returns the x just past it, so callers can chain a name or stats onto the
    same line the way draw_icon_row does.
    """
    flag = flag_surface(nation, nation_data, size)
    surface.blit(flag, (x, y))
    pygame.draw.rect(surface, (100, 100, 100), (x, y, size[0], size[1]), 1)
    return x + size[0] + 6


def draw_flag_centered(surface, nation, nation_data, x, y, line_h, size=ROW_FLAG_SIZE):
    """Same, vertically centred against a line of text `line_h` tall."""
    return draw_flag(surface, nation, nation_data, x, y + (line_h - size[1]) // 2, size)
