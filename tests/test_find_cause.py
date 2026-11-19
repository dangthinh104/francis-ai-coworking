"""The find-cause skill holds each rule of feature 005, and flow sends a session there."""
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
SKILL = SKILLS / 'find-cause' / 'SKILL.md'
FLOW = SKILLS / 'flow' / 'SKILL.md'

NUMBERED = re.compile(r'^(\d+)\. ')


def section(text, heading):
    """The lines under one `## heading`, up to the next one."""
    lines, inside = [], False
    for line in text.split('\n'):
        if line.startswith('## '):
            inside = line.strip() == f'## {heading}'
        elif inside:
            lines.append(line)
    return lines


def numbered(text, heading):
    return [line.lower() for line in section(text, heading) if NUMBERED.match(line)]


def rule_says(*words):
    """A check: one numbered line of `## Rules` carries every one of the words."""
    return lambda text: any(all(w in line for w in words) for line in numbered(text, 'Rules'))


def description(text):
    head = text.split('---\n')[1] if text.startswith('---\n') else ''
    found = re.search(r'^description: (.+)$', head, re.M)
    return (found.group(1) if re.search(r'^name: find-cause$', head, re.M) and found else '').lower()


def applies_before_a_fix(text):
    return all(w in description(text) for w in
               ('a bug', 'a failing test', 'a finding of a code review', 'behaviour nobody expected',
                'before a fix is proposed'))


QUESTIONS = (('command', 'output'), ('cause', 'evidence'), ('fails without', 'both runs'),
             ('deleted', 'skipped', 'assert less'))


def ends_with_review_questions(text):
    """The last section is four numbered questions, in the order FR-002, FR-004, FR-007, FR-010."""
    last = [line for line in text.split('\n') if line.startswith('## ')][-1:]
    asked = numbered(text, 'Review questions')
    body = text.rstrip('\n').split('\n')
    return (last == ['## Review questions'] and len(asked) == len(QUESTIONS)
            and body[-1].lower() == asked[-1]
            and all(q.endswith('?') and all(w in q for w in words) for q, words in zip(asked, QUESTIONS)))


def flow_names_the_skill(flow):
    """Three places: the Fix lane, stage 4 and stage 5."""
    lines = [line.lower() for line in flow.split('\n') if '`find-cause`' in line]
    return (any(line.startswith('- **fix**') for line in lines)
            and any('stage 4' in line for line in lines)
            and any('stage 5' in line for line in lines))


CHECKS = {
    '005/FR-001': applies_before_a_fix,
    '005/FR-002': rule_says('show the failure', 'before', 'a test that shows it', 'command', 'output',
                            'only on a runner', 'log', 'restoring', 'may come first', 'not put back'),
    '005/FR-003': rule_says('not reproduced', 'no change made', 'what was tried', 'how many runs',
                            'nothing as fixed'),
    '005/FR-004': rule_says('cause', 'before', 'one sentence', 'where it is', 'evidence', 'hypothesis'),
    '005/FR-005': rule_says('one stated hypothesis at a time', 'smallest change', 'true or false'),
    '005/FR-006': rule_says('undo', 'did not remove the failure', 'before'),
    '005/FR-007': rule_says('fails without', 'both runs', 'no test to add one to', 'before and after'),
    '005/FR-008': rule_says('stop', '3 failed fixes', 'same failure', 'list each', 'approach is in question',
                            'ask the owner', 'still failing', 'proposed as the fix', 'not counted'),
    '005/FR-009': rule_says('stop', '3 review reports', 'in a row', 'same function', 'same named pattern',
                            'found nothing'),
    '005/FR-010': rule_says('no test', 'deleted', 'skipped', 'assert less', 'itself wrong'),
    '005/FR-012': ends_with_review_questions,
}
RULE_OF = {f'005/FR-{n + 1:03d}': n for n in range(1, 10)}      # rule 1 holds FR-002, rule 9 holds FR-010


def skill():
    return SKILL.read_text(encoding='utf-8')


def without_rule(text, number):
    """A copy of the skill with the line of one rule removed from `## Rules`."""
    target = [line for line in section(text, 'Rules') if line.startswith(f'{number}. ')]
    assert len(target) == 1, f'rule {number} is not one line of ## Rules'
    return text.replace(target[0] + '\n', '', 1)


def test_the_description_says_when_the_skill_applies():
    """005/FR-001"""
    assert CHECKS['005/FR-001'](skill())


def test_the_failure_is_shown_before_anything_changes():
    """005/FR-002"""
    assert CHECKS['005/FR-002'](skill())


def test_a_failure_not_reproduced_is_reported_as_such():
    """005/FR-003"""
    assert CHECKS['005/FR-003'](skill())


def test_the_cause_is_stated_with_its_evidence_before_a_fix():
    """005/FR-004"""
    assert CHECKS['005/FR-004'](skill())


def test_one_hypothesis_is_tested_at_a_time():
    """005/FR-005"""
    assert CHECKS['005/FR-005'](skill())


def test_a_change_that_did_not_help_is_undone():
    """005/FR-006"""
    assert CHECKS['005/FR-006'](skill())


def test_a_fix_comes_with_a_test_that_fails_without_it():
    """005/FR-007"""
    assert CHECKS['005/FR-007'](skill())


def test_three_failed_fixes_stop_the_work():
    """005/FR-008"""
    assert CHECKS['005/FR-008'](skill())


def test_three_review_reports_in_a_row_stop_the_work():
    """005/FR-009"""
    assert CHECKS['005/FR-009'](skill())


def test_no_test_is_weakened_so_that_a_run_passes():
    """005/FR-010"""
    assert CHECKS['005/FR-010'](skill())


def test_flow_names_the_skill_in_the_three_places_a_failure_shows():
    """005/FR-011"""
    flow = FLOW.read_text(encoding='utf-8')
    assert flow.count('find-cause') >= 3
    assert flow_names_the_skill(flow)


def test_the_skill_ends_with_the_questions_of_a_reviewer():
    """005/FR-012"""
    assert CHECKS['005/FR-012'](skill())


@pytest.mark.parametrize('cited', sorted(RULE_OF))
def test_removing_a_rule_fails_its_check_and_no_other(cited):
    """SC-002, for 005/FR-002 to 005/FR-010."""
    text = skill()
    assert len(numbered(text, 'Rules')) == len(RULE_OF)
    mutated = without_rule(text, RULE_OF[cited])
    assert [name for name, check in CHECKS.items() if not check(mutated)] == [cited]
