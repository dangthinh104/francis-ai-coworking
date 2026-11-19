"""claude_md_shrink.py merged: a change to a moved block survives the merge of a shrink (specs/022).

Fixture F of 022 in neutral words: the shrink moves the Workers block to its own skill while the other side
changes "10 workers" to "6 workers" in CLAUDE.md.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SHRINK = ROOT / 'plugins' / 'francis-kit' / 'skills' / 'shrink-claude-md' / 'scripts' / 'claude_md_shrink.py'
SKILL = ROOT / 'plugins' / 'francis-kit' / 'skills' / 'shrink-claude-md' / 'SKILL.md'

TARGET = '.claude/skills/workers/SKILL.md'
POINTER = f'Workers: `{TARGET}`.'
BASE = ('# Project\n\nRule one for every session.\n\n## Workers\n\n'
        'The engine runs 10 workers, each in its own process.\nEach worker reads jobs from the shared queue only.\n')
SIX = 'The engine runs 6 workers, each in its own process.'
SHRUNK = f'# Project\n\nRule one for every session.\n\n{POINTER}\n'
MOVED = '## Workers\n\nThe engine runs 10 workers, each in its own process.\nEach worker reads jobs from the shared queue only.\n'
ON_MAIN = BASE.replace('10 workers', '6 workers')
ASK = 'Ask before any push to production.'


def lost(side, n=7, text=SIX):
    return f'LOST  {side}  CLAUDE.md:{n}  {text}'


@pytest.fixture
def env(tmp_path):
    """Git with no system or global configuration of the machine, so autocrlf, signing or a default branch name
    cannot change a fixture."""
    empty = tmp_path / 'gitconfig'
    empty.write_bytes(b'')
    values = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(empty), GIT_EDITOR='true',
                  GIT_CEILING_DIRECTORIES=str(tmp_path))
    values.pop('GIT_DIR', None)
    values.pop('GIT_WORK_TREE', None)
    return values


def git(repo, env, *args, check=True):
    r = subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                       capture_output=True, text=True, encoding='utf-8', env=env)
    if check:
        assert r.returncode == 0, r.stdout + r.stderr
    return r


def merged(repo, env, *args):
    return subprocess.run([sys.executable, str(SHRINK), 'merged', *args], cwd=repo, capture_output=True, text=True,
                          encoding='utf-8', env=env)


def lost_lines(r):
    return sorted(line for line in r.stdout.splitlines() if line.startswith('LOST'))


def write(repo, path, text, newline='\n'):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.replace('\n', newline).encode('utf-8'))


def commit(repo, env, files, message):
    for path, text in files.items():
        if text is None:
            git(repo, env, 'rm', '-q', path)
        else:
            write(repo, path, text)
            git(repo, env, 'add', path)
    git(repo, env, 'commit', '-qm', message)


def make_f(repo, env, main=ON_MAIN, shrunk=SHRUNK, moved=MOVED, extra=None):
    """F: base on main, `shrink` moves the block, `main` changes it (when `main` differs from the base)."""
    repo.mkdir(exist_ok=True)
    git(repo, env, 'init', '-q', '-b', 'main')
    git(repo, env, 'config', 'core.autocrlf', 'false')
    commit(repo, env, {'CLAUDE.md': BASE, **(extra or {})}, 'base')
    git(repo, env, 'checkout', '-qb', 'shrink')
    commit(repo, env, {'CLAUDE.md': shrunk, TARGET: moved}, 'shrink')
    git(repo, env, 'checkout', '-q', 'main')
    if main != BASE:
        commit(repo, env, {'CLAUDE.md': main}, 'change on main')
    return repo


def merge_main_into_shrink(repo, env, resolve=True):
    git(repo, env, 'checkout', '-q', 'shrink')
    git(repo, env, 'merge', '--no-edit', 'main', check=False)
    if resolve:
        git(repo, env, 'checkout', '--ours', '--', 'CLAUDE.md')
        git(repo, env, 'add', 'CLAUDE.md')


@pytest.fixture
def f(tmp_path, env):
    return make_f(tmp_path / 'repo', env)


def test_sc_001_a_committed_merge_that_kept_the_pointer_names_the_lost_line(f, env):
    merge_main_into_shrink(f, env)
    git(f, env, 'commit', '--no-edit', '-q')
    r = merged(f, env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert lost_lines(r) == [lost('HEAD^2')]
    assert POINTER not in r.stdout


def test_sc_002_an_unfinished_merge_exits_2_while_unmerged_then_names_the_line(f, env):
    merge_main_into_shrink(f, env, resolve=False)
    assert git(f, env, 'ls-files', '-u').stdout.strip()
    assert_unusable(merged(f, env), 'the merge still has unmerged files')
    git(f, env, 'checkout', '--ours', '--', 'CLAUDE.md')
    git(f, env, 'add', 'CLAUDE.md')
    r = merged(f, env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert lost_lines(r) == [lost('MERGE_HEAD')]


def test_sc_003_the_change_carried_into_the_target_counts_once_added(f, env):
    merge_main_into_shrink(f, env)
    write(f, TARGET, MOVED.replace('The engine runs 10 workers, each in its own process.', SIX))
    r = merged(f, env)
    assert r.returncode == 1 and lost_lines(r) == [lost('MERGE_HEAD')], r.stdout + r.stderr
    git(f, env, 'add', TARGET)
    r = merged(f, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr


def test_sc_004_the_other_direction_unfinished(f, env):
    git(f, env, 'merge', '--no-edit', 'shrink', check=False)
    git(f, env, 'checkout', '--theirs', '--', 'CLAUDE.md')
    git(f, env, 'add', 'CLAUDE.md')
    r = merged(f, env)
    assert r.returncode == 1 and lost_lines(r) == [lost('HEAD')], r.stdout + r.stderr


def test_sc_005_the_other_direction_committed(f, env):
    git(f, env, 'merge', '--no-edit', 'shrink', check=False)
    git(f, env, 'checkout', '--theirs', '--', 'CLAUDE.md')
    git(f, env, 'add', 'CLAUDE.md')
    git(f, env, 'commit', '--no-edit', '-q')
    r = merged(f, env)
    assert r.returncode == 1 and lost_lines(r) == [lost('HEAD^1')], r.stdout + r.stderr


def rebase_in_progress(repo, env):
    return any(Path(repo, git(repo, env, 'rev-parse', '--git-path', name).stdout.strip()).exists()
               for name in ('rebase-merge', 'rebase-apply'))


def test_sc_006_a_rebase_onto_a_shrunk_main(tmp_path, env):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, env, 'init', '-q', '-b', 'main')
    git(repo, env, 'config', 'core.autocrlf', 'false')
    commit(repo, env, {'CLAUDE.md': BASE}, 'base')
    git(repo, env, 'checkout', '-qb', 'fix')
    commit(repo, env, {'CLAUDE.md': ON_MAIN}, 'six')
    git(repo, env, 'checkout', '-q', 'main')
    commit(repo, env, {'CLAUDE.md': SHRUNK, TARGET: MOVED}, 'shrink')
    git(repo, env, 'checkout', '-q', 'fix')
    assert git(repo, env, 'rebase', 'main', check=False).returncode != 0
    assert_unusable(merged(repo, env, '--side', 'ORIG_HEAD', '--side', 'main'), 'a rebase is in progress')
    git(repo, env, 'checkout', '--ours', '--', 'CLAUDE.md')
    git(repo, env, 'add', 'CLAUDE.md')
    git(repo, env, 'rebase', '--continue')       # git drops the commit that became empty
    assert not rebase_in_progress(repo, env)
    assert git(repo, env, 'rev-parse', 'HEAD').stdout == git(repo, env, 'rev-parse', 'main').stdout
    r = merged(repo, env, '--side', 'ORIG_HEAD', '--side', 'main')
    assert r.returncode == 1 and lost_lines(r) == [lost('ORIG_HEAD')], r.stdout + r.stderr
    assert_unusable(merged(repo, env), 'no merge to check')


def test_sc_006_b_a_rebase_of_the_shrink_branch_onto_main(f, env):
    git(f, env, 'checkout', '-q', 'shrink')
    assert git(f, env, 'rebase', 'main', check=False).returncode != 0
    git(f, env, 'checkout', '--theirs', '--', 'CLAUDE.md')
    git(f, env, 'add', 'CLAUDE.md')
    git(f, env, 'rebase', '--continue')
    assert not rebase_in_progress(f, env)
    r = merged(f, env, '--side', 'ORIG_HEAD', '--side', 'main')
    assert r.returncode == 1 and lost_lines(r) == [lost('main')], r.stdout + r.stderr


def test_sc_007_a_clone_with_autocrlf(tmp_path, env):
    origin = make_f(tmp_path / 'origin', env)
    clone = tmp_path / 'clone'
    git(tmp_path, env, 'clone', '-q', '-c', 'core.autocrlf=true', str(origin), str(clone))
    git(clone, env, 'checkout', '-q', 'shrink')
    git(clone, env, 'merge', '--no-edit', 'main', check=False)
    git(clone, env, 'checkout', '--ours', '--', 'CLAUDE.md')
    assert b'\r\n' in (clone / 'CLAUDE.md').read_bytes()
    git(clone, env, 'add', 'CLAUDE.md')
    r = merged(clone, env)
    assert r.returncode == 1 and lost_lines(r) == [lost('MERGE_HEAD')], r.stdout + r.stderr
    write(clone, TARGET, MOVED.replace('The engine runs 10 workers, each in its own process.', SIX), '\r\n')
    git(clone, env, 'add', TARGET)
    r = merged(clone, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr


def test_sc_008_a_copy_elsewhere_does_not_hide_the_loss(tmp_path, env):
    main = ON_MAIN.replace(SIX + '\n', SIX + '\nRule one for every session.\n')
    assert main.splitlines()[7] == 'Rule one for every session.'
    repo = make_f(tmp_path / 'repo', env, main=main)
    merge_main_into_shrink(repo, env)
    git(repo, env, 'commit', '--no-edit', '-q')
    r = merged(repo, env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert lost_lines(r) == sorted([lost('HEAD^2'), lost('HEAD^2', 8, 'Rule one for every session.')])


def test_sc_009_a_target_changed_by_the_shrink(tmp_path, env):
    repo = make_f(tmp_path / 'repo', env, moved=MOVED.replace('10 workers', '8 workers'))
    merge_main_into_shrink(repo, env)
    git(repo, env, 'commit', '--no-edit', '-q')
    r = merged(repo, env)
    assert r.returncode == 1 and lost_lines(r) == [lost('HEAD^2')], r.stdout + r.stderr
    for line, code in ((SIX, 0), ('The engine runs six workers, each in its own process.', 1)):
        write(repo, TARGET, MOVED.replace('The engine runs 10 workers, each in its own process.', line))
        git(repo, env, 'add', TARGET)
        git(repo, env, 'commit', '--amend', '--no-edit', '-q')
        r = merged(repo, env)
        assert r.returncode == code, line + r.stdout + r.stderr
        assert lost_lines(r) == ([lost('HEAD^2')] if code else [])


def test_sc_010_f1_a_change_outside_the_block_loses_nothing(tmp_path, env):
    repo = make_f(tmp_path / 'repo', env, main=BASE.replace('Rule one for every session.', 'Rule one, for every session.'))
    git(repo, env, 'checkout', '-q', 'shrink')
    git(repo, env, 'merge', '--no-edit', 'main')
    r = merged(repo, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr


def test_sc_010_f2_the_same_addition_on_both_sides(tmp_path, env):
    repo = make_f(tmp_path / 'repo', env, main=BASE + ASK + '\n', shrunk=SHRUNK + ASK + '\n')
    merge_main_into_shrink(repo, env)
    git(repo, env, 'commit', '--no-edit', '-q')
    assert (repo / 'CLAUDE.md').read_text(encoding='utf-8').count(ASK) == 1
    r = merged(repo, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr
    write(repo, 'CLAUDE.md', SHRUNK)
    git(repo, env, 'add', 'CLAUDE.md')
    git(repo, env, 'commit', '--amend', '--no-edit', '-q')
    r = merged(repo, env)
    assert r.returncode == 1, r.stdout + r.stderr
    assert lost_lines(r) == sorted([lost('HEAD^1', 6, ASK), lost('HEAD^2', 9, ASK)])


def assert_unusable(r, reason):
    """Exit 2 for the reason named, not a crash turned into exit 2 by the script's last resort."""
    assert r.returncode == 2 and reason in r.stderr and not lost_lines(r), r.stdout + r.stderr
    assert 'could not finish' not in r.stderr, r.stderr


def test_sc_011_nothing_can_be_checked(tmp_path, env):
    repo = make_f(tmp_path / 'repo', env)
    git(repo, env, 'checkout', '-q', 'shrink')
    assert_unusable(merged(repo, env), 'no merge to check')
    assert_unusable(merged(repo, env, '--side', 'main'), '--side is given 1 time(s)')
    plain = tmp_path / 'plain'
    plain.mkdir()
    assert_unusable(merged(plain, env), 'not a git repository')
    git(repo, env, 'checkout', '-qb', 'gone', 'main~1')
    commit(repo, env, {'CLAUDE.md': None, 'other.md': 'x\n'}, 'remove the file')
    assert_unusable(merged(repo, env, '--side', 'shrink', '--side', 'gone'), 'CLAUDE.md does not exist at gone')


def test_sc_011_an_octopus_merge(tmp_path, env):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, env, 'init', '-q', '-b', 'main')
    commit(repo, env, {'CLAUDE.md': BASE}, 'base')
    for name in ('a', 'b', 'c'):
        git(repo, env, 'checkout', '-qb', name, 'main')
        commit(repo, env, {f'{name}.md': name + '\n'}, name)
    git(repo, env, 'checkout', '-q', 'a')
    git(repo, env, 'merge', '--no-edit', '-q', 'b', 'c')
    assert len(git(repo, env, 'rev-list', '--parents', '-n1', 'HEAD').stdout.split()) == 4
    assert_unusable(merged(repo, env), 'HEAD is a merge of 3 parents')


def test_sc_011_a_criss_cross_merge(tmp_path, env):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, env, 'init', '-q', '-b', 'main')
    commit(repo, env, {'CLAUDE.md': BASE}, 'base')
    for name in ('x', 'y'):
        git(repo, env, 'checkout', '-qb', name, 'main')
        commit(repo, env, {f'{name}.md': name + '\n'}, name)
    x, y = (git(repo, env, 'rev-parse', name).stdout.strip() for name in ('x', 'y'))
    git(repo, env, 'checkout', '-q', 'x')
    git(repo, env, 'merge', '--no-edit', '-q', y)
    git(repo, env, 'checkout', '-q', 'y')
    git(repo, env, 'merge', '--no-edit', '-q', x)
    git(repo, env, 'checkout', '-q', 'x')
    git(repo, env, 'merge', '--no-edit', '-q', '--no-ff', 'y')
    assert len(git(repo, env, 'merge-base', '--all', 'HEAD^1', 'HEAD^2').stdout.split()) == 2
    assert_unusable(merged(repo, env), 'have 2 merge bases')


def test_an_unfinished_octopus_merge(tmp_path, env):
    """022/FR-003: a merge of more than two sides, not yet committed, is not judged on its first MERGE_HEAD."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, env, 'init', '-q', '-b', 'main')
    commit(repo, env, {'CLAUDE.md': BASE}, 'base')
    for name in ('a', 'b', 'c'):
        git(repo, env, 'checkout', '-qb', name, 'main')
        commit(repo, env, {f'{name}.md': name + '\n'}, name)
    git(repo, env, 'checkout', '-q', 'a')
    git(repo, env, 'merge', '--no-commit', '-q', 'b', 'c')
    assert_unusable(merged(repo, env), 'MERGE_HEAD names 2 commits')


def test_a_merge_in_progress_on_a_merge_commit_judges_head_and_merge_head(f, env):
    """022/FR-002: an unfinished merge comes first, even when HEAD is itself a merge commit."""
    merge_main_into_shrink(f, env)
    git(f, env, 'commit', '--no-edit', '-q')
    git(f, env, 'checkout', '-qb', 'other', 'main')
    commit(f, env, {'other.md': 'other\n'}, 'other')
    git(f, env, 'checkout', '-q', 'shrink')
    git(f, env, 'merge', '--no-commit', '--no-ff', '-q', 'other')
    r = merged(f, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr
    assert 'HEAD and MERGE_HEAD' in r.stdout


@pytest.mark.parametrize('attribute', ['-diff', 'binary'])
def test_a_file_git_would_diff_as_binary_is_still_judged(tmp_path, env, attribute):
    """022, a line a side added: .gitattributes cannot hide the lines of the file from the diff."""
    repo = make_f(tmp_path / 'repo', env, extra={'.gitattributes': f'CLAUDE.md {attribute}\n'})
    merge_main_into_shrink(repo, env)
    git(repo, env, 'commit', '--no-edit', '-q')
    r = merged(repo, env)
    assert r.returncode == 1 and lost_lines(r) == [lost('HEAD^2')], r.stdout + r.stderr


def test_a_users_inter_hunk_context_adds_no_line(tmp_path, env):
    """022, a line a side added: diff.interHunkContext would join two hunks and count the line between as added."""
    repo = make_f(tmp_path / 'repo', env, main=BASE.replace('Rule one for', 'Rule one, for').replace('10 workers', '6 workers'))
    git(repo, env, 'config', 'diff.interHunkContext', '10')
    git(repo, env, 'checkout', '-qb', 'side', 'main~1')
    commit(repo, env, {'side.md': 'side\n'}, 'side')
    git(repo, env, 'merge', '--no-edit', '-q', 'main')
    write(repo, 'CLAUDE.md', (repo / 'CLAUDE.md').read_text(encoding='utf-8').replace('## Workers\n', ''))
    git(repo, env, 'add', 'CLAUDE.md')
    git(repo, env, 'commit', '--amend', '--no-edit', '-q')
    r = merged(repo, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr


def test_a_file_name_with_glob_characters_is_read_literally(tmp_path, env):
    """022, the file: `--file CLAUDE[1].md` is that file, not a pattern that also matches CLAUDE1.md."""
    name = 'CLAUDE[1].md'
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, env, 'init', '-q', '-b', 'main')
    git(repo, env, 'config', 'core.autocrlf', 'false')
    commit(repo, env, {name: BASE, 'CLAUDE1.md': 'x\n'}, 'base')
    git(repo, env, 'checkout', '-qb', 'shrink')
    commit(repo, env, {name: SHRUNK, TARGET: MOVED}, 'shrink')
    git(repo, env, 'checkout', '-q', 'main')
    commit(repo, env, {name: ON_MAIN, 'CLAUDE1.md': 'x\n' + ''.join(f'line {n}\n' for n in range(40))}, 'main')
    git(repo, env, 'checkout', '-q', 'shrink')
    git(repo, env, 'merge', '--no-edit', 'main', check=False)
    git(repo, env, '--literal-pathspecs', 'checkout', '--ours', '--', name)
    git(repo, env, '--literal-pathspecs', 'add', name)
    git(repo, env, 'commit', '--no-edit', '-q')
    r = merged(repo, env, '--file', name)
    assert r.returncode == 1, r.stdout + r.stderr
    assert lost_lines(r) == [f'LOST  HEAD^2  {name}:7  {SIX}']


def test_a_block_the_other_side_deleted_does_not_count_against_a_new_copy(tmp_path, env):
    """022, short: the copies that the other side removed are allowed for (the min(0, O - base) term)."""
    base = '# Project\n\nRule one for every session.\n\n## History\n\n```\nold\n```\n'
    deleted = '# Project\n\nRule one for every session.\n'
    block = '\n## Run\n\n```\nmake\n```\n'
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, env, 'init', '-q', '-b', 'main')
    git(repo, env, 'config', 'core.autocrlf', 'false')
    commit(repo, env, {'CLAUDE.md': base}, 'base')
    git(repo, env, 'checkout', '-qb', 's')
    commit(repo, env, {'CLAUDE.md': deleted}, 'delete the history')
    git(repo, env, 'checkout', '-q', 'main')
    commit(repo, env, {'CLAUDE.md': base + block}, 'add a block')
    git(repo, env, 'checkout', '-q', 's')
    git(repo, env, 'merge', '--no-edit', 'main', check=False)
    write(repo, 'CLAUDE.md', deleted + block)
    git(repo, env, 'add', 'CLAUDE.md')
    git(repo, env, 'commit', '--no-edit', '-q')
    r = merged(repo, env)
    assert r.returncode == 0 and not lost_lines(r), r.stdout + r.stderr


SENTENCES = [
    'When a branch that applied a shrink meets a change to a block that moved, carry the change, including a '
    'deletion, into the block\'s target: keeping the pointer in CLAUDE.md drops it.',
    'Run `merged` after every merge where either side applied a shrink, before or after the merge is committed, and '
    'after every finished rebase of such a branch with `--side ORIG_HEAD --side <upstream>`; paste its output.',
    'A `LOST` line you accept, such as an approved `delete: history` block the other side edited, still exits 1: '
    'name it in the pull request with the reason; before a squash-and-merge, merge the target branch into the pull '
    'request\'s branch and run `merged` there.',
]


@pytest.mark.parametrize('sentence', SENTENCES, ids=['FR-004', 'FR-005', 'FR-006'])
def test_sc_012_the_skill_holds_each_sentence(sentence):
    rel = SKILL.relative_to(ROOT).as_posix()
    r = subprocess.run(['git', '-C', str(ROOT), 'grep', '-nF', sentence, '--', rel], capture_output=True, text=True,
                       encoding='utf-8')
    assert len(r.stdout.splitlines()) == 1, r.stdout + r.stderr


@pytest.mark.private
def test_the_changelog_names_the_feature_under_unreleased():
    changelog = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.16.1')]
    assert 'Spec 022' in unreleased and '`merged`' in unreleased
