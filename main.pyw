import tkinter as tk
from tkinter import ttk, messagebox
import psutil
from collections import defaultdict
import threading
import time
import ctypes
from ctypes import wintypes

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

from startup import scan_startup, set_enabled, StartupAccessError

# ── Palette ────────────────────────────────────────────────────────────────────
C = {
    'bg':       '#141414',
    'panel':    '#1e1e1e',
    'row':      '#242424',
    'border':   '#333333',
    'text':     '#d4d4d4',
    'dim':      '#5a5a5a',
    'green':    '#4caf50',
    'red':      '#e05252',
    'yellow':   '#e0a040',
    'orange':   '#e07840',
    'blue':     '#5296e0',
    'purple':   '#b06ed8',
    'select':   '#1a3a5c',
    'warn':     '#c0392b',
}

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

# tag → text colour
TAG_COLOR = {
    'zombie':     '#e05252',
    'hung':       '#e07840',
    'suspended':  '#5a5a5a',
    'dup_main':   '#e0c040',
    'dup_child':  '#8a7820',
    'orphan':     '#b06ed8',
}


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
        self._live          = False
        self._live_after_id = None
        self._build_ui()
        try:
            self.iconbitmap("icon.ico")
        except Exception:
            pass

    # ── UI ─────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_topbar()
        self._build_notebook()
        self._build_statusbar()

    def _build_topbar(self):
        bar = tk.Frame(self, bg=C['bg'], pady=12, padx=20)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="RAMBO", font=("Consolas", 22, "bold"),
                 bg=C['bg'], fg=C['green']).pack(side=tk.LEFT)
        tk.Label(bar, text="  RAM & Process Cleaner", font=("Consolas", 10),
                 bg=C['bg'], fg=C['dim']).pack(side=tk.LEFT, pady=6)

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

        self.live_btn = self._mk_btn(btns, "◉  LIVE", self._live_toggle, C['dim'])
        self.live_btn.pack(side=tk.RIGHT, padx=(6, 0))

        self.scan_btn = self._mk_btn(btns, "▶  SCAN", self._start_scan, C['green'])
        self.scan_btn.pack(side=tk.RIGHT, padx=(6, 0))

    def _build_filterbar(self, parent):
        bar = tk.Frame(parent, bg=C['panel'], pady=7, padx=20)
        bar.pack(fill=tk.X)

        tk.Label(bar, text="SHOW:", font=("Consolas", 9, "bold"),
                 bg=C['panel'], fg=C['dim']).pack(side=tk.LEFT, padx=(0, 12))

        self.f_dupes     = tk.BooleanVar(value=True)
        self.f_hung      = tk.BooleanVar(value=True)
        self.f_zombies   = tk.BooleanVar(value=True)
        self.f_suspended = tk.BooleanVar(value=True)
        self.f_orphans   = tk.BooleanVar(value=True)
        self.f_sys       = tk.BooleanVar(value=True)

        for label, var, color in [
            ("Duplicates",     self.f_dupes,     C['yellow']),
            ("Not Responding", self.f_hung,      C['orange']),
            ("Zombies",        self.f_zombies,   C['red']),
            ("Suspended",      self.f_suspended, C['dim']),
            ("Orphans",        self.f_orphans,   C['purple']),
            ("|  Hide System", self.f_sys,       C['dim']),
        ]:
            tk.Checkbutton(bar, text=label, variable=var,
                           bg=C['panel'], fg=color, selectcolor=C['row'],
                           activebackground=C['panel'], activeforeground=color,
                           font=("Consolas", 9), command=self._apply_filter
                           ).pack(side=tk.LEFT, padx=8)

    def _build_tree(self, parent):
        frame = tk.Frame(parent, bg=C['bg'], padx=16, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        style = ttk.Style(self)
        style.configure("R.Treeview",
                        background=C['row'], foreground=C['text'],
                        fieldbackground=C['row'], rowheight=26,
                        font=("Consolas", 9), borderwidth=0)
        style.configure("R.Treeview.Heading",
                        background=C['panel'], foreground=C['green'],
                        font=("Consolas", 9, "bold"), relief=tk.FLAT)
        style.map("R.Treeview",
                  background=[("selected", C['select'])],
                  foreground=[("selected", "white")])

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
            self.tree.heading(cid, text=heading, command=lambda c=cid: self._sort(c))
            self.tree.column(cid, width=width, minwidth=55, anchor=anchor)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        for tag, color in TAG_COLOR.items():
            self.tree.tag_configure(tag, foreground=color)

        self.tree.bind("<Button-1>",         self._on_click)
        self.tree.bind("<Control-Button-1>", self._on_ctrl_click)
        self.tree.bind("<Delete>",           lambda e: self._kill_selected())

        self._sort_col = None
        self._sort_rev = False

    def _build_notebook(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("R.TNotebook",
                        background=C['bg'], borderwidth=0,
                        tabmargins=[16, 8, 0, 0])
        style.configure("R.TNotebook.Tab",
                        background=C['panel'], foreground=C['dim'],
                        font=("Consolas", 10, "bold"), padding=[16, 6])
        style.map("R.TNotebook.Tab",
                  background=[("selected", C['panel'])],
                  foreground=[("selected", C['green'])])

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
        toolbar = tk.Frame(parent, bg=C['panel'], pady=7, padx=20)
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
            toolbar, text="", font=("Consolas", 9),
            bg=C['panel'], fg=C['dim'])
        self.startup_summary_lbl.pack(side=tk.RIGHT)

        # ── Tree ───────────────────────────────────────────────────────────────
        frame = tk.Frame(parent, bg=C['bg'], padx=16, pady=10)
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
            self.startup_tree.heading(cid, text=heading,
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
        self.startup_tree.tag_configure("src_hkcu",    foreground=C['blue'])
        self.startup_tree.tag_configure("src_hklm",    foreground=C['yellow'])
        self.startup_tree.tag_configure("src_task",    foreground=C['orange'])
        self.startup_tree.tag_configure("src_folder",  foreground=C['blue'])
        self.startup_tree.tag_configure("src_common",  foreground=C['yellow'])
        # disabled tag overrides source colour
        self.startup_tree.tag_configure("disabled", foreground=C['dim'])

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                           command=self.startup_tree.yview)
        self.startup_tree.configure(yscrollcommand=sb.set)

        sb.pack(side=tk.RIGHT, fill=tk.Y)
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

    def _build_statusbar(self):
        bar = tk.Frame(self, bg=C['panel'], pady=6, padx=20)
        bar.pack(fill=tk.X)

        self.status_var  = tk.StringVar(value="Ready — press SCAN to begin")
        self.summary_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.status_var,
                 bg=C['panel'], fg=C['dim'], font=("Consolas", 9)).pack(side=tk.LEFT)

        # RAM bar (right side)
        ram_frame = tk.Frame(bar, bg=C['panel'])
        ram_frame.pack(side=tk.RIGHT)
        tk.Label(ram_frame, text="RAM", bg=C['panel'], fg=C['dim'],
                 font=("Consolas", 9)).pack(side=tk.LEFT, padx=(0, 6))
        self.ram_canvas = tk.Canvas(ram_frame, width=100, height=8,
                                    bg=C['border'], highlightthickness=0)
        self.ram_canvas.pack(side=tk.LEFT)
        self.ram_fill = self.ram_canvas.create_rectangle(0, 0, 0, 8, fill=C['green'], width=0)
        self.ram_label = tk.Label(ram_frame, text="", bg=C['panel'], fg=C['text'],
                                  font=("Consolas", 9), width=14)
        self.ram_label.pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(bar, textvariable=self.summary_var,
                 bg=C['panel'], fg=C['green'], font=("Consolas", 9, "bold")).pack(side=tk.RIGHT, padx=(0, 20))

        self._update_ram()

    def _mk_btn(self, parent, text, cmd, color, state=tk.NORMAL):
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg="white", activebackground=color,
                         font=("Consolas", 10, "bold"), relief=tk.FLAT,
                         padx=16, pady=5, cursor="hand2", state=state, bd=0)

    # ── RAM ────────────────────────────────────────────────────────────────────
    def _update_ram(self):
        mem = psutil.virtual_memory()
        used_gb  = mem.used  / 1024 ** 3
        total_gb = mem.total / 1024 ** 3
        pct      = mem.percent
        color    = C['green'] if pct < 60 else (C['yellow'] if pct < 85 else C['red'])
        bar_w    = int(100 * pct / 100)
        self.ram_canvas.coords(self.ram_fill, 0, 0, bar_w, 8)
        self.ram_canvas.itemconfig(self.ram_fill, fill=color)
        self.ram_label.config(text=f"{used_gb:.1f} / {total_gb:.1f} GB")

    # ── Scan ───────────────────────────────────────────────────────────────────
    def _start_scan(self):
        if self._scanning:
            return
        self._scanning    = True
        self._all_results = []
        self.tree.delete(*self.tree.get_children())
        self.scan_btn.config(state=tk.DISABLED, text="SCANNING...")
        self.kill_btn.config(state=tk.DISABLED)
        self.kill_children_btn.config(state=tk.DISABLED)
        self.trim_all_btn.config(state=tk.DISABLED)
        self.status_var.set("Scanning processes...")
        self.summary_var.set("")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        try:
            results = self._find_issues()
            self._all_results = results
            self.after(0, self._apply_filter)
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"Error: {e}"))
        finally:
            self.after(0, self._scan_done)

    def _find_issues(self):
        issues      = []
        name_groups = defaultdict(list)
        hung_pids   = get_hung_pids()
        _now        = time.time()
        _live_pids  = {p.pid for p in psutil.process_iter(['pid'])}

        for proc in psutil.process_iter(['pid', 'name', 'status', 'memory_info', 'ppid', 'create_time']):
            try:
                name_groups[proc.info['name'].lower()].append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        for name_key, procs in name_groups.items():
            is_system = name_key in SYSTEM_NAMES
            count     = len(procs)

            group_pids = set()
            for p in procs:
                try:
                    group_pids.add(p.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            for proc in procs:
                try:
                    pid    = proc.pid
                    status = proc.status()
                    mem    = proc.memory_info().rss
                    name   = proc.name()
                    ppid   = proc.ppid()

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
                          and (_now - proc.info.get('create_time', _now)) >= 12 * 3600):
                        issues.append(self._make(
                            name, pid, mem, 'Orphan', 'orphan', '—', 1, is_system))

                    else:
                        issues.append(self._make(
                            name, pid, mem, '—', 'clean', '—', 1, is_system))

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        return sorted(issues, key=lambda x: (
            ISSUE_ORDER.get(x['issue'], 99), x['name'].lower()))

    @staticmethod
    def _make(name, pid, mem, issue, tag, role, count, is_system):
        return {
            'name': name, 'pid': pid, 'memory': mem,
            'issue': issue, 'tag': tag, 'role': role,
            'count': count, 'is_system': is_system,
        }

    def _scan_done(self):
        self._scanning = False
        self.scan_btn.config(state=tk.NORMAL, text="▶  SCAN")
        self.trim_all_btn.config(state=tk.NORMAL)
        has_issues = any(r['issue'] != '—' for r in self._all_results)
        if self._all_results and not has_issues:
            self.status_var.set("No issues found — system looks clean ✓")
        if self._live:
            self.status_var.set("● Live · next refresh in 5s")
        self._update_ram()

    # ── Live scan ──────────────────────────────────────────────────────────────
    def _live_toggle(self):
        self._live = not self._live
        if self._live:
            self.live_btn.config(text="●  LIVE", bg=C['green'])
            self._schedule_live()
        else:
            self.live_btn.config(text="◉  LIVE", bg=C['dim'])
            if self._live_after_id:
                self.after_cancel(self._live_after_id)
                self._live_after_id = None
            self.status_var.set("Live scan stopped")

    def _schedule_live(self):
        if not self._live:
            return
        self._start_scan()
        self._live_after_id = self.after(5000, self._schedule_live)

    # ── Filter & sort ──────────────────────────────────────────────────────────
    def _apply_filter(self):
        prev_sel = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        hide_sys = self.f_sys.get()
        shown    = 0

        for r in self._all_results:
            if hide_sys and r['is_system']:
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

            count_str = str(r['count']) if 'Dupe' in r['issue'] else '—'
            self.tree.insert('', tk.END, iid=str(r['pid']),
                             values=(r['name'], r['pid'], fmt_mem(r['memory']),
                                     r['issue'], r['role'], count_str),
                             tags=(r['tag'],))
            shown += 1

        # Restore selection surviving the refresh
        to_restore = [iid for iid in prev_sel if self.tree.exists(iid)]
        if to_restore:
            self.tree.selection_set(to_restore)

        total = len(self._all_results)
        if total:
            self.status_var.set("Scan complete")
            self.summary_var.set(f"{shown} shown  /  {total} found")
        self.kill_btn.config(state=tk.DISABLED)
        self.kill_children_btn.config(state=tk.DISABLED)
        self._on_select()

    def _sort(self, col):
        rows = [(self.tree.set(k, col), k) for k in self.tree.get_children()]
        rev  = (self._sort_col == col) and not self._sort_rev

        def key(v):
            try:
                return (0, float(v[0].replace(' KB','e3').replace(' MB','e6')
                                     .replace(' GB','e9').replace('—','0')))
            except ValueError:
                return (1, v[0].lower())

        rows.sort(key=key, reverse=rev)
        for i, (_, k) in enumerate(rows):
            self.tree.move(k, '', i)
        self._sort_col = col
        self._sort_rev = rev

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
        iid = self.tree.identify_row(event.y)
        if not iid:
            self.tree.selection_set([])
            self._on_select()
            return "break"
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
                self.tree.delete(iid)
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                failed.append(f"PID {iid}: {e}")

        killed_pids       = {int(iid) for iid in sel}
        self._all_results = [r for r in self._all_results if r['pid'] not in killed_pids]

        shown = len(self.tree.get_children())
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
                self.tree.delete(iid)
                killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                failed.append(f"PID {iid}: {e}")

        killed_pids       = {int(iid) for iid in child_iids}
        self._all_results = [r for r in self._all_results if r['pid'] not in killed_pids]

        shown = len(self.tree.get_children())
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
