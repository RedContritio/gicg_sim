"""Smoke path for paired-consequence RL."""

from concurrent.futures import ProcessPoolExecutor
import random

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.evaluate import initialize
from tools.experiments.semantic_training.paired_replay import PairedReplay
from tools.experiments.semantic_training.rl_rollout import episode
from tools.experiments.semantic_training.rl_update import update
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.value_baseline import attach as attach_value
from training.core.network import AgentConfig


def smoke(args, root, initial, payload, pairs):
    directory = root / 'rollouts'
    directory.mkdir()
    with ProcessPoolExecutor(max_workers=4, initializer=initialize, initargs=(args.config, str(initial), 2)) as pool:
        records = list(pool.map(episode, [(1, i, str(directory), args.seed, args.catalog, 0) for i in range(4)]))
    rows = [row for record in records for row in torch.load(record['path'], weights_only=False)]
    results = {}
    for arm, beta in (('auxiliary', 0.5), ('control', 0.0)):
        torch.manual_seed(args.seed)
        shape = AgentConfig(**payload['shape'])
        agent, anchor = SemanticAgent(shape, 'cuda'), SemanticAgent(shape, 'cuda')
        for model in (agent, anchor):
            model.net.load_state_dict(payload['net'])
        anchor.net.requires_grad_(False)
        optimizer = torch.optim.AdamW(agent.net.parameters(), lr=1e-5, weight_decay=0)
        value_optimizer = torch.optim.AdamW(attach_value(agent).parameters(), lr=0.0003)
        rule_optimizer = torch.optim.AdamW(attach(agent).parameters(), lr=0.0003) if beta else None
        if beta:
            agent.rule_head.load_state_dict(payload['rule_head'])
        replay = PairedReplay(pairs, args.seed + 3)
        results[arm] = update(
            agent,
            anchor,
            optimizer,
            rows[:64],
            [0, 0],
            random.Random(args.seed + 2),
            epochs=1,
            value_optimizer=value_optimizer,
            temperature=0.5,
            rule_optimizer=rule_optimizer,
            rule_beta=beta,
            auxiliary_loss=replay,
        )
        if results[arm]['updates'] < 1:
            raise ValueError('smoke performed no optimizer update')
        results[arm]['replay_calls'] = replay.calls
    return dict(scope='four real games and both update paths; not strength evaluation', results=results)
