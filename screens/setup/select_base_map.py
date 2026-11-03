import os

import data.constants as c
from ui import dialogs
from ui.dialogs import file_exchange
from screens.game import map_launch
from ui.widgets.content_browser import ScenarioLibraryScreen
from ui.widgets.ui_elements import Button, make_back_button, play_ui_sound
from screens.setup import map_refresh


class Select_Base_Map(ScenarioLibraryScreen):
    back_state = "MENU"
    title = "MAP EDITOR"
    content_label = "maps"
    ACTION_COUNT = 3

    # Resolve directory settings when the screen refreshes.
    CATEGORIES = {
        "CUSTOM_MAPS": ("Custom Maps", "SCENARIOS_CUSTOM_DIR"),
        "BASE_MAPS": ("Base Maps", "BASE_MAPS_DIR"),
        "OTHER_HISTORICAL": ("Historical Scenarios", "SCENARIOS_HISTORICAL_DIR"),
        "OTHER_ALTERNATE": ("Alternate Scenarios", "SCENARIOS_ALTERNATE_DIR"),
    }

    def __init__(self):
        super().__init__()
        self.bg_color = (40, 20, 60)
        self.selected_save_path = None
        self.sub_state = "CUSTOM_MAPS"
        self.choosing_sources = False
        self.refresh_ui()

    def on_enter(self, app, previous):
        # Refresh on entry. Frame updates use cached entries.
        self.selected_entry = None
        self.choosing_sources = False
        self.sub_state = "CUSTOM_MAPS"
        self.sort_index = 0
        self.reload_entries()

    def get_title(self):
        return "NEW MAP" if self.choosing_sources else self.title

    @property
    def library_mode(self):
        return self.choosing_sources

    @property
    def library_categories(self):
        return {state: source for state, source in self.CATEGORIES.items() if state != "CUSTOM_MAPS"}

    def prepare_map(self, app):
        map_launch.open_saved_map(app, self.selected_save_path, force_editor=True)
        return True

    @property
    def managed_dir(self):
        return c.SCENARIOS_CUSTOM_DIR

    def refresh_ui(self):
        _label, directory_attr = self.CATEGORIES[self.sub_state]
        directory = getattr(c, directory_attr)
        if self.choosing_sources:
            self.build_browser(directory, "No maps in this category.")
            self.elements.append(make_back_button(self.return_to_maps))
            self.add_category_footer_action("Data Refresh", self.trigger_base_map_data_refresh, "purple",
                                            enabled=self.sub_state == "BASE_MAPS")
            self.open_button = self.add_primary_action("Create Map")
            return
        self.build_browser(directory, "No maps in this category. Import a custom map or choose another category.")
        self.elements.extend([
            make_back_button(self.exit_screen),
            Button(c.SCREEN_WIDTH - 324, 24, (160, 40), "green", "Import .zip", self.import_custom_map,
                   font_preset="button_small"),
            Button(c.SCREEN_WIDTH - 152, 24, (128, 40), "grey", "Refresh", self.reload_entries,
                   font_preset="button_small"),
        ])
        if self.selected_entry:
            self.add_browser_action("Rename", lambda: self.manage_selected(self.start_rename), 0, "blue")
            self.add_browser_action("Export", lambda: self.manage_selected(self.export_scenario_zip), 1, "green")
            self.add_browser_action("Delete…", lambda: self.manage_selected(self.start_delete), 2, "red")
            self.open_button = self.add_primary_action("Edit Map")
        else:
            self.open_button = self.add_primary_action("New Map", self.return_to_sources)

    def return_to_sources(self):
        self.choosing_sources = True
        self.sort_index = 1
        self.set_sub_state("BASE_MAPS")

    def return_to_maps(self):
        self.choosing_sources = False
        self.sort_index = 0
        self.set_sub_state("CUSTOM_MAPS")

    def import_custom_map(self):
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")
        file_exchange.import_zip_to_dir(self, self.managed_dir, self.reload_entries)

    def manage_selected(self, handler):
        if self.sub_state == "CUSTOM_MAPS":
            self.call_selected(handler)

    def activate_selected(self):
        if self.selection_can_open:
            entry = self.selected_entry
            play_ui_sound("click")
            self.start_editor_with_map(entry.name, os.path.dirname(entry.path))

    def trigger_base_map_data_refresh(self):
        """Refresh base map data after confirmation."""
        if self.sub_state != "BASE_MAPS":
            return

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
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")
        self.go_to("MAP")

    def exit_screen(self):
        self.choosing_sources = False
        self.set_sub_state("CUSTOM_MAPS")
        super().exit_screen()

    def handle_back_key(self):
        if self.search_field.active:
            self.finish_search()
        elif self.choosing_sources:
            play_ui_sound("back")
            self.return_to_maps()
        else:
            self.go_back()
