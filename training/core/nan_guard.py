"""NaN guard — fail-fast on non-finite loss / grad with evidence dump.

Paradigm-agnostic: takes loss + grad_norm + batch dict + state-snapshot
dict and dumps to ``<artifacts_dir>/nan_dump_<step>/`` before raising.
"""

from __future__ import annotations

from training.core.artifact_io import save_checkpoint

import json
import pickle
from pathlib import Path
from typing import Any, Optional

import torch


class NaNGuard:
    """Per-run NaN/inf detector. ``check()`` raises with evidence dump."""

    def __init__(self, artifacts_dir: Optional[Path] = None) -> None:
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None

    def check(
        self,
        loss: Any,
        grad_norm: Any,
        *,
        batch: Optional[dict] = None,
        network: Optional[torch.nn.Module] = None,
        optimizer: Optional[Any] = None,
        state_snapshot: Optional[dict] = None,
        train_step: int = 0,
    ) -> None:
        """Raise RuntimeError + dump evidence if loss or grad_norm
        non-finite. No-op when both finite."""
        loss_finite = bool(torch.isfinite(loss).all()) if torch.is_tensor(loss) else _scalar_finite(loss)
        gn_finite = bool(torch.isfinite(grad_norm).all()) if torch.is_tensor(grad_norm) else _scalar_finite(grad_norm)
        if loss_finite and gn_finite:
            return
        dump_dir = self._dump(loss, grad_norm, batch, network, optimizer, state_snapshot, train_step)
        raise RuntimeError(
            f'training step {train_step} produced non-finite loss={_as_float(loss)} / '
            f'grad_norm={_as_float(grad_norm)}. Evidence at {dump_dir}'
        )

    def _dump(
        self,
        loss,
        grad_norm,
        batch,
        network,
        optimizer,
        state_snapshot,
        train_step,
    ):
        base = self.artifacts_dir if self.artifacts_dir is not None else Path('.')
        dump_dir = base / f'nan_dump_{train_step}'
        dump_dir.mkdir(parents=True, exist_ok=True)
        if batch is not None:
            try:
                with open(dump_dir / 'batch.pkl', 'wb') as f:
                    payload = {k: (v.cpu().numpy() if torch.is_tensor(v) else v) for k, v in batch.items()}
                    pickle.dump(payload, f)
            except Exception as e:
                (dump_dir / 'batch_dump_error.txt').write_text(f'{type(e).__name__}: {e}')
        if network is not None:
            try:
                save_checkpoint(
                    {
                        'net': network.state_dict(),
                        'optimizer': optimizer.state_dict() if optimizer is not None else None,
                        'state': state_snapshot or {},
                    },
                    dump_dir / 'pre_step.pt',
                )
            except Exception as e:
                (dump_dir / 'ckpt_dump_error.txt').write_text(f'{type(e).__name__}: {e}')
        diag = {
            'train_step': train_step,
            'loss': _as_float(loss),
            'grad_norm': _as_float(grad_norm),
        }
        if batch is not None:
            diag['batch_keys_any_nan'] = [
                k for k, v in batch.items() if torch.is_tensor(v) and torch.isnan(v).any().item()
            ]
        (dump_dir / 'diag.json').write_text(json.dumps(diag, indent=2))
        return dump_dir


def _scalar_finite(x) -> bool:
    try:
        return x == x and x != float('inf') and x != float('-inf')
    except Exception:
        return False


def _as_float(x):
    try:
        return float(x.item()) if torch.is_tensor(x) else float(x)
    except Exception:
        return None
