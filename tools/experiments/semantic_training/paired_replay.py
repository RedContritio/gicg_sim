"""Train-only numeric consequence replay and explicit compatible diagnostic export."""

import hashlib
from pathlib import Path
import random

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.paired_training import assess, objective, predict
from tools.experiments.semantic_training.rule_auxiliary import attach
from tools.experiments.semantic_training.value_baseline import attach as attach_value
from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.network import AgentConfig


class PairedReplay:
    def __init__(self, pairs, seed, batch_pairs=8):
        self.strata = {}
        for pair in pairs:
            if pair['split'] == 'train':
                self.strata.setdefault(pair['parameter'], []).append(pair)
        if not self.strata or batch_pairs < 1:
            raise ValueError('nonempty train-only replay required')
        self.parameters = sorted(self.strata)
        self.rng = random.Random(seed)
        self.batch_pairs = batch_pairs
        self.calls = 0

    def __call__(self, agent):
        rows = [self.rng.choice(self.strata[self.rng.choice(self.parameters)]) for _ in range(self.batch_pairs)]
        pred, truth = predict(agent, rows)
        self.calls += 1
        return objective(pred, truth, rows, beta=1.0)


def export_initial(source, destination):
    payload = load_checkpoint(source, map_location='cpu', weights_only=False)
    if payload['format'] != 'paired-consequence/1.0.0':
        raise ValueError('expected paired consequence diagnostic checkpoint')
    parent = payload.get('parent_format')
    if parent not in ('semantic-q/1.0.0', 'semantic-q/2.0.0'):
        raise ValueError('unknown semantic parent format')
    agent = SemanticAgent(AgentConfig(**payload['shape']))
    agent.net.load_state_dict(payload['net'], strict=True)
    attach(agent).load_state_dict(payload['rule_head'], strict=True)
    # Structural identity has just been verified under strict source provenance.
    # Exporting a policy container does not alter weights or compatibility fingerprint.
    save_checkpoint(
        dict(
            format=parent,
            shape=payload['shape'],
            net=payload['net'],
            rule_head=payload['rule_head'],
            value_head=attach_value(agent).state_dict(),
            settings={'temperature': 0.5},
            algorithm='explicit paired diagnostic policy export',
            diagnostic_parent=str(source),
            diagnostic_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        ),
        destination,
    )
    return payload


def retention(checkpoint, initial, pairs):
    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    agent = SemanticAgent(AgentConfig(**payload['shape']), 'cuda')
    agent.net.load_state_dict(payload['net'])
    attach(agent).load_state_dict(payload.get('rule_head', initial['rule_head']))
    # RL-only keeps the original readout; shared representations may still change.
    result = assess(agent, pairs)
    del agent
    torch.cuda.empty_cache()
    return result
