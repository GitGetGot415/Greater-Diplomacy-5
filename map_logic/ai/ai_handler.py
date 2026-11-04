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
import weakref
from data.platform import IS_WEB

if not IS_WEB:
    # Networked LLM AI opponents are desktop-only (see Phase 4 of the web-export
    # plan): raw sockets/requests/google-genai have no browser-safe path, and
    # pulling them in on web would otherwise cascade into live, fragile
    # PyPI installs of requests' whole dependency tree at every fresh page load.
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
else:
    requests = None
import data.constants as c
from map_logic.ai.ai_settings import (
    get_gemini_api_key,
    get_chatgpt_api_key,
    get_claude_api_key,
    get_deepseek_api_key,
    get_kimi_api_key,
    get_openrouter_api_key,
    get_ai_mode,
    get_ai_immersion_level,
    get_gemini_model,
    get_chatgpt_model,
    get_claude_model,
    get_deepseek_model,
    get_kimi_model,
    get_openrouter_model,
    get_ollama_model,
    get_ollama_url,
)

from data.migrations import normalize_ai_mode
from map_logic.ai import ai_prompts
# Re-exported so `ai_handler.evaluate_diplomatic_proposal(...)` etc. keep
# working -- see this module's docstring for why these moved but FORCE_SKIP /
# CURRENT_TURN_ID / ACTIVE_OLLAMA_CONNECTIONS did not.
from map_logic.ai.ai_evaluation import (
    _reply,
    LITE_RESPONSE_KEYS,
    get_world_context,
    evaluate_diplomatic_proposal,
    process_custom_message,
    generate_proactive_text,
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

#: Every connection the shared Session has opened. urllib3 owns them and keeps
#: idle ones for reuse, so this set only refers to them (weakly) to let
#: abort_active_requests close a request that is still waiting for its reply.
_HOSTED_CONNECTIONS = weakref.WeakSet()
_HOSTED_LOCK = threading.Lock()

#: How many times abort_active_requests has run. A request that was in flight
#: when this changed was cut short, so _call_provider does not time it.
_ABORT_COUNT = [0]


def _track_connection(conn):
    with _HOSTED_LOCK:
        _HOSTED_CONNECTIONS.add(conn)


if not IS_WEB:
    # requests gives no access to the socket of a request in progress, which is
    # the only thing that stops a blocked read. These subclasses record each
    # connection when it opens. Requests sent through a proxy use another pool
    # and are not recorded; they run to the end, as all hosted requests did
    # before.
    class _TrackedHTTPConnection(HTTPConnection):
        def connect(self):
            super().connect()
            _track_connection(self)

    class _TrackedHTTPSConnection(HTTPSConnection):
        def connect(self):
            super().connect()
            _track_connection(self)

    class _TrackedHTTPConnectionPool(HTTPConnectionPool):
        ConnectionCls = _TrackedHTTPConnection

    class _TrackedHTTPSConnectionPool(HTTPSConnectionPool):
        ConnectionCls = _TrackedHTTPSConnection

    class _TrackedAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {
                "http": _TrackedHTTPConnectionPool,
                "https": _TrackedHTTPSConnectionPool,
            }


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
                session = requests.Session()
                adapter = _TrackedAdapter()
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                _SESSION = session
    return _SESSION


def _gemini_client():
    """The shared genai client, rebuilt only when the API key changes."""
    # Load the optional Gemini SDK only when this provider is used.
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

    Hosted providers are closed too: an abandoned request to one used to run
    for up to two minutes, and was billed, after its answer had been discarded.
    That also closes their idle connections, so the next request opens a new one.
    Gemini goes through its own SDK and cannot be stopped here.
    """
    _ABORT_COUNT[0] += 1
    with _HOSTED_LOCK:
        hosted = list(_HOSTED_CONNECTIONS)
        _HOSTED_CONNECTIONS.clear()

    # --- THE TRUE OS-LEVEL SOCKET KILL ---
    # This forces the blocking recv() in the background threads to instantly throw an exception
    for conn in list(ACTIVE_OLLAMA_CONNECTIONS) + hosted:
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
        # A tiny 0.1s timeout so the Pygame UI doesn't hang if Ollama's HTTP queue is saturated
        _unload_ollama_model(get_ollama_url(), get_ollama_model(), (0.1, 0.1))


#: (chat URL, model) for every Ollama model this session has sent a request to.
#: Quitting the game unloads each of them (see unload_ollama_models).
_OLLAMA_MODELS_USED = set()

#: How long quitting waits for Ollama to connect and to answer one unload
#: request, in seconds. Ollama answers once the model is out of memory.
OLLAMA_UNLOAD_TIMEOUT = (0.5, 3)


def _unload_ollama_model(chat_url, model, timeout):
    """Asks Ollama to unload `model` now. A request with keep_alive 0 does that."""
    if requests is None:
        return    # The web build has no Ollama connection.
    try:
        requests.post(chat_url.replace("/api/chat", "/api/generate"),
                      json={"model": model, "prompt": "", "keep_alive": 0}, timeout=timeout)
    except requests.RequestException:
        pass    # Ollama is not running or did not answer in time.


def unload_ollama_models():
    """Unloads every Ollama model this session used. The game calls this when it quits.

    Ollama runs as its own program, so closing the game does not unload a
    model. Without this, the model would hold its memory until
    OLLAMA_KEEP_ALIVE ran out.
    """
    for chat_url, model in list(_OLLAMA_MODELS_USED):
        _unload_ollama_model(chat_url, model, OLLAMA_UNLOAD_TIMEOUT)
    _OLLAMA_MODELS_USED.clear()

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


def _parse_reply_json(text, fallback=None):
    """A provider's reply, parsed -- or the raw text as a plain message.

    All four providers make the same promise: unparseable output is handed back
    as something the game can still show, not thrown away as an API failure.
    They each spelled that out separately, and Gemini's copy had drifted into
    reporting a decode error as a failed call, which it isn't.

    `fallback` formats the unparseable text (Ollama's says "JSON ERROR:" so a
    local model's mangled output is distinguishable from a real cable). That
    text is flagged as a provider error, like any other failure: a proposal
    still shows it, but letters, the director and proactive lines drop it
    rather than sending "JSON ERROR: ..." as a leader's words.
    """
    json_text = text.strip()
    # Some local models wrap valid JSON in a Markdown code block.
    if json_text.startswith("```") and json_text.endswith("```"):
        language, newline, body = json_text[3:-3].partition("\n")
        if newline and language.strip().lower() in ("", "json"):
            json_text = body.strip()
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        if fallback is None:
            return {"message": text}
        return _provider_error(fallback(text))


def _request_json(url, payload, headers, extract, turn_id=None):
    """POSTs to an HTTP provider and unwraps its reply, or reports the failure.

    The abort checks, the HTTP-status branch and the exception branch are the
    same for every REST provider; only the endpoint, the request shape and
    where the text sits in the response differ, so those are the arguments.
    `extract` pulls the assistant's text out of the decoded response body.

    Aborts return None at each of the three points a Force Skip can land, so a
    request the player has walked away from never writes into the next turn.
    """
    if _aborted(turn_id):
        return None

    try:
        response = _session().post(url, json=payload, headers=headers, timeout=120)
        if _aborted(turn_id):
            return None

        if response.status_code >= 400:
            return _provider_error(f"HTTP ERROR {response.status_code}: {response.text}")

        return _parse_reply_json(extract(response.json()))
    except Exception as e:
        if _aborted(turn_id):
            return None
        return _provider_error(f"API ERROR: {str(e)}")


#: These providers share the OpenAI-style chat completions API.
#: Each entry supplies the endpoint, API-key getter, and model getter.
OPENAI_COMPATIBLE_PROVIDERS = {
    "CHATGPT": (lambda: c.CHATGPT_API_URL, get_chatgpt_api_key, get_chatgpt_model),
    "DEEPSEEK": (lambda: c.DEEPSEEK_API_URL, get_deepseek_api_key, get_deepseek_model),
    "KIMI": (lambda: c.KIMI_API_URL, get_kimi_api_key, get_kimi_model),
    "OPENROUTER": (lambda: c.OPENROUTER_API_URL, get_openrouter_api_key, get_openrouter_model),
}

#: Room for a Claude reply. Newer models think before they answer, and that
#: thinking counts against this limit; at 1024 it could use all of it and
#: leave no text.
CLAUDE_MAX_TOKENS = 16000


def _combined_prompt(system_prompt, user_prompt):
    """The one prompt every provider receives: the world first, instructions last.

    Every caller in the game builds its user half as "<the world> <this
    nation's situation> <the task>", and the world is around ninety percent of
    it and identical for every request in a turn -- but the system half differs
    by phase, and often by request, so putting it in front made a letter
    prompt, a director prompt and a proposal reply share their first eight
    characters. Measured on the 1941 map: 0% shared across phases against 84%
    this way round.

    A local model re-reads from the first token that differs -- nine seconds of
    every phase's budget, spent re-reading a world that had not changed since
    the phase before. Hosted providers cache matching prefixes too, which makes
    the repeated part cheaper and faster, so all of them get the same order.
    One user message also avoids 400 errors on lightweight models whose
    templates have no system role (like many 0.5b models).
    """
    return f"{user_prompt}\n\n{system_prompt}"


def call_openai_compatible(url, api_key, model, system_prompt, user_prompt, turn_id=None):
    """Send a request to an OpenAI-compatible chat completions endpoint."""
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": _combined_prompt(system_prompt, user_prompt)},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    return _request_json(url, payload, headers,
                         lambda body: body["choices"][0]["message"]["content"],
                         turn_id)


def _claude_content(prompt):
    """The prompt as content blocks, with a cache breakpoint after the shared world.

    Claude caches only up to a marked block, so the part that every nation
    shares this turn is its own block. A prompt without the world context is
    sent as plain text. A shared part below the model's minimum cache size is
    simply not cached.
    """
    shared, marker, rest = prompt.partition(ai_prompts.SHARED_CONTEXT_END)
    if not marker or not shared:
        return prompt
    return [
        {"type": "text", "text": shared, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": marker + rest},
    ]


def _claude_text(body):
    """The text block of a Claude reply. A thinking block can come first."""
    for block in body.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    raise ValueError(f"reply had no text (stop_reason: {body.get('stop_reason')})")


def call_claude(api_key, model, system_prompt, user_prompt, turn_id=None):
    """Hits Anthropic's Messages API, which uses its own auth headers and
    request/response shape rather than the OpenAI-style ones above."""
    payload = {
        "model": model,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "messages": [{"role": "user",
                      "content": _claude_content(_combined_prompt(system_prompt, user_prompt))}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": c.CLAUDE_API_VERSION,
    }

    return _request_json(c.CLAUDE_API_URL, payload, headers, _claude_text, turn_id)


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
            contents=_combined_prompt(system_prompt, user_prompt),
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        if _aborted(turn_id):
            return None

        return _parse_reply_json(response.text)
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


def _call_provider(mode, system_prompt, user_prompt, turn_id, schema=None):
    """One request to whichever provider is configured.

    Returns the parsed reply dict, or None when the request was abandoned --
    Force Skip, or the turn moving on while it was out. Gemini is the
    else-branch, so an unrecognised mode still answers.

    A request that failed on its own is timed: a provider that is slow and
    then errors is what the estimate is for. A request the game abandoned or
    cut off is not, because its time says nothing about what a request costs.
    """
    started = time.monotonic()
    aborts = _ABORT_COUNT[0]
    abandoned = False
    try:
        result = _dispatch(mode, system_prompt, user_prompt, turn_id, schema)
        abandoned = result is None
        return result
    finally:
        if not abandoned and _ABORT_COUNT[0] == aborts:
            _time_call(time.monotonic() - started)


def _dispatch(mode, system_prompt, user_prompt, turn_id, schema=None):
    """Sends one request to the provider that `mode` names.

    `schema` is the JSON schema of the reply. Only Ollama uses it (see
    call_ollama). A hosted provider's schema support differs by provider and
    model, and a schema that changes for each country could stop a hosted
    provider from reusing the shared prompt prefix.
    """
    mode = normalize_ai_mode(mode)
    if mode == "OLLAMA":
        return call_ollama(system_prompt, user_prompt, turn_id, schema=schema)

    if mode in OPENAI_COMPATIBLE_PROVIDERS:
        get_url, get_key, get_model = OPENAI_COMPATIBLE_PROVIDERS[mode]
        return call_openai_compatible(get_url(), get_key(), get_model(),
                                      system_prompt, user_prompt, turn_id)

    if mode == "CLAUDE":
        return call_claude(get_claude_api_key(), get_claude_model(),
                           system_prompt, user_prompt, turn_id)

    return call_gemini(system_prompt, user_prompt, turn_id)


def _run_provider(mode, system_prompt, user_prompt, turn_id, canned, accepted=None, raw=False,
                  schema=None):
    """Sends one prompt to the configured provider and shapes the answer.

    raw=True hands back the parsed provider dict (or None) instead of a reply,
    for callers that want a bare string rather than a verdict-carrying answer.
    `schema` is the JSON schema of the reply that the prompt asks for (see
    _dispatch).

    A None result means the request was abandoned, so every provider now falls
    back to the canned line. The Ollama branch used to put its own
    "OLLAMA ERROR: No response" in front of the player instead, which meant
    pressing Force Skip produced an error message dressed as a diplomatic cable.
    """

    result = _call_provider(mode, system_prompt, user_prompt, turn_id, schema)
    if raw:
        return result
    if result is None:
        return _reply(canned, accepted=accepted)
    return _reply(result.get("message", f"{mode} ERROR: reply had no 'message' field"),
                  result, accepted, llm=bool(result.get("message")) and not result.get("error"))

#: Ollama's context window for every request, in tokens. Without it Ollama
#: uses its own default, which on many installs is smaller than one prompt on a
#: world map, and the excess is cut without an error. Every request uses the
#: same value, because a change makes Ollama reload the model. 8192 is the most
#: llama3, the default model, was trained on.
OLLAMA_CONTEXT_TOKENS = 8192

#: How long Ollama keeps the model loaded after a request. Ollama's own default
#: is five minutes, and a player can plan a turn for longer than that. The next
#: AI phase would then load the model again and read the whole world from the
#: start: about 18 seconds per call instead of 5 on one local llama3.
OLLAMA_KEEP_ALIVE = "60m"

#: A reply that has fallen into a loop: its last OLLAMA_REPEAT_MIN_CHARACTERS
#: characters or more are one block of at most OLLAMA_REPEAT_MAX_BLOCK
#: characters, repeated at least OLLAMA_REPEAT_COUNT times in a row.
OLLAMA_REPEAT_MIN_CHARACTERS = 256
OLLAMA_REPEAT_MAX_BLOCK = 256
OLLAMA_REPEAT_COUNT = 4
#: How much new text arrives between checks, so a reply is not rescanned for
#: every token.
OLLAMA_REPEAT_CHECK_CHARACTERS = 64


def _repeats_itself(text):
    """Whether the end of a reply is one block of text repeated again and again.

    A small local model can fall into a loop, such as the same sentence or
    endless whitespace inside its JSON. It then writes until the context window
    is full, which can take minutes of the turn's budget. No usable letter or
    reply ends in four copies of the same block.
    """
    for size in range(1, OLLAMA_REPEAT_MAX_BLOCK + 1):
        length = max(OLLAMA_REPEAT_MIN_CHARACTERS, OLLAMA_REPEAT_COUNT * size)
        if len(text) < length:
            break
        if text[-size:] != text[-2 * size:-size]:
            continue
        tail = text[-length:]
        if tail[size:] == tail[:-size]:
            return True
    return False


def call_ollama(system_prompt, user_prompt, turn_id=None, schema=None):
    """Helper to hit local Ollama instance with direct socket control for instant termination.

    `schema` is the JSON schema of the reply. Ollama enforces it while it
    generates, so a reply can name only the actions, countries and options
    that the schema lists.
    """
    if _aborted(turn_id): return None

    url_str = get_ollama_url()
    parsed_url = urllib.parse.urlparse(url_str)

    model_name = get_ollama_model()
    _OLLAMA_MODELS_USED.add((url_str, model_name))

    # The world goes first and the instructions last, which is the whole reason
    # a turn is affordable here -- see _combined_prompt.
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": _combined_prompt(system_prompt, user_prompt)}
        ],
        "options": {"num_ctx": OLLAMA_CONTEXT_TOKENS},
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "stream": True # Stream token-by-token
    }

    # Conditionally apply strict JSON formatting if the model supports it natively.
    # The schema does not change the prompt, so the shared prefix is unaffected.
    if hasattr(c, 'OLLAMA_JSON_SUPPORTED_MODELS') and any(supported in model_name.lower() for supported in c.OLLAMA_JSON_SUPPORTED_MODELS):
        payload["format"] = schema or "json"

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
            except (ValueError, AttributeError):
                err_msg = error_body

            return _provider_error(f"OLLAMA HTTP ERROR {response.status}: {err_msg}")

        full_text = ""
        checked = 0
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
                if len(full_text) - checked >= OLLAMA_REPEAT_CHECK_CHARACTERS:
                    checked = len(full_text)
                    if _repeats_itself(full_text):
                        # Closing the connection (below) stops the generation in Ollama.
                        return _provider_error("OLLAMA ERROR: the reply kept repeating itself, "
                                               "so the game stopped it.")

        # Parse the final reconstructed string. Its fallback is prefixed so a
        # local model's mangled output reads as such, not as a diplomatic cable.
        return _parse_reply_json(full_text, lambda t: f"JSON ERROR: {t}")

    except Exception as e:
        # If the connection was forcefully closed by the skip button, fail silently
        if _aborted(turn_id):
            return None
        print(f"Ollama Connection Error: {e}")
        return _provider_error(f"OLLAMA ERROR: {str(e)}")
    finally:
        if conn in ACTIVE_OLLAMA_CONNECTIONS:
            ACTIVE_OLLAMA_CONNECTIONS.remove(conn)
        try:
            conn.close()
        except Exception:
            pass
