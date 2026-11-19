"""spec_refs.py and spec_index.py."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import link

KIT = Path(__file__).resolve().parent.parent / 'plugins' / 'francis-kit' / 'skills'
REFS = KIT / 'comment-discipline' / 'scripts' / 'spec_refs.py'
INDEX = KIT / 'kit-init' / 'scripts' / 'spec_index.py'


def run(script, *args, cwd=None):
    return subprocess.run([sys.executable, str(script), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', cwd=cwd)


def git(repo, *args):
    subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True, encoding='utf-8')


def spec(repo, name, body):
    d = repo / 'specs' / name
    d.mkdir(parents=True, exist_ok=True)
    (d / 'spec.md').write_text(body, encoding='utf-8')


def project(tmp_path, files):
    git(tmp_path, 'init', '-q')
    spec(tmp_path, '001-login', '# Login\n\n**Status**: Built\n**Ticket**: none\n\n'
         '- **FR-001**: sign in\n- **FR-002**: sign out\n### FR-010 unique here\n')
    spec(tmp_path, '002-billing', '# Billing\n\n**Status**: Draft\n\n| FR-001 | charge |\n- **SC-001**: fast\n')
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode('utf-8'))      # bytes: Windows text mode would turn \n into \r\n
    git(tmp_path, 'add', '-A')
    return tmp_path


def summary(r):
    return dict(kv.split('=') for kv in r.stdout.splitlines()[0].split(': ', 1)[1].split())


def test_every_verdict(tmp_path):
    repo = project(tmp_path, {'src/a.py': (
        '# 001/FR-001 standard\n'
        '# 003/FR-001 no such feature\n'
        '# 002/FR-002 feature declares no such id\n'
        '# spec 002 FR-001 owner beside it\n'
        '# FR-001-002 dashed\n'
        '# FR-010 only one owner\n'
        '# FR-001 two owners\n'
        '# FR-099 nobody\n'
        '# see FR-002 (spec 002) wrong owner named\n'
        '# FR-999-002 dashed but 999 is no feature\n')})
    r = run(REFS, '--repo', repo, '--report')
    assert summary(r) == {'ok': '1', 'legacy': '2', 'unique': '1', 'contested': '1', 'undefined': '3',
                          'dead': '2', 'ignored_files': '0'}, r.stdout
    assert 'dead      src/a.py:2  003/FR-001' in r.stdout
    assert 'undefined src/a.py:9  FR-002' in r.stdout
    assert r.returncode == 0


def test_a_slash_list_is_not_a_standard_citation(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# FR-001/FR-002 both\n'})
    s = summary(run(REFS, '--repo', repo, '--report'))
    assert s['dead'] == '0' and s['ok'] == '0'


def test_declarations_numbered_list_and_removed_section(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# 003/FR-168\n# 003/FR-002\n'})
    spec(repo, '003-x', '1. **FR-168** numbered\n\n## Removed\n\n- **FR-002**: gone\n\n## Notes\n- **FR-003**: kept\n')
    git(repo, 'add', '-A')
    r = run(REFS, '--repo', repo, '--report')
    s = summary(r)
    assert s['ok'] == '1' and s['dead'] == '1', r.stdout
    assert '003/FR-002' in r.stdout and 'untested  003/FR-003' in r.stdout


def test_a_feature_number_used_twice_owns_nothing(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# spec 002 FR-001\n# 002/FR-001\n'})
    spec(repo, '002-other', '- **FR-001**: also\n')
    git(repo, 'add', '-A')
    s = summary(run(REFS, '--repo', repo, '--report'))
    assert s['dead'] == '1' and s['legacy'] == '0'
    assert 'would rewrite 0' in run(REFS, '--repo', repo, '--fix', '--dry-run').stdout


def test_check_is_a_ratchet(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# FR-001\n# FR-099\n'})
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 1 and 'FAIL contested: 1 now, baseline 0' in r.stdout
    assert run(REFS, '--repo', repo, '--write-baseline').returncode == 0
    assert json.loads((repo / 'specs' / '.kit-refs-baseline.json').read_text(encoding='utf-8')) == {
        'contested': 1, 'undefined': 1, 'ignored_files': 0}
    assert run(REFS, '--repo', repo, '--check').returncode == 0
    (repo / 'src' / 'a.py').write_text('# FR-001\n# FR-099\n# FR-001 again\n', encoding='utf-8')
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 1 and 'FAIL contested: 2 now, baseline 1' in r.stdout
    (repo / 'src' / 'a.py').write_text('# 001/FR-001\n# FR-099\n', encoding='utf-8')
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 0 and 'NOTE contested: 0 now, baseline 1' in r.stdout


def test_baseline_cannot_rise_quietly_and_pragma_is_counted(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# FR-099\n'})
    run(REFS, '--repo', repo, '--write-baseline')
    (repo / 'src' / 'b.py').write_text('# FR-098\n', encoding='utf-8')
    git(repo, 'add', '-A')
    r = run(REFS, '--repo', repo, '--write-baseline')
    assert r.returncode == 1 and 'refused: undefined' in r.stdout
    assert json.loads((repo / 'specs' / '.kit-refs-baseline.json').read_text(encoding='utf-8'))['undefined'] == 1
    assert run(REFS, '--repo', repo, '--write-baseline', '--allow-rise').returncode == 0
    (repo / 'src' / 'b.py').write_text('# spec-refs: ignore\n# 009/FR-001\n', encoding='utf-8')
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 1 and 'FAIL ignored_files: 1 now, baseline 0' in r.stdout


def test_bad_baseline_exits_2(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# FR-099\n'})
    (repo / 'specs' / '.kit-refs-baseline.json').write_text('[]', encoding='utf-8')
    assert run(REFS, '--repo', repo, '--check').returncode == 2
    (repo / 'specs' / '.kit-refs-baseline.json').write_text('{"undefined": "many"}', encoding='utf-8')
    assert run(REFS, '--repo', repo, '--check').returncode == 2


def test_dead_fails_even_inside_the_baseline(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# 009/FR-001\n'})
    run(REFS, '--repo', repo, '--write-baseline')
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 1 and 'point at nothing' in r.stdout


def fix(repo, *extra):
    return run(REFS, '--repo', repo, '--fix', *extra)


def test_fix_rewrites_a_line_only_when_it_names_one_owner_for_every_id(tmp_path):
    body = ('# spec 002 FR-001 here\n'                 # adjacent
            '# FR-001 (spec 002) owner after\n'         # owner later on the line
            '# spec 001 FR-001 and FR-002\n'            # siblings share the owner
            '# FR-001-002 dashed, FR-001 bare\n'        # a bare contested sibling
            '# FR-010 unique\n'                         # no owner written
            '# spec 001 FR-099 undeclared\n'            # owner declares no such id
            '# per spec 001, FR-001 of spec 002 wins\n' # two owners
            '# spec 001 FR-001/002\n'                   # list tail
            '# spec 001 FR-001 and SC-001\n'            # one id the owner lacks
            "# process (spec 001). FR-002's tests differ\n")  # owner in another sentence
    repo = project(tmp_path, {'src/a.py': body})
    r = fix(repo, '--dry-run')
    assert 'would rewrite 4 citation(s) in 1 file(s)' in r.stdout, r.stdout
    assert 'a.py:1  spec 002 FR-001  ->  002/FR-001' in r.stdout
    assert (repo / 'src' / 'a.py').read_text(encoding='utf-8') == body
    fix(repo)
    assert (repo / 'src' / 'a.py').read_text(encoding='utf-8').splitlines()[:3] == [
        '# 002/FR-001 here', '# 002/FR-001 (spec 002) owner after', '# 001/FR-001 and 001/FR-002']
    assert (repo / 'src' / 'a.py').read_text(encoding='utf-8').splitlines()[3:] == body.splitlines()[3:]
    assert 'would rewrite 0' in fix(repo, '--dry-run').stdout


def test_fix_does_not_raise_the_count(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# spec 001 FR-001 and FR-002\n# FR-001 (spec 002)\n# FR-099\n'})
    run(REFS, '--repo', repo, '--write-baseline')
    fix(repo)
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 0, r.stdout
    assert summary(r)['ok'] == '3'


def test_dashed_form_is_opt_in_and_needs_a_declaring_feature(tmp_path):
    body = '# FR-001-002 here\n# FR-001-099 not declared\n# FR-999-002 no feature\n'
    repo = project(tmp_path, {'src/a.py': body})
    assert 'would rewrite 0' in fix(repo, '--dry-run').stdout
    fix(repo, '--dashed')
    assert (repo / 'src' / 'a.py').read_text(encoding='utf-8') == '# 001/FR-002 here\n# FR-001-099 not declared\n# FR-999-002 no feature\n'


def test_fix_leaves_executable_text_alone(tmp_path):
    py = ('"""Module docstring: spec 001 FR-001."""\n'
          'import re\n'
          'MSG = "spec 001 FR-001"\n'
          'PAT = re.compile(r"spec 001 FR-001")\n'
          'def f():\n'
          '    """spec 001 FR-002 in a docstring."""\n'
          '    assert True, "spec 001 FR-001 failed"  # spec 001 FR-002 trailing\n'
          '    return "spec 001 FR-001"\n')
    js = "test.describe('spec 001 FR-001 login', () => {})\n// spec 001 FR-001 comment\n/**\n  * spec 001 FR-002 block\n */\n"
    yml = "name: spec 001 FR-001\n# spec 001 FR-002\n"
    php = "<?php\n$a = ['spec 001 FR-001'];\n    // spec 001 FR-002\n"
    bad = "def broken(:\n# spec 001 FR-001\n"
    repo = project(tmp_path, {'src/a.py': py, 'e2e/a.spec.js': js, 'ci.yml': yml, 'app/A.php': php, 'src/bad.py': bad})
    fix(repo)
    assert (repo / 'src' / 'a.py').read_text(encoding='utf-8') == (
        '"""Module docstring: 001/FR-001."""\n'
        'import re\n'
        'MSG = "spec 001 FR-001"\n'
        'PAT = re.compile(r"spec 001 FR-001")\n'
        'def f():\n'
        '    """001/FR-002 in a docstring."""\n'
        '    assert True, "spec 001 FR-001 failed"  # spec 001 FR-002 trailing\n'
        '    return "spec 001 FR-001"\n')
    assert (repo / 'e2e' / 'a.spec.js').read_text(encoding='utf-8') == (
        "test.describe('spec 001 FR-001 login', () => {})\n// 001/FR-001 comment\n/**\n  * 001/FR-002 block\n */\n")
    assert (repo / 'ci.yml').read_text(encoding='utf-8') == "name: spec 001 FR-001\n# 001/FR-002\n"
    assert (repo / 'app' / 'A.php').read_text(encoding='utf-8') == "<?php\n$a = ['spec 001 FR-001'];\n    // 001/FR-002\n"
    assert (repo / 'src' / 'bad.py').read_text(encoding='utf-8') == bad


def test_fix_keeps_every_other_byte(tmp_path):
    crlf = b'# spec 001 FR-001\r\nx = 1\r\n# spec 001 FR-002, spec 001 FR-001'
    binary = b'# spec 001 FR-001\nname = "\xff\xfe"\n'
    repo = project(tmp_path, {})
    (repo / 'src').mkdir()
    (repo / 'src' / 'crlf.py').write_bytes(crlf)
    (repo / 'src' / 'bin.py').write_bytes(binary)
    link((repo / 'src' / 'link.py'), 'crlf.py')
    git(repo, 'add', '-A')
    fix(repo)
    assert (repo / 'src' / 'crlf.py').read_bytes() == b'# 001/FR-001\r\nx = 1\r\n# 001/FR-002, 001/FR-001'
    assert (repo / 'src' / 'bin.py').read_bytes() == binary
    assert (repo / 'src' / 'link.py').is_symlink()
    assert summary(run(REFS, '--repo', repo, '--report'))['ok'] == '3'


def test_skips_specs_docs_untracked_and_pragma(tmp_path):
    repo = project(tmp_path, {'docs/x.py': '# FR-099\n', 'specs/001-login/x.py': '# FR-099\n',
                              'src/fixture.py': '# spec-refs: ignore\n# FR-099\n',
                              'README.md': 'FR-099\n'})
    (repo / 'src' / 'new.py').write_text('# FR-099\n', encoding='utf-8')
    assert summary(run(REFS, '--repo', repo, '--report'))['undefined'] == '0'


def test_untested_requirements_are_a_warning(tmp_path):
    repo = project(tmp_path, {'tests/test_login.py': '# 001/FR-001\n# FR-010\n',
                              'src/a.py': '# 001/FR-002\n'})
    r = run(REFS, '--repo', repo, '--check')
    assert r.returncode == 0 and 'WARN 3 requirement(s) cited by no test file' in r.stdout
    r = run(REFS, '--repo', repo, '--report')
    assert 'untested  001/FR-002' in r.stdout and 'untested  001/FR-001' not in r.stdout
    assert 'untested  001/FR-010' not in r.stdout and 'untested  002/FR-001' in r.stdout
    (repo / 'tests' / 'test_login.py').write_text('# FR-001 (spec 002)\n', encoding='utf-8')
    assert 'untested  002/FR-001' not in run(REFS, '--repo', repo, '--report').stdout


def test_touched_never_fails_and_lists_only_those_files(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# FR-099\n', 'src/b.py': '# FR-001\n'})
    (repo / 'src' / 'new.py').write_text('# FR-098\n', encoding='utf-8')
    r = run(REFS, '--repo', repo, '--touched', repo / 'src' / 'a.py', repo / 'src' / 'new.py')
    assert r.returncode == 0 and 'a.py:1' in r.stdout and 'new.py:1' in r.stdout and 'b.py' not in r.stdout
    r = run(REFS, '--repo', repo, '--touched', 'a.py', cwd=repo / 'src')
    assert r.returncode == 0 and 'src/a.py:1  FR-099' in r.stdout


def test_no_feature_exits_2(tmp_path):
    git(tmp_path, 'init', '-q')
    assert run(REFS, '--repo', tmp_path, '--check').returncode == 2
    assert run(REFS, '--repo', tmp_path, '--touched', 'x.py').returncode == 0


def test_sub_project_root_and_legacy_specs_dir(tmp_path):
    git(tmp_path, 'init', '-q')
    d = tmp_path / 'app' / '.specify' / 'specs' / '004-x'
    d.mkdir(parents=True)
    (d / 'spec.md').write_text('- **FR-001**: a\n', encoding='utf-8')
    (tmp_path / 'app' / 'src').mkdir()
    (tmp_path / 'app' / 'src' / 'a.py').write_text('# 004/FR-001\n', encoding='utf-8')
    (tmp_path / 'other.py').write_text('# FR-099\n', encoding='utf-8')
    git(tmp_path, 'add', '-A')
    s = summary(run(REFS, '--repo', tmp_path, '--root', 'app', '--report'))
    assert s['ok'] == '1' and s['undefined'] == '0'



def test_index_written_checked_and_stale(tmp_path):
    repo = project(tmp_path, {})
    assert run(INDEX, '--root', repo, '--check').returncode == 1
    r = run(INDEX, '--root', repo)
    assert r.returncode == 0 and '2 feature(s)' in r.stdout
    text = (repo / 'specs' / 'INDEX.md').read_text(encoding='utf-8')
    assert '| [001-login](001-login/spec.md) | Login | Built | none | - | 3 |' in text
    assert '| [002-billing](002-billing/spec.md) | Billing | Draft | - | - | 1 |' in text
    assert run(INDEX, '--root', repo, '--check').returncode == 0
    spec(repo, '003-new', '# New\n')
    assert run(INDEX, '--root', repo, '--check').returncode == 1
    assert run(INDEX, '--root', tmp_path / 'nowhere').returncode == 2


def test_index_ignores_frontmatter_and_fenced_headings(tmp_path):
    repo = project(tmp_path, {})
    spec(repo, '003-fm', '---\n# a yaml comment\nstatus: approved\n---\n  ```\n  # not the title\n  - **FR-009**: no\n  ```\n# Real title\r\n1. **FR-001** yes\n')
    run(INDEX, '--root', repo)
    assert '| [003-fm](003-fm/spec.md) | Real title | - | - | - | 1 |' in (repo / 'specs' / 'INDEX.md').read_text(encoding='utf-8')


def test_two_named_owners_that_both_declare_the_id_resolve_nothing(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# FR-001 as in spec 001 and spec 002\n'})
    s = summary(run(REFS, '--repo', repo, '--report'))
    assert s['legacy'] == '0' and s['undefined'] == '1'


def test_a_symlink_is_neither_judged_nor_written_through(tmp_path):
    repo = project(tmp_path, {'docs/x.py': '# spec 001 FR-001\n'})
    (repo / 'src').mkdir()
    link((repo / 'src' / 'l.py'), '../docs/x.py')
    git(repo, 'add', '-A')
    assert summary(run(REFS, '--repo', repo, '--report'))['legacy'] == '0'
    run(REFS, '--repo', repo, '--fix')
    assert (repo / 'docs' / 'x.py').read_text(encoding='utf-8') == '# spec 001 FR-001\n'


C = 'spec 001 FR-001'


def test_fix_skips_text_that_only_looks_like_a_comment(tmp_path):
    files = {
        'a.js': f'const x = base\n  * weights["{C}"];\nconst t = `\n// {C}\n * {C}\n`;\n',
        'a.php': f"<?php\n$s = <<<EOT\n# {C}\n// {C}\nEOT;\n",
        'a.yml': f'description: |\n  # {C}\nrun: >-\n  # {C}\nname: x\n',
        'a.vue': f'<template>\n  // {C}\n</template>\n<script setup>\nconst a = 1\n</script>\n',
        'a.go': f'# {C}\n',
        'ff.py': f'x = 1\n\x0c\ny = "{C} padding"\n',
        'doc.py': f'def q():\n    """SELECT 1 -- {C}"""\n    return q.__doc__\n',
        'dt.py': f'def d():\n    """\n    >>> d()\n    \'{C}\'\n    """\n    return "{C}"\n',
    }
    repo = project(tmp_path, {f'src/{k}': v for k, v in files.items()})
    assert 'would rewrite 0' in fix(repo, '--dry-run').stdout, fix(repo, '--dry-run').stdout
    fix(repo)
    for name, body in files.items():
        assert (repo / 'src' / name).read_bytes() == body.encode(), name


def test_fix_takes_real_comments_next_to_the_lookalikes(tmp_path):
    files = {
        'a.js': f'const t = `x`;\n// {C}\n',
        'a.php': f"<?php\n$s = <<<EOT\nx\nEOT;\n# {C}\n",
        'a.yml': f'run: |\n  echo hi\n# {C}\nname: x\n',
        'a.vue': f'<template>\n  <!-- {C} -->\n</template>\n<script setup>\n// {C}\n</script>\n',
        'ff.py': f'x = 1\n\x0c\n# {C}\n',
        'a.sql': f'-- {C}\n',
    }
    repo = project(tmp_path, {f'src/{k}': v for k, v in files.items()})
    assert 'would rewrite 7 citation(s) in 6 file(s)' in fix(repo, '--dry-run').stdout, fix(repo, '--dry-run').stdout


def test_fix_does_not_take_an_owner_from_a_loose_phrase(tmp_path):
    body = ('# superseded by spec 002, FR-001 no longer applies here\n'
            '# not spec 001: FR-001 is from the constitution\n'
            '# not spec 001 FR-001\n'
            '# spec 001 FR-001/FR-010\n'
            '# spec 001 FR-001 to FR-010\n'
            '# spec 001 FR-001..FR-010\n'
            '# spec 001 FR-001 then later FR-002\n'
            '# spec 001 FR-001, which unlike FR-002 stays\n')
    repo = project(tmp_path, {'src/a.py': body})
    assert 'would rewrite 0' in fix(repo, '--dry-run').stdout, fix(repo, '--dry-run').stdout


DATA_NOT_COMMENT = {
    'src/gen.sh': '#!/bin/sh\ncat > app.conf <<CONF\n# FR-001 of spec 001 is the header of the generated file\nCONF\n',
    'src/tilde.sh': 'cat <<~\'EOT\'\n  # spec 001 FR-002 stays as written\n  EOT\n',
    'src/dash.rb': 'text = <<-DOC\n# spec 001 FR-001\nDOC\n',
    'src/ci.yml': 'steps:\n  - |\n    # spec 001 FR-001 is printed by this script\n    echo done\n'
                  'note: !!str |\n  # spec 001 FR-002 too\n',
    'src/shift.py': 'a = 1\rb = """\n# spec 001 FR-001 inside a string\n"""\n',
}


@pytest.mark.parametrize('name', DATA_NOT_COMMENT)
def test_fix_leaves_data_that_only_looks_like_a_comment(tmp_path, name):
    body = DATA_NOT_COMMENT[name]
    repo = project(tmp_path, {name: body, 'src/real.sh': '# spec 001 FR-001 is checked here\necho ok\n'})
    run(REFS, '--repo', repo, '--fix')
    assert (repo / name).read_bytes() == body.encode('utf-8'), name
    assert b'001/FR-001' in (repo / 'src' / 'real.sh').read_bytes()       # the fix itself still works


def test_a_here_string_is_not_a_heredoc(tmp_path):
    repo = project(tmp_path, {'src/h.sh': 'grep x <<< "$CONF"\n# spec 001 FR-001 is a real comment\n'})
    run(REFS, '--repo', repo, '--fix')
    assert b'# spec 001 001/FR-001' in (repo / 'src' / 'h.sh').read_bytes() or b'001/FR-001' in (repo / 'src' / 'h.sh').read_bytes()


def test_dry_run_names_the_file_by_its_path_not_its_name(tmp_path):
    repo = project(tmp_path, {'src/a.py': '# spec 002 FR-001 here\n', 'lib/a.py': '# spec 002 FR-001 there\n'})
    out = fix(repo, '--dry-run').stdout
    assert '  src/a.py:1  spec 002 FR-001  ->  002/FR-001' in out and '  lib/a.py:1  ' in out, out


def test_fix_writes_no_file_when_one_of_them_is_read_only(tmp_path):
    files = {f'src/{n}.py': '# spec 001 FR-010 here\n' for n in 'abc'}
    repo = project(tmp_path, files)
    before = {n: (repo / n).read_bytes() for n in files}
    (repo / 'src' / 'b.py').chmod(0o444)
    try:
        r = run(REFS, '--repo', repo, '--fix')
        assert r.returncode == 2 and 'b.py' in r.stdout + r.stderr, r.stdout + r.stderr
        assert {n: (repo / n).read_bytes() for n in files} == before
    finally:
        (repo / 'src' / 'b.py').chmod(0o644)


@pytest.mark.skipif(sys.platform != 'win32', reason='only Windows refuses to replace a file another handle holds')
def test_fix_puts_back_what_it_wrote_when_a_later_file_cannot_be_replaced(tmp_path):
    files = {f'src/{n}.py': '# spec 001 FR-010 here\n' for n in 'abc'}
    repo = project(tmp_path, files)
    before = {n: (repo / n).read_bytes() for n in files}
    with open(repo / 'src' / 'b.py', 'rb'):
        r = run(REFS, '--repo', repo, '--fix')
    assert r.returncode == 2, r.stdout + r.stderr
    assert {n: (repo / n).read_bytes() for n in files} == before


def test_a_project_root_given_by_hand_outside_the_repository_does_not_blame_a_manifest(tmp_path):
    repo = project(tmp_path, {})
    audit = REFS.parents[2] / 'kit-init' / 'scripts' / 'claude_md_audit.py'
    r = run(audit, '--repo', repo, '--project-root', '..')
    assert r.returncode == 2 and 'kit.yml' not in r.stdout + r.stderr, r.stdout + r.stderr
