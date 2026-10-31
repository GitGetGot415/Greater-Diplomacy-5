ULTRABOX PLAYBACK SYNTH
======================

Source: https://ultraabox.github.io/beepbox_synth.min.js
Project: https://github.com/ultraabox/ultrabox_typescript
Retrieved: 2026-10-30
License: MIT. See LICENSE.md.
Original size: 460087 bytes.
Original SHA-256: 89c7fc1bd7d93ded4b37e914318877ddabb9216dfaad240f70df5eee58a41129

The original BeepBox bundle remains in assets/beepbox/.
Only UltraBox songs use this bundle.

LOCAL EXTENSION
===============

getTotalSamples has an optional fourth argument: {bar, part}.
The argument ends its existing duration calculation at that position.
It sets the final bar to bar + 1.
It enables the existing shortened-bar path.
It limits the last bar's parts to the supplied part.
Calls without this argument retain the upstream behavior.
GD5 uses this extension to seek through tempo changes without copying timing rules.

gd5_adapter.js gives the synth separate browser globals and a separate namespace.
It disables editor page reloads and loads samples before playback.
Desktop playback supplies decoded WAV samples instead of browser fetch and AudioContext decoding.
Browser playback uses fetch and AudioContext decoding.
Neither path substitutes a default wave for a missing sample.
External sample packs must first be exported as embedded song audio.

UPDATE PROCEDURE
================

1. Download the playback synth and its license from the upstream project.
2. Add the optional duration argument to the upstream getTotalSamples implementation.
3. Keep all existing duration calculations and default behavior.
4. Update the source information and checksum above.
5. Run tests.test_ultrabox_audio and tests.test_beepbox_audio.
6. Run native audio integration tests with GD5_RUN_NATIVE_AUDIO_TESTS=1.
7. Check browser playback and all music controls.
