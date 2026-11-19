"""024: only a line with a marker before the id declares it; a paragraph that starts with an id declares nothing."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / 'plugins' / 'francis-kit' / 'skills'
REFS = KIT / 'comment-discipline' / 'scripts' / 'spec_refs.py'
INDEX = KIT / 'kit-init' / 'scripts' / 'spec_index.py'
LINT = KIT / 'write-spec' / 'scripts' / 'spec_lint.py'
STANDARD = REPO / 'plugins' / 'francis-kit' / 'STANDARD.md'
CHANGELOG = REPO / 'CHANGELOG.md'
sys.path.insert(0, str(KIT / 'kit-init' / 'scripts'))
import kit_spec  # noqa: E402

# The reader before 024, copied so the comparison does not move with the code.
OLD_ID = r'(?:FR|SC)-[A-Z]?\d+(?:\.\d+)*'
OLD_DEFINITION = re.compile(
    rf'^[ \t]*(?:#+[ \t]*|[-*][ \t]+|\d+\.[ \t]+|\|[ \t]*)?\**[ \t]*({OLD_ID})(?![\w.-]*\d)', re.M)
# 024's "marker", read from its words: a list, heading or table marker, or `**` at the start of the line.
MARKED = re.compile(r'[ \t]*(?:(?:[-*][ \t]+|\d+\.[ \t]+|#{1,6}|\|)[ \t*]*|\*\*[ \t*]*)')


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', cwd=cwd)


def git(repo, *args):
    subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True, encoding='utf-8')


def write(repo, name, text):
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode('utf-8'))      # bytes: Windows text mode would turn \n into \r\n


@pytest.fixture
def recall(tmp_path):
    """The scratch repository of 024/SC-001: 012 recalls 011's FR-040 in a paragraph."""
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 'test@example.com')
    git(tmp_path, 'config', 'user.name', 'test')
    write(tmp_path, 'specs/011-a/spec.md', '# A\n\n**Status**: Draft\n\n### FR-040 — the queue holds 40 jobs\n')
    write(tmp_path, 'specs/012-b/spec.md', '# B\n\n**Status**: Draft\n\n- **FR-041**: The queue MUST hold more jobs.\n\n'
          'FR-040 set the queue to 40 jobs; this round goes further.\n')
    write(tmp_path, 'src/x.py', '# FR-040\n# Spec 011 (FR-034…FR-040) and spec 012 (FR-042…FR-044)\n')
    git(tmp_path, 'add', '-A')
    git(tmp_path, 'commit', '-q', '-m', 'scratch')
    return tmp_path


def test_sc001_a_recall_in_prose_makes_no_second_owner(recall):
    """024/SC-001, 024/FR-001"""
    r = run(REFS, '--repo', '.', '--root', '.', '--report', cwd=recall)
    first = r.stdout.splitlines()[0]
    assert 'against 2 requirement(s)' in first and 'unique=1' in first, r.stdout
    assert '  legacy    src/x.py:2  FR-040' in r.stdout.splitlines(), r.stdout
    assert 'contested src/' not in r.stdout and 'undefined src/x.py:2  FR-040' not in r.stdout


def test_sc002_the_index_counts_one_fr_each(recall):
    """024/SC-002, 024/FR-001"""
    assert run(INDEX, '--root', '.', cwd=recall).returncode == 0
    index = (recall / 'specs' / 'INDEX.md').read_text(encoding='utf-8')
    rows = {line.split('|')[1].strip(): line.split('|')[-2].strip() for line in index.splitlines() if '](01' in line}
    assert rows == {'[011-a](011-a/spec.md)': '1', '[012-b](012-b/spec.md)': '1'}, index


def test_sc003_a_fix_citing_a_recall_is_an_error(recall):
    """024/SC-003, 024/FR-001"""
    tasks = recall / 'specs' / '012-b' / 'tasks.md'
    write(recall, 'specs/012-b/tasks.md', '# Tasks\n\n## Fixes\n\n- [x] none: the queue was short, 012/FR-040\n')
    r = run(LINT, '--root', '.', '012-b', cwd=recall)
    assert r.returncode == 1, r.stdout
    assert any(l.startswith('ERROR 012-b: fix cites 012/FR-040, which no feature declares: ')
               for l in r.stdout.splitlines()), r.stdout
    tasks.write_bytes(b'# Tasks\n\n## Fixes\n\n- [x] none: the queue was short, 011/FR-040\n')
    r = run(LINT, '--root', '.', '012-b', cwd=recall)
    assert r.returncode == 0 and 'ERROR' not in r.stdout, r.stdout


FIXTURE = '\n'.join([
    '- **FR-001**: x', '- FR-002', '- **FR-003 (i18n)**: x', '- **SC-004** (US1): x', '### FR-005 — x',
    '#### FR-006 x', '| FR-007 | x |', '| **FR-008** | x |', '**FR-009.** x', '1. FR-010 x', '| **FR-011a** | x |',
    '- FR-012, FR-099 and SC-099 x', '### FR-013b — x', '', 'FR-014 recalls an earlier feature.', '  FR-015…FR-016.',
]) + '\n'


def test_sc004_every_marker_declares_and_no_bare_line_does():
    """024/SC-004, 024/FR-001, 024/FR-002"""
    wanted = {f'FR-{n:03d}' for n in [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13]} | {'SC-004'}
    assert kit_spec.requirements(FIXTURE) == wanted
    assert set(OLD_DEFINITION.findall(FIXTURE)) == wanted | {'FR-014', 'FR-015'}     # the reader before 024


def test_sc005_a_heading_with_no_separator_and_a_table_row_still_declare():
    """024/SC-005, 024/FR-002: the shapes of the fixtures in test_spec_refs.py."""
    assert kit_spec.requirements('# Login\n\n- **FR-001**: sign in\n### FR-010 unique here\n') == {'FR-001', 'FR-010'}
    assert kit_spec.requirements('# Billing\n\n| FR-001 | charge |\n- **SC-001**: fast\n') == {'FR-001', 'SC-001'}
    assert kit_spec.requirements('   FR-001 indented\nFR-002 at column 0\n') == set()


@pytest.mark.private
def test_sc005_no_spec_of_this_repository_loses_a_declaration():
    """024/FR-003, 024/SC-005: an id the old reader found is lost only where no line put a marker before it."""
    specs = [p for p in sorted((REPO / 'specs').glob('*/spec.md')) if re.fullmatch(r'\d{3}-.+', p.parent.name)]
    assert len(specs) > 10
    for path in specs:
        text = kit_spec.read(path)
        old_body = kit_spec.REMOVED.sub('', kit_spec.body(text))
        lost = set(OLD_DEFINITION.findall(old_body)) - kit_spec.requirements(text)
        for m in OLD_DEFINITION.finditer(old_body):
            if m.group(1) in lost:
                before = m.group(0)[:m.start(1) - m.start(0)]
                assert not MARKED.fullmatch(before), f'{path.parent.name} lost {m.group(1)}: {m.group(0)!r}'


def test_sc006_the_standard_says_what_declares():
    """024/SC-006, 024/FR-004"""
    r = subprocess.run(['git', 'grep', '-n', '-i', 'declares nothing', '--', 'plugins/francis-kit/STANDARD.md'],
                       cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    assert len(r.stdout.splitlines()) == 1, r.stdout
    line = r.stdout
    for marker in ('list', 'heading', 'table', '`**`'):
        assert marker in line, line


@pytest.mark.private
def test_sc006_the_changelog_names_what_goes_red():
    """024/SC-006, 024/FR-005"""
    changelog = CHANGELOG.read_text(encoding='utf-8')
    unreleased = changelog[changelog.index('## Unreleased'):changelog.index('\n## 0.16.1')]
    lines = [l for l in unreleased.splitlines() if 'no marker' in l]
    assert len(lines) == 1, unreleased
    for word in ('spec_index.py', 'dead', '## Fixes', 'INDEX.md', 'NNN/FR-001'):
        assert word in lines[0], lines[0]
