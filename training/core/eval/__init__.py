"""training.core.eval — periodic eval + OpponentRegistry + stats."""

from training.core.eval.baselines import OpponentRegistry, register_default_opponents
from training.core.eval.job import EvalJob, EvalReport, EvalResult
from training.core.eval.periodic import PeriodicEvalScheduler
from training.core.eval.scenario import ScenarioFactory
from training.core.eval.statistics import wilson_ci, wp_ci95
from training.core.eval.worker import EvalWorker

__all__ = [
    'OpponentRegistry',
    'register_default_opponents',
    'EvalJob',
    'EvalReport',
    'EvalResult',
    'PeriodicEvalScheduler',
    'ScenarioFactory',
    'wilson_ci',
    'wp_ci95',
    'EvalWorker',
]
