"""tools/export_public.py: the public copy names no project and no private repository."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXPORT = ROOT / 'tools' / 'export_public.py'


@pytest.mark.private
def test_the_public_copy_holds_no_forbidden_word(tmp_path):
    out = tmp_path / 'pub'
    run = subprocess.run([sys.executable, str(EXPORT), str(out)], capture_output=True, text=True, encoding='utf-8')
    assert run.returncode == 0, run.stdout + run.stderr
    assert '0 forbidden word(s) left' in run.stdout
    assert (out / 'LICENSE').is_file() and (out / 'README.md').is_file()
    assert not (out / 'specs').exists() and not (out / 'CHANGELOG.md').exists() and not (out / 'evals').exists()
    gate = (out / 'plugins/francis-kit/skills/kit-init/templates/common/kit-gate.yml').read_text(encoding='utf-8')
    assert 'repository: dangthinh104/francis-ai-coworking' in gate
    assert 'KIT_READ_TOKEN' not in gate and 'secrets.' not in gate
    for skill in ('kit-init', 'kit-adopt'):
        assert 'KIT_READ_TOKEN' not in (out / f'plugins/francis-kit/skills/{skill}/SKILL.md').read_text(encoding='utf-8')
    assert 'pytest_collection_modifyitems' in (out / 'tests' / 'conftest.py').read_text(encoding='utf-8')
    assert 'the secret' not in (out / 'plugins/francis-kit/skills/kit-init/SKILL.md').read_text(encoding='utf-8')


@pytest.mark.private
def test_every_readme_section_the_public_copy_names_is_in_its_readme(tmp_path):
    """A skill or a test that says 'see README, "<section>"' must find that section in the public README."""
    out = tmp_path / 'pub'
    assert subprocess.run([sys.executable, str(EXPORT), str(out)], capture_output=True).returncode == 0
    headings = {l.lstrip('#').strip() for l in (out / 'README.md').read_text(encoding='utf-8').splitlines()
                if l.startswith('#')}
    named = set()
    for p in list((out / 'plugins').rglob('*.md')) + list((out / 'tests').rglob('*.py')):
        named |= set(re.findall(r'README(?:\.md)?[,"\s]+"([A-Z][^"]+)"', p.read_text(encoding='utf-8')))
    assert named and named <= headings, sorted(named - headings)


@pytest.mark.private
def test_the_export_refuses_a_directory_that_is_not_empty(tmp_path):
    (tmp_path / 'x').write_text('x', encoding='utf-8')
    run = subprocess.run([sys.executable, str(EXPORT), str(tmp_path)], capture_output=True, text=True, encoding='utf-8')
    assert run.returncode == 2 and 'not empty' in run.stdout
