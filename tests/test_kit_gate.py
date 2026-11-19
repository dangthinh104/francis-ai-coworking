"""kit_gate.py: the checks of the gate in one script, and the template that starts it."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_standard import DOCTOR, SCAFFOLD, SCRIPTS, ci, feature, fill, manifest, run, save, write_own_words
import test_standard

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / 'plugins' / 'francis-kit'
GATE = SCRIPTS / 'kit_gate.py'
INDEX = SCRIPTS / 'spec_index.py'
REFS = SCRIPTS.parent.parent / 'comment-discipline' / 'scripts' / 'spec_refs.py'
TEMPLATE = SCRIPTS.parent / 'templates' / 'common' / 'kit-gate.yml'
TEMPLATE_IN_GIT = 'plugins/francis-kit/skills/kit-init/templates/common/kit-gate.yml'
IN_KIT = '.kit/plugins/francis-kit/skills/kit-init/scripts/kit_gate.py'
VERSION = json.loads((KIT / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']
OF_A_ROOT = re.compile(r'kit-gate: (map|citations|lint|refs|index)\b')
SIX = re.compile(r'kit_doctor\.py|map_check\.py|cite_refs\.py|spec_lint\.py|spec_refs\.py|spec_index\.py')
STEP = '      - name: Standard\n'
BASH_REASON = 'the gate step is bash'


def git(repo, *args):
    r = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def start_repo(repo):
    git(repo, 'init', '-q')
    for key, value in (('user.email', 'p@example.invalid'), ('user.name', 'p'),
                       ('core.autocrlf', 'false'), ('commit.gpgsign', 'false')):
        git(repo, 'config', key, value)


def commit(repo):
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', 'change')
    return git(repo, 'rev-parse', 'HEAD').strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def add_map(root, pin, cited='CLAUDE.md'):
    """A map of one citation, pinned to a commit that exists; `cited` is written from the git root."""
    write(root / 'docs' / 'ARCHITECTURE.md', f'<!-- kit:map revision={pin} -->\n# map\n\nThe rules are in `CLAUDE.md`.\n')
    write(root / 'docs' / 'diagrams' / 'map.refs.json',
          json.dumps({'meta': {'repository': {'revision': pin}}, 'sources': [{'path': cited, 'line': 1}]}))


def index(root):
    assert run(INDEX, '--root', root).returncode == 0


def make_p(repo):
    """The project `P` of spec 008, "a project that passes the gate": two commits, the second adds the map."""
    repo.mkdir()
    assert run(SCAFFOLD, '--repo', repo, '--profile', 'python', '--name', 'demo').returncode == 0
    fill(repo, deviations=False)
    ci(repo)
    start_repo(repo)
    first = commit(repo)
    add_map(repo, first)
    index(repo)
    commit(repo)
    assert git(repo, 'status', '--porcelain') == ''
    return repo


@pytest.fixture
def p(tmp_path):
    return make_p(tmp_path / 'p')


class Run:
    def __init__(self, done):
        self.code, self.raw, self.err = done.returncode, done.stdout, done.stderr.decode('utf-8')
        self.lines = done.stdout.decode('utf-8').splitlines()
        self.verdict = self.lines[-1] if self.lines else ''

    def starting(self, text):
        return [l for l in self.lines if l.startswith(text)]

    def failed(self):
        """The names of the verdict line, or [] when it says passed."""
        named = re.fullmatch(r'kit-gate: FAILED: ([a-z, ]+): kit .*', self.verdict)
        return named.group(1).split(', ') if named else []


def gate(repo, script=GATE, env=None):
    """A run: `python GATE --repo .` in the project, its two streams captured apart.

    008/FR-005 is asked of every run: git sees what it saw before, and neither file of the old steps is there.
    """
    tracked = (repo / '.git').exists()
    before = git(repo, 'status', '--porcelain') if tracked else None
    done = subprocess.run([sys.executable, str(script), '--repo', '.'], cwd=repo, env=env, capture_output=True)
    if tracked:
        assert git(repo, 'status', '--porcelain') == before
    assert not (repo / '.kit-roots').exists() and not (repo / '.kit-lint').exists()
    return Run(done)


def stamp(repo):
    return f"kit v{VERSION}, commit {git(repo, 'rev-parse', 'HEAD').strip()}"


def in_order(lines, *wanted):
    """Each text stands in a line below the line of the text before it; a `kit-gate:` text is a whole line."""
    at = -1
    for text in wanted:
        whole = text.startswith('kit-gate:')
        at = next((i for i in range(at + 1, len(lines)) if (lines[i] == text if whole else text in lines[i])), None)
        assert at is not None, f'{text!r} is missing, or out of order, in:\n' + '\n'.join(lines)


def record_debt(repo, name):
    data = manifest(repo)
    data['projects'][0]['deviations'] = [{'rule': 'S07', 'reason': 'r', 'fix': 'f', 'features': [name]}]
    save(repo, data)


def test_a_project_that_passes_every_check_passes_the_gate(p):
    """008/FR-001, 008/FR-002, 008/FR-004, 008/FR-006, SC-001."""
    r = gate(p)
    assert r.code == 0 and r.err == '', r.raw.decode('utf-8') + r.err
    in_order(r.lines, 'kit-gate: doctor', 'summary: 12 pass, 0 gap, 0 debt, 7 skipped', 'kit-gate: roots',
             'kit-gate: map: .', 'citations: ok=1 broken=0 not_from_project_root=0',
             'kit-gate: citations: .', 'checked 1 citation(s) in 1 file(s): 1 ok',
             'kit-gate: lint: .', 'kit-gate: index: .', 'specs/INDEX.md is current',
             'kit-gate: passed: ' + stamp(p))
    assert r.verdict == 'kit-gate: passed: ' + stamp(p)
    assert re.fullmatch(r'kit-gate: passed: kit v\d+\.\d+\.\d+, commit [0-9a-f]{40}', r.verdict)
    assert not r.starting('kit-gate: refs') and not r.starting('spec_lint:') and '.' not in r.lines
    own = [l for l in r.raw.split(b'\n') if l.startswith(b'kit-gate:')]
    assert len(own) == 8 and not any(l.endswith(b'\r') for l in own) and r.raw.endswith(b'\n')


def test_a_red_gate_runs_every_check_and_names_each_that_failed(p):
    """008/FR-001, 008/FR-006, SC-002."""
    feature(p, '001-a', status=None)
    commit(p)
    r = gate(p)
    assert r.code == 1
    in_order(r.lines, 'GAP  S07', 'citations: ok=1', 'ERROR 001-a: no single valid Status line',
             'specs/INDEX.md is stale: run spec_index.py', 'kit-gate: FAILED: doctor, lint, index: ' + stamp(p))
    assert r.verdict == 'kit-gate: FAILED: doctor, lint, index: ' + stamp(p)


def test_a_check_with_nothing_to_run_on_is_left_out(p, tmp_path):
    """008/FR-002, 003/FR-009, SC-003."""
    feature(p, '001-a', status=None)
    record_debt(p, '001-a')
    index(p)
    commit(p)
    r = gate(p)
    assert r.code == 0, r.lines
    in_order(r.lines, 'kit-gate: lint: .', 'left out of the spec lint, recorded as debt in .claude/kit.yml: 001-a')
    assert not r.starting('spec_lint:')
    feature(p, '002-b')
    index(p)
    commit(p)
    r = gate(p)
    assert r.code == 0 and any('spec_lint: 1 spec(s)' in l for l in r.lines), r.lines

    bare = make_p(tmp_path / 'bare')
    (bare / 'docs' / 'diagrams' / 'map.refs.json').unlink()
    (bare / 'specs' / 'INDEX.md').unlink()
    commit(bare)
    r = gate(bare)
    assert not r.starting('kit-gate: map') and not r.starting('kit-gate: citations') and not r.starting('kit-gate: index')
    assert any('GAP  S13' in l for l in r.lines)
    assert (r.code, r.verdict) == (1, 'kit-gate: FAILED: doctor: ' + stamp(bare))

    cited = make_p(tmp_path / 'cited')
    write(cited / 'specs' / '001-a' / 'spec.md',
          '# Feature Specification: 001-a\n\n**Status**: Draft\n**Ticket**: none\n**Capability**: demo\n')
    index(cited)
    assert run(REFS, '--repo', cited, '--root', cited, '--write-baseline').returncode == 0
    commit(cited)
    r = gate(cited)
    assert r.code == 0, r.lines
    at = r.lines.index('kit-gate: refs: .')
    assert any(l.startswith('0 citation(s) against 0 requirement(s)') for l in r.lines[at + 1:]), r.lines
    write(cited / 'src' / 'x.py', '# 001/FR-099\n')
    commit(cited)
    r = gate(cited)
    assert (r.code, r.verdict) == (1, 'kit-gate: FAILED: refs: ' + stamp(cited))


def test_without_a_usable_root_no_check_of_a_root_starts(p, tmp_path):
    """008/FR-003, SC-004."""
    (p / '.claude' / 'kit.yml').write_text('version: 2\nprojects: [\n', encoding='utf-8')
    commit(p)
    r = gate(p)
    assert r.code == 1
    assert sum('cannot check: .claude/kit.yml does not parse' in l for l in r.lines) == 2, r.lines
    assert not [l for l in r.lines if OF_A_ROOT.match(l)]
    assert r.verdict == 'kit-gate: FAILED: doctor, roots: ' + stamp(p)

    gone = make_p(tmp_path / 'gone')
    data = manifest(gone)
    data['projects'][0]['root'] = 'gone'
    save(gone, data)
    commit(gone)
    r = gate(gone)
    assert r.code == 1
    assert any("GAP  S01 demo: root 'gone' does not exist" in l for l in r.lines), r.lines
    assert 'kit-gate: no project roots found' in r.lines
    assert not [l for l in r.lines if OF_A_ROOT.match(l)]
    assert r.verdict == 'kit-gate: FAILED: doctor, roots: ' + stamp(gone)


def test_what_a_check_writes_to_standard_error_stands_where_it_was_written(p, tmp_path):
    """008/FR-004, 008/FR-006, SC-005."""
    copy = tmp_path / 'copy'
    shutil.copytree(p, copy, ignore=shutil.ignore_patterns('.git'))
    r = gate(copy)
    assert r.code == 1 and r.err == '', r.err
    project = r.lines.index('project demo (root .)')
    note = next(i for i, l in enumerate(r.lines) if 'note: S18: this directory is not the root of a git repository' in l)
    rule = next(i for i, l in enumerate(r.lines) if i > project and 'S02' in l)
    assert project < note < rule, r.lines
    in_order(r.lines, 'kit-gate: map: .', 'is not in this clone', 'kit-gate: citations: .',
             'is not inside a git repository')
    assert r.verdict == f'kit-gate: FAILED: map, citations: kit v{VERSION}, commit none'


def only_git(tmp_path):
    """A directory to be the whole PATH: git is found there, and no Python."""
    real = shutil.which('git')
    if sys.platform == 'win32':
        # Windows starts only an .exe by a bare name, and git.exe does not run from a copy:
        # the directory git is installed in stands for the one that holds nothing else.
        assert not list(Path(real).parent.glob('python*'))
        return Path(real).parent
    only = tmp_path / 'only-git'
    only.mkdir()
    (only / 'git').write_text(f'#!/bin/sh\nexec "{real}" "$@"\n', encoding='utf-8')
    (only / 'git').chmod(0o755)
    return only


def test_a_run_writes_nothing_into_the_project_and_needs_no_python_on_the_path(p, tmp_path):
    """008/FR-005, 008/FR-001, SC-006: `gate` asks the first half of every run of this file."""
    feature(p, '001-a', status=None)
    assert gate(p).failed() == ['doctor', 'lint', 'index']
    shutil.rmtree(p / 'specs' / '001-a')
    assert sorted(x.name for x in p.iterdir()) == ['.claude', '.git', '.github', '.specify', 'CLAUDE.md', 'docs', 'specs']
    path = str(only_git(tmp_path))
    assert shutil.which('python', path=path) is None and shutil.which('python3', path=path) is None
    r = gate(p, env=dict(os.environ, PATH=path))
    assert (r.code, r.verdict) == (0, 'kit-gate: passed: ' + stamp(p)), r.lines


@pytest.mark.parametrize('untracked', [None, 'all', 'no'])
def test_the_verdict_says_when_the_files_judged_are_not_the_commit(p, tmp_path, untracked):
    """008/FR-007, 008/FR-006, SC-007: the same under each setting of `status.showUntrackedFiles`."""
    def configure(repo):
        if untracked:
            git(repo, 'config', 'status.showUntrackedFiles', untracked)

    configure(p)
    clean = 'kit-gate: passed: ' + stamp(p)
    changed = clean + ', with uncommitted changes'
    (p / 'note.txt').write_text('x\n', encoding='utf-8')
    r = gate(p)
    assert (r.code, r.verdict) == (0, changed)
    exclude = p / '.git' / 'info' / 'exclude'
    exclude.parent.mkdir(exist_ok=True)
    exclude.write_text('note.txt\n', encoding='utf-8')
    r = gate(p)
    assert (r.code, r.verdict) == (0, clean)
    (p / 'note.txt').unlink()
    exclude.unlink()
    whole = (p / 'CLAUDE.md').read_bytes()
    (p / 'CLAUDE.md').write_bytes(whole + b'\nOne more line.\n')
    r = gate(p)
    assert (r.code, r.verdict) == (0, changed)
    (p / 'CLAUDE.md').write_bytes(whole)

    fresh = tmp_path / 'fresh'
    fresh.mkdir()
    start_repo(fresh)
    configure(fresh)
    (fresh / 'one.txt').write_text('x\n', encoding='utf-8')
    assert gate(fresh).verdict.endswith('commit none, with uncommitted changes')

    shutil.copytree(KIT, p / '.kit' / 'plugins' / 'francis-kit', ignore=shutil.ignore_patterns('__pycache__'))
    if not untracked:
        assert git(p, 'status', '--porcelain') == '?? .kit/\n'
    r = gate(p, script=IN_KIT)
    assert (r.code, r.verdict) == (0, clean), r.lines
    (p / 'note.txt').write_text('x\n', encoding='utf-8')
    r = gate(p, script=IN_KIT)
    assert (r.code, r.verdict) == (0, changed)
    (p / 'note.txt').unlink()

    alone = tmp_path / 'alone'
    alone.mkdir()
    shutil.copy(GATE, alone / 'kit_gate.py')
    r = gate(p, script=alone / 'kit_gate.py')
    assert r.code == 1 and r.verdict.startswith('kit-gate: FAILED: doctor, roots: kit unknown, commit '), r.lines


def at_v090():
    r = subprocess.run(['git', 'show', 'v0.9.0:' + TEMPLATE_IN_GIT], cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, 'the tag v0.9.0 is needed to compare the template with: ' + r.stderr
    return r.stdout


@pytest.mark.private
def test_the_gate_template_starts_the_checks_by_one_step(tmp_path):
    """008/FR-008 as modified by 009, SC-008 of 008 and SC-006 of 009."""
    import yaml
    template = TEMPLATE.read_text(encoding='utf-8')
    rows = template.splitlines()
    assert not [l for l in rows if SIX.search(l)]
    assert not [l for l in rows if '.kit-roots' in l or '.kit-lint' in l]
    assert len([l for l in rows if 'kit_gate.py' in l]) == 1
    job = yaml.safe_load(template.replace('{{KIT_REF}}', 'v0.0.0'))['jobs']['standard']
    standard = [s for s in job['steps'] if s.get('name') == 'Standard']
    assert len(standard) == 1 and 'if' not in standard[0]
    assert standard[0]['run'].splitlines() == ['python ../kit/plugins/francis-kit/skills/kit-init/scripts/kit_gate.py --repo .']
    for gone in ('Map citations', 'Spec lint', 'Requirement citations and index'):
        assert not [s for s in job['steps'] if s.get('name') == gone], gone
    old = at_v090()
    assert template.count(STEP) == 1

    assert run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python').returncode == 0
    written = tmp_path / '.github' / 'workflows' / 'kit-gate.yml'
    gate_text = written.read_text(encoding='utf-8')
    assert 'PASS S14' in run(DOCTOR, '--repo', tmp_path).stdout and 'kit_gate.py' in gate_text
    written.write_text(gate_text[:gate_text.index(STEP)] + old[old.index(STEP):], encoding='utf-8')
    assert 'not the gate of this kit version' in run(DOCTOR, '--repo', tmp_path).stdout


@pytest.mark.private
def test_the_documents_say_where_the_checks_of_the_gate_live():
    """008/FR-009, SC-009."""
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    assert [l for l in readme.splitlines() if l.startswith('| `kit-init/scripts/kit_gate.py')]
    section = readme[readme.index('## The gate in each project'):readme.index('## Releasing the kit')]
    for words in ('kit_gate.py', 'every check', 'last line'):
        assert words in section, words
    step = [l for l in readme[readme.index('## Releasing the kit'):].splitlines() if l.startswith('4. ')][0]
    assert 'kit_gate.py' in step
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.9.0')]
    line = [l for l in unreleased.splitlines() if 'kit_gate.py' in l]
    assert len(line) == 1 and 'writing its gate again' in line[0]
    for words in ('gate template changed', 'every check that failed', 'last line'):
        assert words in line[0], words
    for path in [REPO / 'README.md', *sorted(SCRIPTS.glob('*.py'))]:
        assert 'checks a gate runs' not in path.read_text(encoding='utf-8').lower(), path.name
    helped = run(SCAFFOLD, '--help')
    assert helped.returncode == 0 and 'kit_gate.py' in helped.stdout


def test_only_the_secret_step_is_still_run_by_bash():
    """008/FR-008, SC-010: what the count of skipped tests is made of; the run of the suite is not started from here."""
    sources = {f.name: f.read_text(encoding='utf-8') for f in sorted((REPO / 'tests').glob('*.py'))}
    assert not [name for name, text in sources.items() if 'KIT_TEST_' + 'BASH' in text]
    assert sum(text.count("reason='" + BASH_REASON) for text in sources.values()) == 1
    secret = test_standard.test_the_gate_fails_without_its_secret_except_where_secrets_never_arrive
    skips = [m for m in secret.pytestmark if m.name == 'skipif']
    assert len(skips) == 1 and skips[0].kwargs['reason'].startswith(BASH_REASON)
    assert skips[0].args == (sys.platform == 'win32',) and len(test_standard.GATE_CASES) == 7
    for gone in ('test_the_gate_template_runs_the_lint_after_the_roots_are_known',
                 'test_the_gate_step_fails_on_a_lint_error_and_leaves_out_recorded_debt'):
        assert not hasattr(test_standard, gone), gone


def test_the_gate_fails_on_a_lint_error_and_leaves_out_recorded_debt(p):
    """003/FR-001, 003/FR-009, SC-001 and SC-007 of 003: the lint as the gate runs it, by `kit_gate.py`."""
    r = gate(p)                                       # no feature directory
    assert r.code == 0 and not r.starting('spec_lint:'), r.lines
    feature(p, '001-a', status=None)
    r = gate(p)
    assert r.code == 1 and 'lint' in r.failed() and any('ERROR 001-a' in l for l in r.lines), r.lines
    shutil.rmtree(p / 'specs' / '001-a')
    feature(p, '004-old', status=None)
    feature(p, '005-new')
    record_debt(p, '004-old')
    r = gate(p)
    assert 'lint' not in r.failed() and r.err == '', r.lines
    assert any('left out' in l and '004-old' in l for l in r.lines) and any('spec_lint: 1 spec(s)' in l for l in r.lines)
    shutil.rmtree(p / 'specs' / '005-new')            # every feature left out: SC-007 of 003 as written
    r = gate(p)
    assert 'lint' not in r.failed() and not r.starting('spec_lint:'), r.lines
    assert any('left out' in l and '004-old' in l for l in r.lines)
    data = manifest(p)
    data['projects'][0]['deviations'] = []
    save(p, data)
    r = gate(p)
    assert r.code == 1 and 'lint' in r.failed() and any('ERROR 004-old' in l for l in r.lines), r.lines


def two_roots(repo):
    """A repository made like `P`, with the projects `a` and `b`."""
    repo.mkdir()
    for root in ('a', 'b'):
        (repo / root).mkdir()
        assert run(SCAFFOLD, '--repo', repo, '--project-root', root, '--profile', 'python', '--name', root).returncode == 0
    kit = repo / '.claude' / 'kit.yml'
    text = kit.read_text(encoding='utf-8')
    text = text.replace('pr_target:  ', 'pr_target: main  ').replace('deploy_branches:  ', 'deploy_branches: []  ')
    kit.write_text(text[:text.index('    deviations:')] + '    deviations: []\nscratch: []\n', encoding='utf-8')
    data = manifest(repo)
    data['projects'] = [dict(data['projects'][0], name=root, root=root) for root in ('a', 'b')]
    save(repo, data)
    entry = data['projects'][0]['test'][0]
    ci(repo, ''.join(f'      - run: {entry}\n        working-directory: {root}\n' for root in ('a', 'b')))
    for root in ('a', 'b'):
        write_own_words(repo / root)
    start_repo(repo)
    first = commit(repo)
    for root in ('a', 'b'):
        add_map(repo / root, first, cited=f'{root}/CLAUDE.md')
        index(repo / root)
    commit(repo)
    return repo


def test_a_check_that_failed_is_named_once_whatever_the_number_of_roots(tmp_path):
    """008/FR-001, 008/FR-004, 008/FR-006, SC-011."""
    repo = two_roots(tmp_path / 'two')
    r = gate(repo)
    assert (r.code, r.verdict) == (0, 'kit-gate: passed: ' + stamp(repo)), r.lines
    feature(repo / 'b', '001-x', status=None)
    commit(repo)
    r = gate(repo)
    assert [l for l in r.lines if OF_A_ROOT.match(l)] == [
        'kit-gate: map: a', 'kit-gate: citations: a', 'kit-gate: map: b', 'kit-gate: citations: b',
        'kit-gate: lint: a', 'kit-gate: lint: b', 'kit-gate: index: a', 'kit-gate: index: b']
    assert (r.code, r.verdict) == (1, 'kit-gate: FAILED: doctor, lint, index: ' + stamp(repo))
    feature(repo / 'a', '001-x', status=None)
    commit(repo)
    r = gate(repo)
    assert (r.code, r.verdict) == (1, 'kit-gate: FAILED: doctor, lint, index: ' + stamp(repo))


def test_a_directory_that_is_not_there_is_no_verdict(tmp_path):
    """008/FR-006, SC-012."""
    r = subprocess.run([sys.executable, str(GATE), '--repo', 'no-such-directory'], cwd=tmp_path, capture_output=True)
    out = r.stdout.decode('utf-8').splitlines()
    assert r.returncode == 2 and 'no-such-directory' in r.stderr.decode('utf-8')
    assert not [l for l in out if l.startswith(('kit-gate: passed', 'kit-gate: FAILED'))]


def test_a_listing_is_cut_at_a_line_feed_only_as_the_shell_of_the_template_read_it():
    """008/FR-002, 008/FR-003: a root is a line of `--roots` as `IFS= read -r` read it, blanks and all."""
    sys.path.insert(0, str(SCRIPTS))
    import kit_gate
    assert kit_gate.listed('a b\n   \n\nc d\r\n'.encode('utf-8')) == ['a b', '   ', 'c d']
    assert kit_gate.listed(b'') == []


def test_an_untracked_link_to_a_directory_above_the_kit_is_an_uncommitted_change(p):
    """008/FR-007: only the kit's own directory is left out, not a link that happens to lead above it."""
    from conftest import link
    link(p / 'up', REPO.parent)
    r = gate(p)
    assert (r.code, r.verdict) == (0, 'kit-gate: passed: ' + stamp(p) + ', with uncommitted changes'), r.lines
