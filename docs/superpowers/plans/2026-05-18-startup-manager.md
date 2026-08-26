# Startup Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 🚀 STARTUP tab to RamBo that scans Windows Registry Run keys and Task Scheduler logon tasks, displays them in a styled tree, and lets the user non-destructively enable or disable entries.

**Architecture:** A new `startup.py` module handles all data concerns (scanning, deduplication, enable/disable via `StartupApproved` registry keys and `schtasks`). `main.pyw` is restructured to use a `ttk.Notebook` — the existing process view moves into tab 1, and a new startup tab is added as tab 2. The topbar action buttons are hidden when the startup tab is active.

**Tech Stack:** Python 3, tkinter/ttk, winreg (stdlib), subprocess (schtasks), psutil (existing)

---

## File Structure

| File | Change |
|---|---|
| `Z:\RamBo\startup.py` | **Create.** Pure data module — no tkinter. Exposes `scan_startup()`, `set_enabled()`, `StartupAccessError`. |
| `Z:\RamBo\main.pyw` | **Modify.** Add `ttk.Notebook`, startup tab UI, scan wiring, enable/disable actions. |

---

### Task 1: Create `startup.py` — registry scanning

**Files:**
- Create: `Z:\RamBo\startup.py`

No test runner in this project — verification is syntax check + manual inspection.

- [ ] **Step 1: Create `startup.py` with registry scanning**

Create `Z:\RamBo\startup.py` with this full content:

```python
"""
startup.py — Windows startup entry scanner and toggler for RamBo.
No tkinter dependency. Public API: scan_startup(), set_enabled(), StartupAccessError.
"""
import os
import winreg

class StartupAccessError(Exception):
    """Raised when enable/disable requires elevation."""


# Registry Run key locations to scan (hive, subkey, source label)
_RUN_KEYS = [
    (winreg.HKEY_CURRENT_USER,
     r'Software\Microsoft\Windows\CurrentVersion\Run',
     'HKCU'),
    (winreg.HKEY_LOCAL_MACHINE,
     r'Software\Microsoft\Windows\CurrentVersion\Run',
     'HKLM'),
    (winreg.HKEY_LOCAL_MACHINE,
     r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',
     'HKLM'),
]

# StartupApproved subkeys — used to read/write enabled state without deleting Run entries
_APPROVED_SUBKEYS = {
    winreg.HKEY_CURRENT_USER:  r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
    winreg.HKEY_LOCAL_MACHINE: r'Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
}


def _read_run_key(hive: int, subkey: str, source: str) -> list:
    """Return list of partial entry dicts from one Run registry key. enabled=True placeholder."""
    entries = []
    try:
        key = winreg.OpenKey(hive, subkey, access=winreg.KEY_READ)
    except OSError:
        return []
    with key:
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(key, i)
                entries.append({
                    'name':    name,
                    'command': value,
                    'source':  source,
                    'enabled': True,   # overwritten by _read_approved below
                    'key':     name,   # value name in the Run key
                    'hive':    hive,
                })
                i += 1
            except OSError:
                break
    return entries


def _read_approved(hive: int) -> dict:
    """Return {value_name: bool} from StartupApproved\Run. Missing name → True (enabled)."""
    subkey = _APPROVED_SUBKEYS.get(hive, '')
    result = {}
    try:
        key = winreg.OpenKey(hive, subkey, access=winreg.KEY_READ)
    except OSError:
        return result
    with key:
        i = 0
        while True:
            try:
                name, data, _ = winreg.EnumValue(key, i)
                # First byte: 0x02 = enabled, 0x03 = disabled
                result[name] = (len(data) > 0 and data[0] == 0x02)
                i += 1
            except OSError:
                break
    return result


def scan_startup() -> list:
    """Scan Registry Run keys and Task Scheduler; return deduplicated sorted list of entry dicts."""
    entries = []
    for hive, subkey, source in _RUN_KEYS:
        approved = _read_approved(hive)
        for e in _read_run_key(hive, subkey, source):
            e['enabled'] = approved.get(e['name'], True)
            entries.append(e)
    # Task Scheduler added in task 2; deduplication added in task 2
    return sorted(entries, key=lambda x: x['name'].lower())
```

- [ ] **Step 2: Verify syntax**

```
python -c "import ast; ast.parse(open('Z:/RamBo/startup.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Smoke-test registry read**

```
python -c "import sys; sys.path.insert(0, 'Z:/RamBo'); from startup import scan_startup; r = scan_startup(); print(f'{len(r)} entries'); [print(' -', e['name'], e['source'], e['enabled']) for e in r[:5]]"
```

Expected: prints a list of startup entries from your registry (0 or more — depends on the machine).

---

### Task 2: Add Task Scheduler scanning + deduplication to `startup.py`

**Files:**
- Modify: `Z:\RamBo\startup.py`

- [ ] **Step 1: Add `_scan_tasks()` function**

Add this function to `startup.py` after `_read_approved`:

```python
def _scan_tasks() -> list:
    """Return logon-triggered Task Scheduler entries, excluding SYSTEM tasks."""
    import subprocess
    import csv
    import io

    _SYSTEM_ACCOUNTS = {'SYSTEM', 'NT AUTHORITY\\SYSTEM', 'LOCAL SERVICE', 'NETWORK SERVICE'}

    try:
        result = subprocess.run(
            ['schtasks', '/query', '/fo', 'CSV', '/v'],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    text = result.stdout.decode('utf-8', errors='replace')
    try:
        reader = csv.DictReader(io.StringIO(text))
    except Exception:
        return []

    tasks = []
    seen_names = set()
    for row in reader:
        try:
            schedule_type = row.get('Schedule Type', '').lower()
            if 'logon' not in schedule_type:
                continue
            run_as = row.get('Run As User', '').strip().upper()
            if run_as in _SYSTEM_ACCOUNTS:
                continue
            task_name = row.get('TaskName', '').strip()
            if not task_name or task_name in seen_names:
                continue
            seen_names.add(task_name)
            command = row.get('Task To Run', '').strip()
            # 'Scheduled Task State' column: 'Enabled' or 'Disabled'
            state = row.get('Scheduled Task State', 'Enabled').strip().lower()
            display_name = os.path.basename(task_name.strip('\\')) or task_name
            tasks.append({
                'name':    display_name,
                'command': command,
                'source':  'Task',
                'enabled': state == 'enabled',
                'key':     task_name,
                'hive':    None,
            })
        except (KeyError, AttributeError):
            continue
    return tasks
```

- [ ] **Step 2: Add `_dedup()` function**

Add this function after `_scan_tasks`:

```python
def _dedup(entries: list) -> list:
    """Deduplicate by normalised executable path. Priority: Task > HKCU > HKLM."""
    priority = {'Task': 0, 'HKCU': 1, 'HKLM': 2}
    seen = {}
    for e in entries:
        try:
            raw = e['command'].strip('"').split('"')[0].split()[0]
            exe_key = os.path.normcase(os.path.expandvars(raw))
        except (IndexError, AttributeError):
            exe_key = e['name'].lower()
        current = seen.get(exe_key)
        if current is None or priority.get(e['source'], 9) < priority.get(current['source'], 9):
            seen[exe_key] = e
    return list(seen.values())
```

- [ ] **Step 3: Update `scan_startup()` to include tasks and dedup**

Replace the existing `scan_startup()` body with:

```python
def scan_startup() -> list:
    """Scan Registry Run keys and Task Scheduler; return deduplicated sorted list of entry dicts."""
    entries = []
    for hive, subkey, source in _RUN_KEYS:
        approved = _read_approved(hive)
        for e in _read_run_key(hive, subkey, source):
            e['enabled'] = approved.get(e['name'], True)
            entries.append(e)
    entries.extend(_scan_tasks())
    entries = _dedup(entries)
    return sorted(entries, key=lambda x: x['name'].lower())
```

- [ ] **Step 4: Verify syntax and smoke-test**

```
python -c "import ast; ast.parse(open('Z:/RamBo/startup.py').read()); print('OK')"
python -c "import sys; sys.path.insert(0, 'Z:/RamBo'); from startup import scan_startup; r = scan_startup(); print(f'{len(r)} entries after dedup'); [print(' -', e['name'], e['source'], 'EN' if e['enabled'] else 'DIS') for e in r]"
```

Expected: `OK`, then a list of entries including any Task Scheduler logon tasks.

---

### Task 3: Add `set_enabled()` to `startup.py`

**Files:**
- Modify: `Z:\RamBo\startup.py`

- [ ] **Step 1: Add `_set_registry_enabled()` helper**

Add after `_dedup`:

```python
def _set_registry_enabled(hive: int, name: str, enabled: bool) -> None:
    """Write to StartupApproved\Run to enable/disable without touching the Run key."""
    subkey = _APPROVED_SUBKEYS.get(hive, '')
    # 12-byte binary value: first byte 0x02=enabled, 0x03=disabled, rest zeros
    data = bytes([0x02 if enabled else 0x03]) + b'\x00' * 11
    try:
        key = winreg.OpenKey(hive, subkey, access=winreg.KEY_SET_VALUE)
    except FileNotFoundError:
        # StartupApproved key doesn't exist yet — create it
        try:
            key = winreg.CreateKeyEx(hive, subkey, access=winreg.KEY_SET_VALUE)
        except PermissionError as exc:
            raise StartupAccessError(str(exc)) from exc
    except PermissionError as exc:
        raise StartupAccessError(str(exc)) from exc
    try:
        with key:
            winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, data)
    except PermissionError as exc:
        raise StartupAccessError(str(exc)) from exc
```

- [ ] **Step 2: Add `_set_task_enabled()` helper**

Add after `_set_registry_enabled`:

```python
def _set_task_enabled(task_name: str, enabled: bool) -> None:
    """Enable or disable a scheduled task via schtasks /change."""
    import subprocess
    flag = '/enable' if enabled else '/disable'
    result = subprocess.run(
        ['schtasks', '/change', '/tn', task_name, flag],
        capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=10,
    )
    if result.returncode != 0:
        msg = result.stderr.decode(errors='replace').strip() or f'schtasks exited {result.returncode}'
        raise StartupAccessError(msg)
```

- [ ] **Step 3: Add public `set_enabled()` function**

Add after `_set_task_enabled`:

```python
def set_enabled(entry: dict, enabled: bool) -> None:
    """Enable or disable a startup entry. Raises StartupAccessError on permission failure."""
    if entry['source'] == 'Task':
        _set_task_enabled(entry['key'], enabled)
    else:
        _set_registry_enabled(entry['hive'], entry['key'], enabled)
```

- [ ] **Step 4: Verify syntax**

```
python -c "import ast; ast.parse(open('Z:/RamBo/startup.py').read()); print('OK')"
```

Expected: `OK`

---

### Task 4: Restructure `main.pyw` — introduce `ttk.Notebook`

**Files:**
- Modify: `Z:\RamBo\main.pyw`

The existing filterbar and tree currently pack into `self` (the window). We move them into a `ttk.Notebook` tab frame. `_build_filterbar` and `_build_tree` receive a `parent` parameter instead of using `self`.

- [ ] **Step 1: Add startup imports to `main.pyw`**

At the top of `main.pyw`, after the existing imports, add:

```python
from startup import scan_startup, set_enabled, StartupAccessError
```

- [ ] **Step 2: Add `self._btns_frame` reference in `_build_topbar`**

In `_build_topbar`, find this line:
```python
        btns = tk.Frame(bar, bg=C['bg'])
        btns.pack(side=tk.RIGHT)
```

Add one line after `btns.pack(...)`:
```python
        self._btns_frame = btns
```

- [ ] **Step 3: Update `_build_filterbar` to accept a `parent` parameter**

Change the method signature and its internal `tk.Frame` parent from `self` to `parent`:

```python
    def _build_filterbar(self, parent):
        bar = tk.Frame(parent, bg=C['panel'], pady=7, padx=20)
        bar.pack(fill=tk.X)
        # (rest of method body unchanged)
```

Only the first two lines change — `self` → `parent` in the signature and the `tk.Frame(...)` call.

- [ ] **Step 4: Update `_build_tree` to accept a `parent` parameter**

Change the method signature and its internal `tk.Frame` parent from `self` to `parent`:

```python
    def _build_tree(self, parent):
        frame = tk.Frame(parent, bg=C['bg'], padx=16, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        # (rest of method body unchanged)
```

Only the first two lines change.

- [ ] **Step 5: Add `_build_notebook()` method**

Add this new method to `RamBo` after `_build_topbar`:

```python
    def _build_notebook(self):
        style = ttk.Style(self)
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
```

- [ ] **Step 6: Update `_build_ui` to call `_build_notebook`**

Replace:
```python
    def _build_ui(self):
        self._build_topbar()
        self._build_filterbar()
        self._build_tree()
        self._build_statusbar()
```

With:
```python
    def _build_ui(self):
        self._build_topbar()
        self._build_notebook()
        self._build_statusbar()
```

- [ ] **Step 7: Add `_on_tab_change` method**

Add after `_build_notebook`:

```python
    def _on_tab_change(self, event):
        tab_idx = self.notebook.index(self.notebook.select())
        if tab_idx == 0:   # Processes
            self._btns_frame.pack(side=tk.RIGHT)
        else:              # Startup (or any future tab)
            self._btns_frame.pack_forget()
```

- [ ] **Step 8: Verify syntax and that the app opens**

```
python -c "import ast; ast.parse(open('Z:/RamBo/main.pyw').read()); print('OK')"
```

Expected: `OK`

Then run `python Z:/RamBo/main.pyw` and verify:
- App opens with two tabs: ⚙ PROCESSES and 🚀 STARTUP
- Processes tab shows the existing filterbar and process tree
- Startup tab shows an empty frame (content built in Task 5)
- Switching to Startup tab hides the topbar action buttons; switching back restores them

---

### Task 5: Build startup tab UI

**Files:**
- Modify: `Z:\RamBo\main.pyw` — add `_build_startup_tab` method

- [ ] **Step 1: Add startup state to `__init__`**

In `__init__`, after `self._live_after_id = None`, add:

```python
        self._startup_scanning = False
        self._startup_results  = []
```

- [ ] **Step 2: Add `_build_startup_tab` method**

Add after `_on_tab_change`:

```python
    def _build_startup_tab(self, parent):
        # ── Toolbar ────────────────────────────────────────────────────────────
        toolbar = tk.Frame(parent, bg=C['panel'], pady=7, padx=20)
        toolbar.pack(fill=tk.X)

        self.startup_scan_btn = self._mk_btn(
            toolbar, "▶  SCAN STARTUP", self._start_startup_scan, C['green'])
        self.startup_scan_btn.pack(side=tk.LEFT)

        self.startup_disable_btn = self._mk_btn(
            toolbar, "⊘  DISABLE SELECTED",
            lambda: self._set_startup_enabled(False), C['blue'], state=tk.DISABLED)
        self.startup_disable_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.startup_enable_btn = self._mk_btn(
            toolbar, "✔  ENABLE SELECTED",
            lambda: self._set_startup_enabled(True), C['blue'], state=tk.DISABLED)
        self.startup_enable_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.startup_summary_var = tk.StringVar(value="")
        tk.Label(toolbar, textvariable=self.startup_summary_var,
                 bg=C['panel'], fg=C['green'],
                 font=("Consolas", 9, "bold")).pack(side=tk.RIGHT)

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
            ("command", "COMMAND",  500, tk.W),
        ]
        for cid, heading, width, anchor in col_cfg:
            self.startup_tree.heading(cid, text=heading)
            self.startup_tree.column(cid, width=width, minwidth=40, anchor=anchor)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.startup_tree.yview)
        self.startup_tree.configure(yscrollcommand=sb.set)
        self.startup_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Row colours: source (enabled rows) or dim (disabled rows)
        # Multiple tags per row — 'disabled' is configured last so it overrides source colours
        self.startup_tree.tag_configure('src_hkcu', foreground=C['blue'])
        self.startup_tree.tag_configure('src_hklm', foreground=C['yellow'])
        self.startup_tree.tag_configure('src_task', foreground=C['orange'])
        self.startup_tree.tag_configure('disabled', foreground=C['dim'])

        self.startup_tree.bind("<Button-1>",         self._on_startup_click)
        self.startup_tree.bind("<Control-Button-1>", self._on_startup_ctrl_click)
```

- [ ] **Step 3: Verify syntax and visual**

```
python -c "import ast; ast.parse(open('Z:/RamBo/main.pyw').read()); print('OK')"
```

Run `python Z:/RamBo/main.pyw`. Click the 🚀 STARTUP tab — you should see the toolbar (SCAN STARTUP, greyed-out DISABLE/ENABLE buttons) and an empty tree with NAME / SOURCE / STATUS / COMMAND columns.

---

### Task 6: Wire startup scan and enable/disable actions

**Files:**
- Modify: `Z:\RamBo\main.pyw` — add 6 methods to `RamBo`

Add all methods after `_build_startup_tab`.

- [ ] **Step 1: Add `_start_startup_scan`**

```python
    def _start_startup_scan(self):
        if self._startup_scanning:
            return
        self._startup_scanning = True
        self.startup_scan_btn.config(state=tk.DISABLED, text="SCANNING...")
        self.status_var.set("Scanning startup entries…")
        threading.Thread(target=self._do_startup_scan, daemon=True).start()
```

- [ ] **Step 2: Add `_do_startup_scan`**

```python
    def _do_startup_scan(self):
        try:
            results = scan_startup()
        except Exception:
            results = []
        self.after(0, lambda: self._startup_scan_done(results))
```

- [ ] **Step 3: Add `_startup_scan_done`**

```python
    def _startup_scan_done(self, results):
        self._startup_scanning = False
        self._startup_results  = results
        self.startup_scan_btn.config(state=tk.NORMAL, text="▶  SCAN STARTUP")
        self.startup_tree.delete(*self.startup_tree.get_children())

        _SRC_TAG = {'HKCU': 'src_hkcu', 'HKLM': 'src_hklm', 'Task': 'src_task'}
        for i, e in enumerate(results):
            tags = [_SRC_TAG.get(e['source'], 'src_hkcu')]
            if not e['enabled']:
                tags.append('disabled')
            self.startup_tree.insert('', tk.END, iid=str(i),
                values=(e['name'], e['source'],
                        'Enabled' if e['enabled'] else 'Disabled',
                        e['command']),
                tags=tuple(tags))

        total = len(results)
        self.startup_summary_var.set(f"{total} found" if total else "")
        self.status_var.set(
            f"Found {total} startup item(s)" if total else "No startup items found")
        self._on_startup_select()
```

- [ ] **Step 4: Add click handlers and `_on_startup_select`**

```python
    def _on_startup_click(self, event):
        iid = self.startup_tree.identify_row(event.y)
        if not iid:
            self.startup_tree.selection_set([])
        else:
            self.startup_tree.selection_set([iid])
        self._on_startup_select()
        return "break"

    def _on_startup_ctrl_click(self, event):
        iid = self.startup_tree.identify_row(event.y)
        if not iid:
            return "break"
        if iid in self.startup_tree.selection():
            self.startup_tree.selection_remove([iid])
        else:
            self.startup_tree.selection_add([iid])
        self._on_startup_select()
        return "break"

    def _on_startup_select(self):
        has_sel = bool(self.startup_tree.selection())
        state   = tk.NORMAL if has_sel else tk.DISABLED
        self.startup_disable_btn.config(state=state)
        self.startup_enable_btn.config(state=state)
```

- [ ] **Step 5: Add `_set_startup_enabled`**

```python
    def _set_startup_enabled(self, enable: bool):
        sel = self.startup_tree.selection()
        if not sel:
            return
        changed, errors = 0, []
        for iid in sel:
            e = self._startup_results[int(iid)]
            try:
                set_enabled(e, enable)
                changed += 1
            except StartupAccessError as exc:
                errors.append(f"{e['name']}: {exc}")

        if errors:
            messagebox.showwarning(
                "Admin Required",
                f"Could not modify {len(errors)} item(s) — admin privileges required:\n"
                + "\n".join(errors),
                parent=self)

        action = "Enabled" if enable else "Disabled"
        self.status_var.set(f"{action} {changed} startup item(s)")
        self._start_startup_scan()   # re-scan to reflect new state
```

- [ ] **Step 6: Verify syntax**

```
python -c "import ast; ast.parse(open('Z:/RamBo/main.pyw').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 7: End-to-end manual test**

Run `python Z:/RamBo/main.pyw`:

1. Click 🚀 STARTUP tab — confirm topbar buttons disappear
2. Click ▶ SCAN STARTUP — button shows "SCANNING..." then restores; tree populates
3. Entries show with SOURCE coloured (HKCU = blue, HKLM = yellow, Task = orange); disabled entries are dimmed
4. Click a row — DISABLE SELECTED and ENABLE SELECTED become active
5. Ctrl+click a second row — both selected
6. Click ⊘ DISABLE SELECTED on an enabled HKCU entry — tree re-scans and that entry shows as Disabled
7. Select it again and click ✔ ENABLE SELECTED — re-scans and shows Enabled again
8. Switch back to ⚙ PROCESSES tab — topbar buttons reappear; SCAN/TRIM/KILL work as before

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `startup.py` with `StartupAccessError`, `scan_startup()`, `set_enabled()` | Tasks 1–3 |
| Registry HKCU, HKLM, WOW6432Node Run keys | Task 1 |
| StartupApproved non-destructive toggle | Tasks 1, 3 |
| Task Scheduler logon tasks via schtasks | Task 2 |
| Exclude SYSTEM-owned tasks | Task 2 |
| Deduplication (Task > HKCU > HKLM) | Task 2 |
| `scan_startup()` never raises | Task 2 (`except Exception` guard) |
| `ttk.Notebook` with dark theme | Task 4 |
| Processes tab — existing filterbar + tree unchanged | Task 4 |
| Topbar buttons hidden on startup tab | Tasks 4, `_on_tab_change` |
| Startup toolbar: SCAN STARTUP, DISABLE SELECTED, ENABLE SELECTED | Task 5 |
| Startup tree: NAME, SOURCE, STATUS, COMMAND | Task 5 |
| SOURCE colour-coded; disabled rows dimmed | Task 5 (multi-tag approach) |
| `_startup_scanning` re-entrancy guard | Task 6 |
| Re-scan after enable/disable | Task 6 (`_set_startup_enabled`) |
| `StartupAccessError` → messagebox | Task 6 |
| Startup state in `__init__` | Task 5, step 1 |

**Placeholder scan:** None found.

**Type consistency:** `scan_startup()` → `list`, `set_enabled(entry: dict, enabled: bool)` used identically in Tasks 3 and 6. `self._startup_results` is `list[dict]` — indexed by `int(iid)` in Task 6, populated in Task 6 `_startup_scan_done`. `self.startup_tree` created in Task 5, used in Task 6. `self._btns_frame` set in Task 4 step 2, used in `_on_tab_change` step 7. All consistent.
