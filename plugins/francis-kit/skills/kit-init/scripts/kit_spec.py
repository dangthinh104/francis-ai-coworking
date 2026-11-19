"""How every kit script reads a spec.md: one definition, so two scripts cannot disagree.

Imported by kit_doctor.py, spec_index.py, spec_lint.py and spec_refs.py. Not a command.
Also the one way a script replaces a file it rewrites (`replace`).
"""
import os
import re
import shutil
import tempfile

FEATURE_DIR = re.compile(r'^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*$')
STATUSES = ['Draft', 'Approved', 'Built', 'Released', 'Closed']
ENDED = ['Superseded', 'Dropped']          # terminal, outside the progression
# Front matter starts with a key; a spec that merely opens with a `---` rule has none.
FRONTMATTER = re.compile(r'\A---\n(?=(?:[ \t]*#[^\n]*\n)*[A-Za-z_][\w-]*:).*?\n---\n', re.S)
OPEN_FENCE = re.compile(r'[ \t]*(`{3,}|~{3,})[^`\n]*')


class _Fences:
    """Removes code blocks. Used as `FENCE.sub('', text)`.

    A block is an opening line that holds nothing but the fence and a language (it may be
    indented, inside a list) up to a closing line of the same fence. A line that merely
    starts with inline ```code``` opens nothing, and a fence nobody closed hides nothing:
    dropping the rest of the file would drop its requirements and its open tasks without a
    word. One pass over the lines, so a file of ten thousand openers costs what it weighs.
    """

    @staticmethod
    def sub(_replacement, text, keep_lines=False):
        """`keep_lines` leaves one empty line per line removed, so line numbers still hold."""
        lines = text.split('\n')
        closers = {}            # fence -> indexes of the lines that can close it, descending
        for i in range(len(lines) - 1, -1, -1):
            token = lines[i].strip()
            if token and token[0] in '`~' and len(token) >= 3 and not token.strip('`~'):
                for size in range(3, len(token) + 1):
                    if token.startswith(token[0] * size) and set(token[size:]) <= set('`~'):
                        closers.setdefault(token[0] * size, []).append(i)
        out, i = [], 0
        while i < len(lines):
            m = OPEN_FENCE.fullmatch(lines[i])
            if m:
                later = closers.get(m.group(1), [])
                while later and later[-1] <= i:
                    later.pop()
                if later:
                    out.extend([''] * (later[-1] + 1 - i if keep_lines else 1))
                    i = later[-1] + 1
                    continue
            out.append(lines[i])
            i += 1
        return '\n'.join(out)


FENCE = _Fences()
COMMENT = re.compile(r'<!--.*?-->', re.S)
CODE_SPAN = re.compile(r'`[^`\n]*`')
ID = r'(?:FR|SC)-[A-Z]?\d+(?:\.\d+)*'
# A line declares its first id only when a marker stands before it: a list or heading marker, a
# table bar, or `**` at the start. A paragraph that opens with an id recalls it (024/FR-001).
DEFINITION = re.compile(
    rf'^[ \t]*(?:(?:#{{1,6}}[ \t]*|[-*][ \t]+|\d+\.[ \t]+|\|[ \t]*)\**|\*\*+)[ \t]*({ID})(?![\w.-]*\d)', re.M)
REMOVED = re.compile(r'^##[ \t]+Removed[ \t]*$.*?(?=^##[ \t]|\Z)', re.M | re.S | re.I)


def read(path):
    """The text of a file with one kind of line ending and no BOM, or None."""
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding='utf-8-sig', errors='replace')    # text mode already gives `\n`
    except OSError:
        return None


def body(text):
    """A spec without front matter and code blocks: where requirements are declared."""
    return FENCE.sub('', FRONTMATTER.sub('', text))


def prose(text):
    """`body` without code spans and comments: where Status and Ticket lines count.

    Code spans go first, so a `<!--` quoted in a sentence opens no comment.
    """
    return COMMENT.sub('', CODE_SPAN.sub('``', body(text)))


def fields(name, text):
    """Every value of a `**Name**: value` line in the prose of a spec."""
    return re.findall(rf'^\*\*{re.escape(name)}\*\*:[ \t]*(.+?)[ \t]*$', prose(text), re.M)


def status(text):
    """The Status of a spec, or None unless exactly one Status line holds a valid value.

    A Status line is one word after the colon. `**Status**: done in PR 12` further down
    is a sentence, not a second status.
    """
    found = [value for value in fields('Status', text) if not re.search(r'\s', value)]
    return found[0] if len(found) == 1 and found[0] in STATUSES + ENDED else None


def requirements(text):
    """Ids a spec declares today: `## Removed` and code blocks declare nothing."""
    return set(DEFINITION.findall(REMOVED.sub('', body(text))))


def replace(path, body):
    """Put `body` (bytes) at `path` in one step: a failed write leaves the old file and no leftover.

    The temporary file gets a fresh, unpredictable name beside the target, so a planted file
    or symlink is never written through.
    """
    # A file nobody may write is refused by its own name, on every system: a rename would
    # go through on POSIX and fail on Windows, there with the temporary name in the error.
    if path.is_file() and not path.stat().st_mode & 0o222:
        raise PermissionError(13, 'the file is read-only', str(path))
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
            os.chmod(tmp, 0o644)      # Windows does not delete a read-only file
            os.unlink(tmp)
