import data.constants as c

def get_pending_action(nation_data, player_name, target_name):
    pending = nation_data.get(player_name, {}).get("pending_diplomacy", {})
    info = pending.get(target_name)
    if isinstance(info, dict):
        return info.get("action")
    return info

def queue_text_message(nation_data, player_name, target_name, content):
    if player_name not in nation_data:
        return "Cannot send messages as this entity."
        
    p_data = nation_data[player_name]
    pending = p_data.setdefault("pending_diplomacy", {})
    draft_lists = p_data.setdefault("draft_lists", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    cur_list = draft_lists.setdefault(target_name, [])
    if content and content not in cur_list:
        cur_list.append(content)
        
    if current_action is not None and not current_action.startswith("MSG:"):
        return "Message draft saved alongside formal action."
        
    combined = "\n".join(cur_list) if cur_list else content
    pending[target_name] = {"action": f"MSG:{combined}", "turns": 0, "message": combined}
    return "Message draft saved. Will send at end of turn."

def cancel_text_message(nation_data, player_name, target_name):
    """Safely clears a drafted text message if it hasn't been sent yet."""
    if player_name not in nation_data:
        return "No drafted message to clear."
        
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    if current_action and current_action.startswith("MSG:"):
        info = pending.get(target_name, {})
        if isinstance(info, dict) and info.get("turns", 0) > 0:
            return "Cannot undo! Message is already in transit."
            
        del pending[target_name]
        return "Draft cleared."
    return "No drafted message to clear."

def send_message(map_screen, sender, receiver, content, msg_type="TEXT"):
    nation_data = map_screen.nation_data
    date_str = map_screen.time_manager.get_date_string()
    
    # 1. Deliver the message to the receiver
    receiver_data = nation_data.get(receiver)
    if receiver_data:
        if "inbox" not in receiver_data:
            receiver_data["inbox"] = []
        
        receiver_data["inbox"].insert(0, {
            "sender": sender, "content": content, "type": msg_type, 
            "read": False, "spectator_read": False, "date": date_str
        })

    # 2. Save a "Sent" copy to the sender's inbox
    sender_data = nation_data.get(sender)
    if sender_data:
        if "inbox" not in sender_data:
            sender_data["inbox"] = []
            
        sender_data["inbox"].insert(0, {
            "sender": f"To: {receiver}", "content": content, "type": msg_type, 
            "read": True, "spectator_read": True, "date": date_str
        })