"""Sound effects played by the browser's Web Audio API. Used on Android.

The Pygame mixer mixes on the page's main thread and needs a large buffer on
Android to play music without gaps (see ANDROID_MIXER_BUFFER_FRAMES in
data/platform.py). That buffer delays every sound the mixer starts. Web Audio
mixes on the browser's own audio thread, so an effect starts without waiting
for a mixer buffer or a game frame. It also sets pitch, volume, and start
offset per play, so this path needs no resampled copies of an effect.

sound_effects.play_ui_sound is the only caller of play().
"""

import json
import os

from ui import music_playback


# Whether play_ui_sound sends effects here. load() turns it on.
active = False

_BRIDGE = r"""
window.__gd5_sfx = {context: null, buffers: {}, voices: {}};
window.__gd5_sfx_load = function(kind, pathJson) {
    const sfx = window.__gd5_sfx;
    if (!sfx.context) {
        sfx.context = new (window.AudioContext || window.webkitAudioContext)(
            {latencyHint: 'interactive'});
    }
    // The path arrives as JSON so that non-ASCII names survive pygbag.
    const path = JSON.parse(pathJson);
    let bytes;
    try {
        bytes = FS.readFile(path);
    } catch (error) {
        console.log('Cannot load UI sound ' + path + ': ' + error);
        return;
    }
    // decodeAudioData takes ownership of its buffer, so pass a copy.
    const data = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    sfx.context.decodeAudioData(data, function(buffer) {
        sfx.buffers[kind] = buffer;
    }, function(error) {
        console.log('Cannot decode UI sound ' + path + ': ' + error);
    });
};
// group and limit bound the voices of one battle sound group. The oldest voice
// of a full group stops. Pass an empty group for an ordinary effect.
window.__gd5_sfx_play = function(kind, volume, speed, offset, group, limit) {
    const sfx = window.__gd5_sfx;
    const buffer = sfx.buffers[kind];
    if (!buffer || offset >= buffer.duration) return;
    const context = sfx.context;
    if (context.state === 'suspended') context.resume();
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.playbackRate.value = speed;
    const gain = context.createGain();
    gain.gain.value = volume;
    source.connect(gain);
    gain.connect(context.destination);
    if (group) {
        const voices = sfx.voices[group] || (sfx.voices[group] = []);
        while (voices.length >= limit) voices.shift().stop();
        voices.push(source);
        source.onended = function() {
            const index = voices.indexOf(source);
            if (index >= 0) voices.splice(index, 1);
        };
    }
    source.start(0, offset);
};
"""


def _window():
    import platform  # stdlib `platform`, patched by pygbag with `.window` on web
    return platform.window


def load(sound_paths):
    """Decode each effect in the browser. sound_paths maps a sound kind to its file."""
    global active
    window = _window()
    window.eval(_BRIDGE)
    for kind, path in sound_paths.items():
        # pygbag garbles non-ASCII text on its way to JavaScript; json.dumps
        # writes it as ASCII \u escapes that the bridge decodes.
        getattr(window, "__gd5_sfx_load")(
            kind, json.dumps(os.path.abspath(music_playback.pygame_audio_path(path))))
    active = True


def play(kind, volume, speed, offset, group=None, voice_limit=0):
    """Start one effect. A sound that failed to load or decode stays silent."""
    getattr(_window(), "__gd5_sfx_play")(kind, volume, speed, offset, group or "", voice_limit)
