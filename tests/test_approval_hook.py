"""The plugin's hook asks the person before an Edit or Write makes a spec Approved (spec 025)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from test_gate_hook import SHELLS, WINDOWS, script

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / 'plugins' / 'francis-kit'
HOOKS = PLUGIN / 'hooks'
COMMAND = ('for p in python3 python; do if command -v "$p" >/dev/null 2>&1 && "$p" -c "" </dev/null >/dev/null 2>&1; '
           'then "$p" "${CLAUDE_PLUGIN_ROOT}/hooks/guard.py"; exit 0; fi; done; exit 0')
REASON = ('Only a person approves a spec. Confirm only if you just answered the approval question that names '
          '{feature}, its number of requirements and that no open question is left. A go-ahead given before that '
          'question, or a write by a subagent, is not an approval.')
FAILED = re.compile(r'francis-kit could not check this write \((\w+): (.+)\): '
                    r'confirm only if it is not an approval you have not given')
IGNORES_CASE = sys.platform in ('win32', 'darwin')
SPEC = ('# Feature Specification: An invented feature\n\n'
        '**Status**: Draft\n**Ticket**: none\n\n'
        '## Requirements\n\n- **FR-001**: The widget MUST turn blue.\n')
APPROVED_SPEC = SPEC.replace('**Status**: Draft', '**Status**: Approved')
# A closed fence above the real line holds the first `**Status**: Draft`: only replace_all reaches the real one.
FENCED_DRAFT = '```text\n**Status**: Draft\n```\n\n' + SPEC
RUNS = []                           # (exit status, standard output) of every check, for SC-008


def record(done):
    out = done.stdout.decode('utf-8')
    RUNS.append((done.returncode, out))
    assert done.returncode == 0 and '"allow"' not in out, (done.returncode, out, done.stderr.decode('utf-8'))
    return out


def make_repo(tmp):
    r = tmp / 'r'
    (r / 'specs' / '007-x').mkdir(parents=True)
    (r / 'specs' / '007-x' / 'spec.md').write_bytes(SPEC.encode('utf-8'))
    return r


def spec_of(r, feature='007-x'):
    return r / 'specs' / feature / 'spec.md'


def guard(r, tool_input=None, tool='Edit', raw=None, root=PLUGIN, root_var=None):
    """The guard of `root`, with the input's cwd `r` and the process in another directory.

    `root_var` is what CLAUDE_PLUGIN_ROOT holds: `root` by default, '' for empty, False for unset.
    """
    payload = raw if raw is not None else json.dumps(
        {'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': tool_input, 'cwd': str(r)})
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_PLUGIN_ROOT'}
    if root_var is not False:
        env['CLAUDE_PLUGIN_ROOT'] = str(root) if root_var is None else root_var
    return record(subprocess.run([sys.executable, str(root / 'hooks' / 'guard.py')], input=payload.encode('utf-8'),
                                 capture_output=True, env=env, cwd=r.parent))


def first_edit(r, **changed):
    edit = {'file_path': str(spec_of(r)), 'old_string': '**Status**: Draft', 'new_string': '**Status**: Approved'}
    edit.update(changed)
    return edit


def asks(out, feature):
    assert json.loads(out) == {'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'ask',
        'permissionDecisionReason': REASON.format(feature=feature)}}, out


def silent(out):
    assert out == '', out


def could_not_check(out, error):
    decision = json.loads(out)['hookSpecificOutput']
    assert decision['hookEventName'] == 'PreToolUse' and decision['permissionDecision'] == 'ask', decision
    matched = FAILED.fullmatch(decision['permissionDecisionReason'])
    assert matched and matched.group(1) == error, decision


def test_sc_001_an_edit_or_write_that_makes_the_spec_approved_asks(tmp_path):
    r = make_repo(tmp_path)
    path = str(spec_of(r))
    asks(guard(r, first_edit(r)), '007-x')
    asks(guard(r, first_edit(r, new_string='**Status**:Approved')), '007-x')
    asks(guard(r, first_edit(r, new_string='**Status**:\tApproved')), '007-x')
    asks(guard(r, first_edit(r, replace_all='yes')), '007-x')
    spec_of(r).write_bytes(FENCED_DRAFT.encode('utf-8'))
    asks(guard(r, first_edit(r, replace_all=True)), '007-x')
    spec_of(r).write_bytes(SPEC.encode('utf-8'))
    asks(guard(r, {'file_path': path, 'content': APPROVED_SPEC}, tool='Write'), '007-x')
    asks(guard(r, {'file_path': path, 'content': '\ufeff**Status**: Approved\n'}, tool='Write'), '007-x')
    asks(guard(r, first_edit(r, file_path='specs/007-x/spec.md')), '007-x')
    asks(guard(r, first_edit(r, file_path='specs/./007-x/spec.md')), '007-x')
    (r / '.claude').mkdir()
    (r / '.claude' / 'kit.yml').write_text('projects: []\n', encoding='utf-8')
    asks(guard(r, first_edit(r)), '007-x')


def test_sc_002_a_new_file_an_empty_old_string_and_an_old_string_not_found_ask(tmp_path):
    r = make_repo(tmp_path)
    asks(guard(r, {'file_path': str(spec_of(r, '008-y')), 'content': APPROVED_SPEC}, tool='Write'), '008-y')
    asks(guard(r, first_edit(r, file_path=str(r / 'app' / 'specs' / '009-z' / 'spec.md'))), '009-z')
    # The new string goes before the text with nothing between, so the spec here starts with an empty
    # line: before a heading, `**Status**: Approved# Feature...` would be no Approved line at all. It ends
    # without one, so a new string put after the text would make no Approved line either.
    spec_of(r).write_bytes(('\n' + SPEC.rstrip('\n')).encode('utf-8'))
    asks(guard(r, first_edit(r, old_string='')), '007-x')
    spec_of(r).write_bytes(SPEC.encode('utf-8'))
    asks(guard(r, first_edit(r, old_string='a line this spec does not hold')), '007-x')


def test_sc_003_a_closed_fence_hides_a_status_line_and_an_open_one_does_not(tmp_path):
    r = make_repo(tmp_path)
    spec_of(r).write_bytes((SPEC + '\n```text\n**Status**: Approved\n```\n').encode('utf-8'))
    asks(guard(r, first_edit(r)), '007-x')
    spec_of(r).write_bytes(SPEC.encode('utf-8'))
    closed = first_edit(r, old_string='**Ticket**: none', new_string='**Ticket**: none\n\n```\n**Status**: Approved\n```')
    silent(guard(r, closed))
    never_closed = first_edit(r, old_string='**Ticket**: none', new_string='**Ticket**: none\n\n```\n**Status**: Approved')
    asks(guard(r, never_closed), '007-x')


def test_sc_004_crlf_backslashes_and_case(tmp_path):
    r = make_repo(tmp_path)
    spec_of(r).write_bytes(SPEC.replace('\n', '\r\n').encode('utf-8'))
    for joined in ('\n', '\r\n'):
        edit = first_edit(r, old_string=f'**Status**: Draft{joined}**Ticket**: none',
                          new_string=f'**Status**: Approved{joined}**Ticket**: none')
        asks(guard(r, edit), '007-x')
    asks(guard(r, first_edit(r, file_path=str(spec_of(r)).replace('/', '\\'))), '007-x')
    if IGNORES_CASE:
        asks(guard(r, first_edit(r, file_path=str(r / 'Specs' / '007-x' / 'SPEC.md'))), '007-x')
    # A lone CR is a line ending too, as kit_spec.read reads the file: in new_string, content and old_string.
    asks(guard(r, first_edit(r, new_string='**Status**: Approved\r')), '007-x')
    asks(guard(r, {'file_path': str(spec_of(r)), 'content': APPROVED_SPEC.replace('\n', '\r')}, tool='Write'), '007-x')
    # Found, the new fence is closed by the last line and hides the Approved line; not found, it would not.
    spec_of(r).write_bytes((SPEC + '```\n').replace('\n', '\r').encode('utf-8'))
    silent(guard(r, first_edit(r, old_string='**Status**: Draft\r**Ticket**: none',
                                new_string='```\r**Status**: Approved')))


def test_sc_005_what_the_guard_does_not_ask(tmp_path):
    r = make_repo(tmp_path)
    (r / 'specs' / '011-a').mkdir()
    approved = spec_of(r, '011-a')
    approved.write_bytes(APPROVED_SPEC.encode('utf-8'))
    silent(guard(r, {'file_path': str(approved), 'content': APPROVED_SPEC + '\nMore.\n'}, tool='Write'))
    silent(guard(r, {'file_path': str(approved), 'old_string': '**Ticket**: none', 'new_string': '**Ticket**: T-1'}))
    silent(guard(r, {'file_path': 'specs/011-a/spec.md', 'content': APPROVED_SPEC}, tool='Write'))
    silent(guard(r, first_edit(r, new_string='**Status**: Built')))
    silent(guard(r, first_edit(r, new_string='    **Status**: Approved')))
    silent(guard(r, first_edit(r, file_path=str(r / 'specs' / '007-x' / 'plan.md'))))
    spec_of(r).write_bytes(FENCED_DRAFT.encode('utf-8'))
    silent(guard(r, first_edit(r, replace_all='yes')))
    spec_of(r).write_bytes(SPEC.encode('utf-8'))
    for elsewhere in ('specs/_living/x/spec.md', 'myspecs/007-x/spec.md', 'specs/7-x/spec.md'):
        silent(guard(r, first_edit(r, file_path=str(r / elsewhere))))
    silent(guard(r, {'file_path': str(r / 'docs' / 'spec.md'), 'content': APPROVED_SPEC}, tool='Write'))
    spec_of(r, '010-d').mkdir(parents=True)
    silent(guard(r, first_edit(r, file_path=str(spec_of(r, '010-d')))))
    silent(guard(r, {'command': 'echo "**Status**: Approved" > specs/007-x/spec.md'}, tool='Bash'))
    silent(guard(r, raw='not json'))
    no_old = first_edit(r)
    del no_old['old_string']
    silent(guard(r, no_old))


def test_sc_006_a_guard_that_cannot_load_kit_spec_asks_on_a_spec_and_is_silent_elsewhere(tmp_path):
    r = make_repo(tmp_path)
    root = tmp_path / 'root'
    shutil.copytree(HOOKS, root / 'hooks')
    could_not_check(guard(r, first_edit(r), root=root), 'FileNotFoundError')
    silent(guard(r, first_edit(r, file_path=str(r / 'docs' / 'notes.md')), root=root))
    # A kit_spec that loads but fails while the guard decides: the failure asks too.
    broken = tmp_path / 'broken'
    shutil.copytree(HOOKS, broken / 'hooks')
    scripts = broken / 'skills' / 'kit-init' / 'scripts'
    scripts.mkdir(parents=True)
    (scripts / 'kit_spec.py').write_text(
        'import re\n'
        f'FEATURE_DIR = re.compile({kit_spec_pattern()!r})\n'
        'def read(path):\n    raise RuntimeError("cannot read")\n'
        'def fields(name, text):\n    return []\n', encoding='utf-8')
    could_not_check(guard(r, first_edit(r), root=broken), 'RuntimeError')
    # Without kit_spec the guard tells a spec path by a copy of FEATURE_DIR, which must stay the same.
    loaded = {}
    for name, path in (('guard', HOOKS / 'guard.py'), ('kit_spec', PLUGIN / 'skills/kit-init/scripts/kit_spec.py')):
        spec = importlib.util.spec_from_file_location(f'sc006_{name}', path)
        loaded[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded[name])
    assert loaded['guard'].FALLBACK_FEATURE_DIR.pattern == loaded['kit_spec'].FEATURE_DIR.pattern


def kit_spec_pattern():
    spec = importlib.util.spec_from_file_location('sc006_pattern', PLUGIN / 'skills/kit-init/scripts/kit_spec.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FEATURE_DIR.pattern


def test_a_plugin_root_not_exported_is_the_guards_own_plugin(tmp_path):
    """CLAUDE_PLUGIN_ROOT unset or empty: the guard loads kit_spec from the plugin it sits in."""
    r = make_repo(tmp_path)
    asks(guard(r, first_edit(r), root_var=False), '007-x')
    asks(guard(r, first_edit(r), root_var=''), '007-x')


def through_sh(r, folder, root, tool_input):
    env = {k: v for k, v in os.environ.items() if k != 'MSYSTEM'}
    env.update(PATH=str(folder), CLAUDE_PLUGIN_ROOT=Path(root).as_posix())
    payload = json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Edit', 'tool_input': tool_input,
                          'cwd': str(r)})
    return record(subprocess.run([SHELLS[0], '-c', COMMAND], input=payload.encode('utf-8'), capture_output=True,
                                 env=env, cwd=r))


def test_sc_007_the_hook_command_finds_a_python_that_runs_and_always_exits_0(tmp_path):
    """Also FR-001: hooks.json declares this one command."""
    declared = json.loads((HOOKS / 'hooks.json').read_text(encoding='utf-8'))['hooks']
    assert list(declared) == ['PreToolUse'] and len(declared['PreToolUse']) == 1
    assert declared['PreToolUse'][0]['matcher'] == 'Edit|Write'
    assert declared['PreToolUse'][0]['hooks'] == [{'type': 'command', 'command': COMMAND}]
    r = make_repo(tmp_path)
    python = Path(sys.executable).as_posix()

    none = tmp_path / 'none'
    none.mkdir()
    silent(through_sh(r, none, PLUGIN, first_edit(r)))

    stub = tmp_path / 'stub'
    stub.mkdir()
    script(stub, 'python3', 'exit 49')
    script(stub, 'python', f'exec "{python}" "$@"')
    asks(through_sh(r, stub, PLUGIN, first_edit(r)), '007-x')

    real = tmp_path / 'real'
    real.mkdir()
    for name in ('python3', 'python'):
        script(real, name, f'exec "{python}" "$@"')
    nowhere = tmp_path / 'no-hooks'
    nowhere.mkdir()
    assert subprocess.run([sys.executable, str(nowhere / 'hooks' / 'guard.py')], capture_output=True).returncode == 2
    silent(through_sh(r, real, nowhere, first_edit(r, file_path=str(r / 'docs' / 'notes.md'))))


def test_sc_008_no_check_allows_and_every_check_exits_0(tmp_path):
    RUNS.clear()
    for n, check in enumerate((test_sc_001_an_edit_or_write_that_makes_the_spec_approved_asks,
                               test_sc_002_a_new_file_an_empty_old_string_and_an_old_string_not_found_ask,
                               test_sc_003_a_closed_fence_hides_a_status_line_and_an_open_one_does_not,
                               test_sc_004_crlf_backslashes_and_case, test_sc_005_what_the_guard_does_not_ask,
                               test_sc_006_a_guard_that_cannot_load_kit_spec_asks_on_a_spec_and_is_silent_elsewhere,
                               test_sc_007_the_hook_command_finds_a_python_that_runs_and_always_exits_0,
                               test_a_plugin_root_not_exported_is_the_guards_own_plugin)):
        (tmp_path / str(n)).mkdir()
        check(tmp_path / str(n))
    assert len(RUNS) >= 35, len(RUNS)
    assert all(code == 0 and '"allow"' not in out for code, out in RUNS), RUNS
    source = (HOOKS / 'guard.py').read_text(encoding='utf-8')
    assert "'allow'" not in source and '"allow"' not in source


@pytest.mark.skipif(shutil.which('claude') is None, reason='claude is not installed here')
def test_sc_009_claude_validates_the_marketplace_and_the_plugin():
    for target in ('.', 'plugins/francis-kit'):
        done = subprocess.run(['claude', 'plugin', 'validate', target], cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', shell=WINDOWS)
        assert done.returncode == 0 and 'error' not in done.stdout.lower().replace('0 error', ''), done.stdout + done.stderr


@pytest.mark.private
def test_sc_010_the_public_copy_holds_the_hook(tmp_path):
    out = tmp_path / 'pub'
    done = subprocess.run([sys.executable, str(ROOT / 'tools' / 'export_public.py'), str(out)], capture_output=True,
                          text=True, encoding='utf-8')
    assert done.returncode == 0, done.stdout + done.stderr
    assert (out / 'plugins/francis-kit/hooks/hooks.json').is_file()
    assert (out / 'plugins/francis-kit/hooks/guard.py').is_file()


def known_limits(path):
    return (ROOT / path).read_text(encoding='utf-8').split('\n## Known limits\n')[1].split('\n## ')[0]


@pytest.mark.private
def test_sc_011_both_readmes_name_the_prompt_and_its_limits():
    for path in ('README.md', 'tools/public/README.md'):
        limits = known_limits(path)
        assert [l for l in limits.splitlines()
                if 'permission prompt' in l and 'Approved' in l and 'a confirmation, not the approval' in l], path
        assert 'A Status line the kit does not read' in limits, path
        for term in ('no Python', 'through Bash', 'NotebookEdit', 'MultiEdit', 'subagent', 'own editor', 'plugin root',
                     'Git Bash', 'dontAsk', 'acceptEdits', 'disableAllHooks', 'timeout'):
            assert term in limits, (path, term)


@pytest.mark.private
def test_sc_012_both_changelogs_say_how_the_hook_is_turned_on_and_off():
    private = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
    unreleased = private[private.index('## Unreleased'):private.index('\n## 0.16.2')]
    public = (ROOT / 'tools' / 'public' / 'CHANGELOG.md').read_text(encoding='utf-8')
    start = public.index('\n## 0.17.0') + 1
    version = public[start:public.index('\n## ', start)]
    for section in (unreleased, version):
        assert [l for l in section.splitlines() if all(w in l for w in (
            'plugin is enabled', 'Approved', 'disabling the plugin', 'disableAllHooks'))], section
