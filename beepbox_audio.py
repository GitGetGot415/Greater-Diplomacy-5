"""BeepBox song playback for desktop and browser builds."""

import base64
from contextlib import contextmanager
import importlib
import json
import os
import queue
import threading
import time

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


def is_beepbox_song(path):
    """Return whether *path* contains a BeepBox song object we can synthesize."""
    if not path.lower().endswith(".json"):
        return False
    try:
        with open(path, "r", encoding="utf-8") as song_file:
            song = json.load(song_file)
        return song.get("format") == "BeepBox" and isinstance(song.get("channels"), list)
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
        return False


def is_available():
    """Return whether the real-time-capable native BeepBox runtime is available.

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
            "BeepBox desktop playback requires the bundled V8 runtime "
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


def _drain(q):
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


class BeepBoxStream:
    """Synthesize BeepBox JSON incrementally into native SDL_mixer blocks.

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
            assets_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(self.song_path)
            )))
            synth_path = os.path.join(assets_dir, "beepbox", "beepbox_synth.min.js")
            with open(synth_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            with open(self.song_path, "r", encoding="utf-8") as song_file:
                song_json = song_file.read()

            with _native_js_context() as (context, self._engine_name):
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
    """Play a BeepBox song through the vendor synth's browser Web Audio API."""

    def __init__(self, song_path, volume=1.0, speed=1.0, start_time=0.0):
        import platform

        self._window = platform.window
        self.song_path = song_path
        self.volume = max(0.0, min(1.0, float(volume)))
        self.speed = max(0.25, min(2.0, float(speed)))
        self._error = None
        self._stopped = False

        assets_dir = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(song_path)
        )))
        synth_path = os.path.join(assets_dir, "beepbox", "beepbox_synth.min.js")
        with open(synth_path, "r", encoding="utf-8") as source_file:
            synth_source = source_file.read()
        with open(song_path, "r", encoding="utf-8") as song_file:
            song_json = song_file.read()

        # The bridge and vendor bundle are evaluated once per page. The synth's
        # own activateAudio() method creates/resumes AudioContext on the user's
        # first input event, which is where the controller starts this stream.
        if not getattr(self._window, "__gd5_beepbox_ready", False):
            self._window.eval(synth_source)
            self._window.eval(_WEB_JS_BRIDGE)
            setattr(self._window, "__gd5_beepbox_ready", True)

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


_JS_BRIDGE = r"""
globalThis.gd5Synth = null;
globalThis.gd5Length = 0;
globalThis.gd5OutputRate = 44100;
globalThis.gd5Init = function(songJson, outputRate, speed, seekSeconds) {
    const song = new beepbox.Song();
    song.fromJsonObject(JSON.parse(songJson));
    const synth = new beepbox.Synth(song);
    synth.samplesPerSecond = outputRate / speed;
    synth.computeDelayBufferSizes();
    synth.loopRepeatCount = 0;
    synth.playhead = seekSeconds * outputRate / synth.getSamplesPerBar();
    synth.resetEffects();
    gd5OutputRate = outputRate;
    gd5Synth = synth;
    gd5Length = song.barCount * synth.getSamplesPerBar() / outputRate;
    return JSON.stringify({length: gd5Length});
};
globalThis.gd5Seek = function(seekSeconds, speed) {
    if (!gd5Synth) return JSON.stringify({length: 0});
    gd5Synth.samplesPerSecond = gd5OutputRate / speed;
    gd5Synth.computeDelayBufferSizes();
    gd5Synth.playhead = seekSeconds * gd5OutputRate / gd5Synth.getSamplesPerBar();
    gd5Synth.resetEffects();
    gd5Length = gd5Synth.song.barCount * gd5Synth.getSamplesPerBar() / gd5OutputRate;
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


_WEB_JS_BRIDGE = r"""
window.__gd5_beepbox_synth = null;
window.__gd5_beepbox_gain = null;
window.__gd5_beepbox_pause_requested = false;
window.__gd5_beepbox_speed = 1;
window.__gd5_beepbox_volume = 1;
window.__gd5_beepbox_output_rate = 44100;
window.__gd5_beepbox_length = function() {
    const synth = window.__gd5_beepbox_synth;
    return synth ? synth.song.barCount * synth.getSamplesPerBar() / window.__gd5_beepbox_output_rate : 0;
};
window.__gd5_beepbox_position = function() {
    const synth = window.__gd5_beepbox_synth;
    return synth ? synth.playhead * synth.getSamplesPerBar() / window.__gd5_beepbox_output_rate : 0;
};
window.__gd5_beepbox_finished = function() {
    const synth = window.__gd5_beepbox_synth;
    // BeepBox pauses and wraps its playhead to bar 0 when a non-looping song
    // ends, so the playhead never remains at barCount for the bridge to poll.
    // A separate flag keeps an intentional user pause from looking like EOF.
    return !!synth && !synth.playing && !window.__gd5_beepbox_pause_requested;
};
window.__gd5_beepbox_load = function(songJson, speed, startTime, volume) {
    const previous = window.__gd5_beepbox_synth;
    if (previous) {
        previous.pause();
        previous.deactivateAudio();
    }
    const song = new beepbox.Song();
    song.fromJsonObject(JSON.parse(songJson));
    const synth = new beepbox.Synth(song);
    window.__gd5_beepbox_synth = synth;
    window.__gd5_beepbox_pause_requested = false;
    window.__gd5_beepbox_speed = speed;
    window.__gd5_beepbox_volume = volume;
    synth.loopRepeatCount = 0;
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
    synth.play();
    synth.playhead = startTime * window.__gd5_beepbox_output_rate / synth.getSamplesPerBar();
    synth.resetEffects();
};
window.__gd5_beepbox_pause = function(paused) {
    const synth = window.__gd5_beepbox_synth;
    if (!synth) return;
    window.__gd5_beepbox_pause_requested = !!paused;
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
    synth.samplesPerSecond = window.__gd5_beepbox_output_rate / speed;
    synth.computeDelayBufferSizes();
    synth.playhead = position * window.__gd5_beepbox_output_rate / synth.getSamplesPerBar();
    synth.resetEffects();
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
