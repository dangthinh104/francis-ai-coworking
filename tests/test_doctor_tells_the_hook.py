"""Spec 027: the doctor tells a clone that git does not start the kit's hook."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import link
from test_gate_hook import (HOOK_FILE, SHELLS, WINDOWS, ZERO, h, h_bare, h_filled, head, hook, k,  # noqa: F401
                            make_path, p)
from test_kit_gate import REPO, git
from test_standard import DOCTOR

NOTE = 'note: S14: core.hooksPath is '
NOTE_A = ('note: S14: core.hooksPath is {}, not .githooks, so git does not start .githooks/pre-push at a push from '
          'this clone: switch it on with git config core.hooksPath .githooks')
NOTE_B = ("note: S14: core.hooksPath is {}, not .githooks, and this clone's hooks are run by {}: have that hook "
          'manager start .githooks/pre-push at a push')
NOT_SET = NOTE_A.format('not set')


@pytest.fixture
def quiet_env(tmp_path):
    """The environment of every run of 027's criteria: no global or system config of the machine, no `CI`."""
    empty = tmp_path / 'global-config'
    empty.write_text('', encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if k != 'CI'}
    env.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM='1')
    return env


def doctor(repo, env, *args):
    return subprocess.run([sys.executable, str(DOCTOR), '--repo', str(repo), *args], capture_output=True,
                          text=True, encoding='utf-8', env=env)


def notes(result):
    return [l for l in result.stderr.splitlines() if l.startswith(NOTE)]


def summary_head(result):
    line = next(l for l in result.stdout.splitlines() if l.startswith('summary:'))
    return line[:line.index(' skipped') + len(' skipped')]


def hooks_path(repo, value):
    git(repo, 'config', '--local', 'core.hooksPath', value)


def test_sc001_a_clone_that_has_not_switched_the_hook_on_is_told(h, quiet_env):
    """027/FR-001, 027/SC-001."""
    told = doctor(h, quiet_env)
    assert notes(told) == [NOT_SET], told.stderr
    hooks_path(h, '.githooks')
    on = doctor(h, quiet_env)
    assert notes(on) == [], on.stderr
    assert (told.returncode, summary_head(told)) == (on.returncode, summary_head(on)), (told.stdout, on.stdout)


def same_paths(h):
    githooks = h / '.githooks'
    values = ['.githooks/', githooks.as_posix()]
    if WINDOWS:
        values += [str(githooks), str(githooks).swapcase()]
    return values


def test_sc002_every_spelling_of_githooks_is_switched_on(h, quiet_env):
    """027/SC-002."""
    for value in same_paths(h):
        hooks_path(h, value)
        assert notes(doctor(h, quiet_env)) == [], value


def test_sc002_a_link_to_githooks_is_switched_on(h, quiet_env, tmp_path):
    """027/SC-002: a symbolic link from outside `H`, where the system lets the test make one."""
    outside = tmp_path / 'outside' / 'hooks'
    outside.parent.mkdir()
    link(outside, h / '.githooks')
    hooks_path(h, str(outside))
    assert notes(doctor(h, quiet_env)) == []


def test_sc002_other_values_get_note_a_and_a_global_githooks_none(h, quiet_env):
    """027/SC-002."""
    hooks_path(h, '.git/hooks')
    assert notes(doctor(h, quiet_env)) == [NOTE_A.format('.git/hooks')]
    hooks_path(h, '')
    assert notes(doctor(h, quiet_env)) == [NOT_SET]
    git(h, 'config', '--local', '--unset', 'core.hooksPath')
    Path(quiet_env['GIT_CONFIG_GLOBAL']).write_text('[core]\n\thooksPath = .githooks\n', encoding='utf-8')
    assert notes(doctor(h, quiet_env)) == []


def test_sc003_no_note_where_the_rule_does_not_apply(h, p, quiet_env, tmp_path):
    """027/FR-003, 027/SC-003."""
    assert notes(doctor(p, quiet_env)) == []
    for value in ('true', 'TRUE'):
        assert notes(doctor(h, dict(quiet_env, CI=value))) == [], value
    assert notes(doctor(h, dict(quiet_env, CI='false'))) == [NOT_SET]
    for args in (('--roots',), ('--lint-features', '.')):
        r = doctor(h, quiet_env, *args)
        assert r.returncode == 0 and notes(r) == [] and NOTE not in r.stdout, (args, r.stdout, r.stderr)
    copy = Path(shutil.copytree(h, tmp_path / 'copy', ignore=shutil.ignore_patterns('.git')))
    assert notes(doctor(copy, quiet_env)) == []
    hook_file = h / HOOK_FILE
    text = hook_file.read_text(encoding='utf-8')
    hook_file.write_text(''.join(l for l in text.splitlines(True) if not l.startswith('KIT_REF=')), encoding='utf-8')
    assert notes(doctor(h, quiet_env)) == []
    hook_file.unlink()
    r = doctor(h, quiet_env)
    assert [l for l in r.stdout.splitlines() if 'missing or empty' in l] and notes(r) == [], r.stdout


def test_sc004_a_hook_manager_gets_no_command(h, quiet_env):
    """027/FR-002, 027/SC-004."""
    (h / '.husky').mkdir()
    hooks_path(h, '.husky')
    r = doctor(h, quiet_env)
    assert notes(r) == [NOTE_B.format('.husky', 'core.hooksPath=.husky, .husky/')], r.stderr
    assert 'git config core.hooksPath' not in r.stdout + r.stderr
    (h / '.husky').rmdir()
    git(h, 'config', '--local', '--unset', 'core.hooksPath')
    (h / '.pre-commit-config.yaml').write_text('repos: []\n', encoding='utf-8')
    r = doctor(h, quiet_env)
    assert notes(r) == [NOTE_B.format('not set', '.pre-commit-config.yaml')], r.stderr
    assert 'git config core.hooksPath' not in r.stdout + r.stderr


def test_sc004_a_global_value_other_than_githooks_is_a_hook_manager(h, quiet_env, tmp_path):
    """027/FR-002, 027/SC-004: the owner's answer of 2026-11-24."""
    own = (tmp_path / 'own-hooks').as_posix()
    Path(quiet_env['GIT_CONFIG_GLOBAL']).write_text(f'[core]\n\thooksPath = {own}\n', encoding='utf-8')
    r = doctor(h, quiet_env)
    assert notes(r) == [NOTE_B.format(own, f'core.hooksPath={own}')], r.stderr
    assert 'git config core.hooksPath' not in r.stdout + r.stderr
    hooks_path(h, '.git/hooks')
    assert notes(doctor(h, quiet_env)) == [NOTE_A.format('.git/hooks')]


def test_sc005_the_hook_run_by_hand_holds_the_note_under_the_doctor(h, quiet_env, tmp_path):
    """027/SC-005: kit_gate.py joins the doctor's standard error into its standard output (008/FR-004)."""
    env = {k: quiet_env[k] for k in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_NOSYSTEM')}
    env['CI'] = ''
    pushed = f'refs/heads/main {head(h)} refs/heads/main {ZERO}\n'
    told = hook(SHELLS[0], h, make_path(tmp_path / 'bin'), stdin=pushed, env=env)
    assert told.lines.count(NOT_SET) == 1, told
    at = told.lines.index(NOT_SET)
    assert told.lines.index('kit-gate: doctor') < at < told.lines.index('kit-gate: roots'), told
    hooks_path(h, '.githooks')
    on = hook(SHELLS[0], h, make_path(tmp_path / 'bin-on'), stdin=pushed, env=env)
    assert NOT_SET not in on.lines, on
    assert (told.code, told.verdicts) == (on.code, on.verdicts), (told, on)


def push(h, env):
    """A push that sends something: `HEAD` to a bare remote that does not hold it, git starting the hook."""
    done = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=h, capture_output=True,
                          text=True, encoding='utf-8', errors='replace', env=env)
    return done.stdout + done.stderr


def test_sc006_a_copy_in_git_hooks_runs_and_tells_the_clone(h, quiet_env, tmp_path):
    """027/SC-006: git starts the copy, not the tracked file, and the copy's log says so."""
    remote = tmp_path / 'remote.git'
    git(tmp_path, 'init', '-q', '--bare', str(remote))
    git(h, 'remote', 'add', 'origin', remote.as_posix())
    copy = h / '.git' / 'hooks' / 'pre-push'
    copy.parent.mkdir(exist_ok=True)
    shutil.copyfile(h / HOOK_FILE, copy)
    copy.chmod(0o755)
    log = push(h, quiet_env)
    assert 'kit-gate: doctor' in log and log.count(NOT_SET) == 1, log
    git(remote, 'update-ref', '-d', 'refs/heads/main')
    hooks_path(h, '.githooks')
    log = push(h, quiet_env)
    assert 'kit-gate: doctor' in log and NOTE not in log, log


def readme_hook_section():
    text = (REPO / 'README.md').read_text(encoding='utf-8')
    return text[text.index('### The gate as a git hook'):text.index('## Releasing the kit')]


@pytest.mark.private
def test_sc007_the_readme_says_the_note_turns_nothing_red():
    """027/FR-004, 027/SC-007."""
    found = [l for l in readme_hook_section().splitlines()
             if 'note' in l and 'nothing red' in l and 'git config core.hooksPath .githooks' in l]
    assert len(found) == 1, found


@pytest.mark.private
def test_sc008_the_changelog_holds_the_line():
    """027/FR-005, 027/SC-008."""
    text = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = text[text.index('## Unreleased'):text.index('\n## 0.18.0')]   # the line moves under its release
    assert [l for l in unreleased.splitlines()
            if 'core.hooksPath' in l and 'note' in l and 'CI' in l and 'nothing red' in l], unreleased
