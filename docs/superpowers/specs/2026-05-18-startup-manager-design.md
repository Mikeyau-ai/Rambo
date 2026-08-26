# RamBo — Startup Manager Tab Design

**Date:** 2026-05-18

## Summary

Add a **🚀 STARTUP** tab to RamBo that scans Windows startup entries from Registry Run keys and Task Scheduler, displays them in a tree with enable/disable controls, and toggles them non-destructively. Implemented across two files: a new `startup.py` data module and changes to `main.pyw` for the UI.

---

## 1 · Architecture

### Files

| File | Role |
|---|---|
| `startup.py` | New. Pure data module — scan, deduplicate, enable/disable. No tkinter. |
| `main.pyw` | Modified. Adds `ttk.Notebook`, wires up the new startup tab UI. |

### `startup.py` public API

```python
class StartupAccessError(Exception):
    """Raised when enable/disable requires elevation."""

def scan_startup() -> list[dict]:
    """Scan all startup sources, deduplicate, return sorted list."""

def set_enabled(entry: dict, enabled: bool) -> None:
    """Enable or disable a startup entry. Raises StartupAccessError on permission failure."""
```

### Entry dict schema

```python
{
    'name':    str,   # display name
    'command': str,   # full command string
    'source':  str,   # 'HKCU' | 'HKLM' | 'Task'
    'enabled': bool,  # current state
    'key':     str,   # registry value name OR task name (used by set_enabled)
    'hive':    int,   # winreg hive constant (registry entries only; None for Task)
}
```

---

## 2 · Data Layer (`startup.py`)

### Sources scanned

| Source | Registry path / command |
|---|---|
| HKCU Run | `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` |
| HKLM Run | `HKEY_LOCAL_MACHINE\Software\Microsoft\Windows\CurrentVersion\Run` |
| HKLM Run (32-bit) | `HKEY_LOCAL_MACHINE\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run` |
| Task Scheduler | `schtasks /query /fo CSV /v` — filtered to tasks with "At log on" trigger, excluding SYSTEM-owned tasks |

### Enabled/disabled state

**Registry:** Read from `...\Explorer\StartupApproved\Run` (same hive). Binary value — first byte `0x02` = enabled, `0x03` = disabled. If no `StartupApproved` value exists for an entry, it is considered enabled.

**To toggle registry:** Write `\x02\x00...\x00` (12 bytes) or `\x03\x00...\x00` to `StartupApproved\Run` under the matching hive. The original `Run` key value is never modified or deleted.

**Task Scheduler:** State read from `schtasks` CSV `Status` column. Toggle via:
```
schtasks /change /tn "<task name>" /disable
schtasks /change /tn "<task name>" /enable
```

### Deduplication

Entries are keyed on `os.path.normcase(os.path.expandvars(first_token_of_command))`. On collision:
- HKCU beats HKLM (user-level takes precedence)
- Task beats registry (more metadata, explicit logon trigger)

### Error handling in `scan_startup`

- `PermissionError` / `OSError` on any registry key → skip that source silently, continue
- `schtasks` non-zero exit or parse failure → skip Task Scheduler results silently, continue
- Never raises — always returns a list (may be empty)

### Error handling in `set_enabled`

- `PermissionError` on registry write → raise `StartupAccessError`
- `schtasks /change` non-zero exit → raise `StartupAccessError`

---

## 3 · UI (`main.pyw`)

### Layout restructure

`_build_ui` changes from:
```
topbar → filterbar → tree → statusbar
```
to:
```
topbar → notebook[processes_tab, startup_tab] → statusbar
```

- `processes_tab` contains: filterbar + process tree (unchanged content)
- `startup_tab` contains: startup toolbar + startup tree
- Statusbar remains outside the notebook (shared)

### Topbar button visibility

Topbar action buttons (SCAN, LIVE, TRIM RAM, TRIM SELECTED, KILL CHILDREN, KILL SELECTED) are only relevant to the Processes tab. On `<<NotebookTabChanged>>` event:
- Switching **to Startup tab**: hide all topbar action buttons via `pack_forget()`
- Switching **back to Processes tab**: restore buttons via `pack()`

The RAMBO title label and subtitle are always visible.

### Startup toolbar

A panel inside `startup_tab`, matching the `_build_filterbar` style:

| Widget | Behaviour |
|---|---|
| `▶  SCAN STARTUP` | Green, always enabled. Triggers background scan. |
| `⊘  DISABLE SELECTED` | Blue, disabled by default. Enabled when ≥1 row selected. |
| `✔  ENABLE SELECTED` | Blue, disabled by default. Enabled when ≥1 row selected. |
| Summary label (right-aligned) | `"X shown / Y found"` after scan |

### Startup tree columns

| Column | Width | Anchor | Notes |
|---|---|---|---|
| NAME | 220 | W | Entry display name |
| SOURCE | 70 | CENTER | HKCU / HKLM / Task — colour-coded |
| STATUS | 80 | CENTER | Enabled (green) / Disabled (grey) |
| COMMAND | fills | W | Full command string |

**Row tags:**
- `enabled` → default text colour
- `disabled` → `C['dim']` foreground (dimmed row)

**Source colours:**
- HKCU → `C['blue']`
- HKLM → `C['yellow']`
- Task → `C['orange']`

### New `RamBo` state

```python
self._startup_scanning  = False
self._startup_results   = []   # list[dict] from scan_startup()
```

### New `RamBo` methods

| Method | Description |
|---|---|
| `_build_notebook()` | Creates `ttk.Notebook`, moves filterbar+tree into processes tab, builds startup tab |
| `_build_startup_tab(parent)` | Builds startup toolbar + startup tree inside the tab frame |
| `_on_tab_change(event)` | Handles `<<NotebookTabChanged>>` — show/hide topbar buttons |
| `_start_startup_scan()` | Guards with `_startup_scanning`, spawns background thread |
| `_do_startup_scan()` | Background thread: calls `scan_startup()`, posts result via `after(0, ...)` |
| `_startup_scan_done(results)` | Main thread: populates tree, updates summary label |
| `_on_startup_select()` | Enables/disables DISABLE SELECTED and ENABLE SELECTED buttons |
| `_set_startup_enabled(enable)` | Calls `set_enabled()` for each selected entry; catches `StartupAccessError` → messagebox |

### Selection behaviour

- Click → select row
- Ctrl+click → toggle row
- Both DISABLE SELECTED and ENABLE SELECTED activate on any selection (no filtering by current state — allows bulk-setting a mixed selection)
- After operation: re-scan and refresh tree; status bar shows `"Disabled X item(s)"` or `"Enabled X item(s)"`

### Error UX

`StartupAccessError` → `messagebox.showwarning("Admin required", "This item requires administrator privileges to modify.")` — non-blocking, operation continues for remaining selected items.

---

## 4 · Out of Scope

- Startup folder scanning (`%APPDATA%\...\Startup` .lnk files)
- Services
- "Delete" / permanent removal of startup entries
- Undo/history
- Right-click context menu
- Configurable columns
