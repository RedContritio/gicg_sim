"""Experiment controls: isolate initialization and primitive representation changes."""

import numpy as np
import torch

from tools.experiments.primitive_expansion import read
from training.core.artifact_io import save_dataset


def test_primitive_reencoding_preserves_labels_and_is_invertible(tmp_path):
    ir = np.array([[[5, 1, 2, 3, 4], [5, 1, 1, 3, 4]]], dtype=np.int64)
    path = tmp_path / 'cost.npz'
    save_dataset(path, hook_ir=ir, buffs=np.zeros((1, 1, 16)), action_refs=np.zeros((1, 3)), costs=np.array([3.0]))
    expanded, count = read(path, True)
    assert count == 1
    assert expanded['hook_ir'][0, 0, 0] == 16
    restored = expanded['hook_ir'].copy()
    restored[:, :, 0][restored[:, :, 0] == 16] = 5
    np.testing.assert_array_equal(restored, ir)
    np.testing.assert_array_equal(expanded['costs'], [3.0])


def test_seeded_factory_reuses_network_and_initializes_reproducibly():
    from tools.experiments.train_seeded import SeededParadigm
    from training.core.config.loader import load_cfg

    cfg = load_cfg('configs/dmc/smoke.toml')
    torch.manual_seed(41)
    first = SeededParadigm(41, None)
    a = first.make_network(cfg)
    assert first.make_network(cfg) is a
    torch.manual_seed(41)
    b = SeededParadigm(41, None).make_network(cfg)
    assert all(torch.equal(v, b.state_dict()[k]) for k, v in a.state_dict().items())
    assert a._agent.rng.random() == b._agent.rng.random()
