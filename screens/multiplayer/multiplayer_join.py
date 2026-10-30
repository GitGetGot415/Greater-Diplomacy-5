from screens.multiplayer.tournament_picker import TournamentPickerScreen
from ui.widgets.ui_elements import Button, make_back_button


class Multiplayer_Join(TournamentPickerScreen):
    title = "Join Game"

    def __init__(self):
        super().__init__()
        self.elements = [
            Button("centered", "centered", "medium", "blue", "Load Tournament File", self.load_tour_file),
            make_back_button(self.exit_screen)
        ]

    def load_tour_file(self):
        self.pick_tournament(
            "Player Key",
            "Enter your Country Key, or enter 'Spectator' for the fog-limited Tournament Spectator view:")
