import os
from ui import dialogs
from ui.navigation.game_state import ButtonMenuScreen, FolderListState, RefreshingMenuListScreen
from ui.widgets.ui_elements import Button, make_back_button, play_ui_sound
import data.constants as c
from data import queries
from ui.dialogs import file_exchange
from screens.setup import map_refresh
class Select_Base_Map(RefreshingMenuListScreen, FolderListState):
    back_state = "MENU"

    # sub_state -> (button/header label, data.constants directory attribute name)
    # for browsing maps that live in other scenario directories.
    OTHER_MAP_CATEGORIES = {
        "OTHER_HISTORICAL": ("Historical Scenarios", "SCENARIOS_HISTORICAL_DIR"),
        "OTHER_ALTERNATE": ("Alternate Scenarios", "SCENARIOS_ALTERNATE_DIR"),
    }

    def __init__(self):
        super().__init__()
        self.bg_color = (40, 20, 60)
        self.selected_save_path = None
        self.sub_state = "CUSTOM_MAPS"

        self.last_custom_count = -1
        self.last_base_count = -1
        self.refresh_ui()

    @property
    def managed_dir(self):
        return c.SCENARIOS_CUSTOM_DIR

    def get_title(self):
        if self.sub_state == "CUSTOM_MAPS":
            return "EDIT EXISTING MAP"
        if self.sub_state == "BASE_MAPS":
            return "CREATE NEW MAP FROM BASE"
        if self.sub_state == "OTHER_CATEGORY":
            return "EDIT MAP FROM OTHER DIRECTORY"
        if self.sub_state in self.OTHER_MAP_CATEGORIES:
            return self.OTHER_MAP_CATEGORIES[self.sub_state][0].upper()
        return ""

    def has_menu_list(self):
        return self.sub_state != "OTHER_CATEGORY"

    def update(self):
        # Automatically refresh if the number of maps has changed since last viewed
        current_custom = len(os.listdir(c.SCENARIOS_CUSTOM_DIR)) if os.path.exists(c.SCENARIOS_CUSTOM_DIR) else 0
        current_base = len(os.listdir(c.BASE_MAPS_DIR)) if os.path.exists(c.BASE_MAPS_DIR) else 0

        if self.last_custom_count != current_custom or self.last_base_count != current_base:
            self.last_custom_count = current_custom
            self.last_base_count = current_base
            self.refresh_ui()

        # After the rebuild above, so new buttons also hide during a data refresh.
        super().update()

    def refresh_ui(self):
        self.elements = []

        if self.sub_state == "OTHER_CATEGORY":
            self.elements = [make_back_button(lambda: self.set_sub_state("CUSTOM_MAPS"))]
            self.elements += ButtonMenuScreen.build_menu_buttons(
                [(label, "blue", lambda s=state: self.set_sub_state(s))
                 for state, (label, _attr) in self.OTHER_MAP_CATEGORIES.items()])
            return

        is_custom = self.sub_state == "CUSTOM_MAPS"
        is_other_list = self.sub_state in self.OTHER_MAP_CATEGORIES

        if is_custom:
            self.elements.extend([
                make_back_button(self.exit_screen),
                Button(160, 20, "medium", "green", "Import .zip",
                       lambda: file_exchange.import_zip_to_dir(self, self.managed_dir, self.refresh_ui)),
                Button("centered-160", c.SCREEN_HEIGHT - 100, "large", "purple", "New Map",
                       lambda: self.set_sub_state("BASE_MAPS")),
                Button("centered+160", c.SCREEN_HEIGHT - 100, "large", "orange", "Edit Existing Map",
                       lambda: self.set_sub_state("OTHER_CATEGORY")),
            ])
            directory = c.SCENARIOS_CUSTOM_DIR
        elif is_other_list:
            _label, attr = self.OTHER_MAP_CATEGORIES[self.sub_state]
            directory = getattr(c, attr)
            self.elements.extend([
                make_back_button(lambda: self.set_sub_state("OTHER_CATEGORY")),
            ])
        else:
            self.elements.extend([
                make_back_button(lambda: self.set_sub_state("CUSTOM_MAPS")),
                Button(c.SCREEN_WIDTH - 220, 20, "medium", "purple", "Data Refresh",
                       self.trigger_base_map_data_refresh),
            ])
            directory = c.BASE_MAPS_DIR

        names = self.list_folders(directory)

        # Base maps and maps from other scenario directories are read-only
        # here: one centred button that opens the map into the editor as
        # a copy (saving from the editor always writes a new map, it
        # never overwrites the original).
        if not is_custom:
            self.add_menu_list([(name, name) for name in names],
                               lambda name, d=directory: self.start_editor_with_map(name, d))
            return

        for i, btn_y in self.layout_menu_list(len(names)):
            name = names[i]

            row_buttons = [
                Button(c.SCREEN_WIDTH // 2 - 250, btn_y, "new_game", "blue", name,
                       lambda n=name: self.start_editor_with_map(n, c.SCENARIOS_CUSTOM_DIR)),
                Button(c.SCREEN_WIDTH // 2 + 70, btn_y + 5, "small", "grey", "Rename",
                       lambda n=name: self.start_rename(n)),
                Button(c.SCREEN_WIDTH // 2 + 190, btn_y + 5, "small", "green", "Export",
                       lambda n=name: self.export_scenario_zip(n)),
                Button(c.SCREEN_WIDTH // 2 + 310, btn_y + 5, "small_square", "red", "X",
                       lambda n=name: self.start_delete(n)),
            ]
            for btn in row_buttons:
                self.add_list_row(btn)

    def trigger_base_map_data_refresh(self):
        """Calls the unified data refresh query for base maps."""
        def on_confirm(confirm):
            if confirm:
                map_refresh.refresh_map_directories(self, [c.BASE_MAPS_DIR],
                                                success_message="Synced base maps successfully.")

        dialogs.ask_yes_no(
            "Confirm Data Refresh",
            "Are you sure you want to refresh base map data?\nThis process may take a while.",
            on_confirm
        )

    def export_scenario_zip(self, scenario_name):
        file_exchange.export_dir_as_zip(os.path.join(self.managed_dir, scenario_name),
                                  f"{scenario_name}_scenario.zip")

    def start_editor_with_map(self, map_name, directory):
        self.selected_save_path = os.path.join(directory, map_name)
        self.set_sub_state("CUSTOM_MAPS")
        self.go_to("MAP")

    def exit_screen(self):
        self.set_sub_state("CUSTOM_MAPS")
        super().exit_screen()

    def handle_back_key(self):
        # Escape steps back up the sub-state tree before it leaves the screen.
        if self.sub_state == "CUSTOM_MAPS":
            self.go_back()
            return
        play_ui_sound("back")
        if self.sub_state in self.OTHER_MAP_CATEGORIES:
            self.set_sub_state("OTHER_CATEGORY")
        else:
            self.set_sub_state("CUSTOM_MAPS")
