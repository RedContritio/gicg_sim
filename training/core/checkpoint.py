"""CheckpointManager — paradigm-agnostic save / load / resume.

Spec: design/pipeline-driver.md §5.

Adapted from training/dmc/_resume_helpers.py + _train_helpers.save_ckpt.
Owns ckpt directory layout + RNG capture/restore + optimizer migration.
"""

from __future__ import annotations

from training.core.artifact_io import load_checkpoint, save_checkpoint

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import torch

from training.core.protocols import PipelineState
from training.core.checkpoint_runtime import capture_runtime, restore_runtime


def load_net_state_dict(ckpt_path: Any, *, map_location: Any = 'cpu') -> dict:
    """Load a CheckpointManager-format ckpt and return the net state_dict
    ready for ``module.load_state_dict()``. Handles the production wrapper
    'net.' prefix strip uniformly (W1-T4 — pre-W1-T4 ``_dmc_adapter`` did
    the strip but ``_dmc_evaluator`` silently skipped it, latent bug under
    InfServer-wrapper save paths).

    The CheckpointManager payload format ({'net', 'optimizer', 'state',
    'cfg_run_label'}) is distinct from ``AgentBase.save`` (schema-v2
    self-describing {'net_state_dict', 'paradigm', ...}); this helper only
    handles the CheckpointManager flavor. AgentBase ckpts SHALL go through
    ``AgentBase.load``.

    Args:
        ckpt_path: path to ckpt file (str or PathLike).
        map_location: torch.load map_location (default 'cpu').

    Returns:
        state_dict suitable for ``net.load_state_dict()``.
    """
    blob = load_checkpoint(ckpt_path, map_location=map_location, weights_only=False)
    state_dict = blob['net']
    if state_dict and all(k.startswith('net.') for k in state_dict.keys()):
        state_dict = {k[len('net.') :]: v for k, v in state_dict.items()}
    return state_dict


class CheckpointManager:
    """Manages ckpt save/load for a run.

    Layout:
        artifacts_dir/
            ckpts/
                ckpt_<step>.pt
                latest.pt           (symlink-like copy of last ckpt_<step>.pt)
            metrics.jsonl
            cfg_snapshot.json
    """

    def __init__(self, cfg: Any, network: torch.nn.Module, optimizer: Any, buffer: Any) -> None:
        self.cfg = cfg
        self.network = network
        self.optimizer = optimizer
        self.buffer = buffer
        self.artifacts_dir: Optional[Path] = None
        self.runtime_components = {}

    @staticmethod
    def compute_dir_name(ts: str, run_label: str) -> str:
        """Canonical artifacts-dir basename: `<ts>_<run_label>`. Single
        source of truth so callers (driver auto-complete, sync, etc.)
        don't manually re-implement the formula and silently drift if
        the convention changes."""
        return f'{ts}_{run_label}'

    def init_artifacts_dir(
        self,
        resume_from: Optional[Path] = None,
        *,
        timestamp_utc: Optional[str] = None,
        prebuilt: Optional[Path] = None,
    ) -> Path:
        """Materialize the artifacts dir.

        ``timestamp_utc`` (`%Y%m%d%H%M`): if provided, used verbatim as
        the dir-name prefix; defaults to ``datetime.now().strftime``
        (local tz — only used in the no-metadata fallback path).
        Pass an injected value (typically derived from
        ``RunMetadata.timestamp`` via the legacy ``tools.run --run-id``
        path retired in T-23; post-redesign ``tools.runs.train`` Phase
        A sets ``prebuilt_artifacts_dir`` directly so this kwarg
        becomes unused on that path) to make the dir-name timestamp
        identical to the register-time UTC timestamp — single-sourced,
        sync-safe across machines.

        ``prebuilt``: if provided, the dir is treated as already created
        by the caller (e.g. ``tools.runs.train`` Phase A's allocator
        mkdir under ``artifacts/<ts>_<NNN>_<label>/``). The manager just
        adopts it as ``self.artifacts_dir`` — no mkdir, no name
        derivation, no ``cfg.checkpoint.artifacts_root`` lookup. Mutually
        exclusive with ``resume_from`` and ``timestamp_utc`` (passing
        both is a caller bug — raise). Per spec §Architecture CRIT-X-1
        (`docs/superpowers/specs/2026-05-18-tools-runs-redesign-design
        .md` 行 28-32): the atomic lifecycle owns NNN allocation and dir
        creation; this manager merely writes into the dir handed to it.
        """
        if prebuilt is not None:
            if resume_from is not None:
                raise ValueError(
                    'CheckpointManager.init_artifacts_dir: prebuilt and resume_from are mutually exclusive'
                )
            if timestamp_utc is not None:
                raise ValueError(
                    'CheckpointManager.init_artifacts_dir: prebuilt and timestamp_utc are mutually exclusive '
                    '(prebuilt dir name already determined by caller)'
                )
            if not prebuilt.is_dir():
                raise FileNotFoundError(f'CheckpointManager: prebuilt {prebuilt} is not an existing dir')
            self.artifacts_dir = prebuilt
            return prebuilt
        if resume_from is not None:
            # ckpts live in `<artifacts_dir>/ckpts/<file>.pt` — strip `ckpts/`.
            ckpts_dir = Path(resume_from).parent
            if ckpts_dir.name != 'ckpts':
                raise ValueError(
                    f'CheckpointManager: resume {resume_from} parent dir is '
                    f'{ckpts_dir.name!r}, expected {"ckpts"!r} (per spec §Per-run dir 结构)'
                )
            d = ckpts_dir.parent
            if not (d / 'metrics.jsonl').exists():
                raise FileNotFoundError(f'CheckpointManager: resume {resume_from} missing sibling metrics.jsonl')
            self.artifacts_dir = d
            return d
        ts = timestamp_utc or datetime.now().strftime('%Y%m%d%H%M')
        root = Path(getattr(self.cfg.checkpoint, 'artifacts_root', 'artifacts'))
        d = root / self.compute_dir_name(ts, self.cfg.meta.run_label)
        d.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir = d
        return d

    def should_save(self, state: PipelineState) -> bool:
        save_every = getattr(self.cfg.checkpoint, 'save_every', 1000)
        if save_every <= 0:
            return False
        if state.last_ckpt_at_step < 0:
            return state.step >= save_every
        return state.step - state.last_ckpt_at_step >= save_every

    def save(self, state: PipelineState, *, extra: Optional[dict] = None) -> Path:
        if self.artifacts_dir is None:
            self.init_artifacts_dir()
        d = self.artifacts_dir
        ckpts_dir = d / 'ckpts'
        ckpts_dir.mkdir(parents=True, exist_ok=True)
        ckpt_path = ckpts_dir / f'ckpt_{state.step}.pt'
        payload = {
            'net': self.network.state_dict(),
            'optimizer': self.optimizer.state_dict() if self.optimizer is not None else None,
            'state': state.snapshot(),
            'cfg_run_label': self.cfg.meta.run_label,
            'runtime': capture_runtime(self.runtime_components),
        }
        if extra:
            payload.update(extra)
        save_checkpoint(payload, ckpt_path)
        shutil.copy2(ckpt_path, ckpts_dir / 'latest.pt')
        keep = getattr(self.cfg.checkpoint, 'keep_last_n', 0)
        if keep > 0:
            older = sorted(ckpts_dir.glob('ckpt_*.pt'), key=lambda p: int(p.stem.split('_')[1]))[:-keep]
            for old in older:
                old.unlink()
        return ckpt_path

    def try_resume(self, path: Path, device: str = 'cpu') -> PipelineState:
        ckpt = load_checkpoint(path, map_location=device, weights_only=False)
        self.network.load_state_dict(ckpt['net'])
        if self.optimizer is not None and ckpt.get('optimizer') is not None:
            self.optimizer.load_state_dict(ckpt['optimizer'])
            # Migrate optimizer state tensors to target device (Adam exp_avg etc).
            for group in self.optimizer.state.values():
                for k, v in group.items():
                    if torch.is_tensor(v):
                        group[k] = v.to(device)
        sd = ckpt.get('state', {})
        restore_runtime(ckpt.get('runtime'), self.runtime_components)
        st = PipelineState(**{k: sd[k] for k in sd if k in PipelineState.__dataclass_fields__})
        if 'cfg_run_label' in ckpt and ckpt['cfg_run_label'] != self.cfg.meta.run_label:
            print(
                f'[checkpoint] WARNING: ckpt run_label={ckpt["cfg_run_label"]!r} '
                f'!= cfg.run_label={self.cfg.meta.run_label!r}'
            )
        return st

    def save_cfg_snapshot(self) -> None:
        if self.artifacts_dir is None:
            return
        snap = {
            'meta': {
                'seed': self.cfg.meta.seed,
                'paradigm': self.cfg.meta.paradigm,
                'run_label': self.cfg.meta.run_label,
                'device': self.cfg.meta.device,
            },
            'pipeline_mode': self.cfg.pipeline.mode,
        }
        (self.artifacts_dir / 'cfg_snapshot.json').write_text(json.dumps(snap, ensure_ascii=False, indent=2))
