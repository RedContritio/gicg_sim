"""Reproducible DMC pilot with explicit fresh optimizer and optional clean warm-start."""

import argparse
import json
from pathlib import Path
import random

import numpy as np
import torch

from training.core.artifact_io import provenance
from training.core.checkpoint import load_net_state_dict
from training.core.config.loader import load_cfg
from training.core.env_factory import make_env_factory
from training.core.pipeline import run_pipeline
from training.paradigms.dmc.paradigm import DMCParadigm


class SeededParadigm(DMCParadigm):
    def __init__(self, seed, initial):
        super().__init__()
        self.seed = seed
        self.initial = initial

    def make_network(self, cfg):
        if self._network is None:
            network = super().make_network(cfg)
            network._agent.rng.seed(self.seed)
            if self.initial:
                network._agent.net.load_state_dict(load_net_state_dict(self.initial))
        return self._network


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--initial', type=Path)
    args = parser.parse_args()
    cfg = load_cfg(args.config)
    seed = cfg.meta.seed
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.use_deterministic_algorithms(True)
    args.output.mkdir(parents=True, exist_ok=False)
    paradigm = SeededParadigm(seed, args.initial)
    network = paradigm.make_network(cfg)
    pool = paradigm.make_opponent_pool(cfg, network)
    state = run_pipeline(
        cfg,
        paradigm,
        env_factory=make_env_factory(cfg, None, master_seed=seed),
        opp_pool=pool,
        prebuilt_artifacts_dir=args.output,
    )
    (args.output / 'complete.json').write_text(
        json.dumps(
            {'provenance': provenance(), 'state': state.snapshot(), 'initial': str(args.initial), 'seed': seed},
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
