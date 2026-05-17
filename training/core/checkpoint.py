"""CheckpointManager — paradigm-agnostic save / load / resume.

Spec: design/pipeline-driver.md §5.

Adapted from training/dmc/_resume_helpers.py + _train_helpers.save_ckpt.
Owns ckpt directory layout + RNG capture/restore + optimizer migration.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import torch

from training.core.protocols import PipelineState


class CheckpointManager:
    """Manages ckpt save/load for a run.

    Layout:
        artifacts_dir/
            ckpt_<step>.pt
            latest.pt           (symlink-like copy)
            metrics.jsonl
            cfg_snapshot.json
    """

    def __init__(self, cfg: Any, network: torch.nn.Module, optimizer: Any, buffer: Any) -> None:
        self.cfg = cfg
        self.network = network
        self.optimizer = optimizer
        self.buffer = buffer
        self.artifacts_dir: Optional[Path] = None

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
    ) -> Path:
        """Materialize the artifacts dir.

        ``timestamp_utc`` (`%Y%m%d%H%M`): if provided, used verbatim as
        the dir-name prefix; defaults to ``datetime.now().strftime``
        (local tz — only used in the no-metadata fallback path).
        Pass an injected value (typically derived from
        ``RunMetadata.timestamp`` via ``tools.run --run-id``,
        converted to UTC strftime) to make the dir-name timestamp
        identical to the register-time UTC timestamp — single-sourced,
        sync-safe across machines."""
        if resume_from is not None:
            d = Path(resume_from).parent
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
        ckpt_path = d / f'ckpt_{state.step}.pt'
        payload = {
            'net': self.network.state_dict(),
            'optimizer': self.optimizer.state_dict() if self.optimizer is not None else None,
            'state': state.snapshot(),
            'cfg_run_label': self.cfg.meta.run_label,
        }
        if extra:
            payload.update(extra)
        torch.save(payload, ckpt_path)
        shutil.copy2(ckpt_path, d / 'latest.pt')
        return ckpt_path

    def try_resume(self, path: Path, device: str = 'cpu') -> PipelineState:
        ckpt = torch.load(path, map_location=device, weights_only=False)
        self.network.load_state_dict(ckpt['net'])
        if self.optimizer is not None and ckpt.get('optimizer') is not None:
            self.optimizer.load_state_dict(ckpt['optimizer'])
            # Migrate optimizer state tensors to target device (Adam exp_avg etc).
            for group in self.optimizer.state.values():
                for k, v in group.items():
                    if torch.is_tensor(v):
                        group[k] = v.to(device)
        sd = ckpt.get('state', {})
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
