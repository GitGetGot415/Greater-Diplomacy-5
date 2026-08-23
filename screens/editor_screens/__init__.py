"""Native pygame replacements for the map editor's tkinter tool windows.

Each class here is a MapOverlayScreen launched with
ui.screen_runner._run_pygame_sub_screen. Everything the map editor's
bottom/side bars open lives in one of the sibling modules below, has become a
TableScreen, or -- for the scripted events editor -- has its own module.

ui/editor_menus.py looks screens up here by class name (`getattr(editor_screens,
class_name)`), so every screen class is re-exported at package level.
"""
from screens.editor_screens.date_economy_screens import (
    Editor_Date_Screen,
    Starting_Economy_Edit_Screen,
    Starting_Economy_List_Screen,
)
from screens.editor_screens.research_screens import (
    Research_Edit_Screen,
    Research_List_Screen,
)
from screens.editor_screens.brush_screens import (
    Convoy_Converter_Screen,
    Resource_Brush_Screen,
    Clear_Map_Screen,
)
from screens.editor_screens.diplomacy_editor_screen import Diplomacy_Editor_Screen
from screens.editor_screens.personality_editor import (
    Personality_Edit_Screen,
    Personality_List_Screen,
)
from screens.editor_screens.politics_editor import (
    Politics_Edit_Screen,
    Politics_List_Screen,
)
