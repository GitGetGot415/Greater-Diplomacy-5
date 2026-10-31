import base64
import copy
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from beepbox_audio import (
    _JS_BRIDGE, _WEB_JS_BRIDGE, _native_sample_data, _read_song, _synth_source,
    is_beepbox_song, has_beepbox_replacement,
)
from compilation_scripts import build_support


ROOT = Path(__file__).resolve().parent.parent


def sample_wav():
    # An artificial square wave makes silent or substituted samples detectable.
    import wave

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(bytes([32] * 16 + [224] * 16) * 32)
    return output.getvalue()


def song_fixture():
    encoded = base64.b64encode(sample_wav()).decode("ascii")
    return {
        "format": "UltraBox", "version": 5, "scale": "free", "key": "C",
        "beatsPerMinute": 120, "beatsPerBar": 4, "ticksPerBeat": 24,
        "introBars": 0, "loopBars": 2, "patternInstruments": True,
        "customSamples": ["!s8000,r60!data:audio/wav;base64," + encoded + "/tone.wav"],
        "channels": [{
            "type": "pitch", "sequence": [1, 1],
            "instruments": [{"type": "chip", "wave": "tone.wav", "volume": 0,
                             "effects": [], "eqFilter": [], "envelopes": [],
                             "fadeInSeconds": 0, "fadeOutTicks": -3,
                             "unison": "none", "chord": "simultaneous"}],
            "patterns": [{"instruments": [1], "notes": [{"pitches": [60], "points": [
                {"tick": 0, "volume": 100}, {"tick": 96, "volume": 100},
            ]}]}],
        }],
    }


class UltraBoxFileTests(unittest.TestCase):
    def test_detection_and_packaging_accept_both_formats_and_reject_other_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary, "track.json")
            for format_name, channels, expected in (
                ("UltraBox", [], True), ("BeepBox", [], True),
                ("Other", [], False), ("UltraBox", {}, False),
                ([], [], False), ({}, [], False),
            ):
                with self.subTest(format=format_name, channels=channels):
                    path.write_text(json.dumps({"format": format_name, "channels": channels}), encoding="utf-8-sig")
                    self.assertEqual(is_beepbox_song(str(path)), expected)
                    self.assertEqual(has_beepbox_replacement(str(path.with_suffix(".ogg"))), expected)

    def test_local_server_samples_can_use_companion_files_without_a_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            samples = directory / "track.samples"
            samples.mkdir()
            (samples / "tone.wav").write_bytes(sample_wav())
            song = song_fixture()
            song["customSamples"] = ["!s8000,r60!http://127.0.0.1:8765/track.samples/tone.wav"]
            path = directory / "track.json"
            path.write_text(json.dumps(song))
            loaded = _read_song(str(path))
            self.assertIn("data:audio/wav;base64,", loaded["customSamples"][0])
            self.assertTrue(loaded["customSamples"][0].endswith("/tone.wav"))
            self.assertEqual(len(_native_sample_data(loaded)), 1)
            self.assertEqual(json.loads(path.read_text()), song)

    def test_invalid_samples_report_an_actionable_error(self):
        song = song_fixture()
        song["customSamples"] = ["!s8000!data:audio/wav;base64,bm90LWF1ZGlv"]
        with self.assertRaisesRegex(ValueError, "Supply its sample file or embed it"):
            _native_sample_data(song)

    def test_all_platforms_include_ultrabox_runtime_assets(self):
        files = [ROOT / "assets/ultrabox" / name for name in (
            "ultrabox_synth.min.js", "gd5_adapter.js", "LICENSE.md",
        )]
        for platform in ("windows", "macos", "web"):
            for path in files:
                with self.subTest(platform=platform, path=path.name):
                    self.assertTrue(path.is_file())
                    self.assertTrue(build_support.include_asset(path, platform))

    def test_synth_loading_uses_the_asset_root_when_modules_are_frozen(self):
        with patch("beepbox_audio.__file__", "missing/python313.zip/beepbox_audio.pyc"):
            for format_name in ("UltraBox", "BeepBox"):
                with self.subTest(format=format_name):
                    self.assertTrue(_synth_source({"format": format_name}))


@unittest.skipUnless(importlib.util.find_spec("quickjs"), "QuickJS is not installed")
class UltraBoxSynthTests(unittest.TestCase):
    def make_context(self, song=None):
        # QuickJS stays a test dependency. Desktop playback uses V8.
        import quickjs

        song = song or song_fixture()
        context = quickjs.Context()
        context.eval("globalThis.gd5NativeSamples = " + json.dumps(_native_sample_data(song)))
        context.eval(_synth_source(song))
        context.eval(_JS_BRIDGE)
        return context, song

    def initialize(self, context, song, seconds=0, speed=1):
        result = context.eval(f"gd5Init({json.dumps(json.dumps(song))},44100,{speed},{seconds})")
        while context.execute_pending_job():
            pass
        self.assertTrue(context.eval("gd5SamplesReady()"))
        return json.loads(result)["length"]

    def test_embedded_sample_synthesizes_and_supports_seeking_and_speed(self):
        context, song = self.make_context()
        length = self.initialize(context, song)
        self.assertAlmostEqual(length, 4)
        self.assertTrue(context.eval("gd5Synth instanceof gd5UltraBox.Synth"))
        self.assertEqual(context.eval("gd5UltraBox.Config.rawRawChipWaves.slice(-1)[0].samples.length"), 1025)
        pcm = base64.b64decode(context.eval("gd5Render(2048)"))
        self.assertEqual(len(pcm), 8192)
        self.assertTrue(any(pcm))
        self.assertAlmostEqual(json.loads(context.eval("gd5Seek(1,2)"))["length"], length / 2)
        self.assertAlmostEqual(context.eval("gd5Synth.playhead"), 1, places=4)

    def test_tempo_ramp_and_shortened_bar_control_duration_and_seek(self):
        context, song = self.make_context()
        config = json.loads(context.eval("JSON.stringify({count:gd5UltraBox.Config.modCount,"
                                        "tempo:gd5UltraBox.Config.modulators.dictionary.tempo,"
                                        "next:gd5UltraBox.Config.modulators.dictionary['next bar']})"))
        count = config["count"]
        settings = [0] * count
        settings[0], settings[1] = config["tempo"]["index"], config["next"]["index"]
        factor = config["tempo"]["convertRealFactor"]
        song["channels"].append({
            "type": "mod", "sequence": [1, 0],
            "instruments": [{"type": "mod", "modChannels": [-1] * count,
                             "modInstruments": [0] * count, "modSettings": settings}],
            "patterns": [{"instruments": [1], "notes": [
                {"pitches": [count - 1], "points": [
                    {"tick": 0, "volume": 120 - factor, "forMod": True},
                    {"tick": 48, "volume": 240 - factor, "forMod": True},
                ]},
                {"pitches": [count - 2], "points": [
                    {"tick": 48, "volume": 1, "forMod": True},
                    {"tick": 49, "volume": 1, "forMod": True},
                ]},
            ]}],
        })
        length = self.initialize(context, song)
        # Two beats ramp from 120 to 240 BPM, followed by four beats at 240 BPM.
        self.assertAlmostEqual(length, math.log(2) + 1, places=4)
        target = math.log(1.5)
        context.eval(f"gd5Seek({target},1)")
        self.assertAlmostEqual(context.eval("gd5Synth.playhead"), 0.25, places=4)
        target = math.log(2) + 1 / 44100
        context.eval(f"gd5Seek({target},1)")
        self.assertAlmostEqual(context.eval("gd5Synth.playhead"), 1, places=4)

    def test_bundled_embedded_examples_produce_audio(self):
        for path in sorted((ROOT / "assets/music/Ultrabox JSON").glob("*.json")):
            song = _read_song(str(path))
            if not all(_sample_url.startswith("data:") for _sample_url in
                       [ref.split("!", 2)[-1] for ref in song.get("customSamples", [])]):
                continue
            with self.subTest(song=path.name):
                context, song = self.make_context(song)
                self.initialize(context, song, seconds=20)
                self.assertTrue(any(base64.b64decode(context.eval("gd5Render(2048)"))))

    def test_browser_controls_and_switching_preserve_both_engines(self):
        context, song = self.make_context()
        context.eval(r"""
            globalThis.window = globalThis;
            globalThis.performance = {now() { return 0; }};
            globalThis.callbacks = [];
            globalThis.setTimeout = function(callback) { callbacks.push(callback); };
            globalThis.AudioContext = class {
                constructor() { this.sampleRate = 48000; this.destination = {}; }
                createScriptProcessor() {
                    return {bufferSize: 2048, connect() {}, disconnect() {}};
                }
                createGain() { return {context: this, gain: {value: 1}, connect() {}}; }
                resume() {}
                close() {}
                decodeAudioData() {
                    return Promise.resolve({getChannelData() { return new Float32Array([0,0.5,0,-0.5]); }});
                }
            };
            delete globalThis.gd5NativeSamples;
            globalThis.atob = function() { return "RIFF" + String.fromCharCode(36,4,0,0) + "WAVE"; };
            globalThis.fetch = function(url) {
                if (url.endsWith("/tone.wav")) return Promise.reject(new Error("Invalid base64 URL"));
                return Promise.resolve({ok: true, arrayBuffer() { return new ArrayBuffer(4); }});
            };
        """)
        context.eval(_synth_source(song))
        beepbox = copy.deepcopy(song)
        beepbox["format"] = "BeepBox"
        beepbox.pop("customSamples")
        beepbox["channels"][0]["instruments"][0]["wave"] = "square"
        context.eval(_synth_source(beepbox))
        context.eval(_WEB_JS_BRIDGE)
        for data in (song, beepbox, song):
            with self.subTest(format=data["format"]):
                context.eval(f"window.__gd5_beepbox_load({json.dumps(json.dumps(data))},1,0.5,0.4)")
                self.assertFalse(context.eval("window.__gd5_beepbox_finished()"))
                while context.execute_pending_job():
                    pass
                context.eval("while (callbacks.length) callbacks.shift()();")
                self.assertIsNone(context.eval("window.__gd5_beepbox_error()"))
                self.assertAlmostEqual(context.eval("window.__gd5_beepbox_position()"), 0.5, places=3)
                length = context.eval("window.__gd5_beepbox_length()")
                self.assertTrue(context.eval("window.__gd5_beepbox_synth.playing"))
                context.eval("window.__gd5_beepbox_pause(true)")
                self.assertFalse(context.eval("window.__gd5_beepbox_finished()"))
                context.eval("window.__gd5_beepbox_set_volume(0.2)")
                self.assertAlmostEqual(context.eval("window.__gd5_beepbox_gain.gain.value"), 0.2)
                context.eval("window.__gd5_beepbox_seek(0.75,2)")
                self.assertAlmostEqual(context.eval("window.__gd5_beepbox_length()"), length / 2, places=3)
                self.assertAlmostEqual(context.eval("window.__gd5_beepbox_position()"), 0.75, places=3)
                context.eval("window.__gd5_beepbox_pause(false)")
                context.eval("window.__gd5_beepbox_synth.synthesize(new Float32Array(2048),new Float32Array(2048),2048,true)")
                self.assertGreater(context.eval("window.__gd5_beepbox_position()"), 0.75)
        context.eval("window.__gd5_beepbox_stop()")
        self.assertEqual(context.eval("window.__gd5_beepbox_length()"), 0)

    def test_failed_browser_samples_do_not_finish_or_poison_the_next_track(self):
        context, song = self.make_context()
        self.initialize(context, song)
        context.eval("gd5BeginSampleLoad(); gd5NativeSamples = {};")
        song = copy.deepcopy(song)
        song["customSamples"][0] += "2"
        song["channels"][0]["instruments"][0]["wave"] = "tone.wav2"
        context.eval(f"gd5Init({json.dumps(json.dumps(song))},44100,1,0)")
        while context.execute_pending_job():
            pass
        with self.assertRaisesRegex(Exception, "Cannot load an UltraBox sample"):
            context.eval("gd5SamplesReady()")
        context.eval("gd5BeginSampleLoad()")
        self.assertTrue(context.eval("gd5SamplesReady()"))


class UltraBoxNativeTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("GD5_RUN_NATIVE_AUDIO_TESTS") == "1", "native audio integration is opt-in")
    def test_v8_stream_plays_embedded_examples_and_switches_back_to_beepbox(self):
        script = r"""
import sys, time
from tests.test_beepbox_audio import _disable_windows_native_error_dialogs
_disable_windows_native_error_dialogs()
import pygame
from beepbox_audio import BeepBoxStream
pygame.mixer.init(frequency=44100,size=-16,channels=2,buffer=1024)
try:
    for path in sys.argv[1:]:
        stream = BeepBoxStream(path,start_time=20,volume=0)
        try:
            deadline = time.monotonic()+15
            while stream.position < 20.15 and stream.error is None and time.monotonic()<deadline:
                stream.update()
                time.sleep(0.01)
            assert stream.error is None, stream.error
            assert stream.position >= 20.15, (path,stream.position)
            stream.pause(True)
            position = stream.position
            time.sleep(0.08)
            assert abs(stream.position-position)<0.03
            length = stream.length
            stream.seek(30,speed=1.5)
            stream.pause(False)
            deadline = time.monotonic()+15
            while stream.position < 30.15 and stream.error is None and time.monotonic()<deadline:
                stream.update()
                time.sleep(0.01)
            assert stream.error is None, stream.error
            assert stream.position >= 30.15, (path,stream.position)
            assert abs(stream.length-length/1.5)<0.01
        finally:
            stream.stop(wait=True)
finally:
    pygame.mixer.quit()
"""
        examples = ROOT / "assets/music/Ultrabox JSON"
        paths = [str(p) for p in examples.glob("*.json") if "dream" not in p.name]
        paths.append(str(ROOT / "assets/music/Greater Diplomacy 5/Dschungel.json"))
        environment = dict(os.environ, SDL_AUDIODRIVER="dummy")
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script, *paths],
                                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=65)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
