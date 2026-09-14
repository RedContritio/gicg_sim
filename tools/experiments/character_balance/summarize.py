"""Paired-scene bootstrap and equal-opponent character balance summaries."""

import argparse
from collections import defaultdict
import json
from pathlib import Path

import numpy as np
from tools.experiments.character_balance.run import CHARS, PROFILES


def summarize(root):
    root = Path(root)
    status = json.loads((root / 'result.json').read_text())
    if status['status'] != 'complete':
        raise ValueError('balance run incomplete')
    groups = defaultdict(list)
    with (root / 'games.jsonl').open(encoding='utf-8') as f:
        for line in f:
            row = json.loads(line)
            groups[row['profile'], row['depth'], row['a'], row['b']].append(row)
    n = status['scenarios']
    sampled = np.random.default_rng(139001).integers(n, size=(10000, n))
    panels = {}
    for profile in PROFILES:
        for depth in (1, 2):
            matrix = np.full((5, 5), np.nan)
            opponents = defaultdict(list)
            draws = defaultdict(list)
            pairs, mirrors = [], []
            for ai, a in enumerate(CHARS):
                for bi in range(ai, len(CHARS)):
                    b = CHARS[bi]
                    rows = sorted(groups[profile, depth, a, b], key=lambda r: (r['index'], r['swap']))
                    if [(r['index'], r['swap']) for r in rows] != [(i, s) for i in range(n) for s in (0, 1)]:
                        raise ValueError('missing or duplicate paired games')
                    scores = np.array([r['score'] for r in rows]).reshape(n, 2).mean(1)
                    draw = np.array([r['draw'] for r in rows]).reshape(n, 2).mean(1)
                    info = dict(
                        a=a,
                        b=b,
                        score=float(scores.mean()),
                        draw_rate=float(draw.mean()),
                        ci95=np.quantile(scores[sampled].mean(1), [0.025, 0.975]).tolist(),
                        timeout_tiebreaks=sum(
                            r['final_view']['round'] >= 10
                            and r['winner'] in (0, 1)
                            and all(p['alive_count'] > 0 for p in r['final_view']['players'])
                            for r in rows
                        ),
                        mean_steps=float(np.mean([r['steps'] for r in rows])),
                        mean_round=float(np.mean([r['final_view']['round'] for r in rows])),
                        cap_reached=sum(r['final_view']['round'] >= PROFILES[profile][1] for r in rows),
                        a_slot0_score=float(np.mean([r['score'] for r in rows if r['swap'] == 0])),
                        a_slot1_score=float(np.mean([r['score'] for r in rows if r['swap'] == 1])),
                    )
                    if ai == bi:
                        info['initial_player_score'] = float(
                            np.mean([0.5 if r['draw'] else float(r['winner'] == r['initial_player']) for r in rows])
                        )
                        mirrors.append(info)
                        continue
                    matrix[ai, bi], matrix[bi, ai] = scores.mean(), 1 - scores.mean()
                    opponents[a].append(scores)
                    opponents[b].append(1 - scores)
                    draws[a].append(draw)
                    draws[b].append(draw)
                    pairs.append(info)
            ranking = []
            for a in CHARS:
                scores = np.stack(opponents[a]).mean(0)
                draw = np.stack(draws[a]).mean(0)
                ranking.append(
                    dict(
                        character=a,
                        score=float(scores.mean()),
                        win_rate=float((scores - draw / 2).mean()),
                        draw_rate=float(draw.mean()),
                        ci95=np.quantile(scores[sampled].mean(1), [0.025, 0.975]).tolist(),
                    )
                )
            panels[f'{profile}_D{depth}'] = dict(
                matrix=[[None if np.isnan(v) else float(v) for v in row] for row in matrix],
                ranking=ranking,
                pairs=pairs,
                mirrors=mirrors,
            )
    result = dict(
        characters=CHARS,
        scenarios=n,
        total_games=status['games_done'],
        panels=panels,
        seed=status['seed'],
        scope='symmetric F1 policies; 1v1 current pool; not optimal-play or team balance',
    )
    (root / 'summary.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    for name, panel in panels.items():
        print(
            name,
            [(r['character'], round(r['score'] * 100, 2), round(r['draw_rate'] * 100, 2)) for r in panel['ranking']],
        )
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root')
    summarize(p.parse_args().root)
