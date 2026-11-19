"""The gate on a runner the project chooses: the job and steps of the template, and what is said of them (spec 009)."""
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

from test_standard import DOCTOR, SCAFFOLD, SCRIPTS, feature, run
from test_kit_gate import KIT, REPO, TEMPLATE, TEMPLATE_IN_GIT, VERSION, commit, git, make_p, start_repo, write

DETECT = SCRIPTS / 'kit_detect.py'
BASH_REASON = 'a step of the gate is bash, run as on a Linux runner'
linux_only = pytest.mark.skipif(sys.platform == 'win32', reason=BASH_REASON)
RUNS_ON = "${{ fromJSON(vars.KIT_GATE_RUNNER || '\"ubuntu-latest\"') }}"
JOB_IF = ("github.event_name != 'pull_request' || (github.event.pull_request.head.repo.full_name == github.repository"
          " && github.event.pull_request.user.login != 'dependabot[bot]')")
NO_PYTHON = '::error::This runner has no python3 of 3.9 or newer with venv and ensurepip: the standard was NOT checked.'
NO_GIT = '::error::This runner has no git: the standard was NOT checked.'
CHECK = 'python ../kit/plugins/francis-kit/skills/kit-init/scripts/kit_gate.py --repo .'
CHECKOUT, SETUP_PYTHON = 'actions/checkout@', 'actions/setup-python@'
PIP_LINE = ('pip', 'python -m pip', 'python3 -m pip')


def text():
    return TEMPLATE.read_text(encoding='utf-8')


def job():
    return yaml.safe_load(text().replace('{{KIT_REF}}', 'v0.0.0'))['jobs']['standard']


def step(name):
    found = [s for s in job()['steps'] if s.get('name') == name]
    assert len(found) == 1, (name, [s.get('name') or s.get('uses') for s in job()['steps']])
    return found[0]


def using(action):
    return [s for s in job()['steps'] if s.get('uses', '').startswith(action)]


def git_grep(pattern, *paths, fixed=False):
    """What `git grep -c [-F] <pattern> -- <paths>` prints; empty when nothing matched."""
    r = subprocess.run(['git', 'grep', '-c', *(['-F'] if fixed else []), pattern, '--', *paths],
                       cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode in (0, 1), r.stderr
    return r.stdout


def keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from keys(value)


BASH = shutil.which('bash')


def bash(script, cwd, env):
    return subprocess.run([BASH, '-e', '-c', script], cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8')


def program(directory, name, body):
    """A directory to stand in a PATH, holding one program written as a `sh` script."""
    directory.mkdir(exist_ok=True)
    (directory / name).write_text('#!/bin/sh\n' + body + '\n', encoding='utf-8')
    (directory / name).chmod(0o755)
    return str(directory)


def test_the_runner_comes_from_the_variable_and_forks_start_no_gate():
    """009/FR-001, 009/FR-002, 009/FR-003, SC-001."""
    standard = job()
    assert standard['runs-on'] == RUNS_ON
    assert standard['if'] == JOB_IF
    assert 'vars' not in standard['if']
    assert 'defaults' not in set(keys(yaml.safe_load(text().replace('{{KIT_REF}}', 'v0.0.0'))))
    assert standard['timeout-minutes'] == 5


def test_a_gate_of_this_version_passes_s14_and_a_runner_typed_into_it_does_not(tmp_path):
    """009/FR-001, SC-002: S14 is not loosened."""
    git(tmp_path, 'init', '-q')
    assert run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python').returncode == 0
    gate = tmp_path / '.github' / 'workflows' / 'kit-gate.yml'
    written = gate.read_text(encoding='utf-8')
    assert 'PASS S14' in run(DOCTOR, '--repo', tmp_path).stdout
    assert 'KIT_GATE_RUNNER' in written and 'runs-on: ubuntu-latest' not in written
    gate.write_text(written.replace('runs-on: ' + RUNS_ON, 'runs-on: [self-hosted, team-runner]'), encoding='utf-8')
    assert 'runs-on: [self-hosted, team-runner]' in gate.read_text(encoding='utf-8')
    assert 'not the gate of this kit version' in run(DOCTOR, '--repo', tmp_path).stdout


def test_the_runner_is_checked_before_any_checkout():
    """009/FR-004, SC-004: what the text of the step says."""
    steps = job()['steps']
    assert [s.get('name') for s in steps[:2]] == ['Secret present?', 'Runner ready?']
    ready = steps[1]
    assert ready['if'] == "vars.KIT_GATE_RUNNER != ''"
    assert steps.index(using(CHECKOUT)[0]) > 1
    for words in ('(3, 9)', 'venv', 'ensurepip', NO_PYTHON, NO_GIT):
        assert words in ready['run'], words


@linux_only
def test_a_runner_that_lacks_python_or_git_is_named_and_one_that_has_both_passes(tmp_path):
    """009/FR-004, SC-004: the step run by bash."""
    ready = step('Runner ready?')['run']
    real_git = shutil.which('git')
    failing = program(tmp_path / 'failing', 'python3', 'exit 1')
    only_git = program(tmp_path / 'git', 'git', f'exec "{real_git}" "$@"')
    real_python = program(tmp_path / 'python', 'python3', f'exec "{sys.executable}" "$@"')
    for path in (failing, only_git):
        r = bash(ready, tmp_path, {'PATH': path})
        assert r.returncode == 1 and NO_PYTHON in r.stdout and NO_GIT not in r.stdout, (path, r.stdout, r.stderr)
    r = bash(ready, tmp_path, {'PATH': real_python})
    assert r.returncode == 1 and NO_GIT in r.stdout and NO_PYTHON not in r.stdout, r.stdout + r.stderr
    r = bash(ready, tmp_path, {'PATH': os.pathsep.join([real_python, only_git])})
    assert r.returncode == 0 and '::' not in r.stdout, r.stdout + r.stderr


def test_setup_python_runs_only_where_no_runner_is_chosen_and_no_step_reads_the_secret_step():
    """009/FR-003, 009/FR-005, SC-005."""
    setup = using(SETUP_PYTHON)
    assert len(setup) == 1 and setup[0]['if'] == "vars.KIT_GATE_RUNNER == ''"
    assert setup[0]['with'] == {'python-version': '3.12'}
    with_if = [s.get('name') or s['uses'] for s in job()['steps'] if 'if' in s]
    assert with_if == ['Runner ready?', setup[0]['uses'], 'Leave nothing behind']
    assert git_grep('steps.secret', TEMPLATE_IN_GIT) == ''


def test_pyyaml_goes_into_an_environment_of_the_runners_temp_directory():
    """009/FR-006, SC-006: what the text of the steps says; 008/FR-008 as modified."""
    python = step('Python for the checks')
    for words in ('python3 -m venv', '$RUNNER_TEMP/kit-gate-venv', 'pyyaml==6.0.3', '--no-cache-dir', '$GITHUB_PATH'):
        assert words in python['run'], words
    assert text().count('--no-cache-dir') == 1
    others = [s for s in job()['steps'] if 'run' in s and s is not python]
    for s in others:
        assert not [l for l in s['run'].splitlines() if l.strip().startswith(PIP_LINE)], s['name']
    assert step('Standard')['run'].splitlines() == [CHECK]
    names = [s.get('name') for s in job()['steps']]
    assert names.index('Python for the checks') < names.index('Standard')


@pytest.fixture(scope='module')
def checks_env(tmp_path_factory):
    """The step `Python for the checks` run once by bash, as on a runner: its environment and what it left."""
    base = tmp_path_factory.mktemp('runner')
    temp, home, cache = base / 'temp', base / 'home', base / 'cache'
    for d in (temp, home, cache):
        d.mkdir()
    github_path = base / 'github_path'
    github_path.touch()
    env = dict(os.environ, RUNNER_TEMP=str(temp), HOME=str(home), XDG_CACHE_HOME=str(cache), GITHUB_PATH=str(github_path))

    def system_yaml():
        r = subprocess.run(['python3', '-c', 'import yaml'], env=env, capture_output=True, text=True, encoding='utf-8')
        return r.returncode, r.stderr

    before = system_yaml()
    done = bash(step('Python for the checks')['run'], base, env)
    return {'done': done, 'temp': temp, 'home': home, 'cache': cache, 'github_path': github_path,
            'bin': temp / 'kit-gate-venv' / 'bin', 'yaml': (before, system_yaml())}


@linux_only
def test_the_environment_holds_pyyaml_and_nothing_lands_in_home(checks_env):
    """009/FR-006, SC-006: the step run by bash, the network reachable."""
    done = checks_env['done']
    assert done.returncode == 0, done.stdout + done.stderr
    r = subprocess.run([str(checks_env['bin'] / 'python'), '-c', 'import yaml'], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert list(checks_env['home'].iterdir()) == [] and list(checks_env['cache'].iterdir()) == []
    assert checks_env['github_path'].read_text(encoding='utf-8').splitlines() == [str(checks_env['bin'])]
    before, after = checks_env['yaml']
    assert before == after


def test_the_gate_writes_only_below_one_directory_of_the_workspace():
    """009/FR-007, SC-007: what the text of the steps says."""
    project, kit = using(CHECKOUT)
    assert project['with']['path'] == '.kit-gate/project' and project['with']['fetch-depth'] == 0
    assert kit['with']['path'] == '.kit-gate/kit' and kit['with']['repository'] == 'dangthinh104/francis-ai-coworking'
    assert project['with']['persist-credentials'] is False and kit['with']['persist-credentials'] is False
    assert git_grep('.kit/', TEMPLATE_IN_GIT, fixed=True) == ''
    assert step('Standard')['working-directory'] == '.kit-gate/project'
    assert [s['name'] for s in job()['steps'] if 'working-directory' in s] == ['Standard']


def decoy(root):
    """A project the gate must not judge: a git checkout with a manifest of one root and a spec with no Status line."""
    write(root / '.claude' / 'kit.yml', 'version: 1\nprojects:\n  - name: decoy\n    root: .\n')
    feature(root, '001-x', status=None)
    start_repo(root)
    commit(root)


def outside_the_gate(workspace):
    return sorted(str(p.relative_to(workspace)) for p in workspace.rglob('*')
                  if p.relative_to(workspace).parts[0] != '.kit-gate')


def run_the_check(workspace, env):
    standard = step('Standard')
    project = workspace / standard['working-directory']
    status = git(project, 'status', '--porcelain')
    root = outside_the_gate(workspace)
    r = bash(standard['run'], project, env)
    assert outside_the_gate(workspace) == root
    assert git(project, 'status', '--porcelain') == status
    return r


@linux_only
def test_the_check_judges_the_project_below_the_gate_and_not_the_workspace(checks_env, tmp_path):
    """009/FR-007, 009/FR-006, SC-008."""
    assert checks_env['done'].returncode == 0, checks_env['done'].stderr
    env = dict(os.environ, PATH=str(checks_env['bin']) + os.pathsep + os.environ['PATH'])

    def workspace(name, project_at_root):
        ws = tmp_path / name
        if project_at_root:
            make_p(ws)
        else:
            ws.mkdir()
            decoy(ws)
        shutil.copytree(KIT, ws / '.kit-gate' / 'kit' / 'plugins' / 'francis-kit', ignore=shutil.ignore_patterns('__pycache__'))
        if project_at_root:
            decoy(ws / '.kit-gate' / 'project')
        else:
            make_p(ws / '.kit-gate' / 'project')
        return ws

    r = run_the_check(workspace('decoy-at-root', False), env)
    assert r.returncode == 0 and r.stdout.splitlines()[-1].startswith('kit-gate: passed: '), r.stdout + r.stderr
    r = run_the_check(workspace('project-at-root', True), env)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and '001-x' in out and r.stdout.splitlines()[-1].startswith('kit-gate: FAILED: '), out


def test_the_last_step_leaves_nothing_behind_also_after_a_failure():
    """009/FR-008, SC-009: what the text of the step says."""
    last = job()['steps'][-1]
    assert last['name'] == 'Leave nothing behind' and last['if'] == 'always()' and 'working-directory' not in last


@linux_only
def test_the_last_step_removes_the_gates_directory_and_environment_only(tmp_path):
    """009/FR-008, SC-009: the step run by bash, twice."""
    ws, temp = tmp_path / 'ws', tmp_path / 'temp'
    write(ws / 'keep.txt', 'k\n')
    write(ws / '.kit-gate' / 'project' / 'x', 'x\n')
    write(temp / 'kit-gate-venv' / 'y', 'y\n')
    write(temp / 'other' / 'z', 'z\n')
    env = dict(os.environ, RUNNER_TEMP=str(temp))
    for _ in range(2):
        r = bash(step('Leave nothing behind')['run'], ws, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (ws / 'keep.txt').is_file() and (temp / 'other' / 'z').is_file()
        assert not (ws / '.kit-gate').exists() and not (temp / 'kit-gate-venv').exists()


def test_a_missing_secret_is_never_a_warning():
    """009/FR-003, SC-010: the text; the step run by bash is `GATE_CASES` of `tests/test_standard.py`."""
    assert git_grep('::warning::', TEMPLATE_IN_GIT) == ''
    first = job()['steps'][0]
    assert first['name'] == 'Secret present?' and 'id' not in first and 'if' not in first
    assert '::error::KIT_READ_TOKEN is not set' in first['run'] and 'GITHUB_OUTPUT' not in first['run']


@pytest.mark.private
def test_the_readme_says_how_the_runner_is_chosen_and_what_it_costs():
    """009/FR-009, SC-011."""
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    section = readme[readme.index('## The gate in each project'):readme.index('## Releasing the kit')]
    for words in ('KIT_GATE_RUNNER', '"team-runner"', '["self-hosted", "team-runner"]', 'not JSON', 'the job waits', 'ensurepip',
                  '.kit-gate', 'does not start', 'may push a branch', 'rewrites a workflow file'):
        assert words in section, words
    for gone in ('gets a warning', 'On every pull request'):
        assert gone not in section, gone


def detect_warnings(repo):
    r = run(DETECT, '--repo', repo)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)['warnings']


def test_detect_names_the_variable_where_every_workflow_runs_on_the_projects_own_runner(tmp_path):
    """009/FR-010, SC-012."""
    gate = text().replace('{{KIT_REF}}', 'v' + VERSION)
    for runs_on, own in (('[self-hosted, vm]', True), ('ubuntu-latest', False)):
        repo = tmp_path / runs_on.strip('[]').replace(', ', '-')
        repo.mkdir()
        git(repo, 'init', '-q')
        write(repo / '.github' / 'workflows' / 'deploy.yml', f'on: push\njobs:\n  d:\n    runs-on: {runs_on}\n    steps: []\n')
        for with_gate in (False, True):
            if with_gate:
                write(repo / '.github' / 'workflows' / 'kit-gate.yml', gate)
            warnings = detect_warnings(repo)
            assert not [w for w in warnings if 'may never start' in w], warnings
            named = [w for w in warnings if 'own runner' in w]
            if own:
                assert named and all('KIT_GATE_RUNNER' in w for w in named), (with_gate, warnings)
            else:
                assert not named, (with_gate, warnings)


@pytest.mark.private
def test_the_skills_the_changelog_and_the_standard_name_the_variable():
    """009/FR-011, 009/FR-012, SC-013."""
    skills = 'plugins/francis-kit/skills/'
    named = git_grep('KIT_GATE_RUNNER', skills + 'kit-init/SKILL.md', skills + 'kit-adopt/SKILL.md', 'CHANGELOG.md')
    assert len(named.splitlines()) == 3, named
    rows = text().splitlines()
    head = rows[:rows.index('on:')]
    assert [l for l in head if l.startswith('#') and 'KIT_GATE_RUNNER' in l]
    assert git_grep('delete it and record S14', skills + 'kit-adopt/SKILL.md') == ''
    assert git_grep('only get a warning', skills + 'kit-init/SKILL.md') == ''
    adopt = (REPO / skills / 'kit-adopt' / 'SKILL.md').read_text(encoding='utf-8').splitlines()
    assert not [l for l in adopt if 'has no runner' in l or 'remove the scaffolded' in l]
    recorded = [l for l in adopt if 'record S14' in l]
    assert recorded and all('none of the three' in l for l in recorded), recorded
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.9.0')]
    line = [l for l in unreleased.splitlines() if 'KIT_GATE_RUNNER' in l]
    assert len(line) == 1, unreleased
    for words in ('Dependabot', 'gate template changed', 'no longer starts', 'writing its gate again'):
        assert words in line[0], words
    assert git_grep('on every pull request', 'plugins/francis-kit/STANDARD.md') == ''
