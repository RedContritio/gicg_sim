"""Public API re-export of tools.runs.helpers — actual implementations
live in ``_helpers/`` to respect the 300-line file budget per
``AGENTS.md`` pre-commit 约定。Stable API: 7 helpers (R1-R7).
"""

from __future__ import annotations

from tools.runs._helpers.allocator import allocate_nnn
from tools.runs._helpers.locks import acquire_metadata_lock
from tools.runs._helpers.metadata_io import write_metadata_atomic
from tools.runs._helpers.paths import (
    NEW_RUN_DIR_RE,
    RUN_DIR_RE,
    cfg_checksum,
    experiment_tag_from_cfg,
    extract_meta_field,
    iter_run_dirs,
    normalize_repo_relative,
    run_dir_parts,
)
from tools.runs._helpers.resolver import resolve_nnn_to_dir

__all__ = [
    'RUN_DIR_RE',
    'NEW_RUN_DIR_RE',
    'iter_run_dirs',
    'run_dir_parts',
    'experiment_tag_from_cfg',
    'acquire_metadata_lock',
    'allocate_nnn',
    'cfg_checksum',
    'extract_meta_field',
    'normalize_repo_relative',
    'resolve_nnn_to_dir',
    'write_metadata_atomic',
]
