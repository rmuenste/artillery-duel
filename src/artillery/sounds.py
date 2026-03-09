"""Sound effects for Artillery Duel.

Loads fire/explosion/flight sounds from a WAV file, slicing by time ranges.
Falls back to procedural generation if the file is missing.
"""

from pathlib import Path

import numpy as np
import pygame

_SOUNDS_DIR = Path(__file__).parent / "assets" / "sounds"
_WAV_FILE = _SOUNDS_DIR / "artillery_shell.wav"

_fire_sound: pygame.mixer.Sound | None = None
_flight_sound: pygame.mixer.Sound | None = None
_explosion_sound: pygame.mixer.Sound | None = None
_flight_channel: pygame.mixer.Channel | None = None
_master_volume: float = 1.0

# Mixer rate (set in init after pygame.mixer is ready)
_RATE = 44100


# --------------------------------------------------------------------------- #
# WAV slicing                                                                  #
# --------------------------------------------------------------------------- #

def _load_from_wav() -> tuple[pygame.mixer.Sound, pygame.mixer.Sound, pygame.mixer.Sound]:
    """Slice the combined WAV into fire, explosion, and flight sounds."""
    import wave

    with wave.open(str(_WAV_FILE), "r") as w:
        rate = w.getframerate()
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)

    def _slice(start_s: float, end_s: float) -> np.ndarray:
        s = int(start_s * rate)
        e = min(int(end_s * rate), len(samples))
        return samples[s:e]

    fire_samples = _slice(0.15, 1.0)
    explosion_samples = _slice(1.9, 3.0)
    flight_samples = _slice(3.0, 5.0)

    # Resample to mixer rate if needed
    mixer_rate = pygame.mixer.get_init()[0]
    if rate != mixer_rate:
        fire_samples = _resample(fire_samples, rate, mixer_rate)
        explosion_samples = _resample(explosion_samples, rate, mixer_rate)
        flight_samples = _resample(flight_samples, rate, mixer_rate)

    return (
        _array_to_sound(fire_samples),
        _array_to_sound(explosion_samples),
        _array_to_sound(flight_samples),
    )


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear resampling."""
    ratio = dst_rate / src_rate
    new_len = int(len(samples) * ratio)
    indices = np.linspace(0, len(samples) - 1, new_len)
    return np.interp(indices, np.arange(len(samples)), samples)


def _array_to_sound(samples: np.ndarray) -> pygame.mixer.Sound:
    """Convert a float64 sample array to a pygame Sound (stereo, 16-bit)."""
    peak = np.max(np.abs(samples))
    if peak > 0:
        samples = samples / peak
    int16 = (samples * 32767).astype(np.int16)
    stereo = np.column_stack((int16, int16))
    return pygame.sndarray.make_sound(stereo)


# --------------------------------------------------------------------------- #
# Procedural fallback                                                          #
# --------------------------------------------------------------------------- #

def _generate_fire() -> pygame.mixer.Sound:
    dur = 0.3
    t = np.linspace(0, dur, int(_RATE * dur), endpoint=False)
    envelope = np.exp(-t * 15)
    sine = np.sin(2 * np.pi * 90 * t)
    noise = np.random.default_rng(42).uniform(-1, 1, len(t))
    return _array_to_sound((0.7 * sine + 0.3 * noise) * envelope)


def _generate_flight() -> pygame.mixer.Sound:
    dur = 2.0
    t = np.linspace(0, dur, int(_RATE * dur), endpoint=False)
    freq = np.linspace(1500, 800, len(t))
    phase = 2 * np.pi * np.cumsum(freq) / _RATE
    noise = np.random.default_rng(7).uniform(-1, 1, len(t)) * 0.05
    return _array_to_sound((np.sin(phase) + noise) * 0.3)


def _generate_explosion() -> pygame.mixer.Sound:
    dur = 0.8
    t = np.linspace(0, dur, int(_RATE * dur), endpoint=False)
    envelope = np.exp(-t * 5)
    sine = np.sin(2 * np.pi * 60 * t)
    noise = np.random.default_rng(99).uniform(-1, 1, len(t))
    return _array_to_sound((0.4 * sine + 0.6 * noise) * envelope)


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def init() -> None:
    """Load or generate all sounds. Call after pygame.mixer.init()."""
    global _fire_sound, _flight_sound, _explosion_sound, _RATE
    _RATE = pygame.mixer.get_init()[0]

    if _WAV_FILE.exists():
        _fire_sound, _explosion_sound, _flight_sound = _load_from_wav()
    else:
        _fire_sound = _generate_fire()
        _flight_sound = _generate_flight()
        _explosion_sound = _generate_explosion()
    _apply_volume()


def _apply_volume() -> None:
    for snd in (_fire_sound, _flight_sound, _explosion_sound):
        if snd is not None:
            snd.set_volume(_master_volume)


def set_volume(vol: float) -> None:
    global _master_volume
    _master_volume = max(0.0, min(1.0, vol))
    _apply_volume()


def play_fire() -> None:
    if _fire_sound is not None:
        _fire_sound.play()


def play_flight() -> None:
    global _flight_channel
    if _flight_sound is not None:
        _flight_channel = _flight_sound.play(loops=-1)


def stop_flight() -> None:
    global _flight_channel
    if _flight_channel is not None:
        _flight_channel.stop()
        _flight_channel = None


def play_explosion() -> None:
    if _explosion_sound is not None:
        _explosion_sound.play()
