"""
Compile installer.iss into dist/RamBo-Setup.exe.

Kept separate from build.bat so the version in main.pyw stays the single
source of truth: it is read here and passed to the compiler as /DAppVersion,
rather than being duplicated in the .iss file.

Requires Inno Setup 6:  winget install JRSoftware.InnoSetup
"""
import os
import shutil
import subprocess
import sys

from package import DIST_DIR, SETUP_PATH, get_version

HERE = os.path.dirname(os.path.abspath(__file__))
ISS_PATH = os.path.join(HERE, 'installer.iss')

# winget and the standard installer both land in one of these; PATH is checked
# too so a portable/custom install still works.
_ISCC_CANDIDATES = [
    os.path.expandvars(r'%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe'),
    r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    r'C:\Program Files\Inno Setup 6\ISCC.exe',
]


def find_iscc():
    """Locate the Inno Setup command-line compiler, or return None."""
    for path in _ISCC_CANDIDATES:
        if os.path.isfile(path):
            return path
    return shutil.which('ISCC')


def main():
    if not os.path.isdir(DIST_DIR):
        sys.exit(f"No build found at {DIST_DIR} - run the PyInstaller build first.")

    iscc = find_iscc()
    if iscc is None:
        print("  Inno Setup 6 not found. Install it with:\n"
              "    winget install JRSoftware.InnoSetup")
        return 1

    version = get_version()
    result = subprocess.run([iscc, f'/DAppVersion={version}', ISS_PATH],
                            capture_output=True, text=True)
    if result.returncode != 0:
        # ISCC reports compile errors on stdout, not stderr.
        print(result.stdout.strip() or result.stderr.strip())
        print("  Installer build FAILED.")
        return 1

    print(f"  Built {SETUP_PATH}"
          f" ({os.path.getsize(SETUP_PATH) / 1024 ** 2:.1f} MB)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
