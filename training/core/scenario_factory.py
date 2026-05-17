"""Scenario factory — re-export from eval/scenario.py for top-level convenience.

The factory lives in eval/ because it's shared between actor + eval;
this file just keeps the import path discoverable per design doc."""

from training.core.eval.scenario import ScenarioFactory, eval_seed_pool

__all__ = ['ScenarioFactory', 'eval_seed_pool']
