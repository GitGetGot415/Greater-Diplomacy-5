from screens.multiplayer.tournament_picker import TournamentPickerScreen


class Multiplayer_Host(TournamentPickerScreen):
    title = "Host Dashboard"

    def menu_buttons(self):
        return [
            ("Start New Multiplayer Game", "green", self.start_new),
            ("Load Existing Tournament", "green", self.load_existing),
        ]

    def start_new(self):
        self.go_to("MULTIPLAYER_NEW")

    def load_existing(self):
        self.pick_tournament("Master Key", "Enter your Master Key:")
