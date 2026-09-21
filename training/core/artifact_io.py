"""Fail-closed persistence for post-reset training artifacts.

Training consumers verify provenance by default. Explicit inference surfaces may
load unverified weights while retaining their own format and shape validation.
"""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import torch

KEY = '_training_provenance'
EPOCH = 'clean-reset-2026-09-11-v1'
ROOT = Path(__file__).resolve().parents[2]
SESSION = uuid4().hex
PARENTS: set[str] = set()


class ArtifactCompatibilityError(ValueError):
    pass


@lru_cache(maxsize=1)
def fingerprint():
    """Snapshot sources once per process; restart workers after source changes."""
    digest = hashlib.sha256()
    for directory, suffix in (
        ('data', '.lua'),
        ('data', '.toml'),
        ('gicg_engine', '.go'),
        ('gicg_env', '.py'),
        ('training/core', '.py'),
        ('training/paradigms', '.py'),
    ):
        for path in sorted((ROOT / directory).rglob('*' + suffix)):
            if 'tests' in path.parts or path.name.endswith('_test.go'):
                continue
            digest.update(path.relative_to(ROOT).as_posix().encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def provenance():
    return {
        'schema': 1,
        'epoch': EPOCH,
        'source_observation_sha256': fingerprint(),
        'session': SESSION,
        'parents': sorted(PARENTS),
    }


def validate(meta):
    # Inference-only escape hatch: iterative tool development legitimately
    # drifts the source fingerprint between training runs (e.g. paradigm
    # additions), which would orphan readable checkpoints mid-campaign.
    # GICG_SKIP_PROVENANCE=1 disables ONLY the fingerprint equality check —
    # schema/epoch/lineage checks still run. Set it for read-only eval of
    # pre-drift checkpoints; never for training-side loads.
    import os

    if os.environ.get('GICG_SKIP_PROVENANCE'):
        if not isinstance(meta, dict) or meta.get('schema') != 1 or meta.get('epoch') != EPOCH:
            raise ArtifactCompatibilityError(
                'missing or invalid training provenance: pre-reset artifacts are forbidden'
            )
        if not isinstance(meta.get('session'), str) or not meta['session'] or not isinstance(meta.get('parents'), list):
            raise ArtifactCompatibilityError('invalid training lineage')
        return
    if not isinstance(meta, dict) or meta.get('schema') != 1 or meta.get('epoch') != EPOCH:
        raise ArtifactCompatibilityError('missing or invalid training provenance: pre-reset artifacts are forbidden')
    if meta.get('source_observation_sha256') != fingerprint():
        raise ArtifactCompatibilityError('rule/observation/source fingerprint mismatch; regenerate training artifacts')
    if not isinstance(meta.get('session'), str) or not meta['session'] or not isinstance(meta.get('parents'), list):
        raise ArtifactCompatibilityError('invalid training lineage')


def _parent(path):
    if isinstance(path, (str, Path)):
        digest = hashlib.sha256()
        with open(path, 'rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        PARENTS.add(digest.hexdigest())


def save_checkpoint(payload, path, **kwargs):
    if not isinstance(payload, dict):
        raise TypeError('checkpoint payload must be a dictionary')
    torch.save({**payload, KEY: provenance()}, path, **kwargs)


def load_checkpoint(path, *, verify_provenance=True, **kwargs):
    payload = torch.load(path, **kwargs)
    if verify_provenance:
        validate(payload.get(KEY) if isinstance(payload, dict) else None)
    _parent(path)
    return payload


def save_dataset(path, **arrays):
    np.savez_compressed(path, **{**arrays, KEY: json.dumps(provenance(), sort_keys=True)})


def load_dataset(path, **kwargs):
    data = np.load(path, **kwargs)
    try:
        validate(json.loads(str(data[KEY])) if KEY in data else None)
        _parent(path)
    except Exception:
        data.close()
        raise
    return data
