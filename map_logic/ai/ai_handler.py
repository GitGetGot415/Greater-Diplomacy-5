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
import threading
import time
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
    get_deepseek_api_key,
    get_kimi_api_key,
    get_ai_mode,
    get_ai_immersion_level,
    get_gemini_model,
    get_chatgpt_model,
    get_claude_model,
    get_deepseek_model,
    get_kimi_model,
    get_ollama_model,
    get_ollama_url,
)

# --- NEW GLOBAL ABORT FLAG ---
FORCE_SKIP = False
CURRENT_TURN_ID = 0
ACTIVE_OLLAMA_CONNECTIONS = []

# A turn fans a whole batch of requests at one provider, and each one used to
# build its client and open its own TLS connection from scratch. Both are
# rebuilt only when the setting behind them changes, and both are shared across
# the batch's worker threads -- requests.Session and genai.Client are documented
# as thread-safe, and the lock only guards the swap, not the requests.
_CLIENT_LOCK = threading.Lock()
_SESSION = None
_GEMINI_CLIENT = {"key": None, "client": None}


def _session():
    """The shared requests.Session for Claude and the OpenAI-compatible providers.

    Connection reuse across a batch, which on a hosted provider is the single
    largest latency saving available -- a fresh TLS handshake per call was
    costing more than some of the completions.
    """
    global _SESSION
    if _SESSION is None:
        with _CLIENT_LOCK:
            if _SESSION is None:
                _SESSION = requests.Session()
    return _SESSION


def _gemini_client():
    """The shared genai client, rebuilt only when the API key changes."""
    from google import genai

    api_key = get_gemini_api_key()
    with _CLIENT_LOCK:
        if _GEMINI_CLIENT["client"] is None or _GEMINI_CLIENT["key"] != api_key:
            _GEMINI_CLIENT["client"] = genai.Client(api_key=api_key)
            _GEMINI_CLIENT["key"] = api_key
        return _GEMINI_CLIENT["client"]


def reset_clients():
    """Drops the cached client and session, so the next call picks up new settings.

    The Gemini client keys off the API key on its own; this is for the cases it
    can't see, like the settings screen swapping providers or clearing a key.
    """
    global _SESSION
    with _CLIENT_LOCK:
        if _SESSION is not None:
            try:
                _SESSION.close()
            except Exception:
                pass
        _SESSION = None
        _GEMINI_CLIENT["client"] = None
        _GEMINI_CLIENT["key"] = None

def abort_active_requests():
    """Drops the sockets of any request still out, leaving the model loaded.

    Cancelling a future does nothing to a worker already blocked reading a
    reply, and shutdown(wait=False) returns while it carries on: a batch that
    gave up on its deadline used to leave its last request streaming into the
    *next* phase's budget, which cost 17 to 19 seconds of every phase after the
    first and threw the answer away when it arrived.

    Deliberately without the unload below. The one thing that makes a local
    model affordable here is that it keeps the world context it has already
    read (see ai_prompts.build_world_context), and flushing VRAM to save a few
    seconds would make every following call pay to read it again.
    """
    # --- THE TRUE OS-LEVEL SOCKET KILL ---
    # This forces the blocking recv() in the background threads to instantly throw an exception
    for conn in list(ACTIVE_OLLAMA_CONNECTIONS):
        try:
            if getattr(conn, 'sock', None):
                conn.sock.shutdown(socket.SHUT_RDWR)
            conn.close()
        except Exception:
            pass
    ACTIVE_OLLAMA_CONNECTIONS.clear()


def abort_ai_generation():
    """Forcefully kills local AI generation by dropping OS sockets and flushing VRAM."""
    # 1. Close all active HTTP TCP sockets to instantly snap threads out of blocking I/O
    abort_active_requests()

    # 2. Tell Ollama to abort and unload to free up the GPU immediately
    if get_ai_mode() == "OLLAMA":
        try:
            url = get_ollama_url().replace("/api/chat", "/api/generate")
            # A tiny 0.1s timeout so the Pygame UI doesn't hang if Ollama's HTTP queue is saturated
            requests.post(url, json={"model": get_ollama_model(), "prompt": "", "keep_alive": 0}, timeout=(0.1, 0.1))
        except:
            pass

def _provider_error(message):
    """A provider failure, flagged so callers can tell it from a real answer.

    The text still reaches the player on a proposal -- a bad API key showing up
    in the reply is how you find out it is bad -- but a proactive one-liner has
    no verdict riding on it, so generate_proactive_text drops these and uses its
    fallback line rather than sending "API ERROR: ..." as a diplomatic cable.
    """
    return {"message": message, "error": True}


def _aborted(turn_id=None):
    """True when an in-flight request should give up.

    Either the player pressed Force Skip, or the turn moved on while the
    request was out and its answer is no longer wanted. Nine call sites spelled
    this condition out; they must all agree, because a request that stops
    checking one half of it keeps writing into a turn that has already ended.
    """
    return FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID)


#: ChatGPT, DeepSeek, and Kimi (Moonshot) all speak the same OpenAI-style chat
#: completions REST API, so one caller and this lookup of
#: (endpoint, api key getter, model getter) covers all three instead of writing
#: the request/response handling out three times.
OPENAI_COMPATIBLE_PROVIDERS = {
    "CHATGPT": (lambda: c.CHATGPT_API_URL, get_chatgpt_api_key, get_chatgpt_model),
    "DEEPSEEK": (lambda: c.DEEPSEEK_API_URL, get_deepseek_api_key, get_deepseek_model),
    "KIMI": (lambda: c.KIMI_API_URL, get_kimi_api_key, get_kimi_model),
}


def call_openai_compatible(url, api_key, model, system_prompt, user_prompt, turn_id=None):
    """Hits an OpenAI-style /chat/completions endpoint (DeepSeek, Moonshot/Kimi)."""
    if _aborted(turn_id):
        return None

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    try:
        response = _session().post(url, json=payload, headers=headers, timeout=120)
        if _aborted(turn_id):
            return None

        if response.status_code >= 400:
            return _provider_error(f"HTTP ERROR {response.status_code}: {response.text}")

        content = response.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"message": content}
    except Exception as e:
        if _aborted(turn_id):
            return None
        return _provider_error(f"API ERROR: {str(e)}")


def call_claude(api_key, model, system_prompt, user_prompt, turn_id=None):
    """Hits Anthropic's Messages API, which uses its own auth headers and
    request/response shape rather than the OpenAI-style ones above."""
    if _aborted(turn_id):
        return None

    payload = {
        "model": model,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": c.CLAUDE_API_VERSION,
    }

    try:
        response = _session().post(c.CLAUDE_API_URL, json=payload, headers=headers, timeout=120)
        if _aborted(turn_id):
            return None

        if response.status_code >= 400:
            return _provider_error(f"HTTP ERROR {response.status_code}: {response.text}")

        content = response.json()["content"][0]["text"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"message": content}
    except Exception as e:
        if _aborted(turn_id):
            return None
        return _provider_error(f"API ERROR: {str(e)}")


def call_gemini(system_prompt, user_prompt, turn_id=None):
    """Hits Gemini, shaped like the other three callers above.

    Was inline in the dispatch ladder and duplicated a second time in
    ai_evaluation.generate_proactive_text, which is how the two copies came to
    build a client each and disagree about what a malformed reply means.
    """
    if _aborted(turn_id):
        return None

    from google.genai import types

    try:
        response = _gemini_client().models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        if _aborted(turn_id):
            return None

        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            # The other three providers hand back unparseable output as the
            # message rather than throwing it away; this one used to let the
            # decode error fall into the handler below and report itself as an
            # API failure, which it isn't.
            return {"message": response.text}
    except Exception as e:
        if _aborted(turn_id):
            return None
        print(f"API Error: {e}")
        return _provider_error(f"API ERROR: {str(e)}")


#: What one request has been costing lately, in seconds. Zero until one has
#: been made and timed.
#:
#: Measured rather than assumed because it is not knowable from anywhere else:
#: it depends on the machine, the model, the size of the world being described
#: and whether the model is loaded at all -- on one local llama3 it ranges from
#: 5 seconds warm to 18 cold. A turn needs the number to decide whether a
#: phase's share of the budget can cover the work it is about to start, rather
#: than spending the share finding out it could not.
_CALL_SECONDS = [0.0]

#: How much of the new measurement each request contributes. Low enough that a
#: single cold start does not convince the game every call now costs 18s.
_CALL_SECONDS_WEIGHT = 0.4


def typical_call_seconds():
    """A smoothed estimate of one request's wall clock. 0 means nothing yet."""
    return _CALL_SECONDS[0]


def _time_call(seconds):
    previous = _CALL_SECONDS[0]
    _CALL_SECONDS[0] = (seconds if not previous else
                        previous + (seconds - previous) * _CALL_SECONDS_WEIGHT)


def _call_provider(mode, system_prompt, user_prompt, turn_id):
    """One request to whichever provider is configured.

    Returns the parsed reply dict, or None when the request was abandoned --
    Force Skip, or the turn moving on while it was out. Gemini is the
    else-branch, so an unrecognised mode still answers.
    """
    started = time.monotonic()
    try:
        return _dispatch(mode, system_prompt, user_prompt, turn_id)
    finally:
        _time_call(time.monotonic() - started)


def _dispatch(mode, system_prompt, user_prompt, turn_id):
    if mode == "OLLAMA":
        return call_ollama(system_prompt, user_prompt, turn_id)

    if mode in OPENAI_COMPATIBLE_PROVIDERS:
        get_url, get_key, get_model = OPENAI_COMPATIBLE_PROVIDERS[mode]
        return call_openai_compatible(get_url(), get_key(), get_model(),
                                      system_prompt, user_prompt, turn_id)

    if mode == "CLAUDE":
        return call_claude(get_claude_api_key(), get_claude_model(),
                           system_prompt, user_prompt, turn_id)

    return call_gemini(system_prompt, user_prompt, turn_id)


def _run_provider(mode, system_prompt, user_prompt, turn_id, canned, accepted=None, raw=False):
    """Sends one prompt to the configured provider and shapes the answer.

    raw=True hands back the parsed provider dict (or None) instead of a reply,
    for callers that want a bare string rather than a verdict-carrying answer.

    A None result means the request was abandoned, so every provider now falls
    back to the canned line. The Ollama branch used to put its own
    "OLLAMA ERROR: No response" in front of the player instead, which meant
    pressing Force Skip produced an error message dressed as a diplomatic cable.
    """
    from map_logic.ai.ai_evaluation import _reply

    result = _call_provider(mode, system_prompt, user_prompt, turn_id)
    if raw:
        return result
    if result is None:
        return _reply(canned, accepted=accepted)
    return _reply(result.get("message", f"{mode} ERROR: reply had no 'message' field"),
                  result, accepted, llm=bool(result.get("message")))

def call_ollama(system_prompt, user_prompt, turn_id=None):
    """Helper to hit local Ollama instance with direct socket control for instant termination."""
    if _aborted(turn_id): return None

    url_str = get_ollama_url()
    parsed_url = urllib.parse.urlparse(url_str)

    model_name = get_ollama_model()

    # 1. Combine system and user prompts to prevent 400 errors on lightweight models
    # that lack a system prompt block in their instruction template (like many 0.5b models).
    #
    # The world goes first and the instructions last, which is the whole reason
    # a turn is affordable here. Every caller in the game builds its user half
    # as "<the world> <this nation's situation> <the task>", and the world is
    # around ninety percent of it and identical for every request in a turn --
    # but the system half differs by phase, so putting it in front made a
    # summit prompt, a director prompt and a proposal reply share their first
    # eight characters. Measured on the 1941 map: 0% shared across phases
    # against 84% this way round, and a local model re-reads from the first
    # token that differs -- nine seconds of every phase's budget, spent
    # re-reading a world that had not changed since the phase before.
    #
    # Ollama is the only provider that concatenates the two halves; the rest
    # have a system field of their own and are unaffected.
    combined_prompt = f"{user_prompt}\n\n{system_prompt}"

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
