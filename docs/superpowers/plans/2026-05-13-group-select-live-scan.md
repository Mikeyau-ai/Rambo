# RamBo Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add group-aware selection, Ctrl+click, Delete key kill shortcut, RAM bar, rolling live scan, and Kill Children Only button to `main.pyw`.

**Architecture:** All changes are isolated to `main.pyw`. New UI widgets are added to existing build methods. Two new click handlers replace the old passive `<<TreeviewSelect>>` binding. The live scan reuses the existing scan pipeline, scheduling itself with `self.after`. No new files.

**Tech Stack:** Python 3, tkinter/ttk, psutil

> **Note on testing:** This is a tkinter GUI app with no existing test framework. Tasks include manual verification steps in place of automated tests. Pure-logic helpers are verified inline.

---

### Task 1: Group selection — click Main selects whole group

**Files:**
- Modify: `Z:\rambo\main.pyw`

Replace the current passive `<<TreeviewSelect>>` binding with a direct `<Button-1>` handler that auto-expands selection to the full name group when a Main row is clicked.

- [ ] **Step 1: Replace the TreeviewSelect binding in `_build_tree`**

In `_build_tree`, find this line near the bottom:
```python
self.tree.bind("<<TreeviewSelect>>", self._on_select)
```
Replace it with:
```python
self.tree.bind("<Button-1>", self._on_click)
```

- [ ] **Step 2: Add `_on_click` method to the `# ── Kill` section**

Add after `_on_select`:
```python
def _on_click(self, event):
    iid = self.tree.identify_row(event.y)
    if not iid:
        self.tree.selection_set([])
        self._on_select()
        return "break"
    tags = self.tree.item(iid, "tags")
    if "dup_main" in tags:
        name = self.tree.set(iid, "process")
        matching = [i for i in self.tree.get_children()
                    if self.tree.set(i, "process") == name]
        self.tree.selection_set(matching)
    else:
        self.tree.selection_set([iid])
    self._on_select()
    return "break"
```

- [ ] **Step 3: Manual verification**

Run `python main.pyw`, click SCAN. When results appear:
- Click a `Dupe · Main` row → all rows with the same process name should highlight blue simultaneously.
- Click a `Zombie` or `Child` row → only that row highlights.
- Click empty space below the list → selection clears, KILL SELECTED disables.

- [ ] **Step 4: Commit**
```bash
git add main.pyw
git commit -m "feat: click Main row selects entire duplicate group"
```

---

### Task 2: Ctrl+click to toggle individual rows

**Files:**
- Modify: `Z:\rambo\main.pyw`

- [ ] **Step 1: Add Ctrl+click binding in `_build_tree`**

Directly after the `<Button-1>` bind line added in Task 1:
```python
self.tree.bind("<Control-Button-1>", self._on_ctrl_click)
```

- [ ] **Step 2: Add `_on_ctrl_click` method**

Add directly after `_on_click`:
```python
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
```

- [ ] **Step 3: Manual verification**

Run `python main.pyw`, scan:
- Click a Main row (selects group). Ctrl+click one of the selected Children → it deselects. Ctrl+click it again → it reselects.
- Ctrl+click a Zombie row while a chrome group is selected → Zombie adds to selection without clearing the group.

- [ ] **Step 4: Commit**
```bash
git add main.pyw
git commit -m "feat: Ctrl+click toggles individual rows in/out of selection"
```

---

### Task 3: Delete key kills selected

**Files:**
- Modify: `Z:\rambo\main.pyw`

- [ ] **Step 1: Add Delete binding in `_build_tree`**

Directly after the `<Control-Button-1>` bind line:
```python
self.tree.bind("<Delete>", lambda e: self._kill_selected())
```

- [ ] **Step 2: Manual verification**

Run `python main.pyw`, scan, select a row, press Delete → same confirmation dialog as KILL SELECTED appears. Select nothing, press Delete → nothing happens.

- [ ] **Step 3: Commit**
```bash
git add main.pyw
git commit -m "feat: Delete key triggers kill on selected processes"
```

---

### Task 4: RAM bar in the status bar

**Files:**
- Modify: `Z:\rambo\main.pyw`

- [ ] **Step 1: Rewrite `_build_statusbar` to include RAM widgets**

Replace the entire `_build_statusbar` method:
```python
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
```

- [ ] **Step 2: Add `_update_ram` method**

Add to the class (place it near `_build_statusbar`):
```python
def _update_ram(self):
    mem = psutil.virtual_memory()
    used_gb = mem.used / 1024 ** 3
    total_gb = mem.total / 1024 ** 3
    pct = mem.percent
    color = C['green'] if pct < 60 else (C['yellow'] if pct < 85 else C['red'])
    bar_w = int(100 * pct / 100)
    self.ram_canvas.coords(self.ram_fill, 0, 0, bar_w, 8)
    self.ram_canvas.itemconfig(self.ram_fill, fill=color)
    self.ram_label.config(text=f"{used_gb:.1f} / {total_gb:.1f} GB")
```

- [ ] **Step 3: Call `_update_ram` at the end of `_scan_done`**

In `_scan_done`, add as the last line:
```python
self._update_ram()
```

- [ ] **Step 4: Manual verification**

Run `python main.pyw` — RAM bar should be visible in the bottom-right immediately on launch showing current usage. Run a scan — values refresh after scan completes. Bar colour: green when low usage, yellow when > 60%, red when > 85%.

- [ ] **Step 5: Commit**
```bash
git add main.pyw
git commit -m "feat: add RAM usage bar to status bar"
```

---

### Task 5: Rolling live scan (LIVE toggle button)

**Files:**
- Modify: `Z:\rambo\main.pyw`

- [ ] **Step 1: Add live state variables in `__init__`**

In `__init__`, after `self._all_results = []`:
```python
self._live          = False
self._live_after_id = None
```

- [ ] **Step 2: Rewrite the button block in `_build_topbar`**

Replace everything from `self.kill_btn = ...` to the end of `_build_topbar` with the full final button layout (includes `kill_children_btn` placeholder — the method is wired up in Task 7):
```python
self.kill_btn = self._mk_btn(btns, "⊗  KILL SELECTED",
                             self._kill_selected, C['red'], state=tk.DISABLED)
self.kill_btn.pack(side=tk.RIGHT, padx=(6, 0))

self.kill_children_btn = self._mk_btn(btns, "⊗  KILL CHILDREN",
                                      self._kill_children, C['orange'], state=tk.DISABLED)
self.kill_children_btn.pack(side=tk.RIGHT, padx=(6, 0))

self.live_btn = self._mk_btn(btns, "◉  LIVE", self._live_toggle, C['dim'])
self.live_btn.pack(side=tk.RIGHT, padx=(6, 0))

self.scan_btn = self._mk_btn(btns, "▶  SCAN", self._start_scan, C['green'])
self.scan_btn.pack(side=tk.RIGHT, padx=(6, 0))
```

Also add these two stub methods to the class (they'll be fully implemented in Tasks 5 and 7 — stubs prevent NameErrors while building):
```python
def _live_toggle(self):
    pass

def _kill_children(self):
    pass
```

- [ ] **Step 3: Add `_live_toggle` and `_schedule_live` methods**

Add after `_scan_done`:
```python
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
```

- [ ] **Step 4: Update `_scan_done` to show live countdown**

Replace the `_scan_done` method:
```python
def _scan_done(self):
    self._scanning = False
    self.scan_btn.config(state=tk.NORMAL, text="▶  SCAN")
    if not self._all_results:
        self.status_var.set("No issues found — system looks clean")
        self.summary_var.set("")
    if self._live:
        self.status_var.set("● Live · next refresh in 5s")
    self._update_ram()
```

- [ ] **Step 5: Manual verification**

Run `python main.pyw`. Click `◉ LIVE` — button turns green and shows `● LIVE`, scan starts immediately, repeats every 5s. Status bar shows `● Live · next refresh in 5s`. Click `● LIVE` again — button goes grey, status shows "Live scan stopped", no further scans fire.

- [ ] **Step 6: Commit**
```bash
git add main.pyw
git commit -m "feat: add rolling live scan with 5s interval"
```

---

### Task 6: Preserve selection across live refreshes

**Files:**
- Modify: `Z:\rambo\main.pyw`

Without this, every live refresh wipes the user's selection mid-action.

- [ ] **Step 1: Capture and restore selection in `_apply_filter`**

In `_apply_filter`, replace the opening lines:
```python
# before
def _apply_filter(self):
    self.tree.delete(*self.tree.get_children())
    hide_sys = self.f_sys.get()
    shown    = 0
```
with:
```python
def _apply_filter(self):
    prev_sel = set(self.tree.selection())
    self.tree.delete(*self.tree.get_children())
    hide_sys = self.f_sys.get()
    shown    = 0
```

Then at the end of `_apply_filter`, before the final `self.kill_btn.config(...)` line, add:
```python
        to_restore = [iid for iid in prev_sel if self.tree.exists(iid)]
        if to_restore:
            self.tree.selection_set(to_restore)
```

- [ ] **Step 2: Manual verification**

Run `python main.pyw`, enable LIVE. Select a group. Wait for a refresh — selection should survive intact. If a selected process disappears between refreshes (e.g. it was killed externally), it is simply absent from the restored selection.

- [ ] **Step 3: Commit**
```bash
git add main.pyw
git commit -m "fix: preserve treeview selection across live scan refreshes"
```

---

### Task 7: Kill Children Only button

**Files:**
- Modify: `Z:\rambo\main.pyw`

- [ ] **Step 1: Note on button layout**

`kill_children_btn` was already added to `_build_topbar` as a stub in Task 5. No changes needed here — just implement the method and wire up `_on_select`.

- [ ] **Step 2: Update `_on_select` to enable/disable the button**

Replace `_on_select`:
```python
def _on_select(self, _=None):
    sel = self.tree.selection()
    has_sel = bool(sel)
    has_main = any("dup_main" in self.tree.item(iid, "tags") for iid in sel)
    self.kill_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)
    self.kill_children_btn.config(state=tk.NORMAL if has_main else tk.DISABLED)
```

- [ ] **Step 3: Add `_kill_children` method**

Add after `_kill_selected`:
```python
def _kill_children(self):
    sel = self.tree.selection()
    if not sel:
        return

    # Collect child iids for every selected Main row
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
```

- [ ] **Step 4: Manual verification**

Run `python main.pyw`, scan. Click a `Dupe · Main` row — `⊗ KILL CHILDREN` button should appear in orange next to `⊗ KILL SELECTED`. Click `⊗ KILL CHILDREN` — confirm dialog lists only child processes. After confirmation, children disappear from the list, Main row remains. Click a non-Main row — `⊗ KILL CHILDREN` disappears.

- [ ] **Step 5: Commit**
```bash
git add main.pyw
git commit -m "feat: add Kill Children Only button for duplicate main processes"
```
