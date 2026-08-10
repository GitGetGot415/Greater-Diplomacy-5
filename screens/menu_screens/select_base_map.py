import os
import pygame
from ui import confirm_dialog
from gameState import FolderListState
from ui_elements import Button, make_back_button
import data.constants as c
from data import queries
from map_logic.turn_processing import loading_screen

class Select_Base_Map(FolderListState):
    back_state = "MENU"

    ROW_HEIGHT = 60
    ROW_TOP = 150
    ROW_CULL_BOTTOM_MARGIN = 120

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

        # --- REFRESH STATE ---
        self.is_refreshing = False
        self.refresh_total = 0
        self.refresh_completed = 0
        self.refresh_status = ""

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

    def set_sub_state(self, state):
        self.sub_state = state
        self.scroll_y = 0
        self.renaming_item = None
        self.deleting_item = None
        self.refresh_ui()

    def update(self):
        super().update()

        # Automatically refresh if the number of maps has changed since last viewed
        current_custom = len(os.listdir(c.SCENARIOS_CUSTOM_DIR)) if os.path.exists(c.SCENARIOS_CUSTOM_DIR) else 0
        current_base = len(os.listdir(c.BASE_MAPS_DIR)) if os.path.exists(c.BASE_MAPS_DIR) else 0

        if self.last_custom_count != current_custom or self.last_base_count != current_base:
            self.last_custom_count = current_custom
            self.last_base_count = current_base
            self.refresh_ui()

        # Forcefully hide all UI buttons while the loading screen is active
        for el in self.elements:
            el.visible = not self.is_refreshing

    def refresh_ui(self):
        self.elements = []

        if self.sub_state == "OTHER_CATEGORY":
            self.elements = [make_back_button(lambda: self.set_sub_state("CUSTOM_MAPS"))]
            for i, (state, (label, _attr)) in enumerate(self.OTHER_MAP_CATEGORIES.items()):
                self.elements.append(
                    Button("centered", 220 + i * 100, "large", "blue", label,
                           lambda s=state: self.set_sub_state(s)))
            return

        is_custom = self.sub_state == "CUSTOM_MAPS"
        is_other_list = self.sub_state in self.OTHER_MAP_CATEGORIES

        if is_custom:
            self.elements.extend([
                make_back_button(self.exit_screen),
                Button(160, 20, "medium", "green", "Import .zip",
                       lambda: queries.import_zip_to_dir(self, self.managed_dir, self.refresh_ui)),
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
        cull_bottom = c.SCREEN_HEIGHT - self.ROW_CULL_BOTTOM_MARGIN
        self.scroll_content_rect = pygame.Rect(0, 100, c.SCREEN_WIDTH, cull_bottom - 100)
        rows = self.layout_list_rows(len(names), self.ROW_HEIGHT, self.ROW_TOP, pad=20,
                                    cull_bottom=cull_bottom)

        for i, btn_y in rows:
            name = names[i]

            # Base maps and maps from other scenario directories are read-only
            # here: one centred button that opens the map into the editor as
            # a copy (saving from the editor always writes a new map, it
            # never overwrites the original).
            if not is_custom:
                btn = Button("centered", btn_y, "new_game", "blue", name,
                            lambda n=name, d=directory: self.start_editor_with_map(n, d))
                btn.is_scrollable = True
                btn.click_guard = self.scroll_click_guard
                self.elements.append(btn)
                continue

            if self.is_row_hidden(name):
                continue

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
                btn.is_scrollable = True
                btn.click_guard = self.scroll_click_guard
            self.elements.extend(row_buttons)

    def trigger_base_map_data_refresh(self):
        """Calls the unified data refresh query for base maps."""
        def on_confirm(confirm):
            if confirm:
                queries.refresh_map_directories(self, [c.BASE_MAPS_DIR],
                                                success_message="Synced base maps successfully.")

        confirm_dialog.ask_yes_no(
            "Confirm Data Refresh",
            "Are you sure you want to refresh base map data?\nThis process may take a while.",
            on_confirm
        )

    def export_scenario_zip(self, scenario_name):
        queries.export_dir_as_zip(os.path.join(self.managed_dir, scenario_name),
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
        if self.sub_state == "BASE_MAPS":
            self.set_sub_state("CUSTOM_MAPS")
        elif self.sub_state == "OTHER_CATEGORY":
            self.set_sub_state("CUSTOM_MAPS")
        elif self.sub_state in self.OTHER_MAP_CATEGORIES:
            self.set_sub_state("OTHER_CATEGORY")
        else:
            self.exit_screen()

    def handle_events(self, events):
        if self.is_refreshing:
            return

        for event in events:
            if self.handle_name_prompt_event(event):
                continue

            if self.sub_state != "OTHER_CATEGORY":
                self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")
            super().handle_events([event])

    def additional_draw(self, surface):
        if self.sub_state != "OTHER_CATEGORY":
            self.draw_list_scrollbar(surface, c.SCREEN_WIDTH - 40, self.ROW_TOP, c.SCREEN_HEIGHT - 200)

        if self.renaming_item:
            names = self.list_folders()
            idx = names.index(self.renaming_item) if self.renaming_item in names else 0
            self.draw_rename_box(surface, c.SCREEN_WIDTH // 2 - 250,
                                 self.ROW_TOP + (idx * self.ROW_HEIGHT) + self.scroll_y)

        if self.deleting_item:
            self.draw_delete_confirm(surface)

    def draw(self, surface):
        super().draw(surface)

        # --- Draw Progress Bar Overlay ---
        if self.is_refreshing:
            loading_screen.draw_simple_refresh_bar(surface, self.refresh_status,
                                                   self.refresh_completed, self.refresh_total)
