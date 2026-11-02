from screens.multiplayer.tournament_picker import TournamentPickerScreen


class Multiplayer_Join(TournamentPickerScreen):
    title = "Join Game"

    def menu_buttons(self):
        return [("Load Tournament File", "blue", self.load_tour_file)]

    def load_tour_file(self):
        self.pick_tournament(
            "Player Key",
            "Enter your Country Key, or enter 'Spectator' for the fog-limited Tournament Spectator view:")
