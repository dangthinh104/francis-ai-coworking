#!/usr/bin/env python3
"""Heuristic comment audit for source, config and CI files.

It sees whole-line comments (`#`, `//`, `--`), block comments (`/* */`,
`<!-- -->`, `{{-- --}}`) and dates in those and in trailing comments. It
does not see docstrings. Markdown is skipped. Findings are places to
look, not a verdict.
"""
import argparse
import re
import sys
from collections import Counter

LINE_COMMENT = re.compile(r'^\s*(#|//|--\s)')
# Where `#` opens no comment: an id selector in a stylesheet, a private field in JavaScript,
# a slot in a template.
NO_HASH = ('.css', '.scss', '.sass', '.less', '.styl', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts',
           '.vue', '.svelte', '.html', '.htm', '.xhtml', '.erb', '.blade.php', '.astro', '.pcss', '.postcss')
TRAILING_SLASHES = re.compile(r'\s//\s(.*)$')
PREPROCESSOR = re.compile(r'^\s*#\s*(include|define|undef|if|ifdef|ifndef|elif|else|endif|'
                          r'pragma|region|endregion|import|error|warning)\b|^#!|^\s*#\[')
TRAILING = re.compile(r'\s(?:#|//)\s(.*)$')
# ISO, day/month/year and day/month dates. A lone `3/5` is a ratio, so the
# two-part form needs a two-digit month.
DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}/(?:0[1-9]|1[0-2])\b(?!/)')

MAX_RATIO = 0.30
MIN_LINES_FOR_RATIO = 40
MAX_BLOCK = 3
MAX_DATES = 0
MAX_DUPES = 0


BLOCKS = (('/*', '*/'), ('<!--', '-->'), ('{{--', '--}}'))


def comment_flags(lines, hash_comments=True):
    """True for each line that is a whole-line comment."""
    flags, closer = [], None
    for line in lines:
        stripped = line.strip()
        if closer:
            flags.append(True)
            if closer in stripped:
                closer = None
            continue
        for opener, end in BLOCKS:
            if stripped.startswith(opener):
                flags.append(True)
                if end not in stripped[len(opener):]:
                    closer = end
                break
        else:
            flags.append(bool(LINE_COMMENT.match(line))
                         and not PREPROCESSOR.match(line)
                         and (hash_comments or not stripped.startswith('#')))
    return flags


def audit(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        lines = fh.read().splitlines()
    hash_comments = not str(path).lower().endswith(NO_HASH)
    flags = comment_flags(lines, hash_comments)
    body = [(l, f) for l, f in zip(lines, flags) if l.strip()]
    comments = [l for l, f in body if f]
    longest = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    dated = sum(1 for l in comments if DATE.search(l))
    for line, flag in body:
        if not flag:
            m = (TRAILING if hash_comments else TRAILING_SLASHES).search(line)
            if m and DATE.search(m.group(1)):
                dated += 1
    texts = Counter(l.strip() for l in comments if len(l.strip()) > 20)
    return {
        'lines': len(body),
        'comments': len(comments),
        'ratio': len(comments) / len(body) if body else 0.0,
        'dated': dated,
        'duplicated': sum(n - 1 for n in texts.values() if n > 1),
        'longest_block': longest,
    }


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('--strict', action='store_true',
                    help='exit 1 when a file is over a limit')
    args = ap.parse_args(argv)
    failed = False
    audited = markdown = 0
    for path in args.files:
        if path.lower().endswith(('.md', '.markdown')):
            print(f'{path}: skipped (Markdown)')
            markdown += 1
            continue
        try:
            r = audit(path)
        except OSError as exc:
            print(f'{path}: skipped ({exc.strerror})')
            continue
        over = [name for name, value, limit in (
            # In a short file one needed explanation is already a large share: the ratio says nothing there.
            ('ratio', r['ratio'] if r['lines'] >= MIN_LINES_FOR_RATIO else 0.0, MAX_RATIO),
            ('longest_block', r['longest_block'], MAX_BLOCK),
            ('dated', r['dated'], MAX_DATES),
            ('duplicated', r['duplicated'], MAX_DUPES),
        ) if value > limit]
        failed = failed or bool(over)
        audited += 1
        print(f"{path}: lines={r['lines']} comments={r['comments']} "
              f"ratio={r['ratio']:.0%} dated={r['dated']} "
              f"duplicated={r['duplicated']} longest_block={r['longest_block']}"
              + (f"  OVER: {', '.join(over)}" if over else '  ok'))
    if not audited and markdown < len(args.files):   # only Markdown given: nothing to audit, not a failure
        print('no file was audited', file=sys.stderr)
        return 2
    return 1 if args.strict and failed else 0


if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):   # a Windows console is not UTF-8 by default
        try:
            _stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:      # a crash is "nothing was checked", never a verdict
        print(f'comment_audit.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
