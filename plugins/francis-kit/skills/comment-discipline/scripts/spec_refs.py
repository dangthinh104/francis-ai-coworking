#!/usr/bin/env python3
"""Check that every requirement cited in code leads to exactly one requirement.

    spec_refs.py [--repo DIR] [--root DIR] --report
    spec_refs.py ... --check            fail when it got worse than the baseline
    spec_refs.py ... --write-baseline   record today's counts (refuses a rise
                                        without --allow-rise)
    spec_refs.py ... --touched F [F..]  list problems in these files, never fails
    spec_refs.py ... --fix [--dry-run] [--dashed]
                                        rewrite to the standard form where the
                                        line itself names the one owner

The standard form is `NNN/FR-001`: feature number, slash, requirement id.

Verdicts
    ok          NNN/FR-001 and feature NNN declares FR-001
    dead        NNN/FR-001 but no single such feature, or it declares no FR-001
    legacy      the owner is named another way on the line (`spec 139 FR-008`,
                `FR-063-003`) and that feature declares the id
    unique      bare id that exactly one feature declares
    contested   bare id that several features declare
    undefined   bare id, or a named owner, that declares no such requirement

--fix touches a line only when all of this holds: the citation sits in a comment
or a Python docstring, the line names exactly one feature, the owner touches the
id (`spec 139 FR-008`, `FR-008 (spec 139)`, or a list continuing one), that
feature declares every id on the line, and the file is plain UTF-8 and not a symlink. It changes
the citation text and nothing else. `FR-063-003` is rewritten only with --dashed,
because the same shape can be a range.

Exit 0 clean or no worse than the baseline; 1 under --check when worse or any
`dead`; 2 nothing could be judged.
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
import subprocess
import sys
import tokenize
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'kit-init' / 'scripts'))
import kit_spec  # noqa: E402

ID = r'(?:FR|SC)-[A-Z]?\d+(?:\.\d+)*'
FEATURE_DIR = re.compile(r'^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*$')
CANONICAL = re.compile(rf'(?<![\w/-])(\d{{3}})/({ID})(?![\w-])')
DASHED = re.compile(r'(?<![\w/-])(FR|SC)-(\d{3})-(\d{3})(?![\w-])')
BARE = re.compile(rf'(?<![\w/-])({ID})(?![\w-])')
OWNER = re.compile(r'specs?[ \t#/_-]*(\d{3})(?!\d)', re.I)
ADJACENT = re.compile(rf'\bspecs?[ \t#-]*(\d{{3}})[ \t]+§?({ID})(?![\w-])', re.I)
NEGATED = re.compile(r'\b(?:not|no|never|không|chưa)[ \t]+specs?\b', re.I)
LINES = re.compile(r'[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+')
# `key: |`, `- |` and `key: !!str |`: what follows is data, whatever it looks like.
BLOCK_SCALAR = re.compile(r'(?::|^[ \t]*-)[ \t]*(?:[!&]\S+[ \t]+)*[|>][+-]?\d*[ \t]*(?:#.*)?$')
HEREDOC = re.compile(r'<<<[ \t]*[\'"]?(\w+)[\'"]?')
# Shell and Ruby: `<<EOF`, `<<-EOF`, `<<~EOF`, `<<'EOF'`. `<<<` there is a here-string, one line.
SH_HEREDOC = re.compile(r'(?<!<)<<[-~]?[ \t]*[\'"]?([A-Za-z_]\w*)[\'"]?')

SOURCE_EXT = {'.py', '.php', '.go', '.ts', '.tsx', '.js', '.jsx', '.vue', '.rb', '.java', '.kt',
              '.cs', '.rs', '.sh', '.sql', '.yml', '.yaml'}
HASH_EXT = {'.sh', '.yml', '.yaml', '.php', '.rb'}
SKIP_PARTS = {'node_modules', 'vendor', '.git', 'specs', '.specify', 'docs', 'dist', 'build'}
TEST_PATH = re.compile(r'(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|[._-](test|spec)\.[a-z]+$|Test\.php$', re.I)
PRAGMA = 'spec-refs: ignore'
PRAGMA_WINDOW = 40
COUNTED = ('contested', 'undefined', 'ignored_files')
RESOLVED = ('ok', 'legacy', 'unique')


class Unusable(Exception):
    pass


def specs_dir(root: Path):
    for base in (root / 'specs', root / '.specify' / 'specs'):
        if base.is_dir():
            return base
    return None


def registry(root: Path):
    """{feature number: ids it declares}. A number used by two directories owns nothing."""
    features: dict[str, set[str]] = {}
    seen = Counter()
    for base in (root / 'specs', root / '.specify' / 'specs'):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            m = FEATURE_DIR.match(entry.name)
            if not m or not entry.is_dir():
                continue
            spec = entry / 'spec.md'
            seen[m.group(1)] += 1
            features.setdefault(m.group(1), set()).update(kit_spec.requirements(kit_spec.read(spec) or ''))
    for number, count in seen.items():
        if count > 1:
            features[number] = set()
    return features


def tracked(repo: Path, root: Path):
    out = subprocess.run(['git', '-C', str(repo), 'ls-files', '-z', '--', str(root)],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    if out.returncode != 0:
        raise Unusable(f'not a git repository, or {root} is outside it: {repo}')
    for name in filter(None, out.stdout.split('\0')):
        yield repo / name


def wanted(path: Path, root: Path):
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if path.suffix.lower() not in SOURCE_EXT or SKIP_PARTS & set(rel.parts[:-1]):
        return None
    if path.is_symlink() or not path.is_file():
        return None
    return rel.as_posix()


def python_comment_spans(text: str):
    """(comment columns per line, docstring lines), or None when the file does not parse."""
    if re.search(r'\r(?!\n)', text):
        return None      # a lone CR is a line to this script and not to the tokenizer: leave the file alone
    try:
        tree = ast.parse(text)
        comments = defaultdict(list)
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                comments[tok.start[0]].append((tok.start[1], tok.end[1]))
    except (SyntaxError, ValueError, tokenize.TokenError, RecursionError):
        return None
    doc = set()
    if '__doc__' in text:
        return comments, doc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str) and '>>>' not in first.value.value):
                doc.update(range(first.lineno, first.end_lineno + 1))
    return comments, doc


def comment_lines(path: Path, lines):
    """Line numbers that are whole-line comments in a non-Python file. Errs towards fewer."""
    ext = path.suffix.lower()
    out, in_block, backticks, heredoc, scalar_indent = set(), False, 0, None, None
    in_script = ext != '.vue'
    for n, line in enumerate(lines, 1):
        body = line.strip()
        indent = len(line) - len(line.lstrip(' '))
        if ext == '.vue':
            if re.match(r'<script\b', body):
                in_script = True
            elif body.startswith('</script'):
                in_script = False
        if heredoc is not None:
            if re.match(rf'{re.escape(heredoc)}\b', body):
                heredoc = None
            continue
        if scalar_indent is not None:
            if body and indent <= scalar_indent:
                scalar_indent = None
            else:
                continue
        inside_template = backticks % 2 == 1
        backticks += line.count('`')
        if ext in ('.yml', '.yaml') and BLOCK_SCALAR.search(line.rstrip('\r\n')) and not body.startswith('#'):
            scalar_indent = indent
            continue
        opener = HEREDOC if ext == '.php' else SH_HEREDOC if ext in ('.sh', '.rb') else None
        m = opener.search(line) if opener and not body.startswith('#') else None
        if m:
            heredoc = m.group(1)
            continue
        if inside_template or not in_script:
            if body.startswith('<!--') and ext == '.vue':
                out.add(n)
            continue
        if in_block:
            out.add(n)
            if '*/' in body:
                in_block = False
            continue
        if body.startswith('/*'):
            out.add(n)
            in_block = '*/' not in body
        elif body.startswith('//') and ext != '.sql':
            out.add(n)
        elif body.startswith('#') and ext in HASH_EXT:
            out.add(n)
        elif body.startswith('--') and ext == '.sql':
            out.add(n)
    return out


def in_comment(path: Path, lineno: int, span, ctx):
    if ctx is None:
        return False
    if path.suffix.lower() == '.py':
        comments, doc = ctx
        return lineno in doc or any(a <= span[0] and span[1] <= b for a, b in comments.get(lineno, ()))
    return lineno in ctx


def judge_line(line: str, features, owners_of):
    """Every citation on the line as (verdict, shown text, span, standard form or None)."""
    out, taken = [], []

    def free(span):
        return not any(a < span[1] and span[0] < b for a, b in taken)

    for m in CANONICAL.finditer(line):
        taken.append(m.span())
        good = m.group(2) in features.get(m.group(1), ())
        out.append(('ok' if good else 'dead', m.group(0), m.span(), None))
    for m in DASHED.finditer(line):
        feature, local = m.group(2), f'{m.group(1)}-{m.group(3)}'
        if not free(m.span()):
            continue
        taken.append(m.span())
        if local in features.get(feature, ()):
            out.append(('legacy', m.group(0), m.span(), f'{feature}/{local}'))
        else:
            out.append(('undefined', m.group(0), m.span(), None))
    named = set(OWNER.findall(line))
    for m in ADJACENT.finditer(line):
        if free(m.span()) and m.group(2) in features.get(m.group(1), ()):
            taken.append(m.span())
            out.append(('legacy', m.group(0), m.span(), f'{m.group(1)}/{m.group(2)}'))
    for m in BARE.finditer(line):
        if not free(m.span()):
            continue
        ident = m.group(1)
        if named:
            hit = [n for n in named if ident in features.get(n, ())]
            if len(hit) == 1:
                out.append(('legacy', ident, m.span(), f'{hit[0]}/{ident}'))
            else:
                out.append(('undefined', ident, m.span(), None))
            continue
        count = len(owners_of.get(ident, ()))
        out.append(('unique' if count == 1 else 'contested' if count else 'undefined', ident, m.span(), None))
    return out


CONNECTOR = re.compile(r'\s*(?:,|&|\+|\band\b|\bor\b|\bvà\b)\s*')


def fixable(line: str, judged, dashed: bool):
    """The rewrites for this line, or [] unless the line names one owner for every id on it.

    A bare id takes the owner only from text that touches it: `FR-001 (spec 002)`, or a list
    that continues a citation already owned (`spec 001 FR-001 and FR-002`). An owner named
    elsewhere on the line may belong to another sentence.
    """
    if NEGATED.search(line):
        return []
    owners = set(OWNER.findall(line))
    edits, previous_end = [], None
    for verdict, text, span, new in sorted(judged, key=lambda j: j[2]):
        if verdict == 'ok':
            owners.add(text[:3])
            previous_end = span[1]
            continue
        if new is None:
            return []
        if DASHED.fullmatch(text) and not dashed:
            return []
        if BARE.fullmatch(text):
            after = re.match(r'\s*\(\s*specs?[ \t#/_-]*(\d{3})(?!\d)', line[span[1]:], re.I)
            listed = previous_end is not None and CONNECTOR.fullmatch(line[previous_end:span[0]])
            if not (listed or (after and after.group(1) == new[:3])):
                return []
        owners.add(new[:3])
        if line[span[1]:span[1] + 1] == '/' or re.match(r'\s*(?:\.\.|…|–|-\s*(?:\d|FR|SC)|to\s+(?:\d|FR|SC|§))', line[span[1]:]):
            return []   # a list or a range runs on: its other ids are not on record
        edits.append((span, new))
        previous_end = span[1]
    return edits if len(owners) == 1 else []


def scan(repo: Path, root: Path, features, paths, dashed=False):
    owners_of = defaultdict(set)
    for number, ids in features.items():
        for ident in ids:
            owners_of[ident].add(number)
    found, edits, tested, ignored, done = [], {}, set(), 0, set()
    for path in paths:
        rel = wanted(path, root)
        if rel is None:
            continue
        real = path.resolve()     # after `wanted`: Python 3.9 on Windows raises on a link it cannot follow
        if real in done:
            continue
        done.add(real)
        raw = path.read_bytes()
        try:
            text, editable = raw.decode('utf-8'), True
        except UnicodeDecodeError:
            text, editable = raw.decode('utf-8', errors='replace'), False
        lines = LINES.findall(text)
        if any(PRAGMA in l for l in lines[:PRAGMA_WINDOW]):
            ignored += 1
            continue
        is_test = bool(TEST_PATH.search(rel))
        ctx = False
        for i, line in enumerate(lines):
            if 'FR-' not in line and 'SC-' not in line:
                continue
            judged = judge_line(line, features, owners_of)
            for verdict, shown, span, new in judged:
                found.append((verdict, rel, i + 1, shown))
                if is_test and verdict in RESOLVED:
                    target = new or shown
                    if '/' in target:
                        tested.add(tuple(target.split('/', 1)))
                    elif verdict == 'unique':
                        tested.add((next(iter(owners_of[shown])), shown))
            if not editable:
                continue
            todo = fixable(line, judged, dashed)
            if not todo:
                continue
            if ctx is False:
                ctx = python_comment_spans(text) if path.suffix.lower() == '.py' else comment_lines(path, lines)
            if all(in_comment(path, i + 1, span, ctx) for span, _ in todo):
                edits.setdefault(path, []).extend((i, span, new) for span, new in todo)
    return found, edits, tested, ignored


def apply(edits, dry_run, repo=None):
    changed = 0
    if not dry_run:
        # All or none: a file that cannot be written is found before the first one is.
        for path in sorted(edits):
            if not path.stat().st_mode & 0o222:
                raise PermissionError(13, 'the file is read-only, so no file was rewritten', str(path))
    planned = []
    for path, items in sorted(edits.items()):
        try:
            shown = path.relative_to(repo).as_posix()
        except (TypeError, ValueError):
            shown = path.name
        old = path.read_bytes()
        lines = LINES.findall(old.decode('utf-8'))
        for i, span, new in sorted(items, key=lambda e: (e[0], -e[1][0])):
            before = lines[i]
            lines[i] = before[:span[0]] + new + before[span[1]:]
            changed += 1
            if dry_run:
                print(f'  {shown}:{i + 1}  {before[span[0]:span[1]]}  ->  {new}')
        planned.append((path.resolve(), old, ''.join(lines).encode('utf-8')))
    if not dry_run:
        written = []
        try:
            for real, old, new in planned:
                # One step, and through a link to the file it names: never a half-written source file.
                kit_spec.replace(real, new)
                written.append((real, old))
        except BaseException:
            # All or none: a file another program holds stops the run, and what was written goes back.
            for real, old in written:
                try:
                    kit_spec.replace(real, old)
                except Exception:
                    print(f'  {real}: rewritten, and could not be put back', file=sys.stderr)
            raise
    return changed


def print_group(found, verdict, limit=40):
    rows = [f for f in found if f[0] == verdict]
    for _, rel, line, text in rows[:limit]:
        print(f'  {verdict:<9} {rel}:{line}  {text}')
    if len(rows) > limit:
        print(f'  ... and {len(rows) - limit} more {verdict}')


def _main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--repo', default='.')
    ap.add_argument('--root', default=None, help='project root (holds specs/); default: the repo')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--report', action='store_true')
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--write-baseline', action='store_true')
    mode.add_argument('--touched', nargs='+', metavar='FILE')
    mode.add_argument('--fix', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--dashed', action='store_true', help='with --fix: also rewrite FR-063-003')
    ap.add_argument('--allow-rise', action='store_true', help='with --write-baseline: accept a higher count')
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    root = (repo / args.root).resolve() if args.root else repo
    features = registry(root)
    if not features:
        if args.touched:
            return 0
        print(f'no feature under {root}/specs or {root}/.specify/specs: nothing to judge')
        return 2

    if args.touched:
        paths = [(Path.cwd() / f).resolve() for f in args.touched]
        found, *_ = scan(repo, root, features, paths)
        for verdict in ('dead', 'contested', 'undefined'):
            print_group(found, verdict)
        return 0

    found, edits, tested, ignored = scan(repo, root, features, tracked(repo, root), args.dashed)
    counts = Counter(v for v, *_ in found)
    counts['ignored_files'] = ignored

    if args.fix:
        n = apply(edits, args.dry_run, repo)
        print(f'{"would rewrite" if args.dry_run else "rewrote"} {n} citation(s) in {len(edits)} file(s) to NNN/ID')
        return 0

    declared = sum(len(ids) for ids in features.values())
    untested = sorted((n, i) for n, ids in features.items() for i in ids if (n, i) not in tested)
    summary = ' '.join(f'{k}={counts.get(k, 0)}' for k in ('ok', 'legacy', 'unique', 'contested', 'undefined', 'dead'))
    print(f'{len(found)} citation(s) against {declared} requirement(s) in {len(features)} feature(s): '
          f'{summary} ignored_files={ignored}')

    base_path = specs_dir(root) / '.kit-refs-baseline.json'
    try:
        baseline = json.loads(base_path.read_text(encoding='utf-8')) if base_path.is_file() else {}
        if not isinstance(baseline, dict):
            raise ValueError
        baseline = {k: int(baseline.get(k, 0)) for k in COUNTED}
    except (OSError, ValueError, TypeError):
        print(f'{base_path.name} is not a JSON object of counts')
        return 2

    if args.write_baseline:
        risen = [k for k in COUNTED if base_path.is_file() and counts.get(k, 0) > baseline[k]]
        if risen and not args.allow_rise:
            print(f'refused: {", ".join(risen)} would rise above the recorded baseline; fix the citations, '
                  f'or pass --allow-rise and say why in the pull request')
            return 1
        kit_spec.replace(base_path, (json.dumps({k: counts.get(k, 0) for k in COUNTED}, indent=2) + '\n').encode('utf-8'))
        print(f'baseline written: {base_path.relative_to(repo).as_posix()}')
        return 0

    if args.report:
        for verdict in ('dead', 'contested', 'undefined', 'legacy'):
            print_group(found, verdict)
        print(f'WARN {len(untested)} requirement(s) cited by no test file')
        for n, i in untested[:40]:
            print(f'  untested  {n}/{i}')
        if len(untested) > 40:
            print(f'  ... and {len(untested) - 40} more')

    failed = False
    if counts.get('dead'):
        failed = True
        print(f'FAIL {counts["dead"]} citation(s) in the standard form point at nothing')
        if args.check:
            print_group(found, 'dead')
    for key in COUNTED:
        now = counts.get(key, 0)
        if now > baseline[key]:
            failed = True
            print(f'FAIL {key}: {now} now, baseline {baseline[key]}')
            if args.check:
                print_group(found, key, limit=15)
        elif now < baseline[key]:
            print(f'NOTE {key}: {now} now, baseline {baseline[key]}; run --write-baseline to keep the gain')
    if args.check:
        print(f'WARN {len(untested)} requirement(s) cited by no test file')
    return 1 if failed and args.check else 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError, OSError):
        pass
    try:
        return _main(argv)
    except Unusable as e:
        print(e)
        return 2
    except SystemExit:
        raise
    except BrokenPipeError:   # the reader closed the pipe (`| head`)
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except Exception as e:   # a crash must not read as "worse than baseline"
        print(f'spec_refs.py could not finish: {type(e).__name__}: {e}')
        return 2


if __name__ == '__main__':
    sys.exit(main())
