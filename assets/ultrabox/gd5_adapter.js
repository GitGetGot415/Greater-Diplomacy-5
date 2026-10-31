// Keep UltraBox's browser globals and namespace separate from BeepBox.
globalThis.gd5UltraBox = (function () {
    const host = globalThis;
    const native = host.gd5NativeSamples !== undefined;
    const navigator = host.navigator || {userAgent: "GD5", platform: ""};
    const Event = host.Event || class { constructor(type) { this.type = type; } };
    const EventTarget = host.EventTarget || class { dispatchEvent() {} };
    const URL = host.URL || class {
        constructor(url) { this.pathname = url.replace(/^[a-z]+:\/\/[^/]+/i, ""); }
    };
    const window = {
        AudioContext: host.AudioContext, webkitAudioContext: host.webkitAudioContext,
        location: {hash: ""},
    };
    // Song import can request an editor page reload. Playback needs no reload.
    const setTimeout = function () {};
    const location = {reload() {}};
    const console = host.console || {log() {}};
    const alert = function (message) { throw new Error(message); };
    let state = {pending: 0, failure: null};
    const fail = function (error, loadState) {
        loadState.failure = "Cannot load an UltraBox sample. Supply its file or embed it in the JSON: " + error;
        throw error;
    };
    const fetch = native
        ? function (url) {
            return Promise.resolve({ok: true, arrayBuffer: function () { return url; }});
        }
        : function (url) {
            const loadState = state;
            // Some exports append /InstrumentName to an embedded WAV URL.
            // Keep that name in the song, but fetch only the RIFF file's bytes.
            const marker = url.indexOf(";base64,");
            if (url.startsWith("data:") && marker >= 0) {
                const start = marker + 8;
                const header = host.atob(url.slice(start, start + 16));
                if (header.slice(0, 4) === "RIFF" && header.slice(8, 12) === "WAVE") {
                    const size = (header.charCodeAt(4) | header.charCodeAt(5) << 8 |
                        header.charCodeAt(6) << 16 | header.charCodeAt(7) << 24) >>> 0;
                    url = url.slice(0, start + Math.ceil((size + 8) / 3) * 4);
                }
            }
            return host.fetch(url).then(function (response) {
                if (!response.ok) throw new Error("HTTP " + response.status);
                return response;
            }).catch(function (error) { return fail(error, loadState); });
        };
    function unpack(encoded) {
        const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
        const bytes = new Uint8Array(Math.floor(encoded.length * 3 / 4));
        let value = 0, bits = 0, length = 0;
        for (const character of encoded) {
            const digit = alphabet.indexOf(character);
            if (digit < 0) break;
            value = (value << 6) | digit;
            bits += 6;
            if (bits >= 8) { bits -= 8; bytes[length++] = (value >> bits) & 255; }
        }
        return new Float32Array(bytes.buffer.slice(0, length));
    }
    const AudioContext = function (options) {
        const loadState = state;
        loadState.pending++;
        let closed = false;
        const context = native ? null : new (host.AudioContext || host.webkitAudioContext)(options);
        return {
            decodeAudioData: function (data) {
                if (!native) return context.decodeAudioData(data).catch(function (error) { return fail(error, loadState); });
                const sample = host.gd5NativeSamples[data];
                if (!sample) return Promise.reject(new Error("Missing decoded WAV sample")).catch(function (error) { return fail(error, loadState); });
                let values = unpack(sample.pcm);
                // Browser decodeAudioData resamples to the requested context rate.
                if (sample.rate !== options.sampleRate) {
                    const resampled = new Float32Array(Math.ceil(values.length * options.sampleRate / sample.rate));
                    for (let i = 0; i < resampled.length; i++) {
                        const position = i * sample.rate / options.sampleRate;
                        const index = Math.floor(position), fraction = position - index;
                        const a = values[Math.min(index, values.length - 1)];
                        const b = values[Math.min(index + 1, values.length - 1)];
                        resampled[i] = a + (b - a) * fraction;
                    }
                    values = resampled;
                }
                return Promise.resolve({getChannelData: function () { return values; }});
            },
            close: function () {
                if (!closed) { loadState.pending--; closed = true; }
                if (context) return context.close();
            },
        };
    };
    // Optional packs require separate audio assets. Do not substitute a default wave.
    const document = {
        URL: "",
        createElement: function () {
            state.failure = "Embed UltraBox sample-pack audio in the song JSON before playback";
            throw new Error(state.failure);
        },
    };
    host.gd5BeginSampleLoad = function () { state = {pending: 0, failure: null}; };
    host.gd5SamplesReady = function () {
        if (state.failure) throw new Error(state.failure);
        return state.pending === 0;
    };
    /* GD5_VENDOR_SYNTH */
    // The editor defers sample loading until a page reload. Load in place here.
    Object.defineProperty(beepbox.Config, "willReloadForCustomSamples", {
        get: function () { return false; }, set: function () {},
    });
    return beepbox;
})();
