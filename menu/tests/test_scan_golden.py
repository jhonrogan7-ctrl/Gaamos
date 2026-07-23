"""Golden cases drawn from the four real client menus in /root/zxyn/gaamos/menius/.

Each entry is a documented failure of the old flat {name, description, price}
schema. Pure normalize_item calls: no database, no network. Treat a failure here
as a regression in the extraction contract, not a flaky test.
"""
import json
from pathlib import Path

import pytest

from menu.pipeline import normalize

GOLDEN = Path(__file__).parent / 'fixtures' / 'scan_golden.json'
CASES = json.loads(GOLDEN.read_text())


@pytest.mark.parametrize('case', CASES, ids=[c['id'] for c in CASES])
def test_golden_case(case):
    page_types = {int(k): v for k, v in case.get('page_types', {}).items()}
    got = normalize.normalize_item(case['raw'], page_types, threshold=0.7)
    for key, want in case['expect'].items():
        assert got[key] == want, f"{case['id']} · {key}: {case['why']}"


def test_every_documented_failure_is_covered():
    """Guards against the fixture being trimmed down over time."""
    assert len(CASES) >= 10
    ids = {c['id'] for c in CASES}
    assert 'kailash-hard-drinks-matrix-60ml' in ids
    assert 'tranquility-red-bull-blue' in ids
    assert 'tag-invention-is-stripped' in ids
