"""The kit's own diagrams must keep matching the kit's code."""
import pytest
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CITE_REFS = REPO / 'plugins' / 'francis-kit' / 'skills' / 'map-project' / 'scripts' / 'cite_refs.py'


@pytest.mark.private
def test_own_diagrams_cite_code_that_exists():
    r = subprocess.run([sys.executable, str(CITE_REFS), '--diagrams', str(REPO / 'docs' / 'diagrams'),
                        '--check'], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'checked' in r.stdout and ' in 2 file(s)' in r.stdout
