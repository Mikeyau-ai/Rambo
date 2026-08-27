"""
updater.py — self-update for installed (frozen) RamBo builds.

Checks GitHub Releases for a newer RamBo-Setup.exe, downloads it, then runs it
silently and exits. The freshly-installed build relaunches RamBo itself, via
the installer.iss [Run] entry — the `skipifsilent` flag is deliberately absent
there so a /SILENT install still launches the app at the end.

This replaced an older scheme that unzipped a release over the install
directory with robocopy. That was right while RamBo shipped as a portable zip,
but it is wrong for an installed build: it leaves the version in Apps &
Features stale and writes files the uninstaller has no record of. Letting Inno
Setup perform the upgrade keeps the install self-consistent.

Only ever active in a frozen build — running from source, `is_enabled()` is
False, so dev sessions never see an update prompt. A source tree's version can
legitimately be ahead of the published release, and copying over it would
clobber the working copy.

Stdlib only (urllib/json/threading), deliberately: this module ships
inside the PyInstaller bundle and must not add anything to requirements.txt.
"""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The public GitHub repo whose Releases host the build. Must be PUBLIC — the
# client checks anonymously and a private repo 404s without a token.
# publish_github.py imports this so there's a single source of truth.
GITHUB_REPO = os.getenv('RAMBO_UPDATE_REPO', 'Mikeyau-ai/Rambo')

_API_LATEST = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
_ASSET_NAME = 'RamBo-Setup.exe'
_USER_AGENT = 'RamBo-Updater'
_CHECK_TIMEOUT = 8      # seconds — backgrounded, but don't hang forever

USER_ROOT = Path(os.getenv('LOCALAPPDATA', Path.home())) / 'RamBo'
_UPDATE_DIR = USER_ROOT / 'updates'
_SETTINGS = USER_ROOT / 'settings.json'


# ── Settings (two keys; not worth a module of its own) ─────────────────────────
def _load_settings():
    try:
        with open(_SETTINGS, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_setting(key, value):
    data = _load_settings()
    data[key] = value
    try:
        USER_ROOT.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass


# ── Version helpers ────────────────────────────────────────────────────────────
def _parse_version(text):
    """Turn 'v1.2.3' / '1.2.3' into (1, 2, 3) for ordered comparison.

    Non-numeric junk yields (0,) so a malformed tag always compares as older
    than a real version rather than spuriously triggering an update."""
    nums = re.findall(r'\d+', text or '')
    return tuple(int(n) for n in nums) if nums else (0,)


def current_version():
    """The running build's version, read from main.pyw's APP_VERSION."""
    try:
        from __main__ import APP_VERSION
        return APP_VERSION
    except Exception:
        try:
            from main import APP_VERSION      # noqa: F401 - source-run fallback
            return APP_VERSION
        except Exception:
            return '0.0.0'


def install_dir():
    """The directory holding RamBo.exe (only meaningful in a frozen build)."""
    return Path(sys.executable).resolve().parent


def is_enabled():
    """True only for installed builds with the update check left switched on."""
    if not getattr(sys, 'frozen', False):
        return False
    return bool(_load_settings().get('update_check', True))


# ── Update info ────────────────────────────────────────────────────────────────
@dataclass
class UpdateInfo:
    """A newer release found on GitHub, ready to download."""
    version: str        # '1.2.3' (tag with any leading 'v' stripped)
    url: str            # direct installer download URL
    size: int           # asset size in bytes (0 if GitHub didn't report one)
    notes: str          # release body, shown as a short changelog

    @property
    def size_mb(self):
        return self.size / (1024 * 1024)

    def note_lines(self):
        """The changelog as plain-text bullets for a Tk message box.

        publish_github.py puts the standing install/SmartScreen boilerplate
        below a `---` rule, so stop there: the update prompt should say what
        changed, not repeat instructions the user has already followed."""
        out = []
        for raw in (self.notes or '').splitlines():
            line = raw.strip()
            if line.startswith('---'):
                break
            if line.startswith('#'):            # section headings
                continue
            line = line.lstrip('-*').strip()
            line = line.replace('**', '').replace('__', '').replace('`', '')
            if not line:
                continue
            out.append(line)
        return out[:12]


def _fetch_latest():
    """Query the GitHub Releases API for the newest release, or None.

    Returns None (never raises) for every failure mode — offline, rate-limited,
    repo not yet created, release missing its asset. A silent no-op is right:
    an update check must never block or break launching the app."""
    req = urllib.request.Request(
        _API_LATEST,
        headers={'User-Agent': _USER_AGENT,
                 'Accept': 'application/vnd.github+json'})
    try:
        with urllib.request.urlopen(req, timeout=_CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None

    tag = (data.get('tag_name') or '').lstrip('vV')
    if not tag:
        return None
    for asset in data.get('assets') or []:
        if (asset.get('name') or '').lower() == _ASSET_NAME.lower():
            return UpdateInfo(version=tag,
                              url=asset.get('browser_download_url') or '',
                              size=int(asset.get('size') or 0),
                              notes=(data.get('body') or '').strip())
    return None


def _is_newer(info):
    """True if `info` is a version the user hasn't got and hasn't skipped."""
    if _parse_version(info.version) <= _parse_version(current_version()):
        return False
    return _load_settings().get('update_skip_version') != info.version


# ── Background check ───────────────────────────────────────────────────────────
_result = None
_done = threading.Event()


def start_check():
    """Kick off the version check on a daemon thread. Safe to call always —
    no-ops when updates are disabled or we're running from source."""
    if not is_enabled():
        _done.set()
        return

    def _work():
        global _result
        try:
            info = _fetch_latest()
            if info and info.url and _is_newer(info):
                _result = info
        finally:
            _done.set()

    threading.Thread(target=_work, daemon=True, name='update-check').start()


def check_now():
    """The explicit "check for updates" path: a newer release, or None.

    Unlike start_check() this ignores the auto-check setting and any version
    the user previously skipped, and it runs synchronously. The user asked, so
    answer — but call it off the UI thread, since it makes a network request.
    """
    info = _fetch_latest()
    if info and info.url and _parse_version(info.version) > _parse_version(
            current_version()):
        return info
    return None


def is_check_done():
    """True once the background check has finished (or never started)."""
    return _done.is_set()


def wait_for_result(timeout=0.0):
    """The pending update, or None. Waits up to `timeout` seconds."""
    _done.wait(timeout)
    return _result


def mark_updating(version):
    """Record the version we are restarting into, so the new build can say so.

    Written just before the installer is launched. The updated build reads it
    back on its first run — without this it has no way to know it arrived by
    update rather than by an ordinary launch."""
    _save_setting('updated_to', version)


def take_update_notice():
    """The version we just updated into, once, or None.

    Cleared on read so the message shows on the first launch after an update
    and not on every launch thereafter. The version has to match the running
    build: if the install did not actually land, there is nothing to announce.
    """
    version = _load_settings().get('updated_to')
    if not version:
        return None
    _save_setting('updated_to', None)
    return version if version == current_version() else None


def skip_version(version):
    """Remember that the user declined this version, so it isn't re-offered."""
    _save_setting('update_skip_version', version)


# ── Download + apply ───────────────────────────────────────────────────────────
def download(info, progress_cb=None, cancel=None):
    """Download the release installer, returning its path or None on failure.

    `progress_cb(done_bytes, total_bytes)` is called as chunks arrive and
    `cancel()` is polled per chunk, so the UI can show progress and bail out.
    Leaves no partial download behind."""
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UPDATE_DIR / f'RamBo-Setup-{info.version}.exe'
    part = dest.with_suffix('.exe.part')

    # Don't accumulate a copy of every update ever downloaded.
    for old in _UPDATE_DIR.glob('RamBo-Setup-*.exe'):
        if old != dest:
            try:
                old.unlink()
            except OSError:
                pass

    req = urllib.request.Request(info.url, headers={'User-Agent': _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get('Content-Length') or info.size or 0)
            got = 0
            with open(part, 'wb') as fh:
                while True:
                    if cancel is not None and cancel():
                        raise InterruptedError('cancelled')
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if progress_cb:
                        progress_cb(got, total)
    except Exception:
        part.unlink(missing_ok=True)
        return None

    # Only publish the final name once every byte is on disk, so an interrupted
    # download can never be mistaken for a complete one.
    try:
        dest.unlink(missing_ok=True)
        part.rename(dest)
    except OSError:
        part.unlink(missing_ok=True)
        return None
    return dest


def run_installer(path):
    """Launch the downloaded installer silently and detached, then report success.

    The caller must quit immediately afterwards: /CLOSEAPPLICATIONS lets Inno
    shut the running app down so it can replace its files, and the new build's
    [Run] entry relaunches RamBo once the install finishes."""
    try:
        subprocess.Popen(
            [str(path), '/SILENT', '/SUPPRESSMSGBOXES', '/NOCANCEL',
             '/NORESTART', '/CLOSEAPPLICATIONS'],
            close_fds=True,
            creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0)
                          | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
        return True
    except OSError:
        return False
