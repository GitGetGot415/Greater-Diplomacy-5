"""Reading your mail: popups that know when they are done, and terms that stay.

Three faults, all of them "the UI shows a thing and then never revisits it".

A diplomatic popup was created and never looked at again, so accepting a trade
left its alert sitting on screen next to an offer that no longer existed.
Dismissing one by hand is a different act from reading it, though, and must stay
that way: the X closes the window, it does not open the letter.

And a trade's numbers lived only on the sender's pending_diplomacy entry, which
is deleted the moment the offer resolves -- so a player who accepted a trade had
no way to see afterwards what they had agreed to.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
pygame.init()
pygame.display.set_mode((800, 600))

import data.constants as c
from map_logic.diplomacy import diplomacy_messages as dm
from ui import diplomatic_popups


class Clock:
    @staticmethod
    def get_date_string():
        return "1 January 1939"


class Screen:
    time_manager = Clock()
    player_country = "Player"

    def __init__(self, nation_data):
        self.nation_data = nation_data
        self.diplomatic_popups = []


def nation(**over):
    base = {"inbox": [], "pending_diplomacy": {}, "diplo_responses": {},
            "at_war_with": [], "faction": "", "master": "", "puppets": []}
    base.update(over)
    return base


class PopupLifetimeTests(unittest.TestCase):

    def setUp(self):
        self.msg = {"sender": "Avaria", "content": "We propose a trade.",
                    "type": "DIPLOMACY", "read": False, "date": "1 January 1939"}
        self.nation_data = {
            "Player": nation(inbox=[self.msg]),
            "Avaria": nation(pending_diplomacy={
                "Player": {"action": "TRADE", "turns": 1,
                           "parameters": {"give_materials": 500, "take_fuel": 100}}}),
        }
        self.screen = Screen(self.nation_data)
        diplomatic_popups.spawn_popups_for_player(self.screen)

    def test_an_incoming_request_raises_a_popup(self):
        self.assertEqual(len(self.screen.diplomatic_popups), 1)

    def test_it_stays_up_while_the_request_is_unanswered(self):
        diplomatic_popups.close_spent_popups(self.screen)
        self.assertEqual(len(self.screen.diplomatic_popups), 1)

    def test_answering_the_request_closes_it(self):
        dm.set_response(self.nation_data, "Player", "Avaria", dm.RESPONSE_ACCEPT, "TRADE")
        diplomatic_popups.close_spent_popups(self.screen)
        self.assertEqual(self.screen.diplomatic_popups, [])

    def test_declining_closes_it_too(self):
        dm.set_response(self.nation_data, "Player", "Avaria", dm.RESPONSE_REJECT, "TRADE")
        diplomatic_popups.close_spent_popups(self.screen)
        self.assertEqual(self.screen.diplomatic_popups, [])

    def test_reading_the_message_closes_it(self):
        self.msg["read"] = True
        diplomatic_popups.close_spent_popups(self.screen)
        self.assertEqual(self.screen.diplomatic_popups, [])

    def test_dismissing_it_by_hand_leaves_the_message_unread(self):
        """Closing a window is not reading a letter."""
        popup = self.screen.diplomatic_popups[0]
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                   pos=popup.x_rect.center)
        diplomatic_popups.handle_events(self.screen, event)
        self.assertEqual(self.screen.diplomatic_popups, [])
        self.assertFalse(self.msg.get("read"), "dismissing must not mark it read")

    def test_a_spent_popup_does_not_swallow_the_click_underneath_it(self):
        self.msg["read"] = True
        popup = self.screen.diplomatic_popups[0]
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                   pos=popup.rect.center)
        self.assertFalse(diplomatic_popups.handle_events(self.screen, event))

    def test_a_plain_message_with_no_request_behind_it_stays_up(self):
        self.nation_data["Avaria"]["pending_diplomacy"] = {}
        diplomatic_popups.close_spent_popups(self.screen)
        self.assertEqual(len(self.screen.diplomatic_popups), 1)

    def test_a_popup_with_no_message_behind_it_is_never_reaped(self):
        """Older popups, and any built by hand, must not vanish on sight."""
        orphan = diplomatic_popups.DiplomaticPopup("Avaria", "hello", 0)
        self.screen.diplomatic_popups = [orphan]
        diplomatic_popups.close_spent_popups(self.screen)
        self.assertEqual(self.screen.diplomatic_popups, [orphan])

    def test_the_players_own_sent_copy_never_raises_one(self):
        self.screen.diplomatic_popups = []
        self.nation_data["Player"]["inbox"] = [
            {"sender": "To: Avaria", "content": "Our terms.", "type": "DIPLOMACY",
             "read": True, "date": "1 January 1939"}]
        diplomatic_popups.spawn_popups_for_player(self.screen)
        self.assertEqual(self.screen.diplomatic_popups, [])


class ArchivedTradeTermsTests(unittest.TestCase):
    """The terms have to outlive the offer that carried them."""

    PARAMS = {"give_materials": 4200, "take_fuel": 1100}

    def setUp(self):
        self.nation_data = {"Avaria": nation(), "Borland": nation()}
        self.screen = Screen(self.nation_data)

    def send(self):
        dm.send_treaty_message(self.screen, "Avaria", "Borland", "TRADE",
                               parameters=self.PARAMS)

    def test_the_terms_are_recorded_on_the_receivers_copy(self):
        self.send()
        self.assertEqual(self.nation_data["Borland"]["inbox"][0]["parameters"], self.PARAMS)

    def test_and_on_the_senders_own_copy(self):
        self.send()
        self.assertEqual(self.nation_data["Avaria"]["inbox"][0]["parameters"], self.PARAMS)

    def test_they_survive_the_offer_being_cleared(self):
        """Which is what happens the instant the trade is accepted."""
        self.nation_data["Avaria"]["pending_diplomacy"]["Borland"] = {
            "action": "TRADE", "turns": 1, "parameters": self.PARAMS}
        self.send()
        dm.clear_pending(self.nation_data, "Avaria", "Borland")
        self.assertEqual(self.nation_data["Borland"]["inbox"][0]["parameters"], self.PARAMS)

    def test_the_two_sides_read_the_same_record_opposite_ways(self):
        """Keys are written from the proposer's point of view, so rendering
        them the same way for both would tell one side the exact opposite of
        what it agreed to."""
        self.send()
        theirs = dm.describe_trade(
            self.nation_data["Borland"]["inbox"][0]["parameters"], viewer_is_proposer=False)
        ours = dm.describe_trade(
            self.nation_data["Avaria"]["inbox"][0]["parameters"], viewer_is_proposer=True)
        self.assertEqual(theirs[0], "You receive: 4200 Materials")
        self.assertEqual(ours[0], "You receive: 1100 Fuel")

    def test_a_message_carrying_no_terms_is_unchanged(self):
        dm.send_treaty_message(self.screen, "Avaria", "Borland", "CEASEFIRE")
        self.assertNotIn("parameters", self.nation_data["Borland"]["inbox"][0])

    def test_an_ordinary_message_still_sends(self):
        dm.send_message(self.screen, "Avaria", "Borland", "Hello.", "TEXT")
        self.assertEqual(self.nation_data["Borland"]["inbox"][0]["content"], "Hello.")
        self.assertFalse(self.nation_data["Borland"]["inbox"][0]["read"])
        self.assertTrue(self.nation_data["Avaria"]["inbox"][0]["read"])

    def test_extra_cannot_forge_the_sender(self):
        """It is applied over the built entry, so this is worth knowing about
        rather than discovering later."""
        dm.send_message(self.screen, "Avaria", "Borland", "Hi", "TEXT",
                        extra={"parameters": {"give_fuel": 1}})
        self.assertEqual(self.nation_data["Borland"]["inbox"][0]["sender"], "Avaria")


class TableRowClickTests(unittest.TestCase):
    """A fixed-width column has to truncate; a row has to open the whole thing."""

    def build(self, on_row_click=None):
        from ui.table_screen import TableScreen, TableColumn
        rows = [{"message": "a" * 400, "sender": "Avaria"},
                {"message": "short", "sender": "Borland"}]
        cols = [TableColumn("sender", "Sender", 120),
                TableColumn("message", "Message", 700, align="left")]
        return TableScreen(Screen({}), "T", cols, rows, on_row_click=on_row_click)

    def test_a_table_with_no_handler_collects_no_hitboxes(self):
        screen = self.build()
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertEqual(screen.row_hitboxes, [])

    def test_a_table_with_a_handler_makes_its_rows_clickable(self):
        screen = self.build(on_row_click=lambda row: None)
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertEqual(len(screen.row_hitboxes), 2)

    def test_clicking_a_row_hands_over_that_row(self):
        """Deliberately the second row: clicking the first passes whether the
        hit test works or not, since it is what the loop reaches first."""
        opened = []
        screen = self.build(on_row_click=opened.append)
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        rect, row = screen.row_hitboxes[1]
        screen.additional_events(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center))
        self.assertEqual(opened, [row])
        self.assertEqual(row["sender"], "Borland")

    def test_clicking_below_the_last_row_opens_nothing(self):
        """Inside the scroll region, so the early bounds check cannot be what
        rejects it -- only the per-row hit test can."""
        opened = []
        screen = self.build(on_row_click=opened.append)
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        last_rect = screen.row_hitboxes[-1][0]
        below = (last_rect.centerx, last_rect.bottom + 60)
        self.assertTrue(screen.scroll_content_rect.collidepoint(below))
        screen.additional_events(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=below))
        self.assertEqual(opened, [])

    def test_clicking_outside_the_table_entirely_opens_nothing(self):
        opened = []
        screen = self.build(on_row_click=opened.append)
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        screen.additional_events(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=(2, 2)))
        self.assertEqual(opened, [])

    def test_the_detail_screen_renders_the_whole_message(self):
        from ui.text_detail_screen import TextDetailScreen
        long_text = " ".join(f"word{i}" for i in range(2000))
        detail = TextDetailScreen(Screen({}), "Avaria to Borland", long_text)
        detail.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        # max_scroll is zero or negative throughout this codebase: scroll_y
        # counts down from 0 towards it.
        self.assertLess(detail.max_scroll, 0, "a long message must be scrollable")

    def test_a_short_message_needs_no_scrolling(self):
        from ui.text_detail_screen import TextDetailScreen
        detail = TextDetailScreen(Screen({}), "Avaria to Borland", "Short.")
        detail.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertEqual(detail.max_scroll, 0)


if __name__ == "__main__":
    unittest.main()
