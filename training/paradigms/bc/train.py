"""Behavioral cloning training for AZ ActorCritic.

Loads a dataset produced by ``tools.gen_bc_dataset_az`` and trains
ActorCritic via:
  - policy: soft-target CE on ``tied_mask`` (uniform over teacher's tied
    set; matches PPO BC s016d soft-target which broke the F1-D2
    tiebreak ceiling)
  - value: MSE on ``terminal_z`` (teacher-side perspective)

Output: ``artifacts/<ts>_<run_label>/`` with
  - ``final.pt``  ActorCritic state_dict (consumed by AZ
    ``init_from_ckpt`` field)
  - ``metrics.jsonl``  per-epoch loss + held-out match rate
  - ``summary.json``   final hyper + match rate

Usage:
    .venv/bin/python -m training.paradigms.bc.train configs/<bc_pretrain.toml>
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from training.core.cfg import ObsShape
from training.paradigms.bc.dataset import BCDataset
from training.paradigms.bc._train_loss import forward_batch, hard_match_rate, soft_match_rate, soft_target_ce_loss
from training.core.network import make_actor_critic


def _train_one_epoch(net, ds, train_idx, batch_size, value_coef, opt, device, rng) -> tuple[float, float, float, int]:
    """Returns (avg_loss, avg_pol, avg_val, n_batches)."""
    net.train()
    ep_perm = rng.permutation(len(train_idx))
    n_batches = max(1, len(train_idx) // batch_size)
    ep_loss = ep_pol = ep_val = 0.0
    batch_t0 = time.perf_counter()
    for b in range(n_batches):
        slc = ep_perm[b * batch_size : (b + 1) * batch_size]
        indices = train_idx[slc]
        batch = ds.build_batch(indices)

        logits, value = forward_batch(net, batch, device)
        tied_t = torch.as_tensor(batch['tied_mask'], dtype=torch.bool, device=device)
        legal_t = torch.as_tensor(batch['legal_mask'], dtype=torch.bool, device=device)
        z_t = torch.as_tensor(batch['terminal_z'], dtype=torch.float32, device=device)

        pol_loss = soft_target_ce_loss(logits, tied_t, legal_t)
        val_loss = nn.functional.mse_loss(value, z_t)
        loss = pol_loss + value_coef * val_loss

        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=1.0)
        opt.step()

        ep_loss += float(loss.item())
        ep_pol += float(pol_loss.item())
        ep_val += float(val_loss.item())

        # Progress every 50 batches so we can monitor long epochs.
        if (b + 1) % 50 == 0:
            dt = time.perf_counter() - batch_t0
            print(
                f'[batch {b + 1}/{n_batches}] avg_loss={ep_loss / (b + 1):.3f} '
                f'pol={ep_pol / (b + 1):.3f} val={ep_val / (b + 1):.3f} '
                f'rate={50 / max(dt, 1e-6):.1f} batch/s',
                flush=True,
            )
            batch_t0 = time.perf_counter()
    return ep_loss / n_batches, ep_pol / n_batches, ep_val / n_batches, n_batches


def _milestone_epochs(n_epochs: int) -> set[int]:
    # sqrt(n) evenly-spaced milestones (rounded). For n=10 → {0, 4, 9}.
    sqrt_n = max(1, round(math.sqrt(n_epochs)))
    if sqrt_n == 1:
        return {n_epochs - 1}
    return {round(i * (n_epochs - 1) / (sqrt_n - 1)) for i in range(sqrt_n)}


def _keep_epochs(epoch: int, milestones: set[int], rolling: int = 5) -> set[int]:
    # Milestones (permanent) ∪ last `rolling` epochs from current.
    return milestones | set(range(max(0, epoch - rolling + 1), epoch + 1))


def _eval_held_out(net, ds, eval_idx, device, chunk_size: int = 64) -> dict:
    # Chunk to match training memory profile — single 2048-sample build_batch
    # OOMs on 18 GB VM (HookEncoder reshape (2048*~38, 120, 128) is multi-GB).
    net.eval()
    indices = eval_idx[: min(2048, len(eval_idx))]
    n = len(indices)
    sum_hard = sum_soft = 0.0
    sum_val_mse = sum_val_mae = 0.0
    cnt = 0
    with torch.no_grad():
        for i in range(0, n, chunk_size):
            chunk = indices[i : i + chunk_size]
            batch = ds.build_batch(chunk)
            logits, value = forward_batch(net, batch, device)
            tied_t = torch.as_tensor(batch['tied_mask'], dtype=torch.bool, device=device)
            legal_t = torch.as_tensor(batch['legal_mask'], dtype=torch.bool, device=device)
            chosen_t = torch.as_tensor(batch['chosen_action'], dtype=torch.long, device=device)
            z_t = torch.as_tensor(batch['terminal_z'], dtype=torch.float32, device=device)

            sz = len(chunk)
            sum_hard += hard_match_rate(logits, chosen_t, legal_t) * sz
            sum_soft += soft_match_rate(logits, tied_t, legal_t) * sz
            sum_val_mse += float(nn.functional.mse_loss(value, z_t).item()) * sz
            sum_val_mae += float((value - z_t).abs().mean().item()) * sz
            cnt += sz
    return {
        'hard_match': sum_hard / cnt,
        'soft_match': sum_soft / cnt,
        'value_mse': sum_val_mse / cnt,
        'value_mae': sum_val_mae / cnt,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('config', help='TOML config path')
    args = parser.parse_args()

    with open(args.config, 'rb') as f:
        cfg = tomllib.load(f)

    run_label = cfg['run_label']
    ts = datetime.now().strftime('%Y%m%d%H%M')
    out_dir = Path('artifacts') / f'{ts}_{run_label}'
    out_dir.mkdir(parents=True, exist_ok=True)

    seed = int(cfg.get('seed', 0))
    torch.manual_seed(seed)
    np.random.seed(seed)
    device = torch.device(cfg.get('device', 'cpu'))

    n_counter_slots = int(cfg['n_counter_slots'])
    n_hooks = int(cfg['n_hooks'])
    max_ops_per_hook = int(cfg['max_ops_per_hook'])
    max_actions = int(cfg['max_actions'])
    d_model = int(cfg['d_model'])
    n_cross_layers = int(cfg.get('n_cross_layers', 2))
    dropout = float(cfg.get('dropout', 0.1))

    lr = float(cfg.get('lr', 1e-4))
    batch_size = int(cfg.get('batch_size', 256))
    n_epochs = int(cfg.get('n_epochs', 60))
    value_coef = float(cfg.get('value_coef', 0.5))
    held_out_frac = float(cfg.get('held_out_frac', 0.1))

    dataset_path = Path(cfg['dataset_path'])
    print(f'[bc_train] loading {dataset_path}')
    ds = BCDataset(dataset_path, n_counter_slots, n_hooks, max_ops_per_hook)
    print(f'[bc_train] dataset: {len(ds)} decisions, {len(ds._parsed_statics)} games')

    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(ds))
    n_eval = max(1, int(len(ds) * held_out_frac))
    eval_idx = perm[:n_eval]
    train_idx = perm[n_eval:]

    # BC keeps all 3 heads (policy + value + delta) so the same ckpt can
    # warm-start AZ/PPO/DMC per BC4.2 ckpt-share spec; typed_damage on for
    # AZ ADR-0019 ckpt compat。
    shape = ObsShape(
        n_counter_slots=n_counter_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_ops_per_hook,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=n_cross_layers,
        dropout=dropout,
    )
    net = make_actor_critic(
        shape,
        head_kinds={'policy', 'value', 'delta'},
        use_typed_damage=True,
    ).to(device)
    print(f'[bc_train] params: {sum(p.numel() for p in net.parameters()):,}')

    opt = optim.Adam(net.parameters(), lr=lr)

    metrics_path = out_dir / 'metrics.jsonl'
    summary_path = out_dir / 'summary.json'
    final_path = out_dir / 'final.pt'

    # Save format: {'cfg': ..., 'net': state_dict} — both eval_service AZ
    # loader and async_loop init_from_ckpt unwrap this. Plain state_dict
    # would fail with "missing 'cfg' or 'net' key".
    agent_cfg = {
        'n_counter_slots': n_counter_slots,
        'n_hooks': n_hooks,
        'max_ops_per_hook': max_ops_per_hook,
        'max_actions': max_actions,
        'd_model': d_model,
        'dropout': dropout,
        'n_cross_layers': n_cross_layers,
    }

    milestones = _milestone_epochs(n_epochs)
    print(f'[bc_train] ckpt strategy: milestones={sorted(milestones)} + rolling last 5')

    t_start = time.perf_counter()
    last_eval: dict = {}
    with open(metrics_path, 'w', encoding='utf-8') as fmetrics:
        for epoch in range(n_epochs):
            tr_loss, tr_pol, tr_val, _ = _train_one_epoch(
                net,
                ds,
                train_idx,
                batch_size,
                value_coef,
                opt,
                device,
                rng,
            )
            ev = _eval_held_out(net, ds, eval_idx, device)
            last_eval = ev
            elapsed = time.perf_counter() - t_start
            row = {
                'epoch': epoch,
                't': elapsed,
                'train_loss': tr_loss,
                'train_policy_loss': tr_pol,
                'train_value_loss': tr_val,
                'eval_hard_match': ev['hard_match'],
                'eval_soft_match': ev['soft_match'],
                'eval_value_mse': ev['value_mse'],
                'eval_value_mae': ev['value_mae'],
            }
            print(
                f'[ep={epoch:3d} t={elapsed:.0f}s] loss={tr_loss:.3f} '
                f'pol={tr_pol:.3f} val={tr_val:.3f} '
                f'soft_match={ev["soft_match"]:.3f} hard_match={ev["hard_match"]:.3f} val_mae={ev["value_mae"]:.3f}',
                flush=True,
            )
            fmetrics.write(json.dumps(row) + '\n')
            fmetrics.flush()

            # Per-epoch ckpt + prune.
            ckpt_path = out_dir / f'epoch_{epoch}.pt'
            torch.save({'cfg': agent_cfg, 'net': net.state_dict()}, ckpt_path)
            keep = _keep_epochs(epoch, milestones)
            for e in range(epoch + 1):
                if e in keep:
                    continue
                p = out_dir / f'epoch_{e}.pt'
                if p.exists():
                    p.unlink()

    torch.save({'cfg': agent_cfg, 'net': net.state_dict()}, final_path)
    summary = {
        'run_label': run_label,
        'dataset_path': str(dataset_path),
        'n_decisions': int(len(ds)),
        'n_games': int(len(ds._parsed_statics)),
        'final_soft_match': last_eval.get('soft_match', 0.0),
        'final_hard_match': last_eval.get('hard_match', 0.0),
        'final_value_mae': last_eval.get('value_mae', 0.0),
        'n_epochs': n_epochs,
        'lr': lr,
        'batch_size': batch_size,
        'd_model': d_model,
        'n_cross_layers': n_cross_layers,
        'duration_s': time.perf_counter() - t_start,
    }
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'[bc_train] DONE. final={final_path} summary={summary_path}')
    print(
        f'[bc_train] soft_match={last_eval.get("soft_match", 0.0):.3f} '
        f'hard_match={last_eval.get("hard_match", 0.0):.3f} '
        f'val_mae={last_eval.get("value_mae", 0.0):.3f}'
    )


if __name__ == '__main__':
    main()
