"""TypedDamageEncoder 的 index 校验 / offset 原语 — 从 ``typed_damage`` 拆出。

两个方法都是"叶子"校验器:不依赖 vocab-size 常量(除 skill_slot 自己的 OBS_MAX_SKILLS_PER_CHAR),
因此可以脱离 ``typed_damage`` 单独放置。

``TypedDamageEncoder`` 通过继承本 mixin 取得这两个方法 — 方法名 / 签名 / 语义与拆出前逐字一致,
纯搬家 (原模块超 300 行上限)。

不 import ``typed_damage`` (单向依赖,无环)。
"""

from __future__ import annotations

import torch

from training.core.obs_constants import OBS_MAX_SKILLS_PER_CHAR


class _TypedDamageIndexMixin:
    """Categorical index → embedding-index 校验 + offset 原语。"""

    def _safe_categorical(
        self,
        idx: torch.Tensor,
        field_name: str,
        vocab_size: int,
        real_max: int,
    ) -> torch.Tensor:
        """Validate and offset a categorical field for embedding lookup.

        Valid ranges:
          - -2 (padding sentinel)
          - -1 (real "no-X")
          - 0..real_max (real values)

        +2 offset maps to vocab idx 0..real_max+2; clamp range checked.
        Out-of-range input raises ``ValueError``.
        """
        idx_long = idx.long()
        too_low = idx_long < -2
        too_high = idx_long > real_max
        if (too_low | too_high).any():
            bad = idx_long[too_low | too_high]
            raise ValueError(
                f'{field_name} out of range [-2, {real_max}]: got values {bad.tolist()}. '
                f'Engine emitted value beyond vocab (size={vocab_size}) — bug, not noise.'
            )
        return idx_long + 2

    def _safe_skill_slot(self, idx: torch.Tensor) -> torch.Tensor:
        """Map -2 (padding, never emitted by encodePrepareSkill but
        encoder is uniform), -1 (no prepare real), 0..MSPC-1 → 2..MSPC+1.

        A slot outside [-2, OBS_MAX_SKILLS_PER_CHAR) means the engine
        emitted a slot beyond the network's vocabulary, indicating either
        an engine bug or an OBS_MAX_SKILLS_PER_CHAR drift between Go and
        Python.
        """
        idx_long = idx.long()
        too_low = idx_long < -2
        too_high = idx_long >= OBS_MAX_SKILLS_PER_CHAR
        if (too_low | too_high).any():
            bad = idx_long[too_low | too_high]
            raise ValueError(
                f'skill_slot out of range [-2, {OBS_MAX_SKILLS_PER_CHAR}): '
                f'got values {bad.tolist()}. Engine emitted slot beyond '
                f'OBS_MAX_SKILLS_PER_CHAR={OBS_MAX_SKILLS_PER_CHAR} or a '
                'corrupt obs index — bug, not noise.'
            )
        return idx_long + 2
