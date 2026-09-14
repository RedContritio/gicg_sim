from dataclasses import asdict

import pytest

from tools.experiments.semantic_training.tests.test_verify_native_panel import panel
from tools.rule_validation.variants import specification, sample
from tools.rule_validation.verify_panel import verify_variants
from training.core.episode_seeds import derive_seed

CATALOG = 'configs/rule_validation/native_variants.toml'


def prepared(panel):
    cfg, report = panel
    report['variants'] = CATALOG
    spec, digest = specification(CATALOG)
    for g in report['games']:
        seed = derive_seed(941900, 'rule-variant', g['index'])
        patches, changes = sample(spec, seed, g['team_0'] + g['team_1'], 'heldout')
        g['rule_variant'] = dict(
            variant=True,
            split='heldout',
            seed=seed,
            specification_sha256=digest,
            pool='native_latest',
            patches=[asdict(p) for p in patches],
            changes=changes,
            data_sha256='d' * 64,
        )
    return cfg, report


def check(cfg, report):
    return verify_variants(
        report, cfg, CATALOG, seed=941900, scenarios=55, checkpoint_sha256='a' * 64, source_sha256='b' * 64
    )


def test_reconstructs_variants_and_does_not_mutate_report(panel):
    cfg, report = prepared(panel)
    assert check(cfg, report)['score'] == 1
    assert report['variants'] and report['games'][0]['rule_variant']['variant']


@pytest.mark.parametrize(
    'key,value',
    [
        ('seed', 0),
        ('split', 'train'),
        ('changes', []),
        ('variant', False),
        ('specification_sha256', 'f' * 64),
        ('patches', []),
        ('data_sha256', 'e' * 64),
    ],
)
def test_reject_wrong_or_unpaired_variants(panel, key, value):
    cfg, report = prepared(panel)
    report['games'][0]['rule_variant'][key] = value
    with pytest.raises(ValueError):
        check(cfg, report)
