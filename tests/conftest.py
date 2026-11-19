import pytest


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
