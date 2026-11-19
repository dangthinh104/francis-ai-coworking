#!/usr/bin/env python3
"""Check anchored citations in architecture diagrams against the code.

A citation file is any JSON under --diagrams that carries
``meta.repository.revision`` (a commit) and, anywhere inside it, ``sources``
lists of ``{"path", "line", "end_line", "label"}``. Archify candidates have
this shape; so does the ``map.refs.json`` sidecar the map-project skill writes.
Paths are relative to the git root.

    cite_refs.py --diagrams DIR --report     what moved, what is gone
    cite_refs.py --diagrams DIR --check      exit 1 when a citation is untrue or
                                             cannot be tied to one place
    cite_refs.py --diagrams DIR --fix        re-point what moved and re-pin, in
                                             one write per file; not with --touched;
                                             exit 1, naming each citation, when one
                                             is left other than ok
    cite_refs.py --diagrams DIR --prose      line numbers written into labels
    cite_refs.py --diagrams DIR --touched F  hook mode, always exits 0

Files are found recursively. A file that is not valid JSON, is a symlink, has
malformed `sources`, has citations but no commit as its pin, or (under --check)
cites nothing exits 2, and finding no citation file exits 1: nothing checked
is not a pass. A crash exits 2 as well. JSON that is neither pinned nor citing
is some other file and is ignored.

A citation is judged by the TEXT of the cited line at the pinned commit, not
by its number: line numbers drift on every insertion above them.

  ok          same text, same line
  moved       same text, other line; --fix re-points it; not a failure
  lost        the text is gone; the diagram now says something untrue
  ambiguous   the text matches several places; never auto-fixed; fails --check
  weak anchor the cited line is blank or too short to track; fails --check
  past eof    end_line runs off the file
  file gone   the file is not in the working tree, or the path leaves the
              repository (such a file is never opened)

The comparison is against the working tree. If the pinned commit is not in
this clone (shallow clone), the tool exits 2 instead of passing blind.
"""
from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path('.')
PROJECT_ROOT = Path('.')
DIAGRAMS_DIR = Path('.')

OK = 'ok'
MOVED = 'moved'
LOST = 'lost'
AMBIGUOUS = 'ambiguous'
WEAK = 'weak anchor'
PAST_EOF = 'past eof'
FILE_GONE = 'file gone'
# Under --check a citation that cannot be tied to one place is not a pass.
_FAILING = (LOST, FILE_GONE, PAST_EOF, AMBIGUOUS, WEAK)

# Prose verdicts: a number written into a label has no anchor, so --fix
# cannot move it. ANCHORED means a citation on the same diagram pins it.
ANCHORED = 'anchored'
UNANCHORED = 'unanchored'
SYMBOL_OK = 'symbol ok'
SYMBOL_MOVED = 'symbol moved'
_PROSE_FAILING = (FILE_GONE, PAST_EOF, AMBIGUOUS, SYMBOL_MOVED)

_EXT = (r'py|pyi|js|jsx|mjs|cjs|ts|tsx|vue|svelte|php|go|rs|java|kt|kts|rb|'
        r'cs|swift|dart|scala|lua|c|h|cc|cpp|hpp|m|mm|proto|sh|ps1|sql|'
        r'html|css|scss|tf|gradle|xml|ini|cfg|ya?ml|json|toml|md|txt')

# `Name :123`. Three characters minimum, and no digit or dash after the
# number, so a range or a longer figure does not half-match.
_SYMBOL_REF = re.compile(r'(?<![\w.:/-])([A-Za-z_]\w{2,}) :(\d{1,5})(?![\d-])')

# `src/app/main.py:390`, `main.ts:926-931`. The lookbehind stops it biting
# the tail off a longer path.
_PROSE_REF = re.compile(
    r'(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:' + _EXT + r')):(\d+)(?:-(\d+))?')

_MODIFIERS = (r'(?:(?:export|default|public|private|protected|internal|'
              r'static|abstract|final|sealed|open|data|async|pub(?:\([a-z]+\))?)'
              r'\s+)*')
# Keywords that only ever introduce a definition, at any indent. `func` may
# carry a Go receiver.
_DEF_ANY = (r'^\s*' + _MODIFIERS +
            r'(?:class|def|function|interface|trait|enum|struct|fn|fun|impl|'
            r'mod|module|record|protocol|namespace|func(?:\s*\([^)]*\))?)\s+')
# `const`, `let`, `var`, `val`, `type` also introduce locals, so they count
# as a definition only at column 0.
_DEF_TOP = r'^' + _MODIFIERS + r'(?:const|let|var|val|type)\s+'

# Below this many non-space characters an anchor (`)`, `else:`) matches
# everywhere and cannot be tracked.
_MIN_ANCHOR_CHARS = 6

# The anchor window grows up to this many lines to tell repeated call sites
# apart without matching across unrelated functions.
_MAX_ANCHOR_WINDOW = 6


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=REPO_ROOT, capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


@dataclass
class Finding:
    diagram: str
    path: str
    line: int | None
    end_line: int | None
    label: str
    verdict: str
    new_line: int | None = None
    detail: str = ''

    @property
    def shift(self) -> int | None:
        if self.new_line is None or self.line is None:
            return None
        return self.new_line - self.line

    @property
    def where(self) -> str:
        return self.path if self.line is None else f'{self.path}:{self.line}'


def _norm(path: object) -> str:
    """One spelling per file: `./src/m.py`, `src//m.py` and `src\\m.py` are `src/m.py`."""
    return posixpath.normpath(str(path).replace('\\', '/'))


def _lines(raw: bytes) -> list[str]:
    """Lines the way git counts them: only `\\n` ends a line. `str.splitlines` also breaks on
    form feed, U+2028 and their kin, which shifts every line after one of those."""
    lines = raw.decode('utf-8', errors='replace').replace('\r\n', '\n').split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return lines


def _git_show(rev: str, path: str) -> list[str] | None:
    # `cat-file blob`, not `show`: for a path that is not a blob, `show` prints something else.
    run = subprocess.run(['git', 'cat-file', 'blob', f'{rev}:{path}'], cwd=REPO_ROOT, capture_output=True)
    return _lines(run.stdout) if run.returncode == 0 else None


def _rev_exists(rev: str) -> bool:
    return _git('cat-file', '-e', f'{rev}^{{commit}}').returncode == 0


def _head() -> str:
    return _git('rev-parse', 'HEAD').stdout.strip()


def _read_lines(path: Path) -> list[str]:
    return _lines(path.read_bytes())


_NUMBER = '\x00kit-number:'


def _load(path: Path) -> dict:
    """Read a citation file. A non-integer number keeps its spelling (`1e3` stays `1e3`)."""
    return json.loads(path.read_text(encoding='utf-8-sig'), parse_float=lambda s: _NUMBER + s)


def _style(path: Path) -> tuple[str, int | str | None, str, bool]:
    """How the file is written, so a fix changes two values and not the whole layout:
    (BOM, indent, newline, non-ASCII escaped)."""
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig', errors='replace')
    indent = re.search(r'\n([ \t]+)\S', text)
    return ('\ufeff' if raw.startswith(b'\xef\xbb\xbf') else '',
            indent.group(1) if indent else (None if '\n' not in text.strip() else 2),
            '\r\n' if '\r\n' in text else '\n',
            text.isascii() and '\\u' in text)


def _dump(path: Path, data: dict) -> None:
    """Replace the file in one step: an interrupted or failed write leaves the old one."""
    bom, indent, newline, escaped = _style(path) if path.is_file() else ('', 2, '\n', False)
    text = json.dumps(data, ensure_ascii=escaped, indent=indent) + '\n'
    text = re.sub(r'"\\u0000kit-number:([^"]*)"', r'\1', text)
    body = (bom + text.replace('\n', newline)).encode('utf-8')
    # A fresh, unpredictable name beside the target: a planted file or symlink is never
    # written through, and a failed write leaves the old file and no leftover.
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.kit-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(body)
        if path.is_file():
            shutil.copymode(path, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def _key(path: Path) -> str:
    """A citation file's name in reports: its path under --diagrams."""
    try:
        return path.resolve().relative_to(DIAGRAMS_DIR.resolve()).as_posix()
    except ValueError:
        return path.name


def _pin_of(candidate: object) -> str | None:
    try:
        rev = candidate['meta']['repository']['revision']  # type: ignore[index]
    except (KeyError, TypeError):
        return None
    return rev if isinstance(rev, str) and re.fullmatch(r'[0-9a-f]{7,40}', rev) else None


def _malformed(node: object) -> str | None:
    """Why a `sources` entry cannot be checked, or None when every one can."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'sources':
                if not isinstance(value, list):
                    return '`sources` is not a list'
                for item in value:
                    if not isinstance(item, dict) or not isinstance(item.get('path'), str) or not item['path']:
                        return 'a `sources` entry has no `path`'
                    for field in ('line', 'end_line'):
                        number = item.get(field)
                        if number is not None and (isinstance(number, bool) or not isinstance(number, int)
                                                   or number < 1):
                            return f'`{field}` of {item["path"]} is not a line number'
                    if item.get('end_line') is not None and (
                            item.get('line') is None or item['end_line'] < item['line']):
                        return f'`end_line` of {item["path"]} comes before `line`'
            else:
                found = _malformed(value)
                if found:
                    return found
    elif isinstance(node, list):
        for value in node:
            found = _malformed(value)
            if found:
                return found
    return None


def _iter_sources(node: object):
    """Yield every citation dict, wherever it is nested."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'sources' and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and 'path' in item:
                        yield item
            else:
                yield from _iter_sources(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_sources(value)


def _locate(pinned: list[str], current: list[str],
            line: int) -> tuple[list[int], int, str]:
    """Find where the block starting at `line` lives now.

    One line is often not a fingerprint, so the window grows from the cited
    line until the block is unique or the cap is reached. Returns (1-based
    matching start lines, window used, block text).
    """
    hits: list[int] = []
    window = 1
    needle: list[str] = []
    kept = None
    for window in range(1, _MAX_ANCHOR_WINDOW + 1):
        stop = min(line - 1 + window, len(pinned))
        needle = [text.strip() for text in pinned[line - 1:stop]]
        hits = [
            start + 1
            for start in range(0, max(0, len(current) - len(needle) + 1))
            if [t.strip() for t in current[start:start + len(needle)]] == needle
        ]
        if not hits and kept:
            # The longer block is gone (a line was added inside it) but the shorter one is
            # still there, in several places: that is ambiguous, not lost.
            hits, window, needle = kept
            if line in hits:
                hits = [line]       # and the cited one has not moved
            break
        if len(hits) <= 1:
            break
        kept = (hits, window, needle)
    return hits, window, ' '.join(n for n in needle if n)


def _judge(cite: dict, pinned: list[str] | None,
           current: list[str] | None) -> tuple[str, int | None, str]:
    if current is None:
        return FILE_GONE, None, 'not in the working tree'
    # A citation with no line names a whole file: existence is the question.
    if cite.get('line') is None:
        return OK, None, 'whole file'

    line = int(cite['line'])
    end_line = cite.get('end_line')
    if pinned is None:
        return LOST, None, 'the file did not exist at the pinned revision'
    if not (1 <= line <= len(pinned)):
        return LOST, None, (f'line {line} is outside the pinned file '
                            f'({len(pinned)} lines)')

    hits, window, anchor = _locate(pinned, current, line)
    if not anchor.replace(' ', ''):
        return WEAK, None, (f'the {window} lines from {line} are blank, '
                            f'nothing to track by content')
    if len(anchor.replace(' ', '')) < _MIN_ANCHOR_CHARS:
        return WEAK, None, f'anchor is {anchor!r} even at {window} lines'

    # Range overflow is judged AFTER the anchor search: a file that shrank is
    # exactly when the anchor has moved and --fix is needed.
    def _overflow(resolved: int) -> str:
        if end_line is None:
            return ''
        shifted = int(end_line) + (resolved - line)
        if shifted > len(current):
            return (f'end_line {end_line} -> {shifted} exceeds the file '
                    f'({len(current)} lines)')
        return ''

    if line in hits:
        overflow = _overflow(line)
        return (PAST_EOF, None, overflow) if overflow else (OK, line, '')
    if len(hits) == 1:
        overflow = _overflow(hits[0])
        if overflow:
            return PAST_EOF, None, overflow
        return MOVED, hits[0], f'{line} -> {hits[0]}'
    if len(hits) > 1:
        return AMBIGUOUS, None, (f'{len(hits)} places match even at a '
                                 f'{window}-line window: {hits[:6]}')
    return LOST, None, f'{anchor[:60]!r} is gone'


def collect(diagram_paths: list[Path],
            only_paths: set[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    revisions: set[str] = set()
    pinned_cache: dict[tuple[str, str], list[str] | None] = {}
    current_cache: dict[str, list[str] | None] = {}

    for diagram_path in sorted(diagram_paths):
        candidate = _load(diagram_path)
        rev = _pin_of(candidate)
        if rev is None:
            continue
        revisions.add(rev)
        for cite in _iter_sources(candidate):
            path = _norm(cite['path'])
            if only_paths is not None and path not in only_paths:
                continue
            inside = (not Path(path).is_absolute() and
                      (REPO_ROOT / path).resolve().is_relative_to(REPO_ROOT.resolve()))
            if not inside:
                # Never read it: a file outside the repository is not this project's code.
                findings.append(Finding(
                    diagram=_key(diagram_path), path=path,
                    line=int(cite['line']) if cite.get('line') is not None else None,
                    end_line=cite.get('end_line'), label=str(cite.get('label', '')),
                    verdict=FILE_GONE, new_line=None, detail='the path leaves the repository'))
                continue
            key = (rev, path)
            if key not in pinned_cache:
                pinned_cache[key] = _git_show(rev, path)
            if path not in current_cache:
                on_disk = REPO_ROOT / path
                current_cache[path] = (
                    _read_lines(on_disk) if on_disk.is_file() else None)
            verdict, new_line, detail = _judge(
                cite, pinned_cache[key], current_cache[path])
            if verdict == FILE_GONE and (PROJECT_ROOT / path).is_file():
                detail = ('write the path from the git root: '
                          + (PROJECT_ROOT / path).resolve().relative_to(
                              REPO_ROOT.resolve()).as_posix())
            findings.append(Finding(
                diagram=_key(diagram_path), path=path,
                line=int(cite['line']) if cite.get('line') is not None else None,
                end_line=cite.get('end_line'),
                label=str(cite.get('label', '')),
                verdict=verdict, new_line=new_line, detail=detail))

    collect.revisions = sorted(revisions)
    return findings


@dataclass
class ProseRef:
    diagram: str
    written: str
    line: int
    end_line: int | None
    verdict: str
    path: str = ''
    detail: str = ''


_BASENAME_INDEX: dict[str, list[Path]] | None = None


def _basename_index() -> dict[str, list[Path]]:
    """Tracked files of this project by basename, so a bare `pipeline.py:12`
    can be told apart from other files of the same name. Scoped to the
    project root: a sibling project in a monorepo is not a candidate."""
    global _BASENAME_INDEX
    if _BASENAME_INDEX is None:
        index: dict[str, list[Path]] = {}
        # -z: without it git quotes a name that is not ASCII, and `café.py` is never found.
        listed = _git('ls-files', '-z', '--cached', '--others', '--exclude-standard',
                      '--', str(PROJECT_ROOT)).stdout.split('\0')
        for rel in filter(None, listed):
            if (REPO_ROOT / rel).is_file():
                index.setdefault(Path(rel).name, []).append(REPO_ROOT / rel)
        _BASENAME_INDEX = index
    return _BASENAME_INDEX


def _resolve_prose_path(raw: str,
                        cited: set[str] | None = None) -> tuple[Path | None, str]:
    """Resolve a prose path. A diagram that cites exactly one file of that
    name has already said which one it means; the repo-wide basename search
    only resolves names that are unique."""
    for base in (PROJECT_ROOT, REPO_ROOT):
        candidate = base / raw
        if candidate.is_file():
            return candidate, ''
    if cited:
        same = {c for c in cited if Path(c).name == Path(raw).name}
        if len(same) == 1:
            resolved = REPO_ROOT / next(iter(same))
            if resolved.is_file():
                return resolved, "resolved against this diagram's citations"
    matches = _basename_index().get(Path(raw).name, [])
    if len(matches) == 1:
        return matches[0], f'resolved by basename to {matches[0].name}'
    if len(matches) > 1:
        return None, (f'{len(matches)} files share that basename, write the '
                      f'path from the repo root')
    return None, 'no such file'


def _symbol_lines(name: str, cited: set[str]) -> dict[str, int]:
    """Where `name` is defined among the diagram's cited files: first
    definition per file."""
    found: dict[str, int] = {}
    pattern = re.compile(r'(?:' + _DEF_ANY + r'|' + _DEF_TOP + r')'
                         + re.escape(name) + r'\b')
    for rel in sorted(cited):
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            lines = _read_lines(path)
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if pattern.match(line):
                found[rel] = i
                break
    return found


def _iter_prose(node: object, trail: str = ''):
    """Every string in the candidate except the `sources` blocks."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == 'sources':
                continue
            yield from _iter_prose(value, f'{trail}.{key}')
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _iter_prose(value, f'{trail}[{i}]')
    elif isinstance(node, str):
        yield trail, node


def collect_prose(diagram_paths: list[Path],
                  only_paths: set[str] | None = None) -> list[ProseRef]:
    refs: list[ProseRef] = []
    for diagram_path in diagram_paths:
        data = _load(diagram_path)
        anchored: set[tuple[str, int]] = set()
        cited: set[str] = set()
        for cite in _iter_sources(data):
            path, line = cite.get('path'), cite.get('line')
            if path and not Path(path).is_absolute() and (
                    REPO_ROOT / path).resolve().is_relative_to(REPO_ROOT.resolve()):
                cited.add(_norm(path))    # a file outside the repository is never opened
            if path and isinstance(line, int):
                anchored.add((_norm(path), line))     # by path: `b/x.py:2` is not anchored by `a/x.py` line 2
        for _trail, text in _iter_prose(data):
            for match in _PROSE_REF.finditer(text):
                raw, start, end = match.group(1), int(match.group(2)), match.group(3)
                resolved, detail = _resolve_prose_path(raw, cited)
                if resolved is None:
                    verdict = (AMBIGUOUS if 'share that basename' in detail
                               else FILE_GONE)
                    rel = raw
                else:
                    try:
                        rel = resolved.resolve().relative_to(
                            REPO_ROOT.resolve()).as_posix()
                    except ValueError:
                        rel = None
                if resolved is not None and rel is None:
                    verdict, detail, rel = FILE_GONE, 'outside the repo', raw
                elif resolved is not None:
                    total = len(_read_lines(resolved))
                    last = int(end) if end else start
                    if last > total:
                        verdict, detail = PAST_EOF, f'{total} lines'
                    elif (rel, start) in anchored:
                        verdict = ANCHORED
                    else:
                        verdict = UNANCHORED
                if only_paths is not None and rel not in only_paths:
                    continue
                refs.append(ProseRef(
                    diagram=_key(diagram_path), written=match.group(0),
                    line=start, end_line=int(end) if end else None,
                    verdict=verdict, path=rel, detail=detail))
            for match in _SYMBOL_REF.finditer(text):
                name, start = match.group(1), int(match.group(2))
                where = _symbol_lines(name, cited)
                if not where:
                    continue  # not a definition here, so not a reference
                if start in where.values():
                    rel = next(k for k, v in where.items() if v == start)
                    verdict, detail = SYMBOL_OK, ''
                elif len(where) == 1:
                    rel, actual = next(iter(where.items()))
                    verdict = SYMBOL_MOVED
                    detail = f'{name} is defined at :{actual}'
                else:
                    rel = ''
                    verdict = AMBIGUOUS
                    detail = ('defined in ' + ', '.join(
                        f'{k}:{v}' for k, v in sorted(where.items())))
                if only_paths is not None and rel not in only_paths:
                    continue
                refs.append(ProseRef(
                    diagram=_key(diagram_path), written=match.group(0),
                    line=start, end_line=None, verdict=verdict,
                    path=rel, detail=detail))
    return refs


def render_prose(refs: list[ProseRef]) -> str:
    if not refs:
        return '  no line numbers written into prose'
    counts = Counter(r.verdict for r in refs)
    out = [f'{len(refs)} line number(s) written into diagram prose: '
           f'{", ".join(f"{n} {v}" for v, n in sorted(counts.items()))}',
           '',
           '  UNANCHORED: not checked by --check, not moved by --fix. Pair it',
           '  with a `sources` citation on the same node, or drop the number.',
           '  SYMBOL MOVED: the definition is elsewhere now; --check fails.',
           '']
    for verdict in (FILE_GONE, PAST_EOF, AMBIGUOUS, SYMBOL_MOVED,
                    UNANCHORED, SYMBOL_OK, ANCHORED):
        group = [r for r in refs if r.verdict == verdict]
        if not group:
            continue
        out.append(f'-- {verdict} ({len(group)})')
        for r in group:
            tail = f'  [{r.detail}]' if r.detail else ''
            out.append(f'  {r.written:46s} {r.diagram}{tail}')
        out.append('')
    return '\n'.join(out)


def render_report(findings: list[Finding]) -> str:
    counts = Counter(f.verdict for f in findings)
    out = [f'{len(findings)} citations across '
           f'{len({f.diagram for f in findings})} diagrams and '
           f'{len({f.path for f in findings})} files', '']
    order = [OK, MOVED, AMBIGUOUS, WEAK, PAST_EOF, LOST, FILE_GONE]
    for verdict in order:
        if counts.get(verdict):
            out.append(f'  {counts[verdict]:4d}  {verdict}')
    out.append('')

    interesting = [f for f in findings if f.verdict != OK]
    if not interesting:
        out.append('Every citation resolves at its recorded line.')
        return '\n'.join(out)
    for verdict in order[1:]:
        group = [f for f in interesting if f.verdict == verdict]
        if not group:
            continue
        out.append(f'-- {verdict} ({len(group)})')
        for f in sorted(group, key=lambda x: (x.path, x.line or 0)):
            shift = f'  [{f.shift:+d}]' if f.shift else ''
            out.append(f'  {f.where}{shift}  {f.detail}')
            out.append(f'      {f.diagram} · {f.label}')
        out.append('')
    return '\n'.join(out)


def _dirty_paths() -> set[str]:
    """Uncommitted paths. `-z` keeps names unquoted; a rename or copy entry
    is followed by a second field holding the original path."""
    fields = _git('status', '--porcelain', '-z').stdout.split('\0')
    dirty: set[str] = set()
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        dirty.add(entry[3:].replace('\\', '/'))
        if entry[0] in 'RC' or entry[1] in 'RC':
            if i < len(fields) and fields[i]:
                dirty.add(fields[i].replace('\\', '/'))
            i += 1
    return dirty


COMMIT_FIRST = 'commit first, then run --fix, then commit the re-pinned file.'


def _blocked(findings: list[Finding]) -> list[str]:
    """The cited files that are uncommitted: while one is, nothing is re-pointed or re-pinned."""
    dirty = _dirty_paths()
    return sorted({f.path for f in findings if f.path in dirty})


def repin_targets(diagram_paths: list[Path], findings: list[Finding],
                  allowed: tuple[str, ...] = (OK,),
                  quiet: bool = False) -> list[str]:
    """Which diagrams may advance their pin. The ONLY site that decides, so
    a diagram gets new numbers and a new pin together or neither.

    Refuses while a cited file is uncommitted: numbers fixed against the
    working tree would describe no commit at all.
    """
    blocked = _blocked(findings)
    if blocked:
        if not quiet:
            print('  not re-pointing or re-pinning: these cited files are '
                  'uncommitted:')
            for path in blocked[:8]:
                print(f'      {path}')
            if len(blocked) > 8:
                print(f'      ... and {len(blocked) - 8} more')
            print(f'  {COMMIT_FIRST}')
        return []

    by_diagram: dict[str, list[Finding]] = {}
    for f in findings:
        by_diagram.setdefault(f.diagram, []).append(f)
    targets = []
    for diagram_path in sorted(diagram_paths):
        group = by_diagram.get(_key(diagram_path), [])
        # Re-pinning past an unresolved citation would erase the evidence of
        # what it used to point at.
        if not group or any(f.verdict not in allowed for f in group):
            continue
        targets.append(_key(diagram_path))
    return targets


def fix_and_pin(diagram_paths: list[Path], findings: list[Finding],
                names: list[str], head: str) -> tuple[int, list[str]]:
    """Re-point the moved citations of the named diagrams and move their pin,
    one write per file, so a file never holds new lines under an old pin."""
    moved = {(f.diagram, f.path, f.line): f
             for f in findings if f.verdict == MOVED and f.new_line}
    rewritten, repinned = 0, []
    for diagram_path in sorted(diagram_paths):
        name = _key(diagram_path)
        if name not in names:
            continue
        candidate = _load(diagram_path)
        changed = False
        for cite in _iter_sources(candidate):
            if cite.get('line') is None:
                continue
            found = moved.get((name, _norm(cite['path']), int(cite['line'])))
            if not found:
                continue
            cite['line'] = found.new_line
            if cite.get('end_line') is not None:
                # The end is shifted with its anchor, not tracked by content:
                # a block's last line is usually a weak anchor.
                cite['end_line'] = int(cite['end_line']) + (found.shift or 0)
            changed = True
            rewritten += 1
        if candidate['meta']['repository']['revision'] != head:
            candidate['meta']['repository']['revision'] = head
            repinned.append(name)
            changed = True
        if changed:
            _dump(diagram_path, candidate)
    return rewritten, repinned


def main(argv: list[str] | None = None) -> int:
    """Hook mode (--touched) reports and never fails, whatever goes wrong."""
    args = sys.argv[1:] if argv is None else argv
    if not any(a == '--touched' or a.startswith('--touched=') for a in args):
        try:
            return _main(args)
        except Exception as exc:  # a crash is "nothing was checked", never "a citation is wrong"
            print(f'  cite_refs.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
            return 2
    try:
        _main(args)
    except Exception as exc:  # a hook must not block the edit it follows
        print(f'[cite-refs] skipped: {type(exc).__name__}: {exc}')
    return 0


def _citation_files(directory: Path, checking: bool) -> tuple[list[Path], list[str]]:
    """The files to judge, and the ones that cannot be: (paths, reasons)."""
    # A citation file that cannot be read, or that cites code without a pin,
    # is a failure and not a pass: nothing in it was checked.
    diagram_paths = []
    unusable = []
    for path in sorted(directory.rglob('*.json')):
        if path.is_symlink():
            unusable.append(f'{_key(path)}: is a symlink, which is neither read nor written')
            continue
        try:
            data = _load(path)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError, RecursionError) as exc:
            unusable.append(f'{_key(path)}: not readable as JSON ({type(exc).__name__})')
            continue
        meta = data.get('meta') if isinstance(data, dict) else None
        claims = isinstance(meta, dict) and 'repository' in meta    # says it is a citation file
        try:
            cites = any(isinstance(c, dict) and c.get('path') for c in _iter_sources(data))
        except (TypeError, AttributeError):
            cites = False
        if not claims and not cites:
            continue        # some other JSON (a source map has `sources` too)
        broken = _malformed(data)
        if broken:
            unusable.append(f'{_key(path)}: {broken}')
        elif _pin_of(data) is None:
            unusable.append(f'{_key(path)}: has `sources` but no commit in '
                            f'meta.repository.revision')
        elif not cites and checking:
            unusable.append(f'{_key(path)}: cites nothing, so nothing in it was checked')
        else:
            diagram_paths.append(path)
    return diagram_paths, unusable


def _touched_paths(touched: list[str]) -> set[str]:
    """The paths given to --touched, as the repository writes them."""
    only_paths = set()
    for raw in touched:
        p = Path(raw)
        p = p if p.is_absolute() else (Path.cwd() / p)
        try:
            only_paths.add(p.resolve().relative_to(REPO_ROOT).as_posix())
        except ValueError:
            continue
    return only_paths


def _fix(diagram_paths: list[Path], findings: list[Finding],
         only_paths: set[str] | None) -> tuple[list[Finding], bool]:
    """Re-point and re-pin what fully resolves; return the findings as they stand afterwards,
    and whether an uncommitted cited file refused the whole run."""
    # Decide ONCE, from the verdicts taken before any write, then do both
    # halves on the same set of diagrams.
    refused = bool(_blocked(findings))
    targets = repin_targets(diagram_paths, findings, allowed=(OK, MOVED))
    rewritten, done = fix_and_pin(diagram_paths, findings, targets, _head())
    print(f'  re-pointed {rewritten} moved citation(s)')
    if done:
        print(f'  re-pinned to {_head()[:8]}: {", ".join(done)}')
    elif targets:
        print('  pins already current')
    elif not refused:       # a refusal already said why nothing was
        print('  no diagram fully resolves, so nothing was re-pointed '
              'or re-pinned')
    if rewritten or done:
        findings = collect(diagram_paths, only_paths)
        still = [f for f in findings if f.verdict != OK]
        print(f'  after the fix: {len(findings) - len(still)} ok'
              + (f', {len(still)} still unresolved' if still else
                 ', all citations exact'))
    return findings, refused


def _hook_report(diagram_paths: list[Path], findings: list[Finding], only_paths: set[str]) -> None:
    """What --touched prints: citations into the touched files that no longer resolve."""
    interesting = [f for f in findings if f.verdict != OK]
    if interesting:
        print(f'[cite-refs] {len(interesting)} citation(s) into the files '
              f'you touched no longer resolve as recorded:')
        for f in interesting[:10]:
            print(f'    {f.where}  {f.verdict}  ({f.diagram}) {f.detail}')
        if len(interesting) > 10:
            print(f'    ... and {len(interesting) - 10} more, run --report')
    # --fix cannot move prose numbers, so the only moment to catch them
    # is while the person who moved the code is still looking at it.
    prose = [r for r in collect_prose(diagram_paths, only_paths)
             if r.verdict not in (ANCHORED, SYMBOL_OK)]
    if prose:
        print(f'[cite-refs] {len(prose)} line number(s) written into '
              f'diagram prose point into the files you touched. Nothing '
              f'moves these, read them:')
        for r in prose[:10]:
            print(f'    {r.written}  {r.verdict}  ({r.diagram})')
        if len(prose) > 10:
            print(f'    ... and {len(prose) - 10} more, run --prose')


def _main(argv: list[str]) -> int:
    global REPO_ROOT, PROJECT_ROOT, DIAGRAMS_DIR, _BASENAME_INDEX
    _force_utf8()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--diagrams', type=Path, required=True,
                    help='directory holding the citation JSON files')
    ap.add_argument('--repo', type=Path,
                    help='git root (default: found from --diagrams)')
    ap.add_argument('--root', type=Path,
                    help='project root inside the repo, for prose paths '
                         '(default: the git root)')
    ap.add_argument('--report', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--fix', action='store_true')
    ap.add_argument('--prose', action='store_true')
    ap.add_argument('--touched', nargs='*', metavar='PATH')
    args = ap.parse_args(argv)

    if args.fix and args.touched is not None:
        # A fix decided from a filtered view would re-pin a file past citations it never looked at.
        print('  --fix cannot be combined with --touched: run --fix over everything', file=sys.stderr)
        return 2
    if not args.diagrams.is_dir():
        print(f'  no such directory: {args.diagrams}', file=sys.stderr)
        return 2
    # Always the git toplevel: `git show <rev>:<path>` and `git status` speak
    # in toplevel-relative paths, so a subdirectory here would misjudge.
    REPO_ROOT = (args.repo or args.diagrams).resolve()
    top = _git('rev-parse', '--show-toplevel')
    if top.returncode != 0:
        print(f'  {REPO_ROOT} is not inside a git repository', file=sys.stderr)
        return 2
    REPO_ROOT = Path(top.stdout.strip())
    PROJECT_ROOT = args.root.resolve() if args.root else REPO_ROOT
    DIAGRAMS_DIR = args.diagrams.resolve()
    _BASENAME_INDEX = None

    diagram_paths, unusable = _citation_files(args.diagrams, args.check)
    for line in unusable:
        print(f'  cannot check {line}', file=sys.stderr)
    if unusable and args.touched is None:
        return 2
    if not diagram_paths:
        print(f'  no citation files under {args.diagrams}')
        return 1 if args.check else 0

    only_paths = None
    if args.touched is not None:
        only_paths = _touched_paths(args.touched)
        if not only_paths:
            return 0

    for diagram_path in diagram_paths:
        rev = _pin_of(_load(diagram_path))
        if not _rev_exists(rev):
            print(f'  cannot verify: {_key(diagram_path)} is pinned to '
                  f'{rev[:8]}, which is not in this clone. Fetch it, or '
                  f'deepen a shallow clone.', file=sys.stderr)
            return 0 if args.touched is not None else 2

    findings = collect(diagram_paths, only_paths)
    # Under --touched no citation into the file is no reason to skip the prose:
    # a `file.py:123` written into a label is what the hook exists to catch.
    if not findings and args.touched is None:
        if args.check and args.touched is None:
            print('  the citation files cite nothing: nothing was checked', file=sys.stderr)
            return 1
        return 0
    failing = [f for f in findings if f.verdict in _FAILING]

    left = []
    if args.fix:
        findings, refused = _fix(diagram_paths, findings, only_paths)
        failing = [f for f in findings if f.verdict in _FAILING]
        # Whatever kept a citation from being repaired, say which, and fail. Only a refusal that left
        # nothing but `moved` needs a commit and no person (016/FR-010).
        left = [f for f in findings if f.verdict != OK]
        for f in sorted(left, key=lambda x: (x.path, x.line or 0)):
            print(f'    {f.where}  {f.verdict}  ({f.diagram}) {f.detail}', file=sys.stderr)
        if left:
            todo = COMMIT_FIRST if refused and all(f.verdict == MOVED for f in left) else 'each line above needs a person.'
            print(f'\n  {len(left)} citation(s) are not `ok` after --fix: {todo}', file=sys.stderr)

    if args.touched is not None:
        _hook_report(diagram_paths, findings, only_paths)
        return 0

    prose = collect_prose(diagram_paths, only_paths)
    prose_failing = [r for r in prose if r.verdict in _PROSE_FAILING]

    if args.prose:
        print(render_prose(prose))
        return 1 if left or (args.check and (prose_failing or failing)) else 0

    if args.report or not (args.check or args.fix):
        print(render_report(findings))
        revs = getattr(collect, 'revisions', [])
        if len(revs) > 1:
            print(f'  note: pinned to {len(revs)} different revisions: '
                  f'{[r[:8] for r in revs]}')
        unanchored = [r for r in prose
                      if r.verdict not in (ANCHORED, SYMBOL_OK)]
        print(f'  plus {len(prose)} line number(s) written into prose, '
              f'{len(unanchored)} of them unanchored and therefore unchecked. '
              f'`--prose` lists them.')

    if args.check and (failing or prose_failing):
        if failing:
            for f in failing[:20]:
                print(f'    {f.where}  {f.verdict}  ({f.diagram}) {f.detail}', file=sys.stderr)
            print(f'\n  {len(failing)} citation(s) point at code that is '
                  f'gone or cannot be tied to one place. The diagrams now '
                  f'assert something unchecked.',
                  file=sys.stderr)
        if prose_failing:
            print(f'  {len(prose_failing)} line number(s) in prose are '
                  f'provably wrong: '
                  + ', '.join(f'{r.written} ({r.verdict})'
                              for r in prose_failing[:6]), file=sys.stderr)
        return 1
    if args.check and not args.report:
        counts = Counter(f.verdict for f in findings)
        print(f'  checked {len(findings)} citation(s) in '
              f'{len(diagram_paths)} file(s): '
              + ', '.join(f'{n} {v}' for v, n in sorted(counts.items())))
    return 1 if left else 0


if __name__ == '__main__':
    raise SystemExit(main())
