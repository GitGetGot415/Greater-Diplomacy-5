"""Check request references, compatibility, and independent diplomacy channels."""

import copy
import json
import random
import unittest

from data import migrations
from data.state_access import BackendState
from data.multiplayer.realtime.session import MapRealtimeDriver, RealtimeError
from map_logic.diplomacy import diplomacy_lifecycle as lifecycle, diplomacy_messages as messages
from map_logic.diplomacy.diplomacy_processor import _process_queued_responses


class DiplomacyLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.nations = {"A": {}, "B": {}}

    def test_request_replacement_invalidates_earlier_responses_without_using_gameplay_randomness(self):
        before = random.getstate()
        first = messages.set_pending(self.nations, "A", "B", "TRADE")
        response = messages.set_response(self.nations, "B", "A", "ACCEPT", "TRADE")
        messages.clear_pending(self.nations, "A", "B")
        second = messages.set_pending(self.nations, "A", "B", "TRADE")
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertFalse(lifecycle.response_matches_request(response, second))
        self.assertEqual(random.getstate(), before)
        context = BackendState()
        context.world.nation_data.update(self.nations)
        _process_queued_responses(context)
        self.assertEqual(messages.get_response(self.nations, "B", "A"), {})
        self.assertIs(messages.get_pending(self.nations, "A", "B"), second)

    def test_outgoing_requests_and_incoming_responses_remain_independent(self):
        ours = messages.set_pending(self.nations, "A", "B", "TRADE")
        theirs = messages.set_pending(self.nations, "B", "A", "CEASEFIRE")
        response = messages.set_response(self.nations, "A", "B", "REJECT", "CEASEFIRE")
        self.assertEqual(response["request_id"], theirs["request_id"])
        messages.clear_response(self.nations, "A", "B")
        self.assertIs(messages.get_pending(self.nations, "A", "B"), ours)

    def test_schedule_and_response_paths_keep_existing_timing_fields(self):
        request = messages.set_pending(self.nations, "A", "B", "TRADE", timer=2)
        self.assertEqual(lifecycle.request_state(request), lifecycle.RequestState.SCHEDULED)
        self.assertFalse(lifecycle.tick_schedule(request))
        self.assertTrue(lifecycle.tick_schedule(request))
        self.assertEqual(lifecycle.advance_request(request), lifecycle.RequestState.AWAITING_REPLY)
        response = messages.set_response(self.nations, "B", "A", "ACCEPT", "TRADE")
        self.assertNotIn("turns", response)
        self.assertEqual(lifecycle.advance_request(request), lifecycle.RequestState.EXPIRED)

    def test_legacy_identities_are_reproducible_idempotent_and_survive_save_json(self):
        original = {"A": {"pending_diplomacy": {"B": {"action": "TRADE", "turns": 1,
                                                       "escrow": {"materials": 4}, "future": 7}}},
                    "B": {"diplo_responses": {"A": {"action": "TRADE", "verdict": "ACCEPT"}}}}
        first, second = copy.deepcopy(original), copy.deepcopy(original)
        lifecycle.normalize_diplomatic_records(first)
        lifecycle.normalize_diplomatic_records(second)
        self.assertEqual(first, second)
        saved = json.loads(json.dumps(first))
        lifecycle.normalize_diplomatic_records(saved)
        self.assertEqual(saved, first)
        self.assertEqual(saved["A"]["pending_diplomacy"]["B"]["future"], 7)
        self.assertEqual(saved["B"]["diplo_responses"]["A"]["request_id"],
                         saved["A"]["pending_diplomacy"]["B"]["request_id"])

    def test_server_rejects_stale_or_forged_response_references_without_mutation(self):
        context = BackendState()
        context.world.nation_data.update(self.nations)
        request = messages.set_pending(self.nations, "A", "B", "TRADE", turns=1)
        before = copy.deepcopy(context.world.nation_data)
        driver = MapRealtimeDriver(context)
        command = {"type": "country_diplomacy",
                   "responses": {"A": {"action": "TRADE", "verdict": "ACCEPT", "request_id": "wrong"}}}
        with self.assertRaises(RealtimeError):
            driver.validate_draft("B", [command])
        self.assertEqual(context.world.nation_data, before)
        command["responses"]["A"]["request_id"] = request["request_id"]
        validated = driver.validate_draft("B", [command])[0]
        self.assertEqual(validated["responses"]["A"]["request_id"], request["request_id"])

    def test_server_binds_an_older_response_without_a_reference(self):
        context = BackendState()
        context.world.nation_data.update(self.nations)
        request = messages.set_pending(self.nations, "A", "B", "TRADE", turns=1)
        driver = MapRealtimeDriver(context)
        command = {"type": "country_diplomacy", "responses": {
            "A": {"action": "TRADE", "verdict": "ACCEPT"}}}
        validated = driver.validate_draft("B", [command])[0]
        self.assertEqual(validated["responses"]["A"]["request_id"], request["request_id"])
        self.assertNotIn("request_id", command["responses"]["A"])

    def test_ratification_references_reject_an_answer_to_a_previous_round(self):
        self.nations["B"]["pending_ratification"] = {"treaty_id": "current"}
        with self.assertRaises(ValueError):
            lifecycle.answer_ratification(self.nations, "B", "RATIFY", treaty_id="old")
        self.assertNotIn("verdict", self.nations["B"]["pending_ratification"])
        lifecycle.answer_ratification(self.nations, "B", "RATIFY", treaty_id="current")
        self.assertEqual(self.nations["B"]["pending_ratification"]["verdict"], "RATIFY")
