"""A pygame-free stand-in for the map screen, just big enough to run a turn of
diplomacy.

process_diplomacy_turn only reaches for a handful of attributes, so the whole
world can be a couple of provinces and a nation_data dict. force_skip_llm keeps
the AI's canned fallback answers in play instead of reaching for the network.
"""

import os
import sys

# Import the game package from the repo root regardless of where tests run from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


class StubTimeManager:
    def __init__(self):
        self.total_turns = 0

    def get_date_string(self):
        return f"Turn {self.total_turns}"


class StubMapScreen:
    """Minimal map_screen for the diplomacy engine."""

    def __init__(self, nations, human_players=("A",)):
        self.nation_data = {}
        self.map_data = {}
        self.id_to_province = {}
        self.time_manager = StubTimeManager()
        self.active_players = list(human_players)
        self.player_country = self.active_players[0] if self.active_players else ""
        self.tactical_mode = False

        # LLM plumbing -- skipped entirely, answers come from the fallback table
        self.force_skip_llm = True
        self.loading_status_text = ""
        self.responsive_tasks_total = 0
        self.responsive_tasks_completed = 0
        self.proactive_llm_tasks = []
        self.proactive_tasks_total = 0
        self.proactive_tasks_completed = 0
        # Set only while prepare_turn's AI passes run; the diplomacy engine
        # these tests drive never has one, and must not need one.
        self.ai_world = None

        self.feedback = []
        self.scenario_settings = {}
        self.script_variables = []

        for idx, name in enumerate(nations, start=1):
            self._add_nation(name, idx)

    def _add_nation(self, name, prov_id):
        self.nation_data[name] = {
            "name": name,
            "is_playable": True,
            "at_war_with": [],
            "allied_with": [],
            "pending_diplomacy": {},
            "diplo_responses": {},
            "draft_lists": {},
            "inbox": [],
            "claims": [],
            "puppets": [],
            "master": "",
            "puppet_type": "",
            "faction": "",
            "is_faction_leader": False,
            "military_access": [],
            "materials": 1000,
            "fuel": 1000,
        }
        # One province each, so get_living_nations sees everyone as alive
        prov = {"id": prov_id, "owner": name, "cores": [name], "neighbors": []}
        self.map_data[str(prov_id)] = prov
        self.id_to_province[prov_id] = prov

    def show_feedback(self, text):
        self.feedback.append(text)

    def refresh_diplomacy_maps(self):
        pass

    # --- helpers used by the tests -------------------------------------------------

    def run_turn(self):
        """Advances one diplomatic turn."""
        from map_logic.diplomacy import diplomacy_logic
        self.time_manager.total_turns += 1
        diplomacy_logic.process_diplomacy_turn(self)

    def thread(self, owner, other):
        """The conversation `owner` can see with `other`, oldest first.

        Returns (direction, content) pairs where direction is "in" or "out".
        """
        out = []
        for msg in reversed(self.nation_data[owner]["inbox"]):
            sender = msg.get("sender", "")
            if sender == other:
                out.append(("in", msg.get("content", "")))
            elif sender == f"To: {other}":
                out.append(("out", msg.get("content", "")))
        return out

    def inbound(self, owner, other):
        """Just the messages `owner` received from `other`."""
        return [content for direction, content in self.thread(owner, other) if direction == "in"]

    def pending(self, sender, target):
        from map_logic.diplomacy import diplomacy_messages
        return diplomacy_messages.get_pending(self.nation_data, sender, target)

    def pending_action(self, sender, target):
        return self.pending(sender, target).get("action", "")

    def set_war(self, a, b):
        self.nation_data[a]["at_war_with"].append(b)
        self.nation_data[b]["at_war_with"].append(a)

    def set_faction(self, faction_name, leader, *members):
        self.nation_data[leader]["faction"] = faction_name
        self.nation_data[leader]["is_faction_leader"] = True
        for m in members:
            self.nation_data[m]["faction"] = faction_name
            self.nation_data[m]["is_faction_leader"] = False

    def propose(self, sender, target, action, message="", parameters=None):
        """Queues an outgoing proposal exactly as the player's buttons would."""
        from map_logic.diplomacy import diplomacy_logic
        return diplomacy_logic.toggle_diplomacy_action(
            self.nation_data, sender, target, action, message, parameters=parameters)

    def answer(self, responder, sender, verdict, action, message=""):
        """Queues an answer to an incoming proposal."""
        from map_logic.diplomacy import diplomacy_logic
        return diplomacy_logic.toggle_diplomatic_response(
            self.nation_data, responder, sender, verdict, action, message)
