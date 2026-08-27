"""Generate RamBo's kill-feedback sound effects via the ElevenLabs API.

Writes 44100 Hz mono 16-bit WAV into assets/sfx/, which is the format
winsound.PlaySound wants and what sounds.py loads at runtime.

Build-time only — the generated WAVs are committed, so nothing here ships
inside the app and RamBo keeps its stdlib-plus-psutil runtime.

  python tools/generate_sfx.py            # dry run: prints the plan and cost
  python tools/generate_sfx.py --go       # actually spend credits
  python tools/generate_sfx.py --go --only gunshot

The key is read from $ELEVENLABS_API_KEY, or from a local .env (gitignored).
It is deliberately never written into this repo.

Cost is about 10 credits per second of audio, so the full set below is
roughly 50 credits out of the monthly pool.
"""
import argparse
import array
import os
import sys
import wave
from pathlib import Path

import requests
import urllib3

# This machine's AV re-signs HTTPS with a root that Python 3.14's OpenSSL
# rejects as malformed, so certificate verification cannot succeed here.
# Same workaround the Aeldenmoor audio tools use.
urllib3.disable_warnings()

ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / 'assets' / 'sfx'
ENDPOINT = 'https://api.elevenlabs.io/v1/sound-generation'
SR = 44100
PEAK = 0.82          # same headroom the Aeldenmoor SFX are normalised to

# Several takes per outcome so repeated kills do not sound like a loop.
# Short and dry on purpose: this is UI feedback, not a game world.
CLIPS = [
    ('gunshot', 'Gunshot_01', 0.8, 'single dry pistol gunshot, close mic, punchy, anechoic, no reverb'),
    ('gunshot', 'Gunshot_02', 0.8, 'sharp rifle shot crack, tight transient, very short tail, no reverb'),
    ('gunshot', 'Gunshot_03', 0.9, 'shotgun blast, deep and punchy, fast decay, dry studio recording'),
    ('blocked', 'Ricochet_01', 0.9, 'bullet ricochet off thick steel plate, metallic whine, dry, short'),
    ('blocked', 'Ricochet_02', 0.8, 'bullet deflecting off armour plating, dull metallic clank, no reverb'),
    ('blocked', 'Ricochet_03', 0.9, 'bullet ricochet spark off stone, high pitched whizz away, dry'),
]


def load_key(env_path=None):
    """Return the API key from $ELEVENLABS_API_KEY or a .env file, else exit.

    --env exists so the key can be read straight out of an existing .env
    elsewhere on the machine rather than being copied into this repo.
    """
    key = os.environ.get('ELEVENLABS_API_KEY')
    if key:
        return key.strip()
    for candidate in ([Path(env_path)] if env_path else []) + [ROOT / '.env']:
        if candidate.exists():
            for line in candidate.read_text(encoding='utf-8').splitlines():
                if line.startswith('ELEVENLABS_API_KEY'):
                    return line.split('=', 1)[1].strip()
    sys.exit("ELEVENLABS_API_KEY not set (environment, --env, or ./.env)")


def to_mono_wav(pcm_stereo, path):
    """Downmix raw 16-bit stereo PCM to a peak-normalised mono WAV file.

    Done with the array module rather than numpy so this tool adds no build
    dependency for the sake of a few seconds of audio.
    """
    samples = array.array('h')
    samples.frombytes(pcm_stereo[:len(pcm_stereo) // 4 * 4])

    mono = array.array('h', bytes(len(samples)))       # half as many frames
    peak = 1
    for i in range(0, len(samples), 2):
        avg = (samples[i] + samples[i + 1]) // 2
        mono[i // 2] = avg
        peak = max(peak, abs(avg))

    # Normalise to a consistent level; without this the takes land at wildly
    # different loudness and the quiet ones are inaudible over a game.
    gain = (PEAK * 32767) / peak
    for i, value in enumerate(mono):
        mono[i] = max(-32768, min(32767, int(value * gain)))

    with wave.open(str(path), 'wb') as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(mono.tobytes())
    return len(mono) / SR


def generate(key, text, duration):
    """POST one prompt to the sound-generation endpoint.

    Returns (raw stereo PCM bytes, credit cost). pcm_44100 is requested rather
    than the default mp3 so the result needs no decoder to turn into a WAV.
    """
    response = requests.post(
        ENDPOINT,
        headers={'xi-api-key': key, 'Content-Type': 'application/json'},
        params={'output_format': 'pcm_44100'},
        json={'text': text, 'duration_seconds': duration,
              'prompt_influence': 0.6, 'loop': False},
        verify=False,
        timeout=120,
    )
    if response.status_code != 200:
        sys.exit(f"API error {response.status_code}: {response.text[:300]}")
    return response.content, int(response.headers.get('character-cost', 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go', action='store_true',
                        help='actually call the API (default is a dry run)')
    parser.add_argument('--only', help='generate one group only: gunshot | blocked')
    parser.add_argument('--force', action='store_true',
                        help='regenerate clips that already exist')
    parser.add_argument('--env', help='path to a .env holding ELEVENLABS_API_KEY')
    args = parser.parse_args()

    clips = [c for c in CLIPS if not args.only or c[0] == args.only]
    if not clips:
        sys.exit(f"No clips in group {args.only!r}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pending = [c for c in clips
               if args.force or not (OUT_DIR / f'{c[1]}.wav').exists()]

    print(f"  {len(pending)} clip(s) to generate,"
          f" ~{sum(c[2] for c in pending) * 10:.0f} credits estimated\n")
    for _, name, duration, text in pending:
        print(f"    {name:<14} {duration}s  {text}")

    if not pending:
        print("  Nothing to do (pass --force to regenerate).")
        return 0
    if not args.go:
        print("\n  Dry run. Re-run with --go to spend credits.")
        return 0

    key = load_key(args.env)
    total = 0
    print()
    for _, name, duration, text in pending:
        pcm, cost = generate(key, text, duration)
        length = to_mono_wav(pcm, OUT_DIR / f'{name}.wav')
        total += cost
        print(f"    saved {name}.wav  ({length:.2f}s, {cost} credits)")
    print(f"\n  Total: {total} credits")
    return 0


if __name__ == '__main__':
    sys.exit(main())
