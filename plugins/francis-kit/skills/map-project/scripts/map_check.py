#!/usr/bin/env python3
"""Check the path citations of an architecture map.

Usage: map_check.py PROJECT_ROOT DOC

A citation is a path in backticks, written from the project root, with an
optional `:line` or `:line-line`. Exit 1 when a cited path is missing or was
deleted since the pin, a cited line is past the end of the file, a path leaves
the project root, or the map has no pin. Exit 2 when the pinned commit is not
in this clone or git cannot be run.

This check only proves the paths exist. Whether the cited code still says
what the map claims is the job of cite_refs.py.
"""
import os
import re
import subprocess
import sys

SPAN = re.compile(r'`([^`\s]+)`')
PATHISH = re.compile(r'^([A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*/?)(?::(\d+)(?:-(\d+))?)?$')
FILE_NAME = re.compile(r'^[A-Za-z0-9_\-][A-Za-z0-9_.\-]*\.(?:py|pyi|js|jsx|mjs|ts|tsx|vue|php|go|rs|java|kt|rb|cs|'
                       r'swift|dart|c|h|cpp|sh|ps1|sql|ya?ml|json|toml|md|html|css|scss|xml|txt|ini|cfg|lock)$')
PIN = re.compile(r'kit:map revision=([0-9a-f]{7,40})')


def classify(root, token):
    """Return (kind, path, last_line). kind: cite | bare | skip."""
    m = PATHISH.match(token)
    if not m:
        return 'skip', None, None
    path, start, end = m.group(1), m.group(2), m.group(3)
    last = int(end or start) if start else None
    if '..' in path.split('/'):
        return 'escape', path, last
    if os.path.exists(os.path.join(root, path)):
        return 'cite', path, last
    first = path.split('/', 1)[0]
    has_dir = '/' in path.rstrip('/')
    # `origin/main` or `application/json` look like paths but are not: only
    # treat a slash form as a citation when it starts at something real.
    if has_dir and os.path.exists(os.path.join(root, first)):
        return 'cite', path, last
    # A file name that starts nowhere real is a path written from somewhere
    # other than the project root: listed, not counted as broken.
    if FILE_NAME.match(path.rsplit('/', 1)[-1]):
        return 'bare', path, last
    return 'skip', path, last


def git(root, *args):
    try:
        return subprocess.run(['git', '-C', root, *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    except OSError:
        return None


def main(argv):
    if len(argv) != 2 or argv[0].startswith('-'):
        print(__doc__)
        return 2
    root, doc = argv
    doc_path = doc if os.path.isabs(doc) else os.path.join(root, doc)
    if not os.path.isfile(doc_path):
        print(f'MISSING MAP: {doc_path}')
        return 1
    with open(doc_path, encoding='utf-8', errors='replace') as fh:
        text = fh.read()

    pin = PIN.search(text.split('\n', 1)[0])
    rev = pin.group(1) if pin else None
    if rev:
        known = git(root, 'cat-file', '-e', f'{rev}^{{commit}}')
        if known is None:
            print('git could not be run: nothing was checked')
            return 2
        if known.returncode != 0:
            print(f'pin: {rev[:8]} is not in this clone; fetch it or deepen the clone')
            return 2

    ok = 0
    bad, bare, cited = [], [], set()
    for token in dict.fromkeys(SPAN.findall(text)):
        kind, path, last = classify(root, token)
        if kind == 'escape':
            bad.append(f'{token}: leaves the project root')
            continue
        if kind in ('bare', 'skip'):
            # A path that was there when the map was pinned and is gone now was deleted,
            # not written from the wrong place. `origin/main` was never there.
            was = rev and path and git(root, 'cat-file', '-e', f'{rev}:./{path.rstrip("/")}')
            if was and was.returncode == 0:
                bad.append(f'{token}: deleted since the pin')
            elif kind == 'bare':
                bare.append(token)
            continue
        full = os.path.join(root, path)
        if not os.path.exists(full):
            bad.append(f'{token}: no such path')
            continue
        if last and os.path.isfile(full):
            with open(full, encoding='utf-8', errors='replace') as fh:
                n = sum(1 for _ in fh)
            if last > n:
                bad.append(f'{token}: file has {n} lines')
                continue
        cited.add(os.path.normpath(path).replace(os.sep, '/'))      # `./src/a.py` is `src/a.py` to git
        ok += 1

    print(f'citations: ok={ok} broken={len(bad)} not_from_project_root={len(bare)}')
    for b in bad:
        print(f'  BROKEN {b}')
    for b in bare:
        print(f'  UNCHECKED {b}: not written from the project root')

    code = 1 if bad else 0
    if not rev:
        print('pin: MISSING (first line must be <!-- kit:map revision=<sha> -->)')
        return 1
    diff = git(root, 'diff', '--name-only', '--relative', f'{rev}..HEAD', '--', '.')
    changed = [name for name in (diff.stdout if diff else '').splitlines() if name]
    direct = {c for c in changed if c in cited}
    under = {c for c in changed if c not in direct and any(c.startswith(d + '/') for d in cited)}
    touched = sorted(direct | under)
    print(f'pin: {rev[:8]}, files changed since: {len(changed)}, '
          f'of which cited by the map: {len(direct)} directly, {len(under)} under a cited directory')
    for t in touched[:20]:
        print(f'  REVIEW {t}')
    return code


if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8 by default
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:      # a crash is "nothing was checked", never a verdict
        print(f'map_check.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
