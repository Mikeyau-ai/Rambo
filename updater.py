"""
updater.py — self-update for installed (frozen) RamBo builds.

Checks GitHub Releases for a newer RamBo.zip, downloads it, and swaps it over
the install directory via a detached helper script, because a running exe
cannot overwrite itself.

Only ever active in a frozen build — running from source, `is_enabled()` is
False, so dev sessions never see an update prompt. A source tree's version can
legitimately be ahead of the published release, and copying over it would
clobber the working copy.

Stdlib only (urllib/json/threading/zipfile), deliberately: this module ships
inside the PyInstaller bundle and must not add anything to requirements.txt.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

# The public GitHub repo whose Releases host the build. Must be PUBLIC — the
# client checks anonymously and a private repo 404s without a token.
# publish_github.py imports this so there's a single source of truth.
GITHUB_REPO = os.getenv('RAMBO_UPDATE_REPO', 'Mikeyau-ai/Rambo')

_API_LATEST = f'https://api.github.com/repos/{GITHUB_REPO}/releases/latest'
_ASSET_NAME = 'RamBo.zip'
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
    url: str            # direct .zip asset download URL
    size: int           # asset size in bytes (0 if GitHub didn't report one)
    notes: str          # release body, shown as a short changelog

    @property
    def size_mb(self):
        return self.size / (1024 * 1024)

    def note_lines(self):
        """The release body as plain-text bullets for a Tk message box."""
        out = []
        for raw in (self.notes or '').splitlines():
            line = raw.strip().lstrip('-*').strip()
            line = line.replace('**', '').replace('__', '').replace('`', '')
            if not line or line.lower().startswith('rambo v'):
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


def is_check_done():
    """True once the background check has finished (or never started)."""
    return _done.is_set()


def wait_for_result(timeout=0.0):
    """The pending update, or None. Waits up to `timeout` seconds."""
    _done.wait(timeout)
    return _result


def skip_version(version):
    """Remember that the user declined this version, so it isn't re-offered."""
    _save_setting('update_skip_version', version)


# ── Download + apply ───────────────────────────────────────────────────────────
def download(info, progress_cb=None, cancel=None):
    """Download the release zip, returning its path or None on failure.

    `progress_cb(done_bytes, total_bytes)` is called as chunks arrive and
    `cancel()` is polled per chunk, so the UI can show progress and bail out.
    Leaves no partial zip behind."""
    _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _UPDATE_DIR / f'RamBo-{info.version}.zip'
    part = dest.with_suffix('.zip.part')

    # Don't accumulate a copy of every update ever downloaded.
    for old in _UPDATE_DIR.glob('RamBo-*.zip'):
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


def _stage(zip_path):
    """Extract the zip and return the folder holding the new RamBo.exe."""
    staging = _UPDATE_DIR / 'staging'
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging)
    except (zipfile.BadZipFile, OSError):
        return None
    # The archive is built with a top-level RamBo/ folder, but tolerate a flat
    # one in case the release was packaged by hand.
    inner = staging / 'RamBo'
    root = inner if (inner / 'RamBo.exe').exists() else staging
    return root if (root / 'RamBo.exe').exists() else None


# The swap has to outlive us: a running exe can't overwrite itself, so a detached
# cmd waits for this process to exit, copies the new files in, and relaunches.
# Every tool is called by absolute path. A user with Git-for-Windows or similar
# on PATH can otherwise shadow `find` with the Unix one, which silently breaks
# the wait loop and copies over the app while it is still running.
_APPLY_SCRIPT = """@echo off
setlocal
set "TASKLIST=%SystemRoot%\\System32\\tasklist.exe"
set "FIND=%SystemRoot%\\System32\\find.exe"
set "PING=%SystemRoot%\\System32\\ping.exe"
set "ROBOCOPY=%SystemRoot%\\System32\\robocopy.exe"

rem Wait for RamBo to exit so its files can be replaced. Bounded, so a stuck
rem process leaves the install untouched rather than hanging forever.
set /a tries=0
:wait
"%TASKLIST%" /fi "PID eq {pid}" /nh 2>nul | "%FIND%" "{pid}" >nul
if errorlevel 1 goto ready
set /a tries+=1
if %tries% GEQ 60 (
  echo RamBo did not exit; update cancelled.
  pause
  exit /b 1
)
"%PING%" -n 2 127.0.0.1 >nul
goto wait

:ready
"%ROBOCOPY%" "{src}" "{dst}" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo RamBo update failed to copy files.
  pause
  exit /b 1
)
start "" "{exe}"
rmdir /s /q "{staging}"
"""


def apply(zip_path):
    """Stage the update and launch the detached swap script.

    Returns True once the helper is running, at which point the caller must
    exit immediately so its files can be replaced."""
    src = _stage(zip_path)
    if src is None:
        return False

    dst = install_dir()
    script = _UPDATE_DIR / 'apply_update.cmd'
    try:
        script.write_text(_APPLY_SCRIPT.format(
            pid=os.getpid(), src=src, dst=dst,
            exe=dst / 'RamBo.exe', staging=_UPDATE_DIR / 'staging'),
            encoding='utf-8')
        subprocess.Popen(
            ['cmd', '/c', str(script)],
            close_fds=True,
            creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0)
                          | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
                          | getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return True
    except OSError:
        return False
