"""Public API re-export of tools.runs.helpers — actual implementations
live in ``_helpers/`` to respect the 300-line file budget per
``CLAUDE.md`` pre-commit hook. Stable API: 7 helpers (R1-R7).
"""

from __future__ import annotations

from tools.runs._helpers.allocator import allocate_nnn
from tools.runs._helpers.locks import acquire_metadata_lock
from tools.runs._helpers.metadata_io import write_metadata_atomic
from tools.runs._helpers.paths import cfg_checksum, extract_meta_field, normalize_repo_relative
from tools.runs._helpers.resolver import resolve_nnn_to_dir

__all__ = [
    'acquire_metadata_lock',
    'allocate_nnn',
    'cfg_checksum',
    'extract_meta_field',
    'normalize_repo_relative',
    'resolve_nnn_to_dir',
    'write_metadata_atomic',
]
