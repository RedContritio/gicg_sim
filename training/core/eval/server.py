"""EvalServer — coordinates EvalJobs across workers + aggregates reports.

It calls the supplied worker objects synchronously. Process-backed workers can
be supplied by a caller, but this coordinator does not spawn processes or own
IPC queues."""

from __future__ import annotations

from typing import Any, Dict, List

from training.core.eval.job import EvalJob, EvalReport, EvalResult
from training.core.eval.matchup import aggregate_results


class EvalServer:
    """Coordinator for one PeriodicEval cycle. Owns the worker pool +
    aggregates per-job results into a dict of EvalReport (keyed by
    opponent_id)."""

    def __init__(self, workers: List, master_seed: int = 0) -> None:
        if not workers:
            raise ValueError('EvalServer: workers list empty')
        self.workers = workers
        self.master_seed = master_seed

    def run_jobs(self, jobs: List[EvalJob]) -> Dict[str, EvalReport]:
        """Execute all jobs and return {opponent_id: EvalReport}.

        Round-robin assigns each job to a supplied worker."""
        all_results: Dict[str, List[EvalResult]] = {}
        for i, job in enumerate(jobs):
            worker = self.workers[i % len(self.workers)]
            results = worker.run_job(job, master_seed=self.master_seed, job_id=job.opponent_id)
            all_results.setdefault(job.opponent_id, []).extend(results)

        return {opp: aggregate_results(opp, rs) for opp, rs in all_results.items()}

    def close(self) -> None:
        for w in self.workers:
            if hasattr(w, 'close'):
                w.close()
