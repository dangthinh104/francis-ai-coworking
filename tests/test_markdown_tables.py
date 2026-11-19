"""Every table row of the kit's Markdown has as many cells as its header.

A `|` inside a code span still splits a GitHub table cell unless it is written `\\|`:
the S01 row of STANDARD.md was cut there on GitHub (found by an outside review, 2026-11-19).
"""
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit'
UNESCAPED = re.compile(r'(?<!\\)\|')


def rows_that_break():
    broken = []
    for path in sorted(PLUGIN.rglob('*.md')):
        header = None
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if not line.startswith('|'):
                header = None
                continue
            cells = len(UNESCAPED.findall(line))
            if header is None:
                header = cells
            elif cells != header:
                broken.append(f'{path.relative_to(PLUGIN).as_posix()}:{n}: {cells} pipes, header has {header}')
    return broken


def test_every_table_row_has_the_cells_of_its_header():
    assert rows_that_break() == []
