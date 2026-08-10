"""Provider dispatch and in-flight-request abort state for the LLM AI.

FORCE_SKIP, CURRENT_TURN_ID, and ACTIVE_OLLAMA_CONNECTIONS stay in this module
rather than moving out with the rest: callers reach in and rebind them
directly (`ai_handler.FORCE_SKIP = True`, `ai_handler.CURRENT_TURN_ID += 1`),
which only ever rebinds the name in *this* module's namespace -- splitting
them into a separate module and re-exporting the name here would leave two
copies that drift the moment either side is written to.

The read-only settings getters (map_logic/ai/ai_settings.py) and the
proposal/message/proactive-text evaluation functions (ai_evaluation.py) don't
have that problem -- callers only ever call them, never rebind them -- so they
moved out and are re-exported below for every existing
`ai_handler.get_ai_mode()` / `ai_handler.evaluate_diplomatic_proposal(...)`
call site.
"""
import json
import urllib.parse
import http.client
import socket
from data.platform import IS_WEB

if not IS_WEB:
    # Networked LLM AI opponents are desktop-only (see Phase 4 of the web-export
    # plan): raw sockets/requests/google-genai have no browser-safe path, and
    # pulling them in on web would otherwise cascade into live, fragile
    # PyPI installs of requests' whole dependency tree at every fresh page load.
    import requests
else:
    requests = None
import data.constants as c
from map_logic.ai.ai_settings import (
    get_gemini_api_key,
    get_chatgpt_api_key,
    get_claude_api_key,
    get_ai_mode,
    get_ai_immersion_level,
    get_gemini_model,
    get_chatgpt_model,
    get_claude_model,
    get_ollama_model,
    get_ollama_url,
)

# --- NEW GLOBAL ABORT FLAG ---
FORCE_SKIP = False
CURRENT_TURN_ID = 0
ACTIVE_OLLAMA_CONNECTIONS = []

def abort_ai_generation():
    """Forcefully kills local AI generation by dropping OS sockets and flushing VRAM."""
    # 1. Close all active HTTP TCP sockets to instantly snap threads out of blocking I/O
    for conn in list(ACTIVE_OLLAMA_CONNECTIONS):
        try:
            # --- THE TRUE OS-LEVEL SOCKET KILL ---
            # This forces the blocking recv() in the background threads to instantly throw an exception
            if getattr(conn, 'sock', None):
                conn.sock.shutdown(socket.SHUT_RDWR)
            conn.close()
        except Exception:
            pass
    ACTIVE_OLLAMA_CONNECTIONS.clear()

    # 2. Tell Ollama to abort and unload to free up the GPU immediately
    if get_ai_mode() == "OLLAMA":
        try:
            url = get_ollama_url().replace("/api/chat", "/api/generate")
            # A tiny 0.1s timeout so the Pygame UI doesn't hang if Ollama's HTTP queue is saturated
            requests.post(url, json={"model": get_ollama_model(), "prompt": "", "keep_alive": 0}, timeout=(0.1, 0.1))
        except:
            pass

def _aborted(turn_id=None):
    """True when an in-flight request should give up.

    Either the player pressed Force Skip, or the turn moved on while the
    request was out and its answer is no longer wanted. Nine call sites spelled
    this condition out; they must all agree, because a request that stops
    checking one half of it keeps writing into a turn that has already ended.
    """
    return FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID)


#: Providers with a hook reserved but no implementation yet.
STUBBED_PROVIDERS = {"CHATGPT": "ChatGPT", "CLAUDE": "Claude"}


def _run_provider(mode, system_prompt, user_prompt, turn_id, canned, accepted=None):
    """Sends one prompt to whichever provider is configured and shapes the answer.

    This ladder was written out twice, once for proposals and once for plain
    messages; the two differed only in the canned line used when a provider is
    stubbed or the request is abandoned, and in whether the answer carries a
    verdict.
    """
    from map_logic.ai.ai_evaluation import _reply

    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt, turn_id)
        if result:
            return _reply(result.get("message", "OLLAMA ERROR: Unknown Format"), result, accepted)
        return _reply("OLLAMA ERROR: No response", accepted=accepted)

    if mode in STUBBED_PROVIDERS:
        print(f"[LLM] Custom {STUBBED_PROVIDERS[mode]} hook to be placed here.")
        return _reply(canned, accepted=accepted)

    # Fallback to Gemini
    if not IS_WEB:
        from google import genai
        from google.genai import types
    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        if _aborted(turn_id):
            return _reply(canned, accepted=accepted)

        reply_json = json.loads(response.text)
        return _reply(reply_json.get("message", "JSON ERROR: Parsed fine but missing 'message' key."),
                      reply_json, accepted)
    except Exception as e:
        print(f"API Error: {e}")
        return _reply(f"API ERROR: {str(e)}", accepted=accepted)

def call_ollama(system_prompt, user_prompt, turn_id=None):
    """Helper to hit local Ollama instance with direct socket control for instant termination."""
    if _aborted(turn_id): return None

    url_str = get_ollama_url()
    parsed_url = urllib.parse.urlparse(url_str)

    model_name = get_ollama_model()

    # 1. Combine system and user prompts to prevent 400 errors on lightweight models
    # that lack a system prompt block in their instruction template (like many 0.5b models).
    combined_prompt = f"{system_prompt}\n\n{user_prompt}"

    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": combined_prompt}
        ],
        "stream": True # Stream token-by-token
    }

    # Conditionally apply strict JSON formatting if the model supports it natively
    if hasattr(c, 'OLLAMA_JSON_SUPPORTED_MODELS') and any(supported in model_name.lower() for supported in c.OLLAMA_JSON_SUPPORTED_MODELS):
        payload["format"] = "json"

    payload_bytes = json.dumps(payload).encode('utf-8')

    # Bypass requests and create a raw HTTP connection directly
    conn = None
    if parsed_url.scheme == "https":
        conn = http.client.HTTPSConnection(parsed_url.hostname, parsed_url.port or 443, timeout=300)
    else:
        conn = http.client.HTTPConnection(parsed_url.hostname, parsed_url.port or 80, timeout=300)

    ACTIVE_OLLAMA_CONNECTIONS.append(conn)

    try:
        headers = {"Content-Type": "application/json", "Connection": "close"}

        # This initiates the blocking request. If conn.sock.shutdown() is called from the UI thread,
        # the OS will instantly throw a ConnectionAbortedError here and wake up this thread.
        conn.request("POST", parsed_url.path, body=payload_bytes, headers=headers)
        response = conn.getresponse()

        if response.status >= 400:
            # 2. Extract and decode the actual error message from Ollama
            error_body = response.read().decode('utf-8')
            try:
                # Try to parse it cleanly if it's a JSON error response
                error_json = json.loads(error_body)
                err_msg = error_json.get("error", error_body)
            except:
                err_msg = error_body

            return {"message": f"OLLAMA HTTP ERROR {response.status}: {err_msg}"}

        full_text = ""
        # Iterate over the stream as it generates
        while True:
            if _aborted(turn_id):
                conn.close()
                return None

            line = response.readline()
            if not line:
                break

            line_str = line.decode('utf-8').strip()
            if line_str:
                chunk = json.loads(line_str)
                full_text += chunk.get("message", {}).get("content", "")

        # Parse the final reconstructed string
        try:
            return json.loads(full_text)
        except json.JSONDecodeError:
            return {"message": f"JSON ERROR: {full_text}"} # Fallback if it fails strict parsing

    except Exception as e:
        # If the connection was forcefully closed by the skip button, fail silently
        if _aborted(turn_id):
            return None
        print(f"Ollama Connection Error: {e}")
        return {"message": f"OLLAMA ERROR: {str(e)}"}
    finally:
        if conn in ACTIVE_OLLAMA_CONNECTIONS:
            ACTIVE_OLLAMA_CONNECTIONS.remove(conn)
        try:
            conn.close()
        except:
            pass


# Re-exported so `ai_handler.evaluate_diplomatic_proposal(...)` etc. keep
# working -- see this module's docstring for why these moved but FORCE_SKIP /
# CURRENT_TURN_ID / ACTIVE_OLLAMA_CONNECTIONS did not.
from map_logic.ai.ai_evaluation import (
    LITE_RESPONSE_KEYS,
    get_world_context,
    evaluate_diplomatic_proposal,
    process_custom_message,
    generate_proactive_text,
)
