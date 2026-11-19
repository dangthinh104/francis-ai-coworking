"""kit_detect.py reads where a project's jobs run and suggests where its gate runs (spec 011)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DETECT = REPO / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_detect.py'
QUESTION = 'Does GitHub start jobs on GitHub-hosted runners (such as ubuntu-latest) for this account?'
WARNING = ('every workflow here runs on the project\'s own runner: kit-gate.yml asks for ubuntu-latest unless the '
           'repository variable KIT_GATE_RUNNER names a runner, as JSON ("team-runner" or ["self-hosted", "team-runner"]); '
           'gate_choice says where the gate is suggested to run')


def runs(runs_on, run='pytest', extra=''):
    return f'    runs-on: {runs_on}\n{extra}    steps:\n      - run: {run}\n'


def uses(target):
    return f'    uses: {target}\n'


def wf(on, *jobs):
    """A workflow file: its `on`, then each job as (name, body)."""
    return f'on: {on}\njobs:\n' + ''.join(f'  {name}:\n{body}' for name, body in jobs)


PR_HOSTED = wf('pull_request', ('t', runs('ubuntu-latest')))
PR_OWN = wf('pull_request', ('t', runs('[self-hosted, ci-box]')))
PR_PROD = wf('pull_request', ('t', runs('[self-hosted, prod-box]')))
DEPLOY_PROD = wf('{push: {branches: [main]}}', ('d', runs('[self-hosted, prod-box]', 'rsync -a . host:/srv')))
OLD_GATE = wf('pull_request', ('standard', runs('ubuntu-latest', 'echo gate')))
GATES = "${{ vars.GATES_RUNNER || 'ubuntu-latest' }}"
BACKFILL = wf('workflow_dispatch', ('b', runs('[self-hosted, team-runner]', 'python backfill.py --deploy-check')))
MEMBERS_APP = {
    'kit-gate.yml': OLD_GATE,
    'tests.yml': wf('{pull_request: null, workflow_dispatch: null}', ('gates', uses('./.github/workflows/gates.yml'))),
    'gates.yml': wf('{workflow_call: null}', ('t', runs(GATES))),
    'deploy.yml': wf('{push: {branches: [main]}}', ('gates', uses('./.github/workflows/gates.yml')),
                     ('deploy', runs(GATES, 'ssh host docker compose up -d'))),
}
ORDERS = {name: wf('{push: {branches: [main]}, pull_request: null}', ('t', runs('ubuntu-latest')))
        for name in ('pytest.yml', 'spec-lint.yml')}


def git(repo, *args, env=None):
    r = subprocess.run(['git', *args], cwd=repo, capture_output=True, text=True, encoding='utf-8', env=env)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode('utf-8'))


def commit(repo):
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'commit', '-q', '--no-verify', '-m', 'files')


def make(root, workflows=(), files=()):
    """A throwaway repository: README.md, its workflow files and other files, one commit."""
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-q')
    write(root / 'README.md', '# t\n')
    for name, text in dict(workflows).items():
        write(root / '.github' / 'workflows' / name, text)
    for name, text in dict(files).items():
        write(root / name, text)
    commit(root)
    return root


def run_detect(repo, env=None):
    r = subprocess.run([sys.executable, str(DETECT), '--repo', str(repo)], cwd=repo, capture_output=True,
                       text=True, encoding='utf-8', env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout), r.stdout


def detect(repo, env=None):
    return run_detect(repo, env)[0]


def entry(out, name):
    found = [e for e in out['workflows'] if e['workflow'] == name]
    assert len(found) == 1, (name, out['workflows'])
    return found[0]


def top(repo):
    return Path(git(repo, 'rev-parse', '--show-toplevel'))


def hooks_path(repo, value):
    git(repo, 'config', '--local', 'core.hooksPath', value)


def test_workflows_lists_each_workflow_in_file_name_order(tmp_path):
    """011/FR-001, SC-001."""
    repo = make(tmp_path / 'r', {'ci.yml': PR_OWN, 'deploy.yml': DEPLOY_PROD, 'kit-gate.yml': OLD_GATE})
    out = detect(repo)
    assert out['workflows'] == [
        {'workflow': 'ci.yml', 'pull_requests': True, 'deploys': False, 'calls': [],
         'runners': {'hosted': [], 'own': [['self-hosted', 'ci-box']], 'unknown': []}},
        {'workflow': 'deploy.yml', 'pull_requests': False, 'deploys': True, 'calls': [],
         'runners': {'hosted': [], 'own': [['self-hosted', 'prod-box']], 'unknown': []}}]
    assert out['runners']['hosted'] == ['ubuntu-latest']       # runners still counts kit-gate.yml
    write(repo / '.github' / 'workflows' / 'broken.yml', 'on: [\n')
    commit(repo)
    out = detect(repo)
    assert [e['workflow'] for e in out['workflows']] == ['ci.yml', 'deploy.yml']
    assert any(w.startswith('broken.yml: could not be read') for w in out['warnings'])
    for name in ('B.yml', 'a.yml'):
        write(repo / '.github' / 'workflows' / name, PR_HOSTED)
    commit(repo)
    assert [e['workflow'] for e in detect(repo)['workflows']] == ['B.yml', 'a.yml', 'ci.yml', 'deploy.yml']
    assert detect(make(tmp_path / 'bare'))['workflows'] == []


def test_pull_requests_is_true_where_a_pull_request_starts_the_workflow(tmp_path):
    """011/FR-002, SC-002."""
    job = ('t', runs('ubuntu-latest'))
    shapes = {'text.yml': ('pull_request', True), 'list.yml': ('[push, pull_request_target]', True),
              'key.yml': ('{pull_request: {branches: [main]}}', True),
              'push.yml': ('{push: {branches: [main]}, workflow_dispatch: null}', False),
              'called.yml': ('workflow_call', False)}
    out = detect(make(tmp_path, {name: wf(on, job) for name, (on, _) in shapes.items()}))
    for name, (_, starts) in shapes.items():
        assert entry(out, name)['pull_requests'] is starts, name


def test_deploys_is_true_where_a_push_starts_it_and_it_has_deploy_hints(tmp_path):
    """011/FR-003, SC-003."""
    ci = wf('{pull_request: null, push: {branches: [main]}}', ('t', runs('ubuntu-latest')))
    out = detect(make(tmp_path, {'deploy.yml': DEPLOY_PROD, 'backfill.yml': BACKFILL, 'ci.yml': ci}))
    assert entry(out, 'deploy.yml')['deploys'] is True
    assert entry(out, 'backfill.yml')['deploys'] is False
    assert entry(out, 'ci.yml')['deploys'] is False
    pushes = {p['workflow']: p for p in out['push_workflows']}
    assert pushes['backfill.yml'] == {'workflow': 'backfill.yml', 'starts_on': 'not a push: check by hand',
                                      'deploy_hints': ['deploy']}
    assert pushes['ci.yml']['deploy_hints'] == []


def test_runners_of_an_entry_are_its_label_lists_and_texts_once_in_order(tmp_path):
    """011/FR-004, SC-004."""
    three = wf('push', ('a', runs('team-runner')), ('b', runs('[self-hosted, team-runner]')), ('c', runs('team-runner')))
    out = detect(make(tmp_path / 'three', {'w.yml': three}))
    assert entry(out, 'w.yml')['runners'] == {'hosted': [], 'own': [['team-runner'], ['self-hosted', 'team-runner']],
                                              'unknown': []}
    assert out['runners']['own'] == ['self-hosted, team-runner', 'team-runner']
    mixed = wf('push', ('a', runs('ubuntu-latest')), ('b', runs('${{ matrix.os }}')))
    assert entry(detect(make(tmp_path / 'mixed', {'w.yml': mixed})), 'w.yml')['runners'] == {
        'hosted': ['ubuntu-latest'], 'own': [], 'unknown': ['${{ matrix.os }}']}
    group = wf('push', ('a', runs('{group: big, labels: [self-hosted]}')))
    out = detect(make(tmp_path / 'group', {'w.yml': group}))
    assert entry(out, 'w.yml')['runners']['own'] == [['self-hosted']]
    assert out['runners']['own'] == ['self-hosted']


def test_a_called_file_is_followed_one_level(tmp_path):
    """011/FR-005, SC-005."""
    repo = make(tmp_path / 'h', MEMBERS_APP)
    out = detect(repo)
    tests = entry(out, 'tests.yml')
    assert tests['calls'] == ['gates.yml']
    assert tests['runners'] == {'hosted': [], 'own': [], 'unknown': [GATES]}
    write(repo / '.github' / 'workflows' / 'gates.yml',
          wf('{workflow_call: null}', ('t', runs(GATES)), ('inner', uses('./.github/workflows/inner.yml'))))
    write(repo / '.github' / 'workflows' / 'inner.yml', wf('workflow_call', ('i', runs('[self-hosted, inner-box]'))))
    commit(repo)
    tests = entry(detect(repo), 'tests.yml')
    assert 'inner-box' not in json.dumps(tests)
    assert tests['calls'] == ['gates.yml']
    assert tests['runners']['unknown'] == [GATES, './.github/workflows/inner.yml']
    calls = {'remote.yml': 'octo/ci/.github/workflows/t.yml@v1', 'missing.yml': './.github/workflows/gone.yml',
             'pushy.yml': './.github/workflows/on-push.yml'}
    files = {name: wf('pull_request', ('c', uses(target))) for name, target in calls.items()}
    files['on-push.yml'] = wf('push', ('p', runs('[self-hosted, push-box]')))
    out = detect(make(tmp_path / 'c', files))
    for name, target in calls.items():
        assert entry(out, name)['calls'] == [], name
        assert entry(out, name)['runners'] == {'hosted': [], 'own': [], 'unknown': [target]}, name


def test_hook_manager_names_the_local_hooks_path_and_the_seven_paths(tmp_path):
    """011/FR-006, SC-006."""
    repo = make(tmp_path / 'r', {'ci.yml': PR_HOSTED})
    assert detect(repo)['hook_manager'] == []
    write(repo / '.husky' / 'pre-commit', 'npx lint-staged\n')
    commit(repo)
    hooks_path(repo, '.hooks')
    assert detect(repo)['hook_manager'] == ['core.hooksPath=.hooks', '.husky/']
    write(repo / 'lefthook.yml', 'pre-commit: {}\n')
    write(repo / '.pre-commit-config.yaml', 'repos: []\n')
    assert detect(repo)['hook_manager'] == ['core.hooksPath=.hooks', '.husky/', 'lefthook.yml', '.pre-commit-config.yaml']

    plain = make(tmp_path / 'global', {'ci.yml': PR_HOSTED})
    config = tmp_path / 'global.gitconfig'
    write(config, '[core]\n\thooksPath = .hooks\n')
    env = {**os.environ, 'GIT_CONFIG_GLOBAL': str(config)}
    assert git(plain, 'config', '--get', 'core.hooksPath', env=env) == '.hooks'
    assert detect(plain, env)['hook_manager'] == []

    home = make(tmp_path / 'home', {'ci.yml': PR_HOSTED})
    hooks_path(home, '~/h')
    assert git(home, 'config', '--local', '--get', 'core.hooksPath') == '~/h'
    out = detect(home)
    assert out['hook_manager'] == ['core.hooksPath=~/h']
    assert out['gate_choice']['row'] == 1


def test_gits_own_hooks_directory_is_no_hook_manager(tmp_path):
    """011/FR-007, SC-007."""
    repo = make(tmp_path / 'orders', ORDERS)
    hooks = (top(repo) / '.git' / 'hooks').as_posix()
    for value in (hooks.replace('/', '\\'), hooks, hooks + '/', '.git/hooks'):
        hooks_path(repo, value)
        assert detect(repo)['hook_manager'] == [], value
    other = hooks + '-other'
    hooks_path(repo, other)
    assert detect(repo)['hook_manager'] == [f'core.hooksPath={other}']


def test_githooks_holding_only_the_kits_hook_is_no_hook_manager(tmp_path):
    """011/FR-008, SC-008."""
    repo = make(tmp_path / 'r', {'ci.yml': PR_HOSTED}, {'.githooks/pre-push': 'KIT_REF=v0.9.0\n'})
    githooks = repo / '.githooks'
    for value in ('.githooks', './.githooks/', (top(repo) / '.githooks').as_posix()):
        hooks_path(repo, value)
        assert detect(repo)['hook_manager'] == [], value
    hooks_path(repo, '.githooks')
    write(githooks / 'pre-commit', '#!/bin/sh\nexit 0\n')
    assert detect(repo)['hook_manager'] == ['core.hooksPath=.githooks', '.githooks/']
    (githooks / 'pre-commit').unlink()
    write(githooks / 'pre-push', '#!/bin/sh\nexit 0\n')
    assert detect(repo)['hook_manager'] == ['core.hooksPath=.githooks', '.githooks/']
    for text in ('', ' \n\n'):
        write(githooks / 'pre-push', text)
        out = detect(repo)
        assert out['hook_manager'] == [] and out['gate_choice']['row'] != 1, repr(text)
    shutil.rmtree(githooks)
    githooks.mkdir()
    out = detect(repo)
    assert out['hook_manager'] == [] and out['gate_choice']['row'] != 1


def why(row, file='', labels=None, other=''):
    """The one line of 011/FR-011 for a row."""
    names = json.dumps(labels)
    return {
        1: f"this clone's hooks are run by {file}: the kit's hook would replace them, so no gate is suggested",
        2: f'pull requests already start {file} on the runner {names}, which {other} deploys from: the hook is '
           f'suggested; answer runner where that risk is already accepted',
        3: f'{file} asks for the runner {other}, which only GitHub knows: the hook is suggested where GitHub starts '
           f'no hosted job for this account, and no gate where it does',
        4: f'pull requests already start {file} on the runner {names}, which no workflow that deploys deploys from: '
           f'whoever may push a branch can then run a step on that machine by a pull request',
        5: "no workflow a pull request starts asks for a runner of this repository's own or for one only GitHub knows",
    }[row]


PROD = ['self-hosted', 'prod-box']
CI_BOX = ['self-hosted', 'ci-box']
HUSKY = {'.husky/pre-commit': 'npx lint-staged\n'}
MATRIX = '    strategy: {matrix: {os: [ubuntu-latest, windows-latest]}}\n'
# name: (workflow files, other files, row, yes, no, labels, why); the last three are not repositories of SC-009.
SHAPES = {
    'husky-hosted': ({'ci.yml': PR_HOSTED}, HUSKY, 1, None, None, None, why(1, '.husky/')),
    'husky-own': ({'ci.yml': PR_OWN, 'deploy.yml': DEPLOY_PROD}, HUSKY, 1, None, None, None, why(1, '.husky/')),
    'prod': ({'ci.yml': PR_PROD, 'deploy.yml': DEPLOY_PROD}, {}, 2, 'hook', 'hook', PROD,
             why(2, 'ci.yml', PROD, 'deploy.yml')),
    'prod-defaults': ({'ci.yml': wf('pull_request', ('t', runs('[self-hosted, Linux, X64]'))), 'deploy.yml': DEPLOY_PROD},
                      {}, 2, 'hook', 'hook', ['self-hosted', 'Linux', 'X64'],
                      why(2, 'ci.yml', ['self-hosted', 'Linux', 'X64'], 'deploy.yml')),
    'safe-and-prod': ({'a.yml': PR_OWN, 'b.yml': PR_PROD, 'deploy.yml': DEPLOY_PROD}, {}, 2, 'hook', 'hook', PROD,
                      why(2, 'b.yml', PROD, 'deploy.yml')),
    'prod-and-matrix': ({'ci.yml': wf('pull_request', ('t', runs('[self-hosted, prod-box]')),
                                      ('m', runs('${{ matrix.os }}'))), 'deploy.yml': DEPLOY_PROD},
                        {}, 2, 'hook', 'hook', PROD, why(2, 'ci.yml', PROD, 'deploy.yml')),
    'unknown-deploy': ({'ci.yml': PR_OWN, 'deploy.yml': wf('{push: {branches: [main]}}', (
        'd', runs('${{ vars.DEPLOY_RUNNER }}', 'rsync -a . host:/srv')))},
        {}, 3, None, 'hook', None, why(3, 'deploy.yml', other='${{ vars.DEPLOY_RUNNER }}')),
    'remote-call': ({'ci.yml': wf('pull_request', ('c', uses('octo/ci/.github/workflows/t.yml@v1')))},
                    {}, 3, None, 'hook', None, why(3, 'ci.yml', other='octo/ci/.github/workflows/t.yml@v1')),
    'os-matrix': ({'ci.yml': wf('pull_request', ('t', runs('${{ matrix.os }}', extra=MATRIX)))},
                  {}, 3, None, 'hook', None, why(3, 'ci.yml', other='${{ matrix.os }}')),
    'safe-and-unknown': ({'a.yml': PR_OWN, 'b.yml': wf('pull_request', ('t', runs('${{ vars.CI_RUNNER }}'))),
                          'deploy.yml': DEPLOY_PROD},
                         {}, 3, None, 'hook', None, why(3, 'b.yml', other='${{ vars.CI_RUNNER }}')),
    'safe': ({'ci.yml': PR_OWN, 'deploy.yml': DEPLOY_PROD}, {}, 4, 'runner', 'runner', CI_BOX,
             why(4, 'ci.yml', CI_BOX)),
    'safe-called': ({'ci.yml': wf('[pull_request, workflow_call]', ('t', runs('[self-hosted, ci-box]'))),
                     'deploy.yml': wf('{push: {branches: [main]}}', ('ci', uses('./.github/workflows/ci.yml')),
                                      ('d', runs('[self-hosted, prod-box]', 'rsync -a . host:/srv')))},
                    {}, 4, 'runner', 'runner', CI_BOX, why(4, 'ci.yml', CI_BOX)),
    'hosted': ({'ci.yml': PR_HOSTED}, {}, 5, 'hosted', 'hook', None, why(5)),
    'deploy-only': ({'deploy.yml': DEPLOY_PROD}, {}, 5, 'hosted', 'hook', None, why(5)),
    'none': ({}, {}, 5, 'hosted', 'hook', None, why(5)),
    'one-label': ({'ci.yml': wf('pull_request', ('t', runs('ci-box'))), 'deploy.yml': DEPLOY_PROD},
                  {}, 4, 'runner', 'runner', ['ci-box'], why(4, 'ci.yml', ['ci-box'])),
    'prod-not-first': ({'a.yml': wf('pull_request', ('s', runs('[self-hosted, ci-box]')),
                                    ('p', runs('[self-hosted, prod-box]'))), 'deploy.yml': DEPLOY_PROD},
                       {}, 2, 'hook', 'hook', PROD, why(2, 'a.yml', PROD, 'deploy.yml')),
    'first-safe': ({'a.yml': wf('pull_request', ('h', runs('ubuntu-latest')), ('s', runs('[self-hosted, ARM64, ci-box]')),
                                ('g', runs('[self-hosted, gpu-box]'))),
                    'b.yml': wf('pull_request', ('o', runs('[self-hosted, other]'))), 'deploy.yml': DEPLOY_PROD},
                   {}, 4, 'runner', 'runner', ['self-hosted', 'ARM64', 'ci-box'],
                   why(4, 'a.yml', ['self-hosted', 'ARM64', 'ci-box'])),
}
OF_SC_009 = [name for name in SHAPES if name not in ('one-label', 'prod-not-first', 'first-safe')]


@pytest.fixture(scope='module')
def shapes(tmp_path_factory):
    base = tmp_path_factory.mktemp('shapes')
    return {name: run_detect(make(base / name, files, other)) for name, (files, other, *_) in SHAPES.items()}


def test_gate_choice_is_the_first_row_that_applies(shapes):
    """011/FR-009, SC-009."""
    for name in OF_SC_009:
        choice = shapes[name][0]['gate_choice']
        _, _, row, yes, no, _, _ = SHAPES[name]
        assert choice['question'] == QUESTION, name
        assert (choice['row'], choice['yes'], choice['no']) == (row, yes, no), (name, choice)
    deploy = entry(shapes['safe-called'][0], 'deploy.yml')
    assert CI_BOX in deploy['runners']['own'] and deploy['calls'] == ['ci.yml']


def test_labels_and_variable_are_the_list_the_reason_names(shapes):
    """011/FR-010, SC-010."""
    for name, (_, _, row, _, _, labels, _) in SHAPES.items():
        out, text = shapes[name]
        choice = out['gate_choice']
        assert choice['row'] == row and choice['labels'] == labels, (name, choice)
        if row in (2, 4):
            variable = json.dumps(labels[0]) if len(labels) == 1 else json.dumps(labels)
            assert choice['variable'] == variable, (name, choice)
        else:
            assert choice['variable'] is None, (name, choice)
    assert '"variable": "[\\"self-hosted\\", \\"ci-box\\"]"' in shapes['safe'][1]
    assert '"variable": "\\"ci-box\\""' in shapes['one-label'][1]
    assert '"variable": "[\\"self-hosted\\", \\"prod-box\\"]"' in shapes['prod'][1]


def test_why_is_the_one_line_of_its_row(shapes):
    """011/FR-011, SC-011."""
    for name, (*_, line) in SHAPES.items():
        found = shapes[name][0]['gate_choice']['why']
        assert found == line and '\n' not in found, (name, found)


@pytest.mark.private
def test_the_changelog_names_gate_choice_under_unreleased():
    """011/FR-012, SC-012."""
    r = subprocess.run(['git', 'grep', '-c', 'gate_choice', '--', 'CHANGELOG.md'], cwd=REPO, capture_output=True,
                       text=True, encoding='utf-8')
    assert r.stdout.strip(), r.stderr
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.10.0')]
    lines = [l for l in unreleased.splitlines() if 'gate_choice' in l]
    assert lines and all('KIT_GATE_RUNNER' not in l and 'kit_gate.py' not in l for l in lines), lines
    assert all(l in unreleased.splitlines() for l in changelog.splitlines() if 'gate_choice' in l)
    span = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.9.0')].splitlines()
    for word in ('KIT_GATE_RUNNER', 'kit_gate.py'):
        assert len([l for l in span if word in l]) == 1, word


def test_stock_service_is_row_5(tmp_path):
    """011/FR-005, 011/FR-009, SC-013."""
    files = {
        'kit-gate.yml': OLD_GATE,
        'ci.yml': wf('{pull_request: null, workflow_call: null}', ('t', runs('ubuntu-latest'))),
        'specops.yml': wf('{pull_request: null, push: {branches: [main]}}', ('s', runs('ubuntu-latest', 'python specops.py'))),
        'deploy.yml': wf('{push: {branches: [main]}}', ('ci', uses('./.github/workflows/ci.yml')),
                         ('deploy', runs('[self-hosted, team-runner]', 'rsync -a . host:/srv'))),
        'backfill.yml': BACKFILL,
    }
    out = detect(make(tmp_path, files))
    choice = out['gate_choice']
    assert (choice['row'], choice['yes'], choice['no']) == (5, 'hosted', 'hook'), choice
    deploy = entry(out, 'deploy.yml')
    assert deploy['calls'] == ['ci.yml']
    assert deploy['runners'] == {'hosted': ['ubuntu-latest'], 'own': [['self-hosted', 'team-runner']], 'unknown': []}


def test_options_service_is_row_5_and_its_warning_names_gate_choice(tmp_path):
    """011/FR-009, 011/FR-010, 009/FR-010, SC-014."""
    deploy = wf('{push: {branches: [prod]}, workflow_dispatch: {}}', ('test', runs('[self-hosted, prod-box]')),
                ('deploy', runs('[self-hosted, prod-box]', 'rsync -a . host:/srv')))
    out = detect(make(tmp_path, {'deploy.yml': deploy}))
    choice = out['gate_choice']
    assert (choice['row'], choice['yes'], choice['no'], choice['labels']) == (5, 'hosted', 'hook', None), choice
    named = [w for w in out['warnings'] if 'own runner' in w and 'KIT_GATE_RUNNER' in w and 'gate_choice' in w]
    assert named == [WARNING], out['warnings']
    assert not [w for w in out['warnings'] if 'ask the user which runner' in w]


def test_orders_is_row_5_with_no_hook_manager(tmp_path):
    """011/FR-007, 011/FR-009, SC-015."""
    repo = make(tmp_path, ORDERS)
    hooks_path(repo, (top(repo) / '.git' / 'hooks').as_posix().replace('/', '\\'))
    out = detect(repo)
    assert out['hook_manager'] == []
    choice = out['gate_choice']
    assert (choice['row'], choice['yes'], choice['no']) == (5, 'hosted', 'hook'), choice
    assert out['warnings'] == []


def test_members_app_is_row_3_through_its_called_file(tmp_path):
    """011/FR-005, 011/FR-009, 011/FR-010, 011/FR-011, SC-016."""
    choice = detect(make(tmp_path, MEMBERS_APP))['gate_choice']
    assert (choice['row'], choice['yes'], choice['no'], choice['labels'], choice['variable']) == \
        (3, None, 'hook', None, None), choice
    assert choice['why'] == why(3, 'tests.yml through gates.yml', other=GATES)
