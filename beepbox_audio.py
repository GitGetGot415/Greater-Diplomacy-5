"""BeepBox and UltraBox song playback for desktop and browser builds."""

import base64
from contextlib import contextmanager
import importlib
import io
import json
import os
import queue
import threading
import time
from urllib.parse import unquote, urlsplit
import wave

import data.constants as c


SAMPLE_RATE = 44100
# Rendering a 512-frame block made the producer cross the Python/JavaScript
# boundary about 86 times per second. A 2048-frame synthesis step substantially
# reduces that overhead while still yielding the GIL often enough for the game.
CHUNK_FRAMES = 2048
# SDL_mixer plays these rolling half-second blocks entirely in native code. A
# second block is queued behind the current one, so turn processing only has to
# let the regular game loop run once per half second to keep playback seamless.
# This is deliberately not a whole-song render: switching tracks still starts
# after only the first small block has been synthesized.
PLAYBACK_BLOCK_FRAMES = SAMPLE_RATE // 2
# Keep about sixteen seconds of incrementally rendered PCM ready. The producer
# can fill this while the player is issuing orders, giving unusually expensive
# turn resolution plenty of headroom without delaying track changes or creating
# a temporary WAV file.
BUFFERED_BLOCKS = 32

_MIXER_STREAM_LOCK = threading.Lock()
_MIXER_STREAM_OWNER = None
SONG_SYNTHS = {
    "BeepBox": ("beepbox", "beepbox_synth.min.js"),
    "UltraBox": ("ultrabox", "ultrabox_synth.min.js"),
}


def timeline_seconds_from_source(source_seconds, speed, timeline_mode):
    """Convert source-track seconds to the selected music timeline."""
    if timeline_mode == c.MUSIC_PITCH_TIMELINE_DYNAMIC:
        return source_seconds / speed
    return source_seconds


def source_seconds_from_timeline(timeline_seconds, speed, timeline_mode):
    """Convert a scrubber position in the selected timeline to source seconds."""
    if timeline_mode == c.MUSIC_PITCH_TIMELINE_DYNAMIC:
        return timeline_seconds * speed
    return timeline_seconds


def _song_format(song):
    """Return the supported format for a song object, or None."""
    if (isinstance(song, dict) and isinstance(song.get("format"), str)
            and song["format"] in SONG_SYNTHS and isinstance(song.get("channels"), list)):
        return song["format"]
    return None


def is_beepbox_song(path):
    """Recognize supported BeepBox-family songs without starting an audio engine."""
    if not path.lower().endswith(".json"):
        return False
    try:
        with open(path, "r", encoding="utf-8-sig") as song_file:
            song = json.load(song_file)
        return _song_format(song) is not None
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return False


def is_available():
    """Return whether the native runtime for both song formats is available.

    QuickJS is retained only for tests and tooling that evaluate BeepBox data.
    It is an interpreter and cannot synthesize dense tracks at playback speed,
    so treating it as a desktop playback fallback causes permanent underruns.
    """
    return _can_import_runtime("py_mini_racer")


def _can_import_runtime(module):
    try:
        importlib.import_module(module)
    except (ImportError, OSError):
        return False
    return True


@contextmanager
def _native_js_context():
    """Create the V8 context required for real-time desktop synthesis."""
    try:
        from py_mini_racer import mini_racer
        context_manager = mini_racer()
        context = context_manager.__enter__()
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            "BeepBox and UltraBox desktop playback require the bundled V8 runtime "
            "(mini-racer); QuickJS is too slow for real-time music synthesis"
        ) from exc

    try:
        yield context, "v8"
    except BaseException as exc:
        context_manager.__exit__(type(exc), exc, exc.__traceback__)
        raise
    else:
        context_manager.__exit__(None, None, None)


def has_beepbox_replacement(path):
    """Whether a native package can replace this audio file with sibling JSON."""
    if os.path.splitext(path)[1].lower() not in (".mp3", ".wav", ".ogg"):
        return False
    return is_beepbox_song(os.path.splitext(path)[0] + ".json")


def _sample_url(reference):
    """Separate UltraBox sample options from the sample address."""
    return reference.split("!", 2)[-1] if reference.startswith("!") else reference


def _local_sample_path(song_path, url):
    """Find companion samples, including exports made with a local sample server."""
    parsed = urlsplit(url)
    if parsed.scheme and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        return None
    relative = unquote(parsed.path).lstrip("/")
    path = os.path.join(os.path.dirname(song_path), relative)
    return path if os.path.isfile(path) else None


def _read_song(song_path):
    with open(song_path, encoding="utf-8-sig") as song_file:
        song = json.load(song_file)
    if _song_format(song) is None:
        raise ValueError("Select a BeepBox or UltraBox song JSON file")
    if song["format"] == "UltraBox":
        references = []
        for reference in song.get("customSamples", []):
            url = _sample_url(reference)
            path = _local_sample_path(song_path, url)
            if path:
                with open(path, "rb") as sample_file:
                    encoded = base64.b64encode(sample_file.read()).decode("ascii")
                # Keep the original name. Instruments refer to this URL suffix.
                replacement = "data:audio/wav;base64," + encoded + "/" + url.rsplit("/", 1)[-1]
                reference = reference[:len(reference) - len(url)] + replacement
            references.append(reference)
        song["customSamples"] = references
    return song


def _native_sample_data(song, stop_event=None):
    """Decode custom WAV samples for V8, which has no browser audio decoder."""
    if not song.get("customSamples"):
        return {}
    # Load native decoding dependencies only when a song needs sample playback.
    import numpy as np

    samples = {}
    for reference in song.get("customSamples", []):
        if stop_event is not None and stop_event.is_set():
            return {}
        url = _sample_url(reference)
        if url in samples:
            continue
        label = "embedded sample" if url.startswith("data:") else url
        try:
            if url.startswith("data:"):
                header, _, payload = url.partition(",")
                if ";base64" not in header:
                    raise ValueError("Use a base64 WAV sample")
                raw = base64.b64decode(payload)
            elif urlsplit(url).scheme in ("http", "https"):
                # Network access stays on the synth worker, outside Pygame input.
                import requests

                try:
                    response = requests.get(url, timeout=10)
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise ValueError("Sample download failed: " + str(exc)) from exc
                raw = response.content
            else:
                raise ValueError("Use embedded WAV samples or companion sample files")
            with wave.open(io.BytesIO(raw)) as wav:
                width = wav.getsampwidth()
                channels = wav.getnchannels()
                rate = wav.getframerate()
                pcm = wav.readframes(wav.getnframes())
            if width == 1:
                values = (np.frombuffer(pcm, dtype=np.uint8).astype(np.float32) - 128) / 128
            elif width in (2, 4):
                values = np.frombuffer(pcm, dtype="<i" + str(width)).astype(np.float32) / (1 << (width * 8 - 1))
            elif width == 3:
                octets = np.frombuffer(pcm, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
                integers = octets[:, 0] | octets[:, 1] << 8 | octets[:, 2] << 16
                values = ((integers ^ 0x800000) - 0x800000).astype(np.float32) / 0x800000
            else:
                raise ValueError("Use 8, 16, 24, or 32-bit PCM WAV samples")
            values = values.reshape(-1, channels)[:, 0]
            if not len(values):
                raise ValueError("The WAV sample contains no audio frames")
            samples[url] = {"rate": rate, "pcm": base64.b64encode(values.astype("<f4").tobytes()).decode("ascii")}
        except (OSError, ValueError, wave.Error) as exc:
            raise ValueError(f"Cannot load UltraBox {label}. Supply its sample file or embed it in the JSON: {exc}") from exc
    return samples


def _synth_source(song):
    """Load the selected vendor synth without replacing the other format's engine."""
    directory, filename = SONG_SYNTHS[song["format"]]
    # Frozen modules can live in a temporary folder or a Python archive.
    # Startup sets the working directory to the game's persistent assets.
    assets_dir = c.ASSETS_ROOT_DIR
    with open(os.path.join(assets_dir, directory, filename), encoding="utf-8") as source_file:
        source = source_file.read()
    if song["format"] == "UltraBox":
        with open(os.path.join(assets_dir, directory, "gd5_adapter.js"), encoding="utf-8") as adapter_file:
            source = adapter_file.read().replace("/* GD5_VENDOR_SYNTH */", source)
    return source


def _drain(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


class BeepBoxStream:
    """Synthesize either song format into native SDL_mixer blocks.

    Synthesis remains on a worker, but the time-critical playback path contains
    no Python callback. That distinction matters during large turns: a Pygame
    post-mix callback has to reacquire the GIL for every audio buffer and can
    therefore make fully buffered music stutter while game logic is busy.
    """

    def __init__(self, song_path, volume=1.0, speed=1.0, start_time=0.0):
        import pygame

        mixer_format = pygame.mixer.get_init()
        if mixer_format is None:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=1024)
            mixer_format = pygame.mixer.get_init()
        if mixer_format != (SAMPLE_RATE, -16, 2):
            raise RuntimeError(
                "BeepBox playback needs a 44100 Hz, signed 16-bit stereo Pygame mixer"
            )

        self.song_path = song_path
        self.volume = max(0.0, min(1.0, float(volume)))
        self.speed = max(0.25, min(2.0, float(speed)))
        self._position = max(0.0, float(start_time))
        self._length = 0.0
        self._generation = 0
        self._ready = queue.Queue(maxsize=BUFFERED_BLOCKS)
        self._commands = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._paused = False
        self._started = False
        self._mixed_frames = 0
        self._underrun_frames = 0
        self._worker_done_generation = -1
        self._worker_error = None
        self._pygame = pygame
        # Sound.play() uses only unreserved channels. Keep channel zero for the
        # rolling music blocks so a UI click during first-block synthesis cannot
        # occupy it and make the song queue behind an unrelated sound effect.
        pygame.mixer.set_reserved(1)
        self._channel = pygame.mixer.Channel(0)
        self._current_sound = None
        self._queued_sound = None
        self._playback_origin_time = None
        self._playback_origin_position = self._position
        self._scheduled_end_position = self._position
        self._last_update_time = time.monotonic()
        self._worker = threading.Thread(
            target=self._produce, name="BeepBoxSynth", daemon=True
        )
        self._request_render(self._position, self.speed)
        global _MIXER_STREAM_OWNER
        with _MIXER_STREAM_LOCK:
            if _MIXER_STREAM_OWNER is not None:
                raise RuntimeError("A BeepBox audio stream is already active")
            self._channel.stop()
            _MIXER_STREAM_OWNER = self
        self._worker.start()

    @property
    def length(self):
        return self._length

    @property
    def position(self):
        with self._state_lock:
            self._refresh_position_locked(time.monotonic())
            return self._position

    @property
    def error(self):
        return self._worker_error

    @property
    def finished(self):
        with self._state_lock:
            return (self._worker_done_generation == self._generation
                    and not self._channel.get_busy() and self._ready.empty())

    def _produce(self):
        try:
            song = _read_song(self.song_path)
            source = _synth_source(song)
            song_json = json.dumps(song)
            samples = _native_sample_data(song, self._stop_event) if song["format"] == "UltraBox" else None
            if self._stop_event.is_set():
                return

            with _native_js_context() as (context, self._engine_name):
                if samples is not None:
                    context.eval("globalThis.gd5NativeSamples = " + json.dumps(samples))
                context.eval(source)
                context.eval(_JS_BRIDGE)
                song_json_literal = json.dumps(song_json)
                generation = -1
                cursor = 0.0
                initialized = False
                block_start = 0.0
                block_frames = 0
                block_pcm = bytearray()

                while not self._stop_event.is_set():
                    try:
                        if generation < 0:
                            command = self._commands.get(timeout=0.01)
                        else:
                            command = self._commands.get_nowait()
                        generation, cursor, speed = command
                        if initialized:
                            result = context.eval(f"gd5Seek({cursor}, {speed})")
                        else:
                            result = context.eval(
                                f"gd5Init({song_json_literal}, {SAMPLE_RATE}, {speed}, {cursor})"
                            )
                            while not context.eval("gd5SamplesReady()"):
                                if self._stop_event.wait(0.01):
                                    return
                            initialized = True
                        initialized_song = json.loads(result)
                        self._length = initialized_song["length"]
                        self._worker_done_generation = -1
                        block_start = cursor
                        block_frames = 0
                        block_pcm.clear()
                    except queue.Empty:
                        if generation < 0:
                            continue

                    if generation != self._generation:
                        continue

                    if cursor >= self._length:
                        self._worker_done_generation = generation
                        self._stop_event.wait(0.02)
                        continue

                    frames = min(CHUNK_FRAMES, max(1, int((self._length - cursor) * SAMPLE_RATE)))
                    encoded_pcm = context.eval(f"gd5Render({frames})")
                    pcm = base64.b64decode(encoded_pcm)
                    block_pcm.extend(pcm)
                    block_frames += frames
                    cursor += frames / SAMPLE_RATE

                    if (block_frames >= PLAYBACK_BLOCK_FRAMES
                            or cursor >= self._length):
                        chunk = (generation, block_start, block_frames, bytes(block_pcm))
                        while (not self._stop_event.is_set()
                               and generation == self._generation):
                            try:
                                self._ready.put(chunk, timeout=0.05)
                                block_start = cursor
                                block_frames = 0
                                block_pcm.clear()
                                break
                            except queue.Full:
                                # Keep this rendered PCM while waiting for playback;
                                # rendering it again wastes CPU and can starve playback.
                                continue
        except Exception as exc:
            self._worker_error = exc
            self._worker_done_generation = self._generation

    def update(self):
        """Keep one native PCM block queued behind the block SDL is playing."""
        if self._stop_event.is_set():
            return
        try:
            with self._state_lock:
                now = time.monotonic()
                self._refresh_position_locked(now)

                busy = self._channel.get_busy()
                native_queue = self._channel.get_queue()
                if busy and self._current_sound is None:
                    # Channel.stop() is asynchronous with respect to SDL's
                    # mixer thread. Immediately after a seek it can therefore
                    # still report the discarded pre-seek block as busy. If a
                    # fresh block is merely queued behind that stale status,
                    # audio resumes but _play_chunk() never establishes the
                    # new position clock, leaving the progress bar frozen.
                    # Channel zero is reserved for this stream, so anything
                    # playing here without _current_sound is stale and safe to
                    # replace with the first block of the new generation.
                    self._channel.stop()
                    busy = False
                    native_queue = None
                if self._queued_sound is not None and native_queue is None:
                    # SDL has promoted the queued Sound to the playing slot (or
                    # both blocks ended before this frame got interpreter time).
                    self._current_sound = self._queued_sound if busy else None
                    self._queued_sound = None
                elif not busy and native_queue is None:
                    self._current_sound = None
                    self._queued_sound = None

                if self._paused:
                    self._last_update_time = now
                    return

                # SDL can briefly report the current sound as finished before
                # promoting its queued successor. Do not call play() in that
                # window: it would discard the queued block and jump the song
                # forward by half a second.
                if not busy and native_queue is None:
                    chunk = self._next_current_chunk()
                    if chunk is not None:
                        self._play_chunk(chunk, now)
                        busy = True
                    elif (self._started
                          and self._worker_done_generation != self._generation):
                        elapsed = max(0.0, now - self._last_update_time)
                        self._underrun_frames += int(elapsed * SAMPLE_RATE)
                        self._playback_origin_time = None

                if busy and self._channel.get_queue() is None:
                    chunk = self._next_current_chunk()
                    if chunk is not None:
                        generation, start, frames, pcm = chunk
                        sound = self._pygame.mixer.Sound(buffer=pcm)
                        self._channel.queue(sound)
                        self._queued_sound = sound
                        self._scheduled_end_position = max(
                            self._scheduled_end_position,
                            start + frames / SAMPLE_RATE,
                        )

                self._last_update_time = now
        except Exception as exc:
            self._worker_error = exc

    def _play_chunk(self, chunk, now):
        _generation, start, frames, pcm = chunk
        sound = self._pygame.mixer.Sound(buffer=pcm)
        self._channel.set_volume(self.volume)
        self._channel.play(sound)
        self._current_sound = sound
        self._queued_sound = None
        self._position = start
        self._playback_origin_position = start
        self._playback_origin_time = now
        self._scheduled_end_position = start + frames / SAMPLE_RATE
        self._started = True

    def _refresh_position_locked(self, now):
        if self._paused or self._playback_origin_time is None:
            return
        previous = self._position
        self._position = min(
            self._scheduled_end_position,
            self._playback_origin_position + now - self._playback_origin_time,
        )
        if self._position > previous:
            self._mixed_frames += int((self._position - previous) * SAMPLE_RATE)

    def _next_current_chunk(self):
        while True:
            try:
                chunk = self._ready.get_nowait()
            except queue.Empty:
                return None
            if chunk[0] == self._generation:
                return chunk

    def pause(self, paused):
        with self._state_lock:
            paused = bool(paused)
            if paused == self._paused:
                return
            now = time.monotonic()
            self._refresh_position_locked(now)
            self._paused = paused
            if paused:
                self._channel.pause()
                self._playback_origin_time = None
            else:
                self._channel.unpause()
                if self._channel.get_busy():
                    self._playback_origin_position = self._position
                    self._playback_origin_time = now

    def set_volume(self, volume):
        with self._state_lock:
            self.volume = max(0.0, min(1.0, float(volume)))
            self._channel.set_volume(self.volume)

    def seek(self, position, speed=None):
        with self._state_lock:
            self._position = max(0.0, float(position))
            if speed is not None:
                self.speed = max(0.25, min(2.0, float(speed)))
            self._channel.stop()
            self._generation += 1
            self._current_sound = None
            self._queued_sound = None
            self._playback_origin_position = self._position
            self._playback_origin_time = None
            self._scheduled_end_position = self._position
            self._started = False
            _drain(self._ready)
            self._worker_done_generation = -1
            self._request_render(self._position, self.speed)

    def _request_render(self, position, speed):
        command = (self._generation, position, speed)
        while True:
            try:
                self._commands.put_nowait(command)
                return
            except queue.Full:
                try:
                    self._commands.get_nowait()
                except queue.Empty:
                    pass

    def stop(self, wait=False):
        """Detach this song and optionally wait for its synth worker to exit.

        Normal track changes stay non-blocking so the UI never waits on V8.
        Controlled teardown, such as an isolated audio test, can pass
        ``wait=True`` before shutting down the Pygame mixer.
        """
        self._stop_event.set()
        global _MIXER_STREAM_OWNER
        with _MIXER_STREAM_LOCK:
            if _MIXER_STREAM_OWNER is self:
                self._channel.stop()
                _MIXER_STREAM_OWNER = None
        # The worker is a daemon and checks _stop_event while rendering and
        # while waiting for queue space. Normal track changes must not wait for
        # an in-progress V8 synthesis call before the next song can start.
        if wait and threading.current_thread() is not self._worker:
            self._worker.join()


class WebBeepBoxStream:
    """Play either song format through its vendor's browser Web Audio API."""

    def __init__(self, song_path, volume=1.0, speed=1.0, start_time=0.0):
        import platform

        self._window = platform.window
        self.song_path = song_path
        self.volume = max(0.0, min(1.0, float(volume)))
        self.speed = max(0.25, min(2.0, float(speed)))
        self._error = None
        self._stopped = False

        song = _read_song(song_path)
        song_json = json.dumps(song)

        # The bridge and vendor bundle are evaluated once per page. The synth's
        # own activateAudio() method creates/resumes AudioContext on the user's
        # first input event, which is where the controller starts this stream.
        engine_flag = "__gd5_" + song["format"].lower() + "_ready"
        if not getattr(self._window, engine_flag, False):
            self._window.eval(_synth_source(song))
            setattr(self._window, engine_flag, True)
        if not getattr(self._window, "__gd5_music_bridge_ready", False):
            self._window.eval(_WEB_JS_BRIDGE)
            setattr(self._window, "__gd5_music_bridge_ready", True)

        getattr(self._window, "__gd5_beepbox_load")(
            song_json, self.speed, max(0.0, float(start_time)), self.volume
        )

    @property
    def length(self):
        if self._stopped:
            return 0.0
        try:
            return float(getattr(self._window, "__gd5_beepbox_length")())
        except Exception as exc:
            self._error = exc
            return 0.0

    @property
    def position(self):
        if self._stopped:
            return 0.0
        try:
            return float(getattr(self._window, "__gd5_beepbox_position")())
        except Exception as exc:
            self._error = exc
            return 0.0

    @property
    def error(self):
        if not self._stopped:
            try:
                message = getattr(self._window, "__gd5_beepbox_error")()
                if message:
                    self._error = RuntimeError(str(message))
            except Exception as exc:
                self._error = exc
        return self._error

    @property
    def finished(self):
        if self._stopped or self._error is not None:
            return False
        try:
            return bool(getattr(self._window, "__gd5_beepbox_finished")())
        except Exception as exc:
            self._error = exc
            return False

    def update(self):
        """Keep the stream interface aligned with the native implementation."""

    def pause(self, paused):
        if self._stopped:
            return
        try:
            getattr(self._window, "__gd5_beepbox_pause")(bool(paused))
        except Exception as exc:
            self._error = exc

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, float(volume)))
        if self._stopped:
            return
        try:
            getattr(self._window, "__gd5_beepbox_set_volume")(self.volume)
        except Exception as exc:
            self._error = exc

    def seek(self, position, speed=None):
        if self._stopped:
            return
        if speed is not None:
            self.speed = max(0.25, min(2.0, float(speed)))
        try:
            getattr(self._window, "__gd5_beepbox_seek")(
                max(0.0, float(position)), self.speed
            )
        except Exception as exc:
            self._error = exc

    def stop(self):
        if self._stopped:
            return
        try:
            getattr(self._window, "__gd5_beepbox_stop")()
        except Exception as exc:
            self._error = exc
        self._stopped = True


_SONG_JS_BRIDGE = r"""
function gd5SongEngine(data) {
    return data.format === "UltraBox" ? gd5UltraBox : beepbox;
}
function gd5IsUltraBox(synth) {
    return typeof gd5UltraBox !== "undefined" && synth instanceof gd5UltraBox.Synth;
}
function gd5SongLength(synth, outputRate) {
    return gd5IsUltraBox(synth)
        ? synth.getTotalSamples(true, true, 0) / outputRate
        : synth.song.barCount * synth.getSamplesPerBar() / outputRate;
}
function gd5ConfigureSynth(synth, outputRate, speed, seconds) {
    synth.samplesPerSecond = outputRate / speed;
    synth.computeDelayBufferSizes();
    synth.resetEffects();
    if (gd5IsUltraBox(synth)) {
        const config = gd5UltraBox.Config;
        const parts = config.partsPerBeat * synth.song.beatsPerBar;
        const target = seconds * outputRate;
        const length = synth.getTotalSamples(true, true, 0);
        if (seconds <= 0) synth.playhead = 0;
        else if (target >= length) synth.playhead = synth.song.barCount;
        else {
            // Reuse the vendor's tempo and next-bar calculations for seeking.
            // Search bars first, then the position inside the selected bar.
            let low = 0, high = synth.song.barCount;
            while (low + 1 < high) {
                const middle = (low + high) >> 1;
                const sample = synth.getTotalSamples(true, true, 0, {bar: middle, part: 0});
                if (sample <= target) low = middle; else high = middle;
            }
            const bar = low;
            let partLow = 0, partHigh = synth.findPartsInBar(bar);
            for (let i = 0; i < 24; i++) {
                const middle = (partLow + partHigh) / 2;
                const sample = synth.getTotalSamples(true, true, 0, {bar: bar, part: middle});
                if (sample <= target) partLow = middle; else partHigh = middle;
            }
            synth.playhead = bar + (partLow + partHigh) / (2 * parts);
        }
        synth.computeLatestModValues();
    } else synth.playhead = seconds * outputRate / synth.getSamplesPerBar();
    synth.gd5Position = seconds;
    synth.gd5Length = gd5SongLength(synth, outputRate);
}
"""


_JS_BRIDGE = _SONG_JS_BRIDGE + r"""
if (typeof gd5SamplesReady === "undefined") globalThis.gd5SamplesReady = function () { return true; };
globalThis.gd5Synth = null;
globalThis.gd5Length = 0;
globalThis.gd5OutputRate = 44100;
globalThis.gd5Init = function(songJson, outputRate, speed, seekSeconds) {
    const data = JSON.parse(songJson);
    const engine = gd5SongEngine(data);
    if (data.format === "UltraBox") gd5BeginSampleLoad();
    const song = new engine.Song();
    song.fromJsonObject(data);
    const synth = new engine.Synth(song);
    synth.loopRepeatCount = 0;
    gd5ConfigureSynth(synth, outputRate, speed, seekSeconds);
    gd5OutputRate = outputRate;
    gd5Synth = synth;
    gd5Length = gd5SongLength(synth, outputRate);
    return JSON.stringify({length: gd5Length});
};
globalThis.gd5Seek = function(seekSeconds, speed) {
    if (!gd5Synth) return JSON.stringify({length: 0});
    gd5ConfigureSynth(gd5Synth, gd5OutputRate, speed, seekSeconds);
    gd5Length = gd5SongLength(gd5Synth, gd5OutputRate);
    return JSON.stringify({length: gd5Length});
};
globalThis.gd5Render = function(frameCount) {
    const left = new Float32Array(frameCount);
    const right = new Float32Array(frameCount);
    gd5Synth.synthesize(left, right, frameCount, true);
    const bytes = new Uint8Array(frameCount * 4);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < frameCount; i++) {
        const l = Math.max(-1, Math.min(1, left[i]));
        const r = Math.max(-1, Math.min(1, right[i]));
        view.setInt16(i * 4, Math.round(l * 32767), true);
        view.setInt16(i * 4 + 2, Math.round(r * 32767), true);
    }
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const parts = [];
    const partSize = 4095;
    for (let start = 0; start < bytes.length; start += partSize) {
        const end = Math.min(bytes.length, start + partSize);
        let encoded = "";
        for (let i = start; i < end; i += 3) {
            const a = bytes[i];
            const hasB = i + 1 < end;
            const hasC = i + 2 < end;
            const b = hasB ? bytes[i + 1] : 0;
            const c = hasC ? bytes[i + 2] : 0;
            encoded += alphabet[a >> 2];
            encoded += alphabet[((a & 3) << 4) | (b >> 4)];
            encoded += hasB ? alphabet[((b & 15) << 2) | (c >> 6)] : "=";
            encoded += hasC ? alphabet[c & 63] : "=";
        }
        parts.push(encoded);
    }
    return parts.join("");
};
"""


_WEB_JS_BRIDGE = _SONG_JS_BRIDGE + r"""
window.__gd5_beepbox_synth = null;
window.__gd5_beepbox_gain = null;
window.__gd5_beepbox_pause_requested = false;
window.__gd5_beepbox_speed = 1;
window.__gd5_beepbox_volume = 1;
window.__gd5_beepbox_output_rate = 44100;
window.__gd5_beepbox_loading = false;
window.__gd5_beepbox_failure = null;
window.__gd5_beepbox_error = function() { return window.__gd5_beepbox_failure; };
window.__gd5_beepbox_length = function() {
    const synth = window.__gd5_beepbox_synth;
    return synth ? synth.gd5Length : 0;
};
window.__gd5_beepbox_position = function() {
    const synth = window.__gd5_beepbox_synth;
    return synth ? (gd5IsUltraBox(synth) ? synth.gd5Position :
        synth.playhead * synth.getSamplesPerBar() / window.__gd5_beepbox_output_rate) : 0;
};
window.__gd5_beepbox_finished = function() {
    const synth = window.__gd5_beepbox_synth;
    // BeepBox pauses and wraps its playhead to bar 0 when a non-looping song
    // ends, so the playhead never remains at barCount for the bridge to poll.
    // A separate flag keeps an intentional user pause from looking like EOF.
    return !!synth && !synth.playing && !window.__gd5_beepbox_pause_requested &&
        !window.__gd5_beepbox_loading && !window.__gd5_beepbox_failure;
};
window.__gd5_beepbox_load = function(songJson, speed, startTime, volume) {
    const previous = window.__gd5_beepbox_synth;
    if (previous) {
        previous.pause();
        previous.deactivateAudio();
    }
    window.__gd5_beepbox_failure = null;
    const data = JSON.parse(songJson);
    const engine = gd5SongEngine(data);
    if (data.format === "UltraBox") gd5BeginSampleLoad();
    const song = new engine.Song();
    song.fromJsonObject(data);
    const synth = new engine.Synth(song);
    window.__gd5_beepbox_synth = synth;
    window.__gd5_beepbox_pause_requested = false;
    window.__gd5_beepbox_speed = speed;
    window.__gd5_beepbox_volume = volume;
    synth.loopRepeatCount = 0;
    synth.gd5Position = startTime;
    synth.gd5Length = gd5SongLength(synth, window.__gd5_beepbox_output_rate);
    if (gd5IsUltraBox(synth)) {
        const synthesize = synth.synthesize.bind(synth);
        synth.synthesize = function(left, right, frames, playSong) {
            const playing = this.playing;
            synthesize(left, right, frames, playSong);
            if (playing) this.gd5Position = Math.min(this.gd5Length, this.gd5Position +
                frames / window.__gd5_beepbox_output_rate);
        };
    }
    const activateAudio = synth.activateAudio.bind(synth);
    const deactivateAudio = synth.deactivateAudio.bind(synth);
    synth.deactivateAudio = function() {
        const gain = window.__gd5_beepbox_gain;
        if (this.audioCtx && this.scriptNode && gain && gain.context === this.audioCtx) {
            // BeepBox's original teardown disconnects scriptNode directly from
            // the destination. Restore that edge before calling it, since GD5
            // routes playback through a GainNode for the music volume control.
            this.scriptNode.disconnect(gain);
            this.scriptNode.connect(this.audioCtx.destination);
        }
        deactivateAudio();
    };
    synth.activateAudio = function() {
        activateAudio();
        if (!this.audioCtx || !this.scriptNode) return;
        window.__gd5_beepbox_output_rate = this.audioCtx.sampleRate;
        this.samplesPerSecond = window.__gd5_beepbox_output_rate / window.__gd5_beepbox_speed;
        this.computeDelayBufferSizes();
        if (!window.__gd5_beepbox_gain ||
                window.__gd5_beepbox_gain.context !== this.audioCtx) {
            window.__gd5_beepbox_gain = this.audioCtx.createGain();
            this.scriptNode.disconnect();
            this.scriptNode.connect(window.__gd5_beepbox_gain);
            window.__gd5_beepbox_gain.connect(this.audioCtx.destination);
        }
        window.__gd5_beepbox_gain.gain.value = window.__gd5_beepbox_volume;
    };
    window.__gd5_beepbox_loading = true;
    function start() {
        if (window.__gd5_beepbox_synth !== synth) return;
        try {
            if (gd5IsUltraBox(synth) && !gd5SamplesReady()) {
                window.setTimeout(start, 20);
                return;
            }
            window.__gd5_beepbox_loading = false;
            synth.play();
            gd5ConfigureSynth(synth, window.__gd5_beepbox_output_rate,
                window.__gd5_beepbox_speed, synth.gd5Position);
            if (window.__gd5_beepbox_pause_requested) synth.pause();
        } catch (error) {
            window.__gd5_beepbox_loading = false;
            window.__gd5_beepbox_failure = String(error);
            synth.pause();
            synth.deactivateAudio();
        }
    }
    start();
};
window.__gd5_beepbox_pause = function(paused) {
    const synth = window.__gd5_beepbox_synth;
    if (!synth) return;
    window.__gd5_beepbox_pause_requested = !!paused;
    if (window.__gd5_beepbox_loading) return;
    if (paused) synth.pause(); else synth.play();
};
window.__gd5_beepbox_set_volume = function(volume) {
    window.__gd5_beepbox_volume = volume;
    if (window.__gd5_beepbox_gain) window.__gd5_beepbox_gain.gain.value = volume;
};
window.__gd5_beepbox_seek = function(position, speed) {
    const synth = window.__gd5_beepbox_synth;
    if (!synth) return;
    window.__gd5_beepbox_speed = speed;
    gd5ConfigureSynth(synth, window.__gd5_beepbox_output_rate, speed, position);
};
window.__gd5_beepbox_stop = function() {
    const synth = window.__gd5_beepbox_synth;
    if (!synth) return;
    synth.pause();
    synth.deactivateAudio();
    window.__gd5_beepbox_synth = null;
    window.__gd5_beepbox_gain = null;
};
"""
