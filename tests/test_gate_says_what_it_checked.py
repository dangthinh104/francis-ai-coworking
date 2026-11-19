"""Spec 016: a green gate says what it checked."""
import re

import pytest

from test_kit_gate import REPO, commit, gate, in_order, index, make_p, stamp, two_roots, write
from test_standard import DOCTOR, LINT, ci, feature, manifest, run, save, use_tracker, workflow

ENTRY = 'python -m pytest -q'
BLIND = 'no step this rule can read runs on pull requests to main: '
SEEING = 'no step runs on pull requests to main: '
WORD_FOR_WORD = 'An entry is matched word for word'
LAST = 'in a step that holds only plain commands before it, or record a deviation on S19'


@pytest.fixture
def p(tmp_path):
    return make_p(tmp_path / 'p')


def deviation(repo, rule, name):
    data = manifest(repo)
    data['projects'][0]['deviations'] = [{'rule': rule, 'reason': 'r', 'fix': 'f', 'features': [name]}]
    save(repo, data)


def test_sc001_debt_on_s08_no_longer_keeps_a_spec_from_the_lint(p):
    """016/FR-001, SC-001."""
    use_tracker(p)
    write(p / 'specs' / '001-a' / 'spec.md',
          '# Feature Specification: 001-a\n\n**Status**: Draft\n**Capability**: demo\n\n## Requirements\n\n'
          '- **FR-001**: The system MUST send a receipt.\n- **FR-001**: The system MUST close the account.\n')
    deviation(p, 'S08', '001-a')
    index(p)
    commit(p)
    assert 'DEBT S08' in run(DOCTOR, '--repo', p, '--all').stdout
    r = gate(p)
    assert r.code == 1, r.lines
    in_order(r.lines, 'kit-gate: lint: .', 'ERROR 001-a: declared twice: FR-001', 'kit-gate: FAILED: lint: ' + stamp(p))
    assert r.verdict == 'kit-gate: FAILED: lint: ' + stamp(p)
    assert not [l for l in r.lines if 'left out of the spec lint' in l], r.lines
    for rule in ('S07', 'S04', 'S05', 'S06', 'S09'):
        deviation(p, rule, '001-a')
        listed = run(DOCTOR, '--repo', p, '--lint-features', '.')
        assert '001-a' not in listed.stdout and '001-a' in listed.stderr, (rule, listed.stdout, listed.stderr)


def lint_one_per_case(tmp_path, sentences):
    for n, sentence in enumerate(sentences, 1):
        write(tmp_path / 'specs' / f'{n:03d}-case' / 'spec.md',
              f'# Feature Specification: case {n}\n\n**Status**: Draft\n**Ticket**: none\n**Capability**: demo\n\n'
              f'## Requirements\n\n- **FR-001**: {sentence}\n')
    return run(LINT, '--root', tmp_path)


TWO = 'two behaviours under one id'
WARNED = ['Hệ thống PHẢI gửi email và PHẢI đóng tài khoản.',
          'Hệ thống PHẢI gửi email và KHÔNG ĐƯỢC đóng tài khoản.',
          'Hệ thống NÊN gửi email và NÊN ghi nhật ký.']
CLEAN = ['Hệ thống PHẢI từ chối một yêu cầu KHÔNG PHẢI của chủ tài khoản.',
         'Hệ thống PHẢI xử lý đồng thời 100 yêu cầu.',
         'Hệ thống PHẢI gửi email, cũng như mọi thông báo khác.',
         'Hệ thống phải gửi email và phải đóng tài khoản.',
         'Hệ thống PHẢI hiện nút ở bên trái và phải của màn hình.']


def test_sc002_the_vietnamese_obligation_words_count(tmp_path):
    """016/FR-002, 016/FR-003, SC-002."""
    r = lint_one_per_case(tmp_path, WARNED + CLEAN)
    assert r.returncode == 0, r.stdout + r.stderr
    warned = sorted(l.split()[1].rstrip(':') for l in r.stdout.splitlines() if TWO in l)
    assert warned == ['001-case', '002-case', '003-case'], r.stdout
    assert all('FR-001' in l for l in r.stdout.splitlines() if TWO in l), r.stdout


def test_sc002_words_in_backticks_do_not_count(tmp_path):
    """016/FR-002, SC-002: the same first sentence with each `PHẢI` in backticks."""
    r = lint_one_per_case(tmp_path, ['Hệ thống `PHẢI` gửi email và `PHẢI` đóng tài khoản.'])
    assert r.returncode == 0 and TWO not in r.stdout, r.stdout


@pytest.mark.parametrize('sentence,two', [
    ('Hệ thống PHẢI từ chối một yêu cầu **KHÔNG** PHẢI của chủ tài khoản.', False),
    ('Hệ thống PHẢI từ chối một yêu cầu *KHÔNG* PHẢI của chủ tài khoản.', False),
    ('Hệ thống PHẢI từ chối một yêu cầu __KHÔNG__ PHẢI của chủ tài khoản.', False),
    ('Hệ thống PHẢI từ chối một yêu cầu _KHÔNG_ PHẢI của chủ tài khoản.', False),
    ('Hệ thống **PHẢI** gửi email và **PHẢI** đóng tài khoản.', True),
    ('Hệ thống `**PHẢI**` gửi email và `PHẢI` đóng tài khoản.', False),
])
def test_l2_emphasis_around_a_word_does_not_change_what_counts(tmp_path, sentence, two):
    """016/FR-002, 016/FR-003: `**KHÔNG** PHẢI` is still "is not"; words in backticks still do not count."""
    r = lint_one_per_case(tmp_path, [sentence])
    assert r.returncode == 0 and (TWO in r.stdout) is two, r.stdout


def test_sc012_the_warning_names_the_vietnamese_words(tmp_path):
    """016/FR-012, SC-012: the warning itself."""
    r = lint_one_per_case(tmp_path, WARNED[:1])
    line = [l for l in r.stdout.splitlines() if TWO in l][0]
    for word in ('MUST', 'SHOULD', 'MAY', 'PHẢI', 'KHÔNG ĐƯỢC', 'NÊN'):
        assert word in line, line


def test_sc003_a_project_with_no_citation_baseline_says_refs_was_left_out(p):
    """016/FR-004, SC-003."""
    r = gate(p)
    assert r.code == 0, r.lines
    in_order(r.lines, 'kit-gate: lint: .', 'kit-gate: left out: refs: . (no specs/.kit-refs-baseline.json)',
             'kit-gate: index: .', 'kit-gate: passed: ' + stamp(p))
    assert r.starting('kit-gate: left out:') == ['kit-gate: left out: refs: . (no specs/.kit-refs-baseline.json)']


def test_sc004_each_check_left_out_is_named_where_it_would_have_run(p):
    """016/FR-004, SC-004."""
    (p / 'docs' / 'diagrams' / 'map.refs.json').unlink()
    (p / 'specs' / 'INDEX.md').unlink()
    commit(p)
    r = gate(p)
    own = r.starting('kit-gate:')
    assert own == ['kit-gate: doctor', 'kit-gate: roots',
                   'kit-gate: left out: map: . (no docs/diagrams/map.refs.json)',
                   'kit-gate: left out: citations: . (no docs/diagrams/map.refs.json)',
                   'kit-gate: lint: .',
                   'kit-gate: left out: refs: . (no specs/.kit-refs-baseline.json)',
                   'kit-gate: left out: index: . (no specs/INDEX.md)',
                   'kit-gate: FAILED: doctor: ' + stamp(p)], r.lines
    assert not [l for l in r.lines if l.startswith(('kit-gate: map', 'kit-gate: citations', 'kit-gate: index'))]


def test_sc005_with_two_roots_each_line_stands_with_its_root(tmp_path):
    """016/FR-004, SC-005."""
    repo = two_roots(tmp_path / 'two')
    (repo / 'b' / 'docs' / 'diagrams' / 'map.refs.json').unlink()
    (repo / 'b' / 'specs' / 'INDEX.md').unlink()
    commit(repo)
    r = gate(repo)
    of_a_root = [l for l in r.lines if re.match(r'kit-gate: (left out: )?(map|citations|lint|refs|index)\b', l)]
    assert of_a_root == [
        'kit-gate: map: a', 'kit-gate: citations: a',
        'kit-gate: left out: map: b (no docs/diagrams/map.refs.json)',
        'kit-gate: left out: citations: b (no docs/diagrams/map.refs.json)',
        'kit-gate: lint: a', 'kit-gate: lint: b',
        'kit-gate: left out: refs: a (no specs/.kit-refs-baseline.json)', 'kit-gate: index: a',
        'kit-gate: left out: refs: b (no specs/.kit-refs-baseline.json)',
        'kit-gate: left out: index: b (no specs/INDEX.md)'], r.lines


def test_sc006_a_ticked_checkbox_is_a_checkbox(p):
    """016/FR-005, SC-006."""
    feature(p, '001-a', tasks='# Tasks\n\nT001 write it\n')
    out = run(DOCTOR, '--repo', p, '--all').stdout
    assert 'GAP  S09 tasks.md without checkboxes (`- [ ]` / `- [x]`) in 1: 001-a' in out, out
    assert 'without `- [ ]` checkboxes' not in out


def s19_line(repo):
    out = run(DOCTOR, '--repo', repo, '--all').stdout
    found = [l for l in out.splitlines() if 'GAP  S19' in l]
    assert len(found) == 1, out
    return found[0]


IF_THEN = f'      - run: |\n          if true; then echo hi; fi\n          {ENTRY}\n'


@pytest.mark.parametrize('case', ['not plain', 'pwsh', 'missing call'])
def test_sc007_a_gap_that_could_read_no_step_says_so(p, case):
    """016/FR-006, 016/FR-007, SC-007."""
    if case == 'not plain':
        ci(p, '      - uses: actions/checkout@v4\n' + IF_THEN)
    elif case == 'pwsh':
        ci(p, f'      - run: {ENTRY}\n        shell: pwsh\n')
    else:
        workflow(p, 'on: pull_request\njobs:\n  test:\n    uses: ./.github/workflows/missing.yml\n')
    line = s19_line(p)
    assert BLIND + repr(ENTRY) in line and SEEING not in line, line
    assert WORD_FOR_WORD not in line and 'write the entry as CI runs it' not in line, line
    assert LAST in line, line
    assert {'not plain': 'ci.yml job test step 2 not judged',
            'pwsh': "not judged: its `shell` is 'pwsh'",
            'missing call': 'ci.yml job test not judged (it calls ./.github/workflows/missing.yml, which is missing)',
            }[case] in line, line


@pytest.mark.parametrize('steps', ['      - run: make test\n' + IF_THEN, '      - run: make test\n'])
def test_sc008_a_gap_that_could_read_a_step_keeps_its_opening(p, steps):
    """016/FR-006, 016/FR-007, SC-008."""
    ci(p, steps)
    line = s19_line(p)
    message = line.split('GAP  S19 ', 1)[1]
    assert message.startswith(SEEING + repr(ENTRY)) and WORD_FOR_WORD in line, line
    if IF_THEN in steps:
        assert 'ci.yml job test step 2 not judged' in line, line


def test_sc013_a_step_read_in_part_that_holds_the_entry_is_a_step_read(p):
    """016/FR-006, 016/FR-007, SC-013."""
    ci(p, f'      - run: |\n          cd sub\n          {ENTRY}\n          if true; then :; fi\n')
    (p / 'sub').mkdir()
    line = s19_line(p)
    message = line.split('GAP  S19 ', 1)[1]
    assert message.startswith(SEEING + repr(ENTRY)), line
    for words in (f'has {ENTRY!r} in sub', 'not judged: line 3', WORD_FOR_WORD):
        assert words in line, (words, line)

    # The step runs one entry in full and holds the other only after the line it could not read:
    # it holds the missing entry in none of the lines read, so the gap could read no step.
    data = manifest(p)
    data['projects'][0]['test'] = [ENTRY, 'ruff check .']
    save(p, data)
    ci(p, f'      - run: |\n          {ENTRY}\n          if true; then :; fi\n          ruff check .\n')
    line = s19_line(p)
    message = line.split('GAP  S19 ', 1)[1]
    assert message.startswith(BLIND + repr('ruff check .')) and WORD_FOR_WORD not in line, line


PUSH_ONLY = {
    'local action': '      - uses: ./my-action\n      - run: python -m pytest -q\n',
    'call': None,
}


@pytest.mark.parametrize('case', sorted(PUSH_ONLY))
def test_m1_what_a_workflow_that_does_not_count_leaves_unjudged_is_not_a_step_s19_matches(p, case):
    """016/FR-006, FR-007 (Decisions: decided from the steps S19 matches): a workflow that does not
    start on pull requests to the target adds nothing to "could read no step"."""
    (p / '.github' / 'workflows' / 'ci.yml').unlink()
    if PUSH_ONLY[case]:
        workflow(p, 'on: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n' + PUSH_ONLY[case], 'push.yml')
    else:
        workflow(p, 'on: push\njobs:\n  test:\n    uses: ./.github/workflows/missing.yml\n', 'push.yml')
    line = s19_line(p)
    message = line.split('GAP  S19 ', 1)[1]
    assert message.startswith(SEEING + repr(ENTRY)) and WORD_FOR_WORD in line, line


def readme_section(text, heading):
    start = text.index(heading)
    end = text.find('\n## ', start + len(heading))
    return text[start:end if end != -1 else len(text)]


@pytest.mark.private
def test_sc011_the_documents_say_s08_debt_no_longer_leaves_a_spec_out():
    """016/FR-011, SC-011."""
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    assert 'S04 to S09' not in readme
    assert 'S04 to S07 and S09' in readme_section(readme, '## The gate in each project')
    assert 'S04 to S07 and S09' in readme_section(readme, '## Known limits')
    assert len([l for l in readme.splitlines() if 'S04 to S07 and S09' in l]) == 2
    changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.14.0')]   # the line moves under its release
    line = [l for l in unreleased.splitlines() if 'S04 to S07 and S09' in l]
    assert len(line) == 1 and 'S08' in line[0] and 'goes red' in line[0], line


@pytest.mark.private
def test_sc012_the_documents_name_the_vietnamese_words():
    """016/FR-012, SC-012."""
    readme = (REPO / 'README.md').read_text(encoding='utf-8')
    held = [l for l in readme.splitlines() if 'KHÔNG ĐƯỢC' in l]
    assert len(held) == 2, held
    assert held[0].startswith('| `write-spec/scripts/spec_lint.py')
    assert held[1] in readme_section(readme, '## Known limits') and 'two-behaviour warning' in held[1]
    for line in held:
        for word in ('PHẢI', 'NÊN', 'MUST', 'SHOULD', 'MAY'):
            assert word in line, (word, line)
    skill = (REPO / 'plugins' / 'francis-kit' / 'skills' / 'write-spec' / 'SKILL.md').read_text(encoding='utf-8')
    check = readme_section(skill, '## Check')
    assert [l for l in check.splitlines() if 'KHÔNG ĐƯỢC' in l and 'PHẢI' in l and 'NÊN' in l], check
