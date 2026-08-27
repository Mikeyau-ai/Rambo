import tkinter as tk
from tkinter import ttk, messagebox
import psutil
from collections import defaultdict
import threading
import time
import sys
import os
import subprocess
import ctypes
import math
import webbrowser
from ctypes import wintypes

# Resolve resource path — works both from source and frozen (PyInstaller)
def _res(name):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# psutil's Process.ppid() takes a fresh system-wide snapshot per call on
# Windows, so reading it for every process costs seconds. ppid_map() gets the
# whole table in one call. It is private, hence the guarded import and the
# per-process fallback if a future psutil moves it.
try:
    from psutil._pswindows import ppid_map as _ppid_map
except ImportError:
    def _ppid_map():
        """Fallback: {pid: ppid} the slow way."""
        out = {}
        for proc in psutil.process_iter(['pid', 'ppid']):
            try:
                out[proc.pid] = proc.info['ppid'] or 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return out


from startup import scan_startup, set_enabled, StartupAccessError
import updater
import sounds

# Single source of truth for the version; the release scripts parse this.
APP_VERSION = "1.3.0"

# ── Palette ────────────────────────────────────────────────────────────────────
C = {
    'bg':       '#121212',
    'panel':    '#1a1a1a',
    'row':      '#1f1f1f',
    'row_alt':  '#272727',
    'border':   '#2e2e2e',
    'hairline': '#262626',
    'text':     '#dcdcdc',
    'dim':      '#6b6b6b',
    'dimmer':   '#4a4a4a',
    'green':    '#4caf50',
    'red':      '#e05252',
    'yellow':   '#e0a040',
    'orange':   '#e07840',
    'blue':     '#5296e0',
    'purple':   '#b06ed8',
    'select':   '#1e4468',
    'warn':     '#c0392b',
    'chip_on':  '#2a2a2a',
    'chip_off': '#1a1a1a',
    'btn_off':  '#242424',
}

# UI chrome reads better in the system UI face; tabular data stays monospaced.
FONT_UI      = ("Segoe UI", 9)
FONT_UI_BOLD = ("Segoe UI Semibold", 9)
FONT_BTN     = ("Segoe UI Semibold", 9)
FONT_DATA    = ("Consolas", 9)
FONT_HEAD    = ("Segoe UI Semibold", 9)


def shade(hex_colour, factor):
    """Lighten (factor > 1) or darken (factor < 1) a #rrggbb colour."""
    h = hex_colour.lstrip('#')
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return '#%02x%02x%02x' % tuple(
        max(0, min(255, int(v * factor))) for v in rgb)


def lerp(a, b, t):
    """Blend two #rrggbb colours; t=0 gives a, t=1 gives b."""
    a, b = a.lstrip('#'), b.lstrip('#')
    return '#%02x%02x%02x' % tuple(
        round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t)
        for i in (0, 2, 4))


def dark_titlebar(window):
    """Ask DWM for a dark title bar so the frame matches the app (Win10 1809+)."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        flag = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE; 19 is the pre-20H1 spelling.
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(flag), ctypes.sizeof(flag)) == 0:
                break
    except Exception:
        pass


def is_admin():
    """True when the process is running elevated."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Re-launch this app through the UAC 'runas' verb. Returns True if the
    elevated process was started (the caller should then exit)."""
    if getattr(sys, 'frozen', False):
        exe, params = sys.executable, ''
    else:
        # Running from source: re-run this script under the same interpreter.
        exe = sys.executable
        params = '"{}"'.format(os.path.abspath(__file__))
    try:
        # ShellExecuteW returns >32 on success; <=32 is an error code, and 5
        # specifically means the user dismissed the UAC prompt.
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, params, os.path.dirname(exe) or None, 1)
        return rc > 32
    except Exception:
        return False


class HoverButton(tk.Button):
    """Flat accent button with real hover, press and disabled states."""

    def __init__(self, parent, accent, **kw):
        self._accent = accent
        self._hovering = False
        super().__init__(parent, **kw)
        self._sync()
        self.bind("<Enter>",           self._on_enter)
        self.bind("<Leave>",           self._on_leave)
        self.bind("<ButtonPress-1>",   self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_accent(self, colour):
        """Swap the button's accent colour (used by the LIVE toggle)."""
        self._accent = colour
        self._sync()

    def configure(self, cnf=None, **kw):
        """Intercept state changes so the disabled look is ours, not Tk's."""
        state_changed = 'state' in kw
        if state_changed:
            super().configure(state=kw.pop('state'))
        result = super().configure(cnf, **kw) if (cnf or kw) else None
        if state_changed:
            self._sync()
        return result

    config = configure

    def _sync(self):
        """Repaint for the current state / hover combination."""
        if str(self['state']) == tk.DISABLED:
            super().configure(bg=C['btn_off'], fg=C['dimmer'],
                              activebackground=C['btn_off'],
                              disabledforeground=C['dimmer'], cursor='arrow')
        else:
            bg = shade(self._accent, 1.16) if self._hovering else self._accent
            super().configure(bg=bg, fg='#ffffff',
                              activebackground=shade(self._accent, 0.84),
                              cursor='hand2')

    def _on_enter(self, _):
        self._hovering = True
        self._sync()

    def _on_leave(self, _):
        self._hovering = False
        self._sync()

    def _on_press(self, _):
        if str(self['state']) != tk.DISABLED:
            super().configure(bg=shade(self._accent, 0.80))

    def _on_release(self, _):
        self._sync()


# ── Filter chip help ──────────────────────────────────────────────────────────
# Shown on hover. Each entry describes what _find_issues actually tests for,
# so the wording and the detection cannot drift apart unnoticed.
CHIP_HELP = {
    'dupes': """Two or more processes running the same executable.

Main is the top of the tree - its parent is not another copy. Child processes were spawned by it, so killing a Main usually takes the whole application with it.""",

    'hung': """The process owns a visible window that has stopped answering Windows messages - the same state Task Manager calls "Not responding".

Often temporary: an app busy with a long operation recovers on its own.""",

    'zombie': """The process has terminated, but Windows has not released its entry yet - usually because something still holds an open handle to it.

It is running no code and holding no memory.""",

    'suspended': """Every thread in the process is suspended, so it is using no CPU at all.

Normal for Store apps that Windows has parked in the background; worth a look on an ordinary desktop program.""",

    'orphan': """A non-system process whose parent no longer exists, and which has been running for more than 12 hours.

Typically a leftover helper, installer or updater that was never cleaned up.""",

    'system': """Hides Windows components that legitimately run many copies of themselves - svchost.exe, conhost.exe, RuntimeBroker.exe and similar.

Leave this on unless you are deliberately hunting a system process: without it the Duplicates list is mostly Windows.""",
}


class Tooltip:
    """Delayed hover tooltip, styled to match the dark UI.

    Tk ships no tooltip widget. This is a borderless Toplevel placed under the
    target after a short delay, torn down on leave or click. Bindings are added
    with add="+" so they stack on top of whatever the widget already binds.
    """

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._tip is not None or not self.widget.winfo_viewable():
            return
        tip = self._tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)          # no frame, no title bar
        tip.configure(bg=C['border'])          # 1px border via the packing pad
        tk.Label(tip, text=self.text, justify=tk.LEFT, font=FONT_UI,
                 bg=C['panel'], fg=C['text'], padx=10, pady=7,
                 wraplength=330).pack(padx=1, pady=1)
        tip.update_idletasks()

        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        # Nudge back on-screen when the chip sits near the right edge.
        overshoot = (x + tip.winfo_width()) - (self.widget.winfo_screenwidth() - 8)
        if overshoot > 0:
            x -= overshoot
        tip.wm_geometry(f"+{max(8, x)}+{y}")
        try:
            tip.attributes('-topmost', True)
        except tk.TclError:
            pass

    def _hide(self, _=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def load_changelog():
    """CHANGELOG.md from the PyInstaller bundle or the source tree."""
    try:
        with open(_res("CHANGELOG.md"), encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "Changelog not available in this build."


class AboutWindow(tk.Toplevel):
    """About / changelog window, opened from the wordmark in the topbar.

    The changelog is bundled into the build rather than fetched, so it reads
    the same offline as online, and always describes the version in front of
    you instead of whatever is newest on GitHub.
    """

    def __init__(self, app):
        super().__init__(app)
        self._app = app
        self.title("About RamBo")
        self.geometry("620x640")
        self.minsize(460, 420)
        self.configure(bg=C['bg'])
        self.transient(app)
        try:
            self.iconbitmap(_res("icon.ico"))
        except Exception:
            pass
        dark_titlebar(self)

        self._build_header()
        self._build_actions()
        self._build_changelog()

        self.bind("<Escape>", lambda _: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build_header(self):
        head = tk.Frame(self, bg=C['panel'], padx=18, pady=14)
        head.pack(fill=tk.X)
        line = tk.Frame(head, bg=C['panel'])
        line.pack(anchor=tk.W)
        tk.Label(line, text="RAMBO", font=("Consolas", 21, "bold"),
                 bg=C['panel'], fg=C['green']).pack(side=tk.LEFT, anchor=tk.S)
        # Say plainly when this is a dev run: the updater is inert from source,
        # so "no updates" there means something different.
        suffix = "" if getattr(sys, 'frozen', False) else "   (running from source)"
        tk.Label(line, text="  v" + APP_VERSION + suffix, font=FONT_UI,
                 bg=C['panel'], fg=C['dim']).pack(side=tk.LEFT, anchor=tk.S, pady=4)
        tk.Label(head, text="Windows RAM & process cleaner   ·   by Mikey",
                 font=FONT_UI, bg=C['panel'], fg=C['dimmer']).pack(
            anchor=tk.W, pady=(4, 0))

    def _build_actions(self):
        bar = tk.Frame(self, bg=C['bg'], padx=18, pady=12)
        bar.pack(fill=tk.X)
        self._app._mk_btn(bar, "  VIEW ON GITHUB  ", self._open_repo,
                          C['btn_off']).pack(side=tk.LEFT)
        self.check_btn = self._app._mk_btn(bar, "  CHECK FOR UPDATES  ",
                                           self._check_updates, C['blue'])
        self.check_btn.pack(side=tk.LEFT, padx=8)
        self._msg = tk.Label(self, text="", font=FONT_UI, bg=C['bg'],
                             fg=C['dim'], anchor=tk.W, padx=18)
        self._msg.pack(fill=tk.X)

    def _build_changelog(self):
        tk.Label(self, text="CHANGELOG", font=FONT_UI_BOLD, bg=C['bg'],
                 fg=C['dimmer'], anchor=tk.W, padx=18).pack(fill=tk.X, pady=(8, 4))
        wrap = tk.Frame(self, bg=C['bg'])
        wrap.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 14))
        box = tk.Text(wrap, font=FONT_UI, wrap=tk.WORD, bd=0,
                      bg=C['row'], fg=C['text'], padx=12, pady=10,
                      highlightthickness=0, insertwidth=0, cursor="arrow")
        sb = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=box.yview,
                           style="R.Vertical.TScrollbar")
        box.configure(yscrollcommand=sb.set)
        box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

        box.tag_configure("ver", foreground=C['green'],
                          font=("Consolas", 11, "bold"), spacing1=10, spacing3=4)
        box.tag_configure("body", spacing3=3, lmargin1=0, lmargin2=12)
        for raw in load_changelog().splitlines():
            if raw.startswith("# "):                 # the file's own H1
                continue
            if raw.startswith("## "):
                box.insert(tk.END, raw[3:] + "\n", "ver")
            else:
                box.insert(tk.END, raw + "\n", "body")
        box.configure(state=tk.DISABLED)

    def _open_repo(self):
        webbrowser.open(f"https://github.com/{updater.GITHUB_REPO}")

    def _check_updates(self):
        """Manual check. Updates normally install themselves silently, so this
        exists to answer "am I current?" on demand."""
        self.check_btn.config(state=tk.DISABLED, text="  CHECKING...  ")
        self._msg.config(text="Checking GitHub...")

        def _work():
            info = updater.check_now()
            self.after(0, _done, info)

        def _done(info):
            if not self.winfo_exists():
                return
            self.check_btn.config(state=tk.NORMAL, text="  CHECK FOR UPDATES  ")
            if info is None:
                self._msg.config(text=f"You are on the latest version (v{APP_VERSION}).")
                return
            self._msg.config(text=f"v{info.version} found - downloading...")
            self._app._download_update(info, silent=True)

        threading.Thread(target=_work, daemon=True).start()


class FilterChip(tk.Label):
    """Click-to-toggle filter pill — replaces Tk's checkbox, which looks
    out of place on a dark surface."""

    def __init__(self, parent, text, var, colour, command):
        self._var, self._colour, self._command = var, colour, command
        super().__init__(parent, text="  ● " + text + "  ", font=FONT_UI,
                         bd=0, padx=4, pady=4, cursor="hand2")
        self._sync()
        self.bind("<Button-1>", self._toggle)
        self.bind("<Enter>", lambda _: self._sync(hover=True))
        self.bind("<Leave>", lambda _: self._sync())

    def _toggle(self, _):
        self._var.set(not self._var.get())
        self._sync()
        self._command()

    def _sync(self, hover=False):
        on = self._var.get()
        bg = C['chip_on'] if on else C['chip_off']
        if hover:
            bg = shade(bg, 1.35)
        self.configure(bg=bg, fg=self._colour if on else C['dimmer'])

# Windows system processes that legitimately spawn multiple instances.
SYSTEM_NAMES = {
    'svchost.exe', 'conhost.exe', 'runtimebroker.exe', 'dllhost.exe',
    'wermgr.exe', 'backgroundtaskhost.exe', 'taskhostw.exe', 'sihost.exe',
    'ctfmon.exe', 'fontdrvhost.exe', 'dwm.exe', 'csrss.exe', 'lsass.exe',
    'services.exe', 'wininit.exe', 'winlogon.exe', 'audiodg.exe',
    'searchindexer.exe', 'searchprotocolhost.exe', 'searchfilterhost.exe',
    'msmpeng.exe', 'nissrv.exe', 'smartscreen.exe', 'wudfhost.exe',
    'spoolsv.exe', 'system', 'registry', 'memory compression',
    'secure system', 'smss.exe', 'ntoskrnl.exe', 'system interrupts',
    'applicationframehost.exe', 'systemsettingsbroker.exe', 'usocoreworker.exe',
    'wlanext.exe', 'msiexec.exe', 'rundll32.exe', 'regsvr32.exe',
}

ISSUE_ORDER = {
    'Zombie': 0, 'Not Responding': 1, 'Suspended': 2,
    'Dupe · Main': 3, 'Dupe · Child': 4,
    'Orphan': 5,
    '—': 6,   # clean processes sort after all issues
}

# tag → (text colour, row tint).  Only the genuinely broken states get a tint —
# duplicates are the bulk of any scan and would turn the whole list into noise.
TAG_STYLE = {
    'zombie':     ('#e05252', '#2b1616'),
    'hung':       ('#e07840', '#2b2015'),
    'orphan':     ('#b06ed8', '#241b2b'),
    'suspended':  ('#7a7a7a', ''),
    'dup_main':   ('#e0c040', ''),
    'dup_child':  ('#98842a', ''),
    'clean':      ('#dcdcdc', ''),
}

# ── Kill feedback ──────────────────────────────────────────────────────────────
# A killed row flashes hot/cold, fades into the row colour, and only then leaves
# the tree, while the window recoils slightly. Timings are the "Default" preset
# from tools/preview_killfx.py, which exists to re-tune these by eye.
KILL_BLINKS     = 3        # hot/cold flashes before the fade
KILL_BLINK_MS   = 90
KILL_FADE_STEPS = 6        # colour steps from the flash down to the row colour
KILL_FADE_MS    = 45
FLASH_FG        = '#ffffff'
FLASH_BG        = C['warn']
# Live-scan pacing. The gap between ticks is the previous scan's own duration,
# clamped to this range, so a fast machine refreshes briskly and a slow one
# backs off instead of scanning continuously.
LIVE_MIN_MS     = 1500
LIVE_MAX_MS     = 10000

# Tuned to read as a fine vibration rather than a swing: 6px peak-to-peak at
# ~12Hz over ~240ms. Earlier attempts went wrong in both directions — a 19px
# swing reversing at 22Hz made the window look like it was blinking, and
# slowing that to 5Hz just turned it into the window being thrown around.
# Small travel with quick reversal is what gives a kill punch without moving
# the window far. If you raise the frequency, keep the swing small: it was a
# *large* fast oscillation that flickered, not a fast one.
# tools/preview_killfx.py imports these to compare profiles side by side.
SHAKE_PX        = 4        # peak horizontal offset of the recoil; 0 disables it
SHAKE_MS        = 16       # per frame — one frame at 60Hz
SHAKE_FRAMES    = 14       # 14 x 16ms = ~240ms of recoil
SHAKE_CYCLES    = 4.5      # oscillations over that span, i.e. ~12Hz
SHAKE_DECAY     = 0.8      # ring-down exponent; lower rings longer


def shake_path(amp, frames=SHAKE_FRAMES, cycles=SHAKE_CYCLES, decay=SHAKE_DECAY):
    """Damped-sine offsets for the window recoil.

    The first version alternated +amp/-amp on consecutive frames, which flips
    sign about 28 times a second. That is fast enough to land in flicker-fusion
    territory: a window the size of this one square-waving at 28Hz reads as
    blinking rather than moving, which is why the shake looked like the window
    was closing and reopening.

    A damped sine fixes both halves of that. It starts at zero instead of
    teleporting to full amplitude on frame one, and it crosses zero only
    `cycles` times over the whole animation (~5Hz here), so the eye tracks it
    as motion. The vertical component runs at a different frequency and a third
    of the amplitude so the movement is not a straight line.
    """
    path = []
    for i in range(frames):
        t = i / (frames - 1)
        ring = (1.0 - t) ** decay                 # ring down to nothing
        path.append((
            round(amp * ring * math.sin(2 * math.pi * cycles * t)),
            round(amp * ring * math.sin(2 * math.pi * cycles * 1.5 * t) / 3),
        ))
    path.append((0, 0))                           # guarantee an exact landing
    return path


def fmt_mem(b):
    if b < 1024 ** 2:
        return f"{b / 1024:.0f} KB"
    if b < 1024 ** 3:
        return f"{b / 1024 ** 2:.1f} MB"
    return f"{b / 1024 ** 3:.2f} GB"


# ── Hung-window detection (Win32) ──────────────────────────────────────────────
_EnumWinProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32 = ctypes.windll.user32

def get_hung_pids():
    hung = set()
    def _cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _user32.IsHungAppWindow(hwnd):
                hung.add(pid.value)
        return True
    _user32.EnumWindows(_EnumWinProc(_cb), 0)
    return hung


# ── Working-set trim (Win32) ───────────────────────────────────────────────────
_kernel32 = ctypes.windll.kernel32
PROCESS_SET_QUOTA            = 0x0100

_kernel32.SetProcessWorkingSetSizeEx.argtypes = [
    wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD]
_kernel32.SetProcessWorkingSetSizeEx.restype = wintypes.BOOL

def trim_process(pid: int) -> int:
    try:
        before = psutil.Process(pid).memory_info().rss
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0
    handle = _kernel32.OpenProcess(PROCESS_SET_QUOTA, False, pid)
    if not handle:
        return 0
    try:
        if not _kernel32.SetProcessWorkingSetSizeEx(handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0):
            return 0
        try:
            after = psutil.Process(pid).memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            after = before
        return max(0, before - after)
    finally:
        _kernel32.CloseHandle(handle)


# ── App ────────────────────────────────────────────────────────────────────────
class RamBo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RamBo")
        self.geometry("1104x600")
        self.configure(bg=C['bg'])
        self.minsize(828, 440)
        self._scanning      = False
        self._trimming          = False
        self._startup_scanning  = False
        self._startup_results   = []
        self._all_results   = []
        self._proc_static   = {}   # pid → (name, ppid, create_time), immutable
        self._proc_status   = {}   # pid → status, refreshed on full scans only
        self._live          = False
        self._live_after_id = None
        self._last_scan_ms  = 0.0   # drives the adaptive live interval
        self._hover_iid     = None
        self._update_info   = None
        self._row_base      = {}   # iid → severity tag
        self._row_rec       = {}   # iid → the scan record backing that row
        self._row_band      = {}   # iid → is this row on an alternate band
        self._row_vals      = {}   # iid → cell strings last written to the tree
        self._row_tags      = {}   # iid → tag tuple last written to the tree
        self._dying         = set()   # iids mid kill-animation, not yet removed
        self._shaking       = False
        self._filter_pending = False  # a refresh held back by a running animation
        self._logo_img      = None      # kept alive; Tk does not own PhotoImages
        self._init_style()
        self._build_ui()
        try:
            self.iconbitmap(_res("icon.ico"))
        except Exception:
            pass
        self._fit_topbar()
        dark_titlebar(self)
        updater.start_check()
        self.after(1200, self._poll_update)
        # Populate the list without waiting for a click. Deferred rather than
        # called inline so the window paints before the scan thread starts.
        self.after(200, self._start_scan)

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _init_style(self):
        """All ttk styling in one place, applied before any widget is built."""
        style = ttk.Style(self)
        style.theme_use("clam")

        # clam draws light 3D edges by default; flatten them everywhere.
        style.configure("R.Treeview",
                        background=C['row'], foreground=C['text'],
                        fieldbackground=C['row'], rowheight=28,
                        font=FONT_DATA, borderwidth=0, relief=tk.FLAT,
                        bordercolor=C['bg'], lightcolor=C['bg'],
                        darkcolor=C['bg'])
        style.configure("R.Treeview.Heading",
                        background=C['panel'], foreground=C['dim'],
                        font=FONT_HEAD, relief=tk.FLAT, borderwidth=0,
                        padding=(8, 8), bordercolor=C['panel'],
                        lightcolor=C['panel'], darkcolor=C['panel'])
        style.map("R.Treeview",
                  background=[("selected", C['select'])],
                  foreground=[("selected", "#ffffff")])
        style.map("R.Treeview.Heading",
                  background=[("active", C['border'])],
                  foreground=[("active", C['green'])])
        # Minimal scrollbar: trough + thumb, no stepper arrows.
        style.layout("R.Vertical.TScrollbar", [
            ('Vertical.Scrollbar.trough', {'sticky': 'ns', 'children': [
                ('Vertical.Scrollbar.thumb',
                 {'expand': '1', 'sticky': 'nswe'})]})])
        style.configure("R.Vertical.TScrollbar",
                        troughcolor=C['bg'], background=C['border'],
                        bordercolor=C['bg'], darkcolor=C['border'],
                        lightcolor=C['border'], arrowcolor=C['dim'],
                        relief=tk.FLAT, width=10)
        style.map("R.Vertical.TScrollbar",
                  background=[("active", C['dim']), ("pressed", C['dim'])])

        style.configure("R.TNotebook",
                        background=C['bg'], borderwidth=0,
                        bordercolor=C['bg'], lightcolor=C['bg'],
                        darkcolor=C['bg'], tabmargins=[20, 10, 0, 0])
        style.configure("R.TNotebook.Tab",
                        background=C['bg'], foreground=C['dimmer'],
                        font=("Segoe UI Semibold", 10), padding=[18, 8],
                        borderwidth=0, bordercolor=C['bg'],
                        lightcolor=C['bg'], darkcolor=C['bg'])
        style.map("R.TNotebook.Tab",
                  background=[("selected", C['panel']), ("active", C['row_alt'])],
                  foreground=[("selected", C['green']), ("active", C['text'])],
                  lightcolor=[("selected", C['panel'])],
                  bordercolor=[("selected", C['panel'])],
                  darkcolor=[("selected", C['panel'])])

    def _build_ui(self):
        self._build_topbar()
        self._hairline()
        self._build_notebook()
        self._hairline()
        self._build_statusbar()

    def _fit_topbar(self):
        """Never let the window get narrow enough to clip the button row.

        Measured rather than hard-coded, because the row's width changes with
        the ADMIN and UPDATE buttons appearing or not."""
        self.update_idletasks()
        need = self._topbar.winfo_reqwidth() + 24
        self.minsize(max(880, need), 460)
        if self.winfo_width() < need:
            self.geometry(f"{need}x{max(self.winfo_height(), 660)}")

    def _hairline(self):
        """1px divider between the major horizontal bands of the window."""
        tk.Frame(self, bg=C['hairline'], height=1).pack(fill=tk.X)

    def _build_topbar(self):
        bar = tk.Frame(self, bg=C['bg'], pady=14, padx=20)
        bar.pack(fill=tk.X)
        self._topbar = bar

        # App mark, when the PNG shipped alongside the exe is available.
        try:
            self._logo_img = tk.PhotoImage(file=_res("logo.png"))
            tk.Label(bar, image=self._logo_img, bg=C['bg']).pack(
                side=tk.LEFT, padx=(0, 12))
        except Exception:
            self._logo_img = None

        wordmark = tk.Frame(bar, bg=C['bg'])
        wordmark.pack(side=tk.LEFT)
        mark = tk.Label(wordmark, text="RAMBO", font=("Consolas", 21, "bold"),
                        bg=C['bg'], fg=C['green'])
        mark.pack(side=tk.LEFT, anchor=tk.S)
        tag = tk.Label(wordmark, text="  RAM & Process Cleaner", font=FONT_UI,
                       bg=C['bg'], fg=C['dim'])
        tag.pack(side=tk.LEFT, anchor=tk.S, pady=4)
        ver = tk.Label(wordmark, text="  v" + APP_VERSION, font=FONT_UI,
                       bg=C['bg'], fg=C['dimmer'])
        ver.pack(side=tk.LEFT, anchor=tk.S, pady=4)

        # The whole wordmark opens About / Changelog. Brightening the version
        # on hover is what signals it is clickable — there is no other cue.
        for widget in (mark, tag, ver):
            widget.bind("<Button-1>", lambda _: self._show_about())
            widget.configure(cursor="hand2")
            widget.bind("<Enter>", lambda _, v=ver: v.configure(fg=C['text']))
            widget.bind("<Leave>", lambda _, v=ver: v.configure(fg=C['dimmer']))

        btns = tk.Frame(bar, bg=C['bg'])
        btns.pack(side=tk.RIGHT)
        self._btns_frame = btns

        # Pack order with side=RIGHT: last packed = leftmost visually.
        # Result: [SCAN] [LIVE] [KILL CHILDREN] [KILL SELECTED]
        self.kill_btn = self._mk_btn(btns, "⊗  KILL SELECTED",
                                     self._kill_selected, C['red'], state=tk.DISABLED)
        self.kill_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.kill_children_btn = self._mk_btn(btns, "⊗  KILL CHILDREN",
                                              self._kill_children, C['orange'], state=tk.DISABLED)
        self.kill_children_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.trim_sel_btn = self._mk_btn(btns, "✂  TRIM SELECTED",
                                         self._trim_selected, C['blue'], state=tk.DISABLED)
        self.trim_sel_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.trim_all_btn = self._mk_btn(btns, "✂  TRIM RAM",
                                         self._trim_all, C['blue'])
        self.trim_all_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.live_btn = self._mk_btn(btns, "◉  LIVE", self._live_toggle, C['btn_off'])
        self.live_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.scan_btn = self._mk_btn(btns, "▶  SCAN", self._start_scan, C['green'])
        self.scan_btn.pack(side=tk.RIGHT, padx=(6, 0))

        # Hidden until the background check finds a newer release.
        self.update_btn = self._mk_btn(btns, "⬆  UPDATE", self._show_update,
                                       C['purple'])

        # Only offered when it would actually change anything.
        if not is_admin():
            self.elevate_btn = self._mk_btn(btns, "⛨  ADMIN", self._elevate,
                                            C['btn_off'])
            self.elevate_btn.pack(side=tk.RIGHT, padx=(6, 0))

    # ── Self-update ────────────────────────────────────────────────────────────
    def _show_about(self):
        """Open the About / Changelog window, or raise the open one."""
        existing = getattr(self, '_about', None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        self._about = AboutWindow(self)

    def _poll_update(self):
        """Start the update as soon as the background check finds one.

        Polls rather than calling back from the worker thread, because Tk
        widgets may only be touched from the thread that created them."""
        self._update_info = updater.wait_for_result(0)
        if self._update_info:
            # Updates apply themselves — no prompt. The UPDATE button only
            # appears if that fails, as a manual fallback.
            self._download_update(self._update_info, silent=True)
        elif not updater.is_check_done():
            self.after(1500, self._poll_update)

    def _show_update_button(self):
        """Expose the manual UPDATE button, used when the silent path fails."""
        self.update_btn.config(state=tk.NORMAL, text="⬆  UPDATE")
        self.update_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._fit_topbar()

    def _show_update(self):
        """Offer the update explicitly. Only reachable via the fallback button."""
        info = self._update_info
        if not info:
            return
        notes = "\n".join("  • " + line for line in info.note_lines())
        choice = messagebox.askyesnocancel(
            "Update available",
            f"RamBo v{info.version} is available "
            f"(you have v{APP_VERSION}).\n\n"
            f"{notes}\n\n"
            f"Download {info.size_mb:.1f} MB and restart now?\n\n"
            f"Choosing No skips this version.",
            icon="info", parent=self)
        if choice is None:            # Cancel — ask again next launch
            return
        if not choice:                # No — don't offer this version again
            updater.skip_version(info.version)
            self.update_btn.pack_forget()
            self.status_var.set(f"Skipped v{info.version}")
            return
        self._download_update(info)

    def _download_update(self, info, silent=False):
        """Fetch the release installer on a worker thread, reporting progress.

        `silent` is the automatic path: it never opens a dialog, reports
        through the status bar only, and falls back to the manual button if
        anything goes wrong."""
        if not silent:
            self.update_btn.config(state=tk.DISABLED, text="⬆  DOWNLOADING")

        def _progress(done, total):
            pct = (done / total * 100) if total else 0
            self.after(0, self.status_var.set,
                       f"Downloading v{info.version} — {pct:.0f}%")

        def _work():
            path = updater.download(info, progress_cb=_progress)
            self.after(0, _finish, path)

        def _finish(path):
            if path is None:
                self._show_update_button()
                self.status_var.set("Update download failed")
                if not silent:
                    messagebox.showwarning(
                        "Download failed",
                        "Could not download the update.\n\n"
                        "Check your connection, or grab it from the releases page.",
                        parent=self)
                return
            self._install_update(path, silent)

        threading.Thread(target=_work, daemon=True).start()

    def _install_update(self, path, silent=False):
        """Run the installer once the app is idle, then quit so it can proceed.

        Waiting for idle matters on the silent path: an update can land at any
        moment, and closing the app out from under a running scan, a trim or a
        kill animation would look like a crash. Live ticks leave gaps, so this
        never waits long."""
        if self._scanning or self._trimming or self._dying:
            self.after(500, self._install_update, path, silent)
            return
        self.status_var.set("Installing update…")
        if updater.run_installer(path):
            # The installer needs this process gone before it can replace the
            # files; its [Run] entry relaunches RamBo when it finishes.
            self.destroy()
            return
        self._show_update_button()
        self.status_var.set("Update install failed")
        if not silent:
            messagebox.showwarning(
                "Install failed", "The update could not be applied.", parent=self)

    def _elevate(self):
        """Restart elevated so kills and startup edits stop hitting AccessDenied."""
        if not messagebox.askyesno(
                "Restart as administrator",
                "RamBo will close and reopen with administrator rights.\n\n"
                "Without them, terminating system-owned processes and changing "
                "protected startup entries will fail.\n\nContinue?",
                icon="question", parent=self):
            return
        if relaunch_as_admin():
            self.destroy()
        else:
            messagebox.showwarning(
                "Not elevated",
                "The elevation request was cancelled or refused.",
                parent=self)

    def _build_filterbar(self, parent):
        bar = tk.Frame(parent, bg=C['panel'], pady=9, padx=20)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="SHOW", font=FONT_UI_BOLD,
                 bg=C['panel'], fg=C['dimmer']).pack(side=tk.LEFT, padx=(0, 14))

        self.f_dupes     = tk.BooleanVar(value=True)
        self.f_hung      = tk.BooleanVar(value=True)
        self.f_zombies   = tk.BooleanVar(value=True)
        self.f_suspended = tk.BooleanVar(value=True)
        self.f_orphans   = tk.BooleanVar(value=True)
        self.f_sys       = tk.BooleanVar(value=True)

        for label, var, color, tip in [
            ("Duplicates", self.f_dupes, C['yellow'], CHIP_HELP['dupes']),
            ("Not Responding", self.f_hung, C['orange'], CHIP_HELP['hung']),
            ("Zombies", self.f_zombies, C['red'], CHIP_HELP['zombie']),
            ("Suspended", self.f_suspended, C['text'], CHIP_HELP['suspended']),
            ("Orphans", self.f_orphans, C['purple'], CHIP_HELP['orphan']),
        ]:
            chip = FilterChip(bar, label, var, color, self._apply_filter)
            chip.pack(side=tk.LEFT, padx=(0, 6))
            Tooltip(chip, tip)

        tk.Frame(bar, bg=C['border'], width=1, height=20).pack(
            side=tk.LEFT, padx=10, pady=2)
        sys_chip = FilterChip(bar, "Hide System", self.f_sys, C['blue'],
                              self._apply_filter)
        sys_chip.pack(side=tk.LEFT)
        Tooltip(sys_chip, CHIP_HELP['system'])

        self._build_searchbox(bar)

    def _build_searchbox(self, parent):
        """Live substring filter on the process name, right of the chips."""
        box = tk.Frame(parent, bg=C['row'], padx=8, pady=4,
                       highlightthickness=1, highlightbackground=C['border'])
        box.pack(side=tk.RIGHT)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._on_search_change())
        entry = tk.Entry(box, textvariable=self.search_var, width=24,
                         font=FONT_UI, bg=C['row'], fg=C['text'], bd=0,
                         relief=tk.FLAT, insertbackground=C['green'],
                         highlightthickness=0)
        entry.pack(side=tk.LEFT)
        entry.bind("<Escape>", lambda _: self.search_var.set(""))
        self.search_entry = entry

        # Focus ring: brighten the box border while the entry has focus.
        entry.bind("<FocusIn>",  lambda _: box.config(highlightbackground=C['green']))
        entry.bind("<FocusOut>", lambda _: box.config(highlightbackground=C['border']))

        # Placeholder, drawn over the entry while it is empty and unfocused.
        self.search_hint = tk.Label(box, text="Filter by name…", font=FONT_UI,
                                    bg=C['row'], fg=C['dimmer'])
        self.search_hint.place(in_=entry, x=2, rely=0.5, anchor=tk.W)
        self.search_hint.bind("<Button-1>", lambda _: entry.focus_set())

        self.search_clear = tk.Label(box, text="✕", font=("Segoe UI", 9),
                                     bg=C['row'], fg=C['dimmer'], cursor="hand2")
        self.search_clear.bind("<Button-1>", lambda _: self.search_var.set(""))
        self.search_clear.pack(side=tk.LEFT, padx=(6, 0))

    def _on_search_change(self):
        """Show/hide the placeholder and the clear affordance, then refilter."""
        has_text = bool(self.search_var.get())
        if has_text:
            self.search_hint.place_forget()
        else:
            self.search_hint.place(in_=self.search_entry, x=2, rely=0.5,
                                   anchor=tk.W)
        self.search_clear.config(fg=C['dim'] if has_text else C['chip_off'])
        self._apply_filter()

    def _build_tree(self, parent):
        frame = tk.Frame(parent, bg=C['bg'], padx=20, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ("process", "pid", "memory", "issue", "role", "instances")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 style="R.Treeview", selectmode="extended")

        col_cfg = [
            ("process",   "PROCESS NAME",  255, tk.W),
            ("pid",       "PID",            70, tk.CENTER),
            ("memory",    "MEMORY",        105, tk.E),
            ("issue",     "ISSUE",         130, tk.CENTER),
            ("role",      "ROLE",           90, tk.CENTER),
            ("instances", "INSTANCES",      80, tk.CENTER),
        ]
        for cid, heading, width, anchor in col_cfg:
            # heading anchor is independent of column anchor — keep them in sync
            self.tree.heading(cid, text=heading, anchor=anchor,
                              command=lambda c=cid: self._sort(c))
            self.tree.column(cid, width=width, minwidth=55, anchor=anchor)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview,
                           style="R.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))

        # Placeholder shown over the tree when there is nothing to list.
        self.empty_lbl = tk.Label(frame, text="Press SCAN to begin", font=FONT_UI,
                                  bg=C['row'], fg=C['dimmer'])
        self.empty_lbl.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        # Tk resolves competing tag options first-tag-wins, so rows are always
        # tagged in priority order: hover, then severity tint, then banding.
        self.tree.tag_configure('hover', background=C['border'])
        self.tree.tag_configure('alt',   background=C['row_alt'])

        # Kill animation: two flash states, then a ramp easing them down into
        # the row colour so the row dissolves instead of blinking out.
        self.tree.tag_configure('flash', foreground=FLASH_FG, background=FLASH_BG)
        self.tree.tag_configure('flash_off', foreground=C['red'], background=C['row'])
        for i in range(KILL_FADE_STEPS):
            t = (i + 1) / KILL_FADE_STEPS
            self.tree.tag_configure(f'fade{i}',
                                    foreground=lerp(FLASH_FG, C['row'], t),
                                    background=lerp(FLASH_BG, C['row'], t))

        for tag, (fg, bg) in TAG_STYLE.items():
            if bg:
                self.tree.tag_configure(tag, foreground=fg, background=bg)
            else:
                self.tree.tag_configure(tag, foreground=fg)

        self.tree.bind("<Button-1>",         self._on_click)
        self.tree.bind("<Control-Button-1>", self._on_ctrl_click)
        self.tree.bind("<Delete>",           lambda e: self._kill_selected())
        self.tree.bind("<Motion>",           self._on_hover)
        self.tree.bind("<Leave>",            self._on_hover_leave)
        self.tree.bind("<Button-3>",         self._on_right_click)
        for seq in ("<Control-a>", "<Control-A>"):
            self.tree.bind(seq, self._select_all)
        for seq in ("<Control-c>", "<Control-C>"):
            self.tree.bind(seq, self._copy_selection)

        self._menu = tk.Menu(self, tearoff=0, bg=C['panel'], fg=C['text'],
                             activebackground=C['select'],
                             activeforeground='#ffffff',
                             bd=0, relief=tk.FLAT, font=FONT_UI)
        self._menu.add_command(label="Open file location",
                               command=self._open_location)
        self._menu.add_command(label="Copy PID", command=self._copy_pid)
        self._menu.add_command(label="Copy row", command=self._copy_selection)
        self._menu.add_separator()
        self._menu.add_command(label="Kill", command=self._kill_selected)

        self._sort_col = None
        self._sort_rev = False

    # ── Row painting ───────────────────────────────────────────────────────────
    def _repaint_rows(self):
        """Rebuild every process row's tag list and remember its band parity."""
        for i, iid in enumerate(self.tree.get_children()):
            self._row_band[iid] = bool(i % 2)
            self._paint_row(iid)

    def _paint_row(self, iid):
        """Apply hover / severity / banding tags to one row, in that order.

        The write is skipped when the tags are unchanged: a live refresh walks
        every visible row, and handing Tk an identical tag tuple still costs a
        redraw of that row."""
        if iid in self._dying:          # mid-animation; _die owns its tags
            return
        tags = ['hover'] if iid == self._hover_iid else []
        tags.append(self._row_base.get(iid, 'clean'))
        if self._row_band.get(iid):
            tags.append('alt')
        tags = tuple(tags)
        if self._row_tags.get(iid) == tags:
            return
        self._row_tags[iid] = tags
        self.tree.item(iid, tags=tags)

    def _forget_row(self, iid):
        """Remove one process row and every cache entry keyed on it."""
        if self.tree.exists(iid):
            self.tree.delete(iid)
        for cache in (self._row_base, self._row_rec, self._row_band,
                      self._row_vals, self._row_tags):
            cache.pop(iid, None)
        self._dying.discard(iid)
        if self._hover_iid == iid:
            self._hover_iid = None

    # ── Kill feedback ──────────────────────────────────────────────────────────
    def _shake(self):
        """Recoil the window briefly so a kill lands with some weight.

        The window is moved with SetWindowPos on the real HWND rather than
        wm_geometry. Tk's geometry() is a request-then-confirm round trip that
        emits two <Configure> events per call, so a ten-frame shake pushed the
        window through twenty reconfigures and visibly strobed the frame.

        Skipped while maximised: moving a zoomed window fights the window
        manager and snaps it out of the maximised state."""
        if not SHAKE_PX or self._shaking or self.state() != 'normal':
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
        except Exception:
            return                      # cosmetic only; never break a kill
        origin_x, origin_y = rect.left, rect.top
        # NOSIZE | NOZORDER | NOACTIVATE — move only, never resize or refocus.
        flags = 0x0001 | 0x0004 | 0x0010

        def move(x, y):
            try:
                ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, 0, 0, flags)
            except Exception:
                pass

        path = shake_path(SHAKE_PX)
        self._shaking = True

        def step(i=0):
            if i >= len(path):
                move(origin_x, origin_y)
                self._shaking = False
                return
            dx, dy = path[i]
            move(origin_x + dx, origin_y + dy)
            self.after(SHAKE_MS, step, i + 1)

        step()

    def _start_kill_anim(self, iid):
        """Mark a killed row as dying and begin its blink/fade."""
        if iid in self._dying or not self.tree.exists(iid):
            return
        self._dying.add(iid)
        # The blue selection tint would sit on top of the flash colours.
        self.tree.selection_remove(iid)
        self._die(iid)

    def _die(self, iid, step=0):
        """Blink the row, fade it into the background, then remove it.

        Tags are written straight to the tree rather than through _paint_row,
        whose cache describes the row's resting appearance and must survive
        the animation untouched."""
        if not self.tree.exists(iid):
            self._finish_dying(iid)
            return

        if step < KILL_BLINKS * 2:
            self.tree.item(iid, tags=('flash',) if step % 2 == 0 else ('flash_off',))
            self.after(KILL_BLINK_MS, self._die, iid, step + 1)
            return

        fade = step - KILL_BLINKS * 2
        if fade < KILL_FADE_STEPS:
            self.tree.item(iid, tags=(f'fade{fade}',))
            self.after(KILL_FADE_MS, self._die, iid, step + 1)
            return

        self._forget_row(iid)
        self._finish_dying(iid)

    def _finish_dying(self, iid):
        """Run any refresh that was held back while this row was animating."""
        self._dying.discard(iid)
        if self._dying or not self._filter_pending:
            return
        self._filter_pending = False
        self._apply_filter()

    def _on_hover(self, event):
        """Track the row under the cursor and repaint only what changed."""
        iid = self.tree.identify_row(event.y) or None
        if iid == self._hover_iid:
            return
        previous, self._hover_iid = self._hover_iid, iid
        for target in (previous, iid):
            if target and self.tree.exists(target):
                self._paint_row(target)

    def _on_hover_leave(self, _=None):
        if self._hover_iid and self.tree.exists(self._hover_iid):
            previous, self._hover_iid = self._hover_iid, None
            self._paint_row(previous)
        self._hover_iid = None

    @staticmethod
    def _restripe(tree):
        """Reapply alternating row backgrounds after an insert or a sort."""
        for i, iid in enumerate(tree.get_children()):
            tags = [t for t in tree.item(iid, 'tags') if t != 'alt']
            if i % 2:
                tags.append('alt')
            tree.item(iid, tags=tuple(tags))

    def _build_notebook(self):
        self.notebook = ttk.Notebook(self, style="R.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # ── Processes tab ──────────────────────────────────────────────────────
        proc_frame = tk.Frame(self.notebook, bg=C['bg'])
        self.notebook.add(proc_frame, text="⚙  PROCESSES")
        self._build_filterbar(proc_frame)
        self._build_tree(proc_frame)

        # ── Startup tab ────────────────────────────────────────────────────────
        startup_frame = tk.Frame(self.notebook, bg=C['bg'])
        self.notebook.add(startup_frame, text="🚀  STARTUP")
        self._build_startup_tab(startup_frame)   # implemented in Task 5

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

    def _on_tab_change(self, event):
        sel = self.notebook.select()
        if not sel:
            return
        tab_idx = self.notebook.index(sel)
        if tab_idx == 0:   # Processes
            self._btns_frame.pack(side=tk.RIGHT)
        else:              # Startup (or any future tab)
            self._btns_frame.pack_forget()

    def _build_startup_tab(self, parent):
        # ── Toolbar ────────────────────────────────────────────────────────────
        toolbar = tk.Frame(parent, bg=C['panel'], pady=9, padx=20)
        toolbar.pack(fill=tk.X)

        self.startup_scan_btn = self._mk_btn(
            toolbar, "▶  SCAN STARTUP", self._start_startup_scan, C['green'])
        self.startup_scan_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.startup_disable_btn = self._mk_btn(
            toolbar, "⊘  DISABLE SELECTED",
            lambda: self._set_startup_enabled(False), C['blue'], state=tk.DISABLED)
        self.startup_disable_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.startup_enable_btn = self._mk_btn(
            toolbar, "✔  ENABLE SELECTED",
            lambda: self._set_startup_enabled(True), C['blue'], state=tk.DISABLED)
        self.startup_enable_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.startup_summary_lbl = tk.Label(
            toolbar, text="", font=FONT_UI,
            bg=C['panel'], fg=C['dim'])
        self.startup_summary_lbl.pack(side=tk.RIGHT)

        # ── Tree ───────────────────────────────────────────────────────────────
        frame = tk.Frame(parent, bg=C['bg'], padx=20, pady=12)
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ("name", "source", "status", "command")
        self.startup_tree = ttk.Treeview(
            frame, columns=cols, show="headings",
            style="R.Treeview", selectmode="extended")

        col_cfg = [
            ("name",    "NAME",    220, tk.W),
            ("source",  "SOURCE",   70, tk.CENTER),
            ("status",  "STATUS",   80, tk.CENTER),
            ("command", "COMMAND",   0, tk.W),
        ]
        for cid, heading, width, anchor in col_cfg:
            self.startup_tree.heading(cid, text=heading, anchor=anchor,
                                      command=lambda c=cid: self._startup_sort(c))
            if width:
                self.startup_tree.column(cid, width=width, minwidth=55, anchor=anchor)
            else:
                # "command" fills remaining space
                self.startup_tree.column(cid, width=300, minwidth=100,
                                         anchor=anchor, stretch=True)

        self._startup_sort_col = None
        self._startup_sort_rev = False

        # Source tags (lower priority)
        self.startup_tree.tag_configure("alt", background=C['row_alt'])
        self.startup_tree.tag_configure("src_hkcu",    foreground=C['blue'])
        self.startup_tree.tag_configure("src_hklm",    foreground=C['yellow'])
        self.startup_tree.tag_configure("src_task",    foreground=C['orange'])
        self.startup_tree.tag_configure("src_folder",  foreground=C['blue'])
        self.startup_tree.tag_configure("src_common",  foreground=C['yellow'])
        # disabled tag overrides source colour
        self.startup_tree.tag_configure("disabled", foreground=C['dim'])

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                           command=self.startup_tree.yview,
                           style="R.Vertical.TScrollbar")
        self.startup_tree.configure(yscrollcommand=sb.set)

        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        self.startup_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.startup_tree.bind("<Button-1>",         self._on_startup_click)
        self.startup_tree.bind("<Control-Button-1>", self._on_startup_ctrl_click)

    def _on_startup_click(self, event):
        iid = self.startup_tree.identify_row(event.y)
        if not iid:
            self.startup_tree.selection_set([])
            self._on_startup_select()
            return
        self.startup_tree.selection_set(iid)
        self._on_startup_select()

    def _on_startup_ctrl_click(self, event):
        iid = self.startup_tree.identify_row(event.y)
        if not iid:
            return "break"
        if iid in self.startup_tree.selection():
            self.startup_tree.selection_remove(iid)
        else:
            self.startup_tree.selection_add(iid)
        self._on_startup_select()
        return "break"

    def _start_startup_scan(self):
        if self._startup_scanning:
            return
        self._startup_scanning = True
        self.startup_scan_btn.config(state=tk.DISABLED)
        self.status_var.set("Scanning startup entries…")
        threading.Thread(target=self._do_startup_scan, daemon=True).start()

    def _do_startup_scan(self):
        try:
            results = scan_startup()
            self.after(0, self._startup_scan_done, results)
        except Exception as exc:
            self.after(0, self._startup_scan_error, str(exc))

    def _startup_scan_error(self, msg: str):
        self._startup_scanning = False
        self.startup_scan_btn.config(state=tk.NORMAL)
        self.status_var.set(f"Startup scan failed: {msg}")

    def _startup_scan_done(self, results):
        self._startup_scanning = False
        self.startup_scan_btn.config(state=tk.NORMAL)
        self._startup_results = results
        self.startup_tree.delete(*self.startup_tree.get_children())
        for i, entry in enumerate(results):
            src = entry['source']
            src_tag = {
                'HKCU': 'src_hkcu', 'HKLM': 'src_hklm',
                'Task': 'src_task', 'Folder': 'src_folder', 'Common': 'src_common',
            }.get(src, 'src_hkcu')
            tags = (src_tag, 'disabled') if not entry['enabled'] else (src_tag,)
            values = (
                entry['name'],
                entry['source'],
                'Enabled' if entry['enabled'] else 'Disabled',
                entry['command'],
            )
            self.startup_tree.insert('', tk.END, iid=str(i), values=values, tags=tags)
        self._restripe(self.startup_tree)
        self.startup_summary_lbl.config(text=f"{len(results)} found")
        self.status_var.set("Startup scan complete")

    def _startup_sort(self, col):
        col_idx = {"name": 0, "source": 1, "status": 2, "command": 3}[col]
        reverse = (self._startup_sort_col == col) and not self._startup_sort_rev
        items = [(self.startup_tree.set(iid, col), iid)
                 for iid in self.startup_tree.get_children()]
        items.sort(key=lambda x: x[0].lower(), reverse=reverse)
        for rank, (_, iid) in enumerate(items):
            self.startup_tree.move(iid, '', rank)
        self._restripe(self.startup_tree)
        self._startup_sort_col = col
        self._startup_sort_rev = reverse
        # Update heading arrows
        for c in ("name", "source", "status", "command"):
            heading = {"name": "NAME", "source": "SOURCE",
                       "status": "STATUS", "command": "COMMAND"}[c]
            arrow = (" ▲" if not reverse else " ▼") if c == col else ""
            self.startup_tree.heading(c, text=heading + arrow,
                                      command=lambda cc=c: self._startup_sort(cc))

    def _set_startup_enabled(self, enable: bool):
        # Snapshot entries on the main thread to avoid iid/results race
        entries = [self._startup_results[int(iid)]
                   for iid in self.startup_tree.selection()
                   if int(iid) < len(self._startup_results)]
        if not entries:
            return
        self.startup_disable_btn.config(state=tk.DISABLED)
        self.startup_enable_btn.config(state=tk.DISABLED)
        self.status_var.set(f"{'Enabling' if enable else 'Disabling'} {len(entries)} item(s)…")

        def _worker():
            count = 0
            failed = []
            for entry in entries:
                try:
                    set_enabled(entry, enable)
                    count += 1
                except StartupAccessError:
                    failed.append(entry['name'])
            self.after(0, _done, count, failed)

        def _done(count, failed):
            if failed:
                names = "\n".join(f"  • {n}" for n in failed)
                messagebox.showwarning(
                    "Admin required",
                    f"The following item(s) require administrator privileges to modify:\n\n{names}"
                )
            self.status_var.set(f"{'Enabled' if enable else 'Disabled'} {count} item(s)")
            self._start_startup_scan()

        threading.Thread(target=_worker, daemon=True).start()

    def _on_startup_select(self):
        n = len(self.startup_tree.selection())
        state = tk.NORMAL if n > 0 else tk.DISABLED
        self.startup_disable_btn.config(state=state)
        self.startup_enable_btn.config(state=state)

    RAM_BAR_W = 132
    RAM_BAR_H = 10

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=C['panel'], pady=8, padx=20)
        bar.pack(fill=tk.X)

        self.status_var  = tk.StringVar(value="Ready — press SCAN to begin")
        self.summary_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.status_var,
                 bg=C['panel'], fg=C['dim'], font=FONT_UI).pack(side=tk.LEFT)

        # RAM meter (right side)
        ram_frame = tk.Frame(bar, bg=C['panel'])
        ram_frame.pack(side=tk.RIGHT)
        tk.Label(ram_frame, text="RAM", bg=C['panel'], fg=C['dimmer'],
                 font=FONT_UI_BOLD).pack(side=tk.LEFT, padx=(0, 8))
        self.ram_canvas = tk.Canvas(ram_frame, width=self.RAM_BAR_W,
                                    height=self.RAM_BAR_H, bg=C['panel'],
                                    highlightthickness=0)
        self.ram_canvas.pack(side=tk.LEFT, pady=2)
        self._rounded_bar(self.ram_canvas, self.RAM_BAR_W, C['border'])
        self.ram_fill_ids = []
        self.ram_label = tk.Label(ram_frame, text="", bg=C['panel'], fg=C['text'],
                                  font=FONT_DATA, width=18, anchor=tk.E)
        self.ram_label.pack(side=tk.LEFT, padx=(8, 0))

        tk.Label(bar, textvariable=self.summary_var,
                 bg=C['panel'], fg=C['green'], font=FONT_UI_BOLD
                 ).pack(side=tk.RIGHT, padx=(0, 24))

        self._update_ram()

    def _rounded_bar(self, canvas, width, colour):
        """Draw a pill-shaped bar of `width` px; returns its canvas item ids."""
        h = self.RAM_BAR_H
        if width <= 0:
            return []
        r = h / 2
        w = max(width, h)
        return [
            canvas.create_oval(0, 0, h, h, fill=colour, width=0),
            canvas.create_oval(w - h, 0, w, h, fill=colour, width=0),
            canvas.create_rectangle(r, 0, w - r, h, fill=colour, width=0),
        ]

    def _mk_btn(self, parent, text, cmd, color, state=tk.NORMAL):
        return HoverButton(parent, color, text=text, command=cmd,
                           font=FONT_BTN, relief=tk.FLAT,
                           padx=15, pady=7, state=state, bd=0,
                           highlightthickness=0)

    # ── RAM ────────────────────────────────────────────────────────────────────
    def _update_ram(self):
        mem = psutil.virtual_memory()
        used_gb  = mem.used  / 1024 ** 3
        total_gb = mem.total / 1024 ** 3
        pct      = mem.percent
        color    = C['green'] if pct < 60 else (C['yellow'] if pct < 85 else C['red'])
        for item in self.ram_fill_ids:
            self.ram_canvas.delete(item)
        self.ram_fill_ids = self._rounded_bar(
            self.ram_canvas, int(self.RAM_BAR_W * pct / 100), color)
        self.ram_label.config(text=f"{used_gb:.1f}/{total_gb:.1f} GB {pct:.0f}%")

    # ── Scan ───────────────────────────────────────────────────────────────────
    def _start_scan(self, quiet=False):
        """Kick off a scan on a worker thread.

        Nothing is torn down up front — the tree is reconciled against the new
        results when they land — so neither a manual scan nor a live tick
        blanks the list. `quiet` is the live path, which additionally leaves
        the toolbar and status text alone so they do not strobe every 5s.
        """
        if self._scanning:
            return
        self._scanning = True
        if not quiet:
            self.scan_btn.config(state=tk.DISABLED, text="SCANNING...")
            self.trim_all_btn.config(state=tk.DISABLED)
            self.status_var.set("Scanning processes...")
            if not self._all_results:
                self.empty_lbl.config(text=self._empty_text())
        threading.Thread(target=self._do_scan, args=(quiet,), daemon=True).start()

    def _do_scan(self, quiet=False):
        started = time.perf_counter()
        try:
            # A live tick skips the expensive status() re-read; see _collect.
            self._all_results = self._find_issues(full=not quiet)
            self.after(0, self._apply_filter)
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"Error: {e}"))
        finally:
            self._last_scan_ms = (time.perf_counter() - started) * 1000
            self.after(0, self._scan_done, quiet)

    def _collect(self, full):
        """One snapshot of every process, as (pid, name, ppid, born, rss, status).

        psutil is startlingly expensive on Windows, and measurably so here:
        over ~390 processes, ppid costs 4.5s, status 3.5s, memory 1.8s and
        name+create_time 1.6s. The old scan paid all of that AND then re-read
        the same values through proc.status()/.memory_info() instead of the
        already-fetched proc.info, for about 15 seconds a scan. Live mode ticks
        every 5s, so it was simply always scanning — that is the lag.

        Three things make it cheap:
          * ppid comes from one ppid_map() call rather than one system snapshot
            per process, which is where the 4.5s went (4460ms -> 11ms).
          * name, ppid and create_time cannot change while a pid lives, so they
            are read once and cached.
          * `full` is False on a live tick, which skips status() — the single
            most expensive call. New pids are always read in full, so a process
            that shows up already suspended is still classified correctly; only
            a state change on a pid we have already seen waits for a full scan.
        """
        parents = _ppid_map()
        static, status_cache = self._proc_static, self._proc_status
        rows, seen = [], set()

        for proc in psutil.process_iter(['pid']):
            pid = proc.pid
            try:
                # oneshot() lets psutil reuse one query across these calls.
                with proc.oneshot():
                    fixed = static.get(pid)
                    if fixed is None:
                        fixed = (proc.name(), parents.get(pid, 0), proc.create_time())
                        static[pid] = fixed
                    rss = proc.memory_info().rss
                    if full or pid not in status_cache:
                        status_cache[pid] = proc.status()
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
            seen.add(pid)
            rows.append((pid, fixed[0], fixed[1], fixed[2], rss, status_cache[pid]))

        # Drop cache entries for processes that have exited, so a long live
        # session cannot grow the dictionaries without bound.
        for pid in list(static):
            if pid not in seen:
                static.pop(pid, None)
                status_cache.pop(pid, None)
        return rows, seen

    def _find_issues(self, full=True):
        issues      = []
        name_groups = defaultdict(list)
        hung_pids   = get_hung_pids()
        _now        = time.time()
        rows, _live_pids = self._collect(full)

        for row in rows:
            name_groups[row[1].lower()].append(row)

        for name_key, procs in name_groups.items():
            is_system = name_key in SYSTEM_NAMES
            count     = len(procs)
            group_pids = {r[0] for r in procs}

            for pid, name, ppid, born, mem, status in procs:
                if status == psutil.STATUS_ZOMBIE:
                    issues.append(self._make(
                        name, pid, mem, 'Zombie', 'zombie', '—', count, is_system))

                elif pid in hung_pids:
                    issues.append(self._make(
                        name, pid, mem, 'Not Responding', 'hung', '—', count, is_system))

                elif status == psutil.STATUS_STOPPED:
                    issues.append(self._make(
                        name, pid, mem, 'Suspended', 'suspended', '—', count, is_system))

                elif count > 1:
                    if ppid not in group_pids:
                        issue, tag, role = 'Dupe · Main', 'dup_main', 'Main'
                    else:
                        issue, tag, role = 'Dupe · Child', 'dup_child', 'Child'

                    issues.append(self._make(
                        name, pid, mem, issue, tag, role, count, is_system))

                elif (not is_system and ppid > 4
                      and ppid not in _live_pids
                      and (_now - born) >= 12 * 3600):
                    issues.append(self._make(
                        name, pid, mem, 'Orphan', 'orphan', '—', 1, is_system))

                else:
                    issues.append(self._make(
                        name, pid, mem, '—', 'clean', '—', 1, is_system))

        return sorted(issues, key=lambda x: (
            ISSUE_ORDER.get(x['issue'], 99), x['name'].lower()))

    @staticmethod
    def _make(name, pid, mem, issue, tag, role, count, is_system):
        return {
            'name': name, 'pid': pid, 'memory': mem,
            'issue': issue, 'tag': tag, 'role': role,
            'count': count, 'is_system': is_system,
        }

    def _scan_done(self, quiet=False):
        self._scanning = False
        if not quiet:
            self.scan_btn.config(state=tk.NORMAL, text="▶  SCAN")
        self.trim_all_btn.config(state=tk.NORMAL)
        has_issues = any(r['issue'] != '—' for r in self._all_results)
        if self._all_results and not has_issues:
            self.status_var.set("No issues found — system looks clean ✓")
        if self._live:
            # The interval adapts to how long the scan takes, so report it
            # rather than a fixed figure that would often be wrong.
            gap = max(LIVE_MIN_MS, min(int(self._last_scan_ms), LIVE_MAX_MS))
            self.status_var.set(
                f"● Live · scan {self._last_scan_ms / 1000:.1f}s"
                f" · next in {gap / 1000:.1f}s")
        self._update_ram()

    # ── Live scan ──────────────────────────────────────────────────────────────
    def _live_toggle(self):
        self._live = not self._live
        if self._live:
            self.live_btn.config(text="●  LIVE")
            self.live_btn.set_accent(C['green'])
            self._schedule_live()
        else:
            self.live_btn.config(text="◉  LIVE")
            self.live_btn.set_accent(C['btn_off'])
            if self._live_after_id:
                self.after_cancel(self._live_after_id)
                self._live_after_id = None
            self.status_var.set("Live scan stopped")

    def _schedule_live(self):
        """Run one live tick, then schedule the next one after it finishes.

        The old version fired every 5s from the *start* of the previous tick.
        A scan that took longer than the interval therefore ran back to back
        forever, pinning a core and leaving the UI permanently choppy. Timing
        from completion, and never resting for less time than the scan itself
        took, keeps the duty cycle at or under 50% on any machine."""
        self._live_after_id = None
        if not self._live:
            return
        # Quiet: a live tick refreshes the rows in place and must not touch the
        # SCAN button or the status line.
        self._start_scan(quiet=True)
        self._await_live_tick()

    def _await_live_tick(self):
        """Wait for the running scan, then queue the next tick."""
        if not self._live:
            return
        if self._scanning:
            self.after(100, self._await_live_tick)
            return
        delay = max(LIVE_MIN_MS, min(int(self._last_scan_ms), LIVE_MAX_MS))
        self._live_after_id = self.after(delay, self._schedule_live)

    # ── Filter & sort ──────────────────────────────────────────────────────────
    @staticmethod
    def _row_values(r):
        """The six formatted cell strings for one scan record."""
        count = str(r['count']) if 'Dupe' in r['issue'] else '—'
        return (r['name'], str(r['pid']), fmt_mem(r['memory']),
                r['issue'], r['role'], count)

    def _sort_key(self, r):
        """Sort key for one record, on the stored value not the shown text."""
        col = self._sort_col
        if col == 'process':
            return r['name'].lower()
        if col == 'pid':
            return r['pid']
        if col == 'memory':
            return r['memory']
        if col == 'issue':
            return ISSUE_ORDER.get(r['issue'], 99)
        if col == 'role':
            return r['role']
        # instances: only duplicates carry a count, the rest sort as 0
        return r['count'] if 'Dupe' in r['issue'] else 0

    def _empty_text(self):
        """What the empty-list overlay should say for the current state."""
        if self._scanning:
            return "Scanning processes..."
        if self._all_results:
            return "No processes match the current filters"
        return "Press SCAN to begin"

    def _sync_tree(self, rows):
        """Reconcile the tree against `rows` in place instead of rebuilding it.

        Live mode re-runs the scan every few seconds. Clearing the tree and
        re-inserting every row made that visible: the list blanked, the scroll
        position jumped back to the top, the selection had to be restored by
        hand and the active sort was lost. Reconciling instead means a refresh
        only removes processes that exited, adds ones that appeared, and
        rewrites the cells whose text actually changed — so from the user's
        side nothing moves except the numbers.
        """
        wanted = {str(r['pid']): r for r in rows}

        # Processes that exited, or that the current filters now exclude.
        for iid in list(self.tree.get_children()):
            if iid not in wanted and iid not in self._dying:
                self._forget_row(iid)

        for index, r in enumerate(rows):
            iid    = str(r['pid'])
            values = self._row_values(r)
            if self.tree.exists(iid):
                # Compared against what was last written rather than against
                # the tree itself: values read back out of Tk have been through
                # Tcl, which re-types the numeric cells and never compares equal.
                if self._row_vals.get(iid) != values:
                    self.tree.item(iid, values=values)
                # Everything before `index` is already in place, so a row that
                # is not at `index` only has to move once.
                if self.tree.index(iid) != index:
                    self.tree.move(iid, '', index)
            else:
                self.tree.insert('', index, iid=iid, values=values)
            self._row_vals[iid] = values
            self._row_base[iid] = r['tag']
            self._row_rec[iid]  = r

        self._repaint_rows()

    def _apply_filter(self):
        if self._dying:
            # Under a second, and _finish_dying replays it once the last row
            # clears, so the list is never left stale.
            self._filter_pending = True
            return
        hide_sys = self.f_sys.get()
        query    = self.search_var.get().strip().lower()
        rows     = []

        for r in self._all_results:
            if hide_sys and r['is_system']:
                continue
            if query and query not in r['name'].lower():
                continue
            if r['issue'] in ('Dupe · Main', 'Dupe · Child') and not self.f_dupes.get():
                continue
            if r['issue'] == 'Not Responding' and not self.f_hung.get():
                continue
            if r['issue'] == 'Zombie'         and not self.f_zombies.get():
                continue
            if r['issue'] == 'Suspended'      and not self.f_suspended.get():
                continue
            if r['issue'] == 'Orphan'         and not self.f_orphans.get():
                continue

            rows.append(r)

        # Ordered here rather than by re-sorting the tree afterwards, so a live
        # refresh lands rows in the order the user chose instead of snapping
        # back to scan order every few seconds.
        if self._sort_col:
            rows.sort(key=self._sort_key, reverse=self._sort_rev)

        self._sync_tree(rows)
        shown = len(rows)

        # Empty state is an overlay rather than a tree row, so it can never be
        # selected and fed to the kill/trim paths.
        if shown:
            self.empty_lbl.place_forget()
        else:
            self.empty_lbl.config(text=self._empty_text())
            self.empty_lbl.lift()
            self.empty_lbl.place(relx=0.5, rely=0.45, anchor=tk.CENTER)

        # Selection is no longer restored by hand: surviving rows are never
        # deleted, so Tk keeps them selected on its own.
        total = len(self._all_results)
        if total:
            if not self._live:
                self.status_var.set("Scan complete")
            self.summary_var.set(f"{shown} shown  /  {total} found")
        self._on_select()

    def _sort(self, col):
        """Sort on the underlying record values, never on the formatted text.

        The ordering itself lives in _apply_filter, so that every later live
        refresh reapplies it instead of the tree drifting back to scan order."""
        rev = (self._sort_col == col) and not self._sort_rev
        self._sort_col = col
        self._sort_rev = rev
        self._apply_filter()

        _labels = {
            "process": "PROCESS NAME", "pid": "PID", "memory": "MEMORY",
            "issue": "ISSUE", "role": "ROLE", "instances": "INSTANCES",
        }
        for c, label in _labels.items():
            arrow = (" ▲" if not rev else " ▼") if c == col else ""
            self.tree.heading(c, text=label + arrow,
                              command=lambda cc=c: self._sort(cc))

    # ── Selection ──────────────────────────────────────────────────────────────
    def _on_select(self, _=None):
        sel      = self.tree.selection()
        has_sel  = bool(sel)
        has_main = any("dup_main" in self.tree.item(iid, "tags") for iid in sel)
        self.kill_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)
        self.kill_children_btn.config(state=tk.NORMAL if has_main else tk.DISABLED)
        self.trim_sel_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)

    def _on_click(self, event):
        self.tree.focus_set()
        iid = self.tree.identify_row(event.y)
        if not iid:
            self.tree.selection_set([])
            self._on_select()
            return
        tags = self.tree.item(iid, "tags")
        if "dup_main" in tags:
            name     = self.tree.set(iid, "process")
            matching = [i for i in self.tree.get_children()
                        if self.tree.set(i, "process") == name]
            self.tree.selection_set(matching)
        else:
            self.tree.selection_set([iid])
        self._on_select()
        return "break"

    def _on_ctrl_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid:
            return "break"
        if iid in self.tree.selection():
            self.tree.selection_remove([iid])
        else:
            self.tree.selection_add([iid])
        self._on_select()
        return "break"

    # ── Context menu & shortcuts ───────────────────────────────────────────────
    def _on_right_click(self, event):
        """Open the row menu, selecting the row under the cursor if needed."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            return "break"
        self.tree.focus_set()
        if iid not in self.tree.selection():
            self.tree.selection_set([iid])
            self._on_select()
        # Single-row actions only make sense for one row.
        single = tk.NORMAL if len(self.tree.selection()) == 1 else tk.DISABLED
        self._menu.entryconfig("Open file location", state=single)
        self._menu.entryconfig("Copy PID", state=single)
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()
        return "break"

    def _select_all(self, _=None):
        self.tree.selection_set(self.tree.get_children())
        self._on_select()
        return "break"

    def _copy_selection(self, _=None):
        """Copy the selected rows to the clipboard as tab-separated text."""
        cols = ("process", "pid", "memory", "issue", "role", "instances")
        rows = ["\t".join(self.tree.set(iid, c) for c in cols)
                for iid in self.tree.selection()]
        if not rows:
            return "break"
        self.clipboard_clear()
        self.clipboard_append("\n".join(rows))
        self.status_var.set(f"Copied {len(rows)} row(s) to clipboard")
        return "break"

    def _copy_pid(self):
        sel = self.tree.selection()
        if len(sel) != 1:
            return
        self.clipboard_clear()
        self.clipboard_append(sel[0])
        self.status_var.set(f"Copied PID {sel[0]} to clipboard")

    def _open_location(self):
        """Reveal the selected process's executable in Explorer."""
        sel = self.tree.selection()
        if len(sel) != 1:
            return
        pid = int(sel[0])
        try:
            path = psutil.Process(pid).exe()
        except psutil.AccessDenied:
            self.status_var.set(
                f"PID {pid}: path unreadable — try restarting as administrator")
            return
        except psutil.NoSuchProcess:
            self.status_var.set(f"PID {pid} is gone")
            return
        if not path or not os.path.exists(path):
            self.status_var.set(f"PID {pid}: no executable path on disk")
            return
        # explorer exits non-zero even when it succeeds, so the code is ignored.
        subprocess.Popen(['explorer', '/select,' + os.path.normpath(path)])
        self.status_var.set(f"Revealed {os.path.basename(path)}")

    # ── Kill ───────────────────────────────────────────────────────────────────
    def _kill_selected(self):
        sel = self.tree.selection()
        if not sel:
            return

        pid_map = {str(r['pid']): r for r in self._all_results}
        records = [pid_map[iid] for iid in sel if iid in pid_map]

        main_procs = [r for r in records if r['tag'] == 'dup_main']
        if main_procs:
            names = ', '.join(f"{r['name']} (PID {r['pid']})" for r in main_procs)
            proceed = messagebox.askyesno(
                "⚠  Killing Main Process",
                f"You have selected {len(main_procs)} MAIN process(es):\n\n"
                f"  {names}\n\n"
                f"These are the root processes of multi-instance apps "
                f"(e.g. Electron, Chrome, Claude).\n"
                f"Killing them will likely crash the entire application, "
                f"including all its child processes.\n\n"
                f"Are you sure you want to continue?",
                icon="warning", parent=self
            )
            if not proceed:
                return

        lines = "\n".join(
            f"  •  {r['name']}  (PID {r['pid']})  [{r['issue']}]"
            for r in records
        )
        if not messagebox.askyesno(
            "Confirm Kill",
            f"Terminate {len(sel)} process(es)?\n\n{lines}",
            icon="warning", parent=self
        ):
            return

        killed, failed = 0, []
        for iid in sel:
            try:
                psutil.Process(int(iid)).kill()
                # The row is not removed here: it blinks and fades first, and
                # _die drops it when the animation ends.
                self._start_kill_anim(iid)
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                failed.append(f"PID {iid}: {e}")

        # Audible outcome. A deflection takes priority over the gunshot: on a
        # partial kill the refusal is the part worth hearing, and winsound
        # plays one clip at a time anyway.
        if failed:
            sounds.play_blocked()
        elif killed:
            sounds.play_kill()
            self._shake()

        killed_pids       = {int(iid) for iid in sel}
        self._all_results = [r for r in self._all_results if r['pid'] not in killed_pids]

        shown = len([i for i in self.tree.get_children() if i not in self._dying])
        total = len(self._all_results)
        self.status_var.set(f"Terminated {killed} process(es)")
        self.summary_var.set(f"{shown} shown  /  {total} found" if total else "")
        self.kill_btn.config(state=tk.DISABLED)
        self.kill_children_btn.config(state=tk.DISABLED)

        if failed:
            messagebox.showwarning(
                "Partial Success",
                f"Killed {killed}, failed {len(failed)}:\n" + "\n".join(failed),
                parent=self
            )

    def _kill_children(self):
        sel = self.tree.selection()
        if not sel:
            return

        child_iids = []
        for iid in sel:
            if "dup_main" not in self.tree.item(iid, "tags"):
                continue
            name = self.tree.set(iid, "process")
            child_iids.extend(
                i for i in self.tree.get_children()
                if self.tree.set(i, "process") == name
                and "dup_child" in self.tree.item(i, "tags")
            )

        if not child_iids:
            return

        pid_map = {str(r['pid']): r for r in self._all_results}
        records = [pid_map[iid] for iid in child_iids if iid in pid_map]

        lines = "\n".join(
            f"  •  {r['name']}  (PID {r['pid']})"
            for r in records
        )
        if not messagebox.askyesno(
            "Confirm Kill Children",
            f"Terminate {len(child_iids)} child process(es)?\n\n{lines}\n\n"
            f"The main process will remain running.",
            icon="warning", parent=self
        ):
            return

        killed, failed = 0, []
        for iid in child_iids:
            try:
                psutil.Process(int(iid)).kill()
                # The row is not removed here: it blinks and fades first, and
                # _die drops it when the animation ends.
                self._start_kill_anim(iid)
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                failed.append(f"PID {iid}: {e}")

        # Audible outcome. A deflection takes priority over the gunshot: on a
        # partial kill the refusal is the part worth hearing, and winsound
        # plays one clip at a time anyway.
        if failed:
            sounds.play_blocked()
        elif killed:
            sounds.play_kill()
            self._shake()

        killed_pids       = {int(iid) for iid in child_iids}
        self._all_results = [r for r in self._all_results if r['pid'] not in killed_pids]

        shown = len([i for i in self.tree.get_children() if i not in self._dying])
        total = len(self._all_results)
        self.status_var.set(f"Terminated {killed} child process(es)")
        self.summary_var.set(f"{shown} shown  /  {total} found" if total else "")
        self._on_select()

        if failed:
            messagebox.showwarning(
                "Partial Success",
                f"Killed {killed}, failed {len(failed)}:\n" + "\n".join(failed),
                parent=self
            )

    def _trim_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        freed = sum(trim_process(int(iid)) for iid in sel)
        freed_mb = freed / 1024 ** 2
        self.status_var.set(
            f"Trimmed {len(sel)} process(es) — freed {freed_mb:.1f} MB")
        self._update_ram()

    def _trim_all(self):
        if self._trimming:
            return
        self._trimming = True
        self.trim_all_btn.config(state=tk.DISABLED, text="TRIMMING...")
        self.trim_sel_btn.config(state=tk.DISABLED)
        self.status_var.set("Trimming working sets…")

        def _do():
            freed = 0
            count = 0
            try:
                pids = psutil.pids()
                for pid in pids:
                    result = trim_process(pid)
                    if result > 0:
                        freed += result
                        count += 1
            finally:
                self.after(0, lambda: _done(freed, count))

        def _done(freed, count):
            self._trimming = False
            freed_mb = freed / 1024 ** 2
            self.trim_all_btn.config(state=tk.NORMAL, text="✂  TRIM RAM")
            has_sel = bool(self.tree.selection())
            self.trim_sel_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)
            self.status_var.set(
                f"Trimmed {count} process(es) — freed {freed_mb:.1f} MB")
            self._update_ram()

        threading.Thread(target=_do, daemon=True).start()


if __name__ == "__main__":
    app = RamBo()
    app.mainloop()
