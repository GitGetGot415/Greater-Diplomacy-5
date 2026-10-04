"""Show the current viewer's events from the last completed turn."""
import data.constants as c
from data import queries
from map_logic.turn_processing import unit_events
from map_logic.rendering.font_manager import fonts
from ui import flag_icons, text_utils
from ui.table_screen import TableColumn, TableScreen
from ui_elements import Button

BACKGROUND_COLOR = (80, 60, 40)
ROW_COLOR = (48, 35, 25)
TABLE_MARGIN = 25
CELL_PADDING = 12
UNREAD_BUTTON_SIZE = (120, 30)
UNREAD_BUTTON_MARGIN = 20
FILTER_BUTTON_SIZE = (160, UNREAD_BUTTON_SIZE[1])
BUTTON_GAP = 10
COLUMN_SHARES = (("unit_name", "Unit", .20), ("tile_id", "Tile", .08),
                 ("event_label", "Event", .17), ("amount", "Health", .09),
                 ("details", "Details (click row)", .46))


class UnitEventsScreen(TableScreen):
    def __init__(self, map_screen):
        self.all_rows = [row | {"event_label": unit_events.EVENT_LABELS[row["event"]]}
                         for row in unit_events.entries_for(map_screen)]
        self.flags = {owner: flag_icons.flag_surface(owner, map_screen.nation_data)
                      for owner in {row["owner"] for row in self.all_rows}}
        self.event_filter = unit_events.event_filter_for(map_screen)
        rows = self.filtered_rows()
        available = c.SCREEN_WIDTH - 2 * TABLE_MARGIN
        widths = [int(available * share) for _key, _label, share in COLUMN_SHARES]
        widths[-1] = available - sum(widths[:-1])
        columns = []
        for (key, label, _share), width in zip(COLUMN_SHARES, widths):
            icon = (lambda row: self.flags[row["owner"]]) if key == "unit_name" else None
            text_width = width - CELL_PADDING
            if icon is not None:
                text_width -= flag_icons.ROW_FLAG_SIZE[0] + self.CELL_ICON_GAP
            def fit(value, key=key, text_width=text_width):
                text = f"{value:.2f}" if key == "amount" and value else "" if key == "amount" else str(value)
                return text_utils.fit_text(text, fonts.get("small"), text_width)
            columns.append(TableColumn(key, label, width, align="left", fmt=fit, icon=icon))
        super().__init__(map_screen, "Unit events - Last turn", columns, rows,
                         empty_message=self.empty_report_message(),
                         on_row_click=self.show_event, row_tint=lambda _row: ROW_COLOR)
        self.bg_color = BACKGROUND_COLOR
        unit_events.mark_read(map_screen)
        map_screen.btn_unit_events.notification_count = map_screen._unit_event_unread

    def refresh_ui(self):
        super().refresh_ui()
        self.btn_mark_all_unread = Button(
            c.SCREEN_WIDTH - UNREAD_BUTTON_MARGIN - UNREAD_BUTTON_SIZE[0],
            UNREAD_BUTTON_MARGIN, UNREAD_BUTTON_SIZE, "yellow", "Mark all unread",
            self.mark_all_unread, font_preset="button_small")
        self.btn_mark_all_unread.apply_state(enabled=bool(self.all_rows))
        label = unit_events.EVENT_LABELS[self.event_filter] if self.event_filter else "Filter events"
        self.btn_filter_events = Button(
            self.btn_mark_all_unread.rect.left - BUTTON_GAP - FILTER_BUTTON_SIZE[0],
            UNREAD_BUTTON_MARGIN, FILTER_BUTTON_SIZE, "orange" if self.event_filter else "blue",
            text_utils.fit_text(label, fonts.get("button_small"), FILTER_BUTTON_SIZE[0] - CELL_PADDING),
            self.choose_event_filter, font_preset="button_small")
        self.elements.extend((self.btn_filter_events, self.btn_mark_all_unread))

    def filtered_rows(self):
        return [row for row in self.all_rows if self.event_filter is None or row["event"] == self.event_filter]

    def empty_report_message(self):
        return ("No events of this type from the last turn." if self.event_filter
                else "No unit events from the last turn.")

    def choose_event_filter(self):
        items = [("No filter", None)] + [(label, event) for event, label in unit_events.EVENT_LABELS.items()]
        queries.open_listbox_selector(self, "Filter unit events", "Select an event type or No filter.",
                                      items, self.set_event_filter)

    def set_event_filter(self, event):
        unit_events.set_event_filter(self.map_screen, event)
        self.event_filter = event
        self.rows = self.filtered_rows()
        self.empty_message = self.empty_report_message()
        self.scroll_y = 0
        self.max_scroll = 0
        self.row_hitboxes = []
        self.sort_reverse.clear()
        self.refresh_ui()

    def mark_all_unread(self):
        unit_events.mark_unread(self.map_screen)
        self.map_screen.btn_unit_events.notification_count = self.map_screen._unit_event_unread

    def draw_background(self, surface):
        self.draw_checkerboard_background(surface, self.bg_color)

    def show_event(self, row):
        from ui import confirm_dialog
        amount = f"\nHealth: {row['amount']:.2f}" if row["amount"] else ""
        confirm_dialog.show_info(row["event_label"],
            f"{row['unit_name']}\nTile: {row['tile_id']}{amount}\n{row['details']}")
