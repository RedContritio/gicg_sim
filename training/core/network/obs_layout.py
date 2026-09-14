"""Validate the raw static observation before interpreting its hook stride."""

from training.core.obs_constants import (
    OBS_CHAR_ELEMENT_SLOTS,
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_DEFINITION_LINK_SLOTS,
)


def validate_static_layout(static_obs, cfg):
    validate_static_dimensions(static_obs, cfg.n_counter_slots, cfg.n_hooks, cfg.max_ops_per_hook, cfg.fields_per_op)


def validate_static_dimensions(static_obs, n_counter_slots, n_hooks, max_ops_per_hook, fields_per_op):
    body_size = n_counter_slots * 3 + OBS_CHAR_SKILL_REFS_SIZE + n_hooks * max_ops_per_hook * fields_per_op
    expected = body_size + OBS_CHAR_ELEMENT_SLOTS + OBS_DEFINITION_LINK_SLOTS
    if static_obs.ndim != 1 or static_obs.size != expected:
        raise ValueError(
            f'static observation layout mismatch: got {static_obs.shape}, '
            f'expected ({expected},) '
            f'for max_ops_per_hook={max_ops_per_hook}'
        )
