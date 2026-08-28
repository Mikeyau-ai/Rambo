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

# "Adam - Dominant, Firm". Picked from the account's voices as the closest to
# an arena announcer: deep and declarative rather than warm or conversational.
VOICE_ID = 'pNInz6obpgDQGcFmaJgB'
ENDPOINT = f'https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}'

# Low stability makes the read more theatrical; the exaggeration is the point
# for an announcer, where a neutral delivery sounds like a phone menu.
VOICE_SETTINGS = {
    'stability': 0.35,
    'similarity_boost': 0.75,
    'style': 0.65,
    'use_speaker_boost': True,
}

LINES = [
    ('DoubleKill', 'Double kill!'),
    ('MultiKill', 'Multi kill!'),
]


def to_mono_wav(pcm, path):
    """Write mono 16-bit PCM out as a peak-normalised WAV.

    TTS returns mono already, so unlike the sound-effect path there is nothing
    to downmix — only the level to match.
    """
    samples = array.array('h')
    samples.frombytes(pcm[:len(pcm) // 2 * 2])

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


def speak(key, text):
    """POST one line to the text-to-speech endpoint, returning raw PCM."""
    response = requests.post(
        ENDPOINT,
        headers={'xi-api-key': key, 'Content-Type': 'application/json'},
        params={'output_format': 'pcm_24000'},
        json={'text': text,
              'model_id': 'eleven_multilingual_v2',
              'voice_settings': VOICE_SETTINGS},
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
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pending = [c for c in LINES
               if args.force or not (OUT_DIR / f'{c[0]}.wav').exists()]

    print(f"  {len(pending)} line(s), voice {VOICE_ID}\n")
    for name, text in pending:
        print(f"    {name:<12} {text!r}")
    if not pending:
        print("  Nothing to do (pass --force to regenerate).")
        return 0
    if not args.go:
        print("\n  Dry run. Re-run with --go to spend credits.")
        return 0

    key = load_key(args.env)
    print()
    for name, text in pending:
        length = to_mono_wav(speak(key, text), OUT_DIR / f'{name}.wav')
        print(f"    saved {name}.wav  ({length:.2f}s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
