"""EvalWorker — runs eval episodes for one job + reports results.

Spec: design/episode-runner.md §4.

Uses EpisodeRunner with EpisodeSpec(deterministic=True). Reports to
result_queue / direct return (in-proc)."""

from __future__ import annotations

from typing import Any, List, Optional

from training.core.actor.episode_runner import EpisodeRunner
from training.core.eval.job import EvalJob, EvalResult
from training.core.eval.matchup import aggregate_results
from training.core.eval.scenario import eval_seed_pool
from training.core.protocols import EpisodeSpec, NetworkProvider


class EvalWorker:
    """Synchronous eval worker. Async-mode wraps this in a process."""

    def __init__(
        self,
        env_factory: Any,
        opponent_registry: Any,
        policy_factory: Any,  # callable: (deterministic=True) → EpisodePolicy
        provider: NetworkProvider,
    ) -> None:
        self.runner = EpisodeRunner(env_factory, opponent_registry)
        self.policy_factory = policy_factory
        self.provider = provider

    def run_job(self, job: EvalJob, *, master_seed: int = 0, job_id: str = '') -> List[EvalResult]:
        """Run all games of an EvalJob and return per-game results."""
        seeds = eval_seed_pool(master_seed, job.n_games, prefix=f'eval/{job.opponent_id}')
        policy = self.policy_factory(deterministic=True)
        out: List[EvalResult] = []
        for i, seed in enumerate(seeds):
            our_player = (i % 2) if job.starting_player_alternates else 0
            spec = EpisodeSpec(
                scenario_seed=seed,
                opponent_id=job.opponent_id,
                starting_player=our_player,
                deterministic=True,
                epsilon=0.0,
            )
            record = self.runner.run(spec, policy, self.provider, our_player=our_player)
            out.append(
                EvalResult(
                    job_id=job_id,
                    game_idx=i,
                    winner=record.winner,
                    our_player=our_player,
                    length=record.length,
                )
            )
        return out

    def run_job_report(self, job: EvalJob, *, master_seed: int = 0, job_id: str = ''):
        """Convenience wrapper — returns aggregated EvalReport directly."""
        results = self.run_job(job, master_seed=master_seed, job_id=job_id)
        return aggregate_results(job.opponent_id, results)
