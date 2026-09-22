import pytest
import torch

from tools.ckpt.average_semantic import average_checkpoints, average_payloads
from tools.experiments.semantic_training.player_loader import FORMAT, load_semantic_payload
from training.core.artifact_io import load_checkpoint, save_checkpoint


def _payload(offset, *, with_value=True):
    payload = {
        'format': FORMAT,
        'shape': {'d_model': 4},
        'net': {
            'weight': torch.full((2, 2), float(offset)),
            'counter': torch.tensor([7], dtype=torch.int64),
        },
        'settings': {'master_seed': 932000},
        'algorithm': 'semantic RL16 single-step',
    }
    if with_value:
        payload['value_head'] = {'bias': torch.full((1,), float(offset))}
    return payload


def test_average_semantic_payload_averages_net_and_value_head():
    result = average_payloads([_payload(i) for i in range(4)])
    assert torch.equal(result['net']['weight'], torch.full((2, 2), 1.5))
    assert torch.equal(result['net']['counter'], torch.tensor([7]))
    assert torch.equal(result['value_head']['bias'], torch.tensor([1.5]))
    assert result['format'] == FORMAT
    assert result['shape'] == {'d_model': 4}
    assert result['settings'] == {'master_seed': 932000}


def test_average_semantic_payload_rejects_mixed_value_heads():
    with pytest.raises(ValueError, match='value_head'):
        average_payloads([_payload(0), _payload(1, with_value=False)])


def test_average_semantic_payload_rejects_mixed_value_encoding():
    first, second = _payload(0), _payload(1)
    second['value_encoding'] = 'win_probability'
    with pytest.raises(ValueError, match='value encoding'):
        average_payloads([first, second])


def test_average_semantic_payload_rejects_shape_mismatch():
    other = _payload(1)
    other['net']['weight'] = torch.zeros(3, 2)
    with pytest.raises(ValueError, match='shape or dtype'):
        average_payloads([_payload(0), other])


def test_average_checkpoints_requires_four_inputs(tmp_path):
    with pytest.raises(ValueError, match='exactly four'):
        average_checkpoints([tmp_path / 'a.pt'] * 3, tmp_path / 'out.pt')


def test_average_checkpoints_writes_loadable_envelope(tmp_path):
    inputs = []
    for index in range(4):
        path = tmp_path / f'{index}.pt'
        save_checkpoint(_payload(index), path)
        inputs.append(path)
    output = tmp_path / 'soup.pt'
    average_checkpoints(inputs, output)
    result = load_checkpoint(output, map_location='cpu', weights_only=False)
    loaded = load_semantic_payload(output)
    assert result['format'] == FORMAT
    assert loaded['shape'] == {'d_model': 4}
    assert '_training_provenance' in result
    assert torch.equal(result['net']['weight'], torch.full((2, 2), 1.5))
