"""Read-only accessors for the live AI settings (provider, model, API keys).

Split out of map_logic/ai/ai_handler.py, which re-exports every name here so
existing `ai_handler.get_ai_mode()`-style call sites keep working -- see that
module's docstring for why the mutable abort/turn-id state stayed behind
there instead of moving here too.
"""
import data.constants as c
from data import queries


def _setting(key, default=""):
    """Reads one live setting. All the getters below share this body."""
    return queries.get_settings().get(key, default)


def get_gemini_api_key():
    """Helper to dynamically fetch the saved key from cache."""
    settings = queries.get_settings()
    return settings.get("gemini_api_key", settings.get("api_key", ""))

def get_chatgpt_api_key():
    return _setting("chatgpt_api_key")

def get_claude_api_key():
    return _setting("claude_api_key")

def get_deepseek_api_key():
    return _setting("deepseek_api_key")

def get_kimi_api_key():
    return _setting("kimi_api_key")

def get_ai_mode():
    """Reads the settings config to see which AI is active."""
    return _setting("ai_mode", c.DEFAULT_AI_MODE)

def get_ai_immersion_level():
    """Reads the settings config to see which immersion level is active."""
    return _setting("ai_immersion_level", "LITE")

# --- MODEL / URL GETTERS ---

def get_gemini_model():
    return _setting("gemini_model", c.DEFAULT_GEMINI_MODEL)

def get_chatgpt_model():
    return _setting("chatgpt_model", c.DEFAULT_CHATGPT_MODEL)

def get_claude_model():
    return _setting("claude_model", c.DEFAULT_CLAUDE_MODEL)

def get_deepseek_model():
    return _setting("deepseek_model", c.DEFAULT_DEEPSEEK_MODEL)

def get_kimi_model():
    return _setting("kimi_model", c.DEFAULT_KIMI_MODEL)

def get_ollama_model():
    """Reads the settings config to see which Ollama model is requested."""
    return _setting("ollama_model", c.DEFAULT_OLLAMA_MODEL)

def get_ollama_url():
    """Reads the URL from the settings. Defaults to localhost if empty."""
    url = _setting("ollama_api_key").strip()
    return url if url else "http://localhost:11434/api/chat"
