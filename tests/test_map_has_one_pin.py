"""Spec 023: a map pin behind its citations is named, and the review count says what was cited directly."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_kit_gate import commit, gate, git, make_p, start_repo, write
from test_standard import DOCTOR, run
import test_standard

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills' / 'map-project'
CITE_REFS = KIT / 'scripts' / 'cite_refs.py'
MAP_CHECK = KIT / 'scripts' / 'map_check.py'
SKILL = KIT / 'SKILL.md'
SUMMARY = 'summary: 12 pass, 0 gap, 0 debt, 7 skipped'
TAIL = ': read the REVIEW list of map_check.py, then set line 1 of the map (map-project, Refresh step 4)'


@pytest.fixture
def p(tmp_path):
    return make_p(tmp_path / 'p')


def head(repo):
    return git(repo, 'rev-parse', 'HEAD').strip()


def notes(result):
    return [l for l in result.stderr.splitlines() if l.startswith('note: S13:')]


def doctor(repo):
    return run(DOCTOR, '--repo', repo)


def fix(repo):
    """The fix of 023: `cite_refs.py --diagrams docs/diagrams --root . --fix`, run at the root of the project."""
    return subprocess.run([sys.executable, str(CITE_REFS), '--diagrams', 'docs/diagrams', '--root', '.', '--fix'],
                          cwd=repo, capture_output=True, text=True, encoding='utf-8')


def set_map_pin(repo, pin):
    path = repo / 'docs' / 'ARCHITECTURE.md'
    rest = path.read_text(encoding='utf-8').split('\n', 1)[1]
    write(path, f'<!-- kit:map revision={pin} -->\n{rest}')
    return commit(repo)


def json_pin(repo):
    data = json.loads((repo / 'docs' / 'diagrams' / 'map.refs.json').read_text(encoding='utf-8'))
    return data['meta']['repository']['revision']


def test_sc001_equal_pins_print_no_note(p):
    """023/FR-003, 023/SC-001."""
    r = doctor(p)
    assert r.returncode == 0 and SUMMARY in r.stdout, r.stdout + r.stderr
    assert notes(r) == []


def test_sc002_a_fix_that_leaves_the_map_behind_says_so_and_the_doctor_notes_it(p):
    """023/FR-001, 023/FR-002, 023/FR-003, 023/SC-002."""
    c1 = json_pin(p)
    claude = p / 'CLAUDE.md'
    write(claude, '# note\n' + claude.read_text(encoding='utf-8'))
    c3 = commit(p)
    before = (p / 'docs' / 'ARCHITECTURE.md').read_bytes()
    r = fix(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json_pin(p) == c3
    assert (p / 'docs' / 'ARCHITECTURE.md').read_bytes() == before
    assert r.stdout.splitlines()[-1] == (f'map pin: docs/ARCHITECTURE.md is at {c1[:8]}, '
                                         f'behind map.refs.json at {c3[:8]}' + TAIL)
    c4 = commit(p)
    d = doctor(p)
    assert d.returncode == 0 and SUMMARY in d.stdout, d.stdout + d.stderr
    assert notes(d) == [f'note: S13: docs/ARCHITECTURE.md is pinned to {c1[:8]}, '
                        f'behind map.refs.json at {c3[:8]}' + TAIL]
    set_map_pin(p, c4)
    assert notes(doctor(p)) == []
    set_map_pin(p, c3)
    assert notes(doctor(p)) == []


def test_sc003_a_map_pin_ahead_is_no_note_and_a_fix_past_it_is_named(p):
    """023/FR-001, 023/FR-003, 023/SC-003."""
    c2 = head(p)
    set_map_pin(p, c2)
    d = doctor(p)
    assert d.returncode == 0 and notes(d) == [], d.stderr
    r = fix(p)
    now = head(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json_pin(p) == now
    assert r.stdout.splitlines()[-1] == (f'map pin: docs/ARCHITECTURE.md is at {c2[:8]}, '
                                         f'behind map.refs.json at {now[:8]}' + TAIL)


def verdict(result, rule):
    return next(l.split()[0] for l in result.stdout.splitlines() if l.split()[1:2] == [rule])


def test_sc004_a_pin_git_cannot_resolve_is_not_compared(p, tmp_path):
    """023/FR-003, 023/SC-004."""
    set_map_pin(p, '0' * 40)
    d = doctor(p)
    assert notes(d) == [], d.stderr
    assert verdict(d, 'S12') == 'PASS' and verdict(d, 'S13') == 'PASS', d.stdout
    plain = tmp_path / 'plain'
    plain.mkdir()
    d = doctor(build_plain(plain))
    assert d.returncode == 0 and notes(d) == [], d.stdout + d.stderr


def build_plain(path):
    """The `project` fixture of tests/test_standard.py: no git, both pins `abcdef1`."""
    assert run(test_standard.SCAFFOLD, '--repo', path, '--profile', 'python', '--name', 'demo').returncode == 0
    write(path / 'docs' / 'ARCHITECTURE.md', '<!-- kit:map revision=abcdef1 -->\n# map\n')
    write(path / 'docs' / 'diagrams' / 'map.refs.json',
          json.dumps({'meta': {'repository': {'revision': 'abcdef1'}}, 'sources': [{'path': 'CLAUDE.md', 'line': 1}]}))
    test_standard.fill(path, deviations=False)
    test_standard.ci(path)
    return path


def test_sc005_a_fix_that_leaves_the_citation_file_prints_no_map_pin_line(p):
    """023/FR-001, 023/SC-005."""
    write(p / 'src' / 'a.py', 'def run():\n    return 1\n')
    c3 = commit(p)
    write(p / 'docs' / 'diagrams' / 'flow.json',
          json.dumps({'meta': {'repository': {'revision': c3}}, 'sources': [{'path': 'src/a.py', 'line': 1}]}))
    commit(p)
    claude = p / 'CLAUDE.md'
    write(claude, claude.read_text(encoding='utf-8').split('\n', 1)[1])
    write(p / 'src' / 'a.py', 'import os\ndef run():\n    return 1\n')
    commit(p)
    r = fix(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert re.search(r'CLAUDE\.md:1\s+lost', r.stderr), r.stderr
    assert 'flow.json' in r.stdout and json.loads((p / 'docs' / 'diagrams' / 'flow.json')
                                                  .read_text(encoding='utf-8'))['meta']['repository']['revision'] == head(p)
    assert json_pin(p) == git(p, 'rev-list', '--max-parents=0', 'HEAD').strip()
    assert not [l for l in r.stdout.splitlines() if l.startswith('map pin:')]


def k_repo(tmp_path, cited, changed):
    repo = tmp_path / 'k'
    repo.mkdir(parents=True)
    start_repo(repo)
    for name in ('src/main.py', 'docs/a.md', 'docs/b.md', 'README.md'):
        write(repo / name, 'one\n')
    k1 = commit(repo)
    write(repo / 'ARCH.md', f'<!-- kit:map revision={k1} -->\n# map\n\n' + ''.join(f'See `{c}`.\n' for c in cited))
    commit(repo)
    for name in changed:
        write(repo / name, 'two\n')
    commit(repo)
    return repo, k1


def test_sc006_the_pin_line_splits_direct_citations_from_directory_ones(tmp_path):
    """023/FR-004, 023/SC-006."""
    four = ('src/main.py', 'docs/a.md', 'docs/b.md', 'README.md')
    repo, k1 = k_repo(tmp_path / 'one', ('src/main.py', 'docs/'), four)
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 0, r.stdout
    lines = r.stdout.splitlines()
    pin = next(i for i, l in enumerate(lines) if l.startswith('pin:'))
    assert lines[pin] == (f'pin: {k1[:8]}, files changed since: 5, '
                          f'of which cited by the map: 1 directly, 2 under a cited directory')
    assert lines[pin + 1:] == ['  REVIEW docs/a.md', '  REVIEW docs/b.md', '  REVIEW src/main.py']
    repo, _ = k_repo(tmp_path / 'two', ('src/main.py', 'docs/', 'docs/a.md'), four)
    assert run(MAP_CHECK, repo, 'ARCH.md').stdout.count(', of which cited by the map: 2 directly, 1 under a cited directory\n') == 1
    repo, _ = k_repo(tmp_path / 'three', ('src/main.py', 'docs/'), ('README.md',))
    assert 'of which cited by the map: 0 directly, 0 under a cited directory\n' in run(MAP_CHECK, repo, 'ARCH.md').stdout


def refresh_steps():
    text = SKILL.read_text(encoding='utf-8')
    section = text[text.index('## Refresh\n'):]
    section = section[:section.index('\n## ', 1)]
    return section, re.findall(r'^(\d+)\. (.*)$', section, re.M)


def test_sc007_refresh_step_4_names_both_signs_and_keeps_its_order():
    """023/FR-005, 023/SC-007."""
    section, steps = refresh_steps()
    assert [n for n, _ in steps] == ['1', '2', '3', '4', '5']
    assert steps[0][1].startswith('Run Verify') and steps[1][1].startswith('`moved` only')
    assert steps[3][1].startswith('Set the Markdown pin on line 1') and steps[4][1].startswith('If `.claude/kit.yml`')
    assert 'map pin:' in steps[3][1] and 'note: S13' in steps[3][1]
    assert not re.search(r'[Ss]et (the|its) JSON pin|meta\.repository\.revision', section)


def test_sc008_no_exit_status_changes_and_the_gate_still_passes_while_behind(p):
    """023/FR-002, 023/FR-003, 023/SC-008: the note judges nothing; no mode of cite_refs.py writes the map."""
    claude = p / 'CLAUDE.md'
    write(claude, '# note\n' + claude.read_text(encoding='utf-8'))
    commit(p)
    before = (p / 'docs' / 'ARCHITECTURE.md').read_bytes()
    assert fix(p).returncode == 0
    commit(p)
    for flags in (['--check'], ['--report'], ['--prose'], ['--fix'], ['--touched', 'CLAUDE.md']):
        done = subprocess.run([sys.executable, str(CITE_REFS), '--diagrams', 'docs/diagrams', *flags],
                              cwd=p, capture_output=True, text=True, encoding='utf-8')
        assert done.returncode == 0, (flags, done.stdout, done.stderr)
        assert (p / 'docs' / 'ARCHITECTURE.md').read_bytes() == before, flags
    d = doctor(p)
    assert d.returncode == 0 and SUMMARY in d.stdout and len(notes(d)) == 1, d.stdout + d.stderr
    assert run(MAP_CHECK, p, 'docs/ARCHITECTURE.md').returncode == 0
    g = gate(p)
    assert g.code == 0 and g.verdict.startswith('kit-gate: passed:'), g.lines
    assert any(l.startswith('note: S13:') for l in g.lines), g.lines


def fix_at(repo, diagrams, root):
    return subprocess.run([sys.executable, str(CITE_REFS), '--diagrams', diagrams, '--root', root, '--fix'],
                          cwd=repo, capture_output=True, text=True, encoding='utf-8')


def test_a_citation_file_named_in_capitals_is_fixed_with_the_map_s(p):
    """023/FR-002: the only write is to a citation file, and on Windows rglob('*.json') also finds `z.JSON`."""
    upper = p / 'docs' / 'diagrams' / 'z.JSON'
    write(upper, json.dumps({'meta': {'repository': {'revision': head(p)}},
                             'sources': [{'path': 'CLAUDE.md', 'line': 1}]}))
    commit(p)
    claude = p / 'CLAUDE.md'
    write(claude, '# note\n' + claude.read_text(encoding='utf-8'))
    now = commit(p)
    r = fix(p)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json_pin(p) == now
    if sys.platform == 'win32':
        assert json.loads(upper.read_text(encoding='utf-8'))['meta']['repository']['revision'] == now


def test_a_fix_that_does_not_pin_the_citation_file_prints_no_map_pin_line(p):
    """023/FR-001: a JSON pin ahead of the map's is named only when this run pinned the citation file."""
    c2 = head(p)
    refs = p / 'docs' / 'diagrams' / 'map.refs.json'
    data = json.loads(refs.read_text(encoding='utf-8'))
    data['meta']['repository']['revision'] = c2
    write(refs, json.dumps(data))
    commit(p)
    claude = p / 'CLAUDE.md'
    write(claude, claude.read_text(encoding='utf-8').split('\n', 1)[1])
    commit(p)
    r = fix(p)
    assert r.returncode == 1, r.stdout + r.stderr
    assert json_pin(p) == c2
    assert not [l for l in r.stdout.splitlines() if l.startswith('map pin:')], r.stdout


def make_api(repo):
    """A repository whose one project lives at `api/`, made like `P`."""
    (repo / 'api').mkdir(parents=True)
    assert run(test_standard.SCAFFOLD, '--repo', repo, '--project-root', 'api', '--profile', 'python',
               '--name', 'api').returncode == 0
    data = test_standard.manifest(repo)
    data['projects'] = [dict(data['projects'][0], name='api', root='api')]
    test_standard.save(repo, data)
    start_repo(repo)
    first = commit(repo)
    write(repo / 'api' / 'docs' / 'ARCHITECTURE.md', f'<!-- kit:map revision={first} -->\n# map\n\nSee `CLAUDE.md`.\n')
    write(repo / 'api' / 'docs' / 'diagrams' / 'map.refs.json',
          json.dumps({'meta': {'repository': {'revision': first}}, 'sources': [{'path': 'api/CLAUDE.md', 'line': 1}]}))
    commit(repo)
    return repo, first


def test_a_project_below_the_git_root_names_its_map_from_the_git_root(tmp_path):
    """023/FR-001, 023/FR-003, Definitions: the map path is written from the git root."""
    repo, first = make_api(tmp_path / 'mono')
    claude = repo / 'api' / 'CLAUDE.md'
    write(claude, '# note\n' + claude.read_text(encoding='utf-8'))
    now = commit(repo)
    r = fix_at(repo, 'api/docs/diagrams', 'api')
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == (f'map pin: api/docs/ARCHITECTURE.md is at {first[:8]}, '
                                         f'behind map.refs.json at {now[:8]}' + TAIL)
    commit(repo)
    assert notes(doctor(repo)) == [f'note: S13: api/docs/ARCHITECTURE.md is pinned to {first[:8]}, '
                                   f'behind map.refs.json at {now[:8]}' + TAIL]


def test_a_shallow_clone_compares_no_pins(p, tmp_path):
    """023, Definitions: a shallow clone cuts ancestry, so a map pin ahead would read as behind there.
    Nothing is compared and nothing is printed."""
    c1, c2 = json_pin(p), head(p)
    git(p, 'branch', 'side', c1)
    git(p, 'branch', 'mid', c2)
    set_map_pin(p, c2)
    clone = tmp_path / 'shallow'
    git(tmp_path, 'clone', '-q', '--depth', '1', '--no-single-branch', 'file:///' + p.as_posix().lstrip('/'),
        str(clone))
    assert git(clone, 'rev-parse', '--is-shallow-repository').strip() == 'true'
    for rev in (c1, c2):
        git(clone, 'cat-file', '-e', f'{rev}^{{commit}}')
    assert notes(doctor(clone)) == []
    r = fix(clone)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json_pin(clone) == head(clone)
    assert not [l for l in r.stdout.splitlines() if l.startswith('map pin:')], r.stdout
