"""A frozen baseline must detect drift and refuse silent overwrite."""

import json
from unittest.mock import patch

import pytest

from tools.cards.rule_baseline import check, freeze


@pytest.fixture
def baseline(tmp_path):
    for name in (
        'data/system/round.lua',
        'data/pools/v_legacy/card.lua',
        'data/pools/test_basic/card.lua',
        'gicg_engine/cost.go',
        'configs/dmc/default.toml',
        'go.mod',
        'tools/cards/rule_baseline.py',
        'baseline/rules.md',
        'baseline/interactions.md',
    ):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('initial\n')
    manifest = tmp_path / 'baseline/source-manifest.json'
    with patch('tools.cards.rule_baseline.subprocess.check_output', return_value='commit\n'):
        freeze(tmp_path, manifest, 'test-v1')
    return tmp_path, manifest


def test_unchanged_and_no_overwrite(baseline):
    root, manifest = baseline
    original = manifest.read_bytes()
    assert check(root, manifest)
    with patch('tools.cards.rule_baseline.subprocess.check_output', return_value='other\n'):
        with pytest.raises(FileExistsError):
            freeze(root, manifest, 'test-v2')
    assert manifest.read_bytes() == original
    assert json.loads(original)['baseline'] == 'test-v1'


@pytest.mark.parametrize('mutation', ['changed', 'added', 'removed', 'rules_removed'])
def test_detects_drift(baseline, mutation, capsys):
    root, manifest = baseline
    path = root / 'data/system/round.lua'
    if mutation == 'changed':
        path.write_text('different\n')
    elif mutation == 'added':
        (path.parent / 'new.lua').write_text('new\n')
    elif mutation == 'rules_removed':
        (manifest.parent / 'rules.md').unlink()
    else:
        path.unlink()
    assert not check(root, manifest)
    assert 'Baseline drift' in capsys.readouterr().out
