"""Sound effects: loading, volume and pitch settings, and playback on every audio backend.

play_ui_sound is the one entry point for UI and battle effects. The SoLoud, pygame.mixer,
and browser backends share the volume, pitch, and start-offset settings kept here.
"""
import json
import math
import os
from collections import OrderedDict, deque

import numpy as np
import pygame

import data.constants as c
from data.io import starting_defaults
from ui import browser_sound_effects, music_playback

soloud_engine = None
click_sound = None
slider_sound = None
pygame_click_sound = None
pygame_slider_sound = None
music_ui_sounds = {}
pygame_music_ui_sounds = {}
MUSIC_UI_SOUND_PATHS = {
    "back": "assets/sounds/Back.wav",
    "paper": "assets/sounds/Paper.wav",
    "puppets": "assets/sounds/Puppets.wav",
    "send_message": "assets/sounds/Send Message.mp3",
    "delete_message": "assets/sounds/Delete Message.mp3",
    "open_settings": "assets/sounds/Open Settings.mp3",
    "new_contact": "assets/sounds/New Contact.mp3",
    "info": "assets/sounds/Info.mp3",
    "create_army": "assets/sounds/Create Army.mp3",
    "research": "assets/sounds/Research.mp3",
    "select_unit": "assets/sounds/Select Unit.mp3",
    "bombardment_selected": "assets/sounds/Bombardment Selected.wav",
    "cancel_orders": "assets/sounds/Cancel Orders.wav",
    "click_province": "assets/sounds/Click Province.wav",
    "open_music": "assets/sounds/Open Music.wav",
    "select_category": "assets/sounds/Select Category.wav",
    "select_sub_category": "assets/sounds/Select Sub-Category.wav",
    "toggle_pause": "assets/sounds/Toggle Pause.wav",
    "time_select": "assets/sounds/Time Select.wav",
    "skip_song": "assets/sounds/Skip Song.wav",
    "select_unit_filter": "assets/sounds/Select Unit Filter.wav",
    "select_mode": "assets/sounds/Select Mode.wav",
    "select_view": "assets/sounds/Select View.wav",
    "rifle_shot_1": "assets/sounds/Rifle Shot 1.mp3",
    "rifle_shot_2": "assets/sounds/Rifle Shot 2.mp3",
    "rifle_shot_3": "assets/sounds/Rifle Shot 3.mp3",
    "heavy_gunshot": "assets/sounds/Heavy Gunshot.mp3",
    "tank_shot_1": "assets/sounds/Tank Shot 1.mp3",
    "tank_shot_2": "assets/sounds/Tank Shot 2.mp3",
    "tank_shot_3": "assets/sounds/Tank Shot 3.mp3",
    "tank_explosion": "assets/sounds/Tank Explosion.mp3",
    "torpedo_launch": "assets/sounds/Torpedo Launch.mp3",
    "flesh_wound_1": "assets/sounds/Flesh Wound 1.mp3",
    "flesh_wound_2": "assets/sounds/Flesh Wound 2.mp3",
    "flesh_wound_3": "assets/sounds/Flesh Wound 3.mp3",
    "bullet_ricochet_1": "assets/sounds/Bullet Ricochet 1.mp3",
    "bullet_ricochet_2": "assets/sounds/Bullet Ricochet 2.mp3",
    "bullet_ricochet_3": "assets/sounds/Bullet Ricochet 3.mp3",
    "bullet_ricochet_4": "assets/sounds/Bullet Ricochet 4.mp3",
}
SOUND_VOLUMES_PATH = "assets/sounds/volumes.json"
sound_volume_multipliers = {}
sound_start_offsets = {}
global_sfx_volume = starting_defaults.get_starting_value("settings_config.json", "sfx_volume")
global_sfx_pitch = starting_defaults.get_starting_value("settings_config.json", "sfx_pitch")

# Bound guaranteed battle voices so gunfire cannot exhaust the native mixer.
# Rifles share one pool across variants; tanks and torpedo launches retain their own quieter voices.
# Body impacts share the rifle pool, keeping repeated hits bounded on every backend.
BATTLE_SFX_GROUPS = {
    "rifle_shot_1": "rifle", "rifle_shot_2": "rifle", "rifle_shot_3": "rifle",
    "heavy_gunshot": "tank",
    "tank_shot_1": "tank", "tank_shot_2": "tank", "tank_shot_3": "tank",
    "tank_explosion": "tank", "torpedo_launch": "tank",
    "flesh_wound_1": "rifle", "flesh_wound_2": "rifle", "flesh_wound_3": "rifle",
    "bullet_ricochet_1": "rifle", "bullet_ricochet_2": "rifle",
    "bullet_ricochet_3": "rifle", "bullet_ricochet_4": "rifle",
}
BATTLE_SFX_VOICE_LIMITS = {"rifle": 8, "tank": 4}
BATTLE_SFX_OTHER_CHANNELS = 4  # Room for music and ordinary UI effects on Pygame.
_soloud_battle_engine = None
_soloud_battle_voices = {group: deque() for group in BATTLE_SFX_VOICE_LIMITS}
_pygame_battle_voices = {group: deque() for group in BATTLE_SFX_VOICE_LIMITS}

# pygame.mixer has no playback-rate control.  UI sounds are short, so keeping a
# few resampled PCM copies gives the web build the same pitch response as the
# native SoLoud path without doing audio work every time a button is clicked.
PYGAME_SFX_PITCH_CACHE_SIZE = 24
_pygame_sfx_pitch_cache = {
    "click": OrderedDict(),
    "slider": OrderedDict(),
    **{kind: OrderedDict() for kind in MUSIC_UI_SOUND_PATHS},
}


def read_volumes_file(path):
    """Read a volumes.json file. Return ({filename: volume}, {filename: offset}).

    Sound effects and music albums share this format. A number sets the volume
    multiplier. An object can set "volume" and "offset"; missing values use 1.0
    and 0.0. A missing file has no settings.
    """
    try:
        with open(path, encoding="utf-8") as source:
            values = json.load(source)
    except FileNotFoundError:
        values = {}
    except json.JSONDecodeError as error:
        raise ValueError(f"Fix invalid JSON in {path}: {error}") from error
    if not isinstance(values, dict):
        raise ValueError(f"{path} must contain filenames and volume settings.")
    multipliers = {}
    offsets = {}
    for filename, value in values.items():
        if isinstance(value, dict):
            unknown = value.keys() - {"volume", "offset"}
            if unknown:
                raise ValueError(f"{path}: {filename} has unknown volume settings: {', '.join(sorted(unknown))}.")
            volume, offset = value.get("volume", 1.0), value.get("offset", 0.0)
        else:
            volume, offset = value, 0.0
        for name, number in (("volume", volume), ("offset", offset)):
            if (isinstance(number, bool) or not isinstance(number, (int, float))
                    or not math.isfinite(number) or number < 0):
                raise ValueError(f"{path}: {filename} {name} must be a finite number of zero or greater.")
        multipliers[filename] = volume
        offsets[filename] = offset
    return multipliers, offsets


def load_sound_volumes(path=SOUND_VOLUMES_PATH):
    """Read per-file SFX volume multipliers and start offsets at startup."""
    multipliers, offsets = read_volumes_file(path)
    sound_volume_multipliers.clear()
    sound_volume_multipliers.update(multipliers)
    sound_start_offsets.clear()
    sound_start_offsets.update(offsets)
    for cache in _pygame_sfx_pitch_cache.values():
        cache.clear()


def _ui_sound_filename(kind):
    """Find the configuration key for a UI sound."""
    if kind == "click":
        path = c.SOUND_CLICK_PATH
    elif kind == "slider":
        path = c.SOUND_SLIDER_PATH
    else:
        path = MUSIC_UI_SOUND_PATHS[kind]
    return os.path.basename(path)


def _ui_sound_volume(kind):
    """Combine the file multiplier with the player's SFX volume."""
    return global_sfx_volume * sound_volume_multipliers.get(_ui_sound_filename(kind), 1.0)


def load_music_ui_sounds(sound_factory, *, soloud=False):
    """Load named control effects when the audio backend starts."""
    sounds = music_ui_sounds if soloud else pygame_music_ui_sounds
    sounds.clear()
    for voices in (_soloud_battle_voices if soloud else _pygame_battle_voices).values():
        voices.clear()
    for kind, path in MUSIC_UI_SOUND_PATHS.items():
        if soloud:
            sound = sound_factory()
            sound.load(path)
        else:
            sound = sound_factory(path)
        sounds[kind] = sound
        _pygame_sfx_pitch_cache[kind].clear()


def _load_pygame_ui_sound(path):
    try:
        return music_playback.load_pygame_sound(path)
    except (pygame.error, OSError) as error:
        print(f"Cannot load UI sound {path}: {error}")
        return None


def load_pygame_ui_sounds():
    """Load each effect independently so one bad file cannot mute every button."""
    set_pygame_ui_sounds(
        _load_pygame_ui_sound(c.SOUND_CLICK_PATH),
        _load_pygame_ui_sound(c.SOUND_SLIDER_PATH),
    )
    load_music_ui_sounds(_load_pygame_ui_sound)


def load_browser_ui_sounds():
    """Give every effect to the browser, which then plays all UI sounds."""
    browser_sound_effects.load({
        "click": c.SOUND_CLICK_PATH, "slider": c.SOUND_SLIDER_PATH, **MUSIC_UI_SOUND_PATHS})


def _soloud_battle_slot(group):
    """Reclaim the oldest effect in this group, leaving a native slot for music."""
    global _soloud_battle_engine
    if _soloud_battle_engine is not soloud_engine:
        for voices in _soloud_battle_voices.values():
            voices.clear()
        _soloud_battle_engine = soloud_engine
    budget = max(0, soloud_engine.get_max_active_voice_count() - 1)
    tank_limit = min(BATTLE_SFX_VOICE_LIMITS["tank"], budget)
    limit = tank_limit if group == "tank" else min(BATTLE_SFX_VOICE_LIMITS["rifle"], budget - tank_limit)
    voices = _soloud_battle_voices[group]
    live = [handle for handle in voices if soloud_engine.is_valid_voice_handle(handle)]
    voices.clear()
    voices.extend(live)
    if limit == 0:
        return None
    while len(voices) >= limit:
        soloud_engine.stop(voices.popleft())
    return voices


def _play_pygame_battle_sound(group, sound):
    """Reuse only battle-owned channels; never force-steal the music channel."""
    minimum = sum(BATTLE_SFX_VOICE_LIMITS.values()) + BATTLE_SFX_OTHER_CHANNELS
    if pygame.mixer.get_num_channels() < minimum:
        pygame.mixer.set_num_channels(minimum)
    for voices in _pygame_battle_voices.values():
        live = [(channel, source) for channel, source in voices
                if channel.get_busy() and channel.get_sound() is source]
        voices.clear()
        voices.extend(live)
    voices = _pygame_battle_voices[group]
    if len(voices) >= BATTLE_SFX_VOICE_LIMITS[group]:
        channel, _source = voices.popleft()
    else:
        channel = pygame.mixer.find_channel()
        if channel is None and voices:
            channel, _source = voices.popleft()
        if channel is None and group == "tank" and _pygame_battle_voices["rifle"]:
            channel, _source = _pygame_battle_voices["rifle"].popleft()
    if channel is not None:
        channel.set_volume(1.0)
        channel.play(sound)
        voices.append((channel, sound))


def play_ui_sound(kind="click", volume_scale=1.0):
    """Plays a UI sfx through whichever audio backend is active.

    Single entry point for every click/slider blip in the game, so the SoLoud
    vs. pygame.mixer branch and the volume/pitch maths live in exactly one place.
    ``volume_scale`` lowers one play, such as a battle shot seen from a zoomed-out view.
    """
    if global_sfx_volume <= 0:
        return
    volume = _ui_sound_volume(kind) * volume_scale
    if volume <= 0:
        return
    battle_group = BATTLE_SFX_GROUPS.get(kind)

    if browser_sound_effects.active:
        browser_sound_effects.play(
            kind, volume, 0.5 + global_sfx_pitch,
            sound_start_offsets.get(_ui_sound_filename(kind), 0.0),
            battle_group, BATTLE_SFX_VOICE_LIMITS.get(battle_group, 0))
    elif c.USE_SOLOUD:
        sound = (click_sound if kind == "click" else slider_sound if kind == "slider"
                 else music_ui_sounds.get(kind))
        if sound and soloud_engine:
            offset = sound_start_offsets.get(_ui_sound_filename(kind), 0.0)
            if offset and offset >= sound.get_length():
                return
            voices = _soloud_battle_slot(battle_group) if battle_group is not None else None
            if battle_group is not None and voices is None:
                return
            # Seek a new paused voice at normal speed before it can emit audio.
            paused = bool(offset or battle_group is not None)
            handle = soloud_engine.play(sound, aPaused=1) if paused else soloud_engine.play(sound)
            if offset and soloud_engine.seek(handle, offset) != 0:
                soloud_engine.stop(handle)
                return
            soloud_engine.set_volume(handle, volume)
            # Centres the speed variance directly on a 0.5 pitch input
            soloud_engine.set_relative_play_speed(handle, 0.5 + global_sfx_pitch)
            if battle_group is not None:
                soloud_engine.set_inaudible_behavior(handle, True, False)
                voices.append(handle)
            if paused:
                soloud_engine.set_pause(handle, False)
    else:
        sound = _pygame_sound_at_pitch(kind, max(1.0, volume))
        if sound:
            sound.set_volume(min(1.0, volume))
            if battle_group is None:
                sound.play()
            else:
                _play_pygame_battle_sound(battle_group, sound)

def set_pygame_ui_sounds(click, slider):
    """Sets pygame UI sound sources and invalidates their pitch variants."""
    global pygame_click_sound, pygame_slider_sound
    pygame_click_sound = click
    pygame_slider_sound = slider
    for voices in _pygame_battle_voices.values():
        voices.clear()
    for cache in _pygame_sfx_pitch_cache.values():
        cache.clear()

def _resample_pygame_sound(sound, speed):
    """Returns a pygame sound whose duration is adjusted for ``speed``.

    Resampling changes both duration and pitch, matching the SoLoud relative
    playback-speed control used on desktop.  pygame.sndarray preserves the
    active mixer format, including mono versus stereo samples.
    """
    samples = pygame.sndarray.array(sound)
    source_frames = samples.shape[0]
    target_frames = max(1, round(source_frames / speed))
    positions = np.linspace(0, source_frames - 1, target_frames)
    source_positions = np.arange(source_frames)

    if samples.ndim == 1:
        resampled = np.interp(positions, source_positions, samples)
    else:
        resampled = np.column_stack([
            np.interp(positions, source_positions, samples[:, channel])
            for channel in range(samples.shape[1])
        ])

    if np.issubdtype(samples.dtype, np.integer):
        limits = np.iinfo(samples.dtype)
        resampled = np.clip(np.rint(resampled), limits.min, limits.max)
    return pygame.sndarray.make_sound(resampled.astype(samples.dtype))

def _amplify_pygame_sound(sound, gain):
    """Boost samples and clip peaks to the mixer format's valid range."""
    samples = pygame.sndarray.array(sound)
    amplified = samples.astype(np.float64)
    if np.issubdtype(samples.dtype, np.integer):
        limits = np.iinfo(samples.dtype)
        midpoint = (limits.max + 1) / 2 if limits.min == 0 else 0
        amplified = (amplified - midpoint) * gain + midpoint
        amplified = np.clip(np.rint(amplified), limits.min, limits.max)
    else:
        amplified = np.clip(amplified * gain, -1.0, 1.0)
    return pygame.sndarray.make_sound(amplified.astype(samples.dtype))


def _pygame_sound_at_pitch(kind, gain=1.0):
    """Get a cached pygame effect at the selected pitch and amplification."""
    sound = (pygame_click_sound if kind == "click" else pygame_slider_sound if kind == "slider"
             else pygame_music_ui_sounds.get(kind))
    if sound is None:
        return None

    offset = sound_start_offsets.get(_ui_sound_filename(kind), 0.0)
    if offset and offset >= sound.get_length():
        return None
    speed = 0.5 + global_sfx_pitch
    if offset == 0 and speed == 1.0 and gain == 1.0:
        return sound

    # Quantising very slightly lets a dragged slider reuse neighbouring cached
    # variants while retaining a smooth audible response.
    cache_key = (round(speed, 2), gain, offset)
    cache = _pygame_sfx_pitch_cache[kind]
    cached_sound = cache.get(cache_key)
    if cached_sound is not None:
        cache.move_to_end(cache_key)
        return cached_sound

    if offset:
        start_frame = int(offset * pygame.mixer.get_init()[0])
        samples = pygame.sndarray.array(sound)
        if start_frame >= len(samples):
            return None
        sound = pygame.sndarray.make_sound(np.ascontiguousarray(samples[start_frame:]))
    pitched_sound = _resample_pygame_sound(sound, cache_key[0]) if speed != 1.0 else sound
    if gain != 1.0:
        pitched_sound = _amplify_pygame_sound(pitched_sound, gain)
    cache[cache_key] = pitched_sound
    if len(cache) > PYGAME_SFX_PITCH_CACHE_SIZE:
        cache.popitem(last=False)
    return pitched_sound

def set_sfx_volume(val):
    """Applies a new sfx volume to the shared state and both audio backends."""
    global global_sfx_volume
    global_sfx_volume = val
    if not c.USE_SOLOUD:
        for sound in (pygame_click_sound, pygame_slider_sound, *pygame_music_ui_sounds.values()):
            if sound:
                sound.set_volume(val)

def set_sfx_pitch(val):
    """Updates the shared SFX pitch used by either audio backend."""
    global global_sfx_pitch
    global_sfx_pitch = max(0.0, min(1.0, float(val)))
