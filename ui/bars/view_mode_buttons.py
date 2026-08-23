"""The four red view-mode toggles (Resources/Blank/Units/Economy) from the
bottom-left corner of the map screen, reused by the screens layered over it
(Orders, Production) so switching view types doesn't require backing out to
the map first. Kept in one place so the row's geometry/icons can't drift
between the map's own copy and everyone else's.
"""
import data.constants as c
import ui_elements
from ui_elements import Button

START_X = 10
STEP_X = 50
ROW_Y = c.SCREEN_HEIGHT - 50

MODES = ("RESOURCES", "BLANK", "UNITS", "ECONOMY")
_LABELS = {"RESOURCES": "Resources", "BLANK": "Blank", "UNITS": "Units", "ECONOMY": "Economy"}
_ICONS = {"RESOURCES": "resource", "BLANK": "blank", "UNITS": "unit", "ECONOMY": "industry"}

# Right edge of the row plus a margin. Orders/Production draw the full-width
# bottom resource bar (ui.bars.resource_hud.draw_resource_bar) right where
# this row now also sits, so they start that bar here instead of at its
# default x so the two don't overlap.
RESOURCE_BAR_OFFSET_X = START_X + STEP_X * len(MODES) + 40


def build(navigate):
    """Returns the four buttons. `navigate(mode)` fires on click -- pass a
    closure bound to the calling screen (see ui.event_handler.navigate_view_mode)
    so the jump lands correctly regardless of which screen this row is drawn on.
    """
    icons = ui_elements.UI_ICONS
    return [
        Button(START_X + STEP_X * i, ROW_Y, "small_square", "red", _LABELS[mode],
               (lambda m=mode: navigate(m)), image=icons.get(_ICONS[mode]), show_text=False)
        for i, mode in enumerate(MODES)
    ]


def sync_highlight(buttons, secondary_mode):
    """Marks whichever button matches the map's current view mode selected."""
    for btn, mode in zip(buttons, MODES):
        btn.is_selected = (secondary_mode == mode)
