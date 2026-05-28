"""OSMixin — outcome sampling MCCFR traversal."""

from __future__ import annotations

import numpy as np
import torch

from training.paradigms.cfr.traversal.config import TraversalStats, _RecordedDecision
from training.paradigms.cfr.traversal.encoding import build_dynamic


class OSMixin:
    """Outcome-sampling MCCFR (Lanctot 2013) — one trajectory per
    traversal, regret via importance weighting. PRODUCTION DEFAULT."""

    def _traverse_outcome_sampling(
        self,
        env,
        traverser_player: int,
        iteration: int,
        static,
        adv_buffer,
        gid_adv: int,
        gid_str: int,
        gid_val: int,
        stats: TraversalStats,
    ) -> TraversalStats:
        decisions: list[_RecordedDecision] = []
        reach_q_total = 1.0
        reach_opp_sigma = 1.0

        while not env.done:
            if stats.n_steps >= self.config.max_game_steps:
                raise RuntimeError(f'CFR traversal exceeded max_game_steps={self.config.max_game_steps}')
            acting = env.acting_player
            is_traverser = acting == traverser_player

            dynamic, refs_np, n_legal = build_dynamic(
                env,
                self.n_counter_slots,
                self.max_actions,
            )

            counter_values_t = torch.tensor(
                dynamic['counter_values'],
                dtype=torch.float32,
                device=self.device,
            ).unsqueeze(0)
            structural_values_t = counter_values_t.gather(
                1,
                static.structural_obspos,
            )
            dynamic['structural_values'] = structural_values_t.squeeze(0).detach().cpu().numpy().astype(np.float32)

            net_for_this_node = self.advantage_nets[acting]
            policy = self._current_policy(
                net_for_this_node,
                dynamic,
                static,
                counter_values_t,
                structural_values_t,
                n_legal,
            )

            q = self._sampling_dist(policy, dynamic['legal_mask'], n_legal)
            a_sampled = self._sample_action(q, n_legal)
            q_sampled = float(q[a_sampled])

            decisions.append(
                _RecordedDecision(
                    is_traverser=is_traverser,
                    acting_player=acting,
                    game_id=gid_adv if is_traverser else gid_val,
                    dynamic=dynamic,
                    policy=policy,
                    sampled_action=a_sampled,
                    q_sampled=q_sampled,
                    reach_opp_pre=reach_opp_sigma,
                    reach_q_prefix=reach_q_total,
                )
            )

            reach_q_total *= q_sampled
            if not is_traverser:
                reach_opp_sigma *= float(policy[a_sampled])

            _, _, _, info = env.step(a_sampled)
            if info.get('need_target'):
                raise RuntimeError('CFR traversal: legacy PendingCardTarget path unsupported')
            stats.n_steps += 1
            if is_traverser:
                stats.n_traverser_decisions += 1
            else:
                stats.n_opponent_decisions += 1

        engine_winner = env.winner
        if engine_winner == 0:
            z_p0 = 1.0
        elif engine_winner == 1:
            z_p0 = -1.0
        else:
            z_p0 = 0.0
        z_traverser = z_p0 if traverser_player == 0 else -z_p0
        stats.outcome_traverser = z_traverser

        if not decisions:
            raise RuntimeError(
                'CFR traversal: no decisions recorded; env terminated '
                'during PHASE_SELECT_ACTIVE or before any decision node.'
            )

        W_max = self.config.importance_weight_max

        for dec in decisions:
            z_from_acting = z_p0 if dec.acting_player == 0 else -z_p0
            self.value_buffer.add_sample(
                gid_val,
                dec.dynamic,
                z_from_acting,
                iteration=iteration,
                rng=self.rng,
            )
            stats.value_adds += 1

            if dec.is_traverser:
                self.strategy_buffer.add_sample(
                    gid_str,
                    dec.dynamic,
                    dec.policy,
                    iteration=iteration,
                    rng=self.rng,
                )
                stats.strategy_adds += 1

                q_prefix = max(dec.reach_q_prefix, 1e-12)
                W = min(dec.reach_opp_pre / q_prefix, W_max)
                regret = self._regret_estimate(
                    dec.policy,
                    dec.sampled_action,
                    dec.q_sampled,
                    z_traverser,
                    W,
                    legal_mask=dec.dynamic['legal_mask'],
                )
                adv_buffer.add_sample(
                    gid_adv,
                    dec.dynamic,
                    regret,
                    iteration=iteration,
                    rng=self.rng,
                )
                stats.advantage_adds += 1

        adv_buffer.prune_empty_registrations()
        self.strategy_buffer.prune_empty_registrations()
        self.value_buffer.prune_empty_registrations()

        return stats
