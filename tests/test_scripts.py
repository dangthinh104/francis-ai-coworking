"""map_check.py and comment_audit.py."""
import os
import subprocess
import sys
from pathlib import Path

from conftest import link

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
MAP_CHECK = KIT / 'map-project' / 'scripts' / 'map_check.py'
AUDIT = KIT / 'comment-discipline' / 'scripts' / 'comment_audit.py'


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8')


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True,
                          capture_output=True, text=True, encoding='utf-8').stdout.strip()


def make_repo(tmp_path, doc_body, pin=True):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.email', 't@example.com')
    git(tmp_path, 'config', 'user.name', 't')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.py').write_text('a = 1\nb = 2\nc = 3\n', encoding='utf-8')
    git(tmp_path, 'add', '-A')
    git(tmp_path, 'commit', '-qm', 'init')
    head = f'<!-- kit:map revision={git(tmp_path, "rev-parse", "HEAD")} -->\n' if pin else ''
    (tmp_path / 'ARCH.md').write_text(head + doc_body, encoding='utf-8')
    return tmp_path


def test_map_check_green(tmp_path):
    repo = make_repo(tmp_path, 'See `src/main.py` and `src/main.py:2-3`.\n')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 0, r.stdout
    assert 'ok=2 broken=0' in r.stdout


def test_map_check_missing_path_and_line_range(tmp_path):
    repo = make_repo(tmp_path, '`src/gone.py` and `src/main.py:2-99`\n')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 1
    assert 'BROKEN src/gone.py' in r.stdout and 'BROKEN src/main.py:2-99' in r.stdout


def test_map_check_ignores_things_that_only_look_like_paths(tmp_path):
    repo = make_repo(tmp_path, '`/speckit.plan` `application/json` `origin/main` `self.run`\n')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 0, r.stdout
    assert 'broken=0' in r.stdout and 'not_from_project_root=0' in r.stdout


def test_map_check_reports_bare_file_names(tmp_path):
    repo = make_repo(tmp_path, '`pipeline.py:12`\n')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert 'UNCHECKED pipeline.py:12' in r.stdout


def test_map_check_lists_paths_written_from_a_subproject(tmp_path):
    repo = make_repo(tmp_path, '`api/deps.py`\n')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 0 and 'UNCHECKED api/deps.py' in r.stdout


def test_map_check_requires_a_pin(tmp_path):
    repo = make_repo(tmp_path, '`src/main.py`\n', pin=False)
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 1 and 'pin: MISSING' in r.stdout


def test_map_check_unknown_pin_exits_2(tmp_path):
    repo = make_repo(tmp_path, '`src/main.py`\n', pin=False)
    (repo / 'ARCH.md').write_text('<!-- kit:map revision=' + '0' * 40 + ' -->\n`src/main.py`\n', encoding='utf-8')
    assert run(MAP_CHECK, repo, 'ARCH.md').returncode == 2


def test_map_check_lists_cited_files_changed_since_pin(tmp_path):
    repo = make_repo(tmp_path, '`src/main.py`\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'map')
    (repo / 'src' / 'main.py').write_text('changed = True\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'edit')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 0 and 'REVIEW src/main.py' in r.stdout


def audit_line(tmp_path, name, text, *flags):
    f = tmp_path / name
    f.write_text(text, encoding='utf-8')
    return run(AUDIT, *flags, f)


def test_audit_counts_comments_dates_duplicates_and_blocks(tmp_path):
    text = ('# first long comment line here ok\n' * 2 + '# on 28/10 it broke\n'
            + '# x\n# y\nrun: echo hi\n')
    r = audit_line(tmp_path, 'ci.yml', text, '--strict')
    assert r.returncode == 1
    assert 'comments=5' in r.stdout and 'dated=1' in r.stdout
    assert 'duplicated=1' in r.stdout and 'longest_block=5' in r.stdout


def test_audit_does_not_count_preprocessor_or_star_args(tmp_path):
    r = audit_line(tmp_path, 'a.c', '#include <x.h>\n#define N 1\nint f(\n  *p,\n);\n')
    assert 'comments=0' in r.stdout
    r = audit_line(tmp_path, 'b.py', 'def f(\n    *args,\n    **kw,\n):\n    pass\n')
    assert 'comments=0' in r.stdout


def test_audit_block_comment_and_trailing_date(tmp_path):
    r = audit_line(tmp_path, 'a.ts', '/**\n * doc\n */\nconst a = 1; // fixed 2026-10-28\n')
    assert 'comments=3' in r.stdout and 'dated=1' in r.stdout


def test_audit_ratio_is_not_a_date(tmp_path):
    r = audit_line(tmp_path, 'a.py', '# retry 3/5 times\n' + 'x = 1\n' * 5, '--strict')
    assert 'dated=0' in r.stdout and r.returncode == 0


def test_audit_skips_markdown_and_missing_files(tmp_path):
    (tmp_path / 'ok.py').write_text('x = 1\n', encoding='utf-8')
    r = run(AUDIT, tmp_path / 'README.md', tmp_path / 'gone.py', tmp_path / 'ok.py')
    assert r.returncode == 0
    assert 'skipped (Markdown)' in r.stdout and 'gone.py: skipped' in r.stdout
    assert 'ok.py: lines=1' in r.stdout


def test_audit_block_comments_without_leading_stars_and_html(tmp_path):
    r = audit_line(tmp_path, 'a.php', '<?php\n/*\n free text\n more\n*/\n#[Group("x")]\n$a = 1;\n')
    assert 'comments=4' in r.stdout
    r = audit_line(tmp_path, 'a.vue', '<!--\n note\n-->\n<template/>\n* { margin: 0 }\n')
    assert 'comments=3' in r.stdout


def test_audit_fraction_with_impossible_month_is_not_a_date(tmp_path):
    r = audit_line(tmp_path, 'a.yml', '# 16/16 layers done\n# broke on 31/08\nx: 1\n')
    assert 'dated=1' in r.stdout


def test_map_check_pin_must_be_on_the_first_line(tmp_path):
    repo = make_repo(tmp_path, '`src/main.py`\n', pin=False)
    head = git(repo, 'rev-parse', 'HEAD')
    (repo / 'ARCH.md').write_text(f'# map\n<!-- kit:map revision={head} -->\n`src/main.py`\n', encoding='utf-8')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 1 and 'pin: MISSING' in r.stdout


def test_every_script_survives_a_console_that_is_not_utf8(tmp_path):
    """On a Windows console the default encoding cannot print Vietnamese or an arrow."""
    import os
    git(tmp_path, 'init', '-q')
    spec = tmp_path / 'specs' / '001-thu-phí'
    spec.parent.mkdir()
    (tmp_path / 'specs' / '001-thu-phi').mkdir()
    (tmp_path / 'specs' / '001-thu-phi' / 'spec.md').write_text('# Thu phí trễ hạn → nhắc\n\n- **FR-001**: tính phí\n', encoding='utf-8')
    (tmp_path / 'vi.json').write_text('{"saved": "Lưu thành công"}', encoding='utf-8')
    (tmp_path / 'a.py').write_text('# ghi chú → FR-001\nx = 1\n', encoding='utf-8')
    (tmp_path / 'ARCH.md').write_text('# bản đồ → `a.py`\n', encoding='utf-8')
    git(tmp_path, 'add', '-A')
    skills = KIT
    runs = [
        (skills / 'kit-init' / 'scripts' / 'spec_index.py', ['--root', tmp_path]),
        (skills / 'kit-init' / 'scripts' / 'kit_detect.py', ['--repo', tmp_path]),
        (skills / 'kit-init' / 'scripts' / 'kit_doctor.py', ['--repo', tmp_path]),
        (skills / 'kit-init' / 'scripts' / 'kit_scaffold.py', ['--repo', tmp_path, '--dry-run', '--name', 'thu-phí']),
        (skills / 'ui-copy' / 'scripts' / 'copy_audit.py', [tmp_path / 'vi.json']),
        (skills / 'comment-discipline' / 'scripts' / 'comment_audit.py', [tmp_path / 'a.py']),
        (skills / 'comment-discipline' / 'scripts' / 'spec_refs.py', ['--repo', tmp_path, '--report']),
        (MAP_CHECK, [tmp_path, 'ARCH.md']),
    ]
    env = {**os.environ, 'PYTHONIOENCODING': 'ascii', 'PYTHONUTF8': '0'}
    for script, args in runs:
        r = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, env=env)
        assert b'Traceback' not in r.stderr and b'UnicodeEncodeError' not in r.stderr, (script.name, r.stderr[-300:])


def test_map_check_path_deleted_since_the_pin_is_broken(tmp_path):
    repo = make_repo(tmp_path, '`src/main.py` and `src/`\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'map')
    git(repo, 'rm', '-rq', 'src'); git(repo, 'commit', '-qm', 'drop src')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 1, r.stdout
    assert 'BROKEN src/main.py: deleted since the pin' in r.stdout
    assert 'BROKEN src/: deleted since the pin' in r.stdout


def test_map_check_rejects_a_path_that_leaves_the_root(tmp_path):
    (tmp_path / 'secret.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'proj').mkdir()
    repo = make_repo(tmp_path / 'proj', '`src/../../secret.py`\n')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 1 and 'leaves the project root' in r.stdout


def test_map_check_without_git_exits_2(tmp_path):
    repo = make_repo(tmp_path, '`src/main.py`\n')
    r = subprocess.run([sys.executable, str(MAP_CHECK), str(repo), 'ARCH.md'],
                       capture_output=True, text=True, encoding='utf-8',
                       # Python 3.9 on Windows does not start without SYSTEMROOT
                       env={'PATH': str(tmp_path / 'nowhere'),
                            **{k: os.environ[k] for k in ('SYSTEMROOT',) if k in os.environ}})
    assert r.returncode == 2 and 'git could not be run' in r.stdout


def test_audit_that_looked_at_nothing_exits_2(tmp_path):
    (tmp_path / 'notes.md').write_text('# x\n', encoding='utf-8')
    r = run(AUDIT, tmp_path / 'notes.md', tmp_path / 'absent.py')
    assert r.returncode == 2 and 'no file was audited' in r.stderr


def test_detect_without_pyyaml_exits_2(tmp_path):
    detect = KIT / 'kit-init' / 'scripts' / 'kit_detect.py'
    code = ('import runpy, sys; sys.modules["yaml"] = None; '
            f'sys.argv = ["kit_detect.py", "--repo", {str(tmp_path)!r}]; '
            f'runpy.run_path({str(detect)!r}, run_name="__main__")')
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 2 and 'PyYAML is not installed' in r.stderr


def test_spec_index_refuses_a_symlink_and_keeps_the_target(tmp_path):
    index = KIT / 'kit-init' / 'scripts' / 'spec_index.py'
    (tmp_path / 'specs').mkdir()
    real = tmp_path / 'real.md'
    real.write_text('mine\n', encoding='utf-8')
    link((tmp_path / 'specs' / 'INDEX.md'), real)
    assert run(index, '--root', tmp_path).returncode == 2
    assert real.read_text(encoding='utf-8') == 'mine\n'


def test_map_check_root_level_file_deleted_since_the_pin_is_broken(tmp_path):
    git(tmp_path, 'init', '-q')
    (tmp_path / 'setup.py').write_text('x = 1\n', encoding='utf-8')
    (tmp_path / 'Makefile').write_text('all:\n', encoding='utf-8')
    repo = make_repo(tmp_path, '`setup.py` `Makefile` `origin/main` `self.run`\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'map')
    assert run(MAP_CHECK, repo, 'ARCH.md').returncode == 0
    git(repo, 'rm', '-q', 'setup.py', 'Makefile'); git(repo, 'commit', '-qm', 'drop')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert r.returncode == 1 and 'BROKEN setup.py' in r.stdout and 'BROKEN Makefile' in r.stdout
    assert 'origin/main' not in r.stdout and 'self.run' not in r.stdout


def test_audit_given_only_markdown_is_not_a_failure(tmp_path):
    (tmp_path / 'notes.md').write_text('# x\n', encoding='utf-8')
    assert run(AUDIT, tmp_path / 'notes.md').returncode == 0


def test_spec_index_is_one_replace_and_leaves_nothing_behind(tmp_path):
    index = KIT / 'kit-init' / 'scripts' / 'spec_index.py'
    (tmp_path / 'specs').mkdir()
    victim = tmp_path / 'victim.txt'
    victim.write_text('VICTIM', encoding='utf-8')
    link((tmp_path / 'specs' / 'INDEX.md.kit-tmp'), victim)
    assert run(index, '--root', tmp_path).returncode == 0
    assert victim.read_text(encoding='utf-8') == 'VICTIM'
    assert not (tmp_path / 'specs' / 'INDEX.md').is_symlink()
    (tmp_path / 'specs' / 'INDEX.md.kit-tmp').unlink()
    (tmp_path / 'specs' / 'INDEX.md').unlink()
    (tmp_path / 'specs' / 'INDEX.md').mkdir()
    r = run(index, '--root', tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    assert sorted(p.name for p in (tmp_path / 'specs').iterdir()) == ['INDEX.md']


import importlib.util

import pytest


@pytest.mark.parametrize('rel,func', [('kit_scaffold.py', 'write_new'), ('spec_index.py', 'write')])
def test_writers_put_nothing_at_the_target_until_the_replace(tmp_path, monkeypatch, rel, func):
    spec = importlib.util.spec_from_file_location(rel[:-3], KIT / 'kit-init' / 'scripts' / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / 'out.md'
    target.write_text('old\n', encoding='utf-8')

    def boom(a, b):
        raise OSError('no')
    monkeypatch.setattr(module.os, 'replace', boom)
    with pytest.raises(OSError):
        getattr(module, func)(target, 'new\n')
    assert target.read_text(encoding='utf-8') == 'old\n'
    assert [p.name for p in tmp_path.iterdir()] == ['out.md']


def test_audit_ratio_is_not_judged_on_a_short_file(tmp_path):
    short = '# why\n' * 10 + 'x = 1\n' * 18
    assert 'ratio' not in audit_line(tmp_path, 'small.py', short, '--strict').stdout.split('ratio=')[1].split('OVER')[-1]
    long = '# why this exists, line by line\n' * 20 + 'x = 1\n' * 25
    assert 'ratio' in audit_line(tmp_path, 'big.py', long, '--strict').stdout.split('OVER:')[1]


def test_no_test_or_script_reads_a_pipe_in_the_locale_encoding():
    """On a Windows console the locale is not UTF-8: a pipe read without `encoding=` loses Vietnamese
    output and returns None. Linux cannot show that, so the rule is checked on the source."""
    root = Path(__file__).resolve().parent.parent
    bad = []
    for path in [*root.glob('tests/*.py'), *root.glob('plugins/**/*.py')]:
        source = path.read_text(encoding='utf-8')
        for call in source.split('subprocess.run(')[1:]:
            head = call[:call.find('\n\n') if '\n\n' in call else len(call)][:400]
            if 'text=True' in head and 'encoding=' not in head:
                bad.append(path.name)
    assert not bad, bad


def test_map_check_review_knows_a_path_written_with_a_leading_dot(tmp_path):
    repo = make_repo(tmp_path, '`./src/main.py`\n')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'map')
    (repo / 'src' / 'main.py').write_text('changed = True\n', encoding='utf-8')
    git(repo, 'commit', '-qam', 'change a cited file')
    r = run(MAP_CHECK, repo, 'ARCH.md')
    assert 'cited by the map: 1' in r.stdout, r.stdout


def test_every_text_read_or_write_in_the_kit_names_its_encoding():
    """On Windows the default is the code page of the machine: 'Lưu thành công' written without
    an encoding broke a test there while passing everywhere else."""
    import ast
    root = Path(__file__).resolve().parent.parent
    bare = []
    for path in sorted([*root.joinpath('tests').rglob('*.py'), *root.joinpath('plugins').rglob('*.py')]):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('read_text', 'write_text')
                    and not any(k.arg == 'encoding' for k in node.keywords)):
                bare.append(f'{path.relative_to(root).as_posix()}:{node.lineno}')
    assert bare == []


def test_spec_refs_fix_puts_nothing_at_the_target_until_the_replace(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('spec_refs', KIT / 'comment-discipline' / 'scripts' / 'spec_refs.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules['spec_refs'] = module          # dataclasses and annotations look the module up by name
    spec.loader.exec_module(module)
    target = tmp_path / 'a.py'
    target.write_bytes(b'# spec 002 FR-001 here\n')

    def boom(a, b):
        raise OSError('no')
    monkeypatch.setattr(module.kit_spec.os, 'replace', boom)
    with pytest.raises(OSError):
        module.apply({target: [(0, (2, 17), '002/FR-001')]}, dry_run=False)
    assert target.read_bytes() == b'# spec 002 FR-001 here\n'
    assert [p.name for p in tmp_path.iterdir()] == ['a.py']


CRASH = ('import argparse, os.path, runpy, sys\n'
         'def boom(*a, **k):\n'
         '    raise RuntimeError("not foreseen")\n'
         'argparse.ArgumentParser.parse_args = boom\n'
         'os.path.isfile = boom\n'       # map_check.py reads its two arguments by hand
         'sys.argv = [sys.argv[1], "root", "doc"]\n'
         'runpy.run_path(sys.argv[0], run_name="__main__")\n')
EVERY_SCRIPT = sorted(p for p in KIT.glob('*/scripts/*.py') if p.name != 'kit_spec.py')


@pytest.mark.parametrize('script', EVERY_SCRIPT, ids=lambda p: p.name)
def test_a_crash_nobody_foresaw_exits_2_never_1(script):
    """1 is a verdict in every script; a traceback that exits 1 would be read as one."""
    r = subprocess.run([sys.executable, '-c', CRASH, str(script)], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 2, (script.name, r.returncode, r.stderr[-300:])
    assert 'Traceback' not in r.stderr and 'RuntimeError: not foreseen' in r.stdout + r.stderr


def test_a_hash_is_no_comment_where_the_language_has_none(tmp_path):
    css = '#header {\n  color: red;\n}\n#footer {\n  margin: 0;\n}\n/* why */\n'
    js = 'class A {\n  #count = 0;\n  #name;\n  // why\n  n() { return this.#count }\n}\n'
    assert 'comments=1 ' in audit_line(tmp_path, 'a.css', css).stdout
    assert 'comments=1 ' in audit_line(tmp_path, 'a.js', js).stdout
    assert 'comments=2 ' in audit_line(tmp_path, 'a.py', '# one\n# two\nx = 1\n').stdout


@pytest.mark.parametrize('name,text', [
    ('a.vue', '<template>\n  <x>\n    <template\n      #default="p"\n    >\n    </template>\n  </x>\n</template>\n'),
    ('a.sass', '#app\n  color: red\n#nav\n  margin: 0\n'), ('a.mts', 'class A {\n  #x = 1;\n}\n'),
    ('a.svelte', '<style>\n#app { color: red }\n</style>\n'), ('a.html', '<style>\n#app { color: red }\n</style>\n')])
def test_a_hash_is_no_comment_in_the_relatives_of_css_and_javascript(tmp_path, name, text):
    assert 'comments=0 ' in audit_line(tmp_path, name, text).stdout


def test_replace_refuses_a_read_only_file_by_its_name_and_leaves_nothing(tmp_path):
    sys.path.insert(0, str(KIT / 'kit-init' / 'scripts'))
    import kit_spec
    target = tmp_path / 'ro.py'
    target.write_bytes(b'old\n')
    target.chmod(0o444)
    try:
        with pytest.raises(PermissionError) as caught:
            kit_spec.replace(target, b'new\n')
        assert 'ro.py' in str(caught.value) and '.tmp' not in str(caught.value)
        assert target.read_bytes() == b'old\n'
        assert [p.name for p in tmp_path.iterdir()] == ['ro.py']
    finally:
        target.chmod(0o644)


def test_a_hash_inside_a_line_of_html_is_no_dated_comment(tmp_path):
    out = audit_line(tmp_path, 'a.html', '<p>Release # 2024-01-02 notes</p>\n').stdout
    assert 'dated=0 ' in out and 'OVER' not in out, out


@pytest.mark.parametrize('name', ['a.html.erb', 'a.blade.php', 'a.astro', 'a.pcss', 'a.xhtml'])
def test_a_hash_is_no_comment_in_templates_and_postcss(tmp_path, name):
    assert 'comments=0 ' in audit_line(tmp_path, name, '<style>\n#app { color: red }\n#nav { margin: 0 }\n</style>\n').stdout
