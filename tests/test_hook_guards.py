"""What the hook gate guards, and a push that sends nothing is never refused (spec 017)."""
import pytest
import os
import re
import subprocess
from pathlib import Path

from test_standard import DOCTOR, run
from test_kit_gate import REPO, git
from test_gate_hook import (DASH, HOOK, HOOK_FILE, NO_PYTHON, ONLY_DELETIONS, SHELLS, WINDOWS, ZERO, by_each_shell,
                            bad_spec, cache, fetch_failed, git_grep, h, h_bare, h_empty, h_filled, head, hook, k,
                            make_path, p, stamp)

GUARD = "guards the author's clone, not the release"
REFUSES_NOTHING = 'kit-gate: nothing was pushed, so this verdict refuses nothing'
NOTE = ('  note: the gate is the hook: it guards pushes from the clones that switched it on; '
        'a merge on GitHub and a push from any other clone are not judged')
COUNTED = re.compile(r', (\d+) notes?$')
HAND_RUN = 'echo "HEAD $(git rev-parse HEAD) HEAD 0" | sh .githooks/pre-push'
DOCS = ('plugins/francis-kit/STANDARD.md', 'plugins/francis-kit/skills/kit-init/SKILL.md',
        'plugins/francis-kit/skills/kit-adopt/SKILL.md', 'README.md')


def pushed_line(repo):
    return f'refs/heads/main {head(repo)} refs/heads/main {ZERO}\n'


def hook_section():
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    return readme[readme.index('### The gate as a git hook'):readme.index('## Releasing the kit')]


@pytest.mark.private
def test_four_documents_say_the_hook_guards_the_clone_not_the_release():
    """017/FR-001 to FR-004, SC-001."""
    counted = git_grep('-c', GUARD, '--', *DOCS)
    assert sorted(l.rsplit(':', 1)[0] for l in counted.splitlines()) == sorted(DOCS), counted
    for doc in DOCS:
        found = [l for l in (REPO / doc).read_text(encoding='utf-8').splitlines() if GUARD in l]
        assert len(found) == 1 and 'not judged' in found[0], (doc, found)
        if doc.endswith('STANDARD.md'):
            assert found[0].startswith('| S14 |'), found
        elif doc.endswith('SKILL.md'):
            assert 'gate: hook' in found[0], found
        else:
            assert found[0] in hook_section().splitlines(), found


def deploys(repo, branches):
    kit = repo / '.claude' / 'kit.yml'
    text = kit.read_text(encoding='utf-8')
    assert text.count('deploy_branches: []') == 1 and 'pr_target: main' in text
    kit.write_text(text.replace('deploy_branches: []', f'deploy_branches: {branches}'), encoding='utf-8')


def test_the_doctor_says_what_the_hook_guards_where_every_merge_is_a_release(h, p):
    """017/FR-005, SC-002."""
    quiet = run(DOCTOR, '--repo', h)
    assert not [l for l in quiet.stdout.splitlines() if 'the gate is the hook' in l], quiet.stdout
    deploys(h, '[main]')
    told = run(DOCTOR, '--repo', h)
    lines = told.stdout.splitlines()
    deploy_note = [i for i, l in enumerate(lines) if l.startswith('  note: pull requests target')]
    assert len(deploy_note) == 1 and lines[deploy_note[0] + 1] == NOTE, told.stdout
    assert [l for l in lines if 'the gate is the hook' in l] == [NOTE]
    summary = [[l for l in r.stdout.splitlines() if l.startswith('summary:')] for r in (quiet, told)]
    found = [COUNTED.search(s[0]) for s in summary]
    counted = [(s[0][:m.start()] if m else s[0], int(m.group(1)) if m else 0) for s, m in zip(summary, found)]
    assert (told.returncode, counted[1][0]) == (quiet.returncode, counted[0][0]) and told.returncode == 0, told.stdout
    assert counted[1][1] == counted[0][1] + 2, summary          # 029/SC-009: the deploy note and this one
    deploys(p, '[main]')
    out = run(DOCTOR, '--repo', p).stdout
    assert [l for l in out.splitlines() if l.startswith('  note: pull requests target')], out
    assert 'the gate is the hook' not in out, out


@by_each_shell
def test_a_red_tree_with_an_empty_input_prints_the_verdict_and_refuses_nothing(shell, h, tmp_path):
    """017/FR-006, FR-007, SC-003."""
    bad_spec(h)
    r = hook(shell, h, make_path(tmp_path / 'bin'))
    assert r.code == 0 and r.starting('kit-gate: FAILED: doctor, lint') and r.lines[-1] == REFUSES_NOTHING, r


def without_git_variables():
    dropped = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_PREFIX') + (('MSYSTEM',) if WINDOWS else ())
    return {k: v for k, v in os.environ.items() if k not in dropped}


def test_a_push_of_nothing_from_a_red_tree_is_not_refused(h, tmp_path):
    """017/FR-006, SC-004: git starts the hook with an empty input when the remote already holds the commit."""
    bad_spec(h)
    remote = tmp_path / 'remote.git'
    git(tmp_path, 'init', '-q', '--bare', str(remote))
    git(h, 'remote', 'add', 'origin', remote.as_posix())
    git(h, 'push', '-q', 'origin', 'HEAD:refs/heads/main')
    git(h, 'config', 'core.hooksPath', '.githooks')
    env = without_git_variables()
    env['PATH'] = make_path(tmp_path / 'bin') + os.pathsep + env.get('PATH', '')
    done = subprocess.run(['git', 'push', 'origin', 'HEAD:refs/heads/main'], cwd=h, capture_output=True, env=env)
    said = (done.stdout + done.stderr).decode('utf-8')
    assert done.returncode == 0, said
    assert [l for l in said.splitlines() if l.startswith('kit-gate: FAILED')], said
    assert REFUSES_NOTHING in said.splitlines(), said


@by_each_shell
def test_an_input_line_still_gets_the_exit_status_of_the_check(shell, h, tmp_path):
    """017/FR-006, FR-008, SC-005."""
    bad_spec(h)
    path = make_path(tmp_path / 'bin')
    r = hook(shell, h, path, stdin=pushed_line(h))
    assert r.code == 1 and r.starting('kit-gate: FAILED'), r
    with_sh = path + os.pathsep + str(Path(SHELLS[0]).parent)
    done = subprocess.run([shell, '-c', HAND_RUN], cwd=h, capture_output=True,
                          env=dict(without_git_variables(), PATH=with_sh))
    lines = done.stdout.decode('utf-8').splitlines()
    assert done.returncode == 1 and lines[-1] == f'kit-gate: pushed HEAD at {head(h)}', (done, lines)


@by_each_shell
def test_an_empty_input_is_never_refused_where_the_hook_cannot_check(shell, h, h_empty, tmp_path):
    """017/FR-006, SC-006: no Python, no cache after the fetch, a checker that exits 2."""
    no_python = make_path(tmp_path / 'none', pythons=())
    path = make_path(tmp_path / 'bin')
    nowhere = (tmp_path / 'no-such-kit').as_posix()
    git(h_empty, 'config', 'kit.gateSource', nowhere)
    checker = cache(h) / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_gate.py'
    checker.write_bytes(b'import sys\nsys.exit(2)\n')
    for stdin, codes in (('', (0, 0, 0)), (pushed_line(h), (1, 1, 2))):
        r = hook(shell, h, no_python, stdin=stdin)
        assert (r.code, r.out, r.err.splitlines()) == (codes[0], '', [NO_PYTHON]), r
        r = hook(shell, h_empty, path, stdin=stdin.replace(head(h), head(h_empty)))
        assert (r.code, r.out, r.err.splitlines()) == (codes[1], '', [fetch_failed(nowhere, h_empty)]), r
        r = hook(shell, h, path, stdin=stdin)
        assert r.code == codes[2] and not r.starting('kit-gate: nothing') and not r.starting('kit-gate: pushed'), r


@by_each_shell
def test_a_green_tree_with_an_empty_input_names_what_the_verdict_refuses(shell, h, tmp_path):
    """017/FR-007, SC-007."""
    path = make_path(tmp_path / 'bin')
    r = hook(shell, h, path)
    assert r.code == 0 and r.lines[-2:] == ['kit-gate: passed: ' + stamp(h), REFUSES_NOTHING], r
    r = hook(shell, h, path, stdin=f'(delete) {ZERO} refs/heads/x {head(h)}\n')
    assert (r.code, r.lines) == (0, [ONLY_DELETIONS]), r


@pytest.mark.private
def test_the_readme_says_a_push_of_nothing_is_never_refused():
    """017/FR-008, SC-008."""
    section = hook_section()
    for words in ('never refused', 'sh .githooks/pre-push', HAND_RUN):
        assert words in section, words


def test_the_comment_of_the_hook_says_it_fails_closed_and_what_it_needs():
    """017/FR-009, SC-009."""
    rows = HOOK.read_text(encoding='utf-8').splitlines()
    comment = '\n'.join(rows[:rows.index('KIT_REF={{KIT_REF}}')])
    for words in ('fails closed', '3.9', 'PyYAML', 'PATH'):
        assert words in comment, words
    assert rows[0] == '#!/bin/sh'
    if DASH:
        r = subprocess.run([DASH, '-n', str(HOOK)], capture_output=True, text=True, encoding='utf-8')
        assert r.returncode == 0, r.stderr


@pytest.mark.private
def test_the_changelog_says_hook_projects_write_their_gate_again():
    """017/FR-010, SC-010."""
    assert git_grep('-c', 'writes its gate again', '--', 'CHANGELOG.md').strip()
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.14.0')]   # the line moves under its release
    assert [l for l in unreleased.splitlines() if 'writes its gate again' in l and 'hook' in l], unreleased
