"""Verify paired variant matches against an independently supplied catalog."""

from copy import deepcopy
from dataclasses import asdict

from tools.rule_validation.variants import specification, sample
from tools.experiments.semantic_training.verify_native_panel import verify
from training.core.episode_seeds import derive_seed


def verify_variants(report, cfg, catalog, *, seed, checkpoint_sha256, source_sha256, scenarios=55):
    spec, digest = specification(catalog)
    if not report.get('variants'):
        raise ValueError('expected variant panel')
    by_case = {}
    for game in report.get('games', []):
        manifest = game.get('rule_variant', {})
        rule_seed = derive_seed(seed, 'rule-variant', game['index'])
        patches, changes = sample(spec, rule_seed, game['team_0'] + game['team_1'], 'heldout')
        expected = dict(
            variant=True,
            split='heldout',
            seed=rule_seed,
            specification_sha256=digest,
            pool='native_latest',
            patches=[asdict(p) for p in patches],
            changes=changes,
        )
        if any(manifest.get(k) != v for k, v in expected.items()):
            raise ValueError('variant manifest differs from declared case')
        if game['index'] in by_case and manifest != by_case[game['index']]:
            raise ValueError('variant differs across sides or layouts')
        by_case[game['index']] = manifest
    # Reuse game coverage, roster, trajectory, score and confidence checks only.
    cleaned = deepcopy(report)
    cleaned.pop('variants', None)
    for game in cleaned.get('games', []):
        game.pop('rule_variant', None)
    result = verify(
        cleaned,
        cfg,
        seed=seed,
        depth=2,
        checkpoint_sha256=checkpoint_sha256,
        source_sha256=source_sha256,
        scenarios=scenarios,
    )
    result.update(
        scope='single held-out-parameter variant panel, not native or repeated-run acceptance',
        variant_specification_sha256=digest,
    )
    return result
