"""One interface for the three music backends.

The controller holds at most one playback object in `Controller.music`.
BeepBox and UltraBox songs use BeepBoxPlayback. Other tracks use
SoLoudPlayback on desktop or PygamePlayback when SoLoud is not available.
The callers do not need to know which backend plays the current track.

Positions and lengths are in seconds of the source track. The music player
converts them to the timeline that the player selected. Pygame Mixer cannot
change the playback speed, so its speed is always 1.0 and both timelines show
the source time.

source_position() returns None when the backend cannot report a position.
The music player then keeps its last known position.
"""

import ctypes

import pygame


# Decoding a whole file to read its length is slow, so keep each result.
_SOUND_FILE_LENGTHS = {}


def sound_file_length(track_path):
    """The length of a track file in seconds, or 0 when Pygame cannot read it."""
    if track_path not in _SOUND_FILE_LENGTHS:
        try:
            _SOUND_FILE_LENGTHS[track_path] = pygame.mixer.Sound(track_path).get_length()
        except (pygame.error, OSError):
            _SOUND_FILE_LENGTHS[track_path] = 0
    return _SOUND_FILE_LENGTHS[track_path]


class BeepBoxPlayback:
    """A BeepBox or UltraBox song that a synthesizer stream renders."""

    def __init__(self, stream):
        self.stream = stream
        self.paused = False
        self._stopped = False

    @property
    def speed(self):
        return self.stream.speed

    @property
    def error(self):
        return self.stream.error

    @property
    def finished(self):
        # A stopped stream never reports that it finished. Count it as finished,
        # so that a track that fails to start after it lets the next song play.
        return self._stopped or self.stream.finished

    def update(self):
        self.stream.update()

    def pause(self, paused):
        self.stream.pause(paused)
        self.paused = paused

    def stop(self):
        self.stream.stop()
        self._stopped = True

    def set_volume(self, volume):
        self.stream.set_volume(volume)

    def set_speed(self, speed):
        source_position = self.source_position()
        self.stream.seek(source_position / speed, speed=speed)

    def seek(self, source_seconds):
        # The stream seeks in seconds of playback at its current speed.
        self.stream.seek(source_seconds / self.speed)

    def source_position(self):
        return self.stream.position * self.stream.speed

    def source_length(self):
        return self.stream.length * self.stream.speed


class SoLoudPlayback:
    """A track file that the SoLoud engine streams."""

    error = None

    def __init__(self, engine, stream, track_path, start_time, volume, speed):
        self.engine = engine
        self.stream = stream
        self.track_path = track_path
        self.volume = volume
        self.speed = speed
        self.paused = False
        self._load()
        self.handle = engine.play(stream)
        if start_time > 0:
            engine.seek(self.handle, start_time)
        engine.set_volume(self.handle, volume)
        engine.set_relative_play_speed(self.handle, speed)

    def _load(self):
        # WavStream.load() passes the path through fopen() via the C runtime,
        # which reads it in the OS ANSI codepage instead of UTF-8 on Windows --
        # non-ASCII filenames/titles (e.g. Japanese) silently fail to open.
        # Reading the bytes with Python (Unicode-path-safe) and streaming them
        # in via load_mem() avoids that codepage round-trip.
        with open(self.track_path, 'rb') as f:
            data = f.read()
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        self.stream.load_mem(buf, len(data), aCopy=True, aTakeOwnership=False)

    @property
    def finished(self):
        return not self.engine.is_valid_voice_handle(self.handle)

    def update(self):
        pass

    def pause(self, paused):
        self.engine.set_pause(self.handle, paused)
        self.paused = paused

    def stop(self):
        self.engine.stop(self.handle)

    def set_volume(self, volume):
        self.volume = volume
        self.engine.set_volume(self.handle, volume)

    def set_speed(self, speed):
        self.speed = speed
        self.engine.set_relative_play_speed(self.handle, speed)

    def seek(self, source_seconds):
        # WORKAROUND: This SoLoud DLL's seek() has a bug where it
        # resets mStreamPosition to 0 before the skip loop, so after
        # seeking, mStreamPosition = skip_distance (not absolute target).
        # On repeated seeks the audio decoder overshoots the intended
        # position, eventually running past the end of the stream.
        #
        # Fix: stop → reload → play paused → seek from 0 → unpause.
        # When seeking from position 0, skip_distance == target, so
        # mStreamPosition ends up correct.
        self.engine.stop(self.handle)
        self._load()
        self.handle = self.engine.play(self.stream, aPaused=1)
        self.engine.set_volume(self.handle, self.volume)
        # Seek from position 0 BEFORE setting speed — the seek skip
        # loop internally uses getAudio() which consumes samples at
        # the current play speed. At 1.5x it would overshoot; at
        # 0.75x it would undershoot. Seeking at default 1.0x is exact.
        self.engine.seek(self.handle, source_seconds)
        self.engine.set_relative_play_speed(self.handle, self.speed)
        if not self.paused:
            self.engine.set_pause(self.handle, False)

    def source_position(self):
        # SoLoud's stream position is source time and remains stable
        # when its playback speed changes.
        return self.engine.get_stream_position(self.handle)

    def source_length(self):
        # Prefer SoLoud's own length: pygame.mixer.Sound can report a
        # different duration for compressed formats (MP3/OGG), which would
        # let the scrubber seek past SoLoud's actual stream end.
        length = self.stream.get_length()
        return length if length > 0 else sound_file_length(self.track_path)


class PygamePlayback:
    """A track file that pygame.mixer.music plays. Used on web and as the fallback."""

    # Pygame Mixer cannot change the playback speed.
    speed = 1.0
    error = None

    def __init__(self, track_path, start_time, volume):
        self.track_path = track_path
        self.paused = False
        # get_pos() counts from play(), not from set_pos(). After a seek, the
        # position is the seek target plus the time since the seek. The next
        # update() records get_pos() at the seek as the base.
        self._offset = 0.0
        self._base = 0.0
        self._awaiting_seek = False
        pygame.mixer.music.load(track_path)
        pygame.mixer.music.play(start=start_time)
        pygame.mixer.music.set_volume(volume)

    @property
    def finished(self):
        # Pygame 2 reports a paused track as not busy.
        return not self.paused and not pygame.mixer.music.get_busy()

    def update(self):
        if self._awaiting_seek:
            self._awaiting_seek = False
            self._base = pygame.mixer.music.get_pos() / 1000.0

    def pause(self, paused):
        if paused:
            pygame.mixer.music.pause()
        else:
            pygame.mixer.music.unpause()
        self.paused = paused

    def stop(self):
        pygame.mixer.music.stop()
        self.paused = False

    def set_volume(self, volume):
        pygame.mixer.music.set_volume(volume)

    def set_speed(self, speed):
        pass

    def seek(self, source_seconds):
        # Seeking resumes a paused track.
        if self.paused:
            self.pause(False)
        try:
            pygame.mixer.music.set_pos(source_seconds)
        except pygame.error:
            try:
                pygame.mixer.music.play(start=source_seconds)
            except pygame.error as e:
                print(f"Cannot scrub format: {e}")
        self._offset = source_seconds
        self._awaiting_seek = True

    def source_position(self):
        if self._awaiting_seek or self.paused:
            return None
        raw_pos = max(0.0, pygame.mixer.music.get_pos() / 1000.0)
        return self._offset + (raw_pos - self._base)

    def source_length(self):
        return sound_file_length(self.track_path)
