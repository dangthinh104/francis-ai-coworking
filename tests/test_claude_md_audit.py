"""claude_md_audit.py: what a CLAUDE.md names that git once held and that is gone (specs/001)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
AUDIT = KIT / 'kit-init' / 'scripts' / 'claude_md_audit.py'


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args],
                   check=True, capture_output=True)


def run(*args):
    return subprocess.run([sys.executable, str(AUDIT), *map(str, args)], capture_output=True, text=True, encoding='utf-8')


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'app.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs' / 'old.md').write_text('old\n', encoding='utf-8')
    (tmp_path / '.gitignore').write_text('output/\n.env\n', encoding='utf-8')
    git(tmp_path, 'add', '-A')
    git(tmp_path, 'commit', '-qm', 'init')
    return tmp_path


def claude(repo, text, where='.'):
    (repo / where).mkdir(parents=True, exist_ok=True)
    (repo / where / 'CLAUDE.md').write_text(text, encoding='utf-8')


def findings(result):
    return [line.split()[2] for line in result.stdout.splitlines() if line.startswith('  ') and ':' in line.split()[1]]


def test_a_file_that_names_only_what_is_there_is_clean(repo):
    claude(repo, '# App\n\nRead `src/app.py` and `docs/old.md:1`.\n')
    r = run('--repo', repo)
    assert r.returncode == 0, r.stdout
    assert 'CLAUDE.md (repository root): 3 lines, about' in r.stdout and 'an estimate' in r.stdout


def test_a_path_git_once_held_is_reported_with_its_line(repo):
    claude(repo, '# App\n\nRead `docs/old.md` first.\nThen `src/app.py`.\n')
    git(repo, 'rm', '-q', 'docs/old.md')
    git(repo, 'commit', '-qm', 'drop old doc')
    r = run('--repo', repo)
    assert r.returncode == 1
    assert 'path    CLAUDE.md:3  docs/old.md  (git knew it; it is gone or was moved)' in r.stdout
    assert findings(r) == ['docs/old.md']


def test_deleted_but_not_yet_committed_is_reported_too(repo):
    claude(repo, 'Read `docs/old.md`.\n')
    (repo / 'docs' / 'old.md').unlink()
    assert findings(run('--repo', repo)) == ['docs/old.md']


NOT_PATHS = ['PUT/DELETE', 'DD/MM/YYYY', 'feat/xxx', 'config.py', 'someone@example.com', 'api.example.com',
             'threading.RLock', 'specs/NNN-slug/', '.claude/skills/<domain>/', '*.md', '/etc/hosts', '~/notes.md',
             'C:\\SourceCode\\app', 'pytest -q tests/x.py', 'v0.7.1', '{house_slug}/doc', 'never/was/here.md']


@pytest.mark.parametrize('span', NOT_PATHS)
def test_what_only_looks_like_a_path_is_left_alone(repo, span):
    claude(repo, f'Use `{span}` here.\n')
    r = run('--repo', repo)
    assert r.returncode == 0, r.stdout


def test_run_time_files_negated_lines_and_code_blocks_are_left_alone(repo):
    (repo / 'output').mkdir()
    (repo / 'output' / 'state.json').write_text('{}', encoding='utf-8')
    git(repo, 'add', '-f', 'output/state.json')
    git(repo, 'commit', '-qm', 'tracked by mistake')
    git(repo, 'rm', '-q', '--cached', 'output/state.json')
    git(repo, 'rm', '-q', 'docs/old.md')
    git(repo, 'commit', '-qm', 'untrack, drop')
    (repo / 'output' / 'state.json').unlink()
    claude(repo, 'State lives in `output/state.json`.\n\n```\ncat docs/old.md\n```\n<!-- `docs/old.md` -->\n')
    r = run('--repo', repo)
    assert r.returncode == 0, r.stdout
    claude(repo, 'Read `docs/old.md`; there is no other doc.\n')       # the word comes after: still a pointer
    assert findings(run('--repo', repo)) == ['docs/old.md']


def test_own_skill_named_by_its_path_must_exist(repo):
    (repo / '.claude' / 'skills' / 'billing').mkdir(parents=True)
    (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').write_text('x\n', encoding='utf-8')
    claude(repo, 'See `.claude/skills/billing/SKILL.md`, `.claude/skills/ghost/SKILL.md`, `.claude/agents/nobody.md` '
                 'and the `flow` skill and `/code-review`.\n')
    r = run('--repo', repo)
    assert r.returncode == 1
    assert findings(r) == ['.claude/skills/ghost/SKILL.md', '.claude/agents/nobody.md']
    assert 'no such skill' in r.stdout and 'no such agent' in r.stdout


def manifest(repo, projects):
    (repo / '.claude').mkdir(exist_ok=True)
    body = 'version: 2\nprojects:\n' + ''.join(
        f'  - name: {name}\n    root: {root}\n    test:\n' + ''.join(f'      - {t}\n' for t in tests)
        for name, root, tests in projects)
    (repo / '.claude' / 'kit.yml').write_text(body, encoding='utf-8')


def test_test_command_must_be_in_the_file_or_the_manifest_named(repo):
    manifest(repo, [('app', '.', ['pytest -q --maxfail=1'])])
    claude(repo, 'Run `pytest -q` before a pull request.\n')
    r = run('--repo', repo)
    assert r.returncode == 1 and 'command CLAUDE.md  pytest -q --maxfail=1' in r.stdout
    claude(repo, 'Run `pytest  -q   --maxfail=1` before a pull request.\n')
    assert run('--repo', repo).returncode == 0
    claude(repo, 'Commands are in `.claude/kit.yml`.\n')
    assert run('--repo', repo).returncode == 0


def test_monorepo_judges_the_root_file_and_each_project_file_from_its_own_directory(repo):
    for name in ('api', 'web'):
        (repo / name / 'src').mkdir(parents=True)
        (repo / name / 'src' / 'main.py').write_text('x = 1\n', encoding='utf-8')
    (repo / 'api' / 'notes.md').write_text('n\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'two projects')
    git(repo, 'rm', '-q', 'api/notes.md'); git(repo, 'commit', '-qm', 'drop notes')
    manifest(repo, [('api', 'api', ['pytest -q']), ('web', 'web', ['npm test'])])
    claude(repo, 'Two projects. `src/app.py` is shared.\n')
    claude(repo, 'Run `pytest -q`. Read `src/main.py` and `notes.md`.\n', 'api')
    claude(repo, 'Run `npm test`. Read `src/main.py`.\n', 'web')
    r = run('--repo', repo)
    assert r.returncode == 1
    flush = [line.split(' (')[0] for line in r.stdout.splitlines() if not line.startswith(' ')]
    assert flush[:3] == ['CLAUDE.md', 'api/CLAUDE.md', 'web/CLAUDE.md']
    assert len(flush) == 4 and 'without backticks' in flush[3]          # 007/FR-001: a path finding was reported
    assert findings(r) == ['notes.md'] and 'api/CLAUDE.md:1  notes.md' in r.stdout


def test_exit_2_when_a_file_is_missing_or_this_is_no_repository(repo, tmp_path_factory):
    assert run('--repo', repo).returncode == 2            # no CLAUDE.md at all
    manifest(repo, [('api', 'api', ['pytest -q'])])
    (repo / 'api').mkdir()
    claude(repo, 'root\n')
    r = run('--repo', repo)
    assert r.returncode == 2 and 'api/CLAUDE.md (api): missing or not readable' in r.stdout
    bare = tmp_path_factory.mktemp('plain')
    (bare / 'CLAUDE.md').write_text('x\n', encoding='utf-8')
    r = run('--repo', bare)
    assert r.returncode == 2 and 'not a git repository' in r.stderr


# ---- the doctor's rule S18 (CLAUDE.md names nothing that is gone)

DOCTOR = KIT / 'kit-init' / 'scripts' / 'kit_doctor.py'
SCAFFOLD = KIT / 'kit-init' / 'scripts' / 'kit_scaffold.py'


def doctor(repo):
    return subprocess.run([sys.executable, str(DOCTOR), '--repo', str(repo), '--all'], capture_output=True, text=True,
                          encoding='utf-8')


def rule(result, name, section=None):
    """The verdict lines for one rule, optionally only under one `project x` heading."""
    out, here = [], section is None
    for line in result.stdout.splitlines():
        if not line.startswith(' '):
            here = section is None or line.startswith(section)
        elif here and f' {name} ' in line:
            out.append(line.split()[0])
    return out


@pytest.fixture
def two(repo):
    """A repository of two projects, api and web, each naming a file of its own."""
    import yaml
    (repo / 'api').mkdir()
    (repo / 'web').mkdir()
    subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(repo), '--profile', 'python', '--project-root', 'api'],
                   check=True, capture_output=True)
    subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(repo), '--profile', 'python', '--project-root', 'web'],
                   check=True, capture_output=True)
    kit = repo / '.claude' / 'kit.yml'
    data = yaml.safe_load(kit.read_text(encoding='utf-8'))
    base = dict(data['projects'][0], test=['pytest -q'])
    data['projects'] = [dict(base, name='api', root='api'), dict(base, name='web', root='web')]
    kit.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    for name in ('api', 'web'):
        (repo / name / 'notes.md').write_text('n\n', encoding='utf-8')
        claude(repo, 'Run `pytest -q`. Read `notes.md`.\n', name)
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'two projects')
    return repo


def save_deviation(repo, project, entry):
    import yaml
    kit = repo / '.claude' / 'kit.yml'
    data = yaml.safe_load(kit.read_text(encoding='utf-8'))
    for p in data['projects']:
        if p['name'] == project:
            p['deviations'] = [d for d in p.get('deviations') or [] if d['rule'] != 'S18'] + ([entry] if entry else [])
    kit.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')


def test_deleting_a_named_file_fails_that_project_and_no_other(two):
    assert rule(doctor(two), 'S18', 'project api') == ['PASS'] and rule(doctor(two), 'S18', 'project web') == ['PASS']
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    r = doctor(two)
    assert rule(r, 'S18', 'project api') == ['GAP'] and rule(r, 'S18', 'project web') == ['PASS'], r.stdout
    assert 'notes.md' in r.stdout


def test_s18_is_debt_only_by_name_and_the_list_only_shrinks(two):
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    save_deviation(two, 'api', {'rule': 'S18', 'reason': 'r', 'fix': 'f'})
    assert 'must name what it covers: `names: [name, ...]`' in doctor(two).stdout
    save_deviation(two, 'api', {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['notes.md']})
    assert rule(doctor(two), 'S18', 'project api') == ['DEBT']
    save_deviation(two, 'api', {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['notes.md', 'other.md']})
    assert 'conforming now, remove: other.md' in doctor(two).stdout
    claude(two, 'Run `pytest -q`.\n', 'api')
    r = doctor(two)
    assert rule(r, 'S18', 'project api') == ['GAP'] and 'remove the entry' in r.stdout, r.stdout


def test_an_s02_deviation_for_length_does_not_cover_s18(two):
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    claude(two, 'Run `pytest -q`. Read `notes.md`.\n' + 'line\n' * 160, 'api')
    import yaml
    kit = two / '.claude' / 'kit.yml'
    data = yaml.safe_load(kit.read_text(encoding='utf-8'))
    data['projects'][0]['deviations'] = (data['projects'][0].get('deviations') or []) + [
        {'rule': 'S02', 'reason': 'long', 'fix': 'shrink'}]
    kit.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    r = doctor(two)
    assert rule(r, 'S02', 'project api') == ['DEBT'] and rule(r, 'S18', 'project api') == ['GAP'], r.stdout


def test_the_root_file_of_a_monorepo_is_judged_as_a_rule_of_the_repository(two):
    assert rule(doctor(two), 'S18', 'repository') == []            # no file at the root: nothing to say
    claude(two, 'Two projects. Read `api/notes.md`.\n')
    assert rule(doctor(two), 'S18', 'repository') == ['PASS'] and rule(doctor(two), 'S02', 'repository') == ['PASS']
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    r = doctor(two)
    assert rule(r, 'S18', 'repository') == ['GAP'] and r.returncode == 1
    claude(two, 'Two projects.\n' + 'line\n' * 151)
    assert rule(doctor(two), 'S02', 'repository') == ['GAP']


def test_without_git_s18_is_skipped_not_passed(tmp_path):
    subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(tmp_path), '--profile', 'python'], check=True,
                   capture_output=True)
    assert rule(doctor(tmp_path), 'S18') == ['SKIP']


# ---- what the review of 0.8.0 found

@pytest.mark.parametrize('line, reported', [
    ('Tests do not count. The hook `docs/old.md` runs them.', True),    # a "not" of the sentence before
    ('Do not edit `docs/old.md`.', True),
    ('Never touch `docs/old.md`.', True),
    ('It was moved to `docs/old.md`.', True),                           # where it went, and that is gone too
    ('Read `docs/old.md.`', True),
    ('Read `docs/old.md#part`, then go on.', True),
    ('Read `docs/old.md:3-9`.', True),
    ('Chi tiết đã chuyển sang skill `x` (`docs/old.md`).', True),         # where the detail went
    ('Never deploy without reading `docs/old.md`.', True),
    ('`docs/old.md` replaces the legacy flow.', True),
    ('| `docs/old.md` | read first | removed columns are listed elsewhere |', True),
])
def test_a_sentence_says_a_path_is_gone_on_either_side_and_only_that_sentence(repo, line, reported):
    git(repo, 'rm', '-q', 'docs/old.md'); git(repo, 'commit', '-qm', 'drop')
    claude(repo, f'# App\n\n{line}\n')
    r = run('--repo', repo)
    assert (findings(r) == ['docs/old.md']) is reported, r.stdout
    assert r.returncode == (1 if reported else 0)


def test_a_line_number_after_a_code_block_is_the_line_of_the_file(repo):
    git(repo, 'rm', '-q', 'docs/old.md'); git(repo, 'commit', '-qm', 'drop')
    claude(repo, '# App\n\n```\nls docs/old.md\n```\n\nRead `docs/old.md`.\n')
    assert 'CLAUDE.md:7  docs/old.md' in run('--repo', repo).stdout


def test_a_name_longer_than_a_path_may_be_is_not_a_path(repo):
    claude(repo, f'# App\n\nSee `{"a" * 5000}/x.md`.\n')
    r = run('--repo', repo)
    assert r.returncode == 0, r.stdout + r.stderr


def root_deviation(repo, entry):
    import yaml
    kit = repo / '.claude' / 'kit.yml'
    data = yaml.safe_load(kit.read_text(encoding='utf-8'))
    data['deviations'] = [d for d in data.get('deviations') or [] if d['rule'] != entry['rule']] + [entry]
    kit.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')


def test_the_root_file_of_a_monorepo_can_be_held_as_debt_by_name(two):
    claude(two, 'Two projects. Read `api/notes.md`.\n')
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    root_deviation(two, {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['api/notes.md']})
    r = doctor(two)
    assert rule(r, 'S18', 'repository') == ['DEBT'], r.stdout
    assert 'needs `rule`' not in r.stdout
    root_deviation(two, {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['api/notes.md'], 'features': ['x']})
    assert 'takes `names`, not `features`' in doctor(two).stdout


def test_a_root_deviation_for_s18_is_refused_when_no_root_file_is_judged(two):
    root_deviation(two, {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['api/notes.md']})
    assert 'needs `rule`, one of S14, S15' in doctor(two).stdout


def test_a_shallow_clone_skips_s18_and_says_why(two, tmp_path_factory):
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    assert rule(doctor(two), 'S18', 'project api') == ['GAP']
    clone = tmp_path_factory.mktemp('shallow') / 'c'
    subprocess.run(['git', 'clone', '-q', '--depth', '1', '--no-local', str(two), str(clone)], check=True, capture_output=True)
    r = doctor(clone)
    assert rule(r, 'S18', 'project api') == ['SKIP'], r.stdout
    assert 'shallow clone' in r.stderr and r.stderr.count('shallow clone') == 1


def test_a_directory_inside_another_repository_skips_s18(two, tmp_path_factory):
    inner = two / 'vendor' / 'thing'
    inner.mkdir(parents=True)
    subprocess.run([sys.executable, str(SCAFFOLD), '--repo', str(inner), '--profile', 'python'], check=True,
                   capture_output=True)
    r = doctor(inner)
    assert rule(r, 'S18') == ['SKIP'], r.stdout
    assert 'not the root of a git repository' in r.stderr


def test_an_index_git_cannot_read_skips_s18_and_the_other_rules_are_still_judged(two):
    (two / '.git' / 'index').write_bytes(b'garbage')
    r = doctor(two)
    assert rule(r, 'S18', 'project api') == ['SKIP'], r.stdout + r.stderr
    assert rule(r, 'S02', 'project web') != [] and 'Unjudged' not in r.stderr
    assert 'git cannot list what it tracks' in r.stderr


def test_a_shallow_clone_does_not_ask_for_a_debt_entry_to_be_removed(two, tmp_path_factory):
    git(two, 'rm', '-q', 'api/notes.md'); git(two, 'commit', '-qm', 'drop')
    save_deviation(two, 'api', {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['notes.md']})
    git(two, 'commit', '-qam', 'debt')
    assert rule(doctor(two), 'S18', 'project api') == ['DEBT']
    clone = tmp_path_factory.mktemp('shallow') / 'c'
    subprocess.run(['git', 'clone', '-q', '--depth', '1', '--no-local', str(two), str(clone)], check=True, capture_output=True)
    r = doctor(clone)
    assert rule(r, 'S18', 'project api') == ['SKIP'] and 'remove the entry' not in r.stdout, r.stdout


def test_a_manifest_that_cannot_be_read_is_not_judged_as_no_manifest(repo):
    claude(repo, '# App\n\nRead `src/app.py`.\n')
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'kit.yml').write_text('projects: [unclosed\n  - {', encoding='utf-8')
    r = run('--repo', repo)
    assert r.returncode == 2, r.stdout + r.stderr
    assert '.claude/kit.yml' in r.stderr


def test_without_pyyaml_a_manifest_is_not_judged_as_no_manifest(repo, tmp_path_factory):
    claude(repo, '# App\n\nRead `src/app.py`.\n')
    claude(repo, '# Sub\n', 'sub')
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'kit.yml').write_text('projects:\n  - name: s\n    root: sub\n', encoding='utf-8')
    assert run('--repo', repo).returncode == 0
    shadow = tmp_path_factory.mktemp('noyaml')
    (shadow / 'yaml.py').write_text('raise ImportError("no yaml here")\n', encoding='utf-8')
    r = subprocess.run([sys.executable, str(AUDIT), '--repo', str(repo)], capture_output=True, text=True,
                       encoding='utf-8', env={**os.environ, 'PYTHONPATH': str(shadow)})
    assert r.returncode == 2, r.stdout + r.stderr
    assert 'PyYAML' in r.stderr


def test_a_copy_on_disk_that_git_does_not_track_does_not_hide_a_deleted_path(repo):
    claude(repo, 'Read `docs/old.md`.\n')
    git(repo, 'rm', '-q', 'docs/old.md')
    git(repo, 'commit', '-qm', 'drop old doc')
    (repo / 'docs').mkdir(exist_ok=True)
    (repo / 'docs' / 'old.md').write_text('a local leftover\n', encoding='utf-8')
    r = run('--repo', repo)
    assert findings(r) == ['docs/old.md'], r.stdout
    assert 'git does not track' in r.stdout
    git(repo, 'add', 'docs/old.md')
    assert findings(run('--repo', repo)) == []


def test_an_ignored_copy_on_disk_and_a_new_untracked_file_are_still_left_alone(repo):
    (repo / '.env').write_text('A=1\n', encoding='utf-8')
    (repo / 'notes.md').write_text('new\n', encoding='utf-8')
    claude(repo, 'Read `.env` and `notes.md` and `src/`.\n')
    assert findings(run('--repo', repo)) == []


@pytest.mark.parametrize('body', ['- name: s\n  root: sub\n', 'projects:\n  s:\n    root: sub\n',
                                  'projects:\n  - name: s\n    root: [sub]\n', 'projects:\n  - just a string\n', ''])
def test_a_manifest_of_the_wrong_shape_is_not_judged_as_no_manifest(repo, body):
    claude(repo, '# App\n')
    claude(repo, '# Sub\n', 'sub')
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'kit.yml').write_text(body, encoding='utf-8')
    r = run('--repo', repo)
    assert r.returncode == 2 and '.claude/kit.yml' in r.stderr, r.stdout + r.stderr


def test_when_git_cannot_list_what_it_tracks_nothing_is_judged(repo):
    claude(repo, 'Read `src/app.py`.\n')
    (repo / '.git' / 'index').write_bytes(b'garbage')
    r = run('--repo', repo)
    assert r.returncode == 2, r.stdout + r.stderr


def test_a_file_inside_a_submodule_is_present_though_the_outer_git_once_held_it(repo, tmp_path_factory):
    inner = tmp_path_factory.mktemp('inner')
    git(inner, 'init', '-q')
    (inner / 'lib').mkdir()
    (inner / 'lib' / 'f.py').write_text('x = 1\n', encoding='utf-8')
    git(inner, 'add', '-A')
    git(inner, 'commit', '-qm', 'init')
    (repo / 'vendor' / 'lib').mkdir(parents=True)
    (repo / 'vendor' / 'lib' / 'f.py').write_text('x = 1\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'vendored')
    git(repo, 'rm', '-rq', 'vendor')
    git(repo, 'commit', '-qm', 'drop the copy')
    git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(inner), 'vendor')
    git(repo, 'commit', '-qm', 'as a submodule')
    claude(repo, 'Read `vendor/lib/f.py` and `vendor/`.\n')
    r = run('--repo', repo)
    assert findings(r) == [] and r.returncode == 0, r.stdout + r.stderr


def test_a_path_git_once_held_and_now_ignores_is_left_alone_on_disk_or_not(repo):
    (repo / 'output').mkdir()
    (repo / 'output' / 'report.md').write_text('made at run time\n', encoding='utf-8')
    git(repo, 'add', '-f', 'output/report.md')
    git(repo, 'commit', '-qm', 'committed by mistake')
    git(repo, 'rm', '-q', '--cached', 'output/report.md')
    git(repo, 'commit', '-qm', 'untrack it')
    claude(repo, 'The run writes `output/report.md`.\n')
    assert findings(run('--repo', repo)) == []
    (repo / 'output' / 'report.md').unlink()
    assert findings(run('--repo', repo)) == []


def test_a_submodule_whose_name_git_would_quote_still_holds_its_files(repo, tmp_path_factory):
    inner = tmp_path_factory.mktemp('inner')
    git(inner, 'init', '-q')
    (inner / 'lib').mkdir()
    (inner / 'lib' / 'f.py').write_text('x = 1\n', encoding='utf-8')
    git(inner, 'add', '-A')
    git(inner, 'commit', '-qm', 'init')
    (repo / 'thư-viện' / 'lib').mkdir(parents=True)
    (repo / 'thư-viện' / 'lib' / 'f.py').write_text('x = 1\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'vendored')
    git(repo, 'rm', '-rq', 'thư-viện')
    git(repo, 'commit', '-qm', 'drop the copy')
    git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(inner), 'thư-viện')
    git(repo, 'commit', '-qm', 'as a submodule')
    claude(repo, 'Read `thư-viện/lib/f.py`.\n')
    r = run('--repo', repo)
    assert findings(r) == [] and r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize('body', ['projects:\n  - name: s\n    root: sub\n    test: pytest -q\n',
                                  'projects:\n  - name: s\n    root: ../elsewhere\n',
                                  'projects:\n  - name: s\n    root: ""\n'])
def test_a_project_the_manifest_states_wrongly_is_not_passed_over(repo, body):
    claude(repo, '# App\n')
    claude(repo, '# Sub\n', 'sub')
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'kit.yml').write_text(body, encoding='utf-8')
    r = run('--repo', repo)
    assert r.returncode == 2 and '.claude/kit.yml' in r.stderr, r.stdout + r.stderr


# ---- what is prose and what is not

def held_then_dropped(repo, *names):
    """Commit each file, then delete it with git: every name is one git once held."""
    for name in names:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text('x\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'hold')
    git(repo, 'rm', '-rq', *names); git(repo, 'commit', '-qm', 'drop')


def test_a_comment_opener_in_a_code_span_opens_no_comment(repo):
    held_then_dropped(repo, 'docs/x.md')
    claude(repo, '# App\n\nThe pin is `<!--` on the first line.\n\nAlso read `docs/x.md`.\n\nIt ends with `-->`.\n\n'
                 '<!-- `docs/x.md` -->\n')
    r = run('--repo', repo)
    assert findings(r) == ['docs/x.md'] and 'CLAUDE.md:5  docs/x.md' in r.stdout, r.stdout


def test_a_lone_backtick_in_a_comment_hides_nothing_after_the_comment(repo):
    held_then_dropped(repo, 'docs/x.md')
    claude(repo, '# App\n\n<!-- note: `x --> see `docs/x.md` for rules <!-- todo: `docs/x.md` -->\n')
    r = run('--repo', repo)
    assert findings(r) == ['docs/x.md'] and r.stdout.count('docs/x.md') == 1, r.stdout




# ---- the test command and the manifest

@pytest.mark.parametrize('command, written', [('make test', 'make test-all'), ('pytest -q', 'pytest -qx'),
                                              ('npm test', 'npm test:e2e'), ('pytest', 'mypytest')])
def test_a_test_command_is_matched_whole_not_as_the_start_of_another(repo, command, written):
    manifest(repo, [('app', '.', [command])])
    claude(repo, f'Run `{written}` before a pull request.\n')
    r = run('--repo', repo)
    assert r.returncode == 1 and f'command CLAUDE.md  {command}  ' in r.stdout, r.stdout
    claude(repo, f'Run {command}. Or `{command}`, then push.\n')
    assert run('--repo', repo).returncode == 0


def test_a_trailing_slash_is_the_same_command_and_a_comment_holds_none(repo):
    manifest(repo, [('app', '.', ['pytest -q tests'])])
    claude(repo, 'Run `pytest -q tests/` before a pull request.\n')
    assert run('--repo', repo).returncode == 0
    claude(repo, 'Run `pytest -q tests/unit` before a pull request.\n')
    assert run('--repo', repo).returncode == 1
    claude(repo, 'Run the tests.\n<!-- once it was `pytest -q tests` -->\n')
    r = run('--repo', repo)
    assert r.returncode == 1 and 'command CLAUDE.md  pytest -q tests' in r.stdout, r.stdout
    claude(repo, 'Run the tests:\n\n```\n<!-- not a comment here -->\npytest -q tests\n```\n')
    assert run('--repo', repo).returncode == 0


@pytest.mark.parametrize('body', ['Run `pytest`.\n\n```\ncat .claude/kit.yml\n```\n',
                                  'Run `pytest`.\n<!-- see .claude/kit.yml -->\n',
                                  'Run `pytest`. The old one is `.claude/kit.yml.bak`.\n'])
def test_the_manifest_named_in_a_code_block_or_a_comment_does_not_stand_for_the_command(repo, body):
    manifest(repo, [('app', '.', ['make test'])])
    claude(repo, f'# App\n\n{body}')
    r = run('--repo', repo)
    assert r.returncode == 1 and 'command CLAUDE.md  make test' in r.stdout, r.stdout


# ---- which names are judged, and by which rule

def test_a_file_below_a_skill_that_is_there_is_a_path_like_any_other(repo):
    (repo / '.claude' / 'skills' / 'foo' / 'reference').mkdir(parents=True)
    (repo / '.claude' / 'skills' / 'foo' / 'SKILL.md').write_text('s\n', encoding='utf-8')
    (repo / '.claude' / 'skills' / 'foo' / 'reference' / 'notes.md').write_text('n\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'a skill')
    git(repo, 'rm', '-q', '.claude/skills/foo/reference/notes.md'); git(repo, 'commit', '-qm', 'drop its notes')
    claude(repo, '# App\n\nSee `.claude/skills/foo/reference/notes.md`.\nSee `.claude/skills/foo/reference/never.md`.\n'
                 'See `.claude/skills/bar/` and `.claude/skills/baz`.\nSee `.claude/skills/foo/` and `.claude/skills/foo`.\n')
    r = run('--repo', repo)
    assert findings(r) == ['.claude/skills/foo/reference/notes.md', '.claude/skills/bar/', '.claude/skills/baz'], r.stdout
    assert 'path    CLAUDE.md:3  .claude/skills/foo/reference/notes.md  (git knew it; it is gone or was moved)' in r.stdout
    assert r.stdout.count('no such skill') == 2


@pytest.mark.parametrize('name', ['app.properties', 'build.gradle', 'web.config', 'csp.duckdb', '.env.example'])
def test_a_file_name_with_a_long_extension_is_judged(repo, name):
    held_then_dropped(repo, name)
    claude(repo, f'# App\n\nSee `{name}`.\n')
    assert findings(run('--repo', repo)) == [name]


def test_a_bare_name_without_an_extension_is_not_judged(repo):
    (repo / 'svc').mkdir()
    for name in ('Dockerfile', 'Makefile'):
        (repo / 'svc' / name).write_text('x\n', encoding='utf-8')
    held_then_dropped(repo, 'Dockerfile', 'Makefile')
    claude(repo, '# App\n\nEach service has its own `Dockerfile` and `Makefile`.\n')
    r = run('--repo', repo)
    assert findings(r) == [] and r.returncode == 0, r.stdout


def test_dotted_names_and_branches_are_not_reported_beside_files_of_that_shape(repo):
    (repo / 'src' / 'csp').mkdir()
    (repo / 'src' / 'csp' / '__init__.py').write_text('\n', encoding='utf-8')
    held_then_dropped(repo, 'app_log.log', 'prod/x.md', 'now.py')
    claude(repo, '# App\n\nNo module may import `src.csp`. Log via `repos.app_log.log`.\n'
                 'Branch `origin/prod`, repo `dangthinh104/app`, time `datetime.now`, tag `v0.7.1`, `os.environ`.\n')
    r = run('--repo', repo)
    assert findings(r) == [] and r.returncode == 0, r.stdout


def test_a_code_span_in_an_indented_block_is_read(repo):
    git(repo, 'rm', '-q', 'docs/old.md'); git(repo, 'commit', '-qm', 'drop')
    claude(repo, '# App\n\nExample:\n\n    run `docs/old.md`\n\nDone.\n')
    assert 'CLAUDE.md:5  docs/old.md' in run('--repo', repo).stdout


# ---- the verdict here is the verdict in a clone

def test_a_file_of_a_submodule_that_was_not_fetched_is_not_gone(repo, tmp_path_factory):
    inner = tmp_path_factory.mktemp('inner')
    git(inner, 'init', '-q')
    (inner / 'lib').mkdir()
    (inner / 'lib' / 'f.py').write_text('x = 1\n', encoding='utf-8')
    git(inner, 'add', '-A'); git(inner, 'commit', '-qm', 'init')
    (repo / 'vendor' / 'lib').mkdir(parents=True)
    (repo / 'vendor' / 'lib' / 'f.py').write_text('x = 1\n', encoding='utf-8')
    claude(repo, 'Read `vendor/lib/f.py` and `vendor/`.\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'vendored')
    git(repo, 'rm', '-rq', 'vendor'); git(repo, 'commit', '-qm', 'drop the copy')
    git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(inner), 'vendor')
    git(repo, 'commit', '-qm', 'as a submodule')
    clone = tmp_path_factory.mktemp('clone') / 'c'
    subprocess.run(['git', 'clone', '-q', '--no-local', str(repo), str(clone)], check=True, capture_output=True)
    assert not (clone / 'vendor' / 'lib' / 'f.py').exists()
    r = run('--repo', clone)
    assert findings(r) == [] and r.returncode == 0, r.stdout + r.stderr


def test_a_tracked_file_missing_from_this_working_tree_is_reported_as_that(repo):
    claude(repo, 'Read `docs/old.md`.\n')
    (repo / 'docs' / 'old.md').unlink()
    r = run('--repo', repo)
    assert 'path    CLAUDE.md:1  docs/old.md  (git tracks it; it is missing from this working tree)' in r.stdout, r.stdout
    assert r.returncode == 1


def test_a_skill_git_stopped_tracking_is_reported_here_as_in_a_clone(repo, tmp_path_factory):
    (repo / '.claude' / 'skills' / 'billing').mkdir(parents=True)
    (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').write_text('x\n', encoding='utf-8')
    claude(repo, 'Use the skill `.claude/skills/billing`.\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'a skill')
    git(repo, 'rm', '-rq', '--cached', '.claude/skills/billing'); git(repo, 'commit', '-qm', 'untrack it')
    assert (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').is_file()
    r = run('--repo', repo)
    assert findings(r) == ['.claude/skills/billing'] and 'git does not track' in r.stdout, r.stdout
    clone = tmp_path_factory.mktemp('clone') / 'c'
    subprocess.run(['git', 'clone', '-q', '--no-local', str(repo), str(clone)], check=True, capture_output=True)
    assert findings(run('--repo', clone)) == ['.claude/skills/billing']


# ---- the cost is that of a few git calls, whatever the size of the file

def timed(repo):
    import time
    start = time.monotonic()
    r = run('--repo', repo)
    return r, time.monotonic() - start


def test_a_table_of_four_hundred_deleted_paths_is_judged_in_seconds(repo):
    names = [f'g/k{i:03}.md' for i in range(400)]
    held_then_dropped(repo, *names)
    claude(repo, '# App\n\n| file | rule |\n|---|---|\n' + ''.join(f'| `{n}` | rule |\n' for n in names))
    r, seconds = timed(repo)
    assert findings(r) == names, r.stdout[:400]
    assert seconds < 10, seconds


def test_three_thousand_lines_and_two_thousand_spans_are_judged_in_seconds(repo):
    gone, live = [f'gone/f{i:02}.md' for i in range(40)], [f'live/f{i:02}.md' for i in range(40)]
    held_then_dropped(repo, *gone)
    for name in live:
        (repo / name).parent.mkdir(exist_ok=True)
        (repo / name).write_text('x\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'live')
    spans = [f'Rule {n}: read `{(gone if n % 2 else live)[n % 40]}` before the step, e.g. the first one.' for n in range(2000)]
    filler = ['A line of plain words that names nothing.'] * 15
    body = '\n\n'.join('\n'.join(spans[i:i + 34] + filler) for i in range(0, 2000, 34))
    claude(repo, f'# App\n\n{body}\n')
    assert len(body.splitlines()) > 2900
    r, seconds = timed(repo)
    assert len(findings(r)) == 1000, r.stdout[:400]
    assert seconds < 10, seconds


# ---- a call that fails is not an answer

def test_a_diff_setting_that_breaks_a_diff_does_not_empty_the_history(repo):
    held_then_dropped(repo, 'a/gone.md')
    git(repo, 'config', 'diff.orderFile', 'nope')
    claude(repo, 'Read `a/gone.md`.\n')
    r = run('--repo', repo)
    assert findings(r) == ['a/gone.md'] and r.returncode == 1, r.stdout + r.stderr


def test_a_history_git_cannot_read_is_not_an_empty_history(repo):
    held_then_dropped(repo, 'a/gone.md')
    claude(repo, 'Read `a/gone.md`.\n')
    head = subprocess.run(['git', '-C', str(repo), 'symbolic-ref', 'HEAD'], capture_output=True, text=True).stdout.strip()
    (repo / '.git' / head).write_text('1' * 40 + '\n', encoding='utf-8')
    r = run('--repo', repo)
    assert r.returncode == 2 and 'git log' in r.stderr, r.stdout + r.stderr


def test_a_repository_with_no_commit_has_no_history_and_is_judged(tmp_path):
    git(tmp_path, 'init', '-q')
    claude(tmp_path, 'Read `a/gone.md`.\n')
    r = run('--repo', tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_file_a_fetched_submodule_does_not_hold_is_judged_by_the_history(repo, tmp_path_factory):
    inner = tmp_path_factory.mktemp('inner')
    git(inner, 'init', '-q')
    (inner / 'f.py').write_text('x = 1\n', encoding='utf-8')
    git(inner, 'add', '-A'); git(inner, 'commit', '-qm', 'init')
    held_then_dropped(repo, 'vendor/lib/only-old.md')
    git(repo, '-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', str(inner), 'vendor/lib')
    git(repo, 'commit', '-qm', 'as a submodule')
    claude(repo, 'Read `vendor/lib/only-old.md` and `vendor/lib/f.py`.\n')
    r = run('--repo', repo)
    assert findings(r) == ['vendor/lib/only-old.md'] and r.returncode == 1, r.stdout + r.stderr


def test_a_path_added_and_deleted_on_a_merged_branch_is_one_git_once_held(repo):
    git(repo, 'checkout', '-q', '-b', 'side')
    held_then_dropped(repo, 'docs/side.md')
    git(repo, 'checkout', '-q', '-')
    (repo / 'src' / 'app.py').write_text('x = 2\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'meanwhile')
    git(repo, 'merge', '-q', '--no-ff', '-m', 'merge side', 'side')
    claude(repo, 'Read `docs/side.md`.\n')
    assert findings(run('--repo', repo)) == ['docs/side.md']


@pytest.mark.parametrize('written', ['`make test`: runs everything', 'make test: runs everything', 'Run make test.',
                                     'First make test, then push', 'It is `make test`:'])
def test_punctuation_after_a_test_command_is_not_part_of_another(repo, written):
    manifest(repo, [('app', '.', ['make test'])])
    claude(repo, f'# App\n\n{written}\n')
    r = run('--repo', repo)
    assert r.returncode == 0, r.stdout


def test_the_manifest_named_with_a_leading_dot_slash_is_the_manifest(repo):
    manifest(repo, [('app', '.', ['make test'])])
    claude(repo, '# App\n\nSee `./.claude/kit.yml`.\n')
    assert run('--repo', repo).returncode == 0


# ---- a path that is gone is reported whatever the words around it (specs/007)

HINT = ('without backticks', 'names:')
REPO = KIT.parent.parent.parent
SCRIPT = 'plugins/francis-kit/skills/kit-init/scripts/claude_md_audit.py'


def drop_old(repo):
    git(repo, 'rm', '-q', 'docs/old.md'); git(repo, 'commit', '-qm', 'drop')


def hints(result):
    """The numbers of the lines of standard output that name the two ways."""
    return [n for n, line in enumerate(result.stdout.splitlines()) if all(word in line for word in HINT)]


def kit_grep(*args):
    return subprocess.run(['git', '-C', str(REPO), 'grep', '-n', *args], capture_output=True, text=True,
                          encoding='utf-8')


def reported_at_line_1(repo, text):
    claude(repo, text)
    r = run('--repo', repo)
    return (findings(r) == ['docs/old.md'] and '  path    CLAUDE.md:1  docs/old.md  (' in r.stdout
            and r.returncode == 1), r.stdout


@pytest.mark.parametrize('line', [
    'The agent `docs/old.md` was removed on 2026-05-08.',
    'There is no `docs/old.md` any more.',
    '`src/app.py` replaces what was moved from `docs/old.md`.',
    'đã xóa `docs/old.md`',
    '`docs/old.md` đã bị xoá',
    '`docs/old.md` đã chuyển sang skill khác.',
    '| `src/app.py` | was `docs/old.md`, removed |',
    'Đã xoá `docs/old.md` tháng trước.',
])
def test_a_sentence_that_says_a_path_is_gone_does_not_hide_it(repo, line):
    """001/FR-004, 007/SC-001."""
    drop_old(repo)
    reported, out = reported_at_line_1(repo, f'{line}\n')
    assert reported, out


@pytest.mark.parametrize('line', [
    'Never remove `docs/old.md`.',
    'Do not delete `docs/old.md` by hand.',
    '`docs/old.md` is used to reset the cache.',
])
def test_a_rule_about_a_path_that_is_gone_does_not_hide_it(repo, line):
    """001/FR-004, 007/SC-002."""
    drop_old(repo)
    reported, out = reported_at_line_1(repo, f'{line}\n')
    assert reported, out


@pytest.mark.parametrize('text', ['The file `docs/old.md` was\nremoved.\n', 'The file `docs/old.md` was removed.\n'])
def test_how_a_sentence_is_wrapped_changes_no_verdict(repo, text):
    """001/FR-004, 007/SC-003."""
    drop_old(repo)
    reported, out = reported_at_line_1(repo, text)
    assert reported, out


def test_a_name_without_backticks_is_not_read_and_a_strike_through_hides_nothing(repo):
    """001/FR-004, 007/SC-004."""
    drop_old(repo)
    claude(repo, 'There is no docs/old.md any more.\n')
    r = run('--repo', repo)
    assert findings(r) == [] and r.returncode == 0, r.stdout
    reported, out = reported_at_line_1(repo, '~~`docs/old.md`~~ is gone.\n')
    assert reported, out


def test_the_two_ways_are_named_once_after_the_last_finding_and_only_with_one(repo):
    """007/FR-001, 007/FR-002, 007/SC-005."""
    drop_old(repo)
    claude(repo, 'Read `docs/old.md`.\nSee `docs/old.md` again.\n')
    r = run('--repo', repo)
    out = r.stdout.splitlines()
    found = [n for n, line in enumerate(out) if line.startswith('  path    CLAUDE.md:')]
    assert [out[n].split()[1] for n in found] == ['CLAUDE.md:1', 'CLAUDE.md:2'] and findings(r) == ['docs/old.md'] * 2
    assert len(hints(r)) == 1 and hints(r)[0] > found[1], r.stdout
    assert r.returncode == 1 and not any(word in r.stderr for word in HINT)
    claude(repo, 'Read `src/app.py`.\n')
    r = run('--repo', repo)
    assert not any(word in r.stdout for word in HINT), r.stdout
    assert r.returncode == 0


def test_a_run_with_only_a_command_finding_does_not_name_the_two_ways(repo):
    """007/FR-002, 007/SC-006."""
    drop_old(repo)
    manifest(repo, [('app', '.', ['pytest -q'])])
    claude(repo, 'Read `src/app.py`.\n')
    r = run('--repo', repo)
    assert [line.split()[0] for line in r.stdout.splitlines() if line.startswith('  ')] == ['command'], r.stdout
    assert '  command CLAUDE.md  pytest -q  (' in r.stdout
    assert r.returncode == 1 and 'without backticks' not in r.stdout


def test_no_option_and_no_word_list_reads_the_sentence():
    """007/FR-004, 007/SC-007."""
    import re
    r = run('--help')
    assert r.returncode == 0
    assert set(re.findall(r'(?<![\w-])--?[A-Za-z][\w-]*', r.stdout)) == {'-h', '--help', '--repo', '--project-root'}
    r = kit_grep('-w', '-e', 'says_gone', '-e', 'SENTENCE_END', '-e', 'GONE', '-e', 'WENT', '-e', 'NO_BEFORE',
                 '-e', 'ARRIVES', '--', SCRIPT)
    assert r.returncode == 1 and r.stdout == '', r.stdout + r.stderr


def one_project(repo, text, covered=None):
    """The doctor's run on one project at the root whose test is `pytest -q`, with a deviation
    on S18 that names `covered` when one is given."""
    manifest(repo, [('app', '.', ['pytest -q'])])
    if covered:
        with (repo / '.claude' / 'kit.yml').open('a', encoding='utf-8') as kit:
            kit.write(f"    deviations:\n      - {{rule: S18, reason: r, fix: f, names: ['{covered}']}}\n")
    claude(repo, text)
    return doctor(repo)


def said(result, name):
    """What the doctor prints for one rule: its verdict lines, each with the lines indented under it."""
    out, held = [], False
    for line in result.stdout.splitlines():
        if not line.startswith('       '):
            held = line.startswith('  ') and line.split()[1:2] == [name]
        if held:
            out.append(line)
    return '\n'.join(out)


def test_the_doctor_names_the_two_ways_for_a_gone_path_no_deviation_covers(repo):
    """007/FR-003, 007/SC-008: a plain gap, and a path the recorded deviation does not cover."""
    drop_old(repo)
    gone = 'Run `pytest -q`. There is no `docs/old.md` any more.\n'
    s18 = said(one_project(repo, gone), 'S18')
    assert all(word in s18 for word in ('GAP  S18', 'docs/old.md', 'without backticks', 'names:')), s18
    s18 = said(one_project(repo, gone, 'other.md'), 'S18')
    assert all(word in s18 for word in ('GAP  S18 not covered by the recorded deviation', 'docs/old.md',
                                        'without backticks', 'names:')), s18


def test_the_doctor_does_not_name_the_two_ways_on_debt_or_once_the_name_has_no_backticks(repo):
    """007/FR-003, 007/SC-008: debt, and a deviation the rewritten sentence no longer needs."""
    drop_old(repo)
    r = one_project(repo, 'Run `pytest -q`. There is no `docs/old.md` any more.\n', 'docs/old.md')
    assert 'DEBT S18' in r.stdout and 'GAP  S18' not in r.stdout and 'without backticks' not in r.stdout, r.stdout
    r = one_project(repo, 'Run `pytest -q`. There is no docs/old.md any more.\n', 'docs/old.md')
    assert 'GAP  S18 listed under deviations but conforms now' in r.stdout, r.stdout


def test_the_doctor_does_not_name_the_two_ways_for_a_command(repo):
    """007/FR-003, 007/SC-008: a gap that names only a command, with and without a deviation that covers the path."""
    drop_old(repo)
    r = one_project(repo, 'Read `src/app.py`.\n')
    assert 'GAP  S18' in r.stdout and 'pytest -q' in said(r, 'S18') and 'without backticks' not in r.stdout, r.stdout
    r = one_project(repo, 'Read `docs/old.md`.\n', 'docs/old.md')
    s18 = said(r, 'S18')
    assert 'GAP  S18 not covered by the recorded deviation' in s18 and 'pytest -q' in s18, r.stdout
    assert 'without backticks' not in r.stdout


def test_no_file_to_judge_is_still_exit_2(repo):
    """001/FR-007, 007/SC-009."""
    drop_old(repo)
    r = run('--repo', repo)
    assert r.returncode == 2 and 'CLAUDE.md (repository root): missing or not readable' in r.stdout
    assert hints(r) == []


@pytest.mark.private
def test_the_texts_of_the_kit_say_the_words_are_not_read_and_name_the_two_ways():
    """007/FR-005, 007/SC-010."""
    import ast
    r = kit_grep('-e', 'word list', '-e', 'list of words', '--', 'README.md', SCRIPT)
    assert r.returncode == 1 and r.stdout == '', r.stdout + r.stderr
    r = kit_grep('-e', 'says it is gone', '-e', 'không còn', '--', SCRIPT)
    assert r.returncode == 1 and r.stdout == '', r.stdout + r.stderr
    starts = {'README.md': '', 'plugins/francis-kit/STANDARD.md': '| S18 |',
              'plugins/francis-kit/skills/kit-adopt/SKILL.md': '| S18 (', SCRIPT: ''}
    for name, start in starts.items():
        both = [line for line in (REPO / name).read_text(encoding='utf-8').splitlines()
                if all(word in line for word in HINT)]
        assert both and all(line.startswith(start) for line in both), name
        if start:
            assert 'not read' in both[0], name
    doc = ast.get_docstring(ast.parse((REPO / SCRIPT).read_text(encoding='utf-8')))
    assert 'list of words' not in doc and 'not read' in doc
    assert any(all(word in line for word in HINT) for line in doc.splitlines())
    limits = (REPO / 'README.md').read_text(encoding='utf-8').split('\n## Known limits\n')[1].split('\n## ')[0]
    assert any('not read' in line and all(word in line for word in HINT) for line in limits.splitlines())


def test_a_directory_that_is_gone_is_reported_in_the_sentence_that_says_so(repo):
    """001/FR-004, 007/SC-011."""
    (repo / 'docs' / 'guide.md').write_text('g\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'guide')
    git(repo, 'rm', '-rq', 'docs'); git(repo, 'commit', '-qm', 'drop docs')
    assert not (repo / 'docs').exists()
    claude(repo, 'There is no `docs/` directory: see the wiki.\n')
    r = run('--repo', repo)
    assert findings(r) == ['docs/'] and '  path    CLAUDE.md:1  docs/  (' in r.stdout, r.stdout
    assert r.returncode == 1


def test_a_skill_or_an_agent_that_is_not_there_is_reported_whatever_the_sentence_says(repo):
    """001/FR-005, 007/SC-012."""
    held_then_dropped(repo, '.claude/agents/x.md')
    claude(repo, 'The agent `.claude/agents/x.md` was removed.\n')
    r = run('--repo', repo)
    assert '  skill   CLAUDE.md:1  .claude/agents/x.md  (' in r.stdout and r.returncode == 1, r.stdout
    claude(repo, 'There is no `.claude/skills/ghost` any more.\n')
    r = run('--repo', repo)
    assert '  skill   CLAUDE.md:1  .claude/skills/ghost  (' in r.stdout and r.returncode == 1, r.stdout


@pytest.mark.private
def test_the_changelog_says_a_project_can_turn_red_and_names_the_two_ways():
    """007/FR-006, 007/SC-013. The line stands under `## Unreleased` until the release renames that heading."""
    import re
    heading, sections = None, {}
    for line in (REPO / 'CHANGELOG.md').read_text(encoding='utf-8').splitlines():
        if line.startswith('## '):
            heading = line
        elif all(word in line for word in ('S18', 'can turn red') + HINT):
            sections.setdefault(heading, []).append(line)
    assert len(sections) == 1, sections
    assert re.fullmatch(r'## (?:Unreleased|\d+\.\d+\.\d+ \(\d{4}-\d{2}-\d{2}\))', next(iter(sections)))


def two_projects_that_name_what_is_gone(repo, with_b):
    drop_old(repo)
    manifest(repo, [('a', 'a', ['pytest -q']), ('b', 'b', ['pytest -q'])])
    (repo / 'b').mkdir()
    for name in ('a', 'b') if with_b else ('a',):
        claude(repo, 'Read `docs/old.md`.\n', name)


def test_a_run_that_exits_2_for_a_missing_file_still_names_the_two_ways(repo):
    """007/FR-001, 007/SC-014."""
    two_projects_that_name_what_is_gone(repo, with_b=False)
    r = run('--repo', repo)
    out = r.stdout.splitlines()
    assert r.returncode == 2 and 'b/CLAUDE.md (b): missing or not readable' in out, r.stdout
    found = [n for n, line in enumerate(out) if line.startswith('  path    a/CLAUDE.md:1  docs/old.md  (')]
    assert len(found) == 1 and len(hints(r)) == 1 and hints(r)[0] > found[0], r.stdout
    assert [n for n, line in enumerate(out) if 'without backticks' in line] == hints(r)


def test_a_run_that_stops_with_nothing_was_judged_does_not_name_the_two_ways(repo, capsys, monkeypatch):
    """007/FR-001: the findings of a run that stops are not a verdict."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('claude_md_audit_under_test', AUDIT)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    two_projects_that_name_what_is_gone(repo, with_b=True)
    judge, calls = audit.audit, []

    def second_fails(*args):
        calls.append(args)
        if len(calls) == 2:
            raise audit.Unjudged('git cannot read the history here')
        return judge(*args)
    monkeypatch.setattr(audit, 'audit', second_fails)
    assert audit.main(['--repo', str(repo)]) == 2
    printed = capsys.readouterr()
    assert '  path    a/CLAUDE.md:1  docs/old.md  (' in printed.out and 'nothing was judged' in printed.err
    assert not any(word in printed.out + printed.err for word in HINT)


def test_a_named_file_in_a_directory_the_manifest_does_not_list_is_judged_from_the_git_root(repo):
    """002: the shrink skill measures the CLAUDE.md the person names, wherever it is."""
    (repo / 'sub' / 'docs').mkdir(parents=True)
    (repo / 'sub' / 'docs' / 'here.md').write_text('h\n', encoding='utf-8')
    (repo / 'sub' / 'docs' / 'gone.md').write_text('g\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'sub')
    git(repo, 'rm', '-q', 'sub/docs/gone.md'); git(repo, 'commit', '-qm', 'drop gone')
    manifest(repo, [('app', '.', ['pytest -q'])])
    claude(repo, 'Commands are in `.claude/kit.yml`.\n')
    claude(repo, 'Read `sub/docs/here.md` and `docs/here.md`, not `sub/docs/gone.md`.\n', 'sub')
    r = run('--repo', repo, '--project-root', 'sub')
    assert 'sub/CLAUDE.md (sub): 1 lines' in r.stdout, r.stdout + r.stderr
    assert findings(r) == ['sub/docs/gone.md'] and r.returncode == 1
    assert run('--repo', repo, '--project-root', '.').stdout.count('CLAUDE.md (') == 1   # a listed root, once


# ---- the root CLAUDE.md of a monorepo may name a file from its project's root (specs/021)

ORDERS = '- `stock-service/`: the api service; how it reads its data is in `src/orders/README.md`.'
FOUND_3 = '  found   CLAUDE.md:3  src/orders/README.md  (not at the git root; found under stock-service/)'
NOTE_3 = '         note: CLAUDE.md:3 src/orders/README.md is not at the git root; found under stock-service/'
GONE_3 = '  path    CLAUDE.md:3  src/orders/README.md  (git knew it; it is gone or was moved)'


def write(repo, path, text):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding='utf-8')


def monorepo(repo, moved=True, stock_root='stock-service', root_text=None):
    """`M` of 021: `src/orders/README.md` committed at the git root, moved into `stock-service/`,
    then the manifest of two projects and the three CLAUDE.md. `moved=False`: the file is
    added under `stock-service/` from the start."""
    if moved:
        write(repo, 'src/orders/README.md', 'orders\n')
        git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'one')
        (repo / 'stock-service' / 'src').mkdir(parents=True)
        git(repo, 'mv', 'src/orders', 'stock-service/src/orders'); git(repo, 'commit', '-qm', 'two')
    else:
        write(repo, 'stock-service/src/orders/README.md', 'orders\n')
    write(repo, '.claude/kit.yml', 'version: 2\nprojects:\n'
          f'  - name: stock\n    root: {stock_root}\n    test: []\n'
          '  - name: web\n    root: web\n    test: []\n')
    write(repo, 'web/CLAUDE.md', 'Web.\n')
    write(repo, 'stock-service/CLAUDE.md', 'Stock.\n')
    write(repo, 'CLAUDE.md', root_text if root_text is not None else f'# Monorepo\n\n{ORDERS}\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'three')
    return repo


@pytest.fixture
def bare(tmp_path):
    git(tmp_path, 'init', '-q')
    return tmp_path


def test_a_path_of_the_root_file_found_under_a_project_root_is_not_reported_and_is_named(bare):
    """021/FR-001, 021/FR-002, 021/FR-003, 021/SC-001."""
    monorepo(bare)
    r = run('--repo', bare)
    out = r.stdout.splitlines()
    assert r.returncode == 0, r.stdout
    assert not any('path    CLAUDE.md:3' in line for line in out)
    head = next(n for n, line in enumerate(out) if line.startswith('CLAUDE.md (repository root)'))
    assert FOUND_3 in out[head + 1:], r.stdout
    assert ', 0 finding(s)' in out[head] and 'without backticks' not in r.stdout
    d = doctor(bare)
    lines = d.stdout.splitlines()
    assert not any('GAP  S18' in line for line in lines), d.stdout
    assert NOTE_3 in lines, d.stdout
    s18 = next(n for n, line in enumerate(lines) if ' S18 ' in line)
    project = next(n for n, line in enumerate(lines) if line.startswith('project '))
    assert s18 < lines.index(NOTE_3) < project, d.stdout


def test_a_path_that_would_not_be_reported_prints_nothing_new(bare):
    """021/SC-002."""
    monorepo(bare, moved=False)
    r = run('--repo', bare)
    assert r.returncode == 0 and findings(r) == [] and 'found   ' not in r.stdout, r.stdout
    assert 'note: CLAUDE.md:3' not in doctor(bare).stdout


def test_a_path_found_nowhere_is_reported_as_today(bare):
    """021/SC-003: deleted under the project root too."""
    monorepo(bare)
    git(bare, 'rm', '-q', 'stock-service/src/orders/README.md'); git(bare, 'commit', '-qm', 'four')
    r = run('--repo', bare)
    assert r.returncode == 1 and GONE_3 in r.stdout.splitlines() and 'found   ' not in r.stdout, r.stdout


def test_the_found_line_names_every_root_in_the_order_of_the_manifest(bare):
    """021/SC-003: two roots, joined by `, `."""
    monorepo(bare)
    write(bare, 'web/src/orders/README.md', 'w\n')
    git(bare, 'add', '-A'); git(bare, 'commit', '-qm', 'four')
    r = run('--repo', bare)
    assert ('  found   CLAUDE.md:3  src/orders/README.md  (not at the git root; found under stock-service/, web/)'
            in r.stdout.splitlines()), r.stdout
    assert ('         note: CLAUDE.md:3 src/orders/README.md is not at the git root; found under stock-service/, web/'
            in doctor(bare).stdout.splitlines())


def test_a_root_written_with_a_slash_is_named_with_one(bare):
    """021/SC-003."""
    monorepo(bare, stock_root='stock-service/')
    assert FOUND_3 in run('--repo', bare).stdout.splitlines()


def test_each_place_that_names_a_found_path_gets_its_found_line(bare):
    """021/SC-003: lines 3 and 5, in that order."""
    monorepo(bare, root_text=f'# Monorepo\n\n{ORDERS}\n\nAgain: `src/orders/README.md`.\n')
    out = run('--repo', bare).stdout.splitlines()
    found = [line for line in out if line.startswith('  found   ')]
    assert found == [FOUND_3, FOUND_3.replace('CLAUDE.md:3', 'CLAUDE.md:5')], out


def test_a_path_that_leaves_the_root_or_is_missing_from_the_working_tree_is_not_found(bare):
    """021, Out of scope: `../web/x` is not below `stock-service/`; a tracked file missing here is not found."""
    monorepo(bare, root_text=f'# Monorepo\n\n{ORDERS}\n\nAnd `../web/old.md`.\n')
    write(bare, 'web/old.md', 'o\n'); write(bare, 'old.md', 'o\n')
    git(bare, 'add', '-A'); git(bare, 'commit', '-qm', 'four')
    git(bare, 'rm', '-q', 'old.md'); git(bare, 'commit', '-qm', 'five')
    r = run('--repo', bare)
    assert 'found   CLAUDE.md:5' not in r.stdout, r.stdout
    (bare / 'stock-service' / 'src' / 'orders' / 'README.md').unlink()
    r = run('--repo', bare)
    assert r.returncode == 1 and GONE_3 in r.stdout.splitlines() and 'found   ' not in r.stdout, r.stdout


def test_only_the_root_file_is_read_against_the_project_roots(bare):
    """021/SC-004."""
    monorepo(bare)
    write(bare, 'stock-service/src/old.md', 'o\n')
    git(bare, 'add', '-A'); git(bare, 'commit', '-qm', 'four')
    git(bare, 'rm', '-q', 'stock-service/src/old.md')
    write(bare, 'web/src/old.md', 'w\n')
    write(bare, 'stock-service/CLAUDE.md', 'Stock. Read `src/old.md`.\n')
    git(bare, 'add', '-A'); git(bare, 'commit', '-qm', 'five')
    r = run('--repo', bare)
    assert ('  path    stock-service/CLAUDE.md:1  src/old.md  (git knew it; it is gone or was moved)'
            in r.stdout.splitlines()), r.stdout


def test_a_deviation_that_listed_a_found_path_is_now_a_gap_to_remove(bare):
    """021/SC-005."""
    monorepo(bare)
    root_deviation(bare, {'rule': 'S18', 'reason': 'r', 'fix': 'f', 'names': ['src/orders/README.md']})
    out = doctor(bare).stdout
    assert '  GAP  S18 listed under deviations but conforms now: remove the entry' in out.splitlines(), out
    assert 'DEBT S18' not in out


def unreleased_and_the_release_after():
    """`CHANGELOG.md` from `## Unreleased` down to 0.15.0, the last release without this feature: the line stands
    in that span after any number of later releases (a span counted in headings breaks at the second one)."""
    lines = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8').splitlines()
    return lines[lines.index('## Unreleased'):next(n for n, line in enumerate(lines) if line.startswith('## 0.15.0'))]


@pytest.mark.private
def test_the_changelog_and_the_texts_say_a_path_found_under_a_project_root_is_not_reported():
    """021/FR-004, 021/FR-005, 021/SC-006."""
    said = [line for line in unreleased_and_the_release_after()
            if all(word in line for word in ('S18', 'project root', 'conforms now'))]
    assert len(said) == 1, said
    grep = subprocess.run(['git', '-C', str(REPO), 'grep', '-n', 'found under', '--', SCRIPT, 'README.md'],
                          capture_output=True, text=True, encoding='utf-8')
    hits = grep.stdout.splitlines()
    assert any(h.startswith(SCRIPT + ':') for h in hits), hits
    limits = (REPO / 'README.md').read_text(encoding='utf-8').split('Known limits', 1)[1]
    assert any(h.startswith('README.md:') and h.split(':', 2)[2] in limits for h in hits), hits
