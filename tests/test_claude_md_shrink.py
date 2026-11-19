"""claude_md_shrink.py: a long CLAUDE.md is cut down by an approved proposal, and nothing is lost (specs/002)."""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
SHRINK = KIT / 'shrink-claude-md' / 'scripts' / 'claude_md_shrink.py'
SKILL = KIT / 'shrink-claude-md' / 'SKILL.md'
AUDIT = KIT / 'kit-init' / 'scripts' / 'claude_md_audit.py'
DOCTOR = KIT / 'kit-init' / 'scripts' / 'kit_doctor.py'

# 18 lines. Hazards: 3 to 6. A dated note: 14 to 16.
TEXT = '''# App

## Hazards

- Pushing to main deploys to production.
- The ledger table cannot be recomputed.

## Billing

Round every amount half up.
Never store a float.

## Notes

On 2026-03-02 the importer was rewritten.
It took two days.

Read `docs/guide.md` first.
'''
BLOCKS = [
    {'lines': [1, 1], 'verdict': 'stays'},
    {'lines': [3, 6], 'verdict': 'stays'},
    {'lines': [8, 11], 'verdict': 'moves', 'to': '.claude/skills/billing/SKILL.md',
     'pointer': 'Billing rules: `.claude/skills/billing/SKILL.md`.'},
    {'lines': [13, 13], 'verdict': 'stays'},
    {'lines': [14, 16], 'verdict': 'delete', 'why': 'what was done on a date; no rule'},
    {'lines': [18, 18], 'verdict': 'stays'},
]
AFTER = '''# App

## Hazards

- Pushing to main deploys to production.
- The ledger table cannot be recomputed.

Billing rules: `.claude/skills/billing/SKILL.md`.

## Notes

Read `docs/guide.md` first.
'''
MOVED = '## Billing\n\nRound every amount half up.\nNever store a float.\n'


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *args],
                   check=True, capture_output=True)


def run(*args):
    return subprocess.run([sys.executable, str(SHRINK), *map(str, args)], capture_output=True, text=True, encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'CLAUDE.md').write_bytes((TEXT).encode('utf-8'))
    (tmp_path / 'docs').mkdir()
    (tmp_path / 'docs' / 'guide.md').write_bytes(('# Guide\n').encode('utf-8'))
    git(tmp_path, 'add', '-A')
    git(tmp_path, 'commit', '-qm', 'init')
    return tmp_path


def propose(repo, blocks=None, **changes):
    """Write a proposal as the session would, and return its path."""
    data = {'file': 'CLAUDE.md', 'sha256': sha(repo / 'CLAUDE.md'), 'hazards': [], 'hazards_confirmed': '',
            'approved': '', 'blocks': json.loads(json.dumps(BLOCKS if blocks is None else blocks))}
    data.update(changes)
    path = repo / 'proposal.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    if 'approved' not in changes:       # the owner approves what `show` printed, by its fingerprint
        shown = re.search(r'^fingerprint: ([0-9a-f]{12})$', run('show', path).stdout, re.M)
        data['approved'] = 'yes, apply it (owner, 2026-11-12)' + (f', fingerprint {shown.group(1)}' if shown else '')
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


def with_block(index, **changes):
    blocks = json.loads(json.dumps(BLOCKS))
    blocks[index].update(changes)
    return blocks


def snapshot(repo):
    """Every file outside .git with its bytes: what must not change before approval."""
    return {p.relative_to(repo).as_posix(): p.read_bytes()
            for p in sorted(repo.rglob('*')) if p.is_file() and '.git' not in p.relative_to(repo).parts}


# start: the first proposal (FR-001, FR-004)

def test_start_writes_a_proposal_with_every_line_in_one_block_and_no_verdict(repo):
    r = run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json')
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads((repo / 'p.json').read_text(encoding='utf-8'))
    assert data['file'] == 'CLAUDE.md' and data['sha256'] == sha(repo / 'CLAUDE.md')
    assert data['approved'] == '' and data['hazards_confirmed'] == ''
    assert [b['lines'] for b in data['blocks']] == [[1, 1], [3, 3], [5, 6], [8, 8], [10, 11], [13, 13], [15, 16], [18, 18]]
    assert all(b['verdict'] is None for b in data['blocks'])
    assert data['hazards'] == [[3, 6]]
    assert '8 blocks' in r.stdout and '18 lines' in r.stdout
    assert (repo / 'CLAUDE.md').read_text(encoding='utf-8') == TEXT


def test_start_does_not_cut_a_code_block_and_a_heading_opens_a_block(repo):
    (repo / 'CLAUDE.md').write_bytes(('Intro.\n# Run\n```bash\nmake a\n\n# not a heading\nmake b\n```\nAfter.\n').encode('utf-8'))
    assert run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json').returncode == 0
    data = json.loads((repo / 'p.json').read_text(encoding='utf-8'))
    assert [b['lines'] for b in data['blocks']] == [[1, 1], [2, 9]]


def test_start_lists_the_hazards_section_as_what_the_owner_marked(repo):
    r = run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json')
    assert 'Hazards section' in r.stdout and 'candidate' not in r.stdout
    assert '5: - Pushing to main deploys to production.' in r.stdout


def test_without_a_hazards_section_start_lists_candidates_for_the_owner(repo):
    (repo / 'CLAUDE.md').write_bytes(('# App\n\nA refund is never retried.\nUse tabs.\n'
                                    'Không xóa dữ liệu thật.\nDeploys to production on merge.\n').encode('utf-8'))
    r = run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json')
    assert r.returncode == 0, r.stderr
    assert 'no Hazards section' in r.stdout and 'candidates for the owner to confirm' in r.stdout
    listed = [line.strip() for line in r.stdout.splitlines() if line.startswith('  ')]
    assert listed == ['3: A refund is never retried.', '5: Không xóa dữ liệu thật.', '6: Deploys to production on merge.']
    assert json.loads((repo / 'p.json').read_text(encoding='utf-8'))['hazards'] == []


def test_start_refuses_to_overwrite_a_proposal(repo):
    (repo / 'p.json').write_text('mine', encoding='utf-8')
    r = run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json')
    assert r.returncode == 2 and 'already exists' in r.stderr
    assert (repo / 'p.json').read_text(encoding='utf-8') == 'mine'


def test_start_without_out_writes_beside_the_file_and_exit_2_for_no_file(repo):
    assert run('start', repo / 'CLAUDE.md').returncode == 0
    assert (repo / 'claude-md-shrink.json').is_file()
    assert run('start', repo / 'nothing.md', '--out', repo / 'q.json').returncode == 2
    assert not (repo / 'q.json').exists()


# show: what the owner reads (FR-001 to FR-004, FR-008, FR-009)

def test_show_prints_each_block_and_the_size_before_and_after(repo):
    proposal = propose(repo)
    before = snapshot(repo)
    r = run('show', proposal)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = [line.split() for line in r.stdout.splitlines() if line[:4].strip().isdigit()]
    assert [(row[1], row[2]) for row in rows] == [('1-1', 'stays'), ('3-6', 'stays'), ('8-11', 'moves'),
                                                  ('13-13', 'stays'), ('14-16', 'delete'), ('18-18', 'stays')]
    assert '.claude/skills/billing/SKILL.md' in r.stdout and '## Billing' in r.stdout
    assert f'before: 18 lines, about {len(TEXT) // 4} tokens' in r.stdout
    assert f'after:  12 lines, about {len(AFTER) // 4} tokens' in r.stdout
    assert 'characters / 4' in r.stdout
    assert snapshot(repo) == before


def test_show_says_a_missing_target_will_be_created_and_an_existing_one_is_appended_to(repo):
    r = run('show', propose(repo))
    assert '.claude/skills/billing/SKILL.md (will be created)' in r.stdout
    r = run('show', propose(repo, with_block(2, to='docs/guide.md')))
    assert r.returncode == 0 and 'will be created' not in r.stdout


@pytest.mark.parametrize('blocks, said', [
    (BLOCKS[:5], 'line 18 is in no block'),
    (BLOCKS + [{'lines': [10, 11], 'verdict': 'stays'}], 'line 10 is in block 3 (lines 8-11) and in block 7 (lines 10-11)'),
    (with_block(0, verdict='keep'), 'block 1 (lines 1-1): the verdict is "keep"'),
    (with_block(0, verdict=None), 'block 1 (lines 1-1): no verdict'),
    (with_block(5, lines=[18, 19]), 'block 6 (lines 18-19): the file has 18 lines'),
    (with_block(5, lines=[18]), 'block 6: `lines` is not'),
    (with_block(2, to=''), 'block 3 (lines 8-11): "moves" names no target'),
    (with_block(2, to='../outside.md'), 'block 3 (lines 8-11): the target ../outside.md is outside the repository'),
    (with_block(2, to='CLAUDE.md'), 'block 3 (lines 8-11): the target is the file itself'),
    (with_block(2, to='docs'), 'block 3 (lines 8-11): the target docs is a directory'),
    (with_block(2, pointer='two\nlines'), 'block 3 (lines 8-11): the pointer is more than one line'),
    (with_block(3, verdict='delete', why='old'), 'block 4 (lines 13-13): "delete" on a block that holds no date'),
    (with_block(4, why=''), 'block 5 (lines 14-16): "delete" without `why`'),
    (with_block(1, verdict='moves', to='docs/hazards.md'), 'block 2 (lines 3-6): hazard line 3 is not in a block that stays'),
])
def test_show_refuses_what_the_spec_forbids_and_names_the_block(repo, blocks, said):
    r = run('show', propose(repo, blocks))
    assert r.returncode == 1, r.stdout + r.stderr
    assert said in r.stdout


@pytest.mark.parametrize('dated', ['Decided 3/11/2025: use tabs.', 'In March 2025 we moved hosts.',
                                   'Shipped on 12 Nov 2025.', 'Tháng 11 năm 2025 đã chuyển máy chủ.'])
def test_a_block_with_a_date_in_any_usual_form_may_be_history(repo, dated):
    (repo / 'CLAUDE.md').write_bytes(('# Hazards\n\n- none\n\n# Log\n\n' + dated + '\n').encode('utf-8'))
    blocks = [{'lines': [1, 3], 'verdict': 'stays'}, {'lines': [5, 5], 'verdict': 'stays'},
              {'lines': [7, 7], 'verdict': 'delete', 'why': 'history'}]
    r = run('show', propose(repo, blocks))
    assert r.returncode == 0, r.stdout


def test_a_hazard_the_owner_confirmed_must_stay(repo):
    (repo / 'CLAUDE.md').write_bytes(('# App\n\nRefunds are final.\n\nUse tabs.\n').encode('utf-8'))
    blocks = [{'lines': [1, 1], 'verdict': 'stays'}, {'lines': [3, 3], 'verdict': 'moves', 'to': 'docs/money.md'},
              {'lines': [5, 5], 'verdict': 'stays'}]
    r = run('show', propose(repo, blocks, hazards=[[3, 3]], hazards_confirmed='line 3 only (owner, 2026-11-12)'))
    assert r.returncode == 1 and 'block 2 (lines 3-3): hazard line 3 is not in a block that stays' in r.stdout
    blocks[1] = {'lines': [3, 3], 'verdict': 'stays'}
    blocks[2] = {'lines': [5, 5], 'verdict': 'moves', 'to': 'docs/style.md'}
    r = run('show', propose(repo, blocks, hazards=[[3, 3]], hazards_confirmed='line 3 only (owner, 2026-11-12)'))
    assert r.returncode == 0, r.stdout


def test_without_a_hazards_section_the_owner_must_have_confirmed_the_list(repo):
    (repo / 'CLAUDE.md').write_bytes(('# App\n\nUse tabs.\n').encode('utf-8'))
    blocks = [{'lines': [1, 3], 'verdict': 'stays'}]
    r = run('show', propose(repo, blocks))
    assert r.returncode == 1 and 'no Hazards section' in r.stdout and '`hazards_confirmed` is empty' in r.stdout
    r = run('show', propose(repo, blocks, hazards_confirmed='none in this file (owner, 2026-11-12)'))
    assert r.returncode == 0, r.stdout


def test_show_refuses_a_file_changed_since_the_proposal(repo):
    proposal = propose(repo)
    with (repo / 'CLAUDE.md').open('a', encoding='utf-8', newline='\n') as fh:
        fh.write('One more rule.\n')
    r = run('show', proposal)
    assert r.returncode == 1 and 'CLAUDE.md has changed since the proposal was written' in r.stdout


def test_show_exits_2_when_the_proposal_or_the_file_cannot_be_read(repo):
    assert run('show', repo / 'none.json').returncode == 2
    (repo / 'bad.json').write_text('{not json', encoding='utf-8')
    r = run('show', repo / 'bad.json')
    assert r.returncode == 2 and 'bad.json' in r.stderr
    (repo / 'list.json').write_text('[]', encoding='utf-8')
    assert run('show', repo / 'list.json').returncode == 2
    r = run('show', propose(repo, file='GONE.md'))
    assert r.returncode == 2 and 'GONE.md' in r.stderr


# apply (FR-005 to FR-009)

def test_apply_moves_word_for_word_and_writes_the_short_file(repo):
    r = run('apply', propose(repo))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / 'CLAUDE.md').read_bytes() == AFTER.encode('utf-8')
    assert (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').read_bytes() == MOVED.encode('utf-8')
    assert 'before: 18 lines' in r.stdout and 'after:  12 lines' in r.stdout
    assert 'CLAUDE.md' in r.stdout and '.claude/skills/billing/SKILL.md (created)' in r.stdout
    assert '1 moved block(s) found word for word' in r.stdout and '3 hazard line(s) kept' in r.stdout


def test_a_created_target_holds_the_moved_text_and_nothing_invented(repo):
    assert run('apply', propose(repo)).returncode == 0
    text = (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').read_text(encoding='utf-8')
    assert text == MOVED and 'owner' not in text.lower() and not text.startswith('---')


def test_an_existing_target_is_appended_to_and_several_blocks_arrive_in_file_order(repo):
    blocks = with_block(2, to='docs/guide.md')
    blocks[5] = {'lines': [18, 18], 'verdict': 'moves', 'to': 'docs/guide.md'}
    r = run('apply', propose(repo, blocks))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / 'docs' / 'guide.md').read_text(encoding='utf-8') == '# Guide\n\n' + MOVED + '\nRead `docs/guide.md` first.\n'
    assert 'docs/guide.md (appended)' in r.stdout


def test_crlf_and_a_bom_are_kept_and_the_block_is_still_found(repo):
    (repo / 'CLAUDE.md').write_bytes(b'\xef\xbb\xbf' + TEXT.replace('\n', '\r\n').encode('utf-8'))
    r = run('apply', propose(repo))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / 'CLAUDE.md').read_bytes() == b'\xef\xbb\xbf' + AFTER.replace('\n', '\r\n').encode('utf-8')
    assert (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').read_bytes() == MOVED.replace('\n', '\r\n').encode('utf-8')


def test_blank_lines_inside_a_block_that_stays_are_not_touched(repo):
    (repo / 'CLAUDE.md').write_bytes(('# App\n```\na\n\n\nb\n```\n\n\n\nOn 2026-01-01 done.\n\n\nEnd.\n').encode('utf-8'))
    blocks = [{'lines': [1, 7], 'verdict': 'stays'}, {'lines': [11, 11], 'verdict': 'delete', 'why': 'history'},
              {'lines': [14, 14], 'verdict': 'stays'}]
    assert run('apply', propose(repo, blocks, hazards_confirmed='none (owner, 2026-11-12)')).returncode == 0
    assert (repo / 'CLAUDE.md').read_text(encoding='utf-8') == '# App\n```\na\n\n\nb\n```\n\nEnd.\n'


@pytest.mark.parametrize('approved', ['', '   ', None])
def test_nothing_is_written_before_the_owner_approves(repo, approved):
    proposal = propose(repo, approved=approved)
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'not approved' in r.stderr and 'nothing was written' in r.stderr
    assert snapshot(repo) == before


def test_an_invalid_proposal_is_not_applied(repo):
    proposal = propose(repo, BLOCKS[:5])
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'line 18 is in no block' in r.stdout and 'nothing was written' in r.stderr
    assert snapshot(repo) == before


def test_apply_refuses_a_file_changed_since_the_proposal_and_a_second_run(repo):
    proposal = propose(repo)
    (repo / 'CLAUDE.md').write_bytes((TEXT.replace('half up', 'half down')).encode('utf-8'))
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'has changed since the proposal was written' in r.stdout
    assert snapshot(repo) == before
    (repo / 'CLAUDE.md').write_bytes((TEXT).encode('utf-8'))
    assert run('apply', proposal).returncode == 0
    once = snapshot(repo)
    assert run('apply', proposal).returncode == 2
    assert snapshot(repo) == once


def test_a_write_that_fails_puts_everything_back(repo):
    blocks = with_block(2, to='new/dir/billing.md')
    blocks[5] = {'lines': [18, 18], 'verdict': 'moves', 'to': 'docs/guide.md'}
    proposal = propose(repo, blocks)
    guide = repo / 'docs' / 'guide.md'
    os.chmod(guide, stat.S_IREAD)
    before = snapshot(repo)
    try:
        r = run('apply', proposal)
    finally:
        os.chmod(guide, stat.S_IREAD | stat.S_IWRITE)
    assert r.returncode == 2, r.stdout + r.stderr
    assert 'docs/guide.md' in r.stderr and 'put back' in r.stderr
    assert snapshot(repo) == before and not (repo / 'new').exists()


# verify (FR-006, and the success criteria)

def test_verify_reports_a_moved_block_and_a_hazard_line_that_are_not_found(repo):
    proposal = propose(repo)
    original = repo / 'original.md'
    original.write_bytes((repo / 'CLAUDE.md').read_bytes())
    assert run('apply', proposal).returncode == 0
    r = run('verify', proposal, '--original', original)
    assert r.returncode == 0, r.stdout + r.stderr
    target = repo / '.claude' / 'skills' / 'billing' / 'SKILL.md'
    target.write_bytes((MOVED.replace('half up', 'half-up')).encode('utf-8'))
    (repo / 'CLAUDE.md').write_bytes((AFTER.replace('- The ledger table cannot be recomputed.\n', '')).encode('utf-8'))
    r = run('verify', proposal, '--original', original)
    assert r.returncode == 1
    assert 'block 3 (lines 8-11) is not found word for word in .claude/skills/billing/SKILL.md' in r.stdout
    assert 'hazard line 6 is not in CLAUDE.md: - The ledger table cannot be recomputed.' in r.stdout
    target.unlink()
    r = run('verify', proposal, '--original', original)
    assert r.returncode == 1 and 'block 3 (lines 8-11) is not found word for word' in r.stdout


def test_verify_refuses_an_original_that_is_not_the_one_proposed_on(repo):
    proposal = propose(repo)
    (repo / 'other.md').write_text('# Other\n', encoding='utf-8')
    r = run('verify', proposal, '--original', repo / 'other.md')
    assert r.returncode == 2 and 'is not the file the proposal was written for' in r.stderr


# the result passes the doctor's two rules (FR-007), and the skill says to paste them

def rule(result, name):
    return [line.split()[0] for line in result.stdout.splitlines() if line.startswith(' ') and f' {name} ' in line]


def test_the_shortened_file_passes_s02_and_s18(repo):
    filler = ''.join(f'Detail {n} of the importer.\n' for n in range(160))
    (repo / 'CLAUDE.md').write_bytes((TEXT + '\n## Importer\n\n' + filler).encode('utf-8'))
    (repo / '.claude').mkdir()
    (repo / '.claude' / 'kit.yml').write_text(
        'kit_version: 0.8.0\nprojects:\n  - name: app\n    root: .\n    test: []\n    deviations: []\n', encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'long')

    def doctor():
        return subprocess.run([sys.executable, str(DOCTOR), '--repo', str(repo), '--all'], capture_output=True,
                              text=True, encoding='utf-8')
    assert rule(doctor(), 'S02') == ['GAP']
    blocks = json.loads(json.dumps(BLOCKS)) + [{'lines': [20, 181], 'verdict': 'moves', 'to': 'docs/importer.md',
                                                'pointer': 'The importer: `docs/importer.md`.'}]
    r = run('apply', propose(repo, blocks))
    assert r.returncode == 0, r.stdout + r.stderr
    git(repo, 'add', '-A')
    after = doctor()
    assert rule(after, 'S02') == ['PASS'] and rule(after, 'S18') == ['PASS'], after.stdout
    audit = subprocess.run([sys.executable, str(AUDIT), '--repo', str(repo)], capture_output=True, text=True, encoding='utf-8')
    assert audit.returncode == 0 and 'CLAUDE.md (app): 14 lines' in audit.stdout, audit.stdout


def test_the_skill_stops_for_the_owner_and_pastes_the_doctor(repo):
    text = SKILL.read_text(encoding='utf-8')
    assert text.startswith('---\nname: shrink-claude-md\ndescription: ')
    order = [text.index(word) for word in ('claude_md_shrink.py" start', 'claude_md_shrink.py" show', 'STOP',
                                            'claude_md_shrink.py" apply', 'kit_doctor.py')]
    assert order == sorted(order)
    for needed in ('claude_md_audit.py', 'S02', 'S18', 'hazards_confirmed', 'approved', 'word for word', 'will be created'):
        assert needed in text, needed


# found on the first real run

def test_the_skill_measures_the_named_file_with_paths_from_the_git_root():
    """T013: a CLAUDE.md in a subdirectory is measured with --repo at the git root and --project-root its directory."""
    step = SKILL.read_text(encoding='utf-8').split('## Step 1: measure')[1].split('## Step 2')[0]
    assert '--repo "$(git rev-parse --show-toplevel)" --project-root' in step


def test_the_skill_measures_the_named_file_again_after_apply():
    """T021: Step 7 runs the audit as Step 1 does, so a file in a subdirectory the manifest does not list is measured."""
    step = SKILL.read_text(encoding='utf-8').split('## Step 7')[1].split('## Report')[0]
    audit = next(line for line in step.splitlines() if 'claude_md_audit.py' in line)
    assert '--repo "$(git rev-parse --show-toplevel)" --project-root <directory of the file>' in audit


POINTING = '''# App

> **⚠ Doc-sync note (2026-07-23):** the docs lag the code.
> Trust the code.

## Payload

See the doc-sync note at the top of this file.
- `/x` (PUT) pushes each row (see Special payload fields).
- The payload fields are sent as they are.

## Special payload fields

- `a`: b

## Environment

Set the environment first.
'''
POINTING_BLOCKS = [
    {'lines': [1, 1], 'verdict': 'stays'},
    {'lines': [3, 4], 'verdict': 'moves', 'to': 'docs/sync.md', 'pointer': 'Doc-sync note: `docs/sync.md`.'},
    {'lines': [6, 10], 'verdict': 'stays'},
    {'lines': [12, 14], 'verdict': 'moves', 'to': 'docs/payload.md', 'pointer': 'Payload fields: `docs/payload.md`.'},
    {'lines': [16, 18], 'verdict': 'stays'},
]


def test_show_names_a_line_that_stays_and_points_at_text_that_moves(repo):
    """T014: reported for the owner to reword; nothing is refused or changed."""
    (repo / 'CLAUDE.md').write_bytes(POINTING.encode('utf-8'))
    proposal = propose(repo, POINTING_BLOCKS, hazards_confirmed='none (owner, 2026-11-16)')
    before = snapshot(repo)
    r = run('show', proposal)
    assert r.returncode == 0, r.stdout + r.stderr
    said = [line.strip() for line in r.stdout.splitlines() if 'points at' in line]
    assert said == [
        'line 8 stays and points at "Doc-sync note" of block 2 (lines 3-4), which moves to docs/sync.md: '
        'See the doc-sync note at the top of this file.',
        'line 9 stays and points at "Special payload fields" of block 4 (lines 12-14), which moves to docs/payload.md: '
        '- `/x` (PUT) pushes each row (see Special payload fields).']
    assert 'reword' in r.stdout and re.search(r'^fingerprint: [0-9a-f]{12}$', r.stdout, re.M)
    assert snapshot(repo) == before


def test_shows_after_is_what_apply_writes_and_names_the_pointer_lines(repo):
    """T015: the count after holds the pointers, and says how many of its lines they are."""
    text = ('# App\n\n## A\nalpha\n\n## B\nbeta\n- one\n- two\n## C\ngamma\n\n\n## D\ndelta\n'
            'On 2026-01-01 done.\n\n## E\nend\n- x\n- y\n')
    (repo / 'CLAUDE.md').write_bytes(text.encode('utf-8'))
    blocks = [{'lines': [1, 1], 'verdict': 'stays'},
              {'lines': [3, 4], 'verdict': 'moves', 'to': 'a.md', 'pointer': 'A: `a.md`.'},
              {'lines': [6, 7], 'verdict': 'stays'},
              {'lines': [8, 9], 'verdict': 'moves', 'to': 'b.md', 'pointer': 'B list: `b.md`.'},
              {'lines': [10, 11], 'verdict': 'moves', 'to': 'c.md', 'pointer': 'C: `c.md`.'},
              {'lines': [14, 15], 'verdict': 'moves', 'to': 'd.md', 'pointer': 'D: `d.md`.'},
              {'lines': [16, 16], 'verdict': 'delete', 'why': 'done on a date'},
              {'lines': [18, 19], 'verdict': 'stays'},
              {'lines': [20, 21], 'verdict': 'moves', 'to': 'e.md', 'pointer': 'E list: `e.md`.'}]
    proposal = propose(repo, blocks, hazards_confirmed='none (owner, 2026-11-16)')
    shown = re.search(r'^after:  (\d+) lines, about \d+ tokens \((\d+) that stay, (\d+) pointers?, (\d+) blank\)$',
                      run('show', proposal).stdout, re.M)
    assert shown, run('show', proposal).stdout
    assert run('apply', proposal).returncode == 0
    written = (repo / 'CLAUDE.md').read_text(encoding='utf-8').splitlines()
    assert int(shown.group(1)) == len(written) == 14
    assert [int(n) for n in shown.groups()[1:]] == [5, 5, 4]
    assert int(shown.group(3)) == sum(line.endswith('.md`.') for line in written)


# found by a cold review (2026-11-16)

@pytest.mark.parametrize('line, underline', [
    ('- Pushing to main deploys to production.', '---'),
    ('* Pushing to main deploys to production.', '---'),
    ('+ Pushing to main deploys to production.', '---'),
    ('1. Pushing to main deploys to production.', '---'),
    ('1) Pushing to main deploys to production.', '---'),
    ('> Pushing to main deploys to production.', '---'),
    ('- Pushing to main deploys to production.', '==='),
    ('> Pushing to main deploys to production.', '==='),
    ('- Pushing to main\ndeploys to production.', '---'),         # a lazy continuation of the list item
    ('    Pushing to main deploys to production.', '---'),        # indented code
])
def test_a_list_item_or_a_quote_over_an_underline_is_no_heading_and_its_hazards_cannot_move(repo, line, underline):
    """T018: `---` under a list item, a quote or code is a thematic break, so the Hazards section goes on below it."""
    text = f'# App\n\n## Hazards\n\n{line}\n{underline}\n- The ledger cannot be recomputed.\n\n## Other\n\nx\n'
    (repo / 'CLAUDE.md').write_bytes(text.encode('utf-8'))
    other = text.split('\n').index('## Other') + 1
    blocks = [{'lines': [1, 4], 'verdict': 'stays'}, {'lines': [5, other - 2], 'verdict': 'moves', 'to': 'docs/h.md'},
              {'lines': [other, other + 2], 'verdict': 'stays'}]
    proposal = propose(repo, blocks)
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2, r.stdout + r.stderr
    assert 'block 2 (lines 5-' in r.stdout and 'hazard line 5 is not in a block that stays' in r.stdout
    assert f'hazard line {other - 2} is not in a block that stays' in r.stdout
    assert snapshot(repo) == before and not (repo / 'docs' / 'h.md').exists()


def test_a_paragraph_line_over_an_underline_is_still_a_heading(repo):
    """T018: what CommonMark calls a setext heading still ends the Hazards section."""
    text = '# App\n\n## Hazards\n\n- Never drop the ledger.\n\nOther\nnotes\n---\n\nUse tabs.\n'
    (repo / 'CLAUDE.md').write_bytes(text.encode('utf-8'))
    blocks = [{'lines': [1, 5], 'verdict': 'stays'}, {'lines': [7, 11], 'verdict': 'moves', 'to': 'docs/o.md'}]
    r = run('show', propose(repo, blocks))
    assert r.returncode == 0, r.stdout


POINTER = 'Billing rules: `.claude/skills/billing/SKILL.md`.\n'


@pytest.mark.parametrize('edited, said', [
    (AFTER + '- Pushing to main deploys to production.\n',
     'WRONG  hazard line 5 is in CLAUDE.md 2 times: - Pushing to main deploys to production.'),
    (AFTER.replace(POINTER, POINTER + 'Round every amount half up.\n'),
     'WRONG  block 3 (lines 8-11), which moves to .claude/skills/billing/SKILL.md, is still in CLAUDE.md: '
     'Round every amount half up.'),
    (AFTER + 'On 2026-03-02 the importer was rewritten.\n',
     'WRONG  block 5 (lines 14-16), which is deleted, is still in CLAUDE.md: On 2026-03-02 the importer was rewritten.'),
    (AFTER + POINTER,
     'WRONG  the pointer of block 3 (lines 8-11) is in CLAUDE.md 2 times: Billing rules: `.claude/skills/billing/SKILL.md`.'),
    (AFTER.replace(POINTER, ''),
     'LOST  the pointer of block 3 (lines 8-11) is not in CLAUDE.md: Billing rules: `.claude/skills/billing/SKILL.md`.'),
    (AFTER.replace('## Notes\n', '## Notes\nDeploy on Fridays.\n'),
     'WRONG  line 11 of CLAUDE.md is neither a line that stays, nor a pointer, nor blank: Deploy on Fridays.'),
    (AFTER.replace('- The ledger table cannot be recomputed.\n', '').replace('## Notes\n', '## Notes\n- The ledger table cannot be recomputed.\n'),
     'LOST  line 13 of block 4 (lines 13-13), which stays, is not in CLAUDE.md in its place: ## Notes'),
])
def test_verify_refuses_a_hand_edit_after_a_good_apply_and_names_it(repo, edited, said):
    """T019: not only the lines that stay in order, but nothing else: no line twice, no moved text, no pointer lost."""
    proposal = propose(repo)
    original = repo / 'original.md'
    original.write_bytes((repo / 'CLAUDE.md').read_bytes())
    assert run('apply', proposal).returncode == 0
    (repo / 'CLAUDE.md').write_bytes(edited.encode('utf-8'))
    r = run('verify', proposal, '--original', original)
    assert r.returncode == 1, r.stdout + r.stderr
    assert said in r.stdout.splitlines(), r.stdout


def test_verify_accepts_a_pointer_or_a_blank_line_moved_when_every_line_that_stays_keeps_its_order(repo):
    """T019: with the order of the lines that stay kept and no line added or lost, only a pointer or a blank line moved."""
    proposal = propose(repo)
    original = repo / 'original.md'
    original.write_bytes((repo / 'CLAUDE.md').read_bytes())
    assert run('apply', proposal).returncode == 0
    (repo / 'CLAUDE.md').write_bytes(AFTER.replace(POINTER + '\n', '').replace('first.\n', 'first.\n\n' + POINTER).encode('utf-8'))
    r = run('verify', proposal, '--original', original)
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_line_shared_by_a_block_that_moves_and_one_that_stays_is_no_false_report(repo):
    """T019: a fence line or a hazard text twice in the original is kept as often as it was."""
    text = ('# App\n\n## Hazards\n\n- none\n\n## Run\n\n```\nmake\n```\n\n## Build\n\n```\nbuild\n```\n\n'
            '## More\n\n- none\n')
    (repo / 'CLAUDE.md').write_bytes(text.encode('utf-8'))
    blocks = [{'lines': [1, 5], 'verdict': 'stays'}, {'lines': [7, 11], 'verdict': 'stays'},
              {'lines': [13, 17], 'verdict': 'moves', 'to': 'docs/build.md', 'pointer': 'Build: `docs/build.md`.'},
              {'lines': [19, 21], 'verdict': 'stays'}]
    proposal = propose(repo, blocks, hazards=[[21, 21]], hazards_confirmed='line 21 too (owner, 2026-11-16)')
    original = repo / 'original.md'
    original.write_bytes(text.encode('utf-8'))
    r = run('apply', proposal)
    assert r.returncode == 0, r.stdout + r.stderr
    assert run('verify', proposal, '--original', original).returncode == 0


def test_a_target_created_after_show_is_refused_and_named(repo):
    """T020: `show` said "will be created"; a docs/b.md made after it is not what the owner approved."""
    proposal = propose(repo, with_block(2, to='docs/b.md'))
    assert 'docs/b.md (will be created)' in run('show', proposal).stdout
    (repo / 'docs' / 'b.md').write_bytes(b'# Unrelated\n\nSomething else.\n')
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2, r.stdout + r.stderr
    assert 'docs/b.md was created after `show`' in r.stderr and 'nothing was written' in r.stderr
    assert snapshot(repo) == before


def test_a_target_changed_after_show_is_refused_and_named(repo):
    """T020: an existing target is fingerprinted by its text, CRLF read as LF."""
    proposal = propose(repo, with_block(2, to='docs/guide.md'))
    shown = run('show', proposal).stdout
    guide = repo / 'docs' / 'guide.md'
    assert f'to docs/guide.md (appended to; sha256 {sha(guide)[:12]})' in shown
    guide.write_bytes(guide.read_bytes().replace(b'\n', b'\r\n'))      # the same text: still approved
    again = run('show', proposal)
    assert again.returncode == 0, again.stdout
    assert re.search(r'^approved: yes', again.stdout, re.M), again.stdout
    guide.write_bytes(b'# Guide\r\n\r\nA line added after show.\r\n')
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2, r.stdout + r.stderr
    assert f'docs/guide.md (appended to; sha256 {sha(guide)[:12]})' in r.stderr and 'shown again' in r.stderr
    assert snapshot(repo) == before


def test_an_approval_given_before_the_targets_were_fingerprinted_fails_closed(repo):
    """T020: the fingerprint of a proposal made before this change, approved, is refused: show it again."""
    proposal = propose(repo, approved='')
    data = json.loads(proposal.read_text(encoding='utf-8'))
    blocks = [{key: block.get(key) for key in ('lines', 'verdict', 'to', 'pointer')} for block in data['blocks']]
    shown = {'sha256': data['sha256'], 'blocks': blocks, 'hazards': data['hazards']}
    old = hashlib.sha256(json.dumps(shown, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:12]
    data['approved'] = f'yes, apply it (owner, 2026-11-12), fingerprint {old}'
    proposal.write_text(json.dumps(data), encoding='utf-8')
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'shown again and approved again' in r.stderr, r.stdout + r.stderr
    assert snapshot(repo) == before


def test_a_crlf_checkout_of_the_same_text_is_the_file_proposed_on(repo, tmp_path_factory):
    """T016: core.autocrlf=true writes CRLF; the text is the same, so the proposal holds. A changed text is refused."""
    proposal = propose(repo)
    clone = tmp_path_factory.mktemp('crlf') / 'clone'
    subprocess.run(['git', '-c', 'core.autocrlf=true', 'clone', '-q', str(repo), str(clone)], check=True,
                   capture_output=True)
    assert b'\r\n' in (clone / 'CLAUDE.md').read_bytes()
    (clone / 'proposal.json').write_bytes(proposal.read_bytes())
    r = run('show', clone / 'proposal.json')
    assert r.returncode == 0, r.stdout + r.stderr
    original = clone.parent / 'original.md'
    original.write_bytes((clone / 'CLAUDE.md').read_bytes())
    r = run('apply', clone / 'proposal.json')
    assert r.returncode == 0, r.stdout + r.stderr
    assert (clone / 'CLAUDE.md').read_bytes() == AFTER.replace('\n', '\r\n').encode('utf-8')
    assert run('verify', clone / 'proposal.json', '--original', original).returncode == 0
    (clone / 'CLAUDE.md').write_bytes(TEXT.replace('half up', 'half down').replace('\n', '\r\n').encode('utf-8'))
    r = run('show', clone / 'proposal.json')
    assert r.returncode == 1 and 'CLAUDE.md has changed since the proposal was written' in r.stdout


def test_a_proposal_made_on_a_copy_is_applied_to_the_file_named(repo, tmp_path_factory):
    """T017: --file names the CLAUDE.md in the repository; targets are read from its repository; the copy is untouched."""
    (repo / 'sub').mkdir()
    (repo / 'CLAUDE.md').rename(repo / 'sub' / 'CLAUDE.md')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'sub')
    copy = tmp_path_factory.mktemp('copy')
    (copy / 'CLAUDE.md').write_bytes((repo / 'sub' / 'CLAUDE.md').read_bytes())
    assert run('start', copy / 'CLAUDE.md').returncode == 0
    proposal = copy / 'claude-md-shrink.json'
    data = json.loads(proposal.read_text(encoding='utf-8'))
    data['blocks'] = json.loads(json.dumps(BLOCKS))
    proposal.write_text(json.dumps(data), encoding='utf-8')
    mark = re.search(r'^fingerprint: ([0-9a-f]{12})$', run('show', proposal).stdout, re.M).group(1)
    data['approved'] = f'yes, apply it (owner, 2026-11-16), fingerprint {mark}'
    proposal.write_text(json.dumps(data), encoding='utf-8')
    target = repo / 'sub' / 'CLAUDE.md'
    shown = run('show', proposal, '--file', target)
    assert shown.returncode == 0, shown.stdout + shown.stderr
    assert f'fingerprint: {mark}' in shown.stdout
    copied, kept = snapshot(copy), repo / 'kept.md'
    kept.write_bytes(target.read_bytes())
    r = run('apply', proposal, '--file', target)
    assert r.returncode == 0, r.stdout + r.stderr
    assert target.read_bytes() == AFTER.encode('utf-8')
    assert (repo / '.claude' / 'skills' / 'billing' / 'SKILL.md').read_bytes() == MOVED.encode('utf-8')
    assert 'sub/CLAUDE.md' in r.stdout
    assert snapshot(copy) == copied and not (copy / '.claude').exists()
    r = run('verify', proposal, '--original', kept, '--file', target)
    assert r.returncode == 0, r.stdout + r.stderr
