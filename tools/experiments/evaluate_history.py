"""Paired direct matches against frozen earlier checkpoints of the same run."""

import argparse
import hashlib
import json
from pathlib import Path

import torch

from tools.experiments.calibrate_ladder import play_pair
from tools.experiments.eval_ladder import evaluation_provenance
from training.core.artifact_io import provenance
from training.core.checkpoint import load_net_state_dict
from training.core.config.loader import load_cfg
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.config import DMCParadigmConfig


def builder(cfg, path):
    shape = DMCParadigmConfig.from_dict(cfg.paradigm).agent
    agent = DmcAgent(AgentConfig.from_obs_shape(shape), epsilon=0)
    agent.net.load_state_dict(load_net_state_dict(path))
    agent.net.eval()

    def build(seed):
        agent.rng.seed(seed)
        return agent

    return build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('current', type=Path)
    parser.add_argument('previous', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=int, default=112000)
    parser.add_argument('--scenarios', type=int, default=32)
    args = parser.parse_args()
    torch.set_num_threads(1)
    cfg = load_cfg(args.config)
    result = play_pair(cfg, builder(cfg, args.current), builder(cfg, args.previous), args.scenarios, args.seed)
    result.update(
        provenance=provenance(),
        evaluation=evaluation_provenance(),
        seed=args.seed,
        current=str(args.current),
        previous=str(args.previous),
        checkpoint_sha256={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.current, args.previous)},
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(args.output, result['score'], flush=True)


if __name__ == '__main__':
    main()
