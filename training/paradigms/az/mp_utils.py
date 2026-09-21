"""Shared helpers for AZ multiprocessing components."""

from __future__ import annotations

from typing import Any


def derive_seed(master_seed: int, *labels: Any) -> int:
    value = master_seed & 0xFFFFFFFF
    for label in labels:
        for byte in repr(label).encode('utf-8'):
            value = (value * 1000003) ^ byte
            value &= 0xFFFFFFFF
    return int(value & 0x7FFFFFFF)
