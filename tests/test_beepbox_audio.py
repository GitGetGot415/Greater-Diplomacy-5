import base64
import json
import os
import subprocess
import sys
import unittest

from beepbox_audio import (
    _JS_BRIDGE,
    _WEB_JS_BRIDGE,
    BeepBoxStream,
    has_beepbox_replacement,
    is_available,
    is_beepbox_song,
)
from compilation_scripts.html_compilation import _ignore_web_asset
from data.constants import CREDITS_DATA


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SONG_PATH = os.path.join(ROOT, "assets", "music", "Greater Diplomacy 5", "Dschungel.json")
SYNTH_PATH = os.path.join(ROOT, "assets", "beepbox", "beepbox_synth.min.js")
RUN_NATIVE_AUDIO_TESTS = os.environ.get("GD5_RUN_NATIVE_AUDIO_TESTS") == "1"


def _native_audio_tests_available():
    return RUN_NATIVE_AUDIO_TESTS and is_available()


def _disable_windows_native_error_dialogs():
    """Keep a crashing native test child from blocking the test runner.

    The child still exits nonzero and the parent reports that failure. This
    only prevents Windows from opening a modal Application Error dialog when a
    native audio dependency aborts.
    """
    if sys.platform != "win32":
        return
    import ctypes

    sem_fail_critical_errors = 0x0001
    sem_no_gp_fault_errorbox = 0x0002
    sem_no_open_file_errorbox = 0x8000
    ctypes.windll.kernel32.SetErrorMode(
        sem_fail_critical_errors
        | sem_no_gp_fault_errorbox
        | sem_no_open_file_errorbox
    )


class BeepBoxAudioTests(unittest.TestCase):
    def test_added_song_is_recognized_and_upstream_license_is_shipped(self):
        self.assertTrue(is_beepbox_song(SONG_PATH))
        self.assertTrue(has_beepbox_replacement(os.path.splitext(SONG_PATH)[0] + ".mp3"))
        with open(os.path.join(ROOT, "assets", "beepbox", "LICENSE.md"), encoding="utf-8") as license_file:
            license_text = license_file.read()
        self.assertIn("MIT License", license_text)
        self.assertTrue(os.path.isfile(SYNTH_PATH))
        tools = next(section for section in CREDITS_DATA if section["main_text"] == "Tools: ")
        self.assertTrue(any(person.get("link_text") == "BeepBox" for person in tools["people"]))

    def test_embedded_v8_licenses_are_shipped(self):
        with open(os.path.join(ROOT, "assets", "mini_racer", "LICENSES.txt"),
                  encoding="utf-8") as license_file:
            licenses = license_file.read()
        self.assertIn("PyMiniRacer", licenses)
        self.assertIn("V8 JavaScript Engine", licenses)

    def test_web_build_stages_synth_and_song_but_drops_matching_audio(self):
        song_mp3 = os.path.splitext(SONG_PATH)[0] + ".mp3"
        self.assertFalse(_ignore_web_asset(SONG_PATH))
        self.assertFalse(_ignore_web_asset(SYNTH_PATH))
        self.assertTrue(_ignore_web_asset(song_mp3))

    @unittest.skipUnless(is_available(), "native QuickJS dependency is not installed")
    def test_beepbox_source_synthesizes_pcm_from_the_song_json(self):
        import importlib

        quickjs = importlib.import_module("quickjs")
        with open(SONG_PATH, encoding="utf-8") as song_file:
            song_json = song_file.read()
        with open(SYNTH_PATH, encoding="utf-8") as source_file:
            synth_source = source_file.read()

        context = quickjs.Context()
        context.eval(synth_source)
        context.eval(_JS_BRIDGE)
        init_result = context.eval(
            f"gd5Init({json.dumps(song_json)}, 44100, 1, 0)"
        )
        self.assertGreater(json.loads(init_result)["length"], 0)
        context.eval(f"gd5Init({json.dumps(song_json)}, 44100, 1, 10)")
        self.assertAlmostEqual(context.eval("gd5Synth.playhead"), 5.0, places=4)

        encoded_pcm = context.eval("gd5Render(2048)")
        pcm = base64.b64decode(encoded_pcm)
        self.assertEqual(len(pcm), 2048 * 2 * 2)
        self.assertTrue(any(pcm), "the synthesized song should contain audible samples")

        normal_length = json.loads(
            context.eval(f"gd5Init({json.dumps(song_json)}, 44100, 1, 0)")
        )["length"]
        fast_length = json.loads(
            context.eval(f"gd5Init({json.dumps(song_json)}, 44100, 1.5, 0)")
        )["length"]
        self.assertAlmostEqual(fast_length, normal_length / 1.5, places=3)
        context.eval(f"gd5Init({json.dumps(song_json)}, 44100, 1.5, 10)")
        self.assertAlmostEqual(context.eval("gd5Synth.playhead"), 7.5, places=4)
        context.eval("gd5Seek(12, 1.5)")
        self.assertAlmostEqual(context.eval("gd5Synth.playhead"), 9.0, places=4)
        self.assertAlmostEqual(
            json.loads(context.eval("JSON.stringify({length: gd5Length})"))["length"],
            fast_length,
            places=3,
        )

    @unittest.skipUnless(is_available(), "native QuickJS dependency is not installed")
    def test_browser_bridge_uses_web_audio_and_supports_controls(self):
        import importlib

        quickjs = importlib.import_module("quickjs")
        with open(SONG_PATH, encoding="utf-8") as song_file:
            song_json = song_file.read()
        with open(SYNTH_PATH, encoding="utf-8") as source_file:
            synth_source = source_file.read()

        context = quickjs.Context()
        context.eval(r"""
            globalThis.window = globalThis;
            globalThis.performance = {now: function() { return 0; }};
            globalThis.AudioContext = class {
                constructor() { this.sampleRate = 44100; this.destination = {}; }
                createScriptProcessor(size) {
                    const connections = [];
                    return {
                        bufferSize: size,
                        connect: function(node) { connections.push(node); },
                        disconnect: function(node) {
                            if (arguments.length === 0) { connections.length = 0; return; }
                            const index = connections.indexOf(node);
                            if (index < 0) throw new Error("node is not connected");
                            connections.splice(index, 1);
                        },
                    };
                }
                createGain() {
                    return {context: this, gain: {value: 1}, connect: function() {}};
                }
                resume() {}
                close() {}
            };
        """)
        context.eval(synth_source)
        context.eval(_WEB_JS_BRIDGE)
        context.eval(
            f"window.__gd5_beepbox_load({json.dumps(song_json)}, 1, 2.5, 0.4)"
        )
        self.assertAlmostEqual(context.eval("window.__gd5_beepbox_position()"), 2.5, places=3)
        normal_length = context.eval("window.__gd5_beepbox_length()")
        self.assertGreater(normal_length, 2.5)

        context.eval("window.__gd5_beepbox_pause(true)")
        self.assertFalse(context.eval("window.__gd5_beepbox_synth.playing"))
        self.assertFalse(context.eval("window.__gd5_beepbox_finished()"))
        context.eval(r"""
            const synth = window.__gd5_beepbox_synth;
            const left = new Float32Array(128);
            const right = new Float32Array(128);
            synth.audioProcessCallback({outputBuffer: {
                length: 128,
                getChannelData: function(channel) { return channel === 0 ? left : right; }
            }});
        """)
        self.assertTrue(context.eval("window.__gd5_beepbox_synth.audioCtx === null"))
        context.eval("window.__gd5_beepbox_pause(false)")
        self.assertTrue(context.eval("window.__gd5_beepbox_synth.playing"))
        self.assertTrue(context.eval("window.__gd5_beepbox_synth.audioCtx !== null"))
        context.eval("window.__gd5_beepbox_set_volume(0.25)")
        self.assertAlmostEqual(context.eval("window.__gd5_beepbox_gain.gain.value"), 0.25)

        context.eval("window.__gd5_beepbox_seek(10, 1.5)")
        self.assertAlmostEqual(context.eval("window.__gd5_beepbox_position()"), 10, places=3)
        self.assertAlmostEqual(
            context.eval("window.__gd5_beepbox_length()"), normal_length / 1.5, places=3
        )

        # The vendor synth pauses and wraps its playhead when it crosses the
        # final bar. The bridge must still expose that as EOF for auto-advance.
        context.eval(r"""
            {
            const endingSynth = window.__gd5_beepbox_synth;
            endingSynth.playhead = endingSynth.song.barCount - 0.000001;
            const left = new Float32Array(4096);
            const right = new Float32Array(4096);
            endingSynth.synthesize(left, right, 4096, true);
            }
        """)
        self.assertFalse(context.eval("window.__gd5_beepbox_synth.playing"))
        self.assertTrue(context.eval("window.__gd5_beepbox_finished()"))

        context.eval("window.__gd5_beepbox_stop()")
        self.assertEqual(context.eval("window.__gd5_beepbox_length()"), 0)

    @unittest.skipUnless(
        _native_audio_tests_available(),
        "set GD5_RUN_NATIVE_AUDIO_TESTS=1 to run native audio integration tests",
    )
    def test_pygame_native_stream_supports_play_pause_and_seek_without_underruns(self):
        script = r"""
import sys
import time
from tests.test_beepbox_audio import _disable_windows_native_error_dialogs
_disable_windows_native_error_dialogs()
import pygame
from beepbox_audio import BeepBoxStream

pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
stream = BeepBoxStream(sys.argv[1], volume=0.0)
try:
    deadline = time.monotonic() + 8
    while stream.position < 0.1 and stream.error is None and time.monotonic() < deadline:
        stream.update()
        time.sleep(0.02)
    assert stream.error is None, stream.error
    assert stream._mixed_frames > 0
    assert stream._engine_name == "v8"
    assert stream.position >= 0.1
    normal_length = stream.length

    # SDL may briefly keep reporting a stopped block as busy. Repeated seeks
    # during playback must start both the new audio and its visual position
    # clock instead of queuing behind that stale status.
    for target in (20.0, 40.0, 60.0):
        stream.seek(target)
        seek_deadline = time.monotonic() + 3
        while (stream.position < target + 0.1 and stream.error is None
               and time.monotonic() < seek_deadline):
            stream.update()
            time.sleep(0.005)
        assert stream.error is None, stream.error
        assert stream.position >= target + 0.1, (
            f"visual position froze at {stream.position} after seeking to {target}"
        )

    stream.pause(True)
    paused_at = stream.position
    time.sleep(0.08)
    assert abs(stream.position - paused_at) < 0.03

    stream.seek(4.0)
    stream.seek(8.0)
    stream.seek(12.0, speed=1.5)
    deadline = time.monotonic() + 8
    while (stream.length >= normal_length and stream.error is None
           and time.monotonic() < deadline):
        stream.update()
        time.sleep(0.02)
    assert abs(stream.position - 12.0) < 0.01
    stream.pause(False)
    while stream.position < 12.1 and stream.error is None and time.monotonic() < deadline:
        stream.update()
        time.sleep(0.02)
    assert stream.error is None, stream.error
    assert stream.length < normal_length
    assert stream.position >= 12.1

    # Two native blocks should keep playing after the seek even when the game
    # loop does not pump another block for more than one block duration.
    with stream._state_lock:
        underruns_before = stream._underrun_frames
    playback_deadline = time.monotonic() + 0.6
    while time.monotonic() < playback_deadline:
        assert stream.error is None, stream.error
        time.sleep(0.005)
    with stream._state_lock:
        underruns_after = stream._underrun_frames
    assert underruns_after == underruns_before, (
        f"Pygame native stream underruns: "
        f"{underruns_after - underruns_before} frames"
    )
finally:
    stream.stop(wait=True)
    pygame.mixer.quit()
"""
        environment = os.environ.copy()
        environment["SDL_AUDIODRIVER"] = "dummy"
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script, SONG_PATH],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(
        _native_audio_tests_available(),
        "set GD5_RUN_NATIVE_AUDIO_TESTS=1 to run native audio integration tests",
    )
    def test_rapid_track_switching_keeps_the_latest_stream_playing(self):
        script = r"""
import sys
import time
from tests.test_beepbox_audio import _disable_windows_native_error_dialogs
_disable_windows_native_error_dialogs()
import pygame
from beepbox_audio import BeepBoxStream

pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
stream = None
try:
    for song_path in sys.argv[1:]:
        if stream is not None:
            stream.stop(wait=True)
        stream = BeepBoxStream(song_path, volume=0.0)

    deadline = time.monotonic() + 8
    while stream.position < 0.1 and stream.error is None and time.monotonic() < deadline:
        stream.update()
        time.sleep(0.01)
    assert stream.error is None, stream.error
    assert stream.position >= 0.1
finally:
    if stream is not None:
        stream.stop(wait=True)
    pygame.mixer.quit()
"""
        environment = os.environ.copy()
        environment["SDL_AUDIODRIVER"] = "dummy"
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script,
             SONG_PATH,
             os.path.join(ROOT, "assets", "music", "Greater Diplomacy 5", "Under the Rainbow Redux.json"),
             SONG_PATH,
             os.path.join(ROOT, "assets", "music", "Experimental", "Sensory Overload Rainbow.json"),
             SONG_PATH],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(
        _native_audio_tests_available(),
        "set GD5_RUN_NATIVE_AUDIO_TESTS=1 to run native audio integration tests",
    )
    def test_v8_playback_stays_ahead_in_reported_late_song_sections(self):
        script = r"""
import sys
import time
from tests.test_beepbox_audio import _disable_windows_native_error_dialogs
_disable_windows_native_error_dialogs()
import pygame
from beepbox_audio import BeepBoxStream

pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
for song_path, target in ((sys.argv[1], 247.0), (sys.argv[2], 173.0)):
    stream = BeepBoxStream(song_path, volume=0.0)
    try:
        deadline = time.monotonic() + 10
        while stream.length <= 0 and stream.error is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert stream.error is None, stream.error
        assert stream._engine_name == "v8"

        stream.pause(True)
        stream.seek(target)
        deadline = time.monotonic() + 10
        while stream._ready.qsize() < 8 and stream.error is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert stream.error is None, stream.error
        stream.pause(False)
        while stream.position < target + 0.2 and stream.error is None and time.monotonic() < deadline:
            stream.update()
            time.sleep(0.01)
        assert stream.error is None, stream.error
        assert stream.position >= target + 0.2

        with stream._state_lock:
            underruns_before = stream._underrun_frames
        time.sleep(1.0)
        with stream._state_lock:
            underruns_after = stream._underrun_frames
        assert underruns_after == underruns_before, (
            f"{song_path} underruns at {target}s: "
            f"{underruns_after - underruns_before} frames"
        )
    finally:
        stream.stop(wait=True)
pygame.mixer.quit()
"""
        environment = os.environ.copy()
        environment["SDL_AUDIODRIVER"] = "dummy"
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script,
             os.path.join(ROOT, "assets", "music", "Greater Diplomacy 5", "Under the Rainbow Redux.json"),
             SONG_PATH],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(
        _native_audio_tests_available(),
        "set GD5_RUN_NATIVE_AUDIO_TESTS=1 to run native audio integration tests",
    )
    def test_native_stream_keeps_time_during_heavy_python_turn_work(self):
        script = r"""
import sys
import threading
import time
from tests.test_beepbox_audio import _disable_windows_native_error_dialogs
_disable_windows_native_error_dialogs()
import pygame
from beepbox_audio import BeepBoxStream

pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
stream = BeepBoxStream(sys.argv[1], volume=0.0)
try:
    deadline = time.monotonic() + 8
    while stream.position < 0.2 and stream.error is None and time.monotonic() < deadline:
        stream.update()
        time.sleep(0.005)
    assert stream.error is None, stream.error
    assert stream.position >= 0.2

    position_before = stream.position
    started_at = time.monotonic()
    load_ends_at = started_at + 3.0

    def simulate_heavy_turn():
        value = 1
        while time.monotonic() < load_ends_at:
            for _ in range(200000):
                value = (value * 1664525 + 1013904223) & 0xffffffff

    worker = threading.Thread(target=simulate_heavy_turn)
    worker.start()
    while worker.is_alive():
        # The actual controller continues drawing its loading screen and calls
        # update once per frame while turn resolution runs on its worker.
        stream.update()
        time.sleep(0.02)
    worker.join()
    stream.update()

    wall_time = time.monotonic() - started_at
    music_time = stream.position - position_before
    assert stream.error is None, stream.error
    assert stream._underrun_frames == 0, stream._underrun_frames
    assert wall_time - 0.25 <= music_time <= wall_time + 0.25, (
        f"music advanced {music_time:.3f}s during {wall_time:.3f}s of turn work"
    )
finally:
    stream.stop(wait=True)
    pygame.mixer.quit()
"""
        environment = os.environ.copy()
        environment["SDL_AUDIODRIVER"] = "dummy"
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script, SONG_PATH],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
