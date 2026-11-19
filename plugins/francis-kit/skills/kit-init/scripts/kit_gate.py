#!/usr/bin/env python3
"""Run every check of the gate on a repository and end with one verdict line.

    kit_gate.py [--repo DIR]

The checks are the scripts of this kit, each started as a process of its own in DIR, in this
order: the doctor, the project roots, then for each root the map and its citations, the spec
lint, the requirement citations and the index. Every check runs, also after one failed, so one
run names everything that is red. Everything goes to standard output in the order it was
written; nothing is written into DIR.

The last line is `kit-gate: passed: kit <tag>, commit <sha>` or
`kit-gate: FAILED: <checks>: kit <tag>, commit <sha>`, followed by `, with uncommitted changes`
when the files judged are not the commit.

Exit status: 0 when every check passed, 1 when one failed, 2 when DIR is no directory or this
script itself broke (then no verdict line is printed).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
SKILLS = HERE.parents[2]
DOCTOR = SKILLS / 'kit-init' / 'scripts' / 'kit_doctor.py'
MAP = SKILLS / 'map-project' / 'scripts' / 'map_check.py'
CITATIONS = SKILLS / 'map-project' / 'scripts' / 'cite_refs.py'
LINT = SKILLS / 'write-spec' / 'scripts' / 'spec_lint.py'
REFS = SKILLS / 'comment-discipline' / 'scripts' / 'spec_refs.py'
INDEX = SKILLS / 'kit-init' / 'scripts' / 'spec_index.py'
NAMES = ('doctor', 'roots', 'map', 'citations', 'lint', 'refs', 'index')     # fixed: later features read them


def say(line):
    """One line of this script's own, in UTF-8 and ended by a line feed on every system."""
    sys.stdout.flush()
    sys.stdout.buffer.write(line.encode('utf-8') + b'\n')
    sys.stdout.buffer.flush()


def start(script, *args, cwd, listing=False):
    """Run one script with the Python that runs this one. Its two streams go to our standard output,
    unbuffered, so a line stands where it was written; it writes no bytecode beside itself. A listing keeps its standard output to be read.
    Returns (exit status, the lines of a listing), or (None, []) when it could not be started."""
    command = [sys.executable, '-u', '-B', str(script), *args]        # -B: no __pycache__ in a kit checked out inside DIR
    try:
        if listing:
            done = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=sys.stdout.fileno())
            lines = listed(done.stdout)
            return done.returncode, lines
        return subprocess.run(command, cwd=cwd, stdout=sys.stdout.fileno(), stderr=subprocess.STDOUT).returncode, []
    except OSError as e:
        say(f'kit-gate: could not start {script.name}: {e}')
        return None, []


def listed(out):
    """The lines of a listing as a shell reads them: cut at a line feed only, empty lines dropped."""
    lines = out.decode('utf-8', 'replace').split('\n')
    return [l[:-1] if l.endswith('\r') else l for l in lines if l not in ('', '\r')]


def kit_tag():
    """`v` and the version in this kit's plugin.json, or `unknown` where that gives no version."""
    try:
        version = json.loads((HERE.parents[3] / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError, TypeError):
        return 'unknown'
    return 'v' + version if isinstance(version, str) and version else 'unknown'


def git(repo, *args):
    """The standard output of a git command in repo as bytes, or None when it failed or git is missing."""
    try:
        done = subprocess.run(['git', *args], cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None
    return done.stdout if done.returncode == 0 else None


def is_git_root(repo):
    top = git(repo, 'rev-parse', '--show-toplevel')
    return top is not None and Path(os.fsdecode(top.strip())).resolve() == repo.resolve()


def commit_of(repo):
    sha = git(repo, 'rev-parse', '--verify', '-q', 'HEAD^{commit}')
    return sha.decode('ascii').strip() if sha else 'none'


def kit_home():
    """The directory that holds this kit's `plugins/`, or None where the script is not laid out so."""
    return HERE.parents[5] if HERE.parents[4].name == 'plugins' else None


def uncommitted(repo):
    """True when a tracked file differs from HEAD or a path that is not ignored is untracked,
    whatever the machine's git configuration. The kit's own untracked checkout is not counted."""
    out = git(repo, '-c', 'core.quotePath=false', 'status', '--porcelain', '--untracked-files=normal', '-z')
    if out is None:
        return False
    home = kit_home()
    home = home.resolve() if home else None
    entries = out.split(b'\0')
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], os.fsdecode(entry[3:])
        if b'R' in status or b'C' in status:
            i += 1                                    # the path it came from follows
        if status == b'??' and home is not None:
            entry = repo / path.rstrip('/')
            where = entry.parent.resolve() / entry.name   # a link is the entry itself, not where it points
            if where == home or home in where.parents or where in home.parents:
                continue
        return True
    return False


def stamp(repo):
    if not is_git_root(repo):
        return f'kit {kit_tag()}, commit none'
    line = f'kit {kit_tag()}, commit {commit_of(repo)}'
    return line + ', with uncommitted changes' if uncommitted(repo) else line


def run_checks(repo):
    """Every check in the order of the gate template of 0.9.0. Returns the names of those that failed."""
    failed = set()

    def check(name, script, *args, root=None):
        say(f'kit-gate: {name}' + (f': {root}' if root is not None else ''))
        code, _ = start(script, *args, cwd=repo)
        if code != 0:
            failed.add(name)

    check('doctor', DOCTOR, '--repo', '.', '--all')
    say('kit-gate: roots')
    code, roots = start(DOCTOR, '--repo', '.', '--roots', cwd=repo, listing=True)
    if code != 0 or not roots:
        if code == 0:
            say('kit-gate: no project roots found')
        failed.add('roots')
        return failed

    def left_out(name, root, needs):
        """A check that had no file to run on is named, so a green log tells it from one that passed (016/FR-004)."""
        say(f'kit-gate: left out: {name}: {root} (no {needs})')

    for root in roots:
        if (repo / root / 'docs' / 'diagrams' / 'map.refs.json').is_file():
            check('map', MAP, root, 'docs/ARCHITECTURE.md', root=root)
            check('citations', CITATIONS, '--diagrams', f'{root}/docs/diagrams', '--root', root, '--check', root=root)
        else:
            left_out('map', root, 'docs/diagrams/map.refs.json')
            left_out('citations', root, 'docs/diagrams/map.refs.json')
    for root in roots:
        say(f'kit-gate: lint: {root}')
        code, names = start(DOCTOR, '--repo', '.', '--lint-features', root, cwd=repo, listing=True)
        if code != 0:
            failed.add('lint')
        elif names and start(LINT, '--root', root, *names, cwd=repo)[0] != 0:
            failed.add('lint')
    for root in roots:
        if (repo / root / 'specs' / '.kit-refs-baseline.json').is_file():
            check('refs', REFS, '--repo', '.', '--root', root, '--check', root=root)
        else:
            left_out('refs', root, 'specs/.kit-refs-baseline.json')
        if (repo / root / 'specs' / 'INDEX.md').is_file():
            check('index', INDEX, '--root', root, '--check', root=root)
        else:
            left_out('index', root, 'specs/INDEX.md')
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--repo', type=Path, default=Path('.'), help='git root (default: .)')
    args = ap.parse_args(argv)
    if not args.repo.is_dir():
        print(f'kit_gate.py: no such directory: {args.repo}', file=sys.stderr)
        return 2
    repo = args.repo.resolve()
    taken = stamp(repo)                               # what is judged, before any check runs
    failed = run_checks(repo)
    if failed:
        say(f"kit-gate: FAILED: {', '.join(n for n in NAMES if n in failed)}: {taken}")
        return 1
    say(f'kit-gate: passed: {taken}')
    return 0


if __name__ == '__main__':
    try:
        code = main()
        sys.stdout.flush()
    except Exception as e:                            # a crash is never a verdict, a closed output included
        try:
            print(f'cannot check: kit_gate.py broke: {type(e).__name__}: {e}', file=sys.stderr)
            sys.stderr.flush()
        except Exception:
            pass
        os._exit(2)                                   # no flush at shutdown: it would turn 2 into 120
    sys.exit(code)
