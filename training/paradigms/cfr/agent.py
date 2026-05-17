"""Inference-time adapter: CFRStrategyNet → AgentBase protocol.

CFRAgent inherits from ``AgentBase`` (not from AZ's ``Agent``) to avoid
a CFR → AZ cross-package import. Both classes get their shared
static-cache / parse-scaffolding from ``AgentBase``.
"""

from __future__ import annotations

import numpy as np
import torch

from training.paradigms.cfr.strategy_net import CFRNetConfig, CFRStrategyNet
from training.core.network import AgentBase
from training.core.step_encoding import (
    build_legal_mask,
    pad_action_payments,
    pad_action_refs,
)
from training.core.structural import compute_structural_values


class CFRAgent(AgentBase):
    """Agent-protocol wrapper around CFRStrategyNet."""

    def __init__(self, cfg: CFRNetConfig, device: str = 'cpu'):
        # Core-network-generic-promotion DI: AgentBase 要求 hook_encoder 注入。
        # CFR 用自己的 CFRStrategyNet,不通过 generic ActorCritic,但其内部有
        # 同型 hook_encoder(自 core.network.encoder),直接传递。
        net = CFRStrategyNet(cfg).to(torch.device(device))
        super().__init__(cfg, hook_encoder=net.hook_encoder, device=device)
        self.cfr_cfg = cfg
        self.net = net
        self.optimizer = None  # inference-only

    def load(self, path: str) -> None:
        """Load CFRStrategyNet weights from a ckpt."""
        blob = torch.load(path, weights_only=True, map_location=self.device)
        if not isinstance(blob, dict) or 'net' not in blob:
            raise RuntimeError(f"CFRAgent.load: {path} missing 'net'")
        if blob.get('kind') not in (CFRStrategyNet.KIND, None):
            raise RuntimeError(f'CFRAgent.load: ckpt kind={blob.get("kind")!r} != expected {CFRStrategyNet.KIND!r}')
        self.net.load_state_dict(blob['net'])

    def save(self, path: str) -> None:
        """Save the wrapped CFRStrategyNet."""
        torch.save(
            {
                'cfg': vars(self.cfr_cfg),
                'net': self.net.state_dict(),
                'kind': CFRStrategyNet.KIND,
            },
            path,
        )

    def forward_batch(self, batch):
        """Inference-only; CFR training uses CFRTrainer, not this path."""
        raise RuntimeError('CFRAgent is inference-only; use CFRTrainer for training batched forward passes.')

    def eval_state(
        self,
        dyn_obs_np: np.ndarray,
        refs_np: np.ndarray,
        payments_np: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        """MCTS evaluator protocol. Returns (prior, value)."""
        if self._hook_emb is None:
            raise RuntimeError(
                'CFRAgent.eval_state called before game_start — call '
                "game_start(env.static_obs) once at the game's root "
                'before any MCTS rollouts.'
            )
        n_legal = int(len(refs_np))
        if n_legal == 0:
            raise ValueError('eval_state called with 0 legal actions')
        if n_legal > self.cfr_cfg.max_actions:
            raise ValueError(f'eval_state: n_legal={n_legal} exceeds max_actions={self.cfr_cfg.max_actions}')

        refs_padded = pad_action_refs(refs_np, self.cfr_cfg.max_actions)
        pay_padded = pad_action_payments(payments_np, self.cfr_cfg.max_actions)
        mask = build_legal_mask(self.cfr_cfg.max_actions, n_legal)

        with torch.no_grad():
            # CFR currently does not consume the typed obs segments
            # (recent_damage / prepare_skill / modifier_log). AZ stack
            # added them in ADR-0019 §B.2/§B.3c; CFR can incorporate
            # them in a future PR by extending CFRStrategyNet.forward.
            counter_values, meta, card_buckets, enemy_sizes, _rd, _ps, _ml = self._parse_dynamic_single(dyn_obs_np)
            refs_t = torch.tensor(
                refs_padded,
                dtype=torch.long,
                device=self.device,
            ).unsqueeze(0)
            pay_t = torch.tensor(
                pay_padded,
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0)

            structural_values = compute_structural_values(counter_values, self._structural_obspos)
            logits, value = self.net(
                counter_values=counter_values,
                counter_sids=self._counter_sids,
                active_slot_mask=self._active_slot_mask,
                hook_emb_cached=self._hook_emb,
                hook_mask=self._hook_mask,
                card_buckets=card_buckets,
                enemy_sizes=enemy_sizes,
                meta=meta,
                action_refs=refs_t,
                action_payments=pay_t,
                structural_values=structural_values,
                char_skill_refs=self._char_skill_refs,
            )
            legal_logits = logits[0, :n_legal]
            prior = torch.softmax(legal_logits, dim=-1).cpu().numpy()
            v_scalar = float(value[0].item())
        return prior, v_scalar
