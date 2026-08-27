"""
Shared packaging helpers for the release scripts.

build_installer.py and publish_github.py need the same paths and the same
version string, so they live here rather than being duplicated in each.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(HERE, 'dist', 'RamBo')
SETUP_PATH = os.path.join(HERE, 'dist', 'RamBo-Setup.exe')


def get_version():
    """Read APP_VERSION out of main.pyw — the single source of truth."""
    with open(os.path.join(HERE, 'main.pyw'), encoding='utf-8') as fh:
        match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']',
                          fh.read(), re.MULTILINE)
    if not match:
        sys.exit("Could not find APP_VERSION in main.pyw")
    return match.group(1)
