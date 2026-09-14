from copy import deepcopy
import json

import pytest

from tools.experiments.semantic_training.compare import compare


def reports(tmp_path, mutate=lambda r: None):
    games = [
        dict(index=i, side=s, layout=l, score=s, rule_variant={'variant': True, 'seed': i})
        for i in range(3)
        for s in (0, 1)
        for l in (0, 1)
    ]
    baseline = dict(
        status='complete',
        seed=100,
        scenarios=3,
        layouts=2,
        opponent_depth=2,
        provenance={'source_observation_sha256': 'a' * 64},
        games=games,
        score=0.5,
        checkpoint='baseline.pt',
        checkpoint_sha256='b' * 64,
        per_layout=[0.5, 0.5],
        variants='catalog.toml',
        scenario={'pool': 'native_latest'},
        max_game_steps=512,
    )
    candidate = deepcopy(baseline)
    candidate.update(checkpoint='candidate.pt', checkpoint_sha256='c' * 64)
    mutate(candidate)
    paths = [tmp_path / name for name in ('a.json', 'b.json', 'result.json')]
    for p, r in zip(paths, (baseline, candidate)):
        p.write_text(json.dumps(r))
    return paths


def test_same_scores_have_zero_paired_interval(tmp_path):
    result = compare(*reports(tmp_path))
    assert result['delta'] == 0 and result['paired_cluster95'] == [0, 0]


@pytest.mark.parametrize(
    'mutate',
    [
        lambda r: r['games'][0]['rule_variant'].update(seed=999),
        lambda r: r.update(variants=None),
        lambda r: r.update(max_game_steps=1024),
        lambda r: r.update(score=0.8),
        lambda r: r['games'][0].update(score=float('nan')),
        lambda r: r['games'].__setitem__(1, r['games'][0]),
    ],
)
def test_reject_unpaired_or_corrupted_variant_comparison(tmp_path, mutate):
    with pytest.raises(ValueError):
        compare(*reports(tmp_path, mutate))
