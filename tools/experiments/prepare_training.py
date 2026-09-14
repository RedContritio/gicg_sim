"""No-learning environment gate: exact configs, seeded games, clone/restore, NN inference.

python -m tools.experiments.prepare_training --output /tmp/gicg-readiness.json
On failure a sibling .failure.json stores the config, seeds and exact action prefix.
"""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from gicg_env.engine import ACTION_CARD, ACTION_SKILL, get_lib_path
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.matchup.outcome import terminal_outcome
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.config import DMCParadigmConfig
from tools.experiments.environment_checks import check_privacy, decision, inference, transition

DEFAULT_CONFIGS = ['configs/dmc/readiness_base.toml', 'configs/dmc/readiness_tactics.toml']


def run_episode(cfg, agent, seed, trace):
    env = make_env_factory(cfg, None, seed)(0)
    chooser = np.random.default_rng(seed + 700000)
    counts, cards = Counter(), Counter()
    pending, multi_pending, max_legal, steps = 0, 0, 0, 0
    try:
        env.log_suspend()  # exact decision prefix is recorded separately
        agent.game_start(env.static_obs)
        for step in range(cfg.paradigm['max_game_steps']):
            kinds, refs, payments = decision(env, agent.cfg.max_actions)
            if env.done:
                break
            max_legal = max(max_legal, len(kinds))
            if env._engine.has_pending:
                pending += 1
                multi_pending += int(len(kinds) > 1)
            if step % 8 == 0:
                check_privacy(env)
                inference(agent, env, refs, payments)
            # Exercise action kinds instead of mostly sampling redundant dice
            # payments. This is an environment test policy, not training data.
            if trace['policy'] == 'aggressive' and ACTION_SKILL in kinds:
                kind = ACTION_SKILL
            else:
                kind = int(chooser.choice(np.unique(kinds)))
            index = int(chooser.choice(np.flatnonzero(kinds == kind)))
            label = env.get_action_labels()[index]
            trace['inputs'].append({'index': index, 'kind': kind, 'label': label})
            counts[str(kind)] += 1
            if kind == ACTION_CARD:
                cards[label[1]] += 1
            transition(env, index, agent.cfg.max_actions)
            steps += 1
        if not env.done:
            raise AssertionError('step budget exhausted before terminal state')
        outcome = terminal_outcome(env.winner, 0)
        return dict(
            seed=seed,
            policy=trace['policy'],
            steps=steps,
            outcome=outcome,
            pending=pending,
            multi_choice_pending=multi_pending,
            max_legal=max_legal,
            action_kinds=dict(counts),
            cards=dict(cards),
        )
    finally:
        env.close()


def prepare(configs, seeds, output):
    if not configs or not seeds:
        raise ValueError('at least one config and seed required')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.manual_seed(100)
    report = {
        'status': 'running',
        'provenance': provenance(),
        'training_started': False,
        'engine_sha256': hashlib.sha256(Path(get_lib_path()).read_bytes()).hexdigest(),
        'configs': [],
    }
    # Invalidate a previous green report before doing work. A failed rerun must
    # never leave stale "passed" evidence at the requested output path.
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    for path in configs:
        cfg = load_cfg(path)
        if cfg.meta.paradigm != 'dmc' or 'enemy_dice' not in (cfg.scenario.obs_mask or []):
            raise ValueError('this gate requires DMC with enemy_dice masking')
        if cfg.scenario.char_pool or max(len(cfg.scenario.team_0), len(cfg.scenario.team_1)) > 2:
            raise ValueError(
                'readiness scope is fixed teams of at most two characters; larger rosters need separate review'
            )
        shape = DMCParadigmConfig.from_dict(cfg.paradigm).agent
        agent = DmcAgent(AgentConfig.from_obs_shape(shape), epsilon=0)
        agent.net.eval()
        weights = {k: v.detach().clone() for k, v in agent.net.state_dict().items()}
        row = {
            'path': str(path),
            'resolved_config': asdict(cfg),
            'parameters': sum(p.numel() for p in agent.net.parameters()),
            'episodes': [],
        }
        for seed, policy in [(s, p) for s in seeds for p in ('balanced', 'aggressive')]:
            trace = {
                'config': str(path),
                'resolved_config': asdict(cfg),
                'seed': seed,
                'policy': policy,
                'provenance': report['provenance'],
                'engine_sha256': report['engine_sha256'],
                'inputs': [],
            }
            try:
                row['episodes'].append(run_episode(cfg, agent, seed, trace))
            except Exception as exc:
                trace['error'] = repr(exc)
                output.with_suffix('.failure.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2))
                report.update(status='failed', failure=str(output.with_suffix('.failure.json')))
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
                raise
        for key, tensor in agent.net.state_dict().items():
            if not torch.equal(weights[key], tensor):
                raise AssertionError('preparation must not update network weights')
        report['configs'].append(row)
    report['status'] = 'passed'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configs', nargs='+', default=DEFAULT_CONFIGS)
    parser.add_argument('--seeds', type=int, nargs='+', default=[41, 42, 43, 44, 45, 46, 47, 48])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.configs, args.seeds, args.output)
    for row in report['configs']:
        episodes = row['episodes']
        print(row['path'], 'passed', len(episodes), 'games;', sum(e['steps'] for e in episodes), 'inputs')
    print(args.output)


if __name__ == '__main__':
    main()
