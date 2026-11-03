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

import unittest
import copy
import json
from unittest import mock


import pygame
pygame.init()
pygame.display.set_mode((800, 600))

import data.constants as c
from tests.stub_map_screen import fill_state_defaults, map_double
from map_logic.diplomacy import diplomacy_messages as dm
from ui.panels import diplomatic_popups


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
        fill_state_defaults(self)


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

    def test_popup_uses_the_senders_country_name(self):
        self.msg["sender"] = "AVR"
        self.nation_data["AVR"] = self.nation_data.pop("Avaria")
        self.nation_data["AVR"]["name"] = "Avarian Republic"
        self.msg.pop("popup_shown", None)
        self.screen.diplomatic_popups = []

        diplomatic_popups.spawn_popups_for_player(self.screen)

        self.assertEqual("Avarian Republic", self.screen.diplomatic_popups[0].sender)

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


class TacticalModeTests(unittest.TestCase):
    """A tactical player commands a division, not a country.

    Their host's diplomacy is the AI's business -- it is handed the whole
    country on purpose -- and every screen an alert would send them to is
    read-only for them, so an alert is an interruption with nothing behind it.
    """

    def setUp(self):
        self.msg = {"sender": "Avaria", "content": "We propose a trade.",
                    "type": "DIPLOMACY", "read": False, "date": "1 January 1939"}
        self.screen = Screen({"Player": nation(inbox=[self.msg]), "Avaria": nation()})
        self.screen.tactical_mode = True

    def test_no_alert_is_raised(self):
        diplomatic_popups.spawn_popups_for_player(self.screen)
        self.assertEqual(self.screen.diplomatic_popups, [])

    def test_an_alert_already_up_is_taken_down(self):
        """Declaring independence is the only way the mode changes mid-game, but
        this runs every frame, so it must be the one that holds either way."""
        self.screen.diplomatic_popups = [
            diplomatic_popups.DiplomaticPopup("Avaria", "hello", 0)]

        diplomatic_popups.spawn_popups_for_player(self.screen)

        self.assertEqual(self.screen.diplomatic_popups, [])

    def test_the_message_is_not_saved_up_to_flood_them_later(self):
        """Declaring independence turns tactical mode off. A player who has just
        founded a country should not be handed a stack of alerts about treaties
        their old host signed."""
        diplomatic_popups.spawn_popups_for_player(self.screen)

        self.screen.tactical_mode = False
        diplomatic_popups.spawn_popups_for_player(self.screen)

        self.assertEqual(self.screen.diplomatic_popups, [])

    def test_a_strategic_player_still_gets_them(self):
        """Guards the tests above against passing for the wrong reason."""
        self.screen.tactical_mode = False

        diplomatic_popups.spawn_popups_for_player(self.screen)

        self.assertEqual(len(self.screen.diplomatic_popups), 1)


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
        from ui.widgets.table_screen import TableScreen, TableColumn
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
        from ui.widgets.text_detail_screen import TextDetailScreen
        long_text = " ".join(f"word{i}" for i in range(2000))
        detail = TextDetailScreen(Screen({}), "Avaria to Borland", long_text)
        detail.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        # max_scroll is zero or negative throughout this codebase: scroll_y
        # counts down from 0 towards it.
        self.assertLess(detail.max_scroll, 0, "a long message must be scrollable")

    def test_a_short_message_needs_no_scrolling(self):
        from ui.widgets.text_detail_screen import TextDetailScreen
        detail = TextDetailScreen(Screen({}), "Avaria to Borland", "Short.")
        detail.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertEqual(detail.max_scroll, 0)


class ConversationInteractionTests(unittest.TestCase):
    def setUp(self):
        # Every clock read is far later than the last, so slide-ins are finished
        # before a test reads hitboxes. Tests that time the slide patch it again.
        from screens.game import messages as messages_module

        readings = iter(range(0, 10 ** 9, 1000))
        patcher = mock.patch.object(messages_module.time, "monotonic", side_effect=lambda: next(readings))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_screen(self, *, tactical=False):
        from screens.game.messages import Messages_Screen

        screen = Messages_Screen()
        screen.start_messages(map_double(
            player_country="P", tactical_mode=tactical, show_feedback=mock.Mock(), feedback_text="",
            map_data={1: {"owner": "P"}, 2: {"owner": "A"}, 3: {"owner": "B"}},
            nation_data={
                "P": nation(name="Player", is_playable=True, inbox=[
                    {"sender": "A", "content": "Latest message", "read": False, "type": "TEXT", "date": "Today"},
                    {"sender": "B", "content": "Other conversation", "read": False, "type": "TEXT", "date": "Yesterday"}]),
                "A": nation(name="First country", is_playable=True),
                "B": nation(name="Second country", is_playable=True)}))
        return screen

    def test_conversation_row_selects_its_country_and_marks_only_that_thread_read(self):
        from screens.game.messages import ConversationRow

        screen = self.make_screen()
        row = next(element for element in screen.elements if isinstance(element, ConversationRow) and element.text == "Second country")
        with mock.patch.object(pygame.mouse, "get_pos", return_value=row.rect.center):
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=row.rect.center),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=row.rect.center)])
        self.assertEqual(screen.selected_recipient, "B")
        messages = screen.map_screen.nation_data["P"]["inbox"]
        self.assertFalse(messages[0]["read"])
        self.assertTrue(messages[1]["read"])

    def test_clipped_conversation_row_does_not_select_a_country(self):
        from screens.game.messages import ConversationRow

        screen = self.make_screen()
        row = next(element for element in screen.elements if isinstance(element, ConversationRow))
        row.rect.y = screen.scroll_content_rect.top - row.rect.height + 4
        point = (row.rect.centerx, row.rect.top + 10)
        with mock.patch.object(pygame.mouse, "get_pos", return_value=point):
            row.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point))
            row.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=point))
        self.assertIsNone(screen.selected_recipient)

    def test_new_contact_picker_can_scroll_to_and_open_the_last_country(self):
        from screens.game.messages import ConversationRow

        screen = self.make_screen()
        for index in range(20):
            country = f"C{index:02}"
            screen.map_screen.nation_data[country] = nation(name=f"Country {index:02}", is_playable=True)
            screen.map_screen.map_data[100 + index] = {"owner": country}
        screen.toggle_add_contact()
        screen.contact_scroll_y = screen.max_contact_scroll
        screen.refresh_ui()
        row = next(element for element in screen.elements if isinstance(element, ConversationRow) and element.text == "Country 19")
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        with mock.patch.object(pygame.mouse, "get_pos", return_value=row.rect.center):
            screen.handle_events([
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=row.rect.center),
                pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=row.rect.center)])
        self.assertEqual(screen.selected_recipient, "C19")
        self.assertFalse(screen.show_all_contacts)
        self.assertTrue(screen.text_input_active)
        self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "C19"), {})

    def test_fixed_controls_cannot_scroll_or_activate_hidden_thread_actions(self):
        screen = self.make_screen()
        screen.select_recipient("A")
        screen.drafts = ["Keep this draft"]
        screen.msg_scroll_y = 100
        screen.max_msg_scroll = 500
        with mock.patch.object(screen, "open_forward_picker") as forward:
            for point in ((700, 20), (700, screen.thread_rect.bottom + 15), (700, screen.input_rect.centery)):
                with self.subTest(point=point):
                    rect = pygame.Rect(point[0] - 10, point[1] - 10, 20, 20)
                    screen.draft_edit_rects = [(rect, 0)]
                    screen.forward_button_rects = [(rect, {})]
                    for event in (
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=point),
                        pygame.event.Event(pygame.MOUSEMOTION, pos=(point[0], point[1] + 30), rel=(0, 30), buttons=(1, 0, 0)),
                        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=point),
                        pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1, pos=point)):
                        screen.additional_events(event)
                    self.assertEqual(screen.msg_scroll_y, 100)
                    self.assertEqual(screen.drafts, ["Keep this draft"])
            forward.assert_not_called()

    def test_draw_uses_cached_conversation_and_refresh_reads_new_messages(self):
        from screens.game import messages as messages_module

        screen = self.make_screen()
        screen.select_recipient("A")
        prepared = screen.processed_messages
        with mock.patch.object(dm, "get_pending", side_effect=AssertionError("Draw read diplomacy")), \
                mock.patch.object(dm, "describe_trade", side_effect=AssertionError("Draw described terms")), \
                mock.patch.object(messages_module.flag_icons, "flag_surface", side_effect=AssertionError("Draw rebuilt flags")), \
                mock.patch.object(messages_module.text_utils, "wrap_text", side_effect=AssertionError("Draw wrapped messages")):
            screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
            screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        self.assertIs(screen.processed_messages, prepared)
        screen.map_screen.nation_data["P"]["inbox"].insert(0, {
            "sender": "A", "content": "New message", "read": False, "type": "TEXT", "date": "Today"})
        screen.refresh_ui()
        self.assertEqual(screen.processed_messages[0]["msg_data"]["content"], "New message")

    def test_conversation_bars_roll_with_selection_over_the_animation_time(self):
        from screens.game import messages as messages_module

        screen = self.make_screen()
        buttons = {element.text: element for element in screen.elements}
        rest_y = {name: buttons[name].rect.y for name in ("Trade", "Queue")}
        self.assertEqual(screen.bar_shown, 0.0)
        self.assertLess(buttons["Trade"].rect.bottom, 0)
        self.assertGreaterEqual(buttons["Queue"].rect.top, c.SCREEN_HEIGHT)

        seconds = messages_module.MSG_BAR_ANIM_SECONDS
        with mock.patch.object(messages_module.time, "monotonic", return_value=10.0):
            screen.select_recipient("A")
            screen.update()
            self.assertEqual(screen.bar_shown, 0.0)
        with mock.patch.object(messages_module.time, "monotonic", return_value=10.0 + seconds / 2):
            screen.update()
            midway = screen.bar_shown
        # Ease out covers more than half the distance in half the time.
        self.assertGreater(midway, 0.5)
        self.assertLess(midway, 1.0)
        with mock.patch.object(messages_module.time, "monotonic", return_value=10.0 + seconds):
            screen.update()
        self.assertEqual(screen.bar_shown, 1.0)
        buttons = {element.text: element for element in screen.elements}
        self.assertEqual({name: buttons[name].rect.y for name in rest_y}, rest_y)

        with mock.patch.object(messages_module.time, "monotonic", return_value=20.0):
            screen.select_recipient("A")
            screen.update()
        with mock.patch.object(messages_module.time, "monotonic", return_value=20.0 + seconds):
            screen.update()
        self.assertEqual(screen.bar_shown, 0.0)

    def test_bubbles_slide_in_from_their_own_side_and_only_once(self):
        from screens.game import messages as messages_module

        screen = self.make_screen()
        screen.map_screen.nation_data["P"]["inbox"].insert(0, {
            "sender": "To: A", "content": "Sent message", "read": True, "type": "TEXT", "date": "Today"})
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        with mock.patch.object(messages_module.time, "monotonic", return_value=50.0):
            screen.select_recipient("A")
            screen.drafts = ["Draft"]
            screen.refresh_ui()
            screen.draw(surface)
            # No time has passed: a sent bubble waits at the right edge of the thread.
            waiting_x = screen.draft_edit_rects[0][0].left
            starts = dict(screen.bubble_starts)
            screen.refresh_ui()
            self.assertEqual(screen.bubble_starts, starts)
        with mock.patch.object(messages_module.time, "monotonic",
                               return_value=50.0 + messages_module.MSG_BUBBLE_ANIM_SECONDS):
            screen.draw(surface)
        self.assertLess(screen.draft_edit_rects[0][0].left, waiting_x)

    def test_composer_edit_refreshes_its_cache_without_rebuilding_history(self):
        screen = self.make_screen()
        screen.select_recipient("A")
        prepared = screen.processed_messages
        old_text = screen.compose_surface
        screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, unicode="h", mod=0))
        self.assertEqual(screen.compose_text, "h")
        self.assertIsNot(screen.compose_surface, old_text)
        self.assertIs(screen.processed_messages, prepared)

    def test_deselect_keeps_only_cached_bubbles_and_disables_their_actions_until_exit_finishes(self):
        import copy
        from screens.game import messages as messages_module

        for name, seconds in (("MSG_BAR_ANIM_SECONDS", 0.1), ("MSG_BUBBLE_ANIM_SECONDS", 0.1),
                              ("MSG_BAR_EXIT_ANIM_SECONDS", 1.0), ("MSG_BUBBLE_EXIT_ANIM_SECONDS", 1.0)):
            patcher = mock.patch.object(messages_module, name, seconds)
            patcher.start()
            self.addCleanup(patcher.stop)
        screen = self.make_screen()
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        with mock.patch.object(messages_module.time, "monotonic", return_value=10.0):
            screen.select_recipient("A")
            screen.compose_text = "Keep this queued message"
            screen.send_message()
            screen.update()
        with mock.patch.object(messages_module.time, "monotonic", return_value=11.0):
            screen.update()
            screen.draw(surface)
            forward_rect = next(rect for rect, _message in screen.forward_button_rects if rect.width and rect.height)
            delete_rect = next(rect for rect, _index in screen.draft_edit_rects if rect.width and rect.height)
            state = copy.deepcopy(screen.map_screen.nation_data)
            surfaces = [prepared["surface"] for prepared in screen.processed_messages]
            screen.select_recipient("A")
            screen.update()
        self.assertIsNone(screen.selected_recipient)
        self.assertFalse(screen.text_input_active)
        self.assertEqual([prepared["surface"] for prepared in screen.exiting_thread["messages"]], surfaces)
        self.assertEqual(screen.map_screen.nation_data, state)
        halfway = 11.0 + messages_module.MSG_BUBBLE_EXIT_ANIM_SECONDS / 2
        with mock.patch.object(messages_module.time, "monotonic", return_value=halfway), \
                mock.patch.object(dm, "get_pending", side_effect=AssertionError("Exit read diplomacy")), \
                mock.patch.object(messages_module.text_utils, "wrap_text", side_effect=AssertionError("Exit rebuilt text")), \
                mock.patch.object(screen, "open_forward_picker") as forward:
            screen.update()
            screen.draw(surface)
            self.assertIsNotNone(screen.exiting_thread)
            self.assertIsNotNone(screen.bar_anim)
            self.assertEqual(screen.forward_button_rects, [])
            self.assertEqual(screen.draft_edit_rects, [])
            screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=forward_rect.center))
            screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=delete_rect.center))
            forward.assert_not_called()
        self.assertEqual(screen.map_screen.nation_data, state)
        with mock.patch.object(messages_module.time, "monotonic", return_value=11.0 + messages_module.MSG_BUBBLE_EXIT_ANIM_SECONDS + 0.001):
            screen.update()
        self.assertIsNone(screen.exiting_thread)
        self.assertIsNone(screen.bar_anim)

    def test_selecting_a_country_during_exit_releases_the_old_cache_and_keeps_its_draft(self):
        from screens.game import messages as messages_module

        screen = self.make_screen()
        with mock.patch.object(messages_module.time, "monotonic", return_value=20.0):
            screen.select_recipient("A")
            screen.compose_text = "Saved on deselect"
            screen.select_recipient("A")
            self.assertIsNotNone(screen.exiting_thread)
            screen.select_recipient("B")
        self.assertIsNone(screen.exiting_thread)
        self.assertEqual(screen.selected_recipient, "B")
        self.assertTrue(screen.text_input_active)
        self.assertEqual([prepared["msg_data"]["content"] for prepared in screen.processed_messages], ["Other conversation"])
        self.assertEqual(screen.map_screen.nation_data["P"]["draft_lists"]["A"], ["Saved on deselect"])

    def test_mark_unread_uses_exit_cache_and_still_marks_the_conversation_unread(self):
        from screens.game import messages as messages_module

        screen = self.make_screen()
        with mock.patch.object(messages_module.time, "monotonic", return_value=30.0):
            screen.select_recipient("A")
            screen.mark_thread_unread()
        self.assertIsNone(screen.selected_recipient)
        self.assertIsNotNone(screen.exiting_thread)
        self.assertFalse(screen.map_screen.nation_data["P"]["inbox"][0]["read"])
        screen.start_messages(screen.map_screen)
        self.assertIsNone(screen.exiting_thread)

    def test_follow_up_can_be_typed_and_queued_after_sending_a_message(self):
        import copy

        for submit_with_enter in (False, True):
            with self.subTest(enter=submit_with_enter):
                screen = self.make_screen()
                previous = copy.deepcopy(dm.set_pending(screen.map_screen.nation_data, "P", "A", "MSG:Previous turn", turns=1))
                screen.select_recipient("A")
                self.assertTrue(screen.compose_enabled)
                screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, unicode="h", mod=0))
                self.assertEqual(screen.compose_text, "h")
                if submit_with_enter:
                    screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0))
                else:
                    screen.update()
                    screen.update()
                    queue = next(element for element in screen.elements if element.text == "Queue")
                    screen.handle_events([
                        pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=queue.rect.center),
                        pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=queue.rect.center)])
                self.assertEqual(screen.compose_text, "")
                self.assertEqual(screen.map_screen.nation_data["P"]["draft_lists"]["A"], ["h"])
                self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "A"), previous)
                screen.select_recipient("B")
                screen.select_recipient("A")
                self.assertEqual(screen.drafts, ["h"])

    def test_follow_up_input_still_obeys_formal_action_and_tactical_restrictions(self):
        for tactical, action in ((False, "TRADE"), (True, "MSG:Previous turn")):
            with self.subTest(tactical=tactical, action=action):
                screen = self.make_screen(tactical=tactical)
                dm.set_pending(screen.map_screen.nation_data, "P", "A", action, turns=1)
                screen.select_recipient("A")
                self.assertFalse(screen.compose_enabled)
                screen.additional_events(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h, unicode="h", mod=0))
                self.assertEqual(screen.compose_text, "")

    def test_visible_forward_and_delete_controls_keep_their_callbacks(self):
        screen = self.make_screen()
        screen.select_recipient("A")
        screen.drafts = ["Queued text"]
        screen.save_current_draft()
        screen.refresh_ui()
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        forward_rect, original = next((rect, message) for rect, message in screen.forward_button_rects if rect.width and rect.height)
        with mock.patch.object(screen, "open_forward_picker") as forward:
            screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=forward_rect.center))
            forward.assert_called_once_with(original)
        delete_rect, _index = next((rect, index) for rect, index in screen.draft_edit_rects if rect.width and rect.height)
        screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=delete_rect.center))
        self.assertEqual(screen.drafts, [])
        self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "A"), {})

    def test_forward_to_an_existing_text_conversation_keeps_both_drafts_visible(self):
        screen = self.make_screen()
        dm.queue_text_message(screen.map_screen.nation_data, "P", "B", "Already queued")
        screen.select_recipient("A")
        original = screen.map_screen.nation_data["P"]["inbox"][0]
        screen.queue_forward(original, "B")
        screen.select_recipient("B")
        contents = [prepared["msg_data"]["content"] for prepared in screen.processed_messages]
        self.assertIn("Already queued", contents)
        self.assertTrue(any(original["content"] in text for text in contents))
        screen.save_current_draft()
        pending = dm.get_pending(screen.map_screen.nation_data, "P", "B")
        self.assertEqual(pending["action"], dm.FORWARD_ACTION)
        self.assertEqual(pending["forwarded_message"], original)
        self.assertEqual(screen.map_screen.nation_data["P"]["draft_lists"]["B"], ["Already queued"])

    def test_tactical_mode_blocks_writes_and_keeps_treaty_view_available(self):
        screen = self.make_screen(tactical=True)
        screen.map_screen.nation_data["P"]["pending_ratification"] = {"signatory": "A"}
        screen.select_recipient("A")
        buttons = {element.text: element for element in screen.elements}
        for label in ("Queue", "Trade", "Ratify Treaty", "Refuse & Leave Faction"):
            self.assertTrue(buttons[label].disabled)
        self.assertFalse(buttons["View Treaty"].disabled)
        screen.compose_text = "Do not queue"
        with mock.patch("screens.game.messages.player_diplomacy_actions.handle_ratify_treaty") as answer:
            screen.answer_ratification(True)
            answer.assert_not_called()
        screen.send_message()
        self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "A"), {})

    def test_unavailable_offer_controls_cannot_answer_or_open_a_deal(self):
        screen = self.make_screen()
        for selected in (None, "A"):
            with self.subTest(selected=selected):
                if selected:
                    screen.select_recipient(selected)
                buttons = {element.text: element for element in screen.elements}
                with mock.patch.object(screen, "accept_proposal") as accept, \
                        mock.patch.object(screen, "reject_proposal") as decline, \
                        mock.patch.object(screen, "view_trade_deal") as view:
                    for label in ("Accept", "Decline", "View Offer"):
                        button = buttons[label]
                        self.assertTrue(button.disabled)
                        button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=button.rect.center))
                        button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=button.rect.center))
                    accept.assert_not_called()
                    decline.assert_not_called()
                    view.assert_not_called()

    def test_offer_controls_keep_undo_and_terms_available_after_either_reply(self):
        screen = self.make_screen()
        screen.map_screen.refresh_diplomacy_maps = mock.Mock()
        screen.select_recipient("A")
        dm.set_pending(screen.map_screen.nation_data, "A", "P", "TRADE", turns=1)
        for verdict in (dm.RESPONSE_ACCEPT, dm.RESPONSE_REJECT):
            with self.subTest(verdict=verdict):
                screen.refresh_ui()
                buttons = {element.text: element for element in screen.elements}
                buttons["Accept Trade" if verdict == dm.RESPONSE_ACCEPT else "Decline Trade"].callback()
                self.assertEqual(dm.get_response_status(screen.map_screen.nation_data, "P", "A"), (verdict, "TRADE"))
                buttons = {element.text: element for element in screen.elements}
                undo = buttons["Undo Accept" if verdict == dm.RESPONSE_ACCEPT else "Undo Decline"]
                opposite = buttons["Decline Trade" if verdict == dm.RESPONSE_ACCEPT else "Accept Trade"]
                self.assertFalse(undo.disabled)
                self.assertTrue(opposite.disabled)
                self.assertFalse(buttons["View Trade Deal"].disabled)
                with mock.patch("screens.game.messages.open_view_trade_deal_menu") as view:
                    buttons["View Trade Deal"].callback()
                    view.assert_called_once_with(screen.map_screen, "A")
                undo.callback()
                self.assertEqual(dm.get_response_status(screen.map_screen.nation_data, "P", "A"), ("", ""))
        dm.clear_pending(screen.map_screen.nation_data, "A", "P")
        screen.refresh_ui()
        buttons = {element.text: element for element in screen.elements}
        for label in ("Accept", "Decline", "View Offer"):
            self.assertTrue(buttons[label].disabled)

    def test_ratification_keeps_terms_and_the_matching_undo_after_either_verdict(self):
        from map_logic.diplomacy import ratification

        screen = self.make_screen()
        screen.select_recipient("A")
        for verdict in (ratification.RATIFY, ratification.REFUSE):
            with self.subTest(verdict=verdict):
                request = {"signatory": "A", "verdict": verdict}
                screen.map_screen.nation_data["P"]["pending_ratification"] = request
                screen.refresh_ui()
                buttons = {element.text: element for element in screen.elements}
                undo_label = "Ratified (undo)" if verdict == ratification.RATIFY else "Refused (undo)"
                opposite_label = "Refuse & Leave Faction" if verdict == ratification.RATIFY else "Ratify Treaty"
                self.assertFalse(buttons[undo_label].disabled)
                self.assertTrue(buttons[opposite_label].disabled)
                self.assertFalse(buttons["View Treaty"].disabled)
                with mock.patch.object(screen, "view_peace_treaty") as view:
                    buttons["View Treaty"].callback()
                    view.assert_called_once_with("A")
                buttons[undo_label].callback()
                self.assertNotIn("verdict", request)
                buttons = {element.text: element for element in screen.elements}
                self.assertFalse(buttons["Ratify Treaty"].disabled)
                self.assertFalse(buttons["Refuse & Leave Faction"].disabled)

    def test_forward_after_a_previous_turn_is_visible_and_cancelable_without_losing_the_reply(self):
        import copy

        screen = self.make_screen()
        previous = copy.deepcopy(dm.set_pending(screen.map_screen.nation_data, "P", "B", "MSG:Already sent", turns=1))
        screen.select_recipient("A")
        source = screen.map_screen.nation_data["P"]["inbox"][0]
        screen.queue_forward(source, "B")
        screen.select_recipient("B")
        screen.save_current_draft()
        self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "B")["request_id"], previous["request_id"])
        self.assertTrue(any(source["content"] in prepared["msg_data"]["content"] for prepared in screen.processed_messages))
        screen.draw(pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT)))
        rectangle, _index = next((rect, index) for rect, index in screen.draft_edit_rects
                                 if index == f"FORMAL_{dm.FORWARD_ACTION}")
        screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rectangle.center))
        self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "B"), previous)


class ConversationThemeTests(unittest.TestCase):
    make_screen = ConversationInteractionTests.make_screen

    def setUp(self):
        from data import queries

        self.settings = {"keybinds": {"BACK": "escape"}, "music_volume": 0.37,
                         "conversation_colors": {"A": [100, 110, 120]}}
        patcher = mock.patch.object(queries, "get_settings", return_value=self.settings)
        patcher.start()
        self.addCleanup(patcher.stop)
        writer = mock.patch.object(queries, "save_cached_json")
        self.settings_writer = writer.start()
        self.addCleanup(writer.stop)

    def open_picker(self, screen):
        with mock.patch("screens.game.messages.pickers.open_color_picker") as picker:
            next(button for button in screen.elements if button.text == "Theme").callback()
        return picker

    def test_theme_confirmation_changes_only_this_game_and_preserves_messages(self):
        screen = self.make_screen()
        other_game = self.make_screen()
        settings_before = copy.deepcopy(self.settings)
        screen.select_recipient("A")
        screen.compose_text = "Still typing"
        screen.drafts = ["Already queued"]
        state = copy.deepcopy(screen.map_screen.nation_data)
        picker = self.open_picker(screen)
        # A modal can finish after the underlying screen's selection changes.
        screen.selected_recipient = "B"
        picker.call_args.args[3]((12, 34, 56))
        self.assertEqual(screen.map_screen.conversation_colors, {"A": [12, 34, 56]})
        self.assertEqual(other_game.map_screen.conversation_colors, {})
        self.assertEqual(screen.map_screen.nation_data, state)
        self.assertEqual(screen.compose_text, "Still typing")
        self.assertEqual(screen.drafts, ["Already queued"])
        self.assertEqual(self.settings, settings_before)
        self.settings_writer.assert_not_called()

    def test_reset_removes_only_the_selected_override_in_the_save(self):
        from data import queries

        screen = self.make_screen()
        screen.select_recipient("A")
        self.open_picker(screen).call_args.args[3]((12, 34, 56))
        screen.select_recipient("B")
        self.open_picker(screen).call_args.args[3]((78, 90, 12))
        saved = json.loads(json.dumps(queries.build_save_dict(
            screen.map_screen, include_provinces=False, include_local_preferences=True)))
        self.assertEqual(saved["conversation_colors"], {"A": [12, 34, 56], "B": [78, 90, 12]})
        self.open_picker(screen).call_args.kwargs["on_reset"]()
        saved = queries.build_save_dict(screen.map_screen, include_provinces=False, include_local_preferences=True)
        self.assertEqual(saved["conversation_colors"], {"A": [12, 34, 56]})
        self.settings_writer.assert_not_called()

    def test_opening_another_game_in_the_same_screen_does_not_copy_colors(self):
        screen = self.make_screen()
        screen.select_recipient("A")
        self.open_picker(screen).call_args.args[3]((12, 34, 56))
        first_game = screen.map_screen
        second_game = self.make_screen().map_screen
        screen.start_messages(second_game)
        screen.select_recipient("A")
        self.assertEqual(second_game.conversation_colors, {})
        self.open_picker(screen).call_args.args[3]((78, 90, 12))
        self.assertEqual(first_game.conversation_colors, {"A": [12, 34, 56]})
        self.assertEqual(second_game.conversation_colors, {"A": [78, 90, 12]})

    def test_picker_opened_for_a_previous_game_cannot_color_the_new_game(self):
        screen = self.make_screen()
        screen.select_recipient("A")
        picker = self.open_picker(screen)
        first_game = screen.map_screen
        second_game = self.make_screen().map_screen
        screen.start_messages(second_game)
        picker.call_args.args[3]((12, 34, 56))
        self.assertEqual(first_game.conversation_colors, {"A": [12, 34, 56]})
        self.assertEqual(second_game.conversation_colors, {})

    def test_no_selection_cannot_open_picker_and_cancel_does_not_save(self):
        screen = self.make_screen()
        button = next(button for button in screen.elements if button.text == "Theme")
        self.assertTrue(button.disabled)
        self.open_picker(screen).assert_not_called()
        screen.select_recipient("A")
        self.open_picker(screen).assert_called_once()
        self.assertEqual(screen.map_screen.conversation_colors, {})
        self.settings_writer.assert_not_called()

    def test_local_theme_is_available_in_tactical_mode(self):
        screen = self.make_screen(tactical=True)
        screen.select_recipient("A")
        button = next(button for button in screen.elements if button.text == "Theme")
        self.assertFalse(button.disabled)
        self.open_picker(screen).call_args.args[3]((12, 34, 56))
        self.assertEqual(dm.get_pending(screen.map_screen.nation_data, "P", "A"), {})


if __name__ == "__main__":
    unittest.main()
