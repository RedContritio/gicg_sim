import json
import numpy as np

from tools.experiments.character_balance import run as balance
from tools.experiments.character_balance.summarize import summarize


def test_balance_symmetric_pair_summary_and_mirror_separation(tmp_path):
    rows = []
    for profile in balance.PROFILES:
        for depth in (1, 2):
            for ai, a in enumerate(balance.CHARS):
                for b in balance.CHARS[ai:]:
                    for swap in (0, 1):
                        draw = a == '猫咪' and b == '天星'
                        rows.append(
                            dict(
                                profile=profile,
                                depth=depth,
                                a=a,
                                b=b,
                                index=0,
                                swap=swap,
                                score=0.5 if draw else 1.0,
                                draw=int(draw),
                                winner=2 if draw else swap,
                                initial_player=0,
                                steps=20,
                                final_view={'round': 4},
                            )
                        )
    (tmp_path / 'result.json').write_text(
        json.dumps(dict(status='complete', scenarios=1, games_done=len(rows), seed=0))
    )
    (tmp_path / 'games.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    summary = summarize(tmp_path)
    for panel in summary['panels'].values():
        matrix = np.array(panel['matrix'], dtype=float)
        np.testing.assert_allclose((matrix + matrix.T)[~np.eye(5, dtype=bool)], 1)
        assert all(panel['matrix'][i][i] is None for i in range(5))
        assert np.isclose(np.mean([r['score'] for r in panel['ranking']]), 0.5)
        assert len(panel['mirrors']) == 5 and len(panel['pairs']) == 10
        assert all(m['initial_player_score'] == 0.5 for m in panel['mirrors'])
        assert matrix[2, 4] == 0.5


def test_balance_profiles_preserve_base_config_and_swapped_characters():
    balance.initialize('configs/dmc/semantic_goal.toml')
    before = balance._CFG.scenario.team_0.copy()
    result = balance.play(('blank8', 1, '猫咪', '天星', 1, 1, 139000))
    assert result['winner'] in (0, 1, 2)
    assert balance._CFG.scenario.team_0 == before
    players = result['final_view']['players']
    assert players[0]['chars'][0]['name'] == '天星'
    assert players[1]['chars'][0]['name'] == '猫咪'
