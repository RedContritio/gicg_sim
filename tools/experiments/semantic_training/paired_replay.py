"""Train-only numeric consequence replay and explicit compatible diagnostic export."""

import hashlib
from pathlib import Path
import random
import shutil

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.paired_training import assess, objective, predict
from tools.experiments.semantic_training.rule_auxiliary import attach, attach_adapter
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


def _agent_from_payload(payload):
    shape = payload.get('shape')
    if not isinstance(shape, dict):
        raise ValueError('semantic checkpoint is missing shape')
    for key in ('net', 'rule_head'):
        if not isinstance(payload.get(key), dict):
            raise ValueError(f'semantic checkpoint is missing {key}')
    agent = SemanticAgent(AgentConfig(**shape))
    agent.net.load_state_dict(payload['net'], strict=True)
    attach(agent).load_state_dict(payload['rule_head'], strict=True)
    if 'rule_adapter' in payload:
        if not isinstance(payload['rule_adapter'], dict):
            raise ValueError('semantic checkpoint has invalid rule adapter')
        attach_adapter(agent).load_state_dict(payload['rule_adapter'], strict=True)
    return agent


def _load_diagnostic(source):
    payload = load_checkpoint(source, map_location='cpu', weights_only=False)
    if payload.get('format') != 'paired-consequence/1.0.0':
        raise ValueError('expected paired consequence diagnostic checkpoint')
    parent = payload.get('parent_format')
    if parent not in ('semantic-q/1.0.0', 'semantic-q/2.0.0'):
        raise ValueError('unknown semantic parent format')
    return payload, parent, _agent_from_payload(payload)


def validate_resume(payload, *, anchor_sha256, pair_sha256, expected_beta=0.5):
    if payload.get('anchor_sha256') != anchor_sha256:
        raise ValueError('resume checkpoint anchor mismatch')
    protocol = payload.get('paired_replay')
    if not protocol or protocol.get('beta') != expected_beta:
        raise ValueError('resume checkpoint has the wrong paired-replay protocol')
    if protocol.get('sha256') != pair_sha256:
        raise ValueError('resume checkpoint pair data mismatch')
    if protocol.get('batch_pairs') != 8 or protocol.get('difference_beta') != 1.0:
        raise ValueError('resume checkpoint paired-replay settings mismatch')
    return protocol


def prepare_initial(checkpoint, destination, *, resume_initial=None):
    if resume_initial is None:
        return export_initial(checkpoint, destination)
    _, parent, _ = _load_diagnostic(checkpoint)
    if not Path(resume_initial).is_file():
        raise ValueError('resume initial checkpoint is missing')
    shutil.copyfile(resume_initial, destination)
    try:
        payload = load_checkpoint(destination, map_location='cpu', weights_only=False)
        expected = hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest()
        if payload.get('diagnostic_sha256') != expected:
            raise ValueError('resume initial diagnostic mismatch')
        if payload.get('format') != parent:
            raise ValueError('resume initial parent mismatch')
        _agent_from_payload(payload)
    except Exception:
        destination.unlink()
        raise
    return payload


def export_initial(source, destination):
    payload, parent, agent = _load_diagnostic(source)
    # Structural identity has just been verified under strict source provenance.
    # Exporting a policy container does not alter weights or compatibility fingerprint.
    exported = dict(
        format=parent,
        shape=payload['shape'],
        net=payload['net'],
        rule_head=payload['rule_head'],
        value_head=attach_value(agent).state_dict(),
        settings={'temperature': 0.5},
        algorithm='explicit paired diagnostic policy export',
        diagnostic_parent=str(source),
        diagnostic_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
    )
    if 'rule_adapter' in payload:
        exported['rule_adapter'] = payload['rule_adapter']
    save_checkpoint(
        exported,
        destination,
    )
    return payload


def retention(checkpoint, initial, pairs):
    payload = load_checkpoint(checkpoint, map_location='cpu', weights_only=False)
    agent = SemanticAgent(AgentConfig(**payload['shape']), 'cuda')
    agent.net.load_state_dict(payload['net'])
    attach(agent).load_state_dict(payload.get('rule_head', initial['rule_head']))
    if 'rule_adapter' in payload:
        attach_adapter(agent).load_state_dict(payload['rule_adapter'])
    # RL-only keeps the original readout; shared representations may still change.
    result = assess(agent, pairs)
    del agent
    torch.cuda.empty_cache()
    return result
