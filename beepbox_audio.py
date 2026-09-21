"""BeepBox song playback for desktop and browser builds."""

import base64
import importlib
import json
import os
import queue
import threading


SAMPLE_RATE = 44100
# Keep synth calls short enough that the producer does not hold Python's GIL
# across a large fraction of an output buffer. Pygame consumes these blocks
# from its post-mix callback, so chunk boundaries are not playback boundaries.
CHUNK_FRAMES = 512
BUFFERED_CHUNKS = 64

_POST_MIX_LOCK = threading.Lock()
_POST_MIX_OWNER = None


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
    """QuickJS is needed only for native BeepBox rendering."""
    try:
        importlib.import_module("quickjs")
    except (ImportError, OSError):
        return False
    return True


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
    """Synthesize BeepBox JSON on a worker and mix PCM into Pygame's stream."""

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

        try:
            from pygame._sdl2.mixer import set_post_mix
        except ImportError as exc:
            raise RuntimeError(
                "BeepBox playback requires pygame-ce's post-mix audio callback"
            ) from exc

        self._set_post_mix = set_post_mix

        self.song_path = song_path
        self.volume = max(0.0, min(1.0, float(volume)))
        self.speed = max(0.25, min(2.0, float(speed)))
        self._position = max(0.0, float(start_time))
        self._length = 0.0
        self._generation = 0
        self._ready = queue.Queue(maxsize=BUFFERED_CHUNKS)
        self._commands = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._state_lock = threading.RLock()
        self._paused = False
        self._active = None
        self._active_offset = 0
        self._started = False
        self._mixed_frames = 0
        self._underrun_frames = 0
        self._worker_done_generation = -1
        self._worker_error = None
        self._worker = threading.Thread(
            target=self._produce, name="BeepBoxSynth", daemon=True
        )
        self._request_render(self._position, self.speed)
        self._post_mix_callback = self._mix_post_mix
        global _POST_MIX_OWNER
        with _POST_MIX_LOCK:
            if _POST_MIX_OWNER is not None:
                raise RuntimeError("A BeepBox audio stream is already active")
            self._set_post_mix(self._post_mix_callback)
            _POST_MIX_OWNER = self
        self._worker.start()

    @property
    def length(self):
        return self._length

    @property
    def position(self):
        with self._state_lock:
            return self._position

    @property
    def error(self):
        return self._worker_error

    @property
    def finished(self):
        with self._state_lock:
            return (self._worker_done_generation == self._generation
                    and self._active is None and self._ready.empty())

    def _produce(self):
        try:
            quickjs = importlib.import_module("quickjs")

            assets_dir = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(self.song_path)
            )))
            synth_path = os.path.join(assets_dir, "beepbox", "beepbox_synth.min.js")
            with open(synth_path, "r", encoding="utf-8") as source_file:
                source = source_file.read()
            with open(self.song_path, "r", encoding="utf-8") as song_file:
                song_json = song_file.read()

            context = quickjs.Context()
            context.eval(source)
            context.eval(_JS_BRIDGE)
            song_json_literal = json.dumps(song_json)
            generation = -1
            cursor = 0.0
            initialized = False

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
                result = context.eval(f"gd5Render({frames})")
                pcm_parts = json.loads(result.json())
                pcm = base64.b64decode("".join(pcm_parts))
                chunk = (generation, cursor, frames, pcm)
                while not self._stop_event.is_set() and generation == self._generation:
                    try:
                        self._ready.put(chunk, timeout=0.05)
                        cursor += frames / SAMPLE_RATE
                        break
                    except queue.Full:
                        # Keep this rendered PCM while waiting for playback;
                        # rendering it again wastes CPU and can starve playback.
                        continue
        except Exception as exc:
            self._worker_error = exc
            self._worker_done_generation = self._generation

    def update(self):
        """Keep the public stream interface aligned with the browser stream."""

    def _mix_post_mix(self, _post_mix, audio_buffer):
        """Add available BeepBox PCM to the live Pygame mixer output buffer."""
        if self._stop_event.is_set():
            return
        try:
            output = memoryview(audio_buffer).cast("h")
            with self._state_lock:
                if self._paused or self._stop_event.is_set():
                    return

                output_offset = 0
                volume = self.volume
                while output_offset < len(output):
                    if self._active is None:
                        self._active = self._next_current_chunk()
                        self._active_offset = 0
                    if self._active is None:
                        break

                    _generation, start, frames, pcm = self._active
                    source = memoryview(pcm).cast("h")
                    available = len(source) - self._active_offset
                    count = min(available, len(output) - output_offset)
                    for index in range(count):
                        sample = int(source[self._active_offset + index] * volume)
                        mixed = output[output_offset + index] + sample
                        output[output_offset + index] = max(-32768, min(32767, mixed))

                    output_offset += count
                    self._active_offset += count
                    self._position = start + self._active_offset / (SAMPLE_RATE * 2)
                    if self._active_offset >= len(source):
                        self._active = None
                        self._active_offset = 0

                if output_offset:
                    self._started = True
                    self._mixed_frames += output_offset // 2
                missing_samples = len(output) - output_offset
                if (missing_samples and self._started
                        and self._worker_done_generation != self._generation):
                    self._underrun_frames += missing_samples // 2
        except Exception as exc:
            # Pygame reports but suppresses exceptions from this audio-thread
            # callback, so retain failures for the controller's normal fallback.
            self._worker_error = exc

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
            self._paused = bool(paused)

    def set_volume(self, volume):
        with self._state_lock:
            self.volume = max(0.0, min(1.0, float(volume)))

    def seek(self, position, speed=None):
        with self._state_lock:
            self._position = max(0.0, float(position))
            if speed is not None:
                self.speed = max(0.25, min(2.0, float(speed)))
            self._generation += 1
            self._active = None
            self._active_offset = 0
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

    def stop(self):
        self._stop_event.set()
        global _POST_MIX_OWNER
        with _POST_MIX_LOCK:
            if _POST_MIX_OWNER is self:
                self._set_post_mix(None)
                _POST_MIX_OWNER = None
        self._worker.join(timeout=0.5)


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
    return parts;
};
"""


_WEB_JS_BRIDGE = r"""
window.__gd5_beepbox_synth = null;
window.__gd5_beepbox_gain = null;
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
    return !!synth && synth.playhead >= synth.song.barCount;
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
