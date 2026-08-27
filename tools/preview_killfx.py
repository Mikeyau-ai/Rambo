"""
Standalone preview of the kill feedback: window shake + row blink/fade.

Nothing here is wired into RamBo. Run it, pick rows, hit KILL, and compare the
three presets; whichever numbers feel right get folded into main.pyw.

    python tools/preview_killfx.py
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ctypes                                    # noqa: E402
import importlib.machinery, importlib.util       # noqa: E402
from ctypes import wintypes                      # noqa: E402

import sounds                                    # noqa: E402  real kill audio

# Load main.pyw for the REAL shake_path. The first version of this preview had
# its own copy of the offsets and moved the window with wm_geometry, while the
# app used SetWindowPos — so the preview was never showing what shipped. Import
# it instead, and move the window exactly the way the app does.
_spec = importlib.util.spec_from_loader(
    'rambomain', importlib.machinery.SourceFileLoader(
        'rambomain', os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), 'main.pyw')))
_app_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_app_mod)
shake_path = _app_mod.shake_path

# RamBo's palette and row styling, copied so the preview looks like the app.
C = {
    'bg': '#121212', 'panel': '#1a1a1a', 'row': '#1f1f1f', 'row_alt': '#272727',
    'border': '#2e2e2e', 'text': '#dcdcdc', 'dim': '#6b6b6b', 'dimmer': '#4a4a4a',
    'red': '#e05252', 'green': '#4caf50', 'warn': '#c0392b', 'select': '#1e4468',
}
TAG_STYLE = {
    'zombie':    ('#e05252', '#2b1616'),
    'hung':      ('#e07840', '#2b2015'),
    'orphan':    ('#b06ed8', '#241b2b'),
    'dup_main':  ('#e0c040', ''),
    'dup_child': ('#98842a', ''),
    'clean':     ('#dcdcdc', ''),
}
FONT_UI, FONT_DATA = ("Segoe UI", 9), ("Consolas", 9)

# The row flashes this colour before fading out to the background.
FLASH_FG, FLASH_BG = '#ffffff', C['warn']

# (blinks, blink_ms, fade_steps, fade_ms, amp, frames, cycles, decay)
# The last four drive shake_path(). Swing is peak-to-peak travel in pixels and
# Hz is how fast it reverses — keep Hz high and swing small for a vibration,
# and never pair a big swing with a high Hz or the window reads as blinking.
PRESETS = {
    'Fine':    (3, 90, 6, 45, 4, 14, 4.5, 0.8),   # 6px swing, 12.5 Hz, 240ms  <- shipped
    'Buzz':    (3, 90, 6, 45, 5, 12, 3.0, 0.8),   # 9px swing,  9.6 Hz, 208ms
    'Shipped': (3, 90, 6, 45, 10, 18, 2.0, 0.8),  # 16px swing, 4.9 Hz, 304ms
}

ROWS = [
    ("chrome.exe", 8412, "482.1 MB", "Dupe · Main", "Main", "9", 'dup_main'),
    ("chrome.exe", 8536, "212.7 MB", "Dupe · Child", "Child", "9", 'dup_child'),
    ("Discord.exe", 14002, "331.5 MB", "Not Responding", "—", "—", 'hung'),
    ("steamwebhelper.exe", 6120, "198.0 MB", "Dupe · Child", "Child", "4", 'dup_child'),
    ("OldService.exe", 2288, "12.4 MB", "Zombie", "—", "—", 'zombie'),
    ("backup_agent.exe", 9931, "44.8 MB", "Orphan", "—", "—", 'orphan'),
    ("explorer.exe", 4100, "121.3 MB", "—", "—", "—", 'clean'),
    ("Code.exe", 7745, "612.9 MB", "Dupe · Main", "Main", "6", 'dup_main'),
]


def lerp(a, b, t):
    """Blend two #rrggbb colours; t=0 gives a, t=1 gives b."""
    a, b = a.lstrip('#'), b.lstrip('#')
    return '#%02x%02x%02x' % tuple(
        round(int(a[i:i + 2], 16) + (int(b[i:i + 2], 16) - int(a[i:i + 2], 16)) * t)
        for i in (0, 2, 4))


class Preview(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RamBo — kill FX preview")
        self.geometry("760x420+300+220")
        self.configure(bg=C['bg'])
        self._dying = set()
        self._shaking = False
        self.preset = tk.StringVar(value='Fine')
        self._style()
        self._build()

    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("R.Treeview", background=C['row'], fieldbackground=C['row'],
                    foreground=C['text'], rowheight=26, borderwidth=0, font=FONT_DATA)
        s.configure("R.Treeview.Heading", background=C['panel'], foreground=C['dim'],
                    relief=tk.FLAT, font=FONT_UI)
        s.map("R.Treeview", background=[('selected', C['select'])],
              foreground=[('selected', '#ffffff')])
        s.layout("R.Treeview", [('R.Treeview.treearea', {'sticky': 'nswe'})])

    def _build(self):
        bar = tk.Frame(self, bg=C['bg'], padx=16, pady=10)
        bar.pack(fill=tk.X)
        tk.Label(bar, text="Select rows, then KILL.", bg=C['bg'], fg=C['dim'],
                 font=FONT_UI).pack(side=tk.LEFT)

        tk.Button(bar, text="  KILL  ", command=self._kill, bg=C['warn'],
                  fg='#ffffff', font=("Segoe UI Semibold", 9), bd=0,
                  relief=tk.FLAT, activebackground=C['red'],
                  activeforeground='#ffffff', cursor="hand2",
                  padx=10, pady=4).pack(side=tk.RIGHT)
        tk.Button(bar, text="  Reset  ", command=self._reset, bg=C['border'],
                  fg=C['text'], font=FONT_UI, bd=0, relief=tk.FLAT,
                  cursor="hand2", padx=8, pady=4).pack(side=tk.RIGHT, padx=6)

        for name in PRESETS:
            tk.Radiobutton(bar, text=name, value=name, variable=self.preset,
                           bg=C['bg'], fg=C['text'], selectcolor=C['panel'],
                           activebackground=C['bg'], activeforeground=C['text'],
                           font=FONT_UI, bd=0, highlightthickness=0).pack(
                side=tk.RIGHT, padx=2)

        frame = tk.Frame(self, bg=C['bg'], padx=16, pady=4)
        frame.pack(fill=tk.BOTH, expand=True)
        cols = ("process", "pid", "memory", "issue", "role", "instances")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                 style="R.Treeview", selectmode="extended")
        for cid, head, w, anc in [("process", "PROCESS NAME", 230, tk.W),
                                  ("pid", "PID", 70, tk.CENTER),
                                  ("memory", "MEMORY", 100, tk.E),
                                  ("issue", "ISSUE", 130, tk.CENTER),
                                  ("role", "ROLE", 80, tk.CENTER),
                                  ("instances", "INSTANCES", 80, tk.CENTER)]:
            self.tree.heading(cid, text=head, anchor=anc)
            self.tree.column(cid, width=w, minwidth=55, anchor=anc)
        self.tree.pack(fill=tk.BOTH, expand=True)

        self.tree.tag_configure('alt', background=C['row_alt'])
        for tag, (fg, bg) in TAG_STYLE.items():
            self.tree.tag_configure(tag, foreground=fg, **({'background': bg} if bg else {}))
        self.tree.tag_configure('flash', foreground=FLASH_FG, background=FLASH_BG)
        self.tree.tag_configure('flash_off', foreground=C['red'], background=C['row'])
        # Fade tags are reconfigured per preset, since the step count varies.
        self._reset()

    def _cfg_fade(self, steps):
        """Build fade0..fadeN, easing flash colours down into the row background."""
        for i in range(steps):
            t = (i + 1) / steps
            self.tree.tag_configure(f'fade{i}',
                                    foreground=lerp(FLASH_FG, C['row'], t),
                                    background=lerp(FLASH_BG, C['row'], t))

    def _reset(self):
        self._dying.clear()
        self.tree.delete(*self.tree.get_children())
        for i, (name, pid, mem, issue, role, inst, tag) in enumerate(ROWS):
            tags = [tag] + (['alt'] if i % 2 else [])
            self.tree.insert('', tk.END, iid=str(pid),
                             values=(name, pid, mem, issue, role, inst),
                             tags=tuple(tags))

    # ── the two effects ───────────────────────────────────────────────────────
    def _shake(self, amp, frames, cycles, decay):
        """Recoil the window exactly the way main.pyw._shake does.

        SetWindowPos on the real HWND, not wm_geometry — matching the app is
        the whole point of this preview."""
        if self._shaking or self.state() != 'normal':
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
        except Exception:
            return
        ox, oy = rect.left, rect.top
        flags = 0x0001 | 0x0004 | 0x0010          # NOSIZE | NOZORDER | NOACTIVATE
        path = shake_path(amp, frames, cycles, decay)
        self._shaking = True

        def move(x, y):
            try:
                ctypes.windll.user32.SetWindowPos(hwnd, 0, x, y, 0, 0, flags)
            except Exception:
                pass

        def step(i=0):
            if i >= len(path):
                move(ox, oy)
                self._shaking = False
                return
            dx, dy = path[i]
            move(ox + dx, oy + dy)
            self.after(_app_mod.SHAKE_MS, step, i + 1)

        step()

    def _die(self, iid, base_tag, step=0):
        """Blink the row a few times, fade it out, then remove it."""
        if not self.tree.exists(iid):
            return
        blinks, blink_ms, fade_steps, fade_ms = PRESETS[self.preset.get()][:4]

        if step < blinks * 2:
            # Alternate hot/cold so the row reads as "being shot at".
            self.tree.item(iid, tags=('flash',) if step % 2 == 0 else ('flash_off',))
            self.after(blink_ms, self._die, iid, base_tag, step + 1)
            return

        fade = step - blinks * 2
        if fade < fade_steps:
            self.tree.item(iid, tags=(f'fade{fade}',))
            self.after(fade_ms, self._die, iid, base_tag, step + 1)
            return

        self._dying.discard(iid)
        self.tree.delete(iid)

    def _kill(self):
        sel = [i for i in self.tree.selection() if i not in self._dying]
        if not sel:
            return
        (blinks, blink_ms, fade_steps, fade_ms,
         amp, frames, cycles, decay) = PRESETS[self.preset.get()]
        self._cfg_fade(fade_steps)
        self.tree.selection_remove(*sel)      # so the blue selection tint does not mask it
        sounds.play_kill()
        self._shake(amp, frames, cycles, decay)
        for iid in sel:
            self._dying.add(iid)
            self._die(iid, 'clean')
        xs = [p[0] for p in shake_path(amp, frames, cycles, decay)]
        flips = sum(1 for a, b in zip(xs, xs[1:]) if a * b < 0)
        span = len(xs) * _app_mod.SHAKE_MS
        self.title(f"RamBo — kill FX   {self.preset.get()}: "
                   f"swing {max(xs) - min(xs)}px, "
                   f"{flips / (span / 1000) / 2:.1f}Hz, {span}ms")


if __name__ == "__main__":
    Preview().mainloop()
