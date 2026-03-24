import json
import os
import pygame

CONFIG_PATH = "map_functions/data/settings_config.json"

def save_keybinds(keybind_dict):
    """Converts key codes to strings and saves to JSON."""
    readable_binds = {}
    for action, key_code in keybind_dict.items():
        readable_binds[action] = pygame.key.name(key_code)
    
    with open(CONFIG_PATH, "w") as f:
        json.dump(readable_binds, f, indent=4)

def load_keybinds(default_binds):
    """Loads keybinds from JSON and converts them back to Pygame key codes."""
    if not os.path.exists(CONFIG_PATH):
        return default_binds
    
    try:
        with open(CONFIG_PATH, "r") as f:
            saved_data = json.load(f)
        
        # Convert strings back to pygame codes
        loaded_binds = {}
        for action, key_name in saved_data.items():
            loaded_binds[action] = pygame.key.key_code(key_name)
        
        # Ensure any missing actions from the file use defaults
        for action, code in default_binds.items():
            if action not in loaded_binds:
                loaded_binds[action] = code
                
        return loaded_binds
    except Exception as e:
        print(f"Error loading keybinds: {e}")
        return default_binds