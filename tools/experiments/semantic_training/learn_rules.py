"""Fresh semantic-rule learning diagnostic on the configured training host."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import socket
import time

import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.rule_lessons import build, specifications
from tools.experiments.semantic_training.player_loader import FORMAT
from tools.runs._host import load_remote_from_cfg
from tools.runs._train.setup import phase_a_setup
from tools.runs._train.snapshot import phase_b_write_cfg_metadata
from tools.runs.helpers import write_metadata_atomic
from tools.runs import schema
from training.core.artifact_io import save_checkpoint
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig


def logits_for(agent, rows):
    batch = batch_observations([r['obs'] for r in rows], agent.cfg, agent.device)
    allowed = torch.zeros_like(batch['legal_mask'])
    for i, row in enumerate(rows):
        if not row['tied'] or not set(row['tied']) <= set(row['candidates']):
            raise ValueError('invalid rule lesson labels')
        allowed[i, row['candidates']] = True
    if (allowed & ~batch['legal_mask']).any():
        raise ValueError('lesson candidate is not legal')
    return agent.net(batch).masked_fill(~allowed, -1e9)


def assess(agent, rows):
    groups = defaultdict(lambda: {'correct': 0, 'cases': 0})
    with torch.no_grad():
        for start in range(0, len(rows), 16):
            part = rows[start : start + 16]
            logits = logits_for(agent, part)
            if not torch.isfinite(logits).all():
                raise ValueError('nonfinite diagnostic scores')
            for row, chosen in zip(part, logits.argmax(-1).tolist()):
                group = groups[row['split'] + '/' + row['mode']]
                group['correct'] += chosen in row['tied']
                group['cases'] += 1
    return dict(groups)


def run(config, output, steps=1000, seed=93800):
    remote = load_remote_from_cfg(Path(config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('run rule training on the configured remote host')
    if steps < 1:
        raise ValueError('positive update budget required')
    control = Path(output)
    control.mkdir(parents=True, exist_ok=False)
    state = phase_a_setup(argparse.Namespace(cfg=config, override=['meta.run_label=semantic_rules']))
    phase_b_write_cfg_metadata(state, Path(config))
    root = state.artifacts_dir
    (root / 'ckpts').mkdir()
    tick = time.monotonic()
    status = dict(
        status='building_lessons',
        run=str(root),
        seed=seed,
        steps=steps,
        scope='synthetic rule-learning diagnostic, not native strength acceptance',
        train_pairs=specifications()[0],
        heldout_pairs=specifications()[1],
    )

    def save():
        status['wall_s'] = time.monotonic() - tick
        temp = control / 'result.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(control / 'result.json')

    save()
    try:
        torch.set_num_threads(1)
        torch.manual_seed(seed)
        cfg = load_cfg(config)
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        observer = SemanticAgent(shape)
        rows = build(cfg, observer, seed)
        manifest = [{k: v for k, v in row.items() if k != 'obs'} for row in rows]
        (root / 'lessons.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        # Reset initialization after data construction so no collection RNG affects weights.
        torch.manual_seed(seed)
        agent = SemanticAgent(shape, 'cuda')
        optimizer = torch.optim.AdamW([p for p in agent.net.parameters() if p.requires_grad], lr=0.0003, weight_decay=0)
        train = [r for r in rows if r['split'] == 'train']
        rng = random.Random(seed + 1)
        status.update(status='training', rows=len(rows), initial=assess(agent, rows))
        save()
        for step in range(1, steps + 1):
            selected = rng.choices(train, k=16)
            logp = logits_for(agent, selected).log_softmax(-1)
            loss = torch.stack([-logp[i, r['tied']].mean() for i, r in enumerate(selected)]).mean()
            if not torch.isfinite(loss):
                raise ValueError('nonfinite lesson loss')
            optimizer.zero_grad()
            loss.backward()
            norm = torch.nn.utils.clip_grad_norm_(agent.net.parameters(), 5)
            if not torch.isfinite(norm):
                raise ValueError('nonfinite lesson gradient')
            optimizer.step()
            if step % 100 == 0 or step == steps:
                status.update(step=step, loss=float(loss.detach()))
                save()
                print({k: status[k] for k in ('step', 'loss', 'wall_s')}, flush=True)
        frozen = root / 'ckpts' / f'step_{steps}.pt'
        save_checkpoint(
            dict(
                format=FORMAT,
                net=agent.net.state_dict(),
                shape=vars(shape),
                algorithm='synthetic engine-oracle rule pretraining',
                seed=seed,
                step=steps,
                optimizer=optimizer.state_dict(),
                lesson_manifest=manifest,
            ),
            frozen,
        )
        status.update(status='evaluating', checkpoint=str(frozen))
        save()  # Fixed final weights before withheld-value/syntax evaluation.
        status.update(status='complete', final=assess(agent, rows))
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save()
        meta = schema.load_file(root / 'metadata.toml')
        meta.status = 'done' if status['status'] == 'complete' else 'failed'
        meta.exit_code = 0 if meta.status == 'done' else 1
        meta.wall_seconds = time.monotonic() - tick
        meta.notes = status['scope']
        write_metadata_atomic(root, meta)
    print(status, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('output')
    p.add_argument('--steps', type=int, default=1000)
    p.add_argument('--seed', type=int, default=93800)
    a = p.parse_args()
    run(a.config, a.output, a.steps, a.seed)
