from ui.navigation.game_state import GameState
from ui.widgets.ui_elements import Button, make_back_button
from ui.rendering.font_manager import fonts
from map_logic.imports import gd4_translation, gdhex_translation
from ui.dialogs import pickers
from data.platform import downloads_dir
import data.constants as c
import os


class Translation_Menu(GameState):
    """Choose which game's map format should be used for translation."""

    back_state = "MENU"
    title = "TRANSLATE MAPS"

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 45, 55)
        self.elements = [
            make_back_button(self.exit_screen),
            Button(260, 180, "large", "green", "Open Doctrines",
                   lambda: self.go_to("TRANSLATE")),
            Button(260, 280, "large", "light_blue", "Greater Diplomacy 4",
                   lambda: self.go_to("TRANSLATE_GD4")),
            Button(260, 380, "large", "orange", "GD Hex Edition",
                   lambda: self.go_to("TRANSLATE_GDHEX")),
        ]

    def additional_draw(self, surface):
        text = "Choose the map format you want to translate."
        font = fonts.get("normal")
        text_surface = font.render(text, True, (220, 220, 220))
        surface.blit(text_surface, text_surface.get_rect(midtop=(c.SCREEN_WIDTH // 2, 130)))


class SaveTranslationScreen(GameState):
    """Import a save from another game into a new GD5 save."""

    back_state = "TRANSLATION_MENU"
    translator = None
    translation_error = None
    background_color = None
    initial_status = ""
    browser_title = ""
    extensions = ()
    button_color = ""
    button_text = ""
    detail_text = ""
    detail_color = None
    note_color = None

    def __init__(self):
        super().__init__()
        self.bg_color = self.background_color
        self.status = self.initial_status
        self.status_ok = True
        self.notes = []
        self.pending_path = None
        self.pending_drawn = False
        self.refresh_ui()

    def choose_save(self):
        """Use the cross-platform picker; selected files are never modified."""
        def selected(path):
            if not path:
                return
            self.pending_path = path
            self.pending_drawn = False
            self.status = "Translating " + os.path.basename(path) + "..."
            self.status_ok = True
            self.notes = []
            self.refresh_ui()

        pickers.open_file_browser(
            self, self.browser_title, downloads_dir(),
            extensions=list(self.extensions), on_result=selected,
        )

    def update(self):
        # Let the status paint for one frame before the synchronous conversion.
        if not self.pending_path:
            return
        if not self.pending_drawn:
            self.pending_drawn = True
            return
        source_path = self.pending_path
        self.pending_path = None
        try:
            destination, notes = self.translator.translate_file(source_path)
        except (self.translation_error, OSError) as error:
            self.status = "Could not import: " + str(error)
            self.status_ok = False
            self.notes = []
        else:
            self.status = "Created save: " + os.path.basename(destination)
            self.status_ok = True
            self.notes = notes + ["Open it from Load Game to play the converted save."]
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            make_back_button(self.exit_screen),
            Button("centered", 180, "large", self.button_color, self.button_text, self.choose_save),
        ]

    def additional_draw(self, surface):
        font = fonts.get("normal")
        detail_font = fonts.get("small")
        status_color = (160, 235, 170) if self.status_ok else (255, 155, 155)
        status = font.render(self.status, True, status_color)
        surface.blit(status, status.get_rect(center=(c.SCREEN_WIDTH // 2, 270)))
        detail = detail_font.render(self.detail_text, True, self.detail_color)
        surface.blit(detail, detail.get_rect(center=(c.SCREEN_WIDTH // 2, 320)))
        for index, note in enumerate(self.notes[:3]):
            note_surface = detail_font.render(note, True, self.note_color)
            surface.blit(note_surface, note_surface.get_rect(
                center=(c.SCREEN_WIDTH // 2, 360 + index * 28)))


class Greater_Diplomacy_4_Translation(SaveTranslationScreen):
    """Import a standard Greater Diplomacy 4 save into a new GD5 save."""

    title = "GREATER DIPLOMACY 4 TRANSLATION"
    translator = gd4_translation
    translation_error = gd4_translation.GD4TranslationError
    background_color = (35, 35, 55)
    initial_status = "Choose a GD4 save file to create a new GD5 save."
    browser_title = "Select Greater Diplomacy 4 Save"
    extensions = (".txt", ".gd4", ".save")
    button_color = "light_blue"
    button_text = "Select GD4 Save..."
    detail_text = "Supports TurboWarp Base64/LZ-String saves and decompressed GD4 text saves."
    detail_color = (190, 190, 205)
    note_color = (210, 210, 220)


class Greater_Diplomacy_Hex_Translation(SaveTranslationScreen):
    """Import a Greater Diplomacy Hex Edition save into a generated GD5 map."""

    title = "GREATER DIPLOMACY HEX EDITION TRANSLATION"
    translator = gdhex_translation
    translation_error = gdhex_translation.GDHEXTranslationError
    background_color = (45, 35, 45)
    initial_status = "Choose a Hex Edition save to create a new GD5 save."
    browser_title = "Select Greater Diplomacy Hex Edition Save"
    extensions = (".txt", ".gdhex", ".save")
    button_color = "orange"
    button_text = "Select Hex Save..."
    detail_text = "Builds a GD5 map from any saved Hex Edition grid dimensions."
    detail_color = (210, 190, 210)
    note_color = (220, 210, 220)
