# RamBo — Group Select, Live Scan & RAM Bar Design

**Date:** 2026-05-13

## Summary

Six improvements to `main.pyw`:
1. Group-aware selection (click Main → whole group selected)
2. Ctrl+click to toggle individual rows
3. Delete key shortcut to kill selected
4. RAM usage bar in the status bar
5. Rolling live scan (auto-refresh every 5s)
6. "Kill Children Only" button (visible only when a Main row is selected)

No new files. All changes are in `main.pyw`.

---

## 1 · Group Selection & Keyboard Shortcut

### Bindings (added in `_build_tree`)

| Event | Handler |
|---|---|
| `<Button-1>` | `_on_click` |
| `<Control-Button-1>` | `_on_ctrl_click` |
| `<Delete>` | `_kill_selected` |

Both click handlers return `"break"` to suppress tkinter's default selection behaviour.

### `_on_click(event)`
1. Identify row under cursor via `self.tree.identify_row(event.y)`.
2. If no row, clear selection and return.
3. If row tag is `dup_main`: collect all visible iids whose `process` column matches → `selection_set(matching_iids)`.
4. Otherwise: `selection_set([iid])`.
5. Call `_on_select()`.

### `_on_ctrl_click(event)`
1. Identify row under cursor.
2. If already selected: `selection_remove([iid])`. Otherwise: `selection_add([iid])`.
3. Call `_on_select()`.

### Delete key
Bound directly to `_kill_selected`. Existing empty-selection guard handles the no-op case.

---

## 2 · RAM Bar (Status Bar)

`_build_statusbar` gains a RAM progress bar on the right side of the existing status bar panel, updated on the same cadence as the live scan.

Layout (right side of status bar):
```
RAM  [████████░░]  9.4 / 16 GB
```

- Bar colour: green < 60%, yellow 60–85%, red > 85%.
- Values from `psutil.virtual_memory()` (`.used`, `.total`).
- Updated via `_update_ram()` called at the end of each scan cycle.

New widget references stored as `self.ram_bar` (a `tk.Canvas` drawn rectangle) and `self.ram_label` (`tk.Label`).

---

## 3 · Rolling Live Scan

### UI changes
- Existing `▶ SCAN` button stays (one-shot).
- New `◉ LIVE` toggle button added to its left. When active shows `● LIVE` in green; when idle shows `◉ LIVE` in grey.
- While live mode is active, the one-shot SCAN button is visually dimmed (still functional).
- Status bar left side shows `● Live · refreshing in Xs` countdown during live mode.

### Behaviour
- `_live_toggle()`: flips `self._live` bool. If turning on, calls `_schedule_live()`. If turning off, cancels the pending `after` id.
- `_schedule_live()`: calls `_start_scan()` then schedules itself again with `self.after(5000, _schedule_live)`, storing the id in `self._live_after_id`.
- Live scan reuses the existing `_start_scan` / `_do_scan` / `_apply_filter` pipeline — no separate codepath.
- Selection is preserved across refreshes: before `_apply_filter` clears the tree, capture `self.tree.selection()`; after repopulating, restore any iids that still exist.

---

## 4 · Kill Children Only

### UI changes
- New `⊗ KILL CHILDREN` button (orange, `C['orange']`) added to the left of `⊗ KILL SELECTED` in the top bar.
- Initially hidden (`pack_forget`). Shown only when at least one `dup_main` row is in the current selection.
- `_on_select()` updated to show/hide this button based on selection tags.

### `_kill_children()`
1. Collect selected iids whose tag is `dup_main`.
2. For each, find all visible iids with the same process name whose tag is `dup_child`.
3. Confirm via `messagebox.askyesno` listing the child processes to be killed.
4. Kill each child PID via `psutil.Process(pid).kill()`.
5. Remove killed rows from tree and `_all_results`.
6. Update status bar counts.

---

## Out of Scope

- Configurable refresh interval (hardcoded 5s).
- "Select all by issue type" buttons.
- Right-click context menu.
- Any changes to scan logic or issue detection.
