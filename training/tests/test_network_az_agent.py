"""Tests for training/network.py in AZ form: ActorCritic forward
contract, az_losses computation, Agent eval_state / forward_batch /
save-load round-trip. These are architectural smoke tests — they
do not exercise a real game, only random tensors of the right shape.

Game-integrated smoke (encode_static on a real GicgEnv + eval_state
on a real state) lives in the MCTS step's tests once that kernel
lands."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from training.core.network import ActorCritic
from training.paradigms.az._az_losses import az_losses
from training.core.obs_constants import (
    ACTION_CARD,
    ACTION_END_TURN,
    ACTION_SKILL,
    ACTION_SWITCH,
    DICE_COLOR_COUNT,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
)
from training.paradigms.az.network import Agent, AgentConfig


def _make_net(*, d_model=16, n_slots=128, n_hooks=8, max_tok=12, max_actions=6):
    """Small ActorCritic suitable for random-input tests."""
    torch.manual_seed(0)
    return ActorCritic(
        n_counter_slots=n_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_tok,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=1,
        dropout=0.0,
    )


def _random_batch(*, B=2, d_model=16, n_slots=128, n_hooks=8, max_actions=6, n_legal_per_row=3, seed=0):
    """Build a plausible random batch of inputs for ActorCritic.forward.
    legal_mask marks the first n_legal_per_row columns as legal;
    pi_target is a uniform distribution over those legal slots."""
    rng = np.random.RandomState(seed)

    counter_values = torch.zeros(B, n_slots)
    # Sprinkle a handful of non-zero counter values so the sparse
    # sort path has content to sort.
    for b in range(B):
        for i in rng.choice(n_slots, size=5, replace=False):
            counter_values[b, i] = float(rng.randint(1, 10))
    counter_sids = torch.randint(0, n_slots, (B, n_slots), dtype=torch.long)
    active_slot_mask = torch.ones(B, n_slots, dtype=torch.bool)
    hook_emb = torch.randn(B, n_hooks, d_model)
    hook_mask = torch.ones(B, n_hooks, dtype=torch.bool)
    card_buckets = torch.zeros(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    enemy_sizes = torch.zeros(B, OBS_ENEMY_SIZES)
    meta = torch.zeros(B, OBS_META_SIZE)

    refs = torch.full((B, max_actions, 3), -1, dtype=torch.long)
    refs[:, :, 0] = ACTION_END_TURN  # padding = end turn, hook_idx=-1
    for b in range(B):
        for a in range(n_legal_per_row):
            if a == 0:
                refs[b, a] = torch.tensor([ACTION_SKILL, 0, -1])
            elif a == 1:
                refs[b, a] = torch.tensor([ACTION_CARD, 1, -1])
            else:
                refs[b, a] = torch.tensor([ACTION_SWITCH, -1, 1])

    payments = torch.zeros(B, max_actions, DICE_COLOR_COUNT)
    payments[:, 0, 0] = 3.0
    payments[:, 1, 2] = 1.0
    payments[:, 1, 7] = 2.0

    legal_mask = torch.zeros(B, max_actions, dtype=torch.bool)
    legal_mask[:, :n_legal_per_row] = True

    pi_target = torch.zeros(B, max_actions)
    pi_target[:, :n_legal_per_row] = 1.0 / n_legal_per_row

    z_target = torch.tensor([1.0, -1.0][:B], dtype=torch.float32)
    if B > 2:
        z_target = torch.cat([z_target, torch.zeros(B - 2)])

    structural_values = torch.zeros(B, 66)

    # char_skill_refs: shape (B, 2, 6, 10). Leave as -1 (no skills) by
    # default — forward must handle the all-empty case gracefully.
    char_skill_refs = torch.full((B, 2, 6, 10), -1, dtype=torch.long)

    # ADR-0019 §B.2/§B.3c typed obs segments — Round-6 S-3: 用生产
    # padding sentinel(-2 categorical / 0 scalar)替原 torch.zeros,
    # 跟 engine encode_*_padding 一致避免 fixture 偏离生产路径。
    from training.tests._typed_obs_fixtures import (
        make_modifier_log_padding_torch,
        make_prepare_skill_padding_torch,
        make_recent_damage_padding_torch,
    )

    recent_damage = make_recent_damage_padding_torch(B=B)
    prepare_skill = make_prepare_skill_padding_torch(B=B)
    modifier_log = make_modifier_log_padding_torch(B=B)

    return {
        'counter_values': counter_values,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'hook_emb': hook_emb,
        'hook_mask': hook_mask,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'meta': meta,
        'action_refs': refs,
        'action_payments': payments,
        'structural_values': structural_values,
        'char_skill_refs': char_skill_refs,
        'definition_links': torch.full((B, 1, 2), -1, dtype=torch.long),
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
        'legal_mask': legal_mask,
        'pi_target': pi_target,
        'z_target': z_target,
    }


class TestAgent:
    def _cfg(self):
        return AgentConfig(
            n_counter_slots=128,
            n_hooks=8,
            max_ops_per_hook=12,
            max_actions=6,
            d_model=16,
            n_cross_layers=1,
            dropout=0.0,
        )

    def _synthetic_static_obs(self, cfg: AgentConfig) -> np.ndarray:
        """Build a static obs array with the layout expected by
        encode_static: N_slots*(min,max,sid) meta, then
        2*MaxChars*MaxSkillsPerChar char_skill_refs, then
        N_hooks * max_ops_per_hook * fields_per_op (IR-4 ops). Every hook
        gets one non-NOP opcode at op-slot 0 so the hook counts as
        active. char_skill_refs set to -1 (no skills)."""
        from training.core.obs_constants import (
            OBS_CHAR_ELEMENT_SLOTS,
            OBS_CHAR_SKILL_REFS_SIZE,
            OBS_DEFINITION_LINK_SCHEMA_VERSION,
            OBS_DEFINITION_LINK_SLOTS,
        )

        meta_size = cfg.n_counter_slots * 3
        refs_size = OBS_CHAR_SKILL_REFS_SIZE
        hook_size = cfg.n_hooks * cfg.max_ops_per_hook * cfg.fields_per_op
        obs = np.zeros(
            meta_size + refs_size + hook_size + OBS_CHAR_ELEMENT_SLOTS + OBS_DEFINITION_LINK_SLOTS,
            dtype=np.float32,
        )
        obs[-OBS_DEFINITION_LINK_SLOTS] = OBS_DEFINITION_LINK_SCHEMA_VERSION
        # Counter meta: give each slot a distinct SID
        for i in range(cfg.n_counter_slots):
            obs[i * 3 + 2] = float(i)
        # char_skill_refs: all -1 (empty slots)
        obs[meta_size : meta_size + refs_size] = -1.0
        # Hook data: first field (opcode) of first op in each hook is non-zero
        hook_start = meta_size + refs_size
        stride = cfg.max_ops_per_hook * cfg.fields_per_op
        for h in range(cfg.n_hooks):
            obs[hook_start + h * stride + 0] = 1.0  # opcode
        return obs

    def _synthetic_dynamic_obs(self, cfg: AgentConfig) -> np.ndarray:
        """Dynamic obs layout: meta(3) + counter_values(N_slots) +
        card_buckets(4*80) + enemy_sizes(2) + recent_damage(8*11) +
        prepare_skill(4) + modifier_log(8*4*5).
        ADR-0019 §B.2/§B.3c added the trailing typed segments."""
        from training.core.obs_constants import (
            OBS_MODIFIER_LOG_SLOTS,
            OBS_PREPARE_SKILL_SLOTS,
            OBS_RECENT_DAMAGE_SLOTS,
        )

        size = (
            OBS_META_SIZE
            + cfg.n_counter_slots
            + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
            + OBS_ENEMY_SIZES
            + OBS_RECENT_DAMAGE_SLOTS
            + OBS_PREPARE_SKILL_SLOTS
            + OBS_MODIFIER_LOG_SLOTS
        )
        obs = np.zeros(size, dtype=np.float32)
        obs[0] = 3  # phase
        obs[1] = 1  # round
        # A few non-zero counters
        obs[OBS_META_SIZE + 0] = 5.0
        obs[OBS_META_SIZE + 7] = 2.0
        return obs

    def test_encode_static_populates_cache(self):
        cfg = self._cfg()
        agent = Agent(cfg)
        assert agent._hook_emb is None
        agent.encode_static(self._synthetic_static_obs(cfg))
        assert agent._hook_emb is not None
        assert agent._hook_mask is not None
        assert agent._counter_sids is not None
        assert agent._hook_emb.shape == (1, cfg.n_hooks, cfg.d_model)
        assert agent._hook_mask.shape == (1, cfg.n_hooks)
        assert agent._counter_sids.shape == (1, cfg.n_counter_slots)

    def test_eval_state_returns_prior_and_value(self):
        cfg = self._cfg()
        agent = Agent(cfg)
        static = self._synthetic_static_obs(cfg)
        agent.encode_static(static)

        dyn = self._synthetic_dynamic_obs(cfg)
        refs = np.array(
            [
                [ACTION_SKILL, 0, -1],
                [ACTION_CARD, 1, -1],
                [ACTION_SWITCH, -1, 1],
                [ACTION_END_TURN, -1, -1],
            ],
            dtype=np.int32,
        )
        payments = np.array(
            [
                [3, 0, 0, 0, 0, 0, 0, 0],
                [0, 0, 2, 0, 0, 0, 0, 1],
                [0, 0, 0, 0, 0, 0, 0, 1],
                [0, 0, 0, 0, 0, 0, 0, 0],
            ],
            dtype=np.float32,
        )

        prior, value = agent.eval_state(dyn, refs, payments)
        assert prior.shape == (4,)
        assert abs(prior.sum() - 1.0) < 1e-5
        assert (prior >= 0).all()
        assert -1.0 <= value <= 1.0

    def test_eval_state_without_game_start_raises(self):
        cfg = self._cfg()
        agent = Agent(cfg)
        with pytest.raises(RuntimeError, match='game_start'):
            agent.eval_state(
                self._synthetic_dynamic_obs(cfg),
                np.array([[ACTION_END_TURN, -1, -1]], dtype=np.int32),
                np.zeros((1, DICE_COLOR_COUNT), dtype=np.float32),
            )

    def test_game_start_returns_game_static(self):
        """game_start returns raw hook IR ops (single hook_ir tensor)
        so train_step can re-encode with gradients. Fast-path inference
        still uses Agent._hook_emb cache."""
        cfg = self._cfg()
        agent = Agent(cfg)
        static = self._synthetic_static_obs(cfg)
        game_static = agent.game_start(static)
        assert set(game_static.keys()) == {
            'hook_ir',
            'hook_mask',
            'counter_sids',
            'active_slot_mask',
            'char_skill_refs',
            'definition_links',
        }
        assert game_static['hook_ir'].dtype == np.int64
        assert game_static['hook_mask'].dtype == bool
        assert game_static['counter_sids'].dtype == np.int64
        assert game_static['active_slot_mask'].dtype == bool
        # (n_active, max_ops, fields_per_op)
        assert game_static['hook_ir'].ndim == 3
        assert game_static['hook_ir'].shape[1] == cfg.max_ops_per_hook
        assert game_static['hook_ir'].shape[2] == cfg.fields_per_op
        assert game_static['hook_mask'].shape[0] == game_static['hook_ir'].shape[0]

    def test_forward_batch_shape(self):
        cfg = self._cfg()
        agent = Agent(cfg)
        batch = _random_batch(
            B=3,
            d_model=cfg.d_model,
            n_slots=cfg.n_counter_slots,
            n_hooks=cfg.n_hooks,
            max_actions=cfg.max_actions,
            n_legal_per_row=3,
        )
        # forward_batch now reads hook_ir (not hook_emb). _random_batch
        # produces hook_emb for ActorCritic.forward tests; synthesize
        # IR ops on the fly for this test.
        B, N = 3, cfg.n_hooks
        batch['hook_ir'] = np.random.randint(
            1,
            14,
            (B, N, cfg.max_ops_per_hook, cfg.fields_per_op),
        ).astype(np.int64)
        logits, value, _ = agent.forward_batch(batch)
        assert logits.shape == (3, cfg.max_actions)
        assert value.shape == (3,)

    def test_forward_batch_hook_encoder_receives_gradient(self):
        """Regression test for the hook-gradient disconnect bug: the
        training path must backprop through hook_encoder. Previously
        game_static stored pre-encoded hook_emb in no_grad so
        hook_encoder parameters always had grad=None and weight decay
        silently drove them to zero."""
        cfg = self._cfg()
        agent = Agent(cfg)
        batch = _random_batch(
            B=2,
            d_model=cfg.d_model,
            n_slots=cfg.n_counter_slots,
            n_hooks=cfg.n_hooks,
            max_actions=cfg.max_actions,
            n_legal_per_row=3,
        )
        B, N = 2, cfg.n_hooks
        batch['hook_ir'] = np.random.randint(
            1,
            14,
            (B, N, cfg.max_ops_per_hook, cfg.fields_per_op),
        ).astype(np.int64)
        logits, value, _ = agent.forward_batch(batch)
        loss = value.sum() + logits.sum()
        agent.net.zero_grad()
        loss.backward()
        # At least one hook_encoder parameter must have non-zero grad.
        has_grad = any(
            p.grad is not None and p.grad.abs().sum().item() > 0 for p in agent.net.hook_encoder.parameters()
        )
        assert has_grad, (
            'hook_encoder received no gradient — training path is '
            'disconnected (see docs/az/review_internal.md post-mortem)'
        )

    def test_save_load_round_trip(self, tmp_path):
        cfg = self._cfg()
        agent1 = Agent(cfg)
        # Perturb weights away from default init so the comparison means
        # something.
        with torch.no_grad():
            for p in agent1.net.parameters():
                p.add_(0.01)
        path = str(tmp_path / 'agent.pt')
        agent1.save(path)

        agent2 = Agent(cfg)
        agent2.load(path)
        for p1, p2 in zip(agent1.net.parameters(), agent2.net.parameters()):
            torch.testing.assert_close(p1, p2)
