"""State needed to continue a serial collector at an episode boundary."""

import random

import numpy as np
import torch


def capture_runtime(components):
    if not components:
        return None
    return {
        'version': 1,
        'components': {name: value.state_dict() for name, value in components.items()},
        'python_rng': random.getstate(),
        'numpy_rng': np.random.get_state(),
        'torch_rng': torch.get_rng_state(),
        'cuda_rng': torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else None,
    }


def restore_runtime(saved, components):
    if not components:
        return
    if not saved or saved.get('version') != 1 or set(saved.get('components', {})) != set(components):
        raise ValueError('checkpoint is missing complete serial runtime state')
    for name, value in components.items():
        value.load_state_dict(saved['components'][name])
    random.setstate(saved['python_rng'])
    np.random.set_state(saved['numpy_rng'])
    torch.set_rng_state(saved['torch_rng'].cpu())
    if saved['cuda_rng'] is not None:
        torch.cuda.set_rng_state_all([state.cpu() for state in saved['cuda_rng']])
