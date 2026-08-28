"""
sounds.py — kill-feedback audio for RamBo.

A gunshot when a process actually dies, a ricochet when it survives, so the
outcome of a kill is audible without reading the status bar.

Stdlib only: winsound ships with CPython on Windows and plays a 16-bit PCM
WAV asynchronously, which is all this needs. No mixer, no extra dependency,
nothing new in the PyInstaller bundle beyond the WAV files themselves.

Public API: play_kill(), play_blocked(), play_streak().
"""
import os
import random
import sys
import winsound

# Several takes per outcome, chosen at random, so killing a dozen processes
# does not turn into the same click repeating.
_VARIANTS = {
    'kill':    ('Gunshot_01.wav', 'Gunshot_02.wav', 'Gunshot_03.wav'),
    'blocked': ('Ricochet_01.wav', 'Ricochet_02.wav', 'Ricochet_03.wav'),
    # One take each. An announcer is meant to be recognisable, so unlike the
    # gunshots these deliberately do not vary.
    'double':  ('DoubleKill.wav',),
    'multi':   ('MultiKill.wav',),
}

# Last variant played per group, so the same take is never heard twice running.
_last = {}


def _sfx_dir():
    """assets/sfx, both from source and from inside a PyInstaller bundle."""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'assets', 'sfx')


def _play(group):
    """Play a random take from `group`, never raising.

    Audio is cosmetic feedback layered on top of killing processes: a missing
    file, a machine with no sound device, or a locked audio session must not
    turn into an error dialog on top of a kill that otherwise worked.
    """
    names = _VARIANTS.get(group)
    if not names:
        return

    # Avoid an immediate repeat, but only when there is something else to pick.
    choices = [n for n in names if n != _last.get(group)] or list(names)
    name = random.choice(choices)
    _last[group] = name

    path = os.path.join(_sfx_dir(), name)
    try:
        # ASYNC so the UI thread does not block for the length of the clip;
        # NODEFAULT so a missing file is silent rather than the Windows beep.
        winsound.PlaySound(
            path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


def play_kill():
    """Gunshot — one or more processes were successfully killed."""
    _play('kill')


def play_blocked():
    """Ricochet — the kill was refused, denied, or the process was already gone."""
    _play('blocked')


def play_streak(level):
    """Announce a kill streak. `level` is 'double' or 'multi'.

    Called on a delay rather than straight after the gunshot: winsound plays
    one sound at a time, so an immediate second call would cut the gunshot off
    mid-shot instead of layering over it."""
    _play(level)
