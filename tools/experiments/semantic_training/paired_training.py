"""Frozen-source, matched-budget consequence regression with/without paired differences."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import socket
import time

import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.paired_lessons import build_pair, tasks
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.rule_outcomes import FIELDS
from tools.runs._host import load_remote_from_cfg
from training.core.artifact_io import fingerprint, load_checkpoint, save_checkpoint
from training.core.network import AgentConfig


def predict(agent, pairs):
    rows = [row for pair in pairs for row in pair['rows']]
    batch = batch_observations([row['obs'] for row in rows], agent.cfg, agent.device)
    adapter = getattr(agent, 'rule_adapter', None)
    if adapter is None:
        _, state, actions = agent.net(batch, return_actions=True)
    else:
        with torch.no_grad():
            _, state, actions = agent.net(batch, return_actions=True)
        state, actions = adapter(state, actions)
    raw = agent.rule_head(state, actions)
    pred = raw[torch.arange(len(rows), device=agent.device), [r['action'] for r in rows]]
    truth = pred.new_tensor([r['target'] for r in rows])
    scale = pred.new_tensor([10, 10, 3, 3, 1, 1, 1, 1, 1])
    return pred.reshape(-1, 2, len(FIELDS)), (truth / scale).reshape(-1, 2, len(FIELDS))


def objective(pred, truth, pairs, beta):
    field = torch.tensor([p['field'] for p in pairs], device=pred.device)
    selected = field[:, None, None].expand(-1, 2, 1)
    p, y = pred.gather(2, selected).squeeze(-1), truth.gather(2, selected).squeeze(-1)
    absolute = (p - y).square().mean()
    difference = ((p[:, 1] - p[:, 0]) - (y[:, 1] - y[:, 0])).square().mean()
    return absolute + beta * difference + 0.1 * (pred - truth).square().mean()


def assess(agent, pairs):
    groups = {}
    agent.net.eval()
    with torch.no_grad():
        for start in range(0, len(pairs), 8):
            part = pairs[start : start + 8]
            pred, truth = predict(agent, part)
            for i, pair in enumerate(part):
                f = pair['field']
                p, y = pred[i, :, f] * 10, truth[i, :, f] * 10
                pd, yd = float(p[1] - p[0]), float(y[1] - y[0])
                record = dict(
                    mae=float((p - y).abs().mean()),
                    delta_mae=abs(pd - yd),
                    changed=abs(yd) > 1e-5,
                    correct=pd * yd > 0,
                    within_half=abs(pd - yd) <= 0.5,
                    zero_delta_mae=abs(yd),
                )
                for key in (pair['split'], pair['split'] + '/' + pair['parameter']):
                    groups.setdefault(key, []).append(record)
    return {
        key: dict(
            pairs=len(rows),
            changed=sum(r['changed'] for r in rows),
            mae=sum(r['mae'] for r in rows) / len(rows),
            delta_mae=sum(r['delta_mae'] for r in rows) / len(rows),
            zero_delta_mae=sum(r['zero_delta_mae'] for r in rows) / len(rows),
            delta_within_half=sum(r['within_half'] for r in rows) / len(rows),
            changed_delta_mae=(sum(r['delta_mae'] for r in rows if r['changed']) / sum(r['changed'] for r in rows))
            if any(r['changed'] for r in rows)
            else None,
            changed_direction_accuracy=(
                sum(r['correct'] for r in rows if r['changed']) / sum(r['changed'] for r in rows)
            )
            if any(r['changed'] for r in rows)
            else None,
        )
        for key, rows in groups.items()
    }


def run(args):
    remote = load_remote_from_cfg(Path(args.config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('heavy experiment must run on configured training host')
    if min(args.steps, args.contexts, args.workers) < 1:
        raise ValueError('budgets must be positive')
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    status = dict(
        status='running',
        stage='building',
        seed=args.seed,
        steps=args.steps,
        config=args.config,
        config_sha256=hashlib.sha256(Path(args.config).read_bytes()).hexdigest(),
        catalog=args.catalog,
        catalog_sha256=hashlib.sha256(Path(args.catalog).read_bytes()).hexdigest(),
        contexts=args.contexts,
        workers=args.workers,
        source_sha256=fingerprint(),
        checkpoint=args.checkpoint,
        scope='consequence diagnostic, not RL strength',
        checkpoint_sha256=hashlib.sha256(Path(args.checkpoint).read_bytes()).hexdigest(),
        arms={},
    )
    status['tool_sha256'] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob('*.py'))
    }

    def save(complete=False):
        status['wall_s'] = time.monotonic() - tick
        temp = root / 'status.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(root / ('completion.json' if complete else 'status.json'))

    save()
    try:
        torch.set_num_threads(1)
        payload = load_checkpoint(args.checkpoint, map_location='cpu', weights_only=False)
        jobs = tasks(args.config, args.catalog, payload['shape'], args.seed, args.contexts)
        status['pairs_total'] = len(jobs)
        pairs = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for pair in pool.map(build_pair, jobs, chunksize=1):
                pairs.append(pair)
                status['pairs_done'] = len(pairs)
                if len(pairs) % 10 == 0:
                    save()
        torch.save(pairs, root / 'pairs.pt')
        manifest = [
            {
                **{k: v for k, v in p.items() if k != 'rows'},
                'rows': [{k: v for k, v in r.items() if k != 'obs'} for r in p['rows']],
            }
            for p in pairs
        ]
        (root / 'pairs.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        train = [p for p in pairs if p['split'] == 'train']
        parameters = sorted({p['parameter'] for p in train})
        strata = {k: [p for p in train if p['parameter'] == k] for k in parameters}
        for arm, beta in (('paired', 1.0), ('absolute', 0.0)):
            torch.manual_seed(args.seed)
            agent = SemanticAgent(AgentConfig(**payload['shape']), 'cuda')
            agent.net.load_state_dict(payload['net'])
            attach(agent)
            if 'rule_head' in payload:
                agent.rule_head.load_state_dict(payload['rule_head'])
            params = [p for m in (agent.net, agent.rule_head) for p in m.parameters() if p.requires_grad]
            optimizer = torch.optim.AdamW(params, lr=0.0003, weight_decay=0)
            rng = random.Random(args.seed)
            status.update(stage='training', arm=arm, step=0)
            status['arms'][arm] = dict(initial=assess(agent, pairs), beta=beta)
            save()
            started = time.monotonic()
            for step in range(1, args.steps + 1):
                selected = [rng.choice(strata[rng.choice(parameters)]) for _ in range(8)]
                pred, truth = predict(agent, selected)
                loss = objective(pred, truth, selected, beta)
                if not torch.isfinite(loss):
                    raise ValueError('nonfinite paired objective')
                optimizer.zero_grad()
                loss.backward()
                norm = torch.nn.utils.clip_grad_norm_(params, 5)
                if not torch.isfinite(norm):
                    raise ValueError('nonfinite paired gradient')
                optimizer.step()
                if step % 100 == 0 or step == args.steps:
                    rate = step / (time.monotonic() - started)
                    status.update(step=step, loss=float(loss.detach()), steps_per_s=rate)
                    save()
                    print(f'{arm} {step}/{args.steps} loss={float(loss.detach()):.6f} rate={rate:.2f}/s', flush=True)
            ckpt = root / f'{arm}.pt'
            save_checkpoint(
                dict(
                    format='paired-consequence/1.0.0',
                    net=agent.net.state_dict(),
                    rule_head=agent.rule_head.state_dict(),
                    shape=payload['shape'],
                    optimizer=optimizer.state_dict(),
                    seed=args.seed,
                    steps=args.steps,
                    beta=beta,
                    parent_format=payload.get('format'),
                ),
                ckpt,
            )
            status['arms'][arm].update(final=assess(agent, pairs), checkpoint=str(ckpt))
            save()
            del agent, optimizer, params, pred, truth, loss
            torch.cuda.empty_cache()
        status.update(status='complete', stage='complete')
    except BaseException as error:
        status.update(status='failed', error=repr(error))
        raise
    finally:
        save(complete=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('checkpoint')
    parser.add_argument('output')
    parser.add_argument('--catalog', default='configs/rule_validation/native_variants.toml')
    parser.add_argument('--steps', type=int, default=1500)
    parser.add_argument('--contexts', type=int, default=6)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=95000)
    run(parser.parse_args())
