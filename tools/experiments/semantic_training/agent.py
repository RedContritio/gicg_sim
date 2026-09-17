"""Semantic graph agent and self-contained trainable observation batches."""

import numpy as np
import torch

from training.core.network import AgentBase
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc._episode import capture_obs, collate_batch
from training.paradigms.dmc.buffer import DmcTransition
from tools.experiments.semantic_training.network import SemanticQNet


def batch_observations(observations, cfg, device):
    ts = [DmcTransition(o, 0, 0) for o in observations]
    batch, _, _ = collate_batch(ts, device=device, max_actions=cfg.max_actions)
    for name, width in [('counter_links', 4), ('card_links', 2), ('skill_links', 2), ('card_hook_links', 2)]:
        n = max(1, max(len(o[name]) for o in observations))
        padded = np.full((len(observations), n, width), -1, dtype=np.int64)
        for i, o in enumerate(observations):
            padded[i, : len(o[name])] = np.asarray(o[name], dtype=np.int64).reshape(-1, width)
        batch[name] = padded
    batch['counter_owners'] = np.stack([o['counter_owners'] for o in observations])
    floats = {
        'counter_values',
        'card_buckets',
        'enemy_sizes',
        'meta',
        'recent_damage',
        'prepare_skill',
        'modifier_log',
        'action_payments',
        'buffs',
    }
    bools = {'active_slot_mask', 'hook_mask', 'legal_mask'}
    return {
        k: torch.as_tensor(
            v, device=device, dtype=torch.float32 if k in floats else torch.bool if k in bools else torch.long
        )
        for k, v in batch.items()
    }


class SemanticAgent(DmcAgent):
    def __init__(self, cfg, device='cpu', epsilon=0):
        import random

        net = SemanticQNet(cfg).to(device)
        AgentBase.__init__(self, cfg, net.hook_encoder, device)
        self.net = net
        self.epsilon = epsilon
        self.rng = random.Random(0)
        self.graph = None
        self.net.eval()

    def game_start(self, static_obs):
        super().game_start(static_obs)
        self.graph = None

    def observation(self, env):
        if self.graph is None:
            self.graph = env.get_rule_graph()
            if self.graph['version'] != 2:
                raise ValueError('unsupported rule graph')
        obs = capture_obs(env, self)
        for key in ('counter_owners', 'counter_links', 'card_links', 'skill_links', 'card_hook_links'):
            obs[key] = np.asarray(self.graph[key], dtype=np.int64)
        return obs

    def logits(self, env):
        obs = self.observation(env)
        batch = batch_observations([obs], self.cfg, self.device)
        batch['hook_emb'] = self._hook_emb
        with torch.no_grad():
            q = self.net(batch)[0, : len(obs['action_refs'])]
        if not torch.isfinite(q).all():
            raise ValueError('nonfinite semantic Q')
        return q

    def act_with_logit(self, env):
        q = self.logits(env)
        if self.rng.random() < self.epsilon:
            a = self.rng.randrange(len(q))
        else:
            scaled = (q * 1e5).round()
            best = scaled.max()
            candidates = torch.nonzero(scaled >= best - 1, as_tuple=False).flatten()
            if candidates.numel() == 1:
                a = int(candidates[0])
            else:
                identities = env.get_action_identities()
                payments = env.get_legal_action_payments()
                a = min(
                    (int(i) for i in candidates),
                    key=lambda i: (
                        tuple(int(v) for v in identities[i]),
                        tuple(int(v) for v in payments[i]),
                    ),
                )
        return a, float(q[a])
