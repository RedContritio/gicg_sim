"""ESMixin — external sampling MCCFR traversal."""

from __future__ import annotations

import numpy as np
import torch

from training.paradigms.cfr.traversal.config import TraversalStats
from training.paradigms.cfr.traversal.encoding import build_dynamic


class ESMixin:
    """External sampling MCCFR (Deep CFR paper variant). Enumerates
    traverser actions at each traverser node via env.snapshot /
    env.restore; samples opponent on-policy.

    TCG-INFEASIBLE for production (exponential branch explosion).
    Used for Kuhn-class validation tests only.
    """

    def _traverse_external_sampling(
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
        env.log_suspend()
        try:
            root_val = self._es_recurse(
                env,
                traverser_player,
                iteration,
                static,
                adv_buffer,
                gid_adv,
                gid_str,
                gid_val,
                stats,
                reach_opp=1.0,
            )
        finally:
            env.log_resume()
        stats.outcome_traverser = float(root_val)

        adv_buffer.prune_empty_registrations()
        self.strategy_buffer.prune_empty_registrations()
        self.value_buffer.prune_empty_registrations()
        return stats

    def _es_recurse(
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
        reach_opp: float,
    ) -> float:
        """Recursive ES step."""
        if env.done:
            winner = env.winner
            if winner == traverser_player:
                return 1.0
            if winner == 1 - traverser_player:
                return -1.0
            return 0.0

        if stats.n_steps >= self.config.max_game_steps:
            raise RuntimeError(f'ES traversal exceeded max_game_steps={self.config.max_game_steps}')

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

        policy = self._current_policy(
            self.advantage_nets[acting],
            dynamic,
            static,
            counter_values_t,
            structural_values_t,
            n_legal,
        )
        legal_mask = dynamic['legal_mask']

        if is_traverser:
            # Exact restore deliberately shares the engine chance state across
            # sibling actions. Policy sampling uses self.rng independently;
            # fresh traversals get their seed from the collector's env_factory.
            # restore itself must never advance or mutate the snapshot RNG.
            snap = env.snapshot()
            try:
                action_vals = np.zeros(self.max_actions, dtype=np.float64)
                for a in range(self.max_actions):
                    if not legal_mask[a]:
                        continue
                    env.step(a)
                    stats.n_steps += 1
                    action_vals[a] = self._es_recurse(
                        env,
                        traverser_player,
                        iteration,
                        static,
                        adv_buffer,
                        gid_adv,
                        gid_str,
                        gid_val,
                        stats,
                        reach_opp=reach_opp,
                    )
                    env.restore(snap)
            finally:
                env.snapshot_free(snap)

            expected_val = float((policy * action_vals).sum())
            r_delta = (reach_opp * (action_vals - expected_val)).astype(np.float32)
            r_delta[~legal_mask] = 0.0

            adv_buffer.add_sample(
                gid_adv,
                dynamic,
                r_delta,
                iteration=iteration,
                rng=self.rng,
            )
            stats.advantage_adds += 1
            self.strategy_buffer.add_sample(
                gid_str,
                dynamic,
                policy,
                iteration=iteration,
                rng=self.rng,
            )
            stats.strategy_adds += 1
            val_clamped = max(-1.0, min(1.0, float(expected_val)))
            self.value_buffer.add_sample(
                gid_val,
                dynamic,
                val_clamped,
                iteration=iteration,
                rng=self.rng,
            )
            stats.value_adds += 1
            stats.n_traverser_decisions += 1
            return expected_val

        q = self._sampling_dist(policy, legal_mask, n_legal)
        a_sampled = self._sample_action(q, n_legal)
        sigma_opp_a = float(policy[a_sampled])

        env.step(a_sampled)
        stats.n_steps += 1
        child_val = self._es_recurse(
            env,
            traverser_player,
            iteration,
            static,
            adv_buffer,
            gid_adv,
            gid_str,
            gid_val,
            stats,
            reach_opp=reach_opp * sigma_opp_a,
        )

        z_from_acting = -child_val
        z_clamped = max(-1.0, min(1.0, float(z_from_acting)))
        self.value_buffer.add_sample(
            gid_val,
            dynamic,
            z_clamped,
            iteration=iteration,
            rng=self.rng,
        )
        stats.value_adds += 1
        stats.n_opponent_decisions += 1
        return child_val
