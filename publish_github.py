"""
Publish the built app as a GitHub release asset.

The download link people use is:

    https://github.com/<owner>/<repo>/releases/latest/download/RamBo.zip

That URL is permanent and always resolves to the newest release, so it can be
posted once and never revisited. Bumping APP_VERSION in main.pyw and rebuilding
is all it takes to update what that link serves.

Requires the GitHub CLI, authenticated once:
    winget install GitHub.cli
    gh auth login
"""
import subprocess
import sys

from package import get_version, make_zip
from updater import GITHUB_REPO      # single source of truth for the repo

GH = 'gh'


def run(args, **kw):
    """Run a gh subcommand, returning the CompletedProcess."""
    return subprocess.run([GH] + args, capture_output=True, text=True, **kw)


def check_prerequisites():
    """Verify gh is installed, authenticated, and the cwd is a GitHub repo."""
    try:
        run(['--version'])
    except FileNotFoundError:
        print("  GitHub CLI not found. Install it with:\n"
              "    winget install GitHub.cli")
        return False

    if run(['auth', 'status']).returncode != 0:
        print("  Not logged in to GitHub. Run:\n    gh auth login")
        return False

    view = run(['repo', 'view', '--json', 'nameWithOwner',
                '-q', '.nameWithOwner'])
    if view.returncode != 0:
        print("  No GitHub remote for this directory. Create one with:\n"
              "    gh repo create RamBo --public --source=. --push")
        return False

    # A mismatch here means shipped builds would check a different repo for
    # updates than the one being published to, so every client would go stale.
    slug = view.stdout.strip()
    if slug.lower() != GITHUB_REPO.lower():
        print(f"  Remote is {slug} but updater.py checks {GITHUB_REPO}.\n"
              f"  Update GITHUB_REPO in updater.py before releasing.")
        return False
    return True


def publish(tag, zip_path):
    """Create the release, or replace the asset if the tag already exists."""
    notes = (
        f"RamBo {tag}\n\n"
        "Download `RamBo.zip`, extract anywhere, and run `RamBo.exe`.\n\n"
        "The build is unsigned, so Windows SmartScreen will show "
        "\"Windows protected your PC\" on first run — click **More info** "
        "then **Run anyway**."
    )
    created = run(['release', 'create', tag, zip_path,
                   '--title', f'RamBo {tag}', '--notes', notes])
    if created.returncode == 0:
        print(f"  Created release {tag}")
    else:
        # Most likely cause is that the tag already exists; replace the asset.
        print(f"  Release {tag} exists — replacing its asset")
        uploaded = run(['release', 'upload', tag, zip_path, '--clobber'])
        if uploaded.returncode != 0:
            print(created.stderr.strip() or uploaded.stderr.strip())
            return False

    view = run(['repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'])
    slug = view.stdout.strip()
    print("\n  Permanent download link (paste this into Discord):")
    print(f"  https://github.com/{slug}/releases/latest/download/RamBo.zip")
    print("\n  Release page:")
    print(f"  https://github.com/{slug}/releases/latest\n")
    return True


def main():
    if not check_prerequisites():
        print("  Skipping release.")
        return 0
    tag = 'v' + get_version()
    zip_path = make_zip()
    return 0 if publish(tag, zip_path) else 1


if __name__ == '__main__':
    sys.exit(main())
