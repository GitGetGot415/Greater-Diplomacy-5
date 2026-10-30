from screens.multiplayer.tournament_picker import TournamentPickerScreen
from ui.widgets.ui_elements import Button, make_back_button


class Multiplayer_Host(TournamentPickerScreen):
    title = "Host Dashboard"

    def __init__(self):
        super().__init__()
        self.elements = [
            Button("centered", "centered - 50", "medium", "green", "Start New Multiplayer Game", self.start_new),
            Button("centered", "centered + 50", "medium", "green", "Load Existing Tournament", self.load_existing),
            make_back_button(self.exit_screen)
        ]

    def start_new(self):
        self.go_to("MULTIPLAYER_NEW")

    def load_existing(self):
        self.pick_tournament("Master Key", "Enter your Master Key:")
