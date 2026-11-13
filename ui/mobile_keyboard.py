"""On-screen keyboard for the mobile web build and the Android app.

A phone opens its keyboard only for a focused HTML text element, never for the
game's canvas. While a text box draws as active, a hidden <input> holds the
browser focus. The characters typed into the hidden <input> become pygame
KEYDOWN events, so every text box keeps reading input through
ui_elements.process_text_input.

Phone keyboards rarely send usable key codes, so the hidden <input> compares
its value after each change and queues the added characters and backspaces.
It starts filled with dots so a backspace always has something to delete and
still reaches the game's text box.
"""

import json

import pygame

from data.platform import IS_WEB

# Enter and Escape change no text, so the hidden <input> queues them from
# keydown. Other text keys are kept from SDL, which would type them twice.
# preventDefault on mousedown keeps a tap on the canvas from taking focus away
# from the hidden <input>. A touchend while the hidden <input> is unfocused
# focuses it inside the tap, which iOS requires before it opens the keyboard.
_KEYBOARD_JS = r"""
(() => {
    const FILL = '................';
    const input = document.createElement('input');
    input.type = 'text';
    input.autocomplete = 'off';
    input.spellcheck = false;
    input.setAttribute('aria-hidden', 'true');
    input.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;opacity:0;border:0;padding:0;font-size:16px;';
    document.body.appendChild(input);
    const state = window.__gd5_keyboard = {shown: false, queue: [], previous: FILL};
    const fill = () => {
        input.value = FILL;
        input.setSelectionRange(FILL.length, FILL.length);
        state.previous = FILL;
    };
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === 'Escape') {
            state.queue.push(event.key === 'Enter' ? '\r' : '\x1b');
            event.preventDefault();
            event.stopPropagation();
        } else if (event.key.length === 1 || ['Backspace', 'Delete', 'Unidentified', 'Process'].includes(event.key)) {
            event.stopPropagation();
        }
    });
    input.addEventListener('keyup', event => event.stopPropagation());
    input.addEventListener('keypress', event => event.stopPropagation());
    input.addEventListener('input', event => {
        // Compare characters, not UTF-16 units, so one emoji is one backspace.
        const next = Array.from(input.value);
        const previous = Array.from(state.previous);
        let same = 0;
        while (same < previous.length && same < next.length && previous[same] === next[same]) same++;
        for (let i = same; i < previous.length; i++) state.queue.push('\b');
        state.queue.push(...next.slice(same));
        state.previous = input.value;
        if (!event.isComposing && (next.length < FILL.length / 2 || next.length > 256)) fill();
    });
    document.addEventListener('mousedown', event => {
        if (state.shown && event.target !== input) event.preventDefault();
    }, true);
    document.addEventListener('touchend', () => {
        if (state.shown && document.activeElement !== input) input.focus();
    }, true);
    state.show = () => {
        state.shown = true;
        state.queue = [];
        fill();
        input.focus();
    };
    state.hide = () => {
        state.shown = false;
        state.queue = [];
        input.blur();
    };
    state.take = () => {
        const typed = JSON.stringify(state.queue).replace(/[\u0080-￿]/g, ch => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'));
        state.queue = [];
        return typed;
    };
})();
"""

_CONTROL_KEYS = {"\b": pygame.K_BACKSPACE, "\r": pygame.K_RETURN, "\x1b": pygame.K_ESCAPE}

_installed = False
_shown = False
_requested = False


def request():
    """Ask for the keyboard this frame. Called while a text box draws as active."""
    global _requested
    _requested = True


def typed_events():
    """Return the characters typed since the last frame as pygame KEYDOWN events."""
    if not _shown:
        return []
    import platform  # pygbag supplies platform.window only in the browser.
    typed = json.loads(str(platform.window.eval("window.__gd5_keyboard.take()")))
    # Key K_UNKNOWN keeps a typed letter from also firing a keybind.
    return [pygame.event.Event(pygame.KEYDOWN, key=_CONTROL_KEYS.get(ch, pygame.K_UNKNOWN), mod=0, scancode=0, unicode="" if ch in _CONTROL_KEYS else ch) for ch in typed]


def sync(mobile_controls):
    """Open or close the keyboard once the frame has drawn.

    The keyboard is open while any text box drew as active this frame, on the
    web build in mobile controls. Desktop browsers keep their normal keyboard.
    """
    global _installed, _shown, _requested
    wanted = _requested and IS_WEB and mobile_controls
    _requested = False
    if wanted == _shown:
        return
    import platform  # pygbag supplies platform.window only in the browser.
    if not _installed:
        platform.window.eval(_KEYBOARD_JS)
        _installed = True
    platform.window.eval("window.__gd5_keyboard.show()" if wanted else "window.__gd5_keyboard.hide()")
    _shown = wanted
