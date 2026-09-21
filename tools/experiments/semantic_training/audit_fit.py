"""Measure policy fit on stored teacher episodes: imitation-gap diagnostics.

Answers one question: is a warmup policy underfitting the teacher labels on the
teacher's own state distribution, or does it already fit them (implying the
imitation gap is compounding/distribution-shift, not optimization)?

Metrics per sampled decision row: top-1-in-tied agreement, probability mass on
the teacher tied set, uniform-over-tied cross-entropy (the training objective),
policy entropy over legal actions, legal/tied counts, chance agreement, and the
agreement curve by decision position within the episode.

Read-only: loads checkpoints and episode files, writes one JSON report.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random

import torch

from tools.experiments.semantic_training.agent import batch_observations
from tools.experiments.semantic_training.player_loader import load_semantic_agent


def audit(config, checkpoint, teacher_dir, output, samples=512, seed=94310, device='cuda'):
    teacher_dir = Path(teacher_dir)
    files = sorted(teacher_dir.glob('episode_*.pt'))
    if not files:
        raise ValueError('no teacher episode files found')
    torch.set_num_threads(1)
    rng = random.Random(seed)
    # Uniform reservoir over rows; keep per-row episode position for the position curve.
    rows, seen = [], 0
    for path in files:
        for position, row in enumerate(torch.load(path, map_location='cpu', weights_only=False)['rows']):
            seen += 1
            item = (position, row)
            if len(rows) < samples:
                rows.append(item)
            else:
                j = rng.randrange(seen)
                if j < samples:
                    rows[j] = item
    if not rows:
        raise ValueError('empty teacher dataset')
    agent = load_semantic_agent(checkpoint, device=device)
    totals = dict(
        agreement=0.0,
        tied_mass=0.0,
        uniform_ce=0.0,
        entropy=0.0,
        n_legal=0.0,
        n_tied=0.0,
        chance=0.0,
    )
    by_position = {}
    with torch.no_grad():
        for start in range(0, len(rows), 16):
            chunk = rows[start : start + 16]
            batch = batch_observations([r['obs'] for _, r in chunk], agent.cfg, device)
            logits = agent.net(batch).masked_fill(~batch['legal_mask'], -1e9)
            logp = logits.log_softmax(-1)
            for i, (position, row) in enumerate(chunk):
                n = int(batch['legal_mask'][i].sum())
                lp = logp[i, :n].cpu()
                p = lp.exp()
                tied = torch.as_tensor(row['tied'], dtype=torch.long)
                chosen = int((logits[i, :n] * 1e5).round().argmax())
                totals['agreement'] += float(chosen in row['tied'])
                totals['tied_mass'] += float(p[tied].sum())
                totals['uniform_ce'] += float(-lp[tied].mean())
                totals['entropy'] += float(-(p * lp).sum())
                totals['n_legal'] += n
                totals['n_tied'] += len(row['tied'])
                totals['chance'] += len(row['tied']) / n
                bucket = by_position.setdefault(min(position // 10, 11), [0, 0])
                bucket[0] += float(chosen in row['tied'])
                bucket[1] += 1
    report = dict(
        scope='teacher-state fit; not heldout rule generalization',
        config=config,
        checkpoint=checkpoint,
        checkpoint_sha256=hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        teacher_dir=str(teacher_dir),
        teacher_episodes=len(files),
        population=seen,
        sample=len(rows),
        metrics={k: v / len(rows) for k, v in totals.items()},
        agreement_by_position_bucket={str(k): v[0] / v[1] for k, v in sorted(by_position.items())},
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('teacher_dir')
    p.add_argument('output')
    p.add_argument('--samples', type=int, default=512)
    p.add_argument('--seed', type=int, default=94310)
    p.add_argument('--device', default='cuda')
    a = p.parse_args()
    audit(a.config, a.checkpoint, a.teacher_dir, a.output, a.samples, a.seed, a.device)
