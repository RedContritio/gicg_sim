import numpy as np

from tools.experiments.semantic_training.replication_summary import crossed_interval


def test_crossed_bootstrap_keeps_constant_paired_gain():
    interval = crossed_interval(np.full((5, 256), 0.25), repeats=500)
    np.testing.assert_allclose(interval, [0.25, 0.25])


def test_crossed_bootstrap_includes_training_variation_even_with_many_scenarios():
    delta = np.array([np.ones(256), -np.ones(256)])
    interval = crossed_interval(delta, repeats=1000)
    # More game layouts or scenarios cannot hide opposite outcomes across training runs.
    np.testing.assert_allclose(interval, [-1, 1])


def test_crossed_bootstrap_includes_shared_scenario_variation():
    delta = np.tile([1.0, -1.0], (5, 1))
    np.testing.assert_allclose(crossed_interval(delta, repeats=1000), [-1, 1])
