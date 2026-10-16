"""Read-only country information, prepared when the player opens the screen."""

import pygame

import data.constants as c
from data import queries
from gameState import GameState
from map_logic.rendering.font_manager import fonts
from ui import flag_icons
from ui.bars import ui_bars
from ui.text_utils import fit_text, wrap_text
from ui_elements import Slider, make_back_button

PAGE_MARGIN = 40
COLUMN_GAP = 24
CARD_GAP = 20
CARD_PADDING = 18
CARD_TITLE_HEIGHT = 40
LINE_GAP = 5
CONTENT_TOP = 120
CONTENT_BOTTOM_MARGIN = 25
HEADER_FLAG_POS = (165, 25)
HEADER_FLAG_SIZE = (96, 64)
HEADER_TEXT_X = HEADER_FLAG_POS[0] + HEADER_FLAG_SIZE[0] + 24
ECONOMY_ROW_HEIGHT = 27
ECONOMY_COLUMN_FRACTIONS = (0.36, 0.56, 0.76, 0.96)
SUMMARY_SLIDER_GAP = 65
SUMMARY_SLIDER_HEIGHT = 20


class CountrySummaryScreen(GameState):
    def __init__(self, map_screen, country_id):
        super().__init__()
        self.map_screen = map_screen
        self.country_id = country_id
        self.bg_color = (25, 30, 40)
        self.summary = queries.get_country_summary(map_screen, country_id)
        self.flag = flag_icons.flag_surface(country_id, map_screen.nation_data, HEADER_FLAG_SIZE)
        self._layout_width = None
        self.refresh_ui()

    def _names(self, country_ids):
        return ", ".join(queries.get_country_display_name(country, self.map_screen.nation_data)
                         for country in country_ids) or "None"

    def _military_lines(self):
        military = self.summary["military"]
        scope = "Total" if military["complete"] else "Visible"
        multiplier = military["damage_multiplier"]
        return [
            f"Damage modifier: {multiplier - 1.0:+.2%} ({multiplier:.3g}x)",
            f"{scope} damage output: {military['raw_damage_output']:,.2f} "
            f"x {multiplier:.6g} = {military['damage_output']:,.2f}",
            f"{scope} units: {military['unit_count']:,}",
            f"Politics and policies: {military['political_damage_multiplier']:.3g}x damage",
            f"Conscription bonus: +{military['conscription_damage_bonus']:.2%}",
        ]

    def _politics_lines(self):
        politics = self.summary["politics"]
        direction = {-1: "Liberalising", 0: "Holding", 1: "Centralising"}[politics["drift"]]
        lines = [f"Position: {politics['label']} ({politics['value']:+d})",
                 f"Direction: {direction}",
                 f"Research modifier: {politics['research_multiplier'] - 1.0:+.2%}"]
        if not politics["policies"]:
            lines.append("Policies: None")
        for policy in politics["policies"]:
            state = policy["status"].lower().capitalize()
            remaining = policy["turns_remaining"]
            suffix = f", {remaining} turns remaining" if remaining else ""
            lines.append(f"{policy['name']}: {state}{suffix}")
        return lines

    def _diplomacy_lines(self):
        diplomacy = self.summary["diplomacy"]
        return [
            f"Faction: {diplomacy['faction'] or 'None'}",
            f"Faction leader: {self._names([diplomacy['faction_leader']]) if diplomacy['faction_leader'] else 'None'}",
            f"Faction members: {self._names(diplomacy['faction_members'])}",
            f"Overlord: {self._names([diplomacy['master']]) if diplomacy['master'] else 'None'}",
            f"Puppets ({len(diplomacy['puppets'])}): {self._names(diplomacy['puppets'])}",
            f"Allies: {self._names(diplomacy['allies'])}",
            f"At war with: {self._names(diplomacy['enemies'])}",
        ]

    def _card(self, title, lines, economy=False):
        font = fonts.get("normal")
        wrapped = [line for text in lines
                   for line in wrap_text(text, font, self.card_width - 2 * CARD_PADDING)]
        height = CARD_TITLE_HEIGHT + len(wrapped) * (font.get_height() + LINE_GAP) + CARD_PADDING
        table_y = height
        if economy:
            if self.summary["economy"]["available"]:
                height += ECONOMY_ROW_HEIGHT * (len(self.summary["economy"]["resources"]) + 1)
            slider_y = height + CARD_PADDING + font.get_height()
            height = slider_y + SUMMARY_SLIDER_GAP + SUMMARY_SLIDER_HEIGHT + CARD_PADDING
        card = pygame.Surface((self.card_width, height), pygame.SRCALPHA)
        ui_bars.draw_modal_box(card, card.get_rect(), bg_color=(35, 41, 53),
                               border_color=(75, 90, 115), border_width=1)
        card.blit(fonts.get("heading2").render(title, True, c.UI_ACCENT_BLUE),
                  (CARD_PADDING, CARD_PADDING // 2))
        y = CARD_TITLE_HEIGHT
        for line in wrapped:
            card.blit(font.render(line, True, c.UI_TEXT_BRIGHT), (CARD_PADDING, y))
            y += font.get_height() + LINE_GAP
        if economy:
            self._draw_economy_table(card, table_y)
            # These sliders are rendered into a cached card. They receive no
            # input and cannot edit either the player's or a foreign country.
            width = self.card_width - 2 * CARD_PADDING
            for index, (label, value, maximum) in enumerate((
                    ("Conscription (manpower kept)", self.summary["economy"]["conscription"], 1.0),
                    ("Materials to fuel", self.summary["economy"]["conversion"], c.MAX_CONVERSION_SLIDER_VAL))):
                Slider(CARD_PADDING, slider_y + index * SUMMARY_SLIDER_GAP, width,
                       label, value, None, visual_max=maximum, allowed_max=maximum).draw(card)
        return card

    def _draw_economy_table(self, card, top):
        if not self.summary["economy"]["available"]:
            return
        font = fonts.get("normal")
        right_edges = [int(self.card_width * fraction) for fraction in ECONOMY_COLUMN_FRACTIONS]
        card.blit(font.render("Resource", True, c.UI_TEXT_MUTED), (CARD_PADDING, top))
        for title, right in zip(("Stock", "Income", "Expenses", "Net"), right_edges):
            rendered = font.render(title, True, c.UI_TEXT_MUTED)
            card.blit(rendered, rendered.get_rect(topright=(right, top)))
        for index, row in enumerate(self.summary["economy"]["resources"], 1):
            y = top + index * ECONOMY_ROW_HEIGHT
            card.blit(font.render(row["resource"].title(), True, c.UI_TEXT_BRIGHT), (CARD_PADDING, y))
            for key, right in zip(("stockpile", "income", "expenses", "net"), right_edges):
                text = f"{row[key]:+,.1f}" if key == "net" else f"{row[key]:,.1f}"
                rendered = font.render(text, True, c.UI_TEXT_BRIGHT)
                card.blit(rendered, rendered.get_rect(topright=(right, y)))

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]
        self.scroll_content_rect = pygame.Rect(
            PAGE_MARGIN, CONTENT_TOP, c.SCREEN_WIDTH - 2 * PAGE_MARGIN,
            c.SCREEN_HEIGHT - CONTENT_TOP - CONTENT_BOTTOM_MARGIN)
        if self._layout_width != c.SCREEN_WIDTH:
            self._layout_width = c.SCREEN_WIDTH
            self.card_width = (self.scroll_content_rect.width - COLUMN_GAP) // 2
            military = self._card("Military", self._military_lines())
            politics = self._card("Politics", self._politics_lines())
            economy_lines = (["Income, expenses, and net are per turn."]
                             if self.summary["economy"]["available"] else
                             ["Income, expenses, and stockpiles are private."])
            economy = self._card("Economy", economy_lines, economy=True)
            diplomacy = self._card("Diplomacy", self._diplomacy_lines())
            self.cards = [(military, 0, 0), (politics, self.card_width + COLUMN_GAP, 0),
                          (economy, 0, military.get_height() + CARD_GAP),
                          (diplomacy, self.card_width + COLUMN_GAP, politics.get_height() + CARD_GAP)]
            self.content_height = max(y + card.get_height() for card, _x, y in self.cards)
            font = fonts.get("heading1")
            self.heading = font.render(fit_text(
                self.summary["name"], font, c.SCREEN_WIDTH - HEADER_TEXT_X - PAGE_MARGIN),
                True, c.UI_TEXT_BRIGHT)
            self.subtitle = fonts.get("normal").render("Country summary / Read-only", True, c.UI_TEXT_MUTED)
        self.max_scroll = min(0, self.scroll_content_rect.height - self.content_height)
        self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.get_standard_scrollbar_rects(
            self.scroll_y, self.max_scroll, c.SCREEN_WIDTH - PAGE_MARGIN // 2,
            CONTENT_TOP, self.scroll_content_rect.height)

    def additional_events(self, event):
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_PAGEDOWN:
                self.scroll_y = max(self.max_scroll, self.scroll_y - self.scroll_content_rect.height)
                self.refresh_ui()
            elif event.key == pygame.K_PAGEUP:
                self.scroll_y = min(0, self.scroll_y + self.scroll_content_rect.height)
                self.refresh_ui()

    def additional_draw(self, surface):
        surface.blit(self.flag, HEADER_FLAG_POS)
        surface.blit(self.heading, (HEADER_TEXT_X, HEADER_FLAG_POS[1]))
        surface.blit(self.subtitle, (HEADER_TEXT_X, HEADER_FLAG_POS[1] + 42))
        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect):
            for card, x, y in self.cards:
                surface.blit(card, (PAGE_MARGIN + x, CONTENT_TOP + y + self.scroll_y))
        ui_bars.draw_standard_scrollbar(surface, self.scroll_y, self.max_scroll,
                                       c.SCREEN_WIDTH - PAGE_MARGIN // 2, CONTENT_TOP,
                                       self.scroll_content_rect.height)


def open_country_summary(map_screen, country_id):
    """Open a country inspection without changing the selected tile or player."""
    if country_id not in map_screen.nation_data or country_id in c.UNPLAYABLE_NATIONS:
        return
    from ui.screen_runner import _run_pygame_sub_screen
    _run_pygame_sub_screen(map_screen, CountrySummaryScreen(map_screen, country_id))
