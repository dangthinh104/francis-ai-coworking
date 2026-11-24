"""Spec 029: the doctor's summary line counts the notes it printed (FR-005, FR-006)."""
import re

from test_adoption_shapes import S09_A, S09_B, add_entries, debt_repo, lines_of, monorepo, PROVISIONAL
from test_kit_gate import commit, write
from test_map_has_one_pin import SUMMARY, fix, p              # noqa: F401 (p is a fixture)
from test_standard import DOCTOR, run

COUNT = re.compile(r', (\d+) notes?$')


def summary(result):
    found = [l for l in result.stdout.splitlines() if l.startswith('summary:')]
    assert len(found) == 1, result.stdout
    return found[0]


def split(line):
    """The summary up to `skipped`, and its note count (0 where it has none)."""
    m = COUNT.search(line)
    return (line[:m.start()], int(m.group(1))) if m else (line, 0)


def words_hold(line):
    """029/SC-007: `, 1 note` for one, `, <n> notes` for more, nothing for none."""
    head, n = split(line)
    assert head.endswith(' skipped'), line
    assert line == head + ('' if n == 0 else ', 1 note' if n == 1 else f', {n} notes'), line
    return n


def doctor(repo, *args):
    return run(DOCTOR, '--repo', repo, *args)


def test_sc008_the_ignored_project_root_note_is_counted(p):
    """029/FR-005, 029/SC-007, 029/SC-008."""
    plain, told = doctor(p), doctor(p, '--project-root', '.')
    assert 'note: --project-root is ignored because .claude/kit.yml lists the projects' in told.stderr
    (head0, n0), (head1, n1) = split(summary(plain)), split(summary(told))
    assert head1 == head0 and n1 == n0 + 1, (summary(plain), summary(told))
    words_hold(summary(plain)), words_hold(summary(told))


def test_sc010_the_s13_note_is_counted_and_no_note_prints_no_count(p):
    """029/FR-005, 029/FR-006, 029/SC-007, 029/SC-010, 023/FR-003 as modified."""
    plain = doctor(p)
    assert summary(plain) == SUMMARY, summary(plain)                 # FR-006: as today, byte for byte
    claude = p / 'CLAUDE.md'
    write(claude, '# note\n' + claude.read_text(encoding='utf-8'))
    commit(p)
    assert fix(p).returncode == 0
    commit(p)
    behind = doctor(p)
    assert [l for l in behind.stderr.splitlines() if l.startswith('note: S13:')], behind.stderr
    assert summary(behind) == SUMMARY + ', 1 note', summary(behind)


def test_sc011_a_fix_line_that_starts_with_note_is_not_counted(tmp_path):
    """029/SC-007, 029/SC-011: a note is what the doctor prints as one, not a line of the manifest."""
    counts = []
    for name, text in (('one', 'f1'), ('two', 'f1\nnote: not one of the doctor\'s')):
        (tmp_path / name).mkdir()
        repo = debt_repo(tmp_path / name)
        add_entries(repo, dict(S09_A, fix=text), S09_B)
        r = doctor(repo, '--all')
        assert [l for l in lines_of(r) if 'DEBT S09' in l], r.stdout
        counts.append(words_hold(summary(r)))
    assert 'note: not one of the doctor' in r.stdout
    assert counts[0] == counts[1], counts


def test_sc011_the_provisional_line_stays_under_the_summary(tmp_path):
    """029/SC-011, 018/FR-003: with no manifest the run prints a note, and `provisional:` is still the next line."""
    r = doctor(monorepo(tmp_path))
    lines = lines_of(r)
    at = lines.index(summary(r))
    assert lines[at + 1] == PROVISIONAL and words_hold(lines[at]) >= 1, lines
