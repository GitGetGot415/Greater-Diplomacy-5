import os
import pygame
import data.constants as c
from data import queries

CONFIG_PATH = c.SETTINGS_CONFIG_PATH

def save_settings(keybind_dict, sfx_volume, music_volume, num_players=1, ai_mode="GEMINI", 
                  gemini_api_key="", chatgpt_api_key="", claude_api_key="", ollama_api_key="",
                  gemini_model="", chatgpt_model="", claude_model="", ollama_model="",
                  ai_immersion_level="FULL", music_pitch=0.5, sfx_pitch=0.5, target_fps=60):
    """Converts key codes to strings and saves all config data to JSON."""
    readable_binds = {}
    for action, key_code in keybind_dict.items():
        readable_binds[action] = pygame.key.name(key_code)
    
    data_to_save = {
        "keybinds": readable_binds,
        "music_volume": music_volume,
        "music_pitch": music_pitch,
        "sfx_volume": sfx_volume,
        "sfx_pitch": sfx_pitch,
        "num_players": num_players,
        "ai_mode": ai_mode,
        "gemini_api_key": gemini_api_key,
        "chatgpt_api_key": chatgpt_api_key,
        "claude_api_key": claude_api_key,
        "ollama_api_key": ollama_api_key,
        "gemini_model": gemini_model,
        "chatgpt_model": chatgpt_model,
        "claude_model": claude_model,
        "ollama_model": ollama_model,
        "ai_immersion_level": ai_immersion_level,
        "target_fps": target_fps
    }
    
    # --- OPTIMIZATION: Replaced manual json.dump and clear_json_caches() ---
    # This automatically writes to the disk AND keeps the memory updated seamlessly.
    queries.save_cached_json("settings", data_to_save)

def load_settings(default_binds, default_volume=0.5, default_music_volume=0.5):
    """Loads all settings variables, safely falling back to defaults if missing."""
    default_pitch = getattr(c, 'DEFAULT_AUDIO_PITCH', 0.5)
    
    # --- OPTIMIZATION: Pulled AI defaults from constants ---
    if not os.path.exists(CONFIG_PATH):
        return (default_binds, default_volume, default_music_volume, 1, c.DEFAULT_AI_MODE, 
                "", "", "", "", 
                getattr(c, 'DEFAULT_GEMINI_MODEL', "gemini-2.5-flash"), 
                getattr(c, 'DEFAULT_CHATGPT_MODEL', "gpt-4o-mini"), 
                getattr(c, 'DEFAULT_CLAUDE_MODEL', "claude-3-haiku-20240307"), 
                getattr(c, 'DEFAULT_OLLAMA_MODEL', "llama3"), 
                "FULL", default_pitch, default_pitch)
    
    try:
        # Utilize the caching manager
        saved_data = queries.get_settings()
        if not saved_data:
            import json
            with open(CONFIG_PATH, "r") as f:
                saved_data = json.load(f)
        
        # Backwards compatibility if old save file only has keybinds directly
        if "keybinds" not in saved_data:
            saved_binds = saved_data
            saved_vol = default_volume
            saved_music_vol = default_music_volume
        else:
            saved_binds = saved_data.get("keybinds", {})
            saved_vol = saved_data.get("sfx_volume", default_volume)
            saved_music_vol = saved_data.get("music_volume", default_music_volume)
        
        # Convert strings back to pygame codes
        loaded_binds = {}
        for action, key_name in saved_binds.items():
            loaded_binds[action] = pygame.key.key_code(key_name)
        
        # Ensure any missing actions from the file use defaults
        for action, code in default_binds.items():
            if action not in loaded_binds:
                loaded_binds[action] = code
                
        s = saved_data if isinstance(saved_data, dict) else {}
                
        return (
            loaded_binds, 
            saved_vol, 
            saved_music_vol, 
            s.get("num_players", 1), 
            s.get("ai_mode", c.DEFAULT_AI_MODE),
            s.get("gemini_api_key", s.get("api_key", "")),
            s.get("chatgpt_api_key", ""),
            s.get("claude_api_key", ""),
            s.get("ollama_api_key", ""),
            s.get("gemini_model", getattr(c, 'DEFAULT_GEMINI_MODEL', "gemini-2.5-flash")),
            s.get("chatgpt_model", getattr(c, 'DEFAULT_CHATGPT_MODEL', "gpt-4o-mini")),
            s.get("claude_model", getattr(c, 'DEFAULT_CLAUDE_MODEL', "claude-3-haiku-20240307")),
            s.get("ollama_model", getattr(c, 'DEFAULT_OLLAMA_MODEL', "llama3")),
            s.get("ai_immersion_level", "FULL"),
            s.get("music_pitch", s.get("music_speed", default_pitch)), 
            s.get("sfx_pitch", s.get("sfx_speed", default_pitch)),
            s.get("target_fps", getattr(c, 'TARGET_FPS', 60))
        )
    except Exception as e:
        print(f"Error loading settings: {e}")
        return (default_binds, default_volume, default_music_volume, 1, "GEMINI", 
                "", "", "", "", 
                getattr(c, 'DEFAULT_GEMINI_MODEL', "gemini-2.5-flash"), 
                getattr(c, 'DEFAULT_CHATGPT_MODEL', "gpt-4o-mini"), 
                getattr(c, 'DEFAULT_CLAUDE_MODEL', "claude-3-haiku-20240307"), 
                getattr(c, 'DEFAULT_OLLAMA_MODEL', "llama3"), 
                "FULL", default_pitch, default_pitch)