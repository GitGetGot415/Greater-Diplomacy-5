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

import data.constants as c


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
