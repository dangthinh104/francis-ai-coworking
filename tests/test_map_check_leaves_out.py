"""Spec 029: map_check counts no file that its own pinning or a kit bump changed (FR-001 to FR-004)."""
import subprocess
from pathlib import Path

import pytest

from test_kit_gate import commit, git, start_repo
from test_map_has_one_pin import MAP_CHECK, SKILL, k_repo
from test_standard import run

HOOK = '.githooks/pre-push'
WORKFLOW = '.github/workflows/kit-gate.yml'
PRE_PUSH = b'#!/bin/sh\nKIT_REF=v1.0.0\nKIT_COMMIT=' + b'0' * 40 + b'\necho run\n'
KIT_GATE = b'on: pull_request\n          ref: ' + b'0' * 40 + b'  # v1.0.0\nname: x\n'
BUMPED_HOOK = b'#!/bin/sh\nKIT_REF=v1.1.0\nKIT_COMMIT=' + b'1' * 40 + b'\necho run\n'
BUMPED_WORKFLOW = b'on: pull_request\n          ref: ' + b'1' * 40 + b'  # v1.1.0\nname: x\n'


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode('utf-8'))


def put_map(root, pin, *cited):
    put(root / 'docs' / 'ARCHITECTURE.md',
        f'<!-- kit:map revision={pin} -->\n# map\n\n' + ''.join(f'See `{c}`.\n' for c in cited))


def pin_line(result):
    lines = result.stdout.splitlines()
    at = next(i for i, l in enumerate(lines) if l.startswith('pin:'))
    return lines[at], [l for l in lines[at + 1:] if l.startswith('  REVIEW ')]


def counts(n, d, u):
    return f'files changed since: {n}, of which cited by the map: {d} directly, {u} under a cited directory'


def check(root, doc='docs/ARCHITECTURE.md'):
    r = run(MAP_CHECK, root, doc)
    assert r.returncode == 0, r.stdout + r.stderr
    return pin_line(r)


# FR-001: the map and its citation file

@pytest.fixture
def mapped(tmp_path):
    repo = tmp_path / 'r'
    repo.mkdir()
    start_repo(repo)
    put(repo / 'src' / 'a.py', 'x = 1\n')
    put(repo / 'docs' / 'notes.md', 'notes\n')
    put(repo / 'docs' / 'diagrams' / 'map.refs.json', '{}\n')
    c1 = commit(repo)
    put_map(repo, c1, 'src/a.py', 'docs/')
    put(repo / 'docs' / 'diagrams' / 'map.refs.json', '{"pinned": true}\n')
    return repo, c1


def test_sc001_the_map_and_its_citation_file_are_not_counted(mapped):
    """029/FR-001, 029/SC-001."""
    repo, c1 = mapped
    commit(repo)
    for doc in ('docs/ARCHITECTURE.md', './docs/ARCHITECTURE.md', str(repo / 'docs' / 'ARCHITECTURE.md')):
        assert check(repo, doc) == (f'pin: {c1[:8]}, {counts(0, 0, 0)}', []), doc


def test_sc001_another_file_under_the_cited_directory_still_counts(mapped):
    """029/FR-001, 029/SC-001."""
    repo, c1 = mapped
    put(repo / 'docs' / 'notes.md', 'notes, changed\n')
    commit(repo)
    for doc in ('docs/ARCHITECTURE.md', './docs/ARCHITECTURE.md', str(repo / 'docs' / 'ARCHITECTURE.md')):
        assert check(repo, doc) == (f'pin: {c1[:8]}, {counts(1, 0, 1)}', ['  REVIEW docs/notes.md']), doc


def test_sc002_a_document_that_is_not_the_map_counts_itself_as_today(tmp_path):
    """029/SC-002, 023/SC-006."""
    repo, k1 = k_repo(tmp_path / 'k', ('src/main.py', 'docs/'), ('src/main.py', 'docs/a.md', 'docs/b.md', 'README.md'))
    line, _ = check(repo, 'ARCH.md')
    assert line.startswith(f'pin: {k1[:8]}, files changed since: 5,'), line
    assert 'ARCH.md' in git(repo, 'diff', '--name-only', f'{k1}..HEAD').split()


# FR-002 and FR-003: a gate file

@pytest.fixture
def r(tmp_path):
    """SC-003's `R`, pinned at `C1`, its map citing both gate files and committed as `C2`."""
    repo = tmp_path / 'r'
    repo.mkdir()
    start_repo(repo)
    put(repo / 'src' / 'a.py', 'x = 1\n')
    put(repo / 'docs' / 'diagrams' / 'map.refs.json', '{}\n')
    put(repo / HOOK, PRE_PUSH)
    put(repo / WORKFLOW, KIT_GATE)
    c1 = commit(repo)
    put_map(repo, c1, HOOK, WORKFLOW)
    commit(repo)
    return repo, c1


def crlf(data):
    return data.replace(b'\n', b'\r\n')


SC003 = [
    ('the hook bumped', {HOOK: BUMPED_HOOK}, (0, 0, 0)),
    ('the workflow bumped', {WORKFLOW: BUMPED_WORKFLOW}, (0, 0, 0)),
    ('both bumped', {HOOK: BUMPED_HOOK, WORKFLOW: BUMPED_WORKFLOW}, (0, 0, 0)),
    ('a bump and another line', {HOOK: BUMPED_HOOK.replace(b'echo run', b'echo go')}, (1, 1, 0)),
    ('a pin line added', {HOOK: PRE_PUSH.replace(b'echo run\n', b'KIT_REF=v1.1.0\necho run\n')}, (1, 1, 0)),
    ('a pin line removed', {HOOK: b'#!/bin/sh\nKIT_REF=v1.0.0\necho run\n'}, (1, 1, 0)),
    ('two kinds swapped', {HOOK: b'#!/bin/sh\nKIT_COMMIT=' + b'0' * 40 + b'\nKIT_REF=v1.0.0\necho run\n'}, (1, 1, 0)),
    ('a bump in CRLF', {HOOK: crlf(BUMPED_HOOK)}, (1, 1, 0)),
    ('one pin line in CRLF', {HOOK: BUMPED_HOOK.replace(b'KIT_REF=v1.1.0\n', b'KIT_REF=v1.1.0\r\n')}, (1, 1, 0)),
    ('the final line end removed', {HOOK: BUMPED_HOOK[:-1]}, (1, 1, 0)),
]


@pytest.mark.parametrize('case, files, expected', SC003, ids=[c[0] for c in SC003])
def test_sc003_a_gate_file_changed_only_on_its_pin_lines_is_not_counted(r, case, files, expected):
    """029/FR-002, 029/FR-003, 029/SC-003."""
    repo, c1 = r
    for path, data in files.items():
        put(repo / path, data)
    commit(repo)
    line, review = check(repo)
    assert line == f'pin: {c1[:8]}, {counts(*expected)}', line
    assert review == (['  REVIEW .githooks/pre-push'] if expected[1] else []), review


def test_a_gate_file_whose_mode_alone_changed_counts(r):
    """029/FR-003: the texts must differ for a pin-only change; a mode change alone is a change."""
    repo, c1 = r
    git(repo, 'update-index', '--chmod=+x', HOOK)
    git(repo, 'commit', '-q', '-m', 'mode')
    assert check(repo) == (f'pin: {c1[:8]}, {counts(1, 1, 0)}', ['  REVIEW .githooks/pre-push'])


def test_sc004_a_gate_file_added_since_the_pin_counts(tmp_path):
    """029/FR-003, 029/SC-004."""
    repo = tmp_path / 'r'
    repo.mkdir()
    start_repo(repo)
    put(repo / 'src' / 'a.py', 'x = 1\n')
    put(repo / 'docs' / 'diagrams' / 'map.refs.json', '{}\n')
    c1 = commit(repo)
    put_map(repo, c1, 'src/a.py')
    commit(repo)
    put(repo / HOOK, PRE_PUSH)
    put(repo / WORKFLOW, KIT_GATE)
    commit(repo)
    assert check(repo)[0] == f'pin: {c1[:8]}, {counts(2, 0, 0)}'


@pytest.fixture
def r_workflow(tmp_path):
    """`R` of SC-003 with a map that cites only the workflow."""
    repo = tmp_path / 'r'
    repo.mkdir()
    start_repo(repo)
    put(repo / 'src' / 'a.py', 'x = 1\n')
    put(repo / 'docs' / 'diagrams' / 'map.refs.json', '{}\n')
    put(repo / HOOK, PRE_PUSH)
    put(repo / WORKFLOW, KIT_GATE)
    c1 = commit(repo)
    put_map(repo, c1, WORKFLOW)
    commit(repo)
    return repo, c1


def test_sc004_a_gate_file_deleted_since_the_pin_counts(r_workflow):
    """029/FR-003, 029/SC-004."""
    repo, c1 = r_workflow
    (repo / HOOK).unlink()
    commit(repo)
    assert check(repo)[0] == f'pin: {c1[:8]}, {counts(1, 0, 0)}'


def test_sc004_a_gate_file_renamed_since_the_pin_counts_by_its_new_path(r_workflow):
    """029/FR-001, 029/FR-003, 029/SC-004: git names the rename once, by its new path; the map is left out."""
    repo, c1 = r_workflow
    git(repo, 'mv', HOOK, HOOK + '.old')
    commit(repo)
    assert check(repo)[0] == f'pin: {c1[:8]}, {counts(1, 0, 0)}'


def test_sc005_a_hook_under_a_subdirectory_root_is_not_a_gate_file(tmp_path):
    """029/SC-005."""
    repo = tmp_path / 'r'
    repo.mkdir()
    start_repo(repo)
    api = repo / 'api'
    put(api / 'src' / 'a.py', 'x = 1\n')
    put(api / 'docs' / 'diagrams' / 'map.refs.json', '{}\n')
    put(api / HOOK, PRE_PUSH)
    c1 = commit(repo)
    put_map(api, c1, HOOK)
    commit(repo)
    put(api / HOOK, BUMPED_HOOK)
    commit(repo)
    assert check(api) == (f'pin: {c1[:8]}, {counts(1, 1, 0)}', ['  REVIEW .githooks/pre-push'])


def test_sc006_the_skill_says_what_is_not_counted():
    """029/FR-004, 029/SC-006."""
    bullet = next(l for l in SKILL.read_text(encoding='utf-8').splitlines() if l.startswith('- `map_check.py`:'))
    assert 'citation file' in bullet and 'pin lines' in bullet, bullet
    assert "the changed count is the map's own files" not in bullet, bullet
