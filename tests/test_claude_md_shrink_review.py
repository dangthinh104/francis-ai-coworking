"""claude_md_shrink.py: what a review of specs/002 found, each as a test that failed first."""
import importlib.util
import json
import re

import pytest

from test_claude_md_shrink import AFTER, BLOCKS, MOVED, SHRINK, TEXT, propose, repo, run, sha, snapshot, with_block  # noqa: F401

OWNER = 'yes, apply it (owner, 2026-11-12)'
NONE = 'none in this file (owner, 2026-11-12)'


def write(path, text):
    path.write_bytes(text.encode('utf-8'))


def fingerprint(proposal):
    found = re.search(r'^fingerprint: ([0-9a-f]{12})$', run('show', proposal).stdout, re.M)
    return found.group(1) if found else None


# 1. history needs a real date

NOT_DATES = ['Retries may 2000 ms apart', 'Requests may 1000 fail', 'set sep 2048', 'chmod oct 0755', 'Dec 1000 to 999',
             'Call 5550-12-34', 'id 1234-56-78', 'Ratio 10/10/10 split', 'aspect 16/9/22', 'Path a/1/2/34/b',
             'build 2026-11-123', 'range 2026-13-01', 'key 12026-11-12', 'In march 2026 lowercase']
DATES = ['Done 2026-11-12.', 'Done 12/11/2026.', 'Done 11/25/2026.', 'Nov 2026 release', '12 Nov 2026', 'Nov 12, 2026',
         'November 2026', 'NOVEMBER 2026', 'tháng 11 năm 2026', 'Xong 11/2026', '2026 November']


def dated(repo, line):
    write(repo / 'CLAUDE.md', '# Hazards\n\n- none\n\n# Log\n\n' + line + '\n')
    return propose(repo, [{'lines': [1, 3], 'verdict': 'stays'}, {'lines': [5, 5], 'verdict': 'stays'},
                          {'lines': [7, 7], 'verdict': 'delete', 'why': 'history'}])


@pytest.mark.parametrize('line', NOT_DATES)
def test_what_only_looks_like_a_date_does_not_make_a_block_history(repo, line):
    r = run('show', dated(repo, line))
    assert r.returncode == 1 and 'block 3 (lines 7-7): "delete" on a block that holds no date' in r.stdout, r.stdout


@pytest.mark.parametrize('line', DATES)
def test_a_real_date_does(repo, line):
    r = run('show', dated(repo, line))
    assert r.returncode == 0, r.stdout


# 2. a block whose range ends on a blank line

def test_a_moved_block_is_written_and_compared_without_its_outer_blank_lines(repo):
    write(repo / 'CLAUDE.md', '# T\nkeep\n\n## A\nmove me\n\n## B\nkeep2\n')
    blocks = [{'lines': [1, 2], 'verdict': 'stays'}, {'lines': [4, 6], 'verdict': 'moves', 'to': 'docs/a.md'},
              {'lines': [7, 8], 'verdict': 'stays'}]
    r = run('apply', propose(repo, blocks, hazards_confirmed=NONE))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / 'docs' / 'a.md').read_bytes() == b'## A\nmove me\n'
    assert (repo / 'CLAUDE.md').read_bytes() == b'# T\nkeep\n\n## B\nkeep2\n'


def test_a_moved_block_of_blank_lines_only_is_refused(repo):
    blocks = BLOCKS + [{'lines': [7, 7], 'verdict': 'moves', 'to': 'docs/a.md'}]
    r = run('show', propose(repo, blocks))
    assert r.returncode == 1 and 'block 7 (lines 7-7): "moves" on a block that holds no text' in r.stdout


# 3. any failure puts everything back; a control character is no path

def test_an_error_that_is_no_oserror_puts_everything_back_too(repo, monkeypatch):
    blocks = with_block(2, to='new/dir/billing.md')
    blocks[5] = {'lines': [18, 18], 'verdict': 'moves', 'to': 'docs/guide.md'}
    proposal = propose(repo, blocks)
    spec = importlib.util.spec_from_file_location('claude_md_shrink_under_test', SHRINK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real, calls = module.kit_spec.replace, []

    def second_fails(path, body):
        calls.append(path)
        if len(calls) == 2:
            raise ValueError('embedded null character')
        real(path, body)
    monkeypatch.setattr(module.kit_spec, 'replace', second_fails)
    before = snapshot(repo)
    assert module.main(['apply', str(proposal)]) == 2
    assert len(calls) == 2 and snapshot(repo) == before and not (repo / 'new').exists()


@pytest.mark.parametrize('to', ['b\u0000.md', 'a\nb.md', 'docs/\x1f.md'])
def test_a_target_with_a_control_character_is_refused_before_anything_is_written(repo, to):
    proposal = propose(repo, with_block(2, to=to))
    before = snapshot(repo)
    r = run('show', proposal)
    assert r.returncode == 1 and 'block 3 (lines 8-11): the target holds a control character' in r.stdout, r.stdout + r.stderr
    assert run('apply', proposal).returncode == 2 and snapshot(repo) == before


# 4. a line ends at a line feed and nowhere else

def test_a_form_feed_or_a_unicode_separator_does_not_cut_a_line(repo):
    odd = 'b\x0cc and d e and f\x85g and h\ri'
    write(repo / 'CLAUDE.md', '# Hazards\n\n- ' + odd + '\n\n# Rules\n\nmove ' + odd + '\n')
    blocks = [{'lines': [1, 3], 'verdict': 'stays'}, {'lines': [5, 5], 'verdict': 'stays'},
              {'lines': [7, 7], 'verdict': 'moves', 'to': 'docs/r.md'}]
    proposal = propose(repo, blocks)
    r = run('show', proposal)
    assert r.returncode == 0 and 'before: 7 lines' in r.stdout and 'after:  5 lines' in r.stdout, r.stdout
    assert run('apply', proposal).returncode == 0
    assert (repo / 'CLAUDE.md').read_bytes() == ('# Hazards\n\n- ' + odd + '\n\n# Rules\n').encode('utf-8')
    assert (repo / 'docs' / 'r.md').read_bytes() == ('move ' + odd + '\n').encode('utf-8')


def test_start_counts_lines_the_same_way(repo):
    write(repo / 'CLAUDE.md', '# A\n\nb\x0cc\nd\n')
    r = run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json')
    assert r.returncode == 0 and ': 4 lines' in r.stdout
    assert [b['lines'] for b in json.loads((repo / 'p.json').read_text(encoding='utf-8'))['blocks']] == [[1, 1], [3, 4]]


# 5. a Hazards heading in any dress

HAZARD_HEADINGS = ['## Hazards (read first)', '## ⚠ Hazards', '## Hazards.', '## **Hazard:**', '### HAZARDS ###',
                   'Hazards\n===', 'Hazards\n---', '## Nguy hiểm / hazards']


@pytest.mark.parametrize('heading', HAZARD_HEADINGS)
def test_a_hazards_heading_is_recognised_however_it_is_written(repo, heading):
    text = '# App\n\n' + heading + '\n\n- Never drop the ledger.\n\n## Other\n\ntext\n'
    write(repo / 'CLAUDE.md', text)
    other = text.split('\n').index('## Other') + 1
    blocks = [{'lines': [1, 1], 'verdict': 'stays'}, {'lines': [3, other - 2], 'verdict': 'moves', 'to': 'docs/h.md'},
              {'lines': [other, other + 2], 'verdict': 'stays'}]
    r = run('show', propose(repo, blocks, hazards_confirmed=NONE))
    assert r.returncode == 1 and 'is not in a block that stays' in r.stdout, r.stdout
    assert 'the Hazards section' in r.stdout
    s = run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json')
    assert 'Hazards section' in s.stdout and 'candidates' not in s.stdout


@pytest.mark.parametrize('heading', ['## Haphazard notes', '## Other', 'Not a heading\n\n---'])
def test_what_is_not_a_hazards_heading_is_not_one(repo, heading):
    write(repo / 'CLAUDE.md', '# App\n\n' + heading + '\n\ntext\n')
    assert 'no Hazards section' in run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json').stdout


def test_front_matter_is_not_a_heading(repo):
    write(repo / 'CLAUDE.md', '---\nhazards: none\n---\n\n# App\n')
    assert 'no Hazards section' in run('start', repo / 'CLAUDE.md', '--out', repo / 'p.json').stdout


# 6. verify finds what stays, and a missing file is not a pass

def all_stay(repo):
    write(repo / 'CLAUDE.md', '# App\n\nRule one.\nRule two.\n\nRule three.\n')
    write(repo / 'original.md', '# App\n\nRule one.\nRule two.\n\nRule three.\n')
    return propose(repo, [{'lines': [1, 1], 'verdict': 'stays'}, {'lines': [3, 6], 'verdict': 'stays'}],
                   hazards_confirmed=NONE)


def test_verify_finds_every_line_that_stays_in_order(repo):
    proposal = all_stay(repo)
    r = run('verify', proposal, '--original', repo / 'original.md')
    assert r.returncode == 0 and '4 line(s) that stay found in order' in r.stdout, r.stdout + r.stderr
    write(repo / 'CLAUDE.md', '')
    r = run('verify', proposal, '--original', repo / 'original.md')
    assert r.returncode == 1 and r.stdout.count('LOST') == 4
    assert 'line 3 of block 2 (lines 3-6), which stays, is not in CLAUDE.md in its place: Rule one.' in r.stdout
    write(repo / 'CLAUDE.md', '# App\n\nRule two.\nRule one.\n\nRule three.\n')
    r = run('verify', proposal, '--original', repo / 'original.md')
    assert r.returncode == 1 and r.stdout.count('LOST') == 1 and 'line 4 of block 2' in r.stdout


def test_verify_exits_2_when_the_file_is_gone(repo):
    proposal = all_stay(repo)
    (repo / 'CLAUDE.md').unlink()
    r = run('verify', proposal, '--original', repo / 'original.md')
    assert r.returncode == 2 and 'CLAUDE.md is missing' in r.stderr


# 7. the approval names what was shown

def test_show_prints_a_fingerprint_that_changes_with_what_the_owner_reads(repo):
    seen = {fingerprint(propose(repo))}
    assert None not in seen
    assert fingerprint(propose(repo, hazards_confirmed='other words', approved='other')) in seen     # not what is fingerprinted
    for changed in (with_block(2, to='docs/b.md'), with_block(2, pointer='Elsewhere.'), with_block(3, why='not read'),
                    with_block(5, verdict='moves', to='docs/b.md')):
        seen.add(fingerprint(propose(repo, changed)))
    seen.add(fingerprint(propose(repo, hazards=[[1, 1]])))
    assert len(seen) == 5       # block 4 with the same lines is the same proposal
    with (repo / 'CLAUDE.md').open('ab') as fh:
        fh.write(b'\n')
    assert fingerprint(propose(repo)) not in seen


def test_apply_refuses_an_approval_that_does_not_name_the_fingerprint(repo):
    proposal = propose(repo, approved=OWNER)
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'fingerprint' in r.stderr and 'nothing was written' in r.stderr
    assert snapshot(repo) == before


def test_a_proposal_changed_after_it_was_shown_needs_a_new_approval(repo):
    proposal = propose(repo)
    data = json.loads(proposal.read_text(encoding='utf-8'))
    assert fingerprint(proposal) in data['approved']
    data['blocks'][2]['to'] = 'docs/elsewhere.md'
    proposal.write_text(json.dumps(data), encoding='utf-8')
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'fingerprint' in r.stderr and fingerprint(proposal) in r.stderr
    assert snapshot(repo) == before
    assert 'does not name this fingerprint' in run('show', proposal).stdout


def test_the_skill_binds_the_approval_to_the_fingerprint():
    text = (SHRINK.parent.parent / 'SKILL.md').read_text(encoding='utf-8')
    assert 'fingerprint' in text and 'new approval' in text and 'only an approval' in text.lower()


# 8 and 10. every field is checked before it is used

@pytest.mark.parametrize('blocks, said', [
    (with_block(2, pointer=5), 'block 3 (lines 8-11): the pointer is not text'),
    (with_block(2, pointer=['x']), 'block 3 (lines 8-11): the pointer is not text'),
    (with_block(2, to=5), 'block 3 (lines 8-11): "moves" names no target'),
    (with_block(2, to='   '), 'block 3 (lines 8-11): "moves" names no target'),
    (with_block(2, to='.git/hooks/x.md'), 'block 3 (lines 8-11): the target .git/hooks/x.md is not a file a block can move to'),
    (with_block(2, to='proposal.json'), 'block 3 (lines 8-11): the target proposal.json is not a file a block can move to'),
    (with_block(4, why='   '), 'block 5 (lines 14-16): "delete" without `why`'),
    (with_block(4, why=5), 'block 5 (lines 14-16): "delete" without `why`'),
    (with_block(0, verdict=['stays']), 'block 1 (lines 1-1): the verdict is ["stays"]'),
    (with_block(0, lines=[0, 1]), 'block 1: `lines` is not'),
    (with_block(1, lines=[6, 3]), 'block 2: `lines` is not'),
    (with_block(0, lines=['1', '1']), 'block 1: `lines` is not'),
    (with_block(0, lines=[1.0, 1]), 'block 1: `lines` is not'),
    (with_block(0, lines=[True, 1]), 'block 1: `lines` is not'),
    (with_block(0, lines=None), 'block 1: `lines` is not'),
    (BLOCKS + ['stays'], 'block 7: not an object'),
    (BLOCKS + [None], 'block 7: not an object'),
])
def test_a_field_of_the_wrong_kind_is_an_error_that_names_the_block(repo, blocks, said):
    r = run('show', propose(repo, blocks))
    assert r.returncode == 1, r.stdout + r.stderr
    assert said in r.stdout and 'fingerprint:' not in r.stdout


@pytest.mark.parametrize('hazards', ['x', [[1]], [[1, 99]], [[0, 1]], [[2, 1]], [1, 2], None, {'a': 1}])
def test_hazards_that_are_not_ranges_of_the_file_are_an_error(repo, hazards):
    r = run('show', propose(repo, hazards=hazards))
    assert r.returncode == 1 and '`hazards` is not a list of [first, last]' in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize('confirmed', ['   ', 5, None, ['none']])
def test_a_confirmation_that_is_no_text_is_no_confirmation(repo, confirmed):
    write(repo / 'CLAUDE.md', '# App\n\nUse tabs.\n')
    r = run('show', propose(repo, [{'lines': [1, 3], 'verdict': 'stays'}], hazards_confirmed=confirmed))
    assert r.returncode == 1 and '`hazards_confirmed` is empty' in r.stdout, r.stdout + r.stderr


@pytest.mark.parametrize('approved', [5, ['yes'], {'yes': 1}, True])
def test_an_approval_that_is_no_text_is_no_approval(repo, approved):
    proposal = propose(repo, approved=approved)
    before = snapshot(repo)
    r = run('apply', proposal)
    assert r.returncode == 2 and 'not approved' in r.stderr
    assert snapshot(repo) == before
    assert run('show', proposal).returncode == 0


def test_a_proposal_whose_fields_are_all_wrong_does_not_crash(repo):
    path = repo / 'odd.json'
    path.write_text(json.dumps({'file': 'CLAUDE.md', 'sha256': sha(repo / 'CLAUDE.md'), 'hazards': 5, 'hazards_confirmed': 5,
                                'approved': 5, 'blocks': [5, {'lines': [1, 18], 'verdict': 'moves', 'to': 5, 'pointer': 5,
                                                              'why': 5}]}), encoding='utf-8')
    for command in ('show', 'apply'):
        r = run(command, path)
        assert 'could not finish' not in r.stderr and r.returncode == (1 if command == 'show' else 2), r.stderr


def test_found_word_for_word_means_whole_lines(repo):
    proposal = propose(repo)
    write(repo / 'original.md', TEXT)
    assert run('apply', proposal).returncode == 0
    target = repo / '.claude' / 'skills' / 'billing' / 'SKILL.md'
    for almost in ('x' + MOVED, MOVED.rstrip('\n') + 'y\n', MOVED.replace('\n\n', '\n')):
        write(target, almost)
        r = run('verify', proposal, '--original', repo / 'original.md')
        assert r.returncode == 1 and 'block 3 (lines 8-11) is not found word for word' in r.stdout, almost
    write(target, 'above\n' + MOVED.replace('\n', '\r\n') + 'below\n')
    assert run('verify', proposal, '--original', repo / 'original.md').returncode == 0


@pytest.mark.parametrize('old, wanted', [
    (b'# Guide', b'# Guide\n\n' + MOVED.encode()),
    (b'# Guide\r\n', b'# Guide\r\n\r\n' + MOVED.replace('\n', '\r\n').encode()),
    (b'# Guide\r\nlast', b'# Guide\r\nlast\r\n\r\n' + MOVED.replace('\n', '\r\n').encode()),
    (b'', MOVED.encode()),
])
def test_an_existing_target_keeps_its_bytes_and_its_line_endings(repo, old, wanted):
    (repo / 'docs' / 'guide.md').write_bytes(old)
    r = run('apply', propose(repo, with_block(2, to='docs/guide.md')))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / 'docs' / 'guide.md').read_bytes() == wanted


# 9. smaller

@pytest.mark.parametrize('text', [
    '\n\n# App\n\n\n\nRule one.\n\n\n## Two\n```\na\n\n\nb\n```\n\n\n',
    '# App\r\n\r\n\r\nRule one.\r\n\r\n## Two\r\nlast line without an end',
    '# App\n\nmixed\r\nendings\n\n\nhere\r\n',
])
def test_a_proposal_in_which_everything_stays_gives_the_file_back_byte_for_byte(repo, text):
    write(repo / 'CLAUDE.md', text)
    assert run('start', repo / 'CLAUDE.md', '--out', repo / 'proposal.json').returncode == 0
    data = json.loads((repo / 'proposal.json').read_text(encoding='utf-8'))
    for block in data['blocks']:
        block['verdict'] = 'stays'
    data['hazards_confirmed'] = NONE
    (repo / 'proposal.json').write_text(json.dumps(data), encoding='utf-8')
    data['approved'] = OWNER + ' ' + fingerprint(repo / 'proposal.json')
    (repo / 'proposal.json').write_text(json.dumps(data), encoding='utf-8')
    r = run('apply', repo / 'proposal.json')
    assert r.returncode == 0, r.stdout + r.stderr
    assert (repo / 'CLAUDE.md').read_bytes() == text.encode('utf-8')


def test_blank_lines_collapse_only_where_a_block_was_taken_out(repo):
    write(repo / 'CLAUDE.md', '# App\n\n\nRule.\n\n\nOn 2026-01-01 done.\n\n\nEnd.\n\n\nLast.\n')
    blocks = [{'lines': [1, 1], 'verdict': 'stays'}, {'lines': [4, 4], 'verdict': 'stays'},
              {'lines': [7, 7], 'verdict': 'delete', 'why': 'history'}, {'lines': [10, 10], 'verdict': 'stays'},
              {'lines': [13, 13], 'verdict': 'stays'}]
    assert run('apply', propose(repo, blocks, hazards_confirmed=NONE)).returncode == 0
    assert (repo / 'CLAUDE.md').read_bytes() == b'# App\n\n\nRule.\n\nEnd.\n\n\nLast.\n'


def test_a_target_that_is_not_utf8_is_refused(repo):
    (repo / 'docs' / 'guide.md').write_bytes('# Guide\n'.encode('utf-16'))
    proposal = propose(repo, with_block(2, to='docs/guide.md'))
    before = snapshot(repo)
    r = run('show', proposal)
    assert r.returncode == 1 and 'block 3 (lines 8-11): the target docs/guide.md is not UTF-8' in r.stdout
    assert run('apply', proposal).returncode == 2 and snapshot(repo) == before


def test_the_lost_message_names_the_path_as_the_proposal_wrote_it(repo):
    proposal = propose(repo, with_block(2, to='./docs/../docs/billing.md'))
    write(repo / 'original.md', TEXT)
    assert run('apply', proposal).returncode == 0
    (repo / 'docs' / 'billing.md').unlink()
    r = run('verify', proposal, '--original', repo / 'original.md')
    assert r.returncode == 1 and 'is not found word for word in ./docs/../docs/billing.md' in r.stdout
