"""Flag and portrait image encoding, decoding, and caching."""

import base64
import data.constants as c
import os
import pygame


_default_flag_b64 = None


_default_port_b64 = None


_dynamic_image_cache = {}


def clear_image_cache():
    _dynamic_image_cache.clear()


def _load_and_scale_local_image(file_path, size):
    """Helper to safely load and scale a local image file."""
    if os.path.exists(file_path):
        try:
            img = pygame.image.load(file_path).convert_alpha()
            return pygame.transform.scale(img, size)
        except Exception:
            pass
    return None


def get_default_b64(is_portrait=False):
    global _default_flag_b64, _default_port_b64
    cached = _default_port_b64 if is_portrait else _default_flag_b64
    
    if cached is None:
        path = c.DEFAULT_PORTRAIT_PATH if is_portrait else c.DEFAULT_FLAG_PATH
        size = c.PORTRAIT_SIZE if is_portrait else c.FLAG_SIZE
        img = _load_and_scale_local_image(path, size)
        
        cached = encode_surf_to_b64(img) if img else "ERROR"
        
        if is_portrait: _default_port_b64 = cached
        else: _default_flag_b64 = cached
        
    return cached


#: country -> (flag_b64, portrait_b64) for the on-disk assets, or None where
#: there is no file. Answering this needs a disk load, an alpha conversion, a
#: rescale and a full-buffer base64 per country, and the answer cannot change
#: while the game runs -- but scrub_default_images is called once per nation per
#: history snapshot, so on a 130-turn 752-nation save it was being computed
#: ~98,000 times and cost 8.9 seconds of every save.
_local_image_b64_cache = {}


def _local_image_b64(country):
    """Base64 of this country's own flag/portrait files, memoised for the process."""
    cached = _local_image_b64_cache.get(country)
    if cached is None:
        f_img = _load_and_scale_local_image(os.path.join(c.FLAGS_DIR, f"{country}.png"), c.FLAG_SIZE)
        p_img = _load_and_scale_local_image(os.path.join(c.PORTRAITS_DIR, f"{country}.png"), c.PORTRAIT_SIZE)
        cached = (encode_surf_to_b64(f_img) if f_img else None,
                  encode_surf_to_b64(p_img) if p_img else None)
        _local_image_b64_cache[country] = cached
    return cached


def scrub_default_images(nation_data_block):
    """Replaces large Base64 strings with 'DEFAULT' if they match the default images or local files."""
    def_flag = get_default_b64(is_portrait=False)
    def_port = get_default_b64(is_portrait=True)

    for country, data in nation_data_block.items():
        flag_b64, port_b64 = _local_image_b64(country)

        # 'DEFAULT' means "rebuild it from the country's own file, or failing
        # that the global default" -- so both comparisons collapse to the same
        # replacement, and neither is worth storing. Guarded on truthiness so a
        # nation with no flag_data at all does not gain the key here, which is
        # what a bare `in` test would have done when the local file is absent.
        stored_flag = data.get("flag_data")
        if stored_flag and stored_flag in (def_flag, flag_b64):
            data["flag_data"] = "DEFAULT"

        stored_port = data.get("portrait_data")
        if stored_port and stored_port in (def_port, port_b64):
            data["portrait_data"] = "DEFAULT"


def encode_surf_to_b64(surf, fmt="RGBA"):
    """Encodes a pygame surface to a Base64 string."""
    img_str = pygame.image.tostring(surf, fmt)
    return base64.b64encode(img_str).decode('utf-8')


def decode_b64_to_surf(b64_str, size, is_portrait=False, country_name=None):
    """Decodes a Base64 string back into a pygame surface."""
    cache_key = (b64_str, size, is_portrait, country_name)
    if cache_key in _dynamic_image_cache:
        return _dynamic_image_cache[cache_key]

    scaled = None
    if not b64_str or b64_str == "DEFAULT":
        # --- Check for country-specific local file first ---
        if country_name:
            base_dir = c.PORTRAITS_DIR if is_portrait else c.FLAGS_DIR
            scaled = _load_and_scale_local_image(os.path.join(base_dir, f"{country_name}.png"), size)
            
        # --- Fallback to absolute default ---
        if not scaled:
            path = c.DEFAULT_PORTRAIT_PATH if is_portrait else c.DEFAULT_FLAG_PATH
            scaled = _load_and_scale_local_image(path, size)
            
        if not scaled: # Failsafe
            scaled = pygame.Surface(size, pygame.SRCALPHA)
            scaled.fill((200, 200, 200, 255))
    else:
        try:
            img_bytes = base64.b64decode(b64_str)
            if len(img_bytes) == size[0] * size[1] * 4:
                scaled = pygame.image.fromstring(img_bytes, size, "RGBA")
            else:
                scaled = pygame.image.fromstring(img_bytes, size, "RGB").convert_alpha()
        except Exception:
            scaled = pygame.Surface(size, pygame.SRCALPHA)
            scaled.fill((255, 255, 255, 255))

    _dynamic_image_cache[cache_key] = scaled
    return scaled
