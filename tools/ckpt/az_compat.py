"""tools.ckpt.az_compat — in-place backfill of self-describing keys into
pipeline-format AZ checkpoints.

The unified pipeline's CheckpointManager saves schema-v1 payloads
(``{'net', 'optimizer', 'state', 'cfg_run_label', 'runtime'}``), while
the matchup player loader (``training/paradigms/az/_player_loader.py``)
expects the self-describing schema (``{'cfg', 'net_state_dict', ...}``).
Save-side now emits both (checkpoint.py, duck-gated, purely additive);
this tool fixes ALREADY-LANDED ckpts in place.

Usage:
    .venv/bin/python -m tools.ckpt.az_compat <ckpt_path> --run-dir <run_dir>

``<run_dir>`` is the run's artifacts dir (the one containing
``cfg_resolved.toml`` / ``cfg_leaf.toml``); the AgentConfig is rebuilt
from that cfg via the same path AZParadigm.make_network uses
(``AgentConfig.from_obs_shape(pcfg.agent)``).

Behavior:
- Idempotent: a ckpt that already has ``cfg`` + ``net_state_dict`` is
  reported and left untouched.
- Safety: the derived ``net_state_dict`` is strict-loaded into a fresh
  ``Agent(cfg).net`` BEFORE anything is written; on mismatch the ckpt
  is left untouched and the tool exits non-zero.
- Provenance: the original ``_training_provenance`` key is preserved
  verbatim (plain torch.save, NOT save_checkpoint which would
  re-stamp), so load_checkpoint validation keeps passing.

Exit codes: 0 success / no-op, 1 error (nothing written).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import torch

from training.core.artifact_io import load_checkpoint
from training.core.network import AgentConfig
from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.az.network import Agent


def _resolve_cfg_toml(run_dir: Path) -> Path:
    """Prefer the fully-resolved cfg snapshot (no extends chain)."""
    for name in ('cfg_resolved.toml', 'cfg_leaf.toml'):
        p = run_dir / name
        if p.exists():
            return p
    raise FileNotFoundError(f'az_compat: no cfg_resolved.toml / cfg_leaf.toml in run dir {run_dir}')


def agent_config_from_run_dir(run_dir: Path) -> AgentConfig:
    """Rebuild the run's AgentConfig from its cfg snapshot — the same
    source AZParadigm.make_network constructs the Agent from."""
    from training.core.config.loader import load_cfg

    cfg_toml = _resolve_cfg_toml(run_dir)
    cfg = load_cfg(cfg_toml)
    if cfg.meta.paradigm != 'az':
        raise ValueError(f'az_compat: run dir cfg paradigm={cfg.meta.paradigm!r}, expected "az"')
    pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
    return AgentConfig.from_obs_shape(pcfg.agent)


def backfill_az_ckpt(ckpt_path: Path, run_dir: Path) -> dict:
    """Add ``cfg`` + ``net_state_dict`` to a pipeline-format AZ ckpt, in
    place. Returns a summary dict (also reports no-op)."""
    ckpt_path = Path(ckpt_path)
    run_dir = Path(run_dir)
    if not ckpt_path.exists():
        raise FileNotFoundError(f'az_compat: ckpt {ckpt_path} not found')

    agent_cfg = agent_config_from_run_dir(run_dir)
    cfg_dict = dict(vars(agent_cfg))

    blob = load_checkpoint(ckpt_path, map_location='cpu', weights_only=False)

    if 'cfg' in blob and 'net_state_dict' in blob:
        return {'ckpt': str(ckpt_path), 'added': [], 'noop': True}

    if 'net' not in blob:
        raise RuntimeError(f"az_compat: ckpt {ckpt_path} has neither 'net_state_dict' nor legacy 'net' key")

    # Inner-net state dict: pipeline 'net' is the AZNetwork wrapper's
    # state_dict (keys '_agent.net.*' plus the aliased 'net.*'); the
    # loader needs the bare ActorCritic keys.
    inner = {k[len('net.') :]: v for k, v in blob['net'].items() if k.startswith('net.')}
    if not inner:
        raise RuntimeError(
            f"az_compat: ckpt {ckpt_path} 'net' has no 'net.'-prefixed keys "
            f'(sample: {sorted(blob["net"])[:5]}...) — not an AZNetwork state dict?'
        )

    # Verify BEFORE writing: strict-load into a fresh Agent(cfg).net.
    probe = Agent(agent_cfg)
    probe.net.load_state_dict(inner)
    probe.net.eval()

    blob['cfg'] = cfg_dict
    blob['net_state_dict'] = inner

    tmp_path = ckpt_path.with_suffix(ckpt_path.suffix + '.tmp')
    torch.save(blob, tmp_path)
    os.replace(tmp_path, ckpt_path)  # atomic in-place update
    return {'ckpt': str(ckpt_path), 'added': ['cfg', 'net_state_dict'], 'noop': False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='tools.ckpt.az_compat',
        description=__doc__.split('\n\n')[0],
    )
    parser.add_argument('ckpt', type=str, help='ckpt file path (.pt), updated in place')
    parser.add_argument(
        '--run-dir',
        type=str,
        required=True,
        help='run artifacts dir containing cfg_resolved.toml / cfg_leaf.toml',
    )
    args = parser.parse_args(argv)

    try:
        summary = backfill_az_ckpt(Path(args.ckpt), Path(args.run_dir))
    except Exception as e:
        print(f'error: {e}', file=sys.stderr)
        return 1

    if summary['noop']:
        print(f'{summary["ckpt"]}: already has cfg + net_state_dict — no-op')
    else:
        print(f'{summary["ckpt"]}: backfilled {summary["added"]} (provenance preserved)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
