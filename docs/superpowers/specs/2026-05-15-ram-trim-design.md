# RamBo — Working Set Trim Design

**Date:** 2026-05-15

## Summary

Add a non-destructive RAM cleanup feature to `main.pyw` that trims working sets of running processes via the Win32 `SetProcessWorkingSetSizeEx` API. No processes are killed. Two modes: trim all processes globally, or trim only selected rows. All changes are in `main.pyw`.

---

## 1 · Win32 Helper

Module-level function `trim_process(pid: int) -> int`:

1. Opens a process handle via `kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)`
2. Reads working set before: `psutil.Process(pid).memory_info().rss`
3. Calls `kernel32.SetProcessWorkingSetSizeEx(handle, -1, -1, 0)` to release idle pages
4. Reads working set after and closes the handle
5. Returns bytes freed (before − after), or `0` on `AccessDenied` / `NoSuchProcess`

Protected system processes will raise `AccessDenied` — silently skipped. No new dependencies; project already uses `ctypes` and `psutil`.

---

## 2 · UI Changes

### Top bar button order (left to right on right side)

```
[▶ SCAN]  [◉ LIVE]  [✂ TRIM RAM]  [✂ TRIM SELECTED]  [⊗ KILL CHILDREN]  [⊗ KILL SELECTED]
```

- **`✂ TRIM RAM`** — `C['blue']`, always enabled. Trims all running processes.
- **`✂ TRIM SELECTED`** — `C['blue']`, disabled by default. Enabled when any row is selected (same condition as `KILL SELECTED`).

No confirmation dialog — trimming is non-destructive and immediately reversible by the OS.

### Status bar

- During trim: left label shows `"Trimming working sets…"`
- After trim: `"Trimmed X processes — freed Y MB"`
- RAM bar refreshes immediately after trim completes.

---

## 3 · New Methods

### `_trim_all()`

- Disables `trim_all_btn`, sets status to `"Trimming working sets…"`
- Spawns a background thread (same pattern as `_do_scan`)
- Thread iterates `psutil.pids()`, calls `trim_process(pid)` on each, accumulates total freed bytes and count of processes trimmed
- On completion: `self.after(0, ...)` fires on main thread to re-enable button, update status bar, and call `_update_ram()`

### `_trim_selected()`

- Reads selected iids from `self.tree.selection()`
- Calls `trim_process(int(iid))` on each — fast enough for a handful of PIDs to run on the main thread
- Updates status bar and calls `_update_ram()`

### `_on_select()` update

- One additional line: `self.trim_sel_btn.config(state=tk.NORMAL if has_sel else tk.DISABLED)`

---

## Out of Scope

- Standby list / modified page list flushing (requires admin, more aggressive)
- Threshold-based selective trim (trim only processes above N MB)
- Scheduled/automatic trim on a timer
- Per-process "freed" column in the tree view
