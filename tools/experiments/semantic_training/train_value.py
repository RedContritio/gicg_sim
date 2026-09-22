"""Train a fresh state-value head on frozen RL rollout rows with heldout diagnostics.

The policy encoder stays frozen; only a re-initialized value head is optimized
against terminal outcomes (acting-player perspective, MSE).  Heldout episodes
(reporting R2/correlation/calibration for both the new head and the rollout's
recorded ``old_value`` predictions) guard against overfitting to game outcomes.

Episodes are streamed one file at a time through the frozen backbone: only a
single episode's obs (the bulk of rollout data) is resident in memory at once.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random

import torch

from tools.experiments.semantic_training.agent import batch_observations
from tools.experiments.semantic_training.player_loader import load_semantic_agent, load_semantic_payload
from tools.experiments.semantic_training.value_baseline import EXPECTED_SCORE, attach
from tools.experiments.semantic_training.value_diagnostics import diagnose
from training.core.artifact_io import save_checkpoint

REWARD_SET = (0.0, 0.5, 1.0, -1.0)
SIGNED_OUTCOME = 'signed_outcome'
WIN_PROBABILITY = 'win_probability'
REWARD_ENCODINGS = (SIGNED_OUTCOME, EXPECTED_SCORE, WIN_PROBABILITY)


def _to_target(reward: float, encoding: str) -> float:
    if encoding == SIGNED_OUTCOME:
        if reward not in (-1.0, 0.0, 1.0):
            raise ValueError(f'signed outcome must be -1/0/1, got {reward}')
        return (reward + 1.0) / 2.0
    if encoding in (EXPECTED_SCORE, WIN_PROBABILITY):
        if reward not in (0.0, 0.5, 1.0):
            raise ValueError(f'expected score must be 0/0.5/1, got {reward}')
        return reward
    raise ValueError(f'unknown reward encoding {encoding!r}')


HELDOUT_MODULUS = 5  # 1 in 5 episodes (by episode-number hash) is held out.


def _episode_files(rollout_dirs):
    files = []
    for directory in rollout_dirs:
        files.extend(sorted(Path(directory).rglob('episode_*.pt')))
    unique = sorted({str(path) for path in files})
    if not unique:
        raise ValueError(f'no episode_*.pt files found under {rollout_dirs}')
    return [Path(path) for path in unique]


def _episode_index(path):
    stem = path.stem
    if stem.startswith('episode_') and stem[8:].isdigit():
        return int(stem[8:])
    # Fallback for non-canonical names: hash the full path for stability.
    return int(hashlib.sha256(str(path).encode()).hexdigest(), 16) % (10**9)


def _load_episode(path):
    rows = torch.load(path, map_location='cpu', weights_only=False)
    if not isinstance(rows, list) or not rows:
        return []
    for row in rows:
        reward = float(row['reward'])
        assert reward in REWARD_SET, f'unexpected reward {reward} in {path}'
        encoding = row.get('reward_encoding')
        if encoding is not None and encoding not in REWARD_ENCODINGS:
            raise ValueError(f'unknown reward encoding {encoding!r} in {path}')
    return rows


def _resolve_reward_encoding(paths, requested):
    if requested != 'auto':
        return requested
    markers = set()
    unmarked_rewards = set()
    for path in paths:
        rows = _load_episode(path)
        for row in rows:
            marker = row.get('reward_encoding')
            if marker is None:
                unmarked_rewards.add(float(row['reward']))
            else:
                markers.add(marker)
    if len(markers) > 1:
        raise ValueError(f'mixed reward encodings are not supported: {sorted(markers)}')
    if markers:
        return markers.pop()
    if -1.0 in unmarked_rewards:
        return SIGNED_OUTCOME
    if 0.5 in unmarked_rewards:
        return EXPECTED_SCORE
    if 0.0 in unmarked_rewards:
        raise ValueError(
            'reward 0 is ambiguous without encoding metadata; pass --reward-encoding signed_outcome or expected_score'
        )
    return EXPECTED_SCORE


def plan_episodes(rollout_dirs, episodes, seed):
    """Sample episode files and tag each one as train or heldout by episode-number hash."""
    files = _episode_files(rollout_dirs)
    rng = random.Random(seed)
    plan = []
    for path in rng.sample(files, min(episodes, len(files))):
        tag = f'episode-{_episode_index(path)}'
        digest = int(hashlib.sha256(tag.encode()).hexdigest(), 16)
        plan.append((path, digest % HELDOUT_MODULUS == 0))
    return plan


def embed_episode(agent, path, device, reward_encoding, chunk=512):
    """Validate one episode and embed all its rows through the frozen backbone.

    Only this episode's obs are resident at any time; the returned CPU tensors
    (plus per-row ``old_value`` scalars) are small enough to cache for all
    episodes.  Returns ``None`` for empty episode files.
    """
    rows = _load_episode(path)
    if not rows:
        return None
    states, targets, old_values = [], [], []
    for start in range(0, len(rows), chunk):
        part = rows[start : start + chunk]
        batch = batch_observations([row['obs'] for row in part], agent.cfg, device)
        with torch.no_grad():
            _, state = agent.net(batch, return_state=True)
        states.append(state.cpu())
        targets.extend(_to_target(float(row['reward']), row.get('reward_encoding', reward_encoding)) for row in part)
        old_values.extend(None if row.get('old_value') is None else float(row['old_value']) for row in part)
    states = torch.cat(states)
    if not torch.isfinite(states).all():
        raise ValueError('nonfinite backbone state')
    return states, torch.tensor(targets, dtype=torch.float32), old_values


def train(agent, states, rewards, steps, batch_size, lr, seed, log_every=100):
    torch.manual_seed(seed)
    rng = random.Random(seed)
    optimizer = torch.optim.AdamW(agent.value_head.parameters(), lr=lr, weight_decay=0.0)
    history = []
    total = states.shape[0]
    for step in range(1, steps + 1):
        picks = [rng.randrange(total) for _ in range(batch_size)]
        target = rewards[picks]
        prediction = agent.value_head(states[picks])
        loss = torch.nn.functional.mse_loss(prediction, target)
        if not torch.isfinite(loss):
            raise ValueError('nonfinite value-head loss')
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        if step % log_every == 0 or step == steps:
            history.append({'step': step, 'loss': float(loss.detach())})
    return history


def _concat_parts(parts, index, device):
    return torch.cat([part[index] for part in parts]).to(device)


def run(
    config,
    checkpoint,
    rollout_dirs,
    output,
    episodes=512,
    steps=1500,
    batch_size=256,
    lr=1e-3,
    seed=96400,
    device='cuda',
    threads=8,
    reward_encoding='auto',
    allow_unverified_checkpoint=False,
):
    # train_value is a single process (unlike the 16-worker RL collectors), so
    # multi-threaded CPU forwards are safe and ~threads× faster on big embeds.
    torch.set_num_threads(max(1, threads))
    plan = plan_episodes(rollout_dirs, episodes, seed)
    resolved_reward_encoding = _resolve_reward_encoding([path for path, _heldout in plan], reward_encoding)
    verify = not allow_unverified_checkpoint
    agent = load_semantic_agent(checkpoint, device=device, verify_provenance=verify)
    agent.net.requires_grad_(False)
    attach(agent)  # fresh value head; optimizer only sees head parameters.
    # Stream one episode at a time: obs are released after each embed, so peak
    # memory is ~one episode of obs plus the compact per-episode state cache.
    train_parts, heldout_parts = [], []
    n_heldout = 0
    for path, heldout in plan:
        embedded = embed_episode(agent, path, device, resolved_reward_encoding)
        if embedded is None:
            continue
        (heldout_parts if heldout else train_parts).append(embedded)
        if heldout:
            n_heldout += 1
    if not train_parts or not heldout_parts:
        raise ValueError(
            'need rows in both splits; got '
            f'{sum(part[0].shape[0] for part in train_parts)} train rows and '
            f'{sum(part[0].shape[0] for part in heldout_parts)} heldout rows'
        )
    states = _concat_parts(train_parts, 0, device)
    targets = _concat_parts(train_parts, 1, device)
    history = train(agent, states, targets, steps, batch_size, lr, seed)
    heldout_states = _concat_parts(heldout_parts, 0, device)
    heldout_targets = _concat_parts(heldout_parts, 1, device)
    heldout_old = [old for part in heldout_parts for old in part[2]]
    heldout = diagnose(agent, heldout_states, heldout_targets, heldout_old, device)
    head_state = {key: value.cpu() for key, value in agent.value_head.state_dict().items()}
    payload = dict(load_semantic_payload(checkpoint, verify_provenance=verify))
    payload['value_head'] = head_state
    payload['value_encoding'] = EXPECTED_SCORE
    payload['value_perspective'] = 'acting_player'
    payload['return_definition'] = 'terminal_expected_score'

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report = {
        'scope': 'frozen-backbone value-head fit on RL rollout terminal outcomes; heldout by episode hash',
        'config': config,
        'checkpoint': checkpoint,
        'value_encoding': EXPECTED_SCORE,
        'value_perspective': 'acting_player',
        'return_definition': 'terminal_expected_score',
        'checkpoint_sha256': hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
        'rollout_dirs': [str(directory) for directory in rollout_dirs],
        'episodes_requested': episodes,
        'episodes_used': len(plan),
        'heldout_episodes': n_heldout,
        'train_rows': int(states.shape[0]),
        'heldout_rows': int(heldout_states.shape[0]),
        'settings': {
            'steps': steps,
            'batch_size': batch_size,
            'lr': lr,
            'seed': seed,
            'device': device,
            'reward_encoding': resolved_reward_encoding,
            'heldout_fraction': 1.0 / HELDOUT_MODULUS,
        },
        'train_loss_history': history,
        'heldout': heldout,
    }
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    torch.save(head_state, output / 'value_head.pt')
    save_checkpoint(payload, output / 'agent_with_value.pt')
    print(json.dumps({'report': str(output / 'report.json'), 'heldout': heldout}), flush=True)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('config')
    p.add_argument('checkpoint')
    p.add_argument('rollout_dirs', nargs='+')
    p.add_argument('output')
    p.add_argument('--episodes', type=int, default=512)
    p.add_argument('--steps', type=int, default=1500)
    p.add_argument('--batch-size', type=int, default=256)
    p.add_argument('--lr', type=float, default=1e-3)
    p.add_argument('--seed', type=int, default=96400)
    p.add_argument('--device', default='cuda', choices=['cuda', 'cpu'])
    p.add_argument('--threads', type=int, default=8)
    p.add_argument('--reward-encoding', choices=('auto', *REWARD_ENCODINGS), default='auto')
    p.add_argument('--allow-unverified-checkpoint', action='store_true')
    a = p.parse_args()
    run(
        a.config,
        a.checkpoint,
        a.rollout_dirs,
        a.output,
        episodes=a.episodes,
        steps=a.steps,
        batch_size=a.batch_size,
        lr=a.lr,
        seed=a.seed,
        device=a.device,
        threads=a.threads,
        reward_encoding=a.reward_encoding,
        allow_unverified_checkpoint=a.allow_unverified_checkpoint,
    )


if __name__ == '__main__':
    main()
