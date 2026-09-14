from tools.experiments.eval_ladder import BASELINES
from tools.experiments.semantic_training.ladder import summarize


def test_panel_intervals_cluster_layouts_and_sides():
    rows = []
    for baseline in BASELINES:
        for index in (0, 1):
            for side in (0, 1):
                for layout in (0, 1):
                    rows.append(
                        dict(
                            baseline=baseline,
                            seed=147000,
                            index=index,
                            side=side,
                            layout=layout,
                            team_0=['赤蝶', '墨客'],
                            team_1=['猫咪', '刻师傅'],
                            matchup='pair',
                            win=index,
                            timeout=False,
                            ends_with_skill=0,
                            steps=80,
                        )
                    )
    results = summarize(rows)
    for result in results.values():
        assert result['games'] == 8
        assert result['scenarios'] == 2
        assert result['score'] == 0.5
        assert result['ci95'] == [0, 1]
        assert result['per_side'] == {'0': 0.5, '1': 0.5}
        assert result['per_layout'] == {'0': 0.5, '1': 0.5}
