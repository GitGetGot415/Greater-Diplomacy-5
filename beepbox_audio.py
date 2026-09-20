"""Buffered native playback for songs saved in BeepBox's JSON format."""

import base64
import importlib
import json
import os
import queue
import threading
import time


SAMPLE_RATE = 44100
CHUNK_FRAMES = 44100  # One second keeps channel handoffs infrequent.
BUFFERED_CHUNKS = 4


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
    """Synthesize BeepBox JSON on a worker and feed PCM chunks to a Pygame channel."""

    def __init__(self, song_path, volume=1.0, speed=1.0, start_time=0.0):
        import pygame
        import threading

        mixer_format = pygame.mixer.get_init()
        if mixer_format is None:
            pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2, buffer=1024)
            mixer_format = pygame.mixer.get_init()
        if mixer_format != (SAMPLE_RATE, -16, 2):
            raise RuntimeError(
                "BeepBox playback needs a 44100 Hz, signed 16-bit stereo Pygame mixer"
            )

        self._pygame = pygame
        self._channel = pygame.mixer.Channel(0)
        pygame.mixer.set_reserved(1)
        self._channel.stop()
        self._channel.set_volume(volume)

        self.song_path = song_path
        self.volume = volume
        self.speed = max(0.25, min(2.0, float(speed)))
        self._position = max(0.0, float(start_time))
        self._length = 0.0
        self._generation = 0
        self._ready = queue.Queue(maxsize=BUFFERED_CHUNKS)
        self._commands = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._paused = False
        self._active = None
        self._queued = None
        self._active_started_at = None
        self._active_elapsed = 0.0
        self._worker_done_generation = -1
        self._worker_error = None
        self._worker = threading.Thread(
            target=self._produce, name="BeepBoxSynth", daemon=True
        )
        self._request_render(self._position, self.speed)
        self._worker.start()

    @property
    def length(self):
        return self._length

    @property
    def position(self):
        if self._active is not None:
            _, start, frames, _sound = self._active
            elapsed = self._active_elapsed
            if not self._paused and self._active_started_at is not None:
                elapsed += max(0.0, time.monotonic() - self._active_started_at)
            self._position = start + min(elapsed, frames / SAMPLE_RATE)
        return self._position

    @property
    def error(self):
        return self._worker_error

    @property
    def finished(self):
        if self._worker_done_generation != self._generation:
            return False
        self.update()
        return (not self._channel.get_busy() and self._active is None
                and self._queued is None and self._ready.empty())

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

            while not self._stop_event.is_set():
                try:
                    generation, cursor, speed = self._commands.get(timeout=0.01)
                    initialized = json.loads(context.eval(
                        f"gd5Init({song_json_literal}, {SAMPLE_RATE}, {speed}, {cursor})"
                    ))
                    self._length = initialized["length"]
                    self._worker_done_generation = -1
                except queue.Empty:
                    if generation < 0:
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
                if generation != self._generation:
                    continue
                try:
                    self._ready.put(chunk, timeout=0.05)
                    cursor += frames / SAMPLE_RATE
                except queue.Full:
                    # Let control requests pre-empt a full playback buffer.
                    continue
        except Exception as exc:
            self._worker_error = exc
            self._worker_done_generation = self._generation

    def update(self):
        """Start and queue synthesized buffers on the dedicated channel."""
        channel_busy = self._channel.get_busy()
        if (self._queued is not None and channel_busy
                and self._channel.get_queue() is None):
            if self._active is not None and self._active_started_at is not None:
                remaining = max(
                    0.0,
                    self._active[2] / SAMPLE_RATE - self._active_elapsed,
                )
                self._active_started_at += remaining
            else:
                self._active_started_at = time.monotonic()
            self._active = self._queued
            self._queued = None
            self._active_elapsed = 0.0

        if channel_busy:
            if self._queued is None:
                chunk = self._next_current_chunk()
                if chunk is not None:
                    sound = self._pygame.mixer.Sound(buffer=chunk[3])
                    self._channel.queue(sound)
                    self._queued = (chunk[0], chunk[1], chunk[2], sound)
        else:
            if self._queued is not None:
                self._position = self._queued[1] + self._queued[2] / SAMPLE_RATE
            elif self._active is not None:
                self._position = self.position
            self._active = None
            self._queued = None
            self._active_started_at = None
            self._active_elapsed = 0.0
            chunk = self._next_current_chunk()
            if chunk is not None:
                sound = self._pygame.mixer.Sound(buffer=chunk[3])
                self._channel.play(sound)
                self._active_started_at = time.monotonic()
                if self._paused:
                    self._channel.pause()
                self._active = (chunk[0], chunk[1], chunk[2], sound)

    def _next_current_chunk(self):
        while True:
            try:
                chunk = self._ready.get_nowait()
            except queue.Empty:
                return None
            if chunk[0] == self._generation:
                return chunk

    def pause(self, paused):
        paused = bool(paused)
        if paused and not self._paused:
            if self._active is not None and self._active_started_at is not None:
                self._active_elapsed += max(0.0, time.monotonic() - self._active_started_at)
                self._active_started_at = None
            self._channel.pause()
        elif not paused and self._paused:
            if self._active is not None:
                self._active_started_at = time.monotonic()
            self._channel.unpause()
        self._paused = paused

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, float(volume)))
        self._channel.set_volume(self.volume)

    def seek(self, position, speed=None):
        self._position = max(0.0, float(position))
        if speed is not None:
            self.speed = max(0.25, min(2.0, float(speed)))
        self._generation += 1
        self._active = None
        self._queued = None
        self._active_started_at = None
        self._active_elapsed = 0.0
        self._channel.stop()
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
        self._channel.stop()
        self._worker.join(timeout=0.05)


_JS_BRIDGE = r"""
globalThis.gd5Synth = null;
globalThis.gd5Length = 0;
globalThis.gd5Init = function(songJson, outputRate, speed, seekSeconds) {
    const song = new beepbox.Song();
    song.fromJsonObject(JSON.parse(songJson));
    const synth = new beepbox.Synth(song);
    synth.samplesPerSecond = outputRate / speed;
    synth.computeDelayBufferSizes();
    synth.loopRepeatCount = 0;
    synth.playhead = seekSeconds * outputRate / synth.getSamplesPerBar();
    synth.resetEffects();
    gd5Synth = synth;
    gd5Length = song.barCount * synth.getSamplesPerBar() / outputRate;
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
