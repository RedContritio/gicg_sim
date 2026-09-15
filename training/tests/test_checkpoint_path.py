"""T-06 — CheckpointManager.save writes to <artifacts_dir>/ckpts/ subdir.

Spec ref:
- design/2026-05-18-tools-runs-redesign-design.md §Per-run 完全 self-contained
  (`ckpts/` subdir holds all `.pt` files, separated from metadata + cfg layer)
- design/2026-05-18-tools-runs-redesign-design-rollout.md §ckpts/ 内 naming convention
  (`ckpt_<step>.pt`, `latest.pt` both live in `ckpts/`)

Verifies the implementation contract — caller passes `artifacts_dir`, the
manager creates and writes into the `ckpts/` subdir.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from training.core.checkpoint import CheckpointManager
from training.core.protocols import PipelineState


class _TinyNet(torch.nn.Module):
    """Minimal nn.Module — one Linear layer; state_dict has stable keys."""

    def __init__(self) -> None:
        super().__init__()
        self.fc = torch.nn.Linear(2, 2)


def _make_cfg(run_label: str = 'test_ckpt_path') -> SimpleNamespace:
    return SimpleNamespace(
        meta=SimpleNamespace(run_label=run_label, seed=0, paradigm='test', device='cpu'),
        checkpoint=SimpleNamespace(artifacts_root='artifacts', save_every=10),
        pipeline=SimpleNamespace(mode='test'),
    )


def _make_manager(artifacts_dir: Path) -> CheckpointManager:
    cfg = _make_cfg()
    net = _TinyNet()
    opt = torch.optim.SGD(net.parameters(), lr=0.01)
    mgr = CheckpointManager(cfg, net, opt, buffer=None)
    mgr.artifacts_dir = artifacts_dir
    return mgr


def _state(step: int) -> PipelineState:
    s = PipelineState.fresh(seed=0)
    s.step = step
    return s


def test_save_writes_to_ckpts_subdir(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / 'run_a'
    artifacts_dir.mkdir()
    mgr = _make_manager(artifacts_dir)

    returned = mgr.save(_state(step=30))

    expected = artifacts_dir / 'ckpts' / 'ckpt_30.pt'
    assert returned == expected, f'save() return: expected {expected}, got {returned}'
    assert expected.exists(), f'ckpt_30.pt not at {expected}'
    # Flat layout (old) MUST NOT exist — clean-slate, no compat path.
    assert not (artifacts_dir / 'ckpt_30.pt').exists(), 'flat ckpt_30.pt at artifacts_dir root must NOT exist'


def test_save_writes_latest_in_ckpts_subdir(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / 'run_b'
    artifacts_dir.mkdir()
    mgr = _make_manager(artifacts_dir)

    mgr.save(_state(step=30))

    latest = artifacts_dir / 'ckpts' / 'latest.pt'
    assert latest.exists(), f'latest.pt missing at {latest}'
    assert not (artifacts_dir / 'latest.pt').exists(), 'flat latest.pt at artifacts_dir root must NOT exist'


def test_save_creates_ckpts_dir_when_missing(tmp_path: Path) -> None:
    # artifacts_dir exists but ckpts/ does not yet — save() must mkdir it.
    artifacts_dir = tmp_path / 'run_c'
    artifacts_dir.mkdir()
    assert not (artifacts_dir / 'ckpts').exists()

    mgr = _make_manager(artifacts_dir)
    mgr.save(_state(step=10))

    assert (artifacts_dir / 'ckpts').is_dir(), 'ckpts/ subdir was not created by save()'


def test_save_multiple_steps_latest_tracks_last(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / 'run_d'
    artifacts_dir.mkdir()
    mgr = _make_manager(artifacts_dir)

    mgr.save(_state(step=30))
    mgr.save(_state(step=60))

    ckpts_dir = artifacts_dir / 'ckpts'
    assert (ckpts_dir / 'ckpt_30.pt').exists()
    assert (ckpts_dir / 'ckpt_60.pt').exists()
    latest = ckpts_dir / 'latest.pt'
    assert latest.exists()

    # latest.pt content must reflect step=60 (the most recent save).
    latest_payload = torch.load(latest, map_location='cpu', weights_only=False)
    assert latest_payload['state']['step'] == 60, f'latest.pt step expected 60, got {latest_payload["state"]["step"]}'


def test_resume_loads_from_ckpts_subdir(tmp_path: Path) -> None:
    # Round-trip: save then try_resume from the ckpts/ path.
    artifacts_dir = tmp_path / 'run_e'
    artifacts_dir.mkdir()
    mgr = _make_manager(artifacts_dir)

    saved_path = mgr.save(_state(step=42))
    assert saved_path == artifacts_dir / 'ckpts' / 'ckpt_42.pt'

    # Fresh manager (same cfg + new net) loads from the ckpts/ path.
    mgr2 = _make_manager(artifacts_dir)
    restored = mgr2.try_resume(saved_path, device='cpu')
    assert restored.step == 42


def test_init_artifacts_dir_resume_from_ckpts_subdir(tmp_path: Path) -> None:
    """resume_from is `<artifacts_dir>/ckpts/<file>.pt`; init_artifacts_dir
    strips `ckpts/` to derive the run dir, then sibling-checks metrics.jsonl."""
    artifacts_dir = tmp_path / 'run_f'
    artifacts_dir.mkdir()
    (artifacts_dir / 'ckpts').mkdir()
    ckpt_file = artifacts_dir / 'ckpts' / 'latest.pt'
    torch.save({'dummy': True}, ckpt_file)
    (artifacts_dir / 'metrics.jsonl').write_text('')

    cfg = _make_cfg()
    net = _TinyNet()
    opt = torch.optim.SGD(net.parameters(), lr=0.01)
    mgr = CheckpointManager(cfg, net, opt, buffer=None)

    returned = mgr.init_artifacts_dir(resume_from=ckpt_file)
    assert returned == artifacts_dir, (
        f'init_artifacts_dir(resume_from=ckpts/latest.pt) expected {artifacts_dir}, got {returned}'
    )
    assert mgr.artifacts_dir == artifacts_dir


def test_init_artifacts_dir_rejects_resume_from_flat_layout(tmp_path: Path) -> None:
    """Clean-slate: resume_from at `<artifacts_dir>/latest.pt` (old flat
    layout) MUST raise — backward compat is explicitly NOT supported."""
    artifacts_dir = tmp_path / 'run_g'
    artifacts_dir.mkdir()
    ckpt_file = artifacts_dir / 'latest.pt'  # flat, not in ckpts/
    torch.save({'dummy': True}, ckpt_file)
    (artifacts_dir / 'metrics.jsonl').write_text('')

    cfg = _make_cfg()
    net = _TinyNet()
    opt = torch.optim.SGD(net.parameters(), lr=0.01)
    mgr = CheckpointManager(cfg, net, opt, buffer=None)

    with pytest.raises(ValueError, match='ckpts'):
        mgr.init_artifacts_dir(resume_from=ckpt_file)


def test_init_artifacts_dir_resume_missing_metrics_jsonl(tmp_path: Path) -> None:
    """ckpts/ structure correct but metrics.jsonl missing → FileNotFoundError."""
    artifacts_dir = tmp_path / 'run_h'
    artifacts_dir.mkdir()
    (artifacts_dir / 'ckpts').mkdir()
    ckpt_file = artifacts_dir / 'ckpts' / 'latest.pt'
    torch.save({'dummy': True}, ckpt_file)
    # metrics.jsonl absent.

    cfg = _make_cfg()
    net = _TinyNet()
    opt = torch.optim.SGD(net.parameters(), lr=0.01)
    mgr = CheckpointManager(cfg, net, opt, buffer=None)

    with pytest.raises(FileNotFoundError, match='metrics.jsonl'):
        mgr.init_artifacts_dir(resume_from=ckpt_file)
