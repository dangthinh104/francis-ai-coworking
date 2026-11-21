import atexit
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def kit_source():
    """A bare repository of this kit's `plugins` directory, one commit tagged with the version of plugin.json.

    A gate run of the scaffold reads the commit of that tag from the source (026/FR-003), and the suite runs
    without the network: the source every git of the run sees by default is this repository.
    """
    base = Path(tempfile.mkdtemp(prefix='kit-source-'))
    atexit.register(shutil.rmtree, base, True)
    work, bare = base / 'kit', base / 'kit.git'
    shutil.copytree(REPO / 'plugins', work / 'plugins', ignore=shutil.ignore_patterns('__pycache__'))
    version = json.loads((work / 'plugins' / 'francis-kit' / '.claude-plugin' / 'plugin.json')
                         .read_text(encoding='utf-8'))['version']
    # The person's own hooks and templates do not run on this copy: a hook that fails would stop the whole run.
    ident = ['-c', 'user.email=k@example.invalid', '-c', 'user.name=k', '-c', 'commit.gpgsign=false',
             '-c', 'tag.gpgsign=false', '-c', 'core.autocrlf=false', '-c', f'core.hooksPath={base.as_posix()}/no-hooks']
    for args in (['init', '-q', '--template='], ['add', '-A'], ['commit', '-q', '--no-verify', '-m', 'kit'],
                 ['tag', '-a', '-m', 'kit', 'v' + version]):
        subprocess.run(['git', *ident, *args], cwd=work, check=True, capture_output=True)
    subprocess.run(['git', 'clone', '-q', '--bare', str(work), str(bare)], check=True, capture_output=True)
    return base, bare


def use_kit_source():
    """`kit.gateSource` in a global config of the run's own, which still reads the person's global config.

    A repository's own `kit.gateSource` wins over a global one, so a test that sets it keeps its own source.
    """
    base, bare = kit_source()
    own = os.environ.get('GIT_CONFIG_GLOBAL')
    home = Path(os.environ.get('HOME') or Path.home())     # git reads HOME, also on Windows
    # In git's own order: the XDG file first, then ~/.gitconfig, which wins where both set a key.
    included = [own] if own else [str(Path(os.environ.get('XDG_CONFIG_HOME') or home / '.config') / 'git' / 'config'),
                                  str(home / '.gitconfig')]
    lines = [f'[include]\n\tpath = {Path(p).as_posix()}\n' for p in included if Path(p).is_file()]
    lines.append(f'[kit]\n\tgateSource = {bare.as_posix()}\n')
    config = base / 'gitconfig'
    config.write_text(''.join(lines), encoding='utf-8')
    os.environ['GIT_CONFIG_GLOBAL'] = str(config)
    return bare


KIT_SOURCE = use_kit_source()


def pytest_configure(config):
    config.addinivalue_line('markers', 'private: needs a file only the private repository has '
                            '(its specs, changelog, tags, evals or a project fixture), or tests the secret step the public '
                            'gate does not have; the public copy leaves it out')


def link(path, target):
    """Create a symlink for a test, or skip that one test where the account may not.

    Only Windows error 1314 (the privilege is not held) is a reason to skip; any
    other error is a real failure. pytest's own symlinks are left alone: wrapping
    `Path.symlink_to` for everyone turned its `tmp_path` bookkeeping into a skip
    of nearly the whole suite.
    """
    try:
        path.symlink_to(target)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('this account cannot create symlinks')
        raise


def pytest_sessionfinish(session, exitstatus):
    """A run that skipped more than it ran proved little: it must not read as green."""
    reporter = session.config.pluginmanager.get_plugin('terminalreporter')
    if reporter is None or exitstatus != 0:
        return
    skipped, passed = len(reporter.stats.get('skipped', [])), len(reporter.stats.get('passed', []))
    if skipped > passed and skipped + passed > 20:      # a hand-picked `-k` of one skipped test is not a run
        reporter.write_line(f'FAILED: {skipped} tests skipped and only {passed} ran. '
                            f'This run proves almost nothing; see "Known limits" in README.md.', red=True)
        session.exitstatus = 1


def pytest_collection_modifyitems(config, items):
    """The public copy has no specs, changelog, evals or project fixtures."""
    items[:] = [i for i in items if i.get_closest_marker('private') is None]
