"""Paired untrained/teacher/supervised controls on fresh development scenarios."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.evaluate import evaluate
from tools.experiments.semantic_training.player_loader import FORMAT
from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.network import AgentConfig


def run(config, checkpoint, output, scenarios=128, workers=16):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    torch.set_num_threads(1)
    # Exact original warm-up initialization, before any optimizer updates.
    torch.manual_seed(123001)
    shape = AgentConfig(**payload['shape'])
    agent = SemanticAgent(shape)
    initial = root / 'untrained.pt'
    save_checkpoint({'format': FORMAT, 'net': agent.net.state_dict(), 'shape': vars(shape)}, initial)
    panels = [('untrained', str(initial)), ('teacher', 'teacher-d2'), ('supervised', checkpoint)]
    result = {}
    for name, model in panels:
        evaluate(config, model, root / name, scenarios, 4, workers, 127000)
        result[name] = json.loads((root / name / 'result.json').read_text())
    rng = np.random.default_rng(127001)
    bootstrap = rng.integers(scenarios, size=(10000, scenarios))
    scores = {
        name: np.array([g['score'] for g in panel['games']]).reshape(scenarios, 2, 4).mean(axis=(1, 2))
        for name, panel in result.items()
    }
    summary = {
        name: {k: panel[k] for k in ['score', 'per_layout', 'wins', 'draws', 'cluster_bootstrap95']}
        for name, panel in result.items()
    }
    summary['paired_supervised_minus_untrained95'] = np.quantile(
        (scores['supervised'] - scores['untrained'])[bootstrap].mean(axis=1), [0.025, 0.975]
    ).tolist()
    (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(summary, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('output')
    p.add_argument('--scenarios', type=int, default=128)
    p.add_argument('--workers', type=int, default=16)
    a = p.parse_args()
    run(a.config, a.checkpoint, a.output, a.scenarios, a.workers)
