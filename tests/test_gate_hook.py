"""The gate as a git hook: the hook, S14 on it, the scaffold that writes it, and what is said of them (spec 010)."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_standard import DOCTOR, SCAFFOLD, SCRIPTS, feature, run
from test_kit_gate import REPO, VERSION, commit, git, make_p, start_repo

HOOK = SCRIPTS.parent / 'templates' / 'common' / 'pre-push'
WORKFLOW_TEMPLATE = SCRIPTS.parent / 'templates' / 'common' / 'kit-gate.yml'
TAG = 'v' + VERSION
ZERO = '0' * 40
WINDOWS = sys.platform == 'win32'
HOOK_FILE = '.githooks/pre-push'
WORKFLOW_FILE = '.github/workflows/kit-gate.yml'
DEFAULT_SOURCE = 'https://github.com/dangthinh104/francis-ai-coworking.git'
NO_PYTHON = 'kit-gate: no python3 or python of 3.9 or newer runs on this machine: the standard was NOT checked.'
NO_YAML = ('kit-gate: no python3 or python of 3.9 or newer on this machine can import yaml (pip install pyyaml): '
           'the standard was NOT checked.')
ONLY_DELETIONS = 'kit-gate: only deletions are pushed: the standard was not checked.'
NOT_AMONG = 'kit-gate: the commit judged is not among the commits pushed'
NOTHING = 'kit-gate: nothing was pushed, so this verdict refuses nothing'      # 017/FR-007
TWO_COMMANDS = ('git add --chmod=+x .githooks/pre-push', 'git config core.hooksPath .githooks')
S14_GAPS = {
    'missing': '.githooks/pre-push is missing or empty',
    'no tag': 'pre-push does not pin the kit to a tag (`KIT_REF=v1.2.3`)',
    'other': ('pre-push is not the gate of this kit version: write it again with `kit_scaffold.py --repo . --gate` '
              '(raising `KIT_REF=` alone is not enough)'),
    'untracked': '.githooks/pre-push is not tracked by git: run `git add --chmod=+x .githooks/pre-push`',
    'unknown': '.githooks/pre-push: git could not say how the index holds it (not a git repository, or no git)',
}
BOTH_WORKFLOW = ('.github/workflows/kit-gate.yml is there and the manifest names the hook: '
                 'a project holds one gate, remove the file')
BOTH_HOOK = (".githooks/pre-push is the kit's hook and the manifest names the workflow: "
             'a project holds one gate, remove the file or set gate: hook')


def fetch_failed(source):
    return (f'kit-gate: could not fetch the kit at {TAG} from {source}, which needs read access to that repository '
            f'with your own git credentials: the standard was NOT checked.')


def pinned_elsewhere(tag):
    """The gap of a pin older than the kit (019/FR-003)."""
    return (f'pre-push pins {tag}, and a newer kit, {TAG}, is installed here: the gate runs and is judged by the '
            f'checks of {tag}, and this doctor judges only a gate of {TAG}. To take {TAG}, write the gate again with '
            f'`kit_scaffold.py --repo . --gate`')


def find_shells():
    """`sh`, and `dash` where it is found: on the PATH, or below the directory of Git for Windows."""
    found = {name: shutil.which(name) for name in ('sh', 'dash')}
    if WINDOWS:
        bin_dir = Path(shutil.which('git')).resolve().parent.parent / 'usr' / 'bin'
        for name in found:
            if not found[name] and (bin_dir / f'{name}.exe').is_file():
                found[name] = str(bin_dir / f'{name}.exe')
    assert found['sh'], 'no sh: the hook is run by sh on every system'
    return [found['sh']] + ([found['dash']] if found['dash'] else [])


SHELLS = find_shells()
DASH = SHELLS[1] if len(SHELLS) > 1 else None
by_each_shell = pytest.mark.parametrize('shell', SHELLS, ids=['sh', 'dash'][:len(SHELLS)])


def real_program(name):
    """The full path of a POSIX utility the hook starts, as the sh of this system reads it."""
    if WINDOWS:
        return (Path(SHELLS[0]).parent / f'{name}.exe').as_posix()
    return shutil.which(name)


def script(folder, name, body):
    path = folder / name
    path.write_bytes(f'#!/bin/sh\n{body}\n'.encode('utf-8'))
    path.chmod(0o755)


def make_path(folder, pythons=('python3', 'python'), **scripts):
    """A test PATH: two-line scripts that start git, mkdir, mv, rm and the Pythons named, and nothing else.

    On Windows the Python of the hook starts `git` as Windows starts a program, which finds no script and
    no link this account may make: the directory git.exe is installed in stands beside it, holding no
    Python and none of the utilities, as in 008's `only_git`.
    """
    folder.mkdir()
    for name in ('mkdir', 'mv', 'rm'):
        script(folder, name, f'exec "{real_program(name)}" "$@"')
    for name in pythons:
        script(folder, name, f'exec "{Path(sys.executable).as_posix()}" "$@"')
    for name, body in scripts.items():
        script(folder, name, body)
    if not WINDOWS:
        script(folder, 'git', f'exec "{shutil.which("git")}" "$@"')
        return str(folder)
    installed = Path(shutil.which('git')).parent
    held = {p.stem.lower() for p in installed.iterdir()}
    assert not [n for n in held if n.startswith('python') or n in ('mkdir', 'mv', 'rm')], held
    return os.pathsep.join([str(folder), str(installed)])


class Run:
    def __init__(self, done):
        self.code = done.returncode
        self.out = done.stdout.decode('utf-8')
        self.err = done.stderr.decode('utf-8')
        self.lines = self.out.splitlines()
        self.verdicts = [l for l in self.lines if l.startswith(('kit-gate: passed: ', 'kit-gate: FAILED: '))]

    def starting(self, text):
        return [l for l in self.lines if l.startswith(text)]

    def __repr__(self):
        return f'exit {self.code}\n--- stdout\n{self.out}--- stderr\n{self.err}'


def hook(shell, top, path, stdin='', env=None, args=()):
    """The hook run by sh: `sh .githooks/pre-push` at the top of a working tree, its two streams apart."""
    # Git for Windows' launcher puts its own directories on the PATH only where MSYSTEM is not set:
    # with a test PATH that lacks them, a git started below a Git Bash would find no `sh` for its transport.
    dropped = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_PREFIX') + (('MSYSTEM',) if WINDOWS else ())
    base = {k: v for k, v in os.environ.items() if k not in dropped}
    done = subprocess.run([shell, HOOK_FILE, *args], cwd=top, input=stdin.encode('utf-8'), capture_output=True,
                          env=dict(base, PATH=path, **(env or {})))
    return Run(done)


def head(repo):
    return git(repo, 'rev-parse', 'HEAD').strip()


def stamp(repo):
    return f'kit {TAG}, commit {head(repo)}'


def doctor(repo):
    return run(DOCTOR, '--repo', repo).stdout


def s14(out):
    return [l for l in out.splitlines() if l.startswith('  GAP  S14')]


def listing(repo):
    return sorted(p.relative_to(repo).as_posix() for p in repo.rglob('*'))


def write_lf(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def add_key(repo, line):
    kit = repo / '.claude' / 'kit.yml'
    kit.write_bytes(kit.read_bytes() + f'{line}\n'.encode('utf-8'))


def bare_from(work, folder):
    """A bare repository cloned from a work tree of one commit."""
    git(work.parent, 'clone', '-q', '--bare', str(work), str(folder))
    return folder


@pytest.fixture(scope='session')
def k(tmp_path_factory):
    """`K`: the `plugins` directory of this kit, one commit, the tag of plugin.json, cloned bare."""
    base = tmp_path_factory.mktemp('k')
    work = base / 'kit'
    shutil.copytree(REPO / 'plugins', work / 'plugins', ignore=shutil.ignore_patterns('__pycache__'))
    start_repo(work)
    commit(work)
    git(work, 'tag', TAG)
    return bare_from(work, base / 'k.git')


def make_h(repo, k):
    """`H`: `P` with `gate: hook`, no workflow file, the hook written by the scaffold and added executable,
    in a third commit, and `kit.gateSource` set to `K`."""
    make_p(repo)
    add_key(repo, 'gate: hook')
    (repo / WORKFLOW_FILE).unlink()
    r = run(SCAFFOLD, '--repo', repo, '--gate')
    assert r.returncode == 0, r.stdout + r.stderr
    git(repo, 'add', '--chmod=+x', HOOK_FILE)
    commit(repo)
    git(repo, 'config', 'kit.gateSource', k.as_posix())
    assert git(repo, 'status', '--porcelain') == ''
    return repo


@pytest.fixture(scope='module')
def h_bare(tmp_path_factory, k):
    return make_h(tmp_path_factory.mktemp('h') / 'h', k)


@pytest.fixture(scope='module')
def h_filled(tmp_path_factory, h_bare):
    """`H` whose cache was filled by one run of the hook."""
    repo = tmp_path_factory.mktemp('filled') / 'h'
    shutil.copytree(h_bare, repo, symlinks=True)
    r = hook(SHELLS[0], repo, make_path(repo.parent / 'bin'))
    assert r.code == 0, r
    return repo


@pytest.fixture
def h(tmp_path, h_filled):
    return Path(shutil.copytree(h_filled, tmp_path / 'h', symlinks=True))


@pytest.fixture
def h_empty(tmp_path, h_bare):
    """`H` with no cache."""
    return Path(shutil.copytree(h_bare, tmp_path / 'h-empty', symlinks=True))


@pytest.fixture
def p(tmp_path):
    return make_p(tmp_path / 'p')


def cache(repo):
    return repo / '.git' / 'kit-gate' / TAG


def bad_spec(repo):
    """SC-006: a spec with a title, `**Ticket**: none` and no Status line, committed."""
    feature(repo, '001-a', status=None)
    commit(repo)


def test_s01_takes_the_key_gate_with_two_values(p):
    """010/FR-001, SC-001."""
    plain = doctor(p)
    without = [l for l in plain.splitlines() if ' S14' in l]
    assert len(without) == 1, plain
    kit = p / '.claude' / 'kit.yml'
    whole = kit.read_bytes()
    add_key(p, 'gate: hook')
    assert 'unknown top-level keys' not in doctor(p)
    for value, same in (('workflow', True), ('both', False), ('[hook]', False), ('', False)):
        kit.write_bytes(whole)
        add_key(p, f'gate: {value}'.rstrip())
        out = doctor(p)
        assert 'unknown top-level keys' not in out, out
        if same:
            assert out == plain
        else:
            assert '  GAP  S01 gate must be workflow or hook' in out.splitlines(), (value, out)
            assert without[0] in out.splitlines(), (value, out)


def test_s14_under_the_hook_asks_for_the_hook_of_the_version_it_pins(h, p):
    """010/FR-002, SC-002."""
    out = doctor(h)
    assert '  PASS S14 (the gate)' in out.splitlines() and 'kit-gate.yml' not in out, out
    target = h / HOOK_FILE
    whole = target.read_bytes().decode('utf-8')
    pin = f'KIT_REF={TAG}\n'
    assert whole.count(pin) == 1
    rows = whole.split('\n')
    other = '\n'.join(rows[:1] + [rows[1] + ' # changed'] + rows[2:])
    assert not rows[1].startswith('KIT_REF=')
    for change, gap in ((None, S14_GAPS['missing']), (whole.replace(pin, 'KIT_REF=main\n'), S14_GAPS['no tag']),
                        (whole.replace(pin, 'KIT_REF=v0.0.1\n'), pinned_elsewhere('v0.0.1')),
                        (other, S14_GAPS['other'])):
        if change is None:
            target.unlink()
        else:
            write_lf(target, change)
        assert s14(doctor(h)) == ['  GAP  S14 ' + gap], (gap, doctor(h))
        write_lf(target, whole)
    assert '  PASS S14 (the gate)' in doctor(p).splitlines()
    standard = subprocess.run(['git', 'grep', '-c', '-E', r'gate: hook|\.githooks/pre-push', '--',
                               'plugins/francis-kit/STANDARD.md'], cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert standard.stdout.strip(), standard


def test_s14_under_the_hook_asks_that_the_index_holds_it_executable(h, tmp_path):
    """010/FR-003, SC-003: the same verdicts on a file system that keeps no mode."""
    git(h, 'update-index', '--chmod=-x', HOOK_FILE)
    assert s14(doctor(h)) == ['  GAP  S14 .githooks/pre-push is not executable in the index (mode 100644): '
                              'run `git add --chmod=+x .githooks/pre-push`']
    git(h, 'update-index', '--chmod=+x', HOOK_FILE)      # `H` again: git refuses `rm --cached` of a mode only the index holds
    git(h, 'rm', '--cached', '-q', HOOK_FILE)
    assert s14(doctor(h)) == ['  GAP  S14 ' + S14_GAPS['untracked']]
    copy = tmp_path / 'copy'
    shutil.copytree(h, copy, ignore=shutil.ignore_patterns('.git'))
    assert s14(doctor(copy)) == ['  GAP  S14 ' + S14_GAPS['unknown']]


def test_a_project_holds_one_gate(h, p):
    """010/FR-004, SC-004."""
    write_lf(h / WORKFLOW_FILE, WORKFLOW_TEMPLATE.read_text(encoding='utf-8').replace('{{KIT_REF}}', TAG))
    assert '  GAP  S14 ' + BOTH_WORKFLOW in doctor(h).splitlines()
    write_lf(p / HOOK_FILE, (h / HOOK_FILE).read_bytes().decode('utf-8'))
    assert '  GAP  S14 ' + BOTH_HOOK in doctor(p).splitlines()
    write_lf(p / HOOK_FILE, '#!/bin/sh\nexit 0\n')
    out = doctor(p)
    assert '  PASS S14 (the gate)' in out.splitlines() and not s14(out), out


@by_each_shell
def test_a_push_from_a_worktree_or_a_subdirectory_is_judged_where_it_was_made(shell, h_empty, tmp_path):
    """010/FR-005, SC-005."""
    h = h_empty
    w = tmp_path / 'w'
    git(h, 'worktree', 'add', '-q', '-b', 'side', str(w))
    write_lf(w / 'more.txt', 'one more\n')
    commit(w)
    assert head(w) != head(h)
    path = make_path(tmp_path / 'bin')
    first = hook(shell, h, path)
    assert first.code == 0 and first.verdicts == ['kit-gate: passed: ' + stamp(h)], first
    gitdir = h / '.git' / 'worktrees' / 'w'
    assert gitdir.is_dir()
    moved = hook(shell, h, path, env={'GIT_DIR': str(gitdir), 'GIT_WORK_TREE': str(w),
                                      'GIT_INDEX_FILE': str(tmp_path / 'no-such-index'), 'GIT_PREFIX': 'sub/'})
    assert moved.code == 0 and moved.verdicts == first.verdicts, moved
    there = hook(shell, w, path, env={'GIT_DIR': str(gitdir)})
    assert there.code == 0 and there.verdicts == ['kit-gate: passed: ' + stamp(w)], there
    named = [Path(d) / n for d, dirs, _ in os.walk(h / '.git') for n in dirs if n == 'kit-gate']
    assert named == [h / '.git' / 'kit-gate'], named
    rows = HOOK.read_text(encoding='utf-8').splitlines()
    unset = rows.index('unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_PREFIX')
    assert not [r for r in rows[:unset] if r.strip() and not r.startswith('#') and not r.startswith('KIT_REF=')]


def test_the_hook_is_plain_sh():
    """010/FR-006, SC-006: what is read from the text of `HOOK`."""
    raw = HOOK.read_bytes()
    text = raw.decode('utf-8')
    assert b'\r' not in raw and text.splitlines()[0] == '#!/bin/sh'
    assert '--repo .' in text
    for word in ('pwd', '[[', '((', 'function ', 'local ', '=(', '<<<'):
        assert word not in text, word
    assert [l for l in text.splitlines() if l == 'KIT_REF={{KIT_REF}}']
    if DASH:
        r = subprocess.run([DASH, '-n', str(HOOK)], capture_output=True, text=True, encoding='utf-8')
        assert r.returncode == 0, r.stderr


@by_each_shell
def test_the_hook_starts_the_gate_with_the_python_it_finds(shell, h, tmp_path):
    """010/FR-006, SC-006."""
    paths = {'both': make_path(tmp_path / 'both'),
             'python3 fails': make_path(tmp_path / 'stub', pythons=('python',), python3='exit 1'),
             'python3 only': make_path(tmp_path / 'three', pythons=('python3',))}
    green = {name: hook(shell, h, path) for name, path in paths.items()}
    r = green['both']
    assert r.code == 0 and r.err == '' and 'kit-gate: passed: ' + stamp(h) in r.lines, r
    bad_spec(h)
    # One input line: an empty one is never refused (017/FR-006).
    pushed = f'refs/heads/main {head(h)} refs/heads/main {ZERO}\n'
    red = {name: hook(shell, h, path, stdin=pushed) for name, path in paths.items()}
    r = red['both']
    assert r.code == 1 and [l for l in r.lines if l.startswith('kit-gate: FAILED: doctor, lint')], r
    for name in paths:
        for runs in (green, red):
            assert (runs[name].code, runs[name].verdicts, runs[name].err) == \
                (runs['both'].code, runs['both'].verdicts, runs['both'].err), (name, runs[name])


@by_each_shell
def test_the_hook_fetches_the_kit_once_per_version_into_the_git_directory(shell, h_empty, tmp_path, k):
    """010/FR-007, SC-007."""
    h = h_empty
    path = make_path(tmp_path / 'bin')
    assert not (h / '.git' / 'kit-gate').exists()
    r = hook(shell, h, path)
    verdict = 'kit-gate: passed: ' + stamp(h)
    assert r.code == 0 and r.verdicts == [verdict], r
    assert [e.name for e in (h / '.git' / 'kit-gate').iterdir()] == [TAG]
    plugin = cache(h) / 'plugins' / 'francis-kit' / '.claude-plugin' / 'plugin.json'
    assert json.loads(plugin.read_text(encoding='utf-8'))['version'] == VERSION
    assert git(h, 'status', '--porcelain') == ''
    assert not [l for l in r.err.splitlines() if 'detached HEAD' in l], r
    git(h, 'config', 'kit.gateSource', (tmp_path / 'no-such-kit').as_posix())
    r = hook(shell, h, path)
    assert r.code == 0 and r.verdicts == [verdict], r
    git(h, 'config', 'kit.gateSource', k.as_posix())
    plugin.unlink()
    r = hook(shell, h, path)
    assert r.code == 0 and plugin.is_file(), r
    assert [e.name for e in (h / '.git' / 'kit-gate').iterdir()] == [TAG]
    data = json.loads(plugin.read_text(encoding='utf-8'))
    write_lf(plugin, json.dumps(dict(data, version='0.0.0')))
    r = hook(shell, h, path)
    assert r.code == 0 and r.verdicts == [verdict], r
    assert json.loads(plugin.read_text(encoding='utf-8'))['version'] == VERSION
    assert [e.name for e in (h / '.git' / 'kit-gate').iterdir()] == [TAG]
    text = HOOK.read_text(encoding='utf-8')
    for words in ('GIT_TERMINAL_PROMPT=0', 'advice.detachedHead=false', 'kit.gateSource', DEFAULT_SOURCE):
        assert words in text, words


def refused(r, line):
    assert (r.code, r.out, r.err.splitlines()) == (1, '', [line]), r
    assert line.endswith('the standard was NOT checked.') and '...' not in line
    assert not r.starting('kit-gate: passed')


@by_each_shell
def test_the_hook_refuses_where_it_cannot_check(shell, h, h_empty, tmp_path, k):
    """010/FR-008, SC-008: with one input line, as 017/FR-006 leaves an empty input unrefused."""
    pushed = f'refs/heads/main {head(h)} refs/heads/main {ZERO}\n'
    refused(hook(shell, h, make_path(tmp_path / 'none', pythons=()), stdin=pushed), NO_PYTHON)
    refused(hook(shell, h, make_path(tmp_path / 'fail', pythons=(), python3='exit 1', python='exit 1'), stdin=pushed),
            NO_PYTHON)
    refused(hook(shell, h, make_path(tmp_path / 'old', pythons=(), python3='echo "Python 3.8.10"; exit 0'),
                 stdin=pushed), NO_PYTHON)
    no_yaml = tmp_path / 'no-yaml'
    write_lf(no_yaml / 'yaml.py', 'raise ImportError("no yaml here")\n')
    refused(hook(shell, h, make_path(tmp_path / 'real'), stdin=pushed, env={'PYTHONPATH': str(no_yaml)}), NO_YAML)

    pushed = f'refs/heads/main {head(h_empty)} refs/heads/main {ZERO}\n'
    refused(hook(shell, h_empty, make_path(tmp_path / 'none-empty', pythons=()), stdin=pushed), NO_PYTHON)
    assert not (h_empty / '.git' / 'kit-gate').exists()
    path = make_path(tmp_path / 'bin')
    nowhere = (tmp_path / 'no-such-kit').as_posix()
    git(h_empty, 'config', 'kit.gateSource', nowhere)
    refused(hook(shell, h_empty, path, stdin=pushed), fetch_failed(nowhere))
    assert TAG in fetch_failed(nowhere) and not list((h_empty / '.git' / 'kit-gate').iterdir())
    untagged = tmp_path / 'untagged'
    shutil.copytree(REPO / 'plugins' / 'francis-kit' / '.claude-plugin', untagged / 'plugins' / 'francis-kit' / '.claude-plugin')
    start_repo(untagged)
    commit(untagged)
    other = bare_from(untagged, tmp_path / 'untagged.git')
    git(h_empty, 'config', 'kit.gateSource', other.as_posix())
    refused(hook(shell, h_empty, path, stdin=pushed), fetch_failed(other.as_posix()))
    assert not list((h_empty / '.git' / 'kit-gate').iterdir())


@by_each_shell
def test_a_push_that_only_deletes_is_not_checked(shell, h, tmp_path):
    """010/FR-009, SC-009."""
    bad_spec(h)
    sha = head(h)
    deletion = f'(delete) {ZERO} refs/heads/x {sha}\n'
    for path in (make_path(tmp_path / 'bin'), make_path(tmp_path / 'none', pythons=())):
        r = hook(shell, h, path, stdin=deletion)
        assert (r.code, r.lines) == (0, [ONLY_DELETIONS]), r
        assert not r.starting('kit-gate: FAILED')
    path = make_path(tmp_path / 'again')
    r = hook(shell, h, path, stdin=deletion + f'refs/heads/main {sha} refs/heads/main {ZERO}\n')
    assert r.code == 1, r
    r = hook(shell, h, path, stdin=f'refs/tags/v1 {sha} refs/tags/v1 {ZERO}\n')
    assert r.code == 1, r


@by_each_shell
def test_the_hook_says_what_was_pushed_after_the_verdict(shell, h, tmp_path):
    """010/FR-010, SC-010."""
    path = make_path(tmp_path / 'bin')
    sha = head(h)
    verdict = 'kit-gate: passed: ' + stamp(h)
    r = hook(shell, h, path, stdin=f'refs/heads/main {sha} refs/heads/main {ZERO}\n')
    assert r.code == 0 and r.lines[-2:] == [verdict, f'kit-gate: pushed refs/heads/main at {sha}'], r
    first = git(h, 'rev-list', '--max-parents=0', 'HEAD').strip()
    r = hook(shell, h, path, stdin=f'refs/heads/main {first} refs/heads/main {ZERO}\n')
    assert r.lines[-1] == NOT_AMONG, r
    git(h, 'tag', '-a', 'v2', '-m', 'v2')
    tag = git(h, 'rev-parse', 'v2').strip()
    assert tag != sha
    r = hook(shell, h, path, stdin=f'refs/tags/v2 {tag} refs/tags/v2 {ZERO}\n')
    assert r.code == 0 and not [l for l in r.lines if 'not among' in l] and r.lines[-1] == f'kit-gate: pushed refs/tags/v2 at {tag}', r
    r = hook(shell, h, path)
    assert r.code == 0 and r.lines[-1] == NOTHING, r
    r = hook(shell, h, path, stdin=f'(delete) {ZERO} refs/heads/x {sha}\nrefs/heads/main {sha} refs/heads/main {ZERO}')
    assert len(r.starting('kit-gate: pushed')) == 1 and r.lines[-1] == f'kit-gate: pushed refs/heads/main at {sha}', r
    bad_spec(h)
    sha = head(h)
    r = hook(shell, h, path, stdin=f'refs/heads/main {sha} refs/heads/main {ZERO}\n')
    failed = [i for i, l in enumerate(r.lines) if l.startswith('kit-gate: FAILED')]
    pushed = [i for i, l in enumerate(r.lines) if l.startswith('kit-gate: pushed')]
    assert r.code == 1 and len(failed) == 1 and pushed == [failed[0] + 1], r
    write_lf(cache(h) / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_gate.py',
             'import sys\nsys.exit(2)\n')
    r = hook(shell, h, path, stdin=f'refs/heads/main {sha} refs/heads/main {ZERO}\n')
    assert r.code == 2 and not r.starting('kit-gate: pushed') and not r.starting('kit-gate: nothing'), r


def scaffold(repo, *args, env=None):
    return subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(repo), *args], capture_output=True, text=True,
                          encoding='utf-8', env=None if env is None else dict(os.environ, **env))


def nothing_written(r):
    return r.returncode == 1 and [l for l in r.stdout.splitlines() if l.endswith('Nothing was written.')]


def test_the_scaffold_writes_the_gate_the_manifest_names(tmp_path):
    """010/FR-011, SC-011."""
    def hook_project(name):
        repo = make_p(tmp_path / name)
        add_key(repo, 'gate: hook')
        (repo / WORKFLOW_FILE).unlink()
        commit(repo)
        return repo

    plain = hook_project('plain')
    r = scaffold(plain)
    assert r.returncode == 0 and 'kit-gate.yml' not in r.stdout and not (plain / WORKFLOW_FILE).exists(), r.stdout

    flagged = hook_project('flagged')
    before = listing(flagged)
    r = scaffold(flagged, '--gate')
    assert r.returncode == 0 and f'  create  {HOOK_FILE}' in r.stdout.splitlines(), r.stdout
    for command in TWO_COMMANDS:
        assert [l for l in r.stdout.splitlines() if command in l], command
    assert listing(flagged) == sorted(before + ['.githooks', HOOK_FILE])
    if not WINDOWS:
        assert os.access(flagged / HOOK_FILE, os.X_OK)
    r = scaffold(flagged, '--gate')
    assert f'  kept    {HOOK_FILE} (already the gate of {TAG})' in r.stdout.splitlines(), r.stdout
    whole = (flagged / HOOK_FILE).read_bytes().decode('utf-8')
    write_lf(flagged / HOOK_FILE, whole.replace('\n', ' # changed\n', 2).replace(' # changed\n', '\n', 1))
    r = scaffold(flagged, '--gate')
    assert f'  replace {HOOK_FILE} (the gate of {TAG})' in r.stdout.splitlines(), r.stdout

    no_yaml = tmp_path / 'no-yaml'
    write_lf(no_yaml / 'yaml.py', 'raise ImportError("no yaml here")\n')
    for name, change, env in (('both', 'gate: both', None), ('not-yaml', None, None),
                              ('hook-no-yaml', 'gate: hook', {'PYTHONPATH': str(no_yaml)})):
        repo = make_p(tmp_path / name)
        if change:
            add_key(repo, change)
        else:
            write_lf(repo / '.claude' / 'kit.yml', 'version: 2\nprojects: [\n')
        before = listing(repo)
        for args in ((), ('--gate',)):
            r = scaffold(repo, *args, env=env)
            assert nothing_written(r), (name, args, r.stdout, r.stderr)
            assert listing(repo) == before, (name, args)

    own = hook_project('own')
    write_lf(own / HOOK_FILE, '#!/bin/sh\nexit 0\n')
    for args in (('--gate',), ()):
        r = scaffold(own, *args)
        assert nothing_written(r), (args, r.stdout)
        assert (own / HOOK_FILE).read_bytes() == b'#!/bin/sh\nexit 0\n'

    empty = tmp_path / 'empty'
    empty.mkdir()
    r = scaffold(empty, '--profile', 'python', env={'PYTHONPATH': str(no_yaml)})
    assert r.returncode == 0 and (empty / WORKFLOW_FILE).is_file(), r.stdout + r.stderr
    assert HOOK_FILE in scaffold(tmp_path, '--help').stdout


def git_grep(*args):
    r = subprocess.run(['git', 'grep', *args], cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode in (0, 1), r.stderr
    return r.stdout


@pytest.mark.private
def test_the_readme_and_the_changelog_say_how_a_project_takes_the_hook():
    """010/FR-012, SC-012."""
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    section = readme[readme.index('## The gate in each project'):readme.index('## Releasing the kit')]
    for words in ('gate: hook', 'gate: workflow', '.githooks/pre-push', 'git add --chmod=+x',
                  'git config core.hooksPath .githooks', 'one gate', 'PyYAML', 'read access', 'kit.gateSource',
                  'insteadOf', '.git/kit-gate', 'a tag that moves', 'only deletions', '--no-verify',
                  'until that clone switches it on', 'no check mark', 'last lines', 'conforms now'):
        assert words in section, words
    assert git_grep('-c', 'gate: hook', '--', 'CHANGELOG.md').strip()
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.9.0')]
    assert len([l for l in changelog.splitlines() if 'gate: hook' in l]) == len(
        [l for l in unreleased.splitlines() if 'gate: hook' in l]) >= 1


def test_the_skills_name_the_hook_and_have_no_route_to_it_by_hand():
    """009/FR-011 as modified by 012, SC-013."""
    skills = 'plugins/francis-kit/skills/'
    named = git_grep('-c', 'gate: hook', '--', skills + 'kit-init/SKILL.md', skills + 'kit-adopt/SKILL.md')
    assert len(named.splitlines()) == 2, named
    init = (REPO / skills / 'kit-init' / 'SKILL.md').read_text(encoding='utf-8')
    assert [l for l in init.splitlines() if l.startswith('| `gate`')]
    adopt = (REPO / skills / 'kit-adopt' / 'SKILL.md').read_text(encoding='utf-8')
    assert not [l for l in adopt.splitlines() if 'has no runner' in l or 'remove the scaffolded' in l]
    assert not [l for l in init.splitlines()
                if 'write `gate: hook` into the manifest' in l or 'CI runs on its own runner' in l]
    assert not [l for l in (init + adopt).splitlines() if 'warns "own runner"' in l]


def test_an_empty_hook_file_is_written_again_by_the_scaffold(tmp_path):
    """010/FR-011: an empty `.githooks/pre-push` is a missing one, as S14 says, not a hook of the project's own."""
    repo = tmp_path / 'r'
    repo.mkdir()
    assert run(SCAFFOLD, '--repo', repo, '--profile', 'python').returncode == 0
    kit = repo / '.claude' / 'kit.yml'
    kit.write_text(kit.read_text(encoding='utf-8').replace('version: 2\n', 'version: 2\ngate: hook\n', 1), encoding='utf-8')
    (repo / '.github' / 'workflows' / 'kit-gate.yml').unlink()
    hook = repo / '.githooks' / 'pre-push'
    hook.parent.mkdir(exist_ok=True)
    hook.write_text('', encoding='utf-8')
    r = run(SCAFFOLD, '--repo', repo, '--gate')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'KIT_REF=v' in hook.read_text(encoding='utf-8')


def test_a_hook_held_in_the_index_with_crlf_line_ends_is_not_the_gate(h):
    """010/FR-002: the hook file is HOOK unchanged; a blob with CRLF line ends is not, and on Linux git cannot start it."""
    git(h, 'config', 'core.autocrlf', 'false')
    body = (h / HOOK_FILE).read_bytes()
    (h / HOOK_FILE).write_bytes(body.replace(b'\n', b'\r\n'))
    git(h, 'add', '--chmod=+x', HOOK_FILE)
    assert b'\r\n' in subprocess.run(['git', 'show', ':' + HOOK_FILE], cwd=h, capture_output=True).stdout
    assert s14(doctor(h)) == ['  GAP  S14 pre-push is not the gate of this kit version: write it again with '
                             '`kit_scaffold.py --repo . --gate` (raising `KIT_REF=` alone is not enough)']
    (h / HOOK_FILE).write_bytes(body)                 # LF on disk again, the index still CRLF: the index is judged
    assert len(s14(doctor(h))) == 1
    git(h, 'add', '--chmod=+x', HOOK_FILE)
    assert s14(doctor(h)) == []
