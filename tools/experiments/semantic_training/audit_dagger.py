"""Measure DAgger fit and policy drift on a fixed sample of existing training states."""

import argparse
import json
from pathlib import Path
import random

import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from training.core.artifact_io import load_checkpoint, validate
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def audit(config, root, output, samples=256):
    root = Path(root)
    completion = json.loads((root / 'completion.json').read_text())
    if completion['status'] != 'complete':
        raise ValueError('audit requires completed training')
    torch.set_num_threads(1)
    cfg = load_cfg(config)
    shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
    checkpoints = [x['checkpoint'] for x in completion['candidates']]
    report = {'scope': 'training-state fit and drift; not heldout rule generalization', 'panels': []}
    for index in range(1, completion['rounds'] + 1):
        result = json.loads((root / f'round_{index}/result.json').read_text())
        directory = Path(result['run']) / 'teacher'
        validate(json.loads((directory / 'provenance.json').read_text()))
        rng = random.Random(94310 + index)
        files = sorted(directory.glob('episode_*.pt'))
        rng.shuffle(files)
        # Uniform reservoir over all decision rows; each state's inclusion is independent of episode length.
        rows, seen = [], 0
        for path in files:
            for row in torch.load(path, map_location='cpu', weights_only=False)['rows']:
                seen += 1
                if len(rows) < samples:
                    rows.append(row)
                else:
                    j = rng.randrange(seen)
                    if j < samples:
                        rows[j] = row
        if not rows:
            raise ValueError('empty training dataset')
        panel = dict(round=index, population=seen, sample=len(rows), models=[])
        reference = []
        for model_index, checkpoint in enumerate(checkpoints):
            agent = SemanticAgent(shape, device='cuda')
            agent.net.load_state_dict(load_checkpoint(checkpoint, map_location='cpu', weights_only=False)['net'])
            totals = dict(agreement=0.0, tied_mass=0.0, uniform_ce=0.0, entropy=0.0, kl_from_initial=0.0, changed=0.0)
            with torch.no_grad():
                for start in range(0, len(rows), 16):
                    selected = rows[start : start + 16]
                    batch = batch_observations([r['obs'] for r in selected], shape, 'cuda')
                    logits = agent.net(batch).masked_fill(~batch['legal_mask'], -1e9)
                    logp = logits.log_softmax(-1)
                    for i, row in enumerate(selected):
                        n = int(batch['legal_mask'][i].sum())
                        lp = logp[i, :n].cpu()
                        p = lp.exp()
                        chosen = int((logits[i, :n] * 1e5).round().argmax())
                        if model_index == 0:
                            reference.append((lp, chosen))
                        old, old_choice = reference[start + i]
                        totals['agreement'] += chosen in row['tied']
                        totals['tied_mass'] += float(p[row['tied']].sum())
                        totals['uniform_ce'] += float(-lp[row['tied']].mean())
                        totals['entropy'] += float(-(p * lp).sum())
                        totals['kl_from_initial'] += float((old.exp() * (old - lp)).sum())
                        totals['changed'] += chosen != old_choice
            panel['models'].append(dict(checkpoint=checkpoint, **{k: v / len(rows) for k, v in totals.items()}))
            del agent
        panel['multi_tie_fraction'] = sum(len(r['tied']) > 1 for r in rows) / len(rows)
        panel['mean_ties'] = sum(len(r['tied']) for r in rows) / len(rows)
        report['panels'].append(panel)
    Path(output).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('root')
    p.add_argument('output')
    p.add_argument('--samples', type=int, default=256)
    a = p.parse_args()
    audit(a.config, a.root, a.output, a.samples)
