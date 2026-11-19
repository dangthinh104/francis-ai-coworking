#!/usr/bin/env python3
"""Flag user-facing strings that read like a machine wrote them.

    copy_audit.py PATH [PATH ...] [--strict]

PATH is a locale file (.json, .php, .yml, .yaml, .js, .ts) or a directory of them.

Flags
    stock      a short string built on a phrase that says nothing ("Lưu thành công",
               "Đã xảy ra lỗi", "Failed to save"); a longer sentence is left alone
    internal   something from the code on screen: a status code, a snake_case name, null
    shout      an exclamation mark, or words in capitals
    long       over 60 characters where the key starts or ends with toast, button,
               label, title or action

It also counts how often "vui lòng" / "please" appear: one is polite, one per
line is a tic.

A heuristic for ranking files and comparing before with after. It cannot tell
whether a sentence sounds natural; a person who speaks the language reads a
sample. A file it could not parse is reported, not skipped silently.
Exit 0; 1 with --strict when anything is flagged; 2 when no string was found.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

STOCK = [
    r'thành công', r'thất bại', r'đã xảy ra lỗi', r'có lỗi xảy ra', r'lỗi hệ thống', r'^lỗi khi\b', r'không hợp lệ',
    r'thử lại sau', r'^không thể\b', r'^lỗi\b', r'không tìm thấy dữ liệu', r'không tìm thấy dữ liệu', r'bạn có chắc', r'thực hiện (?:thao tác|hành động)',
    r'something went wrong', r'an error (?:has )?occurred', r'try again later', r'^failed to\b', r'\binvalid\b',
    r'successful', r'\boops\b', r'^no data\b', r'are you sure', r'^(?:\w+ )?not found\.?$', r'^error\b',
    r"une erreur (?:s'est produite|est survenue)", r'réessayer plus tard', r'avec succès', r'êtes-vous sûr',
]
INTERNAL = [r'\b(?:null|undefined|NaN)\b', r'\b[a-z]+_[a-z_]+\b',
            r'(?i:\b(?:lỗi|error|code|mã|http|status)\b\s*:?\s*)[45]\d\d\b',
            r'(?i:\b(?:payload|endpoint|exception|stack ?trace|metadata)\b)']
STOCK_MAX_WORDS = 9   # a longer sentence that contains a stock phrase usually says something more
TIC = re.compile(r'vui lòng|\bplease\b|veuillez', re.I)
SHORT_KEY = re.compile(r'^(?:toast|button|btn|label|title|action)s?$', re.I)
PLACEHOLDER = re.compile(r'\{[^}]*\}|:[a-z_]+\b|%\w|@:[\w.]+')
PHP_ITEM = re.compile(r'''(['"])((?:\\.|(?!\1).)*)\1\s*=>\s*(?:(\[)|(['"])((?:\\.|(?!\4).)*)\4)''')
PHP_COMMENT = re.compile(r'^\s*(?://|#|\*|/\*).*$', re.M)
JS_PAIR = re.compile(r'''(?:^|[{,\s])['"]?([\w.-]+)['"]?\s*:\s*(['"`])((?:\\.|(?!\2).)*)\2''')
YAML_PAIR = re.compile(r'''^\s*([\w.-]+):\s*(['"]?)(.+?)\2\s*(?:#.*)?$''')
EXT = {'.json', '.php', '.yml', '.yaml', '.js', '.ts'}
LOCALE = re.compile(r'[a-z]{2}(?:[-_][A-Za-z]{2})?')


def flatten(node, prefix=''):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from flatten(v, f'{prefix}{k}.')
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from flatten(v, f'{prefix}{i}.')
    elif isinstance(node, str):
        yield prefix.rstrip('.'), node


def strings(path: Path):
    """(key, text) pairs, or None when the file could not be parsed."""
    text = path.read_text(encoding='utf-8-sig', errors='replace')
    if path.suffix == '.json':
        try:
            return list(flatten(json.loads(text)))
        except ValueError:
            return None
    if path.suffix == '.php':
        out, outer = [], ''
        for m in PHP_ITEM.finditer(PHP_COMMENT.sub('', text)):
            if m.group(3):
                outer = m.group(2)
            elif LOCALE.fullmatch(m.group(2)) and outer:
                out.append((f'{outer}.{m.group(2)}', m.group(5)))
            else:
                out.append((m.group(2), m.group(5)))
        return out
    if path.suffix in ('.js', '.ts'):
        return [(m.group(1), m.group(3)) for m in JS_PAIR.finditer(text)
                if not m.group(3).startswith(('/', 'http', '#', '.'))]
    out = []
    for line in text.splitlines():
        m = YAML_PAIR.match(line)
        if m and not m.group(3).startswith(('{', '[', '|', '>', '#')):
            out.append((m.group(1), m.group(3)))
    return out


# `error` is not in the list: `status.error` and `level.error` are labels far more often than messages.
MESSAGE_KEY = re.compile(r'(?:^|[._-])(?:toast|message|msg|alert|notif\w*|flash|snackbar)(?:[._-]|$)', re.I)


def flags(key: str, value: str, display=()):
    """`display` holds key prefixes of copy that is a picture, not a control: a heading
    set in capitals, a venue's name, a greeting on a generated image. Tone rules
    (`stock`, `shout`) do not apply there; a leaked internal name still does."""
    # NFC: the same Vietnamese text typed on another keyboard is the same text.
    plain = unicodedata.normalize('NFC', PLACEHOLDER.sub(' ', value)).strip()
    shown = any(key == p or key.startswith(p.rstrip('.') + '.') for p in display)
    out = []
    words = plain.split()
    # One word (`Lỗi` on a status chip) is a label, unless the key says it is the whole message.
    enough = len(words) >= 2 or MESSAGE_KEY.search(key)
    if not shown and enough and len(words) <= STOCK_MAX_WORDS and any(re.search(p, plain, re.I) for p in STOCK):
        out.append('stock')
    if any(re.search(p, plain) for p in INTERNAL):
        out.append('internal')
    # Two long words in capitals, or three of any length: Vietnamese syllables are short
    # (`CẢNH BÁO XÓA TẤT CẢ`), so length alone misses them.
    caps = [w.isalpha() and w.isupper() and len(w) >= 2 for w in words]
    long_caps = [c and len(w) >= 4 for c, w in zip(caps, words)]
    loud = (any(a and b for a, b in zip(long_caps, long_caps[1:]))
            or any(a and b and c for a, b, c in zip(caps, caps[1:], caps[2:])))
    if not shown and ('!' in plain or loud):
        out.append('shout')
    parts = [s for s in re.split(r'[._-]', key) if not LOCALE.fullmatch(s)]
    if len(plain) > 60 and (any(SHORT_KEY.match(s) for s in parts[-1:]) or (parts[:1] and SHORT_KEY.match(parts[0]))):
        out.append('long')
    return out


def collect(paths):
    files = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.rglob('*') if f.suffix in EXT and f.is_file())
        elif p.is_file() and p.suffix in EXT:
            files.append(p)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+', type=Path)
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--display', action='append', default=[], metavar='KEY_PREFIX',
                    help='keys under this prefix are display copy (image text, headings): '
                         'tone rules are not applied; repeatable')
    args = ap.parse_args(argv)
    total = flagged = tics = 0
    files = collect(args.paths)
    for f in files:
        pairs = strings(f)
        if pairs is None:
            print(f'{f}: unparsed, check by hand')
            continue
        total += len(pairs)
        tics += sum(1 for _, v in pairs if TIC.search(v))
        rows = [(k, found, v) for k, v in pairs for found in [flags(k, v, args.display)] if found]
        if rows:
            flagged += len(rows)
            print(f'{f}: {len(rows)} flagged')
            for key, found, value in rows[:25]:
                print(f'  {",".join(found):<15} {key}: {value[:90]}')
            if len(rows) > 25:
                print(f'  ... and {len(rows) - 25} more')
    if not total:
        print('no string found')
        return 2
    print(f'{flagged} of {total} string(s) flagged in {len(files)} file(s); "vui lòng"/"please" in {tics}')
    return 1 if flagged and args.strict else 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError, OSError):
        pass
    try:
        sys.exit(main())
    except Exception as exc:      # a crash is "nothing was checked", never a verdict
        print(f'copy_audit.py could not finish: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(2)
