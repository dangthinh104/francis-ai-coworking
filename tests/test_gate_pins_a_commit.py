"""The gate pins the kit to a commit, with its tag beside it (spec 026)."""
import re
import shutil
import sys
from pathlib import Path

import pytest

from conftest import KIT_SOURCE
from test_gate_hook import (HOOK_FILE, SHELLS, TAG, WORKFLOW_FILE, add_key, by_each_shell, doctor, hook, listing,
                            make_path, s14, write_lf)
from test_kit_gate import commit, git, make_p, start_repo
from test_standard import SCAFFOLD, run

WORKFLOW_GAP = ('kit-gate.yml does not pin the kit to a commit and its tag (ref: <40-hex commit>  # v1.2.3): '
                'write it again with kit_scaffold.py --repo . --gate')
HOOK_GAP = ('pre-push does not pin the kit to a commit and its tag (KIT_REF=v1.2.3 and KIT_COMMIT=<40-hex commit>): '
            'write it again with kit_scaffold.py --repo . --gate')
REF_LINE = re.compile(r'^[ \t]*ref:[ \t]*([0-9a-f]{40})[ \t]+#[ \t]*(v\d+\.\d+\.\d+)[ \t]*$', re.M)


def tag_commit(source=KIT_SOURCE, tag=TAG):
    return git(source, 'rev-parse', f'{tag}^{{commit}}').strip()


def no_commit(source):
    """The line of 026/FR-003, up to its reason."""
    return re.compile(rf'^ERROR   could not read the commit of {re.escape(TAG)} from {re.escape(source)}: '
                      r'.+\. Nothing was written\.$', re.M)


def refused(source, commit_):
    """The refusal line of 010/FR-008 as 026 modifies it."""
    return (f'kit-gate: could not fetch the kit {TAG} at commit {commit_} from {source}, which needs read access to '
            f'that repository with your own git credentials: the standard was NOT checked.')


def new_project(repo, *args):
    repo.mkdir()
    start_repo(repo)
    return run(SCAFFOLD, '--repo', repo, '--profile', 'python', '--name', 'demo', *args)


def test_the_workflow_gate_pins_the_commit_of_the_tag(tmp_path):
    """026/FR-001, SC-001: the commit of the tag, not the sha of the tag object."""
    r = new_project(tmp_path / 'p')
    assert r.returncode == 0, r.stdout + r.stderr
    text = (tmp_path / 'p' / WORKFLOW_FILE).read_text(encoding='utf-8')
    assert REF_LINE.findall(text) == [(tag_commit(), TAG)]
    assert f'ref: {tag_commit()}  # {TAG}\n' in text
    assert tag_commit() != git(KIT_SOURCE, 'rev-parse', TAG).strip(), 'the tag of the source is annotated'
    assert 'pinned to a commit' in text


def test_the_hook_gate_pins_the_commit_of_the_tag(tmp_path):
    """026/FR-002, SC-002."""
    r = new_project(tmp_path / 'h', '--gate-at', 'hook')
    assert r.returncode == 0, r.stdout + r.stderr
    rows = (tmp_path / 'h' / HOOK_FILE).read_text(encoding='utf-8').splitlines()
    at = rows.index(f'KIT_REF={TAG}')
    assert rows[at + 1] == f'KIT_COMMIT={tag_commit()}'


@pytest.fixture
def other_tag(tmp_path):
    """A bare repository holding one commit tagged v0.0.1, and not the kit's tag."""
    work = tmp_path / 'other'
    work.mkdir()
    start_repo(work)
    write_lf(work / 'x', 'x\n')
    commit(work)
    git(work, 'tag', 'v0.0.1')
    git(tmp_path, 'clone', '-q', '--bare', str(work), str(tmp_path / 'other.git'))
    return (tmp_path / 'other.git').as_posix()


@pytest.mark.parametrize('case', ['init', 'gate', 'dry-run', 'kept'])
@pytest.mark.parametrize('bad', ['no repository', 'no such tag'])
def test_the_scaffold_writes_nothing_where_it_cannot_read_the_commit(tmp_path, other_tag, case, bad):
    """026/FR-003, SC-003: under --gate, without it, under --dry-run, and when the gate is already current."""
    source = (tmp_path / 'nowhere').as_posix() if bad == 'no repository' else other_tag
    repo = tmp_path / 'p'
    if case == 'init':
        repo.mkdir()
        start_repo(repo)
    else:
        make_p(repo)
    git(repo, 'config', 'kit.gateSource', source)
    before = {p: p.read_bytes() for p in map(repo.joinpath, listing(repo)) if p.is_file() and '.git' not in p.parts}
    args = {'init': ['--profile', 'python'], 'gate': ['--gate'], 'dry-run': ['--gate', '--dry-run'], 'kept': []}[case]
    r = run(SCAFFOLD, '--repo', repo, *args)
    assert r.returncode == 1, r.stdout + r.stderr
    assert no_commit(source).search(r.stdout), r.stdout
    after = {p: p.read_bytes() for p in map(repo.joinpath, listing(repo)) if p.is_file() and '.git' not in p.parts}
    assert after == before


def test_a_url_with_a_credential_is_printed_without_it(tmp_path):
    """026/FR-003: the `user:pass@` of a URL is taken out, as 010/FR-008 prints it."""
    repo = tmp_path / 'p'
    make_p(repo)
    git(repo, 'config', 'kit.gateSource', 'file://someone:secret@/no/such/kit.git')
    r = run(SCAFFOLD, '--repo', repo, '--gate')
    assert r.returncode == 1 and 'secret' not in r.stdout and 'someone' not in r.stdout, r.stdout
    assert no_commit('file:///no/such/kit.git').search(r.stdout), r.stdout


@pytest.mark.skipif(sys.platform == 'win32', reason='the ssh command is started by sh, which sleeps here alike, '
                                                    'but the 60 seconds are measured once')
def test_a_source_that_answers_nothing_stops_at_sixty_seconds(tmp_path):
    """026/FR-003, SC-004."""
    repo = tmp_path / 'p'
    make_p(repo)
    git(repo, 'config', 'kit.gateSource', 'ssh://kit.example.invalid/kit.git')
    git(repo, 'config', 'core.sshCommand', f'"{Path(sys.executable).as_posix()}" -c "import time; time.sleep(300)"')
    import time
    started = time.monotonic()
    r = run(SCAFFOLD, '--repo', repo, '--gate')
    spent = time.monotonic() - started
    assert r.returncode == 1 and 'timed out after 60 seconds' in r.stdout, r.stdout
    assert 55 < spent < 120, spent


@pytest.fixture
def p(tmp_path):
    return make_p(tmp_path / 'p')


def test_s14_reads_the_workflow_pin(p):
    """026/FR-004, FR-005, SC-005."""
    path = p / WORKFLOW_FILE
    whole = path.read_text(encoding='utf-8')
    assert not s14(doctor(p)), doctor(p)
    c = tag_commit()
    line = f'ref: {c}  # {TAG}'
    for broken in (f'ref: {c}', f'ref: {c[:39]}  # {TAG}', f'ref: {c.upper()}  # {TAG}', f'ref: {TAG}'):
        write_lf(path, whole.replace(line, broken))
        assert s14(doctor(p)) == ['  GAP  S14 ' + WORKFLOW_GAP], broken
    write_lf(path, whole.replace(line, f'ref:\t{c}\t#{TAG} '))
    assert not [g for g in s14(doctor(p)) if 'does not pin' in g]


def test_s14_reads_the_hook_pin(tmp_path):
    """026/FR-005 by 010/FR-002 as modified, SC-005."""
    repo = tmp_path / 'h'
    make_p(repo)
    add_key(repo, 'gate: hook')
    (repo / WORKFLOW_FILE).unlink()
    assert run(SCAFFOLD, '--repo', repo, '--gate').returncode == 0
    git(repo, 'add', '--chmod=+x', HOOK_FILE)
    commit(repo)
    path = repo / HOOK_FILE
    whole = path.read_text(encoding='utf-8')
    assert not s14(doctor(repo)), doctor(repo)
    line = f'KIT_COMMIT={tag_commit()}\n'
    for broken in ('', line + line, f'KIT_COMMIT={tag_commit()[:39]}\n'):
        write_lf(path, whole.replace(line, broken))
        assert s14(doctor(repo)) == ['  GAP  S14 ' + HOOK_GAP], repr(broken)


def test_an_older_pinned_tag_is_judged_as_before(p):
    """026/FR-005, SC-006: the tag beside the commit is what the older-pin gap names."""
    path = p / WORKFLOW_FILE
    major, minor, patch = TAG[1:].split('.')
    older = f'v{major}.{int(minor) - 1}.0'
    whole = path.read_text(encoding='utf-8')
    write_lf(path, whole.replace(f'# {TAG}\n', f'# {older}\n'))
    gap = s14(doctor(p))
    assert len(gap) == 1 and f'pins {older}, and a newer kit, {TAG}, is installed here' in gap[0], gap


def make_hook_project(repo, source):
    make_p(repo)
    add_key(repo, 'gate: hook')
    (repo / WORKFLOW_FILE).unlink()
    git(repo, 'config', 'kit.gateSource', source.as_posix())
    r = run(SCAFFOLD, '--repo', repo, '--gate')
    assert r.returncode == 0, r.stdout + r.stderr
    git(repo, 'add', '--chmod=+x', HOOK_FILE)
    commit(repo)
    return repo


@pytest.fixture
def k(tmp_path):
    """A copy of the source, so a test may move its tag and delete it."""
    return Path(shutil.copytree(KIT_SOURCE, tmp_path / 'k.git'))


@by_each_shell
def test_the_hook_fetches_and_caches_the_pinned_commit(shell, tmp_path, k):
    """010/FR-007 as modified, SC-007: a tag moved later, or a source gone, changes nothing once cached."""
    repo = make_hook_project(tmp_path / 'h', k)
    c = tag_commit(k)
    path = make_path(tmp_path / 'bin')
    r = hook(shell, repo, path)
    assert r.code == 0, r
    assert [d.name for d in (repo / '.git' / 'kit-gate').iterdir()] == [c]
    work = tmp_path / 'moved'
    git(tmp_path, 'clone', '-q', str(k), str(work))
    start_repo(work)
    write_lf(work / 'y', 'y\n')
    commit(work)
    git(work, 'tag', '-f', TAG)
    git(work, 'push', '-q', '-f', 'origin', f'refs/tags/{TAG}')
    assert tag_commit(k) != c
    shutil.rmtree(k)
    r = hook(shell, repo, path)
    assert r.code == 0, r
    assert [d.name for d in (repo / '.git' / 'kit-gate').iterdir()] == [c]


@by_each_shell
@pytest.mark.parametrize('which', ['another version', 'unreachable'])
def test_the_hook_refuses_a_commit_that_is_not_the_pinned_version(shell, tmp_path, k, which):
    """010/FR-007 and 010/FR-008 as modified, SC-008."""
    repo = make_hook_project(tmp_path / 'h', k)
    if which == 'another version':
        work = tmp_path / 'next'
        git(tmp_path, 'clone', '-q', str(k), str(work))
        start_repo(work)
        manifest = work / 'plugins' / 'francis-kit' / '.claude-plugin' / 'plugin.json'
        manifest.write_text(manifest.read_text(encoding='utf-8').replace(f'"{TAG[1:]}"', '"0.0.1"'),
                            encoding='utf-8')
        pinned = commit(work)
        git(work, 'push', '-q', 'origin', 'HEAD:refs/heads/next')
    else:
        pinned = '1' * 40
    path_ = repo / HOOK_FILE
    write_lf(path_, path_.read_text(encoding='utf-8').replace(f'KIT_COMMIT={tag_commit(k)}', f'KIT_COMMIT={pinned}'))
    r = hook(shell, repo, make_path(tmp_path / 'bin'), stdin=f'HEAD {"2" * 40} HEAD {"0" * 40}\n')
    assert r.code == 1 and r.out == '' and r.err.splitlines() == [refused(k.as_posix(), pinned)], r
    assert not (repo / '.git' / 'kit-gate').exists() or not list((repo / '.git' / 'kit-gate').iterdir())


def test_the_templates_hold_both_placeholders():
    """026/FR-001, FR-002, SC-009: the export's exact-once edits leave the `ref:` line alone."""
    common = Path(SCAFFOLD).parent.parent / 'templates' / 'common'
    assert 'ref: {{KIT_COMMIT}}  # {{KIT_REF}}\n' in (common / 'kit-gate.yml').read_text(encoding='utf-8')
    rows = (common / 'pre-push').read_text(encoding='utf-8').splitlines()
    assert rows[rows.index('KIT_REF={{KIT_REF}}') + 1] == 'KIT_COMMIT={{KIT_COMMIT}}'


def test_a_second_pin_line_is_no_pin(p, tmp_path):
    """026/FR-004 and 010/FR-002 as modified: exactly one pin line, also when a second one is malformed."""
    path = p / WORKFLOW_FILE
    whole = path.read_text(encoding='utf-8')
    line = f'ref: {tag_commit()}  # {TAG}\n'
    write_lf(path, whole.replace(line, line + '          ref: main\n'))
    assert s14(doctor(p)) == ['  GAP  S14 ' + WORKFLOW_GAP]
    repo = tmp_path / 'h'
    make_hook_project(repo, KIT_SOURCE)
    hook_file = repo / HOOK_FILE
    pin = f'KIT_COMMIT={tag_commit()}\n'
    write_lf(hook_file, hook_file.read_text(encoding='utf-8').replace(pin, pin + 'KIT_COMMIT=main\n'))
    assert s14(doctor(repo)) == ['  GAP  S14 ' + HOOK_GAP]


def test_the_reason_is_what_git_says_first(tmp_path):
    """026/FR-003: the first `fatal:` line of git, not the last line of its advice."""
    repo = tmp_path / 'p'
    make_p(repo)
    nowhere = (tmp_path / 'nowhere').as_posix()
    git(repo, 'config', 'kit.gateSource', nowhere)
    r = run(SCAFFOLD, '--repo', repo, '--gate')
    line = [l for l in r.stdout.splitlines() if l.startswith('ERROR')]
    assert len(line) == 1 and 'does not appear to be a git repository' in line[0], r.stdout
    assert 'and the repository exists' not in line[0]


def test_without_a_source_the_kits_repository_is_read(tmp_path):
    """026/FR-003: no `kit.gateSource` anywhere: the kit's repository on GitHub (kept off the network here)."""
    import os
    import subprocess
    repo = tmp_path / 'p'
    make_p(repo)
    empty = tmp_path / 'empty-gitconfig'
    empty.write_text('', encoding='utf-8')
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM='1', GIT_ALLOW_PROTOCOL='file')
    r = subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(repo), '--gate'], capture_output=True,
                       text=True, encoding='utf-8', env=env, timeout=120)
    default = re.search(r"DEFAULT_SOURCE = '([^']+)'", Path(SCAFFOLD).read_text(encoding='utf-8')).group(1)
    assert r.returncode == 1 and no_commit(default).search(r.stdout), r.stdout


def test_the_documents_say_what_the_gate_pins():
    """026/FR-006, FR-007, FR-008."""
    root = Path(SCAFFOLD).resolve().parents[5]
    standard = (root / 'plugins' / 'francis-kit' / 'STANDARD.md').read_text(encoding='utf-8')
    row = next(l for l in standard.splitlines() if l.startswith('| S14 '))
    assert '`ref:` set to a commit and its tag in a comment' in row
    assert '`KIT_REF=` set to a tag and `KIT_COMMIT=` set to its commit' in row
    for readme in ('README.md', 'tools/public/README.md'):
        if not (root / readme).is_file():
            continue        # the public copy holds only its own README, at its root
        text = (root / readme).read_text(encoding='utf-8')
        if not text.count('\n## The gate in each project\n'):
            continue        # the public copy holds only its own README, at its root
        part = text.split('\n## The gate in each project\n', 1)[1].split('\n## ', 1)[0]
        for words in ('so a tag moved later does not change what it runs', 'Writing a gate reads the source over '
                      'the network, with read access to it', 'checked by the gate itself', 'may be deleted'):
            assert words in part, (readme, words)
    private = (root / 'README.md').read_text(encoding='utf-8')
    if '## Releasing the kit' in private:
        steps = private.split('## Releasing the kit', 1)[1].split('\n## ', 1)[0]
        for words in ('New gates pin the commit of `v<version>`', 'the tag has to be pushed before a gate can be '
                      'written', 'The gate fetches the kit by the commit of its tag'):
            assert words in steps, words
    for changelog, heading in (('CHANGELOG.md', '## Unreleased'), ('tools/public/CHANGELOG.md', '## 0.18.0')):
        path = root / changelog
        if path.is_file() and heading in path.read_text(encoding='utf-8'):
            section = path.read_text(encoding='utf-8').split(heading, 1)[1].split('\n## ', 1)[0]
            assert 'pin' in section and 'commit' in section and 'gate again' in section \
                and 'network' in section, changelog
