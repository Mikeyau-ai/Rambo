"""
Shared packaging helpers for the release scripts.

The release scripts and build_installer.py need the same paths and the same
version string, so they live here rather than being duplicated in each.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, 'dist', 'RamBo')
ZIP_PATH = os.path.join(HERE, 'dist', 'RamBo.zip')
SETUP_PATH = os.path.join(HERE, 'dist', 'RamBo-Setup.exe')


def get_version():
    """Read APP_VERSION out of main.pyw — the single source of truth."""
    with open(os.path.join(HERE, 'main.pyw'), encoding='utf-8') as fh:
        match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']',
                          fh.read(), re.MULTILINE)
    if not match:
        sys.exit("Could not find APP_VERSION in main.pyw")
    return match.group(1)


def make_zip():
    """Zip the one-dir build into dist/RamBo.zip and return the path."""
    if not os.path.isdir(DIST_DIR):
        sys.exit(f"No build found at {DIST_DIR} — run the build first.")
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    # make_archive appends its own .zip, so hand it the stem.
    shutil.make_archive(ZIP_PATH[:-4], 'zip', os.path.dirname(DIST_DIR), 'RamBo')
    print(f"  Zipped {os.path.getsize(ZIP_PATH) / 1024 ** 2:.1f} MB"
          f" -> {ZIP_PATH}")
    return ZIP_PATH
