# Changelog

All notable changes to RamBo. Newest first. Bump `APP_VERSION` in `main.pyw`
and add an entry here for every release.

Versions below 1.0.0 are reconstructed from the commit history and the design
docs in `docs/superpowers/`. They were never cut as numbered builds — the alpha
ran straight from source — so the numbers are a reading of that history rather
than tags that once existed.

## 1.5.0
- **Kill streaks.** Kills landing within 10 seconds of each other stack up: two
  earns a *Double Kill*, three or more a *Multi Kill*, called out by an
  announcer over the gunshot. The window restarts on every kill, so a sustained
  run keeps the streak alive rather than expiring on a fixed schedule.
- Kills are counted per process rather than per click, so clearing three rows
  in one go is a multi kill — announced once, not once per process.
- The lines are generated in the style of an arena-shooter announcer rather
  than taken from any game. `tools/generate_voice.py` regenerates them.

## 1.4.2
- A clearer message when antivirus removes the downloaded installer before it
  can run. That gap between downloading an unsigned exe and executing it is
  exactly what heuristic scanners act on, and "Update install failed" gave no
  hint that an exclusion, not a retry, is the fix.

## 1.4.1
- Filter tooltips appear under the chip you are hovering, instead of in the
  top-left corner of the screen. On Windows a borderless window ignores a move
  once it has been shown, so the tooltip is now positioned before it is ever
  displayed. It also flips above the chip rather than running off the bottom.
- The About window no longer shows this file's maintainer preamble, and renders
  bold, italic and `code` as formatting rather than printing the raw markdown
  markers. Bullets are rewrapped to the window width.

## 1.4.0
- Updates **ask before installing** again. 1.2.0 applied them without a word,
  which meant an update could land mid-session with no explanation. RamBo now
  says a new version is available, shows what changed, and asks. Everything
  after Yes runs without further interaction: it downloads, installs and
  reopens on its own.
- **No** skips that version for good, **Cancel** asks again next launch, and
  the **UPDATE** button stays available either way.
- The updated build now **confirms what it is** on first launch — the status
  bar shows *Updated to vX.Y.Z* in green for a few seconds, then hands itself
  back. Without it a silent install just restarts the app and nothing says it
  worked.

## 1.3.0
- The installer now creates a **desktop shortcut by default**, with a checkbox
  to decline it. Declining sticks: Inno records the choice under the uninstall
  key and restores it on the next run, so a silent self-update will not quietly
  put the icon back.

## 1.2.0
- **About / Changelog window**, opened by clicking the RAMBO wordmark in the
  header. Shows the running version, a link to the repo, a manual **Check for
  updates** button, and this changelog. The changelog is bundled into the
  build, so it reads the same offline and always describes the version in front
  of you rather than whatever is newest on GitHub.
- The header flags **(running from source)** on a dev run, where the updater is
  inert and "no updates" therefore means something different.

## 1.1.0
- RamBo now ships as an **installer** (`RamBo-Setup.exe`) instead of a zip.
  Running `RamBo.exe` from inside the archive failed with *"Failed to load
  Python DLL"*, because Explorer unpacks only the exe and not the `_internal`
  folder holding `python314.dll`. Installing to a real directory removes that
  failure mode entirely.
- The install is **per-user** (`%LOCALAPPDATA%\Programs\RamBo`), so there is no
  admin prompt, and it adds a Start Menu folder, an uninstaller and an entry in
  Apps & Features.
- **Live mode no longer rebuilds the list.** It used to clear the tree and
  re-insert every row on each tick, so the list blanked, the scroll position
  jumped to the top and the chosen sort order was lost every few seconds. The
  tree is now reconciled in place: only processes that exited are removed, only
  new ones are added, and only cells whose text actually changed are rewritten.
  Sort order, scroll position and selection all survive a refresh.
- **Live mode is roughly ten times cheaper.** A scan took about 15 seconds
  against a 5-second timer, so RamBo was effectively scanning without pause.
  Reading parent PIDs from a single `ppid_map()` call rather than one system
  snapshot per process accounts for most of it (4460ms to 11ms); caching the
  per-PID values that cannot change and skipping the expensive `status()`
  re-read on live ticks accounts for the rest. A tick is now about 1.6s.
- Live ticks are scheduled from the moment the previous one **finishes**, and
  never rest for less time than the scan itself took, so a slow machine backs
  off instead of scanning continuously. The status bar reports both figures.
- The list **populates itself on launch** rather than waiting for a click.
- **Kill feedback.** A gunshot when a process dies and a ricochet when it
  survives, with three takes of each so repeated kills do not loop. The killed
  row blinks, fades into the background and only then leaves the list, and the
  window gives a short recoil.
- **Updates install themselves silently.** Frozen builds download the new
  installer and run it with no prompt; the installer replaces the files and
  relaunches RamBo. It waits for any running scan, trim or kill animation to
  finish first, so the app never disappears mid-action. The **UPDATE** button
  now appears only as a fallback if that fails.
- The old updater unzipped a release over the install directory with robocopy,
  which left the version in Apps & Features stale and wrote files the
  uninstaller had no record of. Letting Inno Setup perform the upgrade keeps
  the install self-consistent.
- Filter chips gained **hover tooltips** explaining what each category actually
  detects — including why Suspended is normal for Store apps, and what makes a
  process an Orphan.

## 1.0.0
- First public build, published to GitHub Releases.
- **Self-update:** frozen builds check Releases on launch, download the new
  build and swap it in through a detached script, because a running exe cannot
  overwrite itself. Running from source never prompts.
- UI pass throughout: dark title bar via DWM immersive dark mode, `HoverButton`
  with real hover/press/disabled states (Tk's disabled look kept the full
  accent colour and read as broken), and `FilterChip` pills replacing Tk
  checkbuttons, which render a white indicator box on dark surfaces.
- Live name filter with placeholder, focus ring and clear button.
- Row banding, hover highlight, and severity tint for zombie/hung/orphan only —
  duplicates are the bulk of a scan and tinting them is noise.
- Segoe UI for chrome, Consolas retained for tabular data. Flattened clam's 3D
  edges on the notebook, tree and tabs; pill RAM meter; empty-state overlay.
- **Restart as administrator** button, shown only when not already elevated.
- Tree context menu (open file location, copy PID, copy row, kill), Ctrl+A to
  select all, Ctrl+C to copy as TSV.
- Sorting now runs on the backing record instead of re-parsing display text
  like `"197.4 MB"`.
- App icon redrawn at 4x supersample with LANCZOS downsampling, emitted as a
  6-frame `.ico`; the generator also produces the topbar logo.
- Build fix: `--icon` and `--add-data` were both missing, so the exe carried
  PyInstaller's default icon and `iconbitmap()` failed once frozen.

## 0.6.0 (alpha)
- **Orphan detection** — a non-system process whose parent no longer exists and
  which has been running for more than 12 hours. Typically a leftover helper or
  updater that was never cleaned up.
- Every column sortable, with direction arrows in the headings.

## 0.5.0 (alpha)
- The process tree lists **all** processes rather than only ones with an issue,
  so RamBo works as a general process browser and not just a problem report.
- Sort arrows added to the process tree headings.

## 0.4.0 (alpha)
- **Startup tab.** Reads HKCU Run, HKLM Run, HKLM WOW6432Node Run, the user and
  common Startup folders, and logon-triggered scheduled tasks.
- Enable and disable entries by writing the `StartupApproved` registry byte
  (`0x02` enabled, `0x03` disabled) rather than deleting the Run value, so a
  disabled entry can be switched back on.
- Entries colour-coded by source, sortable by column, and de-duplicated by
  executable path with Task > HKCU > HKLM priority.
- `StartupAccessError` cleanly separates the "needs elevation" case, which HKLM
  entries raise, from a genuine failure.
- Startup logic extracted to `startup.py`, a pure-logic module with no tkinter
  dependency.
- Scans and toggles moved onto worker threads so the window never blocks, and
  scan errors are surfaced instead of being swallowed.
- Rambo-themed app icon.

## 0.3.0 (alpha)
- **Working-set trim** via the Win32 `SetProcessWorkingSetSizeEx` API, in two
  modes: trim everything, or trim only the selected rows. Nothing is killed —
  Windows is simply asked to page out working-set RAM — and the amount freed is
  reported.

## 0.2.0 (alpha)
- **Live scan** — the list auto-refreshes on a 5-second timer.
- **RAM bar** in the status bar showing memory used against total.
- Group-aware selection: clicking a Main row selects its whole process group,
  with Ctrl+click to toggle individual rows.
- **Kill Children Only**, shown only when a Main row is selected, for dropping
  an app's helper processes without taking the app itself down.
- Delete key kills the current selection.

## 0.1.0 (alpha)
- First working build, predating version control. Single-file tkinter GUI with
  a dark palette, using `psutil` for process enumeration and `ctypes`/Win32 for
  everything psutil does not cover.
- **SCAN** classifies every process as Zombie, Not Responding (via
  `IsHungAppWindow`), Suspended, or Duplicate Main/Child, ordered by severity.
- Filter bar to show or hide each category, plus a Hide System toggle backed by
  a list of Windows processes that legitimately run many copies of themselves.
- **Kill selected** via `psutil.Process.kill()`.
