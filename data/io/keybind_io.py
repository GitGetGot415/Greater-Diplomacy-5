import json
import os
import pygame

CONFIG_PATH = "data/json/settings_config.json"

def save_settings(keybind_dict, volume, num_players=1):
    """Converts key codes to strings and saves along with volume/players to JSON."""
    readable_binds = {}
    for action, key_code in keybind_dict.items():
        readable_binds[action] = pygame.key.name(key_code)
    
    data_to_save = {
        "keybinds": readable_binds,
        "volume": volume,
        "num_players": num_players # NEW
    }
    
    with open(CONFIG_PATH, "w") as f:
        json.dump(data_to_save, f, indent=4)

def load_settings(default_binds, default_volume=0.5):
    """Loads keybinds and volume from JSON."""
    if not os.path.exists(CONFIG_PATH):
        return default_binds, default_volume
    
    try:
        with open(CONFIG_PATH, "r") as f:
            saved_data = json.load(f)
        
        # Backwards compatibility if old save file only has keybinds directly
        if "keybinds" not in saved_data:
            saved_binds = saved_data
            saved_vol = default_volume
        else:
            saved_binds = saved_data.get("keybinds", {})
            saved_vol = saved_data.get("volume", default_volume)
        
        # Convert strings back to pygame codes
        loaded_binds = {}
        for action, key_name in saved_binds.items():
            loaded_binds[action] = pygame.key.key_code(key_name)
        
        # Ensure any missing actions from the file use defaults
        for action, code in default_binds.items():
            if action not in loaded_binds:
                loaded_binds[action] = code
                
        # NEW: Safely get num_players (default to 1 if it's an old save)
        saved_num_players = saved_data.get("num_players", 1) if isinstance(saved_data, dict) else 1
                
        return loaded_binds, saved_vol, saved_num_players
    except Exception as e:
        print(f"Error loading settings: {e}")
        return default_binds, default_volume, 1