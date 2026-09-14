"""A stale or partially completed preparation must never authorize an RL launch."""

import pytest

from tools.experiments.pre_rl import validate_evidence


def good():
    return dict(
        ready_for_small_rl=True,
        source_observation_sha256='src',
        engine_sha256='lib',
        environment_gate='passed',
        action_alias_gate='passed',
        regression='passed',
        full_smoke='passed',
        seeding='passed',
        exact_resume='passed',
        target_seeds=[41, 42, 43],
        rule_seeds=[41, 42, 43],
        target_accuracy={str(s): [1.0] for s in (41, 42, 43)},
        rule_balanced_accuracy={str(s): [1.0] * 3 for s in (41, 42, 43)},
        target_erased_accuracy={str(s): 0.5 for s in (41, 42, 43)},
    )


def test_final_evidence_is_fail_closed():
    validate_evidence(good(), 'src', 'lib')
    for key in good():
        row = good()
        del row[key]
        with pytest.raises(ValueError):
            validate_evidence(row, 'src', 'lib')
    with pytest.raises(ValueError, match='source'):
        validate_evidence(good(), 'different', 'lib')
    with pytest.raises(ValueError, match='library'):
        validate_evidence(good(), 'src', 'different')


@pytest.mark.parametrize('value', [0.5, float('nan'), float('inf'), 1.1])
def test_failed_or_invalid_learning_metrics_cannot_pass(value):
    row = good()
    row['rule_balanced_accuracy']['41'][0] = value
    with pytest.raises(ValueError, match='threshold'):
        validate_evidence(row, 'src', 'lib')
