"""Before an Edit or Write makes a spec Approved, ask the person (spec 025).

Claude Code runs this before each Edit and Write, with the call as JSON on standard input.
It prints an `ask` decision or nothing, and always exits 0: it never allows and never blocks.
"""
import importlib.util
import json
import os
import posixpath
import re
import sys
from pathlib import Path

REASON = ('Only a person approves a spec. Confirm only if you just answered the approval question that names '
          '{feature}, its number of requirements and that no open question is left. A go-ahead given before that '
          'question, or a write by a subagent, is not an approval.')
FAILED = 'francis-kit could not check this write ({error}): confirm only if it is not an approval you have not given'
# kit_spec.FEATURE_DIR, to tell a spec path before kit_spec is loaded (and when it cannot be).
FALLBACK_FEATURE_DIR = re.compile(r'^(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*$')
IGNORE_CASE = sys.platform in ('win32', 'darwin')


def ask(reason):
    print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'ask',
                                             'permissionDecisionReason': reason}}))


def the_call(raw):
    """(tool, input, path) of an Edit or Write that holds the fields it needs, else None."""
    data = json.loads(raw)
    tool = data.get('tool_name')
    fields = data.get('tool_input')
    if tool not in ('Edit', 'Write') or not isinstance(fields, dict):
        return None
    needed = ('file_path', 'old_string', 'new_string') if tool == 'Edit' else ('file_path', 'content')
    if not all(isinstance(fields.get(name), str) for name in needed):
        return None
    path = fields['file_path'].replace('\\', '/')
    cwd = data.get('cwd')
    if not (path.startswith('/') or re.match(r'^[A-Za-z]:/', path)):
        path = posixpath.join((cwd if isinstance(cwd, str) else os.getcwd()).replace('\\', '/'), path)
    return tool, fields, posixpath.normpath(path)


def feature_of(path, feature_dir):
    """The feature directory's name when `path` is a spec path, else None."""
    parts = path.split('/')
    if len(parts) < 3:
        return None
    specs, feature, name = parts[-3:]
    if IGNORE_CASE:
        specs, name = specs.lower(), name.lower()
    matched = feature_dir.match(feature.lower() if IGNORE_CASE else feature)
    return feature if specs == 'specs' and name == 'spec.md' and matched else None


def load_kit_spec():
    root = os.environ.get('CLAUDE_PLUGIN_ROOT') or str(Path(__file__).resolve().parents[1])
    scripts = os.path.join(root, 'skills', 'kit-init', 'scripts', 'kit_spec.py')
    spec = importlib.util.spec_from_file_location('kit_spec', scripts)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def plain(text):
    """As universal newlines read a file: CRLF, then a lone CR, become LF."""
    return (text[1:] if text.startswith('\ufeff') else text).replace('\r\n', '\n').replace('\r', '\n')


def text_after(tool, fields, before):
    if tool == 'Write':
        return plain(fields['content'])
    old, new = plain(fields['old_string']), plain(fields['new_string'])
    if old == '':
        return new + before
    if old not in before:
        return new
    return before.replace(old, new, -1 if fields.get('replace_all') is True else 1)


def decide(kit_spec, tool, fields, path, feature):
    target = Path(path)
    if target.exists():
        before = kit_spec.read(target) if target.is_file() else None
        if before is None:
            return                         # a directory, or a file that cannot be opened
    else:
        before = ''
    after = text_after(tool, fields, before)
    if 'Approved' in kit_spec.fields('Status', after) and 'Approved' not in kit_spec.fields('Status', before):
        ask(REASON.format(feature=feature))


def main():
    try:
        call = the_call(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
    except Exception:
        return
    if call is None:
        return
    tool, fields, path = call
    try:
        if not feature_of(path, FALLBACK_FEATURE_DIR):
            return                         # not a spec: an ordinary edit pays for no import
    except Exception:
        return
    try:
        kit_spec = load_kit_spec()
    except Exception as exc:
        ask(FAILED.format(error=f'{type(exc).__name__}: {exc}'))
        return
    try:
        feature = feature_of(path, kit_spec.FEATURE_DIR)
    except Exception:
        return
    if feature is None:
        return
    try:
        decide(kit_spec, tool, fields, path, feature)
    except Exception as exc:
        ask(FAILED.format(error=f'{type(exc).__name__}: {exc}'))


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        pass
    sys.exit(0)
