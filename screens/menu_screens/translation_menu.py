from gameState import GameState
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
from map_logic import gd4_translation
from data import queries
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
            Button(260, 300, "large", "light_blue", "Greater Diplomacy 4",
                   lambda: self.go_to("TRANSLATE_GD4")),
        ]

    def additional_draw(self, surface):
        text = "Choose the map format you want to translate."
        font = fonts.get("normal")
        text_surface = font.render(text, True, (220, 220, 220))
        surface.blit(text_surface, text_surface.get_rect(midtop=(c.SCREEN_WIDTH // 2, 130)))


class Greater_Diplomacy_4_Translation(GameState):
    """Import a standard Greater Diplomacy 4 save into a new GD5 save."""

    back_state = "TRANSLATION_MENU"
    title = "GREATER DIPLOMACY 4 TRANSLATION"

    def __init__(self):
        super().__init__()
        self.bg_color = (35, 35, 55)
        self.status = "Choose a GD4 save file to create a new GD5 save."
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

        queries.open_file_browser(
            self, "Select Greater Diplomacy 4 Save", downloads_dir(),
            extensions=[".txt", ".gd4", ".save"], on_result=selected,
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
            destination, notes = gd4_translation.translate_file(source_path)
        except (gd4_translation.GD4TranslationError, OSError) as error:
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
            Button("centered", 180, "large", "light_blue", "Select GD4 Save...", self.choose_save),
        ]

    def additional_draw(self, surface):
        font = fonts.get("normal")
        detail_font = fonts.get("small")
        status_color = (160, 235, 170) if self.status_ok else (255, 155, 155)
        status = font.render(self.status, True, status_color)
        surface.blit(status, status.get_rect(center=(c.SCREEN_WIDTH // 2, 270)))

        detail = detail_font.render(
            "Supports TurboWarp Base64/LZ-String saves and decompressed GD4 text saves.",
            True, (190, 190, 205),
        )
        surface.blit(detail, detail.get_rect(center=(c.SCREEN_WIDTH // 2, 320)))
        for index, note in enumerate(self.notes[:3]):
            note_surface = detail_font.render(note, True, (210, 210, 220))
            surface.blit(note_surface, note_surface.get_rect(
                center=(c.SCREEN_WIDTH // 2, 360 + index * 28)))
