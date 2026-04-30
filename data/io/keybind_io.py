import json
import os
import pygame
import data.constants as c

CONFIG_PATH = c.SETTINGS_CONFIG_PATH

def save_settings(keybind_dict, volume, num_players=1, ai_mode="GEMINI", gemini_api_key="", chatgpt_api_key="", claude_api_key="", ai_immersion_level="FULL", ollama_model="llama3"):
    """Converts key codes to strings and saves along with volume/players/AI/API/Ollama to JSON."""
    readable_binds = {}
    for action, key_code in keybind_dict.items():
        readable_binds[action] = pygame.key.name(key_code)
    
    data_to_save = {
        "keybinds": readable_binds,
        "volume": volume,
        "num_players": num_players,
        "ai_mode": ai_mode,
        "gemini_api_key": gemini_api_key,
        "chatgpt_api_key": chatgpt_api_key,
        "claude_api_key": claude_api_key,
        "ai_immersion_level": ai_immersion_level,
        "ollama_model": ollama_model
    }
    
    with open(CONFIG_PATH, "w") as f:
        json.dump(data_to_save, f, indent=4)

def load_settings(default_binds, default_volume=0.5):
    """Loads keybinds, volume, AI mode, API key, immersion level, and Ollama model from JSON."""
    if not os.path.exists(CONFIG_PATH):
        return default_binds, default_volume, 1, c.DEFAULT_AI_MODE, "", "", "", "FULL", "llama3"
    
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
        saved_ai_mode = saved_data.get("ai_mode", c.DEFAULT_AI_MODE) if isinstance(saved_data, dict) else c.DEFAULT_AI_MODE
        # Fallback to old "api_key" if "gemini_api_key" doesn't exist
        saved_gemini_api_key = saved_data.get("gemini_api_key", saved_data.get("api_key", "")) if isinstance(saved_data, dict) else ""
        saved_chatgpt_api_key = saved_data.get("chatgpt_api_key", "") if isinstance(saved_data, dict) else ""
        saved_claude_api_key = saved_data.get("claude_api_key", "") if isinstance(saved_data, dict) else ""
        saved_ai_immersion = saved_data.get("ai_immersion_level", "FULL") if isinstance(saved_data, dict) else "FULL"
        saved_ollama_model = saved_data.get("ollama_model", "llama3") if isinstance(saved_data, dict) else "llama3"
                
        return loaded_binds, saved_vol, saved_num_players, saved_ai_mode, saved_gemini_api_key, saved_chatgpt_api_key, saved_claude_api_key, saved_ai_immersion, saved_ollama_model
    except Exception as e:
        print(f"Error loading settings: {e}")
        return default_binds, default_volume, 1, "GEMINI", "", "", "", "FULL", "llama3"