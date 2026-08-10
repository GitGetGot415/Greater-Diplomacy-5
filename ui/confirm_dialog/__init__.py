"""Pygame-rendered replacements for tkinter's messagebox.askyesno / simpledialog.askinteger.

Every function here is callback-based: instead of returning a value, it takes
an on_result callback and invokes it once the user answers. Two things drive
that shape (see ui/modal_stack.py for the full rationale):

- When a main-loop-managed display already exists (the normal in-game case),
  the dialog is pushed onto the modal stack and answered on a later frame --
  it can't block the caller, since blocking is exactly what freezes a pygbag
  browser tab (main.py's loop never gets to yield to the browser).
- When no display exists yet (standalone tkinter dev tools like
  data/editors/country_editor.py, run outside the game's main loop entirely),
  there's no modal stack pumping frames, so the dialog falls back to running
  its own short-lived blocking loop and calls on_result() right before
  returning -- same callback shape, just resolved synchronously.

Call sites always look the same either way: `ask_yes_no(title, msg, on_result=...)`.

Split by dialog kind: base.py (the shared modal skeleton and the standalone
blocking-loop runner), yes_no.py, text_input.py (ask_integer/ask_string),
message_box.py (show_info/success/warning/error), person_info.py. Call sites
do `from ui import confirm_dialog; confirm_dialog.ask_yes_no(...)` or import a
name directly (`from ui.confirm_dialog import show_person_info`), so every
public name -- and the couple of private helpers other ui/ modules reach for
directly -- is re-exported here at package level.
"""
from ui.confirm_dialog.base import _hide_tk_chain, _show_tk_chain, _wrap_text
from ui.confirm_dialog.yes_no import ask_yes_no
from ui.confirm_dialog.text_input import ask_integer, ask_string
from ui.confirm_dialog.message_box import (
    _KIND_ACCENTS,
    show_message,
    show_info,
    show_success,
    show_warning,
    show_error,
)
from ui.confirm_dialog.person_info import show_person_info
