"""Spec 018: what adoption meets - a gate with no manifest, a monorepo with none, debt in several
entries, tasks that left the list.

Each test builds, under tmp_path, a repository of the spec's success criteria: "an empty throwaway
repository", "the monorepo repository" or "the debt repository". Nothing reaches the network.
"""
import pytest
import hashlib
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts'
SCAFFOLD = SCRIPTS / 'kit_scaffold.py'
DOCTOR = SCRIPTS / 'kit_doctor.py'
STANDARD = REPO / 'plugins' / 'francis-kit' / 'STANDARD.md'
INIT = REPO / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'SKILL.md'
ADOPT = REPO / 'plugins' / 'francis-kit' / 'skills' / 'kit-adopt' / 'SKILL.md'
CHANGELOG = REPO / 'CHANGELOG.md'
FIXTURES = Path(__file__).resolve().parent / 'fixtures' / '018'
WORKFLOW = '.github/workflows/kit-gate.yml'
REFUSED = 'there is no .claude/kit.yml to name the gate: run it without --gate first'
NOTE = ('note: no code markers at the root but found projects in: {}. For a monorepo pass --project-root once per '
        'project, or list the projects in .claude/kit.yml.')
PROVISIONAL = ('provisional: there is no .claude/kit.yml, so the projects judged here are a guess and these verdicts '
               'can change once it lists them')
SEVERAL = ('A rule that names things (S04 to S09, S11, S18, S19) may have several entries, each with its own reason, '
           'fix and names; a name held by two entries is a gap of S01.')
OLDER_GATE = ('A project whose gate pins an older kit writes its gate again (kit_scaffold.py --repo . --gate) before '
              'it records a second entry on a rule: the gate runs the doctor of the version it pins, which reports '
              'that entry as listed twice.')
OLDER_GATE_README = OLDER_GATE.replace('(kit_scaffold.py --repo . --gate)', '(README, "The gate in each project")')


def git(repo, *args):
    r = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, (args, r.stdout + r.stderr)
    return r.stdout


def scaffold(repo, *args):
    """A scaffold run: `python kit_scaffold.py --repo .` at the root of `repo`."""
    return subprocess.run([sys.executable, str(SCAFFOLD), '--repo', '.', *args], cwd=repo, capture_output=True,
                          text=True, encoding='utf-8')


def doctor(repo, *args, all_=True):
    """A doctor run: `python kit_doctor.py --repo . --all` at the root of `repo`."""
    return subprocess.run([sys.executable, str(DOCTOR), '--repo', '.', *(['--all'] if all_ else []), *args],
                          cwd=repo, capture_output=True, text=True, encoding='utf-8')


def empty_repo(tmp_path, name='r'):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, 'init', '-q')
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


def refusal(repo, *args):
    """012's refusal: exit 1, one line ending `Nothing was written.`, no `gh variable set`, nothing
    created or changed. Returns the line."""
    before = listing(repo)
    r = scaffold(repo, *args)
    lines = (r.stdout + r.stderr).splitlines()
    assert r.returncode == 1, (args, r.returncode, lines)
    assert len(lines) == 1 and lines[0].endswith('Nothing was written.'), (args, lines)
    assert not [l for l in lines if 'gh variable set' in l]
    assert listing(repo) == before, args
    return lines[0]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def monorepo(tmp_path):
    repo = empty_repo(tmp_path, 'mono')
    write(repo / 'api' / 'pyproject.toml', '[project]\n')
    return repo


def feature(repo, name, tasks, status='Released'):
    folder = repo / 'specs' / name
    write(folder / 'spec.md', f'# Feature Specification: {name}\n\n**Status**: {status}\n**Ticket**: none\n')
    write(folder / 'plan.md', f'# Plan: {name}\n')
    if isinstance(tasks, bytes):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'tasks.md').write_bytes(tasks)
    else:
        write(folder / 'tasks.md', tasks)


def debt_repo(tmp_path):
    """The debt repository: scaffolded with --profile python, its project named `demo`, the features
    001-a (Released, no checkbox) and 002-b (Released, one open task)."""
    repo = empty_repo(tmp_path, 'debt')
    r = scaffold(repo, '--profile', 'python')
    assert r.returncode == 0, r.stdout + r.stderr
    data = load(repo)
    data['projects'][0]['name'] = 'demo'
    save(repo, data)
    feature(repo, '001-a', 'free text, no box\n')
    feature(repo, '002-b', '- [ ] open\n')
    return repo


def load(repo):
    return yaml.safe_load((repo / '.claude' / 'kit.yml').read_text(encoding='utf-8'))


def save(repo, data):
    write(repo / '.claude' / 'kit.yml', yaml.safe_dump(data, sort_keys=False))


def add_entries(repo, *entries):
    data = load(repo)
    data['projects'][0]['deviations'] += [dict(e) for e in entries]
    save(repo, data)


S09_A = {'rule': 'S09', 'reason': 'r1', 'fix': 'f1', 'features': ['001-a']}
S09_B = {'rule': 'S09', 'reason': 'r2', 'fix': 'f2', 'features': ['002-b']}


def lines_of(r):
    return r.stdout.splitlines()


# SC-001: 018/FR-001, 010/FR-011 as modified

def test_sc001_gate_with_no_manifest_and_no_workflow_file_is_refused(tmp_path):
    repo = empty_repo(tmp_path)
    for args in (('--gate',), ('--gate', '--dry-run')):
        line = refusal(repo, *args)
        assert 'run it without --gate first' in line and REFUSED in line, line
    assert not (repo / WORKFLOW).exists()


def test_sc001_the_kits_hook_does_not_stop_the_refusal(tmp_path):
    repo = empty_repo(tmp_path)
    write(repo / '.githooks' / 'pre-push', '#!/bin/sh\nKIT_REF=v0.14.0\n')
    assert 'run it without --gate first' in refusal(repo, '--gate', '--dry-run')


def test_sc001_a_directory_at_the_workflow_path_is_not_the_workflow_file(tmp_path):
    repo = empty_repo(tmp_path)
    (repo / WORKFLOW).mkdir(parents=True)
    assert 'run it without --gate first' in refusal(repo, '--gate')


def test_sc001_the_refusal_stands_after_settings_and_before_a_path_that_is_not_a_directory(tmp_path):
    repo = empty_repo(tmp_path, 'settings')
    write(repo / '.claude' / 'settings.json', 'nope')
    line = refusal(repo, '--gate')
    assert '.claude/settings.json' in line and 'run it without --gate first' not in line, line
    repo = empty_repo(tmp_path, 'github-file')
    write(repo / '.github', 'a file\n')
    line = refusal(repo, '--gate')
    assert REFUSED in line and 'not a plain directory' not in line, line


def test_sc001_a_first_run_without_gate_still_writes_the_manifest_and_the_workflow(tmp_path):
    repo = empty_repo(tmp_path)
    r = scaffold(repo)
    assert r.returncode == 0 and (repo / WORKFLOW).is_file() and (repo / '.claude' / 'kit.yml').is_file(), r.stdout


# SC-002: 018/FR-002

def test_sc002_the_doctor_says_the_monorepo_note_above_repository(tmp_path):
    repo = monorepo(tmp_path)
    lines = lines_of(doctor(repo))
    note = NOTE.format('api')
    assert note in lines and lines.index(note) < lines.index('repository'), lines

    write(repo / 'api' / 'requirements.txt', 'x\n')
    write(repo / 'web' / 'artisan', '')
    lines = lines_of(doctor(repo))
    assert NOTE.format('api, web') in lines and lines.index(NOTE.format('api, web')) < lines.index('repository'), lines
    said = scaffold(repo, '--dry-run').stdout
    assert 'found projects in: api, api, web.' in said, said           # the scaffold's own note, unchanged

    r = doctor(repo, '--project-root', 'api')
    assert not [l for l in (r.stdout + r.stderr).splitlines() if 'no code markers' in l], r.stdout


def test_sc002_roots_and_lint_features_gain_no_line(tmp_path):
    repo = monorepo(tmp_path)
    r = doctor(repo, '--roots', all_=False)
    assert r.returncode == 0 and r.stdout.splitlines() == ['.'], r.stdout
    r = doctor(repo, '--lint-features', '.', all_=False)
    assert r.returncode == 0 and r.stdout == '' and 'no code markers' not in r.stderr, (r.stdout, r.stderr)


def test_sc002_a_root_with_a_code_marker_gets_no_note(tmp_path):
    repo = monorepo(tmp_path)
    write(repo / 'pyproject.toml', '[project]\n')
    assert 'no code markers' not in doctor(repo).stdout


# SC-003: 018/FR-003

def test_sc003_with_no_manifest_the_verdict_is_provisional(tmp_path):
    repo = monorepo(tmp_path)
    r = doctor(repo)
    lines = lines_of(r)
    at = [i for i, l in enumerate(lines) if l.startswith('summary:')]
    assert r.returncode == 1 and len(at) == 1 and lines[at[0] + 1] == PROVISIONAL, lines
    r = doctor(repo, '--project-root', 'api')
    lines = lines_of(r)
    assert r.returncode == 1 and PROVISIONAL in lines, lines


def test_sc003_with_a_manifest_nothing_is_provisional(tmp_path):
    r = doctor(debt_repo(tmp_path))
    assert not [l for l in lines_of(r) if l.startswith('provisional:')], r.stdout


# SC-004: 018/FR-004, 018/FR-006, 018/FR-007

def test_sc004_two_entries_on_s09_are_debt_each_with_its_fix(tmp_path):
    repo = debt_repo(tmp_path)
    add_entries(repo, S09_A, S09_B)
    lines = lines_of(doctor(repo))
    assert not [l for l in lines if 'GAP  S01' in l and 'S09' in l], lines
    assert not [l for l in lines if 'GAP  S09' in l], lines
    debt = [i for i, l in enumerate(lines) if 'DEBT S09' in l]
    assert debt, lines
    below = lines[debt[-1] + 1:]
    f1 = [i for i, l in enumerate(below) if 'fix (from .claude/kit.yml): f1' in l]     # 019/FR-005
    f2 = [i for i, l in enumerate(below) if 'fix (from .claude/kit.yml): f2' in l]
    assert f1 and f2 and f1[0] < f2[0], lines


def test_sc004_each_entry_is_judged_as_one(tmp_path):
    repo = debt_repo(tmp_path)
    add_entries(repo, S09_A, {k: v for k, v in S09_B.items() if k != 'fix'})
    lines = [l.strip() for l in lines_of(doctor(repo))]
    assert [l for l in lines if l.startswith('GAP  S01 demo: deviation S09 has no') and 'fix' in l], lines


# SC-005: 018/FR-005

def test_sc005_a_name_in_two_entries_is_a_gap_of_s01(tmp_path):
    repo = debt_repo(tmp_path)
    add_entries(repo, S09_A, dict(S09_B, features=['001-a', '002-b']))
    lines = [l.strip() for l in lines_of(doctor(repo))]
    assert 'GAP  S01 demo: deviation S09 lists 001-a in more than one entry' in lines, lines
    assert not [l for l in lines if '002-b in more than one entry' in l], lines


def test_sc005_s19_names_are_compared_with_their_spaces_made_one(tmp_path):
    repo = debt_repo(tmp_path)
    add_entries(repo, {'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': ['python  -m pytest -q']})
    lines = lines_of(doctor(repo))
    assert [l for l in lines if 'deviation S19 lists' in l and 'in more than one entry' in l], lines


def test_sc005_a_rule_that_names_nothing_is_still_listed_once(tmp_path):
    repo = debt_repo(tmp_path)
    add_entries(repo, {'rule': 'S12', 'reason': 'r', 'fix': 'f'})
    lines = [l.strip() for l in lines_of(doctor(repo))]
    assert 'GAP  S01 demo: deviation S12 is listed twice' in lines, lines


def test_sc005_the_top_level_list_reads_several_entries_too(tmp_path):
    repo = debt_repo(tmp_path)
    data = load(repo)
    first = data['projects'][0]
    data['projects'] = [dict(first, name='one', root='one', deviations=[]),
                        dict(first, name='two', root='two', deviations=[])]
    (repo / 'one').mkdir()
    (repo / 'two').mkdir()
    write(repo / 'CLAUDE.md', '# x\n' * 200)
    data['deviations'] = [{'rule': 'S02', 'reason': 'r', 'fix': 'f'}, {'rule': 'S02', 'reason': 'r', 'fix': 'g'},
                          {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['a']},
                          {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['a', 'b']}]
    save(repo, data)
    lines = [l.strip() for l in lines_of(doctor(repo))]
    assert 'GAP  S01 repository: deviation S02 is listed twice' in lines, lines
    assert 'GAP  S01 repository: deviation S18 lists a in more than one entry' in lines, lines
    assert not [l for l in lines if 'S18 is listed twice' in l], lines


# SC-006: 018/FR-006, 003/FR-009 as modified

def test_sc006_lint_features_leaves_out_the_features_of_every_entry(tmp_path):
    repo = debt_repo(tmp_path)
    add_entries(repo, S09_A, S09_B)
    r = doctor(repo, '--lint-features', '.', all_=False)
    assert r.returncode == 0, r.stderr
    assert '001-a' not in r.stdout.splitlines() and '002-b' not in r.stdout.splitlines(), r.stdout
    assert '001-a' in r.stderr and '002-b' in r.stderr, r.stderr


def test_sc006_a_name_that_conforms_now_is_a_gap_in_any_entry(tmp_path):
    repo = debt_repo(tmp_path)
    feature(repo, '003-c', '- [x] done\n')
    add_entries(repo, S09_A, dict(S09_B, features=['002-b', '003-c']))
    lines = lines_of(doctor(repo))
    assert [l for l in lines if 'listed under the deviation but conforming now, remove: 003-c' in l], lines


def test_sc006_s19_reads_every_entry_for_names_no_test_entry_holds(tmp_path):
    """004/FR-011 as modified: an S19 name of a second entry that no `test` entry is, is a gap."""
    repo = debt_repo(tmp_path)
    add_entries(repo, S09_A, S09_B, {'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': ['make check']})
    data = load(repo)
    data['projects'][0]['release'] = {'pr_target': 'main', 'deploy_branches': []}     # S19 is judged
    save(repo, data)
    lines = lines_of(doctor(repo))
    assert [l for l in lines if 'GAP  S19 listed under the deviation but no' in l and "'make check'" in l], lines


# SC-007: 018/FR-008

def one_line(lines, start):
    found = [l for l in lines if l.startswith(start)]
    assert len(found) == 1, (start, found)
    return found[0]


def test_sc007_several_entries_are_said_in_the_four_places():
    standard = STANDARD.read_text(encoding='utf-8').splitlines()
    paragraph = one_line(standard, 'Where a project cannot conform yet')
    assert SEVERAL in paragraph
    assert SEVERAL in one_line(standard, '| S01 |')
    assert SEVERAL in one_line(INIT.read_text(encoding='utf-8').splitlines(), '| `deviations` |')
    assert SEVERAL in one_line(ADOPT.read_text(encoding='utf-8').splitlines(), '6. ')


# SC-008: 018/FR-009

def unreleased():
    lines = CHANGELOG.read_text(encoding='utf-8').splitlines()
    start = lines.index('## Unreleased')
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith('## 0.14.0'))   # the line moves under its release
    return lines[start + 1:end]


@pytest.mark.private
def test_sc008_the_changelog_says_to_write_the_gate_again_first():
    assert [l for l in unreleased() if OLDER_GATE in l]


def test_sc008_kit_adopt_step_6_says_to_write_the_gate_again_first():
    """In kit-adopt the sentence names the README's step, not the command 012/SC-013 forbids there."""
    assert OLDER_GATE_README in one_line(ADOPT.read_text(encoding='utf-8').splitlines(), '6. ')


# SC-009: 018/FR-010, 018/FR-011

def test_sc009_row_s09_names_the_two_ways_a_task_leaves_the_list():
    row = one_line(STANDARD.read_text(encoding='utf-8').splitlines(), '| S09 |')
    for words in ('no checkbox', 'Not done', 'no longer open', '## Moved out', 'its own spec', 'at least one checkbox'):
        assert words in row, words
    row = one_line(ADOPT.read_text(encoding='utf-8').splitlines(), '| S09 |')
    assert 'Not done' in row and 'Moved out' in row, row


# SC-010: 018/FR-010, the doctor unchanged

STOCK = {'003-feature-a': '13b998ca4ea5039c4422926f0cb3907963ef22f06d9b34e7d65e7c9e2afc823d',
         '033-feature-b': '386f5830b18e187ce9766bcbfb3a2624955ed2f5d5abd574b3b3f57ea5a6dd9c'}


def stock_tasks(name):
    """stock-service's tasks.md, byte for byte."""
    body = (FIXTURES / f'{name}-tasks.md').read_bytes()
    assert hashlib.sha256(body).hexdigest() == STOCK[name], name
    return body


@pytest.mark.private
def test_sc010_tasks_that_left_the_list_pass_s09(tmp_path):
    repo = debt_repo(tmp_path)
    for name in ('001-a', '002-b'):
        for f in (repo / 'specs' / name).iterdir():
            f.unlink()
        (repo / 'specs' / name).rmdir()
    for name in STOCK:
        feature(repo, name, stock_tasks(name))
    lines = [l.strip() for l in lines_of(doctor(repo))]
    assert 'PASS S09 (tasks as checkboxes, none open after release)' in lines, lines

    moved = stock_tasks('033-feature-b').replace(b'\n- C1 \xe2\x80\x94 ', b'\n- [ ] C1 \xe2\x80\x94 ', 1)
    assert moved != stock_tasks('033-feature-b')
    (repo / 'specs' / '033-feature-b' / 'tasks.md').write_bytes(moved)
    lines = [l.strip() for l in lines_of(doctor(repo))]
    assert [l for l in lines if l.startswith('GAP  S09 Released or Closed with open tasks')
            and '033-feature-b' in l], lines


def test_sc010_a_tasks_md_with_no_checkbox_at_all_is_still_a_gap(tmp_path):
    repo = debt_repo(tmp_path)
    feature(repo, '003-c', '## Moved out\n\nMoved out: each needs its own spec.\n\n- one\n')
    lines = lines_of(doctor(repo))
    assert [l for l in lines if 'tasks.md without' in l and 'checkboxes' in l and '003-c' in l], lines
