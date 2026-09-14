"""Parse definition-reference incidence from the static observation trailer."""

from __future__ import annotations

import numpy as np

from training.core.obs_constants import (
    OBS_CHAR_ELEMENT_SLOTS,
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_DEFINITION_LINK_SLOTS,
    OBS_DEFINITION_LINK_SCHEMA_VERSION,
    OBS_MAX_DEFINITION_LINKS,
)


def parse_definition_links_np(
    static_obs: np.ndarray,
    *,
    n_counter_slots: int,
    n_hooks: int,
    max_ops_per_hook: int,
    fields_per_op: int,
) -> np.ndarray:
    """Return ``(E, 2)`` links from the required fixed-capacity trailer."""
    offset = (
        n_counter_slots * 3
        + OBS_CHAR_SKILL_REFS_SIZE
        + n_hooks * max_ops_per_hook * fields_per_op
        + OBS_CHAR_ELEMENT_SLOTS
    )
    if static_obs.size != offset + OBS_DEFINITION_LINK_SLOTS:
        raise ValueError(f'definition-link trailer has unexpected static size {static_obs.size}')
    raw_version = static_obs[offset]
    if raw_version != OBS_DEFINITION_LINK_SCHEMA_VERSION:
        raise ValueError(
            f'unsupported definition-link schema {raw_version}; expected {OBS_DEFINITION_LINK_SCHEMA_VERSION}'
        )
    raw_count = static_obs[offset + 1]
    count = int(raw_count)
    if not np.isfinite(raw_count) or raw_count != count:
        raise ValueError(f'invalid non-integral definition-link count {raw_count}')
    if count < 0 or count > OBS_MAX_DEFINITION_LINKS:
        raise ValueError(f'invalid definition-link count {count}')
    if count == 0:
        return np.full((1, 2), -1, dtype=np.int64)
    raw_links = np.asarray(static_obs[offset + 2 : offset + 2 + 2 * count]).reshape(count, 2)
    links = raw_links.astype(np.int64)
    if not np.isfinite(raw_links).all() or not np.array_equal(raw_links, links):
        raise ValueError('definition links must contain integral hook indices')
    if (links < 0).any() or (links >= n_hooks).any():
        raise ValueError('definition link outside static hook capacity')
    return links.copy()
