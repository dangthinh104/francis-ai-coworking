"""Spec 019: the lint warns on an Approved spec, and the doctor says whose words it prints and which kit is newer.

Each test builds its repository under tmp_path, as the spec's success criteria name it (`P`, `H`, the directory
of `LINT`). Nothing reaches the network: the kit of v0.13.0 is read from this repository's own tag.
"""
import io
import re
import subprocess
import sys
import tarfile

import pytest

from test_adoption_shapes import S09_A, S09_B, add_entries, debt_repo
from test_gate_hook import HOOK_FILE, TAG, WORKFLOW_FILE, k, make_h, write_lf  # noqa: F401 (k is a fixture)
from test_kit_gate import REPO, commit, gate, git, index, make_p, stamp, write
from test_standard import LINT, manifest, save

TWO = 'two behaviours under one id'
WARNED = 'WARN  001-a: two behaviours under one id'
LINT_REQUIREMENTS = ('- **FR-001**: The system MUST send an email and MUST close the account.\n'
                     '- **FR-002**: The system MUST log the request as well as the answer.\n'
                     '- **FR-003**: The system MUST refuse a request with no token.\n')
SCAFFOLD_ADVICE = 'write the gate again with `kit_scaffold.py --repo . --gate`'
OLD_WORDS = 'the gate is judged by the version it pins'
UPDATE = ('Update the installed plugin (claude plugin marketplace update francis-ai-coworking, then claude plugin '
          'update francis-kit@francis-ai-coworking, again with --scope project where the project installed it) and '
          'run the doctor again')
FIX = '         fix (from .claude/kit.yml): '
SPEC_LINT = 'plugins/francis-kit/skills/write-spec/scripts/spec_lint.py'
SKILL = 'plugins/francis-kit/skills/write-spec/SKILL.md'
THREE = (SPEC_LINT, SKILL, 'README.md')


def older(name, pin):
    """019/FR-003, word for word."""
    return (f'{name} pins {pin}, and a newer kit, {TAG}, is installed here: the gate runs and is judged by the checks '
            f'of {pin}, and this doctor judges only a gate of {TAG}. To take {TAG}, write the gate again with '
            f'`kit_scaffold.py --repo . --gate`')


def newer(name, pin):
    """019/FR-004, word for word."""
    return (f'{name} pins {pin}, newer than the kit installed here, {TAG}: this doctor judges only a gate of {TAG}. '
            f'{UPDATE}; writing the gate again with this kit would take it back to {TAG}')


def lint_spec(status):
    head = '# Feature Specification: a\n\n'
    if status:
        head += f'**Status**: {status}\n'
    return head + '**Ticket**: none\n**Capability**: demo\n\n## Requirements\n\n' + LINT_REQUIREMENTS


def lint(root, status, *args):
    write(root / 'specs' / '001-a' / 'spec.md', lint_spec(status))
    return subprocess.run([sys.executable, str(LINT), '--root', '.', *args], cwd=root, capture_output=True,
                          text=True, encoding='utf-8')


def doctor(repo):
    return subprocess.run([sys.executable, str(LINT.parents[2] / 'kit-init' / 'scripts' / 'kit_doctor.py'),
                           '--repo', '.', '--all'], cwd=repo, capture_output=True, text=True, encoding='utf-8')


def s14(r):
    return [l for l in r.stdout.splitlines() if 'GAP  S14' in l]


def pin_workflow(repo, pin):
    path = repo / WORKFLOW_FILE
    text = path.read_text(encoding='utf-8')
    pinned = re.sub(r'(?m)^(\s*ref: )v\d+\.\d+\.\d+$', lambda m: m.group(1) + pin, text)
    assert pinned != text or f'ref: {pin}' in text
    write(path, pinned)
    commit(repo)


@pytest.fixture
def p(tmp_path):
    return make_p(tmp_path / 'p')


def test_sc001_an_approved_spec_gets_the_two_behaviour_warning(tmp_path):
    """019/FR-001, SC-001."""
    for status in ('Approved', 'Draft'):
        r = lint(tmp_path, status)
        warned = [l for l in r.stdout.splitlines() if l.startswith(WARNED)]
        assert r.returncode == 0 and len(warned) == 1, (status, r.stdout)
        assert 'FR-001' in warned[0] and 'FR-002' in warned[0] and 'FR-003' not in warned[0], (status, warned)
        assert lint(tmp_path, status, '--strict').returncode == 1, status
    for status in ('Built', 'Released', 'Closed', None):
        r = lint(tmp_path, status)
        assert not [l for l in r.stdout.splitlines() if 'two behaviours' in l], (status, r.stdout)


def test_sc002_the_gate_prints_the_warning_and_passes(p):
    """019/FR-001, SC-002."""
    write(p / 'specs' / '001-a' / 'spec.md', lint_spec('Approved'))
    index(p)
    commit(p)
    r = gate(p)
    assert r.code == 0 and r.verdict == 'kit-gate: passed: ' + stamp(p), r.lines
    at = r.lines.index('kit-gate: lint: .')
    assert [l for l in r.lines[at + 1:] if l.startswith(WARNED) and 'FR-001' in l and 'FR-002' in l], r.lines


def grep(*args):
    return subprocess.run(['git', 'grep', '-n', *args, '--', *THREE], cwd=REPO, capture_output=True, text=True,
                          encoding='utf-8').stdout.splitlines()


def check_section():
    text = (REPO / SKILL).read_text(encoding='utf-8')
    start = text.index('\n## Check\n')
    return text[start:text.index('\n## ', start + 1)]


@pytest.mark.private
def test_sc003_the_three_documents_say_draft_or_approved():
    """019/FR-002, SC-003."""
    found = grep('Draft or Approved')
    for name in THREE:
        assert [l for l in found if l.startswith(name + ':')], (name, found)
    readme = [l.split(':', 2)[2] for l in found if l.startswith('README.md:')]
    assert [l for l in readme if l.startswith('| `write-spec/scripts/spec_lint.py')], readme
    assert 'Draft or Approved' in check_section()
    assert grep('-e', 'in a Draft spec only', '-e', 'On a Draft the lint also warns',
                '-e', 'in a Draft spec, a requirement that holds two') == []


def test_sc004_a_pin_older_than_the_kit_says_a_newer_kit_is_installed(p, tmp_path):
    """019/FR-003, SC-004."""
    for pin in ('v0.13.0', 'v0.9.0'):
        pin_workflow(p, pin)
        r = doctor(p)
        assert r.returncode == 1 and s14(r) == ['  GAP  S14 ' + older('kit-gate.yml', pin)], (pin, r.stdout)
        assert SCAFFOLD_ADVICE in s14(r)[0] and OLD_WORDS not in r.stdout
        assert f'kit-gate.yml pins {pin}, and a newer kit, {TAG}, is installed here' in s14(r)[0]


@pytest.mark.private
def test_sc004_the_gate_of_the_pinned_kit_passes_s14(p, tmp_path):
    """019/FR-003, SC-004: what the gate runs, `kit_gate.py` of v0.13.0, passes S14 as before."""
    tagged = subprocess.run(['git', 'rev-parse', '-q', '--verify', 'v0.13.0^{commit}'], cwd=REPO, capture_output=True)
    assert tagged.returncode == 0, 'the tag v0.13.0 is not in this clone: fetch the tags (git fetch --tags)'
    archive = subprocess.run(['git', 'archive', '--format=tar', 'v0.13.0', 'plugins'], cwd=REPO, capture_output=True,
                             check=True).stdout
    kit = tmp_path / 'kit-0.13.0'
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        if hasattr(tarfile, 'data_filter'):
            tar.extractall(kit, filter='data')
        else:
            tar.extractall(kit)
    pin_workflow(p, 'v0.13.0')
    r = gate(p, script=kit / 'plugins' / 'francis-kit' / 'skills' / 'kit-init' / 'scripts' / 'kit_gate.py')
    assert r.code == 0 and '  PASS S14 (the gate)' in r.lines, r.lines


def test_sc005_a_pin_newer_than_the_kit_says_update_the_plugin(p):
    """019/FR-004, SC-005."""
    pin_workflow(p, 'v99.0.0')
    r = doctor(p)
    assert r.returncode == 1 and s14(r) == ['  GAP  S14 ' + newer('kit-gate.yml', 'v99.0.0')], r.stdout
    assert 'claude plugin marketplace update francis-ai-coworking' in s14(r)[0] and 'kit_scaffold.py' not in s14(r)[0]


def test_sc006_the_hook_gets_the_same_words(tmp_path, k):
    """019/FR-003, 019/FR-004, SC-006."""
    h = make_h(tmp_path / 'h', k)
    path = h / HOOK_FILE
    whole = path.read_bytes().decode('utf-8')
    assert f'KIT_REF={TAG}\n' in whole
    for pin, said in (('v0.13.0', older), ('v99.0.0', newer)):
        write_lf(path, whole.replace(f'KIT_REF={TAG}\n', f'KIT_REF={pin}\n'))
        commit(h)
        assert s14(doctor(h)) == ['  GAP  S14 ' + said('pre-push', pin)], pin
    write_lf(path, whole + '# changed\n')
    commit(h)
    assert [l for l in s14(doctor(h)) if 'pre-push is not the gate of this kit version' in l]


def test_sc007_the_fix_says_it_comes_from_the_manifest(p):
    """019/FR-005, SC-007."""
    write(p / 'docs' / 'old.md', 'notes\n')
    commit(p)
    (p / 'docs' / 'old.md').unlink()
    claude = p / 'CLAUDE.md'
    write(claude, claude.read_text(encoding='utf-8') + '\nThe old notes are in `docs/old.md`.\n')
    entry = {'rule': 'S18', 'reason': 'the notes moved', 'fix': 'rewrite the line exactly as the 16 already done',
             'names': ['docs/old.md']}
    data = manifest(p)
    data['projects'][0]['deviations'] = [entry]
    save(p, data)
    commit(p)
    lines = doctor(p).stdout.splitlines()
    debt = [i for i, l in enumerate(lines) if 'DEBT S18' in l]
    assert debt and lines[debt[0] + 1] == FIX + 'rewrite the line exactly as the 16 already done', lines
    assert not [l for l in lines if l.startswith('         fix: ')], lines

    entry['fix'] = ''
    save(p, data)
    commit(p)
    lines = doctor(p).stdout.splitlines()
    assert [l for l in lines if 'GAP  S01' in l and 'S18' in l and 'fix' in l], lines
    assert FIX + '(no fix written)' in lines, lines


def test_sc007_two_entries_print_their_fixes_in_order(tmp_path):
    """019/FR-005, SC-007, with 018's SC-004."""
    repo = debt_repo(tmp_path)
    add_entries(repo, S09_A, S09_B)
    lines = doctor(repo).stdout.splitlines()
    debt = [i for i, l in enumerate(lines) if 'DEBT S09' in l]
    assert debt, lines
    below = lines[debt[-1] + 1:]
    assert below.index(FIX + 'f1') < below.index(FIX + 'f2'), lines


def unreleased_up_to_a_release():
    """From `## Unreleased` down to 0.15.0, the last release without this feature: the line stands in that span
    before and after any number of later releases (a span counted in headings breaks at the second one)."""
    text = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
    return text[text.index('## Unreleased'):text.index('\n## 0.15.0')]


@pytest.mark.private
def test_sc008_the_changelog_says_all_three(tmp_path):
    """019/FR-006, SC-008."""
    lines = [l for l in unreleased_up_to_a_release().splitlines()
             if all(w in l for w in ('Approved', 'two-behaviour', 'no gate', 'S14', 'fix (from .claude/kit.yml)'))]
    assert len(lines) == 1, unreleased_up_to_a_release()


def test_sc009_write_spec_puts_the_split_to_the_owner():
    """019/FR-007, SC-009."""
    section = check_section()
    sentences = re.split(r'(?<=[.:])\s+', section)
    warning = next(i for i, s in enumerate(sentences) if 'two behaviours' in s)
    assert [s for s in sentences[warning + 1:] if 'Approved' in s and 'owner' in s], section
