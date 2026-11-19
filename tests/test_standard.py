"""kit_doctor.py and kit_scaffold.py."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import link

SCRIPTS = (Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit'
           / 'skills' / 'kit-init' / 'scripts')
DOCTOR, SCAFFOLD = SCRIPTS / 'kit_doctor.py', SCRIPTS / 'kit_scaffold.py'


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8')


def lines(result, kind):
    return [l.split()[1] for l in result.stdout.splitlines() if l.strip().startswith(kind)]


@pytest.fixture
def project(tmp_path):
    """A scaffolded Python project with a map, so that every rule passes."""
    assert run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python', '--name', 'demo').returncode == 0
    (tmp_path / 'docs' / 'diagrams').mkdir(parents=True)
    (tmp_path / 'docs' / 'ARCHITECTURE.md').write_text('<!-- kit:map revision=abcdef1 -->\n# map\n', encoding='utf-8')
    (tmp_path / 'docs' / 'diagrams' / 'map.refs.json').write_text(
        json.dumps({'meta': {'repository': {'revision': 'abcdef1'}}, 'sources': [{'path': 'CLAUDE.md', 'line': 1}]}), encoding='utf-8')
    fill(tmp_path, deviations=False)
    ci(tmp_path)
    return tmp_path


def fill(repo, deviations=True):
    """Fill in the facts the template leaves blank."""
    kit = repo / '.claude' / 'kit.yml'
    text = kit.read_text(encoding='utf-8')
    text = text.replace('pr_target:  ', 'pr_target: main  ').replace('deploy_branches:  ', 'deploy_branches: []  ')
    assert 'pr_target: main' in text and 'deploy_branches: []' in text
    if not deviations:
        text = text[:text.index('    deviations:')] + '    deviations: []\nscratch: []\n'
    kit.write_text(text, encoding='utf-8')
    write_own_words(repo)


def write_own_words(root):
    """What kit-init does after the questions: no blank of a template is left."""
    claude = root / 'CLAUDE.md'
    claude.write_text(claude.read_text(encoding='utf-8')
                      .replace('<one paragraph: what it does, for whom, where it runs>', 'a demo service')
                      .replace('<one line each: what breaks production, loses data or moves money. '
                               'Remove this line when the first hazard is written.>',
                               '- Pushing to main deploys.'), encoding='utf-8')
    law = root / '.specify' / 'memory' / 'constitution.md'
    law.write_text(law.read_text(encoding='utf-8')
                   .replace('### V. <project principle>\n<replace or remove>\n', '')
                   .replace('<date>', '2026-11-11'), encoding='utf-8')


def manifest(repo):
    import yaml
    return yaml.safe_load((repo / '.claude' / 'kit.yml').read_text(encoding='utf-8'))


def save(repo, data):
    import yaml
    (repo / '.claude' / 'kit.yml').write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')


def use_tracker(repo):
    data = manifest(repo)
    data['projects'][0]['tracker'] = {'type': 'jira', 'id_pattern': r'SCRUM-\d+'}
    save(repo, data)


def feature(root, name, status='Draft', ticket='none', tasks=None, plan=False):
    d = root / 'specs' / name
    d.mkdir(parents=True)
    head = f'# Feature Specification: {name}\n\n'
    if status:
        head += f'**Status**: {status}\n'
    if ticket:
        head += f'**Ticket**: {ticket}\n'
    (d / 'spec.md').write_text(head, encoding='utf-8')
    if plan:
        (d / 'plan.md').write_text('plan\n', encoding='utf-8')
    if tasks is not None:
        (d / 'tasks.md').write_text(tasks, encoding='utf-8')
    return d


def test_scaffold_creates_the_layout_and_never_overwrites(tmp_path):
    (tmp_path / 'CLAUDE.md').write_text('mine\n', encoding='utf-8')
    (tmp_path / '.claude').mkdir()
    (tmp_path / '.claude' / 'settings.json').write_text('{"hooks": {"x": 1}}', encoding='utf-8')
    r = run(SCAFFOLD, '--repo', tmp_path, '--profile', 'generic')
    assert r.returncode == 0 and 'kept    CLAUDE.md' in r.stdout
    assert (tmp_path / 'CLAUDE.md').read_text(encoding='utf-8') == 'mine\n'
    settings = json.loads((tmp_path / '.claude' / 'settings.json').read_text(encoding='utf-8'))
    assert settings['hooks'] == {'x': 1}
    assert settings['enabledPlugins']['francis-kit@francis-ai-coworking'] is True
    for rel in ('.claude/kit.yml', '.specify/memory/constitution.md', 'specs/README.md',
                'specs/_living/README.md', '.github/workflows/kit-gate.yml'):
        assert (tmp_path / rel).is_file(), rel
    again = run(SCAFFOLD, '--repo', tmp_path)
    assert 'create' not in again.stdout and 'update' not in again.stdout


def test_scaffold_dry_run_writes_nothing(tmp_path):
    (tmp_path / 'README.md').write_text('x', encoding='utf-8')
    assert run(SCAFFOLD, '--repo', tmp_path, '--dry-run').returncode == 0
    assert [p.name for p in tmp_path.iterdir()] == ['README.md']


def test_scaffold_detects_laravel(tmp_path):
    (tmp_path / 'artisan').write_text('', encoding='utf-8')
    (tmp_path / 'composer.json').write_text('{}', encoding='utf-8')
    assert 'profile: laravel-vue' in run(SCAFFOLD, '--repo', tmp_path, '--dry-run').stdout


def test_template_fails_until_release_facts_are_filled(tmp_path):
    run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python')
    r = run(DOCTOR, '--repo', tmp_path)
    assert r.returncode == 1 and 'release.pr_target' in r.stdout and 'deploy_branches' in r.stdout


def test_new_project_has_only_the_map_and_its_ci_as_debt(tmp_path):
    run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python')
    fill(tmp_path)
    r = run(DOCTOR, '--repo', tmp_path)
    assert r.returncode == 0, r.stdout
    assert lines(r, 'DEBT') == ['S12', 'S13', 'S19'] and lines(r, 'GAP') == []     # 004/FR-012


def test_a_scaffold_nobody_filled_in_is_not_conforming(tmp_path):
    run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python')
    r = run(DOCTOR, '--repo', tmp_path)
    assert {'S02', 'S03'} <= set(lines(r, 'GAP')), r.stdout
    assert '<one line each' in r.stdout and '<date>' in r.stdout


def test_a_path_placeholder_in_backticks_is_not_a_blank(project):
    assert '`.claude/skills/<domain>/`' in (project / 'CLAUDE.md').read_text(encoding='utf-8')
    assert 'S02' in lines(run(DOCTOR, '--repo', project), 'PASS')


@pytest.mark.parametrize('command', ['true', ':', 'exit 0', 'echo ok'])
def test_a_test_command_that_runs_nothing_is_a_gap(project, command):
    data = manifest(project)
    data['projects'][0]['test'] = [command]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'test runs nothing' in r.stdout


@pytest.mark.parametrize('line', ['* [ ] ship', '1. [ ] ship', '-   [ ] ship', '> - [ ] ship', '+ [ ] ship'])
def test_every_way_to_write_an_open_task_counts(project, line):
    feature(project, '001-a', 'Released', tasks=f'- [x] built\n{line}\n', plan=True)
    r = run(DOCTOR, '--repo', project)
    assert 'Released or Closed with open tasks: 001-a' in r.stdout, r.stdout


def test_a_ticked_fix_alone_is_not_a_task_list(project):
    feature(project, '001-a', 'Built', tasks='# Tasks\n\n## Fixes\n\n- [x] 001/FR-001 off by one\n', plan=True)
    r = run(DOCTOR, '--repo', project)
    assert 'tasks.md without' in r.stdout, r.stdout
    (project / 'specs' / '001-a' / 'tasks.md').write_text(
        '- [x] T001 build\n\n## Fixes\n\n- [ ] 001/FR-001 off by one\n', encoding='utf-8')
    spec = project / 'specs' / '001-a' / 'spec.md'
    spec.write_text(spec.read_text(encoding='utf-8').replace('Built', 'Released'), encoding='utf-8')
    assert 'with open tasks: 001-a' in run(DOCTOR, '--repo', project).stdout


def test_two_status_lines_or_one_inside_a_comment_is_no_status(project):
    feature(project, '001-a', 'Draft')
    spec = project / 'specs' / '001-a' / 'spec.md'
    body = spec.read_text(encoding='utf-8')
    spec.write_text(body + '\n**Status**: Closed\n', encoding='utf-8')
    assert 'no single valid Status line' in run(DOCTOR, '--repo', project).stdout
    spec.write_text(body.replace('**Status**: Draft', '<!--\n**Status**: Draft\n-->'), encoding='utf-8')
    assert 'no single valid Status line' in run(DOCTOR, '--repo', project).stdout


def test_doctor_says_when_a_merge_is_a_release(project):
    data = manifest(project)
    data['projects'][0]['release'] = {'pr_target': 'prod', 'deploy_branches': ['prod']}
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'every merge is a release' in r.stdout


def test_scaffold_refuses_a_symlinked_settings_file(tmp_path):
    (tmp_path / '.claude').mkdir()
    real = tmp_path / 'elsewhere.json'
    real.write_text('{}', encoding='utf-8')
    link((tmp_path / '.claude' / 'settings.json'), real)
    r = run(SCAFFOLD, '--repo', tmp_path, '--profile', 'python')
    assert r.returncode == 1 and real.read_text(encoding='utf-8') == '{}'


def test_scaffold_name_that_cannot_be_encoded_leaves_no_empty_file(tmp_path):
    r = subprocess.run([sys.executable, '-c',
                        'import runpy, sys; sys.argv = ["x", "--repo", sys.argv[1], "--profile", "python", '
                        '"--name", "bad\\udce9"]; runpy.run_path(sys.argv[0] if 0 else %r, run_name="__main__")'
                        % str(SCAFFOLD), str(tmp_path)], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 2, r.stdout + r.stderr
    assert not [f for f in tmp_path.rglob('*') if f.is_file() and f.stat().st_size == 0]


@pytest.mark.parametrize('command,nothing', [
    ('echo x && pytest', False), ('echo "start"; npm test', False), ('true || make test', False),
    (': no tests yet', True), ('true # todo', True), ('/bin/true', True), ('exit', True),
    ('printf ok', True), ('true && true', True), ('echo a; exit 0', True),
])
def test_what_counts_as_a_command_that_runs_nothing(project, command, nothing):
    data = manifest(project)
    data['projects'][0]['test'] = [command]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert ('test runs nothing' in r.stdout) is nothing, r.stdout


def test_one_real_command_among_noops_is_enough(project):
    data = manifest(project)
    data['projects'][0]['test'] = ['echo start', 'pytest -q']
    save(project, data)
    assert 'test runs nothing' not in run(DOCTOR, '--repo', project).stdout


def test_a_comment_marker_quoted_in_a_task_hides_nothing(project):
    feature(project, '001-a', 'Released', plan=True,
            tasks='- [x] add the `<!-- kit:map` pin\n- [ ] T2 still open\n- [x] T3 arrow --> done\n')
    assert 'with open tasks: 001-a' in run(DOCTOR, '--repo', project).stdout
    spec = project / 'specs' / '001-a' / 'spec.md'
    spec.write_text('about `<!--` markers\n' + spec.read_text(encoding='utf-8') + '\narrow --> here\n', encoding='utf-8')
    assert 'no single valid Status line' not in run(DOCTOR, '--repo', project).stdout


def test_a_commented_out_task_is_not_an_open_task(project):
    feature(project, '001-a', 'Released', plan=True, tasks='- [x] T1\n<!--\n- [ ] dropped idea\n-->\n')
    assert 'with open tasks' not in run(DOCTOR, '--repo', project).stdout


@pytest.mark.parametrize('heading', ['## Fixes (after release)', '### Fixes', '## fixes'])
def test_fixes_heading_variants_are_still_the_fixes_section(project, heading):
    feature(project, '001-a', 'Built', plan=True, tasks=f'# Tasks\n\n{heading}\n\n- [x] 001/FR-001 x\n')
    assert 'tasks.md without' in run(DOCTOR, '--repo', project).stdout


def test_tasks_after_the_fixes_section_still_count(project):
    feature(project, '001-a', 'Built', plan=True,
            tasks='## Fixes\n\n- [x] 001/FR-001 x\n\n# Tasks\n\n- [x] T1\n')
    assert 'tasks.md without' not in run(DOCTOR, '--repo', project).stdout
    (project / 'specs' / '001-a' / 'tasks.md').write_text('## Fixesandmore\n\n- [x] T1\n', encoding='utf-8')
    assert 'tasks.md without' not in run(DOCTOR, '--repo', project).stdout


def test_a_short_blank_counts_only_on_the_template_line(project):
    law = project / '.specify' / 'memory' / 'constitution.md'
    law.write_text(law.read_text(encoding='utf-8') + '\nAmendments are logged as <date>: <what changed>.\n',
                   encoding='utf-8')
    assert 'S03' in lines(run(DOCTOR, '--repo', project), 'PASS')
    claude = project / 'CLAUDE.md'
    claude.write_text(claude.read_text(encoding='utf-8') + '\nUse List<int> and <div>, `<one paragraph: what it '
                      'does, for whom, where it runs>` in backticks.\n', encoding='utf-8')
    assert 'S02' in lines(run(DOCTOR, '--repo', project), 'PASS')


def test_scaffold_never_writes_through_a_planted_temp_name_and_keeps_the_mode(tmp_path):
    victim = tmp_path / 'victim.txt'
    victim.write_text('VICTIM', encoding='utf-8')
    repo = tmp_path / 'repo'
    (repo / '.claude').mkdir(parents=True)
    link((repo / 'CLAUDE.md.kit-tmp'), victim)
    settings = repo / '.claude' / 'settings.json'
    settings.write_text('{}', encoding='utf-8')
    settings.chmod(0o600)
    assert run(SCAFFOLD, '--repo', repo, '--profile', 'python').returncode == 0
    assert victim.read_text(encoding='utf-8') == 'VICTIM' and not (repo / 'CLAUDE.md').is_symlink()
    if sys.platform != 'win32':
        assert settings.stat().st_mode & 0o777 == 0o600
    assert not [p for p in repo.rglob('.kit-*')]


def test_generic_profile_needs_a_test_command(tmp_path):
    run(SCAFFOLD, '--repo', tmp_path, '--profile', 'generic')
    r = run(DOCTOR, '--repo', tmp_path)
    assert r.returncode == 1 and 'S01' in lines(r, 'GAP')


def test_conforming_project_passes(project):
    feature(project, '001-login', 'Draft')
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0, r.stdout
    assert lines(r, 'GAP') == [] and lines(r, 'DEBT') == []


def test_bare_repo_reports_gaps(tmp_path):
    r = run(DOCTOR, '--repo', tmp_path)
    assert r.returncode == 1
    assert {'S01', 'S02', 'S03', 'S04', 'S12', 'S13', 'S14', 'S15'} <= set(lines(r, 'GAP'))
    assert lines(r, 'PASS') == ['S05']


def test_a_stale_deviation_fails(project):
    data = manifest(project)
    data['projects'][0]['deviations'] = [{'rule': 'S12', 'reason': 'x', 'fix': 'y'}]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'remove the entry' in r.stdout


@pytest.mark.parametrize('rule,build', [
    ('S04', lambda p: (p / 'specs' / 'notes.md').write_text('x', encoding='utf-8')),
    ('S04', lambda p: [feature(p, '006-a'), feature(p, '006-b')]),
    ('S05', lambda p: (p / '.specify' / 'specs' / '001-x').mkdir(parents=True)),
    ('S06', lambda p: (p / 'specs' / '001-x').mkdir(parents=True)),
    ('S06', lambda p: feature(p, '001-x', 'Built')),
    ('S07', lambda p: feature(p, '001-x', status=None)),
    ('S07', lambda p: feature(p, '001-x', status='Done')),
    ('S08', lambda p: (use_tracker(p), feature(p, '001-x', ticket=None))),
    ('S09', lambda p: feature(p, '001-x', 'Approved', tasks='| T1 | done |\n')),
    ('S09', lambda p: feature(p, '001-x', 'Released', tasks='- [x] a\n- [ ] b\n', plan=True)),
    ('S10', lambda p: feature(p, '001-x', 'Closed', tasks='- [x] a\n', plan=True)),
    ('S12', lambda p: (p / 'docs' / 'ARCHITECTURE.md').write_text('# no pin\n', encoding='utf-8')),
    ('S12', lambda p: (p / 'docs' / 'ARCHITECTURE.md').write_text(
        '<!-- kit:map revision=abcdef1 -->\n' + 'x\n' * 200, encoding='utf-8')),
    ('S13', lambda p: (p / 'docs' / 'diagrams' / 'map.refs.json').write_text('{}', encoding='utf-8')),
    ('S02', lambda p: (p / 'CLAUDE.md').write_text('x\n' * 151, encoding='utf-8')),
    ('S14', lambda p: (p / '.github' / 'workflows' / 'kit-gate.yml').unlink()),
    ('S15', lambda p: (p / '.claude' / 'settings.json').write_text('{}', encoding='utf-8')),
])
def test_each_rule_can_fail(project, rule, build):
    build(project)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and rule in lines(r, 'GAP'), r.stdout


def test_closed_feature_must_be_cited_in_the_living_spec(project):
    feature(project, '001-x', 'Closed', tasks='- [x] a\n', plan=True)
    cap = project / 'specs' / '_living' / 'auth'
    cap.mkdir()
    (cap / 'spec.md').write_text('Users can log in.\n', encoding='utf-8')
    assert 'S11' in lines(run(DOCTOR, '--repo', project), 'GAP')
    (cap / 'spec.md').write_text('Users can log in. (specs/001-x)\n', encoding='utf-8')
    assert run(DOCTOR, '--repo', project).returncode == 0


def test_ticket_must_match_the_tracker_from_approved_on(project):
    data = manifest(project)
    data['projects'][0]['tracker'] = {'type': 'jira', 'id_pattern': r'SCRUM-\d+'}
    save(project, data)
    feature(project, '001-a', 'Draft', ticket='none')
    assert run(DOCTOR, '--repo', project).returncode == 0
    feature(project, '002-b', 'Approved', ticket='none')
    assert 'S08' in lines(run(DOCTOR, '--repo', project), 'GAP')
    (project / 'specs' / '002-b' / 'spec.md').write_text('**Status**: Approved\n**Ticket**: SCRUM-12\n', encoding='utf-8')
    assert run(DOCTOR, '--repo', project).returncode == 0


def test_monorepo_judges_each_project_under_its_own_root(project):
    data = manifest(project)
    two = dict(data['projects'][0], name='two', root='two')
    data['projects'].append(two)
    save(project, data)
    (project / 'two').mkdir()
    r = run(DOCTOR, '--repo', project)
    one, _, other = r.stdout.partition('project two')
    assert 'GAP' not in one and 'GAP  S02 CLAUDE.md is missing' in other
    assert r.stdout.count('S14') == 1 and r.stdout.count('S15') == 1
    assert run(DOCTOR, '--repo', project, '--roots').stdout.split() == ['.', 'two']


def test_a_deviation_cannot_hide_a_new_feature(project):
    feature(project, '001-old', status='Implemented')
    data = manifest(project)
    data['projects'][0]['deviations'] = [
        {'rule': 'S07', 'reason': 'old wording', 'fix': 'rewrite', 'features': ['001-old']}]
    save(project, data)
    assert run(DOCTOR, '--repo', project).returncode == 0
    feature(project, '002-new', status='Shipped')
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'not covered by the recorded deviation: 002-new' in r.stdout


def test_a_feature_deviation_must_say_what_it_covers(project):
    feature(project, '001-old', status='Implemented')
    data = manifest(project)
    data['projects'][0]['deviations'] = [{'rule': 'S07', 'reason': 'x', 'fix': 'y'}]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'must name what it covers' in r.stdout


def test_features_under_dot_specify_are_judged_too(project):
    d = project / '.specify' / 'specs' / '001-x'
    d.mkdir(parents=True)
    (d / 'spec.md').write_text('no status here\n', encoding='utf-8')
    use_tracker(project)
    r = run(DOCTOR, '--repo', project)
    assert {'S05', 'S07', 'S08'} <= set(lines(r, 'GAP'))


def test_s01_cannot_be_debt_and_bad_shapes_do_not_crash(project):
    for mutate in (
        lambda p: p.update(tracker='jira'),
        lambda p: p.update(release='main'),
        lambda p: p.update(tracker={'type': ['jira']}),
        lambda p: p.update(tracker={'type': 'jira', 'id_pattern': 123}),
        lambda p: p.update(deviations=5),
        lambda p: p.update(deviations=[{'rule': 'S99', 'fix': 'x'}]),
        lambda p: p.update(deviations=[{'rule': 'S01', 'fix': 'x'}], test=[]),
        lambda p: p.update(deviations=[{'rule': 'S12', 'reason': 'r'}]),
        lambda p: p.update(deviations=[{'rule': 'S12', 'fix': 'f'}]),
        lambda p: p.update(deviations=[{'rule': 'S12', 'reason': 'r', 'fix': 'f'}] * 2),
        lambda p: p.update(deviations=[{'rule': 'S07', 'reason': 'r', 'fix': 'f', 'features': [['001-a']]}]),
        lambda p: p.update(deviations=[{'rule': 'S14', 'reason': 'r', 'fix': 'f'}]),
        lambda p: p.update(components=[]),
        lambda p: p.update(root='../outside'),
    ):
        data = manifest(project)
        mutate(data['projects'][0])
        save(project, data)
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and 'S01' in lines(r, 'GAP') and 'Traceback' not in r.stderr, r.stdout + r.stderr
        data['projects'][0].update(deviations=[], root='.', test=['x'],
                                   tracker={'type': 'none'}, release={'pr_target': 'main', 'deploy_branches': []})
        save(project, data)
    for bad in ('[]', 'null', '{"enabledPlugins": []}'):
        (project / '.claude' / 'settings.json').write_text(bad, encoding='utf-8')
        r = run(DOCTOR, '--repo', project)
        assert 'S15' in lines(r, 'GAP') and 'Traceback' not in r.stderr


def test_unparseable_manifest_exits_2(project):
    (project / '.claude' / 'kit.yml').write_text('name: shop: api\n', encoding='utf-8')
    assert run(DOCTOR, '--repo', project).returncode == 2


@pytest.mark.parametrize('text,valid', [
    ('**Status**: Draft\n', True),
    ('**Status**: Draft  \r\n', True),
    ('**Status**: Superseded\n**Status note**: by 035\n', True),
    ('**Status**:\n\nApproved by nobody yet\n', False),
    ('```\n**Status**: Closed\n```\n**Status**: Bogus\n', False),
    ('**Status:** Draft\n', False),
    ('**Status**: Draft.\n', False),
])
def test_status_line_parsing(project, text, valid):
    d = project / 'specs' / '001-x'
    d.mkdir()
    (d / 'spec.md').write_text(text + '**Ticket**: none\n', encoding='utf-8')
    assert ('S07' not in lines(run(DOCTOR, '--repo', project), 'GAP')) is valid


def test_pin_must_be_on_the_first_line(project):
    (project / 'docs' / 'ARCHITECTURE.md').write_text('# map\n<!-- kit:map revision=abcdef1 -->\n', encoding='utf-8')
    assert 'S12' in lines(run(DOCTOR, '--repo', project), 'GAP')


def test_living_citation_is_matched_whole(project):
    feature(project, '001-pay', 'Closed', tasks='- [x] a\n', plan=True)
    cap = project / 'specs' / '_living' / 'billing'
    cap.mkdir()
    (cap / 'spec.md').write_text('See myspecs/001-payments-v2 and specs/001-payments.\n', encoding='utf-8')
    assert 'S11' in lines(run(DOCTOR, '--repo', project), 'GAP')


def test_all_lists_every_name(project):
    for n in range(1, 9):
        feature(project, f'{n:03d}-f', status=None)
    assert '+3 more' in run(DOCTOR, '--repo', project).stdout
    assert '008-f' in run(DOCTOR, '--repo', project, '--all').stdout


def test_scaffold_keeps_user_settings_and_encoding(tmp_path):
    (tmp_path / '.claude').mkdir()
    original = {'permissions': {'allow': ['x']}, 'note': 'kiểm tra',
                'extraKnownMarketplaces': {'other': {'a': 1},
                                           'francis-ai-coworking': {'source': {'source': 'directory'}}},
                'enabledPlugins': {'francis-kit@francis-ai-coworking': False}}
    (tmp_path / '.claude' / 'settings.json').write_text(json.dumps(original, ensure_ascii=False), encoding='utf-8')
    run(SCAFFOLD, '--repo', tmp_path)
    raw = (tmp_path / '.claude' / 'settings.json').read_text(encoding='utf-8')
    assert json.loads(raw) == original


@pytest.mark.parametrize('bad', ['[]', '{"enabledPlugins": []}', '// c\n{}', '{'])
def test_scaffold_writes_nothing_when_settings_are_unusable(tmp_path, bad):
    (tmp_path / '.claude').mkdir()
    (tmp_path / '.claude' / 'settings.json').write_text(bad, encoding='utf-8')
    r = run(SCAFFOLD, '--repo', tmp_path)
    assert r.returncode == 1 and 'Traceback' not in r.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ['.claude']


def test_scaffold_does_not_write_through_a_dangling_symlink(tmp_path):
    link((tmp_path / 'CLAUDE.md'), tmp_path / 'elsewhere.md')
    run(SCAFFOLD, '--repo', tmp_path)
    assert not (tmp_path / 'elsewhere.md').exists()


@pytest.mark.parametrize('name', ['shop: api', '@scope/app', '2024', 'yes', 'my #1 app'])
def test_scaffold_quotes_the_project_name(tmp_path, name):
    run(SCAFFOLD, '--repo', tmp_path, '--name', name)
    assert manifest(tmp_path)['projects'][0]['name'] == name


def test_scaffold_project_root_in_a_monorepo(tmp_path):
    (tmp_path / 'api').mkdir()
    (tmp_path / 'api' / 'pyproject.toml').write_text('', encoding='utf-8')
    r = run(SCAFFOLD, '--repo', tmp_path, '--project-root', 'api')
    assert 'profile: python' in r.stdout
    assert (tmp_path / 'api' / 'specs' / '_living' / 'README.md').is_file()
    assert (tmp_path / '.claude' / 'kit.yml').is_file() and not (tmp_path / 'specs').exists()
    assert manifest(tmp_path)['projects'][0]['root'] == 'api'


def test_gate_template_is_valid_yaml_and_pinned(tmp_path):
    import yaml
    run(SCAFFOLD, '--repo', tmp_path)
    gate = yaml.safe_load((tmp_path / '.github' / 'workflows' / 'kit-gate.yml').read_text(encoding='utf-8'))
    steps = gate['jobs']['standard']['steps']
    checkouts = [s for s in steps if s.get('uses', '').startswith('actions/checkout@')]
    kit_checkout = [s['with'] for s in checkouts if s['with'].get('repository')]
    assert len(checkouts) == 2 and len(kit_checkout) == 1
    import re
    assert re.fullmatch(r'v\d+\.\d+\.\d+', kit_checkout[0]['ref'])
    assert all(re.search(r'@[0-9a-f]{40}  # v', s) for s in
               (l for l in (tmp_path / '.github' / 'workflows' / 'kit-gate.yml').read_text(encoding='utf-8').splitlines() if 'uses:' in l))
    assert all(s['with'].get('persist-credentials') is False for s in checkouts)
    assert [s.get('name') or s['uses'] for s in steps if 'if' in s] == [      # 009/FR-003: no step waits on the secret step
        'Runner ready?', next(s['uses'] for s in steps if s.get('uses', '').startswith('actions/setup-python@')),
        'Leave nothing behind']


def test_root_must_stay_inside_the_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    run(SCAFFOLD, '--repo', outside, '--profile', 'python')
    run(SCAFFOLD, '--repo', repo, '--profile', 'python')
    fill(repo)
    data = manifest(repo)
    data['projects'][0]['root'] = '../outside'
    save(repo, data)
    r = run(DOCTOR, '--repo', repo)
    assert r.returncode == 1 and 'outside the repository' in r.stdout


def test_plugin_turned_off_is_a_gap(project):
    path = project / '.claude' / 'settings.json'
    settings = json.loads(path.read_text(encoding='utf-8'))
    settings['enabledPlugins']['francis-kit@francis-ai-coworking'] = False
    path.write_text(json.dumps(settings), encoding='utf-8')
    assert 'S15' in lines(run(DOCTOR, '--repo', project), 'GAP')


def test_ticket_id_must_match_in_full(project):
    data = manifest(project)
    data['projects'][0]['tracker'] = {'type': 'jira', 'id_pattern': r'SCRUM-\d+'}
    save(project, data)
    feature(project, '001-a', 'Approved', ticket='SCRUM-12x')
    assert 'S08' in lines(run(DOCTOR, '--repo', project), 'GAP')


def deviate(project, entries, top=None):
    data = manifest(project)
    data['projects'][0]['deviations'] = entries
    if top is not None:
        data['deviations'] = top
    save(project, data)


def test_a_deviation_names_exactly_what_it_covers(project):
    feature(project, '001-old', status='Implemented')
    feature(project, '002-fine', status='Draft')
    dev = {'rule': 'S07', 'reason': 'old wording', 'fix': 'rewrite', 'features': ['001-old']}
    deviate(project, [dev])
    assert run(DOCTOR, '--repo', project).returncode == 0
    (project / 'specs' / '002-fine' / 'spec.md').write_text('**Status**: Whatever\n**Ticket**: none\n', encoding='utf-8')
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'not covered by the recorded deviation: 002-fine' in r.stdout
    deviate(project, [dict(dev, features=['001-old', '002-fine', '003-gone'])])
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'conforming now, remove: 003-gone' in r.stdout


def test_stray_entries_and_misplaced_directories_cannot_hide_behind_debt(project):
    (project / 'specs' / 'notes.md').write_text('x', encoding='utf-8')
    (project / '.specify' / 'specs' / '001-old').mkdir(parents=True)
    (project / '.specify' / 'specs' / '001-old' / 'spec.md').write_text('**Status**: Draft\n**Ticket**: none\n', encoding='utf-8')
    deviate(project, [{'rule': 'S04', 'reason': 'r', 'fix': 'f', 'features': ['notes.md']},
                      {'rule': 'S05', 'reason': 'r', 'fix': 'f', 'features': ['001-old']}])
    assert run(DOCTOR, '--repo', project).returncode == 0
    (project / 'specs' / 'New_Feature').mkdir()
    (project / '.specify' / 'specs' / '002_Bad').mkdir()
    r = run(DOCTOR, '--repo', project)
    assert 'S04 not covered by the recorded deviation: New_Feature' in r.stdout
    assert 'S05 not covered by the recorded deviation: 002_Bad' in r.stdout


def test_duplicate_numbers_across_both_spec_directories(project):
    feature(project, '001-a')
    (project / '.specify' / 'specs' / '001-b').mkdir(parents=True)
    r = run(DOCTOR, '--repo', project)
    assert 'feature number used twice: 001-a, 001-b' in r.stdout


def test_repository_deviations_live_at_the_top_level(project):
    (project / '.github' / 'workflows' / 'kit-gate.yml').unlink()
    deviate(project, [], top=[{'rule': 'S14', 'reason': 'no CI yet', 'fix': 'add the gate'}])
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and lines(r, 'DEBT') == ['S14']


def test_s10_and_s11_can_both_be_recorded(project):
    feature(project, '001-x', 'Closed', tasks='- [x] a\n', plan=True)
    deviate(project, [{'rule': 'S10', 'reason': 'r', 'fix': 'f'},
                      {'rule': 'S11', 'reason': 'r', 'fix': 'f', 'features': ['001-x']}])
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and lines(r, 'DEBT') == ['S10', 'S11']


def test_a_deviation_on_a_rule_with_nothing_to_judge_is_a_gap(project):
    deviate(project, [{'rule': 'S10', 'reason': 'r', 'fix': 'f'}])
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'nothing to judge: remove the entry' in r.stdout


def test_status_dependent_checks(project):
    feature(project, '001-built', 'Built', tasks='- [x] a\n')            # no plan.md
    feature(project, '002-closed', 'Closed', tasks='- [ ] a\n', plan=True)
    feature(project, '003-dropped', 'Dropped', tasks='- [ ] a\n')
    cap = project / 'specs' / '_living' / 'c'
    cap.mkdir()
    (cap / 'spec.md').write_text('(specs/002-closed)\n', encoding='utf-8')
    out = run(DOCTOR, '--repo', project, '--all').stdout
    assert 'Built or later without plan.md and tasks.md: 001-built' in out
    assert 'Released or Closed with open tasks: 002-closed' in out
    assert '003-dropped' not in out


def test_rules_that_judged_nothing_say_skip(project):
    (project / 'specs' / '001-x').mkdir()
    (project / 'specs' / '001-x' / 'spec.md').write_text('status: approved\n', encoding='utf-8')
    r = run(DOCTOR, '--repo', project)
    assert {'S06', 'S09'} <= set(lines(r, 'SKIP')) and 'S07' in lines(r, 'GAP')


def test_checkbox_inside_a_code_fence_is_not_an_open_task(project):
    feature(project, '001-x', 'Released', tasks='- [x] done\n```\n- [ ] example\n```\n', plan=True)
    assert 'S09' not in lines(run(DOCTOR, '--repo', project), 'GAP')


def test_roots_lists_only_usable_roots_and_keeps_stdout_clean(project):
    data = manifest(project)
    data['projects'].append(dict(data['projects'][0], name='gone', root='missing'))
    save(project, data)
    r = run(DOCTOR, '--repo', project, '--roots', '--project-root', 'x')
    assert r.stdout.split() == ['.'] and 'ignored' in r.stderr


def test_exit_2_when_nothing_can_be_judged(project):
    for text in ('- a list\n', 'since: 2026-02-30\n', '# only a comment\n'):
        (project / '.claude' / 'kit.yml').write_text(text, encoding='utf-8')
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 2 and 'Traceback' not in r.stderr, text
    assert run(DOCTOR, '--repo', project / 'nope').returncode == 2


def test_scaffold_refuses_a_symlinked_parent_and_keeps_bom_and_crlf(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    repo = tmp_path / 'repo'
    repo.mkdir()
    link((repo / 'specs'), outside)
    r = run(SCAFFOLD, '--repo', repo)
    assert r.returncode == 1 and list(outside.iterdir()) == []
    (repo / 'specs').unlink()
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'settings.json').write_bytes(b'\xef\xbb\xbf{\r\n  "a": 1\r\n}\r\n')
    assert run(SCAFFOLD, '--repo', repo).returncode == 0
    raw = (repo / '.claude' / 'settings.json').read_bytes()
    assert raw.startswith(b'\xef\xbb\xbf') and b'\r\n' in raw and b'\n' not in raw.replace(b'\r\n', b'')
    assert json.loads(raw.decode('utf-8-sig'))['a'] == 1


def test_scaffold_name_cannot_inject_another_placeholder(tmp_path):
    run(SCAFFOLD, '--repo', tmp_path, '--name', '{{ROOT}}')
    assert manifest(tmp_path)['projects'][0]['name'] == '{{ROOT}}'


def test_scaffold_needs_a_semver_kit_version(tmp_path):
    import shutil
    kit = tmp_path / 'kit'
    shutil.copytree(SCRIPTS.parents[2], kit)
    target = tmp_path / 'repo'
    target.mkdir()
    for bad in ('{"version": "0.5.0-dev"}', '{"version": 1}', 'not json'):
        (kit / '.claude-plugin' / 'plugin.json').write_text(bad, encoding='utf-8')
        r = run(kit / 'skills' / 'kit-init' / 'scripts' / 'kit_scaffold.py', '--repo', target)
        assert r.returncode == 1 and list(target.iterdir()) == [], bad


def test_s04_allows_the_generated_index_and_the_refs_baseline(project):
    (project / 'specs' / 'INDEX.md').write_text('x', encoding='utf-8')
    (project / 'specs' / '.kit-refs-baseline.json').write_text('{}', encoding='utf-8')
    r = run(DOCTOR, '--repo', project)
    assert 'S04' in lines(r, 'PASS') and r.returncode == 0, r.stdout
    (project / 'specs' / 'notes.json').write_text('{}', encoding='utf-8')
    assert 'S04' in lines(run(DOCTOR, '--repo', project), 'GAP')


def test_s16_voice_and_design_for_a_project_with_an_interface(project):
    assert 'S16' in lines(run(DOCTOR, '--repo', project), 'SKIP')
    data = manifest(project)
    data['projects'][0]['interface'] = True
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'S16' in lines(r, 'GAP') and 'docs/VOICE.md is missing or empty' in r.stdout
    ui = SCRIPTS.parent.parent / 'ui-copy' / 'templates' / 'VOICE.md'
    dd = SCRIPTS.parent.parent / 'design-direction' / 'templates' / 'DESIGN.md'
    good_voice = '# Voice\n\nShop owners, on a phone.\nWe say anh/chị.\nCalm, short, exact.\n'
    good_design = '# Design\n\nA ledger, not a dashboard.\nDense tables.\nOne accent colour.\n'
    (project / 'docs' / 'DESIGN.md').write_text(good_design, encoding='utf-8')
    for hollow, why in [(ui.read_text(encoding='utf-8'), 'line(s) of the template not filled in'),
                        (ui.read_text(encoding='utf-8').replace('<one or two lines', '<two lines'), 'line(s) of the template not filled in'),
                        ('x', 'says almost nothing'), ('# Voice\n\n## Tone\n', 'says almost nothing'),
                        ('<!-- todo -->\n| a | b |\n', 'says almost nothing'), ('  \n', 'missing or empty')]:
        (project / 'docs' / 'VOICE.md').write_text(hollow, encoding='utf-8')
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and 'docs/VOICE.md' in r.stdout and why in r.stdout, (hollow[:20], r.stdout)
    (project / 'docs' / 'VOICE.md').write_text(good_voice, encoding='utf-8')
    (project / 'docs' / 'DESIGN.md').write_text(dd.read_text(encoding='utf-8'), encoding='utf-8')
    assert 'docs/DESIGN.md still has' in run(DOCTOR, '--repo', project).stdout
    (project / 'docs' / 'DESIGN.md').write_text(good_design, encoding='utf-8')
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'S16' in lines(r, 'PASS'), r.stdout
    data['projects'][0]['deviations'] = [{'rule': 'S16', 'reason': 'r', 'fix': 'f'}]
    save(project, data)
    assert run(DOCTOR, '--repo', project).returncode == 1
    data['projects'][0]['deviations'] = []
    for bad in ('yes', 1, None):
        data['projects'][0]['interface'] = bad
        save(project, data)
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and 'interface must be true or false' in r.stdout, bad
    del data['projects'][0]['interface']
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'interface must be true or false' in r.stdout


def test_a_ticked_fix_keeps_a_closed_feature_clean_and_an_open_one_does_not(project):
    feature(project, '001-a', status='Released', ticket='none', tasks='- [x] build it\n\n## Fixes\n\n- [x] T-1 late fee charged twice (001/FR-003)\n', plan=True)
    r = run(DOCTOR, '--repo', project)
    assert 'S09' in lines(r, 'PASS'), r.stdout
    (project / 'specs' / '001-a' / 'tasks.md').write_text('- [x] build it\n\n## Fixes\n\n- [ ] T-2 not done yet (001/FR-003)\n', encoding='utf-8')
    assert 'S09' in lines(run(DOCTOR, '--repo', project), 'GAP')


def test_s17_a_project_names_its_dependency_audit(project):
    assert 'S17' in lines(run(DOCTOR, '--repo', project), 'PASS')
    data = manifest(project)
    for empty in ([], ['true'], None, 'pip-audit'):
        data['projects'][0]['audit'] = empty
        save(project, data)
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and 'S17' in lines(r, 'GAP'), (empty, r.stdout)
    data['projects'][0]['audit'] = []
    data['projects'][0]['deviations'] = [{'rule': 'S17', 'reason': 'no audit tool chosen', 'fix': 'add pip-audit'}]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'S17' in lines(r, 'DEBT')


SLOW_PATTERNS = ['(a+)+$', '((a+))+b', '(a|a)+b', '(a{1,30}){1,30}b']


@pytest.mark.parametrize('pattern', SLOW_PATTERNS)
def test_a_pattern_that_does_not_finish_fails_the_ticket_rule_in_bounded_time(project, pattern):
    feature(project, '001-a', 'Approved', ticket='a' * 40 + '!')
    data = manifest(project)
    data['projects'][0]['tracker'] = {'type': 'jira', 'id_pattern': pattern}
    save(project, data)
    r = subprocess.run([sys.executable, str(DOCTOR), '--repo', str(project)], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert r.returncode == 1 and 'S08' in lines(r, 'GAP') and 'did not finish' in r.stdout, r.stdout


@pytest.mark.parametrize('pattern', [r'(?:[A-Z]+-\d+)(?:,[A-Z]+-\d+)*', r'#\d+(,#\d+)*', r'([A-Z]{2,10}-\d+)+'])
def test_an_ordinary_pattern_with_a_repeated_group_still_checks_tickets(project, pattern):
    feature(project, '001-a', 'Approved', ticket='totally-wrong')
    data = manifest(project)
    data['projects'][0]['tracker'] = {'type': 'jira', 'id_pattern': pattern}
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert 'S01' in lines(r, 'PASS') and 'no valid Ticket line in 1 of 1: 001-a' in r.stdout, r.stdout


def test_a_monorepo_that_shares_commands_through_aliases_is_read(project):
    kit = project / '.claude' / 'kit.yml'
    kit.write_text('x-shared: &cmd [pytest -q]\n' + ''.join(f'x-{i}: *cmd\n' for i in range(40))
                   + kit.read_text(encoding='utf-8'), encoding='utf-8')
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'unknown top-level keys' in r.stdout      # judged, not refused


def test_a_manifest_too_large_to_be_facts_is_refused(project):
    kit = project / '.claude' / 'kit.yml'
    kit.write_text(kit.read_text(encoding='utf-8') + '# ' + 'x' * 200_001 + '\n', encoding='utf-8')
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 2 and '.claude/kit.yml is larger than 200 kB: it holds facts, not data' in r.stderr


def test_a_manifest_built_to_expand_is_refused(project):
    kit = project / '.claude' / 'kit.yml'
    bomb = 'a: &a [x, x]\n' + ''.join(f'{c}: &{c} [*{p}, *{p}, *{p}]\n' for p, c in zip('abcdefghi', 'bcdefghij'))
    kit.write_text(bomb + kit.read_text(encoding='utf-8'), encoding='utf-8')
    r = subprocess.run([sys.executable, str(DOCTOR), '--repo', str(project)], capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert r.returncode == 2 and 'expands to more than' in r.stderr


GATE_CASES = [
    # event, head repo, actor, secret -> exit, level. 009/FR-003: a fork and Dependabot start no gate, so no row passes without the secret.
    ('pull_request', 'me/app', 'me', '', 1, '::error::'),
    ('pull_request', 'me/app', 'me', 'tok', 0, None),
    ('pull_request', 'fork/app', 'someone', '', 1, '::error::'),
    ('pull_request', 'me/app', 'dependabot[bot]', '', 1, '::error::'),
    ('workflow_dispatch', '', 'me', '', 1, '::error::'),
    ('workflow_dispatch', '', 'dependabot[bot]', '', 1, '::error::'),
    ('workflow_dispatch', '', 'me', 'tok', 0, None),
]


@pytest.mark.private
@pytest.mark.skipif(sys.platform == 'win32', reason='the gate step is bash, as on the runner')
@pytest.mark.parametrize('event,head,actor,secret,code,level', GATE_CASES)
def test_the_gate_fails_without_its_secret_except_where_secrets_never_arrive(
        tmp_path, event, head, actor, secret, code, level):
    """009/FR-003, SC-010: a missing secret is a failure whatever else the environment holds."""
    import yaml
    template = (SCRIPTS.parent / 'templates' / 'common' / 'kit-gate.yml').read_text(encoding='utf-8')
    step = yaml.safe_load(template.replace('{{KIT_REF}}', 'v0.0.0'))['jobs']['standard']['steps'][0]
    assert step['name'] == 'Secret present?'
    env = {'PATH': '/usr/bin:/bin', 'KIT_READ_TOKEN': secret, 'EVENT': event, 'HEAD_REPO': head,
           'GITHUB_REPOSITORY': 'me/app', 'GITHUB_ACTOR': actor}
    r = subprocess.run(['bash', '-e', '-c', step['run']], cwd=tmp_path, env=env, capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == code, r.stdout + r.stderr
    assert ('::error::KIT_READ_TOKEN is not set' in r.stdout) if level else ('::' not in r.stdout)
    assert '::warning::' not in r.stdout and not list(tmp_path.iterdir())


def test_without_a_tracker_the_ticket_rule_is_skipped_and_cannot_be_held_as_debt(project):
    feature(project, '001-a', 'Approved', ticket=None)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'S08' in lines(r, 'SKIP'), r.stdout
    data = manifest(project)
    data['projects'][0]['deviations'] = [{'rule': 'S08', 'reason': 'r', 'fix': 'f', 'features': ['001-a']}]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'S08 listed under deviations but there is nothing to judge' in r.stdout


def gate_of(project):
    return project / '.github' / 'workflows' / 'kit-gate.yml'


def test_s14_wants_the_gate_of_the_version_it_pins_not_any_file(project):
    assert 'S14' in lines(run(DOCTOR, '--repo', project), 'PASS')
    whole = gate_of(project).read_text(encoding='utf-8')
    for hollow, why in [('name: kit-gate\n', 'does not pin'),
                        (whole.replace('exit 1', 'exit 0'), 'not the gate of this kit version'),
                        (whole.replace('::error::', '::warning::'), 'not the gate of this kit version'),
                        (whole.replace('v', 'x', 1) if False else whole.replace('ref: v', 'ref: main # v'), 'does not pin')]:
        gate_of(project).write_text(hollow, encoding='utf-8')
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and why in r.stdout, (why, r.stdout)
    gate_of(project).write_bytes(whole.replace('\n', '\r\n').encode('utf-8'))      # a Windows checkout
    assert 'S14' in lines(run(DOCTOR, '--repo', project), 'PASS')


def test_scaffold_gate_writes_the_gate_again_and_nothing_else(project):
    claude = (project / 'CLAUDE.md').read_text(encoding='utf-8')
    whole = gate_of(project).read_text(encoding='utf-8')
    gate_of(project).write_text(whole.replace('exit 1', 'exit 0'), encoding='utf-8')
    plain = run(SCAFFOLD, '--repo', project)
    assert 'kept    .github/workflows/kit-gate.yml' in plain.stdout and 'exit 0' in gate_of(project).read_text(encoding='utf-8')
    assert 'replace .github/workflows/kit-gate.yml' in run(SCAFFOLD, '--repo', project, '--gate', '--dry-run').stdout
    assert 'exit 0' in gate_of(project).read_text(encoding='utf-8')
    r = run(SCAFFOLD, '--repo', project, '--gate')
    assert 'replace .github/workflows/kit-gate.yml' in r.stdout and gate_of(project).read_text(encoding='utf-8') == whole
    assert (project / 'CLAUDE.md').read_text(encoding='utf-8') == claude
    assert 'already the gate' in run(SCAFFOLD, '--repo', project, '--gate').stdout
    assert 'S14' in lines(run(DOCTOR, '--repo', project), 'PASS')


def test_interface_false_beside_screens_is_said_aloud(project):
    assert 'note: interface is false' not in run(DOCTOR, '--repo', project).stdout
    (project / 'package.json').write_text('{"dependencies": {"vue": "^3"}}', encoding='utf-8')
    (project / 'lang').mkdir()
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'note: interface is false' in r.stdout and 'vue' in r.stdout
    data = manifest(project)
    data['projects'][0]['interface'] = True
    save(project, data)
    assert 'note: interface is false' not in run(DOCTOR, '--repo', project).stdout


def test_a_citation_file_that_cites_nothing_fails_s13(project):
    refs = project / 'docs' / 'diagrams' / 'map.refs.json'
    for empty in ({'sections': []}, {'sources': []}, {'sources': [{'line': 3}]}, {'nodes': [{'sources': 'x'}]}):
        refs.write_text(json.dumps({'meta': {'repository': {'revision': 'abcdef1'}}, **empty}), encoding='utf-8')
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and 'cites nothing' in r.stdout, empty
    refs.write_text(json.dumps({'meta': {'repository': {'revision': 'abcdef1'}},
                                'nodes': [{'sources': [{'path': 'src/a.py'}]}]}), encoding='utf-8')
    assert 'S13' in lines(run(DOCTOR, '--repo', project), 'PASS')


def test_a_project_may_be_called_project_something(project):
    data = manifest(project)
    data['projects'][0]['name'] = 'project atlas'
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'name must be' not in r.stdout, r.stdout


def test_released_with_only_an_open_fix_reports_both_problems(project):
    feature(project, '001-a', 'Released', plan=True, tasks='## Fixes\n\n- [ ] 001/FR-001 still open\n')
    out = run(DOCTOR, '--repo', project).stdout
    assert 'tasks.md without' in out and 'Released or Closed with open tasks: 001-a' in out


def test_s16_counts_a_table_the_project_filled_in(project):
    data = manifest(project)
    data['projects'][0]['interface'] = True
    save(project, data)
    template = (SCRIPTS.parent.parent / 'ui-copy' / 'templates' / 'VOICE.md').read_text(encoding='utf-8')
    kept = [line for line in template.splitlines() if not ('<' in line and '>' in line)]
    for name in ('VOICE.md', 'DESIGN.md'):
        (project / 'docs' / name).write_text('\n'.join(kept) + '\n| Saved | Đã lưu |\n| Deleted | Đã xoá |\n'
                                             '| Sign in failed | Sai email hoặc mật khẩu |\n', encoding='utf-8')
    out = run(DOCTOR, '--repo', project).stdout
    assert 'says almost nothing' not in out, out
    (project / 'docs' / 'VOICE.md').write_text('\n'.join(kept) + '\n|---|---|\n', encoding='utf-8')
    assert 'docs/VOICE.md says almost nothing' in run(DOCTOR, '--repo', project).stdout


def test_a_pattern_that_does_not_finish_cannot_be_held_as_debt(project):
    use_tracker(project)
    feature(project, '002-b', 'Approved', ticket='a' * 40 + '!')
    feature(project, '003-c', 'Approved', ticket='a' * 40 + '!')
    data = manifest(project)
    data['projects'][0]['tracker'] = {'type': 'jira', 'id_pattern': '(a+)+$'}
    data['projects'][0]['deviations'] = [{'rule': 'S08', 'reason': 'r', 'fix': 'f', 'features': ['002-b', '003-c']}]
    save(project, data)
    r = subprocess.run([sys.executable, str(DOCTOR), '--repo', str(project)], capture_output=True, text=True,
                       encoding='utf-8', timeout=30)
    assert r.returncode == 1 and 'GAP  S08 tracker.id_pattern did not finish' in r.stdout, r.stdout
    assert 'conforming now' not in r.stdout


def test_s14_judges_the_gate_by_the_version_it_pins(project):
    whole = gate_of(project).read_text(encoding='utf-8')
    for other, said in (('v0.6.0', 'and a newer kit,'), ('v9.9.9', 'newer than the kit installed here')):   # 019
        gate_of(project).write_text(re.sub(r'ref: v[\d.]+', f'ref: {other}', whole), encoding='utf-8')
        r = run(DOCTOR, '--repo', project)
        assert r.returncode == 1 and f'pins {other}, {said}' in r.stdout, r.stdout


def test_gate_flag_touches_the_gate_and_nothing_else(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.github' / 'workflows').mkdir(parents=True)
    (tmp_path / '.github' / 'workflows' / 'kit-gate.yml').write_text('old\n', encoding='utf-8')
    r = run(SCAFFOLD, '--repo', tmp_path, '--gate')
    assert r.returncode == 0 and 'replace .github/workflows/kit-gate.yml' in r.stdout
    made = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*') if p.is_file() and '.git/' not in p.as_posix())
    assert made == ['.github/workflows/kit-gate.yml'], made


def test_gate_flag_refuses_a_symlinked_gate(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.github' / 'workflows').mkdir(parents=True)
    real = tmp_path / 'elsewhere.yml'
    real.write_text('mine\n', encoding='utf-8')
    link(tmp_path / '.github' / 'workflows' / 'kit-gate.yml', real)
    r = run(SCAFFOLD, '--repo', tmp_path, '--gate')
    assert r.returncode == 1 and real.read_text(encoding='utf-8') == 'mine\n'


def test_every_rule_is_said_in_words_wherever_the_doctor_names_it(project):
    import importlib.util
    spec = importlib.util.spec_from_file_location('kit_doctor', DOCTOR)
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    standard = (SCRIPTS.parent.parent.parent / 'STANDARD.md').read_text(encoding='utf-8')
    in_standard = set(re.findall(r'^\| (S\d\d) \|', standard, re.M))
    assert set(doctor.ABOUT) == in_standard == set(['S01', 'S14', 'S15'] + doctor.PROJECT_RULES)
    out = run(DOCTOR, '--repo', project).stdout
    for line in out.splitlines():
        if line.strip().startswith(('PASS', 'SKIP')):
            assert re.search(r'S\d\d \(.+\)', line), line


# Spec 003: the gate judges what it says it judges.

SKILLS = SCRIPTS.parent.parent
LINT = SKILLS / 'write-spec' / 'scripts' / 'spec_lint.py'


def load_doctor():
    import importlib.util
    spec = importlib.util.spec_from_file_location('kit_doctor', DOCTOR)
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    return doctor


def set_key(project, key, value):
    data = manifest(project)
    data['projects'][0][key] = value
    save(project, data)


def gaps_of(result, rule):
    return [l for l in result.stdout.splitlines() if l.strip().startswith(f'GAP  {rule}')]


def track(project, commit=True):
    subprocess.run(['git', 'init', '-q', str(project)], check=True)
    subprocess.run(['git', '-C', str(project), 'add', '-A'], check=True, capture_output=True)
    if commit:
        subprocess.run(['git', '-C', str(project), '-c', 'user.email=t@example.com', '-c', 'user.name=t',
                        'commit', '-q', '-m', 'init'], check=True, capture_output=True)


def test_s17_an_audit_whose_result_is_thrown_away_is_a_gap(project):
    """003/FR-002, 003/FR-003, SC-002."""
    entries = ['pip-audit || true', 'npm audit; true', 'npm audit | tee out.txt']
    set_key(project, 'audit', entries)
    r = run(DOCTOR, '--repo', project)
    gaps = gaps_of(r, 'S17')
    assert r.returncode == 1 and len(gaps) == 3, r.stdout
    for entry, sign in zip(entries, ('||', ';', '|')):
        assert any('audit' in g and repr(entry) in g and f'`{sign}`' in g for g in gaps), (entry, r.stdout)
    set_key(project, 'audit', ['cd app && npm audit'])
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'S17' in lines(r, 'PASS'), r.stdout


def test_s17_a_joined_audit_can_be_recorded_as_debt_like_any_s17_gap(project):
    data = manifest(project)
    data['projects'][0]['audit'] = ['pip-audit || true']
    data['projects'][0]['deviations'] = [{'rule': 'S17', 'reason': 'the audit is noisy', 'fix': 'drop `|| true`'}]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'S17' in lines(r, 'DEBT') and "'pip-audit || true'" in r.stdout, r.stdout


def test_s01_a_test_whose_result_is_thrown_away_is_a_gap(project):
    """003/FR-010, 003/FR-003, SC-008."""
    set_key(project, 'test', ['pytest -q || true'])
    r = run(DOCTOR, '--repo', project)
    gaps = gaps_of(r, 'S01')
    assert r.returncode == 1 and len(gaps) == 1, r.stdout
    assert 'demo' in gaps[0] and 'test' in gaps[0] and "'pytest -q || true'" in gaps[0] and '`||`' in gaps[0]
    set_key(project, 'test', ['cd api && pytest -q'])
    r = run(DOCTOR, '--repo', project)
    assert 'S01' in lines(r, 'PASS'), r.stdout


def test_s01_reports_each_joined_test_entry_and_leaves_the_others(project):
    set_key(project, 'test', ['pytest -q', 'npm test; true', 'make e2e | tee log'])
    gaps = gaps_of(run(DOCTOR, '--repo', project), 'S01')
    assert len(gaps) == 2 and "'npm test; true'" in gaps[0] and '`;`' in gaps[0] and '`|`' in gaps[1], gaps


@pytest.mark.parametrize('command,signs', [
    ('pytest -q', []), ('cd api && pytest -q', []), ('pytest -q || true', ['||']),
    ('npm audit; true', [';']), ('npm audit | tee out.txt', ['|']), ('server & pytest', ['&']),
    ('a || b; c | d', ['||', ';', '|']), ('a || b || c', ['||']), ('(pip-audit || true)', ['||']),
    # a redirection joins nothing
    ('pytest -q 2>&1', []), ('pytest &> out.txt', []), ('pytest >&2', []), ('make test >| out', []),
    ('pytest -q > out.txt 2>&1 || true', ['||']), ('pytest -q |& tee log', ['|&']),
    # quotes, escapes, substitutions and comments hide a sign
    ('pytest -k "a or b; c | d"', []), ("pytest -k 'a || b'", []), ('echo "a\\"; b" && pytest', []),
    ('find . -name "*.pyc" -exec rm {} \\; && pytest', []), ('pytest $(ls tests | head -1)', []),
    ('pytest `ls tests | head -1`', []), ('pytest ${X:-a|b}', []), ('pytest $(a $(b | c) | d) || true', ['||']),
    ('pytest -q  # fast; no network || true', []), ('curl http://x/#a; true', [';']),
    # what joins nothing: a sign with nothing after it, a line that goes on
    ('pytest -q;', []), ('npm audit\n', []), ('cd app &&\n  npm audit', []), ('pytest \\\n  -q', []),
    ('pytest -q &', ['&']), ('npm ci\nnpm audit', ['a line break']), ('a ;; b', [';;']),
    ('"unclosed || true', []), ('', []),
    ("echo 'a; b' && pytest", []), ('echo `a; b` && pytest', []), ("pytest $(echo ')|' )", []),
    ('pytest $(echo `)|`)', []), ('pytest $(echo ")|")', []), ("echo 'a' | tee log", ['|']),
    ('cd app && # first; then || this\npytest -q', []), ('cd app &&# note; more\n pytest', []),
])
def test_which_signs_join_commands(command, signs):
    assert load_doctor().joining_signs(command) == signs


def test_the_shell_reader_takes_a_very_long_entry_in_no_time():
    import time
    doctor = load_doctor()
    started = time.time()
    assert doctor.joining_signs('A=1 ' * 200_000 + '|| true') == ['||']
    assert doctor.joining_signs('$(' * 50_000) == [] and doctor.joining_signs('"' + '\\' * 100_001) == []
    assert time.time() - started < 5


def test_s17_is_skipped_where_there_is_nothing_to_audit(project):
    """003/FR-004, SC-003."""
    set_key(project, 'audit', [])
    track(project)
    r = run(DOCTOR, '--repo', project)
    skip = [l for l in r.stdout.splitlines() if l.strip().startswith('SKIP S17')]
    assert skip and 'no dependency manifest' in skip[0] and not gaps_of(r, 'S17'), r.stdout
    (project / 'package.json').write_text('{}', encoding='utf-8')          # on disk, not tracked
    assert 'S17' in lines(run(DOCTOR, '--repo', project), 'SKIP')
    track(project)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 1 and 'no dependency audit named' in gaps_of(r, 'S17')[0], r.stdout


@pytest.mark.parametrize('name', ['requirements-dev.txt', 'pyproject.toml', 'Pipfile', 'poetry.lock', 'uv.lock',
                                  'web/package.json', 'composer.json', 'go.mod', 'Cargo.toml', 'Gemfile',
                                  'app/pubspec.yaml', 'requirements.txt'])
def test_s17_every_dependency_manifest_counts_at_any_depth(project, name):
    set_key(project, 'audit', [])
    (project / name).parent.mkdir(exist_ok=True)
    (project / name).write_text('', encoding='utf-8')
    track(project, commit=False)
    assert gaps_of(run(DOCTOR, '--repo', project), 'S17')


def test_s17_skip_is_not_given_on_a_guess(project):
    track(project)
    for audit in ('pip-audit', ['true'], [3]):          # somebody tried to name one
        set_key(project, 'audit', audit)
        assert gaps_of(run(DOCTOR, '--repo', project), 'S17'), audit


def test_s17_a_null_audit_is_skipped_like_an_empty_one(project):
    track(project)
    set_key(project, 'audit', None)
    r = run(DOCTOR, '--repo', project)
    assert 'S17' in lines(r, 'SKIP') and not gaps_of(r, 'S17'), r.stdout


def test_s17_a_recorded_deviation_does_not_turn_the_skip_into_a_gap(project):
    track(project)
    data = manifest(project)
    data['projects'][0]['audit'] = []
    data['projects'][0]['deviations'] = [{'rule': 'S17', 'reason': 'r', 'fix': 'f'}]
    save(project, data)
    r = run(DOCTOR, '--repo', project)
    assert r.returncode == 0 and 'S17' in lines(r, 'SKIP') and not gaps_of(r, 'S17'), r.stdout
    assert 'note: S17' in r.stderr and 'can be removed' in r.stderr, r.stderr
    feature(project, '001-a')            # for any other rule the message stays
    data['projects'][0]['deviations'] = [{'rule': 'S10', 'reason': 'r', 'fix': 'f'}]
    save(project, data)
    assert 'S10 listed under deviations but there is nothing to judge' in run(DOCTOR, '--repo', project).stdout


def two_projects(project, first, second):
    data = manifest(project)
    one = dict(data['projects'][0], audit=[])
    data['projects'] = [dict(one, name='a', root=first), dict(one, name='b', root=second)]
    save(project, data)
    for root in (first, second):
        (project / root).mkdir(parents=True, exist_ok=True)


def s17_by_project(result):
    out, name = {}, None
    for line in result.stdout.splitlines():
        if line.startswith('project '):
            name = line.split()[1]
        elif name and ' S17 ' in line:
            out[name] = line.split()[0]
    return out


def test_s17_a_manifest_under_another_projects_root_is_that_projects(project):
    two_projects(project, '.', 'b')
    (project / 'b' / 'package.json').write_text('{}', encoding='utf-8')
    track(project)
    r = run(DOCTOR, '--repo', project)
    assert s17_by_project(r) == {'a': 'SKIP', 'b': 'GAP'}, r.stdout
    (project / 'tools').mkdir()
    (project / 'tools' / 'go.mod').write_text('', encoding='utf-8')       # below `a`, in no other project
    track(project)
    assert s17_by_project(run(DOCTOR, '--repo', project)) == {'a': 'GAP', 'b': 'GAP'}


def test_s17_a_manifest_above_the_project_root_counts_for_the_project(project):
    two_projects(project, 'services/api', 'services/web')
    track(project)
    assert s17_by_project(run(DOCTOR, '--repo', project)) == {'a': 'SKIP', 'b': 'SKIP'}
    (project / 'services' / 'web' / 'package.json').write_text('{}', encoding='utf-8')   # a sibling's is not above
    track(project)
    assert s17_by_project(run(DOCTOR, '--repo', project)) == {'a': 'SKIP', 'b': 'GAP'}
    (project / 'pyproject.toml').write_text('', encoding='utf-8')
    track(project)
    r = run(DOCTOR, '--repo', project)
    assert s17_by_project(r) == {'a': 'GAP', 'b': 'GAP'}, r.stdout


@pytest.mark.parametrize('name', ['setup.py', 'setup.cfg', 'pom.xml', 'build.gradle', 'build.gradle.kts', 'app/Api.csproj',
                                  'Pipfile.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'composer.lock',
                                  'go.sum', 'Cargo.lock', 'Gemfile.lock', 'requirements/base.txt'])
def test_s17_lockfiles_and_other_build_manifests_count(project, name):
    set_key(project, 'audit', [])
    (project / name).parent.mkdir(exist_ok=True)
    (project / name).write_text('', encoding='utf-8')
    track(project, commit=False)
    assert gaps_of(run(DOCTOR, '--repo', project), 'S17')


def test_s17_a_text_file_elsewhere_is_no_dependency_manifest(project):
    set_key(project, 'audit', [])
    (project / 'notes').mkdir()
    for name in ('notes/todo.txt', 'requirements.md', 'notes/setup.pyc'):
        (project / name).write_text('', encoding='utf-8')
    track(project, commit=False)
    assert 'S17' in lines(run(DOCTOR, '--repo', project), 'SKIP')


def test_s01_gap_on_a_joined_test_says_it_cannot_be_a_deviation(project):
    set_key(project, 'test', ['pytest -q || true'])
    gap = gaps_of(run(DOCTOR, '--repo', project), 'S01')[0]
    assert 'S01 cannot be recorded as a deviation' in gap and 'entry has to change' in gap, gap
    set_key(project, 'test', ['pytest -q'])
    set_key(project, 'audit', ['pip-audit || true'])
    assert 'cannot be recorded' not in gaps_of(run(DOCTOR, '--repo', project), 'S17')[0]


def test_lint_features_reads_the_specs_of_the_root_it_is_given(project):
    two_projects(project, '.', 'api')
    feature(project, '001-top')
    feature(project / 'api', '002-api')
    assert lint_features(project, 'api')[:2] == (0, ['002-api'])
    assert lint_features(project, '.')[:2] == (0, ['001-top'])


def test_lint_features_does_not_list_a_symlinked_feature(project, tmp_path_factory):
    feature(project, '001-a')
    elsewhere = tmp_path_factory.mktemp('elsewhere') / '002-b'
    elsewhere.mkdir()
    link(project / 'specs' / '002-b', elsewhere)
    assert lint_features(project)[1] == ['001-a']


def test_s17_a_manifest_outside_the_project_root_is_not_the_projects(tmp_path):
    doctor = load_doctor()
    (tmp_path / 'api').mkdir()
    (tmp_path / 'api' / 'main.py').write_text('', encoding='utf-8')
    (tmp_path / 'package.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'web').mkdir()
    (tmp_path / 'web' / 'go.mod').write_text('', encoding='utf-8')
    assert doctor.tracks_dependencies(tmp_path / 'api', tmp_path) is None          # no repository: nobody knows
    track(tmp_path, commit=False)
    assert doctor.tracks_dependencies(tmp_path / 'web', tmp_path) is True
    assert doctor.tracks_dependencies(tmp_path / 'api', tmp_path) is True          # the one at the git root is above it
    (tmp_path / 'package.json').unlink()
    track(tmp_path, commit=False)
    assert doctor.tracks_dependencies(tmp_path / 'api', tmp_path) is False         # a sibling's is not
    assert doctor.tracks_dependencies(tmp_path, tmp_path) is True
    assert doctor.tracks_dependencies(tmp_path, tmp_path, [tmp_path / 'web']) is False


def lint_features(project, root='.'):
    r = run(DOCTOR, '--repo', project, '--lint-features', root)
    return r.returncode, r.stdout.split(), r.stderr


def test_lint_features_leaves_out_what_is_recorded_as_debt(project):
    """003/FR-009: the names the gate hands to the lint."""
    assert lint_features(project) == (0, [], '')
    feature(project, '001-a')
    feature(project, '004-old', status=None)
    feature(project, '005-closed', status='Closed')
    assert lint_features(project)[1] == ['001-a', '004-old', '005-closed']
    data = manifest(project)
    data['projects'][0]['deviations'] = [
        {'rule': 'S07', 'reason': 'r', 'fix': 'f', 'features': ['004-old', '009-gone']},
        {'rule': 'S10', 'reason': 'r', 'fix': 'f', 'features': ['001-a']},           # not one of S04 to S09
        {'rule': 'S11', 'reason': 'r', 'fix': 'f', 'features': ['005-closed']}]
    save(project, data)
    code, names, said = lint_features(project)
    assert (code, names) == (0, ['001-a', '005-closed']) and 'left out' in said and '004-old' in said
    assert '001-a' not in said
    assert '009-gone' not in said and '005-closed' not in said
    assert run(LINT, '--root', project, *names).returncode == 0
    assert run(LINT, '--root', project, '004-old').returncode == 1
    r = run(DOCTOR, '--repo', project, '--lint-features', 'nowhere')
    assert r.returncode == 2 and r.stdout == '' and 'nowhere' in r.stderr


@pytest.mark.parametrize('rule', ['S04', 'S05', 'S06', 'S07', 'S08', 'S09'])
def test_lint_features_reads_each_rule_from_s04_to_s09(project, rule):
    feature(project, '004-old', status=None)
    data = manifest(project)
    data['projects'][0]['deviations'] = [{'rule': rule, 'reason': 'r', 'fix': 'f', 'features': ['004-old']}]
    save(project, data)
    code, names, said = lint_features(project)
    if rule == 'S08':                                 # 016/FR-001: a feature waiting for its ticket is linted
        assert (code, names, said) == (0, ['004-old'], '')
    else:
        assert (code, names) == (0, []) and '004-old' in said


# Spec 004: a pull request proves the project's tests ran (rule S19).

ENTRY = 'python -m pytest -q'
RUNS = f'      - run: {ENTRY}\n'


def workflow(project, body, name='ci.yml'):
    path = project / '.github' / 'workflows' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding='utf-8')


def ci(project, steps=RUNS, on='on: pull_request\n', job='', name='ci.yml'):
    """One workflow of one job `test`; `job` is extra keys of the job, `steps` its steps, both as YAML."""
    workflow(project, f'{on}jobs:\n  test:\n    runs-on: ubuntu-latest\n{job}    steps:\n{steps}', name)


def doctor_all(project):
    return run(DOCTOR, '--repo', project, '--all')


def s19(result):
    """What the doctor says on S19 for the first project: PASS, GAP, DEBT or SKIP."""
    found = [l.split()[0] for l in result.stdout.splitlines() if l.split()[1:2] == ['S19']]
    assert found, result.stdout
    return found[0]


def by_project(result, rule):
    out, name = {}, None
    for line in result.stdout.splitlines():
        if line.startswith('project '):
            name = line.split()[1]
        elif name and line.split()[1:2] == [rule]:
            out.setdefault(name, line.split()[0])
    return out


def test_s19_a_step_that_runs_the_entry_on_pull_requests_passes(project):
    """004/FR-001, 004/FR-002, SC-001."""
    ci(project)
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout and r.returncode == 0, r.stdout


def test_s19_the_entry_is_matched_word_for_word(project):
    """004/FR-001, 004/FR-002, 004/FR-007, SC-002."""
    ci(project, '      - run: make test\n')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and ENTRY in gaps[0] and 'ci.yml' in gaps[0], r.stdout
    set_key(project, 'test', ['make test'])
    assert 'PASS S19' in doctor_all(project).stdout


@pytest.mark.parametrize('steps', [
    '      - run: pip install -r requirements.txt && python -m pytest -q\n',
    '      - run: CI=1 python -m pytest -q\n',
    '      - run: |\n          pip install -r requirements.txt\n          python -m pytest -q\n',
    # edges
    '      - run: CI=1 FOO=2 python -m pytest -q\n',
    '      - run: >\n          python -m pytest\n          -q\n',
    '      - run: |\n          python -m pytest \\\n            -q\n',
    '      - run: python -m pytest -q   # the whole suite; no network\n',
    '      - uses: actions/checkout@v4\n      - name: nothing to run\n      - run: python -m pytest -q\n',
    '      - run: python -m pytest -q\n        continue-on-error: false\n',
    "      - run: python -m pytest -q\n        continue-on-error: 'false'\n",
    "      - run: python -m pytest -q\n        if: github.event_name == 'pull_request'\n",
    '      - run: python -m pytest -q\n        if: ${{ always() }}\n',
    '      - run: python -m pytest -q || true\n      - run: python -m pytest -q\n',
    "      - run: python -m pytest -q\n        continue-on-error: ' false '\n",
    '      - run: |\n          echo start\n          pip install . && python -m pytest -q\n\n          # done\n',
    '      - run: |\n          pip install .\n          FOO=1 python -m pytest -q\n          echo done && true\n',
    '      - run: |\n          pip install -e .\n\n          # the whole suite\n          python -m pytest -q\n',
    '      - run: |\n          set -euo pipefail\n          python -m pytest -q\n',
    '      - run: |\n          set -e\n          set -x -u\n          python -m pytest -q\n',
    '      - run: |\n          export FOO=1\n          python -m pytest -q\n',
    '      - run: |\n          FOO=1\n          echo "$FOO; $(date) {x} | y" > "out file.txt" 2>&1\n          python -m pytest -q\n',
    '      - run: |\n          python -m pytest -q\n          if [ -f x ]; then echo; fi\n          cmd || true\n          set +e\n',
    '      - run: python -m pytest -q\n        shell: bash\n',
    '      - run: python -m pytest -q\n        shell: sh\n',
    '      - run: python -m pytest -q\n        shell: bash -e {0}\n',
    '      - run: |\n          cd .\n          python -m pytest -q\n',
    '      - run: "python -m pytest -q\\r\\n"\n',
])
def test_s19_steps_that_run_the_entry(project, steps):
    """004/FR-002, SC-003."""
    ci(project, steps)
    r = doctor_all(project)
    assert s19(r) == 'PASS', r.stdout


@pytest.mark.parametrize('steps,job,word', [
    ('      - run: python -m pytest -q || true\n', '', '`||`'),
    ('      - run: python -m pytest -q | tee out.txt\n', '', '`|`'),
    ('      - run: python -m pytest -q; echo done\n', '', '`;`'),
    ('      - run: python -m pytest -q && echo ok\n', '', '`&&`'),
    ('      - run: python -m pytest -q && echo ok || true\n', '', '(`||`)'),
    ('      - run: python -m pytest -q && echo ok; exit 0\n', '', '(`;`)'),
    ('      - run: |\n          python -m pytest -q && echo ok\n          echo done\n', '', '`&&`'),
    ('      - run: true || python -m pytest -q\n', '', '(`||`)'),
    ('      - run: python -m pytest -q --cov\n', '', ''),
    ('      - run: echo "python -m pytest -q"\n', '', ''),
    ('      - run: python -m pytest -q\n        continue-on-error: true\n', '', 'continue-on-error'),
    (RUNS, '    continue-on-error: true\n', 'continue-on-error'),
    ('      - run: python -m pytest -q\n        if: false\n', '', '`if: false`'),
    # edges
    ('      - run: python -m pytest -q &\n', '', '`&`'),
    ('      - run: python -m pytest -q |& tee log\n', '', '`|&`'),
    ('      - run: python -m pytest -q;\n', '', '`;`'),
    ("      - run: echo 'python -m pytest -q'\n", '', ''),
    ('      - run: |\n          # python -m pytest -q\n          make test\n', '', ''),
    ('      - run: echo python -m pytest -q\n', '', ''),
    ('      - run: sh -c "python -m pytest -q"\n', '', ''),
    ('      - run: echo $(python -m pytest -q)\n', '', ''),
    ('      - run: python -m pytest\n      - run: -q\n', '', ''),
    ('      - run: python -m pytest -q > out.txt\n', '', ''),
    ("      - run: python -m pytest -q\n        continue-on-error: 'true'\n", '', 'continue-on-error'),
    ('      - run: python -m pytest -q\n        continue-on-error: ${{ matrix.experimental }}\n', '', 'continue-on-error'),
    (RUNS, "    continue-on-error: 'true'\n", 'continue-on-error'),
    (RUNS, '    continue-on-error: ${{ matrix.experimental }}\n', 'continue-on-error'),
    ("      - run: python -m pytest -q\n        if: 'false'\n", '', '`if: false`'),
    ("      - run: python -m pytest -q\n        if: ' false '\n", '', '`if: false`'),
    ('      - run: setup; python -m pytest -q\n', '', '(`;`)'),
    ('      - run: cat x | python -m pytest -q\n', '', '(`|`)'),
    ('      - run: server & python -m pytest -q\n', '', '(`&`)'),
    ('      - run: (python -m pytest -q) || true\n', '', '(`(`)'),
    ('      - run: (python -m pytest -q)\n', '', '(`(`)'),
    ('      - run: |\n          pip install . &&\n            python -m pytest -q\n', '', '(`&&`)'),
    ('      - run: |\n          && python -m pytest -q\n', '', '(`&&`)'),
    ('      - run: pip install . || true && python -m pytest -q\n', '', '(`||`)'),
    (RUNS, '    if: false\n', '`if: false`'),
    (RUNS, "    if: 'false'\n", '`if: false`'),
    ('      - name: no command here\n      - uses: actions/checkout@v4\n', '', ''),
])
def test_s19_steps_that_do_not_count(project, steps, job, word):
    """004/FR-002, 004/FR-004, 004/FR-005, SC-004. Where a step holds the entry, the gap says why it is not counted."""
    ci(project, steps, job=job)
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and repr(ENTRY) in gaps[0], r.stdout
    assert word in gaps[0], gaps[0]


@pytest.mark.parametrize('on,counts', [
    ('on: push\n', False),
    ('on:\n  pull_request:\n    branches: [develop]\n', False),
    ('on:\n  pull_request:\n    branches: [main]\n', True),
    ('on: [push, pull_request]\n', True),
    # edges
    ('on: pull_request\n', True),
    ('on:\n  pull_request:\n', True),
    ('on:\n  push:\n    branches: [main]\n  pull_request:\n    types: [opened, synchronize]\n', True),
    ('on:\n  pull_request:\n    branches:\n      - develop\n      - main\n', True),
    ('on:\n  pull_request:\n    branches: main\n', True),
    ('"on":\n  pull_request:\n    paths: ["src/**"]\n', True),
    ('on:\n  pull_request:\n    branches: ["**"]\n', False),
    ('on:\n  pull_request:\n    branches: ["ma*"]\n', False),
    ('on:\n  pull_request:\n    branches: [mainline]\n', False),
    ('on:\n  pull_request:\n    branches: mainline\n', False),
    ('on:\n  pull_request:\n    branches: [maintenance, main]\n', True),
    ('on:\n  pull_request:\n    types: [closed]\n', False),
    ('on:\n  pull_request:\n    types: closed\n', False),
    ('on:\n  pull_request:\n    types: [opened, reopened]\n', False),
    ('on:\n  pull_request:\n    types: synchronize\n', True),
    ('on:\n  pull_request:\n    types:\n', True),
    ('on:\n  pull_request:\n    branches: [main]\n    types: [labeled]\n', False),
    ('on: [push, workflow_dispatch]\n', False),
    ('on: pull_request_target\n', False),
    ('on:\n  pull_request_target:\n  push:\n', False),
    ('on: workflow_dispatch\n', False),
    ('', False),
])
def test_s19_a_workflow_counts_only_on_pull_requests_to_the_target(project, on, counts):
    """004/FR-003, 004/FR-007, SC-005."""
    ci(project, on=on)
    r = doctor_all(project)
    if counts:
        assert s19(r) == 'PASS', r.stdout
    else:
        gaps = gaps_of(r, 'S19')
        assert len(gaps) == 1 and 'ci.yml' in gaps[0] and 'not on pull requests to main' in gaps[0], r.stdout


def test_s19_the_target_is_the_projects_own(project):
    """004/FR-003: `release.pr_target` decides, not the name `main`."""
    data = manifest(project)
    data['projects'][0]['release']['pr_target'] = 'develop'
    save(project, data)
    ci(project, on='on:\n  pull_request:\n    branches: [main]\n')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1 and 'ci.yml (not on pull requests to develop)' in gaps[0], gaps
    ci(project, on='on:\n  pull_request:\n    branches: [develop]\n')
    assert s19(doctor_all(project)) == 'PASS'


def test_s19_without_a_workflow_file_the_gap_says_so(project):
    """004/FR-009, SC-006."""
    import shutil
    shutil.rmtree(project / '.github')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and 'no workflow file' in gaps[0] and repr(ENTRY) in gaps[0], r.stdout
    (project / '.github' / 'workflows').mkdir(parents=True)
    (project / '.github' / 'workflows' / 'notes.txt').write_text('on: pull_request\n', encoding='utf-8')
    assert 'no workflow file' in gaps_of(doctor_all(project), 'S19')[0]


def test_s19_a_file_that_is_not_a_workflow_is_named_as_not_judged(project):
    """004/FR-008, SC-007."""
    ci(project, '      - run: make test\n')
    workflow(project, 'on: [pull_request\njobs: {\n', 'broken.yml')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and 'broken.yml not judged' in gaps[0], r.stdout
    assert 'ci.yml (on pull requests to main)' in gaps[0]


@pytest.mark.parametrize('body', ['', '- a\n- b\n', 'just words\n', 'on: pull_request\n', 'on: pull_request\njobs: [a]\n',
                                  'a: &a [x, x, x, x, x, x, x, x, x]\nb: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a]\n'
                                  'c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b]\nd: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c]\n'
                                  'e: &e [*d, *d, *d, *d, *d, *d, *d, *d, *d]\nf: [*e, *e, *e, *e, *e, *e, *e, *e, *e]\n',
                                  '# ' + 'x' * 200_001 + '\n'],
                         ids=['empty', 'list', 'words', 'no-jobs', 'jobs-list', 'aliases', 'large'])
def test_s19_what_cannot_be_read_as_a_workflow(project, body):
    """004/FR-008: an empty file, a list, a file with no jobs, one built to expand, one too large. Never a crash."""
    ci(project, '      - run: make test\n')
    workflow(project, body, 'odd.yml')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and 'odd.yml not judged' in gaps[0], r.stdout + r.stderr


def test_s19_a_broken_file_does_not_hide_a_step_that_runs_the_entry(project):
    ci(project)
    workflow(project, 'on: [pull_request\n', 'broken.yml')
    assert s19(doctor_all(project)) == 'PASS'


def test_s19_a_job_that_calls_another_workflow_or_a_local_action_is_not_judged(project):
    """004/FR-008, SC-007."""
    workflow(project, 'on: pull_request\njobs:\n  suite:\n    uses: ./.github/workflows/tests.yml\n')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1, r.stdout
    assert 'ci.yml job suite not judged' in gaps[0] and './.github/workflows/tests.yml' in gaps[0], gaps[0]
    workflow(project, 'on: pull_request\njobs:\n  composite:\n    runs-on: ubuntu-latest\n    steps:\n'
                      '      - uses: actions/checkout@v4\n      - uses: ./.github/actions/run-tests\n')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert 'ci.yml job composite not judged' in gaps[0] and './.github/actions/run-tests' in gaps[0], gaps[0]
    assert 'actions/checkout' not in gaps[0]
    workflow(project, 'on: pull_request\njobs:\n  suite:\n    uses: ./.github/workflows/tests.yml\n'
                      f'  unit:\n    runs-on: ubuntu-latest\n    steps:\n{RUNS}')
    assert s19(doctor_all(project)) == 'PASS'         # another job runs it: nothing is left to say


def test_s19_jobs_and_steps_of_another_shape_are_passed_over(project):
    workflow(project, 'on: pull_request\njobs:\n  a: nothing\n  b:\n    steps: none\n  c:\n    steps:\n      - just a word\n'
                      '      - run: [not, text]\n      - run:\n  d:\n    runs-on: ubuntu-latest\n    steps:\n' + RUNS)
    r = doctor_all(project)
    assert s19(r) == 'PASS', r.stdout + r.stderr


def test_s19_two_workflow_files_are_both_read_and_named(project):
    """004/FR-007."""
    ci(project, on='on: push\n', name='deploy.yml')
    ci(project, '      - run: ruff check .\n', name='lint.yaml')
    (project / '.github' / 'workflows' / 'ci.yml').unlink()
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1, gaps
    assert 'deploy.yml (not on pull requests to main)' in gaps[0] and 'lint.yaml (on pull requests to main)' in gaps[0]
    assert 'kit-gate.yml (on pull requests to main)' in gaps[0]       # the gate is a workflow that was read
    ci(project, name='tests.yaml')
    assert s19(doctor_all(project)) == 'PASS'


def test_s19_the_gap_says_the_two_ways_out(project):
    """004/FR-007: make a workflow run it, or record the debt and name it."""
    ci(project, '      - run: make test\n')
    gap = gaps_of(doctor_all(project), 'S19')[0]
    assert 'run each entry on pull requests to main' in gap and 'deviation on S19' in gap and '`names:' in gap, gap


def test_s19_a_recorded_deviation_names_the_entries_it_covers(project):
    """004/FR-011, SC-008."""
    ci(project, '      - run: make test\n')
    dev = {'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY]}
    deviate(project, [dev])
    r = doctor_all(project)
    assert 'DEBT S19' in r.stdout and not gaps_of(r, 'S19') and r.returncode == 0, r.stdout
    assert repr(ENTRY) in r.stdout and 'fix (from .claude/kit.yml): f' in r.stdout     # 019/FR-005
    data = manifest(project)
    data['projects'][0]['test'] = [ENTRY, 'npm test']
    save(project, data)
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and "not covered by the recorded deviation: 'npm test'" in gaps[0], r.stdout
    assert 'ci.yml (on pull requests to main)' in r.stdout          # 004/FR-007 holds for this gap too
    ci(project, RUNS + '      - run: npm test\n')
    r = doctor_all(project)
    assert r.returncode == 1 and 'S19 listed under deviations but conforms now: remove the entry' in r.stdout, r.stdout


def test_s19_a_listed_entry_that_a_step_now_runs_is_a_gap(project):
    """004/FR-011: the list only shrinks."""
    set_key(project, 'test', [ENTRY, 'npm test'])
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY, 'npm test']}])
    ci(project)                                    # runs the first, not the second
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and f'conforming now, remove: {ENTRY!r}' in gaps[0], r.stdout
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': ['npm test']}])
    r = doctor_all(project)
    assert 'DEBT S19' in r.stdout and not gaps_of(r, 'S19'), r.stdout


def test_s19_a_deviation_must_name_its_entries_under_names(project):
    """004/FR-011: S01 says which key the deviation takes."""
    ci(project, '      - run: make test\n')
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f'}])
    assert any('deviation S19 must name what it covers: `names:' in g for g in gaps_of(doctor_all(project), 'S01'))
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY], 'features': [ENTRY]}])
    assert any('takes `names`, not `features`' in g for g in gaps_of(doctor_all(project), 'S01'))
    deviate(project, [], top=[{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY]}])
    assert gaps_of(doctor_all(project), 'S01')      # a project rule: not in the top-level list


def test_s19_is_skipped_without_an_entry_or_a_target(project):
    """004/FR-010, SC-009."""
    set_key(project, 'test', [])
    r = doctor_all(project)
    assert 'SKIP S19' in r.stdout and 'test' in next(l for l in r.stdout.splitlines() if 'SKIP S19' in l), r.stdout
    data = manifest(project)
    data['projects'][0]['test'] = [ENTRY]
    data['projects'][0]['release']['pr_target'] = None
    data['projects'][0]['deviations'] = [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY]}]
    save(project, data)
    r = doctor_all(project)
    line = next(l for l in r.stdout.splitlines() if 'SKIP S19' in l)
    assert 'release.pr_target' in line and not gaps_of(r, 'S19'), r.stdout
    assert 'S19' not in r.stderr, r.stderr          # nobody is told to remove a deviation the scaffold wrote
    for bad in ('pytest', None, [3]):
        data['projects'][0]['test'] = bad
        save(project, data)
        assert 'SKIP S19' in doctor_all(project).stdout
    assert 'SKIP S19' in run(DOCTOR, '--repo', project / 'specs', '--all').stdout      # no manifest: no entry


def monorepo(project, entry='npm test'):
    data = manifest(project)
    one = dict(data['projects'][0], test=[entry], audit=[])
    data['projects'] = [dict(one, name='api', root='api'), dict(one, name='web', root='web')]
    save(project, data)
    for root in ('api', 'web'):
        (project / root).mkdir(exist_ok=True)


def test_s19_a_step_run_in_another_projects_directory_does_not_prove_this_one(project):
    """004/FR-006, SC-010."""
    monorepo(project)
    ci(project, '      - run: npm test\n        working-directory: api\n')
    r = doctor_all(project)
    assert by_project(r, 'S19') == {'api': 'PASS', 'web': 'GAP'}, r.stdout
    assert any("'npm test'" in g and 'in api' in g for g in gaps_of(r, 'S19')), r.stdout
    ci(project, '      - run: npm test\n        working-directory: api\n      - run: cd web && npm test\n')
    r = doctor_all(project)
    assert by_project(r, 'S19') == {'api': 'PASS', 'web': 'PASS'}, r.stdout


@pytest.mark.parametrize('steps,job,top,expected', [
    ('      - run: npm test\n        working-directory: ./api\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: ./api/\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: npm test\n', '    defaults:\n      run:\n        working-directory: ./api\n', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: npm test\n', '', 'defaults:\n  run:\n    working-directory: web\n', {'api': 'GAP', 'web': 'PASS'}),
    ('      - run: npm test\n        working-directory: web\n', '    defaults:\n      run:\n        working-directory: api\n', '',
     {'api': 'GAP', 'web': 'PASS'}),
    ('      - run: cd api && npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: cd ./api/ && npm ci && npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: cd api && npm test && cd ../web && npm test\n', '', '', {'api': 'GAP', 'web': 'PASS'}),
    ('      - run: |\n          cd api && npm test\n          cd ../web && npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: |\n          cd api && npm ci\n          npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: |\n          cd api\n          npm ci\n          npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: |\n          cd api\n          npm ci && npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: |\n          (cd api && npm test)\n          (cd web && npm test)\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: |\n          cd api\n          npm ci\n          npm test\n          cd ../web\n          npm test\n', '', '',
     {'api': 'PASS', 'web': 'PASS'}),
    ('      - run: |\n          cd api\n          npm ci\n\n          npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: |\n          cd web\n          npm test\n        working-directory: api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: |\n          cd "api"\n          npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: |\n          (cd api && npm ci)\n          cd web\n          npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: (cd api && npm ci) && npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: |\n          (pushd api)\n          cd web && npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: .' + chr(92) + 'api\n', '', '', {'api': 'PASS', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: api/../web\n', '', '', {'api': 'GAP', 'web': 'PASS'}),
    ('      - run: (cd api && npm test)\n      - run: (cd web && npm test)\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: cd api && npm test\n      - run: cd web && npm test\n', '', '', {'api': 'PASS', 'web': 'PASS'}),
    ('      - run: cd src && npm test\n        working-directory: api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),                    # at the git root
    ('      - run: |\n          cd api\n          npm test\n', '', '', {'api': 'PASS', 'web': 'GAP'}),   # the state of the script
    ('      - run: cd api; npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: cd api || npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: cd "$TARGET" && npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: ${{ matrix.dir }}\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: /srv/api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: cd ../api && npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: cd apiary && npm test\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: ~/api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: C:/api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: $HOME/api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ("      - run: npm test\n        working-directory: ''\n", '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('''      - run: npm test\n        working-directory: '"api"'\n''', '', '', {'api': 'GAP', 'web': 'GAP'}),
    ('      - run: npm test\n        working-directory: ../api\n', '', '', {'api': 'GAP', 'web': 'GAP'}),
])
def test_s19_where_a_step_runs(project, steps, job, top, expected):
    """004/FR-006: `working-directory` on the step, `defaults.run.working-directory`, `cd <root> &&` on the line."""
    monorepo(project)
    ci(project, steps, on=f'on: pull_request\n{top}', job=job)
    r = doctor_all(project)
    assert by_project(r, 'S19') == expected, r.stdout + r.stderr


def test_s19_a_step_run_below_the_root_does_not_prove_a_project_at_the_root(project):
    """004/FR-006, the other way round: the entry of the project at `.` is not run by a step in `api`."""
    ci(project, '      - run: python -m pytest -q\n        working-directory: api\n')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1 and 'in api' in gaps[0], gaps
    ci(project, '      - run: cd api && python -m pytest -q\n')
    assert s19(doctor_all(project)) == 'GAP'
    ci(project, '      - run: python -m pytest -q\n        working-directory: ./\n')
    assert s19(doctor_all(project)) == 'PASS'


def test_s19_an_entry_with_its_own_joins_and_assignments(project):
    """004/FR-002: the entry's own `&&` is part of what a step must hold."""
    set_key(project, 'test', ['cd api && pytest -q'])
    for steps, verdict in (('      - run: cd api && pytest -q\n', 'PASS'),
                           ('      - run: pip install . && cd api && pytest -q\n', 'PASS'),
                           ('      - run: pip install . && cd api && pytest -q && echo ok\n', 'GAP'),
                           ('      - run: cd api && CI=1 pytest -q\n', 'PASS'),
                           ('      - run: |\n          cd api &&\n            pytest -q\n', 'GAP'),
                           ('      - run: pytest -q\n', 'GAP'),
                           ('      - run: pytest -q\n        working-directory: api\n', 'GAP'),
                           ('      - run: |\n          cd api\n          pytest -q\n', 'GAP'),
                           ('      - run: cd api || pytest -q\n', 'GAP'),
                           ('      - run: cd api && pytest -q || true\n', 'GAP')):
        ci(project, steps)
        r = doctor_all(project)
        assert s19(r) == verdict, (steps, r.stdout)
    set_key(project, 'test', ['CI=1 pytest -q'])            # the entry is never stripped
    for steps, verdict in (('      - run: CI=1 pytest -q\n', 'PASS'), ('      - run: pytest -q\n', 'GAP'),
                           ('      - run: FOO=2 CI=1 pytest -q\n', 'GAP')):
        ci(project, steps)
        assert s19(doctor_all(project)) == verdict, steps


def test_s19_each_entry_is_judged_and_only_the_missing_are_quoted(project):
    """004/FR-001, 004/FR-007."""
    set_key(project, 'test', [ENTRY, 'npm test', 'make e2e'])
    ci(project, RUNS + '      - run: npm test || true\n')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1 and "'make e2e', 'npm test'" in gaps[0] and repr(ENTRY) not in gaps[0], gaps


@pytest.mark.parametrize('text,commands', [
    ('python -m pytest -q', [(['python', '-m', 'pytest', '-q'], '')]),
    ('a && b || c; d | e & f\ng', [(['a'], '&&'), (['b'], '||'), (['c'], ';'), (['d'], '|'), (['e'], '&'), (['f'], '\n'), (['g'], '')]),
    ('CI=1 pytest "a; b" $(x | y) # c; d\n\n\n', [(['CI=1', 'pytest', '"a; b"', '$(x | y)'], '\n')]),
    ('a 2>&1 && b', [(['a', '2>&1'], '&&'), (['b'], '')]),
    ('a \\\n  b &&\n  c', [(['a', 'b'], '&&'), (['c'], '')]),
    ('', []), ('  # only a comment', []), ('&& a', [(['a'], '')]),
])
def test_the_commands_of_a_run_text(text, commands):
    """004/FR-002: a command is what stands between two cuts, read by the reader S01 and S17 use."""
    assert load_doctor().shell_commands(text) == commands


def test_s19_a_very_long_run_text_is_read_in_no_time(project):
    """004/FR-002: one pass, no backtracking, whatever the text holds."""
    import time
    doctor = load_doctor()
    started = time.time()
    for text in ('A=1 ' * 25_000, 'python -m pytest -q && ' * 5_000, 'cd a && ' * 12_500, 'python -m pytest -q || true\n' * 4_000,
                 '$(' * 50_000, '"' + '\\' * 100_000, 'python ' * 15_000, ';|&' * 33_334, 'x' * 100_000):
        assert len(text) >= 100_000
        doctor.shell_commands(text)
    assert time.time() - started < 5
    monorepo(project, ENTRY)                       # the directory is asked for every command of the text
    for run_text in ('cd a && ' * 12_500 + ENTRY, (ENTRY + ' && ') * 5_000 + 'true', 'A=1 ' * 25_000 + ENTRY):
        ci(project, f'      - run: {run_text}\n')
        started = time.time()
        r = doctor_all(project)
        assert time.time() - started < 5 and by_project(r, 'S19').keys() == {'api', 'web'}, r.stdout[-500:] + r.stderr


def test_s19_the_profiles_that_write_an_entry_record_the_debt(tmp_path_factory):
    """004/FR-012, SC-011."""
    import yaml
    for profile, entries in (('python', [ENTRY]), ('laravel-vue', ['npm run build']), ('generic', None)):
        repo = tmp_path_factory.mktemp(profile)
        assert run(SCAFFOLD, '--repo', repo, '--profile', profile).returncode == 0
        project = yaml.safe_load((repo / '.claude' / 'kit.yml').read_text(encoding='utf-8'))['projects'][0]
        listed = {d['rule']: d for d in project['deviations']}
        assert project['test'] == (entries or []), profile
        assert (listed['S19']['names'] if entries else listed.get('S19')) == entries, profile
        r = doctor_all(repo)                        # as scaffolded: the release facts are still blank
        assert not gaps_of(r, 'S19'), r.stdout
        if not entries:
            continue
        fill(repo)                                  # what kit-init does next
        r = doctor_all(repo)
        assert 'DEBT S19' in r.stdout and not gaps_of(r, 'S19'), r.stdout
        assert repr(entries[0]) in r.stdout and 'kit-gate.yml (on pull requests to main)' in r.stdout


# Spec 004, after the review of the build.

THREE = {'root': '.', 'api': 'api', 'web': 'web'}


def three_projects(project, entry='npm test'):
    data = manifest(project)
    one = dict(data['projects'][0], test=[entry], audit=[])
    data['projects'] = [dict(one, name=name, root=root) for name, root in THREE.items()]
    save(project, data)
    for root in ('api', 'web'):
        (project / root).mkdir(exist_ok=True)


@pytest.mark.parametrize('run_text,expected,line', [
    ('(cd api && npm ci) && npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`(`)'),
    ('|\n          cd api\n          npm test', {'root': 'GAP', 'api': 'PASS', 'web': 'GAP'}, None),
    ('|\n          cd api\n          cd ..\n          npm test', {'root': 'PASS', 'api': 'GAP', 'web': 'GAP'}, None),
    ('|\n          cd api/\n          cd ../web\n          npm ci && npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'PASS'}, None),
    ('cd api; npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`;`)'),
    ('|\n          cd api || exit 1\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`||`)'),
    ('pushd api && npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`pushd`)'),
    ('|\n          npm ci\n          popd\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '2 holds shell this rule does not read (`popd`)'),
    ('|\n          cd\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd -\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd "$DIR"\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd ~/api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd /srv/api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd ../elsewhere\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd api web\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          FOO=1 cd api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          cd "api\'\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`cd`)'),
    ('|\n          { cd api; }\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`;`)'),
    ('|\n          {\n          cd api\n          }\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`{`)'),
    ('|\n          cd `pwd`/api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (```)'),
    ('|\n          cd ${{ matrix.dir }}\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`{`)'),
    ('|\n          cd api | tee log\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`|`)'),
    ('|\n          cd api &\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`&`)'),
    ('|\n          npm ci\n\n          # move\n          if [ -d api ]; then cd api; fi\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '4 holds shell this rule does not read (`;`)'),
    ('|\n          (pushd api && npm ci)\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`(`)'),
    ('|\n          true || cd api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`||`)'),
    ('|\n          echo x | cd api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`|`)'),
    ('|\n          cd api\n          true || cd ..\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '2 holds shell this rule does not read (`||`)'),
    ('|\n          f() { cd api; }\n          f\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`(`)'),
    ('|\n          function f {\n          cd api\n          }\n          f\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`{`)'),
    ('|\n          \\cd api\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`\\cd`)'),
    ('|\n          case x in\n            x) cd api ;;\n          esac\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`case`)'),
    ('|\n          unused() {\n            cd api\n          }\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`(`)'),
    ("|\n          eval 'cd api'\n          npm test", {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`eval`)'),
    ('|\n          source ./env.sh\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`source`)'),
    ('|\n          . ./env.sh\n          npm test', {'root': 'GAP', 'api': 'GAP', 'web': 'GAP'}, '1 holds shell this rule does not read (`.`)'),
    ('|\n          npm test\n          pushd api', {'root': 'PASS', 'api': 'GAP', 'web': 'GAP'}, None),
])
def test_s19_the_directory_is_the_state_of_the_script(project, run_text, expected, line):
    """004/FR-005, 004/FR-006: a plain `cd` moves the step and stays; a line that is not plain ends the reading,
    and the gap of each project names the line and what it holds."""
    three_projects(project)
    ci(project, f'      - run: {run_text}\n')
    r = doctor_all(project)
    assert by_project(r, 'S19') == expected, r.stdout + r.stderr
    if line:
        gaps = gaps_of(r, 'S19')
        assert len(gaps) == 3 and all(f'ci.yml job test step 1 not judged: line {line}' in g for g in gaps), r.stdout


def test_s19_names_and_entries_are_compared_without_the_blanks_around_them(project):
    """004/FR-011."""
    ci(project, '      - run: make test\n')
    data = manifest(project)
    data['projects'][0]['test'] = [ENTRY + ' ']
    data['projects'][0]['deviations'] = [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY + ' ']}]
    save(project, data)
    r = doctor_all(project)
    assert 'DEBT S19' in r.stdout and not gaps_of(r, 'S19') and r.returncode == 0, r.stdout
    data['projects'][0]['test'] = [ENTRY]
    data['projects'][0]['deviations'][0]['names'] = ['  ' + ENTRY]
    save(project, data)
    r = doctor_all(project)
    assert 'DEBT S19' in r.stdout and not gaps_of(r, 'S19'), r.stdout


def test_s19_a_listed_name_that_is_no_entry_is_said_to_be_that(project):
    """004/FR-011: `tox` under `names:` did not start to conform; it was never an entry."""
    ci(project, '      - run: make test\n')
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY, 'tox']}])
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1 and "'tox'" in gaps[0] and 'no `test` entry' in gaps[0], r.stdout
    assert 'conforming now' not in r.stdout


def test_s19_an_entry_that_runs_nothing_gets_no_gap_of_its_own(project):
    """004/FR-001: S01 (the manifest) already reports it; no workflow has to run `true`."""
    set_key(project, 'test', [ENTRY, 'true'])
    r = doctor_all(project)
    assert s19(r) == 'PASS', r.stdout
    ci(project, '      - run: make test\n')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1 and "'true'" not in gaps[0] and repr(ENTRY) in gaps[0], gaps
    set_key(project, 'test', ['true', 'echo ok'])
    r = doctor_all(project)
    assert 'SKIP S19' in r.stdout and gaps_of(r, 'S01'), r.stdout


def test_s19_the_gap_says_that_the_entry_is_matched_word_for_word(project):
    """004/FR-007."""
    ci(project, '      - run: pytest -q\n')
    gap = gaps_of(doctor_all(project), 'S19')[0]
    assert 'word for word' in gap and 'written another way does not count' in gap, gap
    assert 'write the entry as CI runs it, or the step as the manifest says' in gap, gap


def test_s19_an_empty_target_is_skipped(project):
    """004/FR-010."""
    data = manifest(project)
    data['projects'][0]['release']['pr_target'] = ''
    save(project, data)
    r = doctor_all(project)
    assert 'SKIP S19' in r.stdout and not gaps_of(r, 'S19'), r.stdout


def test_s19_files_that_exist_and_cannot_be_read_are_not_no_workflow_file(project):
    """004/FR-008, 004/FR-009."""
    import shutil
    shutil.rmtree(project / '.github' / 'workflows')
    workflow(project, 'on: [pull_request\n', 'broken.yml')
    workflow(project, '# ' + 'x' * 200_001 + '\n', 'huge.yml')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1 and 'no workflow file' not in gaps[0], gaps
    assert 'broken.yml not judged (does not parse' in gaps[0] and 'huge.yml not judged (is larger than 200 kB)' in gaps[0], gaps


def test_s19_a_job_not_judged_is_named_whatever_its_workflow_starts_on(project):
    """004/FR-008: said for a workflow that does not start on pull requests too; the owner sees where the tests may be."""
    ci(project, '      - run: make test\n')
    workflow(project, 'on: push\njobs:\n  suite:\n    uses: ./.github/workflows/tests.yml\n', 'deploy.yml')
    gap = gaps_of(doctor_all(project), 'S19')[0]
    assert 'deploy.yml (not on pull requests to main)' in gap and 'deploy.yml job suite not judged' in gap, gap


def test_s19_an_entry_written_twice_is_judged_once(project):
    set_key(project, 'test', [ENTRY, ENTRY, ' ' + ENTRY])
    ci(project, '      - run: python -m pytest -q || true\n')
    gaps = gaps_of(doctor_all(project), 'S19')
    assert len(gaps) == 1 and gaps[0].count(repr(ENTRY)) == 1, gaps


# Spec 004, after the second review of the build: a step is read line by line, and only plain lines are read.

@pytest.mark.parametrize('run_text,line,what', [
    ('|\n          (\n            python -m pytest -q\n          ) || true', 1, '('),
    ('|\n          {\n            python -m pytest -q\n          } || true', 1, '{'),
    ('|\n          t() {\n            python -m pytest -q\n          }\n          t || true', 1, '('),
    ('|\n          (\n            python -m pytest -q\n          ) &', 1, '('),
    ('|\n          {\n            python -m pytest -q\n          } | tee log', 1, '{'),
    ('|\n          set +e\n          python -m pytest -q', 1, 'set'),
    ('|\n          set -e +o pipefail\n          python -m pytest -q', 1, 'set'),
    ('|\n          set\n          python -m pytest -q', 1, 'set'),
    ('|\n          pip install .\n          shopt -u errexit\n          python -m pytest -q', 2, 'shopt'),
    ("|\n          trap 'exit 0' EXIT\n          python -m pytest -q", 1, 'trap'),
    ('|\n          if true; then\n          python -m pytest -q\n          fi', 1, ';'),
    ('|\n          if true\n          then\n          python -m pytest -q\n          fi', 1, 'if'),
    ('|\n          for i in 1 2\n          do\n          python -m pytest -q\n          done', 1, 'for'),
    ('|\n          while false\n          do\n          python -m pytest -q\n          done', 1, 'while'),
    ('|\n          ! true\n          python -m pytest -q', 1, '!'),
    ('|\n          exit 0\n          python -m pytest -q', 1, 'exit'),
    ('|\n          exec true\n          python -m pytest -q', 1, 'exec'),
    ('|\n          alias python=true\n          python -m pytest -q', 1, 'alias'),
    ('|\n          cat <<EOF\n          python -m pytest -q\n          EOF', 1, '<<'),
    ('|\n          X=$(mktemp)\n          python -m pytest -q', 1, '$('),
    ('|\n          X=`mktemp`\n          python -m pytest -q', 1, '`'),
    ('|\n          echo ${X}\n          python -m pytest -q', 1, '{'),
    ('|\n          [[ -f x ]]\n          python -m pytest -q', 1, '[['),
    ('|\n          time python -m pytest -q', 1, 'time'),
    ('|\n          true || cd api\n          python -m pytest -q', 1, '||'),
    ('|\n          builtin cd api\n          python -m pytest -q', 1, 'builtin'),
    ('|\n          command cd api\n          python -m pytest -q', 1, 'command'),
    ('|\n          echo a\n          echo b \\\n            c ; true\n          python -m pytest -q', 3, ';'),
    ('|\n          echo "a\n          b" ; true\n          python -m pytest -q', 2, ';'),
])
def test_s19_a_line_that_is_not_plain_ends_the_reading_of_the_step(project, run_text, line, what):
    """004/FR-005: the wrong passes of two reviews, and their kin. The entry is there; the step is not judged."""
    ci(project, f'      - run: {run_text}\n')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1, r.stdout
    assert f'ci.yml job test step 1 not judged: line {line} holds shell this rule does not read (`{what}`)' in gaps[0], gaps[0]


@pytest.mark.parametrize('extra,top,counts', [
    ('        shell: pwsh\n', '', False), ('        shell: python\n', '', False), ('        shell: cmd\n', '', False),
    ('        shell: bash --noprofile --norc -eo pipefail {0}\n', '', True), ('        shell: shell\n', '', False),
    ('', 'defaults:\n  run:\n    shell: pwsh\n', False), ('        shell: bash\n', 'defaults:\n  run:\n    shell: pwsh\n', True),
    ('', 'defaults:\n  run:\n    shell: bash\n', True), ('        shell: ${{ matrix.shell }}\n', '', False),
])
def test_s19_a_step_is_read_only_in_a_posix_shell(project, extra, top, counts):
    """004/FR-005: the lines are read as bash or sh reads them."""
    ci(project, RUNS + extra, on='on: pull_request\n' + top)
    r = doctor_all(project)
    if counts:
        assert s19(r) == 'PASS', r.stdout
    else:
        gaps = gaps_of(r, 'S19')
        assert len(gaps) == 1 and 'ci.yml job test step 1 not judged: its `shell` is ' in gaps[0], r.stdout


def test_s19_a_step_whose_directory_is_not_written_out_is_not_judged(project):
    """004/FR-006."""
    ci(project, RUNS + '        working-directory: ${{ matrix.dir }}\n')
    gap = gaps_of(doctor_all(project), 'S19')[0]
    assert 'ci.yml job test step 1 not judged: its `working-directory` is not a path written out' in gap, gap


def test_s19_a_step_not_judged_is_said_once_and_only_while_an_entry_is_missing(project):
    set_key(project, 'test', [ENTRY, 'npm test'])
    ci(project, '      - run: curl -s https://example.com/install.sh | sh\n' + RUNS + '      - run: npm test\n')
    r = doctor_all(project)
    assert s19(r) == 'PASS' and 'not judged' not in r.stdout, r.stdout
    ci(project, '      - run: curl -s https://example.com/install.sh | sh\n      - run: make test\n')
    gap = gaps_of(doctor_all(project), 'S19')[0]
    assert gap.count('ci.yml job test step 1 not judged: line 1 holds shell this rule does not read (`|`)') == 1, gap
    assert 'kit-gate.yml (on pull requests to main)' in gap and 'kit-gate.yml job' not in gap, gap     # the kit's own gate is read, and not listed step by step


def test_s19_names_and_entries_are_compared_with_runs_of_blanks_as_one(project):
    """004/FR-011: a step already matches the entry that way."""
    ci(project, '      - run: make test\n')
    set_key(project, 'test', ['python -m  pytest   -q'])
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [' python  -m pytest -q']}])
    r = doctor_all(project)
    assert 'DEBT S19' in r.stdout and not gaps_of(r, 'S19') and r.returncode == 0, r.stdout
    ci(project)
    r = doctor_all(project)
    assert 'S19 listed under deviations but conforms now' in r.stdout, r.stdout


def test_names_are_trimmed_for_s19_only(project):
    feature(project, '001-old', status='Implemented')
    deviate(project, [{'rule': 'S07', 'reason': 'r', 'fix': 'f', 'features': [' 001-old']}])
    r = doctor_all(project)
    assert 'S07 not covered by the recorded deviation: 001-old' in r.stdout, r.stdout


@pytest.mark.parametrize('run_text,line', [
    ('|\n          pip install . && python -m pytest -q\n          echo done', 1),
    ('|\n          echo start\n          pip install . && python -m pytest -q\n          echo done', 2),
    ('|\n          pip install . && pip install -e .\n          python -m pytest -q', 1),
    ('|\n          pip install .\n\n          a && b\n          python -m pytest -q', 3),
    ('|\n          pip install . && python -m pytest -q\n          if true; then echo; fi', 1),
])
def test_s19_a_line_joined_by_and_counts_only_as_the_last_line_of_the_step(project, run_text, line):
    """004/FR-005: bash -e does not stop when a command in front of `&&` fails, so the lines after it run without the entry."""
    ci(project, f'      - run: {run_text}\n')
    r = doctor_all(project)
    gaps = gaps_of(r, 'S19')
    assert r.returncode == 1 and len(gaps) == 1, r.stdout
    assert f'ci.yml job test step 1 not judged: line {line} holds shell this rule does not read (`&&`)' in gaps[0], gaps[0]


# Spec 006: tests that run in a called workflow prove the entry (rule S19).

USES = './.github/workflows/run-tests.yml'
CALL = f'ci.yml job tests not judged (it calls {USES}'
MAKE = '      - run: make test\n'
THROWN = f'      - run: {ENTRY} || true\n'


def caller(project, on='on: pull_request\n', job='', uses=USES, name='ci.yml', key='tests'):
    """A workflow of one job that calls another; `job` is extra keys of that job, as YAML."""
    workflow(project, f'{on}jobs:\n  {key}:\n    uses: {uses}\n{job}', name)


def called(project, steps=RUNS, on='on: workflow_call\n', job='', name='run-tests.yml'):
    """A workflow of one job `unit`; `job` is extra keys of the job, `steps` its steps, both as YAML."""
    workflow(project, f'{on}jobs:\n  unit:\n    runs-on: ubuntu-latest\n{job}    steps:\n{steps}', name)


def calling(project, name, key, uses):
    """A workflow that starts on `workflow_call` and holds one job, which calls `uses`."""
    workflow(project, f'on: workflow_call\njobs:\n  {key}:\n    uses: {uses}\n', name)


def gap19(result):
    """The gap on S19 as spec 006 reads it: from the line that holds `GAP  S19` to the next line that holds a
    verdict, a project or `summary:`."""
    out = []
    for line in result.stdout.splitlines():
        if out and (line.split()[:1] in (['PASS'], ['GAP'], ['DEBT'], ['SKIP']) or line.startswith(('project ', 'summary:'))):
            break
        if out or 'GAP  S19' in line:
            out.append(line)
    assert out, result.stdout + result.stderr
    return '\n'.join(out)


def test_s19_a_step_of_a_called_workflow_proves_the_entry(project):
    """006/FR-001, 006/FR-007, 006/FR-008, SC-001."""
    caller(project)
    called(project)
    assert 'PASS S19' in doctor_all(project).stdout
    called(project, MAKE)
    r = doctor_all(project)
    gap = gap19(r)
    assert "'python -m pytest -q'" in gap and 'run-tests.yml (called by ci.yml job tests)' in gap, gap
    assert CALL not in gap and 'run-tests.yml (not on pull requests to main)' not in gap, gap
    assert r.returncode == 1, r.stderr


def test_s19_a_called_file_without_workflow_call_is_not_followed(project):
    """006/FR-002, SC-002."""
    caller(project)
    called(project, on='on: push\n')
    assert CALL + ', which has no `workflow_call` under `on`)' in gap19(doctor_all(project))
    for on in ('on: [push, workflow_call]\n', 'on: {workflow_call: {inputs: {scope: {type: string}}}}\n'):
        called(project, on=on)
        r = doctor_all(project)
        assert 'PASS S19' in r.stdout, on + r.stdout


def test_s19_the_trigger_of_a_call_is_judged_on_the_caller_alone(project):
    """006/FR-001, 006/FR-005, SC-003."""
    called(project)
    for on in ('on: push\n', 'on:\n  pull_request: {branches: [develop]}\n'):
        caller(project, on=on)
        gap = gap19(doctor_all(project))
        assert 'ci.yml (not on pull requests to main)' in gap and CALL + ')' in gap, on + gap
    caller(project)
    called(project, on='on: {workflow_call: {}, pull_request: {branches: [develop]}}\n')
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout, r.stdout


def test_s19_a_call_from_a_job_that_gives_up_its_result_is_not_followed(project):
    """006/FR-003, SC-004."""
    called(project)
    caller(project, job='    if: false\n')
    assert CALL + ', and the job is under `if: false`)' in gap19(doctor_all(project))
    caller(project, job='    continue-on-error: true\n')
    assert CALL + ', and the job is under `continue-on-error`)' in gap19(doctor_all(project))
    caller(project, job='    with: {scope: full}\n    secrets: inherit\n')
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout, r.stdout


@pytest.mark.parametrize('steps,job,said', [
    (THROWN, '', ' not judged: line 1 holds shell this rule does not read (`||`)'),
    (f'      - run: {ENTRY} | tee out.txt\n', '', ' not judged: line 1 holds shell this rule does not read (`|`)'),
    (RUNS + '        continue-on-error: true\n', '', " has 'python -m pytest -q' under `continue-on-error`"),
    (RUNS, '    continue-on-error: true\n', " has 'python -m pytest -q' under `continue-on-error`"),
    (RUNS + '        if: false\n', '', " has 'python -m pytest -q' under `if: false`"),
], ids=['or-true', 'pipe', 'step-continue-on-error', 'job-continue-on-error', 'step-if-false'])
def test_s19_what_is_not_counted_in_a_called_workflow_names_the_call(project, steps, job, said):
    """006/FR-001, 006/FR-009, SC-005."""
    caller(project)
    called(project, steps, job=job)
    gap = gap19(doctor_all(project))
    assert 'run-tests.yml, called by ci.yml job tests, job unit step 1' + said in gap, gap


def test_s19_where_a_step_of_a_called_workflow_runs_is_read_from_the_called_file(project):
    """006/FR-004, SC-006."""
    one = manifest(project)
    monorepo(project)
    caller(project)
    called(project, '      - run: npm test\n        working-directory: api\n')
    r = doctor_all(project)
    assert by_project(r, 'S19') == {'api': 'PASS', 'web': 'GAP'}, r.stdout
    called(project, '      - run: npm test\n')
    caller(project, on='defaults: {run: {working-directory: api}}\non: pull_request\n')
    r = doctor_all(project)
    assert by_project(r, 'S19')['api'] == 'GAP', r.stdout
    save(project, one)
    called(project)
    caller(project, on='defaults: {run: {shell: pwsh}}\non: pull_request\n')
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout, r.stdout


def test_s19_a_called_file_that_is_missing_or_cannot_be_read_is_not_followed(project):
    """006/FR-002, 006/FR-003, SC-007."""
    caller(project)
    for job in ('', '    if: false\n'):
        caller(project, job=job)
        r = doctor_all(project)
        assert CALL + ', which is missing)' in gap19(r) and r.returncode == 1, job + r.stdout + r.stderr
    caller(project)
    workflow(project, 'on: [workflow_call\njobs: {\n', 'run-tests.yml')
    gap = gap19(doctor_all(project))
    assert CALL + ', which cannot be read as a workflow)' in gap and gap.count('run-tests.yml not judged (') == 1, gap


def test_s19_one_level_of_calls_is_followed_never_two(project):
    """006/FR-005, 006/FR-008, 006/FR-010, SC-008."""
    caller(project)
    calling(project, 'run-tests.yml', 'again', USES)
    r = doctor_all(project)
    gap = gap19(r)
    assert r.returncode == 1, r.stderr
    assert f'run-tests.yml job again not judged (it calls {USES})' in gap, gap
    assert 'run-tests.yml (called by ci.yml job tests)' in gap and CALL not in gap, gap

    calling(project, 'run-tests.yml', 'deeper', './.github/workflows/third.yml')
    called(project, name='third.yml')
    r = doctor_all(project)
    gap = gap19(r)
    assert r.returncode == 1, r.stderr
    assert 'run-tests.yml job deeper not judged (it calls ./.github/workflows/third.yml)' in gap, gap
    assert 'run-tests.yml (called by ci.yml job tests)' in gap and 'third.yml (not on pull requests to main)' in gap, gap
    assert CALL not in gap and 'called by run-tests.yml' not in gap, gap

    calling(project, 'third.yml', 'back', USES)
    r = doctor_all(project)
    assert r.returncode == 1 and gap19(r), r.stderr

    called(project, name='third.yml')
    workflow(project, 'on: [pull_request, workflow_call]\njobs:\n  deeper:\n    uses: ./.github/workflows/third.yml\n',
             'run-tests.yml')
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout, r.stdout         # the call to third.yml is at the first level


def test_s19_a_uses_that_is_not_a_call_is_named_as_before(project):
    """006/FR-005, SC-009."""
    called(project)
    there = 'octo-org/ci/.github/workflows/run-tests.yml@v1'
    caller(project, uses=there)
    assert f'ci.yml job tests not judged (it calls {there})' in gap19(doctor_all(project))
    for uses, at in (('./.github/workflows/sub/run-tests.yml', '.github/workflows/sub'),
                     ('./.github/workflows/../../run-tests.yml', '.')):
        caller(project, uses=uses)
        (project / at).mkdir(parents=True, exist_ok=True)
        (project / at / 'run-tests.yml').write_text(
            f'on: workflow_call\njobs:\n  unit:\n    runs-on: ubuntu-latest\n    steps:\n{RUNS}', encoding='utf-8')
        r = doctor_all(project)
        assert 'GAP  S19' in r.stdout and f'ci.yml job tests not judged (it calls {uses})' in gap19(r), r.stdout


def test_s19_a_local_action_in_a_called_workflow_is_named_and_not_opened(project):
    """006/FR-006, SC-010."""
    actions = '      - uses: actions/checkout@v4\n      - uses: ./.github/actions/setup\n'
    caller(project)
    called(project, actions + RUNS)
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout, r.stdout
    called(project, actions + MAKE)
    composite = project / '.github' / 'actions' / 'setup' / 'action.yml'
    for run_step_taken_out in (False, True):
        if run_step_taken_out:
            called(project, actions)
            composite.parent.mkdir(parents=True)
            composite.write_text(f'runs:\n  using: composite\n  steps:\n    - run: {ENTRY}\n      shell: bash\n',
                                 encoding='utf-8')
        gap = gap19(doctor_all(project))
        assert 'run-tests.yml job unit not judged (it calls ./.github/actions/setup)' in gap, gap
        assert 'run-tests.yml (called by ci.yml job tests)' in gap and 'actions/checkout' not in gap, gap


def test_s19_a_file_called_twice_is_read_for_each_call_that_is_followed(project):
    """006/FR-005, 006/FR-007, 006/FR-008, 006/FR-009, 006/FR-010, SC-011."""
    ship = f'deploy.yml job ship not judged (it calls {USES})'
    caller(project)
    called(project)
    caller(project, on='on: push\n', name='deploy.yml', key='ship')
    r = doctor_all(project)
    assert 'PASS S19' in r.stdout, r.stdout

    called(project, MAKE)
    gap = gap19(doctor_all(project))
    assert 'run-tests.yml (called by ci.yml job tests)' in gap and ship in gap, gap
    assert 'called by deploy.yml' not in gap, gap

    caller(project, name='deploy.yml', key='ship')
    called(project, THROWN)
    gap = gap19(doctor_all(project))
    assert 'run-tests.yml (called by ci.yml job tests, deploy.yml job ship)' in gap, gap
    assert 'called by ci.yml job tests, job unit step 1' in gap, gap
    assert 'called by deploy.yml job ship, job unit step 1' in gap, gap

    caller(project, on='on: push\n', name='deploy.yml', key='ship')
    (project / '.github' / 'workflows' / 'run-tests.yml').unlink()
    gap = gap19(doctor_all(project))
    assert CALL + ', which is missing)' in gap and ship in gap, gap

    (project / '.github' / 'workflows' / 'deploy.yml').unlink()
    called(project, THROWN, on='on: [pull_request, workflow_call]\n')
    gap = gap19(doctor_all(project))
    assert 'run-tests.yml (on pull requests to main)' in gap and 'run-tests.yml job unit step 1 not judged' in gap, gap
    assert 'called by' not in gap and CALL not in gap, gap


def test_s19_a_debt_that_a_called_workflow_now_pays_is_asked_back(project):
    """006/FR-001, 004/FR-011, SC-012."""
    caller(project)
    called(project)
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY]}])
    r = doctor_all(project)
    assert 'GAP  S19 listed under deviations but conforms now: remove the entry' in r.stdout and r.returncode == 1, r.stdout
    set_key(project, 'test', [ENTRY, 'npm test'])
    deviate(project, [{'rule': 'S19', 'reason': 'r', 'fix': 'f', 'names': [ENTRY, 'npm test']}])
    r = doctor_all(project)
    assert "listed under the deviation but conforming now, remove: 'python -m pytest -q'" in r.stdout, r.stdout


@pytest.mark.private
def test_s19_the_standard_and_the_readme_say_which_uses_is_followed():
    """006/FR-011, SC-013."""
    kit = SCRIPTS.parents[2]
    found = [l for l in (kit / 'STANDARD.md').read_text(encoding='utf-8').splitlines() if 'workflow_call' in l]
    assert found and all(l.startswith('| S19 |') and 'not judged' in l for l in found), found
    readme = (kit.parent.parent / 'README.md').read_text(encoding='utf-8')
    assert 'It does not follow' not in readme and 'workflow_call' in readme
