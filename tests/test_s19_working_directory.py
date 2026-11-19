"""Spec 014: a tool's own directory option counts as the directory a test runs in (rule S19).

Each test builds, under tmp_path, the repository of the spec's success criteria: `git init` with
no commit, a manifest of one project `stock` at the git root, and a `ci.yml` of two jobs that
run stock-service's tests under `working-directory`.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
DOCTOR = REPO / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_doctor.py'

UV = 'uv --directory py_app run python -m pytest -q'
GO = 'go -C go-app test ./...'
PY_RUN = 'uv run python -m pytest -q'
GO_RUN = 'go test ./...'
SENTENCE = ('An entry is matched word for word, the path of uv --directory, go -C or make -C written directly after '
            'the program read as the directory the tool runs in, so a step that runs the same tool written another '
            'way does not count: write the entry as CI runs it, or the step as the manifest says')


def project(name='stock', root='.', test=(UV, GO), deviations=()):
    return {'name': name, 'root': root, 'setup': [], 'test': list(test), 'lint': [], 'audit': [], 'ci_only': [],
            'release': {'pr_target': 'main', 'deploy_branches': []}, 'deviations': list(deviations)}


def step(run, wd=None, **keys):
    out = {'run': run}
    if wd is not None:
        out['working-directory'] = wd
    out.update(keys)
    return out


PY_STEPS = [{'uses': 'actions/checkout@v4'}, step(PY_RUN, 'py_app')]
GO_STEPS = [step(GO_RUN, 'go-app')]


def stock(tmp_path, test=(UV, GO), py=None, go=None, projects=None, top=None, jobs=None, files=None):
    """The repository of the success criteria; each argument changes one thing of it."""
    repo = tmp_path / 'stock'
    (repo / '.claude').mkdir(parents=True)
    (repo / '.github' / 'workflows').mkdir(parents=True)
    for folder in ('py_app', 'go-app'):
        (repo / folder).mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    data = {'version': 2, 'projects': projects or [project(test=test)], 'scratch': []}
    (repo / '.claude' / 'kit.yml').write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    if jobs is None:
        jobs = {'py': {'runs-on': 'ubuntu-latest', 'steps': PY_STEPS if py is None else py},
                'go': {'runs-on': 'ubuntu-latest', 'steps': GO_STEPS if go is None else go}}
    ci = {'on': {'pull_request': {'branches': ['main']}}, **(top or {}), 'jobs': jobs}
    (repo / '.github' / 'workflows' / 'ci.yml').write_text(yaml.safe_dump(ci, sort_keys=False), encoding='utf-8')
    for name, body in (files or {}).items():
        (repo / '.github' / 'workflows' / name).write_text(yaml.safe_dump(body, sort_keys=False), encoding='utf-8')
    return repo


def doctor(repo):
    r = subprocess.run([sys.executable, str(DOCTOR), '--repo', str(repo), '--all'],
                       capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 1, r.stdout + r.stderr          # gaps on other rules: a verdict, not a crash
    return r.stdout


VERDICT = re.compile(r'^\s*(PASS|GAP|DEBT|SKIP)\s')


def gap(out):
    """From the line that holds `GAP  S19` to the next line that holds a verdict, a project or `summary:`."""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if 'GAP  S19' in line:
            block = [line]
            for more in lines[i + 1:]:
                if VERDICT.match(more) or more.startswith('project') or 'summary:' in more:
                    break
                block.append(more)
            return '\n'.join(block)
    return ''


def passes(out):
    return 'PASS S19' in out and not gap(out)


def by_project(out):
    found, name = {}, None
    for line in out.splitlines():
        if line.startswith('project '):
            name = line.split()[1]
        elif name and line.split()[1:2] == ['S19']:
            found[name] = line.split()[0]
    return found


# One test per success criterion.

def test_sc001_stock_service_as_it_stands_passes(tmp_path):
    """014/FR-001, SC-001: the two steps under `working-directory` prove the two entries."""
    out = doctor(stock(tmp_path))
    assert passes(out), out


def test_sc002_a_project_in_a_subdirectory_proved_from_the_git_root(tmp_path):
    """014/FR-002, 014/FR-003, SC-002."""
    projects = [project('py', 'py_app', [PY_RUN]), project('go', 'go-app', [GO_RUN])]
    out = doctor(stock(tmp_path / 'a', projects=projects, py=[step(UV)], go=[step(GO)]))
    assert by_project(out) == {'py': 'PASS', 'go': 'PASS'}, out
    out = doctor(stock(tmp_path / 'b', projects=projects, top={'defaults': {'run': {'working-directory': 'py_app'}}},
                       py=[step(PY_RUN)], go=[step('go -C ../go-app test ./...')]))
    assert by_project(out) == {'py': 'PASS', 'go': 'PASS'}, out


def test_sc003_two_options_name_the_same_directory_whatever_they_write(tmp_path):
    """014/FR-003, 014/FR-008, 014/FR-001, SC-003."""
    entry = 'uv --directory ./py_app/ run python -m pytest -q'
    out = doctor(stock(tmp_path / 'a', test=(entry, GO), py=[step('uv --directory ../py_app run python -m pytest -q', 'go-app')]))
    assert passes(out), out
    out = doctor(stock(tmp_path / 'b', test=(entry, GO), py=[step('uv --directory ../go-app run python -m pytest -q', 'go-app')]))
    assert f"has '{entry}' in go-app" in gap(out), out
    out = doctor(stock(tmp_path / 'c', py=[step('CI=1 uv run python -m pytest -q', 'py_app')]))
    assert passes(out), out


def test_sc004_the_gap_names_the_directory_the_step_runs_in(tmp_path):
    """014/FR-008, SC-004."""
    out = doctor(stock(tmp_path / 'a', go=[step(GO_RUN)]))
    assert f"ci.yml job go step 1 has '{GO}' at the git root" in gap(out), out
    out = doctor(stock(tmp_path / 'b', go=[step(GO_RUN, 'py_app')]))
    assert f"ci.yml job go step 1 has '{GO}' in py_app" in gap(out), out
    out = doctor(stock(tmp_path / 'c', test=(UV, GO_RUN)))
    assert "'go test ./...'" in gap(out) and 'in go-app' in gap(out), out


@pytest.mark.parametrize('entry', [
    'uv --directory $DIR run python -m pytest -q',
    'uv --directory ${{ env.D }} run python -m pytest -q',
    'go -C ~/go-app test ./...',
    'go -C /go-app test ./...',
    'uv --directory ../elsewhere run python -m pytest -q',
])
def test_sc005_a_path_a_cd_would_not_take_is_read_word_for_word(tmp_path, entry):
    """014/FR-004, SC-005."""
    test = (entry, GO) if entry.startswith('uv') else (UV, entry)
    py = [step(PY_RUN)] if '../elsewhere' in entry else None          # the step at the git root
    out = doctor(stock(tmp_path, test=test, py=py))
    assert repr(entry) in gap(out), out


@pytest.mark.parametrize('entry', ['uv --directory $DIR run python -m pytest -q',
                                   'uv --directory ../elsewhere run python -m pytest -q'])
def test_sc005_the_entry_s_own_words_at_the_git_root_still_prove_it(tmp_path, entry):
    """014/FR-004, SC-005: as at 331bc29."""
    out = doctor(stock(tmp_path, test=(entry, GO), py=[step(entry)]))
    assert passes(out), out


@pytest.mark.parametrize('entry,go', [
    ('uv --project py_app run python -m pytest -q', None),
    ('uv --directory=py_app run python -m pytest -q', None),
    ('uv run --directory py_app python -m pytest -q', None),
    ('go -Cgo-app test ./...', 'go'),
])
def test_sc006_an_option_written_another_way_is_read_word_for_word(tmp_path, entry, go):
    """014/FR-005, SC-006."""
    test = (UV, entry) if go else (entry, GO)
    out = doctor(stock(tmp_path, test=test))
    assert repr(entry) in gap(out), out


def test_sc007_an_entry_of_several_commands_is_matched_as_today(tmp_path):
    """014/FR-006, SC-007."""
    entry = 'cd go-app && go test ./...'
    out = doctor(stock(tmp_path / 'a', test=(UV, entry)))
    assert repr(entry) in gap(out), out
    out = doctor(stock(tmp_path / 'b', test=(UV, entry), go=[step(entry)]))
    assert passes(out), out
    entry = 'go -C go-app vet ./... && go -C go-app test ./...'
    out = doctor(stock(tmp_path / 'c', test=(UV, entry), go=[step('go vet ./... && go test ./...', 'go-app')]))
    assert repr(entry) in gap(out), out


def test_sc008_a_step_of_a_called_workflow_proves_the_entry(tmp_path):
    """014/FR-001, 006/FR-001, SC-008."""
    called = {'on': 'workflow_call', 'jobs': {'unit': {'runs-on': 'ubuntu-latest', 'steps': [step(PY_RUN, 'py_app')]}}}
    jobs = {'py': {'uses': './.github/workflows/py-tests.yml'},
            'go': {'runs-on': 'ubuntu-latest', 'steps': GO_STEPS}}
    out = doctor(stock(tmp_path, jobs=jobs, files={'py-tests.yml': called}))
    assert passes(out), out


def test_sc009_the_recorded_debt_is_asked_back(tmp_path):
    """014/FR-001, 004/FR-011, SC-009."""
    debt = {'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [UV, GO]}
    out = doctor(stock(tmp_path, projects=[project(deviations=[debt])]))
    assert 'GAP  S19 listed under deviations but conforms now: remove the entry' in out, out


def test_sc010_the_gap_says_which_options_are_read(tmp_path):
    """014/FR-009, SC-010."""
    block = gap(doctor(stock(tmp_path, go=[step('cargo test')])))
    assert SENTENCE in block and 'An entry is matched word for word, so a step' not in block, block


def section(text, heading):
    """The lines under a Markdown heading, up to the next heading of the same or a higher level."""
    lines, out, level = text.splitlines(), [], None
    for line in lines:
        hashes = len(line) - len(line.lstrip('#'))
        if level is None:
            if line.startswith('#') and line.lstrip('#').strip() == heading:
                level = hashes
            continue
        if line.startswith('#') and 0 < hashes <= level:
            break
        out.append(line)
    assert level is not None, heading
    return out


def s19_rows(path):
    return [l for l in (REPO / path).read_text(encoding='utf-8').splitlines() if l.startswith('| S19 ')]


@pytest.mark.private
def test_sc011_the_documents_name_the_options_that_count():
    """014/FR-010, 014/FR-011, SC-011."""
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')     # the line moves under its release
    places = {
        'STANDARD.md': s19_rows('plugins/francis-kit/STANDARD.md'),
        'README.md': [l for l in section(readme, 'Known limits') if 'S19' in l],
        'kit-adopt': s19_rows('plugins/francis-kit/skills/kit-adopt/SKILL.md'),
        'CHANGELOG.md': changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.12.0')].splitlines(),
    }
    for name, lines in places.items():
        for option in ('uv --directory', 'go -C', 'make -C'):
            assert any(option in l for l in lines), (name, option)
        if name != 'CHANGELOG.md':
            holding = [l for l in lines if 'uv --directory' in l]
            assert holding and all('uv --project' in l and 'cd X &&' in l for l in holding), name
    assert any('a backslash in the path of a `cd` or of a directory option' in l for l in places['README.md'])


def test_sc012_the_entry_keeps_its_assignments(tmp_path):
    """014/FR-001, SC-012."""
    entry = 'CI=1 ' + UV
    out = doctor(stock(tmp_path, test=(entry, GO)))
    assert repr(entry) in gap(out), out


def test_sc013_a_plain_cd_on_its_own_line_moves_the_step(tmp_path):
    """014/FR-001, 004/FR-006, SC-013."""
    out = doctor(stock(tmp_path, go=[step('cd go-app\ngo test ./...\n')]))
    assert passes(out), out


def test_sc014_make_c_counts_and_needs_a_word_after_its_path(tmp_path):
    """014/FR-001, 014/FR-004, SC-014."""
    out = doctor(stock(tmp_path / 'a', test=(UV, 'make -C go-app test'), go=[step('make test', 'go-app')]))
    assert passes(out), out
    out = doctor(stock(tmp_path / 'b', test=(UV, 'make -C go-app'), go=[step('make', 'go-app')]))
    assert "'make -C go-app'" in gap(out), out


def test_sc015_a_step_whose_option_names_the_root_proves_a_root_entry(tmp_path):
    """014/FR-007, SC-015."""
    out = doctor(stock(tmp_path, test=(UV, GO_RUN), go=[step('go -C .. test ./...', 'go-app')]))
    assert passes(out), out


def test_sc016_continue_on_error_is_said_alone(tmp_path):
    """014/FR-008, SC-016."""
    block = gap(doctor(stock(tmp_path, go=[step(GO_RUN, **{'continue-on-error': True})])))
    assert f"has '{GO}' under `continue-on-error`" in block and 'at the git root' not in block, block


# The requirements' own examples that no success criterion holds.

def test_fr006_a_cd_entry_is_not_proved_under_working_directory(tmp_path):
    """014/FR-006, 014/FR-011: `cd X && ...` is matched word for word."""
    out = doctor(stock(tmp_path / 'a', test=(UV, 'cd go-app && go test ./...')))
    assert "'cd go-app && go test ./...'" in gap(out), out


def test_fr002_a_step_at_the_git_root_proves_a_project_in_its_option_s_directory(tmp_path):
    """014/FR-002: the root of the Go project set to go-app."""
    projects = [project('go', 'go-app', [GO_RUN])]
    out = doctor(stock(tmp_path, projects=projects, py=[], go=[step(GO)]))
    assert by_project(out) == {'go': 'PASS'}, out


def test_fr003_both_options_name_another_directory(tmp_path):
    """014/FR-003: the option on each side, through `..`, naming different directories."""
    out = doctor(stock(tmp_path, py=[step('uv --directory ../py_app/sub run python -m pytest -q', 'go-app')]))
    assert f"has '{UV}' in py_app/sub" in gap(out), out


def test_fr004_the_entry_out_of_the_repository_is_not_proved_from_its_parent(tmp_path):
    """014/FR-004: `../elsewhere` names no directory; a step that runs `uv run` there is no proof."""
    entry = 'uv --directory ../elsewhere run python -m pytest -q'
    out = doctor(stock(tmp_path, test=(entry, GO), py=[step(PY_RUN, 'elsewhere')]))
    assert repr(entry) in gap(out), out


def test_fr007_a_root_entry_is_not_proved_in_a_subdirectory(tmp_path):
    """014/FR-007."""
    out = doctor(stock(tmp_path, test=(PY_RUN, GO)))
    assert f"has '{PY_RUN}' in py_app" in gap(out), out


def test_fr008_followed_by_and_is_said_alone(tmp_path):
    """014/FR-008: `&&` comes before the directory."""
    block = gap(doctor(stock(tmp_path, go=[step(GO_RUN + ' && echo ok')])))
    assert 'followed by `&&`' in block and 'at the git root' not in block, block


# Shapes read word for word: a false pass is worse than a false gap.

@pytest.mark.parametrize('entry', [
    'uv --directory py_app --directory py_app run python -m pytest -q',   # repeated: the second is words
    'uv run --directory py_app python -m pytest -q',                           # after the subcommand
    'uv --no-cache --directory py_app run python -m pytest -q',                # after another option
    'uv --directory=py_app run python -m pytest -q',
    'uv --directory ../py_app run python -m pytest -q',                        # out of the repository
    'uv --directory ${{ env.D }} run python -m pytest -q',
    'uv --directory $D run python -m pytest -q',
    'uv --directory "$D" run python -m pytest -q',
    'uv --directory `pwd` run python -m pytest -q',
    'uv --directory py_* run python -m pytest -q',
    'uv --directory C:/py_app run python -m pytest -q',
    'uv --directory -x run python -m pytest -q',
    'uv --directory "py"_app run python -m pytest -q',
    'uv --project py_app run python -m pytest -q',
    'npm --prefix py_app run python -m pytest -q',
    'pnpm -C py_app run python -m pytest -q',
    'uv -C py_app run python -m pytest -q',
    'python -m uv --directory py_app run python -m pytest -q',
    './uv --directory py_app run python -m pytest -q',
])
def test_an_entry_that_carries_no_option_is_not_proved_under_working_directory(tmp_path, entry):
    """014/FR-004, 014/FR-005: the step `uv run python -m pytest -q` under py_app proves none of these."""
    out = doctor(stock(tmp_path, test=(entry, GO)))
    assert repr(entry) in gap(out), out


@pytest.mark.parametrize('entry', [
    'make --directory go-app test', 'make --directory=go-app test', 'make -Cgo-app test',
    'make test -C go-app', 'make -s -C go-app test', 'go test -C go-app ./...', 'go -C=go-app test ./...',
    'go --C go-app test ./...', 'git -C go-app test ./...',
])
def test_other_forms_of_go_and_make_are_read_word_for_word(tmp_path, entry):
    """014/FR-005: `make test` and `go test ./...` under go-app prove none of these."""
    go = [step('make test', 'go-app'), step(GO_RUN, 'go-app'), step('git test ./...', 'go-app')]
    out = doctor(stock(tmp_path, test=(UV, entry), go=go))
    assert repr(entry) in gap(out), out


@pytest.mark.parametrize('run', [
    'uv --directory=. run python -m pytest -q',
    'uv run --directory . python -m pytest -q',
    'uv --directory ../.. run python -m pytest -q',              # out of the repository
    'uv --directory $D run python -m pytest -q',
    'uv --directory "$D" run python -m pytest -q',
    'uv --project . run python -m pytest -q',
    'npm --prefix . run python -m pytest -q',
    'pnpm -C . run python -m pytest -q',
    'uv --directory . --directory x run python -m pytest -q',   # repeated: the second is words
])
def test_a_step_that_carries_no_option_is_read_word_for_word(tmp_path, run):
    """014/FR-004, 014/FR-005, on the step's side: none of these under py_app proves the entry."""
    out = doctor(stock(tmp_path, py=[step(run, 'py_app')]))
    assert repr(UV) in gap(out), out


def test_a_step_with_assignments_proves_an_entry_without(tmp_path):
    """014/FR-001, 014/FR-002: only the step's assignments are left out."""
    out = doctor(stock(tmp_path / 'a', py=[step('CI=1 FOO=2 uv run python -m pytest -q', 'py_app')]))
    assert passes(out), out
    projects = [project('py', 'py_app', [PY_RUN])]
    out = doctor(stock(tmp_path / 'b', projects=projects, py=[step('CI=1 ' + UV)], go=[]))
    assert by_project(out) == {'py': 'PASS'}, out
    projects = [project('py', 'py_app', ['CI=1 ' + PY_RUN])]
    out = doctor(stock(tmp_path / 'c', projects=projects, py=[step(UV)], go=[]))
    assert by_project(out) == {'py': 'GAP'}, out
    out = doctor(stock(tmp_path / 'd', projects=projects, py=[step('CI=1 ' + UV)], go=[]))
    assert by_project(out) == {'py': 'PASS'}, out


def test_one_pair_of_quotes_around_the_path_is_taken_off(tmp_path):
    """014 definitions: as for a plain `cd`."""
    out = doctor(stock(tmp_path / 'a', test=('uv --directory "py_app" run python -m pytest -q', GO)))
    assert passes(out), out
    out = doctor(stock(tmp_path / 'b', test=(UV, "go -C 'go-app' test ./...")))
    assert passes(out), out


def test_a_backslash_in_the_path_is_read_as_a_cd_reads_it(tmp_path):
    """014/FR-010: as for a `cd`, a backslash is read as `/`; README names it among the ways S19 can be fooled."""
    out = doctor(stock(tmp_path, test=('uv --directory .\\py_app run python -m pytest -q', GO)))
    assert passes(out), out


@pytest.mark.parametrize('path', ['.<py_app/../go-app', 'go-app>x', 'go-app|x', 'go-app&x', 'go-app;x',
                                  '(go-app)'])
def test_a_shell_operator_in_the_path_is_not_read_as_a_directory(tmp_path, path):
    """004/FR-006 (F001): bash runs `go -C .<a/../go-app` in the root, reading `<a/..` as a redirection; a path
    holding a shell operator names no directory the doctor can know, for the option as for a `cd`."""
    out = doctor(stock(tmp_path, go=[step(f'go -C {path} test ./...')]))
    assert repr(GO) in gap(out), out
    out = doctor(stock(tmp_path / 'cd', go=[step(f'cd {path}\ngo test ./...\n')]))
    assert repr(GO) in gap(out), out


def test_a_step_under_continue_on_error_with_the_option_does_not_count(tmp_path):
    """014/FR-001, 004/FR-004 holding."""
    out = doctor(stock(tmp_path, py=[step(PY_RUN, 'py_app', **{'if': False})]))
    assert f"has '{UV}' under `if: false`" in gap(out), out


def test_a_line_that_is_not_plain_still_ends_the_reading(tmp_path):
    """014/FR-001, 004/FR-005 holding: the option does not make a line plain."""
    out = doctor(stock(tmp_path, py=[step('uv run python -m pytest -q || true', 'py_app')]))
    assert repr(UV) in gap(out), out


def test_a_directory_option_in_a_cd_line_does_not_move_the_lines_after_it(tmp_path):
    """014: only `cd` moves the lines after it; `make -C` runs and comes back."""
    out = doctor(stock(tmp_path, test=(UV, GO_RUN), go=[step('make -C go-app build\ngo test ./...\n')]))
    assert passes(out), out
