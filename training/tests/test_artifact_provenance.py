"""Old data rejection must happen before model/optimizer mutation."""

import numpy as np
import pytest
import torch

from training.core.artifact_io import (
    ArtifactCompatibilityError,
    KEY,
    load_checkpoint,
    load_dataset,
    provenance,
    save_checkpoint,
    save_dataset,
)
from training.core.checkpoint import CheckpointManager, load_net_state_dict


def test_raw_and_foreign_weights_rejected_before_resume(tmp_path):
    from types import SimpleNamespace

    net = torch.nn.Linear(2, 1)
    original = {k: v.clone() for k, v in net.state_dict().items()}
    manager = CheckpointManager(SimpleNamespace(), net, None, None)
    for meta in (None, {**provenance(), 'epoch': 'old'}, {**provenance(), 'source_observation_sha256': 'foreign'}):
        path = tmp_path / 'old.pt'
        payload = {'net': {k: torch.zeros_like(v) for k, v in original.items()}}
        if meta is not None:
            payload[KEY] = meta
        torch.save(payload, path)
        with pytest.raises(ArtifactCompatibilityError):
            manager.try_resume(path)
        with pytest.raises(ArtifactCompatibilityError):
            load_net_state_dict(path)
        for k, v in net.state_dict().items():
            torch.testing.assert_close(v, original[k])


def test_clean_checkpoint_and_dataset_roundtrip_and_lineage(tmp_path):
    path = tmp_path / 'new.pt'
    save_checkpoint({'net': {'x': torch.ones(2)}}, path)
    data = load_checkpoint(path, weights_only=True)
    torch.testing.assert_close(data['net']['x'], torch.ones(2))
    child = tmp_path / 'child.pt'
    save_checkpoint({'net': {}}, child)
    assert load_checkpoint(child, weights_only=True)[KEY]['parents']
    dataset = tmp_path / 'new.npz'
    save_dataset(dataset, values=np.arange(3))
    with load_dataset(dataset, allow_pickle=False) as loaded:
        np.testing.assert_array_equal(loaded['values'], np.arange(3))
    np.savez(dataset, values=np.arange(3))
    with pytest.raises(ArtifactCompatibilityError):
        load_dataset(dataset, allow_pickle=False)


def test_production_consumers_cannot_bypass_persistence_gate():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for path in (root / 'training').rglob('*.py'):
        if 'tests' in path.parts or path.name == 'artifact_io.py':
            continue
        source = path.read_text()
        assert 'torch.load(' not in source, path
        assert 'np.load(' not in source, path
