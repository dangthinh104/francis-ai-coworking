"""kit-init and kit-adopt ask where the gate runs, and the scaffold writes the answer (spec 012)."""
import pytest
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SCAFFOLD = REPO / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_scaffold.py'
SKILLS = REPO / 'plugins' / 'francis-kit' / 'skills'
INIT = SKILLS / 'kit-init' / 'SKILL.md'
ADOPT = SKILLS / 'kit-adopt' / 'SKILL.md'
QUESTION = 'Does GitHub start jobs on GitHub-hosted runners (such as ubuntu-latest) for this account?'
MANIFEST = '.claude/kit.yml'
WORKFLOW = '.github/workflows/kit-gate.yml'
HOOK = '.githooks/pre-push'
GH = 'gh variable set'
NOTHING_SET = ('the kit sets nothing on GitHub: run it once in a POSIX shell (Git Bash on Windows), signed in as '
               "someone who may change the repository's variables")
OWN_HOOK = '#!/bin/sh\nexit 0\n'


def git(repo, *args):
    r = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, (args, r.stdout + r.stderr)
    return r.stdout


def commit(repo):
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false',
        'commit', '-q', '--no-verify', '-m', 'change')


def scaffold(repo, *args, env=None):
    """A scaffold run: `python kit_scaffold.py --repo .` at the root of `repo`."""
    return subprocess.run([sys.executable, str(SCAFFOLD), '--repo', '.', *args], cwd=repo, capture_output=True,
                          text=True, encoding='utf-8', env=env)


def empty_repo(tmp_path, name='r'):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, 'init', '-q')
    return repo


def scaffolded(tmp_path, name='r'):
    repo = empty_repo(tmp_path, name)
    r = scaffold(repo, '--profile', 'python')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'gate:' not in (repo / MANIFEST).read_text(encoding='utf-8') and (repo / WORKFLOW).is_file()
    return repo


def listing(repo):
    """Every path below `repo` but `.git`, with each file's bytes."""
    out = {}
    for path in repo.rglob('*'):
        rel = path.relative_to(repo).as_posix()
        if rel == '.git' or rel.startswith('.git/'):
            continue
        out[rel] = path.read_bytes() if path.is_file() else None
    return out


def manifest_lines(repo):
    return (repo / MANIFEST).read_text(encoding='utf-8').splitlines()


def add_gate_line(repo, gate):
    path = repo / MANIFEST
    text = path.read_text(encoding='utf-8')
    assert text.startswith('version: 2\n')
    path.write_bytes(text.replace('version: 2\n', f'version: 2\ngate: {gate}\n', 1).encode('utf-8'))


def output(r):
    return (r.stdout + r.stderr).splitlines()


def refused(repo, *args):
    """A refusal, with and without --dry-run: exit 1, one line ending `Nothing was written.`, no `gh` line,
    and no file created or changed. Returns the line."""
    seen = []
    for dry in ((), ('--dry-run',)):
        before = listing(repo)
        r = scaffold(repo, *args, *dry)
        lines = output(r)
        assert r.returncode == 1, (args, dry, r.returncode, lines)
        assert len(lines) == 1 and lines[0].endswith('Nothing was written.'), (args, dry, lines)
        assert not [l for l in lines if GH in l]
        assert listing(repo) == before, (args, dry)
        seen.append(lines[0])
    assert seen[0] == seen[1], seen
    return seen[0]


def gh_lines(r):
    return [l for l in output(r) if GH in l]


def section(text, start, end):
    lines = text.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith(start))
    last = next(i for i, l in enumerate(lines) if l.startswith(end) and i > first)
    return lines[first + 1:last]


def test_sc001_the_manifest_names_the_gate_of_the_answer(tmp_path):
    """012/FR-001: `gate: <the gate>` directly below `version:`, created or added, `--dry-run` listing it."""
    for name, args, second in (('hook', ('--gate-at', 'hook'), 'gate: hook'),
                               ('hosted', ('--gate-at', 'hosted'), 'gate: workflow'),
                               ('runner', ('--gate-at', 'runner', '--runner-label', 'team-runner'), 'gate: workflow')):
        repo = empty_repo(tmp_path, name)
        r = scaffold(repo, '--profile', 'python', *args)
        assert r.returncode == 0, r.stdout + r.stderr
        lines = manifest_lines(repo)
        assert lines[0] == 'version: 2' and lines[1] == second, (name, lines[:3])
        assert yaml.safe_load((repo / MANIFEST).read_text(encoding='utf-8'))['gate'] == second.split()[1]
    for name, args in (('none', ('--gate-at', 'none')), ('plain', ())):
        repo = empty_repo(tmp_path, name)
        assert scaffold(repo, '--profile', 'python', *args).returncode == 0
        assert not [l for l in manifest_lines(repo) if l.startswith('gate:')], name

    repo = scaffolded(tmp_path, 'keyless')
    (repo / WORKFLOW).unlink()
    before = listing(repo)
    r = scaffold(repo, '--gate-at', 'hook', '--dry-run')
    assert r.returncode == 0 and 'update  .claude/kit.yml (gate: hook)' in r.stdout, r.stdout
    assert listing(repo) == before
    old = (repo / MANIFEST).read_bytes()
    r = scaffold(repo, '--gate-at', 'hook')
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / MANIFEST).read_bytes() == old.replace(b'version: 2\n', b'version: 2\ngate: hook\n', 1)
    assert manifest_lines(repo)[1] == 'gate: hook'

    repo = scaffolded(tmp_path, 'crlf')
    (repo / WORKFLOW).unlink()
    crlf = (repo / MANIFEST).read_bytes().replace(b'\n', b'\r\n')
    (repo / MANIFEST).write_bytes(crlf)
    assert scaffold(repo, '--gate-at', 'hook').returncode == 0
    assert (repo / MANIFEST).read_bytes() == crlf.replace(b'version: 2\r\n', b'version: 2\r\ngate: hook\r\n', 1)

    repo = scaffolded(tmp_path, 'hosted-later')
    workflow = (repo / WORKFLOW).read_bytes()
    r = scaffold(repo, '--gate-at', 'hosted')
    assert r.returncode == 0, r.stdout + r.stderr
    assert manifest_lines(repo)[1] == 'gate: workflow' and (repo / WORKFLOW).read_bytes() == workflow

    r = subprocess.run([sys.executable, str(SCAFFOLD), '--help'], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0 and '--gate-at' in r.stdout and '--runner-label' in r.stdout


def test_sc002_the_gate_file_of_the_answer_and_no_other(tmp_path):
    """012/FR-002: the gate file of the answer, none of another gate, none under `none`."""
    repo = empty_repo(tmp_path, 'hook')
    assert scaffold(repo, '--profile', 'python', '--gate-at', 'hook').returncode == 0
    assert (repo / HOOK).is_file() and not (repo / WORKFLOW).exists()
    repo = empty_repo(tmp_path, 'hosted')
    assert scaffold(repo, '--profile', 'python', '--gate-at', 'hosted').returncode == 0
    assert (repo / WORKFLOW).is_file() and not (repo / '.githooks').exists()
    repo = empty_repo(tmp_path, 'none')
    assert scaffold(repo, '--profile', 'python', '--gate-at', 'none').returncode == 0
    assert not (repo / WORKFLOW).exists() and not (repo / '.githooks').exists()
    assert (repo / MANIFEST).is_file()

    repo = empty_repo(tmp_path, 'dry')
    before = listing(repo)
    r = scaffold(repo, '--profile', 'python', '--dry-run', '--gate-at', 'hook')
    assert r.returncode == 0 and 'create  .githooks/pre-push' in r.stdout, r.stdout
    assert not [l for l in output(r) if 'kit-gate.yml' in l]
    assert listing(repo) == before

    repo = scaffolded(tmp_path, 'kept')
    before = listing(repo)
    r = scaffold(repo, '--gate-at', 'none')
    assert r.returncode == 0, r.stdout + r.stderr
    after = listing(repo)
    assert after[MANIFEST] == before[MANIFEST] and after[WORKFLOW] == before[WORKFLOW]


def test_sc003_a_runner_answer_prints_the_gh_line_and_starts_nothing(tmp_path):
    """012/FR-003: the two last lines, with and without --dry-run; no program started; none on exit 2."""
    stub = tmp_path / 'stub'
    stub.mkdir()
    ran = stub / 'ran'
    (stub / 'gh').write_text(f'#!/bin/sh\n: > "{ran.as_posix()}"\n', encoding='utf-8')
    os.chmod(stub / 'gh', 0o755)
    if sys.platform == 'win32':
        (stub / 'gh.cmd').write_text(f'@echo off\r\ntype nul > "{ran}"\r\n', encoding='utf-8')
    env = {**os.environ, 'PATH': str(stub) + os.pathsep + os.environ.get('PATH', '')}
    for labels, text in ((('self-hosted', 'team-runner'), '["self-hosted", "team-runner"]'), (('team-runner',), '"team-runner"')):
        given = [a for label in labels for a in ('--runner-label', label)]
        for dry in ((), ('--dry-run',)):
            repo = empty_repo(tmp_path, f'r{len(labels)}{len(dry)}')
            r = scaffold(repo, '--gate-at', 'runner', *given, *dry, env=env)
            assert r.returncode == 0, r.stdout + r.stderr
            assert r.stdout.splitlines()[-2:] == [f"gh variable set KIT_GATE_RUNNER --body '{text}'", NOTHING_SET]
            assert len(gh_lines(r)) == 1
            assert not ran.exists()

    r = subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(tmp_path / 'nowhere'), '--gate-at', 'runner',
                        '--runner-label', 'team-runner'], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 2 and not gh_lines(r)
    r = subprocess.run([sys.executable, str(SCAFFOLD), '--help'], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0 and not gh_lines(r)
    found = subprocess.run(['git', 'grep', '-c', GH, '--', 'plugins/francis-kit/skills/kit-init/scripts/kit_scaffold.py'],
                           cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert found.stdout.strip(), found.stdout + found.stderr


def test_sc004_options_that_do_not_go_together_are_refused(tmp_path):
    """012/FR-004: the line names the options, by their names, with no label."""
    repo = empty_repo(tmp_path)
    assert '--runner-label' in refused(repo, '--gate-at', 'runner')
    for args in (('--gate-at', 'hook', '--runner-label', 'team-runner'), ('--gate-at', 'hosted', '--runner-label', 'team-runner'),
                 ('--gate-at', 'none', '--runner-label', 'team-runner'), ('--runner-label', 'team-runner')):
        line = refused(repo, *args)
        assert '--runner-label' in line and 'team-runner' not in line, (args, line)
    line = refused(repo, '--gate', '--gate-at', 'none')
    assert '--gate' in line and 'none' in line, line


def test_sc005_a_label_that_cannot_be_pasted_is_refused(tmp_path):
    """012/FR-005: the label between single quotes; one that argparse reads as an option exits 2."""
    repo = empty_repo(tmp_path)
    for label in ('', '-x', 'vn prod', 'vn\tprod', 'vn,prod', "vn'prod", 'vn"prod'):
        line = refused(repo, '--gate-at', 'runner', f'--runner-label={label}')
        assert f"'{label}'" in line, (label, line)
    for label in ('-1', '-'):
        assert f"'{label}'" in refused(repo, '--gate-at', 'runner', '--runner-label', label), label
    before = listing(repo)
    r = scaffold(repo, '--gate-at', 'runner', '--runner-label', '-x')
    assert r.returncode == 2 and 'expected one argument' in r.stderr, r.stderr
    assert listing(repo) == before


def test_sc006_a_manifest_that_cannot_name_the_gate_is_refused(tmp_path):
    """012/FR-006: another gate named, no `version:` line, `--gate` with no manifest."""
    repo = scaffolded(tmp_path, 'hook')
    add_gate_line(repo, 'hook')
    (repo / WORKFLOW).unlink()
    line = refused(repo, '--gate-at', 'hosted')
    for words in ('hook', 'workflow', 'set gate: workflow in .claude/kit.yml by hand first'):
        assert words in line, (words, line)
    before = (repo / MANIFEST).read_bytes()
    r = scaffold(repo, '--gate-at', 'hook')
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / MANIFEST).read_bytes() == before

    repo = scaffolded(tmp_path, 'noversion')
    path = repo / MANIFEST
    path.write_bytes(path.read_bytes().replace(b'version: 2\n', b'', 1))
    assert 'has no version: line' in refused(repo, '--gate-at', 'hosted')

    repo = empty_repo(tmp_path, 'empty')
    for answer in ('hook', 'hosted'):
        assert 'run it without --gate first' in refused(repo, '--gate', '--gate-at', answer), answer


def test_sc007_kit_init_asks_the_gate_question_in_its_one_round():
    """012/FR-007: the question, gate_choice, the labels, a hook manager, between "Ask once" and "Run"."""
    ask = section(INIT.read_text(encoding='utf-8'), '### 2. Ask once', '### 3. Run')
    assert [l for l in ask if QUESTION in l]
    assert [l for l in ask if 'gate_choice' in l]
    assert [l for l in ask if 'labels' in l and 'null' in l]
    assert [l for l in ask if 'hook_manager' in l and 'hosted' in l]


def test_sc008_kit_init_starts_the_scaffold_with_the_answer():
    """012/FR-008: every python3 line that starts the scaffold holds --gate-at."""
    lines = INIT.read_text(encoding='utf-8').splitlines()
    runs = [l for l in lines if l.lstrip().startswith('python3') and 'kit_scaffold.py' in l]
    assert len(runs) >= 2 and all('--gate-at' in l for l in runs), runs
    assert [l for l in lines if '--runner-label' in l]


def test_sc009_kit_adopt_reads_and_asks_before_it_scaffolds():
    """012/FR-007: kit_detect.py and the question stand above the first scaffold run."""
    lines = ADOPT.read_text(encoding='utf-8').splitlines()

    def first(words):
        return next(i for i, l in enumerate(lines) if words in l)
    assert first('kit_detect.py') < first('kit_scaffold.py')
    assert first(QUESTION) < first('kit_scaffold.py')
    assert [l for l in lines if 'gate_choice' in l]


def test_sc010_kit_adopt_passes_the_answer_and_records_s14_only_for_none():
    """012/FR-008, 012/FR-011."""
    lines = ADOPT.read_text(encoding='utf-8').splitlines()
    first = next(l for l in lines if 'kit_scaffold.py' in l)
    assert '--gate-at' in first and '--dry-run' in first, first
    assert [l for l in lines if '--runner-label' in l]
    assert [l for l in lines if '--gate-at none' in l]
    recorded = [l for l in lines if 'record S14' in l]
    assert recorded and all('none of the three' in l for l in recorded), recorded


@pytest.mark.private
def test_sc011_the_readme_names_the_option():
    """012/FR-012: the section on the gate names --gate-at."""
    part = section((REPO / 'README.md').read_text(encoding='utf-8'), '## The gate in each project', '## Releasing the kit')
    assert [l for l in part if '--gate-at' in l]


@pytest.mark.private
def test_sc012_the_changelog_and_the_readme_name_the_option_and_the_question():
    """012/FR-012."""
    r = subprocess.run(['git', 'grep', '-c', '-e', '--gate-at', '--', 'CHANGELOG.md'], cwd=REPO,
                       capture_output=True, text=True, encoding='utf-8')
    assert r.stdout.strip(), r.stdout + r.stderr
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.10.0')]
    named = [l for l in unreleased.splitlines() if '--gate-at' in l]
    assert len(named) == 1 and 'KIT_GATE_RUNNER' not in named[0] and 'kit_gate.py' not in named[0], named
    span = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.9.0')]
    for word in ('KIT_GATE_RUNNER', 'kit_gate.py'):
        assert len([l for l in span.splitlines() if word in l]) == 1, word
    part = section((REPO / 'README.md').read_text(encoding='utf-8'), '## The gate in each project', '## Releasing the kit')
    assert [l for l in part if QUESTION in l]
    assert [l for l in part if '--gate-at' in l]


def offers(lines, answer):
    """The line of a skill that offers an answer: a list item that starts with it."""
    return [l for l in lines if l.lstrip().startswith(f'- `{answer}`')]


@pytest.mark.private
def test_sc013_the_old_routes_are_gone_and_each_answer_says_what_it_writes():
    """012/FR-007, 009/FR-011 as modified by 012."""
    init, adopt = (p.read_text(encoding='utf-8').splitlines() for p in (INIT, ADOPT))
    assert not [l for l in adopt if 'has no runner' in l or 'remove the scaffolded' in l]
    assert not [l for l in init if 'write `gate: hook` into the manifest' in l or 'CI runs on its own runner' in l]
    assert not [l for l in init + adopt if 'warns "own runner"' in l]
    skills = ['plugins/francis-kit/skills/kit-init/SKILL.md', 'plugins/francis-kit/skills/kit-adopt/SKILL.md']

    def grep(*args):
        r = subprocess.run(['git', 'grep', *args], cwd=REPO, capture_output=True, text=True, encoding='utf-8')
        assert r.returncode in (0, 1), r.stderr
        return r.stdout
    assert grep('-n', '-E', '-e', r'--repo \. --gate([^-]|$)', '--', *skills) == ''
    row = [l for l in adopt if l.startswith('| S14')]
    assert len(row) == 1 and 'KIT_GATE_RUNNER' in row[0] and '`runner`' in row[0], row
    assert "where CI runs on the project's own runner" not in row[0]
    assert len(grep('-c', 'gate: hook', '--', *skills).splitlines()) == 2
    assert len(grep('-c', 'KIT_GATE_RUNNER', '--', *skills, 'CHANGELOG.md').splitlines()) == 3
    for lines in (init, adopt):
        runner, hook = offers(lines, 'runner'), offers(lines, 'hook')
        assert runner and all('KIT_GATE_RUNNER' in l for l in runner), runner
        assert hook and all('gate: hook' in l for l in hook), hook
    assert [l for l in init if l.startswith('| `gate`')]


def test_sc014_a_hook_manager_is_not_replaced_by_the_kits_hook(tmp_path):
    """012/FR-010: `--gate-at hook` refused where hook_manager is not empty."""
    def husky(name):
        repo = scaffolded(tmp_path, name)
        (repo / WORKFLOW).unlink()
        (repo / '.husky').mkdir()
        (repo / '.husky' / 'pre-commit').write_text('npx lint-staged\n', encoding='utf-8')
        commit(repo)
        return repo
    repo = husky('hosted')      # a run of its own: it writes gate: workflow, which the hook would then meet first
    assert scaffold(repo, '--gate-at', 'hosted').returncode == 0
    repo = husky('husky')
    line = refused(repo, '--gate-at', 'hook')
    assert '.husky/' in line and 'answer hosted or runner' in line, line
    git(repo, 'rm', '-rq', '.husky')
    git(repo, 'config', '--local', 'core.hooksPath', '.hooks')
    assert 'core.hooksPath=.hooks' in refused(repo, '--gate-at', 'hook')

    repo = empty_repo(tmp_path, 'own')
    (repo / '.githooks').mkdir()
    (repo / HOOK).write_bytes(OWN_HOOK.encode('utf-8'))
    assert '.githooks/' in refused(repo, '--profile', 'python', '--gate-at', 'hook')
    assert (repo / HOOK).read_bytes() == OWN_HOOK.encode('utf-8')
    r = scaffold(repo, '--profile', 'python', '--gate-at', 'hosted')
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / WORKFLOW).is_file() and (repo / HOOK).read_bytes() == OWN_HOOK.encode('utf-8')

    repo = empty_repo(tmp_path, 'empty')
    (repo / '.githooks').mkdir()
    (repo / HOOK).write_bytes(b'')
    r = scaffold(repo, '--profile', 'python', '--gate-at', 'hook')
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / HOOK).read_bytes() == b''


def test_sc015_a_project_holds_one_gate(tmp_path):
    """012/FR-009: the other gate file is refused, not removed."""
    repo = scaffolded(tmp_path, 'workflow')
    line = refused(repo, '--gate-at', 'hook')
    assert WORKFLOW in line and 'remove it first' in line, line
    (repo / WORKFLOW).write_bytes(b'')
    assert refused(repo, '--gate-at', 'hook') == line

    repo = scaffolded(tmp_path, 'hook')
    (repo / WORKFLOW).unlink()
    assert scaffold(repo, '--gate-at', 'hook').returncode == 0
    path = repo / MANIFEST
    path.write_bytes(path.read_bytes().replace(b'gate: hook\n', b'', 1))
    line = refused(repo, '--gate-at', 'hosted')
    assert HOOK in line and 'remove it first' in line, line


def test_sc016_the_first_refusal_in_the_order_is_printed(tmp_path):
    """012/FR-004, 012/FR-006, 012/FR-009, 012/FR-010: one total order of refusals."""
    repo = scaffolded(tmp_path, 'named')
    (repo / WORKFLOW).unlink()
    add_gate_line(repo, 'workflow')
    (repo / '.githooks').mkdir()
    (repo / HOOK).write_bytes(OWN_HOOK.encode('utf-8'))
    line = refused(repo, '--gate-at', 'hook')
    assert 'set gate: hook' in line and '.githooks/' not in line, line

    repo = scaffolded(tmp_path, 'husky')
    (repo / '.husky').mkdir()
    (repo / '.husky' / 'pre-commit').write_text('npx lint-staged\n', encoding='utf-8')
    commit(repo)
    line = refused(repo, '--gate-at', 'hook')
    assert '.husky/' in line and 'remove it first' not in line, line

    line = refused(empty_repo(tmp_path, 'label'), '--runner-label', '')
    assert '--runner-label' in line and "''" not in line, line


def test_sc017_gate_with_an_answer_adds_the_key_and_writes_only_the_gate(tmp_path):
    """012/FR-001, 012/FR-002: `--gate --gate-at hook` on a manifest without the key."""
    repo = scaffolded(tmp_path)
    (repo / WORKFLOW).unlink()
    before = listing(repo)
    r = scaffold(repo, '--gate', '--gate-at', 'hook')
    assert r.returncode == 0, r.stdout + r.stderr
    after = listing(repo)
    assert manifest_lines(repo)[1] == 'gate: hook'
    assert (repo / HOOK).is_file()
    assert set(after) - set(before) == {'.githooks', HOOK}
    assert {k: v for k, v in after.items() if k in before and k != MANIFEST} == \
        {k: v for k, v in before.items() if k != MANIFEST}


def test_a_label_with_a_line_end_is_refused_on_one_line(tmp_path):
    """012/FR-005: a refusal is one line, also when the label given holds a line end."""
    repo = scaffolded(tmp_path)
    before = listing(repo)
    r = scaffold(repo, '--gate-at', 'runner', '--runner-label=vn\nprod x')
    assert r.returncode == 1 and listing(repo) == before
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == 1 and lines[0].endswith('Nothing was written.') and 'vn\\nprod x' in lines[0], r.stdout


def test_a_manifest_that_is_not_utf8_is_a_refusal(tmp_path):
    """012/FR-001: the line cannot be added to a manifest that is not UTF-8 text; nothing is written, exit 1, not a crash."""
    repo = scaffolded(tmp_path)
    (repo / WORKFLOW).unlink()
    kit = repo / MANIFEST
    kit.write_bytes(kit.read_bytes() + b'# caf\xe9\n')
    before = listing(repo)
    r = scaffold(repo, '--gate-at', 'hook')
    assert r.returncode == 1 and listing(repo) == before, r.stdout + r.stderr
    assert r.stdout.strip().endswith('Nothing was written.') and 'UTF-8' in r.stdout and 'Traceback' not in r.stderr


def test_a_symlinked_hook_under_gate_writes_nothing(tmp_path):
    """012/FR-001, 010/FR-011: the symlink refusal comes before any write, so the manifest is not changed."""
    repo = scaffolded(tmp_path)
    (repo / WORKFLOW).unlink()
    real = tmp_path / 'elsewhere'
    real.write_text('#!/bin/sh\nKIT_REF=v1\n', encoding='utf-8')
    (repo / '.githooks').mkdir()
    try:
        (repo / HOOK).symlink_to(real)
    except OSError as e:
        if getattr(e, 'winerror', None) == 1314:
            import pytest
            pytest.skip('this account cannot create symlinks')
        raise
    before = (repo / MANIFEST).read_bytes()
    r = scaffold(repo, '--gate', '--gate-at', 'hook')
    assert r.returncode == 1 and 'is a symlink' in r.stdout, r.stdout + r.stderr
    assert (repo / MANIFEST).read_bytes() == before and 'update' not in r.stdout
