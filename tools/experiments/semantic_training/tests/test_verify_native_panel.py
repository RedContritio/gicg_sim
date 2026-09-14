from copy import deepcopy
from dataclasses import asdict

import pytest

from tools.experiments.semantic_training.teams import eval_cases
from tools.experiments.semantic_training.verify_native_panel import verify
from training.core.config.loader import load_cfg


@pytest.fixture
def panel():
    cfg = load_cfg('configs/dmc/native_starter.toml')
    games = []
    for i, case in enumerate(eval_cases(cfg, 941900, 55)):
        for side in (0, 1):
            for layout in (0, 1):
                games.append(
                    dict(
                        index=i,
                        side=side,
                        layout=layout,
                        team_0=case.team_0,
                        team_1=case.team_1,
                        win=1,
                        draw=0,
                        score=1,
                        trajectory_sha256='c' * 64,
                    )
                )
    report = dict(
        status='complete',
        seed=941900,
        scenarios=55,
        layouts=2,
        opponent_depth=2,
        checkpoint_sha256='a' * 64,
        scenario=asdict(cfg.scenario),
        max_game_steps=cfg.paradigm['max_game_steps'],
        provenance={'source_observation_sha256': 'b' * 64},
        games=games,
        score=1,
    )
    return cfg, report


def check(cfg, report):
    return verify(report, cfg, seed=941900, depth=2, scenarios=55, checkpoint_sha256='a' * 64, source_sha256='b' * 64)


def test_complete_reordered_panel_recomputed(panel):
    cfg, report = panel
    report['games'].reverse()
    report['cluster_bootstrap95'] = [0, 0]  # Never trust supplied confidence intervals.
    result = check(cfg, report)
    assert result['strength_gate_passed']
    assert result['cluster_bootstrap95'] == [1, 1]
    assert result['games'] == 220


@pytest.mark.parametrize(
    'mutation',
    [
        lambda r: r.pop('scenario'),
        lambda r: r.update(status='running'),
        lambda r: r.update(seed=1),
        lambda r: r.update(checkpoint_sha256='f' * 64),
        lambda r: r['provenance'].update(source_observation_sha256='f' * 64),
        lambda r: r['scenario'].update(random_deck_size=20),
        lambda r: r['games'].__setitem__(1, deepcopy(r['games'][0])),
        lambda r: r['games'][0].update(team_0=['迪卢克'] * 3),
        lambda r: r['games'][0].update(score=float('nan')),
        lambda r: r['games'][0].update(trajectory_sha256='d' * 64),
        lambda r: r.update(score=0.7),
        lambda r: r.update(variants='variant.toml'),
        lambda r: r['games'][0].update(rule_variant={'variant': True}),
    ],
)
def test_reject_corrupted_or_unpaired_evidence(panel, mutation):
    cfg, report = panel
    mutation(report)
    with pytest.raises(ValueError):
        check(cfg, report)


def test_valid_panel_can_fail_strength_gate(panel):
    cfg, report = panel
    for row in report['games']:
        row.update(win=row['side'], score=row['side'])
    report['score'] = 0.5
    result = check(cfg, report)
    assert result['cluster_bootstrap95'] == [0.5, 0.5]
    assert not result['strength_gate_passed']


def test_d1_requires_practical_margin_as_well_as_significance(panel):
    cfg, report = panel
    for row in report['games']:
        win = int(row['side'] == 0 or row['index'] < 10)
        row.update(win=win, score=win)
    report['score'] = 65 / 110
    assert check(cfg, report)['strength_gate_passed']  # D2 lower bound exceeds 50%.
    report['opponent_depth'] = 1
    result = verify(
        report,
        cfg,
        seed=941900,
        depth=1,
        scenarios=55,
        checkpoint_sha256='a' * 64,
        source_sha256='b' * 64,
    )
    assert result['cluster_bootstrap95'][0] > 0.5
    assert not result['strength_gate_passed']  # D1 still needs at least 60%.
