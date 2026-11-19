"""spec_lint.py, and the one reader every script shares."""
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
LINT = KIT / 'write-spec' / 'scripts' / 'spec_lint.py'
INDEX = KIT / 'kit-init' / 'scripts' / 'spec_index.py'
sys.path.insert(0, str(KIT / 'kit-init' / 'scripts'))
import kit_spec  # noqa: E402


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True, encoding='utf-8')


def spec(root, name, status='Draft', reqs=3, extra='', capability='billing'):
    d = root / 'specs' / name
    d.mkdir(parents=True)
    lines = [f'# Feature Specification: {name}', '', f'**Status**: {status}', '**Ticket**: none']
    if capability:
        lines.append(f'**Capability**: {capability}')
    lines += ['', '## Requirements', ''] + [f'- **FR-{i:03d}**: The system MUST do thing {i}.' for i in range(1, reqs + 1)]
    (d / 'spec.md').write_text('\n'.join(lines) + '\n' + extra, encoding='utf-8')
    return d


def test_a_well_formed_spec_is_clean(tmp_path):
    spec(tmp_path, '001-late-fee')
    r = run(LINT, '--root', tmp_path, '--strict')
    assert r.returncode == 0, r.stdout
    assert '1 spec(s), 0 with errors, 0 with warnings' in r.stdout


def test_too_many_requirements_warns_and_fails_only_when_strict(tmp_path):
    spec(tmp_path, '001-big', reqs=13)
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 0 and '13 requirements, more than 12' in r.stdout
    assert run(LINT, '--root', tmp_path, '--strict').returncode == 1
    spec(tmp_path, '002-edge', reqs=12)
    assert 'WARN  002-edge' not in run(LINT, '--root', tmp_path).stdout


def test_an_earlier_feature_is_not_asked_to_change(tmp_path):
    spec(tmp_path, '001-old', status='Closed', reqs=30, capability='')
    r = run(LINT, '--root', tmp_path, '--strict')
    assert r.returncode == 0 and 'WARN' not in r.stdout


@pytest.mark.parametrize('capability,warns', [('', True), ('billing, reports', True), ('billing and reports', True),
                                              ('late-fee billing', False)])
def test_one_capability(tmp_path, capability, warns):
    spec(tmp_path, '001-a', capability=capability)
    assert ('capabilit' in run(LINT, '--root', tmp_path).stdout) is warns


def test_requirement_without_a_checkable_verb_warns(tmp_path):
    spec(tmp_path, '001-a', extra='- **FR-009**: Fast and friendly reports.\n')
    assert 'no MUST, SHOULD or MAY in: FR-009' in run(LINT, '--root', tmp_path).stdout


def test_duplicate_id_and_open_question_are_errors(tmp_path):
    spec(tmp_path, '001-a', status='Approved',
         extra='- **FR-002**: The system MUST also do this.\n\n[NEEDS CLARIFICATION: who pays?]\n')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 1 and 'declared twice: FR-002' in r.stdout and 'NEEDS CLARIFICATION' in r.stdout
    spec(tmp_path, '002-b', status='Draft', extra='[NEEDS CLARIFICATION: scope]\n')
    assert 'ERROR 002-b' not in run(LINT, '--root', tmp_path, '002').stdout


def test_removed_requirements_and_code_blocks_declare_nothing(tmp_path):
    spec(tmp_path, '001-a', extra='\n## Removed\n\n- **FR-001**: The system MUST no longer do thing 1.\n\n'
                                  '```\n- **FR-002**: an example MUST not count\n```\n')
    assert run(LINT, '--root', tmp_path, '--strict').returncode == 0


def test_fix_lines_are_ticked_and_cite_a_real_requirement(tmp_path):
    d = spec(tmp_path, '005-fees', status='Released')
    (d / 'tasks.md').write_text('- [x] T001 build\n\n## Fixes\n\n'
                                '- [x] SCRUM-412 Late fee charged twice (005/FR-003)\n', encoding='utf-8')
    assert run(LINT, '--root', tmp_path).returncode == 0
    (d / 'tasks.md').write_text('- [x] T001 build\n\n## Fixes\n\n- [ ] Charged twice (005/FR-003)\n'
                                '- [x] Wrong total\n- [x] Rounding (005/FR-099)\n- [x] Other (007/FR-001)\n',
                                encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 1
    for text in ('fix not ticked: Charged twice', 'cites no requirement as NNN/FR-001: Wrong total',
                 'cites 005/FR-099, which no feature declares', 'cites 007/FR-001, which no feature declares'):
        assert text in r.stdout, r.stdout


def test_nothing_to_judge_exits_2(tmp_path):
    assert run(LINT, '--root', tmp_path).returncode == 2
    (tmp_path / 'specs').mkdir()
    assert run(LINT, '--root', tmp_path).returncode == 2
    spec(tmp_path, '001-a')
    assert run(LINT, '--root', tmp_path, '009').returncode == 2


STATUS_SHAPES = {
    'plain': ('**Status**: Built\n', 'Built'),
    'two lines': ('**Status**: Draft\n\n**Status**: Closed\n', None),
    'in a comment': ('<!--\n**Status**: Draft\n-->\n', None),
    'in an indented fence': ('- example:\n  ```\n**Status**: Draft\n  ```\n', None),
    'in an unclosed fence, which hides nothing': ('```\n**Status**: Draft\n', 'Draft'),
    'beside a sentence that starts the same way': ('**Status**: Built\n\n**Status**: done in PR 12\n', 'Built'),
    'after a line of inline code': ('```npm test``` is the command.\n\n**Status**: Draft\n\n```\nx\n```\n', 'Draft'),
    'after a quoted comment marker': ('about `<!--` markers\n\n**Status**: Draft\n\nsee --> there\n', 'Draft'),
    'unknown word': ('**Status**: Shipped\n', None),
    'crlf and bom': ('**Status**: Released\r\n', 'Released'),
}


@pytest.mark.parametrize('shape', STATUS_SHAPES)
def test_the_doctor_the_index_and_the_reader_agree_on_status(tmp_path, shape):
    text, expected = STATUS_SHAPES[shape]
    d = tmp_path / 'specs' / '001-a'
    d.mkdir(parents=True)
    (d / 'spec.md').write_bytes(('\ufeff# T\r\n\r\n' + text + '**Ticket**: none\n').encode('utf-8'))
    assert kit_spec.status(kit_spec.read(d / 'spec.md')) == expected
    run(INDEX, '--root', tmp_path)
    row = [line for line in (tmp_path / 'specs' / 'INDEX.md').read_text(encoding='utf-8').splitlines() if '001-a' in line][0]
    cell = row.split('|')[3].strip()
    assert cell == expected if expected else cell not in kit_spec.STATUSES + kit_spec.ENDED
    doctor = run(KIT / 'kit-init' / 'scripts' / 'kit_doctor.py', '--repo', tmp_path, '--project-root', '.')
    assert ('no single valid Status line' in doctor.stdout) is (expected is None), doctor.stdout


def test_ids_repeated_in_a_test_table_are_not_declared_twice(tmp_path):
    spec(tmp_path, '001-a', status='Approved',
         extra='\n## Tests\n\n| FR-001 | test_a |\n| FR-001 | test_b |\n- **FR-002**: `test_c`\n- **FR-002**: `test_d`\n')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 0, r.stdout


def test_a_spec_whose_status_cannot_be_read_is_an_error_not_a_pass(tmp_path):
    d = spec(tmp_path, '001-a', extra='[NEEDS CLARIFICATION: x]\n')
    text = (d / 'spec.md').read_text(encoding='utf-8')
    (d / 'spec.md').write_text(text.replace('**Status**: Draft', '**Status**: approved'), encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 1 and 'no single valid Status line' in r.stdout


def test_open_question_is_an_error_in_every_status_after_draft(tmp_path):
    for i, status in enumerate(['Approved', 'Built', 'Released'], 1):
        spec(tmp_path, f'00{i}-a', status=status, extra='[NEEDS CLARIFICATION: x]\n')
    assert run(LINT, '--root', tmp_path).stdout.count('NEEDS CLARIFICATION') == 3


def test_nothing_readable_exits_2(tmp_path):
    (tmp_path / 'specs' / '001-a').mkdir(parents=True)
    (tmp_path / 'specs' / '002-b' / 'spec.md').mkdir(parents=True)
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 2 and 'nothing was judged' in r.stderr


def test_wrapped_lowercase_and_success_criteria(tmp_path):
    spec(tmp_path, '001-a', reqs=12,
         extra='- **FR-020**: The export\n  must finish in a minute.\n- **FR-021**: Hệ thống phải gửi mail.\n'
               + ''.join(f'- **SC-{i:03d}**: under {i} seconds\n' for i in range(1, 6)), capability='CI/CD pipeline')
    r = run(LINT, '--root', tmp_path)
    assert 'no MUST' not in r.stdout and 'capabilit' not in r.stdout
    assert '14 requirements' in r.stdout


def test_fix_citation_in_backticks_and_a_sub_step(tmp_path):
    d = spec(tmp_path, '005-fees', status='Released')
    (d / 'tasks.md').write_text('- [x] T001\n\n## Fixes\n\n- [x] Rounding (`005/FR-003`)\n'
                                '  - [x] sub-step with no citation\n', encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 0, r.stdout


def test_draft_with_open_questions_says_so_and_a_marker_is_not_a_capability_or_a_verb(tmp_path):
    spec(tmp_path, '002-pass', capability='passes [NEEDS CLARIFICATION: or access, which one]',
         extra='- **FR-020**: The system is fast and [NEEDS CLARIFICATION: MUST it?] refuse.\n')
    r = run(LINT, '--root', tmp_path, '2')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'NOTE  002-pass: 2 open question(s): cannot be approved yet' in r.stdout
    assert 'capabilit' not in r.stdout and 'no MUST, SHOULD or MAY in: FR-020' in r.stdout


def test_a_draft_whose_requirements_are_mostly_questions_warns(tmp_path):
    d = tmp_path / 'specs' / '001-a'
    d.mkdir(parents=True)
    (d / 'spec.md').write_text('# T\n\n**Status**: Draft\n**Ticket**: none\n**Capability**: passes\n\n## Requirements\n\n'
                               '- **FR-001**: The system MUST charge [NEEDS CLARIFICATION: how much?].\n'
                               '- **FR-002**: The system MUST end a period [NEEDS CLARIFICATION: when?].\n'
                               '- **FR-003**: The system MUST refuse an unknown plate.\n', encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert '2 of the requirements still hold an open question' in r.stdout
    assert run(INDEX, '--root', tmp_path).returncode == 0
    assert '| passes | 3 |' in (tmp_path / 'specs' / 'INDEX.md').read_text(encoding='utf-8')


def test_the_layout_spec_kit_writes_is_not_a_double_declaration(tmp_path):
    d = tmp_path / 'specs' / '001-a'
    d.mkdir(parents=True)
    (d / 'spec.md').write_text('# T\n\n**Status**: Approved\n**Ticket**: none\n**Capability**: billing\n\n'
                               '## Requirements *(mandatory)*\n\n### Functional Requirements\n\n'
                               '- **FR-001**: The system MUST charge.\n- **FR-002**: The system MUST refund.\n\n'
                               '## Tests per requirement\n\n- **FR-001**: `test_charge`\n- **FR-001**: `test_charge_twice`\n',
                               encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 0, r.stdout
    text = (d / 'spec.md').read_text(encoding='utf-8')
    (d / 'spec.md').write_text(text.replace('- **FR-002**: The system MUST refund.',
                                            '- **FR-001**: The system MUST refund.'), encoding='utf-8')
    assert 'declared twice: FR-001' in run(LINT, '--root', tmp_path).stdout


def test_a_fix_line_without_a_checkbox_is_a_fix_nobody_ticked(tmp_path):
    d = spec(tmp_path, '005-fees', status='Released')
    (d / 'tasks.md').write_text('- [x] T001\n\n## Fixes\n\n- Rounding was wrong\n', encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert r.returncode == 1 and 'fix not ticked: Rounding was wrong' in r.stdout
    assert 'cites no requirement' in r.stdout


def test_an_error_found_without_any_spec_is_exit_1_not_2(tmp_path):
    spec(tmp_path, '001-a')
    d = tmp_path / 'specs' / '002-b'
    d.mkdir()
    (d / 'tasks.md').write_text('## Fixes\n\n- [ ] not ticked (001/FR-001)\n', encoding='utf-8')
    r = run(LINT, '--root', tmp_path, '002')
    assert r.returncode == 1 and 'fix not ticked' in r.stdout, r.stdout + r.stderr


def test_requirements_written_as_headings_may_carry_notes_that_repeat_an_id(tmp_path):
    d = tmp_path / 'specs' / '043-log'
    d.mkdir(parents=True)
    (d / 'spec.md').write_text('# T\n\n**Status**: Draft\n**Ticket**: none\n**Capability**: logs\n\n## Requirements\n\n'
                               '### FR-001 — The system MUST log.\n\n### FR-011 — Tests pin all FRs\n\n'
                               '- **FR-001**: `test_a`\n- **FR-001**: `test_b`\n', encoding='utf-8')
    assert 'declared twice' not in run(LINT, '--root', tmp_path).stdout
    text = (d / 'spec.md').read_text(encoding='utf-8')
    (d / 'spec.md').write_text(text.replace('### FR-011', '### FR-001'), encoding='utf-8')
    assert 'declared twice: FR-001' in run(LINT, '--root', tmp_path).stdout


def test_a_long_file_of_fence_openers_costs_what_it_weighs():
    import time
    start = time.time()
    hostile = '~~~ a\n' * 30000
    kit_spec.prose(hostile), kit_spec.status(hostile), kit_spec.requirements(hostile)
    assert time.time() - start < 5


@pytest.mark.parametrize('text,kept', [
    ('a\n````\n```\nx\n```\n````\nb\n', 'a\n\nb\n'),
    ('- l\n  ```py\n  hid\n  ```\nc\n', '- l\n\nc\n'),
    ('```npm``` is the command\n', '```npm``` is the command\n'),
    ('~~~\nx\n~~~\nopen:\n```\nstill here\n', '\nopen:\n```\nstill here\n'),
    ('---\n\nNote: a rule, not front matter\n\n---\n**Status**: Draft\n', None),
])
def test_what_counts_as_a_code_block_and_as_front_matter(text, kept):
    if kept is None:
        assert 'Note: a rule' in kit_spec.body(text)
    else:
        assert kit_spec.FENCE.sub('', text) == kept


@pytest.mark.parametrize('capability,several', [('billing-and-invoices', False), ('thu-và-chi', False),
                                               ('billing and invoices', True), ('thu và chi', True),
                                               ('billing, invoices', True)])
def test_and_inside_a_slug_is_one_capability(tmp_path, capability, several):
    spec(tmp_path, '001-x', capability=capability)
    r = run(LINT, '--root', tmp_path)
    assert ('more than one capability' in r.stdout) is several, r.stdout


# Spec 003: a requirement that holds two behaviours.

TWO = 'two behaviours under one id'


def test_a_draft_requirement_with_two_behaviours_warns_by_id(tmp_path):
    """003/FR-008, SC-006, as 019/FR-001 changed it: an Approved spec is warned too."""
    extra = '- **FR-004**: The system MUST send a receipt and also MUST close the account.\n'
    spec(tmp_path, '001-receipt', extra=extra)
    r = run(LINT, '--root', tmp_path)
    warned = [l for l in r.stdout.splitlines() if l.startswith('WARN') and TWO in l]
    assert r.returncode == 0 and len(warned) == 1 and 'FR-004' in warned[0] and 'FR-001' not in warned[0], r.stdout
    assert run(LINT, '--root', tmp_path, '--strict').returncode == 1
    path = tmp_path / 'specs' / '001-receipt' / 'spec.md'
    draft = path.read_text(encoding='utf-8')
    approved = draft.replace('**Status**: Draft', '**Status**: Approved')
    path.write_text(approved, encoding='utf-8')
    r = run(LINT, '--root', tmp_path)
    assert [l for l in r.stdout.splitlines() if l.startswith('WARN') and TWO in l and 'FR-004' in l], r.stdout
    for later in ('Built', 'Released', 'Closed'):
        path.write_text(draft.replace('**Status**: Draft', f'**Status**: {later}'), encoding='utf-8')
        r = run(LINT, '--root', tmp_path, '--strict')
        assert r.returncode == 0 and TWO not in r.stdout, (later, r.stdout)


@pytest.mark.parametrize('text,two', [
    ('The system MUST send a receipt and also close the account.', True),
    ('The system MUST send a receipt and MUST close the account.', True),
    ('The system MUST send a receipt as well as a copy.', True),
    ('The system SHOULD log the call and MAY retry it.', True),
    ('Hệ thống PHẢI gửi biên nhận và cũng đóng tài khoản.', True),
    ('The system MUST send a receipt And Also close the account.', True),
    ('The system MUST send a receipt\n  and also close the account.', True),
    ('The system MUST NOT send a receipt twice.', False),
    ('The system MUST send a receipt; it may retry, and that must not fail.', False),
    ('The lint MUST warn about the phrases `and also` and `as well as`, and about a second `MUST`.', False),
    ('The system MUST keep a MUSTARD list, a MAYBE flag and the standalone.', False),
])
def test_what_counts_as_a_second_behaviour(tmp_path, text, two):
    spec(tmp_path, '001-x', reqs=2, extra=f'- **FR-003**: {text}\n')
    r = run(LINT, '--root', tmp_path)
    assert (TWO in r.stdout) is two, r.stdout
    if two:
        assert 'FR-003' in [l for l in r.stdout.splitlines() if TWO in l][0]


@pytest.mark.private
def test_the_specs_of_this_repository_stay_clean():
    r = run(LINT, '--root', KIT.parent.parent.parent)
    assert r.returncode == 0 and '0 with errors, 0 with warnings' in r.stdout, r.stdout
