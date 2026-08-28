"""Generate RamBo's kill-streak announcer lines via ElevenLabs text-to-speech.

Separate from generate_sfx.py because this is a different endpoint: the sound
effects come from /v1/sound-generation, spoken lines from /v1/text-to-speech.
The two also differ in channel count — sound-generation returns interleaved
stereo, TTS returns mono — so the PCM handling cannot be shared.

These are original recordings in the style of an arena-shooter announcer, not
lifted from any game.

  python tools/generate_voice.py            # dry run: prints the plan
  python tools/generate_voice.py --go       # actually spend credits
  python tools/generate_voice.py --go --force --env Y:\\aeldenmoor\\.env

Billed per character, so the whole set is a rounding error against the pool.
"""
import argparse
import array
import math
import os
import sys
import wave
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_sfx import load_key                      # noqa: E402

# This machine's AV re-signs HTTPS with a root Python 3.14 rejects as malformed.
urllib3.disable_warnings()

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / 'assets' / 'sfx'
# 24 kHz, not 44.1: pcm_44100 is gated behind the Pro tier, and 24 kHz is
# more than enough for a short spoken line. winsound plays any rate.
SR = 24000
PEAK = 0.82              # same headroom as the gunshots, so nothing jumps out

# "Harry - Fierce Warrior", the roughest male voice on the account. Pitched
# down hard below, which is also why its youth stops mattering: what survives
# the shift is the rasp, which is the part worth keeping.
VOICE_ID = 'SOYHLrjzK2X1ezoPC6cr'
ENDPOINT = f'https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}'

# Low stability makes the read more theatrical; the exaggeration is the point
# for an announcer, where a neutral delivery sounds like a phone menu.
VOICE_SETTINGS = {
    'stability': 0.35,
    'similarity_boost': 0.75,
    'style': 0.65,
    'use_speaker_boost': True,
    # Slightly under a normal read. Pitching down by resampling already
    # stretches the clip by 1/PITCH; this adds to it rather than cancelling
    # it, because the weight of the delivery is the point here.
    'speed': 0.95,
}

# Post-processing. The raw read is a normal speaking voice; an arena announcer
# is deeper and lives in a big room. Both are done here rather than asked of
# the model, because pitch and reverb are exactly the things TTS will not give
# you consistently across separate generations.
PITCH = 0.62             # playback rate; below 1.0 deepens and slows the read
DRIVE = 3.2              # soft-clip amount; higher is grittier and more shouted
ECHO_MS = 95             # first repeat, in milliseconds
ECHO_DECAY = 0.5         # level of each repeat relative to the one before
ECHO_REPEATS = 3         # taps after the dry signal

# (filename, spoken text, per-line voice-setting overrides)
#
# Punctuation is doing real work here. An exclamation mark makes the model
# lift at the end of the line; a full stop makes it fall away. Multi and Ultra
# read better landing low, while Double and Monster want the lift.
#
# Regenerating is not idempotent — the same request comes back with a slightly
# different read every time — so once a line is right, leave it alone and use
# --only to work on the others.
# `pitch` overrides the global PITCH for that line; everything else is passed
# through to the model as a voice setting. Length runs as 1/(pitch x speed),
# so the two are adjusted together to change tone without changing pace.
LINES = [
    ('DoubleKill', 'Double kill!', {'speed': 1.00, 'pitch': 0.59}),
    # Stability raised for the same reason as Ultra, and then some: at 0.35
    # the slow read kept dropping into creak, landing this line a whole octave
    # below the others (75Hz against ~152Hz) rather than merely deeper.
    ('MultiKill', 'Multi kill...', {'speed': 0.83, 'stability': 0.65}),
    # Higher stability than the rest. The low-stability read is expressive but
    # inconsistent between takes, and this line kept lifting on the last
    # syllable; a flatter delivery stays down where the ellipsis puts it.
    # The shipped file was re-pitched from a 0.65 take down to 141Hz, to sit a
    # step below Multi so the ladder falls twice and then lifts into Monster.
    # 0.58 is the equivalent factor, but a fresh take will not land on exactly
    # the same frequency — check it against the others before shipping one.
    ('UltraKill', 'Ultra kill...', {'speed': 0.86, 'pitch': 0.58,
                                    'stability': 0.62}),
    ('MonsterKill', 'Monster kill!', {}),
]


def pitch_down(samples, factor):
    """Resample so the voice sits `factor` times lower.

    Reading the source at a fractional step and writing more samples than came
    in scales every frequency by `factor` and stretches the clip to match. It
    slows the delivery as well as deepening it, which for an announcer is the
    right trade — a slower read lands heavier.
    """
    length = int(len(samples) / factor)
    out = array.array('h', bytes(2 * length))
    for i in range(length):
        pos = i * factor
        j = int(pos)
        if j + 1 >= len(samples):
            break
        # Linear interpolation between neighbours; nearest-sample resampling
        # of speech is audibly gritty.
        out[i] = int(samples[j] + (samples[j + 1] - samples[j]) * (pos - j))
    return out


def time_stretch(samples, rate, sr):
    """Change duration by `rate` without moving pitch. rate < 1 shortens.

    Resampling cannot be used here: it changes speed and pitch together, and
    pitch is the thing that has to stay put. Instead overlapping windowed
    segments are laid back down at a different spacing, so the waveform's
    periodicity — and therefore its pitch — is untouched while the timeline
    shifts underneath it.

    Each segment is aligned against the waveform the previous one predicts
    (WSOLA) rather than taken at a fixed stride. Without that search the
    segments join out of phase and speech comes out warbling.
    """
    win_len = int(sr * 0.040) // 2 * 2          # ~40ms, even
    syn_hop = win_len // 2
    ana_hop = max(1, int(syn_hop / rate))
    # The search has to be able to slide a whole pitch period, or it locks
    # part-way into one and shortens it — which shows up as the voice drifting
    # sharp. 8ms covers a period down to 125Hz, below anything here.
    search = int(sr * 0.008)
    window = [0.5 - 0.5 * math.cos(2 * math.pi * i / (win_len - 1))
              for i in range(win_len)]

    total = int(len(samples) * rate) + win_len
    acc = [0.0] * total
    weight = [0.0] * total
    ana = syn = 0
    predicted = None

    while ana + win_len + search < len(samples) and syn + win_len < total:
        if predicted is None:
            best = ana
        else:
            best, best_score = ana, None
            for offset in range(-search, search + 1):
                pos = ana + offset
                if pos < 0 or pos + win_len > len(samples):
                    continue
                # Stride 4: the correlation only has to rank candidates, but
                # too coarse a stride aliases and picks the wrong alignment.
                score = sum(samples[pos + i] * predicted[i]
                            for i in range(0, win_len, 4))
                if best_score is None or score > best_score:
                    best_score, best = score, pos
        for i in range(win_len):
            acc[syn + i] += samples[best + i] * window[i]
            weight[syn + i] += window[i]
        tail = best + syn_hop
        predicted = samples[tail:tail + win_len]
        if len(predicted) < win_len:
            break
        ana += ana_hop
        syn += syn_hop

    out = array.array('h', bytes(2 * syn))
    for i in range(syn):
        value = acc[i] / weight[i] if weight[i] > 1e-6 else 0.0
        out[i] = max(-32768, min(32767, int(value)))
    return out


def saturate(samples, drive=DRIVE):
    """Soft-clip the waveform to add harmonic grit.

    tanh rounds the peaks rather than shearing them flat, which reads as a
    voice pushed too hard through a PA instead of as digital clipping. Applied
    to the dry signal only — running it after the echo would grind the tails
    up as well and turn the tail into noise.
    """
    out = array.array('h', bytes(2 * len(samples)))
    ceiling = math.tanh(drive)
    for i, value in enumerate(samples):
        shaped = math.tanh(drive * (value / 32768.0)) / ceiling
        out[i] = int(max(-1.0, min(1.0, shaped)) * 32767)
    return out


def add_echo(samples, sr, delay_ms=ECHO_MS, decay=ECHO_DECAY, repeats=ECHO_REPEATS):
    """Layer decaying repeats over the dry signal.

    A multi-tap delay rather than real reverb: cheap, stdlib-only, and for a
    short shouted line it reads as the same big empty room.
    """
    delay = max(1, int(sr * delay_ms / 1000))
    out = array.array('h', bytes(2 * (len(samples) + delay * repeats)))
    for i, value in enumerate(samples):
        out[i] = value
    for tap in range(1, repeats + 1):
        gain = decay ** tap
        offset = delay * tap
        for i, value in enumerate(samples):
            mixed = out[i + offset] + int(value * gain)
            out[i + offset] = max(-32768, min(32767, mixed))
    return out


def split_overrides(overrides):
    """Separate a line's post-processing settings from its voice settings."""
    voice = dict(overrides or {})
    return voice.pop('pitch', PITCH), voice


def to_mono_wav(pcm, path, pitch=PITCH):
    """Write mono 16-bit PCM out as a peak-normalised WAV.

    TTS returns mono already, so unlike the sound-effect path there is nothing
    to downmix. The voice is pitched down and given a tail on the way through.
    """
    samples = array.array('h')
    samples.frombytes(pcm[:len(pcm) // 2 * 2])

    # Deepen first, then place it in the room; echoing a thin voice and then
    # pitching the result down would drag the tails out with it.
    samples = pitch_down(samples, pitch)
    samples = saturate(samples)
    samples = add_echo(samples, SR)

    peak = max((abs(s) for s in samples), default=1) or 1
    gain = (PEAK * 32767) / peak
    for i, value in enumerate(samples):
        samples[i] = max(-32768, min(32767, int(value * gain)))

    with wave.open(str(path), 'wb') as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(samples.tobytes())
    return len(samples) / SR


def speak(key, text, overrides=None):
    """POST one line to the text-to-speech endpoint, returning raw PCM."""
    settings = dict(VOICE_SETTINGS, **(overrides or {}))
    response = requests.post(
        ENDPOINT,
        headers={'xi-api-key': key, 'Content-Type': 'application/json'},
        params={'output_format': 'pcm_24000'},
        json={'text': text,
              'model_id': 'eleven_multilingual_v2',
              'voice_settings': settings},
        verify=False,
        timeout=120,
    )
    if response.status_code != 200:
        sys.exit(f"API error {response.status_code}: {response.text[:300]}")
    return response.content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go', action='store_true',
                        help='actually call the API (default is a dry run)')
    parser.add_argument('--force', action='store_true',
                        help='regenerate lines that already exist')
    parser.add_argument('--env', help='path to a .env holding ELEVENLABS_API_KEY')
    parser.add_argument('--only', help='comma-separated line names to regenerate')
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {n.strip() for n in args.only.split(',')} if args.only else None
    if wanted:
        unknown = wanted - {c[0] for c in LINES}
        if unknown:
            sys.exit(f"Unknown line(s): {', '.join(sorted(unknown))}")
    pending = [c for c in LINES
               if (wanted is None or c[0] in wanted)
               and (args.force or not (OUT_DIR / f'{c[0]}.wav').exists())]

    print(f"  {len(pending)} line(s), voice {VOICE_ID}\n")
    for name, text, over in pending:
        pitch, voice = split_overrides(over)
        print(f"    {name:<12} {text!r:<18} pitch {pitch}"
              f"  speed {voice.get('speed', VOICE_SETTINGS['speed'])}")
    if not pending:
        print("  Nothing to do (pass --force to regenerate).")
        return 0
    if not args.go:
        print("\n  Dry run. Re-run with --go to spend credits.")
        return 0

    key = load_key(args.env)
    print()
    for name, text, over in pending:
        pitch, voice = split_overrides(over)
        length = to_mono_wav(speak(key, text, voice), OUT_DIR / f'{name}.wav', pitch)
        print(f"    saved {name}.wav  ({length:.2f}s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
