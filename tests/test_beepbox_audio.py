import base64
import json
import os
import subprocess
import sys
import unittest

from beepbox_audio import (
    _JS_BRIDGE,
    has_beepbox_replacement,
    is_available,
    is_beepbox_song,
)
from data.constants import CREDITS_DATA


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SONG_PATH = os.path.join(ROOT, "assets", "music", "Greater Diplomacy 5", "Dschungel.json")
SYNTH_PATH = os.path.join(ROOT, "assets", "beepbox", "beepbox_synth.min.js")


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

        pcm_parts = json.loads(context.eval("gd5Render(2048)").json())
        pcm = base64.b64decode("".join(pcm_parts))
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

    @unittest.skipUnless(is_available(), "native QuickJS dependency is not installed")
    def test_buffered_pygame_stream_supports_play_pause_and_seek(self):
        script = r"""
import sys
import time
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
    assert stream.position >= 0.1
    normal_length = stream.length

    stream.pause(True)
    paused_at = stream.position
    time.sleep(0.08)
    assert abs(stream.position - paused_at) < 0.03

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
finally:
    stream.stop()
    pygame.mixer.quit()
"""
        environment = os.environ.copy()
        environment["SDL_AUDIODRIVER"] = "dummy"
        result = subprocess.run(
            [sys.executable, "-c", script, SONG_PATH],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
