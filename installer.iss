; installer.iss — Inno Setup script for RamBo.
;
; Wraps the PyInstaller one-dir build (dist\RamBo\) into dist\RamBo-Setup.exe.
; Everything the app needs, including the embedded CPython runtime and
; python3xx.dll, is installed to a real directory — which is the whole point:
; a zip lets Explorer "run" RamBo.exe straight out of the archive, where
; _internal\ was never extracted and loading the Python DLL fails.
;
; Built by build_installer.py, which supplies AppVersion from main.pyw.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "RamBo"
#define AppPublisher "Mikey"
#define AppExe "RamBo.exe"

[Setup]
; Never change AppId — it is what lets a new setup upgrade an existing
; install in place instead of leaving two entries in Apps & Features.
AppId={{7C2F1B4A-9D3E-4A61-8F27-1E5B6C0A9D34}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}

; Per-user install, deliberately. updater.py applies updates by robocopying
; over the install directory from the running (non-elevated) app, so the app
; must live somewhere it can write. With PrivilegesRequired=lowest,
; {autopf} resolves to %LOCALAPPDATA%\Programs. It also means no UAC prompt.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; The app is 64-bit (PyInstaller builds against the 64-bit interpreter).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=dist
OutputBaseFilename=RamBo-Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
; Without this, Apps & Features lists it as "RamBo version 1.0.0" even though
; it already shows the version in its own column.
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes

; Use the Restart Manager to shut down a running RamBo before overwriting it,
; rather than failing mid-copy or demanding a reboot.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Ticked by default — the desktop icon is how most people will actually launch
; RamBo — but it is a task rather than a fixed [Icons] entry so it can be
; unticked. Inno records the choice under the uninstall key and restores it on
; the next run, so a silent self-update honours an earlier opt-out instead of
; quietly putting the icon back.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The entire one-dir bundle: RamBo.exe plus _internal\ (python3xx.dll, the
; stdlib zip, psutil, Tcl/Tk, and the bundled icon/logo).
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; A real Start Menu folder, so the uninstaller is reachable from there and not
; only from Apps & Features.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; No `skipifsilent` — updater.py runs this installer with /SILENT and then
; exits, so this entry is what relaunches RamBo once the update finishes.
; Adding skipifsilent back would leave the user staring at a closed app.
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall

[UninstallDelete]
; Older builds self-updated by robocopying a bundle over the install directory,
; which could leave files in _internal\ that this installer has no record of.
; Clear the folder explicitly so upgrading from such a build and then
; uninstalling does not leave anything behind.
;
; Never list "{app}" itself here: unins000.exe runs from that directory, and
; deleting it out from under itself leaves an orphaned entry in Apps & Features
; pointing at an uninstaller that no longer exists.
Type: filesandordirs; Name: "{app}\_internal"
