"""Independent reproducible episode random streams."""

from typing import Any


def derive_seed(master_seed: int, *labels: Any) -> int:
    """Deterministic seed derivation from master + arbitrary labels."""
    h = master_seed & 0xFFFFFFFF
    for lab in labels:
        s = repr(lab).encode('utf-8')
        for b in s:
            h = (h * 1000003) ^ b
            h &= 0xFFFFFFFF
    return int(h & 0x7FFFFFFF)


def episode_seeds(master: int, index: int) -> dict:
    return {name: derive_seed(master, name, index) for name in ('episode', 'layout', 'deck_0', 'deck_1')}
