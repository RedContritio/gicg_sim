"""Native full-game preparation on the training host; no strength claims."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import socket

import torch

from tools.experiments.semantic_training.agent import SemanticAgent, batch_observations
from tools.experiments.semantic_training.decision_budget import DecisionBudget
from tools.experiments.semantic_training.teams import eval_cases, with_teams
from training.core.artifact_io import provenance
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.network import AgentConfig
from training.paradigms.dmc.config import DMCParadigmConfig
from tools.runs._host import load_remote_from_cfg


def game(job):
    config, case, depth, priority_cards = job
    torch.set_num_threads(1)
    torch.manual_seed(case.env_seed)
    cfg = with_teams(load_cfg(config), case.team_0, case.team_1)
    env = make_env_factory(cfg, None, case.env_seed)(0)
    used, legal, seen = Counter(), set(), set()
    budget = DecisionBudget(cfg.paradigm['max_game_steps'])
    try:
        env.reset(seed=case.env_seed, deck_seeds=(case.deck_seed_p0, case.deck_seed_p1))
        shape = AgentConfig.from_obs_shape(DMCParadigmConfig.from_dict(cfg.paradigm).agent)
        agent = SemanticAgent(shape)
        agent.game_start(env.static_obs)
        players = [GreedyPlayer('F1', depth, seed=case.env_seed + side) for side in (0, 1)]
        names = env._engine.get_card_names()
        for side in (0, 1):
            deck = Counter(names[r] for r in list(env._engine.hand_refs(side)) + list(env._engine.deck_refs(side)))
            if sum(deck.values()) != 30 or max(deck.values()) > 2:
                raise ValueError('invalid native deck')
        backward_checked = False
        for _ in budget.iterate(env):
            for side in (0, 1):
                seen.update(names[r] for r in env._engine.hand_refs(side))
            labels = env.get_action_labels()
            legal.update(name for kind, name, _ in labels if kind == 'Card')
            obs = agent.observation(env)
            n = obs['n_legal']
            if n > shape.max_actions:
                raise ValueError('legal action count exceeds model capacity')
            with torch.no_grad():
                scores = agent.logits(env)
                if not torch.isfinite(scores[:n]).all():
                    raise ValueError('nonfinite native model scores')
            if not backward_checked and n > 1:
                batch = batch_observations([obs], shape, 'cpu')
                q = agent.net(batch)
                q[0, :n].square().mean().backward()
                if not all(torch.isfinite(p.grad).all() for p in agent.net.parameters() if p.grad is not None):
                    raise ValueError('nonfinite native gradients')
                agent.net.zero_grad(set_to_none=True)
                backward_checked = True
            forced = [
                (priority_cards.index(name), i)
                for i, (kind, name, _) in enumerate(labels)
                if kind == 'Card' and name in priority_cards
            ]
            action = min(forced)[1] if forced else players[env.acting_player].select_action(env)
            if labels[action][0] == 'Card':
                used[labels[action][1]] += 1
            env.step(action)
        if not env.done or env.winner not in (0, 1, 2):
            raise RuntimeError('native preflight did not reach a terminal state')
        if not backward_checked:
            raise RuntimeError('no trainable decision observed')
        return dict(
            case=case.scenario_id,
            team_0=case.team_0,
            team_1=case.team_1,
            winner=env.winner,
            actions=budget.actions,
            decisions=budget.decisions,
            internal=budget.internal,
            seen=sorted(seen),
            legal=sorted(legal),
            used=dict(used),
        )
    except Exception as exc:
        raise RuntimeError(f'native case {case.scenario_id}: {exc}') from exc
    finally:
        env.close()


def run(config, output, scenarios=55, workers=8, seed=92001, depth=1, priority_cards=None):
    remote = load_remote_from_cfg(Path(config))
    if remote is None or socket.gethostname().lower() != remote.hostname.lower():
        raise ValueError('run native full-game preflight on the configured training host')
    cfg = load_cfg(config)
    priority_cards = priority_cards or []
    if depth not in (1, 2) or set(priority_cards) - set(cfg.scenario.card_pool):
        raise ValueError('depth must be 1/2 and priority cards must belong to the configured pool')
    cases = eval_cases(cfg, seed, scenarios)
    if workers < 1 or cfg.scenario.pool != 'native_latest' or cfg.scenario.random_deck_size != 30:
        raise ValueError('native random-30 configuration and positive worker count required')
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    status = dict(
        status='running',
        config=config,
        seed=seed,
        scenarios=scenarios,
        depth=depth,
        priority_cards=priority_cards,
        provenance=provenance(),
        games=[],
    )

    def save():
        temp = root / 'result.tmp'
        temp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(root / 'result.json')

    save()
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(game, [(config, case, depth, priority_cards) for case in cases]):
                status['games'].append(result)
                save()
                print(f'completed {len(status["games"])}/{scenarios}', flush=True)
        status['status'] = 'complete'
    except Exception as exc:
        status.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('output')
    parser.add_argument('--scenarios', type=int, default=55)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--seed', type=int, default=92001)
    parser.add_argument('--depth', type=int, choices=(1, 2), default=1)
    parser.add_argument('--priority-cards', nargs='*', default=[])
    args = parser.parse_args()
    run(**vars(args))
