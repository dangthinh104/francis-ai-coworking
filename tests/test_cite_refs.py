"""cite_refs.py against a throwaway git repo."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import link

SCRIPT = (Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit'
          / 'skills' / 'map-project' / 'scripts' / 'cite_refs.py')
spec = importlib.util.spec_from_file_location('cite_refs', SCRIPT)
cite_refs = importlib.util.module_from_spec(spec)
sys.modules['cite_refs'] = cite_refs  # dataclasses look the module up by name
spec.loader.exec_module(cite_refs)

SRC = '''import os


class Engine:
    def start(self):
        return os.getpid()


def helper(value):
    return value + 1
'''


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True,
                          capture_output=True, text=True, encoding='utf-8').stdout.strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 't@example.com')
    git(tmp_path, 'config', 'user.name', 't')
    (tmp_path / 'app').mkdir()
    (tmp_path / 'app' / 'engine.py').write_text(SRC, encoding='utf-8')
    (tmp_path / 'docs').mkdir()
    git(tmp_path, 'add', '-A')
    git(tmp_path, 'commit', '-qm', 'init')
    return tmp_path


def write_diagram(repo, sources, label='Engine', name='map.refs.json', rev=None):
    data = {'meta': {'repository': {'revision': rev or git(repo, 'rev-parse', 'HEAD')}},
            'nodes': [{'label': label, 'sources': sources}]}
    (repo / 'docs' / name).write_text(json.dumps(data), encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', f'diagram {name}')


def run(repo, *flags):
    return cite_refs.main(['--diagrams', str(repo / 'docs'), *flags])


def verdicts(repo):
    cite_refs.REPO_ROOT = cite_refs.PROJECT_ROOT = repo
    cite_refs.DIAGRAMS_DIR = repo / 'docs'
    return [f.verdict for f in cite_refs.collect(sorted((repo / 'docs').glob('*.json')))]


def edit(repo, text, commit=True):
    (repo / 'app' / 'engine.py').write_text(text, encoding='utf-8')
    if commit:
        git(repo, 'commit', '-qam', 'edit')


def test_ok_when_nothing_changed(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4, 'label': 'class'}])
    assert verdicts(repo) == ['ok']
    assert run(repo, '--check') == 0


def test_moved_is_not_a_failure_and_fix_repoints_and_repins(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4, 'end_line': 6}])
    edit(repo, '# header\n# header\n' + SRC)
    assert verdicts(repo) == ['moved']
    assert run(repo, '--check') == 0
    assert run(repo, '--fix') == 0
    data = json.loads((repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8'))
    cite = data['nodes'][0]['sources'][0]
    assert (cite['line'], cite['end_line']) == (6, 8)
    assert data['meta']['repository']['revision'] == git(repo, 'rev-parse', 'HEAD')
    assert verdicts(repo) == ['ok']


def test_lost_fails_check(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 9}])
    edit(repo, SRC.replace('def helper(value):', 'def renamed(v):'))
    assert verdicts(repo) == ['lost']
    assert run(repo, '--check') == 1


def test_file_gone_fails_check(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    git(repo, 'rm', '-q', 'app/engine.py')
    git(repo, 'commit', '-qm', 'rm')
    assert verdicts(repo) == ['file gone']
    assert run(repo, '--check') == 1


def test_weak_anchor_on_blank_lines(repo):
    edit(repo, 'x = 1\n' + '\n' * 8 + 'y = 2\n')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 2}])
    assert verdicts(repo) == ['weak anchor']


def test_fix_refuses_while_cited_file_is_dirty(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    before = (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8')
    edit(repo, '# header\n' + SRC, commit=False)
    assert run(repo, '--fix') == 1          # 003/FR-005: the citation is left `moved`
    assert (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8') == before


def test_fix_is_all_or_nothing_per_diagram(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4},
                         {'path': 'app/engine.py', 'line': 9}])
    before = json.loads((repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8'))
    edit(repo, '# header\n' + SRC.replace('def helper(value):', 'def renamed(v):'))
    assert sorted(verdicts(repo)) == ['lost', 'moved']
    run(repo, '--fix')
    assert json.loads((repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8')) == before


def test_symbol_in_prose_is_checked(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='Engine :4')
    assert run(repo, '--check') == 0
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='Engine :7')
    assert run(repo, '--check') == 1


def test_prose_path_past_eof_fails(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}],
                  label='see app/engine.py:999')
    assert run(repo, '--check') == 1


def test_unknown_pin_exits_2(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], rev='0' * 40)
    assert run(repo, '--check') == 2


def test_unrelated_json_is_ignored_but_no_citation_file_fails_check(repo):
    (repo / 'docs' / 'other.json').write_text('{"a": 1}', encoding='utf-8')
    assert run(repo, '--check') == 1
    assert run(repo, '--report') == 0
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    assert run(repo, '--check') == 0


def test_check_says_what_it_checked(repo, capsys):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    assert run(repo, '--check') == 0
    assert 'checked 1 citation(s) in 1 file(s): 1 ok' in capsys.readouterr().out


def test_same_file_name_in_two_folders_is_fixed_independently(repo):
    head = git(repo, 'rev-parse', 'HEAD')
    for folder, line in (('a', 4), ('b', 9)):
        (repo / 'docs' / folder).mkdir()
        (repo / 'docs' / folder / 'candidate.json').write_text(json.dumps(
            {'meta': {'repository': {'revision': head}},
             'sources': [{'path': 'app/engine.py', 'line': line}]}), encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'two candidates')
    edit(repo, '# header\n' + SRC.replace('def helper(value):', 'def renamed(v):'))
    run(repo, '--fix')
    a = json.loads((repo / 'docs' / 'a' / 'candidate.json').read_text(encoding='utf-8'))
    b = json.loads((repo / 'docs' / 'b' / 'candidate.json').read_text(encoding='utf-8'))
    assert a['sources'][0]['line'] == 5 and a['meta']['repository']['revision'] != head
    assert b['sources'][0]['line'] == 9 and b['meta']['repository']['revision'] == head


def test_short_anchor_is_weak(repo):
    edit(repo, 'value = compute(\n    1,\n)\n\n\n\n\n\n\nother = 2\n')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 3}])
    assert verdicts(repo) == ['weak anchor']


def test_top_level_const_is_a_definition(repo):
    (repo / 'app' / 'conf.ts').write_text('export const PORT = 3000;\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'conf')
    src = [{'path': 'app/conf.ts', 'line': 1}]
    write_diagram(repo, src, label='PORT :1')
    assert run(repo, '--check') == 0
    write_diagram(repo, src, label='PORT :7')
    assert run(repo, '--check') == 1


def test_touched_reports_and_never_fails(repo, capsys):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 9}])
    edit(repo, SRC.replace('def helper(value):', 'def renamed(v):'))
    assert run(repo, '--touched', str(repo / 'app' / 'engine.py')) == 0
    out = capsys.readouterr().out
    assert 'app/engine.py:9  lost' in out


def test_touched_never_fails_even_without_a_diagrams_dir(repo):
    assert cite_refs.main(['--diagrams', str(repo / 'nope'), '--touched', 'x.py']) == 0


def test_touched_with_unknown_pin_exits_0(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], rev='0' * 40)
    assert run(repo, '--touched', str(repo / 'app' / 'engine.py')) == 0


def test_ambiguous_is_reported_and_never_fixed(repo):
    block = 'def same():\n    return 1\n'
    edit(repo, 'x = 0\n' + block)
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 2}])
    before = (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8')
    edit(repo, '# a\n# b\n# c\n' + block + 'gap = 1\n' * 7 + block)
    assert verdicts(repo) == ['ambiguous']
    run(repo, '--fix')
    assert (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8') == before


def test_anchor_window_grows_to_tell_repeats_apart(repo):
    edit(repo, 'call(\n    first,\n)\ncall(\n    second,\n)\n')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, '# header\ncall(\n    first,\n)\ncall(\n    second,\n)\n')
    assert verdicts(repo) == ['moved']
    run(repo, '--fix')
    data = json.loads((repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8'))
    assert data['nodes'][0]['sources'][0]['line'] == 5


def test_past_eof_fails_check(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4, 'end_line': 400}])
    assert verdicts(repo) == ['past eof']
    assert run(repo, '--check') == 1


def test_whole_file_citation_is_ok(repo):
    write_diagram(repo, [{'path': 'app/engine.py'}])
    assert verdicts(repo) == ['ok']
    assert run(repo, '--check') == 0


def test_fix_refuses_dirty_file_with_a_space_in_its_name(repo):
    (repo / 'app' / 'my engine.py').write_text(SRC, encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'add')
    write_diagram(repo, [{'path': 'app/my engine.py', 'line': 4}])
    before = (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8')
    (repo / 'app' / 'my engine.py').write_text('# header\n' + SRC, encoding='utf-8')
    assert run(repo, '--fix') == 1          # 003/FR-005: the citation is left `moved`
    assert (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8') == before


def test_unreadable_or_pinless_citation_file_exits_2(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    (repo / 'docs' / 'broken.json').write_text('<<<<<<< HEAD\n{}', encoding='utf-8')
    assert run(repo, '--check') == 2
    (repo / 'docs' / 'broken.json').write_text(
        json.dumps({'nodes': [{'sources': [{'path': 'app/gone.py', 'line': 1}]}]}), encoding='utf-8')
    assert run(repo, '--check') == 2


def test_citation_files_are_found_in_subdirectories(repo):
    (repo / 'docs' / 'flows').mkdir()
    data = {'meta': {'repository': {'revision': git(repo, 'rev-parse', 'HEAD')}},
            'sources': [{'path': 'app/gone.py', 'line': 1}]}
    (repo / 'docs' / 'flows' / 'flow.json').write_text(json.dumps(data), encoding='utf-8')
    assert run(repo, '--check') == 1


def test_non_python_symbols_are_checked(repo):
    (repo / 'app' / 'server.ts').write_text(
        'export class Server {\n  start() {\n    const port = 3000;\n  }\n}\n'
        'export function boot() {}\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'ts')
    src = [{'path': 'app/server.ts', 'line': 1}]
    write_diagram(repo, src, label='Server :1 and boot :6, listens on port :8080')
    assert run(repo, '--check') == 0
    write_diagram(repo, src, label='boot :2')
    assert run(repo, '--check') == 1


def test_go_method_with_receiver_is_a_definition(repo):
    (repo / 'app' / 'e.go').write_text('package app\n\nfunc (e *Engine) Start() {}\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'go')
    write_diagram(repo, [{'path': 'app/e.go', 'line': 3}], label='Start :9')
    assert run(repo, '--check') == 1


def test_bare_basename_in_prose_resolves_when_unique(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='engine.py:999')
    assert run(repo, '--check') == 1
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='engine.py:4')
    assert run(repo, '--check') == 0


def test_prose_path_to_a_deleted_tracked_file_does_not_crash(repo):
    (repo / 'app' / 'util.py').write_text('u = 1\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'util')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='see util.py:1')
    (repo / 'app' / 'util.py').unlink()
    assert run(repo, '--check') == 1


def test_project_in_a_monorepo_subdirectory(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 't@example.com')
    git(tmp_path, 'config', 'user.name', 't')
    for proj in ('one', 'two'):
        (tmp_path / proj / 'app').mkdir(parents=True)
        (tmp_path / proj / 'app' / 'engine.py').write_text(SRC, encoding='utf-8')
    (tmp_path / 'one' / 'docs').mkdir()
    git(tmp_path, 'add', '-A'); git(tmp_path, 'commit', '-qm', 'init')
    head = git(tmp_path, 'rev-parse', 'HEAD')

    def check(path, label, *extra):
        data = {'meta': {'repository': {'revision': head}},
                'nodes': [{'label': label, 'sources': [{'path': path, 'line': 4}]}]}
        (tmp_path / 'one' / 'docs' / 'map.refs.json').write_text(json.dumps(data), encoding='utf-8')
        return cite_refs.main(['--diagrams', str(tmp_path / 'one' / 'docs'),
                               '--root', str(tmp_path / 'one'), '--check', *extra])

    # Paths are written from the git root; a file of the same name in the
    # sibling project must not make a bare name ambiguous.
    (tmp_path / 'one' / 'app' / 'other.py').write_text('o = 1\n', encoding='utf-8')
    (tmp_path / 'two' / 'app' / 'other.py').write_text('o = 1\n', encoding='utf-8')
    git(tmp_path, 'add', '-A'); git(tmp_path, 'commit', '-qm', 'other')
    assert check('one/app/engine.py', 'engine.py:4 and other.py:1') == 0
    assert check('app/engine.py', 'x') == 1
    assert check('one/app/engine.py', 'x', '--repo', str(tmp_path / 'one')) == 0


def diagram_text(repo):
    return (repo / 'docs' / 'map.refs.json').read_text(encoding='utf-8')


def test_weak_and_ambiguous_fail_check(repo):
    edit(repo, 'x = 1\n' + '\n' * 8 + 'y = 2\n')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 2}])
    assert run(repo, '--check') == 1
    block = 'def same():\n    return 1\n'
    edit(repo, 'x = 0\n' + block)
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 2}])
    edit(repo, '# a\n# b\n# c\n' + block + 'gap = 1\n' * 7 + block)
    assert verdicts(repo) == ['ambiguous']
    assert run(repo, '--check') == 1


def test_fix_with_touched_is_refused_and_writes_nothing(repo, capsys):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4},
                         {'path': 'docs/note.md'}])
    (repo / 'docs' / 'note.md').write_text('note\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'note')
    edit(repo, SRC.replace('class Engine:', 'class Motor:'))
    before = diagram_text(repo)
    assert run(repo, '--fix', '--touched', str(repo / 'docs' / 'note.md')) == 0  # a hook never blocks
    assert 'cannot be combined' in capsys.readouterr().err
    assert diagram_text(repo) == before


def test_pin_must_be_a_commit_id(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], rev='HEAD')
    assert run(repo, '--check') == 2


@pytest.mark.parametrize('sources', [
    [],
    'app/engine.py',
    [{'line': 4}],
    ['app/engine.py'],
    [{'path': 'app/engine.py', 'line': '4'}],
    [{'path': 'app/engine.py', 'line': 0}],
    [{'path': 'app/engine.py', 'line': True}],
])
def test_empty_or_malformed_sources_do_not_pass_check(repo, sources):
    write_diagram(repo, sources)
    assert run(repo, '--check') != 0


def test_path_outside_the_repository_fails_check(repo):
    outside = repo.parent / 'outside.py'
    outside.write_text(SRC, encoding='utf-8')
    write_diagram(repo, [{'path': '../outside.py'}])
    assert run(repo, '--check') == 1
    write_diagram(repo, [{'path': str(outside)}])
    assert run(repo, '--check') == 1


def test_prose_check_fails_on_a_lost_citation(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 9}])
    edit(repo, SRC.replace('def helper(value):', 'def renamed(v):'))
    assert run(repo, '--prose', '--check') == 1


def test_fix_writes_lines_and_pin_together(repo, monkeypatch):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, '# header\n' + SRC)
    before = diagram_text(repo)
    calls = []
    real = cite_refs.os.replace

    def failing(src, dst):
        calls.append(dst)
        raise OSError('disk full')
    monkeypatch.setattr(cite_refs.os, 'replace', failing)
    assert run(repo, '--fix') == 2
    assert len(calls) == 1 and diagram_text(repo) == before
    monkeypatch.setattr(cite_refs.os, 'replace', real)
    assert run(repo, '--fix') == 0
    data = json.loads(diagram_text(repo))
    assert data['nodes'][0]['sources'][0]['line'] == 5
    assert data['meta']['repository']['revision'] == git(repo, 'rev-parse', 'HEAD')


def test_text_that_cannot_be_encoded_leaves_the_file_as_it_was(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='bad \udce9')
    path = repo / 'docs' / 'map.refs.json'
    path.write_text(path.read_text(encoding='utf-8').replace('bad ', 'bad é '), encoding='utf-8')   # not an all-ASCII file
    git(repo, 'commit', '-qam', 'accent')
    edit(repo, '# header\n' + SRC)
    before = (repo / 'docs' / 'map.refs.json').read_bytes()
    assert run(repo, '--fix') == 2
    assert (repo / 'docs' / 'map.refs.json').read_bytes() == before


def test_symlinked_citation_file_is_refused(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    target = repo / 'elsewhere.json'
    (repo / 'docs' / 'map.refs.json').rename(target)
    link((repo / 'docs' / 'map.refs.json'), target)
    assert run(repo, '--check') == 2


def test_a_crash_is_exit_2_not_1(repo, monkeypatch):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    monkeypatch.setattr(cite_refs, 'collect', lambda *a, **k: 1 / 0)
    assert run(repo, '--check') == 2


def good_file(repo):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], name='good.refs.json')


@pytest.mark.parametrize('sources', [
    [], 'app/engine.py', [{'line': 4}], [{'path': ''}], ['app/engine.py', {'path': 'app/engine.py'}],
    [{'path': 'app/engine.py', 'line': 0}], [{'path': 'app/engine.py', 'line': 9, 'end_line': 2}],
])
def test_a_bad_file_fails_even_beside_a_good_one(repo, sources):
    good_file(repo)
    write_diagram(repo, sources)
    assert run(repo, '--check') == 2


def test_absolute_path_inside_the_repo_is_still_refused(repo):
    write_diagram(repo, [{'path': str(repo / 'app' / 'engine.py'), 'line': 4}])
    assert verdicts(repo) == ['file gone']


def test_prose_never_opens_a_file_outside_the_repo(repo, capsys):
    outside = repo.parent / 'secret.py'
    outside.write_text('x = 1\n\n\n\nclass SecretThing:\n    pass\n', encoding='utf-8')
    write_diagram(repo, [{'path': str(outside)}], label='see SecretThing :9')
    run(repo, '--prose')
    assert 'SecretThing is defined' not in capsys.readouterr().out


def test_other_json_with_a_sources_key_is_not_a_citation_file(repo):
    good_file(repo)
    (repo / 'docs' / 'bundle.json').write_text('{"version": 3, "sources": ["a.ts"]}', encoding='utf-8')
    (repo / 'docs' / 'dirs.json').write_text('{"dirs": ["sources", "tests"]}', encoding='utf-8')
    assert run(repo, '--check') == 0


def test_fix_is_one_replace_and_a_planted_temp_name_is_not_followed(repo, monkeypatch):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, '# header\n' + SRC)
    victim = repo.parent / 'victim.txt'
    victim.write_text('VICTIM', encoding='utf-8')
    link((repo / 'docs' / 'map.refs.json.tmp'), victim)
    calls = []
    real = cite_refs.os.replace
    monkeypatch.setattr(cite_refs.os, 'replace', lambda a, b: (calls.append(b), real(a, b))[1])
    assert run(repo, '--fix') == 0
    assert len(calls) == 1
    assert victim.read_text(encoding='utf-8') == 'VICTIM'
    assert not (repo / 'docs' / 'map.refs.json').is_symlink()


def test_a_failed_write_leaves_no_temp_file(repo, monkeypatch):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, '# header\n' + SRC)
    before = sorted(p.name for p in (repo / 'docs').iterdir())

    def boom(a, b):
        raise OSError('no')
    monkeypatch.setattr(cite_refs.os, 'replace', boom)
    assert run(repo, '--fix') == 2
    assert sorted(p.name for p in (repo / 'docs').iterdir()) == before


def test_check_names_the_failing_citation(repo, capsys):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 9}])
    edit(repo, SRC.replace('def helper(value):', 'def renamed(v):'))
    run(repo, '--check')
    assert 'app/engine.py:9' in capsys.readouterr().err


def test_hook_mode_with_equals_and_a_crash_still_exit_0(repo, monkeypatch):
    assert cite_refs.main(['--diagrams', str(repo / 'nope'), f'--touched={repo}/app/engine.py']) == 0
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    monkeypatch.setattr(cite_refs, 'collect', lambda *a, **k: 1 / 0)
    assert run(repo, '--touched', str(repo / 'app' / 'engine.py')) == 0


def test_deeply_nested_json_is_unreadable_not_a_crash(repo):
    good_file(repo)
    (repo / 'docs' / 'deep.json').write_text('[' * 100000 + ']' * 100000, encoding='utf-8')
    assert run(repo, '--check') == 2


def cite(repo, path, line):
    write_diagram(repo, [{'path': path, 'line': line}])


@pytest.mark.parametrize('spelling', ['./app/engine.py', 'app//engine.py', 'app/../app/engine.py', 'app\\engine.py'])
def test_one_file_has_one_spelling(repo, spelling):
    cite(repo, spelling, 4)
    assert verdicts(repo) == ['ok']


def test_fix_does_not_repoint_under_an_uncommitted_edit_however_the_path_is_spelled(repo):
    cite(repo, './app/engine.py', 4)
    (repo / 'app' / 'engine.py').write_text('# header\n' + SRC, encoding='utf-8')       # not committed
    before = diagram_text(repo)
    run(repo, '--fix')
    assert diagram_text(repo) == before


@pytest.mark.parametrize('breaker', ['\f', '\u2028', '\x0b', '\x85', '\r'])
def test_lines_are_counted_the_way_git_counts_them(repo, breaker):
    body = f'a = 1  # odd {breaker} character\nkeep = 1\ntarget_line = compute()\nafter = 2\n'
    (repo / 'app' / 'odd.py').write_bytes(body.encode('utf-8'))
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'odd')
    cite(repo, 'app/odd.py', 3)
    assert verdicts(repo) == ['ok']
    (repo / 'app' / 'odd.py').write_bytes(body.replace('target_line = compute()\n', '').encode('utf-8'))
    git(repo, 'commit', '-qam', 'drop the cited line')
    assert verdicts(repo) == ['lost']
    assert run(repo, '--check') == 1


def test_a_repeated_line_that_did_not_move_is_not_lost(repo):
    body = 'x = 0\nreturn result\ny = 1\nz = 2\nw = 3\nreturn result\nend = 1\n'
    (repo / 'app' / 'twice.py').write_text(body, encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'twice')
    cite(repo, 'app/twice.py', 2)
    (repo / 'app' / 'twice.py').write_text(body.replace('return result\ny = 1', 'return result\nnew = 9\ny = 1'), encoding='utf-8')
    git(repo, 'commit', '-qam', 'insert under the cited line')
    assert verdicts(repo) == ['ok']


def test_a_file_name_that_is_not_ascii_is_found_from_prose(repo, capsys):
    (repo / 'app' / 'café.py').write_text('a = 1\nb = 2\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'accent')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}], label='see café.py:2')
    assert run(repo, '--prose', '--check') == 0
    assert 'file gone' not in capsys.readouterr().out.lower()


def test_prose_is_anchored_by_path_not_by_a_name_two_files_share(repo, capsys):
    for d in ('a', 'b'):
        (repo / d).mkdir()
        (repo / d / 'x.py').write_text('one = 1\ntwo = 2\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'two x')
    write_diagram(repo, [{'path': 'a/x.py', 'line': 2}, {'path': 'b/x.py'}], label='see b/x.py:2')
    run(repo, '--prose')
    assert 'unanchored' in capsys.readouterr().out.lower()


def test_fix_changes_two_values_and_keeps_the_way_the_file_is_written(repo):
    path = repo / 'docs' / 'map.refs.json'
    head = git(repo, 'rev-parse', 'HEAD')
    text = ('\ufeff{\r\n    "meta": {"repository": {"revision": "%s"}},\r\n    "ratio": 1e3,\r\n'
            '    "nodes": [\r\n        {"label": "caf\\u00e9", "sources": [{"path": "app/engine.py", "line": 4}]}\r\n    ]\r\n}\r\n' % head)
    path.write_bytes(text.encode('utf-8'))
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'styled diagram')
    edit(repo, '# header\n' + SRC)
    assert run(repo, '--fix') == 0
    after = path.read_bytes().decode('utf-8')
    assert after.startswith('\ufeff') and '\r\n    "meta"' in after and '\n' not in after.replace('\r\n', '')
    assert '"ratio": 1e3' in after and 'caf\\u00e9' in after and '"line": 5' in after
    assert git(repo, 'rev-parse', 'HEAD') in after


def test_touched_reports_prose_into_a_file_nothing_cites(repo, capsys):
    for folder in ('a', 'b'):
        (repo / folder).mkdir()
        (repo / folder / 'x.py').write_bytes(b'import os\ndef handler():\n    pass\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'two x.py')
    write_diagram(repo, [{'path': 'a/x.py', 'line': 2}], label='other entry at b/x.py:2')
    verdicts(repo)
    capsys.readouterr()
    assert run(repo, '--touched', str(repo / 'b' / 'x.py')) == 0
    assert 'b/x.py:2  unanchored' in capsys.readouterr().out


# Spec 003: `--fix` says what it left.

def left_lines(capsys):
    return [l.strip() for l in capsys.readouterr().err.splitlines() if l.startswith('    ')]


def test_fix_exits_1_and_names_the_citation_it_could_not_repair(repo, capsys):
    """003/FR-005, 003/FR-006, SC-004."""
    (repo / 'src.py').write_text('import os\n\n\ndef helper(value):\n    return value\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'src')
    write_diagram(repo, [{'path': 'src.py', 'line': 4}])
    assert run(repo, '--fix') == 0
    assert left_lines(capsys) == []
    (repo / 'src.py').write_text('import os\n\n\ndef renamed(v):\n    return v\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'rename')
    assert run(repo, '--fix') == 1
    left = left_lines(capsys)
    assert len(left) == 1 and left[0].startswith('src.py:4  lost'), left
    assert run(repo, '--check') == 1


def test_fix_that_refuses_an_uncommitted_file_names_what_stays_moved(repo, capsys):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, '# header\n' + SRC, commit=False)
    assert run(repo, '--fix') == 1
    assert [l.split('  ')[:2] for l in left_lines(capsys)] == [['app/engine.py:4', 'moved']]
    git(repo, 'commit', '-qam', 'edit')
    assert run(repo, '--fix') == 0
    assert left_lines(capsys) == []


def test_fix_names_every_citation_left_whatever_the_verdict(repo, capsys):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}, {'path': 'app/engine.py', 'line': 9},
                         {'path': 'app/engine.py', 'line': 5, 'end_line': 400}, {'path': 'app/gone.py', 'line': 1}])
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 5}], name='other.refs.json')
    edit(repo, '# header\n' + SRC.replace('def helper(value):', 'def renamed(v):'))
    assert run(repo, '--fix') == 1
    left = sorted(l.split('  ')[1] for l in left_lines(capsys))
    assert left == ['file gone', 'lost', 'moved', 'past eof'], left       # the diagram that resolves was re-pinned
    data = json.loads((repo / 'docs' / 'other.refs.json').read_text(encoding='utf-8'))
    assert data['nodes'][0]['sources'][0]['line'] == 6


@pytest.mark.parametrize('flags', [('--fix', '--prose'), ('--fix', '--report'), ('--fix', '--check')])
def test_fix_exits_1_whatever_else_is_asked(repo, capsys, flags):
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 9}])
    edit(repo, SRC.replace('def helper(value):', 'def renamed(v):'))
    assert run(repo, *flags) == 1
    assert 'app/engine.py:9  lost' in capsys.readouterr().err


def test_fix_leaves_ambiguous_and_weak_anchors_as_exit_1(repo, capsys):
    edit(repo, 'x = 1\n' + '\n' * 8 + 'y = 2\n')
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 2}])
    assert run(repo, '--fix') == 1
    assert 'app/engine.py:2  weak anchor' in capsys.readouterr().err


def test_fix_prints_what_it_left_in_order_and_counts_it(repo, capsys):
    for name in ('b.py', 'a.py'):
        (repo / name).write_text('import os\n\n\ndef first_one(value):\n    return value\n\n\n'
                                 'def second_one(value):\n    return value\n', encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'two files')
    write_diagram(repo, [{'path': 'b.py', 'line': 8}, {'path': 'b.py', 'line': 4},
                         {'path': 'a.py', 'line': 8}, {'path': 'a.py', 'line': 4}])
    for name in ('b.py', 'a.py'):
        (repo / name).write_text('import os\n\n\ndef renamed_a(v):\n    return v\n\n\n'
                                 'def renamed_b(v):\n    return v\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'rename')
    assert run(repo, '--fix') == 1
    err = capsys.readouterr().err
    assert [l.split()[0] for l in err.splitlines() if l.startswith('    ')] == ['a.py:4', 'a.py:8', 'b.py:4', 'b.py:8']
    assert '4 citation(s) are not `ok` after --fix' in err


# Spec 016: a refusal says that a commit is all it needs.

ADVICE = 'commit first, then run --fix, then commit the re-pinned file.'


def test_sc009_a_refusal_that_leaves_a_moved_citation_asks_for_a_commit(repo, capsys):
    """016/FR-008, 016/FR-009, 016/FR-010, SC-009."""
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, '# header\n' + SRC, commit=False)
    assert run(repo, '--fix') == 1
    out, err = capsys.readouterr()
    assert ADVICE in out and 'run --fix again' not in out and 'no diagram fully resolves' not in out, out
    assert 'app/engine.py:4  moved' in err and 'needs a person' not in err, err
    assert err.rstrip().endswith(f'1 citation(s) are not `ok` after --fix: {ADVICE}'), err


def test_sc010_a_refusal_with_every_citation_ok_or_one_lost(repo, capsys):
    """016/FR-008, 016/FR-009, 016/FR-010, SC-010."""
    write_diagram(repo, [{'path': 'app/engine.py', 'line': 4}])
    edit(repo, SRC + '# tail\n', commit=False)
    assert run(repo, '--fix') == 0
    out, err = capsys.readouterr()
    assert ADVICE in out and 'no diagram fully resolves' not in out and err == '', (out, err)
    edit(repo, SRC.replace('class Engine:\n', ''))
    edit(repo, SRC.replace('class Engine:\n', '') + '# tail\n', commit=False)
    assert run(repo, '--fix') == 1
    err = capsys.readouterr().err
    assert 'lost' in err and err.rstrip().endswith('each line above needs a person.'), err
