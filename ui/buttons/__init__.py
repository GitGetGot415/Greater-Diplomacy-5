"""Button-building for every screen that used to share one 900-line module.

Split by which screen builds the buttons: map_buttons.py (the main map's huge
left/bottom/contextual bars), edit_country_buttons.py, settings_buttons.py, and
common.py for the make_option_buttons helper shared by settings and (via
screens/map_related_screens/diplomacy_screen_widgets.py) the diplomacy
screens. Call sites do `from ui import buttons; buttons.render_buttons(...)`,
so every public name is re-exported here at package level.
"""
from ui.buttons.map_buttons import render_buttons, update_button_states
from ui.buttons.edit_country_buttons import render_edit_country_buttons
from ui.buttons.settings_buttons import render_settings_buttons
from ui.buttons.common import make_option_buttons
