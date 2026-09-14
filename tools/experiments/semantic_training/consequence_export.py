"""Create matched frozen-backbone residual policies from a current paired checkpoint."""

import argparse
import hashlib
from pathlib import Path

import torch

from tools.experiments.semantic_training.agent import SemanticAgent
from tools.experiments.semantic_training.consequence_policy import ConsequencePolicyNet, FORMAT
from tools.experiments.semantic_training.player_loader import FORMAT as PARENT_FORMAT
from tools.experiments.semantic_training.rule_auxiliary import RuleHead
from training.core.artifact_io import load_checkpoint, save_checkpoint
from training.core.network import AgentConfig


def export(source, output, seed=95400):
    payload = load_checkpoint(source, map_location='cpu', weights_only=False)
    if payload.get('format') != 'paired-consequence/1.0.0' or payload.get('parent_format') != PARENT_FORMAT:
        raise ValueError('current-format paired consequence parent required')
    cfg = AgentConfig(**payload['shape'])
    torch.manual_seed(seed)
    agent = SemanticAgent(cfg)
    agent.net.load_state_dict(payload['net'], strict=True)
    head = RuleHead(cfg.d_model)
    head.load_state_dict(payload['rule_head'], strict=True)
    model = ConsequencePolicyNet(agent.net, head, cfg.d_model)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    for arm, enabled in (('candidate', True), ('control', False)):
        save_checkpoint(
            dict(
                format=FORMAT,
                shape=vars(cfg),
                net=model.state_dict(),
                use_consequences=enabled,
                parent_sha256=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
                parent=str(source),
                initialization_seed=seed,
            ),
            root / f'{arm}.pt',
        )
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    parser.add_argument('--seed', type=int, default=95400)
    args = parser.parse_args()
    export(args.source, args.output, args.seed)
