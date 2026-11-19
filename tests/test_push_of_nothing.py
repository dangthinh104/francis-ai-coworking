"""A push that sends nothing prints only its verdict (spec 020)."""
import pytest
import os
import re
import subprocess

from test_kit_gate import REPO, git
from test_gate_hook import (NOTHING, SHELLS, ZERO, bad_spec, by_each_shell, cache, h, h_bare, h_filled, head, hook,
                            k, make_path, stamp)
from test_hook_guards import hook_section, without_git_variables

LEFT_OUT = ('kit-gate: the lines of the checks are left out on a push that sends nothing: '
            'run sh .githooks/pre-push to read them')


def remote_args(repo, tmp_path):
    """The two arguments git hands every `pre-push`: the remote's name and its location, a bare clone."""
    bare = tmp_path / 'remote.git'
    git(tmp_path, 'clone', '-q', '--bare', str(repo), str(bare))
    return ('origin', bare.as_posix())


@by_each_shell
def test_git_starting_the_hook_with_an_empty_input_prints_only_the_verdict(shell, h, tmp_path):
    """020/FR-001, FR-002, SC-001."""
    path = make_path(tmp_path / 'bin')
    args = remote_args(h, tmp_path)
    r = hook(shell, h, path, args=args)
    assert (r.code, r.lines) == (0, ['kit-gate: passed: ' + stamp(h), NOTHING]), r
    bad_spec(h)
    r = hook(shell, h, path, args=args)
    assert r.code == 0 and len(r.lines) == 3 and r.lines[0].startswith('kit-gate: FAILED: doctor, lint'), r
    assert r.lines[1:] == [LEFT_OUT, NOTHING], r


@by_each_shell
def test_a_hand_run_and_a_push_that_sends_something_print_every_line(shell, h, tmp_path):
    """020/FR-001, SC-002."""
    path = make_path(tmp_path / 'bin')
    pushed = f'refs/heads/main {head(h)} refs/heads/main {ZERO}\n'
    by_git = hook(shell, h, path, stdin=pushed, args=remote_args(h, tmp_path))
    by_hand = hook(shell, h, path, stdin=pushed)
    assert by_git.code == by_hand.code == 0 and by_git.lines == by_hand.lines, (by_git, by_hand)
    assert by_git.starting('kit-gate: doctor') and by_git.lines[-1] == f'kit-gate: pushed refs/heads/main at {head(h)}'
    nothing = hook(shell, h, path)
    assert nothing.code == 0 and nothing.lines == by_git.lines[:-1] + [NOTHING], (nothing, by_git)


@by_each_shell
def test_an_exit_2_on_a_push_of_nothing_is_passed_on_whole(shell, h, tmp_path):
    """020/FR-001, SC-003."""
    checker = cache(h) / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_gate.py'
    checker.write_bytes(b'import sys\nprint("x")\nprint("y")\nsys.exit(2)\n')
    r = hook(shell, h, make_path(tmp_path / 'bin'), args=remote_args(h, tmp_path))
    assert (r.code, r.lines) == (0, ['x', 'y']), r


def test_a_real_push_of_nothing_from_a_red_tree_prints_three_lines(h, tmp_path):
    """020/FR-001, FR-002, SC-004: git starts the hook with an empty input when the remote already holds the commit."""
    path = make_path(tmp_path / 'bin')
    green = hook(SHELLS[0], h, path, args=remote_args(h, tmp_path))
    assert green.code == 0 and not [l for l in green.lines if 'are left out' in l], green
    bad_spec(h)
    remote = tmp_path / 'pushed.git'
    git(tmp_path, 'init', '-q', '--bare', str(remote))
    git(h, 'remote', 'add', 'origin', remote.as_posix())
    git(h, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
    git(h, 'config', 'core.hooksPath', '.githooks')
    env = without_git_variables()
    env['PATH'] = path + os.pathsep + env.get('PATH', '')
    done = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=h, capture_output=True, env=env)
    said = (done.stdout + done.stderr).decode('utf-8').splitlines()
    assert done.returncode == 0, said
    failed = [i for i, l in enumerate(said) if l.startswith('kit-gate: FAILED: doctor, lint')]
    assert len(failed) == 1 and said[failed[0] + 1:failed[0] + 3] == [LEFT_OUT, NOTHING], said
    assert not [l for l in said if l.startswith('kit-gate: doctor')], said


@pytest.mark.private
def test_the_readme_says_a_push_of_nothing_prints_only_its_verdict():
    """020/FR-003, SC-005."""
    lines = hook_section().splitlines()
    assert [l for l in lines if 'no other line' in l], lines
    assert [l for l in lines if 'sh .githooks/pre-push to read them' in l], lines


@pytest.mark.private
def test_the_changelog_says_hook_projects_write_their_gate_again_for_the_verdict_alone():
    """020/FR-004, SC-006: under `## Unreleased`, or under the release that moved it there."""
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    # down to 0.15.0, the last release without this feature: holds after any number of later releases
    section = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.15.0')]
    found = [l for l in section.splitlines() if 'only its verdict' in l]
    assert len(found) == 1, section
    for words in ('writes its gate again', 'hook', 'workflow'):
        assert words in found[0], words
