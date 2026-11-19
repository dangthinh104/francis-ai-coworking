"""kit_detect.py and copy_audit.py."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
DETECT = KIT / 'kit-init' / 'scripts' / 'kit_detect.py'
AUDIT = KIT / 'ui-copy' / 'scripts' / 'copy_audit.py'


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, encoding='utf-8')


def git(repo, *args):
    subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True, encoding='utf-8')


def detect(repo, *extra):
    r = run(DETECT, '--repo', repo, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


def workflow(repo, name, text):
    d = repo / '.github' / 'workflows'
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding='utf-8')


def commit(repo, subject):
    git(repo, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'commit', '-q', '--allow-empty', '-m', subject)


def test_detect_reads_a_laravel_vue_project(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'artisan').write_text('', encoding='utf-8')
    (tmp_path / 'composer.json').write_text('{"require-dev": {"laravel/pint": "^1"}}', encoding='utf-8')
    (tmp_path / 'tsconfig.json').write_text('{}', encoding='utf-8')
    (tmp_path / 'package.json').write_text(json.dumps({
        'scripts': {'build': 'vite build', 'test:browser': 'playwright test', 'dev': 'vite'},
        'dependencies': {'vue': '^3'}, 'devDependencies': {'@playwright/test': '^1', 'vue-tsc': '^2'}}), encoding='utf-8')
    (tmp_path / 'resources' / 'js' / 'locales').mkdir(parents=True)
    for name in ('vi.json', 'en.json', 'index.js'):
        (tmp_path / 'resources' / 'js' / 'locales' / name).write_text('{}', encoding='utf-8')
    git(tmp_path, 'add', '-A')
    commit(tmp_path, 'first files')      # 003/FR-007: without a commit the reading carries a warning
    d = detect(tmp_path)
    assert d['profile'] == 'laravel-vue' and d['name'] == tmp_path.name
    assert d['commands'] == {
        'test': ['npm run test:browser', 'php artisan test   # only with proof of an isolated test database'],
        'lint': ['./vendor/bin/pint --test', 'npx vue-tsc --noEmit'], 'build': ['npm run build']}
    assert d['interface'] == {'frameworks': ['vue'], 'locales': {'resources/js/locales': ['en', 'vi']}, 'playwright': True}
    assert d['already_has'] == [] and d['tracker'] is None and d['sub_projects'] == [] and d['warnings'] == []


DEPLOY_SHAPES = [
    ('name: Deploy\non:\n  push:\n    branches: [develop, "main"]\njobs: {}\n', [{'via': 'push', 'branches': ['develop', 'main']}]),
    ('name: Deploy\non:\n  push:\n    branches:\n      - main  # production\n      - "release/**"\n      - \'staging\'  # box\n'
     '    paths: [src]\n    tags: [v1]\njobs: {}\n', [{'via': 'push', 'branches': ['main', 'release/**', 'staging'], 'tags': ['v1']}]),
    ('name: Deploy\non: [push]\njobs: {}\n', [{'via': 'push', 'branches': 'all'}]),
    ('name: Deploy\non: push\njobs: {}\n', [{'via': 'push', 'branches': 'all'}]),
    ('name: Deploy\non:\n  push:\njobs: {}\n', [{'via': 'push', 'branches': 'all'}]),
    ('name: Deploy\non:\n  push:\n    branches: main\njobs: {}\n', [{'via': 'push', 'branches': ['main']}]),
    ('name: Deploy\non:\n  push:\n    branches-ignore: ["wip/**"]\njobs: {}\n', [{'via': 'push', 'branches': 'all', 'ignore': ['wip/**']}]),
    ('name: Deploy\non:\n  push:\n    tags: ["v*"]\njobs: {}\n', [{'via': 'push', 'branches': [], 'tags': ['v*']}]),
    ('name: Deploy\non:\n  workflow_run:\n    workflows: [CI]\n    branches: [main, staging]\njobs: {}\n',
     [{'via': 'workflow_run', 'branches': ['main', 'staging']}]),
    ('name: Deploy\non:\n  push: {branches: [edge]}\njobs: {}\n', [{'via': 'push', 'branches': ['edge']}]),
    ('name: Deploy\non:\n  push:\n    branches: [main,\n               "prod"]\njobs: {}\n', [{'via': 'push', 'branches': ['main', 'prod']}]),
    ('name: Deploy\non:\n  workflow_dispatch:\njobs: {}\n', 'not a push: check by hand'),
]


@pytest.mark.parametrize('text,expected', DEPLOY_SHAPES)
def test_detect_reads_what_starts_a_deploy(tmp_path, text, expected):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'deploy.yml', text)
    assert detect(tmp_path)['push_workflows'] == [{'workflow': 'deploy.yml', 'starts_on': expected, 'deploy_hints': ['deploy']}]


PUSH = 'on:\n  push:\n    branches: [main]\n'
HIDDEN_DEPLOYS = {
    'reuse.yml': ('name: CI\n' + PUSH + 'jobs:\n  go:\n    uses: acme/infra/.github/workflows/deploy.yml@v1\n', ['deploy']),
    'env.yml': ('name: CI\n' + PUSH + 'jobs:\n  go:\n    environment: production\n    steps:\n      - run: make up\n', ['environment']),
    'jobname.yml': ('name: CI\n' + PUSH + 'jobs:\n  go:\n    name: Deploy to production\n    steps:\n      - run: make up\n', ['deploy']),
    'late.yml': ('name: CI\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: |\n          ' + 'echo x; ' * 60 + './deploy.sh\n', ['deploy']),
    'with.yml': ('name: CI\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - uses: appleboy/ssh-action@v1\n        with:\n          script: cd /srv && git pull\n', ['cd', 'ssh']),
    'cd.yml': ('name: CD\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: docker compose up -d\n', ['cd', 'docker compose up']),
    'action.yml': ('name: CI\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - uses: some/deploy-action@v1\n', ['deploy']),
}


def test_detect_lists_every_push_workflow_so_no_deploy_is_silent(tmp_path):
    git(tmp_path, 'init', '-q')
    for name, (text, _) in HIDDEN_DEPLOYS.items():
        workflow(tmp_path, name, text)
    workflow(tmp_path, 'tests.yml', 'name: Tests\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: pytest\n')
    workflow(tmp_path, 'nightly.yml', 'name: Nightly\non:\n  schedule:\n    - cron: "0 0 * * *"\njobs:\n  t:\n    steps:\n      - run: pytest\n')
    found = {w['workflow']: w for w in detect(tmp_path)['push_workflows']}
    for name, (_, hints) in HIDDEN_DEPLOYS.items():
        assert found[name]['deploy_hints'] == hints, name
        assert found[name]['starts_on'] == [{'via': 'push', 'branches': ['main']}]
    assert found['tests.yml']['deploy_hints'] == [] and 'nightly.yml' not in found


@pytest.mark.parametrize('text', ['name: [deploy\n', '', 'jobs:\n  a:\n    steps: 5\non: push\n',
                                  'on: push\nwhen: 2026-13-45\n', 'a: ' + '[' * 3000 + ']' * 3000 + '\n', '- just\n- a list\n'])
def test_detect_turns_an_unreadable_workflow_into_a_warning(tmp_path, text):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'odd.yml', text)
    d = detect(tmp_path)
    listed = [w['workflow'] for w in d['push_workflows']]
    assert listed == ['odd.yml'] or (listed == [] and d['warnings'] and d['warnings'][0].startswith('odd.yml: could not be read')), d


def test_detect_tracker_ignores_merges_and_code_words(tmp_path):
    git(tmp_path, 'init', '-q')
    for i in range(5):
        commit(tmp_path, f'fix FR-00{i} for UTF-8, see #1{i}')
    assert detect(tmp_path)['tracker'] == {'type': 'github', 'id_pattern': r'#\d+'}
    for i in range(2):
        commit(tmp_path, f'SCRUM-{i + 10} thing')
    assert detect(tmp_path)['tracker']['type'] == 'github'
    commit(tmp_path, 'SCRUM-12 third')
    assert detect(tmp_path)['tracker'] == {'type': 'jira', 'id_pattern': r'SCRUM-\d+'}


def test_detect_merge_subjects_are_not_tickets(tmp_path):
    git(tmp_path, 'init', '-q')
    commit(tmp_path, 'base')
    for i in range(4):
        git(tmp_path, 'checkout', '-q', '-b', f'b{i}')
        commit(tmp_path, 'work')
        git(tmp_path, 'checkout', '-q', '-')
        git(tmp_path, '-c', 'user.email=t@example.com', '-c', 'user.name=t', 'merge', '-q', '--no-ff', f'b{i}',
            '-m', f'Merge pull request #{i + 1} from x/y')
    assert detect(tmp_path)['tracker'] is None


def test_detect_existing_process_python_and_sub_projects(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text('[tool.ruff]\n[tool.pytest.ini_options]\n', encoding='utf-8')
    (tmp_path / 'uv.lock').write_text('', encoding='utf-8')
    d = detect(tmp_path)
    assert d['profile'] == 'python' and d['commands'] == {'test': ['uv run pytest -q'], 'lint': ['uv run ruff check .'], 'build': []}
    assert d['already_has'] == []
    (tmp_path / 'CLAUDE.md').write_text('', encoding='utf-8')
    assert detect(tmp_path)['already_has'] == []
    (tmp_path / 'CLAUDE.md').write_text('x\n' * 41, encoding='utf-8')
    (tmp_path / 'specs').mkdir()
    (tmp_path / '.claude' / 'skills').mkdir(parents=True)
    assert detect(tmp_path)['already_has'] == ['specs', '.claude/skills', 'CLAUDE.md (41 lines)']
    web = tmp_path / 'web'
    web.mkdir()
    (web / 'package.json').write_text('{"dependencies": {"react": "1"}}', encoding='utf-8')
    api = tmp_path / 'api'
    (api / 'specs').mkdir(parents=True)
    (api / 'requirements.txt').write_text('', encoding='utf-8')
    (tmp_path / 'notes').mkdir()
    assert detect(tmp_path)['sub_projects'] == [
        {'dir': 'api', 'profile': 'python', 'interface': False, 'has_process': True},
        {'dir': 'web', 'profile': 'generic', 'interface': True, 'has_process': False}]
    assert detect(tmp_path, '--project-root', 'api')['already_has'] == ['specs', '.claude/skills']


def test_detect_survives_odd_input(tmp_path):
    repo, plain = tmp_path / 'repo', tmp_path / 'plain'
    repo.mkdir()
    plain.mkdir()
    git(repo, 'init', '-q')
    (repo / 'package.json').write_text('{"dependencies": ["vue"], "scripts": "x"}', encoding='utf-8')
    d = detect(repo)
    assert d['interface']['frameworks'] == [] and d['commands']['test'] == []
    (repo / 'package.json').write_text('{not json', encoding='utf-8')
    assert detect(repo)['profile'] == 'generic'
    assert run(DETECT, '--repo', repo, '--project-root', 'nope').returncode == 2
    assert run(DETECT, '--repo', repo, '--project-root', '../plain').returncode == 2
    r = run(DETECT, '--repo', plain)
    assert r.returncode == 0 and 'not a repository' in json.loads(r.stdout)['warnings'][0]


def audit(tmp_path, data, name='vi.json'):
    (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    r = run(AUDIT, tmp_path / name)
    return {line.split()[1].rstrip(':'): line.split()[0] for line in r.stdout.splitlines() if line.startswith('  ')}, r


STOCK = ['Thao tác thành công', 'Lưu thất bại', 'Đã xảy ra lỗi. Vui lòng thử lại sau.', 'Lỗi khi tải dữ liệu',
         'Trạng thái hóa đơn không hợp lệ', 'Bạn có chắc chắn muốn xóa?', 'Không đủ quyền thực hiện thao tác này',
         'Something went wrong', 'Failed to save', 'Invalid email', 'Are you sure you want to delete?',
         'Saved successfully', 'Enregistré avec succès', 'Không thể tải metadata', 'Not found',
         'Property not found.', 'Error loading page', 'No data']
GOOD = ['Đã lưu', 'Đã gửi phiếu cho {name}', 'Số điện thoại phải có 10 chữ số', 'Mất mạng nên chưa lưu được.',
        '300.000 – 500.000 ₫', 'Phòng 403', 'Phiếu đặt phòng đã gửi', 'ID card number must be 9-12 digits',
        'Chưa có hóa đơn nào trong tháng 11', 'Saved', 'Could not record the arrival',
        'Tài khoản {email} có {count} lần đăng nhập thất bại trong 5 phút từ IP {ip}.',
        'Số điện thoại không hợp lệ: phải bắt đầu bằng 0 và có từ 9 đến 11 chữ số.',
        'Không tải được danh sách phòng lúc này, anh chị thử lại sau ít phút giúp em.',
        'Không tìm thấy hồ sơ khách thuê.', 'Cannot sign in on the web or the app', 'Số CMND/CCCD của anh chị',
        'Bản ghi cũ sẽ đóng, bản mới mở từ ngày hiệu lực']


def test_copy_audit_stock_phrases_and_good_text(tmp_path):
    found, r = audit(tmp_path, {f's{i}': v for i, v in enumerate(STOCK)} | {f'g{i}': v for i, v in enumerate(GOOD)})
    assert sorted(found) == sorted(f's{i}' for i in range(len(STOCK))), r.stdout
    assert all('stock' in v for v in found.values())
    assert f'{len(STOCK)} of {len(STOCK) + len(GOOD)} string(s) flagged in 1 file(s); "vui lòng"/"please" in 1' in r.stdout


def test_copy_audit_internal_shout_and_long(tmp_path):
    found, r = audit(tmp_path, {
        'code': 'Máy chủ báo lỗi 500 khi lưu', 'http': 'HTTP 404', 'snake': 'Cột user_id trống', 'nul': 'Giá trị null',
        'bang': 'Đã sao chép!', 'caps': 'KHÔNG ĐƯỢC XÓA', 'one_caps': 'Mã OTP đã gửi', 'two_short': 'Mã OTP SMS đã gửi',
        'toast.long': 'x' * 61, 'toast.ok': 'x' * 60, 'help.long': 'x' * 300, 'page.subtitle': 'y' * 100,
        'user.action.suspend.body': 'z' * 100, 'save.button.vi': 'w' * 61,
        'placeholder': 'Xin chào {user_name}, :count_items mục'})
    assert found == {'code': 'internal', 'http': 'internal', 'snake': 'internal', 'nul': 'internal',
                     'bang': 'shout', 'caps': 'shout', 'toast.long': 'long', 'save.button.vi': 'long'}, r.stdout
    assert r.returncode == 0 and run(AUDIT, '--strict', tmp_path / 'vi.json').returncode == 1


def test_copy_audit_parsers_and_exit_codes(tmp_path):
    (tmp_path / 'a.php').write_text("<?php return [\n  // 'old' => 'Something went wrong',\n  'saved' => 'Lưu thành công',\n"
                                    "  'auth.title' => ['vi' => 'Đăng nhập thất bại', 'en' => 'Sign in'],\n  'ok' => 'Saved'];", encoding='utf-8')
    (tmp_path / 'b.js').write_text("export default { saved: 'Saved successfully', ok: `Saved`, path: '/api/invalid' }\n", encoding='utf-8')
    (tmp_path / 'c.yml').write_text("saved: 'An error occurred'  # todo\nok: Saved\n", encoding='utf-8')
    (tmp_path / 'bom.json').write_text('\ufeff{"x": "Lưu thất bại"}', encoding='utf-8')
    (tmp_path / 'bad.json').write_text('{oops', encoding='utf-8')
    (tmp_path / 'notes.md').write_text('Something went wrong', encoding='utf-8')
    r = run(AUDIT, '--strict', tmp_path)
    out = r.stdout
    assert r.returncode == 1 and '5 of 9 string(s) flagged in 5 file(s)' in out, out
    assert 'bad.json: unparsed, check by hand' in out
    assert 'stock           auth.title.vi: Đăng nhập thất bại' in out and 'old' not in out and '/api/invalid' not in out
    (tmp_path / 'empty').mkdir()
    assert run(AUDIT, tmp_path / 'empty').returncode == 2
    clean = tmp_path / 'clean.json'
    clean.write_text('{"ok": "Saved"}', encoding='utf-8')
    assert run(AUDIT, '--strict', clean).returncode == 0


def test_detect_says_when_no_workflow_runs_on_a_hosted_runner(tmp_path):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'deploy.yml', 'on:\n  push:\n    branches: [prod]\njobs:\n  d:\n    runs-on: [self-hosted, vm]\n    steps: []\n')
    out = detect(tmp_path)
    assert out['runners']['hosted'] == [] and out['runners']['own']
    assert any('own runner' in w and 'KIT_GATE_RUNNER' in w for w in out['warnings'])     # 009/FR-010
    assert not any('may never start' in w for w in out['warnings'])
    workflow(tmp_path, 'ci.yml', 'on: pull_request\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps: []\n')
    out = detect(tmp_path)
    assert out['runners']['hosted'] == ['ubuntu-latest']
    assert not any('own runner' in w for w in out['warnings'])


@pytest.mark.parametrize('runs_on', ["${{ vars.GATES_RUNNER || 'ubuntu-latest' }}", '${{ matrix.os }}'])
def test_detect_does_not_guess_a_runner_written_as_an_expression(tmp_path, runs_on):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'ci.yml', f'on: push\njobs:\n  t:\n    runs-on: "{runs_on}"\n    steps: []\n')
    out = detect(tmp_path)
    assert out['runners']['unknown'] == [runs_on] and not any('own runner' in w for w in out['warnings'])


def test_detect_self_hosted_with_an_os_label_is_the_projects_own(tmp_path):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'ci.yml', 'on: push\njobs:\n  t:\n    runs-on: [self-hosted, ubuntu-latest]\n    steps: []\n')
    assert detect(tmp_path)['runners']['hosted'] == []


def test_copy_audit_one_word_is_a_label_unless_the_key_says_message(tmp_path):
    found, _ = audit(tmp_path, {'status.chip': 'Lỗi', 'dashboard.errors_24h': 'Lỗi 24 giờ qua', 'status.error': 'Lỗi',
                                'operations.level.error': 'Lỗi', 'toast.error': 'Lỗi', 'form.message': 'Error'})
    assert found == {'dashboard.errors_24h': 'stock', 'toast.error': 'stock', 'form.message': 'stock'}


def test_copy_audit_display_copy_keeps_only_the_internal_rule(tmp_path):
    data = {'media.card.title': 'ROOMS - DANH SÁCH PHÒNG TRỌ', 'media.card.greeting': 'Chúc mừng thành công!',
            'media.card.leak': 'Cột full_name trống', 'home.hero': 'ƯU ĐÃI HÀNG TUẦN',
            'mediaplayer.title': 'KHÔNG ĐƯỢC XÓA'}
    (tmp_path / 'vi.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    r = run(AUDIT, tmp_path / 'vi.json', '--display', 'media', '--display', 'home.')
    flagged = {line.split()[1].rstrip(':'): line.split()[0] for line in r.stdout.splitlines() if line.startswith('  ')}
    assert flagged == {'media.card.leak': 'internal', 'mediaplayer.title': 'shout'}, r.stdout


def test_detect_lists_workflows_that_read_the_spec_tree(tmp_path):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'specops.yml', 'on:\n  pull_request:\n    paths: ["specs/**"]\njobs: {}\n')
    workflow(tmp_path, 'ci.yml', 'on: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ls myspecs/ docs\n')
    out = detect(tmp_path)
    workflow(tmp_path, 'kit-gate.yml', 'on: pull_request\njobs:\n  s:\n    steps:\n      - run: ls specs/\n')
    workflow(tmp_path, 'walk.yml', 'on: push\njobs:\n  s:\n    steps:\n      - run: find ./specs -type d\n')
    out = detect(tmp_path)
    assert out['reads_specs'] == ['specops.yml', 'walk.yml']
    assert any('specops.yml' in w and 'specs/_living/' in w for w in out['warnings'])


def test_copy_audit_vietnamese_capitals_and_decomposed_text(tmp_path):
    import unicodedata
    found, _ = audit(tmp_path, {'a.title': 'CẢNH BÁO XÓA TẤT CẢ DỮ LIỆU', 'b.label': 'Mã ID CCCD',
                                'c.toast': unicodedata.normalize('NFD', 'Lưu thành công')})
    assert found == {'a.title': 'shout', 'c.toast': 'stock'}


@pytest.mark.parametrize('runs_on,bucket', [('ubuntu-24.04', 'hosted'), ('ubuntu-latest-8-cores', 'hosted'),
                                            ('ubuntu-prod-vm', 'own'), ('{group: big, labels: [self-hosted]}', 'own')])
def test_detect_runner_buckets(tmp_path, runs_on, bucket):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'ci.yml', f'on: push\njobs:\n  t:\n    runs-on: {runs_on}\n    steps: []\n')
    out = detect(tmp_path)
    assert out['runners'][bucket] and any('own runner' in w for w in out['warnings']) is (bucket == 'own')


def test_detect_an_expression_does_not_hide_a_self_hosted_job(tmp_path):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'ci.yml', 'on: push\njobs:\n  a:\n    runs-on: self-hosted\n    steps: []\n'
                                 '  b:\n    runs-on: "${{ matrix.os }}"\n    steps: []\n')
    assert any('own runner' in w for w in detect(tmp_path)['warnings'])


def test_detect_a_shell_cd_is_not_a_deploy_hint_and_a_cd_pipeline_is(tmp_path):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'tests.yml', 'name: Tests\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: cd frontend && npm test\n')
    workflow(tmp_path, 'ci-cd.yml', 'name: Pipeline\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: make up\n')
    workflow(tmp_path, 'pipe.yml', 'name: CI/CD\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: make up\n')
    found = {w['workflow']: w['deploy_hints'] for w in detect(tmp_path)['push_workflows']}
    assert found == {'tests.yml': [], 'ci-cd.yml': ['cd'], 'pipe.yml': ['cd']}


def test_detect_the_pull_request_number_of_a_squash_merge_is_not_a_ticket(tmp_path):
    git(tmp_path, 'init', '-q')
    for i in range(5):
        commit(tmp_path, f'Add thing {i} (#{i + 10})')
    assert detect(tmp_path)['tracker'] is None
    for i in range(3):
        commit(tmp_path, f'Fix #{i + 1}: cart total (#{i + 20})')
    assert detect(tmp_path)['tracker'] == {'type': 'github', 'id_pattern': r'#\d+'}


def test_detect_asks_the_remote_without_a_password_prompt(tmp_path, monkeypatch):
    sys.path.insert(0, str(DETECT.parent))
    import kit_detect
    git(tmp_path, 'init', '-q')
    asked = []
    real = subprocess.run

    def spy(cmd, *args, **kwargs):
        if 'ls-remote' in cmd:
            asked.append(kwargs.get('env') or {})
        return real(cmd, *args, **kwargs)
    monkeypatch.setattr(kit_detect.subprocess, 'run', spy)
    kit_detect.main(['--repo', str(tmp_path)])
    assert asked and asked[0].get('GIT_TERMINAL_PROMPT') == '0' and asked[0].get('GCM_INTERACTIVE') == 'never'
    assert asked[0].get('PATH') == os.environ.get('PATH')


CD_SHAPES = {
    'job-id.yml': 'name: Pipeline\n' + PUSH + 'jobs:\n  ci:\n    steps:\n      - run: make test\n  cd:\n    steps:\n      - run: make up\n',
    'job-id-prod.yml': 'name: Pipeline\n' + PUSH + 'jobs:\n  cd-prod:\n    steps:\n      - run: make up\n',
    'reuse.yml': 'name: Pipeline\n' + PUSH + 'jobs:\n  go:\n    uses: ./.github/workflows/cd.yml\n',
    'lower.yml': 'name: cd\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n',
    'title.yml': 'name: Cd\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n',
    'job-name.yml': 'name: Pipeline\n' + PUSH + 'jobs:\n  go:\n    name: cd (production)\n    steps:\n      - run: make up\n',
    'spoken.yml': 'name: ci and cd\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n',
    'cicd.yml': 'name: Pipeline\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n',
}
SHELL_CD = ['cd app', 'set -e; cd app && npm ci', 'npm ci\ncd packages/web\nnpm test', '(cd docs && make html)',
            'if [ -d web ]; then cd web; fi', 'cd "$GITHUB_WORKSPACE"', 'cd']


def test_detect_keeps_every_way_a_workflow_calls_itself_cd(tmp_path):
    git(tmp_path, 'init', '-q')
    for name, text in CD_SHAPES.items():
        workflow(tmp_path, name, text)
    found = {w['workflow']: w['deploy_hints'] for w in detect(tmp_path)['push_workflows']}
    assert found == {name: ['cd'] for name in CD_SHAPES}


@pytest.mark.parametrize('command', SHELL_CD)
def test_detect_a_cd_typed_at_a_shell_is_no_hint_wherever_it_stands(tmp_path, command):
    git(tmp_path, 'init', '-q')
    step = '      - run: |\n' + ''.join(f'          {line}\n' for line in command.split('\n'))
    workflow(tmp_path, 'tests.yml', 'name: Tests\n' + PUSH + 'jobs:\n  t:\n    steps:\n' + step)
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == []


@pytest.mark.parametrize('subject', ['Revert "Add a (#{n})"', 'Revert "Add a (#{n})" (#9{n})', 'Add a (#{n}) (#4{n})', 'Add a (#{n}).'])
def test_detect_a_number_in_brackets_is_a_pull_request_wherever_it_stands(tmp_path, subject):
    git(tmp_path, 'init', '-q')
    for n in range(5):
        commit(tmp_path, subject.replace('{n}', str(n + 1)))
    assert detect(tmp_path)['tracker'] is None


@pytest.mark.parametrize('name,text', [
    ('ci_cd.yml', 'name: Pipeline\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n'),
    ('cd_prod.yml', 'name: Pipeline\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n'),
    ('a.yml', 'name: CI_CD\n' + PUSH + 'jobs:\n  go:\n    steps:\n      - run: make up\n'),
    ('b.yml', 'name: Pipeline\n' + PUSH + 'jobs:\n  cd_prod:\n    steps:\n      - run: make up\n'),
])
def test_detect_cd_joined_by_an_underscore_is_still_cd(tmp_path, name, text):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, name, text)
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == ['cd']


@pytest.mark.parametrize('command', [
    'sleep 1 & cd app', 'if cd web; then npm test; fi', 'if ! cd web; then exit 1; fi', '{ cd web; npm test; }',
    "bash -c 'cd web && npm test'", 'sh -c "cd web && npm test"', 'x=`cd web && pwd`', 'FOO=1 cd web',
    'cd..', 'while cd next; do make; done'])
def test_detect_a_shell_cd_behind_other_shell_words_is_no_hint(tmp_path, command):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'tests.yml', 'name: Tests\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: |\n          ' + command + '\n')
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == []


@pytest.mark.parametrize('key', ['command', 'args'])
def test_detect_a_cd_handed_to_an_action_stays_a_hint(tmp_path, key):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'tests.yml', 'name: Tests\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - uses: a/b@v1\n        with:\n'
             '          ' + key + ': cd web && npm test\n')
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == ['cd']


@pytest.mark.parametrize('command', ['make cd', './scripts/cd.sh', 'npm run cd'])
def test_detect_a_cd_that_is_an_argument_stays_a_hint(tmp_path, command):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'tests.yml', 'name: Tests\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: ' + command + '\n')
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == ['cd']


@pytest.mark.parametrize('step', [
    'run: make TARGET=prod cd', 'run: ./x.sh --mode=cd', 'run: STAGE=cd ./go.sh', "run: echo 'cd pipeline'",
    'run: gh workflow run "cd prod"', 'run: echo first time cd runs',
    'uses: a/b@v1\n        with:\n          args: [make, cd]', 'uses: a/b@v1\n        with:\n          command: cd'])
def test_detect_a_cd_that_is_a_value_or_a_quoted_name_stays_a_hint(tmp_path, step):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'build.yml', 'name: Build\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - ' + step + '\n')
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == ['cd']


def test_detect_a_directory_named_cd_in_a_command_is_no_hint(tmp_path):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'build.yml', 'name: Build\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - run: cp build/cd/image.iso out/\n')
    assert detect(tmp_path)['push_workflows'][0]['deploy_hints'] == []


def hints_of(tmp_path, step):
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'build.yml', 'name: Build\n' + PUSH + 'jobs:\n  t:\n    steps:\n      - ' + step + '\n')
    return detect(tmp_path)['push_workflows'][0]['deploy_hints']


def test_detect_reads_a_long_run_of_assignments_in_no_time(tmp_path):
    import time
    began = time.time()
    assert hints_of(tmp_path, 'run: ' + 'A=b  ' * 60 + 'make') == []
    assert time.time() - began < 5


@pytest.mark.parametrize('step', [
    'run: |\n          make \\\n            cd', 'run: |\n          gh workflow run \\\n            cd --ref main',
    'uses: a/b@v1\n        with:\n          script: cd', 'uses: a/b@v1\n        with:\n          run: cd',
    'run: make\n        env:\n          script: cd',
    'uses: a/b@v1\n        with:\n          args: cd prod', 'uses: a/b@v1\n        with:\n          command: cd production',
    'run: echo "CI & cd pipeline"', 'run: echo "ci|cd pipeline"', 'run: echo "pipeline (cd stage)"',
    'run: echo "Done! cd pipeline starts"', "run: tool -c 'cd prod'",
    'run: |\n          case "$1" in\n            ci|cd ) ./go.sh;;\n          esac',
    'run: |\n          make\n          cd/run.sh', 'run: |\n          make\n          cd.sh prod',
    'run: |\n          make\n          cd-pipeline.sh'])
def test_detect_a_name_cd_the_scanner_must_not_take_for_a_shell_cd(tmp_path, step):
    assert hints_of(tmp_path, step) == ['cd']


@pytest.mark.parametrize('step', [
    'run: docker run img bash -c "cd /app && pytest"', 'run: |\n          make\n          cd app\n          make',
    'run: echo $(cd app && pwd)', 'run: cd app', 'run: |\n          cd app\n          make'])
def test_detect_a_shell_cd_the_scanner_takes_out(tmp_path, step):
    assert hints_of(tmp_path, step) == []


@pytest.mark.parametrize('step', [
    'run: |\n          case "$1" in\n            cd|ci) ./go.sh;;\n          esac',
    'uses: a/b@v1\n        with:\n          args: --stages ci;cd;qa', 'uses: a/b@v1\n        with:\n          args: cd; qa',
    'uses: a/b@v1\n        with:\n          args: |\n            cd\n            prod',
    'uses: a/b@v1\n        with:\n          command: >\n            cd production',
    'uses: a/b@v1\n        with:\n          args: cd app && make test'])
def test_detect_what_is_not_a_step_running_cd_keeps_the_hint(tmp_path, step):
    assert hints_of(tmp_path, step) == ['cd']


def test_detect_reads_a_very_long_script_in_no_time(tmp_path):
    import time
    began = time.time()
    assert hints_of(tmp_path, 'run: |\n' + '          cd x\n' * 40000) == []
    assert time.time() - began < 10


# Spec 003: an empty reading is said to be empty.

def nothing_detected(repo, *extra):
    return [w for w in detect(repo, *extra)['warnings'] if 'nothing was detected' in w]


def test_detect_says_that_a_repository_without_a_commit_was_not_read(tmp_path):
    """003/FR-007, SC-005."""
    git(tmp_path, 'init', '-q')
    said = nothing_detected(tmp_path)          # `detect` asserts exit 0
    assert len(said) == 1 and 'no commit' in said[0], said
    (tmp_path / 'main.py').write_text('', encoding='utf-8')
    git(tmp_path, 'add', '-A')                 # staged is not committed
    assert 'no commit' in nothing_detected(tmp_path)[0]


def test_detect_says_when_git_tracks_no_file_under_the_project_root(tmp_path):
    git(tmp_path, 'init', '-q')
    commit(tmp_path, 'empty')
    (tmp_path / 'api').mkdir()
    (tmp_path / 'api' / 'scratch.py').write_text('', encoding='utf-8')      # on disk, not tracked
    for extra in ((), ('--project-root', 'api')):
        said = nothing_detected(tmp_path, *extra)
        assert len(said) == 1 and 'tracks no file' in said[0] and 'no commit' not in said[0], said
    (tmp_path / 'README.md').write_text('x\n', encoding='utf-8')
    git(tmp_path, 'add', '-A')
    commit(tmp_path, 'files')
    assert nothing_detected(tmp_path) == [] and nothing_detected(tmp_path, '--project-root', 'api') == []
    (tmp_path / 'web').mkdir()
    assert 'tracks no file' in nothing_detected(tmp_path, '--project-root', 'web')[0]


def test_detect_outside_a_repository_keeps_the_warning_it_had(tmp_path):
    warnings = detect(tmp_path)['warnings']
    assert 'not a repository' in warnings[0] and not [w for w in warnings if 'nothing was detected' in w]



def test_detect_does_not_say_nothing_was_found_beside_what_it_found(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    d = detect(tmp_path)
    said = [w for w in d['warnings'] if 'no commit' in w]
    assert d['profile'] == 'python' and len(said) == 1
    assert 'from git' in said[0] and 'not read' in said[0] and 'an empty value' not in said[0], said
    commit(tmp_path, 'empty')
    said = [w for w in detect(tmp_path)['warnings'] if 'tracks no file' in w]
    assert len(said) == 1 and 'not tracked' in said[0] and 'an empty value' not in said[0], said


def test_the_own_runner_warning_leaves_the_kits_gate_out(tmp_path):
    """009/FR-010: every workflow "other than the kit's gate": an older gate on a hosted runner does not hide it."""
    git(tmp_path, 'init', '-q')
    workflow(tmp_path, 'deploy.yml', 'on:\n  push:\n    branches: [prod]\njobs:\n  d:\n    runs-on: [self-hosted, vm]\n    steps: []\n')
    workflow(tmp_path, 'kit-gate.yml', 'on: pull_request\njobs:\n  standard:\n    runs-on: ubuntu-latest\n    steps: []\n')
    out = detect(tmp_path)
    assert out['runners']['hosted'] == ['ubuntu-latest']           # runners still counts the gate (011, Out of scope)
    assert any('own runner' in w and 'KIT_GATE_RUNNER' in w for w in out['warnings']), out['warnings']

