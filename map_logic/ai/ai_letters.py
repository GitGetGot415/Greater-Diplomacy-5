"""Letters: how AI countries talk to each other, and how each keeps its plans.

Every word one AI government says to another travels as an ordinary inbox
letter, the same mail a player reads and writes. A country sits at its desk,
reads the letters waiting for it, writes letters of its own, and rewrites a
private notebook of opinions and plans.

A letter changes the game in one way only: its reader's opinion of its author,
bounded by AI_OPINION_CHANGE_MAX. A player's letter to an AI already does the
same through the AI's reply (diplomacy_processor._react_to_reply). Agreements
still need the ordinary proposals, which the director chooses each turn with
the notebook in front of it and the countries it writes to on its menu.

The phase runs before the proactive pass, in AI_LETTER_PASSES passes. Letters
written in one pass reach their readers at once, so the next pass can answer
them inside the same turn.
"""

from data.state_access import world_for, session_for
import json
import time

import data.constants as c
from data import queries
from data.platform import IS_WEB
from map_logic.ai import (ai_evaluation, ai_handler, ai_llm_runner, ai_personality,
                          ai_prompts, ai_world)
from map_logic.diplomacy import diplomacy_messages


#: Stamped on both copies of a letter this phase sends. A player's plain message
#: has no stamp: the response phase answers it (process_custom_message), so the
#: letter phase never answers it a second time.
LETTER = "letter"
#: Stamped on the reader's copy once its reader has sat down with it.
LETTER_READ = "letter_read"
#: The country's private notebook, a plain string on its country record.
NOTEBOOK = "ai_notebook"
#: The turn a country last sat at its desk, for longest-waiting-first order.
LAST_SAT = "letters_last_turn"

_SENT_PREFIX = "To: "


def notebook(nation_data, nation):
    """What this country has written down for itself, or ""."""
    text = (nation_data.get(nation) or {}).get(NOTEBOOK)
    return text if isinstance(text, str) else ""


def unread_letters(nation_data, nation):
    """Letters from other AI governments this country has not read, oldest first."""
    inbox = (nation_data.get(nation) or {}).get("inbox") or []
    return [msg for msg in reversed(inbox)
            if isinstance(msg, dict) and msg.get(LETTER) and not msg.get(LETTER_READ)
            and not str(msg.get("sender", "")).startswith(_SENT_PREFIX)]


def _counterpart(msg):
    sender = str(msg.get("sender", ""))
    return sender[len(_SENT_PREFIX):] if sender.startswith(_SENT_PREFIX) else sender


def _is_correspondence(msg):
    """A letter or a plain message, as opposed to a proposal or a notice."""
    return isinstance(msg, dict) and msg.get("type") == "TEXT"


def correspondents(nation_data, nation, alive, limit=None):
    """Countries this one has exchanged letters with, most recent first.

    Read from the inbox, which keeps a sent copy of everything, so a country
    counts whether it wrote or was written to. A player who writes to an AI
    counts too. `limit` defaults to AI_CORRESPONDENTS_MAX.
    """
    limit = c.AI_CORRESPONDENTS_MAX if limit is None else limit
    found = []
    for msg in (nation_data.get(nation) or {}).get("inbox") or []:
        if not _is_correspondence(msg):
            continue
        other = _counterpart(msg)
        if other == nation or other not in alive or other in found:
            continue
        found.append(other)
        if len(found) >= limit:
            break
    return found


def _thread(nation_data, nation, other, skip_ids):
    """Earlier letters between the two, oldest first, as prompt lines."""
    lines = []
    for msg in reversed((nation_data.get(nation) or {}).get("inbox") or []):
        if not _is_correspondence(msg) or msg.get("message_id") in skip_ids:
            continue
        sender = str(msg.get("sender", ""))
        if sender == other:
            speaker = other
        elif sender == _SENT_PREFIX + other:
            speaker = "You"
        else:
            continue
        lines.append(f"  {speaker} ({msg.get('date', '')}): \"{msg.get('content', '')}\"")
    return lines[-c.AI_LETTER_THREAD_SHOWN:]


SYSTEM_PROMPT = (
    "This is your desk as the head of your government: your private notebook and your "
    "diplomatic mail. Letters are the only way you speak to other governments. Write them "
    "the way statesmen write private letters to each other: specific, in your own voice, "
    "about real events and real interests. You can give your honest or calculated opinion "
    "of other countries, share or ask for information, sound out an alliance or a trade, "
    "coordinate a war, warn, flatter, threaten, or turn someone down. Do not restate "
    "figures from your briefing, do not write form letters, and do not write at all when "
    "you have nothing worth saying.\n"
    "A letter commits nobody to anything. Your government makes formal proposals separately "
    "each turn, guided by your notebook, so plan in your notebook what you want to happen.\n"
    f"Write at most {c.AI_LETTERS_PER_CALL} letters, one per country, and only to countries "
    "listed under WHO READS LETTERS. Answer the letters waiting for you when they deserve "
    "an answer.\n"
    f"For each letter waiting for you, give an integer from -{c.AI_OPINION_CHANGE_MAX} to "
    f"{c.AI_OPINION_CHANGE_MAX}: how much it improved or worsened your opinion of its author.\n"
    f"Then rewrite your notebook in full, in under {c.AI_NOTEBOOK_LENGTH} characters: what you "
    "think of the countries that matter to you, what you want, what you have promised and been "
    "promised, and what you are waiting to hear. Nobody else ever reads it.\n"
    "VOICE: write each letter as your own government, in the first person plural -- 'we', "
    "'our', 'us'. Never refer to your own country by name or in the third person.\n"
    "Reply ONLY with a valid JSON object of this shape:\n"
    '{"letters": [{"to": "Country", "text": "the letter"}], '
    '"opinions": {"Country": 0}, "notebook": "your notebook"}'
)


def build_prompt(world_state, nation, unread, readers, alive, current_date):
    """(system, user) for one country's sitting.

    The world context comes first and is the same for every country this turn,
    and the system half names nobody, so the shared prefix survives (see
    documentation/llm_ai.txt, SHARED PROMPT PREFIX).
    """
    nation_data = world_state.nation_data
    lines = [ai_evaluation.get_world_context(nation_data, alive, nation,
                                             current_date=current_date)]
    lines.append(f"Your temperament: "
                 f"{ai_personality.describe(nation_data, nation, world_state.scenario_settings)}.")

    lines.append("\n--- YOUR PRIVATE NOTEBOOK ---")
    lines.append(notebook(nation_data, nation) or "(empty: you have written nothing yet)")

    lines.append("\n--- LETTERS WAITING FOR YOU ---")
    if unread:
        for msg in unread:
            lines.append(f"From {msg.get('sender')} ({msg.get('date', '')}): "
                         f"\"{msg.get('content', '')}\"")
    else:
        lines.append("None.")

    unread_ids = {msg.get("message_id") for msg in unread}
    others = []
    for name in [msg.get("sender") for msg in unread] + correspondents(nation_data, nation, alive):
        if name not in others:
            others.append(name)
    earlier = []
    for other in others:
        thread = _thread(nation_data, nation, other, unread_ids)
        if thread:
            earlier.append(f"With {other}:")
            earlier.extend(thread)
    if earlier:
        lines.append("\n--- EARLIER LETTERS ---")
        lines.extend(earlier)

    lines.append("\n--- WHO READS LETTERS ---")
    lines.append(", ".join(r for r in readers if r != nation) or "Nobody.")
    lines.append("\nSit down and write.")
    return SYSTEM_PROMPT, "\n".join(lines)


def reply_schema(recipients, authors):
    """The JSON schema of SYSTEM_PROMPT's reply.

    Ollama enforces it while it generates (see ai_handler.call_ollama). A letter
    can go only to a listed recipient. The opinions name exactly the authors of
    the letters that were read, each within AI_OPINION_CHANGE_MAX. With no
    recipients, the letter list must be empty.
    """
    letter = {"type": "object", "additionalProperties": False, "required": ["to", "text"],
              "properties": {"to": {"type": "string", "enum": list(recipients)},
                             "text": {"type": "string"}}}
    letters = ({"type": "array", "maxItems": c.AI_LETTERS_PER_CALL, "items": letter}
               if recipients else {"type": "array", "maxItems": 0})
    opinion = {"type": "integer", "minimum": -c.AI_OPINION_CHANGE_MAX,
               "maximum": c.AI_OPINION_CHANGE_MAX}
    opinions = {"type": "object", "additionalProperties": False, "required": list(authors),
                "properties": {author: opinion for author in authors}}
    return {"type": "object", "additionalProperties": False,
            "required": ["letters", "opinions", "notebook"],
            "properties": {"letters": letters, "opinions": opinions,
                           "notebook": {"type": "string"}}}


def _resolve(name, candidates, nation_data):
    """The country ID a model meant, from an ID or a display name, or None."""
    if not isinstance(name, str):
        return None
    name = name.strip()
    if name in candidates:
        return name
    wanted = name.lower()
    for candidate in candidates:
        display = queries.get_country_display_name(candidate, nation_data)
        if candidate.lower() == wanted or str(display).lower() == wanted:
            return candidate
    return None


def parse_reply(reply, nation, readers, authors, nation_data):
    """(letters, opinions, notebook) from one sitting's reply.

    letters is [(recipient, text)]. opinions maps authors of letters this
    country read to the model's number, unclamped (queries.add_opinion_change
    bounds it). notebook is None when the reply did not give one.

    Anything the model made up is dropped one item at a time: a recipient who
    is not listed, a second letter to the same country, an opinion about a
    country whose letter it never saw, and a letter that talks about its own
    sender in the third person (see ai_prompts.reads_as_third_person).
    """
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except (TypeError, ValueError):
            reply = None
    if not isinstance(reply, dict):
        return [], {}, None

    recipients = [r for r in readers if r != nation]
    letters = []
    raw_letters = reply.get("letters")
    for raw in raw_letters if isinstance(raw_letters, list) else ():
        if len(letters) >= c.AI_LETTERS_PER_CALL:
            break
        if not isinstance(raw, dict):
            continue
        to = _resolve(raw.get("to"), recipients, nation_data)
        text = raw.get("text")
        if not to or any(to == sent for sent, _ in letters) or not isinstance(text, str):
            continue
        text = text.strip()[:c.AI_LETTER_LENGTH]
        if not text or ai_prompts.reads_as_third_person(text, nation, nation_data):
            continue
        letters.append((to, text))

    opinions = {}
    raw_opinions = reply.get("opinions")
    for raw_name, amount in (raw_opinions.items() if isinstance(raw_opinions, dict) else ()):
        author = _resolve(raw_name, list(authors), nation_data)
        if author:
            opinions[author] = amount

    written = reply.get("notebook")
    written = written.strip()[:c.AI_NOTEBOOK_LENGTH] if isinstance(written, str) else None
    return letters, opinions, written


def first_sitting(nation_data, writers, limit=None):
    """Who writes in the first pass, in the order the batch serves them.

    Every country with letters waiting, then up to `limit` others, which
    defaults to AI_LETTER_WRITERS_PER_TURN. Both groups put whoever has waited
    longest first, as the director does, so a short budget does not hand the
    desk to the same country every turn.
    """
    limit = c.AI_LETTER_WRITERS_PER_TURN if limit is None else limit

    def waited(nation):
        stamp = (nation_data.get(nation) or {}).get(LAST_SAT)
        return (0 if stamp is None else 1, stamp or 0, nation)

    waiting = [n for n in writers if unread_letters(nation_data, n)]
    others = [n for n in writers if n not in waiting]
    return sorted(waiting, key=waited) + sorted(others, key=waited)[:max(0, limit)]


def apply_reply(context, job, reply, readers, turn):
    """Delivers one sitting's letters and records what its writer read and wrote."""
    nation_data = world_for(context).nation_data
    nation = job["nation"]
    record = nation_data.setdefault(nation, {})
    # Stamped whether or not the reply was usable, like the director's
    # llm_last_turn: a provider that keeps failing must not keep one country
    # at the front of the queue.
    record[LAST_SAT] = turn
    if not isinstance(reply, dict) or reply.get("error"):
        return

    letters, opinions, written = parse_reply(reply, nation, readers,
                                             job["authors"], nation_data)

    # Only the letters that were in front of it. One that arrived while this
    # sitting was out waits for the next pass.
    for msg in record.get("inbox") or []:
        if msg.get("message_id") in job["letter_ids"]:
            msg[LETTER_READ] = True

    for author, amount in opinions.items():
        queries.add_opinion_change(nation, author, amount, nation_data)
    if written is not None:
        record[NOTEBOOK] = written
    for to, text in letters:
        diplomacy_messages.send_message(context, nation, to, text, "TEXT",
                                        extra={LETTER: True}, llm=True)


def process_letters(context):
    """Runs the turn's letter passes. Every model-driven AI country can write.

    The loading bar counts passes, which are known before the work starts;
    who sits in a later pass depends on the letters of the one before it.
    """
    world_state = world_for(context)
    session_state = session_for(context)
    session_state.letters_total = 0
    session_state.letters_completed = 0
    mode = ai_handler.get_ai_mode()
    if IS_WEB or mode == "OFF":
        return

    world = ai_world.for_screen(context)
    nation_data = world_state.nation_data
    alive = set(queries.get_living_nations(world_state.map_data))
    writers = sorted(n for n in queries.get_active_ai_nations(context)
                     if n in alive and ai_evaluation.llm_enabled_for(n, world) is True)
    if not writers:
        return

    humans = [p for p in session_state.active_players if p in alive and p not in writers]
    readers = sorted(set(writers) | set(humans))
    turn = queries.get_total_turns(world_state.time_manager)
    current_date = world_state.time_manager.get_date_string()
    my_turn_id = ai_handler.CURRENT_TURN_ID
    deadline = ai_llm_runner.turn_deadline(context, c.AI_BUDGET_SHARE_LETTERS)

    session_state.letters_total = c.AI_LETTER_PASSES
    session_state.loading_status_text = "Writing Letters..."

    def call(job):
        return ai_handler._run_provider(mode, job["system"], job["user"],
                                        my_turn_id, None, raw=True, schema=job["schema"])

    def record(job, reply):
        apply_reply(context, job, reply, readers, turn)

    def record_fallback(job):
        pass    # unread letters stay unread and wait for the next sitting

    for index in range(c.AI_LETTER_PASSES):
        sitting = (first_sitting(nation_data, writers) if index == 0
                   else [n for n in writers if unread_letters(nation_data, n)])
        if not sitting:
            # Letters only come from a pass, so no later pass has anyone either.
            session_state.letters_completed = session_state.letters_total
            return
        if deadline is not None and time.monotonic() >= deadline:
            return

        # Built here, on the turn's own thread, so a worker never reads an inbox
        # while another sitting's letters are being delivered into it.
        jobs = []
        for nation in sitting:
            unread = unread_letters(nation_data, nation)
            system, user = build_prompt(world_state, nation, unread, readers, alive,
                                        current_date)
            authors = {msg.get("sender") for msg in unread}
            jobs.append({"nation": nation, "system": system, "user": user,
                         "letter_ids": {msg.get("message_id") for msg in unread},
                         "authors": authors,
                         "schema": reply_schema([r for r in readers if r != nation],
                                                sorted(authors))})

        done = {"count": 0}

        def progress(_job, index=index, total=len(jobs)):
            done["count"] += 1
            session_state.loading_status_text = (
                f"Writing Letters (pass {index + 1}/{c.AI_LETTER_PASSES}, "
                f"{done['count']}/{total})...")

        outcome = ai_llm_runner.run_llm_batch(
            jobs, call, record, record_fallback,
            on_progress=progress,
            should_abort=lambda: session_state.force_skip_llm,
            max_workers=queries.get_ai_threads(),
            deadline=deadline,
            phase=f"Writing letters (pass {index + 1}/{c.AI_LETTER_PASSES})",
            describe=lambda job: queries.get_country_display_name(job["nation"], nation_data))
        ai_llm_runner.report_unserved(context, outcome, "Writing letters",
                                      fallback="read their letters next turn")
        if outcome.abandoned:
            return
        session_state.letters_completed += 1
