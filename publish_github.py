"""
Publish the built app as a GitHub release asset.

The download link people use is:

    https://github.com/<owner>/<repo>/releases/latest/download/RamBo-Setup.exe

That URL is permanent and always resolves to the newest release, so it can be
posted once and never revisited. Bumping APP_VERSION in main.pyw and rebuilding
is all it takes to update what that link serves.

RamBo.zip is uploaded alongside it for two reasons: builds up to v1.0.0 shipped
an updater that fetches the zip by name, so publishing it keeps those installs
able to reach a newer version, and it remains the portable download for anyone
who does not want an installer.

Requires the GitHub CLI, authenticated once:
    winget install GitHub.cli
    gh auth login
"""
import os
import subprocess
import sys

from package import SETUP_PATH, get_version, make_zip
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


def changelog(tag):
    """Commit subjects since the previous tag, as markdown bullets.

    Tags are fetched first: releases are created through the GitHub API, so a
    clone that has never fetched them sees no previous tag and would silently
    report every release as the first one."""
    subprocess.run(['git', 'fetch', '--tags', '--quiet'],
                   capture_output=True, text=True)
    previous = subprocess.run(
        ['git', 'describe', '--tags', '--abbrev=0', tag + '^'],
        capture_output=True, text=True)
    if previous.returncode != 0 or not previous.stdout.strip():
        # First release: don't replay the entire history as a changelog.
        return '- First release.'
    span = f'{previous.stdout.strip()}..{tag}'
    log = subprocess.run(['git', 'log', span, '--no-merges', '--pretty=%s'],
                         capture_output=True, text=True)
    lines = [l.strip() for l in log.stdout.splitlines() if l.strip()]
    return "\n".join('- ' + l for l in lines[:15]) or '- Maintenance release.'


def build_notes(tag):
    """Release body: changelog first, then the standing install boilerplate.

    The `---` rule matters — updater.note_lines() stops there, so the in-app
    update prompt shows what changed rather than install instructions the
    user has already followed."""
    return (
        f"## What's new\n\n{changelog(tag)}\n\n"
        "---\n\n"
        "Download `RamBo-Setup.exe` and run it. It installs for the current "
        "user only, so there is no admin prompt.\n\n"
        "The installer is unsigned, so Windows SmartScreen will show "
        "\"Windows protected your PC\" — click **More info** then "
        "**Run anyway**.\n\n"
        "`RamBo.zip` is the same build as a plain archive, used by RamBo's "
        "own updater. Downloaded by hand it must be extracted in full before "
        "running `RamBo.exe` — launching it from inside the zip fails "
        "with \"Failed to load Python DLL\"."
    )


def publish(tag, assets):
    """Create the release, or update it in place if the tag already exists."""
    notes = build_notes(tag)

    if run(['release', 'view', tag]).returncode == 0:
        print(f"  Release {tag} already exists — updating assets and notes")
        uploaded = run(['release', 'upload', tag, *assets, '--clobber'])
        edited = run(['release', 'edit', tag, '--notes', notes])
        if uploaded.returncode != 0 or edited.returncode != 0:
            print("  " + (uploaded.stderr.strip() or edited.stderr.strip()))
            return False
    else:
        created = run(['release', 'create', tag, *assets,
                       '--title', f'RamBo {tag}', '--notes', notes])
        if created.returncode != 0:
            # Report the real reason rather than assuming the tag existed.
            print("  " + (created.stderr.strip() or 'gh release create failed'))
            return False
        print(f"  Created release {tag}")

    view = run(['repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'])
    slug = view.stdout.strip()
    print("\n  Permanent download link (paste this into Discord):")
    print(f"  https://github.com/{slug}/releases/latest/download/RamBo-Setup.exe")
    print("\n  Release page:")
    print(f"  https://github.com/{slug}/releases/latest\n")
    return True


def main():
    if not check_prerequisites():
        print("  Skipping release.")
        return 0
    tag = 'v' + get_version()
    # The zip still ships so that pre-1.1.0 installs, whose updater looks for
    # RamBo.zip rather than the installer, can still update themselves.
    assets = [make_zip()]
    if os.path.exists(SETUP_PATH):
        assets.insert(0, SETUP_PATH)
    else:
        print("  No dist/RamBo-Setup.exe — releasing the zip only.")
    return 0 if publish(tag, assets) else 1


if __name__ == '__main__':
    sys.exit(main())
