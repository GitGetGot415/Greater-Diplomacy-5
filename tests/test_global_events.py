"""The global event lists stay short.

The log feeds every LLM prompt. news_flash had no limit, so it grew by one
entry for every event of the game and was saved with every turn.
"""

import unittest

from map_logic.diplomacy import diplomacy_events


class GlobalEventLimitTests(unittest.TestCase):
    def events(self, nation_data):
        return nation_data["GLOBAL_EVENTS"]

    def test_both_lists_keep_only_the_newest_events(self):
        nation_data = {}
        total = diplomacy_events.GLOBAL_EVENT_LIMIT * 3
        for i in range(total):
            diplomacy_events.log_global_event(nation_data, f"event {i}")

        limit = diplomacy_events.GLOBAL_EVENT_LIMIT
        newest = [f"event {i}" for i in range(total - limit, total)]
        self.assertEqual(self.events(nation_data)["log"], list(reversed(newest)))
        self.assertEqual(self.events(nation_data)["news_flash"], newest)

    def test_an_older_long_list_is_trimmed_at_the_next_event(self):
        limit = diplomacy_events.GLOBAL_EVENT_LIMIT
        old = [f"old {i}" for i in range(limit * 2)]
        nation_data = {"GLOBAL_EVENTS": {"is_playable": False, "log": [],
                                         "news_flash": list(old)}}
        diplomacy_events.log_global_event(nation_data, "new")
        self.assertEqual(self.events(nation_data)["news_flash"],
                         old[-(limit - 1):] + ["new"])


if __name__ == "__main__":
    unittest.main()
