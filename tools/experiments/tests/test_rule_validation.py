"""Reusable patch guards, real-engine case reports, and non-mutating oracles."""

from pathlib import Path

import pytest

from tools.rule_validation.patches import Patch, apply
from tools.rule_validation.run import run


@pytest.mark.parametrize('name', ['lethal_attack', 'lethal_overload'])
def test_declarative_native_rule_cases(name, tmp_path):
    report = run(f'configs/rule_validation/{name}.toml', tmp_path / 'report')
    assert report['status'] == 'passed'
    assert report['outcomes']
    assert report['patch']['data_sha256']
    assert (tmp_path / 'report/result.json').is_file()


@pytest.mark.parametrize(
    'patch',
    [
        Patch('../escape.lua', 'a', 'b'),
        Patch('/tmp/escape.lua', 'a', 'b'),
        Patch('system/x.lua', 'missing', 'b'),
        Patch('system/x.lua', 'a', 'b'),
    ],
)
def test_invalid_patch_leaves_source_and_destination_untouched(patch, tmp_path):
    source = tmp_path / 'source'
    (source / 'system').mkdir(parents=True)
    p = source / 'system/x.lua'
    p.write_text('a a')
    destination = tmp_path / 'result'
    with pytest.raises(ValueError):
        apply(source, destination, [patch])
    assert p.read_text() == 'a a'
    assert not destination.exists()


def test_case_failure_still_writes_reviewable_report(tmp_path):
    src = Path('configs/rule_validation/lethal_attack.toml').read_text()
    config = tmp_path / 'wrong.toml'
    config.write_text(src.replace('winner = 0', 'winner = 1'))
    output = tmp_path / 'report'
    with pytest.raises(AssertionError, match='winner'):
        run(config, output)
    import json

    report = json.loads((output / 'result.json').read_text())
    assert report['status'] == 'failed' and report['outcomes']
