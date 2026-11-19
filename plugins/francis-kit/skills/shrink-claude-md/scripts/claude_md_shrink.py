#!/usr/bin/env python3
"""Cut a long CLAUDE.md down by a proposal its owner approved, and prove nothing was lost.

    claude_md_shrink.py start FILE [--out PROPOSAL]     write a first proposal, list the hazards
    claude_md_shrink.py show PROPOSAL [--file FILE]     check it and print it for the owner
    claude_md_shrink.py apply PROPOSAL [--file FILE]    move, write, then check the result
    claude_md_shrink.py verify PROPOSAL --original COPY [--file FILE]   the same check later, from a copy
    claude_md_shrink.py merged [--side REV --side REV] [--file FILE]    after a merge: what a side added and lost

Which block stays, moves or is history is decided by the session and the owner.
This script does the mechanics and refuses what must not happen. A proposal is JSON:

    {"file": "CLAUDE.md", "sha256": "<of the file when proposed, CRLF read as LF>",
     "hazards": [[first, last], ...], "hazards_confirmed": "<the owner's words, with the date>",
     "approved": "<the owner's words, with the date and the fingerprint `show` printed>",
     "blocks": [{"lines": [a, b], "verdict": "stays" | "moves" | "delete",
                 "to": "<path, for moves>", "pointer": "<one line left in its place>",
                 "why": "<for delete>"}]}

Lines are 1-based, inclusive, whole lines: a cut inside a line is not supported.
A line ends at a line feed and nowhere else. `file` is read from the directory of
the proposal, or `--file` names it instead: the CLAUDE.md in the repository when
the proposal was made on a copy. `to` is read from the repository (the nearest
directory above the file that holds `.git`, else the file's directory). Neither
path is in the fingerprint; the state of each target, read from there, is.

Refused, each with the block it is about: a non-blank line in no block or in two;
a verdict that is not one of the three; "moves" without a target, or to a target
outside the repository or that is not UTF-8; "delete" on a block that holds no
date or gives no `why`; a hazard line outside a block that stays (the lines of a
section whose heading holds the word Hazard or Hazards are hazards whatever the
proposal lists); no such section and `hazards_confirmed` empty; a file that
changed since the proposal was written.

`show` names each line that stays and points (see, above, below, this file,
section...) at the title of a block that moves or is deleted: a heading, or the
bold words a line opens with, cut at a bracket, a colon or a dash, two words at
least. It is reported for the owner to reword, never an error.

`show` prints a fingerprint of what the owner reads: the file, the blocks, the
hazards and each target (absent, or the sha256 of its text). `apply` writes nothing
unless the proposal is valid and `approved` holds that fingerprint, so a proposal
or a target changed after it was shown needs a new approval.
A moved block is appended to its target word for word, without the blank lines at
its two ends; the new file is the blocks that stay, plus the pointers, and blank
lines are collapsed only where a block was taken out. When anything fails, every
file is put back. Then the result is read from disk: every moved block in its
target, every line that stays in the new file, in order, every pointer, and no
other line: none more often than `apply` writes it (LOST and WRONG name each).

Exit codes. start: 0 written, 2 refused. show: 0 valid, 1 invalid, 2 the proposal
or the file cannot be read. apply and verify: 0 done and everything found, 1 a
moved block, a line that stays or a pointer is missing, or a line is there that
`apply` does not write, 2 refused, a write failed, or the file is gone.

`merged` (specs/022) judges the file after a merge of two sides, or after a finished
rebase with both sides named. A line one side added to it (git diff from the merge
base) that the result holds fewer times than that side does, allowing for what the
other side removed or added too, is printed as LOST with the side and its line
number. The result is the index of an unfinished merge, else the tree of HEAD,
across every tracked file. 0 nothing lost, 1 a LOST line, 2 nothing could be checked.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'kit-init' / 'scripts'))
import claude_md_audit  # noqa: E402
import kit_spec  # noqa: E402

VERDICTS = ('stays', 'moves', 'delete')
LIMIT = 150                                     # S02
DEFAULT_NAME = 'claude-md-shrink.json'
HEADING = re.compile(r'(#{1,6})[ \t]+(.*?)[ \t#]*$')
UNDERLINE = re.compile(r'={2,}|-{3,}')          # a setext heading: the paragraph above is its title
NOT_PARAGRAPH = re.compile(r' {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)| {0,3}>|(?: {4}| {0,3}\t)')
HAZARD_TITLES = {'hazard', 'hazards'}
LEAD = re.compile(r'[ \t>]*(?:[-*+][ \t]+)?\*\*(.+?)\*\*')      # a line that opens with bold words
POINTS = re.compile(r'\b(?:see|above|below|this file|section|top of|bottom of|refer to)\b', re.I)
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
# Candidates only: money, data that cannot be recomputed, production, what cannot be undone.
HAZARD_WORDS = re.compile(
    r'\b(?:money|payments?|billing|invoices?|refunds?|production|prod|live data|irreversibl[ey]|destructive|'
    r'cannot be (?:undone|recomputed|recovered|restored)|drop (?:table|database)|truncate|force[- ]push|rm -rf|'
    r'tiền|thanh toán|hoàn tiền|không thể (?:hoàn tác|khôi phục|tính lại)|xóa|xoá|dữ liệu thật|mất dữ liệu)\b', re.I)
# A date, strictly: a number that merely has the shape of one makes no block history.
YEAR = r'(?:199\d|20\d\d)'
DAY = r'(?:0?[1-9]|[12]\d|3[01])'
MON = r'(?:0?[1-9]|1[0-2])'
_MONTHS = ('January February March April May June July August September October November December '
           'Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec').split()
MONTH = '(?:' + '|'.join(sorted({form for name in _MONTHS for form in (name, name.upper())}, key=len, reverse=True)) + ')'
DATE = re.compile(
    rf'(?<![\d-]){YEAR}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?![\d-])'          # 2026-11-12
    rf'|(?<![\d/])(?:{DAY}/{MON}|{MON}/{DAY})/{YEAR}(?![\d/])'                         # 12/11/2026
    rf'|(?<![\d/]){MON}/{YEAR}(?![\d/])'                                               # 11/2026
    rf'|\b{MONTH}\b\.?,?[ \t]+(?:\d{{1,2}}(?:st|nd|rd|th)?,?[ \t]+)?{YEAR}\b'          # Nov 12, 2026
    rf'|\b{YEAR},?[ \t]+{MONTH}\b'                                                     # 2026 November
    rf'|(?i:tháng)[ \t]+{MON}[ \t]+(?i:năm)[ \t]+{YEAR}\b')                            # tháng 11 năm 2026


class Unusable(Exception):
    """The proposal or the file cannot be read: nothing was judged."""


def raw_lines(text):
    """(lines, whether the last one ends). Cut at line feeds only; a line keeps its `\\r`."""
    parts = text.split('\n')
    ended = parts[-1] == ''
    if ended:
        parts.pop()
    return parts, ended


def clean(line):
    return line[:-1] if line.endswith('\r') else line


def lines_of(text):
    return [clean(line) for line in raw_lines(text)[0]]


def blank(line):
    return not line.strip(' \t\r')


def sha256(raw):
    """Of the bytes with CRLF read as LF: a checkout with core.autocrlf=true is the same text, an LF file the same hash."""
    return hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()


class Source:
    """The file a proposal is about: its bytes, its lines, how its lines end."""

    def __init__(self, path, label):
        try:
            self.raw = path.read_bytes()
        except OSError as exc:
            raise Unusable(f'{label} cannot be read: {type(exc).__name__}: {exc.strerror or exc}')
        self.bom = b'\xef\xbb\xbf' if self.raw.startswith(b'\xef\xbb\xbf') else b''
        try:
            self.text = self.raw[len(self.bom):].decode('utf-8')
        except UnicodeDecodeError as exc:
            raise Unusable(f'{label} is not UTF-8: {exc}')
        self.exact, self.ended = raw_lines(self.text)       # as they are written back
        self.lines = [clean(line) for line in self.exact]   # as they are read and compared
        self.newline = '\r\n' if '\r\n' in self.text else '\n'
        self.sha = sha256(self.raw)


def tokens(text):
    return claude_md_audit.size(text.replace('\r\n', '\n'))[1]


def fenced(lines):
    """For each line, whether it is inside a code block or the front matter."""
    inside, fence, out, start = False, '', [], 0
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() in ('---', '...')), None)
        if end is not None:
            out, start = [True] * (end + 1), end + 1
    for line in lines[start:]:
        token = line.strip()
        if not inside:
            m = re.match(r'(`{3,}|~{3,})', token)
            inside, fence = bool(m), m.group(1) if m else ''
            out.append(inside)
        else:
            out.append(True)
            if token.startswith(fence) and not token.strip('`~'):
                inside = False
    return out


def headings(lines):
    """[(index, level, title)] for the headings outside code blocks, `#` and underlined."""
    code = fenced(lines)
    found = []
    for i, line in enumerate(lines):
        if code[i]:
            continue
        m = HEADING.fullmatch(line.strip())
        if m:
            found.append((i, len(m.group(1)), m.group(2)))
        elif UNDERLINE.fullmatch(line.strip()):
            start = paragraph(lines, code, i)
            if start is not None:
                found.append((start, 1 if line.strip()[0] == '=' else 2, ' '.join(l.strip() for l in lines[start:i])))
    return found


def paragraph(lines, code, i):
    """Where the paragraph an underline at `i` makes a heading of starts, or None (CommonMark).

    The lines above it, up to a blank line, a heading, code or another underline, are
    one paragraph only when the first is not a list item, a quote or indented code:
    under those, `---` is a thematic break and `===` is text.
    """
    start = i
    while (start and not code[start - 1] and not blank(lines[start - 1])
           and not HEADING.fullmatch(lines[start - 1].strip()) and not UNDERLINE.fullmatch(lines[start - 1].strip())):
        start -= 1
    if start == i or NOT_PARAGRAPH.match(lines[start]):
        return None
    return start


def hazard_sections(lines):
    """[[first, last]], 1-based, for each section whose heading holds the word Hazard or Hazards."""
    heads, out = headings(lines), []
    for n, (i, level, title) in enumerate(heads):
        if not HAZARD_TITLES & {word.casefold() for word in re.findall(r'[^\W\d_]+', title)}:
            continue
        end = next((j for j, other, _ in heads[n + 1:] if other <= level), len(lines))
        while end > i + 1 and blank(lines[end - 1]):
            end -= 1
        out.append([i + 1, end])
    return out


def candidates(lines):
    return [i + 1 for i, line in enumerate(lines) if HAZARD_WORDS.search(line)]


def first_cut(lines):
    """One block per heading section, cut again at blank lines; a code block is never cut."""
    code = fenced(lines)
    heads = {i for i, _, _ in headings(lines)}
    blocks, start = [], None
    for i, line in enumerate(lines):
        empty = blank(line) and not code[i]
        if start is not None and (empty or i in heads):
            blocks.append([start + 1, i])
            start = None
        if start is None and not empty:
            start = i
    if start is not None:
        blocks.append([start + 1, len(lines)])
    return blocks


def repository(file):
    for directory in [file.parent, *file.parent.parents]:
        if os.path.lexists(directory / '.git'):
            return directory
    return file.parent


def text_in(value):
    """Whether a field holds words: a string that is not only spaces."""
    return isinstance(value, str) and bool(value.strip())


def load(proposal_path, named=None):
    """(proposal, the path of its file), or Unusable. `named` (--file) is read in place of the `file` it records."""
    try:
        data = json.loads(proposal_path.read_text(encoding='utf-8-sig'))
    except OSError as exc:
        raise Unusable(f'{proposal_path} cannot be read: {type(exc).__name__}: {exc.strerror or exc}')
    except ValueError as exc:
        raise Unusable(f'{proposal_path} is not JSON: {exc}')
    if not isinstance(data, dict) or not isinstance(data.get('blocks'), list):
        raise Unusable(f'{proposal_path} is not a proposal: an object with a list of `blocks` is expected')
    if named is not None:
        data['file'] = str(named)               # only the messages read it; the fingerprint does not
        return data, named.resolve()
    if not text_in(data.get('file')) or CONTROL.search(data['file']):
        raise Unusable(f'{proposal_path} names no `file`')
    return data, (proposal_path.resolve().parent / data['file']).resolve()


def targets(blocks):
    """{target from the repository root: 'absent' or the sha256 of its text}, for the blocks that move."""
    return {b.shown: sha256(b.target.read_bytes()) if b.target.is_file() else 'absent'
            for b in blocks if b.verdict == 'moves' and b.target is not None}


def state(value):
    return 'will be created' if value == 'absent' else f'appended to; sha256 {value[:12]}'


def fingerprint(data, held):
    """Twelve hex characters that change when what the owner was shown changes, the targets as they were included.

    `version` and `targets` are always there, so an approval of a fingerprint made
    before the targets were in it names no fingerprint made now.
    """
    blocks = [{key: block.get(key) for key in ('lines', 'verdict', 'to', 'pointer')} if isinstance(block, dict) else block
              for block in data['blocks']]
    shown = {'version': 2, 'sha256': data.get('sha256'), 'blocks': blocks, 'hazards': data.get('hazards', []),
             'targets': held}
    return hashlib.sha256(json.dumps(shown, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()[:12]


def created_since(data, held, approved):
    """The targets that exist now and were absent when the approved fingerprint was shown."""
    there = [path for path, value in held.items() if value != 'absent']
    for guess in [[path] for path in there] + ([there] if len(there) > 1 else []):
        if fingerprint(data, {**held, **{path: 'absent' for path in guess}}) in approved:
            return guess
    return []


class Block:
    def __init__(self, number, entry, lines):
        self.number = number
        self.first, self.last = entry['lines']
        self.verdict = entry.get('verdict')
        self.to = entry.get('to')
        self.pointer = entry.get('pointer')
        self.why = entry.get('why')
        self.target = None                      # resolved path, for a valid move
        self.shown = ''                         # the target from the repository root
        # Where its text starts and ends: the blank lines at its two ends are not its text.
        held = [n for n in range(self.first, min(self.last, len(lines)) + 1) if not blank(lines[n - 1])]
        self.top, self.bottom = (held[0], held[-1]) if held else (None, None)

    @property
    def name(self):
        return f'block {self.number} (lines {self.first}-{self.last})'

    def text(self, lines):
        return lines[self.top - 1:self.bottom] if self.top else []

    def leaves(self):
        """The lines taken out of the file, or None for a block that stays."""
        return None if self.verdict == 'stays' else (self.top, self.bottom)


def a_range(value, most=None):
    return (isinstance(value, list) and len(value) == 2 and all(type(n) is int for n in value)
            and 1 <= value[0] <= value[1] and (most is None or value[1] <= most))


def check(data, source, file, proposal_path=None):
    """(errors, blocks, hazard line numbers). Blocks that could not be read are left out."""
    lines, errors, blocks = source.lines, [], []
    if data.get('sha256') != source.sha:
        return [f'{file.name} has changed since the proposal was written (its sha256 is not the proposal\'s): '
                f'write the proposal again from the file as it is now'], [], []
    root = repository(file)
    for number, entry in enumerate(data['blocks'], 1):
        if not isinstance(entry, dict):
            errors.append(f'block {number}: not an object with `lines` and `verdict`')
            continue
        if not a_range(entry.get('lines')):
            errors.append(f'block {number}: `lines` is not [first, last] with 1 <= first <= last')
            continue
        block = Block(number, entry, lines)
        if block.last > len(lines):
            errors.append(f'{block.name}: the file has {len(lines)} lines')
            continue
        blocks.append(block)
        if block.pointer is not None and not isinstance(block.pointer, str):
            errors.append(f'{block.name}: the pointer is not text')
            block.pointer = None
        elif block.pointer and re.search(r'[\r\n]', block.pointer):
            errors.append(f'{block.name}: the pointer is more than one line')
        if block.verdict is None:
            errors.append(f'{block.name}: no verdict yet')
        elif not isinstance(block.verdict, str) or block.verdict not in VERDICTS:
            errors.append(f'{block.name}: the verdict is {json.dumps(block.verdict)}, not one of '
                          '"stays", "moves", "delete"')
        elif block.verdict == 'moves':
            errors.extend(f'{block.name}: {why}' for why in check_move(block, root, file, proposal_path))
        elif block.verdict == 'delete':
            if not DATE.search('\n'.join(block.text(lines))):
                errors.append(f'{block.name}: "delete" on a block that holds no date: history is what was done '
                              'or decided on a date')
            if not text_in(block.why):
                errors.append(f'{block.name}: "delete" without `why`')
    owner = {}
    for block in blocks:
        for n in range(block.first, block.last + 1):
            if blank(lines[n - 1]):
                continue
            if n in owner:
                errors.append(f'line {n} is in {owner[n].name} and in {block.name}')
            else:
                owner[n] = block
    errors.extend(f'line {n} is in no block: {line.strip()[:60]}'
                  for n, line in enumerate(lines, 1) if not blank(line) and n not in owner)

    sections = hazard_sections(lines)
    listed = data.get('hazards', [])
    if not isinstance(listed, list) or not all(a_range(r, len(lines)) for r in listed):
        errors.append('`hazards` is not a list of [first, last] ranges of lines of the file')
        listed = []
    if not sections and not text_in(data.get('hazards_confirmed')):
        errors.append('the file has no Hazards section and `hazards_confirmed` is empty: the owner confirms the '
                      'list of hazards before the proposal is written')
    hazards = sorted({n for first, last in sections + listed for n in range(first, last + 1) if not blank(lines[n - 1])})
    for n in hazards:
        block = owner.get(n)
        if block is not None and block.verdict != 'stays':
            errors.append(f'{block.name}: hazard line {n} is not in a block that stays')
    return errors, blocks, hazards


def check_move(block, root, file, proposal_path):
    if not text_in(block.to):
        return ['"moves" names no target (`to`)']
    if CONTROL.search(block.to):
        return ['the target holds a control character']
    try:
        target, home = (root / block.to).resolve(), root.resolve()
    except (OSError, ValueError) as exc:
        return [f'the target {block.to} cannot be a path: {exc}']
    if home != target and home not in target.parents:
        return [f'the target {block.to} is outside the repository']
    if target == file:
        return ['the target is the file itself']
    inside = target.relative_to(home)
    if any(part.lower() == '.git' for part in inside.parts) or (proposal_path and target == proposal_path.resolve()):
        return [f'the target {block.to} is not a file a block can move to']
    if target.is_dir():
        return [f'the target {block.to} is a directory']
    if target.is_file():
        try:
            target.read_bytes().decode('utf-8-sig')
        except UnicodeDecodeError:
            return [f'the target {block.to} is not UTF-8: the block cannot be appended to it']
        except OSError as exc:
            return [f'the target {block.to} cannot be read: {exc.strerror or exc}']
    if block.top is None:
        return ['"moves" on a block that holds no text']
    block.target, block.shown = target, inside.as_posix()
    return []


def new_text(source, blocks):
    """The file after: every line that was not taken out, as it was, and the pointers.

    Blank lines are touched only where a block was taken out: those on both sides of
    the gap become one, and none is left at the start or the end of the file.
    """
    gone = {}
    for block in blocks:
        if block.leaves() and block.top:
            for n in range(block.top, block.bottom + 1):
                gone.setdefault(n, block)
    cr = '\r' if source.newline == '\r\n' else ''
    out, seam, gap, last_kept = [], False, False, False

    def emit(line):
        nonlocal seam, gap
        if seam and gap and out:
            out.append(cr)
        seam = gap = False
        out.append(line)

    for n, line in enumerate(source.exact, 1):
        block = gone.get(n)
        last_kept = block is None
        if block is None:
            if seam and blank(line):
                gap = True
            else:
                emit(line)
        elif n == block.top and block.verdict == 'moves' and text_in(block.pointer):
            emit(block.pointer + cr)
        elif not seam:
            seam = True
            while out and blank(out[-1]):
                out.pop()
                gap = True
    if not out:
        return ''
    return '\n'.join(out) + ('\n' if source.ended or not last_kept or seam else '')


def moves(lines, blocks):
    """{target: [(block, its lines)]}, targets and blocks in file order."""
    out = {}
    for block in sorted((b for b in blocks if b.verdict == 'moves'), key=lambda b: b.first):
        out.setdefault(block.target, []).append((block, block.text(lines)))
    return out


def size_lines(source, after, blocks):
    """The sizes before and after; the count after is the file `apply` writes, its pointers included."""
    written = raw_lines(after)[0]
    pointers = sum(b.verdict == 'moves' and b.top is not None and text_in(b.pointer) for b in blocks)
    empty = sum(blank(line) for line in written)
    return [f'before: {len(source.lines)} lines, about {tokens(source.text)} tokens (characters / 4, an estimate)',
            f'after:  {len(written)} lines, about {tokens(after)} tokens ({len(written) - pointers - empty} that stay, '
            f'{pointers} pointer{"" if pointers == 1 else "s"}, {empty} blank)'], len(written)


def title(text):
    """The name a reader would point at: up to the first bracket, colon or dash; two words at least."""
    text = re.sub(r'^\W+', '', re.sub(r'[`*_]', '', text))
    text = re.split(r'\s*(?:\(|:|—|–|\s-\s|\.\s|\.$)', text, maxsplit=1)[0].strip()
    return text if len(text.split()) >= 2 else None


def dangling(lines, blocks):
    """Lines that stay and point at the title of a block that leaves: for the owner to reword. Reported only."""
    code, leaving = fenced(lines), []
    for block in blocks:
        if block.verdict not in ('moves', 'delete') or block.top is None:
            continue
        names = [t for i, _, t in headings(lines) if block.top - 1 <= i < block.bottom]
        names += [m.group(1) for n in range(block.top, block.bottom + 1) if not code[n - 1]
                  for m in [LEAD.match(lines[n - 1])] if m]
        names = [t for t in dict.fromkeys(title(name) for name in names) if t]
        if names:
            leaving.append((block, names))
    out = []
    for block in (b for b in blocks if b.verdict == 'stays'):
        for n in range(block.first, block.last + 1):
            line = lines[n - 1]
            if code[n - 1] or not POINTS.search(line):
                continue
            for other, names in leaving:
                said = next((t for t in names if re.search(rf'(?<!\w){re.escape(t.casefold())}(?!\w)', line.casefold())),
                            None)
                if said:
                    where = f'moves to {other.to}' if other.verdict == 'moves' else 'is deleted'
                    out.append(f'line {n} stays and points at "{said}" of {other.name}, which {where}: {line.strip()}')
    return out


def report(data, source, file, blocks, hazards, errors):
    lines = source.lines
    print(f'{file.name}: {len(blocks)} block(s)')
    print(f'{"#":>3}  {"lines":<9}  {"verdict":<7}  first words')
    for block in blocks:
        first = next((l.strip() for l in block.text(lines)), '')
        verdict = block.verdict if isinstance(block.verdict, str) else '-'
        print(f'{block.number:>3}  {f"{block.first}-{block.last}":<9}  {verdict:<7}  {first[:60]}')
        if block.verdict == 'moves' and block.target is not None:
            print(f'       to {block.shown} ({state(targets([block])[block.shown])})')
            if text_in(block.pointer):
                print(f'       left in its place: {block.pointer}')
        elif block.verdict == 'delete' and isinstance(block.why, str):
            print(f'       history: {block.why}')
    print()
    confirmed = data.get('hazards_confirmed')
    if hazard_sections(lines):
        print(f'hazards: {len(hazards)} line(s), the Hazards section included; all must stay')
    else:
        print(f'hazards: {len(hazards)} line(s), confirmed by the owner: {confirmed if text_in(confirmed) else "not yet"}')
    pointing = dangling(lines, blocks)
    print(f'lines that stay and point at text that leaves: {len(pointing) or "none"}'
          + (' (for the owner to reword; nothing here is changed)' if pointing else ''))
    for said in pointing:
        print(f'  {said}')
    approved = data.get('approved')
    if errors:
        return
    sizes, after = size_lines(source, new_text(source, blocks), blocks)
    print('\n'.join(sizes))
    if after > LIMIT:
        print(f'note: {after} lines is still over the {LIMIT} of S02')
    mark = fingerprint(data, targets(blocks))
    print(f'fingerprint: {mark}')
    if not text_in(approved):
        print(f'approved: not yet; apply will refuse until `approved` holds the owner\'s words and {mark}')
    elif mark not in approved:
        print(f'approved: {approved}\n          does not name this fingerprint: the proposal changed since it was '
              'approved, and apply will refuse')
    else:
        print(f'approved: {approved}')


def cmd_start(args):
    file = args.file.resolve()
    out = (args.out or file.parent / DEFAULT_NAME).resolve()
    if os.path.lexists(out):
        print(f'{out} already exists: it is not overwritten. Name another with --out, or remove it', file=sys.stderr)
        return 2
    source = Source(file, str(args.file))
    lines = source.lines
    blocks, sections = first_cut(lines), hazard_sections(lines)
    try:
        named = Path(os.path.relpath(file, out.parent)).as_posix()
    except ValueError:                           # another drive
        named = file.as_posix()
    body = ['{', f'  "file": {json.dumps(named, ensure_ascii=False)},', f'  "sha256": "{source.sha}",',
            f'  "hazards": {json.dumps(sections)},', '  "hazards_confirmed": "",', '  "approved": "",', '  "blocks": [',
            ',\n'.join(f'    {{"lines": [{a}, {b}], "verdict": null}}' for a, b in blocks), '  ]', '}']
    out.parent.mkdir(parents=True, exist_ok=True)
    kit_spec.replace(out, ('\n'.join(body) + '\n').encode('utf-8'))
    print(f'{args.file}: {len(lines)} lines, about {tokens(source.text)} tokens (characters / 4, an estimate), '
          f'{len(blocks)} blocks')
    print(f'proposal written: {out}')
    if sections:
        print('Hazards section: these lines are what the owner marked, and they stay')
        listed = [n for first, last in sections for n in range(first, last + 1)]
    else:
        listed = candidates(lines)
        print(f'no Hazards section: {len(listed)} candidates for the owner to confirm, add to or strike '
              '(lines about money, data that cannot be recomputed, production, irreversible actions)')
    for n in listed:
        if not blank(lines[n - 1]):
            print(f'  {n}: {lines[n - 1].strip()}')
    return 0


def judged(args):
    """Everything `show` and `apply` start from."""
    data, file = load(args.proposal, args.file)
    source = Source(file, data['file'])
    errors, blocks, hazards = check(data, source, file, args.proposal)
    return data, file, source, errors, blocks, hazards


def cmd_show(args):
    data, file, source, errors, blocks, hazards = judged(args)
    report(data, source, file, blocks, hazards, errors)
    if errors:
        print(f'\n{len(errors)} error(s): the proposal cannot be applied')
        for error in errors:
            print(f'  {error}')
    return 1 if errors else 0


def found(needle, haystack):
    """Whether the lines `needle` stand in a row, each a whole line, among the lines `haystack`."""
    return '\n' + '\n'.join(needle) + '\n' in '\n' + '\n'.join(haystack) + '\n'


def read_text(path):
    try:
        return path.read_bytes().decode('utf-8-sig', errors='replace')
    except OSError:
        return None


def lost(data, source, file, blocks, hazards):
    """(what is wrong with the result, lines that stay and were found). Read from the files on disk.

    Each message opens with LOST (a moved block, a line that stays or a pointer is
    not there) or WRONG (a line is there that `apply` did not write).
    """
    out, lines = [], source.lines
    for target, parts in moves(lines, blocks).items():
        text = read_text(target)
        for block, body in parts:
            if text is None or not found(body, lines_of(text)):
                out.append(f'LOST  {block.name} is not found word for word in {block.to}')
    text = read_text(file)
    if text is None:
        raise Unusable(f'{data["file"]} is missing or cannot be read: nothing was checked')
    have, at, kept, marked = lines_of(text), 0, 0, set(hazards)
    for block in sorted((b for b in blocks if b.verdict == 'stays'), key=lambda b: b.first):
        for n in range(block.first, block.last + 1):
            line = lines[n - 1]
            if blank(line):
                continue
            try:
                at = have.index(line, at) + 1
                kept += 1
            except ValueError:
                out.append(f'LOST  hazard line {n} is not in {data["file"]}: {line.strip()}' if n in marked else
                           f'LOST  line {n} of {block.name}, which stays, is not in {data["file"]} in its place: '
                           f'{line.strip()}')
    return out + surplus(data, source, blocks, hazards, have), kept


def surplus(data, source, blocks, hazards, have):
    """A pointer that is gone, and every line the new file holds more often than `apply` writes it."""
    lines, name, out = source.lines, data['file'], []
    wrote = Counter(line for line in lines_of(new_text(source, blocks)) if not blank(line))
    held = Counter(line for line in have if not blank(line))
    pointers = sorted((b for b in blocks if b.verdict == 'moves' and b.top and text_in(b.pointer)), key=lambda b: b.first)
    for block in pointers:
        if held[block.pointer] < wrote[block.pointer]:
            out.append(f'LOST  the pointer of {block.name} is not in {name}: {block.pointer.strip()}')
    whose = {}                                   # a text, and the first line of the original that holds it
    for block in sorted(blocks, key=lambda b: (b.verdict != 'stays', b.first)):
        for n in range(block.first, block.last + 1):
            if not blank(lines[n - 1]):
                whose.setdefault(lines[n - 1], (n, block))
    hazard = {lines[n - 1]: n for n in sorted(hazards, reverse=True)}
    leaving = {}
    for k, line in enumerate(have, 1):
        extra = held[line] - wrote[line]
        if blank(line) or extra <= 0 or line in leaving:
            continue
        n, block = whose.get(line, (None, None))
        pointer = next((b for b in pointers if b.pointer == line), None)
        if pointer is not None and block is None:
            out.append(f'WRONG  the pointer of {pointer.name} is in {name} {held[line]} times: {line.strip()}')
        elif line in hazard:
            out.append(f'WRONG  hazard line {hazard[line]} is in {name} {held[line]} times: {line.strip()}')
        elif block is not None and block.verdict == 'stays':
            out.append(f'WRONG  line {n} of {block.name}, which stays, is in {name} {held[line]} times: {line.strip()}')
        elif block is not None:
            where = f'moves to {block.to}' if block.verdict == 'moves' else 'is deleted'
            if block not in leaving.values():
                out.append(f'WRONG  {block.name}, which {where}, is still in {name}: {line.strip()}')
        else:
            out.append(f'WRONG  line {k} of {name} is neither a line that stays, nor a pointer, nor blank: '
                       f'{line.strip()}')
            continue
        leaving[line] = block
    return out


def verdict(data, source, file, blocks, hazards):
    missing, kept = lost(data, source, file, blocks, hazards)
    for message in missing:
        print(message)
    if not missing:
        print(f'{sum(b.verdict == "moves" for b in blocks)} moved block(s) found word for word, '
              f'{len(hazards)} hazard line(s) kept, {kept} line(s) that stay found in order')
    return 1 if missing else 0


def put_back(written, made):
    failed = []
    for path, old in reversed(written):
        try:
            if old is None:
                path.unlink()
            else:
                kit_spec.replace(path, old)
        except Exception as exc:                 # whatever stopped one file, the others are still put back
            failed.append(f'{path}: {type(exc).__name__}: {exc}')
    for directory in reversed(made):
        try:
            directory.rmdir()
        except OSError:
            pass
    return failed


def cmd_apply(args):
    data, file, source, errors, blocks, hazards = judged(args)
    if errors:
        for error in errors:
            print(error)
        print(f'{len(errors)} error(s) in the proposal: nothing was written', file=sys.stderr)
        return 2
    held = targets(blocks)
    approved, mark = data.get('approved'), fingerprint(data, held)
    if not text_in(approved):
        print('the proposal is not approved: `approved` holds the owner\'s words, and it is empty. '
              'nothing was written', file=sys.stderr)
        return 2
    if mark not in approved:
        for path in created_since(data, held, approved):
            print(f'{path} was created after `show`, which said it will be created: it is not what was approved',
                  file=sys.stderr)
        print(f'the approval does not name the proposal as it is now: `approved` must hold the fingerprint {mark} '
              'that `show` prints. A proposal, or a target, changed after it was shown is shown again and approved '
              'again. The targets now: ' + ('; '.join(f'{path} ({state(value)})' for path, value in held.items()) or 'none')
              + '. nothing was written', file=sys.stderr)
        return 2
    root = repository(file).resolve()
    after = new_text(source, blocks)
    written, made, notes = [], [], []
    path = file
    try:
        for path, parts in moves(source.lines, blocks).items():
            old = path.read_bytes() if path.is_file() else None
            newline = source.newline if not old else ('\r\n' if b'\r\n' in old else '\n')
            body = (newline + newline).join(newline.join(lines) for _, lines in parts) + newline
            if old:
                body = ('' if old.endswith(b'\n') else newline) + newline + body
            missing = [d for d in [path.parent, *path.parent.parents] if not d.exists()]
            for directory in reversed(missing):
                directory.mkdir()
                made.append(directory)
            kit_spec.replace(path, (old or b'') + body.encode('utf-8'))     # all or nothing, so listed only once done
            written.append((path, old))
            notes.append(f'{path.relative_to(root).as_posix()} ({"created" if old is None else "appended"})')
        path = file
        kit_spec.replace(file, source.bom + after.encode('utf-8'))
    except Exception as exc:                     # any failure, not only of the disk: nothing stays half done
        failed = put_back(written, made)
        label = path.relative_to(root).as_posix() if root in path.parents else str(path)
        reason = getattr(exc, 'strerror', None) or str(exc)
        print(f'{label} could not be written: {type(exc).__name__}: {reason}. '
              + ('Every file already written was put back; nothing is changed' if not failed else
                 'Could not be put back: ' + '; '.join(failed)), file=sys.stderr)
        return 2
    sizes, _ = size_lines(source, after, blocks)
    print('\n'.join(sizes))
    print('written:')
    for note in [file.relative_to(root).as_posix(), *notes]:
        print(f'  {note}')
    return verdict(data, source, file, blocks, hazards)


def cmd_verify(args):
    data, file = load(args.proposal, args.file)
    source = Source(args.original, str(args.original))
    if data.get('sha256') != source.sha:
        raise Unusable(f'{args.original} is not the file the proposal was written for: its sha256 is not the proposal\'s')
    errors, blocks, hazards = check(data, source, file, args.proposal)
    if errors:
        for error in errors:
            print(error)
        raise Unusable(f'{len(errors)} error(s) in the proposal: nothing was checked')
    return verdict(data, source, file, blocks, hazards)


def git_out(root, *args):
    """stdout of a git command as bytes, or None when it fails."""
    r = subprocess.run(['git', '-C', str(root), *args], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def git_line(root, *args):
    out = git_out(root, *args)
    return out.decode('utf-8', 'replace').strip() if out is not None else None


def count(root, entries, wanted):
    """count(T, L) for each L in `wanted`, across the (mode, oid) entries that are regular files and UTF-8 text.
    One blob is held at a time, and only the wanted lines are counted."""
    counts = Counter()
    oids = [oid for mode, oid in entries if mode in ('100644', '100755')]
    if not oids or not wanted:
        return counts
    batch = subprocess.Popen(['git', '-C', str(root), 'cat-file', '--batch'], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE)
    try:
        for oid in oids:                         # without --buffer, git answers each object before the next is asked
            batch.stdin.write(oid.encode() + b'\n')
            batch.stdin.flush()
            size = int(batch.stdout.readline().split()[2])
            body = batch.stdout.read(size)
            batch.stdout.read(1)
            try:
                text = body.decode('utf-8-sig')
            except UnicodeDecodeError:
                continue
            counts.update(line for line in lines_of(text) if line in wanted)
    finally:
        batch.stdin.close()
        batch.wait()
    return counts


def entries_of(root, ref):
    """(mode, oid) of every file git tracks in the tree of `ref`, or, with None, at stage 0 of the index."""
    if ref is None:
        rows = [row.split(b'\t')[0].decode().split() for row in git_out(root, 'ls-files', '-s', '-z').split(b'\0') if row]
        return [(mode, oid) for mode, oid, stage in rows if stage == '0']
    rows = [row.split(b'\t')[0].decode().split() for row in git_out(root, 'ls-tree', '-r', '-z', ref).split(b'\0') if row]
    return [(mode, oid) for mode, _, oid in rows]


HUNK = re.compile(rb'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', re.M)


def added(root, base, side, path):
    """The line numbers of the file at `side` that git diff adds against `base`, whatever the user's diff
    configuration or .gitattributes say."""
    out = git_out(root, 'diff', '--no-ext-diff', '--no-textconv', '--no-color', '--text', '-U0',
                  '--inter-hunk-context=0', base, side, '--', f':(literal){path}')
    if out is None:
        raise Unusable(f'git diff {base} {side} -- {path} failed: nothing was checked')
    return [n for m in HUNK.finditer(out) for n in range(int(m.group(1)), int(m.group(1)) + int(m.group(2) or 1))]


def cmd_merged(args):
    root = git_line('.', 'rev-parse', '--show-toplevel')
    if not root:
        raise Unusable('not a git repository: nothing was checked')
    root = Path(root)
    if any(os.path.exists(Path(root, git_line(root, 'rev-parse', '--git-path', name))) for name in ('rebase-merge', 'rebase-apply')):
        raise Unusable('a rebase is in progress: finish it, then run merged with --side ORIG_HEAD --side <upstream>')
    try:
        path = Path(os.path.relpath((args.file or root / 'CLAUDE.md').resolve(), root.resolve())).as_posix()
    except ValueError:
        raise Unusable(f'{args.file} is not in the repository at {root}: nothing was checked')
    merge_head = Path(root, git_line(root, 'rev-parse', '--git-path', 'MERGE_HEAD'))
    merging = merge_head.is_file()
    heads = merge_head.read_text(encoding='utf-8').split() if merging else []
    if len(heads) > 1:
        raise Unusable(f'MERGE_HEAD names {len(heads)} commits: only a merge of two can be checked')
    parents = (git_line(root, 'rev-list', '--parents', '-n1', 'HEAD') or '').split()[1:]
    if len(parents) > 2:
        raise Unusable(f'HEAD is a merge of {len(parents)} parents: only a merge of two can be checked')
    if args.side:
        if len(args.side) != 2:
            raise Unusable(f'--side is given {len(args.side)} time(s): name both sides, or none')
        sides = args.side
    elif merging:
        sides = ['HEAD', 'MERGE_HEAD']
    elif len(parents) == 2:
        sides = ['HEAD^1', 'HEAD^2']
    else:
        raise Unusable('no merge to check: HEAD is not a merge and none is in progress. '
                       'After a rebase, name both sides: --side ORIG_HEAD --side <upstream>')
    revs = []
    for side in sides:
        rev = git_line(root, 'rev-parse', '-q', '--verify', f'{side}^{{commit}}')
        if not rev:
            raise Unusable(f'{side} cannot be read as a commit: nothing was checked')
        revs.append(rev)
    bases = (git_line(root, 'merge-base', '--all', *revs) or '').split()
    if len(bases) != 1:
        raise Unusable(f'{sides[0]} and {sides[1]} have {len(bases)} merge bases: only one can be checked')
    base = bases[0]
    texts = []
    for side, rev in zip(sides, revs):
        raw = git_out(root, 'cat-file', 'blob', f'{rev}:{path}')
        if raw is None:
            raise Unusable(f'{path} does not exist at {side}: nothing was checked')
        try:
            texts.append(lines_of(raw.decode('utf-8-sig')))
        except UnicodeDecodeError:
            raise Unusable(f'{path} at {side} is not UTF-8 text: nothing was checked')
    if merging and git_out(root, 'ls-files', '-u'):
        raise Unusable('the merge still has unmerged files (git ls-files -u): resolve and git add them first')
    judged = [[(n, texts[s][n - 1]) for n in added(root, base, rev, path) if not blank(texts[s][n - 1])]
              for s, rev in enumerate(revs)]
    wanted = {line for lines in judged for _, line in lines}
    result = count(root, entries_of(root, None if merging else 'HEAD'), wanted)
    counts = [count(root, entries_of(root, rev), wanted) for rev in revs]
    at_base = count(root, entries_of(root, base), wanted)
    print(f'merged: {path}, {sides[0]} and {sides[1]} against their merge base {base[:12]}; the result is '
          + ('the index of the unfinished merge' if merging else 'the tree of HEAD'))
    found = 0
    for s, side in enumerate(sides):
        mine, other = counts[s], counts[1 - s]
        for n, line in judged[s]:
            if result[line] < mine[line] + min(0, other[line] - at_base[line]):
                print(f'LOST  {side}  {path}:{n}  {line}')
                found += 1
    return 1 if found else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):      # a Windows console is not UTF-8 by default
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='command', required=True)
    start = sub.add_parser('start', help='write a first proposal and list the hazards')
    start.add_argument('file', type=Path)
    start.add_argument('--out', type=Path, help=f'the proposal to write (default: {DEFAULT_NAME} beside the file)')
    start.set_defaults(run=cmd_start)
    for name, run, text in (('show', cmd_show, 'check a proposal and print it for the owner'),
                            ('apply', cmd_apply, 'apply an approved proposal'),
                            ('verify', cmd_verify, 'check an applied proposal against a copy of the original')):
        command = sub.add_parser(name, help=text)
        command.add_argument('proposal', type=Path)
        command.add_argument('--file', type=Path, help='the CLAUDE.md in the repository the proposal applies to, '
                             'in place of the `file` it records (a proposal made on a copy)')
        command.set_defaults(run=run)
        if name == 'verify':
            command.add_argument('--original', type=Path, required=True)
    merge = sub.add_parser('merged', help='after a merge or a finished rebase: name each line a side added and lost')
    merge.add_argument('--file', type=Path, help='the file to judge (default: CLAUDE.md at the git root)')
    merge.add_argument('--side', action='append', help='a side, given twice (after a rebase: ORIG_HEAD and <upstream>)')
    merge.set_defaults(run=cmd_merged)
    args = ap.parse_args(argv)
    try:
        return args.run(args)
    except Unusable as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:      # a crash is "nothing was checked", never a verdict
        print(f'claude_md_shrink.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
