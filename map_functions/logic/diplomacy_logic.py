import random

def toggle_diplomacy_action(nation_data, player_name, target_name, action_type):
    pending = nation_data[player_name].get("pending_diplomacy", {})
    
    # If the exact action is already pending, undo it
    if pending.get(target_name) == action_type:
        del pending[target_name]
        return f"Undo {action_type.replace('_', ' ').title()}"
    else:
        pending[target_name] = action_type
        return f"{action_type.replace('_', ' ').title()} requested..."

def process_diplomacy_turn(self):
    """Called during turn_processor.py to finalize declarations."""
    for country_name, data in self.nation_data.items():
        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []

        for target, action in pending.items():
            if action == "WAR_DECLARATION":
                finalize_war(self.nation_data, country_name, target)
                self.show_feedback(f"{country_name} is now at WAR with {target}!")
            
            elif action == "BREAK_ALLIANCE":
                finalize_neutral(self.nation_data, country_name, target)
                self.show_feedback(f"{country_name} broke the alliance with {target}!")

            elif action == "ALLIANCE_REQUEST":
                if random.random() > 0.5:
                    finalize_alliance(self.nation_data, country_name, target)
                    self.show_feedback(f"{target} accepted alliance with {country_name}!")
                else:
                    self.show_feedback(f"{target} declined alliance request.")
            
            elif action == "CEASEFIRE":
                if random.random() > 0.5:
                    finalize_neutral(self.nation_data, country_name, target)
                    self.show_feedback(f"{target} accepted ceasefire with {country_name}!")
                else:
                    self.show_feedback(f"{target} rejected ceasefire.")

            actions_to_clear.append(target)

        for t in actions_to_clear:
            if t in pending: del pending[t]

def finalize_war(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].append(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)

def finalize_alliance(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].append(other)
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)

def finalize_neutral(nation_data, a, b):
    """Resets both countries to neutral."""
    for country, other in [(a, b), (b, a)]:
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)