"""Text fitting shared by every screen that renders into a fixed-width space.

Before this module there were five word-wrap implementations and six truncation
helpers scattered across `ui/` and `screens/`, and they had drifted: some
compared with `<` and some with `<=` (so identical text broke at different
words), some preserved blank lines and some collapsed them, some hard-broke an
over-wide single word and some let it overflow, and one ellipsised with two dots
instead of three. Screens also reached across module boundaries for each other's
private helpers -- `ui/checkbox_list_screen.py` imported `confirm_dialog._wrap_text`.

Kept deliberately dependency-free (pygame + data.constants only) so it stays a
leaf in the import graph: callers pass an already-resolved font object, which is
what every existing call site already did, so there is no font_manager import
and no risk of a cycle.
"""

import re
import pygame

import data.constants as c

INLINE_ICON_GAP = 6


def render_inline_text(parts, font, max_width, color, *, wrap=False, icon_gap=INLINE_ICON_GAP):
    """Cache text lines with optional icons. Each part contains text and a cached icon."""
    if max_width <= 0:
        raise ValueError("Inline text needs a positive width.")
    line_height = font.get_height()
    lines, pieces = [], []
    width = 0

    def finish_line():
        nonlocal pieces, width
        height = max([line_height] + [piece.get_height() for piece, _x in pieces])
        line = pygame.Surface((max(1, min(width, max_width)), height), pygame.SRCALPHA)
        for piece, x in pieces:
            line.blit(piece, (x, (height - piece.get_height()) // 2))
        lines.append(line)
        pieces, width = [], 0

    if not wrap:
        for text, icon in parts:
            if icon is not None:
                pieces.append((icon, width))
                width += icon.get_width() + icon_gap
            piece = font.render(text.replace("\n", " "), True, color)
            pieces.append((piece, width))
            width += piece.get_width()
        full_width = width
        finish_line()
        if full_width > max_width:
            ellipsis = font.render(c.ELLIPSIS, True, color)
            rect = ellipsis.get_rect(midright=(max_width, lines[0].get_height() // 2))
            lines[0].fill((0, 0, 0, 0), rect)
            lines[0].blit(ellipsis, rect)
        return lines

    pending_space = ""
    for text, icon in parts:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        keep_first_word = icon is not None
        if icon is not None:
            first_word = text.split()[0] if text.split() else ""
            icon_width = icon.get_width() + icon_gap
            prefix_width = font.size(pending_space)[0] if width else 0
            if width and width + prefix_width + icon_width + font.size(first_word)[0] > max_width:
                finish_line()
                pending_space = ""
            if pending_space and width:
                piece = font.render(pending_space, True, color)
                pieces.append((piece, width))
                width += piece.get_width()
            pending_space = ""
            pieces.append((icon, width))
            width += icon_width
        for token in re.findall(r"\n|[^\S\n]+|[^\s]+", text):
            if token == "\n":
                finish_line()
                pending_space = ""
                keep_first_word = False
            elif token.isspace():
                pending_space += token
            else:
                word = (pending_space if width else "") + token
                pending_space = ""
                if width and width + font.size(word)[0] > max_width and not keep_first_word:
                    finish_line()
                    word = token
                while word:
                    chunk = fit_text(word, font, max_width - width, ellipsis="")
                    if not chunk:
                        if not width:
                            raise ValueError("Inline text width must fit at least one character.")
                        finish_line()
                        continue
                    piece = font.render(chunk, True, color)
                    pieces.append((piece, width))
                    width += piece.get_width()
                    word = word[len(chunk):]
                    if word:
                        finish_line()
                keep_first_word = False
    finish_line()
    return lines


def wrap_text(text, font, max_width, *, keep_blank_lines=True,
              break_long_words=True, max_lines=None, ellipsis=None):
    """Word-wraps `text` to `max_width` pixels, returning a list of lines.

    Newlines in `text` are honoured as hard breaks. A word too wide to ever fit
    is split mid-word when `break_long_words` is set, rather than being allowed
    to overflow the panel it was measured against.

    `max_lines` caps the result. `ellipsis` (when given alongside `max_lines`)
    is appended to the last kept line to signal the truncation; leave it None to
    cut silently, which is what the diplomatic popup has always done.
    """
    lines = []
    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")

    for paragraph in normalized.split("\n"):
        if not paragraph:
            # An empty paragraph is a deliberate blank line in the source text.
            if keep_blank_lines:
                lines.append("")
            continue

        current = ""
        for word in paragraph.split(" "):
            candidate = f"{current} {word}" if current else word
            if font.size(candidate)[0] <= max_width:
                current = candidate
                continue

            if current:
                lines.append(current)
                current = ""

            if not break_long_words or font.size(word)[0] <= max_width:
                current = word
                continue

            # The word alone is wider than the box, so break it mid-word.
            chunk = ""
            for ch in word:
                if font.size(chunk + ch)[0] <= max_width:
                    chunk += ch
                else:
                    lines.append(chunk)
                    chunk = ch
            current = chunk

        lines.append(current)

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if ellipsis and lines:
            lines[-1] = fit_text(lines[-1] + ellipsis, font, max_width, ellipsis=ellipsis)
    return lines


def truncate_chars(text, max_chars, ellipsis=c.ELLIPSIS):
    """Shortens by character count -- for fixed-pitch columns whose width is
    expressed in characters rather than pixels (see ui/table_screen.py)."""
    text = str(text)
    if len(text) <= max_chars:
        return text
    keep = max(0, max_chars - len(ellipsis))
    return text[:keep] + ellipsis


def fit_text(text, font, max_width, ellipsis=c.ELLIPSIS):
    """Shortens from the right until it fits `max_width`, keeping the start of
    the string readable. Binary search rather than a character-at-a-time walk,
    since some asset filenames run 40+ characters."""
    text = str(text)
    if font.size(text)[0] <= max_width:
        return text

    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(text[:mid] + ellipsis)[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ellipsis) if lo > 0 else ellipsis


def fit_path(text, font, max_width, ellipsis=c.ELLIPSIS):
    """Counterpart to fit_text that trims from the *left*, which keeps the
    deepest -- and most identifying -- part of a file path readable."""
    text = str(text)
    if font.size(text)[0] <= max_width:
        return text

    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(ellipsis + text[len(text) - mid:])[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (ellipsis + text[len(text) - lo:]) if lo > 0 else ellipsis
