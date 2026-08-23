import os
import pygame
from gameState import GameState
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
from map_logic import odtl
from data import queries
import data.constants as c


class Translate(GameState):
    """Translate maps between GD5 and Open Doctrines, in both directions.

    The two games describe the same kind of world and share no file format.
    open-dragoman converts between them; map_logic/odtl.py is the whole of
    what the rest of the game knows about it.

    Both directions work off directories rather than a file chooser, because
    there is no portable one -- and because the browser build has no such
    thing at all. Maps go out to `translated/` as .odmap files, and .odmap
    files put into that same folder come back in as base maps. One folder,
    both directions, nothing to browse for.

    Nothing here overwrites anything. A destination that already exists is
    refused and says so, which matters more than usual: the maps on the other
    side of this are somebody's work in a different game.
    """
    back_state = "MENU"
    title = "TRANSLATE MAPS"

    # A "new_game" button is 50 tall, so anything under that overlaps the row
    # below it -- which 44 did, by six pixels, all the way down the list.
    ROW_HEIGHT = 60
    ROW_TOP = 160
    LIST_WIDTH = 460

    # Where translated maps are written and where .odmap files are looked for.
    # One folder both ways: a map that goes out lands next to the ones coming
    # back, which is also how a player moves them between the two games.
    TRANSLATED_DIR = "translated"

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 45, 55)
        self.direction = "TO_ODMAP"
        # Where a translated .odmap goes: this game's translated/ folder, or
        # straight into an Open Doctrines install if one has been found.
        # Nothing is searched for until the player asks -- see _find_od().
        self.open_doctrines = ""
        self.searched_for_od = False
        self.send_to_od = False
        self.notes = []
        self.status = ""
        self.status_ok = True
        self.refresh_ui()

    # ------------------------------------------------------------------ data

    def _translated_dir(self):
        if not os.path.isdir(self.TRANSLATED_DIR):
            os.makedirs(self.TRANSLATED_DIR, exist_ok=True)
        return self.TRANSLATED_DIR

    def _gd5_maps(self):
        """Base maps and edited maps, which is everything a player might send."""
        found = []
        for directory in (c.BASE_MAPS_DIR, c.SCENARIOS_CUSTOM_DIR):
            if not os.path.isdir(directory):
                continue
            for name in sorted(os.listdir(directory)):
                path = os.path.join(directory, name)
                # A map is a directory with map_data.json in it. Anything else
                # in these folders is not one and is not offered.
                if os.path.isfile(os.path.join(path, "map_data.json")):
                    found.append((name, path))
        return found

    def _odmaps(self):
        directory = self._translated_dir()
        return [(name, os.path.join(directory, name))
                for name in sorted(os.listdir(directory))
                if odtl.looks_like_odmap(os.path.join(directory, name))]

    def _items(self):
        return self._gd5_maps() if self.direction == "TO_ODMAP" else self._odmaps()

    # ----------------------------------------------------------------- doing

    def translate(self, name, path):
        if not odtl.available():
            self.status = odtl.unavailable_reason() or "the translation layer is not available"
            self.status_ok = False
            self.notes = []
            self.refresh_ui()
            return

        if self.direction == "TO_ODMAP":
            run = odtl.to_odmap
            if self.send_to_od and self.open_doctrines:
                # Open Doctrines keeps a custom map as custom_maps/<name>/map.odmap,
                # which is the layout its own importer writes -- so a map put
                # there is listed by that game with nothing further to do.
                maps_dir = odtl.open_doctrines_maps_dir(self.open_doctrines)
                if not maps_dir:
                    self.status = "That no longer looks like Open Doctrines."
                    self.status_ok = False
                    self.open_doctrines = ""
                    self.send_to_od = False
                    self.refresh_ui()
                    return
                destination = os.path.join(maps_dir, name, "map.odmap")
            else:
                destination = os.path.join(self._translated_dir(), f"{name}.odmap")
        else:
            destination = os.path.join(c.BASE_MAPS_DIR, os.path.splitext(name)[0])
            run = odtl.to_gd5

        if os.path.exists(destination):
            self.status = f"{destination} already exists -- nothing was written."
            self.status_ok = False
            self.notes = []
            self.refresh_ui()
            return

        parent = os.path.dirname(destination)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)

        ok, notes = run(path, destination)

        # On the web the file has landed in a virtual filesystem the player
        # cannot open, so the translation is not finished until the browser has
        # it. Downloading is the only way out of a browser tab.
        if ok and odtl.IS_WEB and self.direction == "TO_ODMAP":
            if odtl.offer_download(destination, os.path.basename(destination)):
                self.status = "Downloading " + os.path.basename(destination)
                self.status_ok = True
                self.notes = notes
                self.refresh_ui()
                return
        self.status = (f"Wrote {destination}" if ok
                       else f"Could not translate {name}: {notes[0] if notes else 'unknown error'}")
        self.status_ok = ok
        self.notes = notes if ok else notes[1:]
        self.refresh_ui()

    def _find_od(self):
        """Look for Open Doctrines, because the player pressed the button that
        says so. Reads its locator file first -- if it has run on this machine
        it has already written down where it is, and nothing needs searching."""
        found = odtl.find_open_doctrines()
        self.open_doctrines = found[0] if found else ""
        self.searched_for_od = True
        self.send_to_od = bool(self.open_doctrines)
        self.status = ("Open Doctrines: " + self.open_doctrines if self.open_doctrines
                       else "Open Doctrines was not found in the usual places.")
        self.status_ok = bool(self.open_doctrines)
        self.notes = []
        self.refresh_ui()

    def choose_od_folder(self):
        """Point at Open Doctrines by hand, when looking for it did not find it.

        Uses the game's own in-engine picker rather than a native dialog, for
        the same reason everything else here does: it works wherever the game
        works, and it already knows what to do on the web build -- which is to
        say so, since a browser has no notion of a path on the real disk.
        """
        def picked(path):
            if not path:
                return
            if not odtl.looks_like_open_doctrines(path):
                # Said plainly, with what was looked for. "Not valid" leaves a
                # player guessing whether they picked the wrong folder or the
                # right one a level too high.
                self.status = ("That folder has no data/STDmaps with a map in it, "
                               "so it is not an Open Doctrines install.")
                self.status_ok = False
                self.notes = []
                self.refresh_ui()
                return
            self.open_doctrines = path
            self.searched_for_od = True
            self.send_to_od = True
            self.status = "Open Doctrines: " + path
            self.status_ok = True
            self.notes = []
            self.refresh_ui()

        queries.ask_directory(self, "Select the Open Doctrines folder",
                              odtl.game_root(), picked)

    def ask_for_upload(self):
        """The browser's file picker, which is the only way a .odmap can reach
        a tab. Nothing is returned here -- see _collect_upload()."""
        if odtl.ask_for_upload():
            self.status = "Choose a .odmap file..."
            self.status_ok = True
            self.notes = []
            self.refresh_ui()

    def _collect_upload(self):
        """Picked files arrive whenever the browser has finished reading them,
        so this is asked once a frame rather than waited on."""
        landed = odtl.take_upload(self._translated_dir())
        if not landed:
            return
        self.direction = "FROM_ODMAP"
        self.status = "Added " + os.path.basename(landed) + " -- pick it below to convert it."
        self.status_ok = True
        self.notes = []
        self.refresh_ui()

    def update(self):
        if odtl.IS_WEB:
            self._collect_upload()

    def toggle_destination(self):
        self.send_to_od = not self.send_to_od
        self.refresh_ui()

    def set_direction(self, direction):
        self.direction = direction
        self.notes = []
        self.status = ""
        self.scroll_y = 0
        self.refresh_ui()

    # -------------------------------------------------------------------- ui

    def _verify_od(self):
        """The remembered install, re-checked before it is offered again.

        This screen is built once at startup and lives for the whole session,
        so a path found at 10am can be a folder somebody moved or deleted at
        11am -- and the button offering to write a map into it would still be
        sitting there. Re-checked here rather than trusted: it is one stat call
        against a directory, and the alternative is writing a map into a place
        that is no longer that game.
        """
        if self.open_doctrines and not odtl.looks_like_open_doctrines(self.open_doctrines):
            gone = self.open_doctrines
            self.open_doctrines = ""
            self.send_to_od = False
            # Searched stays true: the player asked once, and a game that has
            # been moved should not silently turn the button back into "Find".
            self.status = f"{gone} is no longer Open Doctrines -- search again."
            self.status_ok = False

    def refresh_ui(self):
        self._verify_od()
        self.elements = [
            make_back_button(self.exit_screen),
            # Below the title, not beside it: at "medium" these two are wide
            # enough that the second one runs through the centred heading.
            # "medium" is 200 wide, so 25 and 255 leaves 30 between them.
            Button(25, 90, "medium", "green" if self.direction == "TO_ODMAP" else "grey",
                   "GD5 to .odmap", lambda: self.set_direction("TO_ODMAP")),
            Button(255, 90, "medium", "green" if self.direction == "FROM_ODMAP" else "grey",
                   ".odmap to GD5", lambda: self.set_direction("FROM_ODMAP")),
        ]

        # A browser has no folders, so it gets the two things it does have:
        # a download on the way out, and a file picker on the way in. The
        # desktop's search-and-install controls below mean nothing here.
        if odtl.IS_WEB:
            self.elements.append(
                Button(c.SCREEN_WIDTH - 230, 25, "medium", "light_blue",
                       "Import .odmap...", self.ask_for_upload, font_preset="small"))
        elif self.direction == "TO_ODMAP":
            if not self.searched_for_od:
                self.elements.append(
                    Button(c.SCREEN_WIDTH - 230, 25, "medium", "light_blue",
                           "Find Open Doctrines", self._find_od, font_preset="small"))
                self.elements.append(
                    Button(c.SCREEN_WIDTH - 450, 25, "medium", "grey",
                           "Choose folder...", self.choose_od_folder, font_preset="small"))
            elif self.open_doctrines:
                self.elements.append(
                    Button(c.SCREEN_WIDTH - 230, 25, "medium",
                           "green" if self.send_to_od else "grey",
                           "Into Open Doctrines" if self.send_to_od else "Into translated/",
                           self.toggle_destination, font_preset="small"))
                self.elements.append(
                    Button(c.SCREEN_WIDTH - 450, 25, "medium", "grey",
                           "Choose folder...", self.choose_od_folder, font_preset="small"))
            else:
                # Searched, and either found nothing or lost what it found.
                # The manual pick matters most here: a search that came back
                # empty is exactly when a player knows where it is and the
                # game does not.
                self.elements.append(
                    Button(c.SCREEN_WIDTH - 230, 25, "medium", "light_blue",
                           "Search again", self._find_od, font_preset="small"))
                self.elements.append(
                    Button(c.SCREEN_WIDTH - 450, 25, "medium", "grey",
                           "Choose folder...", self.choose_od_folder, font_preset="small"))

        items = self._items()
        self.scroll_content_rect = pygame.Rect(0, 110, self.LIST_WIDTH,
                                               (c.SCREEN_HEIGHT - 60) - 110)
        for i, row_y in self.layout_list_rows(len(items), self.ROW_HEIGHT, self.ROW_TOP,
                                              cull_bottom=c.SCREEN_HEIGHT - 60):
            name, path = items[i]
            self.elements.append(
                Button(25, row_y, "new_game", "light_blue", name,
                       lambda n=name, p=path: self.translate(n, p),
                       font_preset="small"))

    def additional_draw(self, surface):
        items = self._items()
        if not items:
            empty = ("No maps found." if self.direction == "TO_ODMAP" else
                     f"Put .odmap files in {self.TRANSLATED_DIR}/ and they appear here.")
            fonts.draw_text_with_shadow(surface, empty, 25, self.ROW_TOP,
                                        "normal", (180, 180, 180))

        below = self._draw_warning(surface)
        self._draw_result(surface, below + 18)
        self._draw_credit(surface)

    WARNING_LINES = (
        "Translation is lossy, and not equally so",
        "in both directions.",
        "",
        "GD5 has manpower, fuel and faction",
        "leaders Open Doctrines has no field for.",
        "Open Doctrines has fortification and port",
        "technology GD5 does not. Neither game",
        "invents the other's, and nothing is",
        "guessed at.",
        "",
        "What has no home in the destination is",
        "carried in a sidecar file beside the map.",
        "Both games ignore files they do not know,",
        "so a translated map loads normally -- and",
        "translating it back returns what was set",
        "aside.",
    )

    def _draw_warning(self, surface):
        """The side panel. It is not decoration: a player is about to make a
        file for a different game out of somebody's map, and what does not
        survive that is worth reading before rather than after."""
        x = self.LIST_WIDTH + 40
        y = 120
        width = c.SCREEN_WIDTH - x - 30

        # Sized to its own text. A fixed height cut the last two lines off
        # below the border, which is a poor look for the panel whose whole job
        # is to be read before anything is written.
        # The trailing room is for the version line, which is drawn inside.
        height = 34 + len(self.WARNING_LINES) * 15 + 38
        panel = pygame.Rect(x - 12, y - 12, width + 24, height)
        pygame.draw.rect(surface, (30, 30, 40), panel, border_radius=8)
        pygame.draw.rect(surface, (200, 160, 60), panel, width=2, border_radius=8)

        fonts.draw_text_with_shadow(surface, "EXPERIMENTAL", x, y, "heading2", (240, 200, 90))
        y += 34

        for line in self.WARNING_LINES:
            if line:
                fonts.draw_text_with_shadow(surface, line, x, y, "small", (190, 195, 205))
            y += 15

        version = odtl.version() if odtl.available() else (odtl.unavailable_reason() or "unavailable")
        fonts.draw_text_with_shadow(surface, f"open-dragoman {version}", x, y + 4,
                                    "tiny", (120, 125, 140))
        return panel.bottom

    def _draw_result(self, surface, y):
        if not self.status:
            return
        x = self.LIST_WIDTH + 40
        colour = (120, 220, 150) if self.status_ok else (240, 130, 130)
        fonts.draw_text_with_shadow(surface, self.status[:70], x, y, "small", colour)
        y += 22

        if self.notes:
            fonts.draw_text_with_shadow(surface, f"{len(self.notes)} note(s):", x, y,
                                        "small", (220, 190, 110))
            y += 18
            for note in self.notes[:8]:
                fonts.draw_text_with_shadow(surface, "- " + note[:64], x, y, "tiny",
                                            (175, 180, 195))
                y += 14

    def _draw_credit(self, surface):
        """Small, in the corner, and not in anybody's way."""
        fonts.draw_text_with_shadow(surface, "Pr1nted", c.SCREEN_WIDTH - 70,
                                    c.SCREEN_HEIGHT - 22, "tiny", (110, 115, 130))

    def additional_events(self, event):
        self.handle_list_scroll(event)
